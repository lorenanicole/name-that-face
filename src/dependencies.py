"""
dependencies.py — singleton wiring for the rate limiter app.

All shared instances are created here in dependency order and imported
wherever needed. Nothing else should call TokenConfig() or TokenService().

Import pattern:
    from dependencies import token_config, token_service, fraud_service
"""

import duo_client

import logging_config
from fraud_detection_service import FraudDetectionService  # noqa: E402
from settings import Settings, TokenConfig  # noqa: E402
from token_service import TokenService  # noqa: E402

# Lazy-load singletons to support test isolation
_singletons = {
    "settings": None,
    "token_config": None,
    "token_service": None,
    "duo_auth": None,
    "fraud_service": None,
}


def _init_singletons():
    """Initialize all singletons (lazy-loaded for test isolation)."""
    if _singletons["settings"] is None:
        _singletons["settings"] = Settings()
        logging_config.configure(audit_log_path=_singletons["settings"].AUDIT_LOG_PATH)
        _singletons["token_config"] = TokenConfig(_singletons["settings"].TOKEN_CONFIG_PATH)
        _singletons["token_service"] = TokenService(_singletons["token_config"])
        _singletons["duo_auth"] = duo_client.Auth(
            ikey=_singletons["settings"].DUO_INTEGRATION_KEY,
            skey=_singletons["settings"].DUO_SECRET_KEY,
            host=_singletons["settings"].DUO_API_HOST,
        )
        _singletons["fraud_service"] = FraudDetectionService()


def __getattr__(name):
    """Lazy-load singletons on first access."""
    if name in _singletons:
        _init_singletons()
        return _singletons[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
