"""Tests for prompt builder — assembling prompts from configurable library."""

from __future__ import annotations

import pytest

from cellos.config import PromptLibraryConfig


@pytest.fixture()
def sample_library() -> PromptLibraryConfig:
    """Minimal but complete prompt library for testing."""
    return PromptLibraryConfig(
        roles={
            "engineer": (
                "You are an engineer agent. Implement features following the plan precisely."
            ),
            "architect": "You are an architect agent. Design systems with clear structure.",
        },
        modes={
            "planning": (
                "Generate an implementation plan for this task.\n"
                "Analyze requirements and break them into concrete steps."
            ),
            "execution": "Execute the approved plan.",
        },
        tools_header="## Available Tools\nCall the appropriate tool when your work is complete:\n",
        output_instruction="Call the tool that matches your current task.",
    )


@pytest.fixture()
def sample_tool_defs() -> dict:
    """Minimal tool definitions for testing."""
    return {
        "cellos_submit_prompt": {
            "description": "Submit your plan. Call once when planning is complete.",
            "schema": {
                "properties": {
                    "objective": {"type": "string"},
                    "steps": {"type": "array", "items": {"type": "string"}},
                    "approach": {"type": "string"},
                },
                "required": ["objective", "steps"],
            },
        },
        "cellos_submit_reply": {
            "description": "Submit execution results. Call when work is done or blocked.",
            "schema": {
                "properties": {
                    "summary": {"type": "string"},
                    "success": {"type": "boolean"},
                    "actions_taken": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["summary", "success"],
            },
        },
    }


def _base_task(**overrides) -> dict:
    """Build a minimal task dict for testing."""
    base = {
        "role": "engineer",
        "title": "Add login page",
        "status": "draft",
        "task_type": "implementation",
        "details": None,
        "success_criteria": None,
        "failure_criteria": None,
    }
    base.update(overrides)
    return base


# ─── Planning mode tests ────────────────────────────────────────────────


class TestPlanningMode:

    def test_includes_role_instruction(self, sample_library):
        from cellos.prompt_builder import build_task_prompt

        prompt = build_task_prompt(_base_task(), sample_library, mode="planning")
        assert "You are an engineer agent" in prompt

    def test_includes_planning_instructions(self, sample_library):
        from cellos.prompt_builder import build_task_prompt

        prompt = build_task_prompt(_base_task(), sample_library, mode="planning")
        assert "Generate an implementation plan" in prompt

    def test_includes_output_instruction(self, sample_library):
        from cellos.prompt_builder import build_task_prompt

        prompt = build_task_prompt(_base_task(), sample_library, mode="planning")
        assert "Call the tool that matches your current task" in prompt


# ─── Tool injection tests ────────────────────────────────────────────────


class TestToolInjection:

    def test_includes_tools_header(self, sample_library, sample_tool_defs):
        from cellos.prompt_builder import build_task_prompt

        prompt = build_task_prompt(
            _base_task(), sample_library, mode="planning", tool_defs=sample_tool_defs
        )
        assert "## Available Tools" in prompt
        assert "cellos_submit_prompt" in prompt

    def test_includes_tool_descriptions(self, sample_library, sample_tool_defs):
        from cellos.prompt_builder import build_task_prompt

        prompt = build_task_prompt(
            _base_task(), sample_library, mode="planning", tool_defs=sample_tool_defs
        )
        assert "Submit your plan" in prompt

    def test_includes_field_names(self, sample_library, sample_tool_defs):
        from cellos.prompt_builder import build_task_prompt

        prompt = build_task_prompt(
            _base_task(), sample_library, mode="planning", tool_defs=sample_tool_defs
        )
        assert "objective" in prompt
        assert "steps" in prompt
        assert "approach" in prompt

    def test_no_tools_when_empty(self, sample_library):
        from cellos.prompt_builder import build_task_prompt

        prompt = build_task_prompt(_base_task(), sample_library, mode="planning")
        assert "## Available Tools" not in prompt


# ─── Task details and criteria tests ──────────────────────────────────────


class TestTaskDetails:

    def test_includes_details(self, sample_library):
        from cellos.prompt_builder import build_task_prompt

        task = _base_task(details="Build a JWT-based auth system with bcrypt hashing.")
        prompt = build_task_prompt(task, sample_library, mode="planning")
        assert "JWT" in prompt
        assert "bcrypt" in prompt

    def test_includes_success_criteria(self, sample_library):
        from cellos.prompt_builder import build_task_prompt

        task = _base_task(success_criteria="Login works with valid credentials.")
        prompt = build_task_prompt(task, sample_library, mode="planning")
        assert "Success Criteria" in prompt
        assert "valid credentials" in prompt

    def test_includes_failure_criteria(self, sample_library):
        from cellos.prompt_builder import build_task_prompt

        task = _base_task(failure_criteria="No MD5 password hashing.")
        prompt = build_task_prompt(task, sample_library, mode="planning")
        assert "Constraints" in prompt
        assert "MD5" in prompt


# ─── Execution mode tests ────────────────────────────────────────────────


class TestExecutionMode:

    def test_includes_plan(self, sample_library):
        from cellos.prompt_builder import build_task_prompt

        task = _base_task(status="approved")
        plan_text = "1. Create models\n2. Build API endpoints"
        prompt = build_task_prompt(
            task, sample_library, mode="execution", plan=plan_text
        )
        assert "Create models" in prompt
        assert "Build API endpoints" in prompt

    def test_uses_execution_mode_instructions(self, sample_library):
        from cellos.prompt_builder import build_task_prompt

        task = _base_task(status="approved")
        prompt = build_task_prompt(task, sample_library, mode="execution")
        assert "Execute the approved plan" in prompt

    def test_plan_not_included_when_empty(self, sample_library):
        from cellos.prompt_builder import build_task_prompt

        task = _base_task(status="approved")
        prompt = build_task_prompt(task, sample_library, mode="execution", plan=None)
        assert "Approved Plan" not in prompt


# ─── Missing / empty field handling tests ────────────────────────────────


class TestMissingFields:

    def test_missing_role_instruction_uses_default(self):
        from cellos.prompt_builder import build_task_prompt

        library = PromptLibraryConfig(
            roles={},  # no instruction for any role
            modes={"planning": "Plan the task."},
            tools_header="",
            output_instruction="",
        )

        prompt = build_task_prompt(_base_task(role="tester"), library, mode="planning")
        assert "You are a tester agent" in prompt  # fallback default generated

    def test_empty_details_omitted(self, sample_library):
        from cellos.prompt_builder import build_task_prompt

        task = _base_task(details=None)
        prompt = build_task_prompt(task, sample_library, mode="planning")
        assert "## Description" not in prompt or "\n\nNone" not in prompt


# ─── Edge cases ──────────────────────────────────────────────────────────


class TestEdgeCases:

    def test_empty_output_instruction_omitted(self):
        from cellos.prompt_builder import build_task_prompt

        library = PromptLibraryConfig(
            roles={"engineer": "You are an engineer."},
            modes={"planning": "Plan."},
            tools_header="",
            output_instruction="",  # empty — should be omitted
        )

        prompt = build_task_prompt(_base_task(), library, mode="planning")
        assert "Call the tool" not in prompt

    def test_includes_comments_in_planning_mode(self, sample_library):
        from cellos.prompt_builder import build_task_prompt

        task = _base_task(comments="[human] Please add a remember-me checkbox")
        prompt = build_task_prompt(task, sample_library, mode="planning")
        assert "remember-me" in prompt
        assert "## Comments" in prompt

    def test_omits_comments_in_execution_mode(self, sample_library):
        from cellos.prompt_builder import build_task_prompt

        task = _base_task(comments="[human] Please add a remember-me checkbox")
        prompt = build_task_prompt(task, sample_library, mode="execution")
        assert "remember-me" not in prompt


class TestPromptStructure:
    """Verify the overall structure of generated prompts."""

    def test_always_has_task_header(self, sample_library):
        from cellos.prompt_builder import build_task_prompt

        prompt = build_task_prompt(_base_task(), sample_library, mode="planning")
        assert "## Task" in prompt
        assert "Title: Add login page" in prompt

    def test_always_ends_with_newline(self, sample_library):
        from cellos.prompt_builder import build_task_prompt

        prompt = build_task_prompt(_base_task(), sample_library, mode="planning")
        assert prompt.endswith("\n")
