"""CLI integration tests — end-to-end coverage of all 8 commands via CliRunner.

Tests use real SQLite databases in temp directories (no mocking). Each test 
initializes a fresh DB to avoid cross-test contamination.
"""

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from cellos.cli import main


@pytest.fixture()
def runner(tmp_path):
    """CliRunner with isolated config and DB paths."""
    db = str(tmp_path / "test.sqlite")
    config_dir = str(tmp_path)
    return CliRunner(), tmp_path, db, config_dir


# ── init ────────────────────────────────────────────────────────────────

def test_init_creates_config_and_db(runner):
    cli_runner, tmp_path, db, config_dir = runner

    result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert result.exit_code == 0
    assert (tmp_path / "config.json").exists()
    assert (tmp_path / "agentcatalog.json").exists()
    assert (tmp_path / "promptprofiles.json").exists()
    assert Path(db).exists()


def test_init_overwrite(runner):
    cli_runner, tmp_path, db, config_dir = runner

    # First init
    result1 = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert result1.exit_code == 0

    cfg_before = (tmp_path / "config.json").read_text()

    # Second init without overwrite — should skip existing files
    result2 = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert result2.exit_code == 0
    assert (tmp_path / "config.json").read_text() == cfg_before

    # With overwrite — replaces files
    result3 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "init", "--overwrite"]
    )
    assert result3.exit_code == 0


# ── add-task ────────────────────────────────────────────────────────────

def test_add_task_basic(runner):
    cli_runner, tmp_path, db, config_dir = runner

    # Init first
    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    result = cli_runner.invoke(
        main,
        [
            "--config-dir", config_dir,
            "--db", db,
            "add-task", "Build login page", "-d", "Implement JWT auth"
        ],
    )
    assert result.exit_code == 0
    assert "✓ Created task" in result.output


def test_add_task_with_role_and_type(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    result = cli_runner.invoke(
        main,
        [
            "--config-dir", config_dir,
            "--db", db,
            "add-task", "Design schema", "-r", "architect"
        ],
    )
    assert result.exit_code == 0
    # Architect role should infer architecture type
    assert "Type: architecture" in result.output


def test_add_task_with_success_failure_criteria(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    result = cli_runner.invoke(
        main,
        [
            "--config-dir", config_dir,
            "--db", db,
            "add-task", "Test module", "-s", "All tests pass", "-f", "Tests fail"
        ],
    )
    assert result.exit_code == 0


def test_add_task_with_dependencies(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    # Create parent task first
    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Parent task"]
    )
    assert r1.exit_code == 0
    # Extract ID from output — format: "✓ Created task <id>: ..."
    parent_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    result = cli_runner.invoke(
        main,
        [
            "--config-dir", config_dir,
            "--db", db,
            "add-task", "Child task", "--depends", parent_id
        ],
    )
    assert result.exit_code == 0


def test_add_child_task_with_parent_link(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Parent task"]
    )
    assert r1.exit_code == 0
    parent_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    result = cli_runner.invoke(
        main,
        [
            "--config-dir", config_dir,
            "--db", db,
            "add-task", "Child task", "--parent", parent_id
        ],
    )
    assert result.exit_code == 0
    assert f"Parent: {parent_id}" in result.output


def test_add_child_task_with_missing_parent_fails(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    result = cli_runner.invoke(
        main,
        [
            "--config-dir", config_dir,
            "--db", db,
            "add-task", "Child task", "--parent", "missing123"
        ],
    )
    assert result.exit_code == 1
    assert "Task missing123 not found" in result.output


# ── status ──────────────────────────────────────────────────────────────

def test_status_before_init_fails_cleanly(runner):
    cli_runner, tmp_path, db, config_dir = runner

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "status"]
    )
    assert result.exit_code == 1
    assert result.exception is not None
    assert "Database not initialized" in result.output
    assert "Run 'cellos init' to create them" in result.output
    assert "Traceback" not in result.output


def test_status_empty(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "status"]
    )
    assert result.exit_code == 0
    assert "No tasks found" in result.output


def test_status_with_tasks(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Task one"]
    )
    cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Task two"]
    )

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "status"]
    )
    assert result.exit_code == 0
    assert "Total: 2 tasks" in result.output


