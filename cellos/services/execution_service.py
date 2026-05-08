"""Execution result persistence service."""

from cellos.db import CellosDatabase
from cellos.domain.tasks import Task
from cellos.domain.results import TaskResult
from cellos.domain.enums import TaskStatus
from cellos.task_actions import parse_create_task_actions_with_errors, task_from_create_action


async def save_execution_result(
    db: CellosDatabase,
    task: Task,
    result: TaskResult,
    *,
    preapprove_research_tasks: bool,
) -> None:
    blocking_task_ids: list[str] = []
    if result.success:
        actions, action_errors = parse_create_task_actions_with_errors(result.summary)
        for action_error in action_errors:
            await db.record_task_event(
                task.id,
                "invalid_task_action",
                "Skipped invalid structured task action",
                {"error": action_error},
            )
        for action in actions:
            child = task_from_create_action(
                action,
                task,
                preapprove_research_tasks=preapprove_research_tasks,
            )
            await db.create_task(child)
            await db.record_task_event(
                task.id,
                "child_task_created",
                f"Created child task {child.id}: {child.title}",
                {"child_task_id": child.id, "blocks_parent": action.blocks_parent},
            )
            if action.blocks_parent:
                blocking_task_ids.append(child.id)

    await db.save_task_result(result)
    if blocking_task_ids:
        current = await db.get_task(task.id)
        if current is None:
            raise ValueError(f"Task not found: {task.id}")
        dependencies = list(current.dependencies)
        for child_id in blocking_task_ids:
            if child_id not in dependencies:
                dependencies.append(child_id)
        await db.update_task(
            current.model_copy(
                update={
                    "status": TaskStatus.BLOCKED,
                    "dependencies": dependencies,
                }
            )
        )
        await db.record_task_event(
            task.id,
            "blocked_on_children",
            f"Task blocked on child task(s): {', '.join(blocking_task_ids)}",
            {"child_task_ids": blocking_task_ids},
        )
        await db.conn.commit()
