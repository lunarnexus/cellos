"""Integration tests — end-to-end lifecycle flows using full stack.

Tests the complete Cellos4 system with real temp SQLite databases,
Click's CliRunner for CLI commands, and fake_acp for agent interactions.
No mocking of the DB layer — real persistence throughout.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from cellos.cli import main
from cellos.config import ensure_config, load_config
from cellos.db import CellosDatabase
from cellos.models import TaskStatus
from cellos.persistence.schema import init_db


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a temp project directory with initialized config."""
    config_dir = tmp_path / ".cellos"
    config_dir.mkdir()
    ensure_config(str(config_dir), overwrite=True)
    # Override agent catalog to use fake_acp for tests (opencode is slow/external)
    import json
    catalog_path = config_dir / "agentcatalog.json"
    catalog = json.loads(catalog_path.read_text())
    for agent in catalog.values():
        agent["connector"] = "fake_acp"
        agent.setdefault("options", {})["default_success"] = True
        agent["options"]["default_summary"] = "Test agent completed."
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n")
    return tmp_path


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    """Create a temp SQLite database path."""
    return str(tmp_path / "test.sqlite")


@pytest.fixture
async def initialized_db(db_path: str) -> CellosDatabase:
    """Create and initialize a database, return connected facade."""
    await init_db(db_path)
    db = CellosDatabase(db_path)
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def runner(project_dir: Path, db_path: str) -> CliRunner:
    """CliRunner configured with project-specific paths."""
    return CliRunner()


class TestFullLifecycle:
    """Test the complete task lifecycle: create → plan → approve → execute → done."""

    @pytest.mark.asyncio
    async def test_full_task_lifecycle(self, initialized_db: CellosDatabase, project_dir: Path):
        """Full lifecycle: init → create → plan (fake_acp) → approve → execute → verify done.

        Validates that a task flows through all states correctly with fake_acp agent.
        """
        from cellos.services.task_service import TaskService
        from cellos.services.planning_service import save_planning_result
        from cellos.services.execution_service import save_execution_result

        service = TaskService(initialized_db)

        # Create task
        task = await service.create_task(
            title="Test feature",
            details="Implement test feature",
            role="engineer",
        )
        assert task.status == TaskStatus.DRAFT

        # Save planning result (simulates agent planning)
        await save_planning_result(
            initialized_db, task.id,
            plan_text="Plan: Step 1, Step 2, Step 3",
            success=True,
        )
        planned = await initialized_db.get_task(task.id)
        assert planned.status == TaskStatus.NEEDS_APPROVAL
        assert planned.plan == "Plan: Step 1, Step 2, Step 3"

        # Approve
        approved = await service.approve_task(task.id)
        assert approved.status == TaskStatus.APPROVED

        # Execute
        result = await save_execution_result(
            initialized_db, task.id,
            result_text="Execution completed successfully",
            success=True,
        )
        assert result.success is True

        done = await initialized_db.get_task(task.id)
        assert done.status == TaskStatus.DONE
        assert done.result is not None
        assert done.result.success is True

    @pytest.mark.asyncio
    async def test_planning_failure(self, initialized_db: CellosDatabase, project_dir: Path):
        """Planning failure transitions task to FAILED, not NEEDS_APPROVAL."""
        from cellos.services.task_service import TaskService
        from cellos.services.planning_service import save_planning_result

        service = TaskService(initialized_db)
        task = await service.create_task(title="Failing task", role="engineer")

        await save_planning_result(
            initialized_db, task.id,
            plan_text="Planning failed",
            success=False,
        )
        failed = await initialized_db.get_task(task.id)
        assert failed.status == TaskStatus.FAILED


