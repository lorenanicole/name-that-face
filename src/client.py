import base64
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import requests
import streamlit as st
from browser_detection import browser_detection_engine
from dotenv import load_dotenv

from webrtc_liveness import webrtc_liveness_detector

logger = logging.getLogger(__name__)


def setup():
    """Load and validate client configuration from .env.client."""
    env_file = Path(__file__).parent.parent / ".env.client"
    load_dotenv(env_file)

    log_file = os.environ.get("CLIENT_LOG_PATH", "/tmp/name_that_face_client.log")

    # Configure logging to both console and file
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(),
        ],
    )

    config = {
        "BASE_URL": os.environ.get("API_BASE_URL", "http://127.0.0.1:8000"),
        "JWT_SECRET": os.environ.get("JWT_SECRET", "test-secret-change-me"),
        "JWT_ALGORITHM": os.environ.get("JWT_ALGORITHM", "HS256"),
        "USER_ID": os.environ.get("USER_ID", "test-user-1"),
        "USERNAME": os.environ.get("USERNAME", "test@example.com"),
        "PAYLOAD": {
            "name": os.environ.get("USER_NAME", "Test User"),
            "email": os.environ.get("USER_EMAIL", "test@example.com"),
            "age": int(os.environ.get("USER_AGE", "25")),
        },
    }

    logger.info(f"Configuration loaded from {env_file}")
    logger.info(f"Logging to {log_file}")
    logger.info(f"API_BASE_URL: {config['BASE_URL']}")
    logger.info(f"JWT_ALGORITHM: {config['JWT_ALGORITHM']}")
    logger.info(f"USER_ID: {config['USER_ID']}")
    logger.info(f"USERNAME: {config['USERNAME']}")
    logger.info(f"User payload: {config['PAYLOAD']}")

    return config


config = setup()
BASE_URL = config["BASE_URL"]
JWT_SECRET = config["JWT_SECRET"]
JWT_ALGORITHM = config["JWT_ALGORITHM"]
USER_ID = config["USER_ID"]
USERNAME = config["USERNAME"]
PAYLOAD = config["PAYLOAD"]


def build_headers(auth_token=None):
    """Build request headers with auth and original user-agent."""
    headers = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    if "user_agent" in st.session_state and st.session_state.user_agent != "unknown":
        headers["X-Original-User-Agent"] = st.session_state.user_agent
    return headers


def generate_token():
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


def get_challenge(token):
    resp = requests.post(
        f"{BASE_URL}/api/user/{USER_ID}",
        json=PAYLOAD,
        headers=build_headers(token),
        allow_redirects=False,
    )
    if resp.status_code != 307:
        raise RuntimeError(f"Expected 307, got {resp.status_code}: {resp.text}")
    location = resp.headers.get("location", "")
    challenge = location.split("challenge=")[-1].split("&")[0]
    if not challenge:
        raise RuntimeError("Challenge token not found in Location header")
    return challenge


def do_2fa(challenge):
    # Extract client_ip from challenge token payload
    parts = challenge.split(".")
    payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
    client_ip = payload.get("client_ip", "127.0.0.1")

    resp = requests.post(
        f"{BASE_URL}/login-2fa",
        json={"challenge": challenge, "client_ip": client_ip},
        headers=build_headers(),
    )
    if resp.status_code != 200:
        raise RuntimeError(f"2FA failed {resp.status_code}: {resp.text}")
    data = resp.json()
    return data["elevated_token"], data["redirect_to"]


