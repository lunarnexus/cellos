"""Repository for task comment operations."""

import datetime
import json
import uuid
from typing import Optional

from aiosqlite import Connection

from cellos.models import CommentAuthorType, TaskComment
from cellos.persistence.json_util import dumps as _json_dumps


# ─── Helpers ────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _row_to_comment(row: tuple) -> TaskComment:
    """Deserialise a task_comments DB row into a TaskComment model."""
    id_, task_id, author_type, author_id, content, created_at = row
    return TaskComment(
        id=id_,
        task_id=task_id,
        author_type=author_type,  # type: ignore[arg-type]
        author_id=author_id or None,
        content=content,
        timestamp=datetime.datetime.fromisoformat(created_at),
    )


# ─── create_comment ────────────────────────────────────────────────────────

async def create_comment(
    conn: Connection,
    task_id: str,
    author_type: CommentAuthorType,
    content: str,
    author_id: Optional[str] = None,
) -> TaskComment:
    """Insert a new comment and keep the inline JSON array on ``tasks`` in sync.

    Writes to both storage locations so that:
    - The normalised ``task_comments`` table has a queryable row.
    - Loading the parent ``Task`` model via its inline ``comments`` column
      reflects this comment immediately without a separate join.

    Args:
        conn: Open async SQLite connection.
        task_id: Parent task ID the comment belongs to.
        author_type: Who authored the comment (human or system).
        content: Comment text.
        author_id: Optional identifier for attribution (e.g., user name).

    Returns:
        The newly created ``TaskComment`` model instance.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    now_iso = _now_iso()
    comment_id = uuid.uuid4().hex[:16]

    # 1. INSERT into task_comments table
    await conn.execute(
        "INSERT INTO task_comments (id, task_id, author_type, author_id, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (comment_id, task_id, author_type.value, author_id or "", content, now_iso),
    )

    # 2. Append to inline JSON comments array on tasks row
    cursor = await conn.execute(
        "SELECT comments FROM tasks WHERE id = ?",
        (task_id,),
    )
    row = await cursor.fetchone()
    if row is not None:
        existing_comments: list[dict] = json.loads(row[0])

        new_comment_dict = TaskComment(
            id=comment_id,
            task_id=task_id,
            author_type=author_type,
            author_id=author_id,
            content=content,
            timestamp=now,
        ).model_dump()
        existing_comments.append(new_comment_dict)

        await conn.execute(
            "UPDATE tasks SET comments = ?, updated_at = ? WHERE id = ?",
            (_json_dumps(existing_comments), _now_iso(), task_id),
        )

    await conn.commit()

    return TaskComment(
        id=comment_id,
        task_id=task_id,
        author_type=author_type,
        author_id=author_id,
        content=content,
        timestamp=now,
    )


# ─── list_comments ────────────────────────────────────────────────────────

async def list_comments(conn: Connection, task_id: str) -> list[TaskComment]:
    """Return all comments for a task ordered by creation time.

    Reads directly from the normalised ``task_comments`` table rather than
    parsing the inline JSON on the tasks row — this is more efficient when
    only comment data is needed.

    Args:
        conn: Open async SQLite connection.
        task_id: The parent task ID to fetch comments for.

    Returns:
        List of ``TaskComment`` models, ordered oldest-first.
    """
    cursor = await conn.execute(
        "SELECT id, task_id, author_type, author_id, content, created_at FROM task_comments WHERE task_id = ? ORDER BY created_at ASC",
        (task_id,),
    )
    rows = await cursor.fetchall()
    return [_row_to_comment(row) for row in rows]
