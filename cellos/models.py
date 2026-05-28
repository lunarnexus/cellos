"""CelloS domain models - enums, DTOs, and core entities."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


# ─── Enums ──────────────────────────────────────────────────────────────────

class AgentRole(StrEnum):
    """Agent roles with inferred task types."""
    RESEARCHER = "researcher"
    ARCHITECT = "architect"
    ENGINEER = "engineer"
    TESTER = "tester"


class TaskStatus(StrEnum):
    """Task lifecycle states with transition rules."""
    DRAFT = "draft"
    NEEDS_APPROVAL = "needs_approval"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"
    FAILED = "failed"
    CHANGE_REQUESTED = "change_requested"
    CANCELLED = "cancelled"


class TaskType(StrEnum):
    """Task classification types."""
    PROPOSAL = "proposal"
    RESEARCH = "research"
    ARCHITECTURE = "architecture"
    IMPLEMENTATION = "implementation"
    VERIFICATION = "verification"


# Role → task_type inference map
ROLE_TO_TASK_TYPE: dict[AgentRole, TaskType] = {
    AgentRole.RESEARCHER: TaskType.RESEARCH,
    AgentRole.ARCHITECT: TaskType.ARCHITECTURE,
    AgentRole.ENGINEER: TaskType.IMPLEMENTATION,
    AgentRole.TESTER: TaskType.VERIFICATION,
}


class AttentionReason(StrEnum):
    """Reasons for human attention on a task."""
    NEW_TASK = "new_task"
    HUMAN_CHANGED_TASK = "human_changed_task"
    DEPENDENCY_DONE = "dependency_done"
    CHILD_CHANGE_REQUESTED = "child_change_requested"
    CHILD_FAILED = "child_failed"
    APPROVED = "approved"
    EXECUTION_FAILED = "execution_failed"
    HUMAN_COMMENTED = "human_commented"
    PLANNING_COMPLETE = "planning_complete"


class WorkerStatus(StrEnum):
    """Worker subprocess lifecycle states."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskAttemptStatus(StrEnum):
    """Task attempt execution states."""
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class CommentAuthorType(StrEnum):
    """Comment author classification."""
    HUMAN = "human"
    SYSTEM = "system"


# ─── DTOs ──────────────────────────────────────────────────────────────────

class AttentionMetadata(BaseModel):
    """Tracks whether a task requires human attention and why."""
    required: bool = False
    reason: Optional[AttentionReason] = None
    detail: Optional[str] = None
    timestamp: Optional[datetime] = Field(
        default=None, serialization_alias="timestamp"
    )

    @classmethod
    def required_attention(cls, reason: AttentionReason, detail: str | None = None) -> AttentionMetadata:
        """Create attention metadata that signals human review is needed."""
        return cls(
            required=True,
            reason=reason,
            detail=detail,
            timestamp=datetime.now(),
        )


class ProcessingMetadata(BaseModel):
    """Sync and change detection metadata for scheduler coordination."""
    last_processed_at: Optional[datetime] = None
    last_human_change_at: Optional[datetime] = None
    last_ai_change_at: Optional[datetime] = None
    input_hash: Optional[str] = None


class TaskDependency(BaseModel):
    """Dependency relationship between tasks."""
    task_id: str
    status_satisfied: bool = False


class ConversationMessage(BaseModel):
    """Structured message in a task's conversation history."""
    author_type: Literal["human", "agent", "system"]
    content: str
    timestamp: datetime


