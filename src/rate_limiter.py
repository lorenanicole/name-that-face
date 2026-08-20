"""Exercise 1 — Token-bucket rate limiter.

Why this one: abuse prevention is core to an identity/security product like
Nametag, and "implement a rate limiter" is a classic practical prompt.

Fill in the TODOs until `python -m unittest` (or `pytest`) passes.
A reference implementation lives in ../solutions/rate_limiter_solution.py —
try it yourself first.

Design notes / hints:
  - A token bucket has a `capacity` (max tokens) and a `refill_rate`
    (tokens added per second). Each allowed request costs tokens.
  - Track per-key state: (current_tokens, last_refill_timestamp).
  - On each call: first REFILL based on elapsed time (capped at capacity),
    then decide if there are enough tokens for the request.
  - Inject the clock (a function returning "now" in seconds) so behavior is
    testable without real sleeping. This is a good habit to show interviewers.
"""

from __future__ import annotations

import inspect
import math
import pprint
import random
import time
from dataclasses import dataclass
from typing import Callable, Optional

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from dependencies import token_config, token_service  # noqa: E402
from token_service import TokenError  # noqa: E402

logger = structlog.get_logger(__name__)


@dataclass
class Bucket:
    """Per-operation rate-limit state for a token bucket."""

    tokens: float  # current token-bucket fill level
    last_timestamp: float  # when tokens was last updated (for refill calc)
    rpm_remaining: float | None  # requests still allowed this 60-second window (None = unlimited)
    rpm_window_start: float  # when the current 60-second window began
    rpm_limit: float | None  # original rpm cap (used to reset rpm_remaining on window rollover)


@dataclass
class TokenScope:
    """A named token type (e.g. "admin") with a shared daily budget across all its operations.

    Each operation (e.g. "read", "write") has its own Bucket for token-bucket
    rate limiting and rpm tracking, but they all draw from one shared
    remaining_daily pool.
    """

    daily_token_budget: float | None  # initial daily cap (None = unlimited)
    remaining_daily: float | None  # current balance (None = unlimited)
    operations: dict[str, Bucket]  # operation name -> per-operation bucket


class TokenBucketRateLimiter:
    def __init__(
        self,
        capacity: float,
        refill_rate: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """capacity: max tokens a bucket holds.
        refill_rate: tokens replenished per second.
        clock: callable returning the current time in seconds (injectable).
        """
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)
        self.clock = clock
        # token_type -> TokenScope (each scope holds a shared daily budget
        # and a per-operation Bucket dict)
        self._scopes: dict[str, TokenScope] = {}

    def _init_scope(self, token_type: str, daily_token_budget: float | None) -> None:
        """Initialise a TokenScope for `token_type` if not yet seen."""
        if token_type not in self._scopes:
            self._scopes[token_type] = TokenScope(
                daily_token_budget=daily_token_budget,
                remaining_daily=daily_token_budget,
                operations={},
            )

    def _init_operation(
        self, scope: TokenScope, operation: str, now: float, rpm: float | None
    ) -> None:
        """Initialise a Bucket for `operation` inside `scope` if not yet seen."""
        if operation not in scope.operations:
            scope.operations[operation] = Bucket(
                tokens=self.capacity,
                last_timestamp=now,
                rpm_remaining=rpm,
                rpm_window_start=now,
                rpm_limit=rpm,
            )

    def _refill(self, tokens: float, last: float, now: float) -> float:
        """Return the refilled token count, floored to whole slots and capped at capacity.

        Refill accrues continuously but slots are discrete whole units, so floor
        to keep slots as integers (avoids fractional slot values like 2.6 slots).
        e.g. if capacity=5, refill_rate=1, last=0, now=3, tokens=2
        then tokens = min(5, floor(2 + (3 - 0) * 1)) = min(5, 5) = 5
        """
        elapsed = now - last
        return min(self.capacity, math.floor(tokens + elapsed * self.refill_rate))

    def _reset_rpm_window(
        self,
        rpm_remaining: float | None,
        rpm_limit: float | None,
        rpm_window_start: float,
        now: float,
    ) -> tuple[float | None, float]:
        """Reset rpm_remaining to rpm_limit if the 60-second window has rolled over."""
        if rpm_remaining is not None and (now - rpm_window_start) >= 60.0:
            return rpm_limit, now
        return rpm_remaining, rpm_window_start

    def _consume(
        self,
        tokens: float,
        cost: float,
        remaining_daily: float | None,
        rpm_remaining: float | None,
    ) -> tuple[bool, float, float | None, float | None]:
        """Gate on daily budget and rpm, deduct if both pass, then check slot availability.

        Steps:
          1. Gate on daily budget and rpm — if either fails, deny immediately.
          2. Deduct cost from daily budget and decrement rpm counter.
          3. Confirm the cost (the number of tokens needed for a single request
             e.g. 250 cost when a token is 100 means 3 slots) does not surpass current
             available tokens.

        Returns (allowed, updated_tokens, updated_remaining_daily, updated_rpm_remaining).
        """
        daily_ok = (remaining_daily is None) or (remaining_daily >= cost)
        rpm_ok = (rpm_remaining is None) or (rpm_remaining >= 1)
        tokens_ok = (tokens - cost) >= 0

        allowed = daily_ok and rpm_ok and tokens_ok
        if allowed:
            if remaining_daily is not None:
                remaining_daily -= cost
            if rpm_remaining is not None:
                rpm_remaining -= 1
            tokens -= cost

        return allowed, tokens, remaining_daily, rpm_remaining

    def allow(
        self,
        token_type: str,
        operation: str = "default",
        cost: float = 1.0,
        daily_token_budget: float | None = None,
        rpm: float | None = None,
    ) -> bool:
        """Return True if `cost` tokens are available for `token_type`/`operation`
        (and consume them), else False.

        Args:
            token_type: The token type (e.g. "admin", "user"). All operations
                under the same type share one daily budget pool.
            operation: The specific operation (e.g. "read", "write"). Each
                operation has its own token-bucket fill level and rpm counter.
                Defaults to "default" for callers that don't use operations.
            cost: Token cost of this request.
            daily_token_budget: Shared daily budget for the token type (only
                used when the type is first seen; ignored on subsequent calls).
            rpm: Requests-per-minute cap for this operation (only used when
                the operation is first seen; ignored on subsequent calls).
        """
        now = self.clock()
        self._init_scope(token_type, daily_token_budget)
        scope = self._scopes[token_type]

        self._init_operation(scope, operation, now, rpm)
        bucket = scope.operations[operation]

        bucket.tokens = self._refill(bucket.tokens, bucket.last_timestamp, now)
        bucket.rpm_remaining, bucket.rpm_window_start = self._reset_rpm_window(
            bucket.rpm_remaining, bucket.rpm_limit, bucket.rpm_window_start, now
        )
        allowed, bucket.tokens, scope.remaining_daily, bucket.rpm_remaining = self._consume(
            bucket.tokens, cost, scope.remaining_daily, bucket.rpm_remaining
        )
        bucket.last_timestamp = now

        return allowed

    def operation_info(self, token_type: str, operation: str = "default") -> dict | None:
        """Return a snapshot of state for a specific operation, or None if unseen."""
        scope = self._scopes.get(token_type)
        if scope is None:
            return None
        bucket = scope.operations.get(operation)
        if bucket is None:
            return None
        return {
            "tokens": bucket.tokens,
            "last_updated": bucket.last_timestamp,
            "remaining_daily_budget": scope.remaining_daily,
            "remaining_rpm": bucket.rpm_remaining,
            "rpm_window_start": bucket.rpm_window_start,
        }


