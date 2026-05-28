"""Tests for structured action parsing — child task creation from agent output."""

from __future__ import annotations

import pytest


# ─── Fenced JSON format (most common) ──────────────────────────────────────


class TestFencedJsonFormat:

    def test_parses_fenced_json_block(self):
        from cellos.task_actions import parse_create_task_actions

        text = """Here's my plan. I need to create a child task:

```json
{
  "actions": [
    {
      "type": "create_task",
      "title": "Create database models",
      "role": "engineer"
    }
  ]
}
```
"""
        actions = parse_create_task_actions(text)
        assert len(actions) == 1
        assert actions[0].title == "Create database models"
        assert actions[0].role == "engineer"

    def test_parses_multiple_fenced_blocks(self):
        from cellos.task_actions import parse_create_task_actions

        text = """First block:
```json
{
  "actions": [
    {"type": "create_task", "title": "Task A"}
  ]
}
```

Second block with another action:
```json
{
  "actions": [
    {"type": "create_task", "title": "Task B", "role": "tester"}
  ]
}
```
"""
        actions = parse_create_task_actions(text)
        assert len(actions) == 2

    def test_ignores_non_json_fenced_blocks(self):
        from cellos.task_actions import parse_create_task_actions

        text = """Here's some code:
```python
def hello(): pass
```

And the actual action:
```json
{
  "actions": [
    {"type": "create_task", "title": "Real task"}
  ]
}
```
"""
        actions = parse_create_task_actions(text)
        assert len(actions) == 1


# ─── Plain JSON format (no fences) ──────────────────────────────────────


class TestPlainJsonFormat:

    def test_parses_plain_json(self):
        from cellos.task_actions import parse_create_task_actions

        text = '{"actions": [{"type": "create_task", "title": "Direct task"}]}'
        actions = parse_create_task_actions(text)
        assert len(actions) == 1
        assert actions[0].title == "Direct task"


# ─── Nested action format ──────────────────────────────────────────────


class TestNestedFormat:

    def test_parses_nested_action_format(self):
        from cellos.task_actions import parse_create_task_actions

        text = """```json
{
  "actions": [
    {
      "action": "create_task",
      "task": {
        "title": "Nested task",
        "role": "architect",
        "prompt": "Design the schema"
      }
    }
  ]
}
```"""
        actions = parse_create_task_actions(text)
        assert len(actions) == 1
        assert actions[0].title == "Nested task"
        assert actions[0].role == "architect"


# ─── Validation and error handling ──────────────────────────────────────


class TestValidation:

    def test_rejects_empty_title(self):
        from cellos.task_actions import parse_create_task_actions

        text = '{"actions": [{"type": "create_task", "title": ""}]}'
        actions = parse_create_task_actions(text)
        assert len(actions) == 0  # validation failure → silently skipped

    def test_rejects_missing_title(self):
        from cellos.task_actions import parse_create_task_actions

        text = '{"actions": [{"type": "create_task"}]}'
        actions = parse_create_task_actions(text)
        assert len(actions) == 0

    def test_skips_malformed_json_block(self):
        from cellos.task_actions import parse_create_task_actions

        text = """```json
{broken json here!!!
```

```json
{"actions": [{"type": "create_task", "title": "Good task"}]}
```"""
        actions = parse_create_task_actions(text)
        assert len(actions) == 1


# ─── Child task creation from parsed actions ──────────────────────────────


class TestTasksFromCreateActions:

    def test_creates_child_with_parent_reference(self):
        from cellos.task_actions import (
            CreateTaskAction,
            tasks_from_create_actions,
        )

        action = CreateTaskAction(title="Child task", role="engineer")
        result = tasks_from_create_actions("parent123", [action])

        assert len(result) == 1
        child = result[0]
        assert child["title"] == "Child task"
        assert child["parent_id"] == "parent123"
        dep_ids = [d.task_id for d in child.get("dependencies", [])]
        assert "parent123" not in dep_ids

    def test_role_inference_from_agent(self):
        from cellos.models import AgentRole, TaskType
        from cellos.task_actions import (
            CreateTaskAction,
            tasks_from_create_actions,
        )

        action = CreateTaskAction(title="Research task", role="researcher")
        result = tasks_from_create_actions("parent123", [action])

        assert len(result) == 1
        child = result[0]
        # Role should be resolved to enum
        if "role" in child:
            assert str(child["role"]) == "researcher" or child.get("role") == AgentRole.RESEARCHER

    def test_preapprove_research_tasks(self):
        from cellos.task_actions import (
            CreateTaskAction,
            tasks_from_create_actions,
        )

        action = CreateTaskAction(title="Research API", role="researcher")
        result = tasks_from_create_actions(
            "parent123", [action], preapprove_research_tasks=True
        )

        assert len(result) == 1
        child = result[0]
        # Research task should be auto-approved when flag is set
        if "status" in child:
            assert str(child["status"]) == "approved" or child.get("status") == "approved"


# ─── Edge cases ────────────────────────────────────────────────────────


class TestEdgeCases:

    def test_empty_input_returns_no_actions(self):
        from cellos.task_actions import parse_create_task_actions

        assert parse_create_task_actions("") == []

    def test_text_without_json_returns_no_actions(self):
        from cellos.task_actions import parse_create_task_actions

        text = "Just some plain text with no JSON at all."
        actions = parse_create_task_actions(text)
        assert len(actions) == 0

    def test_valid_json_without_actions_key_is_skipped(self):
        """Agent returns valid JSON but not in our expected format."""
        from cellos.task_actions import parse_create_task_actions

        text = '{"result": "done", "summary": "Task completed successfully"}'
        actions = parse_create_task_actions(text)
        assert len(actions) == 0  # no "actions" key → silently skipped


# ─── Nested format with sibling keys ──────────────────────────────────────


class TestNestedFormatWithSiblings:

    def test_sibling_status_is_merged(self):
        """Sibling keys like status should be merged into the normalized result."""
        from cellos.task_actions import parse_create_task_actions

        text = """```json
{
  "actions": [
    {
      "action": "create_task",
      "task": {"title": "Nested task"},
      "status": "approved"
    }
  ]
}
```"""
        actions = parse_create_task_actions(text)
        assert len(actions) == 1
        # status from sibling key should be preserved
        assert actions[0].status == "approved"

    def test_inner_payload_takes_precedence_over_sibling(self):
        """If both inner task and sibling have the same key, inner wins."""
        from cellos.task_actions import parse_create_task_actions

        text = """```json
{
  "actions": [
    {
      "action": "create_task",
      "task": {"title": "Inner title"},
      "title": "Sibling title"
    }
  ]
}
```"""
        actions = parse_create_task_actions(text)
        assert len(actions) == 1
        # Inner task.title should win over sibling key
        assert actions[0].title == "Inner title"


# ─── Multiple child tasks with parent refs ──────────────────────────────


class TestMultipleChildTasks:

    def test_each_child_gets_parent_reference(self):
        from cellos.task_actions import (
            CreateTaskAction,
            tasks_from_create_actions,
        )

        actions = [
            CreateTaskAction(title="First child"),
            CreateTaskAction(title="Second child", role="tester"),
        ]
        result = tasks_from_create_actions("parent123", actions)

        assert len(result) == 2
        for child in result:
            assert child["parent_id"] == "parent123"
            dep_ids = [d.task_id for d in child.get("dependencies", [])]
            assert "parent123" not in dep_ids
