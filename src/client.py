import os
from datetime import datetime, timedelta, timezone

import jwt
import requests
import streamlit as st

BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
JWT_SECRET = os.environ.get("SECRET_KEY", "replace-me-with-a-real-secret-in-env")
JWT_ALGORITHM = "HS256"
USER_ID = "1"
USERNAME = "me@lorenamesa.com"
PAYLOAD = {"name": "Lorena Mesa", "email": "me@lorenamesa.com", "age": 39}


def generate_token():
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
    resp = requests.post(f"{BASE_URL}/login-2fa", json={"challenge": challenge})
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
    selfie = st.camera_input("Take a photo of your face")

    st.subheader("Step 2: Upload your government ID")
    st.caption("Upload a clear photo of your passport, driver's license, or national ID")
    gov_id = st.file_uploader("Government ID photo", type=["jpg", "jpeg", "png"])

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
                    st.error(f"Upload error: {e}")
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
