"""
tests/integration/test_api_2fa.py

Integration tests for POST /login-2fa.
Duo is mocked at the dependency level — no real push sent.
"""

from unittest.mock import MagicMock, patch

import jwt
import pytest

from settings import Settings

_settings = Settings()
SECRET = _settings.SECRET_KEY
ALGORITHM = _settings.ALGORITHM


def _extract_challenge_and_ip(location_header: str):
    """Extract challenge token from redirect location and decode to get bound client_ip."""
    challenge = location_header.split("challenge=")[-1].split("&")[0]
    try:
        decoded = jwt.decode(challenge, SECRET, algorithms=[ALGORITHM])
        client_ip = decoded.get("client_ip", "127.0.0.1")
    except Exception:
        client_ip = "127.0.0.1"  # fallback
    return challenge, client_ip


@pytest.mark.integration
async def test_login_2fa_approved_returns_elevated_token(client, write_token, mock_duo):
    ac, _ = client
    # Step 1: get challenge
    resp = await ac.post(
        "/api/user/u1",
        json={"name": "X"},
        headers={"Authorization": f"Bearer {write_token}"},
        follow_redirects=False,
    )
    assert resp.status_code == 307, f"Expected 307, got {resp.status_code}: {resp.text}"
    challenge, client_ip = _extract_challenge_and_ip(resp.headers["location"])

    # Step 2: complete 2FA (mock_duo already returns allow)
    resp2 = await ac.post("/login-2fa", json={"challenge": challenge, "client_ip": client_ip})
    assert resp2.status_code == 200
    data = resp2.json()
    assert "elevated_token" in data
    assert "redirect_to" in data


@pytest.mark.integration
async def test_login_2fa_denied_returns_401(client, write_token):
    ac, _ = client
    resp = await ac.post(
        "/api/user/u1",
        json={"name": "X"},
        headers={"Authorization": f"Bearer {write_token}"},
        follow_redirects=False,
    )
    assert resp.status_code == 307, f"Expected 307, got {resp.status_code}: {resp.text}"
    challenge, client_ip = _extract_challenge_and_ip(resp.headers["location"])

    denied_duo = MagicMock()
    denied_duo.auth.return_value = {"result": "deny", "status_msg": "Denied"}

    with patch("app.duo_auth", denied_duo):
        resp2 = await ac.post("/login-2fa", json={"challenge": challenge, "client_ip": client_ip})
    assert resp2.status_code == 401


@pytest.mark.integration
async def test_login_2fa_invalid_challenge_returns_400(client):
    ac, _ = client
    resp = await ac.post(
        "/login-2fa", json={"challenge": "garbage.token.value", "client_ip": "127.0.0.1"}
    )
    assert resp.status_code == 400


@pytest.mark.integration
async def test_login_2fa_duo_error_returns_500(client, write_token):
    ac, _ = client
    resp = await ac.post(
        "/api/user/u1",
        json={"name": "X"},
        headers={"Authorization": f"Bearer {write_token}"},
        follow_redirects=False,
    )
    assert resp.status_code == 307, f"Expected 307, got {resp.status_code}: {resp.text}"
    challenge, client_ip = _extract_challenge_and_ip(resp.headers["location"])

    broken_duo = MagicMock()
    broken_duo.auth.side_effect = Exception("Duo API unreachable")

    with patch("app.duo_auth", broken_duo):
        resp2 = await ac.post("/login-2fa", json={"challenge": challenge, "client_ip": client_ip})
    assert resp2.status_code == 500