def test_status_filter(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Draft task"]
    )

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "status", "-s", "draft"]
    )
    assert result.exit_code == 0
    assert "Total: 1 task" in result.output


def test_inbox_empty(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "inbox"]
    )
    assert result.exit_code == 0
    assert "Inbox empty" in result.output


def test_inbox_lists_tasks_requiring_attention(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Inbox task"]
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    comment_result = cli_runner.invoke(
        main,
        ["--config-dir", config_dir, "--db", db, "comment", task_id, "-m", "Need review"],
    )
    assert comment_result.exit_code == 0

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "inbox"]
    )
    assert result.exit_code == 0
    assert "Inbox task" in result.output
    assert "⚠️" in result.output
    assert "Total: 1 task needs attention" in result.output


def test_blocked_empty(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "blocked"]
    )
    assert result.exit_code == 0
    assert "No blocked tasks" in result.output


def test_blocked_lists_blocked_tasks(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Blocked list task"]
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    block_result = cli_runner.invoke(
        main,
        ["--config-dir", config_dir, "--db", db, "block", task_id, "--reason", "waiting on vendor"],
    )
    assert block_result.exit_code == 0

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "blocked"]
    )
    assert result.exit_code == 0
    assert "Blocked list task" in result.output
    assert "blocked" in result.output
    assert "⚠️" in result.output
    assert "Total: 1 blocked task" in result.output


def test_ready_empty(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "ready"]
    )
    assert result.exit_code == 0
    assert "No ready tasks found" in result.output


def test_ready_shows_approved_unblocked_execution_task(runner):
    import asyncio

    from cellos.db import CellosDatabase
    from cellos.models import TaskStatus

    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Ready task"]
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    async def _seed_approved():
        database = CellosDatabase(db)
        await database.connect()
        try:
            task = await database.get_task(task_id)
            assert task is not None
            await database.update_task(task.model_copy(update={"status": TaskStatus.APPROVED}))
        finally:
            await database.close()

    asyncio.run(_seed_approved())

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "ready"]
    )
    assert result.exit_code == 0
    assert "Ready task" in result.output
    assert "approved" in result.output
    assert "Total ready: 1 task" in result.output


def test_ready_excludes_approved_task_with_unsatisfied_dependency(runner):
    import asyncio

    from cellos.db import CellosDatabase
    from cellos.models import TaskStatus

    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    dep = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Dependency"]
    )
    assert dep.exit_code == 0
    dep_id = dep.output.split("Created task ")[1].split(":")[0].strip()

    dependent = cli_runner.invoke(
        main,
        [
            "--config-dir", config_dir,
            "--db", db,
            "add-task", "Dependent task", "--depends", dep_id,
        ],
    )
    assert dependent.exit_code == 0
    task_id = dependent.output.split("Created task ")[1].split(":")[0].strip()

    async def _seed_approved():
        database = CellosDatabase(db)
        await database.connect()
        try:
            task = await database.get_task(task_id)
            assert task is not None
            await database.update_task(task.model_copy(update={"status": TaskStatus.APPROVED}))
        finally:
            await database.close()

    asyncio.run(_seed_approved())

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "ready"]
    )
    assert result.exit_code == 0
    assert "Dependent task" not in result.output


def test_ready_excludes_approved_architect_task(runner):
    import asyncio

    from cellos.db import CellosDatabase
    from cellos.models import TaskStatus

    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    r1 = cli_runner.invoke(
        main,
        ["--config-dir", config_dir, "--db", db, "add-task", "Architect task", "--role", "architect"],
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    async def _seed_approved():
        database = CellosDatabase(db)
        await database.connect()
        try:
            task = await database.get_task(task_id)
            assert task is not None
            await database.update_task(task.model_copy(update={"status": TaskStatus.APPROVED}))
        finally:
            await database.close()

    asyncio.run(_seed_approved())

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "ready"]
    )
    assert result.exit_code == 0
    assert "Architect task" not in result.output


def test_ready_excludes_blocked_task(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Blocked ready task"]
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    block_result = cli_runner.invoke(
        main,
        ["--config-dir", config_dir, "--db", db, "block", task_id, "--reason", "paused"],
    )
    assert block_result.exit_code == 0

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "ready"]
    )
    assert result.exit_code == 0
    assert "Blocked ready task" not in result.output


