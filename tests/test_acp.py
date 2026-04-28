import json
import sys
import textwrap

import pytest

from cellos.acp import exec_task


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_exec_task_collects_prompt_events_and_result(tmp_path):
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
                    print(json.dumps({
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {"protocolVersion": 1, "agentInfo": {"name": "fake"}}
                    }), flush=True)
                elif method == "session/new":
                    print(json.dumps({
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {"sessionId": "session-1"}
                    }), flush=True)
                elif method == "session/prompt":
                    print(json.dumps({
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": "session-1",
                            "update": {
                                "sessionUpdate": "agent_thought_chunk",
                                "content": {"type": "text", "text": "thinking out loud"}
                            }
                        }
                    }), flush=True)
                    print(json.dumps({
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": "session-1",
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": "CELLOS_"}
                            }
                        }
                    }), flush=True)
                    print(json.dumps({
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": "session-1",
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": "ACP_OK"}
                            }
                        }
                    }), flush=True)
                    print(json.dumps({
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {"stopReason": "end_turn"}
                    }), flush=True)
                elif method == "session/close":
                    print(json.dumps({
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {}
                    }), flush=True)
                    break
            """
        )
    )

    result = await exec_task(
        command=[sys.executable, str(fake_server)],
        cwd=tmp_path,
        prompt="Say OK",
    )

    assert result.session_id == "session-1"
    assert result.stop_reason == "end_turn"
    assert result.text == "CELLOS_ACP_OK"
    assert len(result.events) == 3


@pytest.mark.anyio
async def test_exec_task_logs_and_skips_non_json_stdout(tmp_path):
    fake_server = tmp_path / "fake_noisy_acp_server.py"
    debug_log = tmp_path / "acp-debug.log"
    fake_server.write_text(
        textwrap.dedent(
            """
            import json
            import sys

            print("not json banner", flush=True)

            for line in sys.stdin:
                message = json.loads(line)
                method = message.get("method")
                request_id = message.get("id")
                if method == "initialize":
                    print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": {}}), flush=True)
                elif method == "session/new":
                    print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": {"sessionId": "s1"}}), flush=True)
                elif method == "session/prompt":
                    print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": {"stopReason": "end_turn"}}), flush=True)
                elif method == "session/close":
                    print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": {}}), flush=True)
                    break
            """
        )
    )

    result = await exec_task(
        command=[sys.executable, str(fake_server)],
        cwd=tmp_path,
        prompt="Say OK",
        debug_log_path=debug_log,
        skip_non_json_stdout=True,
    )

    assert result.session_id == "s1"
    assert debug_log.read_text() == "b'not json banner\\n'\n"


@pytest.mark.anyio
async def test_exec_task_is_strict_about_non_json_stdout_by_default(tmp_path):
    fake_server = tmp_path / "fake_noisy_acp_server.py"
    fake_server.write_text('print("not json banner", flush=True)')

    with pytest.raises(json.JSONDecodeError):
        await exec_task(
            command=[sys.executable, str(fake_server)],
            cwd=tmp_path,
            prompt="Say OK",
        )
