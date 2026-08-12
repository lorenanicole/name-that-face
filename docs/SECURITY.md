# Security Testing & Pentest Documentation

This document covers the security testing strategy for the Name-that-face service, including the regression test suite, key vulnerabilities, and how to validate the 2FA flow end-to-end.

---

## Overview

The Name-that-face service enforces multiple layers of security:

1. **JWT authentication** — All API requests require a signed bearer token
2. **Scope enforcement** — Tokens are scoped (`user:read`, `user:write`, `admin:admin`) and validated per endpoint
3. **Step-up authentication** — Write operations require 2FA approval (Duo push) before issuing an elevated token
4. **IP binding** — 2FA challenges are bound to the client IP and validated on login
5. **Rate limiting** — Token bucket rate limiter prevents resource exhaustion
6. **Audit logging** — All sensitive operations logged to `logs/audit_log.jsonl`

---

## Security Test Suite

The repository includes six regression tests that probe candidate vulnerabilities. These tests run automatically as part of the pytest suite.

### Running the Security Tests

```bash
# Run all 6 security tests
poetry run pytest tests/integration/test_security_pentest.py -v

# Run a single test
poetry run pytest tests/integration/test_security_pentest.py::test_weak_secret_key -v
```

The test suite uses FastAPI's `TestClient` — no running server needed. Tests import the real app, real settings, and token config.

---

## The Six Vulnerabilities

| # | Test Name | What It Tests | Consequence if VULNERABLE |
|---|-----------|---------------|---------------------------|
| 1 | **WEAK/DEFAULT SECRET_KEY** | Hardcoded default secret allows forging any token | Attacker can forge `admin:admin` tokens and access protected endpoints |
| 2 | **JWT alg=none** | Algorithm confusion — `alg: "none"` bypasses signature verification | Unsigned tokens accepted, full authentication bypass |
| 3 | **STEP-UP IP BINDING** | 2FA challenge bound to client IP; login endpoint must validate it | Attacker can complete 2FA from a different IP than challenge was issued |
| 4 | **SCOPE ENFORCEMENT** | Token's scope validated against endpoint's required scope | `user:read` token accepted on `user:write` endpoint |
| 5 | **READ ENDPOINT** | Read operations should not require step-up flag | Read endpoint allows access without 2FA |
| 6 | **INVALID TOKEN** | Malformed/tampered tokens rejected cleanly | Invalid token accepted or causes 500 error |

### Test Details

#### 1. WEAK/DEFAULT SECRET_KEY
**File:** `tests/integration/test_security_pentest.py:test_weak_secret_key()`

**What it tests:** Verifies that `settings.py` clearly documents any default secret as a placeholder requiring `.env` override.

The test scans `settings.py` for the weak default secret string. If found, it confirms:
1. The secret string says "replace-me" (clearly marked as a placeholder)
2. The context mentions "env" (indicating it will be overridden by environment variables)

This is a *baseline configuration check*—it ensures developers don't accidentally leave weak defaults baked into the code logic, and that the documentation is clear about requiring `.env`.

**Protection:** 
- `settings.py` defines `SECRET_KEY` with the placeholder default
- `.env` (git-ignored) must be created locally with a strong key
- CI generates a random strong key for testing
- Production `.env` uses a cryptographically strong key

**Reference:** `src/settings.py:20` (SECRET_KEY default), `.env` (production secret).

---

#### 2. JWT alg=none
**File:** `tests/integration/test_security_pentest.py:test_jwt_alg_none()`

JWT spec allows `alg: "none"` — an unsigned token. PyJWT and `jwt.decode()` must be configured to reject this.

The test creates a token with `algorithm="none"` and attempts to POST `/api/fraud/detect`. If accepted, the service is vulnerable.

**Protection:** `jwt.decode()` uses `algorithms=[ALGORITHM]` (hardcoded to `["HS256"]`), rejecting `alg=none`.

**Reference:** `src/token_service.py:36` (validate_token).

---

#### 3. STEP-UP IP BINDING
**File:** `tests/integration/test_security_pentest.py:test_step_up_ip_binding()`

When a write operation requires step-up, the service generates a challenge token bound to the client IP. The challenge is valid only for that IP.

The test:
1. Triggers a 2FA challenge on a write endpoint
2. Extracts the challenge from the 307 Location header
3. Attempts to use the challenge from a **different** client IP
4. Expects a 401 error with "client ip" in the message

**Protection:**
- `src/rate_limiter.py` — Resolves client IP and binds it to the challenge
- `src/app.py:104-113` — `login_2fa()` endpoint validates incoming request IP matches challenge's bound IP

**Reference:** `src/models.py:54` (TokenClaims.client_ip), `src/token_service.py:109` (challenge payload).

---

