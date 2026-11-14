"""Shared pytest fixtures.

Every test runs against a throwaway SQLite file so the real ``data/`` database
is never touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture()
def db_path(tmp_path, monkeypatch) -> Path:
    """Point the app at a temporary database for the duration of a test."""
    path = tmp_path / "translatale_test.db"
    monkeypatch.setenv("TRANSLATALE_DB_PATH", str(path))
    monkeypatch.setenv("TRANSLATALE_DATA_DIR", str(tmp_path))
    return path


@pytest.fixture()
def client(db_path):
    """FastAPI TestClient with the app lifespan (schema creation) executed."""
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as test_client:
        yield test_client
