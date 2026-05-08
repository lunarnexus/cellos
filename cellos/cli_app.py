"""App bootstrap, path resolution, and async runner helpers for CelloS CLI."""

import click
from asyncio import run as asyncio_run
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, TypeVar

from cellos.config import CellosConfig, ConfigError, ensure_config, load_config
from cellos.db import CellosDatabase, DatabaseNotInitialized

DEFAULT_DB_PATH = Path(".cellos") / "cellos.sqlite"
DEFAULT_WORKDIR = Path.home()
T = TypeVar("T")


@dataclass
class CellosApp:
    config: CellosConfig
    db: CellosDatabase
    workdir: Path


def _run_cli(coro: Awaitable[T]) -> T:
    try:
        return asyncio_run(coro)
    except (ConfigError, DatabaseNotInitialized) as exc:
        raise click.ClickException(str(exc)) from exc


def _resolve_workdir(workdir: Path | None) -> Path:
    if workdir is not None:
        return workdir.expanduser().resolve()
    current = Path.cwd()
    if (current / DEFAULT_DB_PATH).exists():
        return current.resolve()
    return DEFAULT_WORKDIR.resolve()


def _resolve_db_path(db_path: Path | None, workdir: Path) -> Path:
    if db_path is not None:
        return db_path.expanduser().resolve()
    return workdir / DEFAULT_DB_PATH


async def _open_app(
    db_path: Path | None,
    config_path: Path,
    workdir: Path | None = None,
) -> CellosApp:
    resolved_workdir = _resolve_workdir(workdir)
    resolved_db_path = _resolve_db_path(db_path, resolved_workdir)
    config = load_config(config_path)
    db = CellosDatabase(resolved_db_path)
    await db.connect()
    try:
        await db.ensure_initialized()
    except Exception:
        await db.close()
        raise
    return CellosApp(config=config, db=db, workdir=resolved_workdir)
