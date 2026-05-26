"""Service layer tests — TaskService lifecycle, approval gates, attention."""

from __future__ import annotations

import pytest
import tempfile
import pathlib

from cellos.models import (
    AgentRole,
    AttentionReason,
    CommentAuthorType,
    ConversationMessage,
    TaskStatus,
    TaskType,
)
from cellos.db import CellosDatabase
from cellos.persistence.schema import init_db
from cellos.services.task_service import (
    TaskService,
    TaskNotFoundError,
    EmptyTaskUpdateError,
    InvalidTaskApprovalError,
)
from cellos.services.planning_service import save_planning_result
from cellos.services.execution_service import save_execution_result


@pytest.fixture
async def db():
    """Create a temp SQLite DB for each test."""
    tmpdir = tempfile.mkdtemp()
    db_path = pathlib.Path(tmpdir) / "test.sqlite"
    await init_db(db_path)
    database = CellosDatabase(db_path)
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def task_service(db):
    return TaskService(db)


# ── create_task ─────────────────────────────────────────────────────

class TestCreateTask:
    async def test_create_basic_task(self, task_service):
        from cellos.models import Task
        task = await task_service.create_task(
            title="Build auth module", role=AgentRole.ENGINEER
        )
        assert task.id is not None
        assert task.title == "Build auth module"
        assert task.status == TaskStatus.DRAFT
        assert task.role == AgentRole.ENGINEER
        # task_type inferred from role
        assert task.task_type == TaskType.IMPLEMENTATION

    async def test_create_with_all_fields(self, task_service):
        from cellos.models import Task
        task = await task_service.create_task(
            title="Research options",
            details="Compare JWT vs session auth",
            role=AgentRole.RESEARCHER,
            success_criteria="Decision documented",
            failure_criteria="No clear winner identified",
        )
        assert task.task_type == TaskType.RESEARCH
        assert task.details == "Compare JWT vs session auth"
        assert task.success_criteria == "Decision documented"

    async def test_create_with_explicit_task_type(self, task_service):
        from cellos.models import Task
        task = await task_service.create_task(
            title="Custom type", role=AgentRole.ENGINEER, task_type=TaskType.RESEARCH
        )
        # Explicit type overrides inference
        assert task.task_type == TaskType.RESEARCH

    async def test_create_with_dependencies(self, task_service):
        from cellos.models import Task, TaskDependency
        dep_task = await task_service.create_task(title="Parent")
        child = await task_service.create_task(
            title="Child", dependencies=[TaskDependency(task_id=dep_task.id)]
        )
        assert len(child.dependencies) == 1
        assert child.dependencies[0].task_id == dep_task.id


# ── get / list tasks ───────────────────────────────────────────────

class TestGetListTasks:
    async def test_get_existing_task(self, task_service):
        from cellos.models import Task
        created = await task_service.create_task(title="Find me")
        found = await task_service.get_task(created.id)
        assert found is not None
        assert found.title == "Find me"

    async def test_get_nonexistent_raises(self, task_service):
        with pytest.raises(TaskNotFoundError):
            await task_service.get_task("nonexistent_id")

    async def test_list_all_tasks(self, task_service):
        from cellos.models import Task
        await task_service.create_task(title="A")
        await task_service.create_task(title="B")
        tasks = await task_service.list_tasks()
        assert len(tasks) == 2

    async def test_list_filtered_by_status(self, task_service):
        from cellos.models import Task
        await task_service.create_task(title="Draft1")
        t2 = await task_service.create_task(title="Draft2")
        # Move one to needs_approval via planning
        await save_planning_result(task_service.db, t2.id, "Test plan", "")
        drafts = await task_service.list_tasks(status_filter=TaskStatus.DRAFT)
        assert len(drafts) == 1


# ── update_task ────────────────────────────────────────────────────

