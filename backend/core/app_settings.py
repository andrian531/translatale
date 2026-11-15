"""Typed access to the ``app_settings`` key/value table.

Values are stored as JSON so a setting can grow from a scalar to an object
without a migration.
"""

from __future__ import annotations

import json
from typing import Any

import config
import database

SCRAPER_KEY = "scraper"

Number = int | float

#: Settings that must round-trip as integers.
INT_SETTINGS = frozenset({"fetch_batch_size", "fetch_max_consecutive_errors"})


def get_setting(key: str, default: Any, db_path: str | None = None) -> Any:
    with database.get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT value_json FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value_json"])
    except (TypeError, ValueError):
        return default


def set_setting(key: str, value: Any, db_path: str | None = None) -> Any:
    with database.get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_at = excluded.updated_at
            """,
            (key, json.dumps(value, ensure_ascii=False), database.utcnow()),
        )
    return value


def _coerce(name: str, value: Any) -> Number:
    """Return an int for whole-number settings, else a float."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return config.SCRAPER_SETTINGS_DEFAULTS[name]
    low, high = config.SCRAPER_SETTINGS_LIMITS[name]
    number = min(max(number, low), high)
    if name in INT_SETTINGS:
        return int(round(number))
    return number


def get_scraper_settings(db_path: str | None = None) -> dict[str, Number]:
    """Always returns a complete, validated dict — never a partial one."""
    stored = get_setting(SCRAPER_KEY, {}, db_path)
    if not isinstance(stored, dict):
        stored = {}
    return {
        name: _coerce(name, stored.get(name, default))
        for name, default in config.SCRAPER_SETTINGS_DEFAULTS.items()
    }


def save_scraper_settings(data: dict[str, Any], db_path: str | None = None) -> dict[str, Number]:
    merged = get_scraper_settings(db_path)
    for name in config.SCRAPER_SETTINGS_DEFAULTS:
        if name in data and data[name] is not None:
            merged[name] = _coerce(name, data[name])
    set_setting(SCRAPER_KEY, merged, db_path)
    return get_scraper_settings(db_path)
