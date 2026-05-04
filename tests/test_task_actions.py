from cellos.models import AgentRole, Task, TaskStatus, TaskType
from cellos.task_actions import parse_create_task_actions, task_from_create_action


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
