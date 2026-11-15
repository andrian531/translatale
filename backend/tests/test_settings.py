"""Tests for the settings API (health, provider CRUD, masking, task routing)."""

from __future__ import annotations

import json
import sqlite3

import httpx
import pytest

import config
import database
from llm.base import TaskNotConfiguredError, TaskRouter


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------
def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["tasks"] == list(config.TASKS)


def test_meta_lists_all_provider_types(client):
    response = client.get("/api/settings/meta")
    assert response.status_code == 200
    body = response.json()
    values = [item["value"] for item in body["provider_types"]]
    assert values == list(config.PROVIDER_TYPES)
    assert "ollama" in values
    ollama = next(item for item in body["provider_types"] if item["value"] == "ollama")
    assert ollama["requires_api_key"] is False
    assert [task["value"] for task in body["tasks"]] == list(config.TASKS)


# --------------------------------------------------------------------------
# Provider CRUD + masking
# --------------------------------------------------------------------------
def test_create_provider_masks_api_key(client):
    response = client.post(
        "/api/settings/providers",
        json={
            "provider_type": "openai",
            "display_name": "My OpenAI",
            "api_key": "sk-test-abcd1234",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["provider_type"] == "openai"
    assert body["display_name"] == "My OpenAI"
    assert body["api_key"] == "****1234"
    assert body["has_api_key"] is True
    # Default base URL is filled in automatically.
    assert body["base_url"] == config.DEFAULT_BASE_URLS["openai"]
    assert "sk-test-abcd1234" not in response.text


def test_create_provider_uses_default_display_name_and_base_url(client):
    response = client.post(
        "/api/settings/providers", json={"provider_type": "ollama"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["display_name"] == config.PROVIDER_LABELS["ollama"]
    assert body["base_url"] == config.DEFAULT_BASE_URLS["ollama"]
    assert body["api_key"] == ""
    assert body["has_api_key"] is False


def test_list_providers_never_returns_raw_key(client):
    client.post(
        "/api/settings/providers",
        json={"provider_type": "gemini", "api_key": "AIzaSySECRETVALUE9999"},
    )
    response = client.get("/api/settings/providers")
    assert response.status_code == 200
    providers = response.json()
    assert len(providers) == 1
    assert providers[0]["api_key"] == "****9999"
    assert "AIzaSySECRETVALUE9999" not in response.text


def test_short_key_is_fully_masked(client):
    response = client.post(
        "/api/settings/providers",
        json={"provider_type": "custom", "api_key": "abc"},
    )
    assert response.status_code == 201
    assert response.json()["api_key"] == "****"


def test_update_provider_keeps_key_when_masked_value_sent(client):
    created = client.post(
        "/api/settings/providers",
        json={"provider_type": "deepseek", "api_key": "sk-deepseek-7777"},
    ).json()

    updated = client.post(
        "/api/settings/providers",
        json={
            "id": created["id"],
            "provider_type": "deepseek",
            "display_name": "DeepSeek Renamed",
            "api_key": created["api_key"],  # the masked value the UI shows
            "base_url": "https://api.deepseek.com/v1",
        },
    )
    assert updated.status_code == 201
    body = updated.json()
    assert body["display_name"] == "DeepSeek Renamed"
    assert body["api_key"] == "****7777"

    # The stored key must still be the original one.
    with database.get_conn() as conn:
        row = conn.execute(
            "SELECT api_key FROM provider_configs WHERE id = ?", (created["id"],)
        ).fetchone()
    assert row["api_key"] == "sk-deepseek-7777"


def test_update_provider_replaces_key_when_new_value_sent(client):
    created = client.post(
        "/api/settings/providers",
        json={"provider_type": "openrouter", "api_key": "sk-or-old-1111"},
    ).json()

    updated = client.post(
        "/api/settings/providers",
        json={
            "id": created["id"],
            "provider_type": "openrouter",
            "api_key": "sk-or-new-2222",
        },
    ).json()
    assert updated["api_key"] == "****2222"


def test_update_missing_provider_returns_404(client):
    response = client.post(
        "/api/settings/providers",
        json={"id": 999, "provider_type": "openai", "api_key": "x"},
    )
    assert response.status_code == 404


def test_invalid_provider_type_rejected(client):
    response = client.post(
        "/api/settings/providers", json={"provider_type": "not-a-provider"}
    )
    assert response.status_code == 422


def test_delete_provider_clears_task_routing(client):
    created = client.post(
        "/api/settings/providers",
        json={"provider_type": "openai", "api_key": "sk-1234"},
    ).json()

    client.put(
        "/api/settings/tasks/translate",
        json={"provider_id": created["id"], "model_name": "gpt-4o-mini"},
    )

    deleted = client.delete(f"/api/settings/providers/{created['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True

    assert client.get("/api/settings/providers").json() == []

    tasks = {task["task_name"]: task for task in client.get("/api/settings/tasks").json()}
    assert tasks["translate"]["provider_id"] is None
    assert tasks["translate"]["model_name"] == "gpt-4o-mini"


def test_delete_missing_provider_returns_404(client):
    assert client.delete("/api/settings/providers/4242").status_code == 404


# --------------------------------------------------------------------------
# Task routing
# --------------------------------------------------------------------------
def test_tasks_are_seeded_with_three_slots(client):
    response = client.get("/api/settings/tasks")
    assert response.status_code == 200
    tasks = response.json()
    assert [task["task_name"] for task in tasks] == list(config.TASKS)
    for task in tasks:
        assert task["provider_id"] is None
        assert task["model_name"] == ""
        assert task["temperature"] == pytest.approx(config.DEFAULT_TEMPERATURE)
        assert task["max_tokens"] == config.DEFAULT_MAX_TOKENS
        assert task["label"]


def test_update_task_routing(client):
    provider = client.post(
        "/api/settings/providers",
        json={"provider_type": "anthropic", "api_key": "sk-ant-5555"},
    ).json()

    response = client.put(
        "/api/settings/tasks/story_analysis",
        json={
            "provider_id": provider["id"],
            "model_name": "claude-3-5-sonnet-latest",
            "temperature": 0.3,
            "max_tokens": 8192,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["task_name"] == "story_analysis"
    assert body["provider_id"] == provider["id"]
    assert body["provider_type"] == "anthropic"
    assert body["provider_display_name"] == config.PROVIDER_LABELS["anthropic"]
    assert body["model_name"] == "claude-3-5-sonnet-latest"
    assert body["temperature"] == pytest.approx(0.3)
    assert body["max_tokens"] == 8192

    # Persisted, and the other tasks are untouched.
    tasks = {task["task_name"]: task for task in client.get("/api/settings/tasks").json()}
    assert tasks["story_analysis"]["model_name"] == "claude-3-5-sonnet-latest"
    assert tasks["translate"]["provider_id"] is None


def test_update_task_with_unknown_provider_returns_404(client):
    response = client.put(
        "/api/settings/tasks/translate",
        json={"provider_id": 12345, "model_name": "gpt-4o-mini"},
    )
    assert response.status_code == 404


def test_update_unknown_task_returns_422(client):
    response = client.put(
        "/api/settings/tasks/unknown_task", json={"model_name": "x"}
    )
    assert response.status_code == 422


def test_task_router_resolves_configured_task(client):
    provider = client.post(
        "/api/settings/providers",
        json={
            "provider_type": "openai",
            "api_key": "sk-router-9999",
            "base_url": "https://api.openai.com/v1",
        },
    ).json()
    client.put(
        "/api/settings/tasks/translate",
        json={
            "provider_id": provider["id"],
            "model_name": "gpt-4o-mini",
            "temperature": 0.5,
            "max_tokens": 2048,
        },
    )

    resolved = TaskRouter("translate").resolve()
    assert resolved.provider_type == "openai"
    assert resolved.model == "gpt-4o-mini"
    assert resolved.temperature == pytest.approx(0.5)
    assert resolved.max_tokens == 2048
    assert resolved.provider.api_key == "sk-router-9999"
    assert resolved.provider.base_url == "https://api.openai.com/v1"


def test_task_router_raises_when_unconfigured(client):
    with pytest.raises(TaskNotConfiguredError):
        TaskRouter("scrape_analysis").resolve()


def test_task_router_raises_when_provider_disabled(client):
    provider = client.post(
        "/api/settings/providers",
        json={"provider_type": "openai", "api_key": "sk-x", "is_enabled": False},
    ).json()
    client.put(
        "/api/settings/tasks/translate",
        json={"provider_id": provider["id"], "model_name": "gpt-4o-mini"},
    )
    with pytest.raises(TaskNotConfiguredError):
        TaskRouter("translate").resolve()


# --------------------------------------------------------------------------
# Test connection
# --------------------------------------------------------------------------
def test_connection_unknown_provider_returns_404(client):
    assert client.post("/api/settings/providers/999/test").status_code == 404


def test_connection_without_api_key_fails_gracefully(client):
    provider = client.post(
        "/api/settings/providers", json={"provider_type": "gemini"}
    ).json()

    response = client.post(f"/api/settings/providers/{provider['id']}/test")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "API key" in body["message"]
    assert body["model"] == config.DEFAULT_MODELS["gemini"]


def test_connection_uses_model_from_request(client):
    provider = client.post(
        "/api/settings/providers", json={"provider_type": "anthropic"}
    ).json()

    body = client.post(
        f"/api/settings/providers/{provider['id']}/test",
        json={"model": "claude-3-opus-latest"},
    ).json()
    assert body["ok"] is False
    assert body["model"] == "claude-3-opus-latest"


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------
def test_schema_has_expected_tables(db_path):
    database.init_db(db_path)
    with database.get_conn(db_path) as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {"provider_configs", "task_models"} <= tables


# --------------------------------------------------------------------------
# available_models: migration
# --------------------------------------------------------------------------
OLD_PROVIDER_SCHEMA = """
CREATE TABLE provider_configs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_type TEXT    NOT NULL,
    display_name  TEXT    NOT NULL,
    api_key       TEXT    NOT NULL DEFAULT '',
    base_url      TEXT    NOT NULL DEFAULT '',
    is_enabled    INTEGER NOT NULL DEFAULT 1,
    updated_at    TEXT    NOT NULL
);
"""


def _old_database(path):
    conn = sqlite3.connect(path)
    conn.execute(OLD_PROVIDER_SCHEMA)
    conn.execute(
        "INSERT INTO provider_configs (provider_type, display_name, updated_at) "
        "VALUES ('openai', 'Provider Lama', '2026-01-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()


def test_available_models_column_is_added_to_an_old_database(tmp_path):
    path = tmp_path / "legacy.db"
    _old_database(path)

    with sqlite3.connect(path) as conn:
        before = {row[1] for row in conn.execute("PRAGMA table_info(provider_configs)")}
    assert "available_models" not in before

    database.init_db(path)

    with sqlite3.connect(path) as conn:
        after = {row[1] for row in conn.execute("PRAGMA table_info(provider_configs)")}
        stored = conn.execute("SELECT available_models FROM provider_configs").fetchone()[0]
    assert "available_models" in after
    # Existing rows pick up the constant default.
    assert stored == "[]"


def test_migration_is_idempotent(tmp_path):
    path = tmp_path / "legacy.db"

    database.init_db(path)
    for _ in range(3):
        database.init_db(path)

    with database.get_conn(path) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(provider_configs)")]
        assert columns.count("available_models") == 1
        assert database.migrate_schema(conn) == []


# --------------------------------------------------------------------------
# available_models: API persistence
# --------------------------------------------------------------------------
def test_create_provider_with_available_models(client):
    response = client.post(
        "/api/settings/providers",
        json={
            "provider_type": "custom",
            "display_name": "Kenari",
            "api_key": "sk-kenari-1234",
            "base_url": "https://kenari.id/v1",
            "available_models": ["kenari-pro", "kenari-mini", "kenari-pro"],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    # Duplicates are removed, order preserved.
    assert body["available_models"] == ["kenari-pro", "kenari-mini"]

    listed = client.get("/api/settings/providers").json()[0]
    assert listed["available_models"] == ["kenari-pro", "kenari-mini"]


def test_provider_without_models_defaults_to_empty_list(client):
    response = client.post(
        "/api/settings/providers", json={"provider_type": "openai", "api_key": "sk-1"}
    )
    assert response.status_code == 201
    assert response.json()["available_models"] == []


def test_update_without_models_keeps_the_stored_list(client):
    created = client.post(
        "/api/settings/providers",
        json={
            "provider_type": "custom",
            "display_name": "Groq",
            "api_key": "sk-groq",
            "base_url": "https://api.groq.com/openai/v1",
            "available_models": ["llama-3.3-70b", "mixtral-8x7b"],
        },
    ).json()

    updated = client.post(
        "/api/settings/providers",
        json={"id": created["id"], "provider_type": "custom", "display_name": "Groq (baru)"},
    ).json()
    assert updated["display_name"] == "Groq (baru)"
    assert updated["available_models"] == ["llama-3.3-70b", "mixtral-8x7b"]


def test_update_replaces_the_model_list(client):
    created = client.post(
        "/api/settings/providers",
        json={"provider_type": "custom", "display_name": "X", "available_models": ["a"]},
    ).json()

    updated = client.post(
        "/api/settings/providers",
        json={"id": created["id"], "provider_type": "custom", "available_models": ["b", "c"]},
    ).json()
    assert updated["available_models"] == ["b", "c"]


# --------------------------------------------------------------------------
# available_models: sync endpoint (HTTP mocked)
# --------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _fake_httpx(monkeypatch, payload, status_code=200):
    """Patch httpx.AsyncClient so providers hit a canned response."""
    calls: list[dict] = []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url, **kwargs):
            calls.append({"url": str(url), "kwargs": kwargs})
            return _FakeResponse(payload, status_code)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    return calls


def test_sync_models_persists_to_sqlite(client, monkeypatch):
    provider = client.post(
        "/api/settings/providers",
        json={
            "provider_type": "deepseek",
            "display_name": "DeepSeek",
            "api_key": "sk-deepseek-9999",
        },
    ).json()

    calls = _fake_httpx(
        monkeypatch,
        {"data": [{"id": "deepseek-v4-1-flash"}, {"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]},
    )

    response = client.post(f"/api/settings/providers/{provider['id']}/models/sync")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["count"] == 3
    assert body["models"] == ["deepseek-chat", "deepseek-reasoner", "deepseek-v4-1-flash"]

    # The provider hit the /models endpoint with a bearer token.
    assert calls and calls[0]["url"].endswith("/models")
    assert calls[0]["kwargs"]["headers"]["Authorization"] == "Bearer sk-deepseek-9999"

    # Persisted to SQLite and surfaced by the list endpoint.
    with database.get_conn() as conn:
        row = conn.execute(
            "SELECT available_models FROM provider_configs WHERE id = ?", (provider["id"],)
        ).fetchone()
    assert json.loads(row["available_models"]) == [
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-v4-1-flash",
    ]

    listed = client.get("/api/settings/providers").json()
    assert listed[0]["available_models"] == [
        "deepseek-chat",
        "deepseek-reasoner",
        "deepseek-v4-1-flash",
    ]


def test_sync_models_reports_auth_failure(client, monkeypatch):
    provider = client.post(
        "/api/settings/providers",
        json={"provider_type": "openai", "api_key": "sk-bad"},
    ).json()

    _fake_httpx(
        monkeypatch,
        {"error": {"message": "Incorrect API key provided"}},
        status_code=401,
    )

    response = client.post(f"/api/settings/providers/{provider['id']}/models/sync")
    assert response.status_code == 502
    assert "Incorrect API key" in response.json()["detail"]


def test_sync_models_rejects_empty_list(client, monkeypatch):
    provider = client.post(
        "/api/settings/providers", json={"provider_type": "openai", "api_key": "sk-x"}
    ).json()

    _fake_httpx(monkeypatch, {"data": []})

    response = client.post(f"/api/settings/providers/{provider['id']}/models/sync")
    assert response.status_code == 502
    assert "tidak mengembalikan model" in response.json()["detail"]


def test_sync_models_unknown_provider_404(client):
    assert client.post("/api/settings/providers/999/models/sync").status_code == 404


def test_gemini_list_models_filters_generate_content(client, monkeypatch):
    provider = client.post(
        "/api/settings/providers", json={"provider_type": "gemini", "api_key": "AIza-1234"}
    ).json()

    _fake_httpx(
        monkeypatch,
        {
            "models": [
                {
                    "name": "models/gemini-2.0-flash",
                    "supportedGenerationMethods": ["generateContent", "countTokens"],
                },
                {
                    "name": "models/text-embedding-004",
                    "supportedGenerationMethods": ["embedContent"],
                },
                {
                    "name": "models/gemini-1.5-pro",
                    "supportedGenerationMethods": ["generateContent"],
                },
            ]
        },
    )

    response = client.post(f"/api/settings/providers/{provider['id']}/models/sync")
    assert response.status_code == 200, response.text
    assert response.json()["models"] == ["gemini-1.5-pro", "gemini-2.0-flash"]


def test_test_connection_syncs_models_opportunistically(client, monkeypatch):
    provider = client.post(
        "/api/settings/providers",
        json={"provider_type": "openai", "api_key": "sk-ok"},
    ).json()

    _fake_httpx(monkeypatch, {"data": [{"id": "gpt-4o-mini"}, {"id": "gpt-4o"}]})

    response = client.post(f"/api/settings/providers/{provider['id']}/test")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["model_count"] == 2

    listed = client.get("/api/settings/providers").json()
    assert listed[0]["available_models"] == ["gpt-4o", "gpt-4o-mini"]


def test_test_connection_survives_a_broken_model_list(client, monkeypatch):
    provider = client.post(
        "/api/settings/providers",
        json={"provider_type": "openai", "api_key": "sk-ok"},
    ).json()

    # 200 for the models call but with a shape list_models cannot parse.
    _fake_httpx(monkeypatch, {"unexpected": True})

    response = client.post(f"/api/settings/providers/{provider['id']}/test")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["models_synced"] is False


# --------------------------------------------------------------------------
# Default provider/model, preview & cover_prompt slot
# --------------------------------------------------------------------------
def test_preview_provider_tests_and_lists_models(client, monkeypatch):
    _fake_httpx(monkeypatch, {"data": [{"id": "gpt-4o-mini"}, {"id": "gpt-4o"}]})

    response = client.post(
        "/api/settings/providers/preview",
        json={"provider_type": "openai", "api_key": "sk-preview"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["models"] == ["gpt-4o", "gpt-4o-mini"]
    assert body["model_count"] == 2


def test_default_provider_model_used_as_fallback_for_unconfigured_tasks(client):
    first = client.post(
        "/api/settings/providers",
        json={
            "provider_type": "openai",
            "api_key": "sk-first",
            "default_model": "gpt-4o-mini",
            "is_default": True,
        },
    ).json()
    assert first["is_default"] is True
    assert first["default_model"] == "gpt-4o-mini"

    # Second default provider unsets the first one.
    second = client.post(
        "/api/settings/providers",
        json={
            "provider_type": "gemini",
            "api_key": "AIza-second",
            "default_model": "gemini-2.0-flash",
            "is_default": True,
        },
    ).json()
    assert second["is_default"] is True
    providers = {p["id"]: p for p in client.get("/api/settings/providers").json()}
    assert providers[first["id"]]["is_default"] is False

    # Unconfigured task slots resolve to the active default provider + default_model.
    resolved = TaskRouter("translate").resolve()
    assert resolved.provider_type == "gemini"
    assert resolved.model == "gemini-2.0-flash"
    assert resolved.provider.api_key == "AIza-second"


def test_tasks_endpoint_includes_cover_prompt_slot(client):
    tasks = client.get("/api/settings/tasks").json()
    names = [t["task_name"] for t in tasks]
    assert "cover_prompt" in names
    assert names == ["translate", "scrape_analysis", "story_analysis", "cover_prompt"]

    provider = client.post(
        "/api/settings/providers",
        json={"provider_type": "openai", "api_key": "sk-cover", "default_model": "gpt-4o-mini"},
    ).json()
    saved = client.put(
        "/api/settings/tasks/cover_prompt",
        json={"provider_id": provider["id"], "model_name": "gpt-4o"},
    )
    assert saved.status_code == 200
    assert saved.json()["model_name"] == "gpt-4o"
