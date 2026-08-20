"""OpenCV-based video liveness detection for anti-spoofing."""

import cv2
import numpy as np


def detect_faces_in_frame(frame, cascade_path=None):
    """Detect faces using Haar cascade classifier."""
    if cascade_path is None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"

    face_cascade = cv2.CascadeClassifier(cascade_path)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    return faces


def compute_laplacian_variance(frame):
    """Compute Laplacian variance (higher = sharper/more detailed = more likely real)."""
    if len(frame.shape) == 3:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    laplacian = cv2.Laplacian(frame, cv2.CV_64F)
    variance = laplacian.var()
    return variance


def compute_optical_flow(prev_frame, curr_frame):
    """Compute optical flow magnitude (measures motion)."""
    if len(prev_frame.shape) == 3:
        prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
        curr_gray = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)
    else:
        prev_gray = prev_frame
        curr_gray = curr_frame

    flow = cv2.calcOpticalFlowFarneback(prev_gray, curr_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    magnitude = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
    return magnitude.mean()


def analyze_video_liveness(frames: list, confidence_threshold: float = 0.6) -> dict:
    """
    Analyze video frames for liveness detection.

    Args:
        frames: List of cv2 frames (numpy arrays)
        confidence_threshold: Minimum confidence to pass liveness check

    Returns:
        dict with is_live, confidence, signals, frame_count
    """
    if not frames or len(frames) < 3:
        return {
            "is_live": False,
            "confidence": 0.0,
            "signals": ["Insufficient frames"],
            "frame_count": len(frames) if frames else 0,
        }

    signals = []
    confidence = 0.0

    # Check 1: Face detection in frames (should detect face consistently)
    face_detection_rate = 0.0
    faces_detected_count = 0

    for frame in frames:
        try:
            faces = detect_faces_in_frame(frame)
            if len(faces) > 0:
                faces_detected_count += 1
        except Exception:
            pass

    face_detection_rate = faces_detected_count / len(frames) if frames else 0

    if face_detection_rate > 0.6:
        signals.append(f"Face detected in {face_detection_rate:.0%} of frames")
        confidence += 0.25
    else:
        return {
            "is_live": False,
            "confidence": 0.0,
            "signals": ["Face not consistently detected"],
            "frame_count": len(frames),
        }

    # Check 2: Laplacian variance (image sharpness/detail)
    laplacian_variances = []
    for frame in frames:
        try:
            var = compute_laplacian_variance(frame)
            laplacian_variances.append(var)
        except Exception:
            pass

    if laplacian_variances:
        avg_sharpness = np.mean(laplacian_variances)
        # Real video typically has variance > 100; printed photos < 50
        if avg_sharpness > 100:
            signals.append(f"High image sharpness ({avg_sharpness:.0f})")
            confidence += 0.25
        elif avg_sharpness > 50:
            signals.append(f"Moderate image sharpness ({avg_sharpness:.0f})")
            confidence += 0.15

    # Check 3: Motion consistency (optical flow between consecutive frames)
    optical_flows = []
    for i in range(len(frames) - 1):
        try:
            flow = compute_optical_flow(frames[i], frames[i + 1])
            optical_flows.append(flow)
        except Exception:
            pass

    if optical_flows:
        avg_motion = np.mean(optical_flows)
        motion_consistency = 1.0 - (np.std(optical_flows) / (avg_motion + 1e-6))
        motion_consistency = max(0, min(1, motion_consistency))

        if avg_motion > 1.0:
            signals.append(f"Natural motion detected (flow: {avg_motion:.2f})")
            confidence += 0.25

            if motion_consistency > 0.5:
                signals.append("Consistent motion pattern")
                confidence += 0.1

    confidence = min(confidence, 1.0)
    is_live = confidence >= confidence_threshold and len(signals) >= 2

    return {
        "is_live": is_live,
        "confidence": round(confidence, 3),
        "signals": signals,
        "frame_count": len(frames),
        "avg_sharpness": round(np.mean(laplacian_variances), 1) if laplacian_variances else 0,
        "avg_motion": round(np.mean(optical_flows), 3) if optical_flows else 0,
    }
