# =============================================================================
# Dockerfile — Name-that-face API (FastAPI + DeepFace)
#
# Multi-stage build:
#   stage 1 (deepface-builder): installs TensorFlow / DeepFace into an isolated
#            venv at /opt/deepface-venv using Python 3.12.
#   stage 2 (api): lean runtime image — copies the deepface venv in, then
#            installs only the FastAPI application deps via Poetry.
#
# The two venvs stay separate for the same reason as locally: TensorFlow's
# build/runtime requirements are kept completely out of the FastAPI process.
# fraud_detection_service.py calls /opt/deepface-venv/bin/python via subprocess.
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1 — build the deepface/TensorFlow venv
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS deepface-builder

WORKDIR /build

# System libs required by OpenCV, TensorFlow, and face-detection models
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Create isolated venv and install all deepface deps from the pinned lockfile
RUN python -m venv /opt/deepface-venv
COPY name-that-face/deepface-requirements.txt .
RUN /opt/deepface-venv/bin/pip install --upgrade pip \
    && /opt/deepface-venv/bin/pip install --no-cache-dir -r deepface-requirements.txt

# -----------------------------------------------------------------------------
# Stage 2 — lean FastAPI application image
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS api

# Same runtime system libs (OpenCV needs libgl1 at runtime too)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Bring in the pre-built deepface venv from stage 1
COPY --from=deepface-builder /opt/deepface-venv /opt/deepface-venv

WORKDIR /app

# Install Poetry (no venv inside container — we install deps globally)
RUN pip install --no-cache-dir poetry \
    && poetry config virtualenvs.create false

# Copy dependency manifests first for layer-cache efficiency
COPY name-that-face/pyproject.toml name-that-face/poetry.lock ./

# Install main + dev groups only (deepface group is optional and already in /opt/deepface-venv)
RUN poetry install --no-root --without deepface

# Copy application source, config, and the auth module from its sibling package
COPY name-that-face/src/ ./src/
COPY name-that-face/config/ ./config/

# Audit log directory — mounted as a volume so logs survive container restarts
RUN mkdir -p /app/logs
ENV AUDIT_LOG_PATH=/app/logs/audit_log.jsonl

# Tell fraud_detection_service.py where the isolated venv's python is
ENV DEEPFACE_PYTHON=/opt/deepface-venv/bin/python

# Structured JSON logs in production
ENV LOG_FORMAT=json

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/docs || exit 1

CMD ["uvicorn", "app:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
