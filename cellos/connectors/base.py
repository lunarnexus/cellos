"""Shared agent connector interfaces."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from cellos.config import AgentConfig


@dataclass(frozen=True)
class PromptEnvelope:
    text: str
    mode: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentInvocation:
    agent_id: str
    agent: AgentConfig
    prompt: PromptEnvelope
    workdir: Path
    timeout_seconds: int | None = None
    debug_log_path: Path | None = None
    skip_non_json_stdout: bool = True


@dataclass(frozen=True)
class PreparedAgentInvocation:
    agent_id: str
    connector: str
    launch_command: list[str]
    prompt: PromptEnvelope
    workdir: Path
    timeout_seconds: int | None = None
    debug_log_path: Path | None = None
    skip_non_json_stdout: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentConnector(Protocol):
    def resolve_launch_command(self, options: dict[str, Any] | None = None) -> list[str]: ...

    def prepare_invocation(self, invocation: AgentInvocation) -> PreparedAgentInvocation: ...


def prepare_acp_invocation(
    invocation: AgentInvocation,
    launch_command: list[str],
    metadata: dict[str, Any] | None = None,
) -> PreparedAgentInvocation:
    return PreparedAgentInvocation(
        agent_id=invocation.agent_id,
        connector=invocation.agent.connector,
        launch_command=launch_command,
        prompt=invocation.prompt,
        workdir=invocation.workdir,
        timeout_seconds=invocation.timeout_seconds,
        debug_log_path=invocation.debug_log_path,
        skip_non_json_stdout=invocation.skip_non_json_stdout,
        metadata=metadata or {},
    )
