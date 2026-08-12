"""
tests/unit/test_rate_limiter_decorator.py

Unit tests for the client_ip resolution logic inside the rate_limit decorator.

Three cases are exercised:
  1. x-forwarded-for present  → first IP in the comma-separated list is used.
  2. No x-forwarded-for       → falls back to request.client.host.
  3. request.client is None   → AttributeError caught; client_ip defaults to "".

All external dependencies (token_service, token_config) are patched so these
tests run without any real JWT or config infrastructure.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import Request

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_request(headers: dict, client_host: str | None = "1.2.3.4") -> Request:
    """Return a minimal mock Request."""
    req = MagicMock(spec=Request)
    req.headers = headers
    if client_host is None:
        req.client = None
    else:
        req.client = MagicMock()
        req.client.host = client_host
    req.url = MagicMock()
    req.url.__str__ = lambda _: "http://test/api/user/u1/photo"
    return req


def _patch_dependencies(step_up: bool = False):
    """Return patches + the mock token_service for assertion."""
    claims = {"sub": "u1", "scope": "user:write", "step_up": step_up}

    mock_ts = MagicMock()
    mock_ts.get_token.return_value = "tok"
    mock_ts.validate_token.return_value = claims
    mock_ts.issue_step_up_challenge.return_value = "challenge-abc"

    mock_tc = MagicMock()
    mock_tc.token_permissions = {"user": {"daily_token_budget": 10_000}}
    mock_tc.get_scope_config.return_value = {"rpm": 60, "cost_min": 1, "cost_max": 1}

    return (
        [patch("rate_limiter.token_service", mock_ts), patch("rate_limiter.token_config", mock_tc)],
        mock_ts,
    )


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_client_ip_from_x_forwarded_for_single():
    """x-forwarded-for with one IP → that IP is passed to issue_step_up_challenge."""
    patches, mock_ts = _patch_dependencies(step_up=False)
    with patches[0], patches[1]:
        from rate_limiter import rate_limit

        @rate_limit("user:write")
        async def handler(request: Request):
            return {"ok": True}  # pragma: no cover

        await handler(request=_make_request({"x-forwarded-for": "10.0.0.1"}))

    _, kw = mock_ts.issue_step_up_challenge.call_args
    assert kw["client_ip"] == "10.0.0.1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_client_ip_from_x_forwarded_for_multiple():
    """x-forwarded-for with proxy chain → only the first (original client) IP is used."""
    patches, mock_ts = _patch_dependencies(step_up=False)
    with patches[0], patches[1]:
        from rate_limiter import rate_limit

        @rate_limit("user:write")
        async def handler(request: Request):
            return {"ok": True}  # pragma: no cover

        await handler(
            request=_make_request({"x-forwarded-for": "203.0.113.5, 10.1.1.1, 172.16.0.1"})
        )

    _, kw = mock_ts.issue_step_up_challenge.call_args
    assert kw["client_ip"] == "203.0.113.5"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_client_ip_falls_back_to_request_client_host():
    """No x-forwarded-for header → request.client.host is used."""
    patches, mock_ts = _patch_dependencies(step_up=False)
    with patches[0], patches[1]:
        from rate_limiter import rate_limit

        @rate_limit("user:write")
        async def handler(request: Request):
            return {"ok": True}  # pragma: no cover

        await handler(request=_make_request({}, client_host="9.9.9.9"))

    _, kw = mock_ts.issue_step_up_challenge.call_args
    assert kw["client_ip"] == "9.9.9.9"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_client_ip_empty_string_when_request_client_is_none():
    """request.client is None → AttributeError caught; client_ip defaults to ""."""
    patches, mock_ts = _patch_dependencies(step_up=False)
    with patches[0], patches[1]:
        from rate_limiter import rate_limit

        @rate_limit("user:write")
        async def handler(request: Request):
            return {"ok": True}  # pragma: no cover

        # No x-forwarded-for AND client=None triggers the AttributeError path.
        await handler(request=_make_request({}, client_host=None))

    _, kw = mock_ts.issue_step_up_challenge.call_args
    assert kw["client_ip"] == ""


@pytest.mark.unit
@pytest.mark.asyncio
async def test_step_up_present_skips_client_ip_resolution():
    """If step_up is already True the challenge branch is never entered."""
    patches, mock_ts = _patch_dependencies(step_up=True)
    with (
        patches[0],
        patches[1],
        patch("rate_limiter.TokenBucketRateLimiter.allow", return_value=True),
    ):
        from rate_limiter import rate_limit

        @rate_limit("user:write")
        async def handler(request: Request):
            return {"ok": True}

        result = await handler(request=_make_request({}, client_host=None))

    mock_ts.issue_step_up_challenge.assert_not_called()
    assert result == {"ok": True}
