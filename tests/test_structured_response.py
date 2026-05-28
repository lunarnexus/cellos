"""Tests for structured agent response models and JSON extraction."""

from __future__ import annotations

import pytest

from cellos.structured_response import (
    _extract_json_objects,
    _parse_first_json,
    child_tasks_from_response,
    parse_execution_response,
    parse_planning_response,
    plan_to_text,
    PlanningResponse,
    ExecutionResponse,
    PlanSpec,
    ChildTaskSpec,
)


# ─── JSON extraction ─────────────────────────────────────────────────────


class TestExtractJsonObjects:

    def test_extracts_fenced_json_block(self):
        text = """Here's my plan:
```json
{"plan": {"objective": "Test", "steps": ["A"]}}
```
"""
        results = _extract_json_objects(text)
        assert len(results) == 1
        assert '{"plan": {"objective": "Test", "steps": ["A"]}}' in results[0]

    def test_extracts_fenced_block_without_lang_tag(self):
        text = """```
{"plan": {"objective": "Test", "steps": ["A"]}}
```"""
        results = _extract_json_objects(text)
        assert len(results) == 1

    def test_falls_back_to_bracket_scan_when_no_fences(self):
        text = '{"plan": {"objective": "X", "steps": ["1"]}}'
        results = _extract_json_objects(text)
        assert len(results) >= 1

    def test_handles_multiple_fenced_blocks(self):
        text = """```json
{"a": 1}
```

```json
{"b": 2}
```"""
        results = _extract_json_objects(text)
        assert len(results) == 2

    def test_bracket_scan_finds_embedded_object(self):
        text = "Thinking... {\"plan\": {\"objective\": \"Go\", \"steps\": [\"step1\"]}} ...more text."
        results = _extract_json_objects(text)
        assert len(results) >= 1

    def test_handles_nested_brackets(self):
        text = '{"plan": {"objective": "X", "steps": ["a", "b"]}}'
        results = _extract_json_objects(text)
        assert len(results) == 1

    def test_returns_empty_for_plain_text(self):
        text = "Just some plain text with no JSON at all."
        results = _extract_json_objects(text)
        assert len(results) == 0

    def test_skips_malformed_json(self):
        text = '{"plan": {"objective": "X", "steps": ["broken'
        results = _extract_json_objects(text)
        assert len(results) == 0

    def test_handles_chatty_model_output(self):
        text = """Alright, let me think about this.

The task is to count lines in a file. I should:
1. Check if the file exists
2. Use wc -l
3. Report the result

Here's my structured response:

{"plan": {"objective": "Count lines in README.md", "steps": ["Check file exists", "Run wc -l", "Report result"]}}

I think that covers it. Let me know if you need anything else!
"""
        results = _extract_json_objects(text)
        assert len(results) >= 1

    def test_takes_last_valid_when_model_repeats(self):
        text = """{"plan": {"objective": "First", "steps": ["a"]}}
{"plan": {"objective": "Second", "steps": ["b"]}}"""
        results = _extract_json_objects(text)
        # Both should be found; _parse_first_json takes the first
        assert len(results) == 2


class TestParseFirstJson:

    def test_returns_dict_from_fenced_json(self):
        text = "```json\n{\"key\": \"value\"}\n```"
        result = _parse_first_json(text)
        assert result == {"key": "value"}

    def test_returns_dict_from_raw_json(self):
        text = '{"key": "value"}'
        result = _parse_first_json(text)
        assert result == {"key": "value"}

    def test_returns_none_for_no_json(self):
        text = "Just text"
        assert _parse_first_json(text) is None

    def test_returns_none_for_array(self):
        text = '[1, 2, 3]'
        result = _parse_first_json(text)
        assert result is None  # arrays are not dicts


# ─── Planning response parsing ───────────────────────────────────────────


