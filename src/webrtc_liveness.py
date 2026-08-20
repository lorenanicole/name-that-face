"""WebRTC-based liveness detection using streamlit-webrtc."""

import queue
import time

import streamlit as st

try:
    from streamlit_webrtc import RTCConfiguration, WebRtcMode, webrtc_streamer

    WEBRTC_AVAILABLE = True
except ImportError:
    WEBRTC_AVAILABLE = False


if WEBRTC_AVAILABLE:

    class FrameProcessor:
        """Captures video frames from WebRTC stream."""

        def __init__(self, frame_queue: queue.Queue, max_frames: int = 300):
            self.frame_queue = frame_queue
            self.max_frames = max_frames
            self.frame_count = 0

        def recv(self, frame):
            """Process incoming video frame."""
            if self.frame_count < self.max_frames:
                try:
                    img = frame.to_ndarray(format="bgr24")
                    self.frame_queue.put(img)
                    self.frame_count += 1
                except Exception:
                    pass
            return frame

else:

    class FrameProcessor:
        def __init__(self, *args, **kwargs):
            pass


def webrtc_liveness_detector(duration_seconds: int = 5, rtc_configuration=None):
    """Capture video frames via WebRTC for OpenCV analysis."""
    if not WEBRTC_AVAILABLE:
        st.error("WebRTC not available")
        return None

    if rtc_configuration is None:
        rtc_configuration = RTCConfiguration(
            {"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]}
        )

    if "liveness_frame_queue" not in st.session_state:
        st.session_state.liveness_frame_queue = queue.Queue()
    if "liveness_frames" not in st.session_state:
        st.session_state.liveness_frames = []
    if "liveness_start_time" not in st.session_state:
        st.session_state.liveness_start_time = None

    frame_queue = st.session_state.liveness_frame_queue
    frame_processor = FrameProcessor(frame_queue, max_frames=300)

    webrtc_ctx = webrtc_streamer(
        key="liveness-detection",
        mode=WebRtcMode.SENDRECV,
        rtc_configuration=rtc_configuration,
        media_stream_constraints={"video": {"width": {"ideal": 1280}}, "audio": False},
        async_processing=True,
        video_frame_callback=lambda frame: frame_processor.recv(frame),
    )

    if webrtc_ctx.state.playing:
        if st.session_state.liveness_start_time is None:
            st.session_state.liveness_start_time = time.time()

        elapsed = time.time() - st.session_state.liveness_start_time
        remaining = max(0, duration_seconds - int(elapsed))

        st.success(f"🎥 Recording... {remaining}s remaining")

        # Drain queue into session state (non-blocking, minimal overhead)
        try:
            while True:
                frame = frame_queue.get_nowait()
                st.session_state.liveness_frames.append(frame)
        except queue.Empty:
            pass

        frame_count = len(st.session_state.liveness_frames)
        if frame_count > 0:
            st.write(f"📹 {frame_count} frames")

        # If time exceeded, stop recording
        if elapsed >= duration_seconds:
            st.info("⏹️ Time reached—click STOP or submit")
        else:
            st.rerun()

    else:
        elapsed = (
            time.time() - st.session_state.liveness_start_time
            if st.session_state.liveness_start_time
            else 0
        )
        st.session_state.liveness_start_time = None

        st.info("👆 Click START, allow camera, move head")

        if st.session_state.liveness_frames:
            st.success(f"✅ {len(st.session_state.liveness_frames)} frames captured")
            return st.session_state.liveness_frames

    return None
