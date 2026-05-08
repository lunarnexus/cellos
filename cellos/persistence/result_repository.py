"""Task result persistence for CelloS."""

from cellos.domain.attention import AttentionReason
from cellos.domain.comments import TaskComment
from cellos.domain.enums import CommentAuthorType, TaskStatus, TaskType
from cellos.domain.results import TaskResult
from cellos.domain.tasks import Task
from cellos.persistence.serialization import json_payload


async def save_task_result(conn, result: TaskResult, database) -> None:
    await conn.execute(
        """
        INSERT INTO task_results (task_id, success, created_at, payload)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(task_id) DO UPDATE SET
            success = excluded.success,
            created_at = excluded.created_at,
            payload = excluded.payload
        """,
        (
            result.task_id,
            int(result.success),
            result.created_at.isoformat(),
            result.model_dump_json(),
        ),
    )
    task = await database.get_task(result.task_id)
    if task is not None:
        if result.change_request is not None:
            status = TaskStatus.CHANGE_REQUESTED
        else:
            status = TaskStatus.DONE if result.success else TaskStatus.FAILED
        await database.update_task(task.model_copy(update={"result": result, "status": status}))
    if result.success:
        completed_task = await database.get_task(result.task_id)
        if completed_task is not None:
            await _add_dependency_result_comments(conn, completed_task, result, database)
        await _wake_satisfied_blocked_dependents(conn, result.task_id, database)
    await database.record_task_event(result.task_id, "result_saved", result.summary)
    await conn.commit()


async def _wake_satisfied_blocked_dependents(conn, completed_task_id, database) -> None:
    for dependent in await database.list_tasks_depending_on(completed_task_id):
        if dependent.status != TaskStatus.BLOCKED:
            continue
        if not await database.dependencies_satisfied(dependent):
            continue
        updated = dependent.model_copy(update={"status": TaskStatus.DRAFT}).requires_attention(
            AttentionReason.DEPENDENCY_DONE,
            "Dependency completed; task is ready for replanning",
        )
        await database.update_task(updated)
        await database.record_task_event(dependent.id, "dependency_done", f"Dependency completed: {completed_task_id}")


async def _add_dependency_result_comments(conn, completed_task: Task, result: TaskResult, database) -> None:
    for dependent in await database.list_tasks_depending_on(completed_task.id):
        if completed_task.task_type == TaskType.RESEARCH:
            title = f"Research Results from {completed_task.id} - {completed_task.title}"
            kind = "research_result"
        else:
            title = f"Dependency Result from {completed_task.id} - {completed_task.title}"
            kind = "dependency_result"
        await database.add_task_comment(
            TaskComment(
                task_id=dependent.id,
                author_type=CommentAuthorType.SYSTEM,
                author_id="cellos",
                message=f"{title}\n\n{result.summary}",
                metadata={
                    "kind": kind,
                    "dependency_task_id": completed_task.id,
                    "dependency_task_type": completed_task.task_type.value,
                },
            )
        )