#### 4. SCOPE ENFORCEMENT
**File:** `tests/integration/test_security_pentest.py:test_scope_enforcement()`

Each token carries a `scope` claim (e.g., `user:read`, `user:write`, `admin:admin`). Endpoints validate that the token's scope matches their required scope.

The test forges a `user:read` token and attempts a `user:write` operation (POST /api/user/{id}). Should reject with 401 and "scope" in the error message.

**Protection:** `src/app.py` routes decorated with `@rate_limit(required_scope="...")` validate scope via `token_service.validate_token(token, required_scope="...")`.

**Reference:** `src/token_service.py:42-44` (scope validation), `config/config.yml` (scope definitions).

---

#### 5. READ ENDPOINT
**File:** `tests/integration/test_security_pentest.py:test_read_endpoint_no_step_up()`

Read operations (e.g., `GET /api/user/{id}`) should not require the `step_up` flag. Write operations do.

The test forges a `user:read` token with `step_up=False` and GETs `/api/user/{id}`. Should return 200 OK.

**Protection:** Read endpoints (`GET` routes) require only `user:read` scope; write endpoints (`POST` routes) require `user:write` scope **and** the token must have been issued after 2FA approval (`step_up=True`).

**Reference:** `src/app.py` (endpoint definitions and their scopes).

---

#### 6. INVALID TOKEN
**File:** `tests/integration/test_security_pentest.py:test_invalid_token()`

Malformed tokens (e.g., `invalid.token.here`) should be rejected with a 401 error, not accepted or cause a 500.

The test sends a bad token to `GET /api/user/{id}` and expects 401.

**Protection:** `src/token_service.py:35-40` catches `jwt.InvalidTokenError` and raises `TokenError` (caught by FastAPI as 401).

---

## Running the Tests

### Prerequisite: .env is Required

The security tests **must** have access to `.env` to validate the actual `SECRET_KEY` in use.

```bash
cp .env.example .env
# Fill in: DUO_INTEGRATION_KEY, DUO_SECRET_KEY, DUO_API_HOST, SECRET_KEY
```

**Why:** The `test_weak_secret_key()` test reads `ACTUAL_SECRET` from `Settings()`, which loads from `.env`. This test validates that your deployed secret is **not** the weak default. If `.env` is missing or `SECRET_KEY` is not set, the app falls back to a hardcoded default—which the test will catch as a vulnerability.

Without `.env`, the test cannot determine what secret is actually in use and cannot provide reliable validation.

### Run All Tests
```bash
poetry run pytest tests/integration/test_security_pentest.py -v
```

### Run Individual Test
```bash
poetry run pytest tests/integration/test_security_pentest.py::test_weak_secret_key -v
```

### Expected Output
```
test_weak_secret_key PASSED
test_jwt_alg_none PASSED
test_step_up_ip_binding PASSED
test_scope_enforcement PASSED
test_read_endpoint_no_step_up PASSED
test_invalid_token PASSED

====== 6 passed in 0.45s ======
```

If any test fails, the service is vulnerable to that attack. The test will print a detailed error message.

---

## End-to-End 2FA Validation

The `scripts/validate_2fa_flow.py` script manually exercises the complete 2FA flow: token generation → step-up challenge → Duo push → elevated token → protected endpoint.

### Usage

**Mock mode** (auto-approves Duo push, no phone needed):
```bash
poetry run python scripts/validate_2fa_flow.py --mock-duo
```

**Real Duo mode** (sends push to your phone):
```bash
# Start the server
poetry run inv serve

# In another terminal, run the script
poetry run python scripts/validate_2fa_flow.py
```

### What It Does

1. **Step 1** — POST `/api/user/{user_id}` with a `user:write` token (not elevated)
   - Server responds with 307 redirect and a signed challenge token
   - Challenge is bound to the client IP that the server observes

2. **Step 2** — POST `/login-2fa` with the challenge token
   - Real mode: Sends Duo push to your phone; wait 2 minutes for approval
   - Mock mode: Auto-approves immediately
   - Server returns `elevated_token` (with `step_up=True`) and `redirect_to` URL

3. **Step 3** — POST `redirect_to` with the elevated token
   - Server accepts the elevated token and processes the user update
   - Returns 200 OK with the final result

### IP Binding Behavior

For **localhost testing**, the server sees `127.0.0.1` (loopback), which Duo cannot geolocate. The Duo push will show location as **"unknown"**. This is expected and harmless — the security feature (IP binding) still works perfectly.

**To see your real location in Duo:**

Option A: Use your machine's local IP
```bash
poetry run uvicorn src.app:app --host 0.0.0.0 --port 8000
BASE_URL=http://192.168.1.100:8000 poetry run python scripts/validate_2fa_flow.py
```