def test_review_empty(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "review"]
    )
    assert result.exit_code == 0
    assert "No review tasks found" in result.output


def test_review_includes_needs_approval_task(runner):
    import asyncio

    from cellos.db import CellosDatabase
    from cellos.models import AttentionMetadata, AttentionReason, TaskStatus

    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Plan review task"]
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    async def _seed_review_state():
        database = CellosDatabase(db)
        await database.connect()
        try:
            task = await database.get_task(task_id)
            assert task is not None
            updated = task.model_copy(update={
                "status": TaskStatus.NEEDS_APPROVAL,
                "attention": AttentionMetadata.required_attention(
                    AttentionReason.PLANNING_COMPLETE,
                    "Plan generated and ready for approval",
                ),
            })
            await database.update_task(updated)
        finally:
            await database.close()

    asyncio.run(_seed_review_state())

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "review"]
    )
    assert result.exit_code == 0
    assert "Plan review task" in result.output
    assert "needs_approval" in result.output
    assert "Total review: 1 task" in result.output


def test_review_includes_execution_failure_attention(runner):
    import asyncio

    from cellos.db import CellosDatabase
    from cellos.models import AttentionMetadata, AttentionReason, TaskStatus

    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Execution review task"]
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    async def _seed_execution_review():
        database = CellosDatabase(db)
        await database.connect()
        try:
            task = await database.get_task(task_id)
            assert task is not None
            updated = task.model_copy(update={
                "status": TaskStatus.APPROVED,
                "attention": AttentionMetadata.required_attention(
                    AttentionReason.EXECUTION_FAILED,
                    "Worker failed in execution mode",
                ),
            })
            await database.update_task(updated)
        finally:
            await database.close()

    asyncio.run(_seed_execution_review())

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "review"]
    )
    assert result.exit_code == 0
    assert "Execution review task" in result.output
    assert "approved" in result.output


def test_review_excludes_non_review_attention(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Inbox-only task"]
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    comment_result = cli_runner.invoke(
        main,
        ["--config-dir", config_dir, "--db", db, "comment", task_id, "-m", "Need input"],
    )
    assert comment_result.exit_code == 0

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "review"]
    )
    assert result.exit_code == 0
    assert "Inbox-only task" not in result.output


def test_recent_failures_empty(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "recent-failures"]
    )
    assert result.exit_code == 0
    assert "No recent failed attempts" in result.output


def test_recent_failures_lists_newest_failed_attempts(runner):
    import asyncio

    from cellos.db import CellosDatabase
    from cellos.models import TaskStatus

    cli_runner, tmp_path, db, config_dir = runner
    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    first = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Older failure task"]
    )
    second = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Newer failure task"]
    )
    assert first.exit_code == 0
    assert second.exit_code == 0
    first_id = first.output.split("Created task ")[1].split(":")[0].strip()
    second_id = second.output.split("Created task ")[1].split(":")[0].strip()

    async def _seed_attempts():
        database = CellosDatabase(db)
        await database.connect()
        try:
            a1 = await database.create_attempt(first_id, mode="execution", agent_id="engineer")
            await database.update_attempt(a1.id, TaskStatus.FAILED, error_message="older boom")
            a2 = await database.create_attempt(second_id, mode="planning", agent_id="architect")
            await database.update_attempt(a2.id, TaskStatus.FAILED, error_message="newer boom")
        finally:
            await database.close()

    asyncio.run(_seed_attempts())

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "recent-failures"]
    )
    assert result.exit_code == 0
    assert first_id in result.output
    assert second_id in result.output
    assert "older boom" in result.output
    assert "newer boom" in result.output
    assert result.output.index(second_id) < result.output.index(first_id)
    assert "Total failed attempts shown: 2" in result.output


def test_recent_failures_honors_limit(runner):
    import asyncio

    from cellos.db import CellosDatabase
    from cellos.models import TaskStatus

    cli_runner, tmp_path, db, config_dir = runner
    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    task_ids = []
    for title in ["Failure one", "Failure two", "Failure three"]:
        created = cli_runner.invoke(
            main, ["--config-dir", config_dir, "--db", db, "add-task", title]
        )
        assert created.exit_code == 0
        task_ids.append(created.output.split("Created task ")[1].split(":")[0].strip())

    async def _seed_attempts():
        database = CellosDatabase(db)
        await database.connect()
        try:
            for idx, task_id in enumerate(task_ids, start=1):
                attempt = await database.create_attempt(task_id, mode="execution", agent_id=f"agent-{idx}")
                await database.update_attempt(attempt.id, TaskStatus.FAILED, error_message=f"boom-{idx}")
        finally:
            await database.close()

    asyncio.run(_seed_attempts())

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "recent-failures", "--limit", "2"]
    )
    assert result.exit_code == 0
    assert "Total failed attempts shown: 2" in result.output