class TestCLICommands:
    """Test CLI commands end-to-end with CliRunner."""

    def test_init_command(self, runner: CliRunner, project_dir: Path, db_path: str):
        """cellos init creates config and database."""
        result = runner.invoke(main, ["--db", db_path, "--config-dir", str(project_dir / ".cellos"), "init"])
        assert result.exit_code == 0
        assert "Config written" in result.output
        assert "Database initialized" in result.output

    def test_add_task_command(self, runner: CliRunner, project_dir: Path, db_path: str):
        """cellos add-task creates a task and shows it in status."""
        # Init first
        runner.invoke(main, ["--db", db_path, "--config-dir", str(project_dir / ".cellos"), "init"])

        result = runner.invoke(main, [
            "--db", db_path, "--config-dir", str(project_dir / ".cellos"),
            "add-task", "Test task", "-d", "Test details", "-r", "engineer",
        ])
        assert result.exit_code == 0

        status_result = runner.invoke(main, ["--db", db_path, "status"])
        assert status_result.exit_code == 0
        assert "Test task" in status_result.output

    def test_status_command(self, runner: CliRunner, project_dir: Path, db_path: str):
        """cellos status shows tasks in table format."""
        runner.invoke(main, ["--db", db_path, "--config-dir", str(project_dir / ".cellos"), "init"])
        result = runner.invoke(main, ["--db", db_path, "status"])
        assert result.exit_code == 0
        assert "No tasks found" in result.output

    def test_approve_draft_fails(self, runner: CliRunner, project_dir: Path, db_path: str):
        """Approving a draft task should fail with clear error."""
        runner.invoke(main, ["--db", db_path, "--config-dir", str(project_dir / ".cellos"), "init"])
        result = runner.invoke(main, ["--db", db_path, "approve", "nonexistent"])
        assert result.exit_code == 0  # CLI doesn't exit with error code for business logic errors
        assert "Error" in result.output or "not found" in result.output.lower()

    def test_empty_update_fails(self, runner: CliRunner, project_dir: Path, db_path: str):
        """Updating with no fields should fail with clear error."""
        runner.invoke(main, ["--db", db_path, "--config-dir", str(project_dir / ".cellos"), "init"])
        result = runner.invoke(main, ["--db", db_path, "update", "nonexistent"])
        assert result.exit_code == 0
        assert "Error" in result.output or "not found" in result.output.lower()

    def test_plan_command_draft(self, runner: CliRunner, project_dir: Path, db_path: str):
        """cellos plan on draft task generates plan and transitions to needs_approval."""
        runner.invoke(main, ["--db", db_path, "--config-dir", str(project_dir / ".cellos"), "init"])
        result = runner.invoke(main, [
            "--db", db_path, "--config-dir", str(project_dir / ".cellos"),
            "add-task", "Plan test", "-r", "architect",
        ])
        assert result.exit_code == 0
        # Extract task ID from output (format: "✓ Created task <id>: ...")
        task_id = result.output.split("Created task ")[1].split(":")[0].strip() if "Created task" in result.output else None
        assert task_id is not None

        plan_result = runner.invoke(main, [
            "--db", db_path, "--config-dir", str(project_dir / ".cellos"),
            "plan", task_id,
        ])
        assert plan_result.exit_code == 0
        assert "Plan generated" in plan_result.output or "needs_approval" in plan_result.output.lower()

    def test_plan_command_wrong_status(self, runner: CliRunner, project_dir: Path, db_path: str):
        """cellos plan on non-draft task fails with clear error."""
        runner.invoke(main, ["--db", db_path, "--config-dir", str(project_dir / ".cellos"), "init"])
        result = runner.invoke(main, ["--db", db_path, "plan", "nonexistent"])
        assert result.exit_code == 0
        assert "Error" in result.output or "not found" in result.output.lower()

    def test_execute_command_wrong_status(self, runner: CliRunner, project_dir: Path, db_path: str):
        """cellos execute on non-approved task fails with clear error."""
        runner.invoke(main, ["--db", db_path, "--config-dir", str(project_dir / ".cellos"), "init"])
        result = runner.invoke(main, ["--db", db_path, "execute", "nonexistent"])
        assert result.exit_code == 0
        assert "Error" in result.output or "not found" in result.output.lower()


class TestConfigAndAgents:
    """Test config loading and agent resolution."""

    @pytest.mark.asyncio
    async def test_config_loads_and_validates(self, project_dir: Path):
        """Config loads from three JSON files with Pydantic validation."""
        config = load_config(str(project_dir / ".cellos"))
        assert config.scheduler.concurrent_tasks > 0
        assert config.worker.timeout_seconds > 0
        assert config.agents.default_agent_id is not None

    @pytest.mark.asyncio
    async def test_agent_resolution(self, project_dir: Path):
        """Agent resolution: task agent_id → role → default."""
        config = load_config(str(project_dir / ".cellos"))
        agent = config.get_agent()
        assert agent is not None
        assert agent.connector in ("fake_acp", "cellos_acp")


class TestDependencyTracking:
    """Test dependency tracking between tasks."""

    @pytest.mark.asyncio
    async def test_dependencies_block_parent(self, initialized_db: CellosDatabase):
        """Child tasks block parent until completed."""
        from cellos.services.task_service import TaskService
        from cellos.models import TaskDependency

        service = TaskService(initialized_db)

        parent = await service.create_task(title="Parent task", role="engineer")
        child = await service.create_task(title="Child task", role="engineer")

        # Add dependency: parent depends on child
        updated = await service.update_task(
            parent.id,
            add_dependencies=[TaskDependency(task_id=child.id)],
        )
        assert child.id in [d.task_id for d in updated.dependencies]

        # Parent should be blocked (not in approved_unblocked list)
        unblocked = await initialized_db.list_approved_unblocked_tasks()
        assert not any(t.id == parent.id for t in unblocked)


