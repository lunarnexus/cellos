"""ExecutionService — save execution results and transition tasks to DONE/FAILED."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

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


@dataclass(slots=True)
class ExecutionAssessment:
    success: bool
    summary: str


def _normalize_lines(text: str | None) -> list[str]:
    if not text:
        return []
    return [line.strip(" -*\t") for line in text.splitlines() if line.strip()]


def _criteria_matches(result_text: str, criteria_text: str | None) -> list[str]:
    lower_result = result_text.lower()
    matches: list[str] = []
    for line in _normalize_lines(criteria_text):
        if line.lower() in lower_result:
            matches.append(line)
    return matches


def _parse_execution_result(text: str) -> bool:
    """Determine if execution output indicates success or failure.

    Uses keyword matching on the result text. Defaults to False (failure)
    if no clear indicator is found — better to flag for review than assume
    success from ambiguous output.
    """
    lower = text.lower()
    for indicator in _FAILURE_INDICATORS:
        if indicator in lower:
            return False
    for indicator in _SUCCESS_INDICATORS:
        if indicator in lower:
            return True
    return False


def _assess_execution_result(
    result_text: str,
    *,
    success_criteria: str | None,
    failure_criteria: str | None,
    connector_success: bool | None,
) -> ExecutionAssessment:
    """Assess execution output against explicit task criteria when possible."""
    success_matches = _criteria_matches(result_text, success_criteria)
    failure_matches = _criteria_matches(result_text, failure_criteria)

    if connector_success is not None:
        if connector_success:
            summary = "Execution completed successfully"
            if success_matches:
                summary += f"; matched success criteria: {', '.join(success_matches)}"
            elif success_criteria:
                summary += "; connector reported success; criteria evidence not explicit in output"
            return ExecutionAssessment(success=True, summary=summary)

        summary = "Execution failed"
        if failure_matches:
            summary += f"; violated failure criteria: {', '.join(failure_matches)}"
        return ExecutionAssessment(success=False, summary=summary)

    if failure_matches:
        return ExecutionAssessment(
            success=False,
            summary=f"Execution failed; violated failure criteria: {', '.join(failure_matches)}",
        )

    parsed_success = _parse_execution_result(result_text)
    if parsed_success:
        if success_criteria and not success_matches:
            return ExecutionAssessment(
                success=False,
                summary="Execution ambiguous: generic success indicators present but no explicit success-criteria evidence",
            )
        summary = "Execution completed successfully"
        if success_matches:
            summary += f"; matched success criteria: {', '.join(success_matches)}"
        return ExecutionAssessment(success=True, summary=summary)

    return ExecutionAssessment(
        success=False,
        summary="Execution failed or ambiguous result",
    )


async def save_execution_result(
    db: CellosDatabase, task_id: str, result_text: str, success: bool | None = None
) -> TaskResult:
    """Save the agent's execution result and transition the task."""
    current = await db.get_task(task_id)
    if current is None:
        raise ValueError(f"Task {task_id} not found")

    truncated_output = result_text[:5000] if len(result_text) > 5000 else result_text

    assessment = _assess_execution_result(
        result_text,
        success_criteria=current.success_criteria,
        failure_criteria=current.failure_criteria,
        connector_success=success,
    )
    success = assessment.success
    summary = assessment.summary

    task_result = TaskResult(
        success=success,
        summary=summary,
        output=truncated_output,
    )

    new_status = TaskStatus.DONE if success else TaskStatus.FAILED
    updated = current.model_copy(
        update={
            "status": new_status,
            "result": task_result,
            "updated_at": datetime.datetime.now(),
        }
    )

    if success:
        updated = updated.clear_attention()

    await db.update_task(updated)
    await db.save_task_result(
        task_id, success=success, summary=summary, output=truncated_output
    )
    await db.create_event(
        task_id, "status_changed",
        f"Status changed from {current.status.value} to {new_status.value}"
    )

    return task_result
