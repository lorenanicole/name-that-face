import base64
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import requests
import streamlit as st
from dotenv import load_dotenv

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
        headers={"Authorization": f"Bearer {token}"},
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
        f"{BASE_URL}/login-2fa", json={"challenge": challenge, "client_ip": client_ip}
    )
    if resp.status_code != 200:
        raise RuntimeError(f"2FA failed {resp.status_code}: {resp.text}")
    data = resp.json()
    return data["elevated_token"], data["redirect_to"]


def submit_photo(elevated_token, selfie_bytes, selfie_filename, gov_id_bytes, gov_id_filename):
    resp = requests.post(
        f"{BASE_URL}/api/user/{USER_ID}/photo",
        headers={"Authorization": f"Bearer {elevated_token}"},
        files={
            "selfie": (selfie_filename, selfie_bytes, "image/jpeg"),
            "gov_id": (gov_id_filename, gov_id_bytes, "image/jpeg"),
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Photo upload failed {resp.status_code}: {resp.text}")
    return resp.json()


st.set_page_config(page_title="Name-that-face Identity Verify", page_icon="🔍")
st.title("Name-that-face Identity Verification")
st.caption("Deepfake detection powered by Name-that-face")

if "step" not in st.session_state:
    st.session_state.step = "start"

if "photo_retry_count" not in st.session_state:
    st.session_state.photo_retry_count = 0

if "need_reset" not in st.session_state:
    st.session_state.need_reset = False

if "widget_version" not in st.session_state:
    st.session_state.widget_version = 0

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
    st.success("2FA verified! Complete the two steps below to verify your identity.")

    st.subheader("Step 1: Take a selfie")
    selfie = st.camera_input(
        "Take a photo of your face", key=f"selfie_input_{st.session_state.widget_version}"
    )

    st.subheader("Step 2: Upload your government ID")
    st.caption("Upload a clear photo of your passport, driver's license, or national ID")
    gov_id = st.file_uploader(
        "Government ID photo",
        type=["jpg", "jpeg", "png"],
        key=f"gov_id_input_{st.session_state.widget_version}",
    )

    if selfie is not None:
        st.image(selfie, caption="Selfie preview", width=300)
    if gov_id is not None:
        st.image(gov_id, caption="Government ID preview", width=300)

    if selfie is not None and gov_id is not None:
        if st.button("Submit for verification", type="primary"):
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

        # Show error messages and retry buttons OUTSIDE the spinner
        if "last_error" in st.session_state and st.session_state.last_error:
            error_msg = st.session_state.last_error
            max_retries = 3

            # Check if it's a face detection error
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
                    st.session_state.widget_version += 1  # Force fresh widgets
                    st.rerun()
            else:
                st.warning(
                    "⚠️ Maximum retry attempts exceeded. "
                    "For security, you must complete 2FA verification again."
                )
                if st.button("Start over (requires new 2FA)"):
                    st.session_state.need_reset = True
                    st.rerun()
    else:
        st.info("Both a selfie and government ID are required to proceed.")

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
