"""DigitalOcean resources: VPC, droplet, default-deny cloud firewall, project."""

import pulumi
import pulumi_digitalocean as do


def provision_droplet(
    *,
    name: str,
    region: str,
    size: str,
    image: str,
    user_data: pulumi.Input[str],
) -> do.Droplet:
    """Provision a hardened droplet reachable only over Tailscale."""

    # Dedicated VPC isolates the droplet from the user's other DO resources.
    vpc = do.Vpc(
        f"{name}-vpc",
        name=f"{name}-vpc",
        region=region,
        ip_range="10.10.10.0/24",
    )

    droplet = do.Droplet(
        f"{name}-droplet",
        name=name,
        region=region,
        size=size,
        image=image,
        vpc_uuid=vpc.id,
        user_data=user_data,
        monitoring=True,
        ipv6=False,    # reduce attack surface; enable explicitly if needed
        backups=False, # opt-in; encrypted backups are a separate decision
        tags=["claude-ops"],
        opts=pulumi.ResourceOptions(
            # cloud-init only runs at first boot, so user_data / image / size
            # changes require a fresh droplet to actually take effect.
            # Without this, `pulumi up` would silently no-op those changes.
            replace_on_changes=["user_data", "image", "size"],
            delete_before_replace=True,
        ),
    )

    # Default-deny cloud firewall. Empty inbound_rules = block all inbound
    # at the cloud edge, before any OS firewall runs. Tailscale needs no
    # inbound (outbound-only via DERP / NAT traversal). Outbound is currently
    # permissive because cloud-init needs apt mirrors and Tailscale needs to
    # reach the control plane; tighten later if the threat model warrants.
    do.Firewall(
        f"{name}-firewall",
        name=f"{name}-firewall",
        # `.apply(int)` is acceptable here per AGENTS.md: pure type coercion
        # (DO droplet IDs are numeric but Pulumi exposes them as Output[str]),
        # no logging, no string formatting, value is not secret.
        droplet_ids=[droplet.id.apply(int)],
        inbound_rules=[],
        outbound_rules=[
            do.FirewallOutboundRuleArgs(
                protocol="tcp",
                port_range="1-65535",
                destination_addresses=["0.0.0.0/0", "::/0"],
            ),
            do.FirewallOutboundRuleArgs(
                protocol="udp",
                port_range="1-65535",
                destination_addresses=["0.0.0.0/0", "::/0"],
            ),
            do.FirewallOutboundRuleArgs(
                protocol="icmp",
                destination_addresses=["0.0.0.0/0", "::/0"],
            ),
        ],
    )

    # Group resources under a DO project so audit + teardown happen as a unit.
    # Makes it easy to spot orphaned resources during `pulumi destroy`.
    do.Project(
        f"{name}-project",
        name=name,
        description="Remote Claude Code workstations.",
        purpose="Operational / Developer tooling",
        environment="Development",
        resources=[droplet.urn],
    )

    return droplet
