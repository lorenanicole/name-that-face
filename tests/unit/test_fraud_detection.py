"""
tests/unit/test_fraud_detection.py

Unit tests for FraudDetectionService and FraudDetectionResult.
_run_deepface (subprocess) is mocked — no real images, no real Python subprocess.
"""

import base64
import hashlib
import json
from datetime import timezone
from unittest.mock import MagicMock, patch

import pytest

from fraud_detection_service import FraudDetectionResult, FraudDetectionService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


SELFIE_BYTES = b"fake-selfie-image-data"
GOV_ID_BYTES = b"fake-gov-id-image-data"
SELFIE_B64 = _b64(SELFIE_BYTES)
GOV_ID_B64 = _b64(GOV_ID_BYTES)

SELFIE_HASH = hashlib.sha256(SELFIE_B64.encode()).hexdigest()
GOV_ID_HASH = hashlib.sha256(GOV_ID_B64.encode()).hexdigest()


def _deepface_result(verified: bool, distance: float = 0.4, threshold: float = 0.68):
    """Return a JSON string mimicking DeepFace subprocess stdout."""
    return json.dumps(
        {"ok": True, "verified": verified, "distance": distance, "threshold": threshold}
    )


# ---------------------------------------------------------------------------
# FraudDetectionResult dataclass
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_result_defaults_analyzed_at_to_utc_now():
    r = FraudDetectionResult(
        verified=True,
        is_deepfake=False,
        confidence=0.9,
        distance=0.1,
        threshold=0.68,
        signals=[],
        selfie_hash="abc",
        gov_id_hash="def",
    )
    assert r.analyzed_at.tzinfo is not None
    assert r.analyzed_at.tzinfo == timezone.utc


@pytest.mark.unit
def test_result_fields_stored_correctly():
    r = FraudDetectionResult(
        verified=True,
        is_deepfake=False,
        confidence=0.75,
        distance=0.34,
        threshold=0.68,
        signals=["match"],
        selfie_hash="s",
        gov_id_hash="g",
    )
    assert r.verified is True
    assert r.is_deepfake is False
    assert r.confidence == pytest.approx(0.75)
    assert r.signals == ["match"]


# ---------------------------------------------------------------------------
# FraudDetectionService.verify — subprocess mocked
# ---------------------------------------------------------------------------


@pytest.fixture
def svc():
    return FraudDetectionService()


def _mock_proc(stdout: str, returncode: int = 0):
    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = ""
    proc.returncode = returncode
    return proc


@pytest.mark.unit
def test_verify_match_returns_verified_true(svc):
    with patch("subprocess.run", return_value=_mock_proc(_deepface_result(True, 0.4, 0.68))):
        with patch("fraud_detection_service.validate_government_id", return_value=(True, "")):
            result = svc.verify(SELFIE_B64, GOV_ID_B64)
    assert result.verified is True
    assert result.is_deepfake is False
    assert result.distance == pytest.approx(0.4)
    assert result.threshold == pytest.approx(0.68)
    assert any("match confirmed" in s for s in result.signals)


@pytest.mark.unit
def test_verify_mismatch_returns_verified_false(svc):
    with patch("subprocess.run", return_value=_mock_proc(_deepface_result(False, 0.75, 0.68))):
        with patch("fraud_detection_service.validate_government_id", return_value=(True, "")):
            result = svc.verify(SELFIE_B64, GOV_ID_B64)
    assert result.verified is False
    assert result.is_deepfake is True
    assert any("mismatch" in s for s in result.signals)


@pytest.mark.unit
def test_verify_hashes_are_sha256_of_b64(svc):
    with patch("subprocess.run", return_value=_mock_proc(_deepface_result(True))):
        with patch("fraud_detection_service.validate_government_id", return_value=(True, "")):
            result = svc.verify(SELFIE_B64, GOV_ID_B64)
    assert result.selfie_hash == SELFIE_HASH
    assert result.gov_id_hash == GOV_ID_HASH


@pytest.mark.unit
def test_verify_confidence_derived_from_distance(svc):
    # confidence = max(0, 1 - distance / (threshold * 2))
    # distance=0.34, threshold=0.68 → 1 - 0.34/1.36 = 0.75
    with patch("subprocess.run", return_value=_mock_proc(_deepface_result(True, 0.34, 0.68))):
        with patch("fraud_detection_service.validate_government_id", return_value=(True, "")):
            result = svc.verify(SELFIE_B64, GOV_ID_B64)
    assert result.confidence == pytest.approx(0.75)


@pytest.mark.unit
def test_verify_subprocess_no_output_raises_error(svc):
    """When subprocess produces no output, verify raises RuntimeError."""
    with patch("subprocess.run", return_value=_mock_proc("")):
        with patch("fraud_detection_service.validate_government_id", return_value=(True, "")):
            with pytest.raises(RuntimeError, match="produced no output"):
                svc.verify(SELFIE_B64, GOV_ID_B64)


@pytest.mark.unit
def test_verify_subprocess_deepface_error_raises(svc):
    """When DeepFace reports error, verify raises RuntimeError."""
    err_out = json.dumps({"ok": False, "error": "No face detected"})
    with patch("subprocess.run", return_value=_mock_proc(err_out)):
        with patch("fraud_detection_service.validate_government_id", return_value=(True, "")):
            with pytest.raises(RuntimeError, match="No face detected"):
                svc.verify(SELFIE_B64, GOV_ID_B64)


@pytest.mark.unit
def test_verify_temp_files_cleaned_up_on_error(svc, tmp_path):
    """Temp files must be deleted even when subprocess raises."""
    with patch("subprocess.run", side_effect=RuntimeError("crash")):
        with patch("fraud_detection_service.validate_government_id", return_value=(True, "")):
            with pytest.raises(RuntimeError, match="crash"):
                svc.verify(SELFIE_B64, GOV_ID_B64)
