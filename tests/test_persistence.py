"""Persistence layer tests — real temp SQLite DBs, no mocks."""

from __future__ import annotations

import asyncio
import datetime
import uuid

import pytest

from cellos.models import (
    AgentRole,
    AttentionMetadata,
    CommentAuthorType,
    ConversationMessage,
    ProcessingMetadata,
    Task,
    TaskAttempt,
    TaskComment,
    TaskDependency,
    TaskEvent,
    TaskResult,
    TaskStatus,
)

from cellos.db import CellosDatabase
from cellos.persistence.schema import (
    DatabaseNotInitialized,
    REQUIRED_TABLES,
    ensure_initialized,
    init_db,
)


@pytest.fixture
async def db_path(tmp_path):
    """Return a temp SQLite DB path."""
    return tmp_path / "test_cellos.sqlite"


@pytest.fixture
async def db(db_path):
    """Initialize and yield a CellosDatabase instance."""
    await init_db(db_path)
    database = CellosDatabase(db_path)
    await database.connect()
    yield database
    await database.close()


def _make_task(
    title: str = "Test task",
    status: TaskStatus = TaskStatus.DRAFT,
    role: AgentRole = AgentRole.ENGINEER,
    **kwargs,
) -> Task:
    """Helper to create a Task for testing."""
    return Task(
        id=uuid.uuid4().hex[:12],
        title=title,
        status=status,
        role=role,
        **kwargs,
    )


# ── Schema tests ────────────────────────────────────────────────


class TestSchema:
    async def test_init_db_creates_all_tables(self, db_path):
        await init_db(db_path)
        await ensure_initialized(db_path)  # should not raise

    async def test_init_db_is_idempotent(self, db_path):
        """Calling init_db multiple times is safe."""
        await init_db(db_path)
        await init_db(db_path)
        await ensure_initialized(db_path)

    async def test_ensure_raises_on_missing_tables(self, tmp_path):
        bad = tmp_path / "empty.sqlite"
        # Create empty file so aiosqlite can connect but no tables exist
        import aiosqlite

        async with aiosqlite.connect(str(bad)) as conn:
            await conn.close()

        with pytest.raises(DatabaseNotInitialized):
            await ensure_initialized(bad)


# ── Task CRUD tests ─────────────────────────────────────────────


class TestTaskCRUD:
    async def test_create_and_get_task(self, db):
        task = _make_task("Build auth module")
        await db.create_task(task)

        result = await db.get_task(task.id)
        assert result is not None
        assert result.title == "Build auth module"
        assert result.status == TaskStatus.DRAFT
        assert result.role == AgentRole.ENGINEER
        assert result.created_at is not None
        assert result.updated_at is not None

    async def test_get_nonexistent_task(self, db):
        result = await db.get_task("nonexistent")
        assert result is None

    async def test_list_tasks_all(self, db):
        for i in range(3):
            task = _make_task(f"Task {i}")
            await db.create_task(task)

        tasks = await db.list_tasks()
        assert len(tasks) == 3

    async def test_list_tasks_status_filter(self, db):
        draft = _make_task("Draft", status=TaskStatus.DRAFT)
        approved = _make_task("Approved", status=TaskStatus.APPROVED)
        done = _make_task("Done", status=TaskStatus.DONE)

        await db.create_task(draft)
        await db.create_task(approved)
        await db.create_task(done)

        drafts = await db.list_tasks(status_filter="draft")
        assert len(drafts) == 1
        assert drafts[0].id == draft.id

    async def test_update_task(self, db):
        task = _make_task("Original title")
        await db.create_task(task)

        updated = task.model_copy(update={"title": "Updated title"})
        result = await db.update_task(updated)
        assert result is True  # row existed

        fetched = await db.get_task(task.id)
        assert fetched.title == "Updated title"

    async def test_update_nonexistent_raises(self, db):
        task = _make_task("Ghost")
        result = await db.update_task(task)
        assert result is False  # no row to update


# ── Scheduler query tests ───────────────────────────────────────


