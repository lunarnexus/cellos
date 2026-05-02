import json
import sqlite3
import time
from pathlib import Path

from click.testing import CliRunner

from cellos.cli import DEFAULT_DB_PATH, DEFAULT_WORKDIR, _resolve_db_path, _resolve_workdir, main


def wait_for_status(
    runner: CliRunner,
    db_path: Path,
    config_path: Path,
    expected: str,
    workdir: Path | None = None,
):
    result = None
    for _ in range(30):
        command = ["status", "--db", str(db_path), "--config", str(config_path)]
        if workdir is not None:
            command.extend(["--workdir", str(workdir)])
        result = runner.invoke(main, command)
        if expected in result.output:
            return result
        time.sleep(0.1)
    return result


def task_payload(db_path: Path) -> dict:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT payload FROM tasks ORDER BY created_at LIMIT 1").fetchone()
    return json.loads(row[0])


def task_id_from_add_output(output: str) -> str:
    return output.split("Added ", 1)[1].split(":", 1)[0].strip()


def test_init_creates_database(tmp_path):
    db_path = tmp_path / "cellos.sqlite"
    config_path = tmp_path / ".cellos" / "config.json"
    runner = CliRunner()

    result = runner.invoke(main, ["init", "--db", str(db_path), "--config", str(config_path)])

    assert result.exit_code == 0
    assert db_path.exists()
    assert config_path.exists()


def test_init_creates_database_in_workdir(tmp_path):
    workdir = tmp_path / "project"
    config_path = tmp_path / ".cellos" / "config.json"
    runner = CliRunner()

    result = runner.invoke(main, ["init", "--workdir", str(workdir), "--config", str(config_path)])

    assert result.exit_code == 0
    assert (workdir / ".cellos" / "cellos.sqlite").exists()


def test_resolve_workdir_prefers_current_directory_with_database(tmp_path, monkeypatch):
    workdir = tmp_path / "project"
    (workdir / ".cellos").mkdir(parents=True)
    (workdir / DEFAULT_DB_PATH).touch()
    monkeypatch.chdir(workdir)

    assert _resolve_workdir(None) == workdir.resolve()