def submit_photo(elevated_token, selfie_bytes, selfie_filename, gov_id_bytes, gov_id_filename):
    resp = requests.post(
        f"{BASE_URL}/api/user/{USER_ID}/photo",
        headers=build_headers(elevated_token),
        files={
            "selfie": (selfie_filename, selfie_bytes, "image/jpeg"),
            "gov_id": (gov_id_filename, gov_id_bytes, "image/jpeg"),
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Photo upload failed {resp.status_code}: {resp.text}")
    return resp.json()


def is_mobile():
    """Detect if user is on mobile device via user-agent."""
    try:
        # Streamlit doesn't expose user-agent directly, so we use JavaScript
        # For now, we'll check via a heuristic: mobile browsers often have narrower viewport
        return False  # Will be updated via JavaScript detection below
    except Exception:
        return False


def get_device_info():
    """Detect device type and capabilities using browser engine."""
    if "device_info" not in st.session_state:
        try:
            browser_stats = browser_detection_engine()
            if browser_stats:
                user_agent = browser_stats.get("userAgent", "unknown")
                st.session_state.user_agent = user_agent

                is_mobile = any(
                    x in user_agent.lower() for x in ["mobile", "android", "iphone", "ipad"]
                )
                is_tablet = "ipad" in user_agent.lower() or "tablet" in user_agent.lower()

                st.session_state.device_info = {
                    "detection_method": "browser_engine",
                    "user_agent": user_agent,
                    "is_mobile": is_mobile,
                    "is_tablet": is_tablet,
                    "is_desktop": not is_mobile and not is_tablet,
                    "has_sensors": True,  # Assume mobile devices have sensors
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                logger.info(f"Device detected: mobile={is_mobile}, user_agent={user_agent[:80]}")
            else:
                st.session_state.user_agent = "unknown"
                st.session_state.device_info = {
                    "detection_method": "browser_engine",
                    "user_agent": "unknown",
                    "is_mobile": False,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
        except Exception as e:
            logger.warning(f"Browser detection failed: {e}")
            st.session_state.user_agent = "unknown"

    return st.session_state.device_info


# Page config
st.set_page_config(page_title="Name-that-face Identity Verify", page_icon="🔍", layout="wide")

# Initialize device detection
device_info = get_device_info()

st.title("Name-that-face Identity Verification")
st.caption("Deepfake detection powered by Name-that-face")

# Log device detection
logger.info(f"Client initialized - {device_info}")

if "step" not in st.session_state:
    st.session_state.step = "start"

if "photo_retry_count" not in st.session_state:
    st.session_state.photo_retry_count = 0

if "need_reset" not in st.session_state:
    st.session_state.need_reset = False

if "widget_version" not in st.session_state:
    st.session_state.widget_version = 0

if "liveness_passed" not in st.session_state:
    st.session_state.liveness_passed = False

if "liveness_score" not in st.session_state:
    st.session_state.liveness_score = None

# Handle reset if needed
if st.session_state.need_reset:
    # Clear only the specific keys we need to reset
    for key in [
        "selfie_input",
        "gov_id_input",
        "challenge",
        "elevated_token",
        "redirect_to",
        "result",
    ]:
        st.session_state.pop(key, None)
    st.session_state.step = "start"
    st.session_state.photo_retry_count = 0
    st.session_state.need_reset = False
    # Increment widget version to force Streamlit to create fresh widgets
    st.session_state.widget_version += 1

if st.session_state.step == "start":
    st.info("Click below to begin. A Duo push will be sent to your phone.")
    if st.button("Start Verification", type="primary"):
        with st.spinner("Requesting 2FA challenge..."):
            try:
                token = generate_token()
                challenge = get_challenge(token)
                st.session_state.challenge = challenge
                st.session_state.step = "awaiting_duo"
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

elif st.session_state.step == "awaiting_duo":
    st.warning("📱 Sending Duo push to your phone — approve it now...")
    with st.spinner("Waiting for Duo approval (up to 60s)..."):
        try:
            elevated_token, redirect_to = do_2fa(st.session_state.challenge)
            st.session_state.elevated_token = elevated_token
            st.session_state.redirect_to = redirect_to
            st.session_state.step = "capture_photo"
            st.rerun()
        except Exception as e:
            st.error(f"2FA error: {e}")
            if st.button("Start over"):
                st.session_state.step = "start"
                st.rerun()

elif st.session_state.step == "capture_photo":
    st.success("2FA verified! Complete the steps below to verify your identity.")

    # =====================================================================
    # STEP 1: LIVENESS DETECTION (REQUIRED - Filter deepfakes early)
    # =====================================================================
    st.subheader("Step 1: Liveness Detection")
    st.caption("Verify you're a real person — prevents deepfakes and spoofing")

    if not st.session_state.liveness_passed:
        # LIVENESS NOT PASSED - Show detection UI
        if st.session_state.device_info.get("is_mobile"):
            st.info(
                "📱 WebRTC Liveness Detection: Real-time video capture with OpenCV analysis. "
                "Allow camera access and move your head naturally for 5 seconds."
            )

            with st.spinner("🎬 Initializing WebRTC camera..."):
                frames = webrtc_liveness_detector(duration_seconds=5)

            if frames and len(frames) > 0:
                st.success(f"✅ Captured {len(frames)} video frames via WebRTC")

                if st.button("✅ Analyze with OpenCV", type="primary", key="confirm_liveness"):
                    with st.spinner("Sending frames to server for OpenCV analysis..."):
                        try:
                            # Convert frames to base64 for transmission
                            import base64

                            import cv2

                            frames_b64 = []
                            for frame in frames[:50]:  # Limit to 50 frames
                                _, buffer = cv2.imencode(".jpg", frame)
                                frame_b64 = base64.b64encode(buffer).decode()
                                frames_b64.append(frame_b64)

                            endpoint = f"{BASE_URL}/api/liveness/analyze"
                            headers = build_headers(st.session_state.elevated_token)

                            logger.info(
                                f"Sending {len(frames_b64)} frames to OpenCV analysis: {endpoint}"
                            )

                            resp = requests.post(
                                endpoint,
                                json={"frames_base64": frames_b64},
                                headers=headers,
                                timeout=30,
                            )

                            if resp.status_code == 200:
                                opencv_result = resp.json()
                                logger.info(
                                    f"OpenCV analysis result - is_live={opencv_result.get('is_live')}, "
                                    f"confidence={opencv_result.get('confidence')}, "
                                    f"frames={opencv_result.get('frame_count')}, "
                                    f"signals={opencv_result.get('signals')}"
                                )

                                confidence = opencv_result.get("confidence", 0.0)
                                is_live = opencv_result.get("is_live", False)
                                frame_count = opencv_result.get("frame_count", 0)
                                signals = opencv_result.get("signals", [])

                                if frame_count > 0 and is_live and confidence >= 0.6:
                                    st.success(
                                        f"✅ Liveness Verified! OpenCV confidence: {confidence:.0%}"
                                    )
                                    st.session_state.liveness_passed = True
                                    st.session_state.liveness_score = {
                                        "confidence": confidence,
                                        "is_live": True,
                                        "detection_type": "webrtc_opencv",
                                        "frame_count": frame_count,
                                        "signals": signals,
                                    }
                                    st.rerun()
                                else:
                                    st.warning(
                                        f"⚠️ Low confidence ({confidence:.0%}). Try again with better lighting and movement."
                                    )
                            else:
                                st.error(f"Server error: {resp.status_code}")
                                logger.error(f"OpenCV error response: {resp.text}")

                        except Exception as e:
                            st.error(f"Analysis error: {e}")
                            logger.error(f"OpenCV exception: {e}", exc_info=True)
            else:
                st.warning(
                    "⏳ No frames captured. Make sure camera is enabled and you have sufficient lighting."
                )
        else:
            st.warning(
                "📱 Dual liveness (sensor + video) requires mobile device. Desktop: motion check skipped."
            )
            if st.button("Continue (Desktop Mode)", type="primary", key="desktop_mode"):
                st.session_state.liveness_passed = True
                st.session_state.liveness_score = {
                    "confidence": 0.0,
                    "is_live": True,
                    "detection_type": "desktop_bypass",
                }
                st.rerun()
    else:
        # LIVENESS PASSED - Show success and proceed to selfie
        confidence = (
            st.session_state.liveness_score.get("confidence", 0.0)
            if st.session_state.liveness_score
            else 0.0
        )
        st.success(f"✅ Liveness passed ({confidence:.1%} confidence)")

        # =====================================================================
        # STEP 2: SELFIE CAPTURE (Only shown after liveness passes)
        # =====================================================================
        st.subheader("Step 2: Take a Selfie")
        st.caption("Clear, well-lit photo of your face")

        selfie = st.camera_input(
            "Take a photo of your face", key=f"selfie_input_{st.session_state.widget_version}"
        )

        # STEP 3 AND BEYOND - Only show if selfie is captured
        if selfie is not None:
            st.image(selfie, caption="Selfie preview", width=300)

            # =====================================================================
            # STEP 3: GOVERNMENT ID UPLOAD (Only shown after selfie taken)
            # =====================================================================
            st.subheader("Step 3: Upload Government ID")
            st.caption("Clear photo of your passport, driver's license, or national ID")

            gov_id = st.file_uploader(
                "Government ID photo",
                type=["jpg", "jpeg", "png"],
                key=f"gov_id_input_{st.session_state.widget_version}",
            )

            # STEP 4 AND BEYOND - Only show if both photos are collected
            if gov_id is not None:
                st.image(gov_id, caption="Government ID preview", width=300)

                # =====================================================================
                # STEP 4: SUBMIT (Only enabled when both photos collected)
                # =====================================================================
                if st.button("Submit for Verification", type="primary"):
                    with st.spinner("Analyzing photos with DeepFace..."):
                        try:
                            result = submit_photo(
                                elevated_token=st.session_state.elevated_token,
                                selfie_bytes=selfie.getvalue(),
                                selfie_filename=selfie.name,
                                gov_id_bytes=gov_id.getvalue(),
                                gov_id_filename=gov_id.name,
                            )
                            st.session_state.result = result
                            st.session_state.step = "result"
                            st.rerun()
                        except Exception as e:
                            st.session_state.photo_retry_count += 1
                            st.session_state.last_error = str(e)

                # Show error messages and retry buttons (only after submit attempt)
                if "last_error" in st.session_state and st.session_state.last_error:
                    error_msg = st.session_state.last_error
                    max_retries = 3

                    if "face" in error_msg.lower() or "detect" in error_msg.lower():
                        st.error(
                            f"❌ {error_msg}\n\n"
                            "Please ensure:\n"
                            "- Your face is clearly visible\n"
                            "- You are looking directly at the camera\n"
                            "- The photo is well-lit\n"
                            "- Both photos (selfie and ID) have visible faces"
                        )
                    else:
                        st.error(f"Upload error: {error_msg}")

                    remaining_retries = max_retries - st.session_state.photo_retry_count
                    if remaining_retries > 0:
                        st.info(
                            f"Retries remaining: {remaining_retries}. Please try again with different photos."
                        )
                        if st.button("Try again with new photos"):
                            st.session_state.last_error = None
                            st.session_state.widget_version += 1
                            st.rerun()
                    else:
                        st.warning(
                            "⚠️ Maximum retry attempts exceeded. You must restart the verification."
                        )
                        if st.button("Start Over (requires new 2FA)"):
                            st.session_state.need_reset = True
                            st.rerun()

elif st.session_state.step == "result":
    result = st.session_state.result
    verified = result.get("verified", False)
    confidence = result.get("confidence", 0.0)
    distance = result.get("distance", 0.0)
    threshold = result.get("threshold", 0.0)
    signals = result.get("signals", [])

    if verified:
        st.success("Identity Verified - Selfie matches government ID")
    else:
        st.error("Identity Not Verified - Face mismatch detected")

    col1, col2, col3 = st.columns(3)
    col1.metric("Confidence", f"{confidence * 100:.1f}%")
    col2.metric("Distance", f"{distance:.3f}")
    col3.metric("Threshold", f"{threshold:.3f}")

    if signals:
        st.subheader("Signals")
        for signal in signals:
            st.write(f"- {signal}")

    with st.expander("Full response"):
        st.json(result)

    if st.button("Start over"):
        for key in ["step", "challenge", "elevated_token", "redirect_to", "result"]:
            st.session_state.pop(key, None)
        st.session_state.step = "start"
        st.rerun()
