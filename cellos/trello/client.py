"""Async Trello REST API client with authentication, rate limiting, and retry."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import aiohttp

from cellos.env import get_trello_credentials
from cellos.trello.models import (
    Board,
    Card,
    CardAction,
    CardLabel,
    Member,
    PluginDataValue,
    TrelloList,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://api.trello.com/1"


class TrelloError(Exception):
    """Raised when a Trello API request fails."""


class TrelloClient:
    """Async HTTP client for the Trello REST API.

    Handles authentication (key+token query params), rate limiting (429 retry
    with exponential backoff), and all required endpoints for CelloS sync.
    """

    def __init__(self, api_key: Optional[str] = None, token: Optional[str] = None):
        self.api_key = api_key or ""
        self.token = token or ""

    @classmethod
    def from_env(cls) -> TrelloClient:
        """Create client using credentials from environment variables."""
        api_key, token = get_trello_credentials()
        return cls(api_key=api_key, token=token)

    def _auth_params(self) -> dict[str, str]:
        """Build authentication query parameters for every request."""
        params: dict[str, str] = {}
        if self.api_key:
            params["key"] = self.api_key
        if self.token:
            params["token"] = self.token
        return params

    async def _request(
        self, method: str, path: str, params: Optional[dict[str, str]] = None, json_body: Optional[dict] = None
    ) -> dict | list[dict]:
        """Execute a Trello API request with rate limit retry.

        Args:
            method: HTTP method (GET, POST, PUT).
            path: API path relative to /1/ (e.g., "members/me").
            params: Query parameters (merged with auth params).
            json_body: JSON body for POST/PUT requests.

        Returns:
            Parsed JSON response (dict or list of dicts).

        Raises:
            TrelloError: On HTTP errors, timeouts, or too many retries.
        """
        url = f"{BASE_URL}/{path}"
        merged_params = {**self._auth_params(), **(params or {})}

        delays = [1, 2, 4]
        last_exc: Exception | None = None
        import asyncio as _asyncio

        for attempt in range(len(delays) + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    kwargs = {"json": json_body} if json_body else {}
                    async with session.request(
                        method, url, params=merged_params, **kwargs
                    ) as resp:
                        if resp.status == 429 and attempt < len(delays):
                            wait = delays[attempt]
                            logger.info("Trello rate limited, retrying in %ds", wait)
                            await _asyncio.sleep(wait)
                            continue

                        try:
                            body = await resp.json()
                        except (json.JSONDecodeError, ValueError):
                            body_raw = await resp.text()
                            body = {"message": body_raw[:200] if body_raw else ""}

                        if resp.status == 200 or resp.status == 201:
                            return body

                        detail = body.get("message", resp.reason) if isinstance(body, dict) else str(body)
                        raise TrelloError(f"Trello API {resp.status}: {detail}")

            except aiohttp.ClientError as e:
                last_exc = e
                if attempt < len(delays):
                    await _asyncio.sleep(delays[attempt])
                continue

        raise TrelloError(
            f"Trello API request failed after retries ({method} {path}): "
            f"{last_exc}"
        ) from last_exc

    async def get_me(self) -> Member:
        """Get authenticated user profile."""
        data = await self._request("GET", "members/me")
        return Member(id=data["id"], username=data.get("username", ""), fullName=data.get("fullName"))

    async def get_my_boards(self) -> list[Board]:
        """List boards accessible to the authenticated user."""
        data = await self._request("GET", "members/me/boards")
        return [Board(id=b["id"], name=b["name"], closed=b.get("closed", False), url=b.get("url")) for b in data]

    async def create_board(self, name: str) -> Board:
        """Create a new board for the authenticated user."""
        data = await self._request("POST", "boards", json_body={"name": name})
        return Board(id=data["id"], name=data["name"], url=data.get("url"))

    async def get_lists(self, board_id: str) -> list[TrelloList]:
        """Get all lists on a board."""
        data = await self._request("GET", f"boards/{board_id}/lists")
        return [TrelloList(id=l["id"], name=l["name"], idBoard=l.get("idBoard", board_id), pos=l.get("pos", 0)) for l in data]

    async def create_list(self, board_id: str, name: str, pos: Optional[float] = None) -> TrelloList:
        """Create a new list on a board."""
        body: dict[str, Any] = {"idBoard": board_id, "name": name}
        if pos is not None:
            body["pos"] = pos

        data = await self._request("POST", "lists", json_body=body)
        return TrelloList(id=data["id"], name=data["name"], idBoard=data.get("idBoard", board_id), pos=data.get("pos", 0))

    async def get_all_cards_on_board(self, board_id: str) -> list[Card]:
        """Get all open cards on a board."""
        data = await self._request("GET", f"boards/{board_id}/cards")
        return [self._parse_card(c) for c in data]

    async def get_cards_from_list(self, list_id: str) -> list[Card]:
        """Get all open cards in a specific list."""
        data = await self._request("GET", f"lists/{list_id}/cards")
        return [self._parse_card(c) for c in data]

    async def create_card(self, id_list: str, name: str, desc: Optional[str] = None) -> Card:
        """Create a new card on a list."""
        body: dict[str, Any] = {"idList": id_list, "name": name}
        if desc is not None:
            body["desc"] = desc

        data = await self._request("POST", "cards", json_body=body)
        return self._parse_card(data)

    async def update_card(self, card_id: str, field: str, value: Any) -> Card:
        """Update a single field on a card."""
        params = {field: str(value)} if not isinstance(value, (dict, list)) else {}
        json_body = {field: value} if isinstance(value, (dict, list)) else None

        data = await self._request(
            "PUT", f"cards/{card_id}",
            params=params if params else None,
            json_body=json_body,
        )
        return self._parse_card(data)

    async def move_card_to_list(self, card_id: str, id_list: str) -> Card:
        """Move a card to a different list."""
        data = await self._request("PUT", f"cards/{card_id}/idList", params={"value": id_list})
        return self._parse_card(data)

    async def comment_on_card(self, card_id: str, text: str) -> CardAction:
        """Add a comment to a card."""
        data = await self._request("POST", f"cards/{card_id}/actions/comments", json_body={"text": text})
        return CardAction(id=data["id"], type=data.get("type", "commentCard"), date=data.get("date", ""), data=data.get("data", {}))

    async def get_card_actions(self, card_id: str) -> list[CardAction]:
        """Get actions (comments, moves, etc.) for a card."""
        data = await self._request("GET", f"cards/{card_id}/actions")
        return [CardAction(id=a["id"], type=a.get("type", ""), date=a.get("date", ""), data=a.get("data", {})) for a in data]

    def _parse_card(self, raw: dict) -> Card:
        """Parse a raw card JSON response into a Card model."""
        labels = []
        for lbl in raw.get("labels", []) or []:
            labels.append(CardLabel(id=lbl["id"], name=lbl.get("name"), color=lbl.get("color")))

        plugin_data: dict[str, PluginDataValue] = {}
        for k, v in (raw.get("pluginData", {}) or {}).items():
            plugin_data[k] = PluginDataValue(value=v) if isinstance(v, dict) else PluginDataValue()

        return Card(
            id=raw["id"],
            name=raw["name"],
            desc=raw.get("desc"),
            idList=raw["idList"],
            idBoard=raw.get("idBoard"),
            labels=labels,
            dueDate=raw.get("dueDate"),
            idShort=raw.get("idShort", 0),
            shortLink=raw.get("shortLink"),
            url=raw.get("url"),
            pluginData=plugin_data,
            closed=raw.get("closed", False),
        )
