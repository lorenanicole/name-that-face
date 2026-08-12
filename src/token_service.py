from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Request

from settings import Settings


class TokenError(Exception):
    """Raised for any invalid, expired, or unauthorized token."""


_settings = Settings()
SECRET_KEY = _settings.SECRET_KEY
ALGORITHM = _settings.ALGORITHM


class TokenService:
    def __init__(self, token_config):
        self.token_config = token_config

    def get_token(self, request: Request) -> str:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise TokenError("Missing or invalid Authorization header")
        return auth_header.split(" ")[1]

    def validate_token(self, token: str, required_scope: str) -> dict:
        """
        Verify JWT signature + expiry, then confirm the token's scope
        matches required_scope (format: "token_type:scope", e.g. "user:read").
        Returns claims on success, raises TokenError on any failure.
        """
        try:
            claims = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        except jwt.ExpiredSignatureError:
            raise TokenError("Token expired")
        except jwt.InvalidTokenError:
            raise TokenError("Invalid token")

        token_scope = claims.get("scope", "")
        if token_scope != required_scope:
            raise TokenError(f"Token scope '{token_scope}' does not permit '{required_scope}'")

        if token_expires_at := claims.get("exp"):
            expires_at_dt = datetime.fromtimestamp(token_expires_at, tz=timezone.utc)
            if expires_at_dt < datetime.now(timezone.utc):
                raise TokenError("Token has expired")

        return claims

    def issue(self, user_id: str, scope: str, username: str = "", step_up: bool = False) -> str:
        """
        Issue a signed JWT for the given user and scope.

        Args:
            user_id:  The subject (e.g. "user123")
            scope:    The token_type:scope key (e.g. "user:read")
            username: The human-readable username (e.g. "john.doe") — used by Duo push
            step_up:  True if this token was issued after 2FA approval
        """
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=_settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
        payload = {
            "sub": user_id,
            "username": username,
            "scope": scope,
            "step_up": step_up,
            "exp": expire,
        }
        return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    def refresh(self, token: str) -> str:
        """
        Refresh an existing JWT token, extending its expiry.

        Args:
            token: The existing JWT to refresh
        """
        try:
            claims = jwt.decode(
                token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False}
            )
        except jwt.InvalidTokenError:
            raise TokenError("Invalid token")

        # Update the expiry
        new_expire = datetime.now(timezone.utc) + timedelta(
            minutes=_settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
        claims["exp"] = new_expire

        return jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)

    def issue_step_up_challenge(
        self, claims: dict, required_scope: str, client_ip: str, next_url: str
    ) -> str:
        """
        Issue a short-lived challenge token encoding the context needed
        for the 2FA flow. Not an access token — cannot be used to call APIs.
        """
        expire = datetime.now(timezone.utc) + timedelta(minutes=5)
        payload = {
            "typ": "step_up_challenge",
            "sub": claims["sub"],  # user_id
            "username": claims.get("username", ""),
            "client_ip": client_ip,
            "required_scope": required_scope,  # e.g. "user:write"
            "next": next_url,
            "exp": expire,
        }
        return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    def decode_step_up_challenge(self, token: str) -> dict:
        try:
            claims = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        except jwt.ExpiredSignatureError:
            raise TokenError("Challenge expired")
        except jwt.InvalidTokenError:
            raise TokenError("Invalid challenge token")
        if claims.get("typ") != "step_up_challenge":
            raise TokenError("Not a challenge token")
        return claims
