# ACP Implementation Guide for CelloS

## What is ACP?

**Agent Client Protocol (ACP)** is an open JSON-RPC 2.0 protocol that standardizes communication between coding agents and clients/orchestrators. Think of it like LSP (Language Server Protocol) but for AI agents.

**Spec:** https://agentclientprotocol.com

**Key insight:** Instead of CelloS invoking agent CLIs directly with raw subprocess calls, ACP provides a standardized interface. One client implementation works with all ACP-compatible agents.

---

## How ACP Works

### Transport
- **Local agents:** JSON-RPC over stdio (stdin/stdout) — agent runs as subprocess
- **Remote agents:** HTTP or WebSocket (future)

### Message Format
All messages are newline-delimited JSON (NDJSON):
```
{"jsonrpc": "2.0", "id": 1, "method": "session/new", "params": {...}}
{"jsonrpc": "2.0", "method": "session/update", "params": {...}}  // notification
{"jsonrpc": "2.0", "id": 1, "result": {...}}                     // response
```

### Connection Flow

```
CelloS                          Worker Agent
   │                                  │
   │──── initialize ─────────────────►│
   │◄──── initialize + capabilities ─│
   │                                  │
   │──── session/new ─────────────────►│
   │◄──── sessionId ──────────────────│
   │                                  │
   │──── session/prompt ─────────────►│
   │◄──── session/update (streaming) ─│  // notifications
   │◄──── session/update (tool_call) ──│
   │◄──── session/prompt response ────│  // final result
   │                                  │
   │──── session/close ──────────────►│
   │                                  │
```

---

## Core Methods

### 1. Initialize (once at connection start)

**CelloS → Agent:**
```json
{
  "jsonrpc": "2.0",
  "id": 0,
  "method": "initialize",
  "params": {
    "protocolVersion": 1,
    "clientCapabilities": {
      "fs": {"readTextFile": false, "writeTextFile": false},
      "terminal": false
    },
    "clientInfo": {"name": "cellos", "version": "0.1.0"}
  }
}
```

**Agent → CelloS:**
```json
{
  "jsonrpc": "2.0",
  "id": 0,
  "result": {
    "protocolVersion": 1,
    "agentCapabilities": {
      "loadSession": true,
      "promptCapabilities": {"image": true, "audio": false, "embeddedContext": true},
      "mcpCapabilities": {"http": true, "sse": false},
      "sessionCapabilities": {"list": true, "resume": true, "close": true}
    },
    "agentInfo": {"name": "hermes", "version": "1.0.0"},
    "authMethods": []
  }
}
```

### 2. Session/New (create a task session)

**CelloS → Agent:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "session/new",
  "params": {
    "cwd": "/path/to/project",
    "mcpServers": []
  }
}
```

**Agent → CelloS:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "sessionId": "sess_abc123"
  }
}
```

### 3. Session/Prompt (send task to agent)

**CelloS → Agent:**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "session/prompt",
  "params": {
    "sessionId": "sess_abc123",
    "prompt": [
      {
        "type": "text",
        "text": "Implement a user authentication module with JWT tokens. Requirements: ... [detailed specs]"
      }
    ]
  }
}
```

### 4. Session/Update (agent streams updates to CelloS)

**Agent → CelloS (notifications):**
```json
{"jsonrpc": "2.0", "method": "session/update", "params": {
  "sessionId": "sess_abc123",
  "update": {
    "sessionUpdate": "agent_message_chunk",
    "content": {"type": "text", "text": "I'll implement the auth module..."}
  }
}}

{"jsonrpc": "2.0", "method": "session/update", "params": {
  "sessionId": "sess_abc123",
  "update": {
    "sessionUpdate": "tool_call",
    "content": {
      "type": "tool_call",
      "toolCallId": "call_1",
      "name": "write_file",
      "input": {"path": "/path/to/auth.py", "content": "..."}
    }
  }
}}

{"jsonrpc": "2.0", "method": "session/update", "params": {
  "sessionId": "sess_abc123",
  "update": {
    "sessionUpdate": "message",
    "content": {
      "type": "text",
      "text": "I've created the authentication module."
    }
  }
}}
```

**Agent → CelloS (final response):**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "stopReason": "user_requested_stop",
    "usage": {"inputTokens": 1500, "outputTokens": 800}
  }
}
```

### 5. Session/Cancel (interrupt agent)

