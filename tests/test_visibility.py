"""Visibility and diagnostics tests — persistence, CLI commands, failure summaries."""

from __future__ import annotations

import json
import pathlib
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cellos.config import (
    AgentCatalogEntry,
    CellosConfig,
    PromptLibraryConfig,
)
from cellos.db import CellosDatabase
from cellos.models import (
    AgentRole,
    ROLE_TO_TASK_TYPE,
    Task,
    TaskAttemptStatus,
    TaskStatus,
)
from cellos.persistence.schema import init_db


@pytest.fixture
async def db():
    """Create a temp SQLite DB for each test."""
    tmpdir = tempfile.mkdtemp()
    db_path = pathlib.Path(tmpdir) / "test.sqlite"
    await init_db(db_path)
    database = CellosDatabase(db_path)
    await database.connect()
    yield database, str(db_path), tmpdir
    await database.close()


@pytest.fixture
def config():
    """Minimal config with fake_acp agent."""
    return CellosConfig(
        agents={"default_agent_id": "engineer"},
        worker={"timeout_seconds": 30},
        approvals={"preapprove_research_tasks": False},
        agent_catalog={
            "engineer": AgentCatalogEntry(
                connector="fake_acp",
                options={"default_success": True, "default_summary": "Done."},
            ),
        },
        prompt_library=PromptLibraryConfig(
            roles={"engineer": "You are an engineer."},
            modes={
                "planning": "Plan.",
                "execution": "Execute.",
            },
            tools_header="",
            output_instruction="",
        ),
    )


def _make_task(title="Test task", role=AgentRole.ENGINEER):
    return Task(
        title=title,
        role=role,
        task_type=ROLE_TO_TASK_TYPE[role],
    )


# ── Schema migration tests ──────────────────────────────────────────────────

class TestSchemaMigration:
    async def test_migration_adds_diagnostic_columns(self):
        """Migration adds all diagnostic columns to task_attempts."""
        from cellos.persistence.schema import ensure_initialized

        tmpdir = tempfile.mkdtemp()
        db_path = pathlib.Path(tmpdir) / "test.sqlite"
        await init_db(db_path)
        await ensure_initialized(db_path)  # This triggers the migration

        async with __import__("aiosqlite").connect(str(db_path)) as conn:
            cursor = await conn.execute("PRAGMA table_info(task_attempts)")
            cols = {row[1] async for row in cursor}

        # All diagnostic columns should be present
        assert "acp_session_id" in cols
        assert "acp_message_id" in cols
        assert "agent_provider" in cols
        assert "agent_model" in cols
        assert "last_event_type" in cols
        assert "last_event_at" in cols
        assert "active_tool_name" in cols
        assert "active_tool_call_id" in cols
        assert "nested_session_id" in cols
        assert "partial_text" in cols
        assert "partial_thinking" in cols
        assert "error_type" in cols
        assert "timeout_flag" in cols
        assert "aborted_flag" in cols
        assert "raw_diagnostics_json" in cols

    async def test_migration_is_idempotent(self):
        """Running migration twice does not error."""
        from cellos.persistence.schema import migrate_attempt_diagnostics

        tmpdir = tempfile.mkdtemp()
        db_path = pathlib.Path(tmpdir) / "test.sqlite"
        await init_db(db_path)
        await migrate_attempt_diagnostics(db_path)
        await migrate_attempt_diagnostics(db_path)  # Should not raise


# ── Diagnostic persistence tests ─────────────────────────────────────────────

