"""Planning result persistence service."""

from cellos.db import CellosDatabase
from cellos.models import Task, TaskResult, TaskStatus


async def save_planning_result(db: CellosDatabase, task: Task, result: TaskResult) -> None:
    current = await db.get_task(task.id)
    if current is None:
        raise ValueError(f"Task not found: {task.id}")
    updated = current.clear_attention().model_copy(
        update={
            "plan": result.summary,
            "prompt": result.summary,
            "result": result,
            "status": TaskStatus.NEEDS_APPROVAL,
        }
    )
    await db.update_task(updated)
    await db.record_task_event(task.id, "planning_saved", "Planning result saved; task needs approval")
    await db.conn.commit()
