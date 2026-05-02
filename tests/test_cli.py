import json
import sqlite3
import sys
import time
from pathlib import Path

from click.testing import CliRunner

from cellos.cli import main


def wait_for_status(runner: CliRunner, db_path: Path, config_path: Path, expected: str):
    result = None
    for _ in range(30):
        result = runner.invoke(main, ["status", "--db", str(db_path), "--config", str(config_path)])
        if expected in result.output:
            return result
        time.sleep(0.1)
    return result


def task_payload(db_path: Path) -> dict:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT payload FROM tasks ORDER BY created_at LIMIT 1").fetchone()
    return json.loads(row[0])


def test_init_creates_database(tmp_path):
    db_path = tmp_path / "cellos.sqlite"
    config_path = tmp_path / ".cellos" / "config.json"
    runner = CliRunner()

    result = runner.invoke(main, ["init", "--db", str(db_path), "--config", str(config_path)])

    assert result.exit_code == 0
    assert db_path.exists()
    assert config_path.exists()


def test_init_hard_reset_overwrites_database_and_config(tmp_path):
    db_path = tmp_path / "cellos.sqlite"
    config_path = tmp_path / ".cellos" / "config.json"
    runner = CliRunner()

    runner.invoke(main, ["init", "--db", str(db_path), "--config", str(config_path)])
    config_path.write_text(
        '{"scheduler": {"concurrent_tasks": 99, "worker_timeout_seconds": 99}, '
        '"worker": {"backend": "acp", "command": ["python3", "tests/fakes/acp_server.py"], '
        '"debug_log_path": ".cellos/acp-debug.log"}}'
    )

    result = runner.invoke(main, ["init", "--hard-reset", "--db", str(db_path), "--config", str(config_path)])

    assert result.exit_code == 0
    assert '"concurrent_tasks": 4' in config_path.read_text()


def test_add_task_and_status(tmp_path):
    db_path = tmp_path / "cellos.sqlite"
    config_path = tmp_path / ".cellos" / "config.json"
    runner = CliRunner()
    init_result = runner.invoke(main, ["init", "--db", str(db_path), "--config", str(config_path)])

    add_result = runner.invoke(
        main,
        [
            "add-task",
            "Draft plan",
            "--role",
            "coordinator",
            "--type",
            "proposal",
            "--prompt",
            "Draft a short plan.",
            "--db",
            str(db_path),
            "--config",
            str(config_path),
        ],
    )
    status_result = runner.invoke(main, ["status", "--db", str(db_path), "--config", str(config_path)])

    assert init_result.exit_code == 0
    assert add_result.exit_code == 0
    assert status_result.exit_code == 0
    assert "Draft plan" in status_result.output
    assert "coordinator" in status_result.output
    assert "draft" in status_result.output


def test_add_task_requires_init(tmp_path):
    db_path = tmp_path / "cellos.sqlite"
    config_path = tmp_path / ".cellos" / "config.json"
    runner = CliRunner()
    runner.invoke(main, ["init", "--db", str(db_path), "--config", str(config_path)])
    db_path.unlink()

    result = runner.invoke(
        main,
        ["add-task", "No DB yet", "--db", str(db_path), "--config", str(config_path)],
    )

    assert result.exit_code != 0
    assert "Run `cellos init` first" in result.output


def test_run_schedules_approved_task(tmp_path):
    db_path = tmp_path / "cellos.sqlite"
    config_path = tmp_path / ".cellos" / "config.json"
    runner = CliRunner()
    init_result = runner.invoke(main, ["init", "--db", str(db_path), "--config", str(config_path)])

    add_result = runner.invoke(
        main,
        [
            "add-task",
            "Approved build",
            "--role",
            "engineer",
            "--type",
            "implementation",
            "--status",
            "approved",
            "--prompt",
            "Do the approved work.",
            "--db",
            str(db_path),
            "--config",
            str(config_path),
        ],
    )
    run_result = runner.invoke(main, ["run", "--db", str(db_path), "--config", str(config_path)])
    status_result = wait_for_status(runner, db_path, config_path, "completed")

    assert init_result.exit_code == 0
    assert add_result.exit_code == 0
    assert run_result.exit_code == 0
    assert "scheduled" in run_result.output
    assert "fake ACP" in status_result.output
    assert "completed" in status_result.output


