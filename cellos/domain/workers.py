"""Worker model for CelloS domain models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from cellos.domain.time import utc_now
from cellos.domain.enums import AgentRole, WorkerStatus


class Worker(BaseModel):
    id: str
    role: AgentRole
    status: WorkerStatus = WorkerStatus.IDLE
    backend: str
    spawn_command: list[str]
    current_task_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)