def test_daemon_status_missing(runner):
    cli_runner, tmp_path, db, config_dir = runner

    result = cli_runner.invoke(main, ["daemon-status"])
    assert result.exit_code == 0
    assert "No daemon status found" in result.output


def test_daemon_status_reads_live_status_file(runner):
    cli_runner, tmp_path, db, config_dir = runner

    with cli_runner.isolated_filesystem(temp_dir=str(tmp_path.parent)):
        cwd = Path.cwd()
        status_dir = cwd / ".cellos"
        status_dir.mkdir(parents=True, exist_ok=True)
        (status_dir / "daemon_status.json").write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "state": "running",
                    "started_at": "2026-06-30T16:00:00+00:00",
                    "last_heartbeat_at": "2026-06-30T16:01:00+00:00",
                    "concurrent_limit": 4,
                    "auto_sync_enabled": False,
                    "workdir": str(cwd),
                    "running_workers": [
                        {
                            "task_id": "task123",
                            "mode": "execution",
                            "pid": 4321,
                            "log_path": str(cwd / "logs" / "worker-task123.log"),
                            "started_at": "2026-06-30T16:00:30+00:00",
                        }
                    ],
                }
            )
        )
        result = cli_runner.invoke(main, ["daemon-status"])

    assert result.exit_code == 0
    assert "State: running" in result.output
    assert "PID:" in result.output
    assert "Tracked workers: 1" in result.output
    assert "task123" in result.output
    assert "execution" in result.output


def test_deps_missing_task_fails(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "deps", "missing123"]
    )
    assert result.exit_code == 1
    assert "Task missing123 not found" in result.output


def test_deps_shows_direct_relationships(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    upstream = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Upstream dependency"]
    )
    focus = cli_runner.invoke(
        main,
        [
            "--config-dir", config_dir,
            "--db", db,
            "add-task", "Focus task", "--depends",
            upstream.output.split("Created task ")[1].split(":")[0].strip(),
        ],
    )
    assert upstream.exit_code == 0
    assert focus.exit_code == 0

    focus_id = focus.output.split("Created task ")[1].split(":")[0].strip()

    downstream = cli_runner.invoke(
        main,
        [
            "--config-dir", config_dir,
            "--db", db,
            "add-task", "Downstream dependent", "--depends", focus_id,
        ],
    )
    assert downstream.exit_code == 0

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "deps", focus_id]
    )
    assert result.exit_code == 0
    assert "Parent:" in result.output
    assert "- none" in result.output
    assert "Depends on:" in result.output
    assert "Upstream dependency" in result.output
    assert "unsatisfied" in result.output
    assert "Blocks:" in result.output
    assert "Downstream dependent" in result.output
    assert "Children:" in result.output
    assert "- none" in result.output


def test_deps_shows_child_and_no_parent(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    root = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Root task"]
    )
    assert root.exit_code == 0
    root_id = root.output.split("Created task ")[1].split(":")[0].strip()

    child = cli_runner.invoke(
        main,
        ["--config-dir", config_dir, "--db", db, "add-task", "Leaf child", "--parent", root_id],
    )
    assert child.exit_code == 0

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "deps", root_id]
    )
    assert result.exit_code == 0
    assert "Parent:" in result.output
    assert "- none" in result.output
    assert "Children:" in result.output
    assert "Leaf child" in result.output


def test_tree_missing_task_fails(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "tree", "missing123"]
    )
    assert result.exit_code == 1
    assert "Task missing123 not found" in result.output


