"""ExecutionService — save execution results and transition tasks to DONE/FAILED."""

from __future__ import annotations

import datetime

from cellos.db import CellosDatabase
from cellos.models import TaskResult, TaskStatus


# Keywords that indicate successful completion (case-insensitive)
_SUCCESS_INDICATORS = [
    "completed successfully",
    "task completed",
    "execution completed",
    "all steps completed",
    "successfully implemented",
]

_FAILURE_INDICATORS = [
    "failed with reason",
    "execution failed",
    "encountered error",
    "unable to complete",
    "task failed",
]


def _parse_execution_result(text: str) -> bool:
    """Determine if execution output indicates success or failure.

    Uses keyword matching on the result text. Defaults to False (failure)
    if no clear indicator is found — better to flag for review than assume
    success from ambiguous output.

    Args:
        text: Raw output text from the agent execution.

    Returns:
        True if success indicators are present, False otherwise.
    """
    lower = text.lower()
    # Check failure first (more specific)
    for indicator in _FAILURE_INDICATORS:
        if indicator in lower:
            return False
    for indicator in _SUCCESS_INDICATORS:
        if indicator in lower:
            return True
    # No clear signal — default to failed so human reviews it
    return False


async def save_execution_result(
    db: CellosDatabase,
    task_id: str,
    result_text: str,
    success: bool | None = None,
) -> TaskResult:
    """Save the agent's execution result and transition the task.

    Attempts to parse a structured JSON response first. If valid, uses
    the structured fields (success, summary, actions_taken, etc.). Falls
    back to keyword-based parsing for non-JSON output.

    Args:
        db: Database facade instance.
        task_id: ID of the executed task.
        result_text: Raw output text from the agent execution.
        success: Optional explicit success/failure from the connector.
            If provided, overrides text-based parsing.

    Returns:
        TaskResult with parsed success/failure status.

    Raises:
        ValueError: If task not found or not in approved/in_progress status.
    """
    current = await db.get_task(task_id)
    if current is None:
        raise ValueError(f"Task {task_id} not found")

    # Truncate very long outputs for storage
    truncated_output = result_text[:5000] if len(result_text) > 5000 else result_text

    # Try structured response first
    from cellos.structured_response import parse_execution_response

    structured = parse_execution_response(result_text)
    if structured is not None:
        # Structured response takes precedence
        final_success = success if success is not None else structured.success
        summary = structured.summary
        task_result = TaskResult(
            success=final_success,
            summary=summary,
            output=truncated_output,
            actions_taken=structured.actions_taken,
            files_changed=structured.files_changed,
            commands_run=structured.commands_run,
            criteria_met=structured.criteria_met,
            issues=structured.issues,
        )
    else:
        # Fallback: keyword-based parsing
        if success is None:
            success = _parse_execution_result(result_text)
        summary = (
            "Execution completed successfully"
            if success
            else "Execution failed or ambiguous result"
        )
        task_result = TaskResult(
            success=success,
            summary=summary,
            output=truncated_output,
        )

    # Determine new status
    new_status = TaskStatus.DONE if task_result.success else TaskStatus.FAILED
    updated = current.model_copy(
        update={
            "status": new_status,
            "result": task_result,
            "updated_at": datetime.datetime.now(),
        }
    )

    # Clear attention on completion (task is resolved one way or another)
    if task_result.success:
        updated = updated.clear_attention()

    await db.update_task(updated)

    # Save result record + wake blocked dependents (side effects)
    affected = await db.save_task_result(
        task_id,
        success=task_result.success,
        summary=task_result.summary,
        output=truncated_output,
    )

    # Record status change event
    await db.create_event(
        task_id, "status_changed",
        f"Status changed from {current.status.value} to {new_status.value}"
    )

    return task_result
