from typing import Optional

from pydantic import BaseModel, EmailStr, field_validator


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
