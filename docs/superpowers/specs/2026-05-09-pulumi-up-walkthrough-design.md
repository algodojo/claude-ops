# Interactive setup walkthrough for `pulumi up`

**Status:** Approved (brainstorming complete) — ready for implementation plan.
**Date:** 2026-05-09

## Goal

Reduce first-run friction for new `claude-ops` users by adding an interactive
walkthrough that gathers and configures everything `pulumi up` needs to succeed
on a clean checkout. The walkthrough targets the `dev` stack only; the
production path remains a manual exercise documented in `AGENTS.md` and the
README, with a hand-off hint printed at the end of the wizard.

The walkthrough is *additive*: the manual `pulumi config set ...` flow in the
existing README stays unchanged. Users who prefer the manual path are
unaffected.

## Non-goals

- Automating the `prod` stack. Production has materially different ops posture
  (snapshot pinning per `AGENTS.md` "Strong preferences", optional Pulumi ESC
  for centrally-rotatable secrets) that involves real decisions, not mechanical
  data entry. The wizard prints a graduation hint on success but does not try
  to wizard-ify those decisions.
- Editing the user's Tailscale ACL on their behalf. Tailscale's policy API
  requires an OAuth scope (`policy_file`) we don't currently mint, and writing
  a user's tailnet policy is high-blast-radius. The wizard prints a
  ready-to-paste JSON snippet and a deep link to the admin console.
- Driving `pulumi login` itself. The cloud login flow opens a browser and is
  inherently interactive; trying to wrap it would add complexity for no
  benefit. The wizard tells the user to run it in a separate terminal and
  waits.
- Live-validating the Tailscale OAuth client. Validating without minting a
  real key requires a different OAuth scope than the one we ask for, and
  minting a key as a side-effect of validation would leave a stray key on the
  user's tailnet.
- Replacing or deprecating the existing manual setup steps in the README.

## Threat-model alignment

The wizard interacts with the same secrets the manual flow already handles:
DigitalOcean PAT, Tailscale OAuth client ID + secret, tailnet name. It must
not relax any of the existing security guarantees.

- **Hard rule #1 (no secrets in source):** the wizard reads secrets from
  interactive prompts (`getpass.getpass()`) and writes them via
  `pulumi config set --secret`. They land in `Pulumi.dev.yaml` encrypted by
  Pulumi's secrets provider — same path as the manual flow. Secrets never
  hit disk in plaintext, never appear in argv, never appear in shell history.
- **Hard rule #8 (no interactive prompts in *provisioning*):** this rule
  governs cloud-init / `pulumi up` itself, which must remain unattended. The
  wizard runs *before* provisioning and is explicitly opt-in (`uv run python
  setup.py`); `pulumi up` itself is unchanged and remains non-interactive.
- **No new external dependencies:** the wizard uses stdlib only
  (`subprocess`, `urllib.request`, `getpass`, `json`, `dataclasses`,
  `shutil`, `os`, `sys`). The only new dev dependency is `pytest`. Each
  new dep is supply-chain surface per `AGENTS.md`; stdlib-only keeps that
  surface zero for the runtime path.
- **Pulumi `Output` flow is unaffected:** the wizard does not touch the
  Pulumi program (`__main__.py`, `cloud_init.py`, etc.). It only mutates
  `Pulumi.dev.yaml` via `pulumi config set`, which is the same write path
  the existing README documents.

## File location and invocation

Single file: `infra/setup.py`. Run with:

    cd infra
    uv run python setup.py

`infra/` is the canonical "run pulumi commands here" directory in the existing
README. Putting the script there preserves that mental model: same cwd, same
`uv` toolchain, same Python interpreter. `uv run python setup.py`
automatically picks up the lockfile-pinned environment, so the script runs
against the exact same dependency tree as `pulumi up`.

