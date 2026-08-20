import base64
import json
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.security import HTTPBearer  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from dependencies import duo_auth, fraud_service, settings, token_service  # noqa: E402
from models import LoginRequest, UserRequest  # noqa: E402
from rate_limiter import rate_limit  # noqa: E402
from token_service import TokenError  # noqa: E402

AUDIT_LOG_PATH = settings.AUDIT_LOG_PATH

logger = structlog.get_logger(__name__)

logger.info(f"Starting logging at {AUDIT_LOG_PATH}")

# Swagger UI "Authorize" button — sends Authorization: Bearer <token>
# The actual validation is done by the rate_limit decorator; this only
# wires the lock icon into the OpenAPI schema.
bearer = HTTPBearer(auto_error=False)

app = FastAPI(
    title="Name-that-face API",
    description="""
Deepfake detection API with JWT token authentication and token-bucket rate limiting.

## Authentication

All endpoints require a Bearer JWT in the `Authorization` header.
Use `inv token` to generate a token for local testing, then click **Authorize 🔒** and paste it in.

```
inv token                           # user:read  (30 min)
inv token --scope user:write --step-up
inv token --scope admin:admin --step-up
```

## Rate limiting
- Rate-limit tokens refill every minute (frequency control)
- Daily token budget refills every 24 hours (budget control)
""",
    version="1.0.0",
)

# Enable CORS for liveness detection iframe (Streamlit components)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for local development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/user/{user_id}", dependencies=[Depends(bearer)])
@rate_limit(key="user:read")
async def get_user(request: Request, user_id: str):
    """
    Return information for the requested user.
    JWT claims (sub, username) are available via request.state.jwt_claims,
    set by the rate_limit decorator after successful validation.
    """
    claims = request.state.jwt_claims
    return {
        "user_id": user_id,
        "sub": claims.get("sub"),
        "username": claims.get("username"),
        "token_scope": claims.get("scope"),
        "step_up": claims.get("step_up", False),
        "token_expires_at": datetime.fromtimestamp(claims["exp"], tz=timezone.utc).isoformat(),
    }


@app.post("/api/user/{user_id}", dependencies=[Depends(bearer)])
@rate_limit(key="user:write")
async def update_user(request: Request, user_id: str, body: UserRequest):
    """
    Update information for the requested user.
    JWT claims (sub, username) are available via request.state.jwt_claims,
    set by the rate_limit decorator after successful validation.
    """

    claims = request.state.jwt_claims
    validated = body.model_dump()

    logger.info(
        "user.update",
        user_id=user_id,
        sub=claims.get("sub"),
        username=claims.get("username"),
        token_scope=claims.get("scope"),
        step_up=claims.get("step_up", False),
        token_expires_at=datetime.fromtimestamp(claims["exp"], tz=timezone.utc).isoformat(),
    )
    return JSONResponse(status_code=200, content=validated)


