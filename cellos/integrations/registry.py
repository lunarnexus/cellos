"""Provider registry — discovers, loads, and dispatches integration providers."""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from types import ModuleType

from . import __path__ as integrations_pkg_path
from .base import IntegrationProvider

logger = logging.getLogger(__name__)

_registry: dict[str, type[IntegrationProvider]] | None = None

_RESERVED_MODULES = {"__pycache__", "base", "registry"}


def _iter_provider_module_names() -> list[str]:
    """Return candidate provider module names under cellos.integrations."""
    module_names: list[str] = []
    for module_info in pkgutil.iter_modules(integrations_pkg_path):
        if not module_info.ispkg:
            continue
        if module_info.name in _RESERVED_MODULES:
            continue
        module_names.append(f"cellos.integrations.{module_info.name}.provider")
    return sorted(module_names)


def _import_provider_module(module_name: str) -> ModuleType:
    """Import a provider module by fully-qualified module name."""
    return importlib.import_module(module_name)


def _find_provider_classes(module: ModuleType) -> list[type[IntegrationProvider]]:
    """Find concrete IntegrationProvider subclasses defined in a module."""
    provider_classes: list[type[IntegrationProvider]] = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if obj is IntegrationProvider:
            continue
        if not issubclass(obj, IntegrationProvider):
            continue
        if inspect.isabstract(obj):
            continue
        if obj.__module__ != getattr(module, "__name__", None):
            continue
        provider_classes.append(obj)
    return provider_classes


def _build_default_registry() -> dict[str, type[IntegrationProvider]]:
    """Build the registry by discovering provider packages."""
    registry: dict[str, type[IntegrationProvider]] = {}

    for module_name in _iter_provider_module_names():
        try:
            module = _import_provider_module(module_name)
        except Exception as e:
            logger.warning("Skipping integration provider module %s: %s", module_name, e)
            continue

        provider_classes = _find_provider_classes(module)
        if not provider_classes:
            logger.debug("No concrete IntegrationProvider found in %s", module_name)
            continue

        for cls in provider_classes:
            provider_name = getattr(cls, "PROVIDER_NAME", "") or cls.__name__.lower()
            if provider_name in registry:
                logger.warning(
                    "Duplicate integration provider name '%s' from %s; keeping %s",
                    provider_name,
                    module_name,
                    registry[provider_name].__module__,
                )
                continue
            registry[provider_name] = cls

    return registry


def get_providers() -> list[str]:
    """Return sorted list of available provider names."""
    registry = _get_registry()
    return sorted(registry.keys())


def load_provider(name: str, **kwargs) -> IntegrationProvider:
    """Load and instantiate a provider by name.

    Args:
        name: Provider identifier (e.g., 'wekan').
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