A new `## Quick setup (interactive)` section is added to `README.md`,
slotted *between* the existing "One-time setup" and "Development workflow"
sections, pointing at the wizard. The existing manual flow ("Development
workflow") remains documented verbatim below it.

## Walkthrough flow

Six linear phases. Each phase is independently safe to abort: `Ctrl-C` leaves
the Pulumi config in a known state because every `pulumi config set` is
atomic.

### Phase 1 — Banner and prerequisite check

- Print a brief banner ("Setting up claude-ops dev stack …").
- `shutil.which("pulumi")` — hard fail with install hint if missing
  (`brew install pulumi/tap/pulumi`).
- `shutil.which("tailscale")` — warn-only if missing. Tailscale is only
  needed *after* `pulumi up` to reach the box.
- `uv` is implicitly present (the script ran via it).

### Phase 2 — Pulumi backend

- Run `pulumi whoami`. If exit 0, print "Using backend: <user/url>" and
  continue.
- If non-zero, prompt: `[c]loud / [l]ocal-with-passphrase`.
  - **Cloud:** instruct the user to run `pulumi login` in a separate
    terminal, wait for them to press enter, then re-run `pulumi whoami`. If
    still non-zero, abort with a clear error.
  - **Local:** prompt for a passphrase (`getpass`), set
    `os.environ["PULUMI_CONFIG_PASSPHRASE"]` so the wizard's own subsequent
    `pulumi` subprocess calls work, run `pulumi login --local`. Then print
    a one-time reminder: "Save this passphrase — you must
    `export PULUMI_CONFIG_PASSPHRASE='<value>'` in your shell before running
    `pulumi preview`/`pulumi up`. The wizard will not display it again."
    Echo the passphrase value once, in plaintext, so the user can copy it
    to a password manager. (Echoing once is a deliberate trade-off: the
    alternative — never showing it — leaves the user with no way to recover
    a passphrase they typed but didn't save.)

### Phase 3 — Stack

- `pulumi stack ls --json` to detect existing stacks.
- If `dev` exists, run `pulumi stack select dev`.
- Otherwise, run `pulumi stack init dev`.

### Phase 4 — Config keys

Loop over a data-driven table of four keys:

| Key | Secret? | Live validation |
|---|---|---|
| `digitalocean:token` | yes | `GET /v2/account` with bearer token |
| `tailscale:oauth_client_id` | yes | none |
| `tailscale:oauth_client_secret` | yes | none |
| `tailscale:tailnet` | no | none |

For each key:

1. `pulumi config get <key>` to detect existing value. Note: for secret
   keys, Pulumi returns the *decrypted* plaintext on stdout — so the wizard
   reads it but must never log or echo it. Treat the captured value as
   sensitive: use it only to decide "is this set?", then drop it.
2. If present, show a **masked** rendering (`••••••••` for secrets, full
   value for plain keys like `tailnet`) and ask `[k]eep / [r]eplace / [s]kip`.
3. If absent or user chose `replace`, prompt: `getpass` for secret keys,
   plain `input` for non-secret keys.
4. If a validator is defined, run it. On unambiguous failure (HTTP 401),
   re-prompt — up to 3 attempts before aborting. On ambiguous failure
   (network error, timeout), print a warning and accept the value.
5. `pulumi config set [--secret] <key> <value>`.

### Phase 5 — Tailscale ACL handoff

- Print a ready-to-paste JSON snippet, with `tag:claude-ops` (or the user's
  override) and the user's tailnet pre-filled. The `src` field uses a
  placeholder (`<your-email@example.com>`) the user replaces.
- Print the deep link: `https://login.tailscale.com/admin/acls`.
- Pause: "Press enter once you've saved the ACL." No automated check.

### Phase 6 — Done

Print:

- Confirmation: "Stack `dev` is configured."
- Next steps: `pulumi preview`, `pulumi up`, `tailscale ssh claude@claude-ops`.
- Prod-graduation hint: "To graduate to a `prod` stack: pin a snapshot ID
  via `pulumi config set image <snap-id>` and consider migrating secrets to
  Pulumi ESC. See README §Production."

Exit 0.

## Component layout

`infra/setup.py` — single file, ~250 lines, organized as small functions
each with one clear job:

```
helpers              color()  banner()  prompt()  ask_krs()  run_pulumi()
phase 1              check_prereqs()
phase 2              ensure_backend()
phase 3              ensure_stack(name="dev")
phase 4              configure_key(spec: ConfigKey)        ← loops over CONFIG_KEYS
                     validate_do_token(token)               ← one validator
phase 5              print_acl_snippet(tailnet, tag)
phase 6              print_next_steps()
entry                main() -> int
```

Two design choices worth calling out:

- **`ConfigKey` dataclass + `CONFIG_KEYS` table.** All four keys are
  data-driven from one list with `key`, `label`, `secret: bool`,
  `validator: Callable | None`. Adding a new config key later means
  appending a row, not editing four functions. The k/r/s logic lives in
  one place (`configure_key`) and applies to every key uniformly.

- **`run_pulumi()` wrapper.** Centralizes the capture-vs-stream decision.
  Read commands (`whoami`, `stack ls`, `config get`) capture stdout so we
  can branch on the result. Write commands (`stack init`, `config set`)
  stream stdout/stderr so the user sees Pulumi's own messages — important
  when something goes wrong inside Pulumi itself.

## Live validation: DigitalOcean token

Implementation:

```python
import urllib.request, urllib.error, json

def validate_do_token(token: str) -> None:
    req = urllib.request.Request(
        "https://api.digitalocean.com/v2/account",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                raise InvalidToken(f"DO API returned {resp.status}")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise InvalidToken("Token did not authenticate (HTTP 401).")
        raise NetworkError(f"DO API returned {e.code}; accepting token") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise NetworkError(f"Could not reach DO API: {e}; accepting token") from e
```

`InvalidToken` is fatal-to-the-prompt (re-ask up to 3×). `NetworkError`
prints a warning and accepts the value. Reasoning: 401 is unambiguous
evidence the token won't work; refusing to store *any* token because of a
flaky wifi connection would be hostile.

## Error handling — concrete cases

| Case | Behavior |
|---|---|
| `pulumi` not on PATH | Hard fail. Print install hint. Exit 1. |
| `tailscale` not on PATH | Warn-only. Continue. |
| `pulumi whoami` fails | Treat as "not logged in" → backend prompt. |
| User aborts `pulumi login` | They never reach the wizard's "press enter" prompt → Ctrl-C → exit 130. |
| `pulumi stack init dev` fails (stack exists in cloud) | Surface error verbatim, exit 1. Don't try to recover. |
| `pulumi config get <key>` non-zero | Treat as "not set" (Pulumi's behavior for unset keys). |
| DO token returns 401 | Re-prompt up to 3×. After 3, exit 1. |
| DO token check times out | Warning printed; token accepted. |
| Ctrl-C anywhere | Trap `KeyboardInterrupt`, print "Aborted." in red, exit 130. |

Pulumi config writes are atomic, so abort-mid-flow leaves a known partial
state: keys set so far are set, the rest are unset. A re-run picks up
where the user left off (the k/r/s prompt naturally surfaces what's
already there).

## Testing strategy

Add `pytest` as a dev dependency: `uv add --dev pytest`.

Two test files under `infra/tests/`:

- `test_setup.py` — unit tests for pure parts:
  - `ask_krs()` — `input()` mocked, verify k/r/s mapping, default behavior,
    invalid-input loop.
  - `print_acl_snippet()` — given tailnet and tag, assert stdout (via
    `capsys`) contains valid JSON with the expected `tagOwners`, `acls`,
    and `ssh` blocks.
  - `CONFIG_KEYS` table — assert the four expected keys are present with
    the right `secret` and `validator` attribution.
- `test_validate_do_token.py` — `validate_do_token` with `urllib` mocked:
  - 200 → no raise.
  - 401 → raises `InvalidToken`.
  - `URLError` → raises `NetworkError` (caller treats as fail-soft).

Out of scope for tests:

- Integration against real Pulumi/DO/Tailscale APIs. Would need real
  credentials, would be flaky, and conflicts with `AGENTS.md` hard
  rule #1.
- Tests of `subprocess.run` against real `pulumi`. Covered by humans
  running the script during code review.

## Documentation changes

Add one section to `README.md`, sitting *above* the existing
"Development workflow" block:

```markdown
## Quick setup (interactive)

For a guided walk-through that prompts for everything `pulumi up` needs:

    cd infra
    uv run python setup.py

This sets the four required config keys, validates the DigitalOcean token,
and prints the Tailscale ACL snippet you'll need to paste into your tailnet
policy. Re-runnable — already-set keys can be kept, replaced, or skipped.

For manual setup, follow "Development workflow" below.
```

No other doc changes. `AGENTS.md` is untouched: the wizard does not
introduce any new security rule, and per the "Don't add `README` walls of
text describing what the code already says" guidance, the new section is
deliberately terse.

## Open questions

None remaining at brainstorming-time. All scope, behavior, and dependency
decisions have explicit user approval (see brainstorming transcript).

## Out-of-scope follow-ups (deliberately not in this spec)

- A `prod`-stack wizard, or any prod-aware codepath in `setup.py`. Prod
  remains a manual flow per the README.
- Live validation of Tailscale OAuth credentials. Would require additional
  OAuth scopes and risks side-effects (key minting).
- Driving `pulumi login` programmatically. Browser-based interactive flow
  is fundamentally outside what a script should wrap.
- Pre-commit hooks or CI to run `setup.py --dry-run`. The script is
  human-driven, not CI-driven.
