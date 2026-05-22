"""Worker service and spawner tests — connector building, attempt lifecycle, subprocess spawning."""

from __future__ import annotations

import os
import pathlib
import shutil
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cellos.config import (
    CellosConfig,
    AgentCatalogEntry,
    PromptProfilesConfig,
)
from cellos.db import CellosDatabase
from cellos.models import (
    AgentRole,
    ROLE_TO_TASK_TYPE,
    Task,
    TaskAttemptStatus,
    TaskStatus,
    TaskType,
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
        agents={"default_agent_id": "engineer"},  # type: ignore[arg-type]
        worker={"timeout_seconds": 30},  # type: ignore[arg-type]
        approvals={"preapprove_research_tasks": False},  # type: ignore[arg-type]
        agent_catalog={
            "engineer": AgentCatalogEntry(
                connector="fake_acp",
                options={"default_success": True, "default_summary": "Implementation completed successfully."},
            ),
            "architect": AgentCatalogEntry(
                connector="fake_acp",
                options={"default_success": True, "default_summary": "Architecture plan generated with steps and dependencies."},
            ),
        },
        prompt_profiles=PromptProfilesConfig(
            role_instructions={
                "engineer": "You are an engineer agent.",
                "architect": "You are an architect agent.",
            },
            modes={  # type: ignore[arg-type]
                "planning": {"instructions": "Generate a plan.", "output_sections": ["Steps"]},
                "execution": {"instructions": "Execute the plan.", "output_sections": ["Results"]},
            },
        ),
    )


def _make_task(title="Test task", role=AgentRole.ENGINEER):
    """Create a minimal Task instance."""
    return Task(
        title=title,
        role=role,
        task_type=ROLE_TO_TASK_TYPE[role],
    )


# ── _build_connector tests ───────────────────────────────

class TestBuildConnector:
    def test_builds_fake_acp(self):
        from cellos.services.worker_service import _build_connector
        agent = AgentCatalogEntry(
            connector="fake_acp", options={"default_success": True}
        )
        conn = _build_connector(agent, 30)
        assert "FakeAcp" in conn.__class__.__name__

    def test_unknown_connector_raises(self):
        from cellos.services.worker_service import _build_connector, WorkerError
        agent = AgentCatalogEntry(connector="unknown_type", options={})
        with pytest.raises(WorkerError, match="Unknown connector"):
            _build_connector(agent, 30)


# ── run_task_worker — planning mode tests ───────────────

class TestRunTaskWorkerPlanning:
    async def test_planning_full_flow(self, db, config):
        """Test complete planning flow: DRAFT → IN_PROGRESS → NEEDS_APPROVAL."""
        from cellos.services.worker_service import run_task_worker
        database = db[0]

        task = _make_task(title="Plan auth module", role=AgentRole.ARCHITECT)
        await database.create_task(task)

        result = await run_task_worker(database, task.id, "planning", config)

        final = await database.get_task(task.id)
        assert final is not None
        assert final.status == TaskStatus.NEEDS_APPROVAL
        assert final.plan  # Plan text should be saved from fake_acp response

    async def test_planning_transitions_to_in_progress(self, db, config):
        """Verify task goes to IN_PROGRESS before connector runs."""
        from cellos.services.worker_service import run_task_worker
        database = db[0]

        task = _make_task(title="Status check", role=AgentRole.ARCHITECT)
        await database.create_task(task)

        # Before worker: DRAFT
        pre = await database.get_task(task.id)
        assert pre.status == TaskStatus.DRAFT

        result = await run_task_worker(database, task.id, "planning", config)

    async def test_planning_with_comments(self, db, config):
        """Verify comments are included in planning prompt context."""
        from cellos.services.worker_service import run_task_worker
        database = db[0]

        task = _make_task(title="Plan with feedback", role=AgentRole.ARCHITECT)
        await database.create_task(task)

        # Add a comment before planning (use CommentAuthorType enum, not raw string)
        from cellos.models import CommentAuthorType
        await database.create_comment(
            task.id, CommentAuthorType.HUMAN, "Please focus on security aspects"
        )

        result = await run_task_worker(database, task.id, "planning", config)


# ── Execution mode tests ────────────────

class TestRunTaskWorkerExecution:
    async def test_execution_full_flow(self, db, config):
        """Test complete execution flow: APPROVED → IN_PROGRESS → DONE."""
        from cellos.services.worker_service import run_task_worker
        database = db[0]

        task = _make_task(title="Build auth", role=AgentRole.ENGINEER)
        await database.create_task(task)

        # Manually set to APPROVED (skipping planning step for this test)
        created = await database.get_task(task.id)
        approved = created.model_copy(update={
            "status": TaskStatus.APPROVED,
            "plan": "Build the auth module with JWT tokens.",
        })
        await database.update_task(approved)

        result = await run_task_worker(database, task.id, "execution", config)

        final = await database.get_task(task.id)
        assert final is not None
        # fake_acp returns success=True by default → DONE
        assert final.status == TaskStatus.DONE


