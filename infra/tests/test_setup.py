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