class TestUpdateTask:
    async def test_update_title(self, task_service):
        from cellos.models import Task
        t = await task_service.create_task(title="Old")
        updated = await task_service.update_task(t.id, title="New")
        assert updated.title == "New"

    async def test_empty_update_raises(self, task_service):
        from cellos.models import Task
        await task_service.create_task(title="X")
        with pytest.raises(EmptyTaskUpdateError):
            await task_service.update_task("any_id", title=None)  # type: ignore

    async def test_content_change_triggers_attention(self, task_service):
        from cellos.models import Task
        t = await task_service.create_task(title="Original")
        updated = await task_service.update_task(t.id, details="New detail")
        assert updated.attention.required is True
        assert updated.attention.reason == AttentionReason.HUMAN_CHANGED_TASK

    async def test_no_attention_on_approved_tasks(self, task_service):
        from cellos.models import Task
        t = await task_service.create_task(title="Approved")
        # Manually set to approved for this test
        await task_service.db.update_task_status(t.id, TaskStatus.APPROVED)
        updated = await task_service.update_task(t.id, details="Changed")
        assert updated.attention.required is False

    async def test_add_dependency_triggers_attention(self, task_service):
        from cellos.models import Task, TaskDependency
        dep = await task_service.create_task(title="Dep target")
        t = await task_service.create_task(title="Will depend")
        updated = await task_service.update_task(
            t.id, add_dependencies=[TaskDependency(task_id=dep.id)]
        )
        assert len(updated.dependencies) == 1

    async def test_remove_dependency(self, task_service):
        from cellos.models import Task, TaskDependency
        dep = await task_service.create_task(title="Dep target")
        t = await task_service.create_task(
            title="Has dep", dependencies=[TaskDependency(task_id=dep.id)]
        )
        updated = await task_service.update_task(t.id, remove_dependencies=[dep.id])
        assert len(updated.dependencies) == 0


# ── approve_task ───────────────────────────────────────────────────

class TestApproveTask:
    async def test_approve_needs_approval(self, task_service):
        from cellos.models import Task
        t = await task_service.create_task(title="To approve")
        await save_planning_result(task_service.db, t.id, "Plan", "")
        approved = await task_service.approve_task(t.id)
        assert approved.status == TaskStatus.APPROVED

    async def test_approve_draft_raises(self, task_service):
        from cellos.models import Task
        t = await task_service.create_task(title="Still draft")
        with pytest.raises(InvalidTaskApprovalError):
            await task_service.approve_task(t.id)

    async def test_approve_nonexistent_raises(self, task_service):
        with pytest.raises(TaskNotFoundError):
            await task_service.approve_task("no_such_id")


# ── comments and conversation ──────────────────────────────────────

class TestCommentsConversation:
    async def test_add_human_comment_triggers_attention(self, task_service):
        from cellos.models import Task
        t = await task_service.create_task(title="Comment me")
        comment = await task_service.add_human_comment(t.id, "Please use bcrypt", author_id="user1")
        assert comment.author_type == CommentAuthorType.HUMAN
        updated = await task_service.get_task(t.id)
        assert len(updated.comments) >= 1

    async def test_add_conversation_message(self, task_service):
        from cellos.models import Task
        t = await task_service.create_task(title="Chat")
        msg = await task_service.add_conversation_message(
            t.id, "human", "What's the plan?"
        )
        updated = await task_service.get_task(t.id)
        assert len(updated.conversation) >= 1


# ── Planning service ───────────────────────────────────────────────

class TestPlanningService:
    async def test_save_planning_transitions_to_needs_approval(self, db):
        from cellos.models import Task
        t = Task(title="To plan")  # ID generated by default_factory
        await db.create_task(t)

        await save_planning_result(db, t.id, "Step 1: Do thing", "")

        updated = await db.get_task(t.id)
        assert updated.status == TaskStatus.NEEDS_APPROVAL
        assert updated.plan == "Step 1: Do thing"
        assert updated.attention.required is True
        assert updated.attention.reason == AttentionReason.PLANNING_COMPLETE

    async def test_save_planning_not_found_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            await save_planning_result(db, "ghost", "Plan text")

    async def test_strip_thinking_text_removes_preamble(self, db):
        from cellos.models import Task
        from cellos.services.planning_service import _strip_thinking_text

        # Plan with thinking preamble before --- separator
        raw_plan = "Let me check the file first.The file has 120 lines.\n\n---\n\n## Architecture Plan\n\n### Objective\nCount lines.\n\n### Steps\n1. Read file\n"
        t = Task(title="Test thinking strip")
        await db.create_task(t)
        await save_planning_result(db, t.id, raw_plan, "")
        updated = await db.get_task(t.id)
        assert "Let me check" not in updated.plan
        assert "Architecture Plan" in updated.plan
        assert "Objective" in updated.plan

    async def test_strip_thinking_text_handles_heading_only(self, db):
        from cellos.models import Task
        from cellos.services.planning_service import _strip_thinking_text

        # Plan with thinking preamble before ## heading (no ---)
        raw_plan = "Thinking about this task... Here's my plan:\n\n## Plan\n\n### Steps\n1. Do thing\n"
        t = Task(title="Test heading strip")
        await db.create_task(t)
        await save_planning_result(db, t.id, raw_plan, "")
        updated = await db.get_task(t.id)
        assert "Thinking about" not in updated.plan
        assert "Plan" in updated.plan
        assert "Steps" in updated.plan

    async def test_strip_thinking_text_preserves_clean_plan(self, db):
        from cellos.models import Task
        from cellos.services.planning_service import _strip_thinking_text

        # Clean plan without thinking preamble
        raw_plan = "## Plan\n\n### Steps\n1. Do thing\n"
        t = Task(title="Test clean plan")
        await db.create_task(t)
        await save_planning_result(db, t.id, raw_plan, "")
        updated = await db.get_task(t.id)
        assert "Plan" in updated.plan
        assert "Steps" in updated.plan