@app.post("/login-2fa")
async def login_2fa(request: LoginRequest):
    # 1. decode the challenge to get user_id, username, required_scope, and next url
    try:
        ctx = token_service.decode_step_up_challenge(request.challenge)
    except TokenError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 2. send Duo push to the user
    try:
        check_user = duo_auth.auth(
            username=ctx["username"],
            factor="push",
            device="auto",
            ipaddr=request.client_ip,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Duo error: {e}")

    # 3. evaluate Duo's response
    if check_user.get("result") == "allow":
        elevated_token = token_service.issue(
            user_id=ctx["sub"],
            scope=ctx["required_scope"],
            step_up=True,
        )
        return JSONResponse(
            status_code=200,
            content={
                "elevated_token": elevated_token,
                "redirect_to": ctx["next"],
            },
        )
    else:
        raise HTTPException(status_code=401, detail=f"2FA Denied: {check_user.get('status_msg')}")


@app.post("/api/user/{user_id}/photo", dependencies=[Depends(bearer)])
@rate_limit(key="user:write")
async def upload_photo(
    request: Request, user_id: str, selfie: UploadFile = File(...), gov_id: UploadFile = File(...)
):
    """
    Accept a selfie + government ID photo and run DeepFace identity verification.
    Requires a step-up (2FA-verified) user:write token.
    """
    selfie_bytes = await selfie.read()
    gov_id_bytes = await gov_id.read()

    if len(selfie_bytes) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Selfie exceeds 50MB limit")
    if len(gov_id_bytes) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Government ID photo exceeds 50MB limit")

    selfie_b64 = base64.b64encode(selfie_bytes).decode("utf-8")
    gov_id_b64 = base64.b64encode(gov_id_bytes).decode("utf-8")

    try:
        result = fraud_service.verify(selfie_b64=selfie_b64, gov_id_b64=gov_id_b64)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Append-only audit log entry
    audit_entry = {
        "user_id": user_id,
        "selfie_hash": result.selfie_hash,
        "gov_id_hash": result.gov_id_hash,
        "verified": result.verified,
        "confidence": result.confidence,
        "analyzed_at": result.analyzed_at.isoformat(),
    }
    try:
        with open(AUDIT_LOG_PATH, "a") as f:
            f.write(json.dumps(audit_entry) + "\n")
        logger.info(
            "audit_log.written",
            user_id=user_id,
            selfie_hash=result.selfie_hash,
            gov_id_hash=result.gov_id_hash,
            verified=result.verified,
            confidence=result.confidence,
            analyzed_at=result.analyzed_at.isoformat(),
        )
    except Exception as log_err:
        logger.error("audit_log.write_failed", error=str(log_err))

    return JSONResponse(
        status_code=200,
        content={
            "user_id": user_id,
            "verified": result.verified,
            "is_deepfake": result.is_deepfake,
            "confidence": result.confidence,
            "distance": result.distance,
            "threshold": result.threshold,
            "signals": result.signals,
            "selfie_hash": result.selfie_hash,
            "gov_id_hash": result.gov_id_hash,
            "analyzed_at": result.analyzed_at.isoformat(),
        },
    )


class FraudDetectRequest(BaseModel):
    image_url: Optional[str] = None
    video_url: Optional[str] = None
    base64_blob: Optional[str] = None


class VideoLivenessRequest(BaseModel):
    """Video frames (base64 encoded) for liveness detection analysis."""

    frames_base64: list[str]  # List of base64-encoded JPEG frames


class VideoFramesUploadRequest(BaseModel):
    """Store video frames for later analysis."""

    frames_base64: list[str]
    user_id: str


@app.post("/api/liveness/frames", dependencies=[Depends(bearer)])
@rate_limit(key="user:write")
async def upload_liveness_frames(request: Request, body: VideoFramesUploadRequest):
    """
    Upload video frames captured during motion detection for later analysis.
    Frames are stored temporarily and used by /api/liveness/analyze.
    """
    frame_count = len(body.frames_base64) if body.frames_base64 else 0
    user_id = body.user_id or request.state.jwt_claims.get("sub", "unknown")

    # Validate frame data
    avg_frame_size = 0
    if frame_count > 0:
        avg_frame_size = sum(len(f) for f in body.frames_base64) / frame_count

    logger.info(
        "liveness.frames_uploaded",
        frame_count=frame_count,
        user_id=user_id,
        avg_frame_size_bytes=int(avg_frame_size),
    )

    # Store frames in app state (temporary cache, expires after use)
    if not hasattr(app, "_liveness_frames_cache"):
        app._liveness_frames_cache = {}

    app._liveness_frames_cache[user_id] = {
        "frames": body.frames_base64,
        "timestamp": datetime.now(timezone.utc),
    }

    logger.info(
        "liveness.frames_cached",
        frame_count=frame_count,
        user_id=user_id,
        cache_size=len(app._liveness_frames_cache),
    )

    return JSONResponse(
        status_code=200,
        content={
            "status": "frames_stored",
            "frame_count": frame_count,
        },
    )


@app.post("/api/liveness/analyze", dependencies=[Depends(bearer)])
@rate_limit(key="user:write")
async def analyze_video_liveness(request: Request, body: VideoLivenessRequest):
    """
    Analyze video frames for liveness detection using OpenCV.

    Input: List of base64-encoded video frames captured during motion detection.
    Output: Liveness score, confidence, detected signals (face detection, motion, etc).

    Combines with client-side JavaScript analysis for hybrid approach:
    - Client: Quick heuristic check (frame diversity, duration)
    - Server: Deep analysis (face detection, optical flow, sharpness variance)
    """
    import cv2
    import numpy as np

    from liveness_detector import analyze_video_liveness as opencv_analyze

    frame_count = len(body.frames_base64) if body.frames_base64 else 0
    frames_to_analyze = body.frames_base64 or []
    user_id = request.state.jwt_claims.get("sub", "unknown")
    cache_hit = False

    # Check if frames were uploaded separately via /api/liveness/frames
    if not frames_to_analyze and hasattr(app, "_liveness_frames_cache"):
        if user_id in app._liveness_frames_cache:
            cached = app._liveness_frames_cache[user_id]
            frames_to_analyze = cached.get("frames", [])
            frame_count = len(frames_to_analyze)
            cache_hit = True
            logger.info(
                "liveness.opencv_using_cached_frames",
                frame_count=frame_count,
                user_id=user_id,
            )
            # Clear cache after retrieval
            del app._liveness_frames_cache[user_id]
        else:
            logger.warning(
                "liveness.no_cached_frames",
                user_id=user_id,
                available_users=list(app._liveness_frames_cache.keys())
                if hasattr(app, "_liveness_frames_cache")
                else [],
            )

    logger.info(
        "liveness.opencv_request_received",
        frame_count=frame_count,
        user_id=user_id,
        cache_hit=cache_hit,
    )

    if not frames_to_analyze or len(frames_to_analyze) < 3:
        return JSONResponse(
            status_code=200,
            content={
                "is_live": False,
                "confidence": 0.0,
                "signals": ["Insufficient frames for server-side analysis"],
                "frame_count": len(body.frames_base64) if body.frames_base64 else 0,
                "avg_sharpness": 0.0,
                "avg_motion": 0.0,
                "analysis_type": "opencv_full",
            },
        )

    try:
        # Decode base64 frames to OpenCV format
        frames = []
        for frame_b64 in frames_to_analyze:  # Process all frames for better analysis
            try:
                frame_bytes = base64.b64decode(
                    frame_b64.split(",")[1] if "," in frame_b64 else frame_b64
                )
                nparr = np.frombuffer(frame_bytes, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if frame is not None:
                    frames.append(frame)
            except Exception as e:
                logger.warning(f"Failed to decode frame: {e}")
                continue

        if len(frames) < 3:
            return JSONResponse(
                status_code=200,
                content={
                    "is_live": False,
                    "confidence": 0.0,
                    "signals": ["Could not decode frames"],
                    "frame_count": 0,
                    "avg_sharpness": 0.0,
                    "avg_motion": 0.0,
                    "analysis_type": "opencv_full",
                },
            )

        # Run OpenCV liveness analysis
        result = opencv_analyze(frames)

        logger.info(
            "liveness.opencv_analyzed",
            user_id=user_id,
            is_live=result["is_live"],
            confidence=f"{result['confidence']:.2f}",
            frame_count=result["frame_count"],
            signals=result["signals"],
            avg_sharpness=f"{result.get('avg_sharpness', 0):.1f}",
            avg_motion=f"{result.get('avg_motion', 0):.3f}",
        )

        return JSONResponse(
            status_code=200,
            content={
                "is_live": result["is_live"],
                "confidence": float(result["confidence"]),
                "signals": result["signals"],
                "frame_count": result["frame_count"],
                "avg_sharpness": float(result.get("avg_sharpness", 0)),
                "avg_motion": float(result.get("avg_motion", 0)),
                "analysis_type": "opencv_full",
            },
        )

    except Exception as e:
        logger.error("liveness.opencv_error", user_id=user_id, error=str(e), exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"OpenCV analysis failed: {str(e)}",
                "is_live": False,
                "confidence": 0.0,
            },
        )


@app.post("/api/fraud/detect", dependencies=[Depends(bearer)])
@rate_limit(key="admin:admin")
async def detect_fraud(request: Request, body: FraudDetectRequest):
    """
    Analyze submitted content for deepfake / identity fraud signals.

    Requires an admin-scoped step-up token (2FA enforced).
    Returns is_deepfake, confidence score, and signals list.
    Can also be called internally by other routes via fraud_service.analyze().
    """
    try:
        result = fraud_service.analyze(
            image_url=body.image_url,
            video_url=body.video_url,
            base64_blob=body.base64_blob,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return JSONResponse(
        status_code=200,
        content={
            "is_deepfake": result.is_deepfake,
            "confidence": result.confidence,
            "signals": result.signals,
            "input_hash": result.input_hash,
            "analyzed_at": result.analyzed_at.isoformat(),
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
