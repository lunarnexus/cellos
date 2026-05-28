"""Repository for task result, dependency resolution, and comment operations."""

from datetime import datetime, timezone
import json
import uuid
from typing import Optional

from aiosqlite import Connection

from cellos.persistence.json_util import dumps as _json_dumps

from cellos.models import (
    AttentionMetadata,
    CommentAuthorType,
    TaskComment,
    TaskDependency,
    TaskResult,
)


# ─── Helpers ────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


# ─── save_task_result ───────────────────────────────────────────────────────

async def save_task_result(
    conn: Connection,
    task_id: str,
    success: bool,
    summary: str,
    output: Optional[str] = None,
) -> None:
    """Persist a task execution result and update the inline JSON on the tasks row.

    Inserts a row into ``task_results`` (historical record per attempt) and
    writes the serialised ``TaskResult`` object back to ``tasks.result`` so
    that loading a Task model gives immediate access to its latest outcome.

    Args:
        conn: Open async SQLite connection.
        task_id: The task whose result is being recorded.
        success: Whether execution succeeded.
        summary: Brief description of the result.
        output: Full agent output (truncated by caller if needed).
    """
    now = datetime.now(timezone.utc)

    # 1. INSERT into task_results table
    await conn.execute(
        "INSERT INTO task_results (task_id, success, summary, output, created_at) VALUES (?, ?, ?, ?, ?)",
        (task_id, int(success), summary, output or "", now.isoformat()),
    )

    # 2. Update tasks.result column with JSON TaskResult object
    result = TaskResult(
        success=success,
        summary=summary,
        output=output,
        timestamp=now,
    )
    await conn.execute(
        "UPDATE tasks SET result = ?, updated_at = ? WHERE id = ?",
        (result.model_dump_json(), _now_iso(), task_id),
    )

    await conn.commit()


# ─── wake_blocked_dependents ────────────────────────────────────────────────

async def wake_blocked_dependents(conn: Connection, completed_task_id: str) -> list[str]:
    """Unblock tasks that depend on the given completed task.

    For every task whose dependency chain references *completed_task_id*:

    1. Mark ``status_satisfied=True`` in the ``task_dependencies`` junction table.
    2. Update the inline JSON ``dependencies`` array on each affected ``tasks`` row.
    3. Set ``attention.required=True`` with reason ``dependency_done`` so the
       scheduler / CLI surfaces these tasks for review.

    Args:
        conn: Open async SQLite connection.
        completed_task_id: The task that just finished and may unblock others.

    Returns:
        List of affected (now satisfied) dependent task IDs.
    """
    # Find all junction rows where depends_on = the completed task AND not yet satisfied
    cursor = await conn.execute(
        "SELECT id, task_id FROM task_dependencies WHERE depends_on_task_id = ? AND status_satisfied = 0",
        (completed_task_id,),
    )
    unsatisfied_rows = await cursor.fetchall()

    if not unsatisfied_rows:
        return []

    affected_task_ids: list[str] = []

    for row in unsatisfied_rows:
        junction_id, dependent_task_id = row[0], row[1]

        # 1. Mark satisfied in the junction table
        await conn.execute(
            "UPDATE task_dependencies SET status_satisfied = 1 WHERE id = ?",
            (junction_id,),
        )

        # 2. Update inline JSON dependencies on the dependent task row
        cursor_t = await conn.execute(
            "SELECT dependencies FROM tasks WHERE id = ?",
            (dependent_task_id,),
        )
        dep_row = await cursor_t.fetchone()
        if dep_row is None:
            continue

        dependencies: list[dict] = json.loads(dep_row[0])
        updated_dependencies = []
        for dep in dependencies:
            if dep["task_id"] == completed_task_id:
                dep["status_satisfied"] = True
            updated_dependencies.append(dep)

        await conn.execute(
            "UPDATE tasks SET dependencies = ?, updated_at = ? WHERE id = ?",
            (_json_dumps(updated_dependencies), _now_iso(), dependent_task_id),
        )

        # 3. Set attention.required=True with reason 'dependency_done'
        cursor_a = await conn.execute(
            "SELECT attention FROM tasks WHERE id = ?",
            (dependent_task_id,),
        )
        att_row = await cursor_a.fetchone()
        if att_row is None:
            continue

        current_attention: dict = json.loads(att_row[0])
        new_attention = AttentionMetadata.required_attention(
            reason="dependency_done",  # type: ignore[arg-type]
            detail=f"Dependency task {completed_task_id} has completed.",
        )
        merged_attention = {**current_attention, **new_attention.model_dump()}

        await conn.execute(
            "UPDATE tasks SET attention = ?, updated_at = ? WHERE id = ?",
            (_json_dumps(merged_attention), _now_iso(), dependent_task_id),
        )

        affected_task_ids.append(dependent_task_id)

    await conn.commit()
    return affected_task_ids


