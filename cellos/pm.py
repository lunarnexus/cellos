"""Project-management adapter contract."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from cellos.models import AttentionReason, Task, TaskStatus


class PmChangeKind(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    COMMENTED = "commented"
    STATUS_CHANGED = "status_changed"
    APPROVED = "approved"
    CANCELLED = "cancelled"
    RELATIONSHIP_CHANGED = "relationship_changed"


class PmTaskSnapshot(BaseModel):
    provider: str
    external_id: str
    title: str
    body: str = ""
    status: TaskStatus | None = None
    url: str = ""
    labels: list[str] = Field(default_factory=list)
    parent_external_id: str | None = None
    dependency_external_ids: list[str] = Field(default_factory=list)
    last_human_change_at: datetime | None = None
    last_ai_change_at: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class PmDetectedChange(BaseModel):
    external_id: str
    kind: PmChangeKind
    attention_reason: AttentionReason | None = None
    summary: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class PmTaskUpdate(BaseModel):
    task: Task
    external_id: str
    status: TaskStatus | None = None
    body: str | None = None
    comment: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class PmCreatedTask(BaseModel):
    task: Task
    external_id: str
    url: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class PmSyncResult(BaseModel):
    known_tasks: list[PmTaskSnapshot] = Field(default_factory=list)
    discovered_tasks: list[PmTaskSnapshot] = Field(default_factory=list)
    changes: list[PmDetectedChange] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ProjectManagementAdapter(Protocol):
    name: str

    async def sync_known_tasks(self, tasks: list[Task]) -> PmSyncResult:
        """Sync already-linked tasks from the PM tool into local state."""

    async def discover_tasks(self) -> list[PmTaskSnapshot]:
        """Discover new in-scope PM tasks."""

    async def push_update(self, update: PmTaskUpdate) -> None:
        """Push a local task update, result, or comment to the PM tool."""

    async def create_task(self, task: Task) -> PmCreatedTask:
        """Create a new PM task after approved scope allows task creation."""