def test_tree_shows_root_subtree(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    root = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Root task"]
    )
    assert root.exit_code == 0
    root_id = root.output.split("Created task ")[1].split(":")[0].strip()

    child = cli_runner.invoke(
        main,
        ["--config-dir", config_dir, "--db", db, "add-task", "Child task", "--parent", root_id],
    )
    assert child.exit_code == 0
    child_id = child.output.split("Created task ")[1].split(":")[0].strip()

    grandchild = cli_runner.invoke(
        main,
        ["--config-dir", config_dir, "--db", db, "add-task", "Grandchild task", "--parent", child_id],
    )
    assert grandchild.exit_code == 0

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "tree", root_id]
    )
    assert result.exit_code == 0
    assert "Ancestor path:" in result.output
    assert "- none" in result.output
    assert "Tree:" in result.output
    assert "Root task" in result.output
    assert "Child task" in result.output
    assert "Grandchild task" in result.output


def test_tree_shows_ancestor_path_and_focus(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    root = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Root task"]
    )
    assert root.exit_code == 0
    root_id = root.output.split("Created task ")[1].split(":")[0].strip()

    child = cli_runner.invoke(
        main,
        ["--config-dir", config_dir, "--db", db, "add-task", "Child task", "--parent", root_id],
    )
    assert child.exit_code == 0
    child_id = child.output.split("Created task ")[1].split(":")[0].strip()

    grandchild = cli_runner.invoke(
        main,
        ["--config-dir", config_dir, "--db", db, "add-task", "Grandchild task", "--parent", child_id],
    )
    assert grandchild.exit_code == 0
    grandchild_id = grandchild.output.split("Created task ")[1].split(":")[0].strip()

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "tree", child_id]
    )
    assert result.exit_code == 0
    assert "Ancestor path:" in result.output
    assert root_id in result.output
    assert "Root task" in result.output
    assert child_id in result.output
    assert "Child task  *" in result.output
    assert grandchild_id in result.output
    assert "Grandchild task" in result.output


# ── detail ──────────────────────────────────────────────────────────────

def test_detail_task(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    r1 = cli_runner.invoke(
        main,
        [
            "--config-dir", config_dir,
            "--db", db,
            "add-task", "Detail test task", "-d", "Test details here"
        ],
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "detail", task_id]
    )
    assert result.exit_code == 0
    assert "Detail test task" in result.output


def test_detail_nonexistent(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "detail", "nonexistent"]
    )
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


# ── approve ─────────────────────────────────────────────────────────────

def test_approve_draft_fails(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Draft task"]
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "approve", task_id]
    )
    assert result.exit_code == 1
    assert "draft" in result.output.lower()


# ── comment ─────────────────────────────────────────────────────────────

def test_comment_on_task(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Comment target"]
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    result = cli_runner.invoke(
        main,
        [
            "--config-dir", config_dir,
            "--db", db,
            "comment", task_id, "-m", "Please use bcrypt"
        ],
    )
    assert result.exit_code == 0
    assert "Comment added" in result.output


# ── events ──────────────────────────────────────────────────────────────

def test_events_empty(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Events test"]
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "events", task_id]
    )
    assert result.exit_code == 0


def test_runs_empty(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Runs test"]
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "runs", task_id]
    )
    assert result.exit_code == 0
    assert "No attempts found" in result.output


def test_runs_shows_attempt_history(runner):
    import asyncio

    from cellos.db import CellosDatabase
    from cellos.models import TaskStatus

    cli_runner, tmp_path, db, config_dir = runner
    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Attempted task"]
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    async def _seed_attempt():
        database = CellosDatabase(db)
        await database.connect()
        try:
            attempt = await database.create_attempt(task_id, mode="execution", agent_id="engineer")
            await database.update_attempt(attempt.id, TaskStatus.FAILED, error_message="boom")
        finally:
            await database.close()

    asyncio.run(_seed_attempt())

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "runs", task_id]
    )
    assert result.exit_code == 0
    assert "execution" in result.output
    assert "engineer" in result.output
    assert "boom" in result.output


def test_retry_failed_execution_task(runner):
    import asyncio

    from cellos.db import CellosDatabase
    from cellos.models import TaskStatus

    cli_runner, tmp_path, db, config_dir = runner
    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Retry target"]
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    async def _seed_failed_execution():
        database = CellosDatabase(db)
        await database.connect()
        try:
            task = await database.get_task(task_id)
            assert task is not None
            await database.update_task(task.model_copy(update={"status": TaskStatus.FAILED}))
            attempt = await database.create_attempt(task_id, mode="execution", agent_id="engineer")
            await database.update_attempt(attempt.id, TaskStatus.FAILED, error_message="boom")
        finally:
            await database.close()

    asyncio.run(_seed_failed_execution())

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "retry", task_id]
    )
    assert result.exit_code == 0
    assert "Retried task" in result.output
    assert "approved" in result.output


