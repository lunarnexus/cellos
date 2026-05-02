"""Async SQLite persistence for CelloS."""

import json
from pathlib import Path
from typing import Any

import aiosqlite

from cellos.models import Task, TaskResult, TaskStatus, utc_now


REQUIRED_TABLES = {"tasks", "task_dependencies", "task_results", "task_events"}


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
            """
        )
        await self.conn.commit()

    async def ensure_initialized(self) -> None:
        cursor = await self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN (?, ?, ?, ?)",
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


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload)
