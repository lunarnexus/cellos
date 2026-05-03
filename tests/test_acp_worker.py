import json
import sys
import textwrap

import pytest

from cellos.acp import prepare_agent_invocation
from cellos.acp_worker import AcpWorker
from cellos.config import AgentConfig, load_prompt_profiles
from cellos.connectors.base import PromptEnvelope
from cellos.models import AgentRole, Task, TaskStatus, TaskType
from cellos.prompt_builder import build_task_prompt


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def prompt_profiles():
    return load_prompt_profiles("promptprofiles.example.json")


def test_build_task_prompt_includes_approved_scope(prompt_profiles):
    task = Task(
        id="task-1",
        title="Implement feature",
        role=AgentRole.ENGINEER,
        task_type=TaskType.IMPLEMENTATION,
        status=TaskStatus.APPROVED,
        prompt="Change only the CLI.",
        description="Keep it small.",
    )

    prompt = build_task_prompt(task, prompt_profiles)

    assert "Role: engineer" in prompt
    assert "Task type: implementation" in prompt
    assert "Mode: execution" in prompt
    assert "Perform approved implementation work within scope" in prompt
    assert "Task prompt / approved scope:" in prompt
    assert "Change only the CLI." in prompt
    assert "Keep it small." in prompt


def test_build_task_prompt_uses_planning_profile(prompt_profiles):
    task = Task(
        id="task-1",
        title="Plan feature",
        role=AgentRole.ARCHITECT,
        task_type=TaskType.PROPOSAL,
        status=TaskStatus.DRAFT,
        prompt="Draft a plan.",
    )

    prompt = build_task_prompt(task, prompt_profiles, mode="planning")

    assert "Role: architect" in prompt
    assert "Mode: planning" in prompt
    assert "Draft or revise a plan only." in prompt
    assert "Design task boundaries" in prompt
    assert "Do not perform write actions" in prompt
    assert "Response format:" in prompt
    assert "- Objective" in prompt
    assert "- Proposed Actions" in prompt
    assert "- Files/Systems Affected" in prompt
    assert "- Risks" in prompt
    assert "- Acceptance Criteria" in prompt
    assert "- Approval Request" in prompt


def test_prepare_opencode_agent_invocation(tmp_path):
    prepared = prepare_agent_invocation(
        agent_id="opencode",
        agent=AgentConfig(connector="opencode"),
        prompt=PromptEnvelope(text="Plan the task.", mode="planning"),
        workdir=tmp_path,
    )

    assert prepared.agent_id == "opencode"
    assert prepared.connector == "opencode"
    assert prepared.launch_command == ["opencode", "acp"]
    assert prepared.prompt.text == "Plan the task."
    assert prepared.prompt.mode == "planning"


@pytest.mark.anyio
async def test_acp_worker_runs_task_with_fake_server(tmp_path, prompt_profiles):
    fake_server = tmp_path / "fake_acp_server.py"
    fake_server.write_text(
        textwrap.dedent(
            """
            import json
            import sys

            for line in sys.stdin:
                message = json.loads(line)
                method = message.get("method")
                request_id = message.get("id")

                if method == "initialize":
                    print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": {}}), flush=True)
                elif method == "session/new":
                    print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": {"sessionId": "s1"}}), flush=True)
                elif method == "session/prompt":
                    print(json.dumps({
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": "built"}
                            }
                        }
                    }), flush=True)
                    print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": {"stopReason": "end_turn"}}), flush=True)
                elif method == "session/close":
                    print(json.dumps({
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32601, "message": "Method not found"}
                    }), flush=True)
                    break
            """
        )
    )
    worker = AcpWorker(
        agent_id="fake-test",
        agent=AgentConfig(connector="opencode", options={"command": [sys.executable, str(fake_server)]}),
        prompt_profiles=prompt_profiles,
    )
    task = Task(
        id="task-1",
        title="Implement feature",
        role=AgentRole.ENGINEER,
        task_type=TaskType.IMPLEMENTATION,
        status=TaskStatus.APPROVED,
    )

    result = await worker.run_task(task, tmp_path, mode="planning")

    assert result.task_id == "task-1"
    assert result.success is True
    assert result.summary == "built"
    assert result.output["session_id"] == "s1"
    assert result.output["mode"] == "planning"
    assert result.output["selected_agent_id"] == "fake-test"
    assert result.output["connector"] == "opencode"
    assert result.output["agent_metadata"]["agent_runtime"] == "opencode"
