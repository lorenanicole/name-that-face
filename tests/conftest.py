"""
tests/conftest.py — shared fixtures available to all test suites.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

SECRET = "test-secret-key"
ALGORITHM = "HS256"


def make_jwt(
    user_id: str = "u1",
    username: str = "test@example.com",
    scope: str = "user:read",
    step_up: bool = False,
    secret: str = SECRET,
    expires_delta: timedelta = timedelta(minutes=30),
) -> str:
    """Return a signed JWT suitable for test requests."""
    payload = {
        "sub": user_id,
        "username": username,
        "scope": scope,
        "step_up": step_up,
        "exp": datetime.now(timezone.utc) + expires_delta,
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


@pytest.fixture
def valid_read_token() -> str:
    return make_jwt(scope="user:read")


@pytest.fixture
def valid_write_token() -> str:
    return make_jwt(scope="user:write", step_up=False)


@pytest.fixture
def elevated_write_token() -> str:
    return make_jwt(scope="user:write", step_up=True)


@pytest.fixture
def admin_token() -> str:
    return make_jwt(scope="admin:admin", step_up=True)


@pytest.fixture
def expired_token() -> str:
    return make_jwt(expires_delta=timedelta(seconds=-1))
