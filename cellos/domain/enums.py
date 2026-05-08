"""Core CelloS domain enums."""

from enum import StrEnum


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
