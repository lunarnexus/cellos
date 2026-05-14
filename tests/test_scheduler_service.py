import pytest

from cellos.db import CellosDatabase
from cellos.models import AgentRole, AttentionReason, Task, TaskStatus
from cellos.services.scheduler import SchedulerService


@pytest.fixture
def anyio_backend():
    return "asyncio"


class RecordingSpawner:
    def __init__(self):
        self.spawned: list[tuple[str, str]] = []

    def spawn(self, task, *, db_path, config_path, workdir, mode):
        self.spawned.append((task.id, mode))


class SchedulerConfig:
    concurrent_tasks = 3


class Config:
    scheduler = SchedulerConfig()


@pytest.mark.anyio
async def test_scheduler_service_prioritizes_planning_then_attention_then_execution(tmp_path):
    db_path = tmp_path / "cellos.sqlite"
    db = CellosDatabase(db_path)
    await db.connect()
    await db.init_db()
    await db.create_task(Task(id="plan", title="Plan", role=AgentRole.COORDINATOR, status=TaskStatus.DRAFT))
    await db.create_task(
        Task(
            id="attention",
            title="Attention",
            role=AgentRole.ARCHITECT,
            status=TaskStatus.FAILED,
        ).requires_attention(
            AttentionReason.HUMAN_COMMENTED,
            "Needs review",
        )
    )
    await db.create_task(Task(id="execute", title="Execute", role=AgentRole.ENGINEER, status=TaskStatus.APPROVED))
    spawner = RecordingSpawner()

    result = await SchedulerService(
        db=db,
        config=Config(),
        workdir=tmp_path,
        db_path=db_path,
        config_path=tmp_path / "config.json",
        worker_spawner=spawner,
    ).run_once()

    assert [task.id for task in result.planning_tasks] == ["plan"]
    assert [task.id for task in result.attention_tasks] == ["attention"]
    assert [task.id for task in result.execution_tasks] == ["execute"]
    assert sorted(spawner.spawned) == [("execute", "execution"), ("plan", "planning")]
    assert (await db.get_task("plan")).status == TaskStatus.IN_PROGRESS
    assert (await db.get_task("execute")).status == TaskStatus.IN_PROGRESS
    await db.close()


@pytest.mark.anyio
async def test_scheduler_service_records_spawn_failure_as_task_result(tmp_path):
    class FailingSpawner:
        def spawn(self, task, *, db_path, config_path, workdir, mode):
            raise RuntimeError("spawn exploded")

    db_path = tmp_path / "cellos.sqlite"
    db = CellosDatabase(db_path)
    await db.connect()
    await db.init_db()
    await db.create_task(Task(id="execute", title="Execute", role=AgentRole.ENGINEER, status=TaskStatus.APPROVED))

    result = await SchedulerService(
        db=db,
        config=Config(),
        workdir=tmp_path,
        db_path=db_path,
        config_path=tmp_path / "config.json",
        worker_spawner=FailingSpawner(),
    ).run_once(concurrent_tasks=1)

    saved = await db.get_task("execute")
    assert result.execution_tasks == []
    assert saved.status == TaskStatus.FAILED
    assert saved.result is not None
    assert saved.result.error == "spawn exploded"
    await db.close()
