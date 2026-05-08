"""Comment models for CelloS domain models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from cellos.domain.time import utc_now
from cellos.domain.enums import CommentAuthorType


class TaskComment(BaseModel):
    id: int | None = None
    task_id: str
    author_type: CommentAuthorType
    author_id: str = ""
    message: str
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)