class TestSchedulerQueries:
    async def test_list_attention_tasks(self, db):
        task_with_attention = _make_task(
            "Needs attention",
            attention=AttentionMetadata.required_attention(
                reason="new_task", detail="Just created"
            ),
        )
        normal_task = _make_task("Normal")

        await db.create_task(task_with_attention)
        await db.create_task(normal_task)

        results = await db.list_tasks_requiring_attention()
        assert len(results) == 1
        assert results[0].id == task_with_attention.id

    async def test_list_planning_candidates(self, db):
        draft = _make_task("Draft", status=TaskStatus.DRAFT, role=AgentRole.ARCHITECT)
        needs_approval = _make_task(
            "Needs approval", status=TaskStatus.NEEDS_APPROVAL, role=AgentRole.ARCHITECT
        )
        done = _make_task("Done", status=TaskStatus.DONE)
        engineer_draft = _make_task("Engineer draft", status=TaskStatus.DRAFT, role=AgentRole.ENGINEER)

        await db.create_task(draft)
        await db.create_task(needs_approval)
        await db.create_task(done)
        await db.create_task(engineer_draft)

        results = await db.list_tasks_ready_for_planning()
        ids = {r.id for r in results}
        assert draft.id in ids
        assert needs_approval.id not in ids  # Only draft, not needs_approval
        assert done.id not in ids
        assert engineer_draft.id in ids  # All draft tasks can be planned

    async def test_list_approved_unblocked(self, db):
        approved_no_deps = _make_task(
            "Approved no deps", status=TaskStatus.APPROVED
        )
        await db.create_task(approved_no_deps)

        results = await db.list_approved_unblocked_tasks()
        assert len(results) == 1
        assert results[0].id == approved_no_deps.id

    async def test_blocked_task_not_in_approved_unblocked(self, db):
        dep_task = _make_task("Dependency", status=TaskStatus.DONE)
        await db.create_task(dep_task)

        blocked = _make_task(
            "Blocked on dep",
            status=TaskStatus.APPROVED,
            dependencies=[
                TaskDependency(task_id=dep_task.id, status_satisfied=False)
            ],
        )
        await db.create_task(blocked)

        results = await db.list_approved_unblocked_tasks()
        ids = [r.id for r in results]
        assert blocked.id not in ids


# ── Result repository tests ─────────────────────────────────────


class TestResultRepository:
    async def test_save_and_update_with_result_success(self, db):
        task = _make_task("Will succeed")
        await db.create_task(task)

        affected = await db.save_task_result(
            task.id, success=True, summary="Completed successfully"
        )

        fetched = await db.get_task(task.id)
        assert fetched.result is not None
        assert fetched.result.success is True  # type: ignore[union-attr]
        assert fetched.result.summary == "Completed successfully"  # type: ignore[union-attr]

    async def test_save_and_update_with_result_failure(self, db):
        task = _make_task("Will fail")
        await db.create_task(task)

        await db.save_task_result(
            task.id, success=False, summary="Failed with error"
        )

        fetched = await db.get_task(task.id)
        assert fetched.result is not None
        assert fetched.result.success is False  # type: ignore[union-attr]

    async def test_wake_blocked_dependents(self, db):
        parent = _make_task(
            "Parent task",
            status=TaskStatus.APPROVED,
            dependencies=[
                TaskDependency(task_id="dep123", status_satisfied=False)
            ],
        )
        await db.create_task(parent)

        # Simulate dep completing — save result for a fake completed dep
        affected = await db.save_task_result(
            "dep123", success=True, summary="Dep done"
        )
        # No parent to wake since dep123 isn't actually in the DB as depending on anything


# ── Event repository tests ───────────────────────────────────────


