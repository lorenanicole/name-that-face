"""
tests/unit/test_token_service.py

Unit tests for TokenService — JWT issue, validate, refresh, step-up challenge.
All tests use an isolated TokenService wired to a minimal fake TokenConfig so
they never touch config.yml, the database, or Duo.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest

from token_service import TokenError, TokenService

SECRET = "unit-test-secret"
ALGORITHM = "HS256"


@pytest.fixture
def fake_token_config():
    cfg = MagicMock()
    cfg.token_permissions = {
        "user": {
            "daily_token_budget": 100_000,
            "read": {"cost_min": 100, "cost_max": 300, "rpm": 60},
            "write": {"cost_min": 150, "cost_max": 500, "rpm": 20},
        }
    }
    cfg.get_scope_config.return_value = {"cost_min": 100, "cost_max": 300, "rpm": 60}
    return cfg


@pytest.fixture
def svc(fake_token_config, monkeypatch):
    """TokenService with a fixed secret so JWTs are deterministic."""
    monkeypatch.setattr("token_service.SECRET_KEY", SECRET)
    monkeypatch.setattr("token_service.ALGORITHM", ALGORITHM)
    return TokenService(fake_token_config)


# ---------------------------------------------------------------------------
# issue
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_issue_returns_valid_jwt(svc):
    token = svc.issue(user_id="u1", scope="user:read")
    claims = pyjwt.decode(token, SECRET, algorithms=[ALGORITHM])
    assert claims["sub"] == "u1"
    assert claims["scope"] == "user:read"
    assert claims["step_up"] is False


@pytest.mark.unit
def test_issue_step_up_flag(svc):
    token = svc.issue(user_id="u1", scope="user:write", step_up=True)
    claims = pyjwt.decode(token, SECRET, algorithms=[ALGORITHM])
    assert claims["step_up"] is True


@pytest.mark.unit
def test_issue_includes_username(svc):
    token = svc.issue(user_id="u1", scope="user:read", username="alice@example.com")
    claims = pyjwt.decode(token, SECRET, algorithms=[ALGORITHM])
    assert claims["username"] == "alice@example.com"


# ---------------------------------------------------------------------------
# validate_token
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_validate_token_valid(svc):
    token = svc.issue(user_id="u1", scope="user:read")
    claims = svc.validate_token(token, required_scope="user:read")
    assert claims["sub"] == "u1"


@pytest.mark.unit
def test_validate_token_wrong_scope_raises(svc):
    token = svc.issue(user_id="u1", scope="user:read")
    with pytest.raises(TokenError, match="does not permit"):
        svc.validate_token(token, required_scope="user:write")


@pytest.mark.unit
def test_validate_token_bad_signature_raises(svc):
    token = pyjwt.encode(
        {
            "sub": "u1",
            "scope": "user:read",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        "wrong-secret",
        algorithm=ALGORITHM,
    )
    with pytest.raises(TokenError, match="Invalid token"):
        svc.validate_token(token, required_scope="user:read")


@pytest.mark.unit
def test_validate_token_expired_raises(svc):
    token = pyjwt.encode(
        {
            "sub": "u1",
            "scope": "user:read",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
        SECRET,
        algorithm=ALGORITHM,
    )
    with pytest.raises(TokenError, match="[Ee]xpir"):
        svc.validate_token(token, required_scope="user:read")


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_refresh_extends_expiry(svc):
    original = svc.issue(user_id="u1", scope="user:read")
    refreshed = svc.refresh(original)
    orig_exp = pyjwt.decode(original, SECRET, algorithms=[ALGORITHM])["exp"]
    new_exp = pyjwt.decode(refreshed, SECRET, algorithms=[ALGORITHM])["exp"]
    assert new_exp >= orig_exp


@pytest.mark.unit
def test_refresh_invalid_token_raises(svc):
    with pytest.raises(TokenError, match="Invalid token"):
        svc.refresh("not.a.token")


# ---------------------------------------------------------------------------
# step-up challenge
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_issue_and_decode_step_up_challenge(svc):
    claims = {"sub": "u1", "username": "alice@example.com", "scope": "user:write"}
    challenge = svc.issue_step_up_challenge(
        claims,
        required_scope="user:write",
        client_ip="127.0.0.1",
        next_url="http://localhost/api/user/u1",
    )
    decoded = svc.decode_step_up_challenge(challenge)
    assert decoded["typ"] == "step_up_challenge"
    assert decoded["sub"] == "u1"
    assert decoded["required_scope"] == "user:write"
    assert decoded["next"] == "http://localhost/api/user/u1"


@pytest.mark.unit
def test_decode_non_challenge_token_raises(svc):
    regular = svc.issue(user_id="u1", scope="user:read")
    with pytest.raises(TokenError, match="Not a challenge token"):
        svc.decode_step_up_challenge(regular)


@pytest.mark.unit
def test_decode_expired_challenge_raises(svc, monkeypatch):
    # Issue a challenge then backdate its expiry
    claims = {"sub": "u1", "username": "alice", "scope": "user:write"}
    challenge = svc.issue_step_up_challenge(claims, "user:write", "127.0.0.1", "http://x")
    payload = pyjwt.decode(challenge, SECRET, algorithms=[ALGORITHM])
    payload["exp"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    expired = pyjwt.encode(payload, SECRET, algorithm=ALGORITHM)
    with pytest.raises(TokenError, match="[Ee]xpir"):
        svc.decode_step_up_challenge(expired)
