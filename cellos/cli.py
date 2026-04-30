"""Command line interface for CelloS."""

import asyncio
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import click
from rich.console import Console
from rich.table import Table

from cellos.connectors.opencode import OpenCodeAcpBackend
from cellos.db import CellosDatabase
from cellos.models import AgentRole, Task, TaskStatus, TaskType, utc_now
from cellos.orchestrator import Orchestrator


DEFAULT_DB_PATH = Path(".cellos") / "cellos.sqlite"
SINCE_UNITS = {
    "s": timedelta(seconds=1),
    "m": timedelta(minutes=1),
    "h": timedelta(hours=1),
    "d": timedelta(days=1),
}
console = Console()


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def main() -> None:
    """CelloS orchestration CLI."""


@main.command()
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB_PATH)
def init(db_path: Path) -> None:
    """Initialize the local CelloS database."""
    asyncio.run(_init(db_path))
    console.print(f"Initialized database at [bold]{db_path}[/bold]")


@main.command("reset-db")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB_PATH)
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def reset_db(db_path: Path, yes: bool) -> None:
    """Delete and recreate the local CelloS database."""
    if not yes:
        click.confirm(f"Delete and recreate {db_path}?", abort=True)
    if db_path.exists():
        db_path.unlink()
    asyncio.run(_init(db_path))
    console.print(f"Reset database at [bold]{db_path}[/bold]")


@main.command("add-task")
@click.argument("title")
@click.option("--type", "task_type", type=click.Choice([item.value for item in TaskType]), default=TaskType.BUILD.value)
@click.option("--role", type=click.Choice([item.value for item in AgentRole]), default=AgentRole.CELLO.value)
@click.option("--description", default="")
@click.option("--depends-on", multiple=True, help="Task ID this task depends on. May be repeated.")
@click.option("--timeout", type=int, default=None, help="Per-task timeout in seconds.")
@click.option("--parent", "parent_id", default=None, help="Parent task ID for decomposed work.")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB_PATH)
def add_task(
    title: str,
    task_type: str,
    role: str,
    description: str,
    depends_on: tuple[str, ...],
    timeout: int | None,
    parent_id: str | None,
    db_path: Path,
) -> None:
    """Add a ready task to the local queue."""
    task = Task(
        id=f"task-{uuid4().hex[:8]}",
        title=title,
        task_type=TaskType(task_type),
        role=AgentRole(role),
        status=TaskStatus.READY,
        description=description,
        parent_id=parent_id,
        dependencies=list(depends_on),
        timeout_seconds=timeout,
    )
    asyncio.run(_add_task(db_path, task))
    console.print(f"Added [bold]{task.id}[/bold]: {task.title}")


@main.command()
@click.option("--check-tasks", is_flag=True, help="Actively check in-progress workers when supported.")
@click.option("--since", default=None, help="Show tasks updated within a duration like 10m, 2h, or 1d.")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB_PATH)
def status(check_tasks: bool, since: str | None, db_path: Path) -> None:
    """Show current task status."""
    asyncio.run(_status(db_path, check_tasks, since))


@main.command()
@click.argument("task_id")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB_PATH)
def retry(task_id: str, db_path: Path) -> None:
    """Reset a task to ready so it can be run again."""
    task = asyncio.run(_retry(db_path, task_id))
    console.print(f"Reset [bold]{task.id}[/bold] to ready.")


@main.command()
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB_PATH)
@click.option("--cwd", type=click.Path(path_type=Path), default=Path.cwd())
@click.option("--timeout", type=int, default=300)
@click.option("--concurrent-tasks", type=int, default=4, show_default=True)
def run(db_path: Path, cwd: Path, timeout: int | None, concurrent_tasks: int) -> None:
    """Run one scheduler heartbeat of ready tasks, then stop."""
    results = asyncio.run(_run(db_path, cwd, timeout, concurrent_tasks))
    if not results:
        console.print("No ready tasks to run.")
        return
    for result in results:
        state = "done" if result.success else "failed"
        console.print(f"{result.task_id}: {state} - {result.summary}")


async def _init(db_path: Path) -> None:
    db = CellosDatabase(db_path)
    await db.connect()
    await db.init_db()
    await db.close()


async def _add_task(db_path: Path, task: Task) -> None:
    db = CellosDatabase(db_path)
    await db.connect()
    await db.init_db()
    await db.create_task(task)
    await db.close()


async def _status(db_path: Path, check_tasks: bool = False, since: str | None = None) -> None:
    db = CellosDatabase(db_path)
    await db.connect()
    await db.init_db()
    if since is None:
        tasks = await db.list_tasks()
    else:
        tasks = await db.list_tasks_updated_since(utc_now() - _parse_duration(since))
    await db.close()

    table = Table(title="CelloS Tasks")
    table.add_column("ID")
    table.add_column("Status")
    table.add_column("Role")
    table.add_column("Type")
    table.add_column("Title")
    table.add_column("Response")
    for task in tasks:
        output = task.result.summary if task.result is not None else ""
        table.add_row(task.id, task.status.value, task.role.value, task.task_type.value, task.title, output)
    console.print(table)
    if check_tasks:
        console.print(
            "Active worker checks are not available yet for the current one-process-per-task backend."
        )


async def _retry(db_path: Path, task_id: str) -> Task:
    db = CellosDatabase(db_path)
    await db.connect()
    await db.init_db()
    task = await db.retry_task(task_id)
    await db.close()
    return task


async def _run(db_path: Path, cwd: Path, timeout: int | None, concurrent_tasks: int):
    db = CellosDatabase(db_path)
    await db.connect()
    await db.init_db()
    backend = OpenCodeAcpBackend(timeout_seconds=timeout)
    orchestrator = Orchestrator(db=db, backend=backend, cwd=cwd)
    results = await orchestrator.run_ready_tasks(limit=concurrent_tasks)
    await db.close()
    return results


def _parse_duration(value: str) -> timedelta:
    value = value.strip().lower()
    if len(value) < 2:
        raise click.BadParameter("Use a duration like 10m, 2h, or 1d.")

    unit = value[-1]
    amount = value[:-1]
    if unit not in SINCE_UNITS:
        raise click.BadParameter("Duration unit must be one of s, m, h, or d.")
    if not amount.isdigit() or int(amount) <= 0:
        raise click.BadParameter("Duration amount must be a positive integer.")
    return int(amount) * SINCE_UNITS[unit]


if __name__ == "__main__":
    main()