# ─── add_dependency_result_comment ──────────────────────────────────────────

async def add_dependency_result_comment(
    conn: Connection,
    parent_task_id: str,
    completed_task_id: str,
) -> None:
    """Add a system comment to *parent_task* noting that its dependency completed.

    The comment is inserted both into the ``task_comments`` table (normalised
    storage) and appended to the inline JSON ``comments`` array on the parent's
    ``tasks`` row so that loading the Task model reflects it immediately.

    Args:
        conn: Open async SQLite connection.
        parent_task_id: The task whose dependency was satisfied.
        completed_task_id: The dependency task that just finished.
    """
    comment_content = (
        f"Dependency task {completed_task_id} has completed. "
        f"This may unblock further work on this task."
    )

    now_iso = _now_iso()
    timestamp = datetime.now(timezone.utc)

    # 1. Insert into task_comments table
    comment_id = uuid.uuid4().hex[:16]
    await conn.execute(
        "INSERT INTO task_comments (id, task_id, author_type, author_id, content, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (comment_id, parent_task_id, CommentAuthorType.SYSTEM.value, "", comment_content, now_iso),
    )

    # 2. Append to inline JSON comments array on tasks row
    cursor = await conn.execute(
        "SELECT comments FROM tasks WHERE id = ?",
        (parent_task_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return

    existing_comments: list[dict] = json.loads(row[0])

    new_comment = TaskComment(
        id=comment_id,
        task_id=parent_task_id,
        author_type=CommentAuthorType.SYSTEM,
        content=comment_content,
        timestamp=timestamp,
    )
    existing_comments.append(new_comment.model_dump())

    await conn.execute(
        "UPDATE tasks SET comments = ?, updated_at = ? WHERE id = ?",
        (_json_dumps(existing_comments), _now_iso(), parent_task_id),
    )

    await conn.commit()


# ─── complete_parent_if_all_children_done ───────────────────────────────────

async def complete_parent_if_all_children_done(
    conn: Connection,
    completed_child_id: str,
) -> Optional[str]:
    """Check if all children of a task are done, and transition the parent.

    When a child task completes, find its parent and check the status of all
    sibling tasks. If all children are DONE, transition the parent to DONE.
    If any child FAILED, transition the parent to FAILED.

    Args:
        conn: Open async SQLite connection.
        completed_child_id: The child task that just finished.

    Returns:
        Parent task ID if transitioned, None otherwise.
    """
    # 1. Find the parent of the completed child
    cursor = await conn.execute(
        "SELECT parent_id FROM tasks WHERE id = ?",
        (completed_child_id,),
    )
    row = await cursor.fetchone()
    if row is None or not row[0]:
        return None

    parent_id = row[0]

    # 2. Get all children of the parent
    cursor = await conn.execute(
        "SELECT id, status FROM tasks WHERE parent_id = ?",
        (parent_id,),
    )
    children = await cursor.fetchall()
    if not children:
        return None

    # 3. Check child statuses
    statuses = {child[1] for child in children}
    if statuses <= {"done"}:
        # All children done → parent is done
        await conn.execute(
            "UPDATE tasks SET status = 'done', attention = ?, updated_at = ? WHERE id = ?",
            (_json_dumps(AttentionMetadata().model_dump()), _now_iso(), parent_id),
        )
        return parent_id
    elif statuses <= {"done", "in_progress", "approved"}:
        # Still running, nothing to do yet
        return None
    elif "failed" in statuses:
        # At least one child failed → parent gets attention
        cursor_a = await conn.execute(
            "SELECT attention FROM tasks WHERE id = ?",
            (parent_id,),
        )
        att_row = await cursor_a.fetchone()
        if att_row is None:
            return None

        current_attention: dict = json.loads(att_row[0])
        # Count failed vs done
        failed_ids = [c[0] for c in children if c[1] == "failed"]
        new_attention = AttentionMetadata.required_attention(
            reason="child_failed",
            detail=f"Child task(s) {', '.join(failed_ids)} failed.",
        )
        merged_attention = {**current_attention, **new_attention.model_dump()}
        await conn.execute(
            "UPDATE tasks SET attention = ?, updated_at = ? WHERE id = ?",
            (_json_dumps(merged_attention), _now_iso(), parent_id),
        )
        return parent_id

    return None
