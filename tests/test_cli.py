"""CLI integration tests — end-to-end coverage of all 8 commands via CliRunner.

Tests use real SQLite databases in temp directories (no mocking). Each test 
initializes a fresh DB to avoid cross-test contamination.
"""

import json
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
