from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class LoginRequest(BaseModel):
    challenge: str  # signed challenge token issued by rate_limiter on step-up redirect
    client_ip: str  # client ip


class UserRequest(BaseModel):
    name: str
    email: Optional[EmailStr] = None
    age: Optional[int] = None

    @field_validator("age")
    @classmethod
    def age_must_be_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError("age must be positive")
        return v


class UserResponse(BaseModel):
    user_id: str
    sub: str
    username: str
    token_scope: str
    step_up: bool
    token_expires_at: str

    @field_validator("token_expires_at")
    @classmethod
    def validate_iso_datetime(cls, v):
        try:
            datetime.fromisoformat(v)
        except (ValueError, TypeError):
            raise ValueError("token_expires_at must be a valid ISO 8601 datetime string")
        return v


class TokenClaimsType(Enum):
    SET_UP_CHALLENGE = "set_up_challenge"


class TokenClaims(BaseModel):
    model_config = {"populate_by_name": True}

    claim_type: Optional[str] = Field(None, alias="type")
    user_id: str = Field(alias="sub")
    username: str
    client_ip: str
    required_scope: str
    next_url: str = Field(alias="next")
    token_expires_at: int = Field(alias="exp")

    @field_validator("claim_type", mode="before")
    @classmethod
    def is_supported_type(cls, v):
        if v is not None and v not in [e.value for e in TokenClaimsType]:
            raise ValueError(f"{v} not a supported TokenClaimsType")
        return v

    @field_validator("token_expires_at", mode="before")
    @classmethod
    def validate_unix_timestamp(cls, v):
        if not isinstance(v, int):
            raise ValueError("token_expires_at must be an integer unix timestamp")
        if v <= 0:
            raise ValueError("token_expires_at must be a positive unix timestamp")
        return v
