"""PlanningService — validate and persist planning results."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from cellos.db import CellosDatabase
from cellos.models import AttentionReason, TaskStatus


_REQUIRED_PLAN_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("success criteria", ("success criteria",)),
    ("constraints / failure criteria", ("constraints", "failure criteria")),
    ("dependencies", ("dependencies",)),
    ("missing context", ("missing context",)),
    ("decomposition", ("decomposition",)),
    ("review points", ("review points", "review point")),
)


@dataclass(slots=True)
class PlanningValidationResult:
    is_valid: bool
    missing_sections: list[str]


def validate_planning_result(plan_text: str) -> PlanningValidationResult:
    """Check that a planning result is reviewable before approval.

    Step 3 focuses on structure/quality only, not deep sufficiency scoring.
    """
    normalized = (plan_text or "").lower()
    missing_sections = [
        name for name, aliases in _REQUIRED_PLAN_SECTIONS if not any(alias in normalized for alias in aliases)
    ]
    return PlanningValidationResult(
        is_valid=not missing_sections,
        missing_sections=missing_sections,
    )


async def save_planning_result(
    db: CellosDatabase, task_id: str, plan_text: str, prompt_text: str = "", success: bool = True
) -> None:
    """Save the agent's planning result and only advance valid plans to approval."""
    current = await db.get_task(task_id)
    if current is None:
        raise ValueError(f"Task {task_id} not found")

    now = datetime.datetime.now()
    if not success:
        updated = current.model_copy(
            update={
                "plan": plan_text,
                "prompt_text": prompt_text or current.prompt_text,
                "status": TaskStatus.FAILED,
                "updated_at": now,
            }
        )
    else:
        validation = validate_planning_result(plan_text)
        if validation.is_valid:
            updated = current.model_copy(
                update={
                    "plan": plan_text,
                    "prompt_text": prompt_text or current.prompt_text,
                    "status": TaskStatus.NEEDS_APPROVAL,
                    "updated_at": now,
                }
            ).requires_attention(
                AttentionReason.PLANNING_COMPLETE,
                detail="Plan generated and ready for approval",
            )
        else:
            updated = current.model_copy(
                update={
                    "plan": plan_text,
                    "prompt_text": prompt_text or current.prompt_text,
                    "status": TaskStatus.DRAFT,
                    "updated_at": now,
                }
            ).requires_attention(
                AttentionReason.PLANNING_COMPLETE,
                detail=(
                    "Invalid planning result: missing sections "
                    + ", ".join(validation.missing_sections)
                ),
            )

    await db.update_task(updated)
    await db.create_event(task_id, "planning_saved", "Planning result saved")
    await db.create_event(
        task_id,
        "status_changed",
        f"Status changed from {current.status.value} to {updated.status.value}",
    )


__all__ = ["PlanningValidationResult", "save_planning_result", "validate_planning_result"]
