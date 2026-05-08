"""Conversation messages for CelloS task discussion logs."""

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from cellos.domain.time import utc_now


class ConversationMessage(BaseModel):
    """A single message in a task's conversation log."""

    id: str = Field(default_factory=lambda: uuid4().hex[:8])
    author: Literal["human", "system"]
    message: str
    created_at: datetime = Field(default_factory=utc_now)
