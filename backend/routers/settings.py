"""Settings API: LLM provider credentials and per-task model routing."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

import config
import database
from core.app_settings import get_scraper_settings, save_scraper_settings
from llm.base import LLMError
from llm.cli_provider import describe_cli
from llm.registry import create_provider

router = APIRouter(prefix="/api/settings", tags=["settings"])

ProviderType = Literal[
    "gemini",
    "openai",
    "openrouter",
    "deepseek",
    "anthropic",
    "custom",
    "ollama",
    "agy",
    "codex",
]
TaskName = Literal["translate", "scrape_analysis", "story_analysis", "cover_prompt"]

MASK_PREFIX = "****"


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class ProviderPayload(BaseModel):
    """Create/update payload. ``id`` present means update."""

    id: int | None = None
    provider_type: ProviderType
    display_name: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    is_enabled: bool = True
    #: ``None`` means "leave whatever is stored"; a list replaces it.
    available_models: list[str] | None = None
    default_model: str = ""
    is_default: bool = False

    @field_validator("display_name", "api_key", "base_url", "default_model")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    @field_validator("available_models")
    @classmethod
    def _clean_models(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        seen: set[str] = set()
        cleaned: list[str] = []
        for item in value:
            name = str(item).strip()
            if name and name not in seen:
                seen.add(name)
                cleaned.append(name)
        return cleaned


class ProviderPreviewPayload(BaseModel):
    """Credentials to test and list models before saving a provider."""

    id: int | None = None
    provider_type: ProviderType
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


class ProviderOut(BaseModel):
    id: int
    provider_type: str
    display_name: str
    api_key: str  # masked, never the raw key
    has_api_key: bool
    base_url: str
    is_enabled: bool
    available_models: list[str] = Field(default_factory=list)
    default_model: str = ""
    is_default: bool = False
    updated_at: str


class TaskPayload(BaseModel):
    provider_id: int | None = None
    model_name: str = ""
    fallback_provider_id: int | None = None
    fallback_model_name: str = ""
    temperature: float = Field(default=config.DEFAULT_TEMPERATURE, ge=0.0, le=2.0)
    max_tokens: int = Field(default=config.DEFAULT_MAX_TOKENS, ge=1, le=1_000_000)

    @field_validator("model_name", "fallback_model_name")
    @classmethod
    def _strip_model(cls, value: str) -> str:
        return (value or "").strip()


class TaskOut(BaseModel):
    task_name: str
    label: str
    provider_id: int | None
    provider_type: str | None
    provider_display_name: str | None
    model_name: str
    fallback_provider_id: int | None = None
    fallback_provider_type: str | None = None
    fallback_provider_display_name: str | None = None
    fallback_model_name: str = ""
    temperature: float
    max_tokens: int
    updated_at: str


class TestRequest(BaseModel):
    model: str | None = None


class ScraperSettingsPayload(BaseModel):
    """Bounded so a typo cannot hammer a site or stall a job for hours."""

    fetch_batch_size: int = Field(ge=1, le=500)
    fetch_delay_seconds: float = Field(ge=0.0, le=10.0)
    fetch_max_consecutive_errors: int = Field(ge=1, le=20)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def mask_api_key(api_key: str | None) -> str:
    """``sk-abcdef1234`` -> ``****1234``. Never leaks the raw key."""
    key = (api_key or "").strip()
    if not key:
        return ""
    if len(key) <= 4:
        return MASK_PREFIX
    return f"{MASK_PREFIX}{key[-4:]}"


def _is_masked(value: str | None) -> bool:
    return bool(value) and value.strip().startswith(MASK_PREFIX)


def _parse_models(raw: Any) -> list[str]:
    """Decode the ``available_models`` JSON column defensively."""
    if isinstance(raw, list):
        return [str(item) for item in raw if isinstance(item, str)]
    try:
        parsed = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if isinstance(item, str)]


def _provider_row_to_out(row: sqlite3.Row) -> ProviderOut:
    raw_key = row["api_key"] or ""
    keys = row.keys()
    return ProviderOut(
        id=int(row["id"]),
        provider_type=row["provider_type"],
        display_name=row["display_name"],
        api_key=mask_api_key(raw_key),
        has_api_key=bool(raw_key),
        base_url=row["base_url"] or "",
        is_enabled=bool(row["is_enabled"]),
        available_models=_parse_models(row["available_models"] if "available_models" in keys else "[]"),
        default_model=(row["default_model"] or "") if "default_model" in keys else "",
        is_default=bool(row["is_default"]) if "is_default" in keys else False,
        updated_at=row["updated_at"],
    )


def _fetch_provider(conn: sqlite3.Connection, provider_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM provider_configs WHERE id = ?", (provider_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return row


def _task_row_to_out(row: sqlite3.Row) -> TaskOut:
    task_name = str(row["task_name"])
    keys = row.keys()
    return TaskOut(
        task_name=task_name,
        label=config.TASK_LABELS.get(task_name, task_name),
        provider_id=row["provider_id"],
        provider_type=row["provider_type"],
        provider_display_name=row["display_name"],
        model_name=row["model_name"] or "",
        fallback_provider_id=row["fallback_provider_id"] if "fallback_provider_id" in keys else None,
        fallback_provider_type=row["fallback_provider_type"] if "fallback_provider_type" in keys else None,
        fallback_provider_display_name=(
            row["fallback_display_name"] if "fallback_display_name" in keys else None
        ),
        fallback_model_name=(row["fallback_model_name"] or "") if "fallback_model_name" in keys else "",
        temperature=float(row["temperature"]),
        max_tokens=int(row["max_tokens"]),
        updated_at=row["updated_at"],
    )


TASK_SELECT = """
SELECT t.task_name, t.provider_id, t.model_name,
       t.fallback_provider_id, t.fallback_model_name,
       t.temperature, t.max_tokens, t.updated_at,
       p.provider_type, p.display_name,
       fp.provider_type AS fallback_provider_type,
       fp.display_name AS fallback_display_name
