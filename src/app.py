import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.security import HTTPBearer  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from dependencies import duo_auth, fraud_service, token_service  # noqa: E402
from models import UserRequest  # noqa: E402
from rate_limiter import rate_limit  # noqa: E402
from token_service import TokenError  # noqa: E402

AUDIT_LOG_PATH = Path(
    os.environ.get("AUDIT_LOG_PATH", str(Path(__file__).parent.parent / "logs" / "audit_log.jsonl"))
)

logger = structlog.get_logger(__name__)

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


class LoginRequest(BaseModel):
    challenge: str  # signed challenge token issued by rate_limiter on step-up redirect


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

    if len(selfie_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Selfie exceeds 10MB limit")
    if len(gov_id_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Government ID photo exceeds 10MB limit")

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
