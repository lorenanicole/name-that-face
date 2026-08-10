"""
tests/unit/test_settings.py

Unit tests for TokenConfig YAML loading and tokens_needed calculation.
Uses a real (small) YAML fixture — no network, no env vars.
"""

import textwrap
from pathlib import Path

import pytest

from settings import TokenConfig

MINIMAL_CONFIG = textwrap.dedent("""\
    token_types:
      user:
        daily_token_budget: 100000
        scopes:
          read:
            token_cost_base: 100
            token_cost_max: 300
            rate_limit_per_minute: 60
          write:
            token_cost_base: 150
            token_cost_max: 500
            rate_limit_per_minute: 20
      admin:
        daily_token_budget: 500000
        scopes:
          admin:
            token_cost_base: 200
            token_cost_max: 1000
            rate_limit_per_minute: 30
""")


@pytest.fixture
def config_file(tmp_path) -> Path:
    p = tmp_path / "config.yml"
    p.write_text(MINIMAL_CONFIG)
    return p


@pytest.fixture
def cfg(config_file) -> TokenConfig:
    return TokenConfig(str(config_file))


@pytest.mark.unit
def test_token_config_loads_user_budget(cfg):
    assert cfg.token_permissions["user"]["daily_token_budget"] == 100_000


@pytest.mark.unit
def test_token_config_loads_user_read_scope(cfg):
    scope = cfg.token_permissions["user"]["read"]
    assert scope["cost_min"] == 100
    assert scope["cost_max"] == 300
    assert scope["rpm"] == 60


@pytest.mark.unit
def test_token_config_loads_admin_scope(cfg):
    scope = cfg.token_permissions["admin"]["admin"]
    assert scope["rpm"] == 30


@pytest.mark.unit
def test_get_scope_config_returns_correct_data(cfg):
    scope = cfg.get_scope_config("user", "write")
    assert scope["cost_min"] == 150
    assert scope["rpm"] == 20


@pytest.mark.unit
def test_get_scope_config_unknown_scope_raises(cfg):
    with pytest.raises(KeyError):
        cfg.get_scope_config("user", "nonexistent")


@pytest.mark.unit
def test_tokens_needed_exact_multiple(cfg):
    # cost 200, cost_min 100 → ceil(200/100) = 2
    assert cfg.tokens_needed("user", "read", token_cost=200) == 2


@pytest.mark.unit
def test_tokens_needed_rounds_up(cfg):
    # cost 250, cost_min 100 → ceil(2.5) = 3
    assert cfg.tokens_needed("user", "read", token_cost=250) == 3


@pytest.mark.unit
def test_tokens_needed_minimum_is_one(cfg):
    # cost 1 (< cost_min 100) → ceil(0.01) = 1
    assert cfg.tokens_needed("user", "read", token_cost=1) == 1


@pytest.mark.unit
def test_config_file_not_found_raises():
    with pytest.raises(FileNotFoundError):
        TokenConfig("/nonexistent/path/config.yml")


@pytest.mark.unit
def test_raw_property_returns_dict(cfg):
    assert isinstance(cfg.raw, dict)
    assert "token_types" in cfg.raw
