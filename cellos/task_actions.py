"""Structured actions returned by execution agents."""

import json
import re
from collections.abc import Callable
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from cellos.models import AgentRole, Task, TaskStatus, TaskType


class CreateTaskAction(BaseModel):
    type: Literal["create_task"]
    title: str
    role: AgentRole
    task_type: TaskType
    prompt: str
    description: str = ""
    status: TaskStatus | None = None
    dependencies: list[str] = Field(default_factory=list)
    blocks_parent: bool = False


def parse_create_task_actions(text: str) -> list[CreateTaskAction]:
    actions: list[CreateTaskAction] = []
    for payload in _candidate_payloads(text):
        raw_actions = payload.get("actions")
        if not isinstance(raw_actions, list):
            continue
        for raw_action in raw_actions:
            if not isinstance(raw_action, dict) or raw_action.get("type") != "create_task":
                continue
            normalized = dict(raw_action)
            if "dependencies" not in normalized and "depends" in normalized:
                normalized["dependencies"] = normalized["depends"]
            actions.append(CreateTaskAction.model_validate(normalized))
    return actions


def task_from_create_action(
    action: CreateTaskAction,
    parent: Task,
    *,
    preapprove_research_tasks: bool = False,
    id_factory: Callable[[], str] | None = None,
) -> Task:
    status = _resolve_child_status(action, preapprove_research_tasks)
    return Task(
        id=(id_factory or _new_task_id)(),
        title=action.title,
        role=action.role,
        task_type=action.task_type,
        status=status,
        prompt=action.prompt,
        description=action.description,
        parent_id=parent.id,
        dependencies=list(action.dependencies),
    )


def _resolve_child_status(action: CreateTaskAction, preapprove_research_tasks: bool) -> TaskStatus:
    if action.status == TaskStatus.APPROVED:
        if action.task_type == TaskType.RESEARCH and preapprove_research_tasks:
            return TaskStatus.APPROVED
        if action.task_type == TaskType.RESEARCH:
            return TaskStatus.NEEDS_APPROVAL
        return TaskStatus.DRAFT
    return action.status or TaskStatus.DRAFT


def _candidate_payloads(text: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for match in re.finditer(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE):
        parsed = _parse_json_object(match.group(1))
        if parsed is not None:
            payloads.append(parsed)
    parsed_text = _parse_json_object(text)
    if parsed_text is not None:
        payloads.append(parsed_text)
    return payloads


def _parse_json_object(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _new_task_id() -> str:
    return uuid4().hex[:8]
