"""Central configuration for the Translatale backend.

Everything path-related lives here so tests and future phases can point the
application at a different data directory without touching the rest of the code.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

#: Directory that holds the SQLite database and any generated artefacts.
DATA_DIR = Path(os.environ.get("TRANSLATALE_DATA_DIR") or (BASE_DIR / "data")).resolve()

#: Default database location (``data/translatale.db``).
DB_PATH = Path(os.environ.get("TRANSLATALE_DB_PATH") or (DATA_DIR / "translatale.db")).resolve()

#: The four routing slots the GUI exposes.
TASKS: tuple[str, ...] = ("translate", "scrape_analysis", "story_analysis", "cover_prompt")

TASK_LABELS: dict[str, str] = {
    "translate": "Translate",
    "scrape_analysis": "Scraping / Site Analysis",
    "story_analysis": "Analisa Cerita",
    "cover_prompt": "Cover Prompt Generator",
}

#: Supported provider types (order matters: it drives the frontend dropdown).
PROVIDER_TYPES: tuple[str, ...] = (
    "gemini",
    "openai",
    "openrouter",
    "deepseek",
    "anthropic",
    "custom",
    "ollama",
    "agy",
    "codex",
)

PROVIDER_LABELS: dict[str, str] = {
    "gemini": "Gemini",
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
    "deepseek": "DeepSeek",
    "anthropic": "Anthropic",
    "custom": "Custom (OpenAI-compatible)",
    "ollama": "Ollama",
    "agy": "Antigravity CLI (agy)",
    "codex": "OpenAI Codex CLI (codex)",
}

#: Base URLs pre-filled in the settings form. Users may override them.
DEFAULT_BASE_URLS: dict[str, str] = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "custom": "",
    "ollama": "http://localhost:11434/v1",
    "agy": "",
    "codex": "",
}

#: Model used by "Test Connection" when the user has not picked one yet.
DEFAULT_MODELS: dict[str, str] = {
    "gemini": "gemini-2.0-flash",
    "openai": "gpt-4o-mini",
    "openrouter": "openai/gpt-4o-mini",
    "deepseek": "deepseek-chat",
    "anthropic": "claude-3-5-haiku-latest",
    "custom": "gpt-3.5-turbo",
    "ollama": "llama3.2",
    "agy": "default",
    "codex": "default",
}

#: Providers that do not require an API key.
KEYLESS_PROVIDERS: frozenset[str] = frozenset({"ollama", "agy", "codex"})

#: Default routing values seeded for every task.
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 4096

#: Vite dev server origins allowed to call the API.
CORS_ORIGINS: list[str] = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

#: Defaults for the "scraper" row of ``app_settings``.
SCRAPER_SETTINGS_DEFAULTS: dict[str, float] = {
    "fetch_batch_size": 50,
    "fetch_delay_seconds": 1.0,
    "fetch_max_consecutive_errors": 3,
}

#: (min, max) accepted by ``PUT /api/settings/scraper``.
SCRAPER_SETTINGS_LIMITS: dict[str, tuple[float, float]] = {
    "fetch_batch_size": (1, 500),
    "fetch_delay_seconds": (0.0, 10.0),
    "fetch_max_consecutive_errors": (1, 20),
}

HTTP_TIMEOUT = 180.0


def get_db_path() -> Path:
    """Resolve the database path at call time (env override wins)."""
    override = os.environ.get("TRANSLATALE_DB_PATH")
    if override:
        return Path(override).resolve()
    return DB_PATH


def get_data_dir() -> Path:
    """Resolve the data directory at call time (env override wins)."""
    override = os.environ.get("TRANSLATALE_DATA_DIR")
    if override:
        return Path(override).resolve()
    return DATA_DIR


def ensure_data_dir() -> Path:
    """Create the data directory (and the DB parent) if missing."""
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    get_db_path().parent.mkdir(parents=True, exist_ok=True)
    return data_dir
