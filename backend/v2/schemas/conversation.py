from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.v2.schemas.rag import AskRequest, AskResponse
from backend.v2.schemas.auth import ErrorDetail


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="新会话", min_length=1, max_length=200)
    project_id: UUID | None = None

    @field_validator("title", mode="before")
    @classmethod
    def validate_title(cls, v):
        if isinstance(v, str):
            if "\x00" in v:
                raise ValueError("title must not contain NUL")
            if not v.strip():
                raise ValueError("title must not be blank")
        return v


class ConversationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=200)
    project_id: UUID | None = None

    @field_validator("title", mode="before")
    @classmethod
    def validate_title(cls, v):
        if isinstance(v, str):
            if "\x00" in v:
                raise ValueError("title must not contain NUL")
            if not v.strip():
                raise ValueError("title must not be blank")
        return v


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    project_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class ConversationEnvelope(BaseModel):
    conversation: ConversationResponse


class ConversationList(BaseModel):
    items: list[ConversationResponse]
    total: int
    limit: int
    offset: int


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user"] = "user"
    content: str = Field(min_length=1, max_length=20000)

    @field_validator("content", mode="before")
    @classmethod
    def validate_content(cls, v):
        if isinstance(v, str):
            if "\x00" in v:
                raise ValueError("content must not contain NUL")
            if not v.strip():
                raise ValueError("content must not be blank")
        return v


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    seq: int
    role: Literal["user", "assistant"]
    content: str
    metadata_json: dict = Field(default_factory=dict)
    created_at: datetime


class MessageList(BaseModel):
    items: list[MessageResponse]
    total: int
    limit: int
    offset: int


class ConversationAskRequest(AskRequest):
    # Stable across transport retries, scoped to an owned conversation.
    request_id: UUID


class ConversationAskError(AskResponse):
    error: ErrorDetail


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    memory_source_ids: list[UUID] = Field(default_factory=list, max_length=12)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value):
        if "\x00" in value or not value.strip():
            raise ValueError("Invalid project text")
        return value

    @field_validator("description")
    @classmethod
    def clean_description(cls, value):
        if "\x00" in value:
            raise ValueError("Invalid project description")
        return value


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    memory_source_ids: list[UUID] | None = Field(default=None, max_length=12)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value):
        if value is not None and ("\x00" in value or not value.strip()):
            raise ValueError("Invalid project text")
        return value

    @field_validator("description")
    @classmethod
    def clean_description(cls, value):
        if value is not None and "\x00" in value:
            raise ValueError("Invalid project description")
        return value


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    description: str
    memory_source_ids: list[UUID]
    created_at: datetime
    updated_at: datetime


class ProjectList(BaseModel):
    items: list[ProjectResponse]


class ProjectMemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    topic: str
    summary: str
    created_at: datetime


class ProjectMemoryList(BaseModel):
    items: list[ProjectMemoryResponse]