class TaskComment(BaseModel):
    """Human or system comment on a task."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_id: str
    author_type: CommentAuthorType
    author_id: Optional[str] = None
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)


class TaskResult(BaseModel):
    """Execution result from an agent."""
    success: bool
    summary: str
    output: Optional[str] = None
    actions_taken: list[str] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    commands_run: list[str] = Field(default_factory=list)
    criteria_met: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.now)


class ChangeRequestReport(BaseModel):
    """Child task requesting changes to parent plan."""
    reason: str
    requested_changes: list[str]
    timestamp: datetime = Field(default_factory=datetime.now)


# ─── Core Entities ─────────────────────────────────────────────────────────

class Task(BaseModel):
    """Central entity representing a unit of work in the orchestration system.
    
    Tasks flow through states: draft → needs_approval → approved → in_progress → done/failed
    with attention signals for human review points.
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str
    details: Optional[str] = None
    status: TaskStatus = TaskStatus.DRAFT
    role: AgentRole = AgentRole.ENGINEER
    task_type: TaskType = Field(default_factory=lambda: ROLE_TO_TASK_TYPE[AgentRole.ENGINEER])
    plan: Optional[str] = None
    prompt_text: Optional[str] = None
    
    parent_id: Optional[str] = None
    dependencies: list[TaskDependency] = Field(default_factory=list)
    agent_id: Optional[str] = None
    
    success_criteria: Optional[str] = None
    failure_criteria: Optional[str] = None
    
    attention: AttentionMetadata = Field(default_factory=AttentionMetadata)
    processing: ProcessingMetadata = Field(default_factory=ProcessingMetadata)
    conversation: list[ConversationMessage] = Field(default_factory=list)
    result: Optional[TaskResult] = None
    comments: list[TaskComment] = Field(default_factory=list)
    
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_fields(cls, data: Any) -> Any:
        """Backward-compat migration for legacy field names from Cellos/Cellos2."""
        if isinstance(data, dict):
            # proposal → prompt_text
            if "proposal" in data and "prompt_text" not in data:
                data["prompt_text"] = data.pop("proposal")
            # description → details
            if "description" in data and "details" not in data:
                data["details"] = data.pop("description")
            # constraints → failure_criteria
            if "constraints" in data and "failure_criteria" not in data:
                data["failure_criteria"] = data.pop("constraints")
        return data

    @model_validator(mode="before")
    @classmethod
    def infer_task_type_from_role(cls, data: Any) -> Any:
        """Infer task_type from role if not explicitly provided."""
        if isinstance(data, dict):
            role = data.get("role")
            task_type = data.get("task_type")
            if role and not task_type:
                # Handle both string and enum values
                try:
                    role_enum = AgentRole(role)
                    data["task_type"] = ROLE_TO_TASK_TYPE[role_enum]
                except ValueError:
                    pass
        return data

    def requires_attention(self, reason: AttentionReason, detail: str | None = None) -> Task:
        """Return a copy of this task with attention required.
        
        Args:
            reason: Why human attention is needed.
            detail: Optional additional context for the alert.
            
        Returns:
            New Task instance with attention metadata set.
        """
        return self.model_copy(
            update={
                "attention": AttentionMetadata.required_attention(reason, detail),
                "updated_at": datetime.now(),
            }
        )

    def clear_attention(self) -> Task:
        """Return a copy of this task with attention cleared.
        
        Returns:
            New Task instance with attention metadata reset to defaults.
        """
        return self.model_copy(
            update={
                "attention": AttentionMetadata(),
                "updated_at": datetime.now(),
            }
        )


class TaskAttempt(BaseModel):
    """Record of a single execution attempt on a task."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_id: str
    status: TaskAttemptStatus = TaskAttemptStatus.STARTED
    mode: Optional[str] = None  # "planning" or "execution"
    agent_id: Optional[str] = None
    result_summary: Optional[str] = None
    error_message: Optional[str] = None
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None


class TaskEvent(BaseModel):
    """Audit trail event for task lifecycle tracking."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_id: str
    event_type: str  # e.g., "status_changed", "planning_saved"
    message: str
    timestamp: datetime = Field(default_factory=datetime.now)


class Worker(BaseModel):
    """Tracks a worker subprocess executing a task."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_id: str
    mode: str  # "planning" or "execution"
    status: WorkerStatus = WorkerStatus.PENDING
    pid: Optional[int] = None
    log_path: Optional[str] = None
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None


__all__ = [
    # Enums
    "AgentRole",
    "TaskStatus", 
    "TaskType",
    "AttentionReason",
    "WorkerStatus",
    "TaskAttemptStatus",
    "CommentAuthorType",
    "ROLE_TO_TASK_TYPE",
    
    # DTOs
    "AttentionMetadata",
    "ProcessingMetadata",
    "TaskDependency",
    "ConversationMessage",
    "TaskComment",
    "TaskResult",
    "ChangeRequestReport",
    
    # Core entities
    "Task",
    "TaskAttempt",
    "TaskEvent",
    "Worker",
]