**CelloS → Agent:**
```json
{
  "jsonrpc": "2.0",
  "method": "session/cancel",
  "params": {
    "sessionId": "sess_abc123"
  }
}
```

### 6. Session/Close (cleanup)

**CelloS → Agent:**
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "session/close",
  "params": {
    "sessionId": "sess_abc123"
  }
}
```

### 7. Session/Request_Permission (agent asks for approval)

**Agent → CelloS:**
```json
{
  "jsonrpc": "2.0",
  "method": "session/update",
  "params": {
    "sessionId": "sess_abc123",
    "update": {
      "sessionUpdate": "request_permission",
      "content": {
        "message": "Allow running `rm -rf /`?",
        "options": [
          {"label": "Allow once", "action": "allow_once"},
          {"label": "Allow always", "action": "allow_always"},
          {"label": "Deny", "action": "deny"}
        ]
      }
    }
  }
}
```

**CelloS → Agent:**
```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "session/request_permission",
  "params": {
    "sessionId": "sess_abc123",
    "requestId": "req_xyz",
    "action": "allow_once"
  }
}
```

### 8. Session/Set_Model (optional, per-session model selection)

**CelloS → Agent:**
```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "method": "session/set_model",
  "params": {
    "sessionId": "sess_abc123",
    "model": "claude-sonnet-4-20250514"
  }
}
```

---

## Stop Reasons

When `session/prompt` completes, the `stopReason` indicates why:

| Reason | Meaning |
|--------|---------|
| `end_turn` | Agent completed normally |
| `tool_calls` | Stopped at tool call (awaiting permission or result) |
| `user_requested_stop` | Client cancelled via `session/cancel` |
| `max_tokens` | Token limit reached |
| `context_expired` | Context window exceeded |

---

## Capabilities to Check During Initialize

**Agent Capabilities (advertised by worker):**
- `loadSession` — can load previous sessions
- `sessionCapabilities.list` — can list sessions
- `sessionCapabilities.resume` — can resume without replay
- `sessionCapabilities.close` — can close sessions
- `promptCapabilities.image` — accepts image content
- `promptCapabilities.embeddedContext` — accepts file references
- `mcpCapabilities.http` — supports HTTP MCP transport

---

## Spawning Workers

### Hermes
```bash
hermes -p <profile-name> acp
# Example: hermes -p python-engineer acp
```

### OpenClaw
```bash
openclaw acp --agent <agentId>
```

### OpenCode
```bash
opencode acp
```

### General Pattern
```python
import asyncio
import json
from subprocess import Popen, PIPE

async def spawn_worker(cmd: list[str]) -> tuple:
    """Spawn worker and return reader, writer, process handles."""
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=PIPE,
        stdout=PIPE,
        stderr=PIPE,
        env=dict(os.environ)  # inherit env for API keys
    )
    return process.stdin, process.stdout, process
```

---

## CelloS ACP Client Architecture

### Minimal Implementation

```python
# cellos/acp/client.py
import asyncio
import json
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable
from enum import Enum

class SessionUpdateType(Enum):
    AGENT_MESSAGE_CHUNK = "agent_message_chunk"
    USER_MESSAGE_CHUNK = "user_message_chunk"
    TOOL_CALL = "tool_call"
    TOOL_CALL_UPDATE = "tool_call_update"
    MESSAGE = "message"
    REQUEST_PERMISSION = "request_permission"
    AVAILABLE_COMMANDS_UPDATE = "available_commands_update"

@dataclass
class ACPSession:
    session_id: str
    cwd: str

