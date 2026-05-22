"""Base connector protocol — duck-typed interface for agent backends."""

from __future__ import annotations

import typing
from cellos.models import Task, TaskResult


class TaskConnector(typing.Protocol):
    """Protocol defining the interface all agent connectors must implement.

    Connectors abstract away how tasks are executed — whether via real ACP agents,
    subprocess tools, or canned responses for testing. The orchestration layer
    only depends on this protocol.
    """

    async def run_task(
        self, task: Task, workdir: str | None = None, mode: str = "execution", prompt_text: str | None = None
    ) -> TaskResult: ...
