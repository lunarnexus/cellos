"""Core orchestration loop for ready CelloS tasks."""

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from cellos.agents import AgentBackend
from cellos.db import CellosDatabase
from cellos.models import AgentRole, Task, TaskResult, TaskStatus, TaskType


class Orchestrator:
    def __init__(self, db: CellosDatabase, backend: AgentBackend, cwd: str | Path):
        self.db = db
        self.backend = backend
        self.cwd = Path(cwd)

    async def run_ready_tasks(self, limit: int | None = None) -> list[TaskResult]:
        tasks = await self.db.list_ready_tasks(limit=limit)
        return await asyncio.gather(*(self._run_task(task) for task in tasks))

    async def _run_task(self, task: Task) -> TaskResult:
        await self.db.update_task_status(task.id, TaskStatus.IN_PROGRESS)
        child_tasks: list[Task] = []
        try:
            result = await self.backend.run_task_once(task, self.cwd)
        except Exception as exc:
            result = TaskResult(
                task_id=task.id,
                success=False,
                summary=f"Task failed: {exc}",
                error=str(exc),
            )
        else:
            if result.success and task.task_type == TaskType.DECOMPOSE:
                try:
                    child_tasks = _child_tasks_from_decomposition(task, result.summary)
                except Exception as exc:
                    raw_result = result.model_dump(mode="json")
                    result = result.model_copy(
                        update={
                            "success": False,
                            "summary": f"Task failed: {exc}",
                            "error": str(exc),
                            "output": {
                                **result.output,
                                "raw_summary": result.summary,
                                "raw_result": raw_result,
                                "parse_error": str(exc),
                            },
                        }
                    )
        await self.db.save_task_result(result)
        for child_task in child_tasks:
            await self.db.create_task(child_task)
        return result


def _child_tasks_from_decomposition(parent: Task, summary: str) -> list[Task]:
    payload = _load_decomposition_json(summary)
    if not isinstance(payload, dict):
        raise ValueError("Decomposition result must be a JSON object")

    task_specs = payload.get("tasks")
    if not isinstance(task_specs, list):
        raise ValueError("Decomposition result must contain a tasks list")

    key_to_id: dict[str, str] = {}
    for spec in task_specs:
        if not isinstance(spec, dict):
            raise ValueError("Each decomposed task must be a JSON object")
        key = _required_str(spec, "key")
        if key in key_to_id:
            raise ValueError(f"Duplicate decomposed task key: {key}")
        key_to_id[key] = f"task-{uuid4().hex[:8]}"

    child_tasks: list[Task] = []
    for spec in task_specs:
        key = _required_str(spec, "key")
        depends_on = spec.get("depends_on", [])
        if not isinstance(depends_on, list) or not all(isinstance(item, str) for item in depends_on):
            raise ValueError(f"depends_on for {key} must be a list of task keys")

        child_tasks.append(
            Task(
                id=key_to_id[key],
                title=_required_str(spec, "title"),
                task_type=TaskType(str(spec.get("type", TaskType.BUILD.value))),
                role=AgentRole(str(spec.get("role", AgentRole.CELLO.value))),
                status=TaskStatus.READY,
                description=str(spec.get("description", "")),
                parent_id=parent.id,
                dependencies=[_dependency_id(key_to_id, dependency_key) for dependency_key in depends_on],
                timeout_seconds=_optional_int(spec, "timeout_seconds"),
            )
        )
    return child_tasks


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Decomposed task is missing required string field: {key}")
    return value


def _dependency_id(key_to_id: dict[str, str], dependency_key: str) -> str:
    try:
        return key_to_id[dependency_key]
    except KeyError as exc:
        raise ValueError(f"Unknown decomposed task dependency key: {dependency_key}") from exc


def _optional_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise ValueError(f"Decomposed task field must be an integer: {key}")
    return value


def _load_decomposition_json(summary: str) -> Any:
    text = summary.strip()
    if not text:
        raise ValueError("Decomposition result was empty")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fenced = _extract_fenced_json(text)
    if fenced is not None:
        return json.loads(fenced)

    embedded = _extract_first_json_object(text)
    if embedded is not None:
        return json.loads(embedded)

    raise ValueError("Decomposition result did not contain a JSON object")


def _extract_fenced_json(text: str) -> str | None:
    fence = "```"
    start = text.find(fence)
    while start != -1:
        content_start = start + len(fence)
        line_end = text.find("\n", content_start)
        if line_end == -1:
            return None
        language = text[content_start:line_end].strip().lower()
        end = text.find(fence, line_end + 1)
        if end == -1:
            return None
        content = text[line_end + 1 : end].strip()
        if language in {"json", "cellos-tasks", ""} and content:
            return content
        start = text.find(fence, end + len(fence))
    return None


def _extract_first_json_object(text: str) -> str | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            _payload, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return text[index : index + end]
    return None
