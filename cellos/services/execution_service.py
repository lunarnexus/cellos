"""ExecutionService — save execution results and transition tasks to DONE/FAILED."""

from __future__ import annotations

import datetime
from typing import Any

from cellos.db import CellosDatabase
from cellos.models import TaskResult, TaskStatus


async def save_execution_result(
    db: CellosDatabase,
    task_id: str,
    structured_result: dict[str, Any] | None,
    wait_for_children: bool = False,
) -> TaskResult:
    """Save the agent's execution result and transition the task.

    The agent calls the cellos_submit_reply tool with structured data.
    This function validates the result and persists it.

    Args:
        db: Database facade instance.
        task_id: ID of the executed task.
        structured_result: Structured data from cellos_submit_reply tool call.
        wait_for_children: If True and execution succeeded, keep the task
            approved while child tasks complete instead of marking it done.

    Returns:
        TaskResult with parsed success/failure status.

    Raises:
        ValueError: If task not found or not in approved/in_progress status.
    """
    current = await db.get_task(task_id)
    if current is None:
        raise ValueError(f"Task {task_id} not found")

    if current.status not in (TaskStatus.APPROVED, TaskStatus.IN_PROGRESS):
        raise ValueError(
            f"Cannot save execution result for task {task_id}: "
            f"status is '{current.status.value}', expected 'approved' or 'in_progress'"
        )

    # Build TaskResult from structured tool call data
    if structured_result:
        success = bool(structured_result.get("success", True))
        summary = structured_result.get("summary", "Execution completed")
        task_result = TaskResult(
            success=success,
            summary=summary,
            actions_taken=structured_result.get("actions_taken") or [],
            files_changed=structured_result.get("files_changed") or [],
            issues=structured_result.get("issues") or [],
        )
    else:
        task_result = TaskResult(
            success=True,
            summary="Execution completed",
        )

    # Determine new status
    if task_result.success and wait_for_children:
        new_status = TaskStatus.APPROVED
    else:
        new_status = TaskStatus.DONE if task_result.success else TaskStatus.FAILED
    updated = current.model_copy(
        update={
            "status": new_status,
            "result": task_result,
            "updated_at": datetime.datetime.now(),
        }
    )

    if task_result.success:
        updated = updated.clear_attention()

    await db.update_task(updated)

    # Save result record + wake blocked dependents (side effects)
    await db.save_task_result(
        task_id,
        success=task_result.success,
        summary=task_result.summary,
        output="",
    )

    # Record status change event
    await db.create_event(
        task_id, "status_changed",
        f"Status changed from {current.status.value} to {new_status.value}"
    )

    return task_result
