"""Command line interface for CelloS."""

import asyncio
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, TypeVar
from uuid import uuid4

import click
from rich.console import Console
from rich.table import Table

from cellos.acp_worker import AcpWorker
from cellos.config import CellosConfig, ConfigError, DEFAULT_CONFIG_PATH, ensure_config, load_config
from cellos.db import CellosDatabase, DatabaseNotInitialized
from cellos.models import AgentRole, Task, TaskResult, TaskStatus, TaskType


DEFAULT_DB_PATH = Path(".cellos") / "cellos.sqlite"
console = Console()
T = TypeVar("T")


@dataclass
class CellosApp:
    config: CellosConfig
    db: CellosDatabase
    cwd: Path


@dataclass
class RunScheduleResult:
    attention_tasks: list[Task]
    scheduled_tasks: list[Task]


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def main() -> None:
    """CelloS orchestration CLI."""


@main.command()
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB_PATH)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
@click.option("--hard-reset", is_flag=True, help="Reset local DB and overwrite config from defaults.")
def init(db_path: Path, config_path: Path, hard_reset: bool) -> None:
    """Initialize local CelloS state."""
    if hard_reset and db_path.exists():
        db_path.unlink()
    copied_config = ensure_config(config_path, overwrite=hard_reset)
    asyncio.run(_init(db_path))
    console.print(f"Initialized database at [bold]{db_path}[/bold]")
    console.print(f"Initialized config at [bold]{copied_config}[/bold]")


@main.command("add-task")
@click.argument("title")
@click.option("--role", type=click.Choice([item.value for item in AgentRole]), default=AgentRole.ENGINEER.value)
@click.option("--type", "task_type", type=click.Choice([item.value for item in TaskType]), default=TaskType.PROPOSAL.value)
@click.option("--status", type=click.Choice([item.value for item in TaskStatus]), default=TaskStatus.DRAFT.value)
@click.option("--prompt", default="", help="Task prompt or approved scope.")
@click.option("--description", default="", help="Additional task description.")
@click.option("--depends-on", multiple=True, help="Task ID this task depends on. May be repeated.")
@click.option("--parent", "parent_id", default=None, help="Parent task ID.")
@click.option("--timeout", type=int, default=None, help="Per-task worker timeout in seconds.")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB_PATH)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
def add_task(
    title: str,
    role: str,
    task_type: str,
    status: str,
    prompt: str,
    description: str,
    depends_on: tuple[str, ...],
    parent_id: str | None,
    timeout: int | None,
    db_path: Path,
    config_path: Path,
) -> None:
    """Add a task to the local CelloS database."""
    task = Task(
        id=f"task-{uuid4().hex[:8]}",
        title=title,
        role=AgentRole(role),
        task_type=TaskType(task_type),
        status=TaskStatus(status),
        prompt=prompt,
        description=description,
        parent_id=parent_id,
        dependencies=list(depends_on),
        timeout_seconds=timeout,
    )
    _run_cli(_add_task(db_path, config_path, task))
    console.print(f"Added [bold]{task.id}[/bold]: {task.title}")


@main.command()
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB_PATH)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
def status(db_path: Path, config_path: Path) -> None:
    """Show current task status."""
    _run_cli(_status(db_path, config_path))


@main.command()
@click.argument("task_id", required=False)
@click.option("--limit", type=int, default=50, show_default=True)
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB_PATH)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
def events(task_id: str | None, limit: int, db_path: Path, config_path: Path) -> None:
    """Show stored task events."""
    _run_cli(_events(db_path, config_path, task_id, limit))


@main.command()
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB_PATH)
@click.option("--cwd", type=click.Path(path_type=Path), default=Path.cwd())
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
@click.option("--concurrent-tasks", type=int, default=None)
def run(db_path: Path, cwd: Path, config_path: Path, concurrent_tasks: int | None) -> None:
    """Run one local CelloS heartbeat."""
    result = _run_cli(_run(db_path, config_path, cwd, concurrent_tasks))
    if not result.attention_tasks and not result.scheduled_tasks:
        console.print("No tasks to run.")
        return
    for task in result.attention_tasks:
        console.print(f"{task.id}: attention - {task.attention.reason}")
    for task in result.scheduled_tasks:
        console.print(f"{task.id}: scheduled - {task.title}")


@main.command(hidden=True)
@click.argument("task_id")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB_PATH)
@click.option("--cwd", type=click.Path(path_type=Path), default=Path.cwd())
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
def worker(task_id: str, db_path: Path, cwd: Path, config_path: Path) -> None:
    """Run one task worker process."""
    _run_cli(_worker(task_id, db_path, config_path, cwd))


async def _init(db_path: Path) -> None:
    db = CellosDatabase(db_path)
    await db.connect()
    await db.init_db()
    await db.close()


def _run_cli(coro: Awaitable[T]) -> T:
    try:
        return asyncio.run(coro)
    except (ConfigError, DatabaseNotInitialized) as exc:
        raise click.ClickException(str(exc)) from exc


