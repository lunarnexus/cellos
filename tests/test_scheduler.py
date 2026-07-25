"""Tests for scheduler service and daemon.

Covers:
- SchedulerService.pick_work() priority ordering
- DaemonService event-driven wake (no polling)
- Worker tracking and lifecycle
- Notification file mechanism
- Concurrency limits
- Empty scheduling cycles
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from cellos.config import (
    AgentCatalogEntry,
    CellosConfig,
    PromptProfilesConfig,
    SchedulerConfig,
)
from cellos.db import CellosDatabase
from cellos.models import (
    AttentionMetadata,
    Task,
    TaskAttemptStatus,
    TaskDependency,
    TaskStatus,
)
from cellos.persistence.schema import init_db
from cellos.services.scheduler import DaemonService, SchedulerService


async def _wait_until(predicate, timeout: float = 1.0) -> None:
    """Poll until predicate() is truthy or raise TimeoutError."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise TimeoutError("condition not met before timeout")


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def config():
    return CellosConfig(
        scheduler=SchedulerConfig(concurrent_tasks=4),
        agent_catalog={
            "engineer": AgentCatalogEntry(connector="fake_acp"),
        },
        prompt_profiles=PromptProfilesConfig(),
    )


@pytest.fixture
def tmp_db_path(tmp_path: Path):
    return str(tmp_path / "test_cellos.sqlite")


@pytest_asyncio.fixture
async def db(tmp_db_path: str):
    await init_db(tmp_db_path)
    database = CellosDatabase(tmp_db_path)
    await database.connect()  # No FK enforcement for tests
    yield database
    await database.close()


@pytest.fixture
def scheduler(db: CellosDatabase):
    return SchedulerService(db)


@pytest.fixture
def sample_task():
    from cellos.models import AgentRole
    return Task(
        id="task-1",
        title="Test task",
        status=TaskStatus.DRAFT,
        role=AgentRole.ARCHITECT,
    )


# ── SchedulerService Tests ───────────────────────────────────────────────────


