"""
claude-ops: Pulumi entry point.

Provisions a remote Claude Code workstation on DigitalOcean, reachable only
over the user's Tailscale tailnet. Read AGENTS.md before changing anything
network- or secret-related — the hard rules in that document define the
security posture this program enforces.
"""

import pulumi

from cloud_init import render_user_data
from digitalocean_resources import provision_droplet
from tailscale_resources import mint_tailnet_key

config = pulumi.Config()
region = config.get("region") or "nyc3"
droplet_size = config.get("droplet_size") or "s-2vcpu-4gb"
# Floating slug. Per AGENTS.md "Strong preferences", pin to a snapshot ID for
# fully reproducible bring-up — the floating slug tracks minor releases.
image = config.get("image") or "ubuntu-24-04-x64"
tailscale_tag = config.get("tailscale_tag") or "tag:claude-ops"
droplet_name = config.get("droplet_name") or "claude-ops"

# Mint a fresh ephemeral, single-use, pre-authorized, tagged auth key on every
# `pulumi up` (hard rule #4 in AGENTS.md). The key value is a Pulumi secret.
tailnet_key = mint_tailnet_key(name=droplet_name, tag=tailscale_tag)

# Render cloud-init. The auth key is threaded through Output composition
# (no .apply()), so Pulumi's secret redaction stays intact through state and
# CLI output. See cloud_init.py for the why.
user_data = render_user_data(
    droplet_name=droplet_name,
    tailscale_auth_key=tailnet_key.key,
    tailscale_tag=tailscale_tag,
)

# VPC + droplet + default-deny cloud firewall + project membership.
droplet = provision_droplet(
    name=droplet_name,
    region=region,
    size=droplet_size,
    image=image,
    user_data=user_data,
)

# The public IPv4 is exported so it's easy to run the off-tailnet `nmap` check
# from the verification checklist in AGENTS.md. It is NOT meant for app
# traffic — that's what Tailscale is for.
pulumi.export("droplet_name", droplet.name)
pulumi.export("droplet_public_ipv4", droplet.ipv4_address)
pulumi.export("tailscale_ssh_command", pulumi.Output.format("tailscale ssh claude@{0}", droplet.name))
