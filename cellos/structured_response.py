"""Structured agent response models and JSON extraction.

Provides typed Pydantic models for planning and execution responses, plus
a bracket-scanning JSON extractor that handles chatty LLM output.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─── JSON extraction ─────────────────────────────────────────────────────────

_FENCED_RE = re.compile(r"```[^\n]*\n(.*?)\n```", re.DOTALL)


def _extract_json_objects(text: str) -> list[str]:
    """Extract JSON strings from text using bracket-scanning.

    Strategy (in order):
      1. Fenced code blocks (```json or ```)
      2. All top-level { ... } or [ ... ] via bracket counting

    Returns a list of valid JSON strings (deduplicated, in order found).

    Args:
        text: Raw agent output, possibly with prose and embedded JSON.

    Returns:
        List of JSON strings that parsed successfully.
    """
    found: list[str] = []
    seen: set[str] = set()

    def _add(candidate: str) -> None:
        stripped = candidate.strip()
        if stripped and stripped not in seen:
            try:
                json.loads(stripped)
                found.append(stripped)
                seen.add(stripped)
            except (json.JSONDecodeError, ValueError):
                pass

    # 1. Fenced code blocks
    fenced = _FENCED_RE.findall(text)
    for block in fenced:
        _add(block.strip())

    # 2. Bracket-scan for all top-level { ... } and [ ... ]
    objects = _bracket_scan(text)
    for obj in objects:
        _add(obj)

    return found


def _bracket_scan(text: str) -> list[str]:
    """Find all top-level JSON objects/arrays via bracket counting.

    Returns list of substrings (not yet validated as JSON).
    """
    results: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "{":
            end = _find_matching_bracket(text, i, "{", "}")
            if end is not None:
                results.append(text[i : end + 1])
                i = end + 1
                continue
        elif text[i] == "[":
            end = _find_matching_bracket(text, i, "[", "]")
            if end is not None:
                results.append(text[i : end + 1])
                i = end + 1
                continue
        i += 1
    return results


def _find_matching_bracket(text: str, start: int, open_b: str, close_b: str) -> Optional[int]:
    """Find the matching closing bracket for an opening bracket at position start.

    Handles nested brackets and string escaping.
    Returns the index of the matching close bracket, or None if not found.
    """
    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = ch == "\\"
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == open_b:
            depth += 1
        elif ch == close_b:
            depth -= 1
            if depth == 0:
                return i
    return None


def _parse_first_json(text: str) -> Optional[dict[str, Any]]:
    """Extract and parse the first valid JSON object from text.

    Args:
        text: Raw text that may contain JSON.

    Returns:
        Parsed dict if a valid JSON object is found, None otherwise.
    """
    candidates = _extract_json_objects(text)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            continue
    return None


# ─── Planning response models ────────────────────────────────────────────────

class PlanSpec(BaseModel):
    """The plan portion of a planning response."""

    objective: str = Field(min_length=1)
    steps: list[str] = Field(min_length=1)
    approach: Optional[str] = None
    verification: Optional[list[str]] = None
    dependencies: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class ChildTaskSpec(BaseModel):
    """A child task specification from a planning response."""

    title: str = Field(min_length=1)
    role: Optional[str] = None
    task_type: Optional[str] = None
    details: Optional[str] = None
    success_criteria: Optional[str] = None
    failure_criteria: Optional[str] = None
    dependencies: list[str] = Field(default_factory=list)
    blocks_parent: bool = False


class PlanningResponse(BaseModel):
    """Validated structured planning response from an agent."""

    plan: PlanSpec
    child_tasks: list[ChildTaskSpec] = Field(default_factory=list)


# ─── Execution response models ───────────────────────────────────────────────

class ExecutionResponse(BaseModel):
    """Validated structured execution response from an agent."""

    summary: str = Field(min_length=1)
    success: bool
    actions_taken: list[str] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    commands_run: list[str] = Field(default_factory=list)
    criteria_met: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


# ─── Parsing functions ───────────────────────────────────────────────────────

def parse_planning_response(text: str) -> Optional[PlanningResponse]:
    """Parse a planning response from agent output text.

    Extracts JSON, validates against the PlanningResponse model.

    Args:
        text: Raw agent output (may contain prose + JSON).

    Returns:
        Validated PlanningResponse or None if parsing fails.
    """
    data = _parse_first_json(text)
    if data is None:
        return None
    try:
        return PlanningResponse(**data)
    except Exception:
        return None


def parse_execution_response(text: str) -> Optional[ExecutionResponse]:
    """Parse an execution response from agent output text.

    Extracts JSON, validates against the ExecutionResponse model.

    Args:
        text: Raw agent output (may contain prose + JSON).

    Returns:
        Validated ExecutionResponse or None if parsing fails.
    """
    data = _parse_first_json(text)
    if data is None:
        return None
    try:
        return ExecutionResponse(**data)
    except Exception:
        return None


# ─── Plan text conversion ────────────────────────────────────────────────────

def plan_to_text(response: PlanningResponse) -> str:
    """Convert a validated PlanningResponse to readable markdown for storage.

    Produces a clean plan text suitable for saving as task.plan.

    Args:
        response: Validated planning response.

    Returns:
        Readable markdown plan text.
    """
    plan = response.plan
    parts: list[str] = []

    parts.append(f"## Objective\n{plan.objective}")

    if plan.approach:
        parts.append(f"## Approach\n{plan.approach}")

    parts.append("## Steps")
    for i, step in enumerate(plan.steps, 1):
        parts.append(f"{i}. {step}")

    if plan.verification:
        parts.append("## Verification")
        for item in plan.verification:
            parts.append(f"- {item}")

    if plan.dependencies:
        parts.append("## Dependencies")
        for dep in plan.dependencies:
            parts.append(f"- {dep}")

    if plan.risks:
        parts.append("## Risks")
        for risk in plan.risks:
            parts.append(f"- {risk}")

    return "\n\n".join(parts)


# ─── Child task conversion ───────────────────────────────────────────────────

def child_tasks_from_response(
    response: PlanningResponse,
    parent_id: str,
) -> list[dict[str, Any]]:
    """Convert child task specs from a planning response to task creation dicts.

    Each child task gets the parent's ID as a dependency.

    Args:
        response: Validated planning response.
        parent_id: The task that generated these child tasks.

    Returns:
        List of dicts suitable for TaskService.create_task().
    """
    from cellos.models import AgentRole, ROLE_TO_TASK_TYPE, TaskDependency

    result: list[dict[str, Any]] = []
    for spec in response.child_tasks:
        resolved_role: Optional[AgentRole] = None
        resolved_task_type = None

        if spec.role:
            try:
                resolved_role = AgentRole(spec.role)
                resolved_task_type = ROLE_TO_TASK_TYPE.get(resolved_role)
            except ValueError:
                pass

        task_data: dict[str, Any] = {
            "title": spec.title,
            "details": spec.details,
            "parent_id": parent_id,
            "dependencies": [
                TaskDependency(task_id=pid)
                for pid in (spec.dependencies + [parent_id])
            ],
        }

        if spec.success_criteria:
            task_data["success_criteria"] = spec.success_criteria
        if spec.failure_criteria:
            task_data["failure_criteria"] = spec.failure_criteria

        if resolved_role:
            task_data["role"] = resolved_role
        if resolved_task_type and not spec.task_type:
            task_data["task_type"] = resolved_task_type
        elif spec.task_type:
            try:
                from cellos.models import TaskType
                task_data["task_type"] = TaskType(spec.task_type)
            except ValueError:
                pass

        result.append(task_data)

    return result


__all__ = [
    "PlanSpec",
    "ChildTaskSpec",
    "PlanningResponse",
    "ExecutionResponse",
    "parse_planning_response",
    "parse_execution_response",
    "plan_to_text",
    "child_tasks_from_response",
    "_extract_json_objects",
    "_parse_first_json",
]