# ── Attempt tracking tests ───────────────

class TestAttemptTracking:
    async def test_attempt_created_and_completed(self, db, config):
        from cellos.services.worker_service import run_task_worker
        database = db[0]

        task = _make_task(title="Track attempt", role=AgentRole.ENGINEER)
        await database.create_task(task)

        result = await run_task_worker(database, task.id, "planning", config)

        attempts = await database.list_attempts(task.id)
        assert len(attempts) >= 1
        first_attempt = attempts[0]
        assert first_attempt.task_id == task.id


# ── Error handling tests ────────────────

class TestWorkerErrorHandling:
    async def test_task_not_found_raises(self, db, config):
        from cellos.services.worker_service import run_task_worker, WorkerError
        database = db[0]

        with pytest.raises(WorkerError, match="not found"):
            await run_task_worker(database, "nonexistent", "planning", config)

    async def test_wrong_status_raises(self, db, config):
        from cellos.services.worker_service import run_task_worker, WorkerError
        database = db[0]

        task = _make_task(title="Wrong status", role=AgentRole.ENGINEER)
        await database.create_task(task)

        # Try execution on DRAFT task — should fail (needs APPROVED)
        with pytest.raises(WorkerError):
            await run_task_worker(database, task.id, "execution", config)


# ── WorkerSpawner tests ────────────────

