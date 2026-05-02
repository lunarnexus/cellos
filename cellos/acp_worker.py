"""ACP worker backend."""

from pathlib import Path

from cellos.acp import exec_task
from cellos.models import Task, TaskResult


class AcpWorker:
    def __init__(
        self,
        command: list[str],
        timeout_seconds: int | None = None,
        debug_log_path: str | Path | None = None,
        skip_non_json_stdout: bool = True,
    ):
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.debug_log_path = Path(debug_log_path) if debug_log_path is not None else None
        self.skip_non_json_stdout = skip_non_json_stdout

    async def run_task(self, task: Task, cwd: Path) -> TaskResult:
        result = await exec_task(
            command=self.command,
            cwd=cwd,
            prompt=build_task_prompt(task),
            timeout_seconds=task.timeout_seconds or self.timeout_seconds,
            debug_log_path=self.debug_log_path or Path(cwd) / ".cellos" / "logs" / "acp-debug.log",
            skip_non_json_stdout=self.skip_non_json_stdout,
            ignore_close_not_found=True,
        )
        return TaskResult(
            task_id=task.id,
            success=result.stop_reason in {None, "end_turn"},
            summary=result.text.strip() or f"Agent stopped with {result.stop_reason}",
            output={
                "session_id": result.session_id,
                "stop_reason": result.stop_reason,
                "event_count": len(result.events),
                "result": result.result,
            },
        )


def build_task_prompt(task: Task) -> str:
    parts = [
        f"Role: {task.role.value}",
        f"Task type: {task.task_type.value}",
        f"Title: {task.title}",
        f"Status: {task.status.value}",
        "",
    ]
    if task.prompt.strip():
        parts.extend(["Task prompt / approved scope:", task.prompt.strip(), ""])
    if task.description.strip():
        parts.extend(["Additional description:", task.description.strip(), ""])
    parts.extend(
        [
            "Report the result concisely.",
            "If the approved task cannot be completed as scoped, provide a change request report.",
        ]
    )
    return "\n".join(parts)
