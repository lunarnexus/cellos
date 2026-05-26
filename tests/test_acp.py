"""Tests for ACP client, connectors (fake_acp, acpx), and base protocol."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cellos.acp import AcpError, AcpRunResult, exec_task
from cellos.connectors.base import TaskConnector
from cellos.connectors.fake_acp import FakeAcpConnector
from cellos.connectors.acpx import AcpxConnector
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


def _make_fake_proc(responses: list[str]) -> MagicMock:
    """Create a mocked subprocess that emits the given JSON lines on readline()."""
    proc = MagicMock()
    # Use plain MagicMock for stdin — we only call .write() and .at_eof(), both sync
    stdin_mock = MagicMock()
    stdin_mock.at_eof.return_value = False
    proc.stdin = stdin_mock

    async def fake_readline():
        if responses:
            return (responses.pop(0) + "\n").encode()
        raise asyncio.TimeoutError()

    # stdout.readline is the only async method we call on it
    stdout_mock = AsyncMock()
    stdout_mock.readline.side_effect = fake_readline
    proc.stdout = stdout_mock
    proc.returncode = None
    return proc


# ── Fake ACP Connector tests ─────────────────────────────────────────────────

class TestFakeAcpConnectorDefaults:
    """Test configurable default behavior without fixtures."""

    async def test_default_success(self):
        conn = FakeAcpConnector(options={"default_summary": "Default done."})
        result = await conn.run_task(_make_task())
        assert result.success is True
        assert "[fake_acp]" in result.summary
        assert "Default done" in result.summary

    async def test_default_failure(self):
        conn = FakeAcpConnector(options={
            "default_success": False,
            "default_summary": "Something broke.",
        })
        result = await conn.run_task(_make_task())
        assert result.success is False
        assert "[fake_acp]" in result.summary

    async def test_no_options_uses_sensible_defaults(self):
        conn = FakeAcpConnector()
        result = await conn.run_task(_make_task())
        assert result.success is True
        assert "Task completed successfully" in result.summary


class TestFakeAcpConnectorFixtures:
    """Test fixture-based response loading."""

    async def test_fixture_by_task_and_mode(self, tmp_path):
        (tmp_path / "test123-planning.json").write_text(
            json.dumps({"success": True, "summary": "Task+mode match", "output": "extra"})
        )
        conn = FakeAcpConnector(options={"fixture_dir": str(tmp_path)})
        result = await conn.run_task(_make_task(), mode="planning")
        assert result.success is True
        assert result.summary == "Task+mode match"

    async def test_fixture_by_mode_only(self, tmp_path):
        (tmp_path / "execution.json").write_text(
            json.dumps({"success": False, "summary": "Mode-only fallback"})
        )
        conn = FakeAcpConnector(options={"fixture_dir": str(tmp_path)})
        result = await conn.run_task(_make_task(id="xyz"), mode="execution")
        assert result.success is False
        assert result.summary == "Mode-only fallback"

    async def test_fixture_default_fallback(self, tmp_path):
        (tmp_path / "default.json").write_text(
            json.dumps({"success": True, "summary": "Universal default"})
        )
        conn = FakeAcpConnector(options={"fixture_dir": str(tmp_path)})
        result = await conn.run_task(_make_task(id="unknown"), mode="weird")
        assert result.summary == "Universal default"

    async def test_fixture_priority_task_mode_beats_default(self, tmp_path):
        (tmp_path / "test123-planning.json").write_text(
            json.dumps({"success": True, "summary": "Specific"})
        )
        (tmp_path / "default.json").write_text(
            json.dumps({"success": False, "summary": "Generic"})
        )
        conn = FakeAcpConnector(options={"fixture_dir": str(tmp_path)})
        result = await conn.run_task(_make_task(), mode="planning")
        assert result.summary == "Specific"

    async def test_malformed_fixture_is_skipped(self, tmp_path):
        (tmp_path / "test123-planning.json").write_text("not valid json{{{")
        (tmp_path / "default.json").write_text(
            json.dumps({"success": True, "summary": "Recovery"})
        )
        conn = FakeAcpConnector(options={"fixture_dir": str(tmp_path)})
        result = await conn.run_task(_make_task(), mode="planning")
        assert result.summary == "Recovery"

    async def test_no_fixture_uses_configured_defaults(self, tmp_path):
        (tmp_path / "other.json").write_text(json.dumps({"success": True}))
        conn = FakeAcpConnector(options={
            "fixture_dir": str(tmp_path),
            "default_summary": "Config default",
        })
        result = await conn.run_task(_make_task(id="nope"), mode="planning")
        assert "[fake_acp]" in result.summary
        assert "Config default" in result.summary


# ── Acpx Connector tests ─────────────────────────────────────────────────────

class TestAcpxConnectorInit:
    """Test acpx connector initialization."""

    def test_default_options(self):
        conn = AcpxConnector()
        assert conn.timeout == 1200
        assert conn.approve_mode == "approve-all"
        assert conn.model is None

    def test_custom_options(self):
        conn = AcpxConnector(options={
            "timeout_seconds": 300,
            "approve_mode": "approve-reads",
            "model": "test-model",
        })
        assert conn.timeout == 300
        assert conn.approve_mode == "approve-reads"
        assert conn.model == "test-model"


class TestAcpxConnectorExtractOutput:
    """Test output extraction from acpx NDJSON stream."""

    def test_extract_message_chunks(self):
        conn = AcpxConnector()
        raw = json.dumps({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "Hello world"}
                }
            }
        })
        result = conn._extract_output(raw)
        assert result == "Hello world"

    def test_extract_thought_chunks_fallback(self):
        conn = AcpxConnector()
        raw = json.dumps({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "agent_thought_chunk",
                    "content": {"type": "text", "text": "Thinking..."}
                }
            }
        })
        result = conn._extract_output(raw)
        assert result == "Thinking..."

    def test_prefer_message_over_thought(self):
        conn = AcpxConnector()
        raw = (
            json.dumps({
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "agent_thought_chunk",
                        "content": {"type": "text", "text": "Thinking..."}
                    }
                }
            }) + "\n" +
            json.dumps({
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "Final answer"}
                    }
                }
            })
        )
        result = conn._extract_output(raw)
        assert result == "Final answer"
        assert "Thinking" not in result

    def test_multiple_chunks_concatenated(self):
        conn = AcpxConnector()
        raw = (
            json.dumps({
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "Part A"}
                    }
                }
            }) + "\n" +
            json.dumps({
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": " Part B"}
                    }
                }
            })
        )
        result = conn._extract_output(raw)
        assert result == "Part A Part B"

    def test_empty_input_returns_empty(self):
        conn = AcpxConnector()
        assert conn._extract_output("") == ""

    def test_invalid_json_ignored(self):
        conn = AcpxConnector()
        raw = "not valid json\n" + json.dumps({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "Valid"}
                }
            }
        })
        result = conn._extract_output(raw)
        assert result == "Valid"


# ── ACP Client tests ─────────────────────────────────────────────────────────

class TestAcpClient:
    """Test the standalone ACP client with mocked subprocess."""

    async def test_full_protocol_flow(self):
        fake_proc = _make_fake_proc([
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"id": "sess-42"}}),
            json.dumps({
                "type": "agent_message_chunk",
                "params": {"text": "Hello from agent"},
            }),
            json.dumps({"jsonrpc": "2.0", "result": {"stopReason": "end_turn"}}),
        ])

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_spawn:
            mock_spawn.return_value = fake_proc
            result = await exec_task(["fake_acp"], "test prompt", timeout_seconds=10, spawn_timeout=2.0)

        assert isinstance(result, AcpRunResult)
        assert result.session_id == "sess-42"
        assert result.text == "Hello from agent"
        assert result.stop_reason == "end_turn"

    async def test_multiple_chunks_concatenated(self):
        fake_proc = _make_fake_proc([
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"session_id": "s"}}),
            json.dumps({"type": "agent_message_chunk", "params": {"text": "Part A"}}),
            json.dumps({"type": "agent_message_chunk", "params": {"content": " Part B"}}),
            json.dumps({"jsonrpc": "2.0", "result": {"stopReason": "end_turn"}}),
        ])

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_spawn:
            mock_spawn.return_value = fake_proc
            result = await exec_task(["fake"], "prompt")

        assert result.text == "Part A Part B"

    async def test_binary_not_found_raises_acp_error(self):
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError()):
            with pytest.raises(AcpError, match="not found"):
                await exec_task(["nonexistent"], "prompt")

    async def test_no_response_text_returns_empty(self):
        fake_proc = _make_fake_proc([
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"id": "s"}}),
            # No message chunks — just a stop signal
            json.dumps({"jsonrpc": "2.0", "result": {"stopReason": "end_turn"}}),
        ])

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_spawn:
            mock_spawn.return_value = fake_proc
            result = await exec_task(["fake"], "prompt")

        assert result.text == ""
        assert result.thinking == ""


class TestAcpClientProtocolCompatibility:
    """Test handling of different agent protocol variations."""

    async def test_thinking_block_events_ignored(self):
        """Opencode routes all content through agent_thought_chunk — only message chunks collected."""
        fake_proc = _make_fake_proc([
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"id": "s"}}),
            # Thinking block — should NOT be collected as text (no 'message' in type)
            json.dumps({"type": "agent_thought_chunk", "params": {"text": "thinking..."}}),
            # Actual message — should be collected
            json.dumps({"type": "agent_message_chunk", "params": {"text": "real response"}}),
            json.dumps({"jsonrpc": "2.0", "result": {"stopReason": "end_turn"}}),
        ])

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_spawn:
            mock_spawn.return_value = fake_proc
            result = await exec_task(["fake"], "prompt")

        assert "real response" in result.text
        assert "thinking..." not in result.text

    async def test_stop_reason_in_params(self):
        """Some agents put stopReason in params instead of result."""
        fake_proc = _make_fake_proc([
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"id": "s"}}),
            json.dumps({"type": "agent_message_chunk", "params": {"text": "done"}}),
            # stopReason in params (non-standard but supported)
            json.dumps({"type": "session_update", "params": {"stopReason": "max_tokens"}}),
        ])

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_spawn:
            mock_spawn.return_value = fake_proc
            result = await exec_task(["fake"], "prompt")

        assert result.stop_reason == "max_tokens"


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

    def test_acpx_class_has_run_task(self):
        assert hasattr(AcpxConnector, "run_task")