class TestDiagnosticPersistence:
    async def test_attempt_stores_diagnostics(self, db):
        """Diagnostics are persisted when passed to update_attempt."""
        database = db[0]
        task = _make_task()
        await database.create_task(task)

        attempt = await database.create_attempt(
            task_id=task.id, mode="execution", agent_id="engineer"
        )

        diagnostics = {
            "session_id": "ses_test123",
            "message_id": "msg_abc",
            "agent_provider": "opencode",
            "last_event_type": "AgentMessageChunk",
            "last_event_at": "2026-05-28T18:30:00Z",
            "active_tool_name": "bash",
            "active_tool_call_id": "tc_1",
            "nested_session_id": "ses_nested",
            "timeout": True,
            "error_type": "TimeoutError",
        }

        await database.update_attempt(
            attempt.id, TaskStatus.DONE,
            result_summary="Timed out",
            diagnostics=diagnostics,
        )

        retrieved = await database.get_attempt(attempt.id)
        assert retrieved is not None
        assert retrieved.acp_session_id == "ses_test123"
        assert retrieved.acp_message_id == "msg_abc"
        assert retrieved.agent_provider == "opencode"
        assert retrieved.last_event_type == "AgentMessageChunk"
        assert retrieved.active_tool_name == "bash"
        assert retrieved.active_tool_call_id == "tc_1"
        assert retrieved.nested_session_id == "ses_nested"
        assert retrieved.timeout is True
        assert retrieved.error_type == "TimeoutError"

    async def test_attempt_detail_shows_full_diagnostics(self, db):
        """get_attempt returns full diagnostic data including raw JSON."""
        database = db[0]
        task = _make_task()
        await database.create_task(task)

        attempt = await database.create_attempt(
            task_id=task.id, mode="planning", agent_id="architect"
        )

        diagnostics = {
            "session_id": "ses_plan",
            "stop_reason": "end_turn",
            "partial_thinking": "I need to inspect the codebase...",
        }
        await database.update_attempt(
            attempt.id, TaskStatus.DONE,
            result_summary="Plan generated",
            diagnostics=diagnostics,
        )

        retrieved = await database.get_attempt(attempt.id)
        assert retrieved is not None
        assert retrieved.acp_session_id == "ses_plan"
        assert retrieved.partial_thinking == "I need to inspect the codebase..."
        assert retrieved.raw_diagnostics_json is not None

    async def test_timeout_failure_fixture_persists(self, db, config):
        """A timeout scenario with active tool is persisted correctly."""
        from cellos.services.worker_service import run_task_worker
        database, _, tmpdir = db

        # Create a fixture that simulates a timeout
        fixture_dir = pathlib.Path(tmpdir) / "fixtures"
        fixture_dir.mkdir()
        (fixture_dir / "planning.json").write_text(
            json.dumps({
                "success": True,
                "summary": "Plan generated",
                "output": "Plan: step 1, step 2",
                "diagnostics": {
                    "session_id": "ses_timeout",
                    "message_id": "msg_1",
                    "last_event_type": "ToolCallProgress",
                    "active_tool_name": "task",
                    "active_tool_call_id": "tc_nested",
                    "nested_session_id": "ses_child",
                    "timeout": True,
                    "error_type": "TimeoutError",
                    "error_message": "ACP timeout after 300s",
                },
            }),
            encoding="utf-8",
        )
        config.agent_catalog["engineer"].options["fixture_dir"] = str(fixture_dir)

        task = _make_task(title="Timeout test", role=AgentRole.ENGINEER)
        await database.create_task(task)

        await run_task_worker(database, task.id, "planning", config)

        attempts = await database.list_attempts(task.id)
        assert len(attempts) >= 1
        attempt = attempts[0]
        assert attempt.acp_session_id == "ses_timeout"
        assert attempt.active_tool_name == "task"
        assert attempt.nested_session_id == "ses_child"
        assert attempt.timeout is True


# ── CLI diagnostic commands tests ────────────────────────────────────────────

