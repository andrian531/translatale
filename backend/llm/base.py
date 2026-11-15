"""Provider interface and the task -> (provider, model) router."""

from __future__ import annotations

import re
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import config
import database

_REFUSAL_RE = re.compile(
    r"(?:\bi(?:'m| am) sorry,?\s+i (?:can(?:not|'t)|am unable to)\b"
    r"|\bi (?:can(?:not|'t)|am unable to) (?:translate|fulfill|assist with|process|complete)\b"
    r"|\bas an ai\b.*\b(?:cannot|can't|unable)\b"
    r"|\bviolates? (?:our |the )?(?:content|safety|usage) polic(?:y|ies)\b"
    r"|\bmaaf,?\s+saya tidak (?:dapat|bisa) menerjemahkan\b)",
    re.IGNORECASE,
)


def looks_like_refusal(text: str | None) -> bool:
    """Detect short safety/policy refusals without false-positives on story prose."""
    cleaned = (text or "").strip()
    if not cleaned or len(cleaned) > 600:
        return False
    return bool(_REFUSAL_RE.search(cleaned))


class LLMError(RuntimeError):
    """Raised when a provider call fails (network, auth, bad payload)."""


class TaskNotConfiguredError(LLMError):
    """Raised when a task has no usable provider/model routing yet."""


@dataclass
class LLMResponse:
    """Normalised result returned by every provider adapter."""

    text: str
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:  # convenience for prompt-building code
        return self.text


class BaseLLMProvider(ABC):
    """Common surface for all LLM adapters.

    Subclasses only implement the HTTP specifics; URL joining, defaults and
    error wrapping live here.
    """

    provider_type: str = "base"

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        timeout: float | None = None,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or "").strip() or self.default_base_url
        self.timeout = timeout if timeout is not None else config.HTTP_TIMEOUT

    # -- defaults ---------------------------------------------------------
    @property
    def default_base_url(self) -> str:
        return config.DEFAULT_BASE_URLS.get(self.provider_type, "")

    @property
    def default_model(self) -> str:
        return config.DEFAULT_MODELS.get(self.provider_type, "")

    @property
    def requires_api_key(self) -> bool:
        return self.provider_type not in config.KEYLESS_PROVIDERS

    # -- helpers ----------------------------------------------------------
    def url(self, path: str) -> str:
        """Join ``base_url`` with an API path, tolerating trailing slashes."""
        base = self.base_url.rstrip("/")
        if not base:
            raise LLMError(f"{self.provider_type}: base_url is not configured")
        return f"{base}/{path.lstrip('/')}"

    def _require_key(self) -> None:
        if self.requires_api_key and not self.api_key:
            raise LLMError(f"{self.provider_type}: API key is not configured")

    # -- contract ---------------------------------------------------------
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = config.DEFAULT_TEMPERATURE,
        max_tokens: int = config.DEFAULT_MAX_TOKENS,
    ) -> LLMResponse:
        """Send a single-turn prompt and return the normalised response."""

    @abstractmethod
    async def test_connection(self, model: str | None = None) -> dict[str, Any]:
        """Cheap credential/model check. Returns ``{"ok": bool, "message": str}``."""

    async def list_models(self) -> list[str]:
        """Return the provider's model IDs, sorted.

        Adapters that can enumerate models override this; the default raises so
        the caller can report "not supported" instead of silently returning [].
        """
        raise LLMError(f"{self.provider_type}: daftar model tidak didukung")


@dataclass
class ResolvedTask:
    """Everything needed to run one LLM call for a task."""

    task_name: str
    provider: BaseLLMProvider
    provider_id: int
    provider_type: str
    model: str
    temperature: float
    max_tokens: int


