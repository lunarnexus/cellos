"""Task comment persistence for CelloS."""

import json
from typing import Any

import aiosqlite

from cellos.persistence.serialization import json_payload
from cellos.domain.comments import TaskComment


async def add_task_comment(
    conn: aiosqlite.Connection,
    comment: TaskComment,
) -> TaskComment:
    cursor = await conn.execute(
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
            json_payload(comment.metadata),
        ),
    )
    saved = comment.model_copy(update={"id": cursor.lastrowid})
    return saved


async def list_task_comments(
    conn: aiosqlite.Connection,
    task_id: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
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
    cursor = await conn.execute(sql, params)
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