from click.testing import CliRunner

from cellos.db import CellosDatabase
from cellos.cli import main
from cellos.models import AgentRole, Task, TaskResult, TaskStatus, TaskType


def test_retry_resets_failed_task(tmp_path):
    db_path = tmp_path / "cellos.sqlite"
    runner = CliRunner()

    async def setup_failed_task():
        db = CellosDatabase(db_path)
        await db.connect()
        await db.init_db()
        await db.create_task(
            Task(
                id="task-retry",
                title="Retry me",
                task_type=TaskType.TEST,
                role=AgentRole.CRITIC,
                status=TaskStatus.READY,
            )
        )
        await db.save_task_result(
            TaskResult(task_id="task-retry", success=False, summary="failed", error="boom")
        )
        await db.close()

    import asyncio

    asyncio.run(setup_failed_task())

    retry_result = runner.invoke(main, ["retry", "task-retry", "--db", str(db_path)])
    assert retry_result.exit_code == 0

    status_result = runner.invoke(main, ["status", "--db", str(db_path)])
    assert status_result.exit_code == 0
    assert "ready" in status_result.output
    assert "failed" not in status_result.output


def test_reset_db_clears_existing_tasks(tmp_path):
    db_path = tmp_path / "cellos.sqlite"
    runner = CliRunner()

    init_result = runner.invoke(main, ["init", "--db", str(db_path)])
    assert init_result.exit_code == 0

    add_result = runner.invoke(main, ["add-task", "Tiny task", "--db", str(db_path)])
    assert add_result.exit_code == 0

    status_result = runner.invoke(main, ["status", "--db", str(db_path)])
    assert status_result.exit_code == 0
    assert "Tiny task" in status_result.output

    reset_result = runner.invoke(main, ["reset-db", "--db", str(db_path), "--yes"])
    assert reset_result.exit_code == 0

    empty_status_result = runner.invoke(main, ["status", "--db", str(db_path)])
    assert empty_status_result.exit_code == 0
    assert "Tiny task" not in empty_status_result.output


def test_status_shows_task_response(tmp_path):
    db_path = tmp_path / "cellos.sqlite"
    runner = CliRunner()

    async def setup_completed_task():
        db = CellosDatabase(db_path)
        await db.connect()
        await db.init_db()
        await db.create_task(
            Task(
                id="task-output",
                title="Say OK",
                task_type=TaskType.TEST,
                role=AgentRole.CRITIC,
                status=TaskStatus.READY,
            )
        )
        await db.save_task_result(TaskResult(task_id="task-output", success=True, summary="CELLOS_ACP_OK"))
        await db.close()

    import asyncio

    asyncio.run(setup_completed_task())

    status_result = runner.invoke(main, ["status", "--db", str(db_path)])

    assert status_result.exit_code == 0
    assert "Response" in status_result.output
    assert "CELLOS_ACP_OK" in status_result.output
