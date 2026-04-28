"""Agent orchestration boundary for CelloS.

Intent:
- Keep agent lifecycle code separate from task scheduling and persistence.
- Start with one-task-per-session execution: spawn agent, run task, collect
  result, then close the session/process.
- Use OpenCode as the first real backend.
- Do not add session reuse yet; add it later behind this boundary.
- Keep backend-specific details out of the orchestrator. OpenCode, Hermes,
  OpenClaw, Codex, and Claude Code should eventually plug in here through a
  shared interface.
- ACP may be one backend transport, but this module should not assume ACP is the
  only way to run agents.
"""

from pathlib import Path
from typing import Protocol

from cellos.models import Task, TaskResult


class AgentBackend(Protocol):
    async def run_task_once(self, task: Task, cwd: str | Path) -> TaskResult: ...


def build_task_prompt(task: Task) -> str:
    return "\n".join(
        [
            f"Role: {task.role.value}",
            f"Task type: {task.task_type.value}",
            f"Title: {task.title}",
            "",
            task.description.strip() or "Complete the task described by the title.",
        ]
    )
