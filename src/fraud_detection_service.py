import base64
import hashlib
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class FraudDetectionResult:
    verified: bool  # True = same person in both photos
    is_deepfake: bool  # True = face mismatch / spoof detected
    confidence: float  # 0.0 - 1.0 (derived from DeepFace distance)
    distance: float  # raw DeepFace cosine distance (lower = more similar)
    threshold: float  # model's decision boundary
    signals: list[str]  # human-readable findings
    selfie_hash: str  # sha256 of selfie bytes (audit)
    gov_id_hash: str  # sha256 of gov_id bytes (audit)
    analyzed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class FraudDetectionService:
    """
    Compare a live selfie against a government ID photo using DeepFace.verify.
    No custom model training needed - DeepFace wraps pretrained ArcFace/FaceNet.
    """

    def verify(
        self,
        selfie_b64: str,
        gov_id_b64: str,
        model_name: str = "ArcFace",
        detector_backend: str = "opencv",
    ) -> FraudDetectionResult:
        selfie_hash = hashlib.sha256(selfie_b64.encode()).hexdigest()
        gov_id_hash = hashlib.sha256(gov_id_b64.encode()).hexdigest()
        logger.info(
            "fraud_detection.verify.started", selfie_hash=selfie_hash, gov_id_hash=gov_id_hash
        )
        result = self._run_deepface(
            selfie_b64, gov_id_b64, model_name, detector_backend, selfie_hash, gov_id_hash
        )
        logger.info(
            "fraud_detection.verify.complete", verified=result.verified, distance=result.distance
        )
        return result

    # Path to the Python 3.12 venv where deepface + tensorflow-cpu are installed.
    # Override with DEEPFACE_PYTHON env var (e.g. in Docker: /opt/deepface-venv/bin/python)
    DEEPFACE_PYTHON = os.environ.get(
        "DEEPFACE_PYTHON",
        "/Users/lorenamesa/Workspace/deepface-venv/bin/python",
    )

    def _run_deepface(
        self, selfie_b64, gov_id_b64, model_name, detector_backend, selfie_hash, gov_id_hash
    ):
        import json
        import subprocess

        selfie_bytes = base64.b64decode(selfie_b64)
        gov_id_bytes = base64.b64decode(gov_id_b64)

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as sf:
            sf.write(selfie_bytes)
            selfie_path = sf.name
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as gf:
            gf.write(gov_id_bytes)
            gov_id_path = gf.name

        # Inline script executed by the 3.12 venv so TensorFlow/DeepFace are available.
        script = f"""
import json, sys
try:
    from deepface import DeepFace
    r = DeepFace.verify(
        img1_path={selfie_path!r},
        img2_path={gov_id_path!r},
        model_name={model_name!r},
        detector_backend={detector_backend!r},
        distance_metric="cosine",
        enforce_detection=True,
    )
    print(json.dumps({{"ok": True, "verified": r["verified"], "distance": r["distance"], "threshold": r["threshold"]}}))
except Exception as e:
    print(json.dumps({{"ok": False, "error": str(e)}}))
"""

        try:
            proc = subprocess.run(
                [self.DEEPFACE_PYTHON, "-c", script],
                capture_output=True,
                text=True,
                timeout=120,
            )
            # Grab the last non-empty line which holds our JSON output
            output_lines = [line for line in proc.stdout.strip().splitlines() if line.strip()]
            if not output_lines:
                raise RuntimeError(
                    f"DeepFace subprocess produced no output. stderr: {proc.stderr[-500:]}"
                )
            data = json.loads(output_lines[-1])

            if not data.get("ok"):
                raise RuntimeError(data.get("error", "Unknown DeepFace error"))

            verified = data["verified"]
            distance = data["distance"]
            threshold = data["threshold"]
            confidence = max(0.0, 1.0 - (distance / (threshold * 2)))
            signals = []
            if verified:
                signals.append(
                    f"Face match confirmed (distance={distance:.3f}, threshold={threshold:.3f})"
                )
            else:
                signals.append(
                    f"Face mismatch (distance={distance:.3f}, threshold={threshold:.3f})"
                )
                signals.append("Identity could not be verified against government ID")

            return FraudDetectionResult(
                verified=verified,
                is_deepfake=not verified,
                confidence=confidence,
                distance=distance,
                threshold=threshold,
                signals=signals,
                selfie_hash=selfie_hash,
                gov_id_hash=gov_id_hash,
            )
        except Exception as e:
            logger.error("fraud_detection.deepface_failed", error=str(e))
            return FraudDetectionResult(
                verified=False,
                is_deepfake=True,
                confidence=0.0,
                distance=1.0,
                threshold=0.0,
                signals=[f"Detection error: {str(e)}"],
                selfie_hash=selfie_hash,
                gov_id_hash=gov_id_hash,
            )
        finally:
            os.unlink(selfie_path)
            os.unlink(gov_id_path)
