import asyncio
import json

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


class DecomposeBackend:
    async def run_task_once(self, task: Task, cwd):
        return TaskResult(
            task_id=task.id,
            success=True,
            summary=json.dumps(
                {
                    "tasks": [
                        {
                            "key": "build-note",
                            "title": "Create tmp note",
                            "type": "build",
                            "role": "cello",
                            "description": "Create tmp/cellos-real-test.txt",
                            "depends_on": [],
                        },
                        {
                            "key": "verify-note",
                            "title": "Verify tmp note",
                            "type": "test",
                            "role": "critic",
                            "description": "Verify tmp/cellos-real-test.txt",
                            "depends_on": ["build-note"],
                        },
                    ]
                }
            ),
        )


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


@pytest.mark.anyio
async def test_orchestrator_creates_child_tasks_from_decomposition(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()

    await db.create_task(
        Task(
            id="task-parent",
            title="Plan tmp file test",
            task_type=TaskType.DECOMPOSE,
            role=AgentRole.CONDUCTOR,
            status=TaskStatus.READY,
        )
    )

    orchestrator = Orchestrator(db=db, backend=DecomposeBackend(), cwd=tmp_path)

    results = await orchestrator.run_ready_tasks()
    tasks = await db.list_tasks()

    assert [result.task_id for result in results] == ["task-parent"]
    assert (await db.get_task("task-parent")).status == TaskStatus.DONE

    children = {task.title: task for task in tasks if task.parent_id == "task-parent"}
    assert set(children) == {"Create tmp note", "Verify tmp note"}

    build_task = children["Create tmp note"]
    verify_task = children["Verify tmp note"]
    assert build_task.task_type == TaskType.BUILD
    assert build_task.role == AgentRole.CELLO
    assert build_task.status == TaskStatus.READY
    assert build_task.dependencies == []
    assert verify_task.task_type == TaskType.TEST
    assert verify_task.role == AgentRole.CRITIC
    assert verify_task.status == TaskStatus.READY
    assert verify_task.dependencies == [build_task.id]
    await db.close()
