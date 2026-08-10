import math
from pathlib import Path
from typing import Any, Dict

import yaml
from pydantic_settings import BaseSettings

# Default config path: config/config.yml relative to this file's package root
_DEFAULT_CONFIG_PATH = str(Path(__file__).parent.parent / "config" / "config.yml")


# ---------------------------------------------------------------------------
# Application settings (loaded from environment variables / .env file)
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """Core application settings sourced from environment variables."""

    SECRET_KEY: str = "replace-me-with-a-real-secret-in-env"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    DUO_INTEGRATION_KEY: str = ""
    DUO_SECRET_KEY: str = ""
    DUO_API_HOST: str = ""

    # Path to the token config YAML (can be overridden via env var)
    TOKEN_CONFIG_PATH: str = _DEFAULT_CONFIG_PATH

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# ---------------------------------------------------------------------------
# Token configuration (loaded from config.yml)
# ---------------------------------------------------------------------------


class TokenConfig:
    """
    Loads config.yml and exposes token permissions with rate-limit details.

    The structure mirrors what rate_limiter.py builds in its __main__ block:

        {
            "user": {
                "daily_token_budget": 100000,
                "read":  {"cost_min": 100, "cost_max": 300, "rpm": 60},
                "write": {"cost_min": 150, "cost_max": 500, "rpm": 20},
                ...
            },
            "m2m": { ... },
            "admin": { ... },
        }
    """

    def __init__(self, config_path: str) -> None:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Token config file not found: {path}")

        with open(path, "r") as f:
            self._raw: Dict[str, Any] = yaml.safe_load(f)

        self.token_permissions: Dict[str, Any] = self._build_token_permissions()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_token_permissions(self) -> Dict[str, Any]:
        """
        Convert the raw YAML token_types section into the flat structure
        used by TokenBucketRateLimiter (see rate_limiter.py __main__).
        """
        return {
            token_type: {
                "daily_token_budget": type_data["daily_token_budget"],
                **{
                    scope: {
                        "cost_min": scope_data["token_cost_base"],
                        "cost_max": scope_data["token_cost_max"],
                        "rpm": scope_data["rate_limit_per_minute"],
                    }
                    for scope, scope_data in type_data.get("scopes", {}).items()
                },
            }
            for token_type, type_data in self._raw.get("token_types", {}).items()
        }

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    def get_scope_config(self, token_type: str, scope: str) -> Dict[str, Any]:
        """Return the cost/rpm config for a specific token_type + scope."""
        type_cfg = self.token_permissions.get(token_type, {})
        scope_cfg = type_cfg.get(scope)
        if scope_cfg is None:
            raise KeyError(f"No config found for token_type={token_type!r}, scope={scope!r}")
        return scope_cfg

    def tokens_needed(self, token_type: str, scope: str, token_cost: int) -> int:
        """
        Calculate how many base-unit slots a request of `token_cost` needs.

        Mirrors the calculation in rate_limiter.py __main__:
            tokens_needed = ceil(token_cost / cost_min)
        """
        scope_cfg = self.get_scope_config(token_type, scope)
        return math.ceil(token_cost / scope_cfg["cost_min"])

    @property
    def raw(self) -> Dict[str, Any]:
        """The full parsed YAML document."""
        return self._raw
