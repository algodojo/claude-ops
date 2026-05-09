"""
claude-ops interactive setup wizard.

Walks a new user through everything `pulumi up` needs to succeed against a
fresh `dev` stack: backend login, stack init, four config keys, and the
Tailscale ACL handoff. Stdlib-only at runtime. See:
docs/superpowers/specs/2026-05-09-pulumi-up-walkthrough-design.md
"""

from __future__ import annotations

import getpass
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional


# --- I/O helpers ---------------------------------------------------


def _isatty() -> bool:
    return sys.stdout.isatty()


def color(text: str, code: str) -> str:
    """ANSI color wrapper. No-op when stdout is not a TTY (CI logs stay clean)."""
    if not _isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def green(text: str) -> str: return color(text, "32")
def yellow(text: str) -> str: return color(text, "33")
def red(text: str) -> str: return color(text, "31")
def bold(text: str) -> str: return color(text, "1")


def banner(text: str) -> None:
    """Section header. Visually separates phases in the wizard's output."""
    bar = "─" * max(len(text) + 4, 60)
    print(f"\n{bold(bar)}")
    print(f"  {bold(text)}")
    print(f"{bold(bar)}\n")


def prompt(label: str, *, secret: bool = False) -> str:
    """Single prompt with secret/non-secret routing.

    Strips trailing whitespace. Empty input is returned as "" — caller
    decides whether that's OK.
    """
    text = f"  {label}: "
    raw = getpass.getpass(text) if secret else input(text)
    return raw.strip()


class PulumiError(RuntimeError):
    """A `pulumi ...` invocation exited non-zero. Caller decides whether fatal."""