def test_retry_non_failed_task_rejected(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Retry target"]
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "retry", task_id]
    )
    assert result.exit_code == 1
    assert "Cannot retry task in status 'draft'" in result.output


def test_recover_in_progress_execution_task(runner):
    import asyncio

    from cellos.db import CellosDatabase
    from cellos.models import TaskStatus

    cli_runner, tmp_path, db, config_dir = runner
    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Recover target"]
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    async def _seed_in_progress_execution():
        database = CellosDatabase(db)
        await database.connect()
        try:
            task = await database.get_task(task_id)
            assert task is not None
            await database.update_task(task.model_copy(update={"status": TaskStatus.IN_PROGRESS}))
            await database.create_attempt(task_id, mode="execution", agent_id="engineer")
        finally:
            await database.close()

    asyncio.run(_seed_in_progress_execution())

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "recover", task_id]
    )
    assert result.exit_code == 0
    assert "Recovered task" in result.output
    assert "approved" in result.output

    events_result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "events", task_id]
    )
    assert events_result.exit_code == 0
    assert "operator_recovered" in events_result.output
    assert "task_recovered" in events_result.output


def test_recover_non_in_progress_rejected(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Recover target"]
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "recover", task_id]
    )
    assert result.exit_code == 1
    assert "Cannot recover task in status 'draft'" in result.output


def test_block_task_and_unblock_to_approved(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Blocked target"]
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    blocked = cli_runner.invoke(
        main,
        ["--config-dir", config_dir, "--db", db, "block", task_id, "--reason", "waiting on vendor"],
    )
    assert blocked.exit_code == 0
    assert "Blocked task" in blocked.output
    assert "blocked" in blocked.output

    unblocked = cli_runner.invoke(
        main,
        ["--config-dir", config_dir, "--db", db, "unblock", task_id, "--to", "approved"],
    )
    assert unblocked.exit_code == 0
    assert "Unblocked task" in unblocked.output
    assert "approved" in unblocked.output

    events_result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "events", task_id]
    )
    assert events_result.exit_code == 0
    assert "operator_blocked" in events_result.output
    assert "operator_unblocked" in events_result.output


def test_block_in_progress_rejected_cli(runner):
    import asyncio

    from cellos.db import CellosDatabase
    from cellos.models import TaskStatus

    cli_runner, tmp_path, db, config_dir = runner
    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Busy target"]
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    async def _seed_in_progress():
        database = CellosDatabase(db)
        await database.connect()
        try:
            task = await database.get_task(task_id)
            assert task is not None
            await database.update_task(task.model_copy(update={"status": TaskStatus.IN_PROGRESS}))
        finally:
            await database.close()

    asyncio.run(_seed_in_progress())

    result = cli_runner.invoke(
        main,
        ["--config-dir", config_dir, "--db", db, "block", task_id, "--reason", "stop"],
    )
    assert result.exit_code == 1
    assert "Cannot block task in status 'in_progress'" in result.output


def test_unblock_non_blocked_rejected_cli(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Free target"]
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    result = cli_runner.invoke(
        main,
        ["--config-dir", config_dir, "--db", db, "unblock", task_id, "--to", "approved"],
    )
    assert result.exit_code == 1
    assert "Cannot unblock task in status 'draft'" in result.output


# ── update ──────────────────────────────────────────────────────────────

def test_update_title(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Original title"]
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "update", task_id, "--title", "New title"]
    )
    assert result.exit_code == 0
    assert "Updated task" in result.output


def test_update_empty_fails(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Update target"]
    )
    assert r1.exit_code == 0
    task_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "update", task_id]
    )
    assert result.exit_code == 1
    assert "no fields" in result.output.lower() or "error" in result.output.lower()


