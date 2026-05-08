"""Task lifecycle service for CelloS."""

from collections.abc import Sequence

from cellos.db import CellosDatabase
from cellos.domain.attention import AttentionReason
from cellos.domain.comments import TaskComment
from cellos.domain.conversation import ConversationMessage
from cellos.domain.tasks import Task
from cellos.domain.enums import TaskStatus, CommentAuthorType


class TaskServiceError(Exception):
    """Base task service error."""


class TaskNotFoundError(TaskServiceError):
    """Raised when a task does not exist."""


class EmptyTaskUpdateError(TaskServiceError):
    """Raised when an update request has no fields to change."""


class InvalidTaskApprovalError(TaskServiceError):
    """Raised when a task cannot be approved from its current status."""


class TaskService:
    def __init__(self, db: CellosDatabase) -> None:
        self.db = db

    async def create_task(self, task: Task) -> Task:
        await self.db.create_task(task)
        return task

    async def update_task(
        self,
        task_id: str,
        *,
        title: str | None = None,
        prompt: str | None = None,
        status: TaskStatus | None = None,
        parent_id: str | None = None,
        add_dependencies: Sequence[str] = (),
        remove_dependencies: Sequence[str] = (),
        agent_id: str | None = None,
        clear_agent: bool = False,
    ) -> Task:
        if (
            title is None
            and prompt is None
            and status is None
            and parent_id is None
            and not add_dependencies
            and not remove_dependencies
            and agent_id is None
            and not clear_agent
        ):
            raise EmptyTaskUpdateError("Nothing to update.")

        task = await self.db.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(f"Task not found: {task_id}")

        updates: dict[str, object] = {}
        content_changed = False
        if title is not None:
            updates["title"] = title
            content_changed = content_changed or title != task.title
        if prompt is not None:
            updates["prompt"] = prompt
            content_changed = content_changed or prompt != task.prompt
        if status is not None:
            updates["status"] = status
        relationship_changed = False
        if parent_id is not None:
            updates["parent_id"] = parent_id
            relationship_changed = parent_id != task.parent_id
        if add_dependencies or remove_dependencies:
            dependencies = list(task.dependencies)
            for dependency_id in add_dependencies:
                if dependency_id not in dependencies:
                    dependencies.append(dependency_id)
            for dependency_id in remove_dependencies:
                if dependency_id in dependencies:
                    dependencies.remove(dependency_id)
            updates["dependencies"] = dependencies
            relationship_changed = dependencies != task.dependencies
        if clear_agent:
            updates["agent_id"] = None
        elif agent_id is not None:
            updates["agent_id"] = agent_id

        updated_task = task.model_copy(update=updates)
        if (content_changed or relationship_changed) and updated_task.status != TaskStatus.APPROVED:
            updated_task = updated_task.requires_attention(
                AttentionReason.HUMAN_CHANGED_TASK,
                "Human updated task content or relationships",
            )
        updated = await self.db.update_task(updated_task)
        await self.db.record_task_event(task.id, "updated", "Task updated")
        await self.db.conn.commit()
        return updated

    async def add_human_comment(self, task_id: str, message: str, author_id: str) -> None:
        task = await self.db.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(f"Task not found: {task_id}")
        await self.db.add_task_comment(
            TaskComment(
                task_id=task.id,
                author_type=CommentAuthorType.HUMAN,
                author_id=author_id,
                message=message,
            )
        )
        if task.status != TaskStatus.APPROVED:
            updated = task.requires_attention(AttentionReason.HUMAN_COMMENTED, message)
            await self.db.update_task(updated)
        await self.db.conn.commit()

    async def add_conversation_message(self, task_id: str, raw_message: str) -> None:
        """Add a message to the task's conversation log.

        The raw_message must have an author prefix: "human: ..." or "system: ...".
        The prefix is parsed and stripped; only the content after ": " is stored.
        """
        task = await self.db.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(f"Task not found: {task_id}")

        # Parse author prefix
        if ": " not in raw_message:
            raise ValueError("Conversation message must have an author prefix: 'human: ...' or 'system: ...'")

        author_str, message = raw_message.split(": ", 1)
        author = author_str.strip().lower()
        if author not in ("human", "system"):
            raise ValueError(f"Invalid author '{author}'. Must be 'human' or 'system'.")

        msg = ConversationMessage(author=author, message=message)
        updated_task = task.model_copy(update={"conversation": [*task.conversation, msg]})
        if author == "human" and updated_task.status != TaskStatus.APPROVED:
            updated_task = updated_task.requires_attention(
                AttentionReason.HUMAN_COMMENTED,
                "Human added conversation message",
            )
        await self.db.update_task(updated_task)
        await self.db.conn.commit()

    async def approve_task(self, task_id: str) -> Task:
        task = await self.db.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(f"Task not found: {task_id}")
        if task.status not in {TaskStatus.DRAFT, TaskStatus.NEEDS_APPROVAL}:
            raise InvalidTaskApprovalError(f"Task {task.id} cannot be approved from status {task.status.value}.")
        updated = await self.db.update_task(task.clear_attention().model_copy(update={"status": TaskStatus.APPROVED}))
        await self.db.record_task_event(task.id, "approved", "Task approved")
        await self.db.conn.commit()
        return updated
