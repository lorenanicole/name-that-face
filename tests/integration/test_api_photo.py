"""
tests/integration/test_api_photo.py

Integration tests for POST /api/user/{user_id}/photo.
FraudDetectionService is mocked — no real images or DeepFace subprocess.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from fraud_detection_service import FraudDetectionResult


def _multipart(selfie: bytes = b"img", gov_id: bytes = b"img"):
    return {
        "selfie": ("selfie.jpg", selfie, "image/jpeg"),
        "gov_id": ("gov_id.jpg", gov_id, "image/jpeg"),
    }


@pytest.mark.integration
async def test_photo_upload_verified_returns_200(client, elevated_token):
    ac, _ = client
    resp = await ac.post(
        "/api/user/u1/photo",
        headers={"Authorization": f"Bearer {elevated_token}"},
        files=_multipart(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["verified"] is True
    assert data["is_deepfake"] is False
    assert "confidence" in data
    assert "selfie_hash" in data
    assert "gov_id_hash" in data
    assert "analyzed_at" in data


@pytest.mark.integration
async def test_photo_upload_without_step_up_redirects_307(client, write_token):
    ac, _ = client
    resp = await ac.post(
        "/api/user/u1/photo",
        headers={"Authorization": f"Bearer {write_token}"},
        files=_multipart(),
        follow_redirects=False,
    )
    assert resp.status_code == 307


@pytest.mark.integration
async def test_photo_upload_no_token_returns_401(client):
    ac, _ = client
    resp = await ac.post("/api/user/u1/photo", files=_multipart())
    assert resp.status_code == 401


@pytest.mark.integration
async def test_photo_upload_selfie_too_large_returns_413(client, elevated_token):
    ac, _ = client
    big = b"x" * (10 * 1024 * 1024 + 1)
    resp = await ac.post(
        "/api/user/u1/photo",
        headers={"Authorization": f"Bearer {elevated_token}"},
        files=_multipart(selfie=big),
    )
    assert resp.status_code == 413


@pytest.mark.integration
async def test_photo_upload_gov_id_too_large_returns_413(client, elevated_token):
    ac, _ = client
    big = b"x" * (10 * 1024 * 1024 + 1)
    resp = await ac.post(
        "/api/user/u1/photo",
        headers={"Authorization": f"Bearer {elevated_token}"},
        files=_multipart(gov_id=big),
    )
    assert resp.status_code == 413


@pytest.mark.integration
async def test_photo_upload_writes_audit_log(client, elevated_token):
    ac, audit_log = client
    await ac.post(
        "/api/user/u1/photo",
        headers={"Authorization": f"Bearer {elevated_token}"},
        files=_multipart(),
    )
    assert audit_log.exists()
    entries = [json.loads(line) for line in audit_log.read_text().strip().splitlines()]
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry["user_id"] == "u1"
    assert "selfie_hash" in entry
    assert "gov_id_hash" in entry
    assert "verified" in entry
    assert "analyzed_at" in entry


@pytest.mark.integration
async def test_photo_upload_unverified_still_returns_200(client, elevated_token):
    """A face-mismatch result is still a successful API response (200), not an error."""
    ac, _ = client
    unverified_svc = MagicMock()
    unverified_svc.verify.return_value = FraudDetectionResult(
        verified=False,
        is_deepfake=True,
        confidence=0.1,
        distance=0.9,
        threshold=0.68,
        signals=[
            "Face mismatch (distance=0.900, threshold=0.680)",
            "Identity could not be verified against government ID",
        ],
        selfie_hash="xxx",
        gov_id_hash="yyy",
    )
    with patch("app.fraud_service", unverified_svc):
        resp = await ac.post(
            "/api/user/u1/photo",
            headers={"Authorization": f"Bearer {elevated_token}"},
            files=_multipart(),
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["verified"] is False
    assert data["is_deepfake"] is True
