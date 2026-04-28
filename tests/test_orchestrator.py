import asyncio

import pytest

from cellos.db import CellosDatabase
from cellos.models import AgentRole, Task, TaskResult, TaskStatus, TaskType
from cellos.orchestrator import Orchestrator


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeBackend:
    def __init__(self):
        self.started: list[str] = []

    async def run_task_once(self, task: Task, cwd):
        self.started.append(task.id)
        await asyncio.sleep(0)
        return TaskResult(task_id=task.id, success=True, summary=f"done {task.id}")


@pytest.mark.anyio
async def test_orchestrator_runs_only_ready_unblocked_tasks(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()

    await db.create_task(
        Task(
            id="task-3",
            title="Dependency",
            task_type=TaskType.DESIGN,
            role=AgentRole.COMPOSER,
            status=TaskStatus.IN_PROGRESS,
        )
    )
    await db.create_task(
        Task(
            id="task-1",
            title="Ready build",
            task_type=TaskType.BUILD,
            role=AgentRole.CELLO,
            status=TaskStatus.READY,
        )
    )
    await db.create_task(
        Task(
            id="task-2",
            title="Blocked build",
            task_type=TaskType.BUILD,
            role=AgentRole.CELLO,
            status=TaskStatus.READY,
            dependencies=["task-3"],
        )
    )

    backend = FakeBackend()
    orchestrator = Orchestrator(db=db, backend=backend, cwd=tmp_path)

    results = await orchestrator.run_ready_tasks()

    assert [result.task_id for result in results] == ["task-1"]
    assert backend.started == ["task-1"]
    assert (await db.get_task("task-1")).status == TaskStatus.DONE
    assert (await db.get_task("task-2")).status == TaskStatus.READY
    await db.close()