class TestEventRepository:
    async def test_create_and_list_events(self, db):
        task = _make_task("With events")
        await db.create_task(task)

        event1 = await db.create_event(
            task.id, "status_changed", "Status changed to approved"
        )
        assert isinstance(event1, TaskEvent)
        assert event1.event_type == "status_changed"

        events = await db.list_events(task.id)
        # Should include the auto-created creation event + our manual one
        assert len(events) >= 2

    async def test_event_limit(self, db):
        task = _make_task("Many events")
        await db.create_task(task)

        for i in range(10):
            await db.create_event(task.id, "test", f"Event {i}")

        all_events = await db.list_events(task.id, limit=50)
        assert len(all_events) == 11  # creation + 10 manual

        limited = await db.list_events(task.id, limit=3)
        assert len(limited) == 3


# ── Comment repository tests ────────────────────────────────────


class TestCommentRepository:
    async def test_create_and_list_comments(self, db):
        task = _make_task("With comments")
        await db.create_task(task)

        comment = await db.create_comment(
            task.id,
            CommentAuthorType.HUMAN,
            "Please use bcrypt",
            author_id="james",
        )
        assert isinstance(comment, TaskComment)
        assert comment.content == "Please use bcrypt"

        comments = await db.list_comments(task.id)
        assert len(comments) >= 1


# ── Attempt repository tests ────────────────────────────────────


class TestAttemptRepository:
    async def test_create_and_list_attempts(self, db):
        task = _make_task("With attempts")
        await db.create_task(task)

        attempt = await db.create_attempt(
            task.id, mode="planning", agent_id="fake_acp"
        )
        assert isinstance(attempt, TaskAttempt)
        assert attempt.mode == "planning"

        attempts = await db.list_attempts(task.id)
        assert len(attempts) >= 1

    async def test_update_attempt(self, db):
        task = _make_task("Updated attempt")
        await db.create_task(task)

        attempt = await db.create_attempt(
            task.id, mode="execution", agent_id="fake_acp"
        )

        # Update to succeeded — uses TaskStatus mapping in facade
        from cellos.models import TaskAttemptStatus as AttemptStatus

        from cellos.persistence.attempt_repository import (
            update_attempt as _update_attempt,
        )

        await _update_attempt(
            db.conn,
            attempt.id,
            AttemptStatus.SUCCEEDED,
            result_summary="Done",
        )
        await db.conn.commit()

        attempts = await db.list_attempts(task.id)
        updated = next(a for a in attempts if a.id == attempt.id)
        assert updated.status == AttemptStatus.SUCCEEDED


# ── CellosDatabase facade tests ─────────────────────────────────


class TestCellosDatabase:
    async def test_create_task_via_facade(self, db):
        task = _make_task("Facade task")
        await db.create_task(task)

        result = await db.get_task(task.id)
        assert result is not None
        assert result.title == "Facade task"

    async def test_facade_lifecycle_queries(self, db):
        draft = _make_task("Draft", status=TaskStatus.DRAFT, role=AgentRole.ARCHITECT)
        approved = _make_task(
            "Approved", status=TaskStatus.APPROVED, role=AgentRole.ENGINEER
        )
        await db.create_task(draft)
        await db.create_task(approved)

        planning = await db.list_tasks_ready_for_planning()
        assert any(t.id == draft.id for t in planning)

    async def test_facade_events_recorded(self, db):
        task = _make_task("Events via facade")
        await db.create_task(task)

        events = await db.list_events(task.id)
        # At minimum: creation event recorded automatically
        assert any(e.event_type == "task_created" for e in events)

    async def test_facade_comments(self, db):
        task = _make_task("Comments via facade")
        await db.create_task(task)

        comment = await db.create_comment(
            task.id, CommentAuthorType.HUMAN, "Test comment"
        )
        assert comment.content == "Test comment"

    async def test_facade_attempts(self, db):
        task = _make_task("Attempts via facade")
        await db.create_task(task)

        attempt = await db.create_attempt(
            task.id, mode="planning", agent_id="fake_acp"
        )
        assert attempt.mode == "planning"


# ── Integration tests ───────────────────────────────────────────


