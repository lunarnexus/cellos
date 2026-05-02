from cellos.models import (
    AgentRole,
    AttentionReason,
    ChangeRequestReport,
    Task,
    TaskResult,
    TaskStatus,
    TaskType,
)


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
