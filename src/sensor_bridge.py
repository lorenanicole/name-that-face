"""Bridge DeviceMotionEvent to Streamlit via custom HTML component."""

import streamlit.components.v1 as components


def motion_sensor_bridge(
    duration_seconds: int = 5, auth_token: str = "", user_id: str = "", api_url: str = ""
):
    """
    Capture device motion data (accelerometer + gyroscope) and video frames.
    Sends frames to server for OpenCV analysis.

    Args:
        duration_seconds: How long to collect sensor data (default 5 seconds)
        auth_token: Bearer token for server requests
        user_id: User ID for frame upload
        api_url: Base API URL (e.g., http://127.0.0.1:8000)

    Returns:
        None (renders component)
    """
    # Escape for safe JavaScript injection
    token_safe = auth_token.replace('"', '\\"') if auth_token else ""
    api_url_safe = (api_url or "http://127.0.0.1:8000").replace('"', '\\"')
    user_id_safe = (user_id or "").replace('"', '\\"')
    js_code = f"""
    <div id="sensor-container" style="font-family: sans-serif; padding: 10px;">
        <video id="video-preview" autoplay muted playsinline style="display: none; width: 100%; max-width: 300px; border-radius: 5px; margin-bottom: 10px;"></video>
        <button id="start-btn" style="padding: 10px 20px; font-size: 14px; cursor: pointer;
                                      background: #4CAF50; color: white; border: none; border-radius: 5px;">
            🎬 Start Motion Detection ({duration_seconds}s)
        </button>
        <div id="sensor-status" style="font-size: 14px; color: gray; margin-top: 10px;"></div>
        <div id="motion-stats" style="font-size: 12px; color: #666; margin-top: 5px;"></div>
        <div id="frame-status" style="font-size: 12px; color: #666; margin-top: 5px;"></div>
        <div id="liveness-result" style="display: none; margin-top: 10px; padding: 10px; background: #f0f0f0; border-radius: 5px;"></div>
        <button id="confirm-btn" style="display: none; padding: 10px 20px; font-size: 14px; cursor: pointer;
                                        background: #2196F3; color: white; border: none; border-radius: 5px; margin-top: 10px;">
            ✅ Confirm & Continue
        </button>
    </div>

    <script>
    (function() {{
        const startBtn = document.getElementById("start-btn");
        const confirmBtn = document.getElementById("confirm-btn");
        const statusDiv = document.getElementById("sensor-status");
        const motionStats = document.getElementById("motion-stats");
        const resultDiv = document.getElementById("liveness-result");
        const videoPreview = document.getElementById("video-preview");

        let motionData = [];
        let videoFrames = [];
        let startTime = null;
        let isCollecting = false;
        let stream = null;
        let canvas = null;
        let ctx = null;
        let frameInterval = null;

        startBtn.addEventListener("click", async () => {{
            startBtn.disabled = true;
            startBtn.textContent = "⏳ Requesting permissions...";

            try {{
                // Request motion permission first
                if (typeof DeviceMotionEvent !== "undefined" &&
                    typeof DeviceMotionEvent.requestPermission === "function") {{
                    const motionPerm = await DeviceMotionEvent.requestPermission();
                    if (motionPerm !== "granted") {{
                        statusDiv.textContent = "❌ Motion permission denied";
                        startBtn.textContent = "🎬 Start Motion Detection ({duration_seconds}s)";
                        startBtn.disabled = false;
                        return;
                    }}
                }}

                // Then request camera for video frames
                try {{
                    stream = await navigator.mediaDevices.getUserMedia({{ video: {{ facingMode: "user" }} }});
                    videoPreview.srcObject = stream;
                    videoPreview.style.display = "block";
                    videoPreview.style.width = "100%";
                    videoPreview.style.maxWidth = "300px";
                    videoPreview.autoplay = true;
                    videoPreview.playsInline = true;

                    // Wait for video to be ready - use explicit timeout
                    await new Promise((resolve, reject) => {{
                        let attempts = 0;
                        const checkReady = () => {{
                            if (videoPreview.videoWidth > 0 && videoPreview.videoHeight > 0) {{
                                console.log("Video ready:", videoPreview.videoWidth, "x", videoPreview.videoHeight);
                                resolve();
                            }} else if (attempts++ < 30) {{
                                setTimeout(checkReady, 100);
                            }} else {{
                                reject(new Error("Video timeout"));
                            }}
                        }};
                        checkReady();
                    }});

                    // Create canvas with proper dimensions
                    canvas = document.createElement("canvas");
                    ctx = canvas.getContext("2d");
                    canvas.width = videoPreview.videoWidth;
                    canvas.height = videoPreview.videoHeight;
                    console.log("Canvas created:", canvas.width, "x", canvas.height);
                }} catch (e) {{
                    // Camera permission failed, but motion should still work
                    console.warn("Camera not available:", e.message);
                }}

                startListening();
            }} catch (error) {{
                statusDiv.textContent = "❌ Error: " + error.message;
                console.error("Startup error:", error);
                startBtn.textContent = "🎬 Start Motion Detection ({duration_seconds}s)";
                startBtn.disabled = false;
            }}
        }});

        let listener = null;

        function captureFrame() {{
            if (!canvas || !ctx || !videoPreview) {{
                return;
            }}

            try {{
                // Ensure video is actually playing and has data
                if (videoPreview.paused || videoPreview.ended) {{
                    return;
                }}

                // Skip if dimensions are wrong
                if (videoPreview.videoWidth <= 0 || videoPreview.videoHeight <= 0) {{
                    return;
                }}

                // Update canvas to match video size if needed
                if (canvas.width !== videoPreview.videoWidth || canvas.height !== videoPreview.videoHeight) {{
                    canvas.width = videoPreview.videoWidth;
                    canvas.height = videoPreview.videoHeight;
                }}

                ctx.drawImage(videoPreview, 0, 0);
                const frameData = canvas.toDataURL("image/jpeg", 0.9);

                if (frameData && frameData.length > 500) {{  // At least 500 bytes
                    videoFrames.push(frameData);
                    if (videoFrames.length % 3 === 0) {{
                        const frameStatusDiv = document.getElementById("frame-status");
                        if (frameStatusDiv) {{
                            frameStatusDiv.textContent = "📹 Frames: " + videoFrames.length;
                        }}
                    }}
                }}
            }} catch (e) {{
                // Silently continue on error
                console.error("Frame error:", e.message);
            }}
        }}

        function startListening() {{
            isCollecting = true;
            startTime = Date.now();
            motionData = [];
            videoFrames = [];
            startBtn.textContent = "🟢 Recording...";
            statusDiv.textContent = "Move your head naturally!";

            // Capture frames frequently if camera available
            if (canvas && ctx) {{
                frameInterval = setInterval(captureFrame, 50);  // Capture every 50ms for more frames
                console.log("Frame capture started (50ms interval)");
            }} else {{
                console.warn("Camera not available or canvas not initialized");
            }}

            listener = (event) => {{
                if (!isCollecting) return;

                const elapsed = (Date.now() - startTime) / 1000;
                if (elapsed > {duration_seconds}) {{
                    stopListening();
                    return;
                }}

                const data = {{
                    timestamp: Date.now(),
                    elapsed: parseFloat(elapsed.toFixed(2)),
                    acceleration: {{
                        x: event.acceleration?.x || 0,
                        y: event.acceleration?.y || 0,
                        z: event.acceleration?.z || 0
                    }},
                    rotationRate: {{
                        alpha: event.rotationRate?.alpha || 0,
                        beta: event.rotationRate?.beta || 0,
                        gamma: event.rotationRate?.gamma || 0
                    }}
                }};

                motionData.push(data);

                const accelMag = Math.sqrt(
                    Math.pow(data.acceleration.x, 2) +
                    Math.pow(data.acceleration.y, 2) +
                    Math.pow(data.acceleration.z, 2)
                );
                const rotMag = Math.sqrt(
                    Math.pow(data.rotationRate.alpha, 2) +
                    Math.pow(data.rotationRate.beta, 2) +
                    Math.pow(data.rotationRate.gamma, 2)
                );

                motionStats.innerHTML =
                    `Samples: ${{motionData.length}} | Accel: ${{accelMag.toFixed(2)}} m/s² | Rotation: ${{rotMag.toFixed(2)}}°/s`;
            }};

            window.addEventListener("devicemotion", listener);
        }}

        function stopListening() {{
            isCollecting = false;
            if (frameInterval) {{
                clearInterval(frameInterval);
                console.log("Frame capture stopped");
            }}
            if (stream) {{
                stream.getTracks().forEach(t => t.stop());
                console.log("Camera stopped");
            }}
            if (listener) {{
                window.removeEventListener("devicemotion", listener);
                console.log("Motion listener removed");
            }}
            startBtn.textContent = "✅ Done";
            statusDiv.textContent = "✅ Motion data: " + motionData.length + " samples, Video: " + videoFrames.length + " frames";

            const liveness = analyzeMotion(motionData);
            const confidencePercent = (liveness.confidence * 100).toFixed(0);

            resultDiv.style.display = "block";
            if (liveness.is_live) {{
                resultDiv.innerHTML = `
                    <strong>✅ Motion Liveness Passed!</strong><br>
                    Confidence: ${{confidencePercent}}%<br>
                    Samples: ${{liveness.sample_count}}<br>
                    Signals: ${{liveness.signals.join(', ')}}<br>
                    <small>📹 Video frames: ${{videoFrames.length}} captured</small>
                `;
                resultDiv.style.background = "#c8e6c9";
                confirmBtn.style.display = "block";
                confirmBtn.textContent = "✅ Send for OpenCV Analysis";
                confirmBtn.disabled = false;
            }} else {{
                resultDiv.innerHTML = `
                    <strong>⚠️ Insufficient Motion</strong><br>
                    Confidence: ${{confidencePercent}}%<br>
                    Please try again with more natural head movement.
                `;
                resultDiv.style.background = "#ffccbc";
                confirmBtn.style.display = "none";
                startBtn.style.display = "block";
                startBtn.disabled = false;
                startBtn.textContent = "🎬 Try Again";
            }}

            console.log("Motion detection complete: " + videoFrames.length + " frames captured");
        }}

        function analyzeMotion(data) {{
            if (!data || data.length < 3) {{
                return {{ is_live: false, confidence: 0, signals: ["Insufficient data"], sample_count: data ? data.length : 0 }};
            }}

            const signals = [];
            let confidence = 0.0;

            const accelX = data.map(d => d.acceleration.x);
            const accelY = data.map(d => d.acceleration.y);
            const accelZ = data.map(d => d.acceleration.z);

            const rotAlpha = data.map(d => d.rotationRate.alpha);
            const rotBeta = data.map(d => d.rotationRate.beta);
            const rotGamma = data.map(d => d.rotationRate.gamma);

            function variance(arr) {{
                if (arr.length < 2) return 0;
                const mean = arr.reduce((a, b) => a + b, 0) / arr.length;
                return arr.reduce((sum, x) => sum + Math.pow(x - mean, 2), 0) / arr.length;
            }}

            const accelVar = variance(accelX) + variance(accelY) + variance(accelZ);
            if (accelVar > 0.5) {{
                signals.push("Natural acceleration detected");
                confidence += 0.4;
            }}

            const rotVar = variance(rotAlpha) + variance(rotBeta) + variance(rotGamma);
            if (rotVar > 5) {{
                signals.push("Natural rotation detected");
                confidence += 0.4;
            }}

            if (accelX.some(x => x !== 0) || accelY.some(x => x !== 0) || accelZ.some(x => x !== 0)) {{
                signals.push("Device motion detected");
                confidence += 0.2;
            }}

            if (rotAlpha.some(x => x !== 0) || rotBeta.some(x => x !== 0) || rotGamma.some(x => x !== 0)) {{
                signals.push("Device rotation detected");
                confidence += 0.2;
            }}

            const is_live = confidence >= 0.6 && signals.length >= 2;
            confidence = Math.min(confidence, 1.0);

            return {{ is_live, confidence: parseFloat(confidence.toFixed(3)), signals, sample_count: data.length }};
        }}

        confirmBtn.addEventListener("click", async () => {{
            confirmBtn.disabled = true;
            confirmBtn.textContent = "⏳ Storing frames...";
            statusDiv.innerHTML += `<br><small>📤 Preparing ${{videoFrames.length}} frames for server...</small>`;

            if (!videoFrames || videoFrames.length === 0) {{
                console.warn("No frames captured");
                statusDiv.innerHTML += `<br><small>⚠️ No video frames to upload</small>`;
                confirmBtn.textContent = "✅ Motion Passed (No Video)";
                return;
            }}

            try {{
                const api_url = "{api_url_safe}";
                const auth_token = "{token_safe}";
                const user_id = "{user_id_safe}";

                console.log("Auth token present:", auth_token.length > 0);
                console.log("User ID:", user_id);
                console.log("API URL:", api_url);
                console.log("Frames to send:", videoFrames.length);

                // Limit to 50 frames to avoid payload size
                const frames_to_send = videoFrames.slice(0, 50);

                statusDiv.innerHTML += `<br><small>📤 Uploading ${{frames_to_send.length}} frames...</small>`;

                const upload_response = await fetch(api_url + "/api/liveness/frames", {{
                    method: "POST",
                    headers: {{
                        "Content-Type": "application/json",
                        "Authorization": "Bearer " + auth_token
                    }},
                    body: JSON.stringify({{
                        frames_base64: frames_to_send,
                        user_id: user_id
                    }})
                }});

                console.log("Upload response status:", upload_response.status);

                if (!upload_response.ok) {{
                    const error_text = await upload_response.text();
                    console.error("Upload error:", error_text);
                    throw new Error("Upload failed: " + upload_response.status + " - " + error_text);
                }}

                const upload_result = await upload_response.json();
                console.log("Upload successful:", upload_result);
                statusDiv.innerHTML += `<br><small>✅ ${{upload_result.frame_count}} frames stored on server</small>`;

                confirmBtn.textContent = "✅ Frames Ready";
                confirmBtn.style.background = "#4CAF50";

            }} catch (e) {{
                console.error("Frame upload error:", e.message);
                statusDiv.innerHTML += `<br><small>❌ Upload error: ${{e.message}}</small>`;
                resultDiv.style.background = "#ffccbc";
                confirmBtn.textContent = "❌ Upload Failed";
                confirmBtn.style.background = "#f44336";
            }}
        }});
    }})();
    </script>
    """

    components.html(js_code, height=250)