class TestParsePlanningResponse:

    def test_parses_valid_planning_response(self):
        text = """```json
{
  "plan": {
    "objective": "Count lines in README.md",
    "steps": ["Check file", "Run wc -l", "Report"],
    "approach": "Use shell command",
    "verification": ["Confirm output"]
  },
  "child_tasks": []
}
```"""
        result = parse_planning_response(text)
        assert result is not None
        assert result.plan.objective == "Count lines in README.md"
        assert len(result.plan.steps) == 3
        assert result.plan.approach == "Use shell command"
        assert len(result.child_tasks) == 0

    def test_parses_planning_with_child_tasks(self):
        text = """{
  "plan": {
    "objective": "Implement feature",
    "steps": ["Create task", "Execute"]
  },
  "child_tasks": [
    {
      "title": "Build the module",
      "role": "engineer",
      "details": "Implement the approved behavior",
      "success_criteria": "Tests pass",
      "blocks_parent": true
    }
  ]
}"""
        result = parse_planning_response(text)
        assert result is not None
        assert len(result.child_tasks) == 1
        assert result.child_tasks[0].title == "Build the module"
        assert result.child_tasks[0].blocks_parent is True

    def test_requires_objective_and_steps(self):
        text = '{"plan": {"objective": "X", "steps": ["a"]}}'
        result = parse_planning_response(text)
        assert result is not None
        assert result.plan.objective == "X"
        assert result.plan.steps == ["a"]

    def test_parses_from_chatty_output(self):
        text = """Let me think about this task...

The objective is clear. I need to:
1. First check the file
2. Then count lines
3. Report back

Here's my plan:
{"plan": {"objective": "Count lines", "steps": ["Check", "Count", "Report"]}}

That should work!
"""
        result = parse_planning_response(text)
        assert result is not None
        assert result.plan.objective == "Count lines"

    def test_returns_none_for_malformed_json(self):
        text = '{"plan": {"objective": "X", "steps": ["broken'
        result = parse_planning_response(text)
        assert result is None

    def test_returns_none_for_plain_text(self):
        text = "## Objective\nCount lines.\n\n## Steps\n1. Check file\n"
        result = parse_planning_response(text)
        assert result is None

    def test_returns_none_for_empty_objective(self):
        text = '{"plan": {"objective": "", "steps": []}}'
        result = parse_planning_response(text)
        assert result is None  # min_length=1 rejects empty string/list


# ─── Execution response parsing ──────────────────────────────────────────


class TestParseExecutionResponse:

    def test_parses_valid_execution_response(self):
        text = """```json
{
  "summary": "Counted README.md",
  "success": true,
  "actions_taken": ["Ran wc -l"],
  "files_changed": [],
  "commands_run": ["wc -l README.md"],
  "criteria_met": ["Reported line count"],
  "issues": []
}
```"""
        result = parse_execution_response(text)
        assert result is not None
        assert result.success is True
        assert result.summary == "Counted README.md"
        assert "Ran wc -l" in result.actions_taken

    def test_parses_failed_execution(self):
        text = '{"summary": "File not found", "success": false, "issues": ["README.md missing"]}'
        result = parse_execution_response(text)
        assert result is not None
        assert result.success is False
        assert len(result.issues) == 1

    def test_parses_from_chatty_output(self):
        text = """I've completed the task. Here's what I did:

1. Checked if README.md exists
2. Ran wc -l
3. Got 42 lines

{"summary": "Counted lines", "success": true, "actions_taken": ["Ran wc -l README.md"]}

All done!
"""
        result = parse_execution_response(text)
        assert result is not None
        assert result.success is True
        assert result.summary == "Counted lines"

    def test_returns_none_for_malformed_json(self):
        text = '{"summary": "X", "success": tru'
        result = parse_execution_response(text)
        assert result is None

    def test_returns_none_for_plain_text(self):
        text = "I completed the task successfully!"
        result = parse_execution_response(text)
        assert result is None

    def test_requires_nonempty_summary(self):
        text = '{"summary": "", "success": true}'
        result = parse_execution_response(text)
        assert result is None  # min_length=1 rejects empty summary

    def test_defaults_optional_fields(self):
        text = '{"summary": "Done", "success": true}'
        result = parse_execution_response(text)
        assert result is not None
        assert result.actions_taken == []
        assert result.files_changed == []
        assert result.commands_run == []
        assert result.criteria_met == []
        assert result.issues == []


# ─── Plan text conversion ────────────────────────────────────────────────


class TestPlanToText:

    def test_converts_full_plan(self):
        response = PlanningResponse(
            plan=PlanSpec(
                objective="Count lines",
                steps=["Check file", "Run wc -l"],
                approach="Shell command",
                verification=["Confirm output"],
                risks=["File may not exist"],
            ),
            child_tasks=[],
        )
        text = plan_to_text(response)
        assert "## Objective" in text
        assert "Count lines" in text
        assert "## Approach" in text
        assert "## Steps" in text
        assert "1. Check file" in text
        assert "## Verification" in text
        assert "## Risks" in text

    def test_omits_optional_sections_when_empty(self):
        response = PlanningResponse(
            plan=PlanSpec(objective="Go", steps=["Do"]),
            child_tasks=[],
        )
        text = plan_to_text(response)
        assert "## Approach" not in text
        assert "## Verification" not in text
        assert "## Risks" not in text
        assert "## Dependencies" not in text

    def test_includes_child_tasks(self):
        response = PlanningResponse(
            plan=PlanSpec(objective="Go", steps=["Delegate work"]),
            child_tasks=[
                ChildTaskSpec(
                    title="Count lines",
                    role="engineer",
                    details="Use wc -l",
                )
            ],
        )

        text = plan_to_text(response)

        assert "## Child Tasks" in text
        assert "Will create a engineer child task: Count lines" in text
        assert "Details: Use wc -l" in text


