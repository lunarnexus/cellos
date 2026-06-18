"""Integration provider abstract contract and shared DTOs."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SyncDelta:
    """Structured result of a sync operation.

    Generalized enough to be rendered without provider-specific field names
    leaking into the CLI contract.
    """

    items_created: int = 0
    items_updated: int = 0
    items_moved: int = 0
    comments_imported: int = 0
    statuses_changed: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class IntegrationStatus:
    """Structured status data for CLI rendering."""

    provider_name: str
    configured: bool
    credentials_configured: bool
    board_or_target: str | None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_ready(self) -> bool:
        return self.configured and self.credentials_configured


class IntegrationProvider(abc.ABC):
    """Abstract base for integration providers.

    Each provider (Trello, GitHub Projects, Linear, etc.) implements this
    contract to participate in the generic CLI surface and scheduler hooks.
    """

    @property
    @abc.abstractmethod
    def provider_name(self) -> str:
        """Short identifier used in CLI commands (e.g., 'trello')."""
        ...

    @abc.abstractmethod
    async def is_configured(self) -> bool:
        """Check if the provider has been set up (board/target linked)."""
        ...

    @abc.abstractmethod
    async def setup(self) -> tuple[str, dict[str, str]]:
        """Bootstrap or validate the external resource and persist state.

        Returns:
            Tuple of (target_id, mapping_dict) where target_id is the board/
            project ID and mapping_dict contains any discovered mappings.
        """
        ...

    @abc.abstractmethod
    async def status(self) -> IntegrationStatus:
        """Return structured status for CLI rendering."""
        ...

    @abc.abstractmethod
    async def sync(self, push: bool = True, pull: bool = True) -> SyncDelta:
        """Run bidirectional (or one-directional) sync.

        Args:
            push: Push local changes to the external provider.
            pull: Pull remote changes into local state.

        Returns:
            SyncDelta with counts of changes made.
        """
        ...

    @abc.abstractmethod
    async def auto_push(self) -> SyncDelta:
        """Lightweight auto-push for scheduler cycles."""
        ...

    @abc.abstractmethod
    async def auto_pull_maybe(self, pull_interval_seconds: int) -> SyncDelta:
        """Conditional auto-pull that respects interval gating."""
        ...