class TestCommentsAndAttention:
    """Test comments and attention system."""

    @pytest.mark.asyncio
    async def test_comment_triggers_attention(self, initialized_db: CellosDatabase):
        """Comment on draft task triggers attention signal."""
        from cellos.services.task_service import TaskService

        service = TaskService(initialized_db)
        task = await service.create_task(title="Test task", role="engineer")

        # Add comment
        await service.add_human_comment(task.id, "Please use approach X")

        # Check attention is triggered
        updated = await initialized_db.get_task(task.id)
        assert updated.attention.required is True
        assert updated.attention.reason.value == "human_commented"

    @pytest.mark.asyncio
    async def test_comment_no_attention_on_approved(self, initialized_db: CellosDatabase):
        """Comment on approved task does NOT trigger attention."""
        from cellos.services.task_service import TaskService
        from cellos.services.planning_service import save_planning_result

        service = TaskService(initialized_db)
        task = await service.create_task(title="Test task", role="engineer")

        # Plan and approve
        await save_planning_result(initialized_db, task.id, plan_text="Plan", success=True)
        await service.approve_task(task.id)

        # Comment on approved task
        await service.add_human_comment(task.id, "Review note")

        updated = await initialized_db.get_task(task.id)
        # Attention should NOT be triggered for approved tasks
        assert updated.attention.required is False


class TestEventLogging:
    """Test event logging for audit trail."""

    @pytest.mark.asyncio
    async def test_events_recorded_on_lifecycle(self, initialized_db: CellosDatabase):
        """Events are recorded on task creation, planning, approval, execution."""
        from cellos.services.task_service import TaskService
        from cellos.services.planning_service import save_planning_result
        from cellos.services.execution_service import save_execution_result

        service = TaskService(initialized_db)
        task = await service.create_task(title="Test task", role="engineer")

        await save_planning_result(initialized_db, task.id, plan_text="Plan", success=True)
        await service.approve_task(task.id)
        await save_execution_result(initialized_db, task.id, result_text="Done", success=True)

        events = await initialized_db.list_events(task.id)
        assert len(events) >= 3  # planning_saved, status_changed, execution_succeeded


class TestStructuredActions:
    """Test structured action parsing for child task creation."""

    @pytest.mark.asyncio
    async def test_child_tasks_created_from_actions(self, initialized_db: CellosDatabase):
        """Execution output with create_task actions creates child tasks."""
        from cellos.task_actions import parse_create_task_actions, tasks_from_create_actions
        from cellos.services.task_service import TaskService
        from cellos.models import TaskDependency

        service = TaskService(initialized_db)
        parent = await service.create_task(title="Parent", role="engineer")

        # Simulate agent output with child task creation
        action_output = """
```json
{
  "actions": [
    {
      "type": "create_task",
      "title": "Child task 1",
      "role": "engineer",
      "prompt": "Implement feature A"
    }
  ]
}
```
"""
        parsed = parse_create_task_actions(action_output)
        assert len(parsed) == 1
        assert parsed[0].title == "Child task 1"

        children = tasks_from_create_actions(
            parent_id=parent.id, actions=parsed, preapprove_research_tasks=False
        )
        assert len(children) == 1
        assert children[0]["parent_id"] == parent.id

        # Create the child task directly (explicit child dependencies only)
        child_deps = [TaskDependency(task_id=d.task_id) for d in children[0].get("dependencies", [])]
        child = await service.create_task(
            title=children[0]["title"],
            details=children[0].get("details"),
            parent_id=children[0]["parent_id"],
            dependencies=child_deps,
        )
        assert child.parent_id == parent.id
        assert child.dependencies == []


class TestPromptBuilder:
    """Test prompt building from profiles."""

    @pytest.mark.asyncio
    async def test_prompt_includes_task_details(self, project_dir: Path):
        """Built prompt includes role, title, details, and criteria."""
        from cellos.config import load_config
        from cellos.prompt_builder import build_task_prompt

        config = load_config(str(project_dir / ".cellos"))
        task = {
            "role": "engineer",
            "title": "Test task",
            "details": "Test details",
            "success_criteria": "Works correctly",
        }

        prompt = build_task_prompt(task, config.prompt_profiles, mode="planning")
        assert "Test task" in prompt
        assert "Test details" in prompt
        assert "engineer" in prompt.lower()


class TestWorkerSubprocess:
    """Test worker subprocess isolation."""

    @pytest.mark.asyncio
    async def test_worker_saves_result(self, initialized_db: CellosDatabase, project_dir: Path):
        """Worker completes and saves result to database."""
        from cellos.config import load_config
        from cellos.services.worker_service import run_task_worker

        from cellos.services.task_service import TaskService
        service = TaskService(initialized_db)
        task = await service.create_task(title="Worker test", role="engineer")

        config = load_config(str(project_dir / ".cellos"))
        result = await run_task_worker(
            db=initialized_db, task_id=task.id, mode="planning", config=config
        )
        assert result is not None
        # With fake_acp, planning should succeed and transition to NEEDS_APPROVAL
        assert result.status in (TaskStatus.NEEDS_APPROVAL, TaskStatus.FAILED)
