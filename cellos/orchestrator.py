"""Core orchestration loop for ready CelloS tasks."""

import asyncio
from pathlib import Path

from cellos.agents import AgentBackend
from cellos.db import CellosDatabase
from cellos.models import Task, TaskResult, TaskStatus


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
        try:
            result = await self.backend.run_task_once(task, self.cwd)
        except Exception as exc:
            result = TaskResult(
                task_id=task.id,
                success=False,
                summary=f"Task failed: {exc}",
                error=str(exc),
            )
        await self.db.save_task_result(result)
        return result
