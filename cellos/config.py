"""CelloS runtime configuration."""

import json
from pathlib import Path
from typing import Any

from typing import Literal

from pydantic import BaseModel, ValidationError


DEFAULT_CONFIG_PATH = Path.home() / ".cellos" / "config.json"
EXAMPLE_CONFIG_PATH = Path(__file__).resolve().parent.parent / "cellos.config.example.json"


class ConfigError(RuntimeError):
    pass


class SchedulerConfig(BaseModel):
    concurrent_tasks: int
    worker_timeout_seconds: int


class WorkerConfig(BaseModel):
    backend: Literal["acp"]
    command: list[str]
    debug_log_path: str | None = None


class CellosConfig(BaseModel):
    scheduler: SchedulerConfig
    worker: WorkerConfig


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> CellosConfig:
    config_path = Path(path)
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
        return CellosConfig.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(f"Invalid config file {config_path}: {exc}") from exc


def ensure_config(
    path: str | Path = DEFAULT_CONFIG_PATH,
    example_path: str | Path = EXAMPLE_CONFIG_PATH,
    overwrite: bool = False,
) -> Path:
    config_path = Path(path)
    source_path = Path(example_path)
    if not source_path.exists():
        raise ConfigError(f"Missing example config file: {source_path}")

    config_path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite or not config_path.exists():
        config_path.write_text(source_path.read_text())
    return config_path
