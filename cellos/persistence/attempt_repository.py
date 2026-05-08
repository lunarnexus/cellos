"""Task attempt persistence for CelloS."""

import json
from typing import Any

import aiosqlite

from cellos.persistence.serialization import attempt_row, json_payload
from cellos.domain.attempts import TaskAttempt, TaskAttemptStatus
from cellos.domain.time import utc_now


async def start_task_attempt(
    conn: aiosqlite.Connection,
    attempt: TaskAttempt,
) -> TaskAttempt:
    cursor = await conn.execute(
        """
        INSERT INTO task_attempts (
            task_id, mode, agent_id, connector, status, prompt_snapshot,
            result_summary, result_payload, error, log_path, started_at,
            completed_at, payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, json(?), ?, ?, ?, ?, json(?))
        """,
        attempt_row(attempt),
    )
    saved = attempt.model_copy(update={"id": cursor.lastrowid})
    return saved


async def complete_task_attempt(
    conn: aiosqlite.Connection,
    attempt_id: int,
    status: TaskAttemptStatus,
    result_summary: str,
    result_payload: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    completed_at = utc_now()
    await conn.execute(
        """
        UPDATE task_attempts
        SET status = ?, result_summary = ?, result_payload = json(?), error = ?, completed_at = ?
        WHERE id = ?
        """,
        (
            status.value,
            result_summary,
            json_payload(result_payload or {}),
            error,
            completed_at.isoformat(),
            attempt_id,
        ),
    )


async def list_task_attempts(
    conn: aiosqlite.Connection,
    task_id: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT id, task_id, mode, agent_id, connector, status, prompt_snapshot,
               result_summary, result_payload, error, log_path, started_at,
               completed_at, payload
        FROM task_attempts
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
            "mode": row["mode"],
            "agent_id": row["agent_id"],
            "connector": row["connector"],
            "status": row["status"],
            "prompt_snapshot": row["prompt_snapshot"],
            "result_summary": row["result_summary"],
            "result_payload": json.loads(row["result_payload"]),
            "error": row["error"],
            "log_path": row["log_path"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "payload": json.loads(row["payload"]),
        }
        for row in rows
    ]