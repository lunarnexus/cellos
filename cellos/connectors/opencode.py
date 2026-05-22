"""OpenCode connector — real agent execution via ACP JSON-RPC 2.0 subprocess."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from cellos.acp import AcpError, exec_task
from cellos.connectors.base import TaskConnector
from cellos.models import Task, TaskResult

logger = logging.getLogger(__name__)


# Standard locations where opencode binary might live
_OPENCODE_PATHS = [
    Path.home() / ".opencode" / "bin" / "opencode",
]


class OpenCodeError(Exception):
    """Raised when the opencode connector encounters an error."""


def resolve_opencode_command() -> list[str]:
    """Find the opencode binary and return ``[path, "acp"]``.

    Searches standard install locations first, then falls back to ``$PATH``.

    Raises:
        FileNotFoundError: If no opencode binary is found anywhere.
    """
    for p in _OPENCODE_PATHS:
        if p.exists() and os.access(p, os.X_OK):
            return [str(p), "acp"]

    cmd = shutil.which("opencode")
    if cmd:
        return [cmd, "acp"]

    raise FileNotFoundError(
        "OpenCode binary not found. Install it or set the path in your agent catalog."
    )


class OpenCodeConnector(TaskConnector):
    """Runs tasks via an external opencode ACP subprocess.

    Wraps :func:`cellos.acp.exec_task` with binary resolution and result parsing.

    Args:
        options: Agent-specific options from the config catalog (unused, reserved).
        timeout_seconds: Total time budget for the entire call cycle.
        spawn_timeout: Max seconds to wait for subprocess startup.
    """

    def __init__(
        self,
        options: dict[str, Any] | None = None,
        timeout_seconds: int = 300,
        spawn_timeout: float = 5.0,
    ):
        self.options = options or {}
        self.timeout_seconds = timeout_seconds
        self.spawn_timeout = spawn_timeout

        try:
            self._command = resolve_opencode_command()
        except FileNotFoundError as e:
            raise OpenCodeError(f"Cannot initialize connector: {e}") from e

    async def run_task(
        self, task: Task, workdir: str | None = None, mode: str = "execution", prompt_text: str | None = None
    ) -> TaskResult:
        """Execute the task via opencode ACP subprocess.

        Args:
            task: The task being executed (used for logging).
            workdir: Working directory for the subprocess. Defaults to cwd.
            mode: ``"planning"`` or ``"execution"`` — logged, not sent to agent.
            prompt_text: The assembled prompt to send to the agent.

        Returns:
            TaskResult with success/summary from the agent's response text.

        Raises:
            OpenCodeError: If subprocess fails to start or protocol errors occur.
        """
        if not prompt_text:
            prompt_text = task.details or ""

        logger.info("OpenCode connector (pid=?) for task %s mode=%s", task.id, mode)

        try:
            result = await exec_task(
                command=self._command,
                prompt=prompt_text,
                timeout_seconds=self.timeout_seconds,
                spawn_timeout=self.spawn_timeout,
                cwd=workdir or ".",
            )
        except AcpError as e:
            raise OpenCodeError(f"ACP call failed for task {task.id}: {e}") from e

        return self._parse_result(result.text, mode)

    @staticmethod
    def _parse_result(text: str, mode: str) -> TaskResult:
        """Extract success/summary from agent output text."""
        truncated = (text[:5000] + "...") if len(text) > 5000 else text

        lower = text.lower()
        failed = any(kw in lower for kw in ("failed", "error:", "cannot complete"))
        success = not failed and bool(text.strip())

        summary_prefix = f"[{mode}]"
        if len(truncated) > 500:
            return TaskResult(success=success, summary=f"{summary_prefix} {truncated[:500]}", output=text)
        return TaskResult(success=success, summary=f"{summary_prefix} {truncated}", output=text)