def run_pulumi(*args: str, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a `pulumi ...` command.

    `capture=True` collects stdout/stderr (used for read-only commands like
    `whoami`, `stack ls`, `config get` where we branch on the value).
    `capture=False` streams them to the user's terminal (used for write
    commands like `stack init`, `config set` where the user benefits from
    seeing Pulumi's own messages directly).

    `check=True` raises PulumiError on non-zero exit. Callers that need to
    branch on exit code (e.g. `pulumi whoami` failing means "not logged in")
    pass `check=False` and inspect `.returncode`.
    """
    full = ["pulumi", *args]
    result = subprocess.run(
        full,
        capture_output=capture,
        text=capture,  # only meaningful when capturing
        check=False,
    )
    if check and result.returncode != 0:
        raise PulumiError(f"`{' '.join(full)}` exited {result.returncode}")
    return result


# --- DO token validation -------------------------------------------


class InvalidToken(Exception):
    """The DO token unambiguously failed authentication (HTTP 401)."""


class NetworkError(Exception):
    """The DO API was unreachable or returned a non-401 error.

    Caller treats this as fail-soft: the token is accepted with a printed
    warning rather than refusing to store any credentials over a flaky
    network.
    """


_DO_ACCOUNT_URL = "https://api.digitalocean.com/v2/account"


def validate_do_token(token: str) -> None:
    """Live-check a DigitalOcean PAT against /v2/account.

    A 401 is unambiguous evidence the token is wrong — raise InvalidToken so
    the caller can re-prompt. Anything else (5xx, DNS failure, timeout) is
    ambiguous; raise NetworkError and let the caller decide whether to
    accept the value with a warning.
    """
    req = urllib.request.Request(
        _DO_ACCOUNT_URL,
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                raise NetworkError(f"DO API returned HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise InvalidToken("Token did not authenticate (HTTP 401).") from e
        raise NetworkError(f"DO API returned HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise NetworkError(f"Could not reach DO API: {e}") from e


def mask_secret(value: str) -> str:
    """Return a fixed-width mask for display.

    Always 8 dots regardless of the real length — leaking the length of a
    secret is a small but real signal we don't need to give. Empty strings
    render as a literal `(unset)` so the user can tell apart "set but
    masked" from "not set at all".
    """
    if value == "":
        return "(unset)"
    return "••••••••"


_KRS_CHOICES = {"k": "keep", "r": "replace", "s": "skip"}


def ask_krs(key: str, masked_existing: str) -> str:
    """Ask the user [k]eep / [r]eplace / [s]kip for an already-set config key.

    Empty input defaults to "keep" — the safest action when re-running after
    an interruption. Garbage input re-prompts; we don't raise on the user's
    typo.
    """
    prompt = (
        f"\n  {key} is already set to {masked_existing}.\n"
        f"  [K]eep / [r]eplace / [s]kip? "
    )
    while True:
        answer = input(prompt).strip().lower()
        if answer == "":
            return "keep"
        if answer in _KRS_CHOICES:
            return _KRS_CHOICES[answer]
        # fall through to re-prompt


@dataclass(frozen=True)
class ConfigKey:
    """One row of the wizard's config-key table.

    `key`        is the Pulumi config namespace:name (e.g. "digitalocean:token").
    `label`      is the human-readable string shown in prompts.
    `secret`     decides between getpass()/input() and `pulumi config set --secret` vs `set`.
    `validator`  optionally checks the value before storing — raises on hard failure.
    """

    key: str
    label: str
    secret: bool
    validator: Optional[Callable[[str], None]] = None


_ACL_PLACEHOLDER_EMAIL = "your-email@example.com"
_ACL_ADMIN_URL = "https://login.tailscale.com/admin/acls"


def print_acl_snippet(tailnet: str, tag: str) -> None:
    """Print the ACL JSON the user must paste into their tailnet policy.

    Tailnet name is included in the prose; the JSON itself doesn't reference
    the tailnet (Tailscale's policy file is scoped to one tailnet by
    construction). The src field uses a placeholder email — we don't try to
    discover the user's identity, that's their decision.
    """
    snippet = {
        "tagOwners": {tag: ["autogroup:admin"]},
        "acls": [
            {
                "action": "accept",
                "src": [_ACL_PLACEHOLDER_EMAIL],
                "dst": [f"{tag}:*"],
            }
        ],
        "ssh": [
            {
                "action": "accept",
                "src": [_ACL_PLACEHOLDER_EMAIL],
                "dst": [tag],
                "users": ["claude"],
            }
        ],
    }
    print(
        f"\n  Open your tailnet policy editor:\n"
        f"    {_ACL_ADMIN_URL}\n"
        f"\n  Merge this into your existing policy (replace "
        f"{_ACL_PLACEHOLDER_EMAIL!r} with the principal you want to grant):\n"
    )
    print(json.dumps(snippet, indent=2))
    print(f"\n  Tailnet: {tailnet}")


CONFIG_KEYS: list[ConfigKey] = [
    ConfigKey("digitalocean:token",            "DigitalOcean PAT",                secret=True,  validator=validate_do_token),
    ConfigKey("tailscale:oauth_client_id",     "Tailscale OAuth client ID",       secret=True,  validator=None),
    ConfigKey("tailscale:oauth_client_secret", "Tailscale OAuth client secret",   secret=True,  validator=None),
    ConfigKey("tailscale:tailnet",             "Tailnet name (e.g. example.com)", secret=False, validator=None),
]


# --- phase 1: prereqs ----------------------------------------------


def check_prereqs() -> None:
    """Verify the CLIs the wizard depends on are reachable.

    `pulumi` is hard-required — fail with an install hint if missing.
    `tailscale` is only needed *after* `pulumi up` (to actually reach the
    box), so we warn rather than fail. `uv` is implicitly present because
    we ran via `uv run python setup.py`.
    """
    banner("Phase 1 — Checking prerequisites")
    if shutil.which("pulumi") is None:
        print(red("  pulumi CLI not found on PATH."))
        print("  Install with: brew install pulumi/tap/pulumi")
        print("  Or see: https://www.pulumi.com/docs/install/")
        sys.exit(1)
    print(green("  ✓ pulumi"))

    if shutil.which("tailscale") is None:
        print(yellow("  ! tailscale CLI not found on PATH."))
        print("    You'll need it after `pulumi up` to reach the droplet.")
        print("    Install: https://tailscale.com/download")
    else:
        print(green("  ✓ tailscale"))


# --- phase 2: backend ----------------------------------------------


def ensure_backend() -> None:
    """Detect or set up a Pulumi backend.

    `pulumi whoami` doubles as our "is the CLI usable / are you logged in?"
    check. If it succeeds, we're done. Otherwise we offer cloud (the user
    runs `pulumi login` themselves in a separate terminal — the cloud login
    flow opens a browser and isn't worth wrapping) or local-with-passphrase
    (we set PULUMI_CONFIG_PASSPHRASE in our own env so the wizard's later
    `pulumi config set` calls work, then echo the passphrase once with a
    "save this" warning so the user can put it in a password manager).
    """
    banner("Phase 2 — Pulumi backend")
    result = run_pulumi("whoami", capture=True, check=False)
    if result.returncode == 0:
        who = result.stdout.strip()
        print(green(f"  ✓ Logged in as: {who}"))
        return

    print("  You are not logged into a Pulumi backend.")
    print("  Choose one:")
    print("    [c] Pulumi Cloud (recommended — free for individuals)")
    print("    [l] Local backend with passphrase-encrypted secrets")
    while True:
        choice = input("  [c]/[l]? ").strip().lower()
        if choice in ("c", "l"):
            break

    if choice == "c":
        print()
        print("  In a separate terminal, run:")
        print(bold("    pulumi login"))
        print()
        print("  Complete the browser flow, then come back here.")
        input("  Press enter once you're logged in. ")
        recheck = run_pulumi("whoami", capture=True, check=False)
        if recheck.returncode != 0:
            print(red("  pulumi whoami still fails. Aborting."))
            print("  Re-run `uv run python setup.py` once login succeeds.")
            sys.exit(1)
        print(green(f"  ✓ Logged in as: {recheck.stdout.strip()}"))
        return

    # local backend
    print()
    print("  The local backend encrypts stack secrets with a passphrase.")
    print("  Pick something strong — losing it means losing access to the")
    print("  encrypted stack values.")
    passphrase = prompt("Passphrase", secret=True)
    if not passphrase:
        print(red("  Empty passphrase — refusing to continue."))
        sys.exit(1)
    os.environ["PULUMI_CONFIG_PASSPHRASE"] = passphrase
    run_pulumi("login", "--local")
    print()
    print(yellow("  IMPORTANT — save this passphrase NOW:"))
    print(f"    {bold(passphrase)}")
    print()
    print("  You must `export PULUMI_CONFIG_PASSPHRASE='<value>'` in any")
    print("  shell where you run `pulumi preview` / `pulumi up`. The wizard")
    print("  will not display this passphrase again.")
    input("  Press enter once you've saved it. ")


# --- phase 3: stack ------------------------------------------------


def ensure_stack(name: str = "dev") -> None:
    """Select the named stack, or `pulumi stack init` it if it doesn't exist.

    `pulumi stack ls --json` is the read path. We don't try to be clever
    about pre-existing-elsewhere errors — if `init` fails (e.g. the stack
    exists in Pulumi Cloud under another org), we let Pulumi's error
    surface verbatim and exit. The user then resolves it themselves.
    """
    banner(f"Phase 3 — Stack `{name}`")
    listing = run_pulumi("stack", "ls", "--json", capture=True, check=False)
    if listing.returncode != 0:
        # `stack ls` can fail before any stack exists in some pulumi versions.
        # Treat as "no stacks" and try init.
        existing: list[str] = []
    else:
        try:
            existing = [s["name"] for s in json.loads(listing.stdout)]
        except (json.JSONDecodeError, KeyError, TypeError):
            existing = []

    if name in existing:
        print(green(f"  ✓ Stack `{name}` already exists; selecting it."))
        run_pulumi("stack", "select", name)
        return

    print(f"  Creating stack `{name}`...")
    run_pulumi("stack", "init", name)
    print(green(f"  ✓ Stack `{name}` created and selected."))


# --- phase 4: config keys ------------------------------------------


_MAX_VALIDATION_RETRIES = 3


def _get_existing(key: str) -> Optional[str]:
    """Return the current value of a Pulumi config key, or None if unset.

    `pulumi config get <key>` exits non-zero when the key is unset, which is
    Pulumi's normal behavior — we treat it as "not set". For secret keys
    Pulumi prints the *decrypted* plaintext on success; we use it only to
    decide "is this set?", never log or echo the captured value.
    """
    result = run_pulumi("config", "get", key, capture=True, check=False)
    if result.returncode != 0:
        return None
    return result.stdout.rstrip("\n")


def _set_value(spec: ConfigKey, value: str) -> None:
    args = ["config", "set"]
    if spec.secret:
        args.append("--secret")
    args.extend([spec.key, value])
    # capture=True so the value doesn't echo to the terminal even on
    # success. (`pulumi config set --secret` doesn't echo it, but
    # `set` without --secret does for non-secret keys; capturing is
    # uniformly safe.)
    run_pulumi(*args, capture=True)


def configure_key(spec: ConfigKey) -> None:
    """Walk the user through one config key with [k]/[r]/[s] handling."""
    existing = _get_existing(spec.key)
    if existing is not None:
        masked = mask_secret(existing) if spec.secret else existing
        choice = ask_krs(spec.key, masked)
        if choice == "keep":
            print(green(f"  ✓ Keeping existing {spec.key}."))
            return
        if choice == "skip":
            print(yellow(f"  ! Skipping {spec.key}. `pulumi up` will fail "
                         f"unless you set it manually."))
            return
        # fall through to replace flow

    # ask + (optionally) validate, with retries on InvalidToken
    attempts = 0
    while True:
        value = prompt(spec.label, secret=spec.secret)
        if not value:
            print(yellow("  Empty value; please try again."))
            continue
        if spec.validator is not None:
            try:
                spec.validator(value)
            except InvalidToken as e:
                attempts += 1
                print(red(f"  ✗ {e}"))
                if attempts >= _MAX_VALIDATION_RETRIES:
                    print(red(f"  Aborting after {attempts} failed attempts."))
                    sys.exit(1)
                continue
            except NetworkError as e:
                print(yellow(f"  ! {e}"))
                print(yellow("    Accepting the value without live validation."))
        break

    _set_value(spec, value)
    print(green(f"  ✓ {spec.key} stored."))


def configure_all_keys() -> None:
    banner("Phase 4 — Stack config")
    for spec in CONFIG_KEYS:
        configure_key(spec)
