"""PlanningService — save planning results and transition tasks to NEEDS_APPROVAL."""

from __future__ import annotations

import datetime
import json
import logging
from typing import Any

from cellos.db import CellosDatabase
from cellos.models import AttentionReason, TaskStatus


logger = logging.getLogger(__name__)


def structured_result_to_plan_text(data: dict[str, Any]) -> str:
    """Convert a structured planning result dict to readable markdown.

    Args:
        data: Structured result from cellos_submit_prompt tool call.

    Returns:
        Markdown-formatted plan text for display and storage.
    """
    lines: list[str] = []

    objective = data.get("objective", "")
    if objective:
        lines.append(f"## Objective\n{objective}")

    approach = data.get("approach", "")
    if approach:
        lines.append(f"\n## Approach\n{approach}")

    steps = data.get("steps") or []
    if steps:
        lines.append("\n## Steps")
        for i, step in enumerate(steps, 1):
            lines.append(f"{i}. {step}")

    verification = data.get("verification") or []
    if verification:
        lines.append("\n## Verification")
        for item in verification:
            lines.append(f"- {item}")

    risks = data.get("risks") or []
    if risks:
        lines.append("\n## Risks")
        for item in risks:
            lines.append(f"- {item}")

    return "\n".join(lines)


async def save_planning_result(
    db: CellosDatabase,
    task_id: str,
    structured_result: dict[str, Any] | None,
    success: bool = True,
) -> None:
    """Save the agent's planning result and transition tasks to NEEDS_APPROVAL.

    The planner calls the cellos_submit_prompt tool with structured data.
    This function validates the result, converts it to readable markdown,
    and persists it. The task moves to the approval gate where humans
    review before execution.

    Args:
        db: Database facade instance.
        task_id: ID of the task being planned.
        structured_result: Structured data from cellos_submit_prompt tool call.
        success: Whether the connector reported success. If False, transitions to FAILED.

    Raises:
        ValueError: If task not found or already past draft status.
    """
    current = await db.get_task(task_id)
    if current is None:
        raise ValueError(f"Task {task_id} not found")

    if current.status not in (TaskStatus.DRAFT, TaskStatus.IN_PROGRESS):
        raise ValueError(
            f"Cannot save planning result for task {task_id}: "
            f"status is '{current.status.value}', expected 'draft' or 'in_progress'"
        )

    # Use structured result from tool call
    if structured_result:
        plan_text = structured_result_to_plan_text(structured_result)
        stored_prompt_text = json.dumps(structured_result)
        logger.debug(
            "Planning result from structured tool call for task %s fields=%s",
            task_id, list(structured_result.keys()),
        )
    else:
        plan_text = "No plan generated"
        stored_prompt_text = current.prompt_text or ""
        logger.debug(
            "No structured result for task %s", task_id,
        )

    if not success:
        updated = current.model_copy(
            update={
                "plan": plan_text,
                "prompt_text": stored_prompt_text,
                "status": TaskStatus.FAILED,
                "updated_at": datetime.datetime.now(),
            }
        )
    else:
        updated = current.model_copy(
            update={
                "plan": plan_text,
                "prompt_text": stored_prompt_text,
                "status": TaskStatus.NEEDS_APPROVAL,
                "updated_at": datetime.datetime.now(),
            }
        )
        updated = updated.requires_attention(
            AttentionReason.PLANNING_COMPLETE,
            detail="Plan generated and ready for approval",
        )

    await db.update_task(updated)

    await db.create_event(task_id, "planning_saved", f"Planning result saved")
    await db.create_event(
        task_id, "status_changed",
        f"Status changed from {current.status.value} to {updated.status.value}"
    )
