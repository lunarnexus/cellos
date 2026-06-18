"""SQLite schema definitions and initialization."""

import aiosqlite
from pathlib import Path


REQUIRED_TABLES = frozenset({
    "tasks",
    "task_dependencies",
    "task_results",
    "task_events",
    "task_comments",
    "task_attempts",
    "trello_sync",
})

SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    details TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    role TEXT NOT NULL DEFAULT 'engineer',
    task_type TEXT NOT NULL,
    plan TEXT DEFAULT '',
    prompt_text TEXT DEFAULT '',
    parent_id TEXT REFERENCES tasks(id),
    agent_id TEXT DEFAULT '',
    success_criteria TEXT DEFAULT '',
    failure_criteria TEXT DEFAULT '',
    dependencies TEXT DEFAULT '[]',
    attention TEXT DEFAULT '{"required": false}',
    processing TEXT DEFAULT '{}',
    conversation TEXT DEFAULT '[]',
    result TEXT DEFAULT '',
    comments TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attention_required
    ON tasks(json_extract(attention, '$.required'));

CREATE TABLE IF NOT EXISTS task_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    depends_on_task_id TEXT NOT NULL REFERENCES tasks(id),
    status_satisfied BOOLEAN DEFAULT FALSE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    success BOOLEAN NOT NULL,
    summary TEXT DEFAULT '',
    output TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    event_type TEXT NOT NULL,
    message TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_comments (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    author_type TEXT NOT NULL,
    author_id TEXT DEFAULT '',
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_attempts (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    status TEXT NOT NULL DEFAULT 'started',
    mode TEXT DEFAULT '',
    agent_id TEXT DEFAULT '',
    result_summary TEXT DEFAULT '',
    error_message TEXT DEFAULT '',
    started_at TEXT NOT NULL,
    completed_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS trello_sync (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL
);
"""


class DatabaseNotInitialized(Exception):
    """Raised when the database has not been initialized."""


async def init_db(db_path: str | Path) -> None:
    """Initialize the SQLite database by creating all tables.

    Idempotent — safe to call multiple times.
    """
    async with aiosqlite.connect(str(db_path)) as db:
        await db.executescript(SCHEMA_SQL)
        await db.commit()


async def ensure_initialized(db_path: str | Path) -> None:
    """Verify all required tables exist; raise if not initialized.

    Checks table existence rather than relying on a sentinel file, so it's
    resilient to manual DB drops or corruption.
    """
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        existing = {row[0] async for row in cursor}

    missing = REQUIRED_TABLES - existing
    if missing:
        raise DatabaseNotInitialized(
            f"Database not initialized. Missing tables: {', '.join(sorted(missing))}. "
            "Run 'cellos init' to create them."
        )