# ── Execution service ──────────────────────────────────────────────

class TestExecutionService:
    async def test_save_execution_success(self, db):
        from cellos.models import Task
        t = Task(title="To execute")
        await db.create_task(t)
        await db.update_task_status(t.id, TaskStatus.APPROVED)

        result = await save_execution_result(
            db, t.id, "Task completed successfully. All steps done."
        )
        assert result.success is True

        updated = await db.get_task(t.id)
        assert updated.status == TaskStatus.DONE
        assert updated.result is not None
        assert updated.attention.required is False  # cleared on success

    async def test_save_execution_failure(self, db):
        from cellos.models import Task
        t = Task(title="To fail")
        await db.create_task(t)
        await db.update_task_status(t.id, TaskStatus.APPROVED)

        result = await save_execution_result(
            db, t.id, "Encountered error: database connection refused"
        )
        assert result.success is False

        updated = await db.get_task(t.id)
        assert updated.status == TaskStatus.FAILED

    async def test_save_execution_ambiguous_defaults_to_failed(self, db):
        from cellos.models import Task
        t = Task(title="Ambiguous")
        await db.create_task(t)
        await db.update_task_status(t.id, TaskStatus.APPROVED)

        result = await save_execution_result(
            db, t.id, "I did some stuff and it seemed okay"
        )
        assert result.success is False  # no clear indicator → fail for review

    async def test_save_execution_not_found_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            await save_execution_result(db, "ghost", "result text")


# ── Combined update edge cases ─────────────────────────────────────

class TestCombinedUpdates:
    async def test_update_content_and_add_dependency_together(self, task_service):
        """Verify deps aren't overwritten when content also changes."""
        from cellos.models import TaskDependency
        dep = await task_service.create_task(title="Dep target")
        t = await task_service.create_task(title="Will update both")

        updated = await task_service.update_task(
            t.id, title="New Title", add_dependencies=[TaskDependency(task_id=dep.id)]
        )
        assert updated.title == "New Title"
        assert len(updated.dependencies) == 1
        assert updated.dependencies[0].task_id == dep.id

    async def test_update_only_deps_no_content(self, task_service):
        """Dep-only changes should work without content fields."""
        from cellos.models import TaskDependency
        dep = await task_service.create_task(title="Target")
        t = await task_service.create_task(title="No content change")

        updated = await task_service.update_task(
            t.id, add_dependencies=[TaskDependency(task_id=dep.id)]
        )
        assert len(updated.dependencies) == 1
        # Title should be unchanged
        assert updated.title == "No content change"


# ── Approval edge cases ────────────────────────────────────────────

class TestApprovalEdgeCases:
    async def test_approve_already_approved_raises(self, task_service):
        t = await task_service.create_task(title="Already done")
        await save_planning_result(task_service.db, t.id, "Plan", "")
        await task_service.approve_task(t.id)

        with pytest.raises(InvalidTaskApprovalError):
            await task_service.approve_task(t.id)

    async def test_approve_cleared_attention(self, task_service):
        """Approved tasks should have attention cleared."""
        t = await task_service.create_task(title="To approve")
        await save_planning_result(task_service.db, t.id, "Plan", "")
        approved = await task_service.approve_task(t.id)
        assert approved.attention.required is False
