"""Configuration loading, validation, and defaults for CelloS."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, ConfigDict, model_validator


# ─── Exceptions ──────────────────────────────────────────────────────────────

class ConfigError(Exception):
    """Raised when config is invalid or missing."""


# ─── Sub-configs ─────────────────────────────────────────────────────────────

class SchedulerConfig(BaseModel):
    """Scheduler daemon settings."""
    concurrent_tasks: int = 4
    heartbeat_interval_seconds: float = 5.0



class ProviderConfig(BaseModel):
    """Generic per-provider integration configuration.

    Provider-specific fields (for example ``board_id`` or ``project_id``) are allowed and kept
    on the model so providers can validate and consume their own settings.
    """

    model_config = ConfigDict(extra="allow")

    auto_sync_enabled: bool = False
    pull_interval_seconds: int = 300

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        extra = object.__getattribute__(self, "__pydantic_extra__") or {}
        return extra.get(name)


class IntegrationsConfig(BaseModel):
    """Integrations-oriented top-level config shape.

    Stores provider configs generically under ``providers`` while preserving the
    existing ``integrations.<provider>`` access pattern for compatibility.
    """

    enabled_providers: list[str] = Field(default_factory=list)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_provider_blocks(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        raw = dict(data)
        providers = dict(raw.get("providers") or {})
        for key in list(raw.keys()):
            if key in {"enabled_providers", "providers"}:
                continue
            providers[key] = raw.pop(key)
        raw["providers"] = providers
        return raw

    def __getattr__(self, name: str) -> Any:
        providers = self.__dict__.setdefault("providers", {})
        if name.startswith("__"):
            raise AttributeError(name)
        if name not in providers:
            providers[name] = ProviderConfig()
        return providers[name]

    def get_provider(self, name: str) -> ProviderConfig:
        return getattr(self, name)


class WorkerConfig(BaseModel):
    """Worker execution settings."""
    backend: str = "acp"
    timeout_seconds: int = 300


class AgentCatalogEntry(BaseModel):
    """Single agent definition in the catalog."""
    connector: str  # e.g., "opencode", "fake_acp"
    model: Optional[str] = None
    options: dict[str, Any] = Field(default_factory=dict)


# ─── Prompt Profile Configs ──────────────────────────────────────────────────

class ModeProfile(BaseModel):
    """Mode-specific prompt configuration (planning or execution)."""
    instructions: str
    output_sections: list[str] = Field(default_factory=list)


class PromptProfilesConfig(BaseModel):
    """Externalized prompt profiles loaded from promptprofiles.json."""
    role_instructions: dict[str, str] = Field(default_factory=dict)
    modes: dict[str, ModeProfile] = Field(default_factory=dict)
    final_instructions: str = ""


# ─── Approval Config ─────────────────────────────────────────────────────────

class ApprovalConfig(BaseModel):
    """Approval gate settings."""
    preapprove_research_tasks: bool = False


# ─── Agent Runtime (resolved from catalog + main config) ─────────────────────

class AgentRuntimeConfig(BaseModel):
    """Resolved agent configuration for runtime use."""
    default_agent_id: str = "engineer"
    catalog_path: Optional[str] = None


class PromptRuntimeConfig(BaseModel):
    """Path to prompt profiles file."""
    profiles_path: Optional[str] = None


# ─── Top-level Config ────────────────────────────────────────────────────────

class CellosConfig(BaseModel):
    """Top-level configuration combining all config sources."""
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    worker: WorkerConfig = Field(default_factory=WorkerConfig)
    agents: AgentRuntimeConfig = Field(default_factory=AgentRuntimeConfig)
    approvals: ApprovalConfig = Field(default_factory=ApprovalConfig)
    prompts: PromptRuntimeConfig = Field(default_factory=PromptRuntimeConfig)
    integrations: IntegrationsConfig = Field(default_factory=IntegrationsConfig)

    # Resolved at load time from separate files
    agent_catalog: dict[str, AgentCatalogEntry] = Field(default_factory=dict)
    prompt_profiles: PromptProfilesConfig = Field(default_factory=PromptProfilesConfig)

    def get_agent(self, agent_id: str | None = None) -> Optional[AgentCatalogEntry]:
        """Resolve an agent from the catalog by ID or default."""
        aid = agent_id or self.agents.default_agent_id
        return self.agent_catalog.get(aid)


# ─── Path resolution helpers ─────────────────────────────────────────────────

def _resolve_path(config_dir: str, relative_or_absolute: Optional[str]) -> Optional[Path]:
    """Resolve a path that may be relative to config dir or absolute."""
    if not relative_or_absolute:
        return None
    p = Path(relative_or_absolute)
    if p.is_absolute():
        return p
    return Path(config_dir) / p


# ─── Load functions ──────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict[str, Any]:
    """Load and parse a JSON file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}")
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in {path}: {e}")


