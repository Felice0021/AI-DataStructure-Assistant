from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="新会话", min_length=1, max_length=200)

    @field_validator("title", mode="before")
    @classmethod
    def reject_blank(cls, v):
        if isinstance(v, str) and not v.strip():
            raise ValueError("title must not be blank")
        return v


class ConversationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title", mode="before")
    @classmethod
    def reject_blank(cls, v):
        if isinstance(v, str) and not v.strip():
            raise ValueError("title must not be blank")
        return v


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
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
