"""Database schema and initialization helpers for CelloS."""

from pathlib import Path
from typing import Any

import aiosqlite

REQUIRED_TABLES = {
    "tasks",
    "task_dependencies",
    "task_results",
    "task_events",
    "task_comments",
    "task_attempts",
}


class DatabaseNotInitialized(RuntimeError):
    def __init__(self, path: Path):
        super().__init__(f"CelloS database is not initialized at {path}. Run `cellos init` first.")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    role TEXT NOT NULL,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL,
    attention_required INTEGER NOT NULL,
    assigned_worker_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    conversation TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS task_dependencies (
    task_id TEXT NOT NULL,
    depends_on_task_id TEXT NOT NULL,
    PRIMARY KEY (task_id, depends_on_task_id),
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (depends_on_task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS task_results (
    task_id TEXT PRIMARY KEY,
    success INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS task_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    author_type TEXT NOT NULL,
    author_id TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS task_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    connector TEXT NOT NULL,
    status TEXT NOT NULL,
    prompt_snapshot TEXT NOT NULL,
    result_summary TEXT NOT NULL DEFAULT '',
    result_payload TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    log_path TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    completed_at TEXT,
    payload TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);
"""


async def init_db(conn: aiosqlite.Connection) -> None:
    await conn.executescript(SCHEMA_SQL)
    await conn.commit()


async def ensure_initialized(conn: aiosqlite.Connection, path: Path) -> None:
    placeholders = ", ".join("?" for _ in REQUIRED_TABLES)
    cursor = await conn.execute(
        f"SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ({placeholders})",
        tuple(sorted(REQUIRED_TABLES)),
    )
    rows = await cursor.fetchall()
    found_tables = {row["name"] for row in rows}
    if found_tables != REQUIRED_TABLES:
        raise DatabaseNotInitialized(path)
