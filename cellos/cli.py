"""Command line interface for CelloS."""

import asyncio
from pathlib import Path
from uuid import uuid4

import click
from rich.console import Console

from cellos.cli_app import (
    DEFAULT_DB_PATH,
    DEFAULT_WORKDIR,
    _open_app,
    _resolve_db_path,
    _resolve_workdir,
    _run_cli,
)
from cellos.cli_formatting import detail_formatter, events_formatter, status_formatter
from cellos.config import DEFAULT_CONFIG_PATH
from cellos.domain.enums import AgentRole, TaskStatus, TaskType
from cellos.domain.tasks import Task
from cellos.services.scheduler import SchedulerService
from cellos.services.task_service import (
    EmptyTaskUpdateError,
    InvalidTaskApprovalError,
    TaskNotFoundError,
    TaskService,
)
from cellos.services.worker_service import WorkerService

console = Console()


# Re-exports for backward compatibility and tests
__all__ = [
    "DEFAULT_DB_PATH",
    "DEFAULT_WORKDIR",
    "_resolve_db_path",
    "_resolve_workdir",
    "main",
]


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def main() -> None:
    """CelloS orchestration CLI."""


@main.command()
@click.option("--workdir", type=click.Path(path_type=Path), default=None)
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
@click.option("--hard-reset", is_flag=True, help="Reset local DB and overwrite config from defaults.")
def init(workdir, db_path, config_path, hard_reset):
    """Initialize local CelloS state."""
    resolved_workdir = _resolve_workdir(workdir)
    resolved_db_path = _resolve_db_path(db_path, resolved_workdir)
    if hard_reset and resolved_db_path.exists():
        resolved_db_path.unlink()
    from cellos.config import ensure_config

    copied_config = ensure_config(config_path, overwrite=hard_reset)

    async def _init():
        from cellos.db import CellosDatabase

        db = CellosDatabase(resolved_db_path)
        await db.connect()
        await db.init_db()
        await db.close()

    asyncio.run(_init())
    console.print(f"Initialized database at [bold]{resolved_db_path}[/bold]")
    console.print(f"Initialized config at [bold]{copied_config}[/bold]")
    console.print(f"Initialized agent catalog at [bold]{copied_config.parent / 'agentcatalog.json'}[/bold]")
    console.print(f"Initialized prompt profiles at [bold]{copied_config.parent / 'promptprofiles.json'}[/bold]")


@main.command("add-task")
@click.argument("title")
@click.option("--role", type=click.Choice([item.value for item in AgentRole]), default=AgentRole.ENGINEER.value)
@click.option("--type", "task_type", type=click.Choice([item.value for item in TaskType]), default=TaskType.PROPOSAL.value)
@click.option("--status", type=click.Choice([item.value for item in TaskStatus]), default=TaskStatus.DRAFT.value)
@click.option("--prompt", default="", help="Task prompt or approved scope.")
@click.option("--depends", "depends_on", multiple=True, help="Task ID this task depends on. May be repeated.")
@click.option("--parent", "parent_id", default=None, help="Parent task ID.")
@click.option("--timeout", type=int, default=None, help="Per-task worker timeout in seconds.")
@click.option("--agent", "agent_id", default=None, help="Agent catalog ID to run this task with.")
@click.option("--workdir", type=click.Path(path_type=Path), default=None)
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
def add_task(title, role, task_type, status, prompt, depends_on, parent_id, timeout, agent_id, workdir, db_path, config_path):
    """Add a task to the local CelloS database."""
    task = Task(
        id=uuid4().hex[:8],
        title=title,
        role=AgentRole(role),
        task_type=TaskType(task_type),
        status=TaskStatus(status),
        prompt=prompt,
        parent_id=parent_id,
        dependencies=list(depends_on),
        timeout_seconds=timeout,
        agent_id=agent_id,
    )
    _run_cli(_add_task(db_path, config_path, workdir, task))
    console.print(f"Added [bold]{task.id}[/bold]: {task.title}")


