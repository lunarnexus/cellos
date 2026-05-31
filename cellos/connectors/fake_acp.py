"""Fake ACP connector — deterministic canned responses for testing and development."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cellos.connectors.base import ConnectorResult, ToolCallInfo
from cellos.models import Task, TaskResult


class FakeAcpConnector:
    """Returns deterministic results from fixture files or configurable defaults.

    Fixture lookup order:
      1. ``{fixture_dir}/{task_id}-{mode}.json`` — task-specific + mode-specific
      2. ``{fixture_dir}/{mode}.json`` — mode-only fallback
      3. ``{fixture_dir}/default.json`` — universal fallback
      4. Configured defaults (``options["default_success"]``, ``options["default_summary"]``)

    Each fixture file should contain a JSON object with at least:
        - ``success`` (bool)
        - ``summary`` (str)
        Optional: ``output`` (str), ``diagnostics`` (dict),
        ``structured_result`` (dict), ``tool_calls`` (list)
    """

    def __init__(self, options: dict[str, Any] | None = None):
        self.options = options or {}
        self.fixture_dir: str | None = self.options.get("fixture_dir")
        self.default_success: bool = self.options.get("default_success", True)
        self.default_summary: str = self.options.get(
            "default_summary", "Task completed successfully."
        )

    async def run_task(
        self,
        task: Task,
        workdir: str | None = None,
        mode: str = "execution",
        prompt_text: str | None = None,
        config: Any | None = None,
    ) -> ConnectorResult:
        """Execute a task with canned responses.

        Simulates a 0.1 s delay to mimic real agent latency without blocking tests.
        """
        await _async_sleep(0.05)
        return self._resolve_result(task, mode, prompt_text)

    # ── Fixture resolution (synchronous — safe to call from tests) ────────────

    def _resolve_result(self, task: Task, mode: str, prompt_text: str | None = None) -> ConnectorResult:
        """Walk the fixture lookup chain and fall back to defaults."""
        if self.fixture_dir:
            fixture = self._load_fixture(task.id, mode)
            if fixture is not None:
                return self._fixture_to_result(fixture)

        # No fixture found — use configured defaults
        summary = f"[fake_acp] {self.default_summary}"
        task_result = TaskResult(success=self.default_success, summary=summary)

        # Mode-appropriate structured result
        if mode == "planning":
            structured_result = {
                "objective": self.default_summary,
                "steps": ["Execute planned steps"],
            }
        else:
            structured_result = {
                "summary": self.default_summary,
                "success": self.default_success,
            }
        return ConnectorResult(
            task_result=task_result,
            structured_result=structured_result,
            diagnostics=None,
        )

    def _load_fixture(self, task_id: str, mode: str) -> dict | None:
        """Try each fixture path in priority order; return first match or None."""
        if not self.fixture_dir:
            return None

        base = Path(self.fixture_dir)
        candidates = [
            f"{task_id}-{mode}.json",  # task-specific + mode
            f"{mode}.json",             # mode-only
            "default.json",             # universal
        ]
        for name in candidates:
            path = base / name
            if path.exists():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue  # malformed file — skip and try next

        return None

    @staticmethod
    def _fixture_to_result(data: dict) -> ConnectorResult:
        """Convert a fixture JSON object into a ConnectorResult."""
        task_result = TaskResult(
            success=data.get("success", True),
            summary=data.get("summary", "Fixture response."),
            output=data.get("output"),
        )
        diagnostics = data.get("diagnostics")

        # Extract structured_result
        structured_result = data.get("structured_result")

        # Extract tool_calls
        raw_tool_calls = data.get("tool_calls", [])
        tool_calls: list[ToolCallInfo] | None = None
        if raw_tool_calls:
            tool_calls = [
                ToolCallInfo(tc.get("title", ""), tc.get("arguments", {}))
                for tc in raw_tool_calls
            ]

        return ConnectorResult(
            task_result=task_result,
            structured_result=structured_result,
            tool_calls=tool_calls,
            diagnostics=diagnostics,
        )


async def _async_sleep(seconds: float) -> None:
    """Minimal async delay — avoids importing asyncio in the connector module."""
    import asyncio

    await asyncio.sleep(seconds)