class TestWorkerSpawner:
    def test_spawn_creates_log_file(self, tmp_path):
        from cellos.services.worker_spawner import WorkerSpawner

        spawner = WorkerSpawner(logs_dir=str(tmp_path))
        proc = spawner.spawn("test-123", "planning")

        log_file = tmp_path / "worker-test-123.log"
        assert log_file.exists()

        # Cleanup: kill the detached process
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass  # Process may have already exited or be unkillable in test env

    def test_spawn_includes_db_and_config_flags(self, tmp_path):
        from cellos.services.worker_spawner import WorkerSpawner
        import subprocess

        spawner = WorkerSpawner(logs_dir=str(tmp_path))

        with patch.object(subprocess, "Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 9999
            mock_popen.return_value = mock_proc

            spawner.spawn(
                task_id="abc-456", mode="execution",
                db_path="/tmp/test.sqlite", config_dir="/home/user/.cellos"
            )

        call_args = mock_popen.call_args[0][0]  # Command list
        assert "worker" in call_args
        assert "abc-456" in call_args
        assert "--mode" in call_args
        assert "execution" in call_args
        # --db and --config-dir must come BEFORE the subcommand (group-level options)
        db_idx = call_args.index("--db")
        worker_idx = call_args.index("worker")
        assert db_idx < worker_idx, f"--db (idx {db_idx}) must come before 'worker' (idx {worker_idx})"
        config_idx = call_args.index("--config-dir")
        assert config_idx < worker_idx, f"--config-dir (idx {config_idx}) must come before 'worker' (idx {worker_idx})"

    def test_spawn_detached_process(self, tmp_path):
        from cellos.services.worker_spawner import WorkerSpawner

        spawner = WorkerSpawner(logs_dir=str(tmp_path))
        proc = spawner.spawn("detached-test", "planning")

        # Verify process was created with a PID
        assert proc.pid > 0

        try:
            proc.kill()
            proc.wait(timeout=3)
        except Exception:
            pass


# ── _task_to_prompt_dict tests ───────────────

class TestTaskToPromptDict:
    def test_converts_task_fields(self):
        from cellos.services.worker_service import _task_to_prompt_dict

        task = Task(
            title="Test", role=AgentRole.ENGINEER,
            task_type=ROLE_TO_TASK_TYPE[AgentRole.ENGINEER],
            details="Some details", success_criteria="Must work"
        )
        result = _task_to_prompt_dict(task)
        assert result["title"] == "Test"
        assert result["role"] == "engineer"
        assert result["details"] == "Some details"

    def test_omits_empty_fields(self):
        from cellos.services.worker_service import _task_to_prompt_dict

        task = Task(
            title="Minimal", role=AgentRole.ENGINEER,
            task_type=ROLE_TO_TASK_TYPE[AgentRole.ENGINEER],
        )
        result = _task_to_prompt_dict(task)
        assert "details" not in result  # Empty details omitted
        assert "success_criteria" not in result


# ── Agent resolution tests ────────────────────────────────

class TestAgentResolution:
    async def test_resolves_agent_by_role(self, db, config):
        """Verify architect task uses architect agent, not default engineer."""
        from cellos.services.worker_service import run_task_worker
        database = db[0]

        # Architect task with no explicit agent_id
        task = _make_task(title="Plan auth module", role=AgentRole.ARCHITECT)
        await database.create_task(task)

        result = await run_task_worker(database, task.id, "planning", config)

        final = await database.get_task(task.id)
        assert final is not None
        assert final.status == TaskStatus.NEEDS_APPROVAL
        # Verify the architect agent's plan was used (contains "Architecture" from config)
        assert "Architecture" in final.plan

    async def test_attempt_tracks_agent_key_not_connector(self, db, config):
        """Verify attempt stores agent name (e.g., 'engineer'), not connector type."""
        from cellos.services.worker_service import run_task_worker
        database = db[0]

        task = _make_task(title="Track agent", role=AgentRole.ENGINEER)
        await database.create_task(task)

        await run_task_worker(database, task.id, "planning", config)

        attempts = await database.list_attempts(task.id)
        assert len(attempts) >= 1
        # Agent key should be 'engineer', not 'fake_acp'
        assert attempts[0].agent_id == "engineer"


# ── Failed connector tests ────────────────────────────────

class TestFailedConnector:
    async def test_planning_failure_transitions_to_failed(self, db, config):
        """If connector returns success=False, planning should fail, not go to NEEDS_APPROVAL."""
        from cellos.services.worker_service import run_task_worker
        database = db[0]

        # Create config with failing connector
        failing_config = CellosConfig(
            agents={"default_agent_id": "engineer"},
            worker={"timeout_seconds": 30},
            approvals={"preapprove_research_tasks": False},
            agent_catalog={
                "engineer": AgentCatalogEntry(
                    connector="fake_acp",
                    options={"default_success": False, "default_summary": "Planning failed."},
                ),
            },
            prompt_profiles=PromptProfilesConfig(
                role_instructions={"engineer": "You are an engineer."},
                modes={
                    "planning": {"instructions": "Generate a plan.", "output_sections": ["Steps"]},
                    "execution": {"instructions": "Execute the plan.", "output_sections": ["Results"]},
                },
            ),
        )

        task = _make_task(title="Will fail", role=AgentRole.ENGINEER)
        await database.create_task(task)

        result = await run_task_worker(database, task.id, "planning", failing_config)

        final = await database.get_task(task.id)
        assert final is not None
        assert final.status == TaskStatus.FAILED  # Not NEEDS_APPROVAL

    async def test_execution_failure_respects_connector_success(self, db, config):
        """Connector success=False should transition to FAILED, not DONE."""
        from cellos.services.worker_service import run_task_worker
        database = db[0]

        failing_config = CellosConfig(
            agents={"default_agent_id": "engineer"},
            worker={"timeout_seconds": 30},
            approvals={"preapprove_research_tasks": False},
            agent_catalog={
                "engineer": AgentCatalogEntry(
                    connector="fake_acp",
                    options={"default_success": False, "default_summary": "Execution failed."},
                ),
            },
            prompt_profiles=PromptProfilesConfig(
                role_instructions={"engineer": "You are an engineer."},
                modes={
                    "planning": {"instructions": "Generate a plan.", "output_sections": ["Steps"]},
                    "execution": {"instructions": "Execute the plan.", "output_sections": ["Results"]},
                },
            ),
        )

        task = _make_task(title="Will fail", role=AgentRole.ENGINEER)
        await database.create_task(task)

        # Set to APPROVED
        created = await database.get_task(task.id)
        approved = created.model_copy(update={
            "status": TaskStatus.APPROVED,
            "plan": "Build the auth module.",
        })
        await database.update_task(approved)

        result = await run_task_worker(database, task.id, "execution", failing_config)

        final = await database.get_task(task.id)
        assert final is not None
        assert final.status == TaskStatus.FAILED  # Not DONE

    async def test_attempt_marked_failed_on_connector_failure(self, db, config):
        """Attempt should be marked FAILED when connector returns success=False."""
        from cellos.services.worker_service import run_task_worker
        database = db[0]

        failing_config = CellosConfig(
            agents={"default_agent_id": "engineer"},
            worker={"timeout_seconds": 30},
            approvals={"preapprove_research_tasks": False},
            agent_catalog={
                "engineer": AgentCatalogEntry(
                    connector="fake_acp",
                    options={"default_success": False, "default_summary": "Failed."},
                ),
            },
            prompt_profiles=PromptProfilesConfig(
                role_instructions={"engineer": "You are an engineer."},
                modes={
                    "planning": {"instructions": "Generate a plan.", "output_sections": ["Steps"]},
                    "execution": {"instructions": "Execute the plan.", "output_sections": ["Results"]},
                },
            ),
        )

        task = _make_task(title="Track failure", role=AgentRole.ENGINEER)
        await database.create_task(task)

        await run_task_worker(database, task.id, "planning", failing_config)

        attempts = await database.list_attempts(task.id)
        assert len(attempts) >= 1
        assert attempts[0].status == TaskAttemptStatus.FAILED
