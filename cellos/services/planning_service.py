"""PlanningService — save planning results and transition tasks to NEEDS_APPROVAL."""

from __future__ import annotations

import datetime

from cellos.db import CellosDatabase
from cellos.models import AttentionReason, TaskStatus


async def save_planning_result(
    db: CellosDatabase, task_id: str, plan_text: str, prompt_text: str = "", success: bool = True
) -> None:
    """Save the agent's planning result to a task and transition to NEEDS_APPROVAL.

    The planner (architect agent) generates a structured plan with analysis,
    steps, and verification approach. This function persists that output and
    moves the task to the approval gate where humans review before execution.

    Args:
        db: Database facade instance.
        task_id: ID of the task being planned.
        plan_text: The generated plan text from the agent.
        prompt_text: Optional structured prompt/output from planning.
        success: Whether the connector reported success. If False, transitions to FAILED.

    Raises:
        ValueError: If task not found or already past draft status.
    """
    current = await db.get_task(task_id)
    if current is None:
        raise ValueError(f"Task {task_id} not found")

    if not success:
        # Planning failed — transition directly to FAILED
        updated = current.model_copy(
            update={
                "plan": plan_text,
                "prompt_text": prompt_text or current.prompt_text,
                "status": TaskStatus.FAILED,
                "updated_at": datetime.datetime.now(),
            }
        )
    else:
        updated = current.model_copy(
            update={
                "plan": plan_text,
                "prompt_text": prompt_text or current.prompt_text,
                "status": TaskStatus.NEEDS_APPROVAL,
                "updated_at": datetime.datetime.now(),
            }
        )
        # Planning complete triggers attention for human review
        updated = updated.requires_attention(
            AttentionReason.PLANNING_COMPLETE,
            detail="Plan generated and ready for approval",
        )

    await db.update_task(updated)

    # Record events
    await db.create_event(task_id, "planning_saved", f"Planning result saved")
    await db.create_event(
        task_id, "status_changed",
        f"Status changed from {current.status.value} to {updated.status.value}"
    )
