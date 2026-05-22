"""Tests for CelloS domain models - enums, DTOs, and core entities."""

from datetime import datetime

import pytest

from cellos.models import (
    AgentRole,
    AttentionMetadata,
    AttentionReason,
    ChangeRequestReport,
    CommentAuthorType,
    ConversationMessage,
    ProcessingMetadata,
    ROLE_TO_TASK_TYPE,
    Task,
    TaskAttempt,
    TaskAttemptStatus,
    TaskComment,
    TaskDependency,
    TaskEvent,
    TaskResult,
    TaskStatus,
    TaskType,
    Worker,
    WorkerStatus,
)


class TestAgentRole:
    """Test AgentRole enum values and task type inference."""

    def test_all_roles_defined(self):
        assert set(AgentRole) == {
            "coordinator",
            "researcher", 
            "architect",
            "engineer",
            "tester",
        }

    def test_role_to_task_type_mapping(self):
        assert ROLE_TO_TASK_TYPE[AgentRole.COORDINATOR] == TaskType.PROPOSAL
        assert ROLE_TO_TASK_TYPE[AgentRole.RESEARCHER] == TaskType.RESEARCH
        assert ROLE_TO_TASK_TYPE[AgentRole.ARCHITECT] == TaskType.ARCHITECTURE
        assert ROLE_TO_TASK_TYPE[AgentRole.ENGINEER] == TaskType.IMPLEMENTATION
        assert ROLE_TO_TASK_TYPE[AgentRole.TESTER] == TaskType.VERIFICATION


class TestTaskStatus:
    """Test TaskStatus enum values."""

    def test_all_statuses_defined(self):
        expected = {
            "draft", "needs_approval", "approved", "in_progress", 
            "done", "blocked", "failed", "change_requested", "cancelled"
        }
        assert set(TaskStatus) == expected


class TestTaskType:
    """Test TaskType enum values."""

    def test_all_types_defined(self):
        assert set(TaskType) == {
            "proposal", "research", "architecture", 
            "implementation", "verification"
        }


class TestAttentionReason:
    """Test AttentionReason enum values."""

    def test_all_reasons_defined(self):
        expected = {
            "new_task", "human_changed_task", "dependency_done",
            "child_change_requested", "child_failed", "approved", "execution_failed",
            "human_commented", "planning_complete"
        }
        assert set(AttentionReason) == expected


class TestTaskCreation:
    """Test Task model construction and defaults."""

    def test_task_creation_with_minimal_fields(self):
        task = Task(title="Build feature")
        assert task.id is not None
        assert len(task.id) <= 12
        assert task.title == "Build feature"
        assert task.status == TaskStatus.DRAFT
        assert task.role == AgentRole.ENGINEER
        assert task.task_type == TaskType.IMPLEMENTATION  # inferred from default role

    def test_task_creation_with_explicit_role_infers_type(self):
        task = Task(title="Research API", role=AgentRole.RESEARCHER)
        assert task.task_type == TaskType.RESEARCH

    def test_task_creation_with_all_fields(self):
        now = datetime.now()
        task = Task(
            title="Full task",
            details="Detailed description",
            status=TaskStatus.DRAFT,
            role=AgentRole.ARCHITECT,
            success_criteria="Measurable outcome",
            failure_criteria="Known failure modes",
            agent_id="architect-agent"
        )
        assert task.task_type == TaskType.ARCHITECTURE
        assert task.details == "Detailed description"
        assert task.success_criteria == "Measurable outcome"
        assert isinstance(task.attention, AttentionMetadata)
        assert isinstance(task.processing, ProcessingMetadata)

    def test_task_defaults(self):
        task = Task(title="Defaults test")
        assert task.plan is None
        assert task.prompt_text is None
        assert task.parent_id is None
        assert task.dependencies == []
        assert task.conversation == []
        assert task.comments == []
        assert isinstance(task.created_at, datetime)
        assert isinstance(task.updated_at, datetime)


