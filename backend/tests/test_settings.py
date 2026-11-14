"""Tests for the settings API (health, provider CRUD, masking, task routing)."""

from __future__ import annotations

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
