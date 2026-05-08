"""Result models for CelloS domain models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from cellos.domain.time import utc_now


class ChangeRequestReport(BaseModel):
    blocker_summary: str
    why_current_task_cannot_be_completed: str
    evidence: str = ""
    recommended_next_action: str = ""
    human_approval_needed: bool = False


class TaskResult(BaseModel):
    task_id: str
    success: bool
    summary: str
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    change_request: ChangeRequestReport | None = None
    created_at: datetime = Field(default_factory=utc_now)
