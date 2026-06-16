"""Scheduler — event-driven daemon for CelloS.

Uses asyncio.Event() instead of polling. Wakes when:
  - A worker subprocess exits (detected via process status check)
  - Human CLI actions write a notification file (watched via file watcher)
  - SIGINT/SIGTERM received (graceful shutdown)

Priority ordering per cycle:
  1. Attention tasks (human changes, comments)
  2. Planning candidates (draft tasks ready for planning)
  3. Approved unblocked tasks (execution candidates)
"""

from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from cellos.config import CellosConfig
from cellos.db import CellosDatabase
from cellos.models import Task
from cellos.services.worker_spawner import WorkerSpawner

logger = logging.getLogger(__name__)


@dataclass
class ScheduleResult:
    """Result of a single scheduling cycle."""

    attention_tasks: list[Task] = field(default_factory=list)
    planning_tasks: list[Task] = field(default_factory=list)
    execution_tasks: list[Task] = field(default_factory=list)


class SchedulerService:
    """Query the database and pick work in priority order.

    Stateless — each call opens a fresh view of the database.
    """

    def __init__(self, db: CellosDatabase):
        self.db = db

    async def pick_work(self, max_tasks: int = 10) -> ScheduleResult:
        """Pick available work in priority order.

        Priority: attention → planning → execution.
        Attention tasks are reported but do NOT count against max_tasks
        (they require human review and don't spawn workers).
        Planning and execution tasks together respect the max_tasks limit.

        Args:
            max_tasks: Maximum number of worker-spawning tasks to pick.

        Returns:
            ScheduleResult with tasks grouped by category.
        """
        result = ScheduleResult()

        # 1. Attention tasks (reported but don't consume worker slots)
        result.attention_tasks = await self.db.list_tasks_requiring_attention()
        attention_ids = {t.id for t in result.attention_tasks}

        remaining = max_tasks

        # 2. Planning candidates (draft tasks ready for planning)
        planning = await self.db.list_tasks_ready_for_planning()
        # Exclude tasks already flagged for attention
        result.planning_tasks = [t for t in planning if t.id not in attention_ids]
        # Cap to remaining budget
        result.planning_tasks = result.planning_tasks[:remaining]
        remaining -= len(result.planning_tasks)

        if remaining <= 0:
            return result

        # 3. Approved unblocked tasks (execution candidates)
        # Exclude tasks already in attention or planning lists
        execution = await self.db.list_approved_unblocked_tasks(
            max_results=remaining
        )
        result.execution_tasks = [
            t for t in execution if t.id not in attention_ids
        ][:remaining]

        return result


