"""Task models for CelloS domain models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from cellos.domain.time import utc_now
from cellos.domain.enums import AgentRole, TaskStatus, TaskType, AttentionReason
from cellos.domain.attention import AttentionMetadata, ProcessingMetadata
from cellos.domain.conversation import ConversationMessage
from cellos.domain.results import TaskResult


class TaskDependency(BaseModel):
    task_id: str
    depends_on_task_id: str


class Task(BaseModel):
    id: str
    title: str
    role: AgentRole
    status: TaskStatus = TaskStatus.DRAFT
    task_type: TaskType = TaskType.PROPOSAL
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
        if isinstance(data, dict) and "prompt" not in data and "proposal" in data:
            migrated = dict(data)
            migrated["prompt"] = migrated.pop("proposal")
            return migrated
        return data

    def requires_attention(self, reason: AttentionReason, detail: str = "") -> "Task":
        return self.model_copy(update={"attention": AttentionMetadata.required_attention(reason, detail)})

    def clear_attention(self) -> "Task":
        return self.model_copy(update={"attention": self.attention.cleared()})