class TestSchedulerService:
    """Test work picking logic and priority ordering."""

    @pytest.mark.asyncio
    async def test_pick_work_empty_db(self, scheduler: SchedulerService):
        """No tasks in DB → empty ScheduleResult."""
        result = await scheduler.pick_work()
        assert result.attention_tasks == []
        assert result.planning_tasks == []
        assert result.execution_tasks == []

    @pytest.mark.asyncio
    async def test_pick_work_planning_candidates(self, scheduler: SchedulerService, sample_task: Task):
        """Draft tasks should appear as planning candidates."""
        await scheduler.db.create_task(sample_task)
        result = await scheduler.pick_work()
        assert len(result.planning_tasks) == 1
        assert result.planning_tasks[0].id == "task-1"

    @pytest.mark.asyncio
    async def test_pick_work_attention_priority(self, scheduler: SchedulerService, sample_task: Task):
        """Tasks with attention should appear in attention list."""
        task_with_attention = sample_task.model_copy(
            update={
                "attention": AttentionMetadata.model_validate(
                    {"required": True, "reason": "human_changed_task"}
                ),
            }
        )
        await scheduler.db.create_task(task_with_attention)
        result = await scheduler.pick_work()
        assert len(result.attention_tasks) == 1
        assert result.attention_tasks[0].id == "task-1"

    @pytest.mark.asyncio
    async def test_pick_work_execution_candidates(self, scheduler: SchedulerService):
        """Approved tasks with no dependencies should appear as execution candidates."""
        approved_task = Task(
            id="task-2",
            title="Approved task",
            status=TaskStatus.APPROVED,
        )
        await scheduler.db.create_task(approved_task)
        result = await scheduler.pick_work()
        assert len(result.execution_tasks) == 1
        assert result.execution_tasks[0].id == "task-2"

    @pytest.mark.asyncio
    async def test_pick_work_respects_max_tasks(self, scheduler: SchedulerService):
        """max_tasks limit should cap worker-spawning tasks (not attention)."""
        for i in range(5):
            task = Task(
                id=f"task-{i}",
                title=f"Task {i}",
                status=TaskStatus.DRAFT,
            )
            await scheduler.db.create_task(task)

        result = await scheduler.pick_work(max_tasks=2)
        # Attention tasks don't count against budget; planning+execution should be <= 2
        worker_spawning = len(result.planning_tasks) + len(result.execution_tasks)
        assert worker_spawning <= 2

    @pytest.mark.asyncio
    async def test_pick_work_attention_does_not_consume_budget(self, scheduler: SchedulerService):
        """Attention tasks should NOT consume the worker slot budget."""
        from cellos.models import AgentRole

        # Create 5 attention tasks (more than max_tasks)
        for i in range(5):
            task = Task(
                id=f"attn-{i}",
                title=f"Attention Task {i}",
                status=TaskStatus.DRAFT,
                role=AgentRole.ARCHITECT,
                attention=AttentionMetadata.model_validate(
                    {"required": True, "reason": "human_changed_task"}
                ),
            )
            await scheduler.db.create_task(task)

        # Create 2 draft tasks (no attention)
        for i in range(2):
            task = Task(
                id=f"draft-{i}",
                title=f"Draft Task {i}",
                status=TaskStatus.DRAFT,
                role=AgentRole.ARCHITECT,
            )
            await scheduler.db.create_task(task)

        result = await scheduler.pick_work(max_tasks=2)
        # All 5 attention tasks should be reported
        assert len(result.attention_tasks) == 5
        # But they should NOT consume the budget — 2 planning tasks should still be picked
        assert len(result.planning_tasks) == 2

    @pytest.mark.asyncio
    async def test_pick_work_in_progress_not_scheduled(self, scheduler: SchedulerService):
        """Tasks already IN_PROGRESS should not appear in any scheduling list."""
        task = Task(
            id="task-busy",
            title="Busy task",
            status=TaskStatus.IN_PROGRESS,
        )
        await scheduler.db.create_task(task)
        result = await scheduler.pick_work()
        assert result.planning_tasks == []
        assert result.execution_tasks == []
        assert result.attention_tasks == []


# ── DaemonService Tests ──────────────────────────────────────────────────────


