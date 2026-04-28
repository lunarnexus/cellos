"""Core CelloS domain models."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class AgentRole(StrEnum):
    CONDUCTOR = "conductor"
    COMPOSER = "composer"
    CELLO = "cello"
    CRITIC = "critic"


class TaskType(StrEnum):
    PLAN = "plan"
    DECOMPOSE = "decompose"
    DESIGN = "design"
    RESEARCH = "research"
    BUILD = "build"
    TEST = "test"
    REVIEW = "review"
    DOCUMENT = "document"
    INTEGRATE = "integrate"
    ESCALATE = "escalate"


class TaskStatus(StrEnum):
    BACKLOG = "backlog"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"
    STALE = "stale"
    ESCALATED = "escalated"


class WorkerStatus(StrEnum):
    IDLE = "idle"
    BUSY = "busy"
    STALE = "stale"
    STOPPED = "stopped"
    FAILED = "failed"


class TaskDependency(BaseModel):
    task_id: str
    depends_on_task_id: str


class TaskResult(BaseModel):
    task_id: str
    success: bool
    summary: str
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class Task(BaseModel):
    id: str
    title: str
    task_type: TaskType
    role: AgentRole
    status: TaskStatus = TaskStatus.BACKLOG
    description: str = ""
    parent_id: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    assigned_worker_id: str | None = None
    timeout_seconds: int | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: TaskResult | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


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
