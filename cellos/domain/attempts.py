"""Attempt models for CelloS domain models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from cellos.domain.time import utc_now
from cellos.domain.enums import TaskAttemptStatus


class TaskAttempt(BaseModel):
    id: int | None = None
    task_id: str
    mode: str
    agent_id: str
    connector: str
    status: TaskAttemptStatus = TaskAttemptStatus.STARTED
    prompt_snapshot: str = ""
    result_summary: str = ""
    result_payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    log_path: str = ""
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