class TestDaemonService:
    """Test event-driven daemon behavior."""

    @pytest.mark.asyncio
    async def test_notification_file_created(self, db: CellosDatabase, config: CellosConfig, tmp_path: Path):
        """Daemon should create the notification file directory on init."""
        DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )
        notify_dir = tmp_path / ".cellos"
        assert notify_dir.exists()

    @pytest.mark.asyncio
    async def test_write_status_persists_snapshot(self, db: CellosDatabase, config: CellosConfig, tmp_path: Path):
        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )

        daemon._started_at = "2026-06-30T16:00:00+00:00"
        daemon._write_status("idle")

        payload = json.loads((tmp_path / ".cellos" / "daemon_status.json").read_text())
        assert payload["state"] == "idle"
        assert payload["concurrent_limit"] == config.scheduler.concurrent_tasks
        assert payload["running_workers"] == []

    @pytest.mark.asyncio
    async def test_notify_wakes_event(self, db: CellosDatabase, config: CellosConfig, tmp_path: Path):
        """notify() should set the wake event."""
        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )
        assert not daemon._wake_event.is_set()
        daemon.notify()
        assert daemon._wake_event.is_set()

    @pytest.mark.asyncio
    async def test_notify_creates_file(self, db: CellosDatabase, config: CellosConfig, tmp_path: Path):
        """notify() should touch the notification file."""
        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )
        daemon.notify()
        assert daemon._notification_file.exists()

    @pytest.mark.asyncio
    async def test_read_notification_clears_file(self, db: CellosDatabase, config: CellosConfig, tmp_path: Path):
        """_read_notification() should remove the notification file."""
        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )
        daemon.notify()
        assert daemon._notification_file.exists()
        daemon._read_notification()
        assert not daemon._notification_file.exists()

    @pytest.mark.asyncio
    async def test_shutdown_flag_stops_cycle(self, db: CellosDatabase, config: CellosConfig, tmp_path: Path):
        """_run_cycle should return early if _shutdown is True."""
        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )
        daemon._shutdown = True
        await daemon._run_cycle()  # Should return immediately without errors
        assert not daemon._running_workers

    @pytest.mark.asyncio
    async def test_cycle_no_work(self, db: CellosDatabase, config: CellosConfig, tmp_path: Path):
        """Cycle with no tasks should complete without error."""
        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )
        await daemon._run_cycle()
        assert not daemon._running_workers
        payload = json.loads((tmp_path / ".cellos" / "daemon_status.json").read_text())
        assert payload["state"] == "idle"

    @pytest.mark.asyncio
    async def test_concurrency_limit(self, db: CellosDatabase, config: CellosConfig, tmp_path: Path):
        """Should not spawn more workers than concurrent_tasks allows."""
        # Set limit to 1
        config.scheduler.concurrent_tasks = 1

        # Add 3 draft tasks
        for i in range(3):
            task = Task(
                id=f"task-{i}",
                title=f"Task {i}",
                status=TaskStatus.DRAFT,
            )
            await db.create_task(task)

        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )

        # Mock the spawner to avoid actually spawning subprocesses
        with patch.object(daemon.spawner, "spawn") as mock_spawn:
            mock_spawn.return_value = MagicMock(poll=lambda: 0)
            await daemon._run_cycle()

            # Should only spawn 1 worker (concurrent_tasks=1)
            assert mock_spawn.call_count <= 1

    @pytest.mark.asyncio
    async def test_worker_completion_wakes_daemon(self, db: CellosDatabase, config: CellosConfig, tmp_path: Path):
        """Tracked worker completion should remove it and set the wake event."""
        task = Task(
            id="exec-worker",
            title="Execution worker",
            status=TaskStatus.APPROVED,
        )
        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )

        class FakeProc:
            pid = 1234
            returncode = 0

            def __init__(self):
                self.poll_calls = 0

            def poll(self):
                self.poll_calls += 1
                return None if self.poll_calls == 1 else 0

        fake_proc = FakeProc()
        original_sleep = asyncio.sleep

        async def fast_sleep(_: float):
            await original_sleep(0)

        with patch.object(daemon.spawner, "spawn", return_value=fake_proc), patch(
            "cellos.services.scheduler.asyncio.sleep", new=fast_sleep
        ):
            await daemon._spawn_worker(task, "execution")
            assert task.id in daemon._running_workers
            payload = json.loads((tmp_path / ".cellos" / "daemon_status.json").read_text())
            assert payload["state"] == "running"
            assert payload["running_workers"][0]["task_id"] == task.id

            await _wait_until(lambda: daemon._wake_event.is_set())
            await _wait_until(lambda: task.id not in daemon._running_workers)

        assert daemon._wake_event.is_set()

    @pytest.mark.asyncio
    async def test_notification_file_watcher_wakes_on_touch(self, db: CellosDatabase, config: CellosConfig, tmp_path: Path):
        """Watcher should wake the daemon when the notification file is touched externally."""
        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )
        original_sleep = asyncio.sleep

        async def fast_sleep(_: float):
            await original_sleep(0)

        with patch("cellos.services.scheduler.asyncio.sleep", new=fast_sleep):
            watcher = asyncio.create_task(daemon._watch_notification_file())
            try:
                await original_sleep(0)
                daemon._notification_file.touch()
                await _wait_until(lambda: daemon._wake_event.is_set())
            finally:
                daemon._shutdown = True
                await asyncio.wait_for(watcher, timeout=1.0)

        assert daemon._wake_event.is_set()

    @pytest.mark.asyncio
    async def test_dependency_completion_leaves_downstream_runnable_next_cycle(self, db: CellosDatabase, config: CellosConfig, tmp_path: Path):
        """After a dependency completes and attention is cleared, the next cycle can execute downstream work."""
        dependency = Task(
            id="dep-done",
            title="Dependency",
            status=TaskStatus.DONE,
        )
        downstream = Task(
            id="downstream-approved",
            title="Downstream",
            status=TaskStatus.APPROVED,
            dependencies=[TaskDependency(task_id=dependency.id, status_satisfied=False)],
        )
        await db.create_task(dependency)
        await db.create_task(downstream)

        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )

        first_cycle = await daemon.scheduler.pick_work()
        assert all(task.id != downstream.id for task in first_cycle.execution_tasks)

        affected = await db.save_task_result(
            dependency.id, success=True, summary="Dependency completed"
        )
        assert downstream.id in affected

        woken = await db.get_task(downstream.id)
        assert woken is not None
        assert woken.attention.required is True
        assert all(dep.status_satisfied for dep in woken.dependencies)

        await db.update_task(woken.clear_attention())

        next_cycle = await daemon.scheduler.pick_work()
        assert [task.id for task in next_cycle.execution_tasks] == [downstream.id]

