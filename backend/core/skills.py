"""Markdown skill loader for LLM system prompts."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

_EDITOR_SKILL_MAP = {
    "id": "editor_id",
    "indonesian": "editor_id",
    "en": "editor_en",
    "english": "editor_en",
}


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].strip()
    return text.strip()


@lru_cache(maxsize=32)
def _read_skill_file(name: str) -> str | None:
    path = SKILLS_DIR / f"{name}.md"
    if not path.is_file():
        return None
    return _strip_frontmatter(path.read_text(encoding="utf-8"))


def clear_skill_cache() -> None:
    """Reset cached skill files (useful in tests)."""
    _read_skill_file.cache_clear()


def load_skill(name: str, fallback: str = "", **vars: Any) -> str:
    """Load a markdown skill from backend/skills/<name>.md and format variables."""
    template = _read_skill_file(name)
    if template is None:
        template = fallback
    if not template:
        return ""
    return template.format(**vars) if vars else template


def load_editor_skill(target_lang: str) -> str:
    """Load the language-specific copyeditor skill if available."""
    key = (target_lang or "").strip().lower()
    skill_name = _EDITOR_SKILL_MAP.get(key)
    if not skill_name:
        return ""
    return _read_skill_file(skill_name) or ""
