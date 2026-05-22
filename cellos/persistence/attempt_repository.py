"""Repository for task attempt lifecycle operations."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from aiosqlite import Connection

from cellos.models import TaskAttempt, TaskAttemptStatus


# ─── Helpers ────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _attempt_id() -> str:
    """Generate a short hex attempt ID (UUID-4, first 16 chars)."""
    return uuid.uuid4().hex[:16]


# ─── create_attempt ─────────────────────────────────────────────────────────

async def create_attempt(
    conn: Connection,
    task_id: str,
    mode: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> TaskAttempt:
    """Create a new attempt record for *task_id* and return the model.

    Inserts into ``task_attempts`` with status ``'started'`` and returns
    the freshly created ``TaskAttempt`` instance.

    Args:
        conn: Open async SQLite connection.
        task_id: The parent task this attempt belongs to.
        mode: Optional execution context (e.g. ``"planning"``, ``"execution"``).
        agent_id: Optional identifier of the agent handling this attempt.

    Returns:
        The created :class:`TaskAttempt` model.
    """
    now = _now_iso()
    attempt_id = _attempt_id()

    await conn.execute(
        "INSERT INTO task_attempts (id, task_id, status, mode, agent_id, started_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            attempt_id,
            task_id,
            TaskAttemptStatus.STARTED.value,
            mode or "",
            agent_id or "",
            now,
        ),
    )
    await conn.commit()

    return TaskAttempt(
        id=attempt_id,
        task_id=task_id,
        status=TaskAttemptStatus.STARTED,
        mode=mode,
        agent_id=agent_id,
        started_at=datetime.fromisoformat(now),
    )


# ─── update_attempt ────────────────────────────────────────────────────────

async def update_attempt(
    conn: Connection,
    attempt_id: str,
    status: TaskAttemptStatus,
    result_summary: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """Update an existing attempt's status and optional outcome fields.

    Sets ``completed_at`` to *now* for terminal statuses (succeeded / failed).

    Args:
        conn: Open async SQLite connection.
        attempt_id: The attempt to update.
        status: New :class:`TaskAttemptStatus` value.
        result_summary: Brief outcome description (for successful attempts).
        error_message: Failure reason text (for failed attempts).
    """
    columns = ["status = ?"]
    params: list = [status.value]

    # Set completed_at for terminal states
    if status in (TaskAttemptStatus.SUCCEEDED, TaskAttemptStatus.FAILED):
        now = _now_iso()
        columns.append("completed_at = ?")
        params.append(now)

    if result_summary is not None:
        columns.append("result_summary = ?")
        params.append(result_summary)

    if error_message is not None:
        columns.append("error_message = ?")
        params.append(error_message)

    params.append(attempt_id)

    await conn.execute(
        f"UPDATE task_attempts SET {', '.join(columns)} WHERE id = ?",
        params,
    )
    await conn.commit()


# ─── list_attempts ──────────────────────────────────────────────────────────

async def list_attempts(conn: Connection, task_id: str) -> list[TaskAttempt]:
    """Return all attempts for a given task, newest first.

    Args:
        conn: Open async SQLite connection.
        task_id: The parent task to query attempts for.

    Returns:
        A list of :class:`TaskAttempt` models ordered by ``started_at`` descending.
    """
    cursor = await conn.execute(
        "SELECT id, task_id, status, mode, agent_id, result_summary, error_message, started_at, completed_at FROM task_attempts WHERE task_id = ? ORDER BY started_at DESC",
        (task_id,),
    )
    rows = await cursor.fetchall()

    attempts: list[TaskAttempt] = []
    for row in rows:
        attempt = TaskAttempt(
            id=row[0],
            task_id=row[1],
            status=TaskAttemptStatus(row[2]),
            mode=row[3] or None,
            agent_id=row[4] or None,
            result_summary=row[5] or None,
            error_message=row[6] or None,
            started_at=datetime.fromisoformat(row[7]) if row[7] else datetime.now(timezone.utc),
            completed_at=datetime.fromisoformat(row[8]) if row[8] else None,
        )
        attempts.append(attempt)

    return attempts
