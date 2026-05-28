"""Cellos-ACP connector — wraps cellos-acp AcpClient for TaskConnector protocol."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from cellos.connectors.base import TaskConnector
from cellos.models import Task, TaskResult

logger = logging.getLogger(__name__)


class CellosAcpConnector:
    """Connector that uses cellos-acp AcpClient for ACP task execution.

    Args:
        options: Connector-specific options from agent catalog.
            - agent: Agent name from cellos-acp registry (default: "opencode")
            - timeout_seconds: Max wait time (default: 300)
            - auto_approve: Auto-approve permissions (default: true)
            - text_wait: Seconds to wait for late chunks (default: 2.0)
            - log_file: Enable cellos-acp DEBUG logging to this file (optional)
            - model: Model ID - passed via agent-specific env var (optional)
    """

    def __init__(self, options: dict[str, Any] | None = None):
        self.options = options or {}
        self.agent_name = self.options.get("agent", "opencode")
        self.timeout = int(self.options.get("timeout_seconds", 300))
        self.auto_approve = self.options.get("auto_approve", True)
        self.text_wait = float(self.options.get("text_wait", 2.0))
        self.log_file = self.options.get("log_file")
        self.model = self.options.get("model")

    async def run_task(
        self, task: Task, workdir: str | None = None, mode: str = "execution", prompt_text: str | None = None
    ) -> TaskResult:
        """Execute a task via cellos-acp AcpClient."""
        from cellos_acp import AcpClient, configure_logging

        cwd = workdir or "."

        if self.log_file:
            acp_log_file = str(Path(str(self.log_file)).expanduser())
            configure_logging(acp_log_file)
            logger.debug("cellos-acp library debug logging enabled at %s", acp_log_file)

        # Build env for model override (opencode uses OPENCODE_CONFIG_CONTENT)
        env = None
        if self.model:
            env = {"OPENCODE_CONFIG_CONTENT": json.dumps({"model": self.model})}

        client = AcpClient(
            agent=self.agent_name,
            cwd=cwd,
            env=env,
            auto_approve=self.auto_approve,
            timeout=self.timeout,
            text_wait=self.text_wait,
        )

        logger.info(
            "Running cellos-acp for task %s mode=%s agent=%s",
            task.id, mode, self.agent_name,
        )
        logger.debug(
            "cellos-acp request for task %s mode=%s prompt_chars=%d prompt_repr=%r",
            task.id, mode, len(prompt_text or ""), prompt_text or "",
        )
        logger.debug(
            "cellos-acp request body for task %s mode=%s BEGIN\n%s\ncellos-acp request body END",
            task.id, mode, prompt_text or "",
        )

        try:
            result = await client.run(prompt_text or "")

            output = result.combined_text
            raw_text = getattr(result, "text", "")
            raw_thinking = getattr(result, "thinking", "")
            if not isinstance(raw_text, str):
                raw_text = ""
            if not isinstance(raw_thinking, str):
                raw_thinking = ""
            logger.info(
                "cellos-acp returned for task %s: success=%s chars=%d stop=%s",
                task.id, result.success, len(output), result.stop_reason,
            )
            logger.debug(
                "cellos-acp response metadata for task %s mode=%s success=%s stop=%s text_chars=%d thinking_chars=%d combined_chars=%d",
                task.id, mode, result.success, result.stop_reason,
                len(raw_text), len(raw_thinking), len(output),
            )
            logger.debug(
                "cellos-acp response text for task %s mode=%s repr=%r",
                task.id, mode, raw_text,
            )
            logger.debug(
                "cellos-acp response thinking for task %s mode=%s repr=%r",
                task.id, mode, raw_thinking,
            )
            logger.debug(
                "cellos-acp response combined for task %s mode=%s repr=%r",
                task.id, mode, output,
            )
            logger.debug(
                "cellos-acp response combined body for task %s mode=%s BEGIN\n%s\ncellos-acp response combined body END",
                task.id, mode, output,
            )

            return TaskResult(
                success=result.success,
                summary=output[:500] if output else "No output from agent",
                output=output,
            )

        except Exception as e:
            logger.error("cellos-acp failed for task %s: %s", task.id, e)
            return TaskResult(
                success=False,
                summary=f"Agent execution failed: {e}",
                output="",
            )


__all__ = ["CellosAcpConnector"]
