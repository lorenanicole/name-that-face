# GitHub Copilot Code Review Instructions

This file configures Copilot's automated PR review behaviour for the
**Name-that-face** project — a deepfake detection API built with FastAPI,
Duo 2FA, DeepFace/ArcFace, and a token-bucket rate limiter.

---

## Project context

| Layer | Technology |
|-------|-----------|
| API server | FastAPI (Python 3.12), uvicorn |
| Front-end | Streamlit |
| Auth | PyJWT HS256, Duo Security push (step-up 2FA) |
| Rate limiting | Custom token-bucket (`rate_limiter.py`) driven by `config/config.yml` |
| ML inference | DeepFace / ArcFace via subprocess in an isolated Python 3.12 venv |
| Structured logging | structlog — pretty in dev, JSON in prod/Docker |
| Task runner | Invoke (`tasks.py`) — `inv serve`, `inv client`, `inv token`, `inv ngrok`, `inv test`, `inv lint`, `inv fmt` |
| Tests | pytest — `@pytest.mark.unit` (fast, no I/O) and `@pytest.mark.integration` (full FastAPI via TestClient) |
| Pre-commit | ruff fix + format on commit; unit tests on commit; integration tests on push |

---

## Review priorities

### 🔴 Always flag

- **Secrets in code** — API keys, tokens, passwords, connection strings hardcoded anywhere other than `.env` (which is gitignored). `settings.py` defaults must be empty strings or obvious placeholders like `replace-me-…`.
- **Missing authentication** — any new route that lacks `@rate_limit(key=…)` and `dependencies=[Depends(bearer)]`.
- **Unhandled `TokenError`** — any call to `token_service.validate_token()` or `token_service.get_token()` not wrapped in `try/except TokenError`.
- **Subprocess injection** — `_run_deepface` builds a Python script string; flag any user-controlled input interpolated into it without sanitisation.
- **Audit log bypass** — the `/photo` endpoint must always write to `AUDIT_LOG_PATH`; flag any code path that skips it.
- **`pty=True` on `inv serve` / `inv client`** — causes `env: node: No such file or directory` on macOS with nvm. Keep these `pty=False`.

### 🟡 Flag if not justified

- **New `sys.path` manipulation** — `auth.py` is now co-located in `src/`; there should be no new `sys.path.insert` hacks.
- **Subprocess timeout absent** — `_run_deepface` uses `timeout=120`; any new subprocess call must have an explicit timeout.
- **`body.dict()` instead of `body.model_dump()`** — Pydantic v2 deprecation.
- **`datetime.utcnow()` / `datetime.utcfromtimestamp()`** — deprecated in Python 3.12; use `datetime.now(timezone.utc)` / `datetime.fromtimestamp(ts, tz=timezone.utc)`.
- **Tests missing a marker** — every test function must have `@pytest.mark.unit` or `@pytest.mark.integration`.
- **Integration test patching wrong namespace** — mock `duo_auth` and `fraud_service` at both `dependencies.*` and `app.*` to avoid stale references.

### 🟢 Style & conventions

- **Structlog keyword-arg style** — `logger.info("event.name", key=value)`, never f-strings or `extra={}`.
- **Import order** — stdlib → third-party → local, enforced by ruff. The only allowed `# noqa: E402` is on imports that follow a required `sys.path` block (there should be none of these left).
- **Route naming** — use `noun:verb` dot-notation for log event names (e.g. `fraud_detection.verify.started`).
- **No inline imports** — `import base64` etc. belong at the top of the file, not inside function bodies.
- **`AUDIT_LOG_PATH`** comes from `os.environ.get("AUDIT_LOG_PATH", …)` — never hardcoded.

---

## Test coverage expectations

| Module | Expected coverage |
|--------|------------------|
| `fraud_detection_service.py` | 100% |
| `models.py` | 100% |
| `settings.py` | 100% |
| `token_service.py` | ≥ 95% |
| `app.py` | ≥ 85% |
| `rate_limiter.py` | ≥ 75% |

New features must ship with tests. New routes need at minimum:
- One integration test for the happy path (200)
- One test for missing/invalid token (401)
- One test for the step-up redirect if the route requires `step_up=True` (307)

---

## Pre-commit hook behaviour

Copilot should expect CI to enforce the same gates as pre-commit:

1. `ruff check --fix` + `ruff format` on all changed files
2. `pytest -m unit` must pass on every commit
3. `pytest -m integration` must pass on every push/PR

Flag any PR where new code would cause either suite to fail.

---

## Security checklist for every PR

- [ ] No secrets, credentials, or PII in committed files
- [ ] `.env` remains gitignored; only `.env.example` (with placeholders) is committed
- [ ] All new routes have JWT validation via `@rate_limit` decorator
- [ ] All new routes declare `dependencies=[Depends(bearer)]` for Swagger
- [ ] Subprocess calls have explicit timeouts
- [ ] Temp files created in `_run_deepface` are deleted in `finally` blocks
- [ ] Audit log writes are inside a `try/except` so errors don't mask the HTTP response