class TaskRouter:
    """Resolve ``task_name`` -> provider instance + model + parameters.

    Reads ``task_models`` joined with ``provider_configs`` from SQLite so the
    GUI can re-route a task without restarting the server.
    """

    def __init__(self, task_name: str, db_path: str | None = None) -> None:
        self.task_name = task_name
        self.db_path = db_path

    def _fetch(self) -> sqlite3.Row | None:
        with database.get_conn(self.db_path) as conn:
            return conn.execute(
                """
                SELECT t.task_name, t.provider_id, t.model_name, t.temperature,
                       t.max_tokens, p.provider_type, p.api_key, p.base_url,
                       p.is_enabled, p.display_name
                FROM task_models AS t
                LEFT JOIN provider_configs AS p ON p.id = t.provider_id
                WHERE t.task_name = ?
                """,
                (self.task_name,),
            ).fetchone()

    def _build_resolved(
        self,
        provider_id: int,
        provider_type: str,
        api_key: str | None,
        base_url: str | None,
        model_name: str,
        temperature: float,
        max_tokens: int,
    ) -> ResolvedTask:
        # Imported lazily: registry imports the provider modules, which import
        # this module.
        from llm.registry import create_provider

        provider = create_provider(
            provider_type=provider_type,
            api_key=api_key or "",
            base_url=base_url or "",
        )
        return ResolvedTask(
            task_name=self.task_name,
            provider=provider,
            provider_id=int(provider_id),
            provider_type=provider_type,
            model=model_name.strip(),
            temperature=float(temperature),
            max_tokens=int(max_tokens),
        )

    def _resolve_default_provider(
        self, temperature: float, max_tokens: int
    ) -> ResolvedTask | None:
        """Fall back to the provider marked ``is_default = 1`` when it has a ``default_model``."""
        with database.get_conn(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT id, provider_type, api_key, base_url, default_model
                FROM provider_configs
                WHERE is_default = 1 AND is_enabled = 1 AND trim(default_model) <> ''
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return self._build_resolved(
            provider_id=int(row["id"]),
            provider_type=row["provider_type"],
            api_key=row["api_key"],
            base_url=row["base_url"],
            model_name=row["default_model"],
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def resolve(self) -> ResolvedTask:
        row = self._fetch()
        if row is None:
            raise TaskNotConfiguredError(f"Unknown task: {self.task_name}")

        has_explicit = (
            row["provider_id"] is not None
            and bool(row["is_enabled"])
            and bool((row["model_name"] or "").strip())
        )
        if has_explicit:
            return self._build_resolved(
                provider_id=int(row["provider_id"]),
                provider_type=row["provider_type"],
                api_key=row["api_key"],
                base_url=row["base_url"],
                model_name=row["model_name"],
                temperature=float(row["temperature"]),
                max_tokens=int(row["max_tokens"]),
            )

        default_resolved = self._resolve_default_provider(
            temperature=float(row["temperature"]),
            max_tokens=int(row["max_tokens"]),
        )
        if default_resolved is not None:
            return default_resolved

        if row["provider_id"] is None:
            raise TaskNotConfiguredError(
                f"Task '{self.task_name}' has no provider assigned yet"
            )
        if not row["is_enabled"]:
            raise TaskNotConfiguredError(
                f"Provider '{row['display_name']}' for task '{self.task_name}' is disabled"
            )
        raise TaskNotConfiguredError(
            f"Task '{self.task_name}' has no model name configured"
        )

    def resolve_fallback(self) -> ResolvedTask | None:
        """Resolve the optional secondary/fallback model for this task, or None."""
        with database.get_conn(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT t.fallback_provider_id, t.fallback_model_name,
                       t.temperature, t.max_tokens,
                       p.provider_type, p.api_key, p.base_url, p.is_enabled
                FROM task_models AS t
                LEFT JOIN provider_configs AS p ON p.id = t.fallback_provider_id
                WHERE t.task_name = ?
                """,
                (self.task_name,),
            ).fetchone()
        if row is None or row["fallback_provider_id"] is None:
            return None
        if not row["is_enabled"] or not (row["fallback_model_name"] or "").strip():
            return None
        return self._build_resolved(
            provider_id=int(row["fallback_provider_id"]),
            provider_type=row["provider_type"],
            api_key=row["api_key"],
            base_url=row["base_url"],
            model_name=row["fallback_model_name"],
            temperature=float(row["temperature"]),
            max_tokens=int(row["max_tokens"]),
        )

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        **overrides: Any,
    ) -> LLMResponse:
        """Resolve the task and run one generation with its stored settings."""
        resolved = self.resolve()
        return await resolved.provider.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model=overrides.get("model", resolved.model),
            temperature=overrides.get("temperature", resolved.temperature),
            max_tokens=overrides.get("max_tokens", resolved.max_tokens),
        )