Option B: Use ngrok for a real public IP
```bash
ngrok http 8000
BASE_URL=https://abc123.ngrok.io poetry run python scripts/validate_2fa_flow.py
```

---

## Key Implementation Details

### JWT Claims Structure

**Access Tokens** (issued by `token_service.issue()`):
```json
{
  "sub": "user_id",
  "username": "alice@example.com",
  "scope": "user:write",
  "step_up": true,
  "exp": 1691234567
}
```

**Challenge Tokens** (issued by `token_service.issue_step_up_challenge()`):
```json
{
  "type": "set_up_challenge",
  "sub": "user_id",
  "username": "alice@example.com",
  "client_ip": "203.0.113.5",
  "required_scope": "user:write",
  "next": "/api/user/{user_id}",
  "exp": 1691234567
}
```

Note: Challenge tokens use JWT standard claim names (`type`, `sub`, `next`, `exp`). The `TokenClaims` model maps these via Pydantic field aliases to clear property names (`claim_type`, `user_id`, `next_url`, `token_expires_at`).

### Rate Limiter & IP Resolution

`src/rate_limiter.py` resolves the client IP from:
1. `x-forwarded-for` header (if behind a proxy/load balancer)
2. `request.client.host` (direct connection)

This resolved IP is bound to the challenge token. When the client calls `/login-2fa`, the same IP must be used.

### Scope & Step-Up Validation

Every route is decorated with `@rate_limit(required_scope="...")`:
```python
@app.post("/api/user/{user_id}", response_model=UserResponse)
@rate_limit(required_scope="user:write")
def update_user(user_id: str, request: Request, user_data: UserRequest):
    ...
```

If the token lacks the required scope or step_up flag is missing for write endpoints, the decorator returns a 401 with a clear error message.

---

## CI/CD Configuration

The security tests run in GitHub Actions CI and require environment variables:

### Environment Variables Needed

- `SECRET_KEY` — Strong cryptographic key (not the weak default)
- `DUO_INTEGRATION_KEY`, `DUO_SECRET_KEY`, `DUO_API_HOST` — Duo credentials (mocked in tests, but env vars must exist)

### Current Setup (.github/workflows/ci.yml)

The CI workflow generates random secrets before each test run:
```yaml
- name: Generate test secrets
  run: |
    echo "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" >> $GITHUB_ENV
    echo "DUO_INTEGRATION_KEY=test_ikey" >> $GITHUB_ENV
    echo "DUO_SECRET_KEY=test_skey" >> $GITHUB_ENV
    echo "DUO_API_HOST=api-test.duosecurity.com" >> $GITHUB_ENV
```

This ensures `test_weak_secret_key()` always passes (the generated key is strong), and all integration tests run successfully.

### For Production CI/CD

To validate against your production secrets (recommended):

1. Store real secrets in GitHub Settings → Secrets and variables
2. Update the workflow to use them:
   ```yaml
   - name: Load production secrets
     env:
       SECRET_KEY: ${{ secrets.PROD_SECRET_KEY }}
       DUO_INTEGRATION_KEY: ${{ secrets.PROD_DUO_IKEY }}
       DUO_SECRET_KEY: ${{ secrets.PROD_DUO_SKEY }}
       DUO_API_HOST: ${{ secrets.PROD_DUO_API_HOST }}
     run: poetry run inv test --integration
   ```

This way, the security tests validate against the exact keys that will be deployed.

---

## Security Checklist

Before deploying to production:

- [ ] `.env` contains a **strong cryptographic `SECRET_KEY`** (32+ byte base64 string)
- [ ] `.env` is **NOT committed to git** (listed in `.gitignore`)
- [ ] Duo Auth API credentials are **valid and secret**
- [ ] All 6 security tests **PASS**
- [ ] Endpoint scopes and step-up flags are **correct** per your threat model
- [ ] Audit logs are **persisted securely** (encrypted at rest if in the cloud)
- [ ] Logs are **rotated** to prevent unbounded disk usage
- [ ] TLS/HTTPS is **enforced** in production (via load balancer or reverse proxy)
- [ ] Rate limiter **thresholds** are tuned to your expected load

---

## References

- **JWT Specification:** [RFC 7519](https://tools.ietf.org/html/rfc7519)
- **Duo Security Auth API:** https://duo.com/docs/authapi
- **PyJWT Library:** https://pyjwt.readthedocs.io/
- **OWASP Authentication Cheat Sheet:** https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html

---

## Questions or Issues?

If you find a security issue or have questions:

1. Run the security tests: `poetry run pytest tests/integration/test_security_pentest.py -v`
2. Check endpoint scopes in `config/config.yml`
3. Verify `.env` is configured correctly
4. Enable debug logging: `LOG_LEVEL=DEBUG poetry run inv serve`
5. Review the audit log: `cat logs/audit_log.jsonl | jq '.'`
