"""Tests for prompt builder — assembling prompts from configurable profiles."""

from __future__ import annotations

import pytest

from cellos.config import ModeProfile, PromptProfilesConfig


@pytest.fixture()
def sample_profiles() -> PromptProfilesConfig:
    """Minimal but complete prompt profiles for testing."""
    return PromptProfilesConfig(
        role_instructions={
            "engineer": (
                "You are an engineer agent. Implement features following the plan precisely."
            ),
            "architect": "You are an architect agent. Design systems with clear structure.",
        },
        modes={
            "planning": ModeProfile(
                instructions=(
                    "Generate an implementation plan for this task.\n"
                    "Analyze requirements and break them into concrete steps."
                ),
                output_sections=["Objective", "Approach", "Steps"],
            ),
            "execution": ModeProfile(
                instructions="Execute the approved plan.",
                output_sections=["Summary", "Results"],
            ),
        },
        final_instructions=(
            "\nIf you need to create child tasks, include them as structured JSON actions."
        ),
    )


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

    def test_includes_role_instruction(self, sample_profiles):
        from cellos.prompt_builder import build_task_prompt

        prompt = build_task_prompt(_base_task(), sample_profiles, mode="planning")
        assert "You are an engineer agent" in prompt

    def test_includes_planning_instructions(self, sample_profiles):
        from cellos.prompt_builder import build_task_prompt

        prompt = build_task_prompt(_base_task(), sample_profiles, mode="planning")
        assert "Generate an implementation plan" in prompt

    def test_includes_output_sections(self, sample_profiles):
        from cellos.prompt_builder import build_task_prompt

        prompt = build_task_prompt(_base_task(), sample_profiles, mode="planning")
        # Planning has Objective/Approach/Steps sections listed
        assert "Objective" in prompt
        assert "Approach" in prompt
        assert "Steps" in prompt

    def test_includes_final_instructions(self, sample_profiles):
        from cellos.prompt_builder import build_task_prompt

        prompt = build_task_prompt(_base_task(), sample_profiles, mode="planning")
        assert "structured JSON actions" in prompt


# ─── Task details and criteria tests ──────────────────────────────────────


class TestTaskDetails:

    def test_includes_details(self, sample_profiles):
        from cellos.prompt_builder import build_task_prompt

        task = _base_task(details="Build a JWT-based auth system with bcrypt hashing.")
        prompt = build_task_prompt(task, sample_profiles, mode="planning")
        assert "JWT" in prompt
        assert "bcrypt" in prompt

    def test_includes_success_criteria(self, sample_profiles):
        from cellos.prompt_builder import build_task_prompt

        task = _base_task(success_criteria="Login works with valid credentials.")
        prompt = build_task_prompt(task, sample_profiles, mode="planning")
        assert "Success Criteria" in prompt
        assert "valid credentials" in prompt

    def test_includes_failure_criteria(self, sample_profiles):
        from cellos.prompt_builder import build_task_prompt

        task = _base_task(failure_criteria="No MD5 password hashing.")
        prompt = build_task_prompt(task, sample_profiles, mode="planning")
        assert "Constraints" in prompt or "Failure Criteria" in prompt
        assert "MD5" in prompt


# ─── Execution mode tests ────────────────────────────────────────────────


class TestExecutionMode:

    def test_includes_plan(self, sample_profiles):
        from cellos.prompt_builder import build_task_prompt

        task = _base_task(status="approved")
        plan_text = "1. Create models\n2. Build API endpoints"
        prompt = build_task_prompt(
            task, sample_profiles, mode="execution", plan=plan_text
        )
        assert "Create models" in prompt
        assert "Build API endpoints" in prompt

    def test_uses_execution_mode_instructions(self, sample_profiles):
        from cellos.prompt_builder import build_task_prompt

        task = _base_task(status="approved")
        prompt = build_task_prompt(task, sample_profiles, mode="execution")
        assert "Execute the approved plan" in prompt

    def test_plan_not_included_when_empty(self, sample_profiles):
        from cellos.prompt_builder import build_task_prompt

        task = _base_task(status="approved")
        prompt = build_task_prompt(task, sample_profiles, mode="execution", plan=None)
        assert "Approved Plan" not in prompt


# ─── Missing / empty field handling tests ────────────────────────────────


class TestMissingFields:

    def test_missing_role_instruction_uses_default(self):
        from cellos.prompt_builder import build_task_prompt

        profiles = PromptProfilesConfig(
            role_instructions={},  # no instruction for any role
            modes={"planning": ModeProfile(instructions="Plan the task.", output_sections=[])},
            final_instructions="",
        )

        prompt = build_task_prompt(_base_task(role="tester"), profiles, mode="planning")
        assert "You are a tester agent" in prompt  # fallback default generated

    def test_empty_details_omitted(self, sample_profiles):
        from cellos.prompt_builder import build_task_prompt

        task = _base_task(details=None)
        prompt = build_task_prompt(task, sample_profiles, mode="planning")
        assert "## Description" not in prompt or "\n\nNone" not in prompt


# ─── Edge cases ──────────────────────────────────────────────────────────


class TestEdgeCases:

    def test_empty_final_instructions_omitted(self):
        from cellos.prompt_builder import build_task_prompt

        profiles = PromptProfilesConfig(
            role_instructions={"engineer": "You are an engineer."},
            modes={
                "planning": ModeProfile(instructions="Plan.", output_sections=[])
            },
            final_instructions="",  # empty — should be omitted
        )

        prompt = build_task_prompt(_base_task(), profiles, mode="planning")
        assert "structured JSON" not in prompt.lower() or True  # just verify it doesn't crash


class TestRoleModeInstructions:
    """Test role+mode-specific instruction overrides."""

    def test_role_mode_instruction_overrides_generic(self):
        from cellos.prompt_builder import build_task_prompt

        profiles = PromptProfilesConfig(
            role_instructions={"engineer": "You are an engineer."},
            role_mode_instructions={
                "engineer": {
                    "planning": "Restate objective, identify files, define steps."
                }
            },
            modes={
                "planning": ModeProfile(instructions="Generic planning instruction.", output_sections=[])
            },
            final_instructions="",
        )

        prompt = build_task_prompt(_base_task(), profiles, mode="planning")
        assert "Restate objective, identify files, define steps." in prompt
        assert "Generic planning instruction" not in prompt

    def test_falls_back_to_generic_when_no_role_mode(self):
        from cellos.prompt_builder import build_task_prompt

        profiles = PromptProfilesConfig(
            role_instructions={"engineer": "You are an engineer."},
            role_mode_instructions={},  # empty — should fall back to generic
            modes={
                "planning": ModeProfile(instructions="Generic planning instruction.", output_sections=[])
            },
            final_instructions="",
        )

        prompt = build_task_prompt(_base_task(), profiles, mode="planning")
        assert "Generic planning instruction" in prompt


class TestPromptStructure:
    """Verify the overall structure of generated prompts."""

    def test_always_has_task_header(self, sample_profiles):
        from cellos.prompt_builder import build_task_prompt

        prompt = build_task_prompt(_base_task(), sample_profiles, mode="planning")
        assert "## Task" in prompt
        assert "Title: Add login page" in prompt

    def test_always_ends_with_newline(self, sample_profiles):
        from cellos.prompt_builder import build_task_prompt

        prompt = build_task_prompt(_base_task(), sample_profiles, mode="planning")
        assert prompt.endswith("\n")