FROM task_models AS t
LEFT JOIN provider_configs AS p ON p.id = t.provider_id
LEFT JOIN provider_configs AS fp ON fp.id = t.fallback_provider_id
"""


# --------------------------------------------------------------------------
# Meta (keeps the frontend dropdowns in sync with the backend)
# --------------------------------------------------------------------------
@router.get("/meta")
def get_meta() -> dict[str, Any]:
    return {
        "provider_types": [
            {
                "value": ptype,
                "label": config.PROVIDER_LABELS.get(ptype, ptype),
                "default_base_url": config.DEFAULT_BASE_URLS.get(ptype, ""),
                "default_model": config.DEFAULT_MODELS.get(ptype, ""),
                "requires_api_key": ptype not in config.KEYLESS_PROVIDERS,
                **(
                    {"cli_available": describe_cli(ptype)["available"], "cli_path": describe_cli(ptype)["path"]}
                    if ptype in ("agy", "codex")
                    else {}
                ),
            }
            for ptype in config.PROVIDER_TYPES
        ],
        "cli_status": {
            "agy": describe_cli("agy"),
            "codex": describe_cli("codex"),
        },
        "tasks": [
            {"value": task, "label": config.TASK_LABELS.get(task, task)}
            for task in config.TASKS
        ],
    }


# --------------------------------------------------------------------------
# Scraper settings
# --------------------------------------------------------------------------
@router.get("/scraper")
def get_scraper_config() -> dict[str, Any]:
    return get_scraper_settings()


@router.put("/scraper")
def put_scraper_config(payload: ScraperSettingsPayload) -> dict[str, Any]:
    return save_scraper_settings(payload.model_dump())


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------
@router.get("/providers", response_model=list[ProviderOut])
def list_providers() -> list[ProviderOut]:
    with database.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM provider_configs ORDER BY id ASC"
        ).fetchall()
    return [_provider_row_to_out(row) for row in rows]


@router.post("/providers", response_model=ProviderOut, status_code=201)
def upsert_provider(payload: ProviderPayload) -> ProviderOut:
    now = database.utcnow()
    display_name = payload.display_name or config.PROVIDER_LABELS.get(
        payload.provider_type, payload.provider_type
    )
    base_url = payload.base_url
    if base_url is None or base_url == "":
        base_url = config.DEFAULT_BASE_URLS.get(payload.provider_type, "")

    models_json = json.dumps(payload.available_models or [], ensure_ascii=False)
    default_model = (payload.default_model or "").strip()

    with database.get_conn() as conn:
        is_default = bool(payload.is_default) and payload.is_enabled
        if payload.id is None and payload.is_enabled and default_model and not is_default:
            has_default = conn.execute(
                "SELECT 1 FROM provider_configs WHERE is_default = 1 AND is_enabled = 1 LIMIT 1"
            ).fetchone()
            if not has_default:
                is_default = True

        if is_default:
            conn.execute("UPDATE provider_configs SET is_default = 0")

        if payload.id is not None:
            existing = _fetch_provider(conn, payload.id)
            # An empty or masked key means "keep the stored one".
            if payload.api_key is None or payload.api_key == "" or _is_masked(payload.api_key):
                api_key = existing["api_key"] or ""
            else:
                api_key = payload.api_key
            # Omitting the field keeps the stored model list.
            if payload.available_models is None:
                models_json = existing["available_models"] or "[]"

            conn.execute(
                """
                UPDATE provider_configs
                   SET provider_type = ?, display_name = ?, api_key = ?,
                       base_url = ?, is_enabled = ?, available_models = ?,
                       default_model = ?, is_default = ?, updated_at = ?
                 WHERE id = ?
                """,
                (
                    payload.provider_type,
                    display_name,
                    api_key,
                    base_url,
                    1 if payload.is_enabled else 0,
                    models_json,
                    default_model,
                    1 if is_default else 0,
                    now,
                    payload.id,
                ),
            )
            row = _fetch_provider(conn, payload.id)
        else:
            cursor = conn.execute(
                """
                INSERT INTO provider_configs
                    (provider_type, display_name, api_key, base_url, is_enabled,
                     available_models, default_model, is_default, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.provider_type,
                    display_name,
                    payload.api_key or "",
                    base_url,
                    1 if payload.is_enabled else 0,
                    models_json,
                    default_model,
                    1 if is_default else 0,
                    now,
                ),
            )
            row = _fetch_provider(conn, int(cursor.lastrowid or 0))

    return _provider_row_to_out(row)


