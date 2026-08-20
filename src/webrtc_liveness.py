"""WebRTC-based liveness detection using streamlit-webrtc."""

import queue

import streamlit as st

try:
    from streamlit_webrtc import RTCConfiguration, WebRtcMode, webrtc_streamer

    WEBRTC_AVAILABLE = True
except ImportError:
    WEBRTC_AVAILABLE = False


if WEBRTC_AVAILABLE:

    class FrameProcessor:
        """Captures video frames from WebRTC stream."""

        def __init__(self, frame_queue: queue.Queue, max_frames: int = 100):
            self.frame_queue = frame_queue
            self.max_frames = max_frames
            self.frame_count = 0

        def recv(self, frame):
            """Process incoming video frame."""
            if self.frame_count < self.max_frames:
                try:
                    # Convert to numpy array for OpenCV
                    img = frame.to_ndarray(format="bgr24")
                    self.frame_queue.put(img)
                    self.frame_count += 1
                except Exception as e:
                    print(f"Frame capture error: {e}")

            return frame
else:

    class FrameProcessor:
        """Placeholder when WebRTC not available."""

        def __init__(self, *args, **kwargs):
            pass


def webrtc_liveness_detector(
    duration_seconds: int = 5,
    rtc_configuration=None,
):
    """
    Capture video frames via WebRTC for server-side OpenCV analysis.

    Args:
        duration_seconds: How long to capture frames
        rtc_configuration: RTCConfiguration for WebRTC setup

    Returns:
        List of cv2 frames or None if cancelled
    """
    if not WEBRTC_AVAILABLE:
        st.error("WebRTC not available. Install streamlit-webrtc: poetry install")
        return None

    if rtc_configuration is None:
        rtc_configuration = RTCConfiguration(
            {"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]}
        )

    # Create frame queue
    frame_queue = queue.Queue()

    # Create WebRTC streamer
    webrtc_ctx = webrtc_streamer(
        key="liveness-detection",
        mode=WebRtcMode.SENDRECV,
        rtc_configuration=rtc_configuration,
        media_stream_constraints={"video": {"width": {"ideal": 1280}}, "audio": False},
        async_processing=True,
        video_frame_callback=lambda frame: FrameProcessor(frame_queue, max_frames=100).recv(frame),
    )

    if webrtc_ctx.state.playing:
        st.info("🎥 Recording video... Keep your head in frame and move naturally for 5 seconds")

        # Placeholder for status
        status_placeholder = st.empty()
        frames_placeholder = st.empty()

        # Collect frames
        frames = []
        for i in range(duration_seconds * 10):  # ~10 fps expected
            try:
                frame = frame_queue.get(timeout=0.5)
                frames.append(frame)
                frames_placeholder.write(f"📹 Frames captured: {len(frames)}")
            except queue.Empty:
                pass

        status_placeholder.success(f"✅ Captured {len(frames)} video frames")
        return frames if frames else None
    else:
        st.warning("⏳ Waiting for camera connection...")
        return None
