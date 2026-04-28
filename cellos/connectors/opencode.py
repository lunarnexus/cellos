"""OpenCode ACP connector."""

from pathlib import Path

from cellos.acp import exec_task
from cellos.agents import build_task_prompt
from cellos.models import Task, TaskResult


class OpenCodeAcpBackend:
    def __init__(self, command: list[str] | None = None, timeout_seconds: int | None = None):
        self.command = command or ["opencode", "acp"]
        self.timeout_seconds = timeout_seconds

    async def run_task_once(self, task: Task, cwd: str | Path) -> TaskResult:
        result = await exec_task(
            command=[*self.command, "--cwd", str(cwd)],
            cwd=cwd,
            prompt=build_task_prompt(task),
            timeout_seconds=task.timeout_seconds or self.timeout_seconds,
            debug_log_path=Path(cwd) / ".cellos" / "acp-debug.log",
            skip_non_json_stdout=True,
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
