"""Rich table and console formatters for CelloS CLI output."""

from rich.console import Console
from rich.table import Table

from cellos.models import Task

console = Console()


def status_formatter(tasks: list[Task]) -> None:
    """Render task list as a Rich table."""
    table = Table(title="CelloS Tasks")
    table.add_column("ID", no_wrap=True)
    table.add_column("Status")
    table.add_column("Role")
    table.add_column("Type")
    table.add_column("Title")
    table.add_column("Result")
    for task in tasks:
        result = task.result.summary if task.result is not None else ""
        table.add_row(
            task.id,
            task.status.value,
            task.role.value,
            task.task_type.value,
            task.title,
            result,
        )
    console.print(table)


def events_formatter(events: list[dict]) -> None:
    """Render event list as a Rich table."""
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


def detail_formatter(
    task: Task,
    comments: list[dict],
    attempts: list[dict],
    events: list[dict],
) -> None:
    """Render task detail with prompt, comments, attempts, and events."""
    console.print(f"[bold]{task.title}[/bold]")
    console.print(f"ID: {task.id}")
    console.print(f"Status: {task.status.value}")
    console.print(f"Role: {task.role.value}")
    console.print(f"Type: {task.task_type.value}")
    if task.agent_id:
        console.print(f"Agent: {task.agent_id}")
    if task.parent_id:
        console.print(f"Parent: {task.parent_id}")
    if task.dependencies:
        console.print(f"Dependencies: {', '.join(task.dependencies)}")
    console.print("")
    if task.details:
        console.print("[bold]Details[/bold]")
        console.print(task.details)
        console.print("")
    if task.success_criteria:
        console.print("[bold]Success Criteria[/bold]")
        console.print(task.success_criteria)
        console.print("")
    if task.failure_criteria:
        console.print("[bold]Failure Criteria[/bold]")
        console.print(task.failure_criteria)
        console.print("")
    if task.plan:
        console.print("[bold]Plan[/bold]")
        console.print(task.plan)
        console.print("")
    console.print("[bold]Prompt[/bold]")
    console.print(task.prompt or "")
    if task.conversation:
        console.print("")
        console.print("[bold]Conversation[/bold]")
        for msg in task.conversation:
            console.print(f"- ({msg.author}) @{msg.id}: {msg.message}")
    if task.result is not None:
        console.print("")
        console.print("[bold]Result[/bold]")
        console.print(task.result.summary)
    if comments:
        console.print("")
        console.print("[bold]Recent Comments[/bold]")
        for comment in comments:
            author = comment["author_id"] or comment["author_type"]
            console.print(f"- {author}: {comment['message']}")
    if attempts:
        console.print("")
        console.print("[bold]Attempts[/bold]")
        for attempt in attempts:
            summary = attempt["result_summary"] or attempt["error"] or attempt["log_path"]
            console.print(
                f"- #{attempt['id']} {attempt['mode']} {attempt['status']} "
                f"via {attempt['agent_id']} ({attempt['connector']}): {summary}"
            )
    if events:
        console.print("")
        console.print("[bold]Recent Events[/bold]")
        for event in events:
            console.print(f"- {event['event_type']}: {event['message']}")
