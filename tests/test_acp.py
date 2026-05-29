"""Tests for connectors (fake_acp, cellos_acp) and base protocol."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cellos.connectors.base import ConnectorResult, TaskConnector
from cellos.connectors.fake_acp import FakeAcpConnector
from cellos.connectors.cellos_acp import CellosAcpConnector
from cellos.models import AgentRole, Task


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_task(**kwargs) -> Task:
    defaults = {
        "id": "test123",
        "title": "Test task",
        "details": "Do something.",
        "role": AgentRole.ENGINEER,
    }
    defaults.update(kwargs)
    return Task(**defaults)


def _result(conn_result: ConnectorResult):
    """Extract TaskResult from ConnectorResult for test assertions."""
    return conn_result.task_result


# ── Fake ACP Connector tests ─────────────────────────────────────────────────

class TestFakeAcpConnectorDefaults:
    """Test configurable default behavior without fixtures."""

    async def test_default_success(self):
        conn = FakeAcpConnector(options={"default_summary": "Default done."})
        result = await conn.run_task(_make_task())
        assert _result(result).success is True
        assert "[fake_acp]" in _result(result).summary
        assert "Default done" in _result(result).summary

    async def test_default_failure(self):
        conn = FakeAcpConnector(options={
            "default_success": False,
            "default_summary": "Something broke.",
        })
        result = await conn.run_task(_make_task())
        assert _result(result).success is False
        assert "[fake_acp]" in _result(result).summary

    async def test_no_options_uses_sensible_defaults(self):
        conn = FakeAcpConnector()
        result = await conn.run_task(_make_task())
        assert _result(result).success is True
        assert "Task completed successfully" in _result(result).summary


class TestFakeAcpConnectorFixtures:
    """Test fixture-based response loading."""

    async def test_fixture_by_task_and_mode(self, tmp_path):
        (tmp_path / "test123-planning.json").write_text(
            json.dumps({"success": True, "summary": "Task+mode match", "output": "extra"})
        )
        conn = FakeAcpConnector(options={"fixture_dir": str(tmp_path)})
        result = await conn.run_task(_make_task(), mode="planning")
        assert _result(result).success is True
        assert _result(result).summary == "Task+mode match"

    async def test_fixture_by_mode_only(self, tmp_path):
        (tmp_path / "execution.json").write_text(
            json.dumps({"success": False, "summary": "Mode-only fallback"})
        )
        conn = FakeAcpConnector(options={"fixture_dir": str(tmp_path)})
        result = await conn.run_task(_make_task(id="xyz"), mode="execution")
        assert _result(result).success is False
        assert _result(result).summary == "Mode-only fallback"

    async def test_fixture_default_fallback(self, tmp_path):
        (tmp_path / "default.json").write_text(
            json.dumps({"success": True, "summary": "Universal default"})
        )
        conn = FakeAcpConnector(options={"fixture_dir": str(tmp_path)})
        result = await conn.run_task(_make_task(id="unknown"), mode="weird")
        assert _result(result).summary == "Universal default"

    async def test_fixture_priority_task_mode_beats_default(self, tmp_path):
        (tmp_path / "test123-planning.json").write_text(
            json.dumps({"success": True, "summary": "Specific"})
        )
        (tmp_path / "default.json").write_text(
            json.dumps({"success": False, "summary": "Generic"})
        )
        conn = FakeAcpConnector(options={"fixture_dir": str(tmp_path)})
        result = await conn.run_task(_make_task(), mode="planning")
        assert _result(result).summary == "Specific"

    async def test_malformed_fixture_is_skipped(self, tmp_path):
        (tmp_path / "test123-planning.json").write_text("not valid json{{{")
        (tmp_path / "default.json").write_text(
            json.dumps({"success": True, "summary": "Recovery"})
        )
        conn = FakeAcpConnector(options={"fixture_dir": str(tmp_path)})
        result = await conn.run_task(_make_task(), mode="planning")
        assert _result(result).summary == "Recovery"

    async def test_no_fixture_uses_configured_defaults(self, tmp_path):
        (tmp_path / "other.json").write_text(json.dumps({"success": True}))
        conn = FakeAcpConnector(options={
            "fixture_dir": str(tmp_path),
            "default_summary": "Config default",
        })
        result = await conn.run_task(_make_task(id="nope"), mode="planning")
        assert "[fake_acp]" in _result(result).summary
        assert "Config default" in _result(result).summary


# ── Cellos ACP Connector tests ───────────────────────────────────────────────

class TestCellosAcpConnectorInit:
    """Test cellos_acp connector initialization."""

    def test_default_options(self):
        conn = CellosAcpConnector()
        assert conn.agent_name == "opencode"
        assert conn.timeout == 300
        assert conn.auto_approve is True
        assert conn.text_wait == 2.0
        assert conn.log_file is None
        assert conn.model is None

    def test_custom_options(self):
        conn = CellosAcpConnector(options={
            "agent": "hermes",
            "timeout_seconds": 600,
            "auto_approve": False,
            "text_wait": 2.5,
            "log_file": "/tmp/cellos-acp-test.log",
            "model": "test-model",
        })
        assert conn.agent_name == "hermes"
        assert conn.timeout == 600
        assert conn.auto_approve is False
        assert conn.text_wait == 2.5
        assert conn.log_file == "/tmp/cellos-acp-test.log"
        assert conn.model == "test-model"


class TestCellosAcpConnectorRunTask:
    """Test cellos_acp connector task execution."""

    async def test_successful_execution(self):
        conn = CellosAcpConnector(options={"agent": "opencode"})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.combined_text = "Task completed successfully."
        mock_result.stop_reason = "end_turn"

        with patch("cellos_acp.AcpClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=mock_result)
            MockClient.return_value = mock_instance
            result = await conn.run_task(_make_task(), workdir="/tmp", mode="execution", prompt_text="test prompt")

        assert _result(result).success is True
        assert "Task completed" in _result(result).summary
        assert _result(result).output == "Task completed successfully."

    async def test_exception_handling(self):
        conn = CellosAcpConnector()
        with patch("cellos_acp.AcpClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(side_effect=RuntimeError("connection refused"))
            MockClient.return_value = mock_instance
            result = await conn.run_task(_make_task(), prompt_text="prompt")

        assert _result(result).success is False
        assert "connection refused" in _result(result).summary

    async def test_model_override_passes_env(self):
        conn = CellosAcpConnector(options={"agent": "opencode", "model": "claude-sonnet-4-20250514"})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.combined_text = "done"
        mock_result.stop_reason = "end_turn"

        with patch("cellos_acp.AcpClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=mock_result)
            MockClient.return_value = mock_instance
            await conn.run_task(_make_task(), prompt_text="test")

        call_kwargs = MockClient.call_args.kwargs
        assert call_kwargs["env"] is not None
        assert json.loads(call_kwargs["env"]["OPENCODE_CONFIG_CONTENT"])["model"] == "claude-sonnet-4-20250514"

    async def test_no_model_no_env(self):
        conn = CellosAcpConnector(options={"agent": "opencode"})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.combined_text = "done"
        mock_result.stop_reason = "end_turn"

        with patch("cellos_acp.AcpClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=mock_result)
            MockClient.return_value = mock_instance
            await conn.run_task(_make_task(), prompt_text="test")

        call_kwargs = MockClient.call_args.kwargs
        assert call_kwargs["env"] is None

    async def test_log_file_configures_cellos_acp_logging(self):
        conn = CellosAcpConnector(options={"log_file": "~/cellos-acp-test.log"})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.combined_text = "done"
        mock_result.text = "done"
        mock_result.thinking = ""
        mock_result.stop_reason = "end_turn"

        with patch("cellos_acp.AcpClient") as MockClient, patch("cellos_acp.configure_logging") as configure_logging:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=mock_result)
            MockClient.return_value = mock_instance
            await conn.run_task(_make_task(), prompt_text="test")

        configure_logging.assert_called_once()
        assert configure_logging.call_args.args[0].endswith("/cellos-acp-test.log")

    async def test_empty_output_returns_default_message(self):
        conn = CellosAcpConnector()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.combined_text = ""
        mock_result.stop_reason = "end_turn"

        with patch("cellos_acp.AcpClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=mock_result)
            MockClient.return_value = mock_instance
            result = await conn.run_task(_make_task(), prompt_text="test")

        assert _result(result).success is True
        assert "No output from agent" in _result(result).summary


# ── Diagnostics tests ────────────────────────────────────────────────────────

class TestConnectorResultDiagnostics:
    """Test that connectors return diagnostic data."""

    async def test_cellos_acp_returns_diagnostics(self):
        conn = CellosAcpConnector(options={"agent": "opencode", "model": "test-model"})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.combined_text = "done"
        mock_result.stop_reason = "end_turn"
        mock_result.session_id = "ses_abc123"
        mock_result.message_id = "msg_xyz789"
        mock_result.last_event_type = "AgentMessageChunk"
        mock_result.last_event_at = "2026-05-28T18:30:00Z"

        with patch("cellos_acp.AcpClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=mock_result)
            MockClient.return_value = mock_instance
            result = await conn.run_task(_make_task(), prompt_text="test")

        assert result.diagnostics is not None
        assert result.diagnostics["session_id"] == "ses_abc123"
        assert result.diagnostics["message_id"] == "msg_xyz789"
        assert result.diagnostics["agent_provider"] == "opencode"
        assert result.diagnostics["agent_model"] == "test-model"
        assert result.diagnostics["last_event_type"] == "AgentMessageChunk"

    async def test_cellos_acp_diagnostics_on_timeout(self):
        conn = CellosAcpConnector(options={"agent": "opencode"})
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.combined_text = "partial output"
        mock_result.stop_reason = ""
        mock_result.timeout = True
        mock_result.error_type = "TimeoutError"
        mock_result.error_message = "ACP timeout after 300s"
        mock_result.last_event_type = "ToolCallProgress"
        mock_result.active_tool_calls = [MagicMock(title="task", tool_call_id="tc_1")]

        with patch("cellos_acp.AcpClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=mock_result)
            MockClient.return_value = mock_instance
            result = await conn.run_task(_make_task(), prompt_text="test")

        assert result.diagnostics is not None
        assert result.diagnostics["timeout"] is True
        assert result.diagnostics["error_type"] == "TimeoutError"
        assert result.diagnostics["active_tool_name"] == "task"

    async def test_fake_acp_fixture_diagnostics(self, tmp_path):
        (tmp_path / "default.json").write_text(
            json.dumps({
                "success": True,
                "summary": "Done",
                "diagnostics": {"session_id": "ses_fake", "stop_reason": "end_turn"},
            })
        )
        conn = FakeAcpConnector(options={"fixture_dir": str(tmp_path)})
        result = await conn.run_task(_make_task(), mode="execution")

        assert result.diagnostics is not None
        assert result.diagnostics["session_id"] == "ses_fake"

    async def test_fake_acp_no_diagnostics_by_default(self):
        conn = FakeAcpConnector()
        result = await conn.run_task(_make_task())

        assert result.diagnostics is None


# ── Protocol conformance test ────────────────────────────────────────────────

class TestTaskConnectorProtocol:
    """Verify connectors implement the TaskConnector protocol."""

    def test_fake_acp_implements_protocol(self):
        conn = FakeAcpConnector()
        assert hasattr(conn, "run_task")
        import inspect
        sig = inspect.signature(conn.run_task)
        params = list(sig.parameters.keys())
        assert "task" in params

    def test_cellos_acp_implements_protocol(self):
        conn = CellosAcpConnector()
        assert hasattr(conn, "run_task")
        import inspect
        sig = inspect.signature(conn.run_task)
        params = list(sig.parameters.keys())
        assert "task" in params