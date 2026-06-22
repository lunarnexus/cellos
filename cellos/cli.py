"""CelloS CLI — Click command group for human task management.

All manual operations: init, add-task, status, detail, approve, comment, events, update.
No ACP integration yet — everything is local state manipulation via services layer.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cellos.config import ensure_config, load_config
from cellos.env import load_env
from cellos.db import CellosDatabase
from cellos.models import (
    AgentRole,
    AttentionReason,
    CommentAuthorType,
    TaskDependency,
    TaskStatus,
    TaskType,
)
from cellos.persistence.schema import init_db
from cellos.services.task_service import (
    EmptyTaskUpdateError,
    InvalidTaskApprovalError,
    TaskNotFoundError,
    TaskService,
)

console = Console()


# ── Global options via context params ────────────────────────────────────────

DEFAULT_DB_PATH = str(Path.home() / ".cellos" / "cellos.sqlite")
DEFAULT_CONFIG_DIR = str(Path.home() / ".cellos")
DEFAULT_DEBUG_LOG = str(Path.home() / ".cellos" / "debug.log")


def _debug_callback(ctx: click.Context, param: click.Parameter, value: str | bool | None) -> str | None:
    """Handle --debug flag with optional path argument."""
    if value is True:  # Flag used without argument
        return DEFAULT_DEBUG_LOG
    if isinstance(value, str):
        return value
    return None


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--db", default=DEFAULT_DB_PATH, help="Path to SQLite database.")
@click.option(
    "--config-dir", default=DEFAULT_CONFIG_DIR, help="Directory containing config files."
)
@click.option(
    "--debug",
    default=None,
    is_flag=True,
    flag_value=DEFAULT_DEBUG_LOG,
    help="Enable debug logging to file. Defaults to ~/.cellos/debug.log",
)
@click.pass_context
def main(ctx: click.Context, db: str, config_dir: str, debug: str | None):
    """CelloS — Human-governed AI orchestration."""
    # Load .env from config directory (injects secrets into os.environ)
    load_env(str(Path(config_dir) / ".env"))

    ctx.ensure_object(dict)
    ctx.obj["db"] = db
    ctx.obj["config_dir"] = config_dir

    if debug is not None:
        debug_path = Path(debug)
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=str(debug_path), level=logging.DEBUG,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        console.print(f"[dim]Debug logging to {debug_path}[/]")


# ── Helper functions ────────────────────────────────────────────────────────

async def _get_db(db_path: str) -> CellosDatabase:
    """Create and connect a CellosDatabase instance."""
    db = CellosDatabase(db_path)
    await db.connect()
    return db


def _notify_daemon(config_dir: str | None = None, workdir: str = ".") -> None:
    """Signal the daemon to wake and re-evaluate scheduling.

    Touches the notification file so the daemon's file watcher picks it up.
    """
    notify_path = Path(workdir) / ".cellos" / "daemon_notify"
    notify_path.parent.mkdir(parents=True, exist_ok=True)
    notify_path.touch()


def _format_status_table(tasks, status_filter=None):
    """Format tasks as Rich table with attention markers."""
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Status", style="bold")
    table.add_column("Role", width=12)
    table.add_column("Title", overflow="fold")

    for task in tasks:
        status_str = str(task.status.value)
        if task.attention.required:
            status_str += " ⚠️"
        table.add_row(
            task.id,
            status_str,
            str(task.role.value),
            task.title[:60],  # truncate long titles
        )

    return table


def _format_detail_panel(task):
    """Format full task details as Rich panel."""
    lines = [
        f"[bold]{task.title}[/]",
        "",
        f"ID:           {task.id}",
        f"Status:       {task.status.value}",
        f"Role:         {task.role.value}",
        f"Type:         {task.task_type.value}",
    ]

    if task.details:
        lines.append(f"Details:      {task.details}")
    if task.success_criteria:
        lines.append(f"Success Crit: {task.success_criteria}")
    if task.failure_criteria:
        lines.append(f"Failure Crit: {task.failure_criteria}")
    if task.plan:
        lines.extend(["", f"[italic]Plan:[/]\n{task.plan}"])

    if task.result:
        result_icon = "✅" if task.result.success else "❌"
        lines.extend(["", f"[bold]{result_icon} Result:[/] {task.result.summary}"])

    # Attention warning
    if task.attention.required:
        lines.insert(
            2,
            f"\n[red bold]⚠️ ATTENTION REQUIRED[/]",
        )
        lines.insert(3, f"   Reason: {task.attention.reason.value if task.attention.reason else 'unknown'}")
        if task.attention.detail:
            lines.insert(4, f"   Detail: {task.attention.detail}")

    # Dependencies
    if task.dependencies:
        dep_ids = ", ".join(d.task_id for d in task.dependencies)
        lines.extend(["", f"Dependencies: {dep_ids}"])

    # Comments
    if task.comments:
        lines.append("")
        for c in task.comments[-5:]:  # last 5 comments
            author_label = "Human" if c.author_type == CommentAuthorType.HUMAN else "System"
            lines.append(f"[dim]{author_label}:[/dim] {c.content[:80]}")

    return Panel("\n".join(lines), title="Task Details", border_style="blue")


def _format_events_table(events, limit=None):
    """Format events as Rich table (newest first)."""
    if limit:
        events = events[:limit]

    table = Table(show_header=True, header_style="bold")
    table.add_column("Time", style="dim")
    table.add_column("Event", style="cyan")
    table.add_column("Message", overflow="fold")

    for e in events:
        time_str = e.timestamp.strftime("%H:%M:%S") if hasattr(e, "timestamp") else str(e.timestamp)
        table.add_row(time_str, e.event_type, e.message[:80])

    return table


# ── Commands ────────────────────────────────────────────────────────────────

@main.command()
@click.option("--overwrite", is_flag=True, help="Overwrite existing config files.")
@click.pass_context
def init(ctx: click.Context, overwrite: bool):
    """Initialize project — create config files and database."""
    config_dir = ctx.obj["config_dir"]
    db_path = ctx.obj["db"]

    # Ensure config dir exists
    Path(config_dir).mkdir(parents=True, exist_ok=True)

    # Write config files
    ensure_config(config_dir, overwrite=overwrite)
    console.print(f"✓ Config written to {config_dir}")
    console.print("  config.json, agentcatalog.json, promptprofiles.json")

    # Init database (reset if overwriting)
    if overwrite and Path(db_path).exists():
        Path(db_path).unlink()
    asyncio.run(init_db(db_path))
    console.print(f"✓ Database initialized at {db_path}")


@main.command(name="add-task")
@click.argument("title", required=True)
@click.option("-d", "--details", default=None, help="Task details/description.")
@click.option(
    "-r",
    "--role",
    type=click.Choice([r.value for r in AgentRole]),
    default=AgentRole.ENGINEER.value,
    help="Agent role (infers task_type).",
)
@click.option(
    "-t",
    "--type",
    "task_type",
    type=click.Choice([t.value for t in TaskType]),
    default=None,
    help="Explicit task type.",
)
@click.option("-s", "--success-criteria", default=None, help="Success criteria.")
@click.option("-f", "--failure-criteria", default=None, help="Failure criteria.")
@click.option(
    "--depends", multiple=True, default=(), help="Dependency task IDs (can specify multiple)."
)
@click.pass_context
def add_task(ctx: click.Context, title, details, role, task_type, success_criteria, failure_criteria, depends):
    """Create a new task."""

    async def _run():
        db = await _get_db(ctx.obj["db"])
        service = TaskService(db)

        try:
            deps = [TaskDependency(task_id=dep_id) for dep_id in depends] if depends else []

            created = await service.create_task(
                title=title,
                details=details,
                role=AgentRole(role),
                task_type=TaskType(task_type) if task_type else None,
                success_criteria=success_criteria,
                failure_criteria=failure_criteria,
                dependencies=deps,
            )

            console.print(f"✓ Created task {created.id}: {title}")
            console.print(
                f"  Role: {created.role.value} | Type: {created.task_type.value} | Status: {created.status.value}"
            )
            _notify_daemon()
        finally:
            await db.close()

    asyncio.run(_run())


@main.command()
@click.option("-s", "--status-filter", type=click.Choice([s.value for s in TaskStatus]), default=None, help="Filter by status.")
@click.pass_context
def status(ctx: click.Context, status_filter):
    """List tasks with attention markers."""

    async def _run():
        db = await _get_db(ctx.obj["db"])
        service = TaskService(db)

        try:
            filter_enum = TaskStatus(status_filter) if status_filter else None
            tasks = await service.list_tasks(status_filter=filter_enum)

            if not tasks:
                console.print("No tasks found.")
                return

            table = _format_status_table(tasks, status_filter)
            console.print(table)
            console.print(f"\nTotal: {len(tasks)} task{'s' if len(tasks) != 1 else ''}")
        finally:
            await db.close()

    asyncio.run(_run())


@main.command()
@click.argument("task_id", required=True)
@click.pass_context
def detail(ctx: click.Context, task_id):
    """Show full task details."""

    async def _run():
        db = await _get_db(ctx.obj["db"])
        service = TaskService(db)

        try:
            try:
                task = await service.get_task(task_id)
            except TaskNotFoundError as e:
                console.print(f"[red]Error: {e}[/]")
                sys.exit(1)

            panel = _format_detail_panel(task)
            console.print(panel)
        finally:
            await db.close()

    asyncio.run(_run())


@main.command()
@click.argument("task_id", required=True)
@click.pass_context
def approve(ctx: click.Context, task_id):
    """Approve a planned task for execution."""

    async def _run():
        db = await _get_db(ctx.obj["db"])
        service = TaskService(db)

        try:
            try:
                approved = await service.approve_task(task_id)
            except TaskNotFoundError as e:
                console.print(f"[red]Error: {e}[/]")
                sys.exit(1)
            except InvalidTaskApprovalError as e:
                console.print(f"[red]Error: {e}[/]")
                sys.exit(1)

            console.print(f"✓ Approved task {task_id}")
            console.print(f"  Status: {approved.status.value}")
            _notify_daemon()
        finally:
            await db.close()

    asyncio.run(_run())


@main.command()
@click.argument("task_id", required=True)
@click.option("-m", "--message", required=True, help="Comment text.")
@click.pass_context
def comment(ctx: click.Context, task_id, message):
    """Add a human comment to a task."""

    async def _run():
        db = await _get_db(ctx.obj["db"])
        service = TaskService(db)

        try:
            try:
                current_task = await service.get_task(task_id)
            except TaskNotFoundError as e:
                console.print(f"[red]Error: {e}[/]")
                sys.exit(1)

            comment_obj = await service.add_human_comment(task_id, message)

            # Check if attention was triggered (non-approved tasks)
            attention_triggered = current_task.status not in (
                TaskStatus.APPROVED,
                TaskStatus.DONE,
                TaskStatus.CANCELLED,
            )

            console.print(f"✓ Comment added to {task_id}")
            if attention_triggered:
                console.print("  ⚠️ Attention triggered: Human commented")
            _notify_daemon()
        finally:
            await db.close()

    asyncio.run(_run())


@main.command()
@click.argument("task_id", required=True)
@click.option("--limit", default=10, help="Max events to show.")
@click.pass_context
def events(ctx: click.Context, task_id, limit):
    """Show audit trail events for a task."""

    async def _run():
        db = await _get_db(ctx.obj["db"])
        service = TaskService(db)

        try:
            try:
                # Verify task exists first
                await service.get_task(task_id)
            except TaskNotFoundError as e:
                console.print(f"[red]Error: {e}[/]")
                sys.exit(1)

            event_list = await db.list_events(task_id, limit=limit)

            if not event_list:
                console.print("No events found.")
                return

            table = _format_events_table(event_list, limit)
            console.print(table)
        finally:
            await db.close()

    asyncio.run(_run())


@main.command()
@click.argument("task_id", required=True)
@click.option("--title", default=None, help="New title.")
@click.option("-d", "--details", default=None, help="New details/description.")
@click.option("-s", "--success-criteria", default=None, help="New success criteria.")
@click.option("-f", "--failure-criteria", default=None, help="New failure criteria.")
@click.option("--add-dep", multiple=True, default=(), help="Add dependency task ID (can specify multiple).")
@click.option("--remove-dep", multiple=True, default=(), help="Remove dependency task ID (can specify multiple).")
@click.pass_context
def update(ctx: click.Context, task_id, title, details, success_criteria, failure_criteria, add_dep, remove_dep):
    """Update any field on a task."""

    async def _run():
        db = await _get_db(ctx.obj["db"])
        service = TaskService(db)

        try:
            deps_to_add = [TaskDependency(task_id=d) for d in add_dep] if add_dep else None
            deps_to_remove = list(remove_dep) if remove_dep else None

            try:
                updated = await service.update_task(
                    task_id=task_id,
                    title=title,
                    details=details,
                    success_criteria=success_criteria,
                    failure_criteria=failure_criteria,
                    add_dependencies=deps_to_add,
                    remove_dependencies=deps_to_remove,
                )
            except TaskNotFoundError as e:
                console.print(f"[red]Error: {e}[/]")
                sys.exit(1)
            except EmptyTaskUpdateError as e:
                console.print(f"[red]Error: {e}[/]")
                sys.exit(1)

            changes = []
            if title:
                changes.append(f"title → '{title}'")
            if details is not None:
                changes.append("details updated")
            if success_criteria is not None:
                changes.append("success criteria updated")
            if failure_criteria is not None:
                changes.append("failure criteria updated")
            if add_dep:
                changes.append(f"added deps: {', '.join(add_dep)}")
            if remove_dep:
                changes.append(f"removed deps: {', '.join(remove_dep)}")

            console.print(f"✓ Updated task {task_id}")
            for c in changes:
                console.print(f"  - {c}")

            if updated.attention.required:
                console.print("  ⚠️ Attention triggered by content change")
            _notify_daemon()
        finally:
            await db.close()

    asyncio.run(_run())


@main.command("worker")
@click.argument("task_id")
@click.option("--mode", required=True, type=click.Choice(["planning", "execution"]), help="Worker mode: planning or execution.")
@click.pass_context
def worker(ctx: click.Context, task_id, mode):
    """Execute a single worker (called by spawner or manually).

    Spawns the full worker lifecycle: load task → build connector → run agent → save result.
    Used both directly for testing and via WorkerSpawner subprocesses.
    """

    async def _run():
        db = await _get_db(ctx.obj["db"])
        config_dir = ctx.obj.get("config_dir") or DEFAULT_CONFIG_DIR
        try:
            from cellos.config import load_config, ConfigError as CfgErr
            config = load_config(config_dir)
        except (CfgErr, FileNotFoundError):
            console.print(f"[red]Config not found in {config_dir}. Run 'cellos init' first.[/]")
            sys.exit(1)

        try:
            from cellos.services.worker_service import run_task_worker, WorkerError as WkErr
            result = await run_task_worker(db=db, task_id=task_id, mode=mode, config=config)
            console.print(f"✓ Worker completed for {task_id} (status={result.status.value})")
        except WkErr as e:
            console.print(f"[red]Worker error: {e}[/]")
            sys.exit(1)
        except Exception as e:
            console.print(f"[red]Unexpected error: {type(e).__name__}: {e}[/]")
            sys.exit(1)
        finally:
            await db.close()

    asyncio.run(_run())


@main.command("run")
@click.pass_context
def run(ctx: click.Context):
    """Start the event-driven daemon scheduler.

    Watches for work and spawns worker subprocesses. No polling — uses
    asyncio.Event() to sleep until signaled by worker exits or human CLI actions.
    Press Ctrl+C for graceful shutdown.
    """

    async def _run():
        db = await _get_db(ctx.obj["db"])
        config_dir = ctx.obj.get("config_dir") or DEFAULT_CONFIG_DIR

        try:
            from cellos.config import load_config, ConfigError as CfgErr
            config = load_config(config_dir)
        except (CfgErr, FileNotFoundError) as e:
            console.print(f"[red]Config error: {e}[/]")
            console.print(f"  Run 'cellos init' first.")
            sys.exit(1)

        console.print(f"Starting daemon (concurrent_tasks={config.scheduler.concurrent_tasks})...")
        console.print("  Press Ctrl+C to stop.")

        from cellos.services.scheduler import DaemonService

        daemon = DaemonService(
            db=db,
            config=config,
            config_dir=config_dir,
            workdir=".",
        )

        try:
            await daemon.start()
        except KeyboardInterrupt:
            console.print("\n[yellow]Daemon stopped.[/]")

    asyncio.run(_run())


@main.command()
@click.argument("task_id", required=True)
@click.pass_context
def plan(ctx: click.Context, task_id):
    """Generate a plan for a task via agent (manual trigger).

    Triggers a planning agent to generate an implementation plan.
    Task must be in DRAFT status. Falls back to fake_acp if the configured
    agent connector is unavailable.
    """

    async def _run():
        db = await _get_db(ctx.obj["db"])
        config_dir = ctx.obj.get("config_dir") or DEFAULT_CONFIG_DIR

        try:
            from cellos.config import load_config, ConfigError as CfgErr
            config = load_config(config_dir)
        except (CfgErr, FileNotFoundError):
            console.print(f"[red]Config not found in {config_dir}. Run 'cellos init' first.[/]")
            sys.exit(1)

        task = await db.get_task(task_id)
        if task is None:
            console.print(f"[red]Error: Task {task_id} not found[/]")
            await db.close()
            sys.exit(1)

        if task.status != TaskStatus.DRAFT:
            console.print(f"[red]Error: Cannot plan task in status '{task.status.value}'. Must be 'draft'.[/]")
            await db.close()
            sys.exit(1)

        if task.role not in (AgentRole.ARCHITECT, AgentRole.COORDINATOR):
            console.print(f"[red]Error: Cannot plan task with role '{task.role.value}'. Planning is restricted to architect and coordinator roles.[/]")
            await db.close()
            sys.exit(1)

        console.print(f"▶ Planning {task_id}: {task.title}")

        try:
            from cellos.services.worker_service import run_task_worker, WorkerError as WkErr
            result = await run_task_worker(db=db, task_id=task_id, mode="planning", config=config)
            console.print(f"✓ Plan generated for {task_id}")
            console.print(f"  Status: {result.status.value}")
            _notify_daemon()
        except WkErr as e:
            console.print(f"[red]Planning error: {e}[/]")
            sys.exit(1)
        except Exception as e:
            console.print(f"[red]Unexpected error: {type(e).__name__}: {e}[/]")
            sys.exit(1)
        finally:
            await db.close()

    asyncio.run(_run())


@main.command()
@click.argument("task_id", required=True)
@click.pass_context
def execute(ctx: click.Context, task_id):
    """Execute an approved task via agent (manual trigger).

    Triggers an execution agent to run the approved task's plan.
    Task must be in APPROVED status. Falls back to fake_acp if the configured
    agent connector is unavailable.
    """

    async def _run():
        db = await _get_db(ctx.obj["db"])
        config_dir = ctx.obj.get("config_dir") or DEFAULT_CONFIG_DIR

        try:
            from cellos.config import load_config, ConfigError as CfgErr
            config = load_config(config_dir)
        except (CfgErr, FileNotFoundError):
            console.print(f"[red]Config not found in {config_dir}. Run 'cellos init' first.[/]")
            sys.exit(1)

        task = await db.get_task(task_id)
        if task is None:
            console.print(f"[red]Error: Task {task_id} not found[/]")
            await db.close()
            sys.exit(1)

        if task.status != TaskStatus.APPROVED:
            console.print(f"[red]Error: Cannot execute task in status '{task.status.value}'. Must be 'approved'.[/]")
            await db.close()
            sys.exit(1)

        console.print(f"▶ Executing {task_id}: {task.title}")

        try:
            from cellos.services.worker_service import run_task_worker, WorkerError as WkErr
            result = await run_task_worker(db=db, task_id=task_id, mode="execution", config=config)
            console.print(f"✓ Task completed with status: {result.status.value}")
            if result.result:
                console.print(f"  Result: {result.result.summary}")
            _notify_daemon()
        except WkErr as e:
            console.print(f"[red]Execution error: {e}[/]")
            sys.exit(1)
        except Exception as e:
            console.print(f"[red]Unexpected error: {type(e).__name__}: {e}[/]")
            sys.exit(1)
        finally:
            await db.close()

    asyncio.run(_run())


# ── PM Console command group ───────────────────────────────────────

@main.group(name="pmcon")
def pmcon():
    """Manage external project management integrations."""
    pass


@pmcon.command("list")
@click.pass_context
def pmcon_list(ctx: click.Context):
    """List available PM tool providers."""
    from cellos.integrations.registry import get_providers, load_provider

    providers = get_providers()
    if not providers:
        console.print("No PM tool providers registered.")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Provider", style="cyan")
    table.add_column("Description")

    for name in providers:
        try:
            prov = load_provider(name)
            desc = prov.provider_description
        except Exception:
            desc = name
        table.add_row(name, desc)

    console.print(table)


@pmcon.command("setup")
@click.argument("provider", required=True)
@click.pass_context
def pmcon_setup(ctx: click.Context, provider: str):
    """Bootstrap or validate an external PM tool integration.

    Creates or links the target resource (board, project, etc.) and persists state.
    """
    db_path = ctx.obj["db"]

    async def _run():
        from cellos.integrations.registry import load_provider

        config_dir = ctx.obj["config_dir"]
        config = load_config(config_dir)

        try:
            prov = load_provider(provider, config=config, _config_dir=config_dir)
        except ValueError as e:
            console.print(f"[red]{e}[/]")
            sys.exit(1)

        db = await _get_db(db_path)
        prov._db = db
        try:
            result = await prov.setup()
        except Exception as e:
            console.print(f"[red]Setup failed:[/] {e}")
            sys.exit(1)
        finally:
            await db.close()

        console.print(f"✓ Provider '{provider}' configured")
        console.print(f"  Target ID: {result.target_id}")
        for k, v in result.mappings.items():
            console.print(f"  {k}: {v}")

    asyncio.run(_run())


@pmcon.command("sync")
@click.argument("provider", required=True)
@click.option("--push", is_flag=True, default=False, help="Only push (Cellos → provider).")
@click.option("--pull", is_flag=True, default=False, help="Only pull (provider → Cellos).")
@click.pass_context
def pmcon_sync(ctx: click.Context, provider: str, push: bool, pull: bool):
    """Run bidirectional sync between CelloS and an external PM tool.

    By default runs both push and pull. Use --push or --pull to run only one direction.
    Cellos DB remains the authoritative source of truth.
    """
    db_path = ctx.obj["db"]

    async def _run():
        from cellos.integrations.registry import load_provider

        config_dir = ctx.obj["config_dir"]
        config = load_config(config_dir)

        do_push = push or not pull
        do_pull = pull or not push

        try:
            prov = load_provider(provider, config=config, _config_dir=config_dir)
        except ValueError as e:
            console.print(f"[red]{e}[/]")
            sys.exit(1)

        db = await _get_db(db_path)
        prov._db = db
        try:
            delta = await prov.sync(push=do_push, pull=do_pull)
        except OSError as e:
            console.print(f"[red]Missing credentials:[/] {e}")
            sys.exit(1)
        finally:
            await db.close()

        if do_push and not do_pull:
            console.print(f"✓ Push complete")
            console.print(f"  Items created: {delta.items_created}")
            console.print(f"  Items updated: {delta.items_updated}")
        elif do_pull and not do_push:
            console.print(f"✓ Pull complete")
            console.print(f"  Comments imported: {delta.comments_imported}")
            console.print(f"  Statuses changed: {delta.statuses_changed}")
        else:
            console.print(f"✓ Sync complete")
            console.print(f"  Created: {delta.items_created} | Updated: {delta.items_updated}")
            console.print(f"  Comments imported: {delta.comments_imported} | Statuses changed: {delta.statuses_changed}")

        if delta.errors:
            for err in delta.errors[:5]:
                console.print(f"  [red]Error:[/] {err}")

    asyncio.run(_run())


@pmcon.command("status")
@click.argument("provider", required=True)
@click.pass_context
def pmcon_status(ctx: click.Context, provider: str):
    """Show current configuration and sync status for a PM tool integration.

    Displays target ID, mappings, timestamps, and credential state.
    """
    db_path = ctx.obj["db"]

    async def _run():
        from cellos.integrations.registry import load_provider

        config_dir = ctx.obj["config_dir"]
        config = load_config(config_dir)

        try:
            prov = load_provider(provider, config=config, _config_dir=config_dir)
        except ValueError as e:
            console.print(f"[red]{e}[/]")
            sys.exit(1)

        db = await _get_db(db_path)
        prov._db = db
        try:
            status = await prov.status()
        finally:
            await db.close()

        lines = []

        cred_label = "[green]configured[/]" if status.credentials_configured else "[yellow]missing[/]"
        lines.append(f"[bold]{status.provider_name}[/] PM integration")
        lines.append(f"  Credentials: {cred_label}")

        if status.board_or_target:
            lines.append(f"  Target ID: [cyan]{status.board_or_target}[/]")
        else:
            action = f"'cellos pmcon setup {provider}'"
            lines.append(f"  Target: not configured — run {action}")

        details = status.details
        if details:
            list_mapping = details.get("list_mapping")
            if list_mapping:
                lines.append("")
                lines.append("List Mapping:")
                for name, lid in list_mapping.items():
                    icon = "✓" if lid != "(not mapped)" else "✗"
                    lines.append(f"  {icon} {name}: [dim]{lid}[/]")

            last_push = details.get("last_push_ts")
            last_pull = details.get("last_pull_ts")
            if last_push:
                lines.append(f"\nLast push: [dim]{last_push}[/]")
            if last_pull:
                lines.append(f"Last pull: [dim]{last_pull}[/]")

        console.print("\n".join(lines))

    asyncio.run(_run())


if __name__ == "__main__":
    main()
