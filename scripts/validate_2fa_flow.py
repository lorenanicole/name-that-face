#!/usr/bin/env python3
"""
validate_2fa_flow.py

End-to-end validation script for the 2FA step-up flow.

Flow:
  1. POST /api/user/{user_id} with a non-step-up write token
     → 307 redirect with a signed challenge token in the Location header
  2. POST /login-2fa with the challenge token
     → Duo push sent to phone; approve it within 60 seconds
     → 200 OK with { "elevated_token": "...", "redirect_to": "..." }
  3. POST redirect_to with the elevated token
     → 200 OK with the updated user data
"""

import os
from datetime import datetime, timedelta, timezone

import jwt
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL = "http://localhost:8000"
JWT_SECRET = os.environ.get("SECRET_KEY", "replace-me-with-a-real-secret-in-env")
JWT_ALGORITHM = "HS256"

USER_ID = "1"
USERNAME = "me@lorenamesa.com"
PAYLOAD = {"name": "Lorena Mesa", "email": "me@lorenamesa.com", "age": 39}


def generate_token() -> str:
    """Issue a fresh write-scope JWT with step_up=False to trigger 2FA."""
    return jwt.encode(
        {
            "sub": USER_ID,
            "username": USERNAME,
            "scope": "user:write",
            "step_up": False,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def step1_get_challenge(token: str) -> str:
    """POST /api/user/{user_id} and extract the challenge token from the 307 redirect."""
    print("\n--- Step 1: POST /api/user/{user_id} (step_up=False) ---")
    resp = requests.post(
        f"{BASE_URL}/api/user/{USER_ID}",
        json=PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
        allow_redirects=False,
    )
    print(f"Status: {resp.status_code}")
    assert resp.status_code == 307, f"Expected 307, got {resp.status_code}: {resp.text}"

    location = resp.headers.get("location", "")
    print(f"Location: {location}")

    challenge = location.split("challenge=")[-1].split("&")[0]
    assert challenge, "Challenge token not found in Location header"
    print(f"Challenge token: {challenge[:40]}...")
    return challenge


def step2_duo_push(challenge: str) -> tuple[str, str]:
    """POST /login-2fa with the challenge; waits for Duo push approval."""
    print("\n--- Step 2: POST /login-2fa (approve Duo push on your phone!) ---")
    resp = requests.post(
        f"{BASE_URL}/login-2fa",
        json={"challenge": challenge},
    )
    print(f"Status: {resp.status_code}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    data = resp.json()
    print(f"elevated_token: {data['elevated_token'][:40]}...")
    print(f"redirect_to:    {data['redirect_to']}")
    return data["elevated_token"], data["redirect_to"]


def step3_elevated_request(elevated_token: str, redirect_to: str) -> dict:
    """POST redirect_to with the elevated token; expect 200 OK with user data."""
    print("\n--- Step 3: POST redirect_to with elevated token ---")
    resp = requests.post(
        redirect_to,
        json=PAYLOAD,
        headers={"Authorization": f"Bearer {elevated_token}"},
    )
    print(f"Status: {resp.status_code}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    data = resp.json()
    print(f"Response: {data}")
    return data


def main():
    print("=== 2FA Step-Up Flow Validation ===")

    token = generate_token()
    print(f"Generated token: {token[:40]}...")

    challenge = step1_get_challenge(token)
    elevated_token, redirect_to = step2_duo_push(challenge)
    result = step3_elevated_request(elevated_token, redirect_to)

    print("\n✅ Full 2FA flow completed successfully!")
    print(f"   Final response: {result}")


if __name__ == "__main__":
    main()
