"""Task event persistence for CelloS."""

import json
from typing import Any

import aiosqlite

from cellos.persistence.serialization import json_payload
from cellos.domain.time import utc_now


async def record_task_event(
    conn: aiosqlite.Connection,
    task_id: str,
    event_type: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO task_events (task_id, event_type, message, created_at, payload)
        VALUES (?, ?, ?, ?, json(?))
        """,
        (task_id, event_type, message, utc_now().isoformat(), json_payload(payload or {})),
    )


async def list_task_events(
    conn: aiosqlite.Connection,
    task_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
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
    cursor = await conn.execute(sql, params)
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