@router.post("/providers/preview")
async def preview_provider(payload: ProviderPreviewPayload) -> dict[str, Any]:
    """Test credentials and fetch available models before saving a provider."""
    api_key = payload.api_key or ""
    if payload.id is not None and (api_key == "" or _is_masked(api_key)):
        with database.get_conn() as conn:
            existing = _fetch_provider(conn, payload.id)
        api_key = existing["api_key"] or ""

    base_url = payload.base_url
    if base_url is None or base_url == "":
        base_url = config.DEFAULT_BASE_URLS.get(payload.provider_type, "")

    model = (payload.model or "").strip() or config.DEFAULT_MODELS.get(
        payload.provider_type, ""
    )

    try:
        provider = create_provider(
            provider_type=payload.provider_type,
            api_key=api_key,
            base_url=base_url,
        )
        result = await provider.test_connection(model=model or None)
    except LLMError as exc:
        return {
            "ok": False,
            "model": model,
            "models": [],
            "model_count": 0,
            "message": str(exc),
        }

    ok = bool(result.get("ok"))
    synced: list[str] = []
    if ok:
        try:
            synced = sorted({m for m in await provider.list_models() if m})
        except Exception:  # noqa: BLE001
            synced = []

    reported = synced or list(result.get("models") or [])
    return {
        "ok": ok,
        "model": result.get("model", model),
        "models": reported,
        "model_count": len(reported),
        "message": result.get("message", ""),
    }


@router.delete("/providers/{provider_id}")
def delete_provider(provider_id: int) -> dict[str, Any]:
    with database.get_conn() as conn:
        _fetch_provider(conn, provider_id)
        # Detach any task routed to this provider so routing stays consistent.
        conn.execute(
            "UPDATE task_models SET provider_id = NULL, updated_at = ? WHERE provider_id = ?",
            (database.utcnow(), provider_id),
        )
        conn.execute(
            "UPDATE task_models SET fallback_provider_id = NULL, updated_at = ? "
            "WHERE fallback_provider_id = ?",
            (database.utcnow(), provider_id),
        )
        conn.execute("DELETE FROM provider_configs WHERE id = ?", (provider_id,))
    return {"ok": True, "deleted_id": provider_id}


