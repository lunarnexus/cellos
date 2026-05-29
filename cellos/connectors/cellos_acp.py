"""Cellos-ACP connector — wraps cellos-acp AcpClient for TaskConnector protocol."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from cellos.connectors.base import ConnectorResult
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
    ) -> ConnectorResult:
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

            task_result = TaskResult(
                success=result.success,
                summary=output[:500] if output else "No output from agent",
                output=output,
            )

            # Extract diagnostics from AcpRunResult (graceful degradation)
            diagnostics = _extract_diagnostics(result, self.agent_name, self.model)

            return ConnectorResult(task_result=task_result, diagnostics=diagnostics)

        except Exception as e:
            logger.error("cellos-acp failed for task %s: %s", task.id, e)
            task_result = TaskResult(
                success=False,
                summary=f"Agent execution failed: {e}",
                output="",
            )
            diagnostics = {
                "error_type": type(e).__name__,
                "error_message": str(e),
                "agent_provider": self.agent_name,
                "agent_model": self.model,
            }
            return ConnectorResult(task_result=task_result, diagnostics=diagnostics)


def _extract_diagnostics(result: Any, agent_name: str, model: str | None) -> dict[str, Any]:
    """Extract diagnostic fields from an AcpRunResult.

    Uses getattr with defaults for graceful degradation when cellos-acp
    doesn't yet provide the new fields.
    """
    diagnostics: dict[str, Any] = {
        "agent_provider": agent_name,
        "agent_model": model,
    }

    # Session/message IDs
    session_id = getattr(result, "session_id", None)
    message_id = getattr(result, "message_id", None)
    if session_id:
        diagnostics["session_id"] = session_id
    if message_id:
        diagnostics["message_id"] = message_id

    # Timestamps
    started_at = getattr(result, "started_at", None)
    completed_at = getattr(result, "completed_at", None)
    last_event_at = getattr(result, "last_event_at", None)
    if started_at:
        diagnostics["started_at"] = started_at
    if completed_at:
        diagnostics["completed_at"] = completed_at
    if last_event_at:
        diagnostics["last_event_at"] = last_event_at

    # Last event type
    last_event_type = getattr(result, "last_event_type", None)
    if last_event_type:
        diagnostics["last_event_type"] = last_event_type

    # Previews
    last_message_preview = getattr(result, "last_message_preview", None)
    last_thought_preview = getattr(result, "last_thought_preview", None)
    if last_message_preview:
        diagnostics["last_message_preview"] = last_message_preview
    if last_thought_preview:
        diagnostics["last_thought_preview"] = last_thought_preview

    # Timeout/abort flags
    timeout = getattr(result, "timeout", None)
    aborted = getattr(result, "aborted", None)
    if timeout:
        diagnostics["timeout"] = timeout
    if aborted:
        diagnostics["aborted"] = aborted

    # Error info
    error_type = getattr(result, "error_type", None)
    error_message = getattr(result, "error_message", None)
    if error_type:
        diagnostics["error_type"] = error_type
    if error_message:
        diagnostics["error_message"] = error_message

    # Active tool calls
    active_tool_calls = getattr(result, "active_tool_calls", None)
    if active_tool_calls and len(active_tool_calls) > 0:
        first_tool = active_tool_calls[0]
        diagnostics["active_tool_name"] = getattr(first_tool, "title", "") or getattr(first_tool, "name", "")
        diagnostics["active_tool_call_id"] = getattr(first_tool, "tool_call_id", None)
        nested = getattr(first_tool, "nested_session_id", None)
        if nested:
            diagnostics["nested_session_id"] = nested

    # Tool calls
    tool_calls = getattr(result, "tool_calls", None)
    if tool_calls and len(tool_calls) > 0:
        diagnostics["tool_calls_count"] = len(tool_calls)

    # Stop reason
    stop_reason = getattr(result, "stop_reason", None)
    if stop_reason:
        diagnostics["stop_reason"] = stop_reason

    return diagnostics


__all__ = ["CellosAcpConnector", "ConnectorResult"]