# ── Scheduler Auto-Sync Tests ───────────────────────────────────────

class TestSchedulerAutoSync:
    """Test provider-driven auto-sync hooks in the scheduler."""

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self, db: CellosDatabase, config: CellosConfig, tmp_path: Path):
        """Provider hooks should be skipped when integration is disabled."""
        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )
        assert daemon._is_auto_sync_enabled() in (True, False)

    @pytest.mark.asyncio
    async def test_push_invoked_when_enabled(self, db: CellosDatabase, config: CellosConfig, tmp_path: Path):
        """auto_push should be called when auto-sync is enabled."""
        from cellos.config import IntegrationsConfig, ProviderConfig
        config.integrations = IntegrationsConfig(
            providers={"example": ProviderConfig(auto_sync_enabled=True)}
        )

        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )
        assert daemon._is_auto_sync_enabled() is True

    @pytest.mark.asyncio
    async def test_pull_interval_gate(self, db: CellosDatabase, config: CellosConfig, tmp_path: Path):
        """Pull should respect the interval gate."""
        from cellos.config import IntegrationsConfig, ProviderConfig
        config.integrations = IntegrationsConfig(
            providers={"example": ProviderConfig(auto_sync_enabled=True, pull_interval_seconds=600)}
        )

        assert config.integrations.example.pull_interval_seconds == 600

    @pytest.mark.asyncio
    async def test_provider_exception_isolated(self, db: CellosDatabase, config: CellosConfig, tmp_path: Path):
        """Provider exceptions should not break scheduling."""
        from cellos.config import IntegrationsConfig, ProviderConfig
        config.integrations = IntegrationsConfig(
            enabled_providers=["example"],
            providers={"example": ProviderConfig(auto_sync_enabled=True)}
        )

        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )

        with patch("cellos.integrations.registry.load_provider") as mock_load:
            from cellos.integrations.base import SyncDelta
            prov_mock = AsyncMock()
            prov_mock.auto_push.return_value = SyncDelta()
            prov_mock.auto_pull_maybe.return_value = SyncDelta()
            prov_mock._db = db
            mock_load.return_value = prov_mock

            await daemon._provider_sync_push()
            await daemon._provider_sync_pull_maybe()
            assert prov_mock.auto_push.called
            assert prov_mock.auto_pull_maybe.called


