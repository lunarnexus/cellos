"""PlanningService — save planning results and transition tasks to NEEDS_APPROVAL."""

from __future__ import annotations

import datetime
import logging
import re

from cellos.db import CellosDatabase
from cellos.models import AttentionReason, TaskStatus


logger = logging.getLogger(__name__)


def _strip_thinking_text(plan_text: str) -> str:
    """Strip thinking/thought text from plan output.

    Opencode routes all content through agent_thought_chunk events, so the
    plan often starts with thinking text like 'Let me check the file...'
    before the actual structured plan. This function strips that preamble
    by finding the first horizontal rule (---), section heading (##), or
    fenced code block.

    Args:
        plan_text: Raw plan text from the agent, possibly with thinking preamble.

    Returns:
        Cleaned plan text with thinking preamble removed.
    """
    text = plan_text.strip()

    # Strategy 0: Strip leading fenced code block (JSON actions before plan prose)
    code_match = re.match(r'\s*```(?:\w+)?\s*\n(.*?)\n```\s*\n?', text, re.DOTALL)
    if code_match and code_match.end() < len(text):
        remaining = text[code_match.end():].strip()
        if remaining:
            text = remaining

    # Strategy 1: Find first horizontal rule or section heading
    match = re.search(r'\n*(---\s*|\s*##\s)', text)
    if match:
        return text[match.end():].lstrip('\n')

    # Strategy 2: Find first fenced code block (JSON actions or structured output)
    match = re.search(r'\n*(```)', text)
    if match:
        return text[match.end():].lstrip('\n')

    return text.strip()


async def save_planning_result(
    db: CellosDatabase,
    task_id: str,
    plan_text: str,
    prompt_text: str = "",
    success: bool = True,
) -> None:
    """Save the agent's planning result and transition tasks to NEEDS_APPROVAL.

    The planner (architect agent) generates a structured plan with analysis,
    steps, and verification approach. This function attempts to parse a
    structured JSON response first, falling back to regex-based text stripping.
    Persists the plan and moves the task to the approval gate where humans
    review before execution.

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

    # Try structured response first
    from cellos.structured_response import parse_planning_response, plan_to_text

    logger.debug(
        "Planning result raw input for task %s chars=%d repr=%r",
        task_id, len(plan_text), plan_text,
    )
    structured = parse_planning_response(plan_text)
    if structured is not None:
        plan_text = plan_to_text(structured)
        logger.debug(
            "Planning result parsed as structured JSON for task %s stored_chars=%d repr=%r",
            task_id, len(plan_text), plan_text,
        )
    else:
        # Fallback: strip thinking text from plan output
        plan_text = _strip_thinking_text(plan_text)
        logger.debug(
            "Planning result used fallback text for task %s stored_chars=%d repr=%r",
            task_id, len(plan_text), plan_text,
        )

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
