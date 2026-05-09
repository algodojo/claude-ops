# Interactive `pulumi up` Setup Walkthrough — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in interactive wizard (`infra/setup.py`) that walks new users through everything `pulumi up` needs to succeed on a clean checkout — backend, stack init, four config keys (with live DO-token validation), and a Tailscale ACL handoff.

**Architecture:** Single-file Python script in `infra/`, run via `uv run python setup.py`. Stdlib-only at runtime. Six linear phases with detect-and-ask (`[k]eep/[r]eplace/[s]kip`) for already-set values. Targets `dev` stack only; prints a graduation hint for `prod`. Companion design spec: `docs/superpowers/specs/2026-05-09-pulumi-up-walkthrough-design.md`.

**Tech Stack:** Python 3.12 (per `infra/.python-version`), Pulumi CLI (driven via `subprocess`), `urllib.request` for DO-token validation, `getpass` for secret input, `pytest` for tests (new dev-only dependency).

---

## File structure

| Path | Status | Responsibility |
|---|---|---|
| `infra/setup.py` | new | Wizard entry point, helpers, phases, `main()` |
| `infra/tests/__init__.py` | new | Empty package marker |
| `infra/tests/test_setup.py` | new | Unit tests for `ask_krs`, `mask_secret`, `print_acl_snippet`, `CONFIG_KEYS` |
| `infra/tests/test_validate_do_token.py` | new | Unit tests for DO token validator |
| `infra/pyproject.toml` | modify | Add `pytest` to dev deps, add `[tool.pytest.ini_options]` |
| `infra/uv.lock` | modify (auto) | Updated by `uv add --dev pytest` |
| `README.md` | modify | Insert "Quick setup (interactive)" section between existing "One-time setup" and "Development workflow" |

`setup.py` is one file, but its functions have clean boundaries — each phase is its own function, the four config keys are data-driven from one `CONFIG_KEYS` list, and the testable parts (`ask_krs`, `mask_secret`, `print_acl_snippet`, `validate_do_token`) are pure or trivially-mockable. Per the spec, no internal package; the audit surface stays one file.

---

## Conventions for this plan

**Working directory:** All `uv`, `pulumi`, and `pytest` commands run from `infra/` unless otherwise noted. Git commands run from the repo root.

**Pytest invocation:** `cd infra && uv run pytest` (config in `infra/pyproject.toml`, `testpaths = ["tests"]`).

**Commit style:** Match existing log style — `feat:` / `test:` / `docs:` / `chore:` prefix, one-line subject, body explaining *why*. Co-authorship trailer required.

---

## Task 1: Bootstrap — add pytest dev dep, scaffold tests/

**Files:**
- Modify: `infra/pyproject.toml`
- Create: `infra/tests/__init__.py`
- Create: `infra/tests/test_smoke.py` (temporary smoke test, deleted in Task 2)

- [ ] **Step 1: Add pytest as a dev dependency**

Run from `infra/`:

```bash
uv add --dev pytest
```

Expected: `infra/pyproject.toml` gains a `[dependency-groups]` table with a `dev` group containing `pytest`. `uv.lock` is regenerated.

- [ ] **Step 2: Add a minimal pytest config to `infra/pyproject.toml`**

Append to `infra/pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
```

This pins pytest's discovery to the `tests/` directory so a stray `test_*.py` elsewhere in the tree never gets picked up by accident.

- [ ] **Step 3: Create the tests package**

Create `infra/tests/__init__.py` as an empty file.

- [ ] **Step 4: Create a smoke test to verify pytest is wired**

Create `infra/tests/test_smoke.py`:

```python
"""Temporary smoke test — verifies pytest discovery works. Deleted in Task 2."""


def test_pytest_runs():
    assert 1 + 1 == 2
```

- [ ] **Step 5: Run pytest and verify it passes**

Run from `infra/`:

```bash
uv run pytest -v
```

Expected: `tests/test_smoke.py::test_pytest_runs PASSED`. One test passed.

- [ ] **Step 6: Commit**

Run from repo root:

