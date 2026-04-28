"""Minimal generic ACP client for one-task agent execution."""

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AcpEvent:
    method: str
    params: dict[str, Any]


@dataclass
class AcpRunResult:
    session_id: str
    stop_reason: str | None
    events: list[AcpEvent] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    text: str = ""


class AcpError(RuntimeError):
    def __init__(self, method: str, error: dict[str, Any]):
        self.method = method
        self.error = error
        super().__init__(f"ACP call failed for {method}: {error}")

    @property
    def code(self) -> Any:
        return self.error.get("code")


class AcpClient:
    def __init__(
        self,
        command: list[str],
        cwd: str | Path,
        debug_log_path: str | Path | None = None,
        skip_non_json_stdout: bool = False,
    ):
        self.command = command
        self.cwd = Path(cwd)
        self.debug_log_path = Path(debug_log_path) if debug_log_path is not None else None
        self.skip_non_json_stdout = skip_non_json_stdout
        self.process: asyncio.subprocess.Process | None = None
        self._next_id = 0

    async def start(self) -> None:
        self.process = await asyncio.create_subprocess_exec(
            *self.command,
            cwd=self.cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def initialize(self) -> dict[str, Any]:
        return await self.call(
            "initialize",
            {
                "protocolVersion": 1,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
                "clientInfo": {"name": "cellos", "version": "0.1.0"},
            },
        )

    async def new_session(self, cwd: str | Path) -> str:
        result = await self.call("session/new", {"cwd": str(cwd), "mcpServers": []})
        session_id = result.get("sessionId")
        if not isinstance(session_id, str):
            raise RuntimeError(f"ACP session/new did not return a sessionId: {result!r}")
        return session_id

    async def prompt(self, session_id: str, text: str) -> AcpRunResult:
        response, events = await self.call_with_events(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": text}],
            },
        )
        return AcpRunResult(
            session_id=session_id,
            stop_reason=response.get("stopReason"),
            events=events,
            result=response,
            text=_events_to_text(events),
        )

    async def cancel(self, session_id: str) -> None:
        await self.notify("session/cancel", {"sessionId": session_id})

    async def close_session(self, session_id: str, ignore_method_not_found: bool = False) -> None:
        try:
            await self.call("session/close", {"sessionId": session_id})
        except AcpError as exc:
            if ignore_method_not_found and exc.code == -32601:
                return
            raise

    async def stop(self, grace_seconds: float = 2.0) -> None:
        if self.process is None:
            return
        if self.process.returncode is not None:
            return
        if self.process.stdin is not None:
            self.process.stdin.close()
            try:
                await self.process.stdin.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass
        try:
            await asyncio.wait_for(self.process.wait(), timeout=grace_seconds)
            return
        except TimeoutError:
            pass
        self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=grace_seconds)
        except TimeoutError:
            self.process.kill()
            await self.process.wait()

    async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        response, _events = await self.call_with_events(method, params)
        return response

    async def call_with_events(
        self,
        method: str,
        params: dict[str, Any],
    ) -> tuple[dict[str, Any], list[AcpEvent]]:
        request_id = self._next_request_id()
        await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})

        events: list[AcpEvent] = []
        while True:
            message = await self._read()
            if "method" in message and "id" not in message:
                events.append(
                    AcpEvent(
                        method=str(message["method"]),
                        params=message.get("params") or {},
                    )
                )
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                error = message["error"]
                if not isinstance(error, dict):
                    error = {"message": str(error)}
                raise AcpError(method, error)
            result = message.get("result") or {}
            if not isinstance(result, dict):
                raise RuntimeError(f"ACP call returned non-object result for {method}: {result!r}")
            return result, events

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def _write(self, message: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("ACP process is not started")
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        await self.process.stdin.drain()

    async def _read(self) -> dict[str, Any]:
        if self.process is None or self.process.stdout is None:
            raise RuntimeError("ACP process is not started")
        while True:
            line = await self.process.stdout.readline()
            if not line:
                stderr = ""
                if self.process.stderr is not None:
                    stderr = (await self.process.stderr.read()).decode(errors="replace")
                raise RuntimeError(f"ACP process exited before response. stderr={stderr}")
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                if not self.skip_non_json_stdout:
                    raise
                await self._write_debug_line(line)

    async def _write_debug_line(self, line: bytes) -> None:
        if self.debug_log_path is None:
            return
        self.debug_log_path.parent.mkdir(parents=True, exist_ok=True)
        existing = ""
        if self.debug_log_path.exists():
            existing = self.debug_log_path.read_text()
        self.debug_log_path.write_text(existing + repr(line) + "\n")

    def _next_request_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id


async def exec_task(
    command: list[str],
    cwd: str | Path,
    prompt: str,
    timeout_seconds: int | None = None,
    debug_log_path: str | Path | None = None,
    skip_non_json_stdout: bool = False,
    close_session: bool = True,
    ignore_close_not_found: bool = False,
) -> AcpRunResult:
    client = AcpClient(
        command=command,
        cwd=cwd,
        debug_log_path=debug_log_path,
        skip_non_json_stdout=skip_non_json_stdout,
    )
    session_id: str | None = None
    await client.start()
    try:
        await client.initialize()
        session_id = await client.new_session(cwd)
        if timeout_seconds is None:
            result = await client.prompt(session_id, prompt)
        else:
            result = await asyncio.wait_for(client.prompt(session_id, prompt), timeout=timeout_seconds)
        if close_session:
            await client.close_session(session_id, ignore_method_not_found=ignore_close_not_found)
        return result
    except TimeoutError:
        if session_id is not None:
            await client.cancel(session_id)
        raise
    finally:
        await client.stop()


def _events_to_text(events: list[AcpEvent]) -> str:
    parts: list[str] = []
    for event in events:
        update = event.params.get("update")
        if not isinstance(update, dict):
            continue
        if update.get("sessionUpdate") != "agent_message_chunk":
            continue
        content = update.get("content")
        if isinstance(content, dict) and content.get("type") == "text":
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)