class TestCLICommands:
    def test_attempts_command_lists_attempts(self, tmp_path):
        """cellos attempts TASK_ID shows attempt table."""
        from click.testing import CliRunner
        from cellos.cli import main

        runner = CliRunner()
        db_path = str(tmp_path / "test.sqlite")
        config_dir = str(tmp_path / ".cellos")

        # Init
        runner.invoke(main, ["--config-dir", config_dir, "--db", db_path, "init"])

        # Add a task
        result = runner.invoke(
            main, ["--config-dir", config_dir, "--db", db_path, "add-task", "Test task"]
        )
        assert result.exit_code == 0
        task_id = result.output.split("Created task ")[1].split(":")[0].strip()

        # Run attempts (should show no attempts or empty)
        result = runner.invoke(
            main, ["--config-dir", config_dir, "--db", db_path, "attempts", task_id]
        )
        assert result.exit_code == 0
        assert "No attempts found" in result.output or "ID" in result.output

    def test_attempts_detail_flag(self, tmp_path):
        """cellos attempts -d shows per-attempt diagnostic details."""
        from click.testing import CliRunner
        from cellos.cli import main

        runner = CliRunner()
        db_path = str(tmp_path / "test.sqlite")
        config_dir = str(tmp_path / ".cellos")

        runner.invoke(main, ["--config-dir", config_dir, "--db", db_path, "init"])
        result = runner.invoke(
            main, ["--config-dir", config_dir, "--db", db_path, "add-task", "Test"]
        )
        assert result.exit_code == 0
        task_id = result.output.split("Created task ")[1].split(":")[0].strip()

        # -d flag should work even with no attempts
        result = runner.invoke(
            main, ["--config-dir", config_dir, "--db", db_path, "attempts", "-d", task_id]
        )
        assert result.exit_code == 0

    def test_detail_shows_attempt_summary(self, tmp_path):
        """cellos detail shows attempt count and last attempts."""
        from click.testing import CliRunner
        from cellos.cli import main

        runner = CliRunner()
        db_path = str(tmp_path / "test.sqlite")
        config_dir = str(tmp_path / ".cellos")

        runner.invoke(main, ["--config-dir", config_dir, "--db", db_path, "init"])
        result = runner.invoke(
            main, ["--config-dir", config_dir, "--db", db_path, "add-task", "Test"]
        )
        assert result.exit_code == 0
        task_id = result.output.split("Created task ")[1].split(":")[0].strip()

        result = runner.invoke(
            main, ["--config-dir", config_dir, "--db", db_path, "detail", task_id]
        )
        assert result.exit_code == 0
        # No attempts yet, so no attempt section
        assert "Attempts" not in result.output or "Attempts (0)" in result.output


# ── Failure summary tests ────────────────────────────────────────────────────

class TestFailureSummaries:
    def test_timeout_with_active_tool(self):
        from cellos.services.worker_service import _build_failure_summary

        diagnostics = {
            "timeout": True,
            "active_tool_name": "task",
            "nested_session_id": "ses_child",
            "last_event_type": "ToolCallProgress",
            "last_event_at": "2026-05-28T18:30:00Z",
            "partial_text": "I'm working on this...",
        }
        summary = _build_failure_summary(diagnostics)
        assert "timed out" in summary.lower()
        assert "task" in summary
        assert "ses_child" in summary

    def test_abort_no_tool(self):
        from cellos.services.worker_service import _build_failure_summary

        diagnostics = {
            "aborted": True,
            "last_event_type": "AgentThoughtChunk",
        }
        summary = _build_failure_summary(diagnostics)
        assert "aborted" in summary.lower()
        assert "AgentThoughtChunk" in summary

    def test_no_diagnostics(self):
        from cellos.services.worker_service import _build_failure_summary

        summary = _build_failure_summary(None)
        assert "No output from agent" in summary

    def test_error_type(self):
        from cellos.services.worker_service import _build_failure_summary

        diagnostics = {
            "error_type": "RuntimeError",
            "error_message": "connection refused",
        }
        summary = _build_failure_summary(diagnostics)
        assert "RuntimeError" in summary


# ── TaskAttempt model tests ──────────────────────────────────────────────────

class TestTaskAttemptModel:
    def test_attempt_has_diagnostic_fields(self):
        from cellos.models import TaskAttempt

        attempt = TaskAttempt(task_id="t1")
        assert attempt.acp_session_id is None
        assert attempt.acp_message_id is None
        assert attempt.agent_provider is None
        assert attempt.agent_model is None
        assert attempt.last_event_type is None
        assert attempt.active_tool_name is None
        assert attempt.active_tool_call_id is None
        assert attempt.nested_session_id is None
        assert attempt.partial_text is None
        assert attempt.partial_thinking is None
        assert attempt.error_type is None
        assert attempt.timeout is False
        assert attempt.aborted is False
        assert attempt.raw_diagnostics_json is None

    def test_attempt_with_full_diagnostics(self):
        from cellos.models import TaskAttempt

        attempt = TaskAttempt(
            task_id="t1",
            acp_session_id="ses_123",
            acp_message_id="msg_456",
            agent_provider="opencode",
            agent_model="gpt-4",
            last_event_type="ToolCallProgress",
            active_tool_name="bash",
            active_tool_call_id="tc_1",
            nested_session_id="ses_nested",
            partial_text="partial output",
            partial_thinking="thinking...",
            error_type="TimeoutError",
            timeout=True,
            aborted=False,
            raw_diagnostics_json='{"key": "value"}',
        )
        assert attempt.acp_session_id == "ses_123"
        assert attempt.timeout is True
        assert attempt.aborted is False
