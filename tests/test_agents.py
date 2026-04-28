import json
import sys
import textwrap

import pytest

from cellos.connectors.opencode import OpenCodeAcpBackend
from cellos.models import AgentRole, Task, TaskType


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_opencode_acp_backend_runs_task_once(tmp_path):
    fake_server = tmp_path / "fake_acp_server.py"
    fake_server.write_text(
        textwrap.dedent(
            """
            import json
            import sys

            print("opencode plugin banner", flush=True)

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
    backend = OpenCodeAcpBackend(command=[sys.executable, str(fake_server)])
    task = Task(
        id="task-1",
        title="Build something tiny",
        task_type=TaskType.BUILD,
        role=AgentRole.CELLO,
    )

    result = await backend.run_task_once(task, tmp_path)

    assert result.task_id == "task-1"
    assert result.success is True
    assert result.summary == "built"
    assert result.output["session_id"] == "s1"
    assert (tmp_path / ".cellos" / "acp-debug.log").read_text() == "b'opencode plugin banner\\n'\n"