@dataclass
class ACPClient:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    process: asyncio.subprocess.Process
    _request_id: int = 0
    _pending: dict[int, asyncio.Future] = field(default_factory=dict)
    _session_id: str | None = None

    async def initialize(self) -> dict:
        """Send initialize, receive agent capabilities."""
        return await self._call("initialize", {
            "protocolVersion": 1,
            "clientCapabilities": {"fs": {}, "terminal": {}},
            "clientInfo": {"name": "cellos", "version": "0.1.0"}
        })

    async def new_session(self, cwd: str) -> ACPSession:
        """Create a new session."""
        result = await self._call("session/new", {"cwd": cwd, "mcpServers": []})
        self._session_id = result["sessionId"]
        return ACPSession(session_id=self._session_id, cwd=cwd)

    async def prompt(self, session_id: str, message: str) -> dict:
        """Send a prompt and get final response."""
        return await self._call("session/prompt", {
            "sessionId": session_id,
            "prompt": [{"type": "text", "text": message}]
        })

    async def cancel(self, session_id: str) -> None:
        """Cancel ongoing operation."""
        await self._notify("session/cancel", {"sessionId": session_id})

    async def close(self, session_id: str) -> None:
        """Close session."""
        await self._call("session/close", {"sessionId": session_id})

    async def stream_updates(self, session_id: str) -> AsyncIterator[dict]:
        """Yield session_update notifications as they arrive."""
        # Read from stdout, yield parsed updates
        ...

    async def _call(self, method: str, params: dict) -> dict:
        """Send request and wait for response."""
        self._request_id += 1
        id = self._request_id
        msg = json.dumps({"jsonrpc": "2.0", "id": id, "method": method, "params": params})
        self.writer.write((msg + "\n").encode())
        await self.writer.drain()
        # Wait for response with matching id
        ...

    async def _notify(self, method: str, params: dict) -> None:
        """Send notification (no response expected)."""
        msg = json.dumps({"jsonrpc": "2.0", "method": method, "params": params})
        self.writer.write((msg + "\n").encode())
        await self.writer.drain()
```

### Worker Spawner

```python
# cellos/acp/spawner.py
from dataclasses import dataclass
from typing import Protocol

class WorkerAdapter(Protocol):
    """Interface each agent adapter must implement."""
    async def spawn(self, profile: str, cwd: str) -> ACPClient: ...

@dataclass
class HermesAdapter:
    hermes_bin: str = "hermes"

    async def spawn(self, profile: str, cwd: str) -> ACPClient:
        import asyncio
        process = await asyncio.create_subprocess_exec(
            self.hermes_bin, "-p", profile, "acp",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        client = ACPClient(process.stdin, process.stdout, process)
        await client.initialize()
        await client.new_session(cwd)
        return client

@dataclass
class OpenClawAdapter:
    openclaw_bin: str = "openclaw"

    async def spawn(self, agent_id: str, cwd: str) -> ACPClient:
        ...

@dataclass
class OpenCodeAdapter:
    opencode_bin: str = "opencode"

    async def spawn(self, cwd: str) -> ACPClient:
        ...
```

### Agent Registry

```python
# cellos/acp/registry.py
from dataclasses import dataclass

@dataclass
class AgentProfile:
    agent_type: str  # "hermes", "openclaw", "opencode"
    profile: str | None  # profile name for hermes/openclaw
    model: str | None  # optional model override

AGENT_REGISTRY: dict[str, AgentProfile] = {
    "architect-backend": AgentProfile("hermes", "architect", None),
    "engineer-python": AgentProfile("hermes", "python-engineer", None),
    "engineer-web": AgentProfile("hermes", "web-engineer", None),
    "tester": AgentProfile("openclaw", "tester", None),
}
```

---

## Hermes-Specific Notes

Hermes ACP mode exposes a curated `hermes-acp` toolset including:
- File tools: `read_file`, `write_file`, `patch`, `search_files`
- Terminal tools: `terminal`, `process`
- Web/browser tools
- Memory, todo, session search
- Skills
- `execute_code` and `delegate_task`
- Vision

Install ACP support:
```bash
pip install hermes-agent[acp]
# or
pip install '.[acp]'
```

Command entry points:
```bash
hermes acp
hermes-acp
python -m acp_adapter
```

Hermes reuses its normal provider resolution for ACP — credentials come from existing Hermes config.

---

## ContentBlock Types (for prompts)

| Type | Description |
|------|-------------|
| `text` | Plain text content |
| `image` | Image (requires `promptCapabilities.image`) |
| `audio` | Audio (requires `promptCapabilities.audio`) |
| `resource` | Embedded resource content |
| `resourceLink` | Reference to external resource |

---

## Error Codes

Standard JSON-RPC 2.0 errors:
- `-32600` Invalid Request
- `-32601` Method not found
- `-32602` Invalid params
- `-32603` Internal error

ACP-specific errors may include:
- `auth_required` — Session requires authentication
- `session_not_found` — Session ID doesn't exist

---

## References

- **Spec:** https://agentclientprotocol.com
- **Hermes ACP:** https://hermes-agent.nousresearch.com/docs/user-guide/features/acp
- **Hermes ACP Internals:** https://hermes-agent.nousresearch.com/docs/developer-guide/acp-internals
- **OpenCode ACP:** https://opencode.ai/docs/acp/
- **Schema:** https://agentclientprotocol.com/protocol/draft/schema