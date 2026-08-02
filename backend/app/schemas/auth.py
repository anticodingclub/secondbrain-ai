"""Auth request/response contracts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import MIN_PASSWORD_LENGTH


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)

    @field_validator("display_name")
    @classmethod
    def _strip_display_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Display name cannot be blank.")
        return stripped

    @field_validator("password")
    @classmethod
    def _reject_whitespace_only_padding(cls, value: str) -> str:
        # A password of spaces passes a length check but is not a secret.
        if not value.strip():
            raise ValueError("Password cannot be blank.")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    """The access token only.

    The refresh token is deliberately absent: it travels in an httpOnly cookie
    so JavaScript — and therefore any XSS on the page — cannot read it.
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds.")
    user: UserResponse
