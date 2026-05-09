"""OpenCode ACP connector."""

import shutil
from pathlib import Path
from typing import Any

from cellos.connectors.base import AgentInvocation, PreparedAgentInvocation, prepare_acp_invocation

# Prioritized list of known opencode binary locations.
# Falls through to shutil.which (PATH) if none match.
_DEFAULT_PATHS: list[Path] = [
    Path.home() / ".opencode" / "bin" / "opencode",
    Path.home() / ".local" / "bin" / "opencode",
    Path("/usr/local/bin/opencode"),
    Path("/usr/bin/opencode"),
]


def _resolve_opencode_path() -> str | None:
    """Find the opencode binary using known paths, falling back to PATH."""
    for p in _DEFAULT_PATHS:
        if p.exists() and p.is_file():
            return str(p)
    which = shutil.which("opencode")
    if which:
        return which
    return None


def resolve_launch_command(options: dict[str, Any] | None = None) -> list[str]:
    options = options or {}
    command = options.get("command")
    if command is None:
        path = _resolve_opencode_path()
        if path is None:
            raise FileNotFoundError(
                "opencode binary not found. Add ~/.opencode/bin to your PATH "
                "or configure via agent options: {\"command\": [\"/path/to/opencode\", \"acp\"]}"
            )
        return [path, "acp"]
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise ValueError("OpenCode connector option 'command' must be a list of strings.")
    return command


def prepare_invocation(invocation: AgentInvocation) -> PreparedAgentInvocation:
    return prepare_acp_invocation(
        invocation,
        resolve_launch_command(invocation.agent.options),
        metadata={"agent_runtime": "opencode"},
    )