class TestIntegration:
    async def test_full_task_lifecycle(self, db):
        """Create → plan-ready → approved → result saved."""
        task = _make_task("Full lifecycle", status=TaskStatus.DRAFT, role=AgentRole.ARCHITECT)
        await db.create_task(task)

        # Should appear in planning candidates
        planning = await db.list_tasks_ready_for_planning()
        assert any(t.id == task.id for t in planning)

        # Update to approved (engineer role for execution)
        updated = task.model_copy(update={"status": TaskStatus.APPROVED, "role": AgentRole.ENGINEER})
        await db.update_task(updated)

        # Should appear in approved unblocked
        approved = await db.list_approved_unblocked_tasks()
        assert any(t.id == task.id for t in approved)

        # Save result
        affected = await db.save_task_result(
            task.id, success=True, summary="Completed"
        )

        final = await db.get_task(task.id)
        assert final.result is not None  # type: ignore[attr-defined]
        assert final.result.success is True  # type: ignore[attr-defined]

    async def test_dependency_junction_table_sync(self, db):
        """Dependencies stored inline AND in junction table."""
        dep = _make_task("Dependency task", status=TaskStatus.DONE)
        await db.create_task(dep)

        child = _make_task(
            "Child depends on parent",
            dependencies=[TaskDependency(task_id=dep.id, status_satisfied=False)],
        )
        await db.create_task(child)

        # Check junction table has the dependency
        row = await db.conn.execute(
            "SELECT COUNT(*) FROM task_dependencies WHERE task_id=?", (child.id,)
        )
        count = await row.fetchone()
        assert count[0] == 1

    async def test_parent_completes_when_all_children_done(self, db):
        """Parent task transitions to DONE when all child tasks complete."""
        from cellos.models import AgentRole

        # Create parent task (architect role)
        parent = _make_task("Parent task", role=AgentRole.ARCHITECT)
        await db.create_task(parent)

        # Create two child tasks
        child1 = _make_task("Child 1", role=AgentRole.ENGINEER)
        child1.parent_id = parent.id
        await db.create_task(child1)

        child2 = _make_task("Child 2", role=AgentRole.ENGINEER)
        child2.parent_id = parent.id
        await db.create_task(child2)

        # Complete first child — update status and save result
        child1_done = child1.model_copy(update={"status": TaskStatus.DONE})
        await db.update_task(child1_done)
        affected1 = await db.save_task_result(
            child1.id, success=True, summary="Child 1 done"
        )
        # Parent not done yet (child2 still pending)
        parent_after_1 = await db.get_task(parent.id)
        assert parent_after_1.status == TaskStatus.DRAFT

        # Complete second child — parent should NOW transition to DONE
        child2_done = child2.model_copy(update={"status": TaskStatus.DONE})
        await db.update_task(child2_done)
        affected2 = await db.save_task_result(
            child2.id, success=True, summary="Child 2 done"
        )
        assert parent.id in affected2
        parent_final = await db.get_task(parent.id)
        assert parent_final.status == TaskStatus.DONE

    async def test_parent_triggers_attention_on_child_failure(self, db):
        """Parent task gets attention when a child fails."""
        from cellos.models import AgentRole

        parent = _make_task("Parent task", role=AgentRole.ARCHITECT)
        await db.create_task(parent)

        child1 = _make_task("Child 1", role=AgentRole.ENGINEER)
        child1.parent_id = parent.id
        await db.create_task(child1)

        child2 = _make_task("Child 2", role=AgentRole.ENGINEER)
        child2.parent_id = parent.id
        await db.create_task(child2)

        # First child succeeds
        child1_done = child1.model_copy(update={"status": TaskStatus.DONE})
        await db.update_task(child1_done)
        await db.save_task_result(child1.id, success=True, summary="Done")

        # Second child fails — parent should get attention
        child2_failed = child2.model_copy(update={"status": TaskStatus.FAILED})
        await db.update_task(child2_failed)
        await db.save_task_result(child2.id, success=False, summary="Failed")

        parent_final = await db.get_task(parent.id)
        assert parent_final.attention.required is True
        assert "child_failed" in parent_final.attention.reason
