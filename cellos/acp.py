"""ACP (Agent Communication Protocol) JSON-RPC 2.0 client.

Provides a reusable, subprocess-based ACP client that handles the full protocol
flow: initialize → session/new → session/prompt → stream events → session/close.

Used by connectors and CLI commands for agent interaction.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ── Exceptions ────────────────────────────────────────────────────────────────


class AcpError(Exception):
    """Base exception for ACP protocol errors."""


class AcpTimeoutError(AcpError):
    """Raised when an ACP call exceeds its timeout budget."""


# ── Result types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AcpRunResult:
    """Outcome of a single ACP task execution.

    Attributes:
        session_id: Session ID returned by the agent (may be None).
        text: Full concatenated response text from all message chunks.
        thinking: Full concatenated thinking/reasoning text from thought chunks.
            May contain the agent's internal reasoning. Empty if no thought events.
        stop_reason: Final stop reason reported by the agent, if any.
    """

    session_id: str | None = None
    text: str = ""
    thinking: str = ""
    stop_reason: str | None = None


# ── Public API ────────────────────────────────────────────────────────────────


async def exec_task(
    command: list[str],
    prompt: str,
    timeout_seconds: int = 300,
    spawn_timeout: float = 5.0,
    cwd: str | None = None,
) -> AcpRunResult:
    """Execute a task via an ACP-compatible subprocess.

    Full protocol flow:
        1. ``initialize`` — handshake with protocol version
        2. ``session/new`` — create a new session
        3. ``session/prompt`` — send the prompt text
        4. Collect agent events until done
        5. ``session/close`` (best-effort)

    Args:
        command: Subprocess command, e.g. ``["opencode", "acp"]``.
        prompt: Prompt text to send to the agent.
        timeout_seconds: Total time budget for the entire call cycle.
        spawn_timeout: Max seconds to wait for subprocess startup.
        cwd: Working directory for the subprocess.

    Returns:
        AcpRunResult with session_id, concatenated response text, and stop reason.

    Raises:
        AcpError: If subprocess fails to start or protocol errors occur.
        AcpTimeoutError: If total timeout is exceeded.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds

    proc = await _spawn(command, spawn_timeout)
    logger.info("ACP client started (pid=%s)", proc.pid)

    try:
        # 1. Initialize handshake
        await _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": 1}})
        await _recv(proc, deadline)

        # 2. Create session
        await _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": cwd or ".", "mcpServers": []}})
        init_resp = await _recv(proc, deadline)
        session_id = _extract_session_id(init_resp)

        # 3. Send prompt
        await _send(proc, {"jsonrpc": "2.0", "id": 3, "method": "session/prompt", "params": {
            "prompt": [{"type": "text", "text": prompt}],
            "sessionId": session_id,
        }})

        # 4. Collect events until done or timeout
        chunks: list[str] = []
        thought_chunks: list[str] = []
        stop_reason: str | None = None
        max_events = 10_000  # safety guard against infinite loops from misbehaving agents

        for _ in range(max_events):
            try:
                msg = await _recv(proc, deadline)
                parsed = _parse_event(msg, chunks, thought_chunks)
                if parsed.stop_reason and parsed.stop_reason != "running":
                    stop_reason = parsed.stop_reason
                    break
            except asyncio.TimeoutError:
                logger.warning("ACP timeout — returning partial output (%d chars)", sum(len(c) for c in chunks))
                break

        # 5. Close session (best-effort, don't block)
        await _send(proc, {"jsonrpc": "2.0", "id": 4, "method": "session/close", "params": {"sessionId": session_id}})

        return AcpRunResult(
            session_id=session_id,
            text="".join(chunks),
            thinking="".join(thought_chunks),
            stop_reason=stop_reason,
        )

    finally:
        await _cleanup(proc)


# ── Internal helpers ──────────────────────────────────────────────────────────


async def _spawn(command: list[str], spawn_timeout: float) -> asyncio.subprocess.Process:
    """Spawn an ACP subprocess with timeout."""
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=spawn_timeout,
        )
    except FileNotFoundError as e:
        raise AcpError(f"ACP binary not found: {command[0]}") from e
    except asyncio.TimeoutError:
        raise AcpTimeoutError(
            f"ACP subprocess failed to start within {spawn_timeout}s: {' '.join(command)}"
        )

    return proc


