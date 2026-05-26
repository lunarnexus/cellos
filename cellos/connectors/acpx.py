"""acpx connector — calls acpx CLI directly for ACP task execution.

Uses npx acpx as a headless CLI client. Handles all ACP protocol internally,
so we just pass a prompt and get structured JSON output back.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from cellos.connectors.base import TaskConnector
from cellos.models import Task, TaskResult

logger = logging.getLogger(__name__)


class AcpxConnector:
    """Connector that calls acpx CLI directly.

    acpx handles the full ACP protocol (session management, JSON-RPC, etc.)
    internally. We pass a prompt and get back structured JSON output.

    Args:
        options: Connector-specific options from agent catalog.
            - timeout_seconds: Max wait time (default: 300)
            - approve_mode: Permission policy (default: "approve-all")
            - model: Agent model ID (optional)
            - allowed_tools: Comma-separated tool names (optional)
            - max_turns: Max turns for the session (optional)
            - agent: Raw ACP agent command override (optional)
    """

    def __init__(self, options: dict[str, Any] | None = None):
        self.options = options or {}
        self.timeout = int(self.options.get("timeout_seconds", 1200))
        self.approve_mode = self.options.get("approve_mode", "approve-all")
        self.model = self.options.get("model")
        self.allowed_tools = self.options.get("allowed_tools")
        self.max_turns = self.options.get("max_turns")
        self.agent = self.options.get("agent")

    async def run_task(
        self, task: Task, workdir: str | None = None, mode: str = "execution", prompt_text: str | None = None
    ) -> TaskResult:
        """Execute a task via acpx CLI.

        Args:
            task: The task being executed.
            workdir: Working directory for the agent.
            mode: "planning" or "execution".
            prompt_text: The assembled prompt to send to the agent.

        Returns:
            TaskResult with success, summary, and full output.
        """
        # acpx command structure: npx acpx [global options] [agent] exec [prompt]
        # Global options (--format, --approve-all, etc.) must come before the agent name
        cmd = [
            "npx", "acpx",
            "--format", "json",
            f"--{self.approve_mode}",
        ]

        if self.model:
            cmd.extend(["--model", self.model])
        if self.allowed_tools:
            cmd.extend(["--allowed-tools", self.allowed_tools])
        if self.max_turns:
            cmd.extend(["--max-turns", str(self.max_turns)])
        if self.agent:
            cmd.extend(["--agent", self.agent])

        # Agent name (default: opencode)
        agent_name = self.options.get("agent_name", "opencode")
        cmd.append(agent_name)

        # exec subcommand for one-shot execution
        cmd.append("exec")

        # Append the prompt as the final argument
        cmd.append(prompt_text or "")

        logger.info(
            "Running acpx for task %s mode=%s cmd='%s'",
            task.id, mode, " ".join(cmd[:10]) + "...",
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir or ".",
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout + 30
            )

            raw_output = stdout.decode().strip()
            stderr_output = stderr.decode().strip()

            logger.info("acpx raw output length for task %s: %d bytes", task.id, len(raw_output))

            if stderr_output:
                logger.debug("acpx stderr for task %s: %s", task.id, stderr_output[:500])

            # acpx --format json outputs NDJSON (newline-delimited JSON)
            # We want the final agent output, so parse the last meaningful line
            output_text = self._extract_output(raw_output)

            logger.info("acpx extracted output length for task %s: %d chars", task.id, len(output_text))

            success = proc.returncode == 0

            return TaskResult(
                success=success,
                summary=output_text[:500] if output_text else "No output from agent",
                output=output_text,
            )

        except asyncio.TimeoutError:
            logger.error("acpx timed out for task %s after %ds", task.id, self.timeout)
            return TaskResult(
                success=False,
                summary=f"Agent timed out after {self.timeout} seconds",
                output="",
            )
        except FileNotFoundError:
            logger.error("acpx not found - ensure npx is available")
            return TaskResult(
                success=False,
                summary="acpx not found - ensure Node.js and npx are installed",
                output="",
            )

    def _extract_output(self, raw_output: str) -> str:
        """Extract meaningful output from acpx NDJSON stream.

        acpx --format json outputs newline-delimited JSON. We look for
        agent_message_chunk events first, then fall back to agent_thought_chunk
        events (opencode routes all content through thinking blocks).
        """
        if not raw_output:
            return ""

        message_chunks = []
        thought_chunks = []

        for line in raw_output.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if isinstance(msg, dict) and msg.get("method") == "session/update":
                    update = msg.get("params", {}).get("update", {})
                    event_type = update.get("sessionUpdate", "")
                    content = update.get("content", {})

                    if event_type == "agent_message_chunk" and isinstance(content, dict):
                        text = content.get("text", "")
                        if text:
                            message_chunks.append(text)
                    elif event_type == "agent_thought_chunk" and isinstance(content, dict):
                        text = content.get("text", "")
                        if text:
                            thought_chunks.append(text)
            except json.JSONDecodeError:
                pass

        # Prefer message chunks; fall back to thought chunks (opencode behavior)
        if message_chunks:
            logger.info("acpx extracted %d message chunks", len(message_chunks))
            return "".join(message_chunks)

        if thought_chunks:
            logger.info("acpx extracted %d thought chunks (no message chunks)", len(thought_chunks))
            return "".join(thought_chunks)

        logger.warning("acpx extracted no chunks, falling back to raw output")
        return raw_output[:5000]


__all__ = ["AcpxConnector"]
