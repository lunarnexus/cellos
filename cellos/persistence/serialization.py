"""Serialization helpers for CelloS database persistence."""

import json
from typing import Any

from cellos.domain.tasks import Task
from cellos.domain.attempts import TaskAttempt


def json_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload)


def task_row(task: Task) -> tuple[Any, ...]:
    return (
        task.id,
        task.parent_id,
        task.role.value,
        task.task_type.value,
        task.status.value,
        int(task.attention.required),
        task.assigned_worker_id,
        task.created_at.isoformat(),
        task.updated_at.isoformat(),
        task.model_dump_json(),
        json.dumps([m.model_dump(mode="json") for m in task.conversation]),
    )


def attempt_row(attempt: TaskAttempt) -> tuple[Any, ...]:
    return (
        attempt.task_id,
        attempt.mode,
        attempt.agent_id,
        attempt.connector,
        attempt.status.value,
        attempt.prompt_snapshot,
        attempt.result_summary,
        json_payload(attempt.result_payload),
        attempt.error,
        attempt.log_path,
        attempt.started_at.isoformat(),
        attempt.completed_at.isoformat() if attempt.completed_at is not None else None,
        json_payload(attempt.metadata),
    )
