"""SQLite setup and small data-access helpers.

The schema is intentionally tiny for Phase 1: provider credentials plus the
per-task model routing table. Later phases add novel/chapter tables here.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS provider_configs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_type TEXT    NOT NULL,
    display_name  TEXT    NOT NULL,
    api_key       TEXT    NOT NULL DEFAULT '',
    base_url      TEXT    NOT NULL DEFAULT '',
    is_enabled    INTEGER NOT NULL DEFAULT 1,
    updated_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS task_models (
    task_name   TEXT    PRIMARY KEY,
    provider_id INTEGER REFERENCES provider_configs(id) ON DELETE SET NULL,
    model_name  TEXT    NOT NULL DEFAULT '',
    temperature REAL    NOT NULL DEFAULT 0.7,
    max_tokens  INTEGER NOT NULL DEFAULT 4096,
    updated_at  TEXT    NOT NULL
);
"""


def utcnow() -> str:
    """Timestamp string used for every ``updated_at`` column."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_db_path() -> Path:
    return config.get_db_path()


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a connection with row access by name and FK enforcement on."""
    path = Path(db_path) if db_path is not None else get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """Context manager that commits on success and always closes."""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str | None = None) -> Path:
    """Create tables (idempotent) and seed the three routing slots."""
    path = Path(db_path) if db_path is not None else get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    with get_conn(path) as conn:
        conn.executescript(SCHEMA)
        now = utcnow()
        for task in config.TASKS:
            conn.execute(
                """
                INSERT INTO task_models (task_name, provider_id, model_name,
                                         temperature, max_tokens, updated_at)
                VALUES (?, NULL, '', ?, ?, ?)
                ON CONFLICT(task_name) DO NOTHING
                """,
                (task, config.DEFAULT_TEMPERATURE, config.DEFAULT_MAX_TOKENS, now),
            )
    return path


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None