def test_update_add_remove_dep(runner):
    cli_runner, tmp_path, db, config_dir = runner

    cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])

    # Create two tasks
    r1 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Task A"]
    )
    assert r1.exit_code == 0
    task_a_id = r1.output.split("Created task ")[1].split(":")[0].strip()

    r2 = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "add-task", "Task B"]
    )
    assert r2.exit_code == 0
    task_b_id = r2.output.split("Created task ")[1].split(":")[0].strip()

    # Add dependency A -> B
    result = cli_runner.invoke(
        main, ["--config-dir", config_dir, "--db", db, "update", task_a_id, "--add-dep", task_b_id]
    )
    assert result.exit_code == 0
    assert "added deps" in result.output.lower()


# ── Worker command ────────────────────────────────────────────

class TestWorkerCommand:
    async def test_worker_command_exists(self):
        from cellos.cli import main
        assert "worker" in [cmd.name for cmd in main.commands.values()]

    async def test_worker_command_requires_mode(self, tmp_path):
        from click.testing import CliRunner
        from cellos.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["--db", str(tmp_path / "t.sqlite"), "worker", "fake-id"])
        assert result.exit_code != 0  # Should fail without --mode

    def test_worker_command_planning_e2e(self, tmp_path):
        """End-to-end: init → add-task → worker planning → verify result."""
        from click.testing import CliRunner
        from cellos.cli import main
        from cellos.persistence.schema import init_db
        from cellos.config import ensure_config
        import asyncio

        # Init config and DB (sync wrapper for async init)
        asyncio.run(init_db(tmp_path / "test.sqlite"))
        ensure_config(str(tmp_path), overwrite=True)
        # Override to use fake_acp for tests
        import json
        catalog_path = tmp_path / "agentcatalog.json"
        catalog = json.loads(catalog_path.read_text())
        valid_plan = """## Success Criteria\n- ship the requested change\n## Constraints / Failure Criteria\n- do not break existing behavior\n## Dependencies\n- confirm prerequisite task state\n## Missing Context\n- note open questions explicitly\n## Decomposition\n1. architect — define the implementation slices\n## Review Points\n- human review before execution\n"""
        for agent in catalog.values():
            agent["connector"] = "fake_acp"
            agent.setdefault("options", {})["default_success"] = True
            agent["options"]["default_summary"] = valid_plan
        catalog_path.write_text(json.dumps(catalog, indent=2) + "\n")

        runner = CliRunner()

        # Add a task
        result = runner.invoke(main, [
            "--db", str(tmp_path / "test.sqlite"),
            "--config-dir", str(tmp_path),
            "add-task", "Plan something", "-r", "architect"
        ])
        assert result.exit_code == 0, f"add-task failed: {result.output}"
        # Extract task ID from output
        task_id = None
        for line in result.output.split("\n"):
            if "Created task" in line:
                task_id = line.split("task")[1].split(":")[0].strip()
                break
        assert task_id is not None

        # Run worker in planning mode
        result = runner.invoke(main, [
            "--db", str(tmp_path / "test.sqlite"),
            "--config-dir", str(tmp_path),
            "worker", task_id, "--mode", "planning"
        ])
        assert result.exit_code == 0, f"worker failed: {result.output}"
        assert "Worker completed" in result.output

        # Verify task is now in NEEDS_APPROVAL
        result = runner.invoke(main, [
            "--db", str(tmp_path / "test.sqlite"),
            "--config-dir", str(tmp_path),
            "status"
        ])
        assert result.exit_code == 0
        assert "needs_approval" in result.output.lower()


# ── integration commands ────────────────────────────────────────────────

def test_pmcon_help(runner):
    cli_runner, tmp_path, db, config_dir = runner

    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    result = cli_runner.invoke(main, [
        "--config-dir", config_dir, "--db", db, "pmcon", "--help"
    ])
    assert result.exit_code == 0
    assert "setup" in result.output
    assert "sync" in result.output
    assert "status" in result.output


def test_pmcon_list(runner):
    cli_runner, tmp_path, db, config_dir = runner

    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    result = cli_runner.invoke(main, [
        "--config-dir", config_dir, "--db", db, "pmcon", "list"
    ])
    assert result.exit_code == 0
    assert "example" in result.output


def test_pmcon_status_unknown_provider(runner):
    cli_runner, tmp_path, db, config_dir = runner

    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    result = cli_runner.invoke(main, [
        "--config-dir", config_dir, "--db", db, "pmcon", "status", "wekan"
    ])
    assert result.exit_code == 1
    assert "Unknown integration provider 'wekan'" in result.output



