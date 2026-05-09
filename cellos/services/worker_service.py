"""Background worker runtime service for CelloS."""

from pathlib import Path
from typing import Literal

from cellos.acp_worker import AcpWorker
from cellos.config import AgentConfig, CellosConfig
from cellos.db import CellosDatabase
from cellos.domain.tasks import Task
from cellos.domain.attempts import TaskAttempt, TaskAttemptStatus
from cellos.domain.results import TaskResult
from cellos.prompt_builder import build_task_prompt
from cellos.services.execution_service import save_execution_result
from cellos.services.planning_service import save_planning_result

WorkerRunMode = Literal["planning", "execution"]


class WorkerService:
    """Run one scheduled task worker and persist its attempt/result."""

    def __init__(self, *, db: CellosDatabase, config: CellosConfig, workdir: Path) -> None:
        self.db = db
        self.config = config
        self.workdir = workdir

    async def run_task_worker(self, task_id: str, mode: WorkerRunMode) -> None:
        task = await self.db.get_task(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        agent_id, agent = self.config.get_agent(task.agent_id)
        log_path = self.workdir / ".cellos" / "logs" / f"worker-{task.id}.log"
        comments = await self.db.list_task_comments(task.id) if mode == "planning" else None
        prompt_text = build_task_prompt(
            task,
            self.config.prompt_profiles,
            mode=mode,
            comments=comments,
        )
        attempt = await self.db.start_task_attempt(
            TaskAttempt(
                task_id=task.id,
                mode=mode,
                agent_id=agent_id,
                connector=agent.connector,
                prompt_snapshot=prompt_text,
                log_path=str(log_path),
            )
        )
        await self.db.record_task_event(task.id, "worker_started", f"Background {mode} worker started")
        await self.db.conn.commit()
        worker_backend = self._build_worker(agent_id, agent)
        try:
            result = await worker_backend.run_task(task, self.workdir, mode=mode, prompt_text=prompt_text)
        except Exception as exc:
            result = TaskResult(
                task_id=task.id,
                success=False,
                summary=f"Task failed: {exc}",
                error=str(exc),
            )
        if mode == "planning" and result.success:
            await save_planning_result(self.db, task, result)
        else:
            await save_execution_result(
                self.db,
                task,
                result,
                preapprove_research_tasks=self.config.approvals.preapprove_research_tasks,
            )
        if attempt.id is not None:
            await self.db.complete_task_attempt(
                attempt.id,
                TaskAttemptStatus.SUCCEEDED if result.success else TaskAttemptStatus.FAILED,
                result.summary,
                result.model_dump(mode="json"),
                result.error,
            )

        # Write attempt details to per-task log file
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a") as f:
            f.write(f"=== Attempt #{attempt.id} ({mode}) ===\n")
            f.write(f"Prompt:\n{prompt_text}\n\n")
            f.write(f"Result: {'SUCCESS' if result.success else 'FAILED'}\n")
            f.write(f"Summary: {result.summary}\n")
            if result.error:
                f.write(f"Error: {result.error}\n")
            f.write("\n")

    def _build_worker(self, agent_id: str, agent: AgentConfig):
        if self.config.worker.backend == "acp":
            if self.config.worker.debug_logging and self.config.worker.debug_log_path is not None:
                debug_log_path = self.config.worker.debug_log_path
                if not Path(debug_log_path).is_absolute():
                    debug_log_path = str(self.workdir / debug_log_path)
            else:
                debug_log_path = None
            return AcpWorker(
                agent_id=agent_id,
                agent=agent,
                prompt_profiles=self.config.prompt_profiles,
                timeout_seconds=self.config.scheduler.worker_timeout_seconds,
                debug_log_path=debug_log_path,
            )
        raise ValueError(f"Unsupported worker backend: {self.config.worker.backend}")
