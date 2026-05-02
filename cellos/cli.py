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
from cellos.models import AgentRole, AttentionReason, Task, TaskResult, TaskStatus, TaskType


DEFAULT_DB_PATH = Path(".cellos") / "cellos.sqlite"
DEFAULT_WORKDIR = Path.home()
console = Console()
T = TypeVar("T")


@dataclass
class CellosApp:
    config: CellosConfig
    db: CellosDatabase
    workdir: Path


@dataclass
class RunScheduleResult:
    attention_tasks: list[Task]
    planning_tasks: list[Task]
    execution_tasks: list[Task]


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def main() -> None:
    """CelloS orchestration CLI."""


@main.command()
@click.option("--workdir", type=click.Path(path_type=Path), default=None)
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
@click.option("--hard-reset", is_flag=True, help="Reset local DB and overwrite config from defaults.")
def init(workdir: Path | None, db_path: Path | None, config_path: Path, hard_reset: bool) -> None:
    """Initialize local CelloS state."""
    resolved_workdir = _resolve_workdir(workdir)
    resolved_db_path = _resolve_db_path(db_path, resolved_workdir)
    if hard_reset and resolved_db_path.exists():
        resolved_db_path.unlink()
    copied_config = ensure_config(config_path, overwrite=hard_reset)
    asyncio.run(_init(resolved_db_path))
    console.print(f"Initialized database at [bold]{resolved_db_path}[/bold]")
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
@click.option("--workdir", type=click.Path(path_type=Path), default=None)
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
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
    workdir: Path | None,
    db_path: Path | None,
    config_path: Path,
) -> None:
    """Add a task to the local CelloS database."""
    task = Task(
        id=uuid4().hex[:8],
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
    _run_cli(_add_task(db_path, config_path, workdir, task))
    console.print(f"Added [bold]{task.id}[/bold]: {task.title}")


@main.command()
@click.option("--workdir", type=click.Path(path_type=Path), default=None)
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
def status(workdir: Path | None, db_path: Path | None, config_path: Path) -> None:
    """Show current task status."""
    _run_cli(_status(db_path, config_path, workdir))


@main.command()
@click.argument("task_id", required=False)
@click.option("--limit", type=int, default=50, show_default=True)
@click.option("--workdir", type=click.Path(path_type=Path), default=None)
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
def events(task_id: str | None, limit: int, workdir: Path | None, db_path: Path | None, config_path: Path) -> None:
    """Show stored task events."""
    _run_cli(_events(db_path, config_path, workdir, task_id, limit))


@main.command()
@click.argument("task_id")
@click.option("--events", "event_limit", type=int, default=10, show_default=True)
@click.option("--workdir", type=click.Path(path_type=Path), default=None)
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
def detail(task_id: str, event_limit: int, workdir: Path | None, db_path: Path | None, config_path: Path) -> None:
    """Show task details."""
    _run_cli(_detail(db_path, config_path, workdir, task_id, event_limit))


@main.command()
@click.argument("task_id")
@click.option("--title", default=None)
@click.option("--prompt", default=None)
@click.option("--description", default=None)
@click.option("--status", type=click.Choice([item.value for item in TaskStatus]), default=None)
@click.option("--workdir", type=click.Path(path_type=Path), default=None)
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
def update(
    task_id: str,
    title: str | None,
    prompt: str | None,
    description: str | None,
    status: str | None,
    workdir: Path | None,
    db_path: Path | None,
    config_path: Path,
) -> None:
    """Update a task."""
    task = _run_cli(_update(db_path, config_path, workdir, task_id, title, prompt, description, status))
    console.print(f"Updated [bold]{task.id}[/bold]: {task.title}")


@main.command()
@click.argument("task_id")
@click.option("--workdir", type=click.Path(path_type=Path), default=None)
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
def approve(task_id: str, workdir: Path | None, db_path: Path | None, config_path: Path) -> None:
    """Approve a planned task for execution."""
    task = _run_cli(_approve(db_path, config_path, workdir, task_id))
    console.print(f"Approved [bold]{task.id}[/bold]: {task.title}")


@main.command()
@click.option("--workdir", type=click.Path(path_type=Path), default=None)
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
@click.option("--concurrent-tasks", type=int, default=None)
def run(workdir: Path | None, db_path: Path | None, config_path: Path, concurrent_tasks: int | None) -> None:
    """Run one local CelloS heartbeat."""
    result = _run_cli(_run(db_path, config_path, workdir, concurrent_tasks))
    if not result.attention_tasks and not result.planning_tasks and not result.execution_tasks:
        console.print("No tasks to run.")
        return
    for task in result.attention_tasks:
        console.print(f"{task.id}: attention - {task.attention.reason}")
    for task in result.planning_tasks:
        console.print(f"{task.id}: scheduled planning - {task.title}")
    for task in result.execution_tasks:
        console.print(f"{task.id}: scheduled execution - {task.title}")


@main.command(hidden=True)
@click.argument("task_id")
@click.option("--mode", type=click.Choice(["planning", "execution"]), required=True)
@click.option("--workdir", type=click.Path(path_type=Path), default=None)
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
def worker(task_id: str, mode: str, workdir: Path | None, db_path: Path | None, config_path: Path) -> None:
    """Run one task worker process."""
    _run_cli(_worker(task_id, mode, db_path, config_path, workdir))


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


def _resolve_workdir(workdir: Path | None) -> Path:
    if workdir is not None:
        return workdir.expanduser().resolve()
    current = Path.cwd()
    if (current / DEFAULT_DB_PATH).exists():
        return current.resolve()
    return DEFAULT_WORKDIR.resolve()


def _resolve_db_path(db_path: Path | None, workdir: Path) -> Path:
    if db_path is not None:
        return db_path.expanduser().resolve()
    return workdir / DEFAULT_DB_PATH


async def _open_app(db_path: Path | None, config_path: Path, workdir: Path | None = None) -> CellosApp:
    resolved_workdir = _resolve_workdir(workdir)
    resolved_db_path = _resolve_db_path(db_path, resolved_workdir)
    config = load_config(config_path)
    db = CellosDatabase(resolved_db_path)
    await db.connect()
    try:
        await db.ensure_initialized()
    except Exception:
        await db.close()
        raise
    return CellosApp(config=config, db=db, workdir=resolved_workdir)


async def _add_task(db_path: Path | None, config_path: Path, workdir: Path | None, task: Task) -> None:
    app = await _open_app(db_path, config_path, workdir)
    try:
        await app.db.create_task(task)
    finally:
        await app.db.close()


async def _status(db_path: Path | None, config_path: Path, workdir: Path | None) -> None:
    app = await _open_app(db_path, config_path, workdir)
    try:
        tasks = await app.db.list_tasks()
    finally:
        await app.db.close()

    table = Table(title="CelloS Tasks")
    table.add_column("ID", no_wrap=True)
    table.add_column("Status")
    table.add_column("Role")
    table.add_column("Type")
    table.add_column("Title")
    table.add_column("Result")
    for task in tasks:
        result = task.result.summary if task.result is not None else ""
        table.add_row(task.id, task.status.value, task.role.value, task.task_type.value, task.title, result)
    console.print(table)


async def _events(
    db_path: Path | None,
    config_path: Path,
    workdir: Path | None,
    task_id: str | None,
    limit: int,
) -> None:
    app = await _open_app(db_path, config_path, workdir)
    try:
        events = await app.db.list_task_events(task_id=task_id, limit=limit)
    finally:
        await app.db.close()

    table = Table(title="CelloS Events")
    table.add_column("ID", no_wrap=True)
    table.add_column("Task", no_wrap=True)
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


async def _detail(
    db_path: Path | None,
    config_path: Path,
    workdir: Path | None,
    task_id: str,
    event_limit: int,
) -> None:
    app = await _open_app(db_path, config_path, workdir)
    try:
        task = await app.db.get_task(task_id)
        if task is None:
            raise click.ClickException(f"Task not found: {task_id}")
        events = await app.db.list_task_events(task_id=task_id, limit=event_limit)
    finally:
        await app.db.close()

    console.print(f"[bold]{task.title}[/bold]")
    console.print(f"ID: {task.id}")
    console.print(f"Status: {task.status.value}")
    console.print(f"Role: {task.role.value}")
    console.print(f"Type: {task.task_type.value}")
    if task.parent_id:
        console.print(f"Parent: {task.parent_id}")
    if task.dependencies:
        console.print(f"Dependencies: {', '.join(task.dependencies)}")
    console.print("")
    console.print("[bold]Prompt[/bold]")
    console.print(task.prompt or "")
    if task.description:
        console.print("")
        console.print("[bold]Description[/bold]")
        console.print(task.description)
    if task.result is not None:
        console.print("")
        console.print("[bold]Result[/bold]")
        console.print(task.result.summary)
    if events:
        console.print("")
        console.print("[bold]Recent Events[/bold]")
        for event in events:
            console.print(f"- {event['event_type']}: {event['message']}")


async def _update(
    db_path: Path | None,
    config_path: Path,
    workdir: Path | None,
    task_id: str,
    title: str | None,
    prompt: str | None,
    description: str | None,
    status: str | None,
) -> Task:
    if title is None and prompt is None and description is None and status is None:
        raise click.ClickException("Nothing to update.")
    app = await _open_app(db_path, config_path, workdir)
    try:
        task = await app.db.get_task(task_id)
        if task is None:
            raise click.ClickException(f"Task not found: {task_id}")

        updates: dict[str, object] = {}
        content_changed = False
        if title is not None:
            updates["title"] = title
            content_changed = content_changed or title != task.title
        if prompt is not None:
            updates["prompt"] = prompt
            content_changed = content_changed or prompt != task.prompt
        if description is not None:
            updates["description"] = description
            content_changed = content_changed or description != task.description
        if status is not None:
            updates["status"] = TaskStatus(status)

        updated_task = task.model_copy(update=updates)
        if content_changed and updated_task.status != TaskStatus.APPROVED:
            updated_task = updated_task.requires_attention(
                AttentionReason.HUMAN_CHANGED_TASK,
                "Human updated task content",
            )
        updated = await app.db.update_task(updated_task)
        await app.db.record_task_event(task.id, "updated", "Task updated")
        await app.db.conn.commit()
        return updated
    finally:
        await app.db.close()


async def _approve(db_path: Path | None, config_path: Path, workdir: Path | None, task_id: str) -> Task:
    app = await _open_app(db_path, config_path, workdir)
    try:
        task = await app.db.get_task(task_id)
        if task is None:
            raise click.ClickException(f"Task not found: {task_id}")
        if task.status not in {TaskStatus.DRAFT, TaskStatus.NEEDS_APPROVAL}:
            raise click.ClickException(
                f"Task {task.id} cannot be approved from status {task.status.value}."
            )
        updated = await app.db.update_task(task.clear_attention().model_copy(update={"status": TaskStatus.APPROVED}))
        await app.db.record_task_event(task.id, "approved", "Task approved")
        await app.db.conn.commit()
        return updated
    finally:
        await app.db.close()


def _build_worker(config: CellosConfig, workdir: Path):
    if config.worker.backend == "acp":
        if not config.worker.command:
            raise click.ClickException("Config worker.command is required when worker.backend is 'acp'.")
        debug_log_path = config.worker.debug_log_path
        if debug_log_path is not None and not Path(debug_log_path).is_absolute():
            debug_log_path = str(workdir / debug_log_path)
        return AcpWorker(
            command=config.worker.command,
            timeout_seconds=config.scheduler.worker_timeout_seconds,
            debug_log_path=debug_log_path,
        )
    raise click.ClickException(f"Unsupported worker backend: {config.worker.backend}")


async def _run(db_path: Path | None, config_path: Path, workdir: Path | None, concurrent_tasks: int | None):
    app = await _open_app(db_path, config_path, workdir)
    resolved_concurrent_tasks = concurrent_tasks or app.config.scheduler.concurrent_tasks
    try:
        planning_candidates = await app.db.list_tasks_ready_for_planning(limit=resolved_concurrent_tasks)
        planning_ids = {task.id for task in planning_candidates}
        remaining_after_planning = max(resolved_concurrent_tasks - len(planning_candidates), 0)
        attention_tasks = [
            task
            for task in await app.db.list_tasks_requiring_attention(limit=resolved_concurrent_tasks)
            if task.id not in planning_ids
        ][:remaining_after_planning]
        remaining_slots = max(remaining_after_planning - len(attention_tasks), 0)
        approved_tasks = await app.db.list_approved_unblocked_tasks(limit=remaining_slots)
        planning_tasks: list[Task] = []
        execution_tasks: list[Task] = []
        for task in planning_candidates:
            scheduled = await _schedule_worker(app, task, db_path, config_path, "planning")
            if scheduled is not None:
                planning_tasks.append(scheduled)
        for task in approved_tasks:
            scheduled = await _schedule_worker(app, task, db_path, config_path, "execution")
            if scheduled is not None:
                execution_tasks.append(scheduled)
        return RunScheduleResult(
            attention_tasks=attention_tasks,
            planning_tasks=planning_tasks,
            execution_tasks=execution_tasks,
        )
    finally:
        await app.db.close()


async def _schedule_worker(
    app: CellosApp,
    task: Task,
    db_path: Path | None,
    config_path: Path,
    mode: str,
) -> Task | None:
    scheduled = await app.db.update_task_status(task.id, TaskStatus.IN_PROGRESS)
    await app.db.record_task_event(task.id, "worker_spawned", f"Background {mode} worker spawned")
    await app.db.conn.commit()
    try:
        _spawn_worker(scheduled, db_path, config_path, app.workdir, mode)
    except Exception as exc:
        await app.db.save_task_result(
            TaskResult(
                task_id=task.id,
                success=False,
                summary=f"Worker spawn failed: {exc}",
                error=str(exc),
            )
        )
        return None
    return scheduled


async def _worker(task_id: str, mode: str, db_path: Path | None, config_path: Path, workdir: Path | None) -> None:
    app = await _open_app(db_path, config_path, workdir)
    try:
        task = await app.db.get_task(task_id)
        if task is None:
            raise click.ClickException(f"Task not found: {task_id}")
        await app.db.record_task_event(task.id, "worker_started", f"Background {mode} worker started")
        await app.db.conn.commit()
        worker_backend = _build_worker(app.config, app.workdir)
        try:
            result = await worker_backend.run_task(task, app.workdir, mode=mode)
        except Exception as exc:
            result = TaskResult(
                task_id=task.id,
                success=False,
                summary=f"Task failed: {exc}",
                error=str(exc),
            )
        if mode == "planning" and result.success:
            await _save_planning_result(app, task, result)
        else:
            await app.db.save_task_result(result)
    finally:
        await app.db.close()


async def _save_planning_result(app: CellosApp, task: Task, result: TaskResult) -> None:
    current = await app.db.get_task(task.id)
    if current is None:
        raise click.ClickException(f"Task not found: {task.id}")
    updated = current.clear_attention().model_copy(
        update={
            "prompt": result.summary,
            "result": result,
            "status": TaskStatus.NEEDS_APPROVAL,
        }
    )
    await app.db.update_task(updated)
    await app.db.record_task_event(task.id, "planning_saved", "Planning result saved; task needs approval")
    await app.db.conn.commit()


def _spawn_worker(task: Task, db_path: Path | None, config_path: Path, workdir: Path, mode: str) -> None:
    resolved_db_path = _resolve_db_path(db_path, workdir)
    log_path = workdir / ".cellos" / "logs" / f"worker-{task.id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "cellos.cli",
        "worker",
        task.id,
        "--mode",
        mode,
        "--db",
        str(resolved_db_path),
        "--config",
        str(config_path),
        "--workdir",
        str(workdir),
    ]
    with log_path.open("ab") as log:
        subprocess.Popen(
            command,
            cwd=workdir,
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

if __name__ == "__main__":
    main()
