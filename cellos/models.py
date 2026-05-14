"""Canonical CelloS schema and type models.

This module is the authoritative home for CelloS enums, DTOs, and Pydantic
models. Legacy `cellos.domain.*` modules remain as compatibility shims.
"""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


# ---- time helpers ----

def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


# ---- enums ----

class AgentRole(StrEnum):
    COORDINATOR = "coordinator"
    RESEARCHER = "researcher"
    ARCHITECT = "architect"
    ENGINEER = "engineer"
    TESTER = "tester"


class TaskStatus(StrEnum):
    DRAFT = "draft"
    NEEDS_APPROVAL = "needs_approval"
    APPROVED = "approved"
    BLOCKED = "blocked"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
    CHANGE_REQUESTED = "change_requested"
    CANCELLED = "cancelled"


class TaskType(StrEnum):
    PROPOSAL = "proposal"
    RESEARCH = "research"
    ARCHITECTURE = "architecture"
    IMPLEMENTATION = "implementation"
    VERIFICATION = "verification"


class AttentionReason(StrEnum):
    NEW_TASK = "new_task"
    HUMAN_CHANGED_TASK = "human_changed_task"
    HUMAN_COMMENTED = "human_commented"
    APPROVED = "approved"
    DEPENDENCY_DONE = "dependency_done"
    CHILD_CHANGE_REQUESTED = "child_change_requested"
    STALE_IN_PROGRESS = "stale_in_progress"
    EXTERNAL_STATE_CHANGED = "external_state_changed"


class WorkerStatus(StrEnum):
    IDLE = "idle"
    BUSY = "busy"
    STALE = "stale"
    STOPPED = "stopped"
    FAILED = "failed"


class TaskAttemptStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CommentAuthorType(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"


# ---- supporting DTOs ----

class AttentionMetadata(BaseModel):
    required: bool = False
    reason: AttentionReason | None = None
    detail: str = ""
    since: datetime | None = None

    @classmethod
    def required_attention(cls, reason: AttentionReason, detail: str = "") -> "AttentionMetadata":
        return cls(required=True, reason=reason, detail=detail, since=utc_now())

    def cleared(self) -> "AttentionMetadata":
        return AttentionMetadata()


class ProcessingMetadata(BaseModel):
    last_processed_at: datetime | None = None
    last_human_change_at: datetime | None = None
    last_ai_change_at: datetime | None = None
    last_observed_external_change_at: datetime | None = None
    last_processed_external_change_at: datetime | None = None
    last_processed_input_hash: str | None = None


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


class ConversationMessage(BaseModel):
    """A single message in a task's conversation log."""

    id: str = Field(default_factory=lambda: uuid4().hex[:8])
    author: Literal["human", "agent", "system"]
    message: str
    created_at: datetime = Field(default_factory=utc_now)


class TaskComment(BaseModel):
    id: int | None = None
    task_id: str
    author_type: CommentAuthorType
    author_id: str = ""
    message: str
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


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


class TaskDependency(BaseModel):
    task_id: str
    depends_on_task_id: str


class Task(BaseModel):
    id: str
    title: str
    details: str = ""
    success_criteria: str = ""
    failure_criteria: str = ""
    role: AgentRole
    status: TaskStatus = TaskStatus.DRAFT
    task_type: TaskType = TaskType.PROPOSAL
    plan: str = ""
    prompt: str = ""
    conversation: list[ConversationMessage] = Field(default_factory=list)
    parent_id: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    attention: AttentionMetadata = Field(default_factory=AttentionMetadata)
    processing: ProcessingMetadata = Field(default_factory=ProcessingMetadata)
    assigned_worker_id: str | None = None
    agent_id: str | None = None
    timeout_seconds: int | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: TaskResult | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def migrate_proposal_to_prompt(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        migrated = dict(data)
        if "prompt" not in migrated and "proposal" in migrated:
            migrated["prompt"] = migrated.pop("proposal")
        if "details" not in migrated and "description" in migrated:
            migrated["details"] = migrated["description"]
        if "failure_criteria" not in migrated and "constraints" in migrated:
            migrated["failure_criteria"] = migrated["constraints"]
        return migrated

    def requires_attention(self, reason: AttentionReason, detail: str = "") -> "Task":
        return self.model_copy(update={"attention": AttentionMetadata.required_attention(reason, detail)})

    def clear_attention(self) -> "Task":
        return self.model_copy(update={"attention": self.attention.cleared()})


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


__all__ = [
    "utc_now",
    "AgentRole",
    "TaskStatus",
    "TaskType",
    "AttentionReason",
    "WorkerStatus",
    "TaskAttemptStatus",
    "CommentAuthorType",
    "AttentionMetadata",
    "ProcessingMetadata",
    "ChangeRequestReport",
    "TaskResult",
    "ConversationMessage",
    "TaskComment",
    "TaskAttempt",
    "TaskDependency",
    "Task",
    "Worker",
]