def test_pmcon_status_vikunja_provider(runner, monkeypatch):
    cli_runner, tmp_path, db, config_dir = runner

    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    monkeypatch.setenv("VIKUNJA_BASE_URL", "https://vikunja.example")
    monkeypatch.setenv("VIKUNJA_API_TOKEN", "secret-token")

    result = cli_runner.invoke(main, [
        "--config-dir", config_dir, "--db", db, "pmcon", "status", "vikunja"
    ])
    assert result.exit_code == 0
    assert "vikunja" in result.output.lower()


def test_pmcon_status_example_provider(runner):
    cli_runner, tmp_path, db, config_dir = runner

    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    result = cli_runner.invoke(main, [
        "--config-dir", config_dir, "--db", db, "pmcon", "status", "example"
    ])
    assert result.exit_code == 0
    assert "example" in result.output.lower()


def test_pmcon_setup_passes_clean_flag(runner, monkeypatch):
    cli_runner, tmp_path, db, config_dir = runner

    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    captured = {}

    class FakeProvider:
        def __init__(self):
            self._db = None

        async def setup(self, clean: bool = False):
            captured["clean"] = clean
            from cellos.integrations.base import SetupResult
            return SetupResult(target_id="17", mappings={"to-do": "1"}, details={})

    monkeypatch.setattr("cellos.integrations.registry.load_provider", lambda *args, **kwargs: FakeProvider())

    result = cli_runner.invoke(main, [
        "--config-dir", config_dir, "--db", db, "pmcon", "setup", "vikunja", "--clean"
    ])
    assert result.exit_code == 0
    assert captured["clean"] is True


def test_pmcon_setup_persists_vikunja_bucket_mapping(runner, monkeypatch):
    cli_runner, tmp_path, db, config_dir = runner

    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    class FakeProvider:
        def __init__(self):
            self._db = None

        async def setup(self, clean: bool = False):
            from cellos.integrations.base import SetupResult
            return SetupResult(
                target_id="17",
                mappings={"to-do": "4", "doing": "5", "done": "6"},
                details={},
            )

    monkeypatch.setattr("cellos.integrations.registry.load_provider", lambda *args, **kwargs: FakeProvider())

    result = cli_runner.invoke(main, [
        "--config-dir", config_dir, "--db", db, "pmcon", "setup", "vikunja", "--clean"
    ])
    assert result.exit_code == 0

    saved = json.loads((Path(config_dir) / "config.json").read_text())
    assert saved["integrations"]["providers"]["vikunja"]["bucket_map"] == {
        "to-do": "4",
        "doing": "5",
        "done": "6",
    }


def test_pmcon_setup_enables_provider_in_config(runner, monkeypatch):
    cli_runner, tmp_path, db, config_dir = runner

    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    class FakeProvider:
        def __init__(self):
            self._db = None

        async def setup(self, clean: bool = False):
            from cellos.integrations.base import SetupResult
            return SetupResult(target_id="17", mappings={}, details={})

    monkeypatch.setattr("cellos.integrations.registry.load_provider", lambda *args, **kwargs: FakeProvider())

    result = cli_runner.invoke(main, [
        "--config-dir", config_dir, "--db", db, "pmcon", "setup", "vikunja"
    ])
    assert result.exit_code == 0

    saved = json.loads((Path(config_dir) / "config.json").read_text())
    assert saved["integrations"]["enabled_providers"] == ["vikunja"]


def test_pmcon_sync_reports_non_credential_http_errors(runner, monkeypatch):
    cli_runner, tmp_path, db, config_dir = runner

    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    class FakeProvider:
        def __init__(self):
            self._db = None

        async def sync(self, push: bool = True, pull: bool = True):
            raise OSError("HTTP Error 404: Not Found")

    monkeypatch.setattr("cellos.integrations.registry.load_provider", lambda *args, **kwargs: FakeProvider())

    result = cli_runner.invoke(main, [
        "--config-dir", config_dir, "--db", db, "pmcon", "sync", "vikunja", "--push"
    ])
    assert result.exit_code == 1
    assert "Sync failed:" in result.output
    assert "HTTP Error 404: Not Found" in result.output
    assert "Missing credentials:" not in result.output
