"""Render cloud-init user-data while preserving Pulumi secret redaction."""

from pathlib import Path

import pulumi
from jinja2 import Environment, FileSystemLoader

# cloud-init/ lives at the repo root; this module sits in infra/.
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "cloud-init"
_TEMPLATE_NAME = "user-data.yaml.j2"
_AUTHKEY_PLACEHOLDER = "__TAILSCALE_AUTH_KEY__"


def render_user_data(
    *,
    droplet_name: str,
    tailscale_auth_key: pulumi.Input[str],
    tailscale_tag: str,
) -> pulumi.Output[str]:
    """
    Render cloud-init with non-secret values via Jinja, then thread the
    Tailscale auth key in via `pulumi.Output.concat`.

    Why two stages: Jinja's `render()` only accepts plain strings. Passing a
    `pulumi.Output[str]` to it would force an `.apply()` and the resulting
    user-data string would no longer be marked as a Pulumi secret — it would
    appear in plaintext in `pulumi up` output, state, and any log capture.
    Rendering with a sentinel placeholder first and then substituting via
    `Output.concat` keeps the secret marker intact end-to-end.
    """
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=False,  # YAML is not HTML; autoescape would corrupt it
        keep_trailing_newline=True,
    )
    template = env.get_template(_TEMPLATE_NAME)
    rendered = template.render(
        droplet_name=droplet_name,
        tailscale_tag=tailscale_tag,
        tailscale_auth_key=_AUTHKEY_PLACEHOLDER,
    )

    parts = rendered.split(_AUTHKEY_PLACEHOLDER)
    if len(parts) != 2:
        raise ValueError(
            "cloud-init template must contain exactly one "
            "{{ tailscale_auth_key }} reference; "
            f"found {len(parts) - 1}"
        )
    return pulumi.Output.concat(parts[0], tailscale_auth_key, parts[1])