@main.command()
@click.option("--workdir", type=click.Path(path_type=Path), default=None)
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
def status(workdir, db_path, config_path):
    """Show current task status."""
    _run_cli(_status(db_path, config_path, workdir))


@main.command()
@click.argument("task_id", required=False)
@click.option("--limit", type=int, default=50, show_default=True)
@click.option("--workdir", type=click.Path(path_type=Path), default=None)
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
def events(task_id, limit, workdir, db_path, config_path):
    """Show stored task events."""
    _run_cli(_events(db_path, config_path, workdir, task_id, limit))


@main.command()
@click.argument("task_id")
@click.option("--events", "event_limit", type=int, default=10, show_default=True)
@click.option("--workdir", type=click.Path(path_type=Path), default=None)
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
def detail(task_id, event_limit, workdir, db_path, config_path):
    """Show task details."""
    _run_cli(_detail(db_path, config_path, workdir, task_id, event_limit))


@main.command()
@click.argument("task_id")
@click.option("--title", default=None)
@click.option("--prompt", default=None)
@click.option("--status", type=click.Choice([item.value for item in TaskStatus]), default=None)
@click.option("--parent", "parent_id", default=None)
@click.option("--depends", "add_dependencies", multiple=True, help="Add a task dependency. May be repeated.")
@click.option("--remove-dep", "remove_dependencies", multiple=True, help="Remove a task dependency. May be repeated.")
@click.option("--agent", "agent_id", default=None, help="Agent catalog ID to run this task with.")
@click.option("--clear-agent", is_flag=True, help="Clear task-specific agent and use default.")
@click.option("--comment", "comment_message", default=None, help="Add a conversation message. Format: 'human: message' or 'system: message'.")
@click.option("--workdir", type=click.Path(path_type=Path), default=None)
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
def update(task_id, title, prompt, status, parent_id, add_dependencies, remove_dependencies, agent_id, clear_agent, comment_message, workdir, db_path, config_path):
    """Update a task."""
    if agent_id is not None and clear_agent:
        raise click.ClickException("Use either --agent or --clear-agent, not both.")
    if comment_message is not None and any([title, prompt, status, parent_id, add_dependencies, remove_dependencies, agent_id, clear_agent]):
        raise click.ClickException("--comment cannot be combined with other update flags.")
    if comment_message is not None:
        _run_cli(_add_conversation(db_path, config_path, workdir, task_id, comment_message))
        console.print(f"Conversation added to [bold]{task_id}[/bold]")
        return
    task = _run_cli(
        _update(
            db_path,
            config_path,
            workdir,
            task_id,
            title,
            prompt,
            status,
            parent_id,
            add_dependencies,
            remove_dependencies,
            agent_id,
            clear_agent,
        )
    )
    console.print(f"Updated [bold]{task.id}[/bold]: {task.title}")


@main.command("comment")
@click.argument("task_id")
@click.argument("message")
@click.option("--author", "author_id", default="human")
@click.option("--workdir", type=click.Path(path_type=Path), default=None)
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
def comment_task(task_id, message, author_id, workdir, db_path, config_path):
    """Add a human comment to a task."""
    _run_cli(_comment(db_path, config_path, workdir, task_id, message, author_id))
    console.print(f"Commented on [bold]{task_id}[/bold]")


@main.command()
@click.argument("task_id")
@click.option("--workdir", type=click.Path(path_type=Path), default=None)
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
def approve(task_id, workdir, db_path, config_path):
    """Approve a planned task for execution."""
    task = _run_cli(_approve(db_path, config_path, workdir, task_id))
    console.print(f"Approved [bold]{task.id}[/bold]: {task.title}")


@main.command()
@click.option("--workdir", type=click.Path(path_type=Path), default=None)
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=DEFAULT_CONFIG_PATH)
@click.option("--concurrent-tasks", type=int, default=None)
def run(workdir, db_path, config_path, concurrent_tasks):
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
def worker(task_id, mode, workdir, db_path, config_path):
    """Run one task worker process."""
    _run_cli(_worker(task_id, mode, db_path, config_path, workdir))