# ─── Child task conversion ───────────────────────────────────────────────


class TestChildTasksFromResponse:

    def test_converts_child_task_spec_to_task_data(self):
        response = PlanningResponse(
            plan=PlanSpec(objective="Go", steps=["Do"]),
            child_tasks=[
                ChildTaskSpec(
                    title="Build module",
                    role="engineer",
                    details="Implement it",
                    success_criteria="Tests pass",
                    blocks_parent=True,
                )
            ],
        )
        result = child_tasks_from_response(response, "parent123")
        assert len(result) == 1
        child = result[0]
        assert child["title"] == "Build module"
        assert child["details"] == "Implement it"
        assert child["parent_id"] == "parent123"
        assert child["success_criteria"] == "Tests pass"

    def test_does_not_add_parent_as_dependency(self):
        response = PlanningResponse(
            plan=PlanSpec(objective="Go", steps=["Do"]),
            child_tasks=[ChildTaskSpec(title="Child")],
        )
        result = child_tasks_from_response(response, "parent123")
        child = result[0]
        dep_ids = [d.task_id for d in child["dependencies"]]
        assert "parent123" not in dep_ids

    def test_handles_empty_child_tasks(self):
        response = PlanningResponse(
            plan=PlanSpec(objective="Go", steps=["Do"]),
            child_tasks=[],
        )
        result = child_tasks_from_response(response, "parent123")
        assert len(result) == 0

    def test_resolves_role_to_task_type(self):
        response = PlanningResponse(
            plan=PlanSpec(objective="Go", steps=["Do"]),
            child_tasks=[ChildTaskSpec(title="Test", role="tester")],
        )
        result = child_tasks_from_response(response, "parent123")
        child = result[0]
        from cellos.models import TaskType
        assert child["role"].value == "tester"
        assert child["task_type"] == TaskType.VERIFICATION


# ─── Edge cases ──────────────────────────────────────────────────────────


class TestEdgeCases:

    def test_empty_input_returns_none(self):
        assert parse_planning_response("") is None
        assert parse_execution_response("") is None

    def test_whitespace_only_returns_none(self):
        assert parse_planning_response("   \n  ") is None
        assert parse_execution_response("   \n  ") is None

    def test_multiple_json_blocks_takes_first_valid(self):
        text = """{"plan": {"objective": "First", "steps": ["a"]}}
{"plan": {"objective": "Second", "steps": ["b"]}}"""
        result = parse_planning_response(text)
        assert result is not None
        assert result.plan.objective == "First"

    def test_fenced_json_takes_precedence_over_raw(self):
        text = """{"plan": {"objective": "Raw", "steps": ["a"]}}

```json
{"plan": {"objective": "Fenced", "steps": ["b"]}}
```"""
        result = parse_planning_response(text)
        assert result is not None
        # Fenced should be found first
        assert result.plan.objective == "Fenced"

    def test_handles_unicode_in_json(self):
        text = '{"plan": {"objective": "Count línès", "steps": ["Çhëck"]}}'
        result = parse_planning_response(text)
        assert result is not None
        assert result.plan.objective == "Count línès"

    def test_handles_escaped_quotes_in_json(self):
        text = '{"plan": {"objective": "Count \\"lines\\"", "steps": ["Step \\"1\\\""]}}'
        result = parse_planning_response(text)
        assert result is not None
        assert 'lines' in result.plan.objective


# ─── Integration: models ─────────────────────────────────────────────────


class TestModels:

    def test_planning_response_model_validation(self):
        plan = PlanSpec(objective="Go", steps=["A", "B"])
        assert plan.objective == "Go"
        assert len(plan.steps) == 2
        assert plan.approach is None
        assert plan.dependencies == []
        assert plan.risks == []

    def test_child_task_spec_model(self):
        spec = ChildTaskSpec(title="Task", role="engineer")
        assert spec.title == "Task"
        assert spec.blocks_parent is False
        assert spec.dependencies == []

    def test_execution_response_model(self):
        resp = ExecutionResponse(summary="Done", success=True)
        assert resp.summary == "Done"
        assert resp.success is True
        assert resp.actions_taken == []

    def test_execution_response_with_all_fields(self):
        resp = ExecutionResponse(
            summary="Done",
            success=True,
            actions_taken=["Ran cmd"],
            files_changed=["foo.py"],
            commands_run=["cmd"],
            criteria_met=["Works"],
            issues=["Minor warning"],
        )
        assert len(resp.actions_taken) == 1
        assert len(resp.files_changed) == 1
        assert len(resp.commands_run) == 1
        assert len(resp.criteria_met) == 1
        assert len(resp.issues) == 1
