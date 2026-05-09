import json
import sys
import textwrap

import pytest

from cellos.acp import prepare_agent_invocation
from cellos.acp_worker import AcpWorker
from cellos.config import AgentConfig, load_prompt_profiles
from cellos.connectors.base import PromptEnvelope
from cellos.domain.enums import AgentRole, TaskStatus, TaskType
from cellos.domain.tasks import Task
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
    )

    prompt = build_task_prompt(task, prompt_profiles)

    assert "Role: engineer" in prompt
    assert "Task type: implementation" in prompt
    assert "Mode: execution" in prompt
    assert "Perform approved implementation work within scope" in prompt
    assert "Task prompt / approved scope:" in prompt
    assert "Change only the CLI." in prompt


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


def test_planning_prompt_includes_comments_and_research_results(prompt_profiles):
    task = Task(
        id="task-1",
        title="Replan feature",
        role=AgentRole.ARCHITECT,
        task_type=TaskType.ARCHITECTURE,
        status=TaskStatus.DRAFT,
        prompt="Previous plan.",
    )

    prompt = build_task_prompt(
        task,
        prompt_profiles,
        mode="planning",
        comments=[
            {
                "author_id": "james",
                "author_type": "human",
                "message": "Prefer the smaller design.",
                "payload": {},
            },
            {
                "author_id": "cellos",
                "author_type": "system",
                "message": "Research Results from abc123 - API research\n\nUse endpoint v2.",
                "payload": {"kind": "research_result"},
            },
        ],
    )

    assert "Comments:" in prompt
    assert "james: Prefer the smaller design." in prompt
    assert "Research Results:" in prompt
    assert "cellos: Research Results from abc123 - API research" in prompt
    assert "Use endpoint v2." in prompt


def test_execution_prompt_omits_comments_and_research_results(prompt_profiles):
    task = Task(
        id="task-1",
        title="Execute feature",
        role=AgentRole.ENGINEER,
        task_type=TaskType.IMPLEMENTATION,
        status=TaskStatus.APPROVED,
        prompt="Approved scope.",
    )

    prompt = build_task_prompt(
        task,
        prompt_profiles,
        mode="execution",
        comments=[
            {
                "author_id": "james",
                "author_type": "human",
                "message": "Backstory that should not be in execution.",
                "payload": {},
            },
            {
                "author_id": "cellos",
                "author_type": "system",
                "message": "Research Results from abc123 - API research\n\nUse endpoint v2.",
                "payload": {"kind": "research_result"},
            },
        ],
    )

    assert "Comments:" not in prompt
    assert "Research Results:" not in prompt
    assert "Backstory that should not be in execution." not in prompt
    assert "Use endpoint v2." not in prompt


def test_execution_prompt_does_not_execute_child_tasks(prompt_profiles):
    task = Task(
        id="task-1",
        title="Create child task",
        role=AgentRole.ARCHITECT,
        task_type=TaskType.ARCHITECTURE,
        status=TaskStatus.APPROVED,
        prompt="Create one implementation child task to edit docs.",
    )

    prompt = build_task_prompt(task, prompt_profiles, mode="execution")

    assert "If the approved plan says to create child tasks, create only those child tasks." in prompt
    assert "Do not execute, partially execute, or simulate child tasks in the same execution turn." in prompt
    assert "Do not edit files merely because a child task would edit files." in prompt
    assert "After creating child tasks, stop and report the created tasks." in prompt
    assert "return only the create_task actions plus a brief summary" in prompt


def test_prepare_opencode_agent_invocation(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "cellos.connectors.opencode._resolve_opencode_path",
        lambda: "/mock/path/opencode",
    )
    prepared = prepare_agent_invocation(
        agent_id="opencode",
        agent=AgentConfig(connector="opencode"),
        prompt=PromptEnvelope(text="Plan the task.", mode="planning"),
        workdir=tmp_path,
    )

    assert prepared.agent_id == "opencode"
    assert prepared.connector == "opencode"
    assert prepared.launch_command == ["/mock/path/opencode", "acp"]
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


def test_resolve_opencode_path_found(tmp_path, monkeypatch):
    """When a known path exists, it is returned."""
    fake_bin = tmp_path / ".opencode" / "bin" / "opencode"
    fake_bin.parent.mkdir(parents=True)
    fake_bin.touch(mode=0o755)
    monkeypatch.setattr("cellos.connectors.opencode._DEFAULT_PATHS", [fake_bin])
    monkeypatch.delenv("PATH", raising=False)

    from cellos.connectors.opencode import _resolve_opencode_path

    assert _resolve_opencode_path() == str(fake_bin)


def test_resolve_opencode_path_fallback_to_which(tmp_path, monkeypatch):
    """When no known path exists, shutil.which is used."""
    monkeypatch.setattr("cellos.connectors.opencode._DEFAULT_PATHS", [])
    import sys
    mod = sys.modules["cellos.connectors.opencode"]
    orig_which = mod.shutil.which
    mod.shutil.which = lambda name: "/usr/bin/opencode"
    try:
        from cellos.connectors.opencode import _resolve_opencode_path
        assert _resolve_opencode_path() == "/usr/bin/opencode"
    finally:
        mod.shutil.which = orig_which


def test_resolve_opencode_path_none(tmp_path, monkeypatch):
    """When nothing is found, None is returned."""
    monkeypatch.setattr("cellos.connectors.opencode._DEFAULT_PATHS", [])
    import sys
    mod = sys.modules["cellos.connectors.opencode"]
    orig_which = mod.shutil.which
    mod.shutil.which = lambda name: None
    try:
        from cellos.connectors.opencode import _resolve_opencode_path
        assert _resolve_opencode_path() is None
    finally:
        mod.shutil.which = orig_which


def test_resolve_launch_command_no_path(monkeypatch):
    """When opencode binary is not found, a clear error is raised."""
    monkeypatch.setattr("cellos.connectors.opencode._resolve_opencode_path", lambda: None)

    from cellos.connectors.opencode import resolve_launch_command

    with pytest.raises(FileNotFoundError, match="opencode binary not found"):
        resolve_launch_command()
