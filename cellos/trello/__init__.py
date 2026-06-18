"""Trello integration module for CelloS.

Provides async Trello REST API client, Pydantic models, and bidirectional sync
between Cellos tasks and Trello cards. Import gracefully degrades if aiohttp
is not installed — Trello features will raise a clear error when used.
"""

from __future__ import annotations

# Re-export public API surface (now lives under integrations)
from cellos.integrations.trello.client import TrelloClient, TrelloError
from cellos.integrations.trello.models import (
    Board,
    Card,
    CardAction,
    CardLabel,
    Member,
    PluginDataValue,
    TrelloList,
)

__all__ = [
    # Client
    "TrelloClient",
    "TrelloError",
    # Models
    "Board",
    "Card",
    "CardAction",
    "CardLabel",
    "Member",
    "PluginDataValue",
    "TrelloList",
]
