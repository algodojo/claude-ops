"""Unit tests for pure parts of setup.py."""

from setup import CONFIG_KEYS, ConfigKey, ask_krs, mask_secret


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
