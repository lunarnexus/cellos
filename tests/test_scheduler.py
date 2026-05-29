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
import tempfile
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
    TaskStatus,
)
from cellos.persistence.schema import init_db
from cellos.services.scheduler import DaemonService, SchedulerService, ScheduleResult


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
        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )
        notify_dir = tmp_path / ".cellos"
        assert notify_dir.exists()

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
    async def test_attention_tasks_logged_not_executed(self, db: CellosDatabase, config: CellosConfig, tmp_path: Path, caplog):
        """Attention tasks should be logged but not auto-executed."""
        task = Task(
            id="task-attn",
            title="Attention task",
            status=TaskStatus.DRAFT,
            attention=AttentionMetadata.model_validate(
                {"required": True, "reason": "human_changed_task"}
            ),
        )
        await db.create_task(task)

        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )

        with patch.object(daemon.spawner, "spawn") as mock_spawn:
            await daemon._run_cycle()
            # Attention tasks should NOT spawn workers
            assert mock_spawn.call_count == 0


# ── Connector Concurrency Tests ──────────────────────────────────────────────


class TestConnectorConcurrency:
    """Test per-connector concurrency limits."""

    @pytest.fixture
    def config_with_connector_limits(self):
        return CellosConfig(
            scheduler=SchedulerConfig(
                concurrent_tasks=4,
                connector_concurrency={
                    "cellos_acp": 1,
                    "fake_acp": 8,
                },
            ),
            agent_catalog={
                "engineer": AgentCatalogEntry(connector="cellos_acp"),
                "researcher": AgentCatalogEntry(connector="fake_acp"),
            },
            prompt_profiles=PromptProfilesConfig(),
        )

    @pytest.mark.asyncio
    async def test_connector_limit_respected(
        self, db: CellosDatabase, config_with_connector_limits: CellosConfig, tmp_path: Path
    ):
        """Should not spawn more workers than connector limit allows."""
        config = config_with_connector_limits

        # Add 3 tasks using cellos_acp (limit=1)
        for i in range(3):
            task = Task(
                id=f"task-cellos-{i}",
                title=f"Cellos Task {i}",
                status=TaskStatus.DRAFT,
            )
            await db.create_task(task)

        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )

        with patch.object(daemon.spawner, "spawn") as mock_spawn:
            mock_spawn.return_value = MagicMock(poll=lambda: 0)
            await daemon._run_cycle()

            # Should only spawn 1 worker (cellos_acp limit=1)
            assert mock_spawn.call_count <= 1

    @pytest.mark.asyncio
    async def test_different_connectors_spawn_independently(
        self, db: CellosDatabase, config_with_connector_limits: CellosConfig, tmp_path: Path
    ):
        """Tasks using different connectors should spawn independently."""
        config = config_with_connector_limits

        # Add 2 tasks using cellos_acp (limit=1)
        for i in range(2):
            task = Task(
                id=f"task-cellos-{i}",
                title=f"Cellos Task {i}",
                status=TaskStatus.DRAFT,
            )
            await db.create_task(task)

        # Add 1 task using fake_acp (limit=8)
        from cellos.models import AgentRole
        task = Task(
            id="task-fake",
            title="Fake Task",
            status=TaskStatus.DRAFT,
            role=AgentRole.RESEARCHER,
        )
        await db.create_task(task)

        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )

        with patch.object(daemon.spawner, "spawn") as mock_spawn:
            mock_spawn.return_value = MagicMock(poll=lambda: 0)
            await daemon._run_cycle()

            # Should spawn 1 cellos_acp + 1 fake_acp = 2 workers
            assert mock_spawn.call_count == 2

    @pytest.mark.asyncio
    async def test_global_cap_still_applies(
        self, db: CellosDatabase, config_with_connector_limits: CellosConfig, tmp_path: Path
    ):
        """Global concurrent_tasks cap should still limit total workers."""
        config = config_with_connector_limits
        # Set global limit to 1 (lower than sum of connector limits)
        config.scheduler.concurrent_tasks = 1

        # Add 1 task using cellos_acp
        task1 = Task(
            id="task-cellos-1",
            title="Cellos Task 1",
            status=TaskStatus.DRAFT,
        )
        await db.create_task(task1)

        # Add 1 task using fake_acp
        from cellos.models import AgentRole
        task2 = Task(
            id="task-fake-1",
            title="Fake Task 1",
            status=TaskStatus.DRAFT,
            role=AgentRole.RESEARCHER,
        )
        await db.create_task(task2)

        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )

        with patch.object(daemon.spawner, "spawn") as mock_spawn:
            mock_spawn.return_value = MagicMock(poll=lambda: 0)
            await daemon._run_cycle()

            # Global cap=1, so only 1 worker should spawn
            assert mock_spawn.call_count <= 1

    @pytest.mark.asyncio
    async def test_connector_default_limit(self, db: CellosDatabase, config: CellosConfig, tmp_path: Path):
        """Unconfigured connectors should default to limit of 1."""
        # Default config has no connector_concurrency
        assert config.scheduler.connector_concurrency == {}

        # Verify default limit is 1
        assert config.get_connector_concurrency("unknown_connector") == 1

    @pytest.mark.asyncio
    async def test_connector_count_decremented_on_exit(
        self, db: CellosDatabase, config_with_connector_limits: CellosConfig, tmp_path: Path
    ):
        """Connector worker count should be decremented when worker exits."""
        config = config_with_connector_limits

        # Add 2 tasks using cellos_acp (limit=1)
        for i in range(2):
            task = Task(
                id=f"task-cellos-{i}",
                title=f"Cellos Task {i}",
                status=TaskStatus.DRAFT,
            )
            await db.create_task(task)

        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )

        with patch.object(daemon.spawner, "spawn") as mock_spawn:
            mock_spawn.return_value = MagicMock(poll=lambda: 0)
            await daemon._run_cycle()

            # First cycle: 1 worker spawned (limit=1)
            assert daemon._connector_workers.get("cellos_acp", 0) == 1

            # Wait for worker to "exit" (poll returns 0 immediately)
            await asyncio.sleep(0.1)

            # Second cycle: should spawn another worker now that first exited
            await daemon._run_cycle()

            # Should have spawned 1 more (total 2 across cycles)
            assert mock_spawn.call_count == 2

    @pytest.mark.asyncio
    async def test_can_spawn_checks_both_limits(
        self, db: CellosDatabase, config_with_connector_limits: CellosConfig, tmp_path: Path
    ):
        """_can_spawn should check both global and connector limits."""
        config = config_with_connector_limits

        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )

        # No workers running — should be able to spawn
        assert daemon._can_spawn("cellos_acp") is True
        assert daemon._can_spawn("fake_acp") is True

        # Simulate running workers at global limit
        config.scheduler.concurrent_tasks = 1
        daemon._running_workers["task-1"] = MagicMock()
        assert daemon._can_spawn("cellos_acp") is False
        assert daemon._can_spawn("fake_acp") is False

        # Reset global, simulate connector at limit
        config.scheduler.concurrent_tasks = 4
        daemon._running_workers.clear()
        daemon._connector_workers["cellos_acp"] = 1
        assert daemon._can_spawn("cellos_acp") is False  # At limit
        assert daemon._can_spawn("fake_acp") is True  # Different connector, under limit

    @pytest.mark.asyncio
    async def test_resolve_agent_for_task(
        self, db: CellosDatabase, config_with_connector_limits: CellosConfig, tmp_path: Path
    ):
        """_get_connector_for_task should resolve agent and connector correctly."""
        config = config_with_connector_limits

        daemon = DaemonService(
            db=db, config=config, config_dir=str(tmp_path), workdir=str(tmp_path)
        )

        from cellos.models import AgentRole
        task = Task(
            id="test-task",
            title="Test",
            status=TaskStatus.DRAFT,
            role=AgentRole.ENGINEER,
        )

        agent, connector_type = daemon._get_connector_for_task(task)
        assert agent.connector == "cellos_acp"
        assert connector_type == "cellos_acp"
