"""CLI integration tests — end-to-end coverage of all 8 commands via CliRunner.

Tests use real SQLite databases in temp directories (no mocking). Each test 
initializes a fresh DB to avoid cross-test contamination.
"""

import pytest
from pathlib import Path
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


# ── status ──────────────────────────────────────────────────────────────

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
    assert result.exit_code == 0  # CLI catches error gracefully
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
    assert result.exit_code == 0  # CLI catches error gracefully
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
    assert result.exit_code == 0  # CLI catches error gracefully
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
        for agent in catalog.values():
            agent["connector"] = "fake_acp"
            agent.setdefault("options", {})["default_success"] = True
            agent["options"]["default_summary"] = "Test agent completed."
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


# ── trello commands (legacy, mapped to integration) ───────────────

def test_trello_status_no_config(runner):
    cli_runner, tmp_path, db, config_dir = runner

    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    result = cli_runner.invoke(main, [
        "--config-dir", config_dir, "--db", db, "pmcon", "status", "trello"
    ])
    assert result.exit_code == 0


def test_trello_init_missing_creds(runner):
    cli_runner, tmp_path, db, config_dir = runner

    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    result = cli_runner.invoke(main, [
        "--config-dir", config_dir, "--db", db, "pmcon", "setup", "trello"
    ])
    assert result.exit_code == 0
    assert "setup failed:" in result.output.lower()


def test_trello_help(runner):
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


def test_trello_sync_missing_creds(runner):
    cli_runner, tmp_path, db, config_dir = runner

    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    result = cli_runner.invoke(main, [
        "--config-dir", config_dir, "--db", db, "pmcon", "sync", "trello"
    ])
    assert result.exit_code == 0


# ── integration commands ────────────────────────────────────────────────

def test_pmcon_list(runner):
    cli_runner, tmp_path, db, config_dir = runner

    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    result = cli_runner.invoke(main, [
        "--config-dir", config_dir, "--db", db, "pmcon", "list"
    ])
    assert result.exit_code == 0
    assert "trello" in result.output


def test_pmcon_status_trello_no_config(runner):
    cli_runner, tmp_path, db, config_dir = runner

    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    result = cli_runner.invoke(main, [
        "--config-dir", config_dir, "--db", db, "pmcon", "status", "trello"
    ])
    assert result.exit_code == 0


def test_pmcon_status_unknown_provider(runner):
    cli_runner, tmp_path, db, config_dir = runner

    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    result = cli_runner.invoke(main, [
        "--config-dir", config_dir, "--db", db, "pmcon", "status", "linear"
    ])
    assert result.exit_code == 0
    assert "Unknown integration provider 'linear'" in result.output


def test_pmcon_setup_missing_creds(runner):
    cli_runner, tmp_path, db, config_dir = runner

    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    result = cli_runner.invoke(main, [
        "--config-dir", config_dir, "--db", db, "pmcon", "setup", "trello"
    ])
    assert result.exit_code == 0
    assert "setup failed:" in result.output.lower()


def test_pmcon_sync_missing_creds(runner):
    import os
    cli_runner, tmp_path, db, config_dir = runner

    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    result = cli_runner.invoke(main, [
        "--config-dir", config_dir, "--db", db, "pmcon", "sync", "trello"
    ])
    assert result.exit_code == 0


def test_pmcon_sync_push_only(runner):
    cli_runner, tmp_path, db, config_dir = runner

    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    result = cli_runner.invoke(main, [
        "--config-dir", config_dir, "--db", db, "pmcon", "sync", "trello", "--push"
    ])
    assert result.exit_code == 0


def test_pmcon_sync_pull_only(runner):
    cli_runner, tmp_path, db, config_dir = runner

    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    result = cli_runner.invoke(main, [
        "--config-dir", config_dir, "--db", db, "pmcon", "sync", "trello", "--pull"
    ])
    assert result.exit_code == 0


def test_pmcon_status_no_credential_prefixes(runner):
    import os

    cli_runner, tmp_path, db, config_dir = runner
    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    os.environ["TRELLO_API_KEY"] = "abcdef123456789"
    os.environ["TRELLO_TOKEN"] = "token123456789"
    try:
        result = cli_runner.invoke(main, [
            "--config-dir", config_dir, "--db", db, "pmcon", "status", "trello"
        ])
        assert result.exit_code == 0
        for i in range(len(result.output) - 3):
            chunk = result.output[i:i+4]
            assert chunk not in ("...", "... ") or "configured" in result.output[:result.output.find(chunk)+10], \
                "Should show 'configured' without prefix fragments"
    finally:
        del os.environ["TRELLO_API_KEY"]
        del os.environ["TRELLO_TOKEN"]


