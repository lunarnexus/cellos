from cellos.domain.attempts import TaskAttempt, TaskAttemptStatus
from cellos.domain.attention import AttentionMetadata, ProcessingMetadata
from cellos.domain.comments import TaskComment
from cellos.domain.enums import (
    AgentRole,
    AttentionReason,
    CommentAuthorType,
    TaskAttemptStatus,
    TaskStatus,
    TaskType,
    WorkerStatus,
)
from cellos.domain.results import ChangeRequestReport, TaskResult
from cellos.domain.tasks import Task, TaskDependency
from cellos.domain.time import utc_now
from cellos.domain.workers import Worker


def test_task_defaults_match_canonical_lifecycle():
    task = Task(id="task-1", title="Draft plan", role=AgentRole.COORDINATOR)

    assert task.status == TaskStatus.DRAFT
    assert task.task_type == TaskType.PROPOSAL
    assert task.attention.required is False
    assert task.dependencies == []


def test_task_migrates_legacy_proposal_field_to_prompt():
    task = Task.model_validate(
        {
            "id": "task-1",
            "title": "Build",
            "role": "engineer",
            "proposal": "Do the approved work.",
        }
    )

    assert task.prompt == "Do the approved work."
    assert "proposal" not in task.model_dump()


def test_task_attention_helpers_are_immutable_updates():
    task = Task(id="task-1", title="Draft plan", role=AgentRole.COORDINATOR)

    updated = task.requires_attention(AttentionReason.HUMAN_COMMENTED, "Human added a revision comment")
    cleared = updated.clear_attention()

    assert task.attention.required is False
    assert updated.attention.required is True
    assert updated.attention.reason == AttentionReason.HUMAN_COMMENTED
    assert updated.attention.detail == "Human added a revision comment"
    assert updated.attention.since is not None
    assert cleared.attention.required is False
    assert cleared.attention.reason is None


def test_change_request_result_records_structured_report():
    report = ChangeRequestReport(
        blocker_summary="API contract is missing",
        why_current_task_cannot_be_completed="The approved task requires an endpoint that is not defined.",
        evidence="No route or schema exists in the approved proposal.",
        recommended_next_action="Ask Architect to revise the plan.",
        human_approval_needed=True,
    )
    result = TaskResult(
        task_id="task-1",
        success=False,
        summary="Change requested",
        change_request=report,
    )

    assert result.change_request == report
    assert result.change_request.human_approval_needed is True


def test_models_compatibility_exports():
    """Verify cellos.models shim still exports all symbols."""
    from cellos.models import (
        AgentRole,
        AttentionMetadata,
        AttentionReason,
        ChangeRequestReport,
        CommentAuthorType,
        ProcessingMetadata,
        Task,
        TaskAttempt,
        TaskAttemptStatus,
        TaskComment,
        TaskDependency,
        TaskResult,
        TaskStatus,
        TaskType,
        Worker,
        WorkerStatus,
        utc_now,
    )

    assert Task is not None
    assert TaskStatus.APPROVED == "approved"
    assert AgentRole.ENGINEER == "engineer"
    assert utc_now() is not None
    assert TaskAttempt is not None
    assert TaskComment is not None
    assert ChangeRequestReport is not None
    assert TaskResult is not None
    assert Worker is not None
    assert AttentionMetadata is not None
    assert ProcessingMetadata is not None
    assert TaskDependency is not None
    assert WorkerStatus is not None
    assert CommentAuthorType is not None
    assert TaskAttemptStatus is not None


def test_task_agent_id_defaults_to_none():
    task = Task(id="task-1", title="Draft", role=AgentRole.ENGINEER)
    assert task.agent_id is None


def test_task_agent_id_can_be_set():
    task = Task(id="task-1", title="Draft", role=AgentRole.ENGINEER, agent_id="qwen")
    assert task.agent_id == "qwen"


def test_task_model_dump_includes_agent_id():
    task = Task(id="task-1", title="Draft", role=AgentRole.ENGINEER, agent_id="qwen")
    dump = task.model_dump()
    assert dump["agent_id"] == "qwen"


def test_task_model_validate_json_backwards_compatible_without_agent_id():
    json_str = Task(
        id="old-task",
        title="Legacy",
        role=AgentRole.ENGINEER,
    ).model_dump_json()

    loaded = Task.model_validate_json(json_str)
    assert loaded.id == "old-task"
    assert loaded.agent_id is None


def test_task_model_validate_json_with_agent_id():
    json_str = Task(
        id="new-task",
        title="With agent",
        role=AgentRole.ENGINEER,
        agent_id="qwen",
    ).model_dump_json()

    loaded = Task.model_validate_json(json_str)
    assert loaded.agent_id == "qwen"
