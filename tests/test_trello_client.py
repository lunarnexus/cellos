"""Tests for Trello API client, models, and authentication."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cellos.integrations.trello.client import TrelloError, TrelloClient, BASE_URL
from cellos.integrations.trello.models import (
    Board,
    Card,
    CardAction,
    CardLabel,
    Member,
    PluginDataValue,
    TrelloList,
)


# ── Helpers ───────────────────────────────────────────────────────────

def _make_client(api_key="k1", token="t1"):
    return TrelloClient(api_key=api_key, token=token)


def _mock_session(json_data):
    """Create a mock aiohttp session that returns the given JSON."""
    resp = MagicMock()
    resp.status = 200
    resp.json = AsyncMock(return_value=json_data)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.request = MagicMock(return_value=resp)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session


# ── Model tests ─────────────────────────────────────────────────────

class TestCardModel:
    def test_basic_card(self):
        card = Card(id="c1", name="Test card", idList="l1")
        assert card.id == "c1"
        assert card.labels == []
        assert card.pluginData == {}
        assert not card.closed

    def test_card_with_labels(self):
        card = Card(
            id="c2", name="Labeled", idList="l1",
            labels=[CardLabel(id="lbl1", color="green")]
        )
        assert len(card.labels) == 1
        assert card.labels[0].color == "green"


class TestCardAction:
    def test_comment_action_properties(self):
        action = CardAction(
            id="a1", type="commentCard", date="2026-01-01T00:00:00Z",
            data={"text": "Hello", "card": {"id": "c1"}, "memberCreator": {"id": "m1"}}
        )
        assert action.card_id == "c1"
        assert action.text == "Hello"
        assert action.member_creator_id == "m1"

    def test_action_missing_optional_data(self):
        action = CardAction(id="a2", type="updateCard", date="", data={})
        assert action.card_id is None
        assert action.text == ""


# ── Client auth tests ───────────────────────────────────────────────

class TestTrelloClientAuth:
    def test_auth_params(self):
        client = _make_client()
        params = client._auth_params()
        assert params["key"] == "k1"
        assert params["token"] == "t1"

    def test_empty_creds_omitted(self):
        client = TrelloClient(api_key="", token="")
        params = client._auth_params()
        assert params == {}

    async def test_from_env(self):
        with patch("cellos.integrations.trello.client.get_trello_credentials", return_value=("ek", "et")):
            client = TrelloClient.from_env()
            assert client.api_key == "ek"
            assert client.token == "et"


# ── Client request tests ───────────────────────────────────────────

class TestTrelloClientRequest:
    async def test_get_my_boards(self):
        boards_json = [
            {"id": "b1", "name": "Project Alpha", "closed": False, "url": "https://trello.com/b/b1"}
        ]
        session = _mock_session(boards_json)

        with patch("aiohttp.ClientSession", return_value=session):
            client = _make_client()
            result = await client.get_my_boards()

        assert len(result) == 1
        assert isinstance(result[0], Board)
        assert result[0].name == "Project Alpha"

    async def test_get_me(self):
        me_json = {"id": "m42", "username": "james", "fullName": "James Dev"}
        session = _mock_session(me_json)

        with patch("aiohttp.ClientSession", return_value=session):
            client = _make_client()
            result = await client.get_me()

        assert isinstance(result, Member)
        assert result.username == "james"

    async def test_create_board(self):
        board_json = {"id": "bnew", "name": "My Board", "url": "https://trello.com/b/bnew"}
        resp = MagicMock()
        resp.status = 201
        resp.json = AsyncMock(return_value=board_json)
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=None)

        session = MagicMock()
        session.request = MagicMock(return_value=resp)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=session):
            client = _make_client()
            result = await client.create_board("My Board")

        assert isinstance(result, Board)
        assert result.id == "bnew"

    async def test_create_card(self):
        card_json = {
            "id": "cnew", "name": "New Card", "desc": "", "idList": "l1",
            "labels": [], "pluginData": {}, "closed": False,
        }
        resp = MagicMock()
        resp.status = 200
        resp.json = AsyncMock(return_value=card_json)
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=None)

        session = MagicMock()
        session.request = MagicMock(return_value=resp)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=session):
            client = _make_client()
            result = await client.create_card(id_list="l1", name="New Card")

        assert isinstance(result, Card)
        assert result.id == "cnew"
        assert result.name == "New Card"

    async def test_move_card_to_list(self):
        card_json = {"id": "c1", "name": "Moved", "idList": "l2"}
        session = _mock_session(card_json)

        with patch("aiohttp.ClientSession", return_value=session):
            client = _make_client()
            result = await client.move_card_to_list("c1", "l2")

        assert isinstance(result, Card)
        assert result.idList == "l2"

    async def test_get_cards_from_list(self):
        cards_json = [
            {"id": "ca", "name": "Card A", "idList": "l1"},
            {"id": "cb", "name": "Card B", "idList": "l1"},
        ]
        session = _mock_session(cards_json)

        with patch("aiohttp.ClientSession", return_value=session):
            client = _make_client()
            result = await client.get_cards_from_list("l1")

        assert len(result) == 2
        for c in result:
            assert isinstance(c, Card)

    async def test_get_card_actions(self):
        actions_json = [
            {"id": "a1", "type": "commentCard", "date": "2026-01-01T00:00:00Z", "data": {"text": "Hi"}},
            {"id": "a2", "type": "updateCard", "date": "2026-01-01T01:00:00Z", "data": {}},
        ]
        session = _mock_session(actions_json)

        with patch("aiohttp.ClientSession", return_value=session):
            client = _make_client()
            result = await client.get_card_actions("c1")

        assert len(result) == 2
        assert isinstance(result[0], CardAction)
        assert result[0].text == "Hi"


# ── Rate limiting tests ────────────────────────────────────────────

class TestTrelloClientRateLimit:
    async def test_retry_on_429(self):
        """On 429, client retries with exponential backoff."""
        cards_json = [{"id": "c1", "name": "After retry", "idList": "l1"}]

        statuses_iter = iter([429, 200])

        def mock_response(*args, **kwargs):
            status = next(statuses_iter)
            resp = MagicMock()
            resp.status = status
            resp.json = AsyncMock(return_value=cards_json)
            resp.reason = "Rate limited" if status == 429 else ""
            resp.__aenter__ = AsyncMock(return_value=resp)
            resp.__aexit__ = AsyncMock(return_value=None)
            return resp

        session = MagicMock()
        session.request = mock_response
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=session):
            client = _make_client()
            result = await client.get_cards_from_list("l1")

        assert len(result) == 1
        assert result[0].name == "After retry"


# ── Error handling tests ───────────────────────────────────────────

class TestTrelloClientErrors:
    async def test_trello_error_on_404(self):
        resp = MagicMock()
        resp.status = 404
        resp.json = AsyncMock(return_value={"message": "Board not found"})
        resp.reason = "Not Found"
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=None)

        session = MagicMock()
        session.request = MagicMock(return_value=resp)
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=session):
            client = _make_client()
            with pytest.raises(TrelloError, match="404"):
                await client.get_all_cards_on_board("nonexistent")


# ── Parse card tests ──────────────────────────────────────────────

class TestParseCard:
    def test_parse_card_with_plugin_data(self):
        raw = {
            "id": "c1", "name": "Test", "idList": "l1",
            "labels": [{"id": "lbl", "color": "blue"}],
            "pluginData": {"powerup-123": {"task_id": "abc456"}},
        }
        client = _make_client()
        card = client._parse_card(raw)

        assert card.id == "c1"
        assert len(card.labels) == 1
        assert "powerup-123" in card.pluginData
        assert card.pluginData["powerup-123"].value.get("task_id") == "abc456"

    def test_parse_card_minimal(self):
        raw = {"id": "c2", "name": "Minimal", "idList": "l1"}
        client = _make_client()
        card = client._parse_card(raw)

        assert card.desc is None
        assert card.labels == []
        assert card.pluginData == {}
