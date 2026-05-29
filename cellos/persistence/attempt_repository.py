"""Repository for task attempt lifecycle operations."""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from aiosqlite import Connection

from cellos.models import TaskAttempt, TaskAttemptStatus


# ─── Helpers ────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _attempt_id() -> str:
    """Generate a short hex attempt ID (UUID-4, first 16 chars)."""
    return uuid.uuid4().hex[:16]


def _parse_optional_datetime(value: str | None) -> datetime | None:
    """Parse an ISO datetime string, returning None for empty/missing values."""
    if not value:
        return None
    return datetime.fromisoformat(value)


def _row_to_attempt(row: tuple) -> TaskAttempt:
    """Convert a database row to a TaskAttempt model.

    Handles both legacy rows (9 columns) and extended rows (24 columns).
    """
    attempt = TaskAttempt(
        id=row[0],
        task_id=row[1],
        status=TaskAttemptStatus(row[2]),
        mode=row[3] or None,
        agent_id=row[4] or None,
        result_summary=row[5] or None,
        error_message=row[6] or None,
        started_at=datetime.fromisoformat(row[7]) if row[7] else datetime.now(timezone.utc),
        completed_at=_parse_optional_datetime(row[8]),
    )

    # Extended diagnostic columns (if present)
    if len(row) > 9:
        attempt.acp_session_id = row[9] or None
        attempt.acp_message_id = row[10] or None
        attempt.agent_provider = row[11] or None
        attempt.agent_model = row[12] or None
        attempt.last_event_type = row[13] or None
        attempt.last_event_at = _parse_optional_datetime(row[14])
        attempt.active_tool_name = row[15] or None
        attempt.active_tool_call_id = row[16] or None
        attempt.nested_session_id = row[17] or None
        attempt.partial_text = row[18] or None
        attempt.partial_thinking = row[19] or None
        attempt.error_type = row[20] or None
        attempt.timeout = bool(row[21]) if row[21] else False
        attempt.aborted = bool(row[22]) if row[22] else False
        attempt.raw_diagnostics_json = row[23] or None

    return attempt


# ─── create_attempt ─────────────────────────────────────────────────────────

async def create_attempt(
    conn: Connection,
    task_id: str,
    mode: Optional[str] = None,
    agent_id: Optional[str] = None,
    diagnostics: Optional[dict[str, Any]] = None,
) -> TaskAttempt:
    """Create a new attempt record for *task_id* and return the model.

    Inserts into ``task_attempts`` with status ``'started'`` and returns
    the freshly created ``TaskAttempt`` instance.

    Args:
        conn: Open async SQLite connection.
        task_id: The parent task this attempt belongs to.
        mode: Optional execution context (e.g. ``"planning"``, ``"execution"``).
        agent_id: Optional identifier of the agent handling this attempt.
        diagnostics: Optional diagnostic payload to persist immediately.

    Returns:
        The created :class:`TaskAttempt` model.
    """
    now = _now_iso()
    attempt_id = _attempt_id()

    # Build column list dynamically based on available diagnostics
    base_cols = ["id", "task_id", "status", "mode", "agent_id", "started_at"]
    base_vals = [
        attempt_id,
        task_id,
        TaskAttemptStatus.STARTED.value,
        mode or "",
        agent_id or "",
        now,
    ]

    diag_cols = []
    diag_vals = []
    if diagnostics:
        diag_cols = [
            "acp_session_id", "acp_message_id", "agent_provider", "agent_model",
            "last_event_type", "last_event_at",
            "active_tool_name", "active_tool_call_id", "nested_session_id",
            "partial_text", "partial_thinking",
            "error_type", "timeout_flag", "aborted_flag", "raw_diagnostics_json",
        ]
        import json
        diag_vals = [
            diagnostics.get("session_id") or "",
            diagnostics.get("message_id") or "",
            diagnostics.get("agent_provider") or "",
            diagnostics.get("agent_model") or "",
            diagnostics.get("last_event_type") or "",
            diagnostics.get("last_event_at") or "",
            diagnostics.get("active_tool_name") or "",
            diagnostics.get("active_tool_call_id") or "",
            diagnostics.get("nested_session_id") or "",
            diagnostics.get("partial_text") or "",
            diagnostics.get("partial_thinking") or "",
            diagnostics.get("error_type") or "",
            diagnostics.get("timeout", False),
            diagnostics.get("aborted", False),
            json.dumps(diagnostics) if diagnostics else "",
        ]

    all_cols = base_cols + diag_cols
    all_vals = base_vals + diag_vals
    placeholders = ", ".join(["?"] * len(all_cols))

    await conn.execute(
        f"INSERT INTO task_attempts ({', '.join(all_cols)}) VALUES ({placeholders})",
        all_vals,
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
    diagnostics: Optional[dict[str, Any]] = None,
) -> None:
    """Update an existing attempt's status and optional outcome fields.

    Sets ``completed_at`` to *now* for terminal statuses (succeeded / failed).

    Args:
        conn: Open async SQLite connection.
        attempt_id: The attempt to update.
        status: New :class:`TaskAttemptStatus` value.
        result_summary: Brief outcome description (for successful attempts).
        error_message: Failure reason text (for failed attempts).
        diagnostics: Optional diagnostic payload to merge into the attempt.
    """
    import json

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

    # Merge diagnostic fields
    if diagnostics:
        diag_map = {
            "session_id": "acp_session_id",
            "message_id": "acp_message_id",
            "agent_provider": "agent_provider",
            "agent_model": "agent_model",
            "last_event_type": "last_event_type",
            "last_event_at": "last_event_at",
            "active_tool_name": "active_tool_name",
            "active_tool_call_id": "active_tool_call_id",
            "nested_session_id": "nested_session_id",
            "partial_text": "partial_text",
            "partial_thinking": "partial_thinking",
            "error_type": "error_type",
        }
        for key, col in diag_map.items():
            val = diagnostics.get(key)
            if val is not None:
                columns.append(f"{col} = ?")
                params.append(val)

        if diagnostics.get("timeout"):
            columns.append("timeout_flag = 1")
        if diagnostics.get("aborted"):
            columns.append("aborted_flag = 1")
        if diagnostics.get("raw_diagnostics_json"):
            columns.append("raw_diagnostics_json = ?")
            params.append(diagnostics["raw_diagnostics_json"])
        else:
            columns.append("raw_diagnostics_json = ?")
            params.append(json.dumps(diagnostics))

    params.append(attempt_id)

    await conn.execute(
        f"UPDATE task_attempts SET {', '.join(columns)} WHERE id = ?",
        params,
    )
    await conn.commit()