```bash
git add infra/pyproject.toml infra/uv.lock infra/tests/__init__.py infra/tests/test_smoke.py
git commit -m "$(cat <<'EOF'
chore: add pytest dev dep and scaffold tests/ for setup wizard

Adds pytest as a dev-only dependency (per the design spec: stdlib-only
runtime, pytest is the single new dev dep) and pins discovery to
infra/tests/ via [tool.pytest.ini_options].

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Define `ConfigKey` dataclass and `CONFIG_KEYS` table (TDD)

**Files:**
- Create: `infra/setup.py`
- Modify: `infra/tests/test_setup.py` (replaces test_smoke.py)
- Delete: `infra/tests/test_smoke.py`

Why this is first: `CONFIG_KEYS` is the data spine of phase 4. Most other functions reference it (or types from it), so locking it in early avoids churn.

- [ ] **Step 1: Write the failing test**

Replace `infra/tests/test_smoke.py` with `infra/tests/test_setup.py`:

```python
"""Unit tests for pure parts of setup.py."""

from setup import CONFIG_KEYS, ConfigKey


def test_config_keys_has_four_entries():
    assert len(CONFIG_KEYS) == 4


def test_config_keys_are_in_expected_order():
    keys = [k.key for k in CONFIG_KEYS]
    assert keys == [
        "digitalocean:token",
        "tailscale:oauth_client_id",
        "tailscale:oauth_client_secret",
        "tailscale:tailnet",
    ]


def test_only_tailnet_is_non_secret():
    secret_flags = {k.key: k.secret for k in CONFIG_KEYS}
    assert secret_flags == {
        "digitalocean:token": True,
        "tailscale:oauth_client_id": True,
        "tailscale:oauth_client_secret": True,
        "tailscale:tailnet": False,
    }


def test_only_do_token_has_a_validator():
    validators = {k.key: k.validator is not None for k in CONFIG_KEYS}
    assert validators == {
        "digitalocean:token": True,
        "tailscale:oauth_client_id": False,
        "tailscale:oauth_client_secret": False,
        "tailscale:tailnet": False,
    }


def test_config_key_is_a_dataclass_with_label():
    """label is the human-readable string shown in prompts."""
    do = next(k for k in CONFIG_KEYS if k.key == "digitalocean:token")
    assert isinstance(do, ConfigKey)
    assert isinstance(do.label, str) and do.label  # non-empty
