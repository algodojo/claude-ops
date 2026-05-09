"""Tailscale: mint an ephemeral, single-use, pre-authorized, tagged auth key."""

import pulumi_tailscale as tailscale


def mint_tailnet_key(*, name: str, tag: str) -> tailscale.TailnetKey:
    """
    Mint a single-use Tailscale auth key for cloud-init bring-up.

    Hard rule #4 in AGENTS.md: never reuse, never bake into images, never
    commit. A new key is minted on every `pulumi up` and consumed on first
    boot. The returned `key` attribute is a Pulumi secret — keep it inside
    Output composition (Output.concat / Output.format), never .apply() it
    through a logger or string formatter.
    """
    return tailscale.TailnetKey(
        f"{name}-authkey",
        description=f"claude-ops bootstrap for {name}",
        ephemeral=True,      # tailnet entry disappears when the droplet shuts down
        preauthorized=True,  # joins without admin approval
        reusable=False,      # consumed on first use; leaked user-data can't replay
        tags=[tag],          # ACLs target the tag, never a user identity
        # Auth-key expiry in seconds. 1 hour is plenty of headroom for cloud-init
        # in the happy path. Single-use is the primary defense; expiry is a
        # fallback if cloud-init never runs.
        expiry=3600,
    )
