from datetime import datetime
from typing import Literal
from uuid import UUID
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema


class KnowledgeBaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("name", mode="before", check_fields=False)
    @classmethod
    def normalize_name(cls, value):
        if isinstance(value, str):
            value = " ".join(unicodedata.normalize("NFKC", value).split())
            if "\x00" in value or not 1 <= len(value) <= 120:
                raise ValueError("Name must contain 1 to 120 characters after normalization")
        return value

    @field_validator("description", mode="before", check_fields=False)
    @classmethod
    def validate_description(cls, value):
        if isinstance(value, str) and "\x00" in value:
            raise ValueError("Description must not contain NUL")
        return value


class KnowledgeBaseCreate(KnowledgeBaseInput):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)


class KnowledgeBaseUpdate(KnowledgeBaseInput):
    @model_validator(mode="before")
    @classmethod
    def reject_null(cls,value):
        if isinstance(value,dict) and any(value.get(k) is None for k in ('name','description') if k in value):
            raise ValueError("Explicit null is not allowed")
        return value

    name: str | SkipJsonSchema[None] = Field(default=None, min_length=1, max_length=120, json_schema_extra=lambda schema:schema.pop('default',None))
    description: str | SkipJsonSchema[None] = Field(default=None, max_length=4000, json_schema_extra=lambda schema:schema.pop('default',None))

    @model_validator(mode="after")
    def require_changes(self):
        if not self.model_fields_set or any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Provide at least one non-null field; use empty description to clear it")
        return self


class KnowledgeBaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    owner_id: UUID | None
    name: str
    description: str
    visibility: Literal["private", "public"]
    index_version: int
    created_at: datetime
    updated_at: datetime


class KnowledgeBaseEnvelope(BaseModel):
    knowledge_base: KnowledgeBaseResponse


class KnowledgeBaseList(BaseModel):
    items: list[KnowledgeBaseResponse]
    total: int
    limit: int
    offset: int
