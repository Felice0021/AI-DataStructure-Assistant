from datetime import datetime
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator
from pydantic_core import PydanticCustomError


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr = Field(max_length=320)
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def trim_email(cls, value):
        return value.strip().casefold() if isinstance(value, str) else value

    @field_validator("email")
    @classmethod
    def canonical_email(cls, value):
        return str(value).casefold()


class Registration(Credentials):
    @field_validator("password")
    @classmethod
    def password_policy(cls, value):
        password = value.get_secret_value()
        common = {"passwordpassword", "123456789012345", "1234567890123456", "qwertyuiopasdfgh"}
        if (len(password.strip()) < 15 or len(set(password)) < 4
            or "\x00" in password or password.casefold() in common):
            raise PydanticCustomError("weak_password", "Password does not meet policy")
        return value


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    role: Literal["student", "admin"]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserEnvelope(BaseModel):
    user: UserResponse


class CsrfResponse(BaseModel):
    csrf_token: str


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
