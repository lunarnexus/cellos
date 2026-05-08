"""Async SQLite persistence for CelloS."""

import json
from pathlib import Path
from typing import Any

import aiosqlite

from cellos.domain.attention import AttentionReason
from cellos.domain.attempts import TaskAttempt, TaskAttemptStatus
from cellos.domain.comments import TaskComment
from cellos.domain.enums import CommentAuthorType, TaskStatus, TaskType
from cellos.domain.results import TaskResult
from cellos.domain.tasks import Task
from cellos.domain.time import utc_now
from cellos.persistence.schema import (
    REQUIRED_TABLES,
    DatabaseNotInitialized,
    ensure_initialized,
    init_db,
)
from cellos.persistence.serialization import attempt_row, json_payload, task_row
from cellos.persistence.event_repository import list_task_events, record_task_event
from cellos.persistence.comment_repository import add_task_comment as _add_task_comment, list_task_comments as _list_task_comments
from cellos.persistence.attempt_repository import complete_task_attempt as _complete_task_attempt, list_task_attempts as _list_task_attempts, start_task_attempt as _start_task_attempt
from cellos.persistence.task_repository import (
    create_task as _create_task,
    dependencies_satisfied as _dependencies_satisfied,
    fetchone as _fetchone,
    get_task as _get_task,
    list_approved_unblocked_tasks as _list_approved_unblocked_tasks,
    list_tasks as _list_tasks,
    list_tasks_depending_on as _list_tasks_depending_on,
    list_tasks_ready_for_planning as _list_tasks_ready_for_planning,
    list_tasks_requiring_attention as _list_tasks_requiring_attention,
    replace_dependencies as _replace_dependencies,
    update_task as _update_task,
    update_task_status as _update_task_status,
)
from cellos.persistence.result_repository import (
    save_task_result as _save_task_result,
    _wake_satisfied_blocked_dependents as _wake_satisfied_blocked_dependents_repo,
    _add_dependency_result_comments as _add_dependency_result_comments_repo,
)


class CellosDatabase:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        return self._conn

    async def init_db(self) -> None:
        await init_db(self.conn)

    async def ensure_initialized(self) -> None:
        await ensure_initialized(self.conn, self.path)

    async def create_task(self, task: Task) -> None:
        await _create_task(self.conn, task)
        await self._replace_dependencies(task)
        await self.record_task_event(task.id, "created", "Task created")
        await self.conn.commit()

    async def update_task(self, task: Task) -> Task:
        updated = await _update_task(self.conn, task)
        await self._replace_dependencies(updated)
        await self.conn.commit()
        return updated

    async def get_task(self, task_id: str) -> Task | None:
        return await _get_task(self.conn, task_id)

    async def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        return await _list_tasks(self.conn, status=status)

    async def list_tasks_requiring_attention(self, limit: int | None = None) -> list[Task]:
        return await _list_tasks_requiring_attention(self.conn, limit=limit)

    async def list_tasks_ready_for_planning(self, limit: int | None = None) -> list[Task]:
        return await _list_tasks_ready_for_planning(self.conn, limit=limit)

    async def list_approved_unblocked_tasks(self, limit: int | None = None) -> list[Task]:
        return await _list_approved_unblocked_tasks(self.conn, limit=limit)

    async def list_tasks_depending_on(self, task_id: str) -> list[Task]:
        return await _list_tasks_depending_on(self.conn, task_id)

    async def dependencies_satisfied(self, task: Task) -> bool:
        return await _dependencies_satisfied(self.conn, task)

    async def list_task_events(self, task_id: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        return await list_task_events(self.conn, task_id=task_id, limit=limit)

    async def add_task_comment(self, comment: TaskComment) -> TaskComment:
        saved = await _add_task_comment(self.conn, comment)
        await record_task_event(self.conn, comment.task_id, "comment_added", f"{comment.author_type.value}: {comment.message}")
        await self.conn.commit()
        return saved

    async def list_task_comments(self, task_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        return await _list_task_comments(self.conn, task_id=task_id, limit=limit)

    async def start_task_attempt(self, attempt: TaskAttempt) -> TaskAttempt:
        saved = await _start_task_attempt(self.conn, attempt)
        await record_task_event(self.conn, attempt.task_id, "attempt_started", f"{attempt.mode} attempt started")
        await self.conn.commit()
        return saved

    async def complete_task_attempt(
        self,
        attempt_id: int,
        status: TaskAttemptStatus,
        result_summary: str,
        result_payload: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        await _complete_task_attempt(self.conn, attempt_id, status, result_summary, result_payload, error)
        row = await _fetchone(self.conn, "SELECT task_id, mode FROM task_attempts WHERE id = ?", (attempt_id,))
        if row is not None:
            await record_task_event(self.conn, row["task_id"], "attempt_completed", f"{row['mode']} attempt {status.value}")
        await self.conn.commit()

    async def list_task_attempts(self, task_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        return await _list_task_attempts(self.conn, task_id=task_id, limit=limit)

    async def update_task_status(self, task_id: str, status: TaskStatus) -> Task:
        task = await self.get_task(task_id)
        if task is None:
            raise KeyError(f"Task not found: {task_id}")

        updated = await _update_task_status(self.conn, task_id, status, task)
        await self.record_task_event(task_id, "status_changed", f"Task marked {status.value}")
        await self.conn.commit()
        return updated

    async def save_task_result(self, result: TaskResult) -> None:
        await _save_task_result(self.conn, result, self)

    async def record_task_event(
        self,
        task_id: str,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        await record_task_event(self.conn, task_id, event_type, message, payload)

    async def _replace_dependencies(self, task: Task) -> None:
        await _replace_dependencies(self.conn, task)

    async def _wake_satisfied_blocked_dependents(self, completed_task_id: str) -> None:
        await _wake_satisfied_blocked_dependents_repo(self.conn, completed_task_id, self)

    async def _add_dependency_result_comments(self, completed_task: Task, result: TaskResult) -> None:
        await _add_dependency_result_comments_repo(self.conn, completed_task, result, self)

    async def _fetchone(self, sql: str, params: tuple[Any, ...]):
        return await _fetchone(self.conn, sql, params)


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload)
