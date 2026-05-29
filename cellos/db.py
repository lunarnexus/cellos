"""CellosDatabase — async SQLite facade wrapping repository functions."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Optional

import aiosqlite

from cellos.models import (
    AttentionMetadata,
    CommentAuthorType,
    ConversationMessage,
    ProcessingMetadata,
    Task,
    TaskAttempt,
    TaskComment,
    TaskDependency,
    TaskEvent,
    TaskResult,
    TaskStatus,
)

from cellos.persistence.attempt_repository import (
    create_attempt as _create_attempt,
    get_attempt as _get_attempt,
    list_attempts as _list_attempts,
    update_attempt as _update_attempt,
)
from cellos.persistence.comment_repository import (
    create_comment as _create_comment,
    list_comments as _list_comments,
)
from cellos.persistence.event_repository import (
    create_event as _create_event,
    list_events as _list_events,
)
from cellos.persistence.result_repository import (
    add_dependency_result_comment as _add_dep_comment,
    complete_parent_if_all_children_done as _complete_parent,
    save_task_result as _save_task_result,
    wake_blocked_dependents as _wake_blocked,
)
from cellos.persistence.schema import DatabaseNotInitialized, ensure_initialized, init_db
from cellos.persistence.task_repository import (
    _replace_dependencies,
    create_task as _create_task,
    get_task as _get_task,
    list_child_tasks as _list_child_tasks,
    list_approved_unblocked_tasks as _list_approved_unblocked,
    list_tasks as _list_tasks,
    list_tasks_depending_on as _list_dependents,
    list_tasks_ready_for_planning as _list_planning_candidates,
    list_tasks_requiring_attention as _list_attention_tasks,
    update_task as _update_task,
    update_task_status as _update_task_status,
)


class CellosDatabase:
    """Async SQLite facade over persistence repositories.

    Manages connection lifecycle and delegates CRUD/scheduler queries to
    function-based repository modules.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._conn: Optional[aiosqlite.Connection] = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    async def connect(self, foreign_keys: bool = True) -> aiosqlite.Connection:
        """Open the SQLite connection."""
        await ensure_initialized(self.db_path)
        self._conn = await aiosqlite.connect(self.db_path)
        if foreign_keys:
            await self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    async def connect_without_fk(self) -> aiosqlite.Connection:
        """Open without FK enforcement (for testing/migrations)."""
        await ensure_initialized(self.db_path)
        self._conn = await aiosqlite.connect(self.db_path)
        return self._conn

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # ── Task CRUD ────────────────────────────────────────────────

    async def create_task(self, task: Task) -> None:
        """Insert a new task and record the creation event."""
        conn = self.conn
        await _create_task(conn, task)
        await _create_event(
            conn, task.id, "task_created", f"Task created: {task.title}"
        )
        await conn.commit()

    async def get_task(self, task_id: str) -> Optional[Task]:
        return await _get_task(self.conn, task_id)

    async def list_tasks(
        self, status_filter: Optional[str] = None
    ) -> list[Task]:
        return await _list_tasks(self.conn, status_filter=status_filter)

    async def list_child_tasks(self, parent_id: str) -> list[Task]:
        return await _list_child_tasks(self.conn, parent_id)

    async def update_task(self, task: Task) -> bool:
        """Update a task and commit. Returns True if row existed."""
        conn = self.conn
        result = await _update_task(conn, task)
        await conn.commit()
        return result

    async def update_task_status(
        self, task_id: str, new_status: TaskStatus
    ) -> None:
        """Partial status update with event recording."""
        old_task = await _get_task(self.conn, task_id)
        if not old_task:
            raise ValueError(f"Task {task_id} not found")

        conn = self.conn
        await _update_task_status(conn, task_id, new_status)
        await _create_event(
            conn,
            task_id,
            "status_changed",
            f"Status changed from {old_task.status.value} to {new_status.value}",
        )
        await conn.commit()

    # ── Scheduler queries ────────────────────────────────────────

    async def list_tasks_requiring_attention(self) -> list[Task]:
        return await _list_attention_tasks(self.conn)

    async def list_tasks_ready_for_planning(self) -> list[Task]:
        return await _list_planning_candidates(self.conn)

    async def list_approved_unblocked_tasks(
        self, max_results: int = 10
    ) -> list[Task]:
        return await _list_approved_unblocked(self.conn, max_results=max_results)

    # ── Dependencies ─────────────────────────────────────────────

    async def add_dependencies(
        self, task_id: str, dependencies: list[TaskDependency]
    ) -> None:
        """Add new dependencies to a task (merge with existing)."""
        conn = self.conn
        task = await _get_task(conn, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        # Merge: keep existing deps that don't overlap, add new ones
        existing_ids = {d.task_id for d in task.dependencies}
        merged = list(task.dependencies)
        for dep in dependencies:
            if dep.task_id not in existing_ids:
                merged.append(dep)

        await _update_task(conn, task.model_copy(update={"dependencies": merged}))
        await _replace_dependencies(conn, task_id, merged)
        await conn.commit()

    async def remove_dependencies(self, task_id: str, dep_ids: list[str]) -> None:
        """Remove specific dependencies from a task."""
        conn = self.conn
        task = await _get_task(conn, task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        remaining = [d for d in task.dependencies if d.task_id not in dep_ids]
        await _update_task(conn, task.model_copy(update={"dependencies": remaining}))
        await _replace_dependencies(conn, task_id, remaining)
        await conn.commit()

    async def dependencies_satisfied(self, task_id: str) -> bool:
        """Check if all dependencies for a task are satisfied."""
        task = await _get_task(self.conn, task_id)
        if not task or not task.dependencies:
            return True
        return all(d.status_satisfied for d in task.dependencies)

    async def list_tasks_depending_on(self, task_id: str) -> list[int]:
        """Return junction table row IDs of tasks depending on this one."""
        return await _list_dependents(self.conn, task_id)

    # ── Results ───────────────────────────────────────────────────

    async def save_task_result(
        self,
        task_id: str,
        success: bool,
        summary: str,
        output: Optional[str] = None,
    ) -> list[str]:
        """Save a result, wake blocked dependents, check parent completion.

        Returns list of affected task IDs (dependents + parent if transitioned).
        """
        conn = self.conn
        await _save_task_result(conn, task_id, success, summary, output=output)

        event_type = "execution_succeeded" if success else "execution_failed"
        await _create_event(
            conn, task_id, event_type, summary or "Execution completed"
        )

        affected = await _wake_blocked(conn, task_id)
        for parent_id in affected:
            await _add_dep_comment(conn, parent_id, task_id)

        # Check if parent should transition (all children done or any failed)
        parent_id = await _complete_parent(conn, task_id)
        if parent_id:
            await _create_event(
                conn, parent_id, "status_changed",
                f"Parent task status updated due to child {task_id} completion."
            )
            if parent_id not in affected:
                affected.append(parent_id)

        await conn.commit()
        return affected

    # ── Events ────────────────────────────────────────────────────

    async def create_event(
        self, task_id: str, event_type: str, message: str
    ) -> TaskEvent:
        event = await _create_event(self.conn, task_id, event_type, message)
        await self.conn.commit()
        return event

    async def list_events(
        self, task_id: str, limit: int = 50
    ) -> list[TaskEvent]:
        return await _list_events(self.conn, task_id, limit=limit)

    # ── Comments ──────────────────────────────────────────────────

    async def create_comment(
        self,
        task_id: str,
        author_type: CommentAuthorType,
        content: str,
        author_id: Optional[str] = None,
    ) -> TaskComment:
        comment = await _create_comment(
            self.conn, task_id, author_type, content, author_id=author_id
        )
        await self.conn.commit()
        return comment

    async def list_comments(self, task_id: str) -> list[TaskComment]:
        return await _list_comments(self.conn, task_id)

    # ── Attempts ──────────────────────────────────────────────────

    async def create_attempt(
        self,
        task_id: str,
        mode: Optional[str] = None,
        agent_id: Optional[str] = None,
        diagnostics: Optional[dict] = None,
    ) -> TaskAttempt:
        attempt = await _create_attempt(
            self.conn, task_id, mode=mode, agent_id=agent_id, diagnostics=diagnostics
        )
        await self.conn.commit()
        return attempt

    async def update_attempt(
        self,
        attempt_id: str,
        status: TaskStatus,  # Note: uses TaskAttemptStatus in repo but exposed as TaskStatus here for type safety
        result_summary: Optional[str] = None,
        error_message: Optional[str] = None,
        diagnostics: Optional[dict] = None,
    ) -> None:
        from cellos.models import TaskAttemptStatus

        attempt_status_map = {
            TaskStatus.DONE: TaskAttemptStatus.SUCCEEDED,
            TaskStatus.FAILED: TaskAttemptStatus.FAILED,
            TaskStatus.CANCELLED: TaskAttemptStatus.FAILED,
        }
        repo_status = attempt_status_map.get(status, TaskAttemptStatus.STARTED)

        await _update_attempt(
            self.conn, attempt_id, repo_status,
            result_summary=result_summary, error_message=error_message, diagnostics=diagnostics
        )
        await self.conn.commit()

    async def get_attempt(self, attempt_id: str) -> Optional[TaskAttempt]:
        return await _get_attempt(self.conn, attempt_id)

    async def list_attempts(self, task_id: str) -> list[TaskAttempt]:
        return await _list_attempts(self.conn, task_id)


async def init_database(db_path: str | Path) -> None:
    """Top-level convenience: initialize DB and verify."""
    await init_db(db_path)
    db = CellosDatabase(db_path)
    await db.connect()
    await db.close()
