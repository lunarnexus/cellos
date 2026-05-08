"""One-turn scheduler service for CelloS."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cellos.config import CellosConfig
from cellos.db import CellosDatabase
from cellos.domain.tasks import Task
from cellos.domain.results import TaskResult
from cellos.domain.enums import TaskStatus
from cellos.services.worker_spawner import WorkerMode, WorkerSpawner


class SchedulerConfigLike(Protocol):
    scheduler: object


@dataclass
class ScheduleResult:
    attention_tasks: list[Task]
    planning_tasks: list[Task]
    execution_tasks: list[Task]


class SchedulerService:
    """Select and schedule bounded work for one CelloS heartbeat."""

    def __init__(
        self,
        *,
        db: CellosDatabase,
        config: CellosConfig | SchedulerConfigLike,
        workdir: Path,
        db_path: Path,
        config_path: Path,
        worker_spawner: WorkerSpawner | None = None,
    ) -> None:
        self.db = db
        self.config = config
        self.workdir = workdir
        self.db_path = db_path
        self.config_path = config_path
        self.worker_spawner = worker_spawner or WorkerSpawner()

    async def run_once(self, concurrent_tasks: int | None = None) -> ScheduleResult:
        resolved_concurrent_tasks = concurrent_tasks or self.config.scheduler.concurrent_tasks
        planning_candidates = await self.db.list_tasks_ready_for_planning(limit=resolved_concurrent_tasks)
        planning_ids = {task.id for task in planning_candidates}
        remaining_after_planning = max(resolved_concurrent_tasks - len(planning_candidates), 0)
        attention_tasks = [
            task
            for task in await self.db.list_tasks_requiring_attention(limit=resolved_concurrent_tasks)
            if task.id not in planning_ids
        ][:remaining_after_planning]
        remaining_slots = max(remaining_after_planning - len(attention_tasks), 0)
        approved_tasks = await self.db.list_approved_unblocked_tasks(limit=remaining_slots)
        planning_tasks: list[Task] = []
        execution_tasks: list[Task] = []
        for task in planning_candidates:
            scheduled = await self._schedule_worker(task, "planning")
            if scheduled is not None:
                planning_tasks.append(scheduled)
        for task in approved_tasks:
            scheduled = await self._schedule_worker(task, "execution")
            if scheduled is not None:
                execution_tasks.append(scheduled)
        return ScheduleResult(
            attention_tasks=attention_tasks,
            planning_tasks=planning_tasks,
            execution_tasks=execution_tasks,
        )

    async def _schedule_worker(self, task: Task, mode: WorkerMode) -> Task | None:
        scheduled = await self.db.update_task_status(task.id, TaskStatus.IN_PROGRESS)
        await self.db.record_task_event(task.id, "worker_spawned", f"Background {mode} worker spawned")
        await self.db.conn.commit()
        try:
            self.worker_spawner.spawn(
                scheduled,
                db_path=self.db_path,
                config_path=self.config_path,
                workdir=self.workdir,
                mode=mode,
            )
        except Exception as exc:
            await self.db.save_task_result(
                TaskResult(
                    task_id=task.id,
                    success=False,
                    summary=f"Worker spawn failed: {exc}",
                    error=str(exc),
                )
            )
            return None
        return scheduled