```

Then delete `infra/tests/test_smoke.py`:

```bash
rm infra/tests/test_smoke.py
```

- [ ] **Step 2: Run the tests and verify they fail**

Run from `infra/`:

```bash
uv run pytest -v
```

Expected: All five tests FAIL with `ModuleNotFoundError: No module named 'setup'` (or similar — `setup.py` doesn't exist yet).

- [ ] **Step 3: Create `infra/setup.py` with the minimal `ConfigKey` definition**

Create `infra/setup.py`:

```python
"""
claude-ops interactive setup wizard.

Walks a new user through everything `pulumi up` needs to succeed against a
fresh `dev` stack: backend login, stack init, four config keys, and the
Tailscale ACL handoff. Stdlib-only at runtime. See:
docs/superpowers/specs/2026-05-09-pulumi-up-walkthrough-design.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


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


# Validators are wired up in later tasks; for now the slot is just None.
CONFIG_KEYS: list[ConfigKey] = [
    ConfigKey("digitalocean:token",            "DigitalOcean PAT",                secret=True,  validator=None),
    ConfigKey("tailscale:oauth_client_id",     "Tailscale OAuth client ID",       secret=True,  validator=None),
    ConfigKey("tailscale:oauth_client_secret", "Tailscale OAuth client secret",   secret=True,  validator=None),
    ConfigKey("tailscale:tailnet",             "Tailnet name (e.g. example.com)", secret=False, validator=None),
]
```

- [ ] **Step 4: Run the tests and verify they pass**

Run from `infra/`:

```bash
uv run pytest -v
```

Expected: All five tests PASS.

- [ ] **Step 5: Commit**

```bash
git add infra/setup.py infra/tests/test_setup.py
git rm infra/tests/test_smoke.py
git commit -m "$(cat <<'EOF'
feat: add ConfigKey table for setup wizard

Defines the data spine of the wizard's config-key phase: a frozen
ConfigKey dataclass and a CONFIG_KEYS list with the four keys the
existing pulumi program reads. Validator slots are present but None
until task 3 wires up the DO-token validator.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `validate_do_token()` with HTTP 401 / network-error handling (TDD)

**Files:**
- Modify: `infra/setup.py` (add validator + exception types)
- Create: `infra/tests/test_validate_do_token.py`

- [ ] **Step 1: Write the failing test**

Create `infra/tests/test_validate_do_token.py`:

```python
"""Unit tests for validate_do_token — the only live-validation step."""

from io import BytesIO
from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError

import pytest

from setup import InvalidToken, NetworkError, validate_do_token


def _ok_response():
    """Mimic a successful urllib response context manager."""
    resp = MagicMock()
    resp.status = 200
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda *a: False
    return resp


def test_200_response_does_not_raise(monkeypatch):
    monkeypatch.setattr("setup.urllib.request.urlopen", lambda *a, **kw: _ok_response())
    validate_do_token("dop_v1_real-looking-token")  # should not raise


def test_401_raises_invalid_token(monkeypatch):
    def fake_urlopen(*a, **kw):
        raise HTTPError(
            url="https://api.digitalocean.com/v2/account",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=BytesIO(b""),
        )

    monkeypatch.setattr("setup.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(InvalidToken):
        validate_do_token("bad-token")


def test_other_http_error_is_network_error(monkeypatch):
    """5xx etc. should be treated as ambiguous, not as 'token is bad'."""

    def fake_urlopen(*a, **kw):
        raise HTTPError(
            url="https://api.digitalocean.com/v2/account",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=BytesIO(b""),
        )

    monkeypatch.setattr("setup.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(NetworkError):
        validate_do_token("dop_v1_real-looking-token")


def test_url_error_is_network_error(monkeypatch):
    def fake_urlopen(*a, **kw):
        raise URLError("nodename nor servname provided")

    monkeypatch.setattr("setup.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(NetworkError):
        validate_do_token("dop_v1_real-looking-token")


def test_timeout_is_network_error(monkeypatch):
    def fake_urlopen(*a, **kw):
        raise TimeoutError("timed out")

    monkeypatch.setattr("setup.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(NetworkError):
        validate_do_token("dop_v1_real-looking-token")
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
uv run pytest tests/test_validate_do_token.py -v
```

Expected: All five tests FAIL with `ImportError: cannot import name 'InvalidToken' from 'setup'` (or similar).

- [ ] **Step 3: Implement `validate_do_token` and exceptions in `setup.py`**

Append to `infra/setup.py`:

```python
import urllib.error
import urllib.request


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
```

- [ ] **Step 4: Wire `validate_do_token` into `CONFIG_KEYS`**

In `infra/setup.py`, change the `digitalocean:token` row of `CONFIG_KEYS` from `validator=None` to `validator=validate_do_token`:

```python
CONFIG_KEYS: list[ConfigKey] = [
    ConfigKey("digitalocean:token",            "DigitalOcean PAT",                secret=True,  validator=validate_do_token),
    ConfigKey("tailscale:oauth_client_id",     "Tailscale OAuth client ID",       secret=True,  validator=None),
    ConfigKey("tailscale:oauth_client_secret", "Tailscale OAuth client secret",   secret=True,  validator=None),
    ConfigKey("tailscale:tailnet",             "Tailnet name (e.g. example.com)", secret=False, validator=None),
]
```

`CONFIG_KEYS` must come *after* the `validate_do_token` definition in the file. If your earlier task placed `CONFIG_KEYS` above the new validator code, move the `CONFIG_KEYS` block to the bottom of the module (after `validate_do_token`).

- [ ] **Step 5: Run all tests and verify they pass**

```bash
uv run pytest -v
```

Expected: 5 tests in `test_setup.py` PASS, 5 tests in `test_validate_do_token.py` PASS. Total: 10 passing.

- [ ] **Step 6: Commit**

```bash
git add infra/setup.py infra/tests/test_validate_do_token.py
git commit -m "$(cat <<'EOF'
feat: add live DO-token validator with 401 vs network-error split

validate_do_token hits GET /v2/account with the supplied PAT. A 401 is
unambiguous and raises InvalidToken (caller re-prompts). Anything else
(5xx, DNS failure, timeout) raises NetworkError so the caller can
fail-soft — refusing to store a token over flaky wifi would be hostile.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `mask_secret()` and `ask_krs()` helpers (TDD)

**Files:**
- Modify: `infra/setup.py`
- Modify: `infra/tests/test_setup.py`

- [ ] **Step 1: Write the failing tests**

Append to `infra/tests/test_setup.py`:

```python
import pytest

from setup import ask_krs, mask_secret


# --- mask_secret -------------------------------------------------


def test_mask_secret_returns_fixed_dots_for_non_empty():
    assert mask_secret("hunter2") == "••••••••"


def test_mask_secret_returns_dots_regardless_of_length():
    """Length-leakage is a real concern. Always 8 dots."""
    assert mask_secret("a") == "••••••••"
    assert mask_secret("a" * 200) == "••••••••"


def test_mask_secret_empty_renders_explicitly():
    """Empty string is a real possibility (`pulumi config get` of an unset secret)."""
    assert mask_secret("") == "(unset)"


# --- ask_krs -----------------------------------------------------


def test_ask_krs_keep(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "k")
    assert ask_krs("digitalocean:token", "••••••••") == "keep"


def test_ask_krs_replace(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "r")
    assert ask_krs("digitalocean:token", "••••••••") == "replace"


def test_ask_krs_skip(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "s")
    assert ask_krs("digitalocean:token", "••••••••") == "skip"


def test_ask_krs_is_case_insensitive(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "K")
    assert ask_krs("digitalocean:token", "••••••••") == "keep"


def test_ask_krs_default_on_empty_is_keep(monkeypatch):
    """Pressing enter on the prompt should default to the safest action: keep."""
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    assert ask_krs("digitalocean:token", "••••••••") == "keep"


def test_ask_krs_reprompts_on_invalid(monkeypatch):
    """Garbage input should re-ask, not raise."""
    answers = iter(["nope", "wat", "r"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    assert ask_krs("digitalocean:token", "••••••••") == "replace"
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
uv run pytest tests/test_setup.py -v
```

Expected: The 9 new tests FAIL with `ImportError: cannot import name 'ask_krs' from 'setup'` (or `mask_secret`).

- [ ] **Step 3: Implement `mask_secret` and `ask_krs`**

Add to `infra/setup.py` (above `CONFIG_KEYS`):

```python
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
```

- [ ] **Step 4: Run all tests and verify they pass**

```bash
uv run pytest -v
```

Expected: 14 tests in `test_setup.py` PASS, 5 tests in `test_validate_do_token.py` PASS. Total: 19 passing.

- [ ] **Step 5: Commit**

```bash
git add infra/setup.py infra/tests/test_setup.py
git commit -m "$(cat <<'EOF'
feat: add mask_secret and ask_krs helpers for the wizard

mask_secret returns a fixed 8-dot string for any non-empty secret (length
is a small but real signal we don't need to leak) and "(unset)" for
empty. ask_krs reads [k]eep/[r]eplace/[s]kip with empty-defaults-to-keep
(safest action when resuming after Ctrl-C) and re-prompts on bad input.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `print_acl_snippet()` — Tailscale ACL handoff (TDD)

**Files:**
- Modify: `infra/setup.py`
- Modify: `infra/tests/test_setup.py`

- [ ] **Step 1: Write the failing test**

Append to `infra/tests/test_setup.py`:

```python
import json
import re

from setup import print_acl_snippet


def _extract_json_block(captured: str) -> dict:
    """Pull the first {...} JSON object out of captured stdout.

    The function prints prose around the snippet; we just want the JSON.
    """
    match = re.search(r"\{.*\}", captured, re.DOTALL)
    assert match, f"no JSON block found in:\n{captured}"
    return json.loads(match.group(0))


def test_print_acl_snippet_emits_valid_json(capsys):
    print_acl_snippet(tailnet="example.com", tag="tag:claude-ops")
    out = capsys.readouterr().out
    parsed = _extract_json_block(out)
    assert "tagOwners" in parsed
    assert "acls" in parsed
    assert "ssh" in parsed


def test_print_acl_snippet_uses_supplied_tag(capsys):
    print_acl_snippet(tailnet="example.com", tag="tag:custom")
    out = capsys.readouterr().out
    parsed = _extract_json_block(out)
    assert "tag:custom" in parsed["tagOwners"]
    assert any("tag:custom" in str(rule) for rule in parsed["acls"])
    assert any("tag:custom" in str(rule) for rule in parsed["ssh"])


def test_print_acl_snippet_includes_admin_url(capsys):
    print_acl_snippet(tailnet="example.com", tag="tag:claude-ops")
    out = capsys.readouterr().out
    assert "https://login.tailscale.com/admin/acls" in out


def test_print_acl_snippet_uses_email_placeholder(capsys):
    """src must be a placeholder the user replaces, not their real email."""
    print_acl_snippet(tailnet="example.com", tag="tag:claude-ops")
    out = capsys.readouterr().out
    parsed = _extract_json_block(out)
    # both acl and ssh blocks should reference the placeholder
    assert any("your-email@example.com" in str(rule) for rule in parsed["acls"])
    assert any("your-email@example.com" in str(rule) for rule in parsed["ssh"])
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
uv run pytest tests/test_setup.py -v
```

Expected: The 4 new tests FAIL with `ImportError: cannot import name 'print_acl_snippet' from 'setup'`.

- [ ] **Step 3: Implement `print_acl_snippet`**

Add to `infra/setup.py`:

```python
import json

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
```

- [ ] **Step 4: Run all tests and verify they pass**

```bash
uv run pytest -v
```

Expected: 18 tests in `test_setup.py` PASS, 5 tests in `test_validate_do_token.py` PASS. Total: 23 passing.

- [ ] **Step 5: Commit**

```bash
git add infra/setup.py infra/tests/test_setup.py
git commit -m "$(cat <<'EOF'
feat: add print_acl_snippet for the Tailscale ACL handoff

Renders a ready-to-paste tagOwners/acls/ssh JSON block scoped to the
supplied tag, with a placeholder email the user replaces. We can't
edit their tailnet policy automatically (would need a different OAuth
scope and is high-blast-radius anyway), so this is a hard handoff.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: I/O helpers — `color`, `banner`, `prompt`, `run_pulumi`

**Files:**
- Modify: `infra/setup.py`

These are thin wrappers around `print()`, `input()`, `getpass()`, and `subprocess.run()`. Per the spec, none are unit-tested — they're either trivial passthroughs or wrap impure system calls. Their value is centralizing one decision each.

- [ ] **Step 1: Add color helpers and `banner`**

Insert at the top of `infra/setup.py` (just under the docstring, before existing code):

```python
import sys


# ANSI escapes — narrow palette, only used for prose. Disabled when stdout
# is not a TTY (CI logs, redirected output).
def _isatty() -> bool:
    return sys.stdout.isatty()


def color(text: str, code: str) -> str:
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
```

- [ ] **Step 2: Add `prompt` wrapper**

Append to `infra/setup.py` (after `ask_krs`):

```python
import getpass


def prompt(label: str, *, secret: bool = False) -> str:
    """Single prompt with secret/non-secret routing.

    Strips trailing whitespace. Empty input is returned as "" — caller
    decides whether that's OK.
    """
    text = f"  {label}: "
    raw = getpass.getpass(text) if secret else input(text)
    return raw.strip()
```

- [ ] **Step 3: Add `run_pulumi` wrapper**

Append to `infra/setup.py`:

```python
import subprocess


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
```

- [ ] **Step 4: Run tests to verify nothing regressed**

```bash
uv run pytest -v
```

Expected: All 23 tests still PASS. (No new tests; we're verifying the new code didn't break imports.)

- [ ] **Step 5: Commit**

```bash
git add infra/setup.py
git commit -m "$(cat <<'EOF'
feat: add I/O helpers (color, banner, prompt, run_pulumi)

color/green/yellow/red/bold/banner are TTY-aware ANSI wrappers (no-op
when stdout isn't a TTY, so CI logs stay clean). prompt routes
input vs getpass via a single secret= kwarg. run_pulumi centralizes
the capture-vs-stream decision and the non-zero-exit policy.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `check_prereqs()` — phase 1

**Files:**
- Modify: `infra/setup.py`

- [ ] **Step 1: Implement `check_prereqs`**

Append to `infra/setup.py`:

```python
import shutil


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
```

- [ ] **Step 2: Run tests to verify nothing regressed**

```bash
uv run pytest -v
```

Expected: All 23 tests still PASS.

- [ ] **Step 3: Manually smoke-test the prereq check**

Run from `infra/`:

```bash
uv run python -c "from setup import check_prereqs; check_prereqs()"
```

Expected: Banner printed, "✓ pulumi" and "✓ tailscale" (or warnings if either is missing).

- [ ] **Step 4: Commit**

```bash
git add infra/setup.py
git commit -m "$(cat <<'EOF'
feat: add phase 1 — prereq check (pulumi hard-required, tailscale warn)

shutil.which keeps it simple: pulumi missing is fatal (install hint
printed), tailscale missing is a warning since it's only needed after
pulumi up to reach the droplet over the tailnet.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `ensure_backend()` — phase 2

**Files:**
- Modify: `infra/setup.py`

- [ ] **Step 1: Implement `ensure_backend`**

Append to `infra/setup.py`:

```python
import os


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
        # `pulumi whoami --verbose` would also print the backend URL, but
        # not every Pulumi version supports it; the simple form is enough.
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
```

- [ ] **Step 2: Run tests to verify nothing regressed**

```bash
uv run pytest -v
```

Expected: 23 tests still PASS. (The new code is impure; we're verifying imports still work.)

- [ ] **Step 3: Commit**

```bash
git add infra/setup.py
git commit -m "$(cat <<'EOF'
feat: add phase 2 — backend detection and login

pulumi whoami doubles as the "is the CLI usable" check. On failure,
offer cloud (user runs `pulumi login` in another terminal — wrapping a
browser flow isn't worth the complexity) or local (we set
PULUMI_CONFIG_PASSPHRASE in our own env for subsequent subprocess
calls, then echo the passphrase once with a save-this-now warning).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `ensure_stack()` — phase 3

**Files:**
- Modify: `infra/setup.py`

- [ ] **Step 1: Implement `ensure_stack`**

Append to `infra/setup.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify nothing regressed**

```bash
uv run pytest -v
```

Expected: 23 tests still PASS.

- [ ] **Step 3: Commit**

```bash
git add infra/setup.py
git commit -m "$(cat <<'EOF'
feat: add phase 3 — stack selection or init

`pulumi stack ls --json` to detect; `pulumi stack select` if present,
`pulumi stack init` otherwise. On any unexpected failure we surface
Pulumi's own error verbatim — the user is better placed to resolve
e.g. an org-conflict than the wizard is.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: `configure_key()` — phase 4 orchestration

**Files:**
- Modify: `infra/setup.py`

- [ ] **Step 1: Implement `configure_key` and the phase-4 loop driver**

Append to `infra/setup.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify nothing regressed**

```bash
uv run pytest -v
```

Expected: 23 tests still PASS.

- [ ] **Step 3: Commit**

```bash
git add infra/setup.py
git commit -m "$(cat <<'EOF'
feat: add phase 4 — config-key walk with k/r/s and validation retries

configure_key loops over CONFIG_KEYS. For each: pulumi config get to
detect existing, ask k/r/s if so, otherwise prompt and (optionally)
validate. InvalidToken re-prompts up to 3 times before aborting;
NetworkError prints a warning and accepts. Captured `pulumi config get`
plaintext is used only for the set/unset branch — never echoed.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: `print_next_steps()` and `main()` wiring

**Files:**
- Modify: `infra/setup.py`

- [ ] **Step 1: Implement `print_next_steps` and `main`**

Append to `infra/setup.py`:

```python
def print_next_steps() -> None:
    banner("Done")
    print(green("  Stack `dev` is configured."))
    print()
    print("  Next steps (run from the `infra/` directory):")
    print(f"    {bold('pulumi preview')}    inspect the diff")
    print(f"    {bold('pulumi up')}         provision")
    print(f"    {bold('tailscale ssh claude@claude-ops')}    reach the droplet")
    print()
    print("  To graduate to a `prod` stack:")
    print("    - Pin a snapshot ID:  pulumi config set image <snap-id>")
    print("    - Consider Pulumi ESC for centrally-rotatable secrets.")
    print("    See README §Production workflow.")


def _phase5_acl(tailnet: str, tag: str = "tag:claude-ops") -> None:
    banner("Phase 5 — Tailscale ACL")
    print_acl_snippet(tailnet=tailnet, tag=tag)
    input("\n  Press enter once you've saved the ACL. ")


def main() -> int:
    try:
        banner("claude-ops setup wizard (dev stack)")
        check_prereqs()
        ensure_backend()
        ensure_stack("dev")
        configure_all_keys()
        # Pull tailnet back out of pulumi config to render the ACL snippet
        # accurately (handles the case where the user kept an existing value).
        tailnet = _get_existing("tailscale:tailnet") or "<your-tailnet>"
        _phase5_acl(tailnet=tailnet)
        print_next_steps()
        return 0
    except KeyboardInterrupt:
        print()
        print(red("  Aborted."))
        return 130
    except PulumiError as e:
        print(red(f"  pulumi failed: {e}"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run tests to verify nothing regressed**

```bash
uv run pytest -v
```

Expected: 23 tests still PASS.

- [ ] **Step 3: Manually smoke-test that the entry point launches**

Run from `infra/`:

```bash
uv run python setup.py < /dev/null || true
```

Expected: The banner prints, phase 1 prereq check runs, phase 2 starts. The script will fail or hit EOF on the first interactive prompt — that's fine; we're confirming the entry point and phase orchestration work.

(Don't worry about the non-zero exit; we just want to see the banners and prereq output before the first prompt.)

- [ ] **Step 4: Commit**

```bash
git add infra/setup.py
git commit -m "$(cat <<'EOF'
feat: wire up main() with KeyboardInterrupt and PulumiError handling

Six phases run in order. Ctrl-C → exit 130 with a red "Aborted." line.
PulumiError → exit 1 surfacing the failed command. Phase 5 reads
tailscale:tailnet back from pulumi config so the ACL snippet uses the
correct value even when the user kept an existing one in phase 4.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Update `README.md` with Quick setup section

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Insert the new section**

Open `README.md`. Find the heading `## One-time setup` (around line 56) and the heading `## Development workflow` (around line 73). Insert this new section *between* them — after the closing of the One-time setup code block and before the `## Development workflow` heading:

```markdown
## Quick setup (interactive)

For a guided walk-through that prompts for everything `pulumi up` needs:

```bash
cd infra
uv run python setup.py
```

This sets the four required config keys, validates the DigitalOcean token
(catching a wrong PAT before it costs you a `pulumi up` round-trip),
and prints the Tailscale ACL snippet you'll need to paste into your tailnet
policy. Re-runnable — already-set keys can be kept, replaced, or skipped.

For manual setup, follow "Development workflow" below.
```

- [ ] **Step 2: Verify the rendered markdown is sane**

Run from repo root:

```bash
sed -n '50,90p' README.md
```

Expected: "One-time setup" → its code block → blank line → "## Quick setup (interactive)" with prose and code → blank line → "## Development workflow". No broken nesting.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs: add Quick setup section pointing to the interactive wizard

Slotted between One-time setup and Development workflow. Manual flow
remains documented verbatim — the wizard is additive.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Final test run + manual end-to-end smoke

**Files:**
- None (verification task)

- [ ] **Step 1: Full test run**

Run from `infra/`:

```bash
uv run pytest -v
```

Expected: 23 tests PASS. Total runtime under 5 seconds.

- [ ] **Step 2: Verify the wizard launches cleanly**

Run from `infra/`:

```bash
uv run python setup.py < /dev/null || true
```

Expected output prefix (exact wording may differ slightly):
```
─────────────────────────────────────
  claude-ops setup wizard (dev stack)
─────────────────────────────────────
─────────────────────────────────────
  Phase 1 — Checking prerequisites
─────────────────────────────────────
  ✓ pulumi
  ✓ tailscale
─────────────────────────────────────
  Phase 2 — Pulumi backend
─────────────────────────────────────
```

The script will then either print "Logged in as ..." (if the user happens to have `pulumi whoami` working) or hit EOF on the cloud/local prompt and exit. Either is fine — we've verified phases 1 and 2 launch.

- [ ] **Step 3: Verify `pulumi preview` is unaffected**

If the user has an existing `dev` stack with valid config, run from `infra/`:

```bash
pulumi preview
```

Expected: same diff as before — the wizard does not touch the Pulumi program (`__main__.py`, etc.), only `Pulumi.dev.yaml`.

If there's no working stack, skip this step — it's a sanity check, not a gate.

- [ ] **Step 4: Final summary commit (if any docs were tweaked during smoke)**

If steps 1-3 didn't surface any issues, no commit needed. If you fixed something small (typo, off-by-one in a banner), commit it as `chore:` with a one-line subject.

- [ ] **Step 5: Done**

The wizard is implemented, tested, and documented. The plan's terminal state is reached.

---

## Self-review

**Spec coverage:**

| Spec section | Implementing task(s) |
|---|---|
| File location & invocation (`infra/setup.py`, `uv run python`) | 2 (creates the file), 11 (entry point) |
| Stdlib only at runtime | 1 (only pytest is added, dev-only), 2-11 (no runtime imports outside stdlib) |
| Phase 1 — prereqs | 7 |
| Phase 2 — backend (cloud + local with passphrase echo) | 8 |
| Phase 3 — stack | 9 |
| Phase 4 — config keys with k/r/s + validation | 4 (helpers), 10 (orchestration) |
| Phase 5 — ACL handoff | 5 (snippet), 11 (`_phase5_acl` wiring) |
| Phase 6 — done + prod hint | 11 |
| `ConfigKey` dataclass + `CONFIG_KEYS` | 2, 3 (validator wired) |
| `run_pulumi()` capture-vs-stream | 6 |
| `validate_do_token` 401 vs network | 3 |
| Error handling table cases | 6 (`PulumiError`), 7 (pulumi missing), 8 (login failures), 10 (401 retries), 11 (Ctrl-C, PulumiError) |
| Test files | 1 (scaffold), 2-5 (tests added) |
| README change | 12 |

All spec items covered.

**Placeholder scan:** No "TBD" / "TODO" / "implement later" / "similar to Task N" appears in the plan. Each task contains the actual code or commands needed.

**Type consistency:**
- `ConfigKey(key, label, secret, validator)` — same signature in tasks 2, 3, 4, 5, 10.
- `validate_do_token(token: str) -> None` — task 3 defines, task 3 also wires into CONFIG_KEYS.
- `ask_krs(key, masked_existing) -> str` returning `"keep"|"replace"|"skip"` — task 4 defines, task 10 calls.
- `mask_secret(value) -> str` — task 4 defines, task 10 calls.
- `print_acl_snippet(tailnet, tag)` — task 5 defines, task 11 calls (via `_phase5_acl`).
- `run_pulumi(*args, capture=False, check=True)` — task 6 defines, tasks 8/9/10 call.
- `prompt(label, *, secret=False)` — task 6 defines, tasks 8/10 call.
- Exceptions: `InvalidToken`, `NetworkError`, `PulumiError` — defined in tasks 3, 3, 6 respectively; caught in tasks 10, 10, 11.

All consistent.
