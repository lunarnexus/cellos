"""Base connector protocol — duck-typed interface for agent backends."""

from __future__ import annotations

import typing
from dataclasses import dataclass
from typing import Any

from cellos.models import Task, TaskResult


@dataclass
class ToolCallInfo:
    """Information about a non-required tool call made by the agent."""
    title: str  # e.g. "cellos_create_task"
    arguments: dict[str, Any]  # raw tool call payload


@dataclass
class ConnectorResult:
    """Wraps a TaskResult with structured data and optional diagnostics.

    Connectors return this to carry both the task outcome, any structured
    result from tool calls, non-required tool calls, and structured
    diagnostics from the agent (session IDs, timestamps, etc.).
    """
    task_result: TaskResult
    structured_result: dict[str, Any] | None = None
    tool_calls: list[ToolCallInfo] | None = None
    diagnostics: dict[str, Any] | None = None


class TaskConnector(typing.Protocol):
    """Protocol defining the interface all agent connectors must implement.

    Connectors abstract away how tasks are executed — whether via real ACP agents,
    subprocess tools, or canned responses for testing. The orchestration layer
    only depends on this protocol.
    """

    async def run_task(
        self,
        task: Task,
        workdir: str | None = None,
        mode: str = "execution",
        prompt_text: str | None = None,
        config: Any | None = None,
    ) -> ConnectorResult: ...
