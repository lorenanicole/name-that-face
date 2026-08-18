"""Tests for Streamlit client configuration setup."""

import os
from unittest.mock import patch

import pytest


@pytest.mark.unit
def test_setup_returns_config_dict_with_required_keys(monkeypatch):
    """Setup returns a properly structured config dictionary with all required keys."""
    # Clear env to test defaults
    monkeypatch.delenv("API_BASE_URL", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("USER_ID", raising=False)
    monkeypatch.delenv("USERNAME", raising=False)

    from src.client import setup

    config = setup()

    assert isinstance(config, dict)
    assert "BASE_URL" in config
    assert "JWT_SECRET" in config
    assert "JWT_ALGORITHM" in config
    assert "USER_ID" in config
    assert "USERNAME" in config
    assert "PAYLOAD" in config
    assert isinstance(config["PAYLOAD"], dict)
    assert "name" in config["PAYLOAD"]
    assert "email" in config["PAYLOAD"]
    assert "age" in config["PAYLOAD"]


def test_setup_returns_config_dict():
    """Setup returns a properly structured config dictionary."""
    from src.client import setup

    config = setup()

    assert isinstance(config, dict)
    assert "BASE_URL" in config
    assert "JWT_SECRET" in config
    assert "JWT_ALGORITHM" in config
    assert "USER_ID" in config
    assert "USERNAME" in config
    assert "PAYLOAD" in config
    assert isinstance(config["PAYLOAD"], dict)
    assert "name" in config["PAYLOAD"]
    assert "email" in config["PAYLOAD"]
    assert "age" in config["PAYLOAD"]


def test_setup_payload_age_is_int():
    """Setup correctly converts USER_AGE to integer in payload."""
    with patch.dict(os.environ, {"USER_AGE": "42"}, clear=False):
        from src.client import setup

        config = setup()

        assert isinstance(config["PAYLOAD"]["age"], int)
        assert config["PAYLOAD"]["age"] == 42


@pytest.mark.unit
def test_client_module_calls_setup_on_import():
    """Client module calls setup() when imported."""
    import sys

    if "src.client" in sys.modules:
        del sys.modules["src.client"]

    # Import should trigger setup
    from src import client

    assert hasattr(client, "BASE_URL")
    assert hasattr(client, "JWT_SECRET")
    assert hasattr(client, "PAYLOAD")
    assert client.BASE_URL is not None
