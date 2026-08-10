"""
tests/integration/test_api_auth.py

Integration tests for JWT + rate-limit auth on GET /api/user and POST /api/user.
No real Duo, no real DeepFace.
"""

import pytest


@pytest.mark.integration
async def test_get_user_valid_read_token(client, read_token):
    ac, _ = client
    resp = await ac.get("/api/user/u1", headers={"Authorization": f"Bearer {read_token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == "u1"
    assert data["token_scope"] == "user:read"
    assert data["step_up"] is False


@pytest.mark.integration
async def test_get_user_missing_token_returns_401(client):
    ac, _ = client
    resp = await ac.get("/api/user/u1")
    assert resp.status_code == 401


@pytest.mark.integration
async def test_get_user_wrong_scope_returns_401(client, elevated_token):
    # elevated_token has scope user:write — not user:read
    ac, _ = client
    resp = await ac.get("/api/user/u1", headers={"Authorization": f"Bearer {elevated_token}"})
    assert resp.status_code == 401


@pytest.mark.integration
async def test_get_user_expired_token_returns_401(client, expired_token):
    ac, _ = client
    resp = await ac.get("/api/user/u1", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code == 401


@pytest.mark.integration
async def test_post_user_without_step_up_redirects_307(client, write_token):
    """A write-scope token without step_up=True must trigger a 307 to /login-2fa."""
    ac, _ = client
    resp = await ac.post(
        "/api/user/u1",
        json={"name": "Test User"},
        headers={"Authorization": f"Bearer {write_token}"},
        follow_redirects=False,
    )
    assert resp.status_code == 307
    assert "/login-2fa?challenge=" in resp.headers["location"]


@pytest.mark.integration
async def test_post_user_with_step_up_returns_200(client, elevated_token):
    ac, _ = client
    resp = await ac.post(
        "/api/user/u1",
        json={"name": "Test User", "email": "test@example.com", "age": 25},
        headers={"Authorization": f"Bearer {elevated_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Test User"


@pytest.mark.integration
async def test_post_user_invalid_body_returns_422(client, elevated_token):
    ac, _ = client
    resp = await ac.post(
        "/api/user/u1",
        json={"name": "Alice", "age": -5},  # negative age
        headers={"Authorization": f"Bearer {elevated_token}"},
    )
    assert resp.status_code == 422