class RateLimitError(Exception):
    """Raised when a request exceeds the rate limit."""

    def __init__(self, operation: str):
        super().__init__(f"Rate limit exceeded for operation '{operation}'")
        self.operation = operation


def rate_limit(key, max_requests: Optional[int] = None):
    """
    Decorator that enforces rate limits driven entirely by the token config.

    key format: "<token_type>:<scope>"  e.g. "user:read", "admin:write"
    All limits (rpm, cost, daily budget) are pulled from config.yml via
    token_config — no magic numbers in the decorator call site.
    """
    # --- parse key once at decoration time ---
    try:
        token_type, scope = key.split(":", 1)
    except ValueError:
        raise ValueError(f"rate_limit key must be 'token_type:scope', got {key!r}")

    # --- look up config once at decoration time ---
    type_cfg = token_config.token_permissions[token_type]  # has daily_token_budget
    scope_cfg = token_config.get_scope_config(token_type, scope)  # has rpm, cost_min, cost_max

    rpm = float(scope_cfg["rpm"])
    daily_token_budget = float(type_cfg["daily_token_budget"])

    def decorator(func):
        limiter = TokenBucketRateLimiter(
            capacity=float(rpm),
            refill_rate=rpm / 60.0,
        )

        async def wrapper(*args, **kwargs):
            # --- 1. extract Request from handler arguments ---
            request: Request | None = kwargs.get("request")
            if request is None:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
            if request is None:
                return JSONResponse(status_code=500, content={"detail": "No Request object found"})

            # --- 1.5 log device info ---
            x_original_ua = request.headers.get("x-original-user-agent")
            default_ua = request.headers.get("user-agent", "unknown")
            user_agent = x_original_ua or default_ua
            is_mobile = any(
                x in user_agent.lower() for x in ["mobile", "android", "iphone", "ipad"]
            )
            logger.info(
                "request.device_detected",
                is_mobile=is_mobile,
                user_agent=user_agent[:80],
                x_original_user_agent=x_original_ua,
                default_user_agent=default_ua[:80],
                endpoint=request.url.path,
            )

            # --- 2. extract Bearer token and verify JWT ---
            try:
                raw_token = token_service.get_token(request)
                claims = token_service.validate_token(raw_token, key)
            except TokenError as e:
                return JSONResponse(status_code=401, content={"detail": str(e)})

            # -- 4. check if step-up 2FA is required for this scope ---
            if not claims.get("step_up") and scope in ("write", "delete", "admin"):
                client_ip = ""
                try:
                    x_forwarded_for = request.headers.get("x-forwarded-for")

                    if x_forwarded_for:
                        # The header can contain a comma-separated list of proxy IPs;
                        # the first element is always the original client IP.
                        client_ip = x_forwarded_for.split(",")[0].strip()
                    else:
                        # Fallback to direct client host if header is missing
                        client_ip = request.client.host
                    logger.info(
                        "audit_log.written",
                        user_id=claims.get("sub"),
                        client_ip=f"Client IP Resolved: {client_ip}",
                    )
                except AttributeError:
                    logger.info(
                        "audit_log.written",
                        user_id=claims.get("sub"),
                        client_ip="Client IP Invalid",
                    )

                challenge_token = token_service.issue_step_up_challenge(
                    claims=claims,
                    required_scope=key,
                    client_ip=client_ip,
                    next_url=str(request.url),
                )
                return RedirectResponse(
                    url=f"/login-2fa?challenge={challenge_token}",
                    status_code=307,
                )

            # --- 5. enforce rate limit ---
            if not limiter.allow(
                token_type,
                operation=scope,
                cost=1.0,
                daily_token_budget=daily_token_budget,
                rpm=rpm,
            ):
                return JSONResponse(
                    status_code=429, content={"detail": f"Rate limit exceeded for '{key}'"}
                )

            # --- 6. pass verified claims downstream via request.state ---
            request.state.jwt_claims = claims

            return await func(*args, **kwargs)

        wrapper.__signature__ = inspect.signature(func)
        return wrapper

    return decorator