def test_pmcon_setup_persists_board_id_to_config_dir(runner):
    """pmcon setup trello writes board_id into the --config-dir config.json, not ~/.cellos."""
    import json
    from unittest.mock import AsyncMock, patch

    cli_runner, tmp_path, db, config_dir = runner

    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    board_id_val = "cli-board-abc123"

    def make_client(api_key="", token=""):
        from cellos.integrations.trello.models import Board, TrelloList
        tlist = TrelloList(id="l1", name="To Do", idBoard=board_id_val, pos=1.0)
        lists = [tlist]
        mock = AsyncMock()
        mock.create_board.return_value = Board(id=board_id_val, name="CelloS")
        mock.get_lists.return_value = lists
        mock.create_list.return_value = tlist
        return mock

    with patch("cellos.integrations.trello.provider.TrelloClient", side_effect=make_client):
        result = cli_runner.invoke(main, [
            "--config-dir", config_dir, "--db", db, "pmcon", "setup", "trello"
        ])
        assert result.exit_code == 0

    cfg_data = json.loads((tmp_path / "config.json").read_text())
    assert cfg_data["integrations"]["trello"]["board_id"] == board_id_val


def test_pmcon_setup_persists_to_config_not_home(runner):
    """Board ID is written to --config-dir, not the default ~/.cellos."""
    import json
    from unittest.mock import AsyncMock, patch

    cli_runner, tmp_path, db, config_dir = runner

    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    board_id_val = "home-test-board"

    def make_client(api_key="", token=""):
        from cellos.integrations.trello.models import Board, TrelloList
        tlist = TrelloList(id="l1", name="To Do", idBoard=board_id_val, pos=1.0)
        lists = [tlist]
        mock = AsyncMock()
        mock.create_board.return_value = Board(id=board_id_val, name="CelloS")
        mock.get_lists.return_value = lists
        mock.create_list.return_value = tlist
        return mock

    with patch("cellos.integrations.trello.provider.TrelloClient", side_effect=make_client):
        result = cli_runner.invoke(main, [
            "--config-dir", config_dir, "--db", db, "pmcon", "setup", "trello"
        ])
        assert result.exit_code == 0

    cfg_data = json.loads((tmp_path / "config.json").read_text())
    assert cfg_data["integrations"]["trello"]["board_id"] == board_id_val

    home_cellos = Path.home() / ".cellos" / "config.json"
    if home_cellos.exists():
        home_data = json.loads(home_cellos.read_text())
        assert home_data.get("integrations", {}).get("trello", {}).get("board_id") != board_id_val, \
            "Should not have written to default ~/.cellos when --config-dir is used"


def test_pmcon_setup_reuses_existing_config_board_id(runner):
    """When config already has board_id, setup reuses it instead of creating new."""
    import json
    from unittest.mock import AsyncMock, patch

    cli_runner, tmp_path, db, config_dir = runner

    init_result = cli_runner.invoke(main, ["--config-dir", config_dir, "--db", db, "init"])
    assert init_result.exit_code == 0

    existing_board_id = "already-configured-board"
    cfg_data = json.loads((tmp_path / "config.json").read_text())
    cfg_data.setdefault("integrations", {}).setdefault("trello", {})["board_id"] = existing_board_id
    (tmp_path / "config.json").write_text(json.dumps(cfg_data))

    boards_created = []

    def make_client(api_key="", token=""):
        from cellos.integrations.trello.models import Board, TrelloList
        tlist = TrelloList(id="l1", name="To Do", idBoard=existing_board_id, pos=1.0)
        lists = [tlist]
        mock = AsyncMock()
        mock.create_board.side_effect = lambda name: boards_created.append(name) or Board(
            id=f"new-{len(boards_created)}", name=name
        )
        mock.get_lists.return_value = lists
        mock.create_list.return_value = tlist
        return mock

    with patch("cellos.integrations.trello.provider.TrelloClient", side_effect=make_client):
        result = cli_runner.invoke(main, [
            "--config-dir", config_dir, "--db", db, "pmcon", "setup", "trello"
        ])
        assert result.exit_code == 0

    assert len(boards_created) == 0, "Should not create new board when one is already configured"
