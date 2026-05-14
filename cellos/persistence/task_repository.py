"""Task CRUD and query persistence for CelloS."""

from typing import Any

import json

from cellos.models import ConversationMessage, Task, TaskStatus, utc_now
from cellos.persistence.serialization import task_row


async def create_task(conn, task: Task) -> None:
    await conn.execute(
        """
        INSERT INTO tasks (
            id, parent_id, role, task_type, status, attention_required,
            assigned_worker_id, created_at, updated_at, payload, conversation
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        task_row(task),
    )


async def update_task(conn, task: Task) -> Task:
    updated = task.model_copy(update={"updated_at": utc_now()})
    await conn.execute(
        """
        UPDATE tasks
        SET parent_id = ?, role = ?, task_type = ?, status = ?,
            attention_required = ?, assigned_worker_id = ?,
            created_at = ?, updated_at = ?, payload = ?, conversation = ?
        WHERE id = ?
        """,
        (*task_row(updated)[1:], updated.id),
    )
    return updated


async def get_task(conn, task_id: str) -> Task | None:
    cursor = await conn.execute("SELECT payload, conversation FROM tasks WHERE id = ?", (task_id,))
    row = await cursor.fetchone()
    if row is None:
        return None
    task = Task.model_validate_json(row["payload"])
    if row["conversation"] is not None:
        try:
            task = task.model_copy(update={
                "conversation": [
                    ConversationMessage.model_validate(m)
                    for m in json.loads(row["conversation"])
                ]
            })
        except (json.JSONDecodeError, Exception):
            pass  # migration: old DB rows without conversation column
    return task


async def list_tasks(conn, status: TaskStatus | None = None) -> list[Task]:
    if status is None:
        cursor = await conn.execute("SELECT payload FROM tasks ORDER BY created_at")
    else:
        cursor = await conn.execute(
            "SELECT payload FROM tasks WHERE status = ? ORDER BY created_at",
            (status.value,),
        )
    rows = await cursor.fetchall()
    return [Task.model_validate_json(row["payload"]) for row in rows]


async def list_tasks_requiring_attention(conn, limit: int | None = None) -> list[Task]:
    sql = "SELECT payload FROM tasks WHERE attention_required = 1 ORDER BY updated_at"
    params: list[Any] = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    cursor = await conn.execute(sql, params)
    rows = await cursor.fetchall()
    return [Task.model_validate_json(row["payload"]) for row in rows]


async def list_tasks_ready_for_planning(conn, limit: int | None = None) -> list[Task]:
    sql = """
        SELECT t.payload
        FROM tasks t
        WHERE (t.status = ?
           OR (t.status = ? AND t.attention_required = 1))
          AND NOT EXISTS (
            SELECT 1
            FROM task_dependencies d
            JOIN tasks dep ON dep.id = d.depends_on_task_id
            WHERE d.task_id = t.id AND dep.status != ?
          )
        ORDER BY t.created_at
    """
    params: list[Any] = [TaskStatus.DRAFT.value, TaskStatus.NEEDS_APPROVAL.value, TaskStatus.DONE.value]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    cursor = await conn.execute(sql, params)
    rows = await cursor.fetchall()
    return [Task.model_validate_json(row["payload"]) for row in rows]


async def list_approved_unblocked_tasks(conn, limit: int | None = None) -> list[Task]:
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
    cursor = await conn.execute(sql, params)
    rows = await cursor.fetchall()
    return [Task.model_validate_json(row["payload"]) for row in rows]


async def list_tasks_depending_on(conn, task_id: str) -> list[Task]:
    cursor = await conn.execute(
        """
        SELECT t.payload
        FROM tasks t
        JOIN task_dependencies d ON d.task_id = t.id
        WHERE d.depends_on_task_id = ?
        ORDER BY t.created_at
        """,
        (task_id,),
    )
    rows = await cursor.fetchall()
    return [Task.model_validate_json(row["payload"]) for row in rows]


async def dependencies_satisfied(conn, task: Task) -> bool:
    if not task.dependencies:
        return True
    placeholders = ", ".join("?" for _ in task.dependencies)
    cursor = await conn.execute(
        f"SELECT COUNT(*) AS incomplete FROM tasks WHERE id IN ({placeholders}) AND status != ?",
        (*task.dependencies, TaskStatus.DONE.value),
    )
    row = await cursor.fetchone()
    return bool(row is not None and row["incomplete"] == 0)


async def update_task_status(conn, task_id: str, status: TaskStatus, task: Task) -> Task:
    if task is None:
        task = await get_task(conn, task_id)
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

    updated = await update_task(conn, task.model_copy(update=updates))
    return updated


async def replace_dependencies(conn, task: Task) -> None:
    await conn.execute("DELETE FROM task_dependencies WHERE task_id = ?", (task.id,))
    await conn.executemany(
        """
        INSERT OR IGNORE INTO task_dependencies (task_id, depends_on_task_id)
        VALUES (?, ?)
        """,
        [(task.id, dependency_id) for dependency_id in task.dependencies],
    )


async def fetchone(conn, sql: str, params: tuple[Any, ...]):
    cursor = await conn.execute(sql, params)
    return await cursor.fetchone()
