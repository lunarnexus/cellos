"""Pydantic models for Trello API resources."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class Board(BaseModel):
    """Trello board resource."""

    id: str
    name: str
    closed: bool = False
    url: Optional[str] = None


class TrelloList(BaseModel):
    """Trello list (column) on a board."""

    id: str
    name: str
    idBoard: str
    pos: float


class CardLabel(BaseModel):
    """Color label attached to a card."""

    id: str
    name: Optional[str] = None
    color: Optional[str] = None


class PluginDataValue(BaseModel):
    """Single pluginData entry scoped to a Power-Up ID."""

    value: Any = Field(default_factory=dict)


class Card(BaseModel):
    """Trello card resource."""

    id: str
    name: str
    desc: Optional[str] = None
    idList: str
    idBoard: Optional[str] = None
    labels: list[CardLabel] = Field(default_factory=list)
    dueDate: Optional[str] = None
    idShort: int = 0
    shortLink: Optional[str] = None
    url: Optional[str] = None
    pluginData: dict[str, PluginDataValue] = Field(default_factory=dict)
    closed: bool = False


class CardAction(BaseModel):
    """A Trello card action (comment, move, rename, etc.)."""

    id: str
    type: str  # "commentCard", "updateCard", etc.
    date: str
    data: dict[str, Any] = Field(default_factory=dict)

    @property
    def card_id(self) -> Optional[str]:
        """The card ID the action belongs to."""
        return self.data.get("card", {}).get("id") if "card" in self.data else None

    @property
    def text(self) -> str:
        """Comment text (for commentCard actions)."""
        return self.data.get("text", "")

    @property
    def member_creator_id(self) -> Optional[str]:
        """ID of the member who created this action."""
        mc = self.data.get("memberCreator", {}) or {}
        return mc.get("id")


class Member(BaseModel):
    """Trello member resource (minimal)."""

    id: str
    username: str
    fullName: Optional[str] = None
