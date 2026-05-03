"""Fake ACP-compatible connector for local development and smoke tests."""

import json
import sys
from typing import Any

from cellos.connectors.base import AgentInvocation, PreparedAgentInvocation, prepare_acp_invocation


def resolve_launch_command(_options: dict[str, Any] | None = None) -> list[str]:
    return [sys.executable, "-m", "cellos.connectors.fake_acp"]


def prepare_invocation(invocation: AgentInvocation) -> PreparedAgentInvocation:
    return prepare_acp_invocation(
        invocation,
        resolve_launch_command(invocation.agent.options),
        metadata={"agent_runtime": "fake_acp"},
    )


def send(message: dict) -> None:
    print(json.dumps(message), flush=True)


def main() -> None:
    for line in sys.stdin:
        message = json.loads(line)
        method = message.get("method")
        request_id = message.get("id")

        if method == "initialize":
            send({"jsonrpc": "2.0", "id": request_id, "result": {}})
        elif method == "session/new":
            send({"jsonrpc": "2.0", "id": request_id, "result": {"sessionId": "fake-session"}})
        elif method == "session/prompt":
            send(
                {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "fake ACP completed task"},
                        }
                    },
                }
            )
            send({"jsonrpc": "2.0", "id": request_id, "result": {"stopReason": "end_turn"}})
        elif method == "session/close":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": "Method not found"},
                }
            )
            break


if __name__ == "__main__":
    main()
