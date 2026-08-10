## Description

<!-- What does this PR do? Why? Link any related issues. -->

Closes #

---

## Type of change

<!-- Check all that apply -->

- [ ] 🐛 Bug fix
- [ ] ✨ New feature
- [ ] ♻️ Refactor (no behaviour change)
- [ ] 🔒 Security fix
- [ ] 🧪 Tests only
- [ ] 📝 Docs / comments only
- [ ] 🏗️ Infrastructure / CI

---

## Changes made

<!-- Brief bullet list of what changed and where -->

-
-

---

## Testing

<!-- How was this tested? Pre-commit hooks run automatically — note anything beyond that. -->

- [ ] `poetry run inv test --unit` passes
- [ ] `poetry run inv test --integration` passes
- [ ] `poetry run inv lint` passes clean
- [ ] Manually tested locally (describe below if relevant)

**Manual test notes:**

---

## Security checklist

<!-- Required for any PR touching auth, tokens, routes, or secrets -->

- [ ] No secrets, credentials, or API keys in committed files
- [ ] `.env` remains gitignored — only `.env.example` with placeholders is committed
- [ ] New routes have `@rate_limit(key=…)` and `dependencies=[Depends(bearer)]`
- [ ] New `TokenError` call sites are wrapped in `try/except TokenError`
- [ ] Subprocess calls have an explicit `timeout=`
- [ ] `pty=False` on any new `inv` serve/client-style tasks (avoids macOS nvm PATH issue)

---

## For routes / API changes

- [ ] Swagger docs updated (summary, response model, tags)
- [ ] Integration test covers: happy path (2xx), missing token (401), step-up redirect (307) if applicable
- [ ] Audit log write is not bypassable on `/photo` or any new verification endpoint

---

## Screenshots / output

<!-- Paste token output, curl response, Swagger screenshot, etc. if helpful -->

<details>
<summary>Example output</summary>

```
# paste here
```

</details>
