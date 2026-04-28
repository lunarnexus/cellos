"""Command line interface for CelloS."""

import asyncio
from pathlib import Path
from uuid import uuid4

import click
from rich.console import Console
from rich.table import Table

from cellos.connectors.opencode import OpenCodeAcpBackend
from cellos.db import CellosDatabase
from cellos.models import AgentRole, Task, TaskStatus, TaskType
from cellos.orchestrator import Orchestrator


DEFAULT_DB_PATH = Path(".cellos") / "cellos.sqlite"
console = Console()


@click.group()
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
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB_PATH)
def add_task(title: str, task_type: str, role: str, description: str, db_path: Path) -> None:
    """Add a ready task to the local queue."""
    task = Task(
        id=f"task-{uuid4().hex[:8]}",
        title=title,
        task_type=TaskType(task_type),
        role=AgentRole(role),
        status=TaskStatus.READY,
        description=description,
    )
    asyncio.run(_add_task(db_path, task))
    console.print(f"Added [bold]{task.id}[/bold]: {task.title}")


@main.command()
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB_PATH)
def status(db_path: Path) -> None:
    """Show current task status."""
    asyncio.run(_status(db_path))


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
@click.option("--timeout", type=int, default=None)
def run(db_path: Path, cwd: Path, timeout: int | None) -> None:
    """Run the current batch of ready tasks, then stop."""
    results = asyncio.run(_run(db_path, cwd, timeout))
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


async def _status(db_path: Path) -> None:
    db = CellosDatabase(db_path)
    await db.connect()
    await db.init_db()
    tasks = await db.list_tasks()
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


async def _retry(db_path: Path, task_id: str) -> Task:
    db = CellosDatabase(db_path)
    await db.connect()
    await db.init_db()
    task = await db.retry_task(task_id)
    await db.close()
    return task


async def _run(db_path: Path, cwd: Path, timeout: int | None):
    db = CellosDatabase(db_path)
    await db.connect()
    await db.init_db()
    backend = OpenCodeAcpBackend(timeout_seconds=timeout)
    orchestrator = Orchestrator(db=db, backend=backend, cwd=cwd)
    results = await orchestrator.run_ready_tasks()
    await db.close()
    return results


if __name__ == "__main__":
    main()
