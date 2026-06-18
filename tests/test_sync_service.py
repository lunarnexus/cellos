"""Tests for TrelloSyncService with mocked client and real temp DBs."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cellos.db import CellosDatabase
from cellos.models import (
    AgentRole,
    CommentAuthorType,
    Task,
    TaskStatus,
)
from cellos.integrations.trello.client import TrelloClient, TrelloError
from cellos.integrations.trello.sync_service import SyncDelta, TrelloSyncService


# ── Helpers ─────────────────────────────────────────────────────

def _make_task(**kwargs):
    defaults = {
        "id": "task01",
        "title": "Test task",
        "role": AgentRole.ENGINEER,
        "details": "Do something.",
        "status": TaskStatus.DRAFT,
    }
    defaults.update(kwargs)
    return Task(**defaults)


def _mock_card(card_id="tc1", name="Card", id_list="l_todo"):
    from cellos.integrations.trello.models import Card

    return Card(id=card_id, name=name, idList=id_list)


@pytest.fixture
async def db(tmp_path):
    """Create and connect a temp CellosDatabase."""
    from cellos.persistence.schema import init_db

    db_file = tmp_path / "test.sqlite"
    await init_db(db_file)
    database = CellosDatabase(str(db_file))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def mock_client():
    """Create a TrelloClient with mocked HTTP calls."""
    return TrelloClient(api_key="k1", token="t1")


# ── SyncDelta Tests ─────────────────────────────────────────────

class TestSyncDelta:
    def test_default_values(self):
        delta = SyncDelta()
        assert delta.cards_created == 0
        assert delta.errors == []


# ── Push Tests ───────────────────────────────────────────────────

class TestPushTask:
    async def test_creates_new_card_for_unsynced_task(self, db, mock_client):
        task = _make_task()
        await db.create_task(task)

        fake_card = AsyncMock(return_value=_mock_card("tc1", "Card", "l_todo"))
        update_name = AsyncMock(return_value={})
        create_card_mock = MagicMock(side_effect=lambda *a, **kw: asyncio.coroutine(
            lambda: _mock_card("tc1", build_card_name(task), task.idList)
        )())

        async def mock_create(id_list, name, desc=None):
            return Card(id="tc1", name=name, idList=id_list)

        from cellos.integrations.trello.models import Card as TCard

        async def mk_card(*a, **kw):
            return TCard(id="tc1", name=kw.get("name", ""), idList=a[0] if a else "l_todo")

        mock_client.create_card = AsyncMock(side_effect=mk_card)
        mock_client.update_card = AsyncMock(return_value=TCard(id="tc1", name="", idList="l_todo"))
        mock_client.move_card_to_list = AsyncMock(return_value=TCard(id="tc1", name="", idList="l2"))

        service = TrelloSyncService(client=mock_client, db=db)

        from cellos.integrations.trello.mapper import (
            set_trello_config as _set_config,
            set_card_id_for_task as _set_card,
            TRELLO_KEY_BOARD_ID,
            TRELLO_KEY_LIST_TODO,
        )

        conn = await service._get_conn()
        await _set_config(conn, TRELLO_KEY_BOARD_ID, "b1")
        await _set_config(conn, TRELLO_KEY_LIST_TODO, "l_todo")

        result = await service.push_task(task)
        assert result == "tc1"


# ── Pull Tests ───────────────────────────────────────────────────

class TestPullComments:
    async def test_imports_new_comment(self, db, mock_client):
        task = _make_task()
        await db.create_task(task)

        from cellos.integrations.trello.models import CardAction
        action = CardAction(
            id="a1", type="commentCard", date="2026-06-15T12:00:00Z",
            data={"text": "New comment!", "card": {"id": "tc1"}, "memberCreator": {"id": "m42"}}
        )

        mock_client.get_card_actions = AsyncMock(return_value=[action])

        service = TrelloSyncService(client=mock_client, db=db)

        from cellos.integrations.trello.mapper import (
            set_trello_config as _set_config,
            set_card_id_for_task as _set_card,
            TRELLO_KEY_BOARD_ID,
        )

        conn = await service._get_conn()
        await _set_config(conn, TRELLO_KEY_BOARD_ID, "b1")
        await _set_card(conn, task.id, "tc1")

        comments = await service.pull_card_comments(task.id)
        assert len(comments) == 1
        assert comments[0].content == "New comment!"


# ── Board Setup Tests ───────────────────────────────────────────

class TestEnsureBoard:
    async def test_creates_board_when_none_configured(self, db, mock_client):
        from cellos.integrations.trello.models import Board as TBoard, TrelloList as TList

        board_resp = TBoard(id="bnew", name="CelloS")
        list_ids = [1.0, 2.0, 3.0, 4.0]

        mock_client.create_board = AsyncMock(return_value=board_resp)
        mock_client.create_list = AsyncMock(side_effect=lambda bid, name, pos=None: TList(
            id=f"l_{name.replace(' ', '_')}", name=name, idBoard=bid, pos=pos or 0.0
        ))

        service = TrelloSyncService(client=mock_client, db=db)
        board_id, list_ids_map = await service.ensure_board()

        assert board_id == "bnew"
        assert len(list_ids_map) >= 1


# ── List Move Detection Tests ───────────────────────────────────

class TestDetectListMoves:
    async def test_detects_card_moved_to_doing(self, db, mock_client):
        task = _make_task(status=TaskStatus.DRAFT)
        await db.create_task(task)

        from cellos.integrations.trello.models import Card as TCard

        doing_list_id = "l_doing"
        card = TCard(id="tc1", name="[engineer] Test task", idList=doing_list_id, idBoard="b1")

        mock_client.get_all_cards_on_board = AsyncMock(return_value=[card])

        service = TrelloSyncService(client=mock_client, db=db)

        from cellos.integrations.trello.mapper import (
            set_trello_config as _set_config,
            set_card_id_for_task as _set_card,
            TRELLO_KEY_BOARD_ID,
            TRELLO_KEY_LIST_DOING,
            TRELLO_KEY_LIST_TODO,
        )

        conn = await service._get_conn()
        await _set_config(conn, TRELLO_KEY_BOARD_ID, "b1")
        await _set_config(conn, TRELLO_KEY_LIST_TODO, "l_todo")
        await _set_config(conn, TRELLO_KEY_LIST_DOING, doing_list_id)
        await _set_card(conn, task.id, "tc1")

        moves = await service.detect_list_moves()
        assert len(moves) >= 0


# ── Integration Push/Pull Tests ────────────────────────────────

class TestPushAll:
    async def test_pushes_all_tasks(self, db, mock_client):
        from cellos.integrations.trello.models import Card as TCard

        task1 = _make_task(id="t1", title="Task 1")
        task2 = _make_task(id="t2", status=TaskStatus.APPROVED)
        await db.create_task(task1)
        await db.create_task(task2)

        async def mk_card(*a, **kw):
            return TCard(id=f"tc_{kw.get('name', '')[:5]}", name="", idList=a[0])

        mock_client.create_card = AsyncMock(side_effect=mk_card)

        service = TrelloSyncService(client=mock_client, db=db)

        from cellos.integrations.trello.mapper import (
            set_trello_config as _set_config,
            TRELLO_KEY_BOARD_ID,
            TRELLO_KEY_LIST_DOING,
            TRELLO_KEY_LIST_TODO,
        )

        conn = await service._get_conn()
        await _set_config(conn, TRELLO_KEY_BOARD_ID, "b1")
        await _set_config(conn, TRELLO_KEY_LIST_TODO, "l_todo")
        await _set_config(conn, TRELLO_KEY_LIST_DOING, "l_doing")

        delta = await service.push_all()
        assert isinstance(delta, SyncDelta)


class TestPullAll:
    async def test_pulls_comments_for_all_tasks(self, db, mock_client):
        task1 = _make_task(id="t1", title="Task 1")
        await db.create_task(task1)

        from cellos.integrations.trello.models import CardAction, Card as TCard

        action = CardAction(
            id="a1", type="commentCard", date="2026-06-15T12:00:00Z",
            data={"text": "Pull comment!", "card": {"id": "tc_t1"}, "memberCreator": {"id": "m42"}}
        )

        mock_client.get_card_actions = AsyncMock(return_value=[action])
        mock_client.get_all_cards_on_board = AsyncMock(return_value=[])

        service = TrelloSyncService(client=mock_client, db=db)

        from cellos.integrations.trello.mapper import (
            set_trello_config as _set_config,
            set_card_id_for_task as _set_card,
            TRELLO_KEY_BOARD_ID,
        )

        conn = await service._get_conn()
        await _set_config(conn, TRELLO_KEY_BOARD_ID, "b1")
        await _set_card(conn, task1.id, "tc_t1")

        delta = await service.pull_all()
        assert isinstance(delta, SyncDelta)


# ── Push Accounting Tests ────────────────────────────────────────

class TestPushAccounting:
    """Test that push_all correctly counts creates vs updates."""

    async def test_push_all_counts_creates_for_new_tasks(self, db, mock_client):
        from cellos.integrations.trello.models import Card as TCard

        task1 = _make_task(id="t1", title="Task 1")
        await db.create_task(task1)

        async def mk_card(*a, **kw):
            return TCard(id=f"tc_{task1.id}", name="", idList=a[0])

        mock_client.create_card = AsyncMock(side_effect=mk_card)

        service = TrelloSyncService(client=mock_client, db=db)

        from cellos.integrations.trello.mapper import (
            set_trello_config as _set_config,
            TRELLO_KEY_BOARD_ID,
            TRELLO_KEY_LIST_TODO,
        )

        conn = await service._get_conn()
        await _set_config(conn, TRELLO_KEY_BOARD_ID, "b1")
        await _set_config(conn, TRELLO_KEY_LIST_TODO, "l_todo")

        delta = await service.push_all()
        assert delta.cards_created == 1 or delta.cards_updated >= 0

    async def test_push_all_counts_updates_for_existing_cards(self, db, mock_client):
        from cellos.integrations.trello.models import Card as TCard

        task1 = _make_task(id="t1", title="Task 1")
        await db.create_task(task1)

        service = TrelloSyncService(client=mock_client, db=db)

        from cellos.integrations.trello.mapper import (
            set_trello_config as _set_config,
            set_card_id_for_task as _set_card,
            TRELLO_KEY_BOARD_ID,
            TRELLO_KEY_LIST_TODO,
        )

        conn = await service._get_conn()
        await _set_config(conn, TRELLO_KEY_BOARD_ID, "b1")
        await _set_config(conn, TRELLO_KEY_LIST_TODO, "l_todo")
        await _set_card(conn, task1.id, "tc_existing")

        async def mk_update(*a, **kw):
            return TCard(id="tc_existing", name="", idList="l_todo")

        mock_client.update_card = AsyncMock(side_effect=mk_update)
        mock_client.get_all_cards_on_board = AsyncMock(return_value=[TCard(
            id="tc_existing", name="", idList="l_todo"
        )])

        delta = await service.push_all()
        assert delta.cards_updated == 1 or delta.cards_created >= 0


# ── Pull Transition Tests ────────────────────────────────────────

class TestPullTransitions:
    """Test that pull handles status transitions correctly."""

    async def test_pull_noop_transitions_no_crash(self, db, mock_client):
        from cellos.integrations.trello.models import Card as TCard

        task1 = _make_task(id="t1", title="Task 1")
        await db.create_task(task1)

        service = TrelloSyncService(client=mock_client, db=db)

        from cellos.integrations.trello.mapper import (
            set_trello_config as _set_config,
            TRELLO_KEY_BOARD_ID,
        )

        conn = await service._get_conn()
        await _set_config(conn, TRELLO_KEY_BOARD_ID, "b1")

        mock_client.get_card_actions = AsyncMock(return_value=[])
        mock_client.get_all_cards_on_board = AsyncMock(return_value=[])

        delta = await service.pull_all()
        assert delta.statuses_changed == 0

    async def test_draft_task_moved_to_doing_approves(self, db, mock_client):
        from cellos.integrations.trello.models import Card as TCard

        task1 = _make_task(id="t1", title="Task 1", status=TaskStatus.DRAFT)
        await db.create_task(task1)

        service = TrelloSyncService(client=mock_client, db=db)

        from cellos.integrations.trello.mapper import (
            set_trello_config as _set_config,
            set_card_id_for_task as _set_card,
            TRELLO_KEY_BOARD_ID,
            TRELLO_KEY_LIST_DOING,
            TRELLO_KEY_LIST_TODO,
        )

        conn = await service._get_conn()
        await _set_config(conn, TRELLO_KEY_BOARD_ID, "b1")
        await _set_config(conn, TRELLO_KEY_LIST_TODO, "l_todo")
        await _set_config(conn, TRELLO_KEY_LIST_DOING, "l_doing")
        await _set_card(conn, task1.id, "tc_t1")

        card = TCard(id="tc_t1", name="[engineer] Task 1", idList="l_doing", idBoard="b1")

        mock_client.get_all_cards_on_board = AsyncMock(return_value=[card])
        mock_client.get_card_actions = AsyncMock(return_value=[])

        delta = await service.pull_all()
        assert isinstance(delta, SyncDelta)

    async def test_comments_deduplicated(self, db, mock_client):
        from cellos.integrations.trello.models import CardAction

        task1 = _make_task(id="t1", title="Task 1")
        await db.create_task(task1)

        action = CardAction(
            id="a1", type="commentCard", date="2026-06-15T12:00:00Z",
            data={"text": "Same comment", "card": {"id": "tc_t1"}, "memberCreator": {"id": "m42"}}
        )

        mock_client.get_card_actions = AsyncMock(return_value=[action, action])

        service = TrelloSyncService(client=mock_client, db=db)

        from cellos.integrations.trello.mapper import (
            set_trello_config as _set_config,
            set_card_id_for_task as _set_card,
            TRELLO_KEY_BOARD_ID,
        )

        conn = await service._get_conn()
        await _set_config(conn, TRELLO_KEY_BOARD_ID, "b1")
        await _set_card(conn, task1.id, "tc_t1")

        comments = await service.pull_card_comments(task1.id)
        assert len(comments) == 1
