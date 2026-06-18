"""Provider registry — loads and dispatches to registered providers."""

from __future__ import annotations

import logging
from typing import Optional

from .base import IntegrationProvider

logger = logging.getLogger(__name__)

_registry: dict[str, type[IntegrationProvider]] | None = None


def _build_default_registry() -> dict[str, type[IntegrationProvider]]:
    """Build the default provider registry.

    Lazy-loaded to avoid importing Trello client code when not needed.
    New providers are registered here by adding their class to the dict.
    """
    from cellos.integrations.trello.provider import TrelloProvider

    return {
        "trello": TrelloProvider,
    }


def get_providers() -> list[str]:
    """Return sorted list of available provider names."""
    registry = _get_registry()
    return sorted(registry.keys())


def load_provider(name: str, **kwargs) -> IntegrationProvider:
    """Load and instantiate a provider by name.

    Args:
        name: Provider identifier (e.g., 'trello').
        **kwargs: Additional arguments forwarded to the provider constructor.

    Returns:
        Fresh instance of the provider.

    Raises:
        ValueError: If the provider name is not registered.
    """
    registry = _get_registry()
    if name not in registry:
        available = ", ".join(sorted(registry.keys()))
        raise ValueError(
            f"Unknown integration provider '{name}'. "
            f"Available: {available}"
        )

    cls = registry[name]
    return cls(**kwargs)


def _get_registry() -> dict[str, type[IntegrationProvider]]:
    """Get the global provider registry (lazy-initialized)."""
    global _registry
    if _registry is None:
        _registry = _build_default_registry()
    return _registry


class ProviderRegistry:
    """Programmatic access to the provider registry.

    Used by scheduler and CLI to enumerate or load providers without
    hard-coding provider names.
    """

    @classmethod
    def list_providers(cls) -> list[str]:
        """Return available provider names."""
        return get_providers()

    @classmethod
    def get_provider(cls, name: str, **kwargs) -> IntegrationProvider:
        """Instantiate a provider by name."""
        return load_provider(name, **kwargs)