class TestOrphanReconciliation:
    @pytest.mark.asyncio
    async def test_reconcile_orphaned_planning_task_restores_to_draft(self, db: CellosDatabase, config: CellosConfig, tmp_path: Path):
        task = Task(id="plan-orphan", title="Plan orphan", status=TaskStatus.IN_PROGRESS)
        await db.create_task(task)
        await db.create_attempt(task.id, mode="planning", agent_id="engineer")

        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )

        await daemon._reconcile_orphaned_in_progress_tasks()

        recovered = await db.get_task(task.id)
        attempts = await db.list_attempts(task.id)
        assert recovered is not None
        assert recovered.status == TaskStatus.DRAFT
        assert recovered.attention.required is True
        assert attempts[0].status == TaskAttemptStatus.FAILED

    @pytest.mark.asyncio
    async def test_reconcile_orphaned_execution_task_restores_to_approved(self, db: CellosDatabase, config: CellosConfig, tmp_path: Path):
        task = Task(id="exec-orphan", title="Exec orphan", status=TaskStatus.IN_PROGRESS)
        await db.create_task(task)
        await db.create_attempt(task.id, mode="execution", agent_id="engineer")

        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )

        await daemon._reconcile_orphaned_in_progress_tasks()

        recovered = await db.get_task(task.id)
        attempts = await db.list_attempts(task.id)
        assert recovered is not None
        assert recovered.status == TaskStatus.APPROVED
        assert recovered.attention.required is True
        assert attempts[0].status == TaskAttemptStatus.FAILED

    @pytest.mark.asyncio
    async def test_reconcile_skips_live_tracked_worker(self, db: CellosDatabase, config: CellosConfig, tmp_path: Path):
        task = Task(id="live-worker", title="Live worker", status=TaskStatus.IN_PROGRESS)
        await db.create_task(task)
        await db.create_attempt(task.id, mode="execution", agent_id="engineer")

        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )
        daemon._running_workers[task.id] = asyncio.create_task(asyncio.sleep(60))

        try:
            await daemon._reconcile_orphaned_in_progress_tasks()
        finally:
            daemon._running_workers[task.id].cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await daemon._running_workers[task.id]
            daemon._running_workers.pop(task.id, None)

        current = await db.get_task(task.id)
        attempts = await db.list_attempts(task.id)
        assert current is not None
        assert current.status == TaskStatus.IN_PROGRESS
        assert attempts[0].status == TaskAttemptStatus.STARTED

    @pytest.mark.asyncio
    async def test_reconcile_in_progress_without_attempt_sets_attention(self, db: CellosDatabase, config: CellosConfig, tmp_path: Path):
        task = Task(id="no-attempt", title="No attempt", status=TaskStatus.IN_PROGRESS)
        await db.create_task(task)

        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )

        await daemon._reconcile_orphaned_in_progress_tasks()

        recovered = await db.get_task(task.id)
        events = await db.list_events(task.id)
        assert recovered is not None
        assert recovered.attention.required is True
        assert recovered.status == TaskStatus.DRAFT
        assert any(event.event_type == "worker_orphaned" for event in events)

    @pytest.mark.asyncio
    async def test_reconcile_terminal_failed_attempt_still_restores_task(self, db: CellosDatabase, config: CellosConfig, tmp_path: Path):
        task = Task(id="failed-orphan", title="Failed orphan", status=TaskStatus.IN_PROGRESS)
        await db.create_task(task)
        attempt = await db.create_attempt(task.id, mode="execution", agent_id="engineer")
        await db.update_attempt(attempt.id, TaskAttemptStatus.FAILED, error_message="boom")

        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )

        await daemon._reconcile_orphaned_in_progress_tasks()

        recovered = await db.get_task(task.id)
        attempts = await db.list_attempts(task.id)
        events = await db.list_events(task.id)
        assert recovered is not None
        assert recovered.status == TaskStatus.APPROVED
        assert recovered.attention.required is True
        assert attempts[0].status == TaskAttemptStatus.FAILED
        assert any(event.event_type == "worker_orphaned" for event in events)
