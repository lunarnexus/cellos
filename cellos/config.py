"""CelloS runtime configuration."""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError


DEFAULT_CONFIG_PATH = Path.home() / ".cellos" / "config.json"
DEFAULT_AGENT_CATALOG_PATH = Path.home() / ".cellos" / "agentcatalog.json"
DEFAULT_PROMPT_PROFILES_PATH = Path.home() / ".cellos" / "promptprofiles.json"
EXAMPLE_CONFIG_PATH = Path(__file__).resolve().parent.parent / "cellos.config.example.json"
EXAMPLE_AGENT_CATALOG_PATH = Path(__file__).resolve().parent.parent / "agentcatalog.example.json"
EXAMPLE_PROMPT_PROFILES_PATH = Path(__file__).resolve().parent.parent / "promptprofiles.example.json"


class ConfigError(RuntimeError):
    pass


class SchedulerConfig(BaseModel):
    concurrent_tasks: int
    worker_timeout_seconds: int


class WorkerConfig(BaseModel):
    backend: Literal["acp"]
    debug_log_path: str | None = None


class AgentConfig(BaseModel):
    connector: Literal["fake_acp", "opencode"]
    description: str = ""
    options: dict[str, Any] = Field(default_factory=dict)


class AgentCatalogConfig(BaseModel):
    available: dict[str, AgentConfig]


class AgentRuntimeConfig(BaseModel):
    default: str
    catalog_path: str = "agentcatalog.json"


class PromptRuntimeConfig(BaseModel):
    profiles_path: str = "promptprofiles.json"


class PromptModeProfile(BaseModel):
    instructions: list[str] = Field(default_factory=list)
    output_sections: list[str] = Field(default_factory=list)


class PromptProfilesConfig(BaseModel):
    role_instructions: dict[str, str] = Field(default_factory=dict)
    modes: dict[str, PromptModeProfile] = Field(default_factory=dict)
    final_instructions: list[str] = Field(default_factory=list)


class CellosConfig(BaseModel):
    scheduler: SchedulerConfig
    worker: WorkerConfig
    agents: AgentRuntimeConfig
    prompts: PromptRuntimeConfig = Field(default_factory=PromptRuntimeConfig)
    agent_catalog: AgentCatalogConfig = Field(default_factory=lambda: AgentCatalogConfig(available={}))
    prompt_profiles: PromptProfilesConfig = Field(default_factory=PromptProfilesConfig)

    def get_default_agent(self) -> AgentConfig:
        try:
            return self.agent_catalog.available[self.agents.default]
        except KeyError as exc:
            raise ValueError(f"Default agent is not in the available agent catalog: {self.agents.default}") from exc


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> CellosConfig:
    config_path = Path(path).expanduser()
    if not config_path.exists():
        raise ConfigError(
            f"Missing config file: {config_path}. "
            "Run `cellos init` or copy cellos.config.example.json to ~/.cellos/config.json."
        )
    try:
        payload: dict[str, Any] = json.loads(config_path.read_text())
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in config file {config_path}: {exc}") from exc
    try:
        config = CellosConfig.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(f"Invalid config file {config_path}: {exc}") from exc
    catalog_path = resolve_agent_catalog_path(config.agents.catalog_path, config_path)
    catalog = load_agent_catalog(catalog_path)
    prompt_profiles_path = resolve_prompt_profiles_path(config.prompts.profiles_path, config_path)
    prompt_profiles = load_prompt_profiles(prompt_profiles_path)
    return config.model_copy(update={"agent_catalog": catalog, "prompt_profiles": prompt_profiles})


def load_agent_catalog(path: str | Path = DEFAULT_AGENT_CATALOG_PATH) -> AgentCatalogConfig:
    catalog_path = Path(path).expanduser()
    if not catalog_path.exists():
        raise ConfigError(
            f"Missing agent catalog file: {catalog_path}. "
            "Run `cellos init` or copy agentcatalog.example.json to ~/.cellos/agentcatalog.json."
        )
    try:
        payload: dict[str, Any] = json.loads(catalog_path.read_text())
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in agent catalog file {catalog_path}: {exc}") from exc
    try:
        return AgentCatalogConfig.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(f"Invalid agent catalog file {catalog_path}: {exc}") from exc


def load_prompt_profiles(path: str | Path = DEFAULT_PROMPT_PROFILES_PATH) -> PromptProfilesConfig:
    profiles_path = Path(path).expanduser()
    if not profiles_path.exists():
        raise ConfigError(
            f"Missing prompt profiles file: {profiles_path}. "
            "Run `cellos init` or copy promptprofiles.example.json to ~/.cellos/promptprofiles.json."
        )
    try:
        payload: dict[str, Any] = json.loads(profiles_path.read_text())
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in prompt profiles file {profiles_path}: {exc}") from exc
    try:
        return PromptProfilesConfig.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(f"Invalid prompt profiles file {profiles_path}: {exc}") from exc


def resolve_agent_catalog_path(catalog_path: str | Path, config_path: str | Path) -> Path:
    path = Path(catalog_path).expanduser()
    if path.is_absolute():
        return path
    return Path(config_path).expanduser().parent / path


def resolve_prompt_profiles_path(profiles_path: str | Path, config_path: str | Path) -> Path:
    path = Path(profiles_path).expanduser()
    if path.is_absolute():
        return path
    return Path(config_path).expanduser().parent / path


def ensure_config(
    path: str | Path = DEFAULT_CONFIG_PATH,
    example_path: str | Path = EXAMPLE_CONFIG_PATH,
    agent_catalog_path: str | Path | None = None,
    agent_catalog_example_path: str | Path = EXAMPLE_AGENT_CATALOG_PATH,
    prompt_profiles_path: str | Path | None = None,
    prompt_profiles_example_path: str | Path = EXAMPLE_PROMPT_PROFILES_PATH,
    overwrite: bool = False,
) -> Path:
    config_path = Path(path).expanduser()
    source_path = Path(example_path)
    catalog_path = (
        Path(agent_catalog_path).expanduser() if agent_catalog_path is not None else config_path.parent / "agentcatalog.json"
    )
    profiles_path = (
        Path(prompt_profiles_path).expanduser()
        if prompt_profiles_path is not None
        else config_path.parent / "promptprofiles.json"
    )
    catalog_source_path = Path(agent_catalog_example_path)
    profiles_source_path = Path(prompt_profiles_example_path)
    if not source_path.exists():
        raise ConfigError(f"Missing example config file: {source_path}")
    if not catalog_source_path.exists():
        raise ConfigError(f"Missing example agent catalog file: {catalog_source_path}")
    if not profiles_source_path.exists():
        raise ConfigError(f"Missing example prompt profiles file: {profiles_source_path}")

    config_path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite or not config_path.exists():
        config_path.write_text(source_path.read_text())
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite or not catalog_path.exists():
        catalog_path.write_text(catalog_source_path.read_text())
    profiles_path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite or not profiles_path.exists():
        profiles_path.write_text(profiles_source_path.read_text())
    return config_path