if __name__ == "__main__":
    import doctest
    import math

    import yaml

    doctest.testmod()

    with open("name-that-face/token_config.yml") as f:
        config = yaml.safe_load(f)

    token_permissions_with_limits = {
        token_type: {
            "daily_token_budget": type_data["daily_token_budget"],
            **{
                scope: {
                    "cost_min": scope_data["token_cost_base"],
                    "cost_max": scope_data["token_cost_max"],
                    "rpm": scope_data["rate_limit_per_minute"],
                }
                for scope, scope_data in type_data["scopes"].items()
            },
        }
        for token_type, type_data in config["token_types"].items()
    }

    pprint.pprint(token_permissions_with_limits)

    token_type = random.choice(list(token_permissions_with_limits.keys()))
    token_operation = random.choice(
        [k for k in token_permissions_with_limits[token_type] if k != "daily_token_budget"]
    )
    type_cfg = token_permissions_with_limits[token_type]
    scope_cfg = type_cfg[token_operation]

    daily_token_budget = type_cfg["daily_token_budget"]  # from token-type level
    rpm = scope_cfg["rpm"]
    token_cost_base = scope_cfg["cost_min"]  # one base-unit slot = this many real tokens
    token_cost = random.randint(
        scope_cfg["cost_min"], scope_cfg["cost_max"]
    )  # real cost of this request

    # How many base-unit slots does this request need?
    # e.g. cost_base=100, token_cost=250 → ceil(250/100) = 3 slots needed
    tokens_needed = math.ceil(token_cost / token_cost_base)

    # Derive limiter parameters from the config:
    #   - capacity    = rpm  (bucket holds up to one full minute's worth of base-unit slots)
    #   - refill_rate = rpm / 60  (slots refilled per second)
    #   - cost        = tokens_needed (base-unit slots this request consumes)
    #   - rpm         = the rpm allotment; request is only allowed if this hasn't been exceeded
    limiter = TokenBucketRateLimiter(
        capacity=float(rpm),
        refill_rate=rpm / 60.0,
    )

    print(
        f"Testing token_type={token_type}, token_operation={token_operation}, "
        f"token_cost={token_cost} (tokens_needed={tokens_needed} slots of {token_cost_base}), "
        f"rpm={rpm}, daily_token_budget={daily_token_budget}"
    )

    while limiter.allow(
        token_type,
        operation=token_operation,
        cost=tokens_needed,
        daily_token_budget=float(daily_token_budget),
        rpm=float(rpm),
    ):
        info = limiter.operation_info(token_type, token_operation)
        assert info is not None
        print(
            f"Allowed | slots_remaining={info['tokens']:.1f}, "
            f"remaining_rpm={info['remaining_rpm']}, "
            f"remaining_daily={info['remaining_daily_budget']}"
        )
        time.sleep(0.2)

    print("Denied — limit reached.")
    pprint.pprint(limiter.operation_info(token_type, token_operation))

"""
1. Create a token configuration file (token_config.yml) that defines:
    - token types (scopes) and their operations
    - the token types daily budgets and per-operation costs
    - the token types to operation RPM limits.
2. Implement the TokenBucketRateLimiter class with methods to initialize:
    - scopes and operations
    - refill tokens
    - reset RPM windows
    - consume tokens
    - check if a request is allowed
3. Write unit tests to verify the behavior of the rate limiter under various scenarios, including:
    - exceeding daily budgets
    - exceeding RPM limits
    - token costs.
4. Use the provided main block to test the rate limiter with random token
"""
