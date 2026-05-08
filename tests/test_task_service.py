import pytest

from cellos.db import CellosDatabase
from cellos.domain.attention import AttentionReason
from cellos.domain.enums import AgentRole, TaskStatus
from cellos.domain.tasks import Task
from cellos.services.task_service import EmptyTaskUpdateError, TaskService


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_task_service_create_update_comment_and_approve(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()
    service = TaskService(db)
    task = Task(id="task-1", title="Original", role=AgentRole.ENGINEER)

    created = await service.create_task(task)
    updated = await service.update_task("task-1", prompt="New plan", status=TaskStatus.NEEDS_APPROVAL)
    await service.add_human_comment("task-1", "Please revise", "james")
    commented = await db.get_task("task-1")
    approved = await service.approve_task("task-1")
    comments = await db.list_task_comments("task-1")
    events = await db.list_task_events(task_id="task-1")

    assert created.id == "task-1"
    assert updated.prompt == "New plan"
    assert updated.attention.required is True
    assert updated.attention.reason == AttentionReason.HUMAN_CHANGED_TASK
    assert commented.attention.reason == AttentionReason.HUMAN_COMMENTED
    assert comments[0]["message"] == "Please revise"
    assert approved.status == TaskStatus.APPROVED
    assert approved.attention.required is False
    assert [event["event_type"] for event in events] == ["created", "updated", "comment_added", "approved"]
    await db.close()


@pytest.mark.anyio
async def test_task_service_rejects_empty_update(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()
    service = TaskService(db)
    await service.create_task(Task(id="task-1", title="Original", role=AgentRole.ENGINEER))

    with pytest.raises(EmptyTaskUpdateError):
        await service.update_task("task-1")

    await db.close()


@pytest.mark.anyio
async def test_task_service_updates_dependencies(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()
    service = TaskService(db)
    await service.create_task(Task(id="task-1", title="Original", role=AgentRole.ENGINEER))
    await service.create_task(Task(id="dep-1", title="Dependency 1", role=AgentRole.TESTER))
    await service.create_task(Task(id="dep-2", title="Dependency 2", role=AgentRole.TESTER))

    updated = await service.update_task("task-1", add_dependencies=("dep-1", "dep-2"), remove_dependencies=("dep-1",))

    assert updated.dependencies == ["dep-2"]
    assert updated.attention.reason == AttentionReason.HUMAN_CHANGED_TASK
    await db.close()


@pytest.mark.anyio
async def test_task_service_sets_agent_id(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()
    service = TaskService(db)
    await service.create_task(Task(id="task-1", title="Original", role=AgentRole.ENGINEER))

    updated = await service.update_task("task-1", agent_id="qwen")

    assert updated.agent_id == "qwen"
    await db.close()


@pytest.mark.anyio
async def test_task_service_clears_agent_id(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()
    service = TaskService(db)
    task = Task(id="task-1", title="Original", role=AgentRole.ENGINEER, agent_id="qwen")
    await service.create_task(task)

    updated = await service.update_task("task-1", clear_agent=True)

    assert updated.agent_id is None
    await db.close()


@pytest.mark.anyio
async def test_task_service_agent_only_update_not_empty(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()
    service = TaskService(db)
    await service.create_task(Task(id="task-1", title="Original", role=AgentRole.ENGINEER))

    updated = await service.update_task("task-1", agent_id="qwen")

    assert updated.agent_id == "qwen"
    await db.close()


@pytest.mark.anyio
async def test_task_service_clear_agent_not_empty(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()
    service = TaskService(db)
    task = Task(id="task-1", title="Original", role=AgentRole.ENGINEER, agent_id="qwen")
    await service.create_task(task)

    updated = await service.update_task("task-1", clear_agent=True)

    assert updated.agent_id is None
    await db.close()


@pytest.mark.anyio
async def test_task_service_add_conversation_message(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()
    service = TaskService(db)
    await service.create_task(Task(id="task-1", title="Original", role=AgentRole.ENGINEER))

    await service.add_conversation_message("task-1", "human: I want to focus on X")
    task = await db.get_task("task-1")

    assert len(task.conversation) == 1
    assert task.conversation[0].author == "human"
    assert task.conversation[0].message == "I want to focus on X"
    assert task.conversation[0].id is not None
    await db.close()


@pytest.mark.anyio
async def test_task_service_add_system_conversation_message(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()
    service = TaskService(db)
    await service.create_task(Task(id="task-1", title="Original", role=AgentRole.ENGINEER))

    await service.add_conversation_message("task-1", "system: Plan revised")
    task = await db.get_task("task-1")

    assert len(task.conversation) == 1
    assert task.conversation[0].author == "system"
    assert task.conversation[0].message == "Plan revised"
    await db.close()


@pytest.mark.anyio
async def test_task_service_conversation_rejects_invalid_author(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()
    service = TaskService(db)
    await service.create_task(Task(id="task-1", title="Original", role=AgentRole.ENGINEER))

    with pytest.raises(ValueError, match="Invalid author"):
        await service.add_conversation_message("task-1", "unknown: message")

    await db.close()


@pytest.mark.anyio
async def test_task_service_conversation_rejects_missing_prefix(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()
    service = TaskService(db)
    await service.create_task(Task(id="task-1", title="Original", role=AgentRole.ENGINEER))

    with pytest.raises(ValueError, match="author prefix"):
        await service.add_conversation_message("task-1", "no prefix here")

    await db.close()


@pytest.mark.anyio
async def test_task_service_conversation_appends_multiple_messages(tmp_path):
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()
    service = TaskService(db)
    await service.create_task(Task(id="task-1", title="Original", role=AgentRole.ENGINEER))

    await service.add_conversation_message("task-1", "human: First message")
    await service.add_conversation_message("task-1", "system: System response")
    await service.add_conversation_message("task-1", "human: Second message")
    task = await db.get_task("task-1")

    assert len(task.conversation) == 3
    assert task.conversation[0].message == "First message"
    assert task.conversation[1].message == "System response"
    assert task.conversation[2].message == "Second message"
    # Verify unique IDs
    ids = [m.id for m in task.conversation]
    assert len(set(ids)) == 3
    await db.close()
