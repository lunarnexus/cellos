import asyncio

import pytest

from cellos.db import CellosDatabase
from cellos.heartbeat import Heartbeat
from cellos.models import AgentRole, AttentionReason, Task, TaskResult, TaskStatus


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeWorker:
    def __init__(self):
        self.started: list[str] = []

    async def run_task(self, task: Task, cwd):
        self.started.append(task.id)
        await asyncio.sleep(0)
        return TaskResult(task_id=task.id, success=True, summary=f"done {task.id}")


@pytest.mark.anyio
async def test_heartbeat_executes_approved_unblocked_tasks(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()

    await db.create_task(
        Task(
            id="task-1",
            title="Build",
            role=AgentRole.ENGINEER,
            status=TaskStatus.APPROVED,
        )
    )

    worker = FakeWorker()
    heartbeat = Heartbeat(db=db, worker=worker, cwd=tmp_path)
    result = await heartbeat.run_once()

    assert worker.started == ["task-1"]
    assert [item.task_id for item in result.executed_results] == ["task-1"]
    assert (await db.get_task("task-1")).status == TaskStatus.DONE
    await db.close()


@pytest.mark.anyio
async def test_heartbeat_does_not_execute_blocked_tasks(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()

    await db.create_task(
        Task(
            id="task-dep",
            title="Dependency",
            role=AgentRole.TESTER,
            status=TaskStatus.APPROVED,
        )
    )
    await db.create_task(
        Task(
            id="task-blocked",
            title="Blocked",
            role=AgentRole.ENGINEER,
            status=TaskStatus.APPROVED,
            dependencies=["task-dep"],
        )
    )

    worker = FakeWorker()
    heartbeat = Heartbeat(db=db, worker=worker, cwd=tmp_path)
    await heartbeat.run_once()

    assert worker.started == ["task-dep"]
    assert (await db.get_task("task-blocked")).status == TaskStatus.APPROVED
    await db.close()


@pytest.mark.anyio
async def test_heartbeat_reserves_capacity_for_attention_tasks(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()

    attention_task = Task(
        id="task-attention",
        title="Needs review",
        role=AgentRole.ARCHITECT,
    ).requires_attention(AttentionReason.HUMAN_COMMENTED, "Human changed the task")
    await db.create_task(attention_task)
    await db.create_task(
        Task(
            id="task-approved",
            title="Build",
            role=AgentRole.ENGINEER,
            status=TaskStatus.APPROVED,
        )
    )

    worker = FakeWorker()
    heartbeat = Heartbeat(db=db, worker=worker, cwd=tmp_path, concurrent_tasks=1)
    result = await heartbeat.run_once()

    assert [task.id for task in result.attention_tasks] == ["task-attention"]
    assert worker.started == []
    assert result.executed_results == []
    await db.close()


@pytest.mark.anyio
async def test_heartbeat_records_worker_failure(tmp_path):
    class FailingWorker:
        async def run_task(self, task: Task, cwd):
            raise RuntimeError("boom")

    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()
    await db.create_task(
        Task(
            id="task-1",
            title="Build",
            role=AgentRole.ENGINEER,
            status=TaskStatus.APPROVED,
        )
    )

    heartbeat = Heartbeat(db=db, worker=FailingWorker(), cwd=tmp_path)
    result = await heartbeat.run_once()

    saved = await db.get_task("task-1")
    assert result.executed_results[0].success is False
    assert result.executed_results[0].error == "boom"
    assert saved.status == TaskStatus.FAILED
    await db.close()
