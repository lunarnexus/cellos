"""Task persistence layer — function-based async SQLite repository."""

from __future__ import annotations

import datetime
import json
from typing import Optional

from aiosqlite import Connection

from cellos.persistence.json_util import dumps as _json_dumps

from cellos.models import (
    AgentRole,
    AttentionMetadata,
    ConversationMessage,
    ProcessingMetadata,
    Task,
    TaskComment,
    TaskDependency,
    TaskResult,
    TaskStatus,
)


def _task_row_to_task(row: tuple, columns: list[str]) -> Task:
    """Deserialize a database row (tuple + column names) into a Task model."""
    data = dict(zip(columns, row))

    # Deserialize JSON columns
    raw_deps = data["dependencies"] or "[]"
    data["dependencies"] = [TaskDependency.model_validate(d) for d in json.loads(raw_deps)] if raw_deps else []

    raw_attention = data["attention"] or "{}"
    data["attention"] = AttentionMetadata.model_validate(json.loads(raw_attention))

    raw_processing = data["processing"] or "{}"
    data["processing"] = ProcessingMetadata.model_validate(json.loads(raw_processing))

    raw_conversation = data["conversation"] or "[]"
    data["conversation"] = [ConversationMessage.model_validate(m) for m in json.loads(raw_conversation)] if raw_conversation else []

    raw_result = data.get("result") or ""
    data["result"] = TaskResult.model_validate(json.loads(raw_result)) if raw_result and raw_result != "null" else None

    raw_comments = data["comments"] or "[]"
    data["comments"] = [TaskComment.model_validate(c) for c in json.loads(raw_comments)] if raw_comments else []

    return Task(**data)


async def _fetch_columns(conn: Connection, query: str, params: tuple = ()) -> list[tuple[list[str], tuple]]:
    """Execute a query and return (columns, row_tuples)."""
    cursor = await conn.execute(query, params)
    columns = [desc[0] for desc in cursor.description] if cursor.description else []
    rows = await cursor.fetchall()
    return [(columns, r) for r in rows]


async def _fetch_one(conn: Connection, query: str, params: tuple = ()) -> Optional[tuple[list[str], tuple]]:
    """Execute a query and return (columns, row_tuple) or None."""
    cursor = await conn.execute(query, params)
    columns = [desc[0] for desc in cursor.description] if cursor.description else []
    row = await cursor.fetchone()
    if row is None:
        return None
    return (columns, row)


async def create_task(conn: Connection, task: Task) -> None:
    """INSERT a new task row."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    await conn.execute(
        """INSERT INTO tasks (
            id, title, details, status, role, task_type, plan, prompt_text,
            parent_id, agent_id, success_criteria, failure_criteria,
            dependencies, attention, processing, conversation, result, comments,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            task.id,
            task.title,
            task.details or "",
            str(task.status),
            str(task.role),
            str(task.task_type),
            task.plan or "",
            task.prompt_text or "",
            task.parent_id or "",
            task.agent_id or "",
            task.success_criteria or "",
            task.failure_criteria or "",
            _json_dumps([d.model_dump() for d in task.dependencies]),
            _json_dumps(task.attention.model_dump()),
            _json_dumps(task.processing.model_dump()),
            _json_dumps([m.model_dump() for m in task.conversation]),
            _json_dumps(task.result.model_dump()) if task.result else "",
            _json_dumps([c.model_dump() for c in task.comments]),
            now,
            now,
        ),
    )
    # Sync junction table with inline dependencies
    if task.dependencies:
        await _replace_dependencies(conn, task.id, task.dependencies)


async def get_task(conn: Connection, task_id: str) -> Optional[Task]:
    """SELECT a single task by ID and deserialize JSON columns."""
    result = await _fetch_one(conn, "SELECT * FROM tasks WHERE id = ?", (task_id,))
    if result is None:
        return None
    cols, row = result
    return _task_row_to_task(row, cols)


async def list_tasks(
    conn: Connection, status_filter: Optional[str] = None
) -> list[Task]:
    """List all tasks, optionally filtered by status."""
    query = "SELECT * FROM tasks"
    params: tuple = ()

    if status_filter is not None:
        query += " WHERE status = ?"
        params = (status_filter,)

    query += " ORDER BY created_at DESC"
    results = await _fetch_columns(conn, query, params)
    return [_task_row_to_task(row, cols) for cols, row in results]


