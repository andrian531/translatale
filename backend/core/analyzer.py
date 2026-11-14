"""Story analysis: extract characters/terms/guide and roll chapter summaries."""

from __future__ import annotations

import json
import re
from typing import Any

import database
from core.reference import (
    append_chapter_context,
    load_reference,
    merge_reference,
    save_reference,
)
from llm.base import LLMError, TaskNotConfiguredError, TaskRouter

TASK_NAME = "story_analysis"

ANALYSIS_SYSTEM_PROMPT = (
    "You are a literary analyst preparing a translation reference sheet for a "
    "web novel. You read source-language chapters and return structured JSON. "
    "Answer with JSON only — no prose, no markdown fences."
)

ANALYSIS_PROMPT = """Read the chapters below and build a reference sheet for a translator.

Return JSON with exactly these keys:
{{
  "characters": [
    {{"name": "source-script name", "romanized_name": "pinyin/romaji reading",
      "age": "", "gender": "", "aliases": ["..."],
      "relationships": "short description", "notes": "short description"}}
  ],
  "locations": [{{"source": "source-script place", "target": "translated place", "note": ""}}],
  "terms": [{{"source": "source-script term", "target": "translated term", "note": "why"}}],
  "translation_guide": "3-6 sentences: tone, register, naming rules, honorifics, punctuation"
}}

Rules:
- Only include characters, places and terms that actually appear in the text.
- `terms` are recurring nouns that must be translated consistently (cultivation
  realms, ranks, techniques, organizations, items).
- `romanized_name` must be a real reading, not a guess at the meaning.
- Keep every string short. Do not invent facts.

[EXISTING REFERENCE — extend it, do not drop entries]
{existing}

[CHAPTERS]
{chapters}
"""

SUMMARY_SYSTEM_PROMPT = (
    "You summarise novel chapters for a translator's rolling context. "
    "Answer with the summary only, no preamble."
)

SUMMARY_PROMPT = """Summarise this chapter in {target_chars} characters or fewer, in Indonesian.
Keep: who did what, where, and any plot turn a translator must know for the next chapter.
No bullet points, no title, plain prose.

Chapter title: {title}

{text}
"""

MAX_CHAPTERS = 3
MAX_CHARS_PER_CHAPTER = 6000
SUMMARY_TARGET_CHARS = 330


class AnalysisError(RuntimeError):
    """Raised when analysis cannot run (no chapters, bad model output, ...)."""


def _parse_json(text: str) -> dict[str, Any] | None:
    candidate = (text or "").strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z]*\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", candidate, re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None


def _as_entries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _load_chapters(
    novel_id: int,
    chapter_ids: list[int] | None,
    db_path: str | None,
    max_chapters: int,
) -> list[dict[str, Any]]:
    with database.get_conn(db_path) as conn:
        if chapter_ids:
            placeholders = ",".join("?" for _ in chapter_ids)
            rows = conn.execute(
                f"SELECT * FROM chapters WHERE novel_id = ? AND id IN ({placeholders}) "
                "ORDER BY chapter_number ASC",
                (novel_id, *chapter_ids),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM chapters WHERE novel_id = ? AND raw_content <> '' "
                "ORDER BY chapter_number ASC LIMIT ?",
                (novel_id, max_chapters),
            ).fetchall()
    return [dict(row) for row in rows]


def _render_chapters(chapters: list[dict[str, Any]], max_chars: int) -> str:
    blocks = []
    for chapter in chapters:
        body = (chapter.get("raw_content") or "")[:max_chars]
        blocks.append(
            f"--- Chapter {chapter.get('chapter_number')}: {chapter.get('title')} ---\n{body}"
        )
    return "\n\n".join(blocks)


