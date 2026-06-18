"""Generic integration plugin surface for external providers."""

from .base import (
    IntegrationProvider,
    IntegrationStatus,
    SyncDelta,
)
from .registry import ProviderRegistry, get_providers, load_provider

__all__ = [
    "IntegrationProvider",
    "IntegrationStatus",
    "SyncDelta",
    "ProviderRegistry",
    "get_providers",
    "load_provider",
]