class DaemonService:
    """Event-driven scheduler daemon.

    Uses asyncio.Event() to sleep until signaled. No polling loop.
    Wakes when workers exit or human CLI actions write a notification file.
    """

    def __init__(
        self,
        db: CellosDatabase,
        config: CellosConfig,
        config_dir: str | None = None,
        workdir: str | None = None,
    ):
        self.db = db
        self.config = config
        self.config_dir = config_dir
        self.workdir = workdir or "."
        self.scheduler = SchedulerService(db)
        self.spawner = WorkerSpawner(
            logs_dir=str(Path(self.workdir) / "logs"),
        )

        # Event-driven wake mechanism
        self._wake_event = asyncio.Event()
        self._running_workers: dict[str, asyncio.Task] = {}
        self._shutdown = False

        # Notification file for CLI actions to signal the daemon
        self._notification_file = Path(self.workdir) / ".cellos" / "daemon_notify"
        self._notification_file.parent.mkdir(parents=True, exist_ok=True)

        # File watcher
        self._file_watcher_task: Optional[asyncio.Task] = None

    def notify(self) -> None:
        """Signal the daemon to wake and re-evaluate scheduling.

        Called by CLI commands after human actions (approve, update, add-task).
        """
        self._notification_file.touch()
        self._wake_event.set()

    def _read_notification(self) -> None:
        """Consume the notification file (clear the signal)."""
        try:
            self._notification_file.unlink(missing_ok=True)
        except OSError:
            pass

    async def start(self) -> None:
        """Start the daemon loop.

        Blocks until SIGINT/SIGTERM or explicit stop().
        On shutdown: waits for running workers, closes DB connection.
        """
        logger.info("Daemon starting in %s", self.workdir)

        # Register signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._handle_signal)

        # Start file watcher
        self._file_watcher_task = asyncio.create_task(self._watch_notification_file())

        # Trigger initial cycle on startup so existing draft tasks are discovered.
        self._wake_event.set()

        try:
            while not self._shutdown:
                # Wait for wake signal (blocks until notified)
                await self._wake_event.wait()
                self._wake_event.clear()
                self._read_notification()

                await self._run_cycle()

                # If no workers are running and not shutting down, wait for next signal
                if not self._running_workers and not self._shutdown:
                    logger.info("No workers running, waiting for signal...")
                    # Don't return here — loop back to await _wake_event
        finally:
            # Cleanup
            logger.info("Daemon shutting down...")
            if self._file_watcher_task:
                self._file_watcher_task.cancel()
                try:
                    await self._file_watcher_task
                except asyncio.CancelledError:
                    pass

            # Wait for running workers to finish
            if self._running_workers:
                logger.info(
                    "Waiting for %d running workers to finish...",
                    len(self._running_workers),
                )
                await asyncio.gather(*self._running_workers.values(), return_exceptions=True)

            await self.db.close()
            logger.info("Daemon stopped.")

    def _handle_signal(self) -> None:
        """Handle SIGINT/SIGTERM — initiate graceful shutdown."""
        logger.info("Signal received, initiating shutdown...")
        self._shutdown = True
        self._wake_event.set()

    async def _watch_notification_file(self) -> None:
        """Watch the notification file for changes (human CLI actions).

        Polls every 0.5s — lightweight since it's just checking file existence/mtime.
        """
        last_mtime = 0.0
        while not self._shutdown:
            await asyncio.sleep(0.5)
            try:
                if self._notification_file.exists():
                    current_mtime = self._notification_file.stat().st_mtime
                    if current_mtime != last_mtime:
                        last_mtime = current_mtime
                        self._wake_event.set()
                        logger.debug("Notification file changed, waking daemon")
            except OSError:
                pass

    async def _run_cycle(self) -> None:
        """Run a single scheduling cycle: pick work and spawn workers."""
        if self._shutdown:
            return

        max_concurrent = self.config.scheduler.concurrent_tasks

        # Check how many workers are already running
        running_count = len(self._running_workers)
        available_slots = max_concurrent - running_count

        if available_slots <= 0:
            logger.info(
                "At concurrency limit (%d/%d), skipping cycle",
                running_count, max_concurrent,
            )
            return

        # Pick work
        work = await self.scheduler.pick_work(max_tasks=available_slots)

        total_picked = (
            len(work.attention_tasks)
            + len(work.planning_tasks)
            + len(work.execution_tasks)
        )

        if total_picked == 0:
            logger.debug("No work to schedule")
            return

        logger.info(
            "Cycle: attention=%d planning=%d execution=%d (slots=%d)",
            len(work.attention_tasks),
            len(work.planning_tasks),
            len(work.execution_tasks),
            available_slots,
        )

        # Spawn workers for each task
        spawned = 0

        # Attention tasks: these need human review, log but don't auto-execute
        for task in work.attention_tasks:
            reason = task.attention.reason or "unknown"
            logger.info(
                "Attention task %s: %s (reason: %s) — requires human review",
                task.id, task.title, reason,
            )

        # Planning candidates
        for task in work.planning_tasks:
            if spawned >= available_slots:
                break
            await self._spawn_worker(task, "planning")
            spawned += 1

        # Execution candidates
        for task in work.execution_tasks:
            if spawned >= available_slots:
                break
            await self._spawn_worker(task, "execution")
            spawned += 1

        logger.info("Spawned %d workers this cycle", spawned)

    async def _spawn_worker(self, task: Task, mode: str) -> None:
        """Spawn a worker subprocess for the task and track it."""
        proc = self.spawner.spawn(
            task_id=task.id,
            mode=mode,
            db_path=self.db.db_path,
            config_dir=self.config_dir,
            workdir=self.workdir,
        )

        # Track the worker process — we'll poll for its exit
        async def _track_worker() -> None:
            try:
                # Poll the detached process until it exits
                while proc.poll() is None:
                    await asyncio.sleep(1)
                logger.info(
                    "Worker for task %s (pid=%d) exited with code %d",
                    task.id, proc.pid, proc.returncode,
                )
            except Exception as e:
                logger.error("Error tracking worker %s: %s", task.id, e)
            finally:
                # Remove from tracking and wake daemon for next cycle
                self._running_workers.pop(task.id, None)
                self._wake_event.set()

        self._running_workers[task.id] = asyncio.create_task(_track_worker())
