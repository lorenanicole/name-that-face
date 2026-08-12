#!/usr/bin/env python3
"""
validate_2fa_flow.py

End-to-end validation script for the 2FA step-up flow.

Flow:
  1. POST /api/user/{user_id} with a non-step-up write token
     → 307 redirect with a signed challenge token in the Location header
  2. POST /login-2fa with the challenge token + client_ip
     → Real mode: Duo push sent to phone; approve within 60 seconds
     → Mock mode: auto-approved, no phone needed
     → 200 OK with { "elevated_token": "...", "redirect_to": "..." }
  3. POST redirect_to with the elevated token
     → 200 OK with the updated user data

IP Binding & Duo Location:
  The script enforces IP binding — the challenge is bound to the client IP the
  server sees, and that same IP must be used for /login-2fa.

  For localhost testing, the server sees 127.0.0.1 (loopback), which Duo cannot
  geolocate, so the push notification shows "unknown" location. This is expected
  and harmless — the security feature still works perfectly.

  To see your real location in Duo:
    • Access server via machine IP, not localhost:
      poetry run uvicorn src.app:app --host 0.0.0.0 --port 8000
      BASE_URL=http://192.168.1.100:8000 poetry run python scripts/validate_2fa_flow.py

    • Or use ngrok tunneling for a real public IP:
      ngrok http 8000
      BASE_URL=https://abc123.ngrok.io poetry run python scripts/validate_2fa_flow.py

Usage:
  # Mock-Duo mode — runs ASGI app in-process, auto-approves; no server or phone needed:
  poetry run python scripts/validate_2fa_flow.py --mock-duo

  # Real Duo demo — hits a running server at localhost:8000, sends a live push:
  poetry run python scripts/validate_2fa_flow.py

  # Override the client IP forwarded to Duo (defaults to resolved public IP):
  poetry run python scripts/validate_2fa_flow.py --client-ip 203.0.113.5
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import jwt

# Add src/ to path to import settings
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from settings import Settings

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL = "http://localhost:8000"
_settings = Settings()
JWT_SECRET = _settings.SECRET_KEY
JWT_ALGORITHM = _settings.ALGORITHM

USER_ID = "1"
USERNAME = "me@lorenamesa.com"
PAYLOAD = {"name": "Lorena Mesa", "email": "me@lorenamesa.com", "age": 39}

# Default client IP for local runs (loopback is always safe for Duo ipaddr)


# ---------------------------------------------------------------------------
# Token generation
# ---------------------------------------------------------------------------


def generate_token() -> str:
    """Issue a fresh write-scope JWT with step_up=False to trigger 2FA."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=30)
    return jwt.encode(
        {
            "sub": USER_ID,
            "username": USERNAME,
            "scope": "user:write",
            "step_up": False,
            "exp": int(expire.timestamp()),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


# ---------------------------------------------------------------------------
# Steps — transport-agnostic (work with requests.Session or httpx.Client)
# ---------------------------------------------------------------------------


def step1_get_challenge(client, token: str) -> str:
    """POST /api/user/{user_id} and extract the challenge token from the 307 redirect.

    Returns: challenge_token
    """
    print("\n--- Step 1: POST /api/user/{user_id} (step_up=False) ---")
    resp = client.post(
        f"{BASE_URL}/api/user/{USER_ID}",
        json=PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    print(f"Status: {resp.status_code}")
    if resp.status_code != 307:
        print(f"Response body: {resp.text}")
        sys.exit(f"❌ Expected 307, got {resp.status_code}")

    location = resp.headers.get("location", "")
    print(f"Location: {location}")
    challenge = location.split("challenge=")[-1].split("&")[0]
    if not challenge:
        sys.exit("❌ Challenge token not found in Location header")

    print(f"Challenge token: {challenge[:40]}...")
    return challenge


def step2_duo_push(client, challenge: str, mock: bool = False) -> tuple[str, str]:
    """POST /login-2fa with the challenge token. Server resolves IP from request."""
    print("\n--- Step 2: POST /login-2fa ---")

    if mock:
        print("⚠️  Mock mode: auto-approving Duo push...")
    else:
        print("📱 Sending Duo push to your phone — approve it now to continue...")
        print("   (waiting up to 2 minutes for push approval...)")

    resp = client.post(
        f"{BASE_URL}/login-2fa",
        json={"challenge": challenge},
    )
    print(f"Status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"Response body: {resp.text}")
        sys.exit(f"❌ Expected 200, got {resp.status_code}")

    data = resp.json()
    print("✅ Duo push approved!")
    print(f"elevated_token: {data['elevated_token'][:40]}...")
    print(f"redirect_to:    {data['redirect_to']}")
    return data["elevated_token"], data["redirect_to"]


def step3_elevated_request(client, elevated_token: str, redirect_to: str) -> dict:
    """POST redirect_to with the elevated token; expect 200 OK with user data."""
    print("\n--- Step 3: POST redirect_to with elevated token ---")
    # redirect_to may be an absolute URL; strip host so in-process client resolves correctly.
    path = redirect_to.replace(BASE_URL, "")
    url = f"{BASE_URL}{path}" if not path.startswith("http") else path
    resp = client.post(
        url,
        json=PAYLOAD,
        headers={"Authorization": f"Bearer {elevated_token}"},
    )
    print(f"Status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"Response body: {resp.text}")
        sys.exit(f"❌ Expected 200, got {resp.status_code}")

    data = resp.json()
    print(f"Response: {data}")
    return data


# ---------------------------------------------------------------------------
# Transport implementations
# ---------------------------------------------------------------------------


def _real_client():
    """
    Thin wrapper around requests.Session that disables automatic redirect
    following so step 1 can capture the raw 307 response.

    Adds a timeout to prevent hanging indefinitely on network issues,
    while still allowing up to 2 minutes for Duo phone approval.
    """
    import requests

    session = requests.Session()

    class _NoRedirectSession:
        def post(self, url, **kwargs):
            kwargs.setdefault("allow_redirects", False)
            kwargs.setdefault("timeout", 120)  # 2 min timeout for Duo approval
            return session.post(url, **kwargs)

    return _NoRedirectSession()


def _mock_duo_client():
    """
    httpx.AsyncClient backed by the FastAPI ASGI app in-process, with duo_auth
    patched to auto-approve and fraud_service patched to return a clean result.
    No running server or phone required.
    """
    import asyncio

    import httpx

    from fraud_detection_service import FraudDetectionResult

    mock_duo = MagicMock()
    mock_duo.auth.return_value = {"result": "allow", "status": "allow", "status_msg": "Pushed"}

    mock_fraud = MagicMock()
    mock_fraud.verify.return_value = FraudDetectionResult(
        verified=True,
        is_deepfake=False,
        confidence=0.95,
        distance=0.20,
        threshold=0.68,
        signals=["Face match confirmed (distance=0.200, threshold=0.680)"],
        selfie_hash="mock-selfie-hash",
        gov_id_hash="mock-gov-id-hash",
    )

    # Start patches before importing app so the module-level singletons are replaced.
    active_patches = [
        patch("dependencies.duo_auth", mock_duo),
        patch("app.duo_auth", mock_duo),
        patch("dependencies.fraud_service", mock_fraud),
        patch("app.fraud_service", mock_fraud),
    ]
    for p in active_patches:
        p.start()

    from app import app as fastapi_app

    # Wrapper to run async methods synchronously
    class SyncClient:
        def __init__(self, async_client):
            self.async_client = async_client
            self.loop = asyncio.new_event_loop()

        def post(self, url, **kwargs):
            return self.loop.run_until_complete(self.async_client.post(url, **kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.loop.close()

    async_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fastapi_app),
        base_url=BASE_URL,
        follow_redirects=False,  # step 1 must capture the raw 307
    )
    client = SyncClient(async_client)
    return client, active_patches


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Validate the 2FA step-up flow end-to-end.")
    parser.add_argument(
        "--mock-duo",
        action="store_true",
        help=(
            "Run in-process with a mocked Duo that auto-approves. "
            "No running server or phone needed — ideal for local dev."
        ),
    )
    args = parser.parse_args()

    print("=== 2FA Step-Up Flow Validation ===")

    active_patches = []
    if args.mock_duo:
        print("⚠️  Mock-Duo mode: Duo push will be auto-approved (no phone or server needed).")
        # Ensure src/ is on the path when running from the repo root.
        src_path = os.path.join(os.path.dirname(__file__), "..", "src")
        sys.path.insert(0, os.path.abspath(src_path))
        client, active_patches = _mock_duo_client()
    else:
        print(f"🔒 Real-Duo mode: approve the push on your phone. Server: {BASE_URL}")
        client = _real_client()

    try:
        token = generate_token()
        print(f"Generated token: {token[:40]}...")

        challenge = step1_get_challenge(client, token)
        elevated_token, redirect_to = step2_duo_push(client, challenge, mock=args.mock_duo)
        result = step3_elevated_request(client, elevated_token, redirect_to)

        print("\n✅ Full 2FA flow completed successfully!")
        print(f"   Final response: {result}")
    finally:
        for p in active_patches:
            p.stop()


if __name__ == "__main__":
    main()
