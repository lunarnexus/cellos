"""Repository for task event (audit trail) operations."""

import datetime
import uuid

from aiosqlite import Connection

from cellos.models import TaskEvent


def _row_to_event(row: tuple) -> TaskEvent:
    """Deserialize a database row into a TaskEvent model."""
    return TaskEvent(
        id=str(row[0]),
        task_id=row[1],
        event_type=row[2],
        message=row[3],
        timestamp=datetime.datetime.fromisoformat(row[4]),
    )


async def create_event(
    conn: Connection,
    task_id: str,
    event_type: str,
    message: str,
) -> TaskEvent:
    """Insert a new audit trail event and return the created model.

    Args:
        conn: Open async SQLite connection.
        task_id: Parent task reference.
        event_type: Event category (e.g., "status_changed", "planning_saved").
        message: Human-readable description of what happened.

    Returns:
        The newly created TaskEvent instance.
    """
    ts = datetime.datetime.now(datetime.timezone.utc)
    await conn.execute(
        "INSERT INTO task_events (task_id, event_type, message, created_at) VALUES (?, ?, ?, ?)",
        (task_id, event_type, message, ts.isoformat()),
    )

    cursor = await conn.execute("SELECT last_insert_rowid()")
    row = await cursor.fetchone()
    event_id = row[0]

    return TaskEvent(
        id=str(event_id),
        task_id=task_id,
        event_type=event_type,
        message=message,
        timestamp=ts,
    )


async def list_events(
    conn: Connection,
    task_id: str,
    limit: int = 50,
) -> list[TaskEvent]:
    """Retrieve the most recent events for a given task.

    Args:
        conn: Open async SQLite connection.
        task_id: Parent task reference to filter by.
        limit: Maximum number of events to return (default 50).

    Returns:
        List of TaskEvent models ordered newest-first.
    """
    cursor = await conn.execute(
        "SELECT id, task_id, event_type, message, created_at FROM task_events WHERE task_id = ? ORDER BY created_at DESC LIMIT ?",
        (task_id, limit),
    )

    rows = await cursor.fetchall()
    return [_row_to_event(row) for row in rows]