# ─── get_attempt ────────────────────────────────────────────────────────────

async def get_attempt(conn: Connection, attempt_id: str) -> TaskAttempt | None:
    """Return a single attempt by ID.

    Args:
        conn: Open async SQLite connection.
        attempt_id: The attempt to retrieve.

    Returns:
        The :class:`TaskAttempt` model, or None if not found.
    """
    cursor = await conn.execute(
        "SELECT id, task_id, status, mode, agent_id, result_summary, error_message, "
        "started_at, completed_at, "
        "COALESCE(acp_session_id, ''), COALESCE(acp_message_id, ''), "
        "COALESCE(agent_provider, ''), COALESCE(agent_model, ''), "
        "COALESCE(last_event_type, ''), COALESCE(last_event_at, ''), "
        "COALESCE(active_tool_name, ''), COALESCE(active_tool_call_id, ''), "
        "COALESCE(nested_session_id, ''), COALESCE(partial_text, ''), "
        "COALESCE(partial_thinking, ''), COALESCE(error_type, ''), "
        "COALESCE(timeout_flag, 0), COALESCE(aborted_flag, 0), "
        "COALESCE(raw_diagnostics_json, '') "
        "FROM task_attempts WHERE id = ?",
        (attempt_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return _row_to_attempt(row)


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
        "SELECT id, task_id, status, mode, agent_id, result_summary, error_message, "
        "started_at, completed_at, "
        "COALESCE(acp_session_id, ''), COALESCE(acp_message_id, ''), "
        "COALESCE(agent_provider, ''), COALESCE(agent_model, ''), "
        "COALESCE(last_event_type, ''), COALESCE(last_event_at, ''), "
        "COALESCE(active_tool_name, ''), COALESCE(active_tool_call_id, ''), "
        "COALESCE(nested_session_id, ''), COALESCE(partial_text, ''), "
        "COALESCE(partial_thinking, ''), COALESCE(error_type, ''), "
        "COALESCE(timeout_flag, 0), COALESCE(aborted_flag, 0), "
        "COALESCE(raw_diagnostics_json, '') "
        "FROM task_attempts WHERE task_id = ? ORDER BY started_at DESC",
        (task_id,),
    )
    rows = await cursor.fetchall()

    return [_row_to_attempt(row) for row in rows]
