"""Parse structured actions (child task creation) from agent output."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from pydantic import BaseModel, Field

# ─── Action Model ──────────────────────────────────────────────────────────


class CreateTaskAction(BaseModel):
    """Represents a child task creation request from an agent."""

    title: str = Field(min_length=1)
    role: Optional[str] = None  # e.g., "engineer", "researcher"
    task_type: Optional[str] = None  # inferred from role if missing
    prompt: Optional[str] = None  # details/description for the child task
    status: Optional[str] = None  # explicit target status (e.g. "approved")
    dependencies: list[str] = Field(default_factory=list)  # parent task IDs this depends on


# ─── Parsing helpers ────────────────────────────────────────────────────────

_FENCED_JSON_RE = re.compile(r"```[^\n]*\n(.*?)\n```", re.DOTALL)
_NESTED_ACTION_KEY = "action"  # key in nested format: {"action": "create_task", ...}


def _extract_json_blocks(text: str) -> list[str]:
    """Extract JSON strings from fenced code blocks or the entire text.

    Tries fenced `` ```json `` blocks first; if none found, treats the whole
    input as a raw JSON string.

    Args:
        text: Raw agent output (may contain markdown + embedded JSON).

    Returns:
        List of JSON strings to attempt parsing on.
    """
    # Try fenced code blocks first
    matches = _FENCED_JSON_RE.findall(text)
    if matches:
        return [m.strip() for m in matches]

    # Fallback: treat entire text as a single JSON blob
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return [stripped]

    return []


def _normalize_raw_action(raw: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Normalize different action formats into the flat CreateTaskAction shape.

    Supported input formats:
      1. Flat:   {"type": "create_task", "title": "..."}
      2. Nested: {"action": "create_task", "task": {"title": "..."}}

    For nested format, sibling keys (e.g., ``status``, ``dependencies``) are merged
    into the normalized result so they aren't silently discarded.

    Returns None if this dict is not a create_task action, or the normalized dict.
    """
    # Format 1: flat with type field (and no "action" key to indicate nested format)
    if raw.get("type") == "create_task" and _NESTED_ACTION_KEY not in raw:
        return {k: v for k, v in raw.items() if k != "type"}

    # Format 2: nested under "task" key — merge sibling fields too
    if raw.get(_NESTED_ACTION_KEY) == "create_task":
        task_payload = raw.get("task", {})
        if isinstance(task_payload, dict):
            normalized = {k: v for k, v in raw.items() if k not in (_NESTED_ACTION_KEY,)}
            # Task payload takes precedence over sibling keys (e.g., title from inner wins)
            normalized.update(task_payload)
            return normalized

    return None


def parse_create_task_actions(text: str) -> list[CreateTaskAction]:
    """Parse all create_task actions from agent output text.

    Searches for JSON blocks (fenced or plain), looks for an "actions" array
    containing entries with type/action == "create_task", normalizes them, and
    validates via Pydantic. Invalid actions are silently skipped — we don't want
    one malformed action to discard the rest of a valid response.

    Args:
        text: Raw output from an agent (may contain markdown + JSON).

    Returns:
        List of validated CreateTaskAction instances. Empty list if none found.
    """
    actions: list[CreateTaskAction] = []

    for json_str in _extract_json_blocks(text):
        try:
            parsed = json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            continue  # malformed JSON — skip this block

        if not isinstance(parsed, dict):
            continue

        action_list = parsed.get("actions", [])
        if not isinstance(action_list, list):
            continue

        for raw in action_list:
            if not isinstance(raw, dict):
                continue

            normalized = _normalize_raw_action(raw)
            if normalized is None:
                continue  # not a create_task action or unknown format

            try:
                actions.append(CreateTaskAction(**normalized))
            except Exception:
                pass  # validation failed — skip this one silently

    return actions


# ─── Child task creation from parsed actions ────────────────────────────────

def tasks_from_create_actions(
    parent_id: str,
    actions: list[CreateTaskAction],
    preapprove_research_tasks: bool = False,
) -> list[dict[str, Any]]:
    """Convert parsed CreateTaskActions into task dicts ready for TaskService.create_task.

    Each child task gets the parent's ID as a dependency and inherits sensible defaults.

    Args:
        parent_id: The task that generated these actions (becomes a dependency).
        actions: Parsed list of CreateTaskAction instances.
        preapprove_research_tasks: If True, research-type tasks default to APPROVED status;
                                   otherwise they stay at DRAFT/NEEDS_APPROVAL based on explicit status.

    Returns:
        List of dicts suitable for passing to TaskService.create_task().
        Each dict contains: title, role (optional), task_type (optional), details/prompt_text,
                           dependencies=[parent_id], and optional status override.
    """
    from cellos.models import AgentRole, ROLE_TO_TASK_TYPE

    result = []
    for action in actions:
        # Resolve role → task_type inference if type not explicitly set
        resolved_role = None
        resolved_task_type = None

        if action.role:
            try:
                resolved_role = AgentRole(action.role)
                resolved_task_type = ROLE_TO_TASK_TYPE.get(resolved_role)
            except ValueError:
                pass  # unknown role — leave as-is, Task model will handle it

        task_data: dict[str, Any] = {
            "title": action.title,
            "details": action.prompt or None,
            "parent_id": parent_id,
            "dependencies": [TaskDependencyModel(task_id=pid) for pid in (action.dependencies + [parent_id])],
        }

        if resolved_role:
            task_data["role"] = resolved_role
        if resolved_task_type and not action.task_type:
            task_data["task_type"] = resolved_task_type
        elif action.task_type:
            # Explicit type from agent — use it directly (Task model validates)
            pass  # will be set below

        # Status resolution: explicit > preapprove logic > default draft
        if action.status:
            task_data["status"] = action.status.lower()
        elif resolved_task_type and resolved_task_type.value == "research" and preapprove_research_tasks:
            from cellos.models import TaskStatus
            task_data["status"] = TaskStatus.APPROVED

        # Override type if explicitly provided by agent
        if action.task_type:
            try:
                from cellos.models import TaskType
                task_data["task_type"] = TaskType(action.task_type)
            except ValueError:
                pass  # invalid task_type — let model default handle it

        result.append(task_data)

    return result


class TaskDependencyModel(BaseModel):
    """Minimal dependency for child tasks."""

    task_id: str
    status_satisfied: bool = False


__all__ = [
    "CreateTaskAction",
    "parse_create_task_actions",
    "tasks_from_create_actions",
]