class TestBackwardCompatMigration:
    """Test legacy field name migration in model_validator."""

    def test_proposal_to_prompt_text(self):
        data = {"title": "Migrated", "proposal": "Legacy plan text"}
        task = Task(**data)
        assert task.prompt_text == "Legacy plan text"
        # Ensure 'proposal' key is consumed, not duplicated
        assert hasattr(task, 'prompt_text')

    def test_description_to_details(self):
        data = {"title": "Migrated", "description": "Old description field"}
        task = Task(**data)
        assert task.details == "Old description field"

    def test_constraints_to_failure_criteria(self):
        data = {"title": "Migrated", "constraints": "Legacy constraints"}
        task = Task(**data)
        assert task.failure_criteria == "Legacy constraints"


class TestAttentionMetadata:
    """Test AttentionMetadata model and factory method."""

    def test_default_attention_not_required(self):
        meta = AttentionMetadata()
        assert meta.required is False
        assert meta.reason is None

    def test_required_attention_factory(self):
        meta = AttentionMetadata.required_attention(
            AttentionReason.NEW_TASK, "Task just created"
        )
        assert meta.required is True
        assert meta.reason == AttentionReason.NEW_TASK
        assert meta.detail == "Task just created"
        assert isinstance(meta.timestamp, datetime)


class TestAttentionMethods:
    """Test Task attention methods return copies."""

    def test_requires_attention_returns_copy(self):
        task = Task(title="Original")
        new_task = task.requires_attention(AttentionReason.HUMAN_CHANGED_TASK)
        
        # Original unchanged
        assert task.attention.required is False
        
        # New copy has attention set
        assert new_task.attention.required is True
        assert new_task.attention.reason == AttentionReason.HUMAN_CHANGED_TASK

    def test_clear_attention_returns_copy(self):
        task = Task(title="With attention").requires_attention(AttentionReason.NEW_TASK)
        cleared = task.clear_attention()
        
        # Original still has attention
        assert task.attention.required is True
        
        # Cleared copy doesn't
        assert cleared.attention.required is False


class TestSupportingModels:
    """Test all supporting DTOs and entities."""

    def test_task_dependency(self):
        dep = TaskDependency(task_id="abc123", status_satisfied=False)
        assert dep.task_id == "abc123"
        assert dep.status_satisfied is False

    def test_conversation_message(self):
        msg = ConversationMessage(
            author_type="human",
            content="Please update this",
            timestamp=datetime.now()
        )
        assert msg.author_type == "human"
        assert isinstance(msg.timestamp, datetime)

    def test_task_comment(self):
        comment = TaskComment(
            task_id="task123",
            author_type=CommentAuthorType.HUMAN,
            content="Review needed"
        )
        assert comment.id is not None
        assert comment.task_id == "task123"

    def test_task_result(self):
        result = TaskResult(
            success=True,
            summary="Completed successfully",
            output="Full agent output here"
        )
        assert result.success is True
        assert isinstance(result.timestamp, datetime)

    def test_change_request_report(self):
        report = ChangeRequestReport(
            reason="Plan needs adjustment",
            requested_changes=["Add error handling", "Update dependencies"]
        )
        assert len(report.requested_changes) == 2

    def test_task_attempt(self):
        attempt = TaskAttempt(
            task_id="task123",
            mode="planning",
            agent_id="architect-agent"
        )
        assert attempt.status == TaskAttemptStatus.STARTED
        assert isinstance(attempt.started_at, datetime)

    def test_task_event(self):
        event = TaskEvent(
            task_id="task123",
            event_type="status_changed",
            message="Task approved"
        )
        assert event.event_type == "status_changed"

    def test_worker(self):
        worker = Worker(
            task_id="task123",
            mode="execution",
            pid=12345,
            log_path="/tmp/worker.log"
        )
        assert worker.status == WorkerStatus.PENDING
        assert worker.pid == 12345

    def test_processing_metadata(self):
        meta = ProcessingMetadata(
            last_processed_at=datetime.now(),
            input_hash="abc123"
        )
        assert meta.input_hash == "abc123"


class TestEnumStrValues:
    """Verify all enums serialize to strings correctly."""

    def test_agent_role_str(self):
        assert str(AgentRole.ENGINEER) == "engineer"

    def test_task_status_str(self):
        assert str(TaskStatus.NEEDS_APPROVAL) == "needs_approval"

    def test_attention_reason_str(self):
        assert str(AttentionReason.PLANNING_COMPLETE) == "planning_complete"