def load_config(config_dir: str) -> CellosConfig:
    """Load full configuration from three JSON files in the given directory.

    Args:
        config_dir: Path to directory containing config.json, agentcatalog.json,
                    and promptprofiles.json.

    Returns:
        Fully resolved CellosConfig with catalog and profiles loaded.

    Raises:
        ConfigError: If required files are missing or invalid.
    """
    cfg_path = Path(config_dir) / "config.json"
    raw_main = _load_json(cfg_path)

    # Build base config from main file
    config = CellosConfig(**raw_main)

    # Load agent catalog (from path in config, or default location)
    catalog_rel = raw_main.get("agents", {}).get("catalog_path")
    catalog_file = _resolve_path(config_dir, catalog_rel) or Path(config_dir) / "agentcatalog.json"
    if catalog_file.exists():
        raw_catalog = _load_json(catalog_file)
        config.agent_catalog = {k: AgentCatalogEntry(**v) for k, v in raw_catalog.items()}

    # Load prompt profiles (from path in config, or default location)
    profiles_rel = raw_main.get("prompts", {}).get("profiles_path")
    profiles_file = _resolve_path(config_dir, profiles_rel) or Path(config_dir) / "promptprofiles.json"
    if profiles_file.exists():
        raw_profiles = _load_json(profiles_file)
        config.prompt_profiles = PromptProfilesConfig(**raw_profiles)

    return config


def update_provider_config(config_dir: str, provider_name: str, updates: dict[str, Any]) -> None:
    """Persist shallow updates into a provider block inside config.json."""
    cfg_path = Path(config_dir) / "config.json"
    raw_main = _load_json(cfg_path)

    integrations = raw_main.setdefault("integrations", {})
    providers = integrations.setdefault("providers", {})
    provider_block = providers.setdefault(provider_name, {})
    provider_block.update(updates)

    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(raw_main, f, indent=2)
        f.write("\n")


def enable_provider(config_dir: str, provider_name: str) -> None:
    """Ensure a provider is listed in integrations.enabled_providers."""
    cfg_path = Path(config_dir) / "config.json"
    raw_main = _load_json(cfg_path)

    integrations = raw_main.setdefault("integrations", {})
    enabled = list(integrations.setdefault("enabled_providers", []))
    if provider_name not in enabled:
        enabled.append(provider_name)
    integrations["enabled_providers"] = enabled

    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(raw_main, f, indent=2)
        f.write("\n")


# ─── Init helpers ─────────────────────────────────────────────────────────────

def ensure_config(config_dir: str, overwrite: bool = False) -> Path:
    """Copy example config files from the package root to the config directory.

    Args:
        config_dir: Directory to write config files into. Created if missing.
        overwrite: If True, replace existing files. If False, skip if present.

    Returns:
        Path to the created/verified config directory.
    """
    import shutil

    dest = Path(config_dir)
    dest.mkdir(parents=True, exist_ok=True)

    # Source: example files bundled inside the cellos package
    package_dir = Path(__file__).resolve().parent
    copies = {
        "cellos.config.json.example": "config.json",
        "agentcatalog.json.example": "agentcatalog.json",
        "promptprofiles.json.example": "promptprofiles.json",
        "env.example": ".env",
    }

    for src_name, dst_name in copies.items():
        src = package_dir / src_name
        dst = dest / dst_name
        if not overwrite and dst.exists():
            continue
        # .env is never overwritten (preserves user secrets), even with --overwrite
        if dst_name == ".env" and dst.exists():
            continue
        if not src.exists():
            raise ConfigError(f"Example config not found: {src}")
        shutil.copy2(str(src), str(dst))

    return dest
