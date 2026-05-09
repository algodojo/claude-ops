# claude-ops

Provision a remote [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) workstation on a DigitalOcean droplet, reachable **only** over your Tailscale tailnet. One `pulumi up` produces a hardened VM with no public ingress — Claude Code runs there, you reach it via `tailscale ssh`.

The infrastructure is Pulumi (Python) and the bring-up is `cloud-init`. Security posture is documented in [`AGENTS.md`](./AGENTS.md); read it before changing anything network- or secrets-related.

## What you get

- A DigitalOcean droplet in a dedicated VPC, attached to a default-deny cloud firewall (empty `inbound_rules`).
- A `claude` user (sudoer, key-locked, no password), Node.js LTS, and `@anthropic-ai/claude-code` pre-installed.
- An ephemeral, single-use, pre-authorized, tagged Tailscale node — tailnet entry vanishes when the droplet shuts down.
- Unattended security upgrades with a 03:30 reboot window.
- Hardened `sshd` (no root, no password, `claude` only), with Tailscale SSH as the primary entry point.

## Prerequisites

Install on your local machine:

| Tool | Why | Install |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | Manages Python and the Pulumi program's lockfile. | `brew install uv` (or [other methods](https://docs.astral.sh/uv/getting-started/installation/)) |
| [Pulumi CLI](https://www.pulumi.com/docs/install/) | Runs the IaC. | `brew install pulumi/tap/pulumi` |
| [Tailscale](https://tailscale.com/download) (on your client) | You need a tailnet to reach the droplet. | platform-specific |

You'll also need accounts and credentials for:

- **DigitalOcean** — a [Personal Access Token](https://cloud.digitalocean.com/account/api/tokens) with read/write scope.
- **Tailscale** — an [OAuth client](https://login.tailscale.com/admin/settings/oauth) with the `auth_keys` scope, plus an ACL tag (default `tag:claude-ops`) declared in your tailnet policy and owned by that OAuth client.
- **Pulumi backend** — Pulumi Cloud (free for individuals) or a self-managed encrypted backend. Per `AGENTS.md` hard rule #7, state must be encrypted at rest.

### Tailscale ACL — minimal example

In your tailnet policy, declare the tag and grant your user account access to it:

```jsonc
{
  "tagOwners": {
    "tag:claude-ops": ["autogroup:admin"]
  },
  "acls": [
    { "action": "accept", "src": ["your-email@example.com"], "dst": ["tag:claude-ops:*"] }
  ],
  "ssh": [
    {
      "action": "accept",
      "src": ["your-email@example.com"],
      "dst": ["tag:claude-ops"],
      "users":  ["claude"]
    }
  ]
}
```

Adjust `src` to the principals you actually want to grant.

## One-time setup

```bash
git clone <this-repo> claude-ops
cd claude-ops/infra

# Install Python (per .python-version) and the locked dependency tree.
# `--frozen` enforces uv.lock; never run `pip install` directly.
uv sync --frozen

# Pick a Pulumi backend. Pulumi Cloud:
pulumi login
# ...or a self-managed encrypted backend (example: local with passphrase):
#   export PULUMI_CONFIG_PASSPHRASE='<a-strong-passphrase>'
#   pulumi login --local
```

## Development workflow

A `dev` stack is for iterating on the IaC against a real (but disposable) droplet.

```bash
cd infra
pulumi stack init dev

# Required secrets — stored encrypted in Pulumi.dev.yaml.
pulumi config set --secret digitalocean:token            "$DIGITALOCEAN_TOKEN"
pulumi config set --secret tailscale:oauth_client_id     "$TS_OAUTH_CLIENT_ID"
pulumi config set --secret tailscale:oauth_client_secret "$TS_OAUTH_CLIENT_SECRET"
pulumi config set          tailscale:tailnet             "$YOUR_TAILNET"  # e.g. example.com or tail-scales.ts.net

# Optional overrides (defaults shown):
# pulumi config set region        nyc3
# pulumi config set droplet_size  s-2vcpu-4gb
# pulumi config set image         ubuntu-24-04-x64
# pulumi config set droplet_name  claude-ops
# pulumi config set tailscale_tag tag:claude-ops

pulumi preview            # inspect the diff
pulumi up                 # provision

# Reach the box. Run from a tailnet-joined device:
tailscale ssh claude@claude-ops

# When you're done iterating:
pulumi destroy
```

Cloud-init runs only on first boot, so changing `user_data`, `image`, or `size` triggers a droplet replacement (`replace_on_changes` is set in `infra/digitalocean_resources.py`). Expect a new public-IP window during replacement.

### Iterating on cloud-init quickly

The fastest dev loop is `pulumi up` → `tailscale ssh` → check → `pulumi destroy`. To inspect what cloud-init actually did on the droplet:

```bash
tailscale ssh claude@claude-ops
sudo cloud-init status --long
sudo journalctl -u cloud-final --no-pager
```

## Production workflow

A `prod` stack is the same program with stricter inputs and tighter ops hygiene.

```bash
cd infra
pulumi stack init prod

# Same config keys as dev, but consider managing secrets through Pulumi ESC
# (https://www.pulumi.com/docs/esc/) so they're centrally rotatable rather
# than duplicated per-stack.

# Pin to a snapshot you control rather than the floating Ubuntu slug, so
# bring-up is bit-for-bit reproducible (AGENTS.md "Strong preferences").
# Create the snapshot in the DO console from a known-good image, then:
pulumi config set image <snapshot-id>

pulumi preview
pulumi up
```

After any production `up`, run the verification checklist in `AGENTS.md` — at minimum:

```bash
# From a device that is NOT on your tailnet, against the exported public IPv4:
nmap -Pn $(pulumi -C infra stack output droplet_public_ipv4)
# Expected: no `open` ports.

# From the droplet, via tailnet:
tailscale ssh claude@claude-ops -- ss -tlnp
# Expected: listeners only on 127.0.0.1 or tailscale0, never 0.0.0.0.

tailscale ssh claude@claude-ops -- tailscale status
# Expected: tagged tag:claude-ops, online.
```

## Using Claude Code on the droplet

```bash
tailscale ssh claude@claude-ops
claude            # first run will prompt you to authenticate
```

Per `AGENTS.md`, treat the droplet as disposable: anything Claude Code writes that you want to keep should be pushed to a git remote or otherwise persisted off the droplet, because `pulumi destroy` (or a replacement triggered by an `image`/`size`/`user_data` change) wipes it.

## Teardown

```bash
cd infra
pulumi destroy        # removes droplet, VPC, firewall, project membership, tailnet auth key
pulumi stack rm dev   # only after destroy succeeds
```

The ephemeral tailnet node entry should disappear on its own when the droplet powers off; if it lingers, remove it from the Tailscale admin console.

## Repository layout

```
infra/                       Pulumi Python program (run all pulumi commands from here)
  __main__.py                entry point — wires the three modules below
  tailscale_resources.py     mints the ephemeral, single-use auth key
  cloud_init.py              renders user-data while preserving secret redaction
  digitalocean_resources.py  VPC + droplet + default-deny firewall + project
  pyproject.toml, uv.lock    dependencies (both committed, both reviewed)
cloud-init/
  user-data.yaml.j2          first-boot bootstrap (Tailscale, Node.js, Claude Code, sshd hardening)
AGENTS.md                    security contract — read before any infra change
```

## License

See [LICENSE](./LICENSE).
