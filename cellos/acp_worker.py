"""ACP worker backend."""

from pathlib import Path

from cellos.acp import exec_task
from cellos.models import AgentRole, Task, TaskResult


ROLE_INSTRUCTIONS = {
    AgentRole.COORDINATOR: "Coordinate project direction, clarify scope, and produce human-reviewable plans.",
    AgentRole.RESEARCHER: "Research only. Report findings, assumptions, evidence, and uncertainties.",
    AgentRole.ARCHITECT: "Design task boundaries, dependencies, acceptance criteria, and implementation approach.",
    AgentRole.ENGINEER: "Perform approved implementation work within scope and report concise results.",
    AgentRole.TESTER: "Verify work against scope, report evidence, risks, and pass/fail findings.",
}

MODE_INSTRUCTIONS = {
    "planning": [
        "Mode: planning",
        "Draft or revise a plan only.",
        "Do not perform write actions, run commands, create tasks, or execute the plan.",
        "Return a concise plan suitable for human approval.",
    ],
    "execution": [
        "Mode: execution",
        "Perform only the approved task scope.",
        "Do not expand scope or redesign the plan.",
        "If the task cannot be completed as approved, return a concise change request report.",
    ],
}


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

    async def run_task(self, task: Task, cwd: Path, mode: str = "execution") -> TaskResult:
        result = await exec_task(
            command=self.command,
            cwd=cwd,
            prompt=build_task_prompt(task, mode=mode),
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
                "mode": mode,
                "result": result.result,
            },
        )


def build_task_prompt(task: Task, mode: str = "execution") -> str:
    mode_instructions = MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["execution"])
    parts = [
        f"Role: {task.role.value}",
        f"Task type: {task.task_type.value}",
        f"Title: {task.title}",
        f"Status: {task.status.value}",
        "",
        "Role instructions:",
        ROLE_INSTRUCTIONS[task.role],
        "",
        *mode_instructions,
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
