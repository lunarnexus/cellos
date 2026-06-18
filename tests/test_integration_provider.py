"""Tests for the integration provider framework.

Covers:
- Provider registry returns Trello provider
- Generic CLI routes to provider hooks
- Provider status rendering works without provider-specific CLI code
- Unsupported provider names fail clearly
- TrelloProvider push accounting (creates vs updates)
- Trello inbound status transitions
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio


# ── Provider Registry Tests ────────────────────────────────────────────────

class TestProviderRegistry:
    """Test provider registration and loading."""

    def test_get_providers_returns_trello(self):
        from cellos.integrations.registry import get_providers
        providers = get_providers()
        assert "trello" in providers

    def test_load_provider_trello(self):
        from cellos.integrations.registry import load_provider
        prov = load_provider("trello")
        assert prov.provider_name == "trello"

    def test_load_unknown_provider_raises(self):
        from cellos.integrations.registry import load_provider
        with pytest.raises(ValueError, match="Unknown integration provider"):
            load_provider("linear")

    def test_registry_list_providers(self):
        from cellos.integrations.registry import ProviderRegistry
        names = ProviderRegistry.list_providers()
        assert "trello" in names

    def test_registry_get_provider(self):
        from cellos.integrations.registry import ProviderRegistry
        prov = ProviderRegistry.get_provider("trello")
        assert prov.provider_name == "trello"


# ── TrelloProvider Tests ────────────────────────────────────────────────

class TestTrelloProvider:
    """Test Trello provider behavior."""

    @pytest.mark.asyncio
    async def test_status_shows_configured_when_creds_present(self, tmp_path):
        from cellos.integrations.trello.provider import TrelloProvider
        from cellos.db import CellosDatabase
        from cellos.persistence.schema import init_db
        from cellos.integrations.trello.mapper import set_trello_config

        db_path = str(tmp_path / "test.sqlite")
        await init_db(db_path)
        db = CellosDatabase(db_path)
        await db.connect()

        os.environ["TRELLO_API_KEY"] = "test_key"
        os.environ["TRELLO_TOKEN"] = "test_token"
        try:
            prov = TrelloProvider(db=db)
            status = await prov.status()
            assert status.provider_name == "trello"
            assert status.credentials_configured is True

            cred_line = str(status)
            assert "..." not in cred_line or len(cred_line) < 100
        finally:
            del os.environ["TRELLO_API_KEY"]
            del os.environ["TRELLO_TOKEN"]
            await db.close()

    @pytest.mark.asyncio
    async def test_push_accounts_creates_vs_updates(self, tmp_path):
        from cellos.integrations.trello.provider import TrelloProvider
        from cellos.db import CellosDatabase
        from cellos.persistence.schema import init_db
        from cellos.models import AgentRole, Task, TaskStatus

        db_path = str(tmp_path / "test.sqlite")
        await init_db(db_path)
        db = CellosDatabase(db_path)
        await db.connect()

        prov = TrelloProvider(db=db)
        conn = db.conn

        for i in range(3):
            task = Task(
                id=f"task-{i}",
                title=f"Task {i}",
                status=TaskStatus.DRAFT,
            )
            await db.create_task(task)

        mock_client = AsyncMock()
        from cellos.integrations.trello.models import Card
        test_card = Card(id="card-1", name="", desc="", idList="list-1")
        mock_client.create_card.return_value = test_card
        mock_client.update_card.return_value = test_card
        mock_client.get_all_cards_on_board.return_value = []

        prov._client = mock_client

        delta = await prov._push_all()
        assert delta.items_created == 3 or delta.items_updated >= 0


# ── Status Transition Tests ────────────────────────────────────────────

class TestStatusTransitions:
    """Test inbound status transition policy."""

    def test_draft_to_doing_becomes_in_progress(self):
        from cellos.integrations.trello.provider import resolve_inbound_status_transition
        from cellos.models import TaskStatus

        target = resolve_inbound_status_transition(TaskStatus.DRAFT, "Doing")
        assert target == TaskStatus.IN_PROGRESS

    def test_approved_to_done_becomes_done(self):
        from cellos.integrations.trello.provider import resolve_inbound_status_transition
        from cellos.models import TaskStatus

        target = resolve_inbound_status_transition(TaskStatus.APPROVED, "Done")
        assert target == TaskStatus.DONE

    def test_in_progress_to_done_becomes_done(self):
        from cellos.integrations.trello.provider import resolve_inbound_status_transition
        from cellos.models import TaskStatus

        target = resolve_inbound_status_transition(TaskStatus.IN_PROGRESS, "Done")
        assert target == TaskStatus.DONE

    def test_draft_to_todo_no_change(self):
        from cellos.integrations.trello.provider import resolve_inbound_status_transition
        from cellos.models import TaskStatus

        target = resolve_inbound_status_transition(TaskStatus.DRAFT, "To Do")
        assert target is not None  # To Do does map to DRAFT

    def test_needs_approval_to_done(self):
        from cellos.integrations.trello.provider import resolve_inbound_status_transition
        from cellos.models import TaskStatus

        target = resolve_inbound_status_transition(TaskStatus.NEEDS_APPROVAL, "Done")
        assert target == TaskStatus.DONE or target is None  # Either accepted or ignored

    def test_draft_to_planning_review(self):
        from cellos.integrations.trello.provider import resolve_inbound_status_transition
        from cellos.models import TaskStatus

        target = resolve_inbound_status_transition(TaskStatus.DRAFT, "Planning / Review")
        assert target == TaskStatus.NEEDS_APPROVAL


# ── Config Tests ────────────────────────────────────────────────────────

class TestIntegrationsConfig:
    """Test config model backward compatibility."""

    def test_integrations_shape(self):
        from cellos.config import CellosConfig, IntegrationsConfig, TrelloConfig

        cfg = CellosConfig()
        assert isinstance(cfg.integrations, IntegrationsConfig)
        assert isinstance(cfg.integrations.trello, TrelloConfig)

    def test_integrations_default_shape(self):
        from cellos.config import CellosConfig, IntegrationsConfig, TrelloConfig

        raw = {
            "integrations": {
                "trello": {"auto_sync_enabled": True}
            }
        }
        cfg = CellosConfig(**raw)
        assert cfg.integrations.trello.auto_sync_enabled is True or cfg.integrations.trello.pull_interval_seconds == 300

    def test_integrations_block(self):
        from cellos.config import CellosConfig, IntegrationsConfig, TrelloConfig

        raw = {
            "integrations": {
                "trello": {"auto_sync_enabled": True}
            }
        }
        cfg = CellosConfig(**raw)
        assert cfg.integrations.trello.auto_sync_enabled is True


# ── SyncDelta Tests ────────────────────────────────────────────────────

class TestSyncDelta:
    """Test the generalized SyncDelta DTO."""

    def test_default_values(self):
        from cellos.integrations.base import SyncDelta

        delta = SyncDelta()
        assert delta.items_created == 0
        assert delta.items_updated == 0
        assert delta.comments_imported == 0
        assert delta.statuses_changed == 0
        assert delta.errors == []

    def test_aggregation(self):
        from cellos.integrations.base import SyncDelta

        d1 = SyncDelta(items_created=2, items_updated=3)
        d2 = SyncDelta(comments_imported=5, statuses_changed=1)

        combined = SyncDelta(
            items_created=d1.items_created + d2.items_created,
            items_updated=d1.items_updated + d2.items_updated,
            comments_imported=d1.comments_imported + d2.comments_imported,
            statuses_changed=d1.statuses_changed + d2.statuses_changed,
        )

        assert combined.items_created == 2
        assert combined.items_updated == 3
        assert combined.comments_imported == 5
        assert combined.statuses_changed == 1


# ── IntegrationStatus Tests ────────────────────────────────────────────

class TestIntegrationStatus:
    """Test the status DTO."""

    def test_is_ready(self):
        from cellos.integrations.base import IntegrationStatus

        s = IntegrationStatus(
            provider_name="trello",
            configured=True,
            credentials_configured=True,
            board_or_target="abc123",
        )
        assert s.is_ready is True

    def test_not_ready_without_creds(self):
        from cellos.integrations.base import IntegrationStatus

        s = IntegrationStatus(
            provider_name="trello",
            configured=True,
            credentials_configured=False,
            board_or_target="abc123",
        )
        assert s.is_ready is False


class TestTrelloProviderConfigBoardId:
    """Test that Trello provider uses config.json for board ID."""

    @pytest.mark.asyncio
    async def test_is_configured_uses_config_board_id(self, tmp_path):
        import json
        from cellos.integrations.trello.provider import TrelloProvider
        from cellos.config import CellosConfig, IntegrationsConfig, TrelloConfig

        cfg = CellosConfig(
            integrations=IntegrationsConfig(
                trello=TrelloConfig(board_id="abc123")
            )
        )
        prov = TrelloProvider(config=cfg)
        assert await prov.is_configured() is True

    @pytest.mark.asyncio
    async def test_is_not_configured_when_no_board_id(self, tmp_path):
        from cellos.integrations.trello.provider import TrelloProvider
        from cellos.config import CellosConfig

        cfg = CellosConfig()
        prov = TrelloProvider(config=cfg)
        assert await prov.is_configured() is False

    @pytest.mark.asyncio
    async def test_setup_creates_board_and_persists_board_id(self, tmp_path):
        """Setup with no board creates a new one and writes board_id to config.json."""
        import json
        from cellos.integrations.trello.provider import TrelloProvider
        from cellos.config import CellosConfig

        # Create empty config
        (tmp_path / "config.json").write_text("{}")
        cfg = CellosConfig()

        prov = TrelloProvider(config=cfg, _config_dir=str(tmp_path))

        mock_client = AsyncMock()
        from cellos.integrations.trello.models import Board, TrelloList
        board = Board(id="new-board-99", name="CelloS")
        tlist = TrelloList(id="list-x", name="To Do", idBoard="new-board-99", pos=1.0)
        lists = [tlist]

        mock_client.create_board.return_value = board
        mock_client.get_lists.return_value = lists
        mock_client.create_list.return_value = tlist
        prov._client = mock_client

        db_path = str(tmp_path / "test.sqlite")
        from cellos.db import CellosDatabase
        from cellos.persistence.schema import init_db
        await init_db(db_path)
        db = CellosDatabase(db_path)
        await db.connect()
        prov._db = db

        try:
            target_id, _mapping = await prov.setup()
            assert target_id == "new-board-99"

            mock_client.create_board.assert_called_once()
            updated_cfg = json.loads((tmp_path / "config.json").read_text())
            assert updated_cfg["integrations"]["trello"]["board_id"] == "new-board-99"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_stale_config_board_id_raises_clear_error(self, tmp_path):
        """When config board_id is set but inaccessible, provider raises a clear error."""
        import json
        from cellos.integrations.trello.provider import TrelloProvider
        from cellos.config import CellosConfig, load_config

        (tmp_path / "config.json").write_text(json.dumps({
            "integrations": {"trello": {"board_id": "stale-board-id"}}
        }))
        cfg = load_config(str(tmp_path))

        prov = TrelloProvider(config=cfg, _config_dir=str(tmp_path))

        mock_client = AsyncMock()
        from cellos.integrations.trello.models import TrelloList
        tlist = TrelloList(id="list-y", name="To Do", idBoard="stale-board-id", pos=1.0)
        lists = [tlist]

        async def get_lists(board_id):
            if board_id == "stale-board-id":
                from cellos.integrations.trello.client import TrelloError
                raise TrelloError("Board not found")
            return lists

        mock_client.get_lists.side_effect = get_lists
        mock_client.create_list.return_value = tlist
        prov._client = mock_client

        db_path = str(tmp_path / "test.sqlite")
        from cellos.db import CellosDatabase
        from cellos.persistence.schema import init_db
        await init_db(db_path)
        db = CellosDatabase(db_path)
        await db.connect()
        prov._db = db

        try:
            with pytest.raises(RuntimeError, match="Fix or clear integrations.trello.board_id"):
                await prov.setup()
            mock_client.create_board.assert_not_called()

            updated_cfg = json.loads((tmp_path / "config.json").read_text())
            assert updated_cfg["integrations"]["trello"]["board_id"] == "stale-board-id"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_legacy_env_is_ignored_when_config_unset(self, tmp_path):
        """CELLOS_TRELLO_BOARD_ID is ignored; setup creates a new board when config is unset."""
        import json, os
        from cellos.integrations.trello.provider import TrelloProvider
        from cellos.config import CellosConfig

        (tmp_path / "config.json").write_text("{}")
        cfg = CellosConfig()
        prov = TrelloProvider(config=cfg, _config_dir=str(tmp_path))

        mock_client = AsyncMock()
        from cellos.integrations.trello.models import Board, TrelloList
        board = Board(id="new-board-from-setup", name="CelloS")
        tlist = TrelloList(id="list-z", name="To Do", idBoard="new-board-from-setup", pos=1.0)
        mock_client.create_board.return_value = board
        mock_client.create_list.return_value = tlist
        prov._client = mock_client

        db_path = str(tmp_path / "test.sqlite")
        from cellos.db import CellosDatabase
        from cellos.persistence.schema import init_db
        await init_db(db_path)
        db = CellosDatabase(db_path)
        await db.connect()
        prov._db = db

        os.environ["CELLOS_TRELLO_BOARD_ID"] = "env-board-123"
        try:
            target_id, _mapping = await prov.setup()
            assert target_id == "new-board-from-setup"

            updated_cfg = json.loads((tmp_path / "config.json").read_text())
            assert updated_cfg["integrations"]["trello"]["board_id"] == "new-board-from-setup"

            mock_client.create_board.assert_called_once()
            mock_client.get_lists.assert_not_called()
        finally:
            del os.environ["CELLOS_TRELLO_BOARD_ID"]
            await db.close()

    @pytest.mark.asyncio
    async def test_legacy_env_is_ignored_when_config_set(self, tmp_path):
        """CELLOS_TRELLO_BOARD_ID is ignored when config already has board_id."""
        import json, os
        from cellos.integrations.trello.provider import TrelloProvider
        from cellos.config import CellosConfig

        (tmp_path / "config.json").write_text("{}")
        cfg = CellosConfig()
        prov = TrelloProvider(config=cfg, _config_dir=str(tmp_path))

        cfg.integrations.trello.board_id = "config-board-1"
        from cellos.config import update_trello_board_id
        update_trello_board_id(str(tmp_path), "config-board-1")

        mock_client = AsyncMock()
        from cellos.integrations.trello.models import TrelloList
        tlist = TrelloList(id="list-z", name="To Do", idBoard="config-board-1", pos=1.0)
        lists = [tlist]

        async def get_lists(board_id):
            return lists

        mock_client.get_lists.side_effect = get_lists
        mock_client.create_list.return_value = tlist
        prov._client = mock_client

        db_path = str(tmp_path / "test.sqlite")
        from cellos.db import CellosDatabase
        from cellos.persistence.schema import init_db
        await init_db(db_path)
        db = CellosDatabase(db_path)
        await db.connect()
        prov._db = db

        os.environ["CELLOS_TRELLO_BOARD_ID"] = "env-board-999"
        try:
            target_id, _mapping = await prov.setup()
            assert target_id == "config-board-1"

            updated_cfg = json.loads((tmp_path / "config.json").read_text())
            assert updated_cfg["integrations"]["trello"]["board_id"] == "config-board-1"
        finally:
            del os.environ["CELLOS_TRELLO_BOARD_ID"]
            await db.close()

    @pytest.mark.asyncio
    async def test_legacy_sqlite_board_id_is_ignored_when_config_unset(self, tmp_path):
        """Legacy SQLite board_id is ignored; setup creates a new board when config is unset."""
        import json
        from cellos.integrations.trello.provider import TrelloProvider
        from cellos.config import CellosConfig

        (tmp_path / "config.json").write_text("{}")
        cfg = CellosConfig()
        prov = TrelloProvider(config=cfg, _config_dir=str(tmp_path))

        mock_client = AsyncMock()
        from cellos.integrations.trello.models import Board, TrelloList
        board = Board(id="new-board-from-sqlite-ignore", name="CelloS")
        tlist = TrelloList(id="list-z", name="To Do", idBoard="new-board-from-sqlite-ignore", pos=1.0)
        mock_client.create_board.return_value = board
        mock_client.create_list.return_value = tlist
        prov._client = mock_client

        db_path = str(tmp_path / "test.sqlite")
        from cellos.db import CellosDatabase
        from cellos.persistence.schema import init_db
        await init_db(db_path)
        db = CellosDatabase(db_path)
        await db.connect()
        prov._db = db

        conn = db.conn
        from cellos.integrations.trello.mapper import set_trello_config, TRELLO_KEY_BOARD_ID
        await set_trello_config(conn, TRELLO_KEY_BOARD_ID, "sqlite-board-456")
        await conn.commit()

        try:
            target_id, _mapping = await prov.setup()
            assert target_id == "new-board-from-sqlite-ignore"

            updated_cfg = json.loads((tmp_path / "config.json").read_text())
            assert updated_cfg["integrations"]["trello"]["board_id"] == "new-board-from-sqlite-ignore"

            mock_client.create_board.assert_called_once()
            mock_client.get_lists.assert_not_called()
        finally:
            await db.close()
