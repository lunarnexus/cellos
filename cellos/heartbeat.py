"""One-turn scheduler heartbeat for CelloS."""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from cellos.db import CellosDatabase
from cellos.models import Task, TaskResult, TaskStatus
from cellos.workers import TaskWorker


@dataclass
class HeartbeatResult:
    attention_tasks: list[Task] = field(default_factory=list)
    executed_results: list[TaskResult] = field(default_factory=list)


class Heartbeat:
    def __init__(
        self,
        db: CellosDatabase,
        worker: TaskWorker,
        cwd: str | Path,
        concurrent_tasks: int = 4,
    ):
        self.db = db
        self.worker = worker
        self.cwd = Path(cwd)
        self.concurrent_tasks = concurrent_tasks

    async def run_once(self) -> HeartbeatResult:
        attention_tasks = await self.db.list_tasks_requiring_attention(limit=self.concurrent_tasks)
        remaining_slots = max(self.concurrent_tasks - len(attention_tasks), 0)
        approved_tasks = await self.db.list_approved_unblocked_tasks(limit=remaining_slots)
        executed_results = await asyncio.gather(*(self._run_task(task) for task in approved_tasks))
        return HeartbeatResult(
            attention_tasks=attention_tasks,
            executed_results=list(executed_results),
        )

    async def _run_task(self, task: Task) -> TaskResult:
        await self.db.update_task_status(task.id, TaskStatus.IN_PROGRESS)
        try:
            result = await self.worker.run_task(task, self.cwd)
        except Exception as exc:
            result = TaskResult(
                task_id=task.id,
                success=False,
                summary=f"Task failed: {exc}",
                error=str(exc),
            )
        await self.db.save_task_result(result)
        return result