async def analyze_novel(
    novel_id: int,
    chapter_ids: list[int] | None = None,
    db_path: str | None = None,
    max_chapters: int = MAX_CHAPTERS,
    max_chars_per_chapter: int = MAX_CHARS_PER_CHAPTER,
) -> dict[str, Any]:
    """Extract a reference sheet from raw chapters and merge it into the store."""
    chapters = _load_chapters(novel_id, chapter_ids, db_path, max_chapters)
    if not chapters:
        raise AnalysisError(
            "Tidak ada bab dengan isi raw untuk dianalisis. Fetch atau paste bab dulu."
        )

    existing = load_reference(novel_id, db_path)
    existing_payload = {
        "characters": existing.get("characters") or [],
        "locations": existing.get("locations") or [],
        "terms": existing.get("terms") or [],
        "translation_guide": existing.get("translation_guide") or "",
    }

    router = TaskRouter(TASK_NAME, db_path=db_path)
    try:
        resolved = router.resolve()
    except TaskNotConfiguredError as exc:
        raise AnalysisError(
            "Task 'story_analysis' belum dikonfigurasi. Buka Settings → Model Routing "
            f"per Proses dan pilih provider + model untuk Analisa Cerita. ({exc})"
        ) from exc

    prompt = ANALYSIS_PROMPT.format(
        existing=json.dumps(existing_payload, ensure_ascii=False)[:4000],
        chapters=_render_chapters(chapters, max_chars_per_chapter),
    )

    try:
        response = await resolved.provider.generate(
            prompt=prompt,
            system_prompt=ANALYSIS_SYSTEM_PROMPT,
            model=resolved.model,
            temperature=resolved.temperature,
            max_tokens=resolved.max_tokens,
        )
    except LLMError as exc:
        raise AnalysisError(f"Analisis cerita gagal: {exc}") from exc

    parsed = _parse_json(response.text)
    if parsed is None:
        raise AnalysisError("Model tidak mengembalikan JSON yang valid untuk analisa cerita.")

    incoming = {
        "characters": _as_entries(parsed.get("characters")),
        "locations": _as_entries(parsed.get("locations")),
        "terms": _as_entries(parsed.get("terms")),
        "translation_guide": str(parsed.get("translation_guide") or "").strip(),
    }

    merged = merge_reference(existing, incoming)
    saved = save_reference(novel_id, merged, db_path)

    return {
        "reference": saved,
        "chapters_analyzed": [
            {
                "id": chapter["id"],
                "chapter_number": chapter["chapter_number"],
                "title": chapter["title"],
            }
            for chapter in chapters
        ],
        "provider_type": resolved.provider_type,
        "model": resolved.model,
        "counts": {
            "characters": len(saved.get("characters") or []),
            "locations": len(saved.get("locations") or []),
            "terms": len(saved.get("terms") or []),
        },
    }


async def summarize_chapter_for_context(
    chapter_id: int,
    db_path: str | None = None,
    target_chars: int = SUMMARY_TARGET_CHARS,
    max_input_chars: int = 8000,
) -> dict[str, Any]:
    """Summarise one chapter and append it to the rolling context (max 5)."""
    with database.get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM chapters WHERE id = ?", (chapter_id,)).fetchone()
    if row is None:
        raise AnalysisError(f"Bab {chapter_id} tidak ditemukan")

    chapter = dict(row)
    text = (chapter.get("raw_content") or "").strip()
    if not text:
        raise AnalysisError(f"Bab {chapter_id} belum punya isi raw")

    router = TaskRouter(TASK_NAME, db_path=db_path)
    try:
        resolved = router.resolve()
    except TaskNotConfiguredError as exc:
        raise AnalysisError(
            "Task 'story_analysis' belum dikonfigurasi. Buka Settings → Model Routing "
            f"per Proses dan pilih provider + model untuk Analisa Cerita. ({exc})"
        ) from exc

    prompt = SUMMARY_PROMPT.format(
        target_chars=target_chars,
        title=chapter.get("title") or f"Chapter {chapter.get('chapter_number')}",
        text=text[:max_input_chars],
    )

    try:
        response = await resolved.provider.generate(
            prompt=prompt,
            system_prompt=SUMMARY_SYSTEM_PROMPT,
            model=resolved.model,
            temperature=min(resolved.temperature, 0.5),
            max_tokens=min(resolved.max_tokens, 800),
        )
    except LLMError as exc:
        raise AnalysisError(f"Ringkasan bab gagal: {exc}") from exc

    summary = re.sub(r"\s+", " ", response.text or "").strip()
    if not summary:
        raise AnalysisError("Model mengembalikan ringkasan kosong")
    summary = summary[: target_chars + 50]

    entry = {
        "chapter_id": chapter["id"],
        "chapter_number": chapter["chapter_number"],
        "title": chapter.get("title") or "",
        "summary": summary,
        "updated_at": database.utcnow(),
    }
    append_chapter_context(chapter["novel_id"], entry, db_path)
    return entry
