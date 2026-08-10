"""
dependencies.py — singleton wiring for the rate limiter app.

All shared instances are created here in dependency order and imported
wherever needed. Nothing else should call TokenConfig() or TokenService().

Import pattern:
    from dependencies import token_config, token_service, fraud_service
"""

import duo_client

# Configure structlog/stdlib logging before anything else imports logging
import logging_config

logging_config.configure()

from fraud_detection_service import FraudDetectionService  # noqa: E402
from settings import Settings, TokenConfig  # noqa: E402
from token_service import TokenService  # noqa: E402

# 1. App settings (env vars / .env)
settings = Settings()

# 2. Token config (parsed from config.yml)
token_config = TokenConfig(settings.TOKEN_CONFIG_PATH)

# 3. Token service (depends on token_config)
token_service = TokenService(token_config)

# 4. Duo Auth
duo_auth = duo_client.Auth(
    ikey=settings.DUO_INTEGRATION_KEY, skey=settings.DUO_SECRET_KEY, host=settings.DUO_API_HOST
)

# 5. Fraud detection service
fraud_service = FraudDetectionService()