# -- Async helpers (thin wrappers over services) --


async def _add_task(db_path, config_path, workdir, task):
    app = await _open_app(db_path, config_path, workdir)
    try:
        if task.agent_id is not None:
            try:
                app.config.get_agent(task.agent_id)
            except ValueError as exc:
                raise click.ClickException(str(exc)) from exc
        await TaskService(app.db).create_task(task)
    finally:
        await app.db.close()


async def _status(db_path, config_path, workdir):
    app = await _open_app(db_path, config_path, workdir)
    try:
        tasks = await app.db.list_tasks()
    finally:
        await app.db.close()
    status_formatter(tasks)


async def _events(db_path, config_path, workdir, task_id, limit):
    app = await _open_app(db_path, config_path, workdir)
    try:
        events = await app.db.list_task_events(task_id=task_id, limit=limit)
    finally:
        await app.db.close()
    events_formatter(events)


async def _detail(db_path, config_path, workdir, task_id, event_limit):
    app = await _open_app(db_path, config_path, workdir)
    try:
        task = await app.db.get_task(task_id)
        if task is None:
            raise click.ClickException(f"Task not found: {task_id}")
        events = await app.db.list_task_events(task_id=task_id, limit=event_limit)
        comments = await app.db.list_task_comments(task_id=task_id, limit=10)
        attempts = await app.db.list_task_attempts(task_id=task_id, limit=10)
    finally:
        await app.db.close()
    detail_formatter(task, comments, attempts, events)


async def _update(db_path, config_path, workdir, task_id, title, prompt, status, parent_id, add_dependencies, remove_dependencies, agent_id, clear_agent):
    app = await _open_app(db_path, config_path, workdir)
    try:
        if agent_id is not None:
            try:
                app.config.get_agent(agent_id)
            except ValueError as exc:
                raise click.ClickException(str(exc)) from exc
        return await TaskService(app.db).update_task(
            task_id,
            title=title,
            prompt=prompt,
            status=TaskStatus(status) if status is not None else None,
            parent_id=parent_id,
            add_dependencies=add_dependencies,
            remove_dependencies=remove_dependencies,
            agent_id=agent_id,
            clear_agent=clear_agent,
        )
    except EmptyTaskUpdateError as exc:
        raise click.ClickException(str(exc)) from exc
    except TaskNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        await app.db.close()


async def _comment(db_path, config_path, workdir, task_id, message, author_id):
    app = await _open_app(db_path, config_path, workdir)
    try:
        await TaskService(app.db).add_human_comment(task_id, message, author_id)
    except TaskNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        await app.db.close()


async def _add_conversation(db_path, config_path, workdir, task_id, raw_message):
    app = await _open_app(db_path, config_path, workdir)
    try:
        await TaskService(app.db).add_conversation_message(task_id, raw_message)
    except TaskNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        await app.db.close()


async def _approve(db_path, config_path, workdir, task_id):
    app = await _open_app(db_path, config_path, workdir)
    try:
        return await TaskService(app.db).approve_task(task_id)
    except (TaskNotFoundError, InvalidTaskApprovalError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        await app.db.close()


async def _run(db_path, config_path, workdir, concurrent_tasks):
    app = await _open_app(db_path, config_path, workdir)
    resolved_db_path = _resolve_db_path(db_path, app.workdir)
    try:
        return await SchedulerService(
            db=app.db,
            config=app.config,
            workdir=app.workdir,
            db_path=resolved_db_path,
            config_path=config_path,
        ).run_once(concurrent_tasks)
    finally:
        await app.db.close()


async def _worker(task_id, mode, db_path, config_path, workdir):
    app = await _open_app(db_path, config_path, workdir)
    try:
        await WorkerService(db=app.db, config=app.config, workdir=app.workdir).run_task_worker(task_id, mode)
    finally:
        await app.db.close()


if __name__ == "__main__":
    main()