async def _open_app(db_path: Path, config_path: Path, cwd: Path | None = None) -> CellosApp:
    config = load_config(config_path)
    db = CellosDatabase(db_path)
    await db.connect()
    try:
        await db.ensure_initialized()
    except Exception:
        await db.close()
        raise
    return CellosApp(config=config, db=db, cwd=cwd or Path.cwd())


async def _add_task(db_path: Path, config_path: Path, task: Task) -> None:
    app = await _open_app(db_path, config_path)
    try:
        await app.db.create_task(task)
    finally:
        await app.db.close()


async def _status(db_path: Path, config_path: Path) -> None:
    app = await _open_app(db_path, config_path)
    try:
        tasks = await app.db.list_tasks()
    finally:
        await app.db.close()

    table = Table(title="CelloS Tasks")
    table.add_column("ID")
    table.add_column("Status")
    table.add_column("Role")
    table.add_column("Type")
    table.add_column("Title")
    table.add_column("Result")
    for task in tasks:
        result = task.result.summary if task.result is not None else ""
        table.add_row(task.id, task.status.value, task.role.value, task.task_type.value, task.title, result)
    console.print(table)


async def _events(db_path: Path, config_path: Path, task_id: str | None, limit: int) -> None:
    app = await _open_app(db_path, config_path)
    try:
        events = await app.db.list_task_events(task_id=task_id, limit=limit)
    finally:
        await app.db.close()

    table = Table(title="CelloS Events")
    table.add_column("ID")
    table.add_column("Task")
    table.add_column("Type")
    table.add_column("Message")
    table.add_column("Created")
    for event in events:
        table.add_row(
            str(event["id"]),
            event["task_id"],
            event["event_type"],
            event["message"],
            event["created_at"],
        )
    console.print(table)


def _build_worker(config: CellosConfig):
    if config.worker.backend == "acp":
        if not config.worker.command:
            raise click.ClickException("Config worker.command is required when worker.backend is 'acp'.")
        return AcpWorker(
            command=config.worker.command,
            timeout_seconds=config.scheduler.worker_timeout_seconds,
            debug_log_path=config.worker.debug_log_path,
        )
    raise click.ClickException(f"Unsupported worker backend: {config.worker.backend}")


async def _run(db_path: Path, config_path: Path, cwd: Path, concurrent_tasks: int | None):
    app = await _open_app(db_path, config_path, cwd)
    resolved_concurrent_tasks = concurrent_tasks or app.config.scheduler.concurrent_tasks
    try:
        attention_tasks = await app.db.list_tasks_requiring_attention(limit=resolved_concurrent_tasks)
        remaining_slots = max(resolved_concurrent_tasks - len(attention_tasks), 0)
        approved_tasks = await app.db.list_approved_unblocked_tasks(limit=remaining_slots)
        scheduled_tasks: list[Task] = []
        for task in approved_tasks:
            scheduled = await app.db.update_task_status(task.id, TaskStatus.IN_PROGRESS)
            await app.db.record_task_event(task.id, "worker_spawned", "Background worker spawned")
            await app.db.conn.commit()
            try:
                _spawn_worker(scheduled, db_path, config_path, app.cwd)
            except Exception as exc:
                await app.db.save_task_result(
                    TaskResult(
                        task_id=task.id,
                        success=False,
                        summary=f"Worker spawn failed: {exc}",
                        error=str(exc),
                    )
                )
                continue
            scheduled_tasks.append(scheduled)
        return RunScheduleResult(attention_tasks=attention_tasks, scheduled_tasks=scheduled_tasks)
    finally:
        await app.db.close()


async def _worker(task_id: str, db_path: Path, config_path: Path, cwd: Path) -> None:
    app = await _open_app(db_path, config_path, cwd)
    try:
        task = await app.db.get_task(task_id)
        if task is None:
            raise click.ClickException(f"Task not found: {task_id}")
        await app.db.record_task_event(task.id, "worker_started", "Background worker started")
        await app.db.conn.commit()
        worker_backend = _build_worker(app.config)
        try:
            result = await worker_backend.run_task(task, app.cwd)
        except Exception as exc:
            result = TaskResult(
                task_id=task.id,
                success=False,
                summary=f"Task failed: {exc}",
                error=str(exc),
            )
        await app.db.save_task_result(result)
    finally:
        await app.db.close()


def _spawn_worker(task: Task, db_path: Path, config_path: Path, cwd: Path) -> None:
    log_path = cwd / ".cellos" / f"worker-{task.id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "cellos.cli",
        "worker",
        task.id,
        "--db",
        str(db_path),
        "--config",
        str(config_path),
        "--cwd",
        str(cwd),
    ]
    with log_path.open("ab") as log:
        subprocess.Popen(
            command,
            cwd=cwd,
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

if __name__ == "__main__":
    main()
