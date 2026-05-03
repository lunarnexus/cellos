"""Async SQLite persistence for CelloS."""

import json
from pathlib import Path
from typing import Any

import aiosqlite

from cellos.models import Task, TaskAttempt, TaskAttemptStatus, TaskComment, TaskResult, TaskStatus, utc_now


REQUIRED_TABLES = {
    "tasks",
    "task_dependencies",
    "task_results",
    "task_events",
    "task_comments",
    "task_attempts",
}


class DatabaseNotInitialized(RuntimeError):
    def __init__(self, path: Path):
        super().__init__(f"CelloS database is not initialized at {path}. Run `cellos init` first.")


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
        await self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                parent_id TEXT,
                role TEXT NOT NULL,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL,
                attention_required INTEGER NOT NULL,
                assigned_worker_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_dependencies (
                task_id TEXT NOT NULL,
                depends_on_task_id TEXT NOT NULL,
                PRIMARY KEY (task_id, depends_on_task_id),
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (depends_on_task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS task_results (
                task_id TEXT PRIMARY KEY,
                success INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS task_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                author_type TEXT NOT NULL,
                author_id TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS task_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                connector TEXT NOT NULL,
                status TEXT NOT NULL,
                prompt_snapshot TEXT NOT NULL,
                result_summary TEXT NOT NULL DEFAULT '',
                result_payload TEXT NOT NULL DEFAULT '{}',
                error TEXT,
                log_path TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL,
                completed_at TEXT,
                payload TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );
            """
        )
        await self.conn.commit()

    async def ensure_initialized(self) -> None:
        placeholders = ", ".join("?" for _ in REQUIRED_TABLES)
        cursor = await self.conn.execute(
            f"SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ({placeholders})",
            tuple(sorted(REQUIRED_TABLES)),
        )
        rows = await cursor.fetchall()
        found_tables = {row["name"] for row in rows}
        if found_tables != REQUIRED_TABLES:
            raise DatabaseNotInitialized(self.path)

    async def create_task(self, task: Task) -> None:
        await self.conn.execute(
            """
            INSERT INTO tasks (
                id, parent_id, role, task_type, status, attention_required,
                assigned_worker_id, created_at, updated_at, payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._task_row(task),
        )
        await self._replace_dependencies(task)
        await self.record_task_event(task.id, "created", "Task created")
        await self.conn.commit()

    async def update_task(self, task: Task) -> Task:
        updated = task.model_copy(update={"updated_at": utc_now()})
        await self.conn.execute(
            """
            UPDATE tasks
            SET parent_id = ?, role = ?, task_type = ?, status = ?,
                attention_required = ?, assigned_worker_id = ?,
                created_at = ?, updated_at = ?, payload = ?
            WHERE id = ?
            """,
            (*self._task_row(updated)[1:], updated.id),
        )
        await self._replace_dependencies(updated)
        await self.conn.commit()
        return updated

    async def get_task(self, task_id: str) -> Task | None:
        row = await self._fetchone("SELECT payload FROM tasks WHERE id = ?", (task_id,))
        return Task.model_validate_json(row["payload"]) if row else None

    async def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        if status is None:
            cursor = await self.conn.execute("SELECT payload FROM tasks ORDER BY created_at")
        else:
            cursor = await self.conn.execute(
                "SELECT payload FROM tasks WHERE status = ? ORDER BY created_at",
                (status.value,),
            )
        rows = await cursor.fetchall()
        return [Task.model_validate_json(row["payload"]) for row in rows]

    async def list_tasks_requiring_attention(self, limit: int | None = None) -> list[Task]:
        sql = "SELECT payload FROM tasks WHERE attention_required = 1 ORDER BY updated_at"
        params: list[Any] = []
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        cursor = await self.conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [Task.model_validate_json(row["payload"]) for row in rows]

    async def list_tasks_ready_for_planning(self, limit: int | None = None) -> list[Task]:
        sql = """
            SELECT payload
            FROM tasks
            WHERE status = ?
               OR (status = ? AND attention_required = 1)
            ORDER BY created_at
        """
        params: list[Any] = [TaskStatus.DRAFT.value, TaskStatus.NEEDS_APPROVAL.value]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        cursor = await self.conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [Task.model_validate_json(row["payload"]) for row in rows]

    async def list_approved_unblocked_tasks(self, limit: int | None = None) -> list[Task]:
        sql = """
            SELECT t.payload
            FROM tasks t
            WHERE t.status = ?
              AND NOT EXISTS (
                SELECT 1
                FROM task_dependencies d
                JOIN tasks dep ON dep.id = d.depends_on_task_id
                WHERE d.task_id = t.id AND dep.status != ?
              )
            ORDER BY t.created_at
        """
        params: list[Any] = [TaskStatus.APPROVED.value, TaskStatus.DONE.value]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        cursor = await self.conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [Task.model_validate_json(row["payload"]) for row in rows]

    async def list_task_events(self, task_id: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT id, task_id, event_type, message, created_at, payload
            FROM task_events
        """
        params: list[Any] = []
        if task_id is not None:
            sql += " WHERE task_id = ?"
            params.append(task_id)
        sql += " ORDER BY id"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        cursor = await self.conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "event_type": row["event_type"],
                "message": row["message"],
                "created_at": row["created_at"],
                "payload": json.loads(row["payload"]),
            }
            for row in rows
        ]

    async def add_task_comment(self, comment: TaskComment) -> TaskComment:
        cursor = await self.conn.execute(
            """
            INSERT INTO task_comments (task_id, author_type, author_id, message, created_at, payload)
            VALUES (?, ?, ?, ?, ?, json(?))
            """,
            (
                comment.task_id,
                comment.author_type.value,
                comment.author_id,
                comment.message,
                comment.created_at.isoformat(),
                _json(comment.metadata),
            ),
        )
        saved = comment.model_copy(update={"id": cursor.lastrowid})
        await self.record_task_event(comment.task_id, "comment_added", f"{comment.author_type.value}: {comment.message}")
        await self.conn.commit()
        return saved

    async def list_task_comments(self, task_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT id, task_id, author_type, author_id, message, created_at, payload
            FROM task_comments
            WHERE task_id = ?
            ORDER BY id
        """
        params: list[Any] = [task_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        cursor = await self.conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "author_type": row["author_type"],
                "author_id": row["author_id"],
                "message": row["message"],
                "created_at": row["created_at"],
                "payload": json.loads(row["payload"]),
            }
            for row in rows
        ]

    async def start_task_attempt(self, attempt: TaskAttempt) -> TaskAttempt:
        cursor = await self.conn.execute(
            """
            INSERT INTO task_attempts (
                task_id, mode, agent_id, connector, status, prompt_snapshot,
                result_summary, result_payload, error, log_path, started_at,
                completed_at, payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, json(?), ?, ?, ?, ?, json(?))
            """,
            self._attempt_row(attempt),
        )
        saved = attempt.model_copy(update={"id": cursor.lastrowid})
        await self.record_task_event(attempt.task_id, "attempt_started", f"{attempt.mode} attempt started")
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
        completed_at = utc_now()
        await self.conn.execute(
            """
            UPDATE task_attempts
            SET status = ?, result_summary = ?, result_payload = json(?), error = ?, completed_at = ?
            WHERE id = ?
            """,
            (
                status.value,
                result_summary,
                _json(result_payload or {}),
                error,
                completed_at.isoformat(),
                attempt_id,
            ),
        )
        row = await self._fetchone("SELECT task_id, mode FROM task_attempts WHERE id = ?", (attempt_id,))
        if row is not None:
            await self.record_task_event(row["task_id"], "attempt_completed", f"{row['mode']} attempt {status.value}")
        await self.conn.commit()

    async def list_task_attempts(self, task_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT id, task_id, mode, agent_id, connector, status, prompt_snapshot,
                   result_summary, result_payload, error, log_path, started_at,
                   completed_at, payload
            FROM task_attempts
            WHERE task_id = ?
            ORDER BY id
        """
        params: list[Any] = [task_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        cursor = await self.conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "mode": row["mode"],
                "agent_id": row["agent_id"],
                "connector": row["connector"],
                "status": row["status"],
                "prompt_snapshot": row["prompt_snapshot"],
                "result_summary": row["result_summary"],
                "result_payload": json.loads(row["result_payload"]),
                "error": row["error"],
                "log_path": row["log_path"],
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "payload": json.loads(row["payload"]),
            }
            for row in rows
        ]

    async def update_task_status(self, task_id: str, status: TaskStatus) -> Task:
        task = await self.get_task(task_id)
        if task is None:
            raise KeyError(f"Task not found: {task_id}")

        updates: dict[str, Any] = {"status": status, "updated_at": utc_now()}
        if status == TaskStatus.IN_PROGRESS and task.started_at is None:
            updates["started_at"] = utc_now()
        if status in {
            TaskStatus.DONE,
            TaskStatus.FAILED,
            TaskStatus.CHANGE_REQUESTED,
            TaskStatus.CANCELLED,
        }:
            updates["completed_at"] = utc_now()

        updated = await self.update_task(task.model_copy(update=updates))
        await self.record_task_event(task_id, "status_changed", f"Task marked {status.value}")
        await self.conn.commit()
        return updated

    async def save_task_result(self, result: TaskResult) -> None:
        await self.conn.execute(
            """
            INSERT INTO task_results (task_id, success, created_at, payload)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                success = excluded.success,
                created_at = excluded.created_at,
                payload = excluded.payload
            """,
            (
                result.task_id,
                int(result.success),
                result.created_at.isoformat(),
                result.model_dump_json(),
            ),
        )
        task = await self.get_task(result.task_id)
        if task is not None:
            if result.change_request is not None:
                status = TaskStatus.CHANGE_REQUESTED
            else:
                status = TaskStatus.DONE if result.success else TaskStatus.FAILED
            await self.update_task(task.model_copy(update={"result": result, "status": status}))
        await self.record_task_event(result.task_id, "result_saved", result.summary)
        await self.conn.commit()

    async def record_task_event(
        self,
        task_id: str,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO task_events (task_id, event_type, message, created_at, payload)
            VALUES (?, ?, ?, ?, json(?))
            """,
            (task_id, event_type, message, utc_now().isoformat(), _json(payload or {})),
        )

    async def _replace_dependencies(self, task: Task) -> None:
        await self.conn.execute("DELETE FROM task_dependencies WHERE task_id = ?", (task.id,))
        await self.conn.executemany(
            """
            INSERT OR IGNORE INTO task_dependencies (task_id, depends_on_task_id)
            VALUES (?, ?)
            """,
            [(task.id, dependency_id) for dependency_id in task.dependencies],
        )

    async def _fetchone(self, sql: str, params: tuple[Any, ...]) -> aiosqlite.Row | None:
        cursor = await self.conn.execute(sql, params)
        return await cursor.fetchone()

    @staticmethod
    def _task_row(task: Task) -> tuple[Any, ...]:
        return (
            task.id,
            task.parent_id,
            task.role.value,
            task.task_type.value,
            task.status.value,
            int(task.attention.required),
            task.assigned_worker_id,
            task.created_at.isoformat(),
            task.updated_at.isoformat(),
            task.model_dump_json(),
        )

    @staticmethod
    def _attempt_row(attempt: TaskAttempt) -> tuple[Any, ...]:
        return (
            attempt.task_id,
            attempt.mode,
            attempt.agent_id,
            attempt.connector,
            attempt.status.value,
            attempt.prompt_snapshot,
            attempt.result_summary,
            _json(attempt.result_payload),
            attempt.error,
            attempt.log_path,
            attempt.started_at.isoformat(),
            attempt.completed_at.isoformat() if attempt.completed_at is not None else None,
            _json(attempt.metadata),
        )


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload)
