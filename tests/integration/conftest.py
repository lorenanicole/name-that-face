"""
tests/integration/conftest.py

Shared fixtures for integration tests.

Strategy:
  - The FastAPI app is tested via httpx.AsyncClient (ASGI transport) so no
    real server port is bound.
  - duo_auth and fraud_service are patched at the app module level so no real
    Duo calls or subprocess/DeepFace calls are made.
  - JWT tokens are generated with the same SECRET_KEY the app uses so the
    rate_limit decorator accepts them.
"""

import base64
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from fraud_detection_service import FraudDetectionResult
from settings import Settings

# Read the actual SECRET_KEY from settings (which loads from .env)
_settings = Settings()
SECRET = _settings.SECRET_KEY
ALGO = "HS256"
USER_ID = "test-user-1"


def _jwt(scope: str, step_up: bool = False, exp_delta: timedelta = timedelta(minutes=30)) -> str:
    expire = datetime.now(timezone.utc) + exp_delta
    return pyjwt.encode(
        {
            "sub": USER_ID,
            "username": "test@example.com",
            "scope": scope,
            "step_up": step_up,
            "exp": int(expire.timestamp()),
        },
        SECRET,
        algorithm=ALGO,
    )


@pytest.fixture(scope="session")
def mock_duo():
    """Duo client that always approves pushes."""
    duo = MagicMock()
    duo.auth.return_value = {"result": "allow", "status": "allow", "status_msg": "Pushed"}
    return duo


@pytest.fixture(scope="session")
def mock_fraud_service_verified():
    """FraudDetectionService that always returns a verified match."""
    svc = MagicMock()
    svc.verify.return_value = FraudDetectionResult(
        verified=True,
        is_deepfake=False,
        confidence=0.75,
        distance=0.34,
        threshold=0.68,
        signals=["Face match confirmed (distance=0.340, threshold=0.680)"],
        selfie_hash="aaa",
        gov_id_hash="bbb",
    )
    return svc


@pytest_asyncio.fixture
async def client(mock_duo, mock_fraud_service_verified, tmp_path):
    """AsyncClient backed by the FastAPI ASGI app with all external calls mocked."""
    audit_log = tmp_path / "audit_log.jsonl"

    with (
        patch("dependencies.duo_auth", mock_duo),
        patch("dependencies.fraud_service", mock_fraud_service_verified),
        patch("app.duo_auth", mock_duo),
        patch("app.fraud_service", mock_fraud_service_verified),
        patch("app.AUDIT_LOG_PATH", audit_log),
    ):
        from app import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac, audit_log


# ── convenience token fixtures ────────────────────────────────────────────


@pytest.fixture
def read_token():
    return _jwt("user:read")


@pytest.fixture
def write_token():
    return _jwt("user:write", step_up=False)


@pytest.fixture
def elevated_token():
    return _jwt("user:write", step_up=True)


@pytest.fixture
def admin_token():
    return _jwt("admin:admin", step_up=True)


@pytest.fixture
def expired_token():
    return _jwt("user:read", exp_delta=timedelta(seconds=-1))


@pytest.fixture
def tiny_image_b64() -> bytes:
    """Minimal valid JPEG bytes for upload tests."""
    # 1×1 white pixel JPEG
    return base64.b64decode(
        "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8U"
        "HRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgN"
        "DRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
        "MjL/wAARCAABAAEDASIAAhEBAxEB/8QAFgABAQEAAAAAAAAAAAAAAAAABgUEA/8QABRAB"
        "AAAAAAAAAAAAAAAAAAAAAP/EABQBAQAAAAAAAAAAAAAAAAAAAAD/xAAUEQEAAAAAAAAAAAAA"
        "AAAAAAAA/9oADAMBAAIRAxEAPwCwABmX/9k="
    )
