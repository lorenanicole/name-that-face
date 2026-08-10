# Name-that-face 🔍

Deepfake detection as a service. Upload a selfie and a government ID photo — [DeepFace](https://github.com/serengil/deepface) (ArcFace model) verifies the faces match. Every request goes through Duo 2FA step-up authentication and a token-bucket rate limiter.

---

## Requirements

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.12 | Main app and deepface venv |
| Poetry | ≥ 2.0 | Dependency management |
| Docker + Docker Compose | ≥ 27 | Containerised deployment |
| ngrok | ≥ 3 | Expose local ports over HTTPS |
| Duo account | any | Free trial works; needs Auth API application |

---

## Project structure

```
name-that-face/
├── src/
│   ├── app.py                      # FastAPI routes + Swagger config
│   ├── client.py                   # Streamlit front-end
│   ├── dependencies.py             # Singleton wiring (settings, duo, services)
│   ├── fraud_detection_service.py  # DeepFace wrapper (subprocess)
│   ├── logging_config.py           # structlog (pretty dev / JSON prod)
│   ├── models.py                   # Pydantic request/response models
│   ├── rate_limiter.py             # Token-bucket rate limiter + @rate_limit
│   ├── settings.py                 # Pydantic settings (env vars / .env)
│   └── token_service.py            # JWT issue / validate / refresh + TokenError
├── tests/
│   ├── conftest.py                 # Shared JWT fixtures
│   ├── unit/                       # @pytest.mark.unit — fast, no I/O (~0.7s)
│   │   ├── test_token_bucket.py
│   │   ├── test_token_service.py
│   │   ├── test_fraud_detection.py
│   │   ├── test_models.py
│   │   └── test_settings.py
│   └── integration/                # @pytest.mark.integration — full FastAPI
│       ├── test_api_auth.py
│       ├── test_api_2fa.py
│       └── test_api_photo.py
├── config/config.yml               # Token types, scopes, rate-limit config
├── scripts/validate_2fa_flow.py    # Manual end-to-end 2FA script
├── tasks.py                        # Invoke task runner (inv serve, inv test …)
├── token_task.py                   # Logic for inv token
├── pyproject.toml                  # Poetry + pytest + ruff config
├── .pre-commit-config.yaml         # Pre-commit hooks (ruff + tests)
├── deepface-requirements.txt       # Pinned deps for the isolated deepface venv
├── Dockerfile / Dockerfile.client  # Multi-stage API + Streamlit containers
├── docker-compose.yml              # Wires api + client services
├── .env.example                    # Safe template — copy to .env
└── logs/audit_log.jsonl            # Append-only audit log (auto-created)
```

---

## Local development setup

### 1. Configure environment

```bash
cp .env.example .env
# Fill in: DUO_INTEGRATION_KEY, DUO_SECRET_KEY, DUO_API_HOST, SECRET_KEY
```

### 2. Install dependencies

```bash
poetry install
poetry run python --version   # Python 3.12.x
```

### 3. Set up the DeepFace venv (one-time, ~5 min)

DeepFace + TensorFlow run in a **separate** Python 3.12 venv — TensorFlow is incompatible with Python 3.13 and too heavy to run in the main process.

```bash
python3.12 -m venv /Users/lorenamesa/Workspace/deepface-venv
source /Users/lorenamesa/Workspace/deepface-venv/bin/activate
pip install -r deepface-requirements.txt
deactivate

# Verify
/Users/lorenamesa/Workspace/deepface-venv/bin/python \
  -c "from deepface import DeepFace; print('DeepFace OK')"
```

> **First request:** ArcFace model weights (~600 MB) download to `~/.deepface/weights/` on first use.

### 4. Install pre-commit hooks

```bash
poetry run python -m pre_commit install --hook-type pre-commit --hook-type pre-push
```

---

## Task runner — `inv`

All developer workflows go through [Invoke](https://www.pyinvoke.org/).

```bash
poetry run inv --list   # show all available tasks
```

### Servers

| Command | What it does |
|---------|-------------|
| `poetry run inv serve` | FastAPI on `http://127.0.0.1:8000` (hot-reload) |
| `poetry run inv client` | Streamlit UI on `http://localhost:8501` |

### ngrok

| Command | What it does |
|---------|-------------|
| `poetry run inv ngrok` | Tunnel Streamlit (`:8501`) to a public HTTPS URL |
| `poetry run inv ngrok --port 8000` | Tunnel the API instead |
| `poetry run inv ngrok --url` | Print the current public ngrok URL |

### Token generation

Generate signed JWTs for `curl` testing and Swagger UI authorization.

| Command | Scope | Notes |
|---------|-------|-------|
| `poetry run inv token` | `user:read` | Default — 30 min TTL |
| `poetry run inv token --scope user:write --step-up` | `user:write` | step_up=True required for write endpoints |
| `poetry run inv token --scope admin:admin --step-up` | `admin:admin` | Full admin access |
| `poetry run inv token --ttl 120` | `user:read` | Custom TTL in minutes |
| `poetry run inv token --user-id alice --username alice@example.com` | `user:read` | Custom identity |
| `poetry run inv token --list-scopes` | — | Print all 17 valid scopes from `config.yml` |

Every call prints a summary table, the raw JWT, and a ready-to-paste `curl` example.

### Testing

| Command | What it does |
|---------|-------------|
| `poetry run inv test` | All 67 tests |
| `poetry run inv test --unit` | 49 unit tests (~0.7s, no I/O) |
| `poetry run inv test --integration` | 18 integration tests (full FastAPI) |
| `poetry run inv test --coverage` | All tests + HTML report in `htmlcov/` |
| `poetry run inv test --verbose` | Any of the above with `-v` |

### Linting & formatting

| Command | What it does |
|---------|-------------|
| `poetry run inv lint` | `ruff check src/ tests/` |
| `poetry run inv fmt` | `ruff format src/ tests/` |

---
## Pre-commit hooks

Installed into `.git/hooks/` — run automatically on `git commit` and `git push`.

| Hook | Trigger | What it does |
|------|---------|-------------|
| `ruff` | commit | Lint + auto-fix |
| `ruff-format` | commit | Auto-format |
| `unit tests` | commit | 49 unit tests (`-m unit`) |
| `integration tests` | push | 18 integration tests (`-m integration`) |

If ruff modifies files, stage them and re-commit. Tests must pass before commit/push completes.

**Re-install after cloning:**
```bash
poetry install
poetry run python -m pre_commit install --hook-type pre-commit --hook-type pre-push
```

**Skip in an emergency:**
```bash
git commit --no-verify
git push --no-verify
```

---

## Swagger UI

Interactive docs: **http://localhost:8000/docs**

1. `poetry run inv token` — copy the JWT
2. Click **Authorize 🔒** (top-right)
3. Paste the token → **Authorize** → try any endpoint from the browser

---

## ngrok setup (mobile / public access)

```bash
brew install ngrok
ngrok config add-authtoken <YOUR_AUTHTOKEN>   # one-time setup

poetry run inv ngrok          # start tunnel on :8501
poetry run inv ngrok --url    # print the URL
```

Open the public URL on your phone to run the full Duo push → selfie → gov ID flow.

---

## Docker deployment

```bash
docker compose up --build    # first run (~10 min — TensorFlow layer)
docker compose up            # subsequent runs
docker compose down          # stop
docker compose logs -f api   # tail JSON logs
```

| Service | Port | Description |
|---------|------|-------------|
| `api` | 8000 | FastAPI — rate limiter, Duo 2FA, DeepFace |
| `client` | 8501 | Streamlit front-end |

### Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DUO_INTEGRATION_KEY` | ✅ | — | Duo Auth API integration key |
| `DUO_SECRET_KEY` | ✅ | — | Duo Auth API secret key |
| `DUO_API_HOST` | ✅ | — | e.g. `api-xxxxxxxx.duosecurity.com` |
| `SECRET_KEY` | ✅ | insecure default | JWT signing secret |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | | `30` | JWT TTL |
| `DEEPFACE_PYTHON` | | `/opt/deepface-venv/bin/python` | Set automatically in Docker |
| `AUDIT_LOG_PATH` | | `/app/logs/audit_log.jsonl` | Set automatically in Docker |
| `LOG_FORMAT` | | `pretty` / `json` in Docker | `pretty` or `json` |
| `LOG_LEVEL` | | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `API_BASE_URL` | | `http://api:8000` | URL the Streamlit client calls |

---

## Duo Security setup

1. Log in to https://admin.duosecurity.com
2. **Applications → Protect an Application → Auth API → Protect**
3. Copy **Integration key**, **Secret key**, **API hostname** into `.env`
4. Under **Users**, add a user matching `USERNAME` in `src/client.py` (default: `me@lorenamesa.com`) and enroll a device

---

## API reference

Interactive docs: **http://localhost:8000/docs**

| Method | Path | Scope | Description |
|--------|------|-------|-------------|
| `GET` | `/api/user/{user_id}` | `user:read` | Get user info from JWT claims |
| `POST` | `/api/user/{user_id}` | `user:write` + step_up | Update user — 307 to 2FA if not elevated |
| `POST` | `/login-2fa` | challenge token | Complete Duo push; returns elevated JWT |
| `POST` | `/api/user/{user_id}/photo` | `user:write` + step_up | Selfie + gov ID → DeepFace result + audit log |
| `POST` | `/api/fraud/detect` | `admin:admin` + step_up | Raw fraud detection on image/video/base64 |

---

## Audit log

Every `/photo` call appends one JSON line to `logs/audit_log.jsonl`:

```json
{"user_id":"1","selfie_hash":"52a9f0...","gov_id_hash":"aadc83...","verified":true,"confidence":0.555,"analyzed_at":"2026-08-10T19:34:55+00:00"}
```

```bash
cat logs/audit_log.jsonl | jq 'select(.verified == false)'   # failures
cat logs/audit_log.jsonl | jq 'select(.user_id == "1")'      # by user
```

---

## Logging

Structured logs via [structlog](https://www.structlog.org/).

**Development** (`LOG_FORMAT=pretty`):
```
2026-08-10T19:43:29Z [info] audit_log.written [app] user_id=1 verified=True confidence=0.555
```

**Production / Docker** (`LOG_FORMAT=json`):
```json
{"user_id":"1","verified":true,"event":"audit_log.written","level":"info","logger":"app","timestamp":"2026-08-10T19:43:29Z"}
```

Override at runtime: `LOG_LEVEL=DEBUG poetry run inv serve`