def test_resolve_workdir_falls_back_to_home(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert _resolve_workdir(None) == DEFAULT_WORKDIR.resolve()


def test_resolve_db_path_uses_workdir_default(tmp_path):
    workdir = tmp_path / "project"

    assert _resolve_db_path(None, workdir) == workdir / ".cellos" / "cellos.sqlite"


def test_init_hard_reset_overwrites_database_and_config(tmp_path):
    db_path = tmp_path / "cellos.sqlite"
    config_path = tmp_path / ".cellos" / "config.json"
    runner = CliRunner()

    runner.invoke(main, ["init", "--db", str(db_path), "--config", str(config_path)])
    config_path.write_text(
        '{"scheduler": {"concurrent_tasks": 99, "worker_timeout_seconds": 99}, '
        '"worker": {"backend": "acp", "command": ["python3", "-m", "cellos.connectors.fake_acp"], '
        '"debug_log_path": ".cellos/logs/acp-debug.log"}}'
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
    task_id = task_id_from_add_output(add_result.output)
    assert not task_id.startswith("task-")
    assert len(task_id) == 8
    assert status_result.exit_code == 0
    assert task_id in status_result.output
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


def test_detail_shows_prompt_result_and_events(tmp_path):
    db_path = tmp_path / "cellos.sqlite"
    config_path = tmp_path / ".cellos" / "config.json"
    runner = CliRunner()
    runner.invoke(main, ["init", "--db", str(db_path), "--config", str(config_path)])
    add_result = runner.invoke(
        main,
        [
            "add-task",
            "Detail task",
            "--prompt",
            "Explain the work.",
            "--db",
            str(db_path),
            "--config",
            str(config_path),
        ],
    )
    task_id = task_id_from_add_output(add_result.output)

    result = runner.invoke(main, ["detail", task_id, "--db", str(db_path), "--config", str(config_path)])

    assert result.exit_code == 0
    assert "Detail task" in result.output
    assert "Explain the work." in result.output
    assert "created" in result.output
    assert "Task created" in result.output


def test_update_changes_prompt_and_records_event(tmp_path):
    db_path = tmp_path / "cellos.sqlite"
    config_path = tmp_path / ".cellos" / "config.json"
    runner = CliRunner()
    runner.invoke(main, ["init", "--db", str(db_path), "--config", str(config_path)])
    add_result = runner.invoke(
        main,
        [
            "add-task",
            "Needs edits",
            "--prompt",
            "Old prompt.",
            "--db",
            str(db_path),
            "--config",
            str(config_path),
        ],
    )
    task_id = task_id_from_add_output(add_result.output)

    update_result = runner.invoke(
        main,
        [
            "update",
            task_id,
            "--prompt",
            "New prompt.",
            "--status",
            "needs_approval",
            "--db",
            str(db_path),
            "--config",
            str(config_path),
        ],
    )
    detail_result = runner.invoke(main, ["detail", task_id, "--db", str(db_path), "--config", str(config_path)])
    events_result = runner.invoke(main, ["events", task_id, "--db", str(db_path), "--config", str(config_path)])
    saved_task = task_payload(db_path)

    assert update_result.exit_code == 0
    assert f"Updated {task_id}" in update_result.output
    assert "New prompt." in detail_result.output
    assert saved_task["status"] == "needs_approval"
    assert saved_task["attention"]["required"] is True
    assert saved_task["attention"]["reason"] == "human_changed_task"
    assert "Task updated" in events_result.output


def test_update_rejects_empty_update(tmp_path):
    db_path = tmp_path / "cellos.sqlite"
    config_path = tmp_path / ".cellos" / "config.json"
    runner = CliRunner()
    runner.invoke(main, ["init", "--db", str(db_path), "--config", str(config_path)])
    add_result = runner.invoke(
        main,
        ["add-task", "No-op", "--db", str(db_path), "--config", str(config_path)],
    )
    task_id = task_id_from_add_output(add_result.output)

    result = runner.invoke(main, ["update", task_id, "--db", str(db_path), "--config", str(config_path)])

    assert result.exit_code != 0
    assert "Nothing to update." in result.output


def test_approve_moves_task_to_approved(tmp_path):
    db_path = tmp_path / "cellos.sqlite"
    config_path = tmp_path / ".cellos" / "config.json"
    runner = CliRunner()
    runner.invoke(main, ["init", "--db", str(db_path), "--config", str(config_path)])
    add_result = runner.invoke(
        main,
        [
            "add-task",
            "Approve me",
            "--status",
            "needs_approval",
            "--prompt",
            "Approved scope.",
            "--db",
            str(db_path),
            "--config",
            str(config_path),
        ],
    )
    task_id = task_id_from_add_output(add_result.output)

    approve_result = runner.invoke(main, ["approve", task_id, "--db", str(db_path), "--config", str(config_path)])
    status_result = runner.invoke(main, ["status", "--db", str(db_path), "--config", str(config_path)])
    events_result = runner.invoke(main, ["events", task_id, "--db", str(db_path), "--config", str(config_path)])

    assert approve_result.exit_code == 0
    assert f"Approved {task_id}" in approve_result.output
    assert "approved" in status_result.output
    assert "Task approved" in events_result.output


def test_planned_task_can_be_approved_and_executed(tmp_path):
    db_path = tmp_path / "cellos.sqlite"
    config_path = tmp_path / ".cellos" / "config.json"
    runner = CliRunner()
    runner.invoke(main, ["init", "--db", str(db_path), "--config", str(config_path)])
    add_result = runner.invoke(
        main,
        [
            "add-task",
            "Plan then execute",
            "--role",
            "engineer",
            "--type",
            "implementation",
            "--prompt",
            "Plan the work.",
            "--db",
            str(db_path),
            "--config",
            str(config_path),
        ],
    )
    task_id = task_id_from_add_output(add_result.output)
    planning_result = runner.invoke(main, ["run", "--db", str(db_path), "--config", str(config_path)])
    wait_for_status(runner, db_path, config_path, "fake ACP")

    approve_result = runner.invoke(main, ["approve", task_id, "--db", str(db_path), "--config", str(config_path)])
    execution_result = runner.invoke(main, ["run", "--db", str(db_path), "--config", str(config_path)])
    status_result = wait_for_status(runner, db_path, config_path, "done")

    assert planning_result.exit_code == 0
    assert "scheduled planning" in planning_result.output
    assert approve_result.exit_code == 0
    assert execution_result.exit_code == 0
    assert "scheduled execution" in execution_result.output
    assert "done" in status_result.output


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
    runner = CliRunner()

    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps(
            {
                "scheduler": {"concurrent_tasks": 4, "worker_timeout_seconds": 30},
                "worker": {
                    "backend": "acp",
                    "command": ["python3", "-m", "cellos.connectors.fake_acp"],
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
    assert "--workdir" in result.output
    assert "--cwd" not in result.output
