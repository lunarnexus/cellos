from cellos.domain.enums import AgentRole, TaskStatus, TaskType
from cellos.domain.tasks import Task
from cellos.task_actions import parse_create_task_actions, parse_create_task_actions_with_errors, task_from_create_action


def test_parse_create_task_actions_from_markdown_json_block():
    text = """
    Summary.

    ```json
    {
      "actions": [
        {
          "type": "create_task",
          "title": "Research dependency",
          "role": "researcher",
          "task_type": "research",
          "prompt": "Find the answer.",
          "status": "approved",
          "blocks_parent": true
        }
      ]
    }
    ```
    """

    actions = parse_create_task_actions(text)

    assert len(actions) == 1
    assert actions[0].title == "Research dependency"
    assert actions[0].role == AgentRole.RESEARCHER
    assert actions[0].task_type == TaskType.RESEARCH
    assert actions[0].blocks_parent is True


def test_parse_create_task_actions_reports_invalid_actions_without_raising():
    actions, errors = parse_create_task_actions_with_errors(
        """
        ```json
        {"actions": [{"type": "create_task", "task_id": "missing-title"}]}
        ```
        """
    )

    assert actions == []
    assert len(errors) == 1
    assert "title" in errors[0]


def test_parse_create_task_actions_normalizes_nested_action_shape():
    actions, errors = parse_create_task_actions_with_errors(
        """
        ```json
        {"actions": [{"action": "create_task", "task": {"title": "Research",
        "role": "researcher", "task_type": "research", "prompt": "Research it.",
        "status": "approved", "blocks_parent": true}}]}
        ```
        """
    )

    assert errors == []
    assert len(actions) == 1
    assert actions[0].title == "Research"
    assert actions[0].blocks_parent is True


def test_research_task_preapproval_is_config_controlled():
    parent = Task(
        id="parent",
        title="Parent",
        role=AgentRole.ARCHITECT,
        task_type=TaskType.ARCHITECTURE,
    )
    action = parse_create_task_actions(
        """
        {"actions": [{"type": "create_task", "title": "Research", "role": "researcher",
        "task_type": "research", "prompt": "Research it.", "status": "approved"}]}
        """
    )[0]

    gated = task_from_create_action(action, parent, preapprove_research_tasks=False, id_factory=lambda: "gated")
    preapproved = task_from_create_action(
        action,
        parent,
        preapprove_research_tasks=True,
        id_factory=lambda: "approved",
    )

    assert gated.status == TaskStatus.NEEDS_APPROVAL
    assert preapproved.status == TaskStatus.APPROVED
    assert gated.parent_id == "parent"