@router.post("/providers/{provider_id}/test")
async def test_provider(provider_id: int, payload: TestRequest | None = None) -> dict[str, Any]:
    with database.get_conn() as conn:
        row = _fetch_provider(conn, provider_id)

    model = (payload.model if payload and payload.model else "").strip()
    if not model:
        # Fall back to whatever the tasks already use for this provider.
        with database.get_conn() as conn:
            used = conn.execute(
                """
                SELECT model_name FROM task_models
                 WHERE provider_id = ? AND model_name <> ''
                 ORDER BY task_name LIMIT 1
                """,
                (provider_id,),
            ).fetchone()
        model = (used["model_name"] if used else "") or config.DEFAULT_MODELS.get(
            row["provider_type"], ""
        )

    try:
        provider = create_provider(
            provider_type=row["provider_type"],
            api_key=row["api_key"] or "",
            base_url=row["base_url"] or "",
        )
        result = await provider.test_connection(model=model or None)
    except LLMError as exc:
        return {
            "ok": False,
            "provider_id": provider_id,
            "model": model,
            "message": str(exc),
        }

    ok = bool(result.get("ok"))

    # Opportunistic model sync: a provider without a /models endpoint must not
    # make the connection test fail.
    synced: list[str] = []
    if ok:
        try:
            synced = sorted({m for m in await provider.list_models() if m})
        except Exception:  # noqa: BLE001 - never fatal for a test call
            synced = []
        if synced:
            with database.get_conn() as conn:
                conn.execute(
                    "UPDATE provider_configs SET available_models = ?, updated_at = ? "
                    "WHERE id = ?",
                    (json.dumps(synced, ensure_ascii=False), database.utcnow(), provider_id),
                )

    reported = synced or list(result.get("models") or [])
    return {
        "ok": ok,
        "provider_id": provider_id,
        "model": result.get("model", model),
        "message": result.get("message", ""),
        "models": reported,
        "model_count": len(reported),
        "models_synced": bool(synced),
    }


@router.post("/providers/{provider_id}/models/sync")
async def sync_provider_models(provider_id: int) -> dict[str, Any]:
    """Fetch the provider's model list and store it in ``available_models``."""
    with database.get_conn() as conn:
        row = _fetch_provider(conn, provider_id)

    try:
        provider = create_provider(
            provider_type=row["provider_type"],
            api_key=row["api_key"] or "",
            base_url=row["base_url"] or "",
        )
        models = await provider.list_models()
    except LLMError as exc:
        raise HTTPException(
            status_code=502, detail=f"Gagal mengambil daftar model: {exc}"
        ) from exc

    cleaned = sorted({str(item).strip() for item in models if str(item).strip()})
    if not cleaned:
        raise HTTPException(
            status_code=502,
            detail=(
                "Provider tidak mengembalikan model apa pun. Periksa API key, base URL, "
                "atau isi daftar model secara manual."
            ),
        )

    with database.get_conn() as conn:
        conn.execute(
            "UPDATE provider_configs SET available_models = ?, updated_at = ? WHERE id = ?",
            (json.dumps(cleaned, ensure_ascii=False), database.utcnow(), provider_id),
        )

    return {
        "ok": True,
        "provider_id": provider_id,
        "count": len(cleaned),
        "models": cleaned,
    }


# --------------------------------------------------------------------------
# Task routing
# --------------------------------------------------------------------------
@router.get("/tasks", response_model=list[TaskOut])
def list_tasks() -> list[TaskOut]:
    with database.get_conn() as conn:
        rows = conn.execute(
            TASK_SELECT + " ORDER BY CASE t.task_name "
            "WHEN 'translate' THEN 0 WHEN 'scrape_analysis' THEN 1 "
            "WHEN 'story_analysis' THEN 2 WHEN 'cover_prompt' THEN 3 ELSE 4 END"
        ).fetchall()
    return [_task_row_to_out(row) for row in rows]


@router.put("/tasks/{task_name}", response_model=TaskOut)
def update_task(task_name: TaskName, payload: TaskPayload) -> TaskOut:
    with database.get_conn() as conn:
        if payload.provider_id is not None:
            _fetch_provider(conn, payload.provider_id)
        if payload.fallback_provider_id is not None:
            _fetch_provider(conn, payload.fallback_provider_id)

        exists = conn.execute(
            "SELECT 1 FROM task_models WHERE task_name = ?", (task_name,)
        ).fetchone()
        now = database.utcnow()
        if exists is None:
            conn.execute(
                """
                INSERT INTO task_models
                    (task_name, provider_id, model_name, fallback_provider_id,
                     fallback_model_name, temperature, max_tokens, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_name,
                    payload.provider_id,
                    payload.model_name,
                    payload.fallback_provider_id,
                    payload.fallback_model_name,
                    payload.temperature,
                    payload.max_tokens,
                    now,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE task_models
                   SET provider_id = ?, model_name = ?, fallback_provider_id = ?,
                       fallback_model_name = ?, temperature = ?, max_tokens = ?,
                       updated_at = ?
                 WHERE task_name = ?
                """,
                (
                    payload.provider_id,
                    payload.model_name,
                    payload.fallback_provider_id,
                    payload.fallback_model_name,
                    payload.temperature,
                    payload.max_tokens,
                    now,
                    task_name,
                ),
            )

        row = conn.execute(
            TASK_SELECT + " WHERE t.task_name = ?", (task_name,)
        ).fetchone()

    return _task_row_to_out(row)
