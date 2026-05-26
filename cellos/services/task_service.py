"""TaskService — business logic for task lifecycle with state machine enforcement.

Enforces approval gates, attention auto-triggering on content changes, and
dependency management. Wraps CellosDatabase persistence calls.
"""

from __future__ import annotations

import datetime
from typing import Optional

from cellos.db import CellosDatabase
from cellos.models import (
    AgentRole,
    AttentionReason,
    CommentAuthorType,
    ConversationMessage,
    ROLE_TO_TASK_TYPE,
    Task,
    TaskComment,
    TaskDependency,
    TaskEvent,
    TaskStatus,
    TaskType,
)


# ── Custom Exceptions ───────────────────────────────────────────────

class TaskServiceError(Exception):
    """Base exception for task service errors."""


class TaskNotFoundError(TaskServiceError):
    """Task with the given ID does not exist."""


class EmptyTaskUpdateError(TaskServiceError):
    """No fields provided to update — all values were None/empty."""


class InvalidTaskApprovalError(TaskServiceError):
    """Cannot approve task in current status (must be NEEDS_APPROVAL)."""


# ── TaskService ─────────────────────────────────────────────────────

class TaskService:
    """Business logic layer for task operations.

    Enforces state machine transitions, attention auto-triggering on content
    changes for non-approved tasks, and dependency management. All persistence
    is delegated to CellosDatabase.
    """

    def __init__(self, db: CellosDatabase):
        self.db = db

    # ── Create / Read ────────────────────────────────────────────

    async def create_task(
        self,
        title: str,
        details: Optional[str] = None,
        role: AgentRole = AgentRole.ENGINEER,
        task_type: Optional[TaskType] = None,
        success_criteria: Optional[str] = None,
        failure_criteria: Optional[str] = None,
        parent_id: Optional[str] = None,
        dependencies: Optional[list[TaskDependency]] = None,
        agent_id: Optional[str] = None,
    ) -> Task:
        """Create a new task.

        Args:
            title: Task title (required).
            details: Detailed description of the work.
            role: Agent role for this task.
            task_type: Explicit type; inferred from role if not provided.
            success_criteria: What constitutes successful completion.
            failure_criteria: Conditions that mean the task has failed.
            parent_id: Parent task ID (for child tasks).
            dependencies: List of TaskDependency objects.
            agent_id: Specific agent to use for this task.

        Returns:
            Created Task instance with generated ID and defaults.
        """
        task = Task(
            title=title,
            details=details,
            role=role,
            task_type=task_type or ROLE_TO_TASK_TYPE[role],
            success_criteria=success_criteria,
            failure_criteria=failure_criteria,
            parent_id=parent_id,
            dependencies=dependencies or [],
            agent_id=agent_id,
        )

        await self.db.create_task(task)
        return task

    async def get_task(self, task_id: str) -> Task:
        """Get a task by ID. Raises TaskNotFoundError if not found."""
        task = await self.db.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(f"Task {task_id} not found")
        return task

    async def list_tasks(
        self, status_filter: Optional[TaskStatus] = None
    ) -> list[Task]:
        """List tasks, optionally filtered by status."""
        filter_val = status_filter.value if status_filter else None
        return await self.db.list_tasks(status_filter=filter_val)

    # ── Update with attention tracking ───────────────────────────

    async def update_task(
        self,
        task_id: str,
        title: Optional[str] = None,
        details: Optional[str] = None,
        success_criteria: Optional[str] = None,
        failure_criteria: Optional[str] = None,
        add_dependencies: Optional[list[TaskDependency]] = None,
        remove_dependencies: Optional[list[str]] = None,
    ) -> Task:
        """Update task fields with attention auto-triggering.

        Content changes on draft/needs_approval tasks trigger an attention
        signal (HUMAN_CHANGED_TASK). Approved/done/cancelled tasks do not
        generate attention on content changes.

        Args:
            task_id: The task to update.
            title: New title.
            details: New details.
            success_criteria: New success criteria.
            failure_criteria: New failure criteria.
            add_dependencies: Dependencies to add (merged with existing).
            remove_dependencies: Dependency IDs to remove.

        Returns:
            Updated Task instance.

        Raises:
            TaskNotFoundError: If task doesn't exist.
            EmptyTaskUpdateError: If no fields provided to update.
        """
        # Check if any content field is being changed (not None means "set this")
        has_content_change = False
        updates = {}

        if title is not None:
            updates["title"] = title
            has_content_change = True
        if details is not None:
            updates["details"] = details
            has_content_change = True
        if success_criteria is not None:
            updates["success_criteria"] = success_criteria
            has_content_change = True
        if failure_criteria is not None:
            updates["failure_criteria"] = failure_criteria
            has_content_change = True

        # Dependency changes count as relationship changes (trigger attention)
        has_relationship_change = bool(add_dependencies or remove_dependencies)

        if not has_content_change and not has_relationship_change:
            raise EmptyTaskUpdateError(
                f"No fields provided to update for task {task_id}"
            )

        current = await self.get_task(task_id)

        # Handle dependency changes (commits immediately)
        if add_dependencies:
            await self.db.add_dependencies(task_id, add_dependencies)
        if remove_dependencies:
            await self.db.remove_dependencies(task_id, remove_dependencies)

        # Re-read from DB to get merged deps + any side effects
        updated = await self.get_task(task_id)

        # Apply content updates on top of the fresh task state
        if updates:
            for key, value in updates.items():
                setattr(updated, key, value)
            updated.updated_at = datetime.datetime.now()

        # Trigger attention on content/relationship changes for non-approved tasks
        if has_content_change or has_relationship_change:
            if current.status not in (TaskStatus.APPROVED, TaskStatus.DONE, TaskStatus.CANCELLED):
                updated = updated.requires_attention(
                    AttentionReason.HUMAN_CHANGED_TASK,
                    detail=f"Human changed {', '.join(updates.keys())}" if updates else "dependencies",
                )

        await self.db.update_task(updated)
        return updated

    # ── Approval gate ────────────────────────────────────────────

    async def approve_task(self, task_id: str) -> Task:
        """Approve a task for execution. Only works on NEEDS_APPROVAL tasks.

        All roles transition to APPROVED on approval. Architect tasks remain
        in APPROVED until their child tasks complete successfully.

        Args:
            task_id: The task to approve.

        Returns:
            Approved Task instance with status APPROVED and attention cleared.

        Raises:
            TaskNotFoundError: If task doesn't exist.
            InvalidTaskApprovalError: If task is not in NEEDS_APPROVAL state.
        """
        current = await self.get_task(task_id)

        if current.status != TaskStatus.NEEDS_APPROVAL:
            raise InvalidTaskApprovalError(
                f"Cannot approve task in status '{current.status.value}'. "
                f"Must be 'needs_approval'."
            )

        approved = current.model_copy(
            update={"status": TaskStatus.APPROVED, "updated_at": datetime.datetime.now()}
        )
        approved = approved.clear_attention()

        await self.db.update_task(approved)
        await self.db.create_event(
            task_id, "status_changed",
            f"Status changed from {current.status.value} to {approved.status.value}"
        )
        return approved

    # ── Comments ─────────────────────────────────────────────────

    async def add_human_comment(
        self, task_id: str, content: str, author_id: Optional[str] = None
    ) -> TaskComment:
        """Add a human comment to a task. Triggers attention on draft/needs_approval tasks.

        Args:
            task_id: The task to comment on.
            content: Comment text.
            author_id: Optional identifier for the commenting user.

        Returns:
            Created TaskComment instance.
        """
        current = await self.get_task(task_id)

        comment = await self.db.create_comment(
            task_id, CommentAuthorType.HUMAN, content, author_id=author_id
        )

        # Append to in-memory conversation list on the task model
        updated_comments = list(current.comments) + [comment]
        new_task = current.model_copy(update={"comments": updated_comments})

        # Trigger attention for non-approved tasks
        if current.status not in (TaskStatus.APPROVED, TaskStatus.DONE, TaskStatus.CANCELLED):
            new_task = new_task.requires_attention(
                AttentionReason.HUMAN_COMMENTED,
                detail=f"Human commented: {content[:80]}",
            )

        await self.db.update_task(new_task)
        return comment

    # ── Conversation messages ────────────────────────────────────

    async def add_conversation_message(
        self, task_id: str, author_type: str, content: str
    ) -> ConversationMessage:
        """Add a structured conversation message to the task history.

        Args:
            task_id: The task to add the message to.
            author_type: One of "human", "agent", "system".
            content: Message text.

        Returns:
            Created ConversationMessage instance.
        """
        current = await self.get_task(task_id)

        msg = ConversationMessage(
            author_type=author_type,  # type: ignore[literal-required]
            content=content,
            timestamp=datetime.datetime.now(),
        )

        updated_conversation = list(current.conversation) + [msg]
        new_task = current.model_copy(
            update={"conversation": updated_conversation, "updated_at": datetime.datetime.now()}
        )
        await self.db.update_task(new_task)
        return msg

