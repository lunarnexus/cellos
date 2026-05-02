import pytest

from cellos.db import CellosDatabase, DatabaseNotInitialized
from cellos.models import (
    AgentRole,
    AttentionReason,
    ChangeRequestReport,
    Task,
    TaskResult,
    TaskStatus,
    TaskType,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_database_creates_and_gets_task(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()

    task = Task(
        id="task-1",
        title="Draft proposal",
        role=AgentRole.COORDINATOR,
        task_type=TaskType.PROPOSAL,
    )
    await db.create_task(task)

    saved = await db.get_task("task-1")

    assert saved == task
    await db.close()


@pytest.mark.anyio
async def test_database_sanity_check_requires_init(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()

    with pytest.raises(DatabaseNotInitialized, match="Run `cellos init` first"):
        await db.ensure_initialized()

    await db.close()


@pytest.mark.anyio
async def test_database_lists_tasks_requiring_attention(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()

    quiet = Task(id="task-quiet", title="Quiet", role=AgentRole.ENGINEER)
    needs_attention = Task(
        id="task-attention",
        title="Needs attention",
        role=AgentRole.ARCHITECT,
    ).requires_attention(AttentionReason.HUMAN_COMMENTED, "Human asked for changes")

    await db.create_task(quiet)
    await db.create_task(needs_attention)

    tasks = await db.list_tasks_requiring_attention()

    assert [task.id for task in tasks] == ["task-attention"]
    assert tasks[0].attention.reason == AttentionReason.HUMAN_COMMENTED
    await db.close()


@pytest.mark.anyio
async def test_database_lists_only_approved_unblocked_tasks(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()

    dependency = Task(
        id="task-dep",
        title="Dependency",
        role=AgentRole.TESTER,
        status=TaskStatus.APPROVED,
    )
    ready = Task(
        id="task-ready",
        title="Ready",
        role=AgentRole.ENGINEER,
        status=TaskStatus.APPROVED,
    )
    blocked = Task(
        id="task-blocked",
        title="Blocked",
        role=AgentRole.ENGINEER,
        status=TaskStatus.APPROVED,
        dependencies=["task-dep"],
    )

    await db.create_task(dependency)
    await db.create_task(ready)
    await db.create_task(blocked)

    tasks = await db.list_approved_unblocked_tasks()
    assert [task.id for task in tasks] == ["task-dep", "task-ready"]

    await db.update_task_status("task-dep", TaskStatus.DONE)
    tasks = await db.list_approved_unblocked_tasks()
    assert [task.id for task in tasks] == ["task-ready", "task-blocked"]
    await db.close()


@pytest.mark.anyio
async def test_database_save_task_result_updates_status(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()

    task = Task(
        id="task-1",
        title="Build",
        role=AgentRole.ENGINEER,
        status=TaskStatus.APPROVED,
    )
    await db.create_task(task)
    await db.save_task_result(TaskResult(task_id="task-1", success=True, summary="done"))

    saved = await db.get_task("task-1")

    assert saved.status == TaskStatus.DONE
    assert saved.result.summary == "done"
    await db.close()


@pytest.mark.anyio
async def test_database_save_change_request_updates_status(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()

    task = Task(
        id="task-1",
        title="Build",
        role=AgentRole.ENGINEER,
        status=TaskStatus.APPROVED,
    )
    report = ChangeRequestReport(
        blocker_summary="Missing API details",
        why_current_task_cannot_be_completed="The approved scope does not define the endpoint.",
    )
    await db.create_task(task)
    await db.save_task_result(
        TaskResult(
            task_id="task-1",
            success=False,
            summary="Change requested",
            change_request=report,
        )
    )

    saved = await db.get_task("task-1")

    assert saved.status == TaskStatus.CHANGE_REQUESTED
    assert saved.result.change_request.blocker_summary == "Missing API details"
    await db.close()


@pytest.mark.anyio
async def test_database_lists_task_events(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()

    task = Task(id="task-1", title="Build", role=AgentRole.ENGINEER)
    await db.create_task(task)
    await db.update_task_status("task-1", TaskStatus.APPROVED)

    events = await db.list_task_events("task-1")

    assert [event["event_type"] for event in events] == ["created", "status_changed"]
    assert events[0]["message"] == "Task created"
    await db.close()