def test_run_schedules_draft_task_for_planning(tmp_path):
    db_path = tmp_path / "cellos.sqlite"
    config_path = tmp_path / ".cellos" / "config.json"
    runner = CliRunner()
    init_result = runner.invoke(main, ["init", "--db", str(db_path), "--config", str(config_path)])

    add_result = runner.invoke(
        main,
        [
            "add-task",
            "Plan this work",
            "--role",
            "coordinator",
            "--type",
            "proposal",
            "--prompt",
            "Create a short plan.",
            "--db",
            str(db_path),
            "--config",
            str(config_path),
        ],
    )
    run_result = runner.invoke(main, ["run", "--db", str(db_path), "--config", str(config_path)])
    wait_for_status(runner, db_path, config_path, "fake ACP")
    events_result = runner.invoke(main, ["events", "--db", str(db_path), "--config", str(config_path)])
    saved_task = task_payload(db_path)

    assert init_result.exit_code == 0
    assert add_result.exit_code == 0
    assert run_result.exit_code == 0
    assert "scheduled planning" in run_result.output
    assert saved_task["status"] == "needs_approval"
    assert saved_task["prompt"] == "fake ACP completed task"
    assert "planning_saved" in events_result.output


def test_events_shows_task_history(tmp_path):
    db_path = tmp_path / "cellos.sqlite"
    config_path = tmp_path / ".cellos" / "config.json"
    runner = CliRunner()
    init_result = runner.invoke(main, ["init", "--db", str(db_path), "--config", str(config_path)])
    add_result = runner.invoke(
        main,
        [
            "add-task",
            "Eventful task",
            "--db",
            str(db_path),
            "--config",
            str(config_path),
        ],
    )
    events_result = runner.invoke(main, ["events", "--db", str(db_path), "--config", str(config_path)])

    assert init_result.exit_code == 0
    assert add_result.exit_code == 0
    assert events_result.exit_code == 0
    assert "Task created" in events_result.output
    assert "created" in events_result.output


def test_run_schedules_approved_task_with_fake_acp(tmp_path):
    db_path = tmp_path / "cellos.sqlite"
    config_path = tmp_path / ".cellos" / "config.json"
    fake_server = Path(__file__).parent / "fakes" / "acp_server.py"
    runner = CliRunner()

    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps(
            {
                "scheduler": {"concurrent_tasks": 4, "worker_timeout_seconds": 30},
                "worker": {
                    "backend": "acp",
                    "command": [sys.executable, str(fake_server)],
                    "debug_log_path": str(tmp_path / "acp-debug.log"),
                },
            }
        )
    )
    init_result = runner.invoke(main, ["init", "--db", str(db_path), "--config", str(config_path)])
    add_result = runner.invoke(
        main,
        [
            "add-task",
            "Approved ACP build",
            "--role",
            "engineer",
            "--type",
            "implementation",
            "--status",
            "approved",
            "--prompt",
            "Do the approved ACP work.",
            "--db",
            str(db_path),
            "--config",
            str(config_path),
        ],
    )
    run_result = runner.invoke(main, ["run", "--db", str(db_path), "--config", str(config_path)])
    status_result = wait_for_status(runner, db_path, config_path, "done")

    assert init_result.exit_code == 0
    assert add_result.exit_code == 0
    assert run_result.exit_code == 0
    assert "scheduled" in run_result.output
    assert "done" in status_result.output


def test_run_help_shows_concurrent_tasks_option():
    runner = CliRunner()

    result = runner.invoke(main, ["run", "--help"])

    assert result.exit_code == 0
    assert "--concurrent-tasks" in result.output