async def update_task(conn: Connection, task: Task) -> bool:
    """UPDATE an existing task row. Returns True if the row existed."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cursor = await conn.execute(
        """UPDATE tasks SET
            title = ?, details = ?, status = ?, role = ?, task_type = ?,
            plan = ?, prompt_text = ?, parent_id = ?, agent_id = ?,
            success_criteria = ?, failure_criteria = ?, dependencies = ?,
            attention = ?, processing = ?, conversation = ?, result = ?,
            comments = ?, updated_at = ?
        WHERE id = ?""",
        (
            task.title,
            task.details or "",
            str(task.status),
            str(task.role),
            str(task.task_type),
            task.plan or "",
            task.prompt_text or "",
            task.parent_id or "",
            task.agent_id or "",
            task.success_criteria or "",
            task.failure_criteria or "",
            _json_dumps([d.model_dump() for d in task.dependencies]),
            _json_dumps(task.attention.model_dump()),
            _json_dumps(task.processing.model_dump()),
            _json_dumps([m.model_dump() for m in task.conversation]),
            _json_dumps(task.result.model_dump()) if task.result else "",
            _json_dumps([c.model_dump() for c in task.comments]),
            now,
            task.id,
        ),
    )
    return cursor.rowcount > 0


async def update_task_status(
    conn: Connection, task_id: str, new_status: TaskStatus
) -> None:
    """Partial update — only change the status and updated_at timestamp."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    await conn.execute(
        "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
        (str(new_status), now, task_id),
    )


async def list_tasks_requiring_attention(conn: Connection) -> list[Task]:
    """List tasks where attention.required is true via json_extract."""
    results = await _fetch_columns(
        conn, "SELECT * FROM tasks WHERE json_extract(attention, '$.required') = 1 ORDER BY created_at DESC"
    )
    return [_task_row_to_task(row, cols) for cols, row in results]


async def list_tasks_ready_for_planning(conn: Connection) -> list[Task]:
    """List tasks ready for planning: draft/needs_approval of any role."""
    results = await _fetch_columns(
        conn, "SELECT * FROM tasks WHERE status IN ('draft', 'needs_approval') ORDER BY created_at DESC"
    )
    return [_task_row_to_task(row, cols) for cols, row in results]


async def list_approved_unblocked_tasks(
    conn: Connection, max_results: int = 10
) -> list[Task]:
    """List approved tasks where all dependencies are satisfied (engineer/researcher/tester only)."""
    query = (
        "SELECT t.* FROM tasks t"
        " LEFT JOIN task_dependencies td ON t.id = td.task_id"
        " WHERE t.status = 'approved'"
        " AND t.role IN ('engineer', 'researcher', 'tester')"
        " GROUP BY t.id"
        " HAVING COUNT(CASE WHEN NOT td.status_satisfied THEN 1 END) = 0"
        " ORDER BY t.created_at ASC"
        f" LIMIT {max_results}"
    )
    results = await _fetch_columns(conn, query)
    return [_task_row_to_task(row, cols) for cols, row in results]


async def _replace_dependencies(
    conn: Connection, task_id: str, deps: list[TaskDependency]
) -> None:
    """Delete old junction table rows and insert new ones."""
    await conn.execute(
        "DELETE FROM task_dependencies WHERE task_id = ?", (task_id,)
    )
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for dep in deps:
        await conn.execute(
            "INSERT INTO task_dependencies"
            " (task_id, depends_on_task_id, status_satisfied, created_at)"
            " VALUES (?, ?, ?, ?)",
            (task_id, dep.task_id, 1 if dep.status_satisfied else 0, now),
        )


async def list_tasks_depending_on(conn: Connection, task_id: str) -> list[int]:
    """Return the integer primary keys of junction rows for tasks that depend on the given task."""
    cursor = await conn.execute(
        "SELECT id FROM task_dependencies WHERE depends_on_task_id = ?", (task_id,)
    )
    rows = await cursor.fetchall()
    return [r[0] for r in rows]
