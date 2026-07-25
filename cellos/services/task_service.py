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


class InvalidTaskRetryError(TaskServiceError):
    """Cannot retry task in current status (must be FAILED)."""


class InvalidTaskRecoverError(TaskServiceError):
    """Cannot recover task in current status (must be IN_PROGRESS)."""


class InvalidTaskBlockError(TaskServiceError):
    """Cannot block task in current status."""


class InvalidTaskUnblockError(TaskServiceError):
    """Cannot unblock task in current status or to invalid target."""


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

    async def create_child_task(
        self,
        parent_id: str,
        title: str,
        details: Optional[str] = None,
        role: AgentRole = AgentRole.ENGINEER,
        task_type: Optional[TaskType] = None,
        success_criteria: Optional[str] = None,
        failure_criteria: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> Task:
        """Create a child task and block the parent on that child."""
        await self.get_task(parent_id)

        child = await self.create_task(
            title=title,
            details=details,
            role=role,
            task_type=task_type,
            success_criteria=success_criteria,
            failure_criteria=failure_criteria,
            parent_id=parent_id,
            agent_id=agent_id,
        )
        await self.db.add_dependencies(parent_id, [TaskDependency(task_id=child.id)])
        return await self.get_task(child.id)

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

    async def list_attention_tasks(self) -> list[Task]:
        """List tasks currently requiring human attention."""
        return await self.db.list_tasks_requiring_attention()

    async def list_review_tasks(self) -> list[Task]:
        """List tasks currently awaiting human approval or review."""
        review_reasons = {
            AttentionReason.PLANNING_COMPLETE,
            AttentionReason.EXECUTION_FAILED,
            AttentionReason.DEPENDENCY_DONE,
            AttentionReason.CHILD_CHANGE_REQUESTED,
            AttentionReason.CHILD_FAILED,
        }

        review_tasks: list[Task] = []
        seen_ids: set[str] = set()

        needs_approval_tasks = await self.db.list_tasks(status_filter=TaskStatus.NEEDS_APPROVAL.value)
        for task in needs_approval_tasks:
            if task.id not in seen_ids:
                review_tasks.append(task)
                seen_ids.add(task.id)

        attention_tasks = await self.db.list_tasks_requiring_attention()
        for task in attention_tasks:
            if task.id in seen_ids:
                continue
            if task.attention.required and task.attention.reason in review_reasons:
                review_tasks.append(task)
                seen_ids.add(task.id)

        return review_tasks

    async def list_recent_failed_attempts(self, limit: int = 10):
        """List recent failed attempts across all tasks, newest first."""
        return await self.db.list_failed_attempts(limit=limit)

    async def get_dependency_view(self, task_id: str) -> dict:
        """Return direct relationship context for a task.

        Includes parent, direct dependencies, direct dependents, and direct children.
        Built from existing task data only — no new persistence schema required.
        """
        task = await self.get_task(task_id)
        all_tasks = await self.db.list_tasks()
        by_id = {candidate.id: candidate for candidate in all_tasks}

        parent = by_id.get(task.parent_id) if task.parent_id else None
        children = [candidate for candidate in all_tasks if candidate.parent_id == task.id]
        dependents = [
            candidate for candidate in all_tasks
            if any(dep.task_id == task.id for dep in candidate.dependencies)
        ]
        dependencies = [
            {
                "dependency": dep,
                "task": by_id.get(dep.task_id),
            }
            for dep in task.dependencies
        ]

        return {
            "task": task,
            "parent": parent,
            "children": children,
            "dependents": dependents,
            "dependencies": dependencies,
        }

    async def get_tree_view(self, task_id: str) -> dict:
        """Return ancestor + descendant tree context for a task.

        Uses existing parent_id links only. This is an operator visibility view,
        not a new graph model.
        """
        task = await self.get_task(task_id)
        all_tasks = await self.db.list_tasks()
        by_id = {candidate.id: candidate for candidate in all_tasks}
        by_parent: dict[str, list[Task]] = {}
        for candidate in all_tasks:
            if candidate.parent_id:
                by_parent.setdefault(candidate.parent_id, []).append(candidate)

        for children in by_parent.values():
            children.sort(key=lambda candidate: candidate.created_at)

        ancestors: list[Task] = []
        seen: set[str] = set()
        current = task
        while current.parent_id:
            parent = by_id.get(current.parent_id)
            if parent is None or parent.id in seen:
                break
            ancestors.append(parent)
            seen.add(parent.id)
            current = parent
        ancestors.reverse()

        def build_node(node_task: Task) -> dict:
            children = by_parent.get(node_task.id, [])
            return {
                "task": node_task,
                "children": [build_node(child) for child in children],
            }

        root = ancestors[0] if ancestors else task
        return {
            "task": task,
            "root": root,
            "ancestors": ancestors,
            "tree": build_node(root),
        }

    async def list_ready_tasks(self, max_results: int = 50) -> list[Task]:
        """List execution tasks that are runnable by the daemon right now."""
        return await self.db.list_approved_unblocked_tasks(max_results=max_results)

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

        All roles transition to APPROVED on approval. Architect and coordinator
        tasks remain in APPROVED until their child tasks complete successfully.

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

    async def retry_task(self, task_id: str) -> Task:
        """Restore a failed task to a runnable state based on the latest attempt mode."""
        current = await self.get_task(task_id)

        if current.status != TaskStatus.FAILED:
            raise InvalidTaskRetryError(
                f"Cannot retry task in status '{current.status.value}'. Must be 'failed'."
            )

        attempts = await self.db.list_attempts(task_id)
        latest_mode = attempts[0].mode if attempts else None
        retry_status = TaskStatus.DRAFT if latest_mode == "planning" else TaskStatus.APPROVED

        retried = current.clear_attention().model_copy(
            update={"status": retry_status, "updated_at": datetime.datetime.now()}
        )
        await self.db.update_task(retried)
        await self.db.create_event(
            task_id,
            "task_retried",
            f"Task retried from failed to {retry_status.value}",
        )
        return retried

    async def recover_task(self, task_id: str) -> Task:
        """Recover a stuck in-progress task to its last safe state."""
        current = await self.get_task(task_id)

        if current.status != TaskStatus.IN_PROGRESS:
            raise InvalidTaskRecoverError(
                f"Cannot recover task in status '{current.status.value}'. Must be 'in_progress'."
            )

        attempts = await self.db.list_attempts(task_id)
        latest_attempt = attempts[0] if attempts else None

        restore_status = TaskStatus.DRAFT
        attempt_mode = "unknown"
        detail = "Operator recovered task from in_progress with no live worker confirmation"
        if latest_attempt and latest_attempt.mode == "planning":
            restore_status = TaskStatus.DRAFT
            attempt_mode = "planning"
        elif latest_attempt and latest_attempt.mode == "execution":
            restore_status = TaskStatus.APPROVED
            attempt_mode = "execution"
        elif not latest_attempt:
            detail = "Operator recovered task from in_progress with no attempt record"

        recovered = current.requires_attention(
            AttentionReason.EXECUTION_FAILED,
            detail=f"{detail} (mode={attempt_mode})",
        ).model_copy(update={"status": restore_status, "updated_at": datetime.datetime.now()})
        await self.db.update_task(recovered)
        await self.db.create_event(
            task_id,
            "operator_recovered",
            f"Operator recovered in_progress task; restoring to {restore_status.value} (mode={attempt_mode})",
        )
        await self.db.create_event(
            task_id,
            "task_recovered",
            f"Task restored from in_progress to {restore_status.value} by operator recovery",
        )

        if latest_attempt and latest_attempt.status.value == "started":
            await self.db.update_attempt(
                latest_attempt.id,
                TaskStatus.FAILED,
                error_message=f"operator_recovered: {detail} (mode={attempt_mode})",
            )

        return recovered

    async def block_task(self, task_id: str, reason: str) -> Task:
        """Manually block a task that cannot proceed until operator action resolves it."""
        current = await self.get_task(task_id)
        allowed_statuses = {
            TaskStatus.DRAFT,
            TaskStatus.NEEDS_APPROVAL,
            TaskStatus.APPROVED,
            TaskStatus.CHANGE_REQUESTED,
        }
        if current.status not in allowed_statuses:
            raise InvalidTaskBlockError(
                f"Cannot block task in status '{current.status.value}'."
            )

        blocked = current.requires_attention(
            AttentionReason.HUMAN_CHANGED_TASK,
            detail=f"Operator blocked task: {reason}",
        ).model_copy(update={"status": TaskStatus.BLOCKED, "updated_at": datetime.datetime.now()})
        await self.db.update_task(blocked)
        await self.db.create_event(
            task_id,
            "status_changed",
            f"Status changed from {current.status.value} to blocked",
        )
        await self.db.create_event(
            task_id,
            "operator_blocked",
            f"Operator blocked task: {reason}",
        )
        return blocked

    async def unblock_task(self, task_id: str, target_status: TaskStatus) -> Task:
        """Restore a manually blocked task to an explicit safe target status."""
        current = await self.get_task(task_id)
        if current.status != TaskStatus.BLOCKED:
            raise InvalidTaskUnblockError(
                f"Cannot unblock task in status '{current.status.value}'. Must be 'blocked'."
            )

        allowed_targets = {
            TaskStatus.DRAFT,
            TaskStatus.NEEDS_APPROVAL,
            TaskStatus.APPROVED,
            TaskStatus.CHANGE_REQUESTED,
            TaskStatus.FAILED,
        }
        if target_status not in allowed_targets:
            raise InvalidTaskUnblockError(
                f"Cannot unblock task to status '{target_status.value}'."
            )

        unblocked = current.clear_attention().model_copy(
            update={"status": target_status, "updated_at": datetime.datetime.now()}
        )
        await self.db.update_task(unblocked)
        await self.db.create_event(
            task_id,
            "status_changed",
            f"Status changed from blocked to {target_status.value}",
        )
        await self.db.create_event(
            task_id,
            "operator_unblocked",
            f"Operator unblocked task to {target_status.value}",
        )
        return unblocked

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

    async def list_attempts(self, task_id: str):
        """Return attempt history for a task, newest first."""
        await self.get_task(task_id)
        return await self.db.list_attempts(task_id)

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

