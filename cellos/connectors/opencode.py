"""OpenCode ACP connector."""

from typing import Any

from cellos.connectors.base import AgentInvocation, PreparedAgentInvocation, prepare_acp_invocation


def resolve_launch_command(options: dict[str, Any] | None = None) -> list[str]:
    options = options or {}
    command = options.get("command")
    if command is None:
        return ["opencode", "acp"]
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise ValueError("OpenCode connector option 'command' must be a list of strings.")
    return command


def prepare_invocation(invocation: AgentInvocation) -> PreparedAgentInvocation:
    return prepare_acp_invocation(
        invocation,
        resolve_launch_command(invocation.agent.options),
        metadata={"agent_runtime": "opencode"},
    )
