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
