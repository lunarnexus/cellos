"""Cellos-ACP connector — wraps cellos-acp AcpClient for TaskConnector protocol."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from cellos.config import get_tools_for_role_mode
from cellos.connectors.base import ConnectorResult, ToolCallInfo
from cellos.models import Task, TaskResult

logger = logging.getLogger(__name__)

_CELLOS_RESULT_TOOL_PREFIX = "cellos-result-tools_"


def _normalize_tool_title(title: str) -> str:
    if title.startswith(_CELLOS_RESULT_TOOL_PREFIX):
        return title[len(_CELLOS_RESULT_TOOL_PREFIX):]
    return title


def _payload_to_dict(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        if "output" in payload:
            output_val = payload["output"]
            if isinstance(output_val, str):
                try:
                    output_val = json.loads(output_val)
                except (json.JSONDecodeError, ValueError):
                    pass
            if isinstance(output_val, dict):
                if set(output_val.keys()) == {"result"} and isinstance(output_val["result"], dict):
                    return output_val["result"]
                return output_val
        if set(payload.keys()) == {"result"} and isinstance(payload["result"], dict):
            return payload["result"]
        return payload
    return {}


def _tool_call_arguments(tool_call: Any) -> dict[str, Any]:
    raw_input = getattr(tool_call, "raw_input", None) or {}
    if raw_input:
        return _payload_to_dict(raw_input)
    return _payload_to_dict(getattr(tool_call, "raw_output", None))


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
        self,
        task: Task,
        workdir: str | None = None,
        mode: str = "execution",
        prompt_text: str | None = None,
        config: Any | None = None,
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

        # Resolve tools from config
        output_tools: list[dict[str, Any]] | None = None
        required_tool: str | None = None
        if config is not None:
            role = str(task.role) if task.role else "engineer"
            tool_names, required_tool = get_tools_for_role_mode(
                getattr(config, "tool_profiles", {}), role, mode
            )
            if tool_names:
                tools_dict = getattr(config, "tools", {})
                output_tools = []
                for name in tool_names:
                    tool_def = tools_dict.get(name)
                    if tool_def:
                        output_tools.append({
                            "name": name,
                            "description": tool_def.description,
                            "parameters": tool_def.schema_,
                        })
                        logger.debug("Tool %s registered for task %s", name, task.id)

        client = AcpClient(
            agent=self.agent_name,
            cwd=cwd,
            env=env,
            auto_approve=self.auto_approve,
            timeout=self.timeout,
            text_wait=self.text_wait,
        )

        logger.info(
            "Running cellos-acp for task %s mode=%s agent=%s tools=%s",
            task.id, mode, self.agent_name,
            len(output_tools) if output_tools else 0,
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
            result = await client.run(
                prompt_text or "",
                output_tools=output_tools,
                required_output_tool=required_tool,
            )

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

            # Extract structured result from tool call
            structured_result: dict[str, Any] | None = None
            if result.structured_result is not None:
                structured_result = result.structured_result.data
                logger.info(
                    "Structured result captured for task %s: %s",
                    task.id, list(structured_result.keys()),
                )

            # Extract Cellos tool calls (e.g. cellos_create_task). ACP/MCP
            # reports output-tool payloads in raw_output, not raw_input.
            tool_calls: list[ToolCallInfo] | None = None
            result_tool_calls = getattr(result, "tool_calls", None) or []
            captured_tool_calls: list[ToolCallInfo] = []
            for tc in result_tool_calls:
                title = _normalize_tool_title(getattr(tc, "title", "") or "")
                if not title.startswith("cellos_"):
                    continue
                if title == required_tool and title != "cellos_create_task":
                    continue
                captured_tool_calls.append(ToolCallInfo(title, _tool_call_arguments(tc)))

            if captured_tool_calls:
                tool_calls = captured_tool_calls
                logger.info(
                    "Tool calls captured for task %s: %d calls",
                    task.id, len(tool_calls),
                )

            # Extract diagnostics from AcpRunResult (graceful degradation)
            diagnostics = _extract_diagnostics(result, self.agent_name, self.model)

            return ConnectorResult(
                task_result=task_result,
                structured_result=structured_result,
                tool_calls=tool_calls,
                diagnostics=diagnostics,
            )

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
