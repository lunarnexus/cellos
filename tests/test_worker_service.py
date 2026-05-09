import json
from pathlib import Path

import pytest

from cellos.config import load_config
from cellos.db import CellosDatabase
from cellos.domain.enums import AgentRole, TaskStatus
from cellos.domain.tasks import Task
from cellos.services.worker_service import WorkerService
from tests.test_cli import MINIMAL_PROMPT_PROFILES


@pytest.fixture
def anyio_backend():
    return "asyncio"


def write_fake_config(config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "scheduler": {"concurrent_tasks": 4, "worker_timeout_seconds": 30},
                "worker": {"backend": "acp", "debug_log_path": ".cellos/logs/acp-debug.log", "debug_logging": True},
                "agents": {"default": "fake", "catalog_path": "agentcatalog.json"},
                "prompts": {"profiles_path": "promptprofiles.json"},
            }
        )
    )
    (config_path.parent / "agentcatalog.json").write_text(
        json.dumps({"available": {"fake": {"connector": "fake_acp", "description": "Fake agent"}}})
    )
    (config_path.parent / "promptprofiles.json").write_text(json.dumps(MINIMAL_PROMPT_PROFILES))


@pytest.mark.anyio
async def test_worker_service_runs_planning_worker_and_records_attempt(tmp_path):
    config_path = tmp_path / ".cellos" / "config.json"
    write_fake_config(config_path)
    config = load_config(config_path)
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()
    await db.create_task(Task(id="plan", title="Plan", role=AgentRole.COORDINATOR, status=TaskStatus.IN_PROGRESS))

    await WorkerService(db=db, config=config, workdir=tmp_path).run_task_worker("plan", "planning")

    saved = await db.get_task("plan")
    attempts = await db.list_task_attempts("plan")
    events = await db.list_task_events(task_id="plan")
    assert saved.status == TaskStatus.NEEDS_APPROVAL
    assert saved.prompt == "fake ACP completed task"
    assert len(attempts) == 1
    assert attempts[0]["mode"] == "planning"
    assert attempts[0]["status"] == "succeeded"
    assert any(event["event_type"] == "worker_started" for event in events)
    assert any(event["event_type"] == "planning_saved" for event in events)
    await db.close()


@pytest.mark.anyio
async def test_worker_service_runs_execution_worker_and_records_attempt(tmp_path):
    config_path = tmp_path / ".cellos" / "config.json"
    write_fake_config(config_path)
    config = load_config(config_path)
    db = CellosDatabase(tmp_path / "cellos.sqlite")
    await db.connect()
    await db.init_db()
    await db.create_task(Task(id="execute", title="Execute", role=AgentRole.ENGINEER, status=TaskStatus.IN_PROGRESS))

    await WorkerService(db=db, config=config, workdir=tmp_path).run_task_worker("execute", "execution")

    saved = await db.get_task("execute")
    attempts = await db.list_task_attempts("execute")
    assert saved.status == TaskStatus.DONE
    assert saved.result is not None
    assert saved.result.summary == "fake ACP completed task"
    assert len(attempts) == 1
    assert attempts[0]["mode"] == "execution"
    assert attempts[0]["status"] == "succeeded"
    await db.close()