async def _send(proc: asyncio.subprocess.Process, obj: dict) -> None:
    """Send a JSON-RPC message."""
    if not proc.stdin or proc.returncode is not None:
        return
    try:
        proc.stdin.write((json.dumps(obj) + "\n").encode())
        await asyncio.sleep(0.01)  # flush window
    except (BrokenPipeError, OSError):
        pass


async def _recv(proc: asyncio.subprocess.Process, deadline: float) -> Any:
    """Read one JSON line from stdout with a deadline, skipping debug output.

    Raises:
        AcpTimeoutError: If the deadline is exceeded or the agent closes without response.
        AcpError: If the subprocess has no stdout pipe.
    """
    if not proc.stdout:
        raise AcpError("Subprocess has no stdout")

    while True:
        remaining = max(deadline - asyncio.get_running_loop().time(), 0.1)
        try:
            raw = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
        except asyncio.TimeoutError:
            raise AcpTimeoutError(
                "Agent did not respond within deadline"
            ) from None

        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            raise AcpTimeoutError("Agent subprocess closed without response")

        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue  # skip non-JSON debug output


def _extract_session_id(resp: Any) -> str | None:
    """Extract session ID from a JSON-RPC response."""
    if not isinstance(resp, dict):
        return None
    result = resp.get("result") or {}
    if not isinstance(result, dict):
        return None
    return result.get("id") or result.get("session_id") or result.get("sessionId")


@dataclass(frozen=True)
class _EventParseResult:
    stop_reason: str | None = None


def _parse_event(msg: Any, chunks: list[str], thought_chunks: list[str] | None = None) -> _EventParseResult:
    """Extract text content and check for done signal from an agent event.

    Supports multiple protocol conventions:
      - ``agent_message_chunk`` — standard message events (text collected)
      - ``agent_thought_chunk`` — thinking blocks; collected into thought_chunks
        as a fallback when no message chunks are found (Opencode routes all
        content through thought events)
      - JSON-RPC responses with ``stopReason`` in result or params

    Raises:
        AcpError: If a JSON-RPC error response is received from the agent.
    """
    if not isinstance(msg, dict):
        return _EventParseResult()

    # Check for JSON-RPC error responses — these are protocol-level errors
    if "error" in msg and isinstance(msg.get("error"), dict):
        logger.error("JSON-RPC error from agent: %s", msg["error"])
        raise AcpError(f"Agent returned JSON-RPC error: {msg['error']}")

    params = msg.get("params") or {}

    # Resolve event type: check params.sessionUpdate first (Opencode format),
    # then fall back to msg.type (Anthropic/flat format).
    update = params.get("update") or {}
    event_type = (
        params.get("sessionUpdate")
        or (update.get("sessionUpdate") if isinstance(update, dict) else None)
        or msg.get("type", "")
    ) or ""

    # Extract text from content — supports plain string or {"type":"text","text":"..."} dict
    content = params.get("content") or update.get("content") if isinstance(update, dict) else None
    text: str | None = None
    if isinstance(content, str):
        text = content
    elif isinstance(content, dict):
        text = content.get("text") or content.get("content")
    elif isinstance(params, dict):
        # Fallback: check params-level text or streaming delta
        text = (
            params.get("text")
            or params.get("delta", {}).get("content")  # streaming format
        )

    if text:
        text_str = str(text)
        if "message" in event_type.lower():
            chunks.append(text_str)
        elif "thought" in event_type.lower() and thought_chunks is not None:
            thought_chunks.append(text_str)

    # Check for stop signal — can come from result field of session_update events
    update = msg.get("result") or {}
    if isinstance(update, dict):
        sr = update.get("stopReason") or update.get("stop_reason")
        if sr:
            return _EventParseResult(stop_reason=sr)

    # Also check params for stop signals (some agents put it there)
    if isinstance(params, dict):
        sr = params.get("stopReason") or params.get("stop_reason")
        if sr and sr != "running":
            return _EventParseResult(stop_reason=sr)

    return _EventParseResult()


async def _cleanup(proc: asyncio.subprocess.Process) -> None:
    """Terminate the subprocess gracefully."""
    if proc.returncode is not None:
        return  # already exited
    try:
        proc.terminate()
        await asyncio.wait_for(proc.wait(), timeout=3.0)
    except Exception:
        pass
