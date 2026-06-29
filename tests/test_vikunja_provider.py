from __future__ import annotations

import json
from typing import Any

import pytest
import pytest_asyncio

from cellos.db import CellosDatabase
from cellos.models import AgentRole, Task, TaskStatus
from cellos.persistence.schema import init_db


@pytest_asyncio.fixture
async def db(tmp_path):
    db_path = tmp_path / "vikunja-provider.sqlite"
    await init_db(str(db_path))
    database = CellosDatabase(str(db_path))
    await database.connect()
    yield database
    await database.close()


class TestVikunjaProvider:
    def test_registry_discovers_vikunja_provider(self):
        from cellos.integrations.registry import get_providers

        providers = get_providers()
        assert "vikunja" in providers

    def test_load_vikunja_provider(self):
        from cellos.config import CellosConfig
        from cellos.integrations.registry import load_provider

        prov = load_provider("vikunja", config=CellosConfig(), _config_dir="/tmp")
        assert prov.provider_name == "vikunja"
        assert prov.provider_description == "Vikunja project/task sync"

    @pytest.mark.asyncio
    async def test_status_reports_missing_credentials_when_unconfigured(self, monkeypatch):
        from cellos.config import CellosConfig
        from cellos.integrations.registry import load_provider

        monkeypatch.delenv("VIKUNJA_BASE_URL", raising=False)
        monkeypatch.delenv("VIKUNJA_API_TOKEN", raising=False)

        prov = load_provider("vikunja", config=CellosConfig(), _config_dir="/tmp")
        status = await prov.status()

        assert status.provider_name == "vikunja"
        assert status.configured is False
        assert status.credentials_configured is False
        assert status.board_or_target is None

    @pytest.mark.asyncio
    async def test_status_uses_configured_project_details(self, monkeypatch):
        from cellos.config import CellosConfig, IntegrationsConfig, ProviderConfig
        from cellos.integrations.registry import load_provider

        monkeypatch.setenv("VIKUNJA_BASE_URL", "https://vikunja.example")
        monkeypatch.setenv("VIKUNJA_API_TOKEN", "secret-token")

        cfg = CellosConfig(
            integrations=IntegrationsConfig(
                providers={
                    "vikunja": ProviderConfig(
                        project_id="proj-123",
                        view_id="view-abc",
                        bucket_map={"backlog": "bucket-1", "done": "bucket-2"},
                    )
                }
            )
        )
        prov = load_provider("vikunja", config=cfg, _config_dir="/tmp")

        status = await prov.status()

        assert status.configured is True
        assert status.credentials_configured is True
        assert status.board_or_target == "proj-123"
        assert status.details["view_id"] == "view-abc"
        assert status.details["list_mapping"] == {"backlog": "bucket-1", "done": "bucket-2"}

    @pytest.mark.asyncio
    async def test_setup_fetches_project_and_buckets(self, monkeypatch):
        from cellos.config import CellosConfig, IntegrationsConfig, ProviderConfig
        from cellos.integrations.registry import load_provider

        monkeypatch.setenv("VIKUNJA_BASE_URL", "https://vikunja.example")
        monkeypatch.setenv("VIKUNJA_API_TOKEN", "secret-token")

        cfg = CellosConfig(
            integrations=IntegrationsConfig(
                providers={"vikunja": ProviderConfig(project_id="17", view_id="3")}
            )
        )
        prov = load_provider("vikunja", config=cfg, _config_dir="/tmp")

        created_buckets: list[str] = []

        class FakeClient:
            async def get_project(self, project_id: str):
                assert project_id == "17"
                return {"id": 17, "title": "Infra"}

            async def get_buckets(self, project_id: str, view_id: str):
                assert project_id == "17"
                assert view_id == "3"
                return [
                    {"id": 10, "title": "Backlog"},
                    {"id": 20, "title": "In Progress"},
                    {"id": 30, "title": "Done"},
                ]

            async def create_bucket(self, project_id: str, view_id: str, title: str):
                created_buckets.append(title)
                return {"id": 30 + len(created_buckets), "title": title}

            async def get_labels(self):
                return [
                    {"id": 1, "title": "architect"},
                    {"id": 2, "title": "engineer"},
                ]

        monkeypatch.setattr(prov, "_build_client", lambda: FakeClient())

        result = await prov.setup()

        assert created_buckets == ["To-Do", "Doing"]
        assert result.target_id == "17"
        assert result.mappings == {
            "backlog": "10",
            "in progress": "20",
            "done": "30",
            "to-do": "31",
            "doing": "32",
        }
        assert result.details["project_title"] == "Infra"
        assert result.details["view_id"] == "3"

    @pytest.mark.asyncio
    async def test_setup_ensures_required_labels_exist(self, monkeypatch):
        from cellos.config import CellosConfig, IntegrationsConfig, ProviderConfig
        from cellos.integrations.registry import load_provider

        monkeypatch.setenv("VIKUNJA_BASE_URL", "https://vikunja.example")
        monkeypatch.setenv("VIKUNJA_API_TOKEN", "secret-token")

        cfg = CellosConfig(
            integrations=IntegrationsConfig(
                providers={"vikunja": ProviderConfig(project_id="17", view_id="3")}
            )
        )
        prov = load_provider("vikunja", config=cfg, _config_dir="/tmp")

        created: list[str] = []

        class FakeClient:
            async def get_project(self, project_id: str):
                return {"id": 17, "title": "Infra"}

            async def get_buckets(self, project_id: str, view_id: str):
                return [
                    {"id": 10, "title": "To-Do"},
                    {"id": 20, "title": "Doing"},
                    {"id": 30, "title": "Done"},
                ]

            async def get_labels(self):
                return [{"id": 1, "title": "backend"}]

            async def create_label(self, title: str):
                created.append(title)
                return {"id": len(created) + 1, "title": title}

        monkeypatch.setattr(prov, "_build_client", lambda: FakeClient())

        result = await prov.setup()

        assert created == ["architect", "engineer"]
        assert result.details["required_labels"] == ["architect", "engineer"]
        assert result.details["created_labels"] == ["architect", "engineer"]

    @pytest.mark.asyncio
    async def test_setup_preserves_existing_required_labels(self, monkeypatch):
        from cellos.config import CellosConfig, IntegrationsConfig, ProviderConfig
        from cellos.integrations.registry import load_provider

        monkeypatch.setenv("VIKUNJA_BASE_URL", "https://vikunja.example")
        monkeypatch.setenv("VIKUNJA_API_TOKEN", "secret-token")

        cfg = CellosConfig(
            integrations=IntegrationsConfig(
                providers={"vikunja": ProviderConfig(project_id="17", view_id="3")}
            )
        )
        prov = load_provider("vikunja", config=cfg, _config_dir="/tmp")

        created: list[str] = []

        class FakeClient:
            async def get_project(self, project_id: str):
                return {"id": 17, "title": "Infra"}

            async def get_buckets(self, project_id: str, view_id: str):
                return [
                    {"id": 10, "title": "To-Do"},
                    {"id": 20, "title": "Doing"},
                    {"id": 30, "title": "Done"},
                ]

            async def get_labels(self):
                return [
                    {"id": 1, "title": "architect"},
                    {"id": 2, "title": "engineer"},
                ]

            async def create_label(self, title: str):
                created.append(title)
                return {"id": len(created) + 2, "title": title}

        monkeypatch.setattr(prov, "_build_client", lambda: FakeClient())

        result = await prov.setup()

        assert created == []
        assert result.details["created_labels"] == []
        assert result.details["required_labels"] == ["architect", "engineer"]

    @pytest.mark.asyncio
    async def test_setup_creates_missing_default_buckets(self, monkeypatch):
        from cellos.config import CellosConfig, IntegrationsConfig, ProviderConfig
        from cellos.integrations.registry import load_provider

        monkeypatch.setenv("VIKUNJA_BASE_URL", "https://vikunja.example")
        monkeypatch.setenv("VIKUNJA_API_TOKEN", "secret-token")

        cfg = CellosConfig(
            integrations=IntegrationsConfig(
                providers={"vikunja": ProviderConfig(project_id="17", view_id="3")}
            )
        )
        prov = load_provider("vikunja", config=cfg, _config_dir="/tmp")

        created_buckets: list[str] = []

        class FakeClient:
            async def get_project(self, project_id: str):
                return {"id": 17, "title": "Infra"}

            async def get_project_view(self, project_id: str, view_id: str):
                return {"id": 3, "title": "Board"}

            async def list_project_views(self, project_id: str):
                return [{"id": 3, "title": "Board"}]

            async def get_buckets(self, project_id: str, view_id: str):
                return [{"id": 10, "title": "To-Do"}]

            async def create_bucket(self, project_id: str, view_id: str, title: str):
                created_buckets.append(title)
                return {"id": len(created_buckets) + 10, "title": title}

            async def get_labels(self):
                return [
                    {"id": 1, "title": "architect"},
                    {"id": 2, "title": "engineer"},
                ]

        monkeypatch.setattr(prov, "_build_client", lambda: FakeClient())

        result = await prov.setup()

        assert created_buckets == ["Doing", "Done"]
        assert result.mappings == {
            "to-do": "10",
            "doing": "11",
            "done": "12",
        }
        assert result.details["created_buckets"] == ["Doing", "Done"]

    @pytest.mark.asyncio
    async def test_setup_clean_resets_project_state_without_deleting_labels(self, monkeypatch, db):
        from cellos.config import CellosConfig, IntegrationsConfig, ProviderConfig
        from cellos.integrations.registry import load_provider

        monkeypatch.setenv("VIKUNJA_BASE_URL", "https://vikunja.example")
        monkeypatch.setenv("VIKUNJA_API_TOKEN", "secret-token")

        cfg = CellosConfig(
            integrations=IntegrationsConfig(
                providers={"vikunja": ProviderConfig(project_id="17", view_id="3")}
            )
        )
        prov = load_provider("vikunja", config=cfg, _config_dir="/tmp")
        prov._db = db

        deleted_tasks: list[str] = []
        deleted_views: list[str] = []
        deleted_buckets: list[str] = []
        created_buckets: list[str] = []

        await db.conn.execute(
            "INSERT INTO integration_sync(key, value) VALUES(?, ?)",
            ("vikunja.task.local-1", json.dumps({"remote_task_id": 101})),
        )
        await db.conn.execute(
            "INSERT INTO integration_sync(key, value) VALUES(?, ?)",
            ("vikunja.task.local-2", json.dumps({"remote_task_id": 102})),
        )
        await db.conn.commit()

        class FakeClient:
            async def get_project(self, project_id: str):
                return {"id": 17, "title": "Infra"}

            async def get_project_view(self, project_id: str, view_id: str):
                return {"id": 3, "title": "Managed Board"}

            async def list_project_views(self, project_id: str):
                return [
                    {"id": 3, "title": "Managed Board"},
                    {"id": 4, "title": "Throwaway Board"},
                ]

            async def delete_project_view(self, project_id: str, view_id: str):
                deleted_views.append(view_id)
                return None

            async def list_project_tasks(self, project_id: str, expand=None):
                return [
                    {"id": 101, "title": "old task"},
                    {"id": 102, "title": "old task 2"},
                ]

            async def delete_task(self, task_id: str):
                deleted_tasks.append(task_id)
                return None

            async def get_buckets(self, project_id: str, view_id: str):
                return [
                    {"id": 10, "title": "To-Do"},
                    {"id": 20, "title": "Doing"},
                    {"id": 30, "title": "Done"},
                    {"id": 40, "title": "Extra"},
                ]

            async def delete_bucket(self, project_id: str, view_id: str, bucket_id: str):
                deleted_buckets.append(bucket_id)
                return None

            async def create_bucket(self, project_id: str, view_id: str, title: str):
                created_buckets.append(title)
                return {"id": 100 + len(created_buckets), "title": title}

            async def get_labels(self):
                return [
                    {"id": 1, "title": "architect"},
                    {"id": 2, "title": "engineer"},
                ]

        monkeypatch.setattr(prov, "_build_client", lambda: FakeClient())

        result = await prov.setup(clean=True)

        assert deleted_tasks == ["101", "102"]
        assert deleted_views == ["4"]
        assert deleted_buckets == ["10", "20", "30", "40"]
        assert created_buckets == ["To-Do", "Doing", "Done"]
        assert result.details["cleaned"] is True
        assert result.details["deleted_tasks"] == 2
        assert result.details["deleted_views"] == ["4"]
        assert result.details["deleted_buckets"] == ["10", "20", "30", "40"]
        assert result.details["cleared_task_mappings"] == 2
        assert result.details["created_labels"] == []

        cursor = await db.conn.execute(
            "SELECT COUNT(*) FROM integration_sync WHERE key LIKE 'vikunja.task.%'"
        )
        row = await cursor.fetchone()
        assert row[0] == 0

    @pytest.mark.asyncio
    async def test_setup_clean_refreshes_in_memory_bucket_map_for_followup_push(self, monkeypatch, db):
        from cellos.config import CellosConfig, IntegrationsConfig, ProviderConfig
        from cellos.integrations.registry import load_provider

        monkeypatch.setenv("VIKUNJA_BASE_URL", "https://vikunja.example")
        monkeypatch.setenv("VIKUNJA_API_TOKEN", "secret-token")

        task = Task(
            id="task-local-clean",
            title="Fresh after clean",
            details="Uses recreated buckets",
            role=AgentRole.ENGINEER,
            status=TaskStatus.APPROVED,
        )
        await db.create_task(task)

        cfg = CellosConfig(
            integrations=IntegrationsConfig(
                providers={
                    "vikunja": ProviderConfig(
                        project_id="17",
                        view_id="4",
                        bucket_map={"to-do": "1", "doing": "2", "done": "3"},
                    )
                }
            )
        )
        prov = load_provider("vikunja", config=cfg, _config_dir="/tmp")
        prov._db = db

        captured: dict[str, Any] = {}

        class FakeClient:
            async def get_project(self, project_id: str):
                return {"id": 17, "title": "Infra"}

            async def get_project_view(self, project_id: str, view_id: str):
                return {"id": 4, "title": "Board"}

            async def list_project_views(self, project_id: str):
                return [{"id": 4, "title": "Board"}]

            async def list_project_tasks(self, project_id: str, expand=None):
                return []

            async def get_buckets(self, project_id: str, view_id: str):
                return [
                    {"id": 1, "title": "To-Do"},
                    {"id": 2, "title": "Doing"},
                    {"id": 3, "title": "Done"},
                ]

            async def delete_bucket(self, project_id: str, view_id: str, bucket_id: str):
                return None

            async def create_bucket(self, project_id: str, view_id: str, title: str):
                mapping = {"To-Do": 4, "Doing": 5, "Done": 6}
                return {"id": mapping[title], "title": title}

            async def get_labels(self):
                return [
                    {"id": 1, "title": "architect"},
                    {"id": 2, "title": "engineer"},
                ]

            async def create_task(self, project_id: str, payload: dict):
                captured["payload"] = payload
                return {"id": 901, **payload}

            async def move_task_to_bucket(self, project_id: str, view_id: str, bucket_id: int, task_id: int):
                captured["move"] = {
                    "project_id": project_id,
                    "view_id": view_id,
                    "bucket_id": bucket_id,
                    "task_id": task_id,
                }
                return {}

        monkeypatch.setattr(prov, "_build_client", lambda: FakeClient())

        result = await prov.setup(clean=True)
        assert result.mappings == {"to-do": "4", "doing": "5", "done": "6"}

        delta = await prov.sync(push=True, pull=False)
        assert delta.items_created == 1
        assert captured["move"] == {
            "project_id": "17",
            "view_id": "4",
            "bucket_id": 4,
            "task_id": 901,
        }

    @pytest.mark.asyncio
    async def test_sync_returns_empty_delta_when_no_push_or_pull_work(self, monkeypatch):
        from cellos.config import CellosConfig, IntegrationsConfig, ProviderConfig
        from cellos.integrations.base import SyncDelta
        from cellos.integrations.registry import load_provider

        monkeypatch.setenv("VIKUNJA_BASE_URL", "https://vikunja.example")
        monkeypatch.setenv("VIKUNJA_API_TOKEN", "secret-token")

        cfg = CellosConfig(
            integrations=IntegrationsConfig(
                providers={"vikunja": ProviderConfig(project_id="17", view_id="3")}
            )
        )
        prov = load_provider("vikunja", config=cfg, _config_dir="/tmp")
        delta = await prov.sync(push=True, pull=True)

        assert isinstance(delta, SyncDelta)
        assert delta.items_created == 0
        assert delta.items_updated == 0
        assert delta.comments_imported == 0
        assert delta.statuses_changed == 0
        assert delta.errors == []

    @pytest.mark.asyncio
    async def test_sync_push_creates_remote_task_and_persists_mapping(self, monkeypatch, db):
        from cellos.config import CellosConfig, IntegrationsConfig, ProviderConfig
        from cellos.integrations.registry import load_provider

        monkeypatch.setenv("VIKUNJA_BASE_URL", "https://vikunja.example")
        monkeypatch.setenv("VIKUNJA_API_TOKEN", "secret-token")

        task = Task(
            id="task-local-1",
            title="Ship connector",
            details="Implement outbound sync",
            role=AgentRole.ENGINEER,
            status=TaskStatus.APPROVED,
        )
        await db.create_task(task)

        cfg = CellosConfig(
            integrations=IntegrationsConfig(
                providers={
                    "vikunja": ProviderConfig(
                        project_id="17",
                        view_id="4",
                        bucket_map={"to-do": "1", "doing": "2", "done": "3"},
                    )
                }
            )
        )
        prov = load_provider("vikunja", config=cfg, _config_dir="/tmp")
        prov._db = db

        captured = {}

        class FakeClient:
            async def create_task(self, project_id: str, payload: dict):
                captured["project_id"] = project_id
                captured["payload"] = payload
                return {"id": 401, **payload}

            async def move_task_to_bucket(self, project_id: str, view_id: str, bucket_id: int, task_id: int):
                captured["move"] = {
                    "project_id": project_id,
                    "view_id": view_id,
                    "bucket_id": bucket_id,
                    "task_id": task_id,
                }
                return {"bucket_id": bucket_id, "task_id": task_id, "project_view_id": int(view_id)}

        monkeypatch.setattr(prov, "_build_client", lambda: FakeClient())

        delta = await prov.sync(push=True, pull=False)

        assert delta.items_created == 1
        assert captured["project_id"] == "17"
        assert captured["payload"]["title"] == "Ship connector"
        assert captured["payload"]["description"] == "Implement outbound sync"
        assert "bucket_id" not in captured["payload"]
        assert captured["payload"]["done"] is False
        assert captured["move"] == {
            "project_id": "17",
            "view_id": "4",
            "bucket_id": 1,
            "task_id": 401,
        }

        cursor = await db.conn.execute(
            "SELECT value FROM integration_sync WHERE key = ?",
            ("vikunja.task.task-local-1",),
        )
        row = await cursor.fetchone()
        assert row is not None
        mapping = json.loads(row[0])
        assert mapping["remote_task_id"] == 401
        assert mapping["last_bucket_id"] == 1

    @pytest.mark.asyncio
    async def test_sync_push_updates_existing_remote_task(self, monkeypatch, db):
        from cellos.config import CellosConfig, IntegrationsConfig, ProviderConfig
        from cellos.integrations.registry import load_provider

        monkeypatch.setenv("VIKUNJA_BASE_URL", "https://vikunja.example")
        monkeypatch.setenv("VIKUNJA_API_TOKEN", "secret-token")

        task = Task(
            id="task-local-2",
            title="Ship connector v2",
            details="Add status updates",
            role=AgentRole.ENGINEER,
            status=TaskStatus.DONE,
        )
        await db.create_task(task)
        await db.conn.execute(
            "INSERT INTO integration_sync(key, value) VALUES(?, ?)",
            (
                "vikunja.task.task-local-2",
                json.dumps({"remote_task_id": 402, "last_synced_status": "approved"}),
            ),
        )
        await db.conn.commit()

        cfg = CellosConfig(
            integrations=IntegrationsConfig(
                providers={
                    "vikunja": ProviderConfig(
                        project_id="17",
                        view_id="4",
                        bucket_map={"to-do": "1", "doing": "2", "done": "3"},
                    )
                }
            )
        )
        prov = load_provider("vikunja", config=cfg, _config_dir="/tmp")
        prov._db = db

        captured = {}

        class FakeClient:
            async def update_task(self, task_id: str, payload: dict):
                captured["task_id"] = task_id
                captured["payload"] = payload
                return {"id": int(task_id), **payload}

            async def move_task_to_bucket(self, project_id: str, view_id: str, bucket_id: int, task_id: int):
                captured["move"] = {
                    "project_id": project_id,
                    "view_id": view_id,
                    "bucket_id": bucket_id,
                    "task_id": task_id,
                }
                return {"bucket_id": bucket_id, "task_id": task_id, "project_view_id": int(view_id)}

        monkeypatch.setattr(prov, "_build_client", lambda: FakeClient())

        delta = await prov.sync(push=True, pull=False)

        assert delta.items_created == 0
        assert delta.items_updated == 1
        assert delta.statuses_changed == 1
        assert captured["task_id"] == "402"
        assert captured["payload"]["title"] == "Ship connector v2"
        assert "bucket_id" not in captured["payload"]
        assert captured["payload"]["done"] is True
        assert captured["move"] == {
            "project_id": "17",
            "view_id": "4",
            "bucket_id": 3,
            "task_id": 402,
        }

    @pytest.mark.asyncio
    async def test_sync_pull_imports_remote_task_with_bucket_status(self, monkeypatch, db):
        from cellos.config import CellosConfig, IntegrationsConfig, ProviderConfig
        from cellos.integrations.registry import load_provider

        monkeypatch.setenv("VIKUNJA_BASE_URL", "https://vikunja.example")
        monkeypatch.setenv("VIKUNJA_API_TOKEN", "secret-token")

        cfg = CellosConfig(
            integrations=IntegrationsConfig(
                providers={
                    "vikunja": ProviderConfig(
                        project_id="17",
                        view_id="4",
                        bucket_map={"to-do": "1", "doing": "2", "done": "3"},
                    )
                }
            )
        )
        prov = load_provider("vikunja", config=cfg, _config_dir="/tmp")
        prov._db = db

        class FakeClient:
            async def list_project_tasks(self, project_id: str, expand: list[str] | None = None):
                assert project_id == "17"
                assert expand == ["buckets"]
                return [
                    {
                        "id": 9001,
                        "title": "Remote task",
                        "description": "Imported from Vikunja",
                        "done": False,
                        "buckets": [{"id": 2, "title": "Doing", "project_view_id": 4}],
                    }
                ]

            async def get_task_comments(self, task_id: str):
                assert task_id == "9001"
                return []

        monkeypatch.setattr(prov, "_build_client", lambda: FakeClient())

        delta = await prov.sync(push=False, pull=True)

        assert delta.items_created == 1
        assert delta.statuses_changed == 1

        tasks = await db.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].title == "Remote task"
        assert tasks[0].details == "Imported from Vikunja"
        assert tasks[0].status == TaskStatus.IN_PROGRESS

        cursor = await db.conn.execute(
            "SELECT key, value FROM integration_sync WHERE key LIKE 'vikunja.task.%'"
        )
        rows = await cursor.fetchall()
        assert len(rows) == 1
        mapping = json.loads(rows[0][1])
        assert mapping["remote_task_id"] == 9001
        assert mapping["last_bucket_id"] == 2

    @pytest.mark.asyncio
    async def test_sync_pull_maps_remote_architect_label_to_architect_role(self, monkeypatch, db):
        from cellos.config import CellosConfig, IntegrationsConfig, ProviderConfig
        from cellos.integrations.registry import load_provider

        monkeypatch.setenv("VIKUNJA_BASE_URL", "https://vikunja.example")
        monkeypatch.setenv("VIKUNJA_API_TOKEN", "secret-token")

        cfg = CellosConfig(
            integrations=IntegrationsConfig(
                providers={
                    "vikunja": ProviderConfig(
                        project_id="17",
                        view_id="4",
                        bucket_map={"to-do": "1", "doing": "2", "done": "3"},
                    )
                }
            )
        )
        prov = load_provider("vikunja", config=cfg, _config_dir="/tmp")
        prov._db = db

        class FakeClient:
            async def list_project_tasks(self, project_id: str, expand: list[str] | None = None):
                return [
                    {
                        "id": 9005,
                        "title": "Architect task",
                        "description": "Design the system",
                        "done": False,
                        "labels": [{"id": 1, "title": "architect"}],
                        "buckets": [{"id": 1, "title": "To-Do", "project_view_id": 4}],
                    }
                ]

            async def get_task_comments(self, task_id: str):
                return []

        monkeypatch.setattr(prov, "_build_client", lambda: FakeClient())

        delta = await prov.sync(push=False, pull=True)

        assert delta.items_created == 1
        imported = await db.get_task("vik9005")
        assert imported is not None
        assert imported.role == AgentRole.ARCHITECT

    @pytest.mark.asyncio
    async def test_sync_pull_defaults_unlabeled_remote_task_to_engineer_role(self, monkeypatch, db):
        from cellos.config import CellosConfig, IntegrationsConfig, ProviderConfig
        from cellos.integrations.registry import load_provider

        monkeypatch.setenv("VIKUNJA_BASE_URL", "https://vikunja.example")
        monkeypatch.setenv("VIKUNJA_API_TOKEN", "secret-token")

        cfg = CellosConfig(
            integrations=IntegrationsConfig(
                providers={
                    "vikunja": ProviderConfig(
                        project_id="17",
                        view_id="4",
                        bucket_map={"to-do": "1", "doing": "2", "done": "3"},
                    )
                }
            )
        )
        prov = load_provider("vikunja", config=cfg, _config_dir="/tmp")
        prov._db = db

        class FakeClient:
            async def list_project_tasks(self, project_id: str, expand: list[str] | None = None):
                return [
                    {
                        "id": 9006,
                        "title": "Engineer task",
                        "description": "Implement the system",
                        "done": False,
                        "labels": [{"id": 2, "title": "backend"}],
                        "buckets": [{"id": 2, "title": "Doing", "project_view_id": 4}],
                    }
                ]

            async def get_task_comments(self, task_id: str):
                return []

        monkeypatch.setattr(prov, "_build_client", lambda: FakeClient())

        await prov.sync(push=False, pull=True)

        imported = await db.get_task("vik9006")
        assert imported is not None
        assert imported.role == AgentRole.ENGINEER

    @pytest.mark.asyncio
    async def test_sync_pull_updates_existing_local_task_status_from_remote_bucket(self, monkeypatch, db):
        from cellos.config import CellosConfig, IntegrationsConfig, ProviderConfig
        from cellos.integrations.registry import load_provider

        monkeypatch.setenv("VIKUNJA_BASE_URL", "https://vikunja.example")
        monkeypatch.setenv("VIKUNJA_API_TOKEN", "secret-token")

        task = Task(
            id="task-local-3",
            title="Existing task",
            details="Local copy",
            role=AgentRole.ENGINEER,
            status=TaskStatus.APPROVED,
        )
        await db.create_task(task)
        await db.conn.execute(
            "INSERT INTO integration_sync(key, value) VALUES(?, ?)",
            (
                "vikunja.task.task-local-3",
                json.dumps({"remote_task_id": 9002, "last_synced_status": "approved", "last_bucket_id": 1}),
            ),
        )
        await db.conn.commit()

        cfg = CellosConfig(
            integrations=IntegrationsConfig(
                providers={
                    "vikunja": ProviderConfig(
                        project_id="17",
                        view_id="4",
                        bucket_map={"to-do": "1", "doing": "2", "done": "3"},
                    )
                }
            )
        )
        prov = load_provider("vikunja", config=cfg, _config_dir="/tmp")
        prov._db = db

        class FakeClient:
            async def list_project_tasks(self, project_id: str, expand: list[str] | None = None):
                return [
                    {
                        "id": 9002,
                        "title": "Existing task",
                        "description": "Remote says done",
                        "done": True,
                        "buckets": [{"id": 3, "title": "Done", "project_view_id": 4}],
                    }
                ]

            async def get_task_comments(self, task_id: str):
                return []

        monkeypatch.setattr(prov, "_build_client", lambda: FakeClient())

        delta = await prov.sync(push=False, pull=True)

        assert delta.items_updated == 1
        assert delta.statuses_changed == 1

        updated = await db.get_task("task-local-3")
        assert updated is not None
        assert updated.status == TaskStatus.DONE
        assert updated.details == "Local copy"

    @pytest.mark.asyncio
    async def test_sync_pull_imports_remote_comments_once(self, monkeypatch, db):
        from cellos.config import CellosConfig, IntegrationsConfig, ProviderConfig
        from cellos.integrations.registry import load_provider

        monkeypatch.setenv("VIKUNJA_BASE_URL", "https://vikunja.example")
        monkeypatch.setenv("VIKUNJA_API_TOKEN", "secret-token")

        task = Task(
            id="task-local-4",
            title="Comment target",
            details="Keep me",
            role=AgentRole.ENGINEER,
            status=TaskStatus.APPROVED,
        )
        await db.create_task(task)
        await db.conn.execute(
            "INSERT INTO integration_sync(key, value) VALUES(?, ?)",
            (
                "vikunja.task.task-local-4",
                json.dumps({"remote_task_id": 9003, "last_synced_status": "approved", "last_bucket_id": 1}),
            ),
        )
        await db.conn.commit()

        cfg = CellosConfig(
            integrations=IntegrationsConfig(
                providers={
                    "vikunja": ProviderConfig(
                        project_id="17",
                        view_id="4",
                        bucket_map={"to-do": "1", "doing": "2", "done": "3"},
                    )
                }
            )
        )
        prov = load_provider("vikunja", config=cfg, _config_dir="/tmp")
        prov._db = db

        class FakeClient:
            async def list_project_tasks(self, project_id: str, expand: list[str] | None = None):
                return [
                    {
                        "id": 9003,
                        "title": "Comment target",
                        "description": "Keep me",
                        "done": False,
                        "buckets": [{"id": 1, "title": "To-Do", "project_view_id": 4}],
                    }
                ]

            async def get_task_comments(self, task_id: str):
                return [
                    {"id": 501, "comment": "First remote note", "author": {"username": "james"}},
                    {"id": 502, "comment": "Second remote note", "author": {"username": "alex"}},
                ]

        monkeypatch.setattr(prov, "_build_client", lambda: FakeClient())

        delta1 = await prov.sync(push=False, pull=True)
        delta2 = await prov.sync(push=False, pull=True)

        assert delta1.comments_imported == 2
        assert delta2.comments_imported == 0

        comments = await db.list_comments("task-local-4")
        assert [c.content for c in comments] == ["First remote note", "Second remote note"]
        assert [c.author_id for c in comments] == ["james", "alex"]
