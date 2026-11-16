"""Story analysis: extract characters/terms/guide and roll chapter summaries."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import database
from core.reference import (
    append_chapter_context,
    load_reference,
    merge_reference,
    save_reference,
)
from core.skills import load_skill
from llm.base import LLMError, ResolvedTask, TaskNotConfiguredError, TaskRouter, looks_like_refusal

TASK_NAME = "story_analysis"

logger = logging.getLogger(__name__)

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
  "locations": [{{"source": "source-script place", "romanized": "pinyin/romaji/latin reading", "target": "{target_lang} place name", "note": ""}}],
  "terms": [{{"source": "source-script term", "romanized": "pinyin/romaji/latin reading", "target": "{target_lang} term", "note": "why"}}],
  "translation_guide": "3-6 sentences in {target_lang}: tone, register, naming rules, honorifics, punctuation"
}}

Rules:
- Only include characters, places and terms that actually appear in the text.
- `terms` are recurring nouns that must be translated consistently (cultivation
  realms, ranks, techniques, organizations, items).
- `locations.target`, `terms.target`, `relationships`, `notes`, `note`, and
  `translation_guide` MUST be written in {target_lang}. Do NOT output English
  translations or English guide examples when {target_lang} is not English.
- `romanized_name` and `romanized` (on locations & terms) must be a real reading
  in Latin letters (pinyin/romaji/Korean romanization), not a guess at the meaning.
- Keep every string short. Do not invent facts.

[EXISTING REFERENCE — extend it, do not drop entries]
{existing}

[CHAPTERS]
{chapters}
"""

NEW_ENTITIES_PROMPT = """A translator already has the reference sheet below. Read the
following chapter and extract ONLY what is new in it.

Return JSON with exactly these keys:
{{
  "characters": [
    {{"name": "source-script name", "romanized_name": "pinyin/romaji reading",
      "age": "", "gender": "", "aliases": ["..."],
      "relationships": "short description", "notes": "short description"}}
  ],
  "locations": [{{"source": "source-script place", "romanized": "pinyin/romaji/latin reading", "target": "{target_lang} place name", "note": ""}}],
  "terms": [{{"source": "source-script term", "romanized": "pinyin/romaji/latin reading", "target": "{target_lang} term", "note": "why"}}]
}}

Rules:
- Return ONLY entries that are not in the existing reference yet, plus aliases or
  relationships of a character that is already listed but lacks them.
- `locations.target`, `terms.target`, `relationships`, `notes`, and `note` MUST
  be written in {target_lang}. Do NOT output English translations when
  {target_lang} is not English.
- Never repeat an existing `name` or `source`. If an entry only needs a new alias or
  relationship, return that same `name`/`source` with just the missing field filled.
- Do not rename, re-translate or contradict anything already in the reference.
- Return empty lists when the chapter adds nothing. Never invent facts.
- Keep every string short.

[EXISTING REFERENCE]
{existing}

[CHAPTER — Chapter {number}: {title}]
{text}
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
    if not candidate:
        return None
    # Strip reasoning blocks that thinking models sometimes emit before JSON.
    candidate = re.sub(r"<think>.*?</think>", "", candidate, flags=re.DOTALL | re.IGNORECASE).strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", candidate, re.DOTALL | re.IGNORECASE)
    if fence:
        candidate = fence.group(1).strip()
    elif candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z]*\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate).strip()

    for attempt in (candidate,):
        try:
            parsed = json.loads(attempt)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{.*\}", candidate, re.DOTALL)
    if not match:
        return None
    raw_obj = match.group(0)
    for attempt in (raw_obj, re.sub(r",\s*([}\]])", r"\1", raw_obj)):
        try:
            parsed = json.loads(attempt)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            continue
    return None


def _as_entries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


_TARGET_LANG_NAMES = {
    "id": "Indonesian",
    "en": "English",
    "ms": "Malay",
}


def _novel_target_lang(novel_id: int, db_path: str | None) -> str:
    with database.get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT target_lang FROM novels WHERE id = ?", (novel_id,)
        ).fetchone()
    code = (row["target_lang"] if row else None) or "id"
    return _TARGET_LANG_NAMES.get(code.lower(), code)


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


async def _generate_analysis_with_fallback(
    resolved: ResolvedTask,
    fallback: ResolvedTask | None,
    *,
    prompt: str,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    expect_json: bool = False,
) -> tuple[str, dict[str, Any] | None, ResolvedTask]:
    """Run an analysis LLM call, falling back to secondary model on error/refusal/bad JSON."""
    candidates = [resolved] + ([fallback] if fallback is not None else [])
    last_error: LLMError | None = None
    last_text = ""
    last_candidate = resolved

    for index, candidate in enumerate(candidates):
        last_candidate = candidate
        try:
            response = await candidate.provider.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                model=candidate.model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except LLMError as exc:
            last_error = exc
            if index + 1 < len(candidates):
                logger.warning(
                    "Analysis primary model (%s) error (%s); trying fallback (%s)",
                    candidate.model,
                    exc,
                    candidates[index + 1].model,
                )
                continue
            raise

        last_text = response.text or ""
        if not last_text.strip() or looks_like_refusal(last_text):
            if index + 1 < len(candidates):
                logger.warning(
                    "Analysis primary model (%s) empty/refused; trying fallback (%s)",
                    candidate.model,
                    candidates[index + 1].model,
                )
                continue
            return last_text, None, candidate

        if expect_json:
            parsed = _parse_json(last_text)
            if parsed is not None:
                return last_text, parsed, candidate
            if index + 1 < len(candidates):
                logger.warning(
                    "Analysis primary model (%s) invalid JSON; trying fallback (%s)",
                    candidate.model,
                    candidates[index + 1].model,
                )
                continue
            return last_text, None, candidate

        return last_text, None, candidate

    if last_error is not None:
        raise last_error
    return last_text, None, last_candidate


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

    fallback = router.resolve_fallback()

    prompt = ANALYSIS_PROMPT.format(
        target_lang=_novel_target_lang(novel_id, db_path),
        existing=json.dumps(existing_payload, ensure_ascii=False)[:4000],
        chapters=_render_chapters(chapters, max_chars_per_chapter),
    )

    try:
        raw_text, parsed, used = await _generate_analysis_with_fallback(
            resolved,
            fallback,
            prompt=prompt,
            system_prompt=load_skill("story_analysis", fallback=ANALYSIS_SYSTEM_PROMPT),
            temperature=resolved.temperature,
            max_tokens=resolved.max_tokens,
            expect_json=True,
        )
    except LLMError as exc:
        raise AnalysisError(f"Analisis cerita gagal: {exc}") from exc

    if parsed is None:
        raw_preview = re.sub(r"\s+", " ", raw_text.strip())[:180]
        logger.warning(
            "analyze_novel invalid JSON from model %s: %r",
            used.model,
            raw_text[:500],
        )
        if not raw_preview:
            raise AnalysisError(
                f"Model ({used.model}) mengembalikan respons kosong untuk analisa cerita. "
                "Coba naikkan Max Tokens di Settings atau ganti model."
            )
        raise AnalysisError(
            f"Model ({used.model}) tidak mengembalikan JSON yang valid untuk analisa cerita: "
            f"{raw_preview}"
        )

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


async def update_reference_from_chapter(
    chapter_id: int,
    db_path: str | None = None,
    max_input_chars: int = 8000,
) -> dict[str, int]:
    """Extract only the *new* entities a single chapter introduces.

    Called from the translation pipeline before a chapter is translated, so the
    characters/terms that first appear in that chapter are already in the prompt
    used to translate it. Never raises: a missing task, a provider error or bad
    JSON all degrade to "nothing new found".
    """
    counts = {"characters_added": 0, "locations_added": 0, "terms_added": 0}

    with database.get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM chapters WHERE id = ?", (chapter_id,)).fetchone()
    if row is None:
        return counts

    chapter = dict(row)
    text = (chapter.get("raw_content") or "").strip()
    if not text:
        return counts

    router = TaskRouter(TASK_NAME, db_path=db_path)
    try:
        resolved = router.resolve()
    except TaskNotConfiguredError:
        # Auto-update is a bonus; translation must still run.
        return counts
    fallback = router.resolve_fallback()

    existing = load_reference(chapter["novel_id"], db_path)
    existing_payload = {
        "characters": existing.get("characters") or [],
        "locations": existing.get("locations") or [],
        "terms": existing.get("terms") or [],
    }

    prompt = NEW_ENTITIES_PROMPT.format(
        target_lang=_novel_target_lang(chapter["novel_id"], db_path),
        existing=json.dumps(existing_payload, ensure_ascii=False)[:4000],
        number=chapter.get("chapter_number"),
        title=chapter.get("title") or "",
        text=text[:max_input_chars],
    )

    try:
        _, parsed, _ = await _generate_analysis_with_fallback(
            resolved,
            fallback,
            prompt=prompt,
            system_prompt=load_skill("story_analysis", fallback=ANALYSIS_SYSTEM_PROMPT),
            temperature=min(resolved.temperature, 0.3),
            max_tokens=min(resolved.max_tokens, 2000),
            expect_json=True,
        )
    except LLMError as exc:
        logger.warning(
            "Auto-update referensi bab %s dilewati (LLM error): %s", chapter_id, exc
        )
        return counts

    if parsed is None:
        logger.warning(
            "Auto-update referensi bab %s dilewati: model tidak mengembalikan JSON valid",
            chapter_id,
        )
        return counts

    incoming = {
        "characters": _as_entries(parsed.get("characters")),
        "locations": _as_entries(parsed.get("locations")),
        "terms": _as_entries(parsed.get("terms")),
        # The guide is written by the full analysis pass, not per chapter.
        "translation_guide": "",
    }

    merged = merge_reference(existing, incoming)
    for field in ("characters", "locations", "terms"):
        counts[f"{field}_added"] = max(
            0, len(merged.get(field) or []) - len(existing.get(field) or [])
        )

    if any(counts.values()):
        save_reference(chapter["novel_id"], merged, db_path)

    return counts


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

    fallback = router.resolve_fallback()

    prompt = SUMMARY_PROMPT.format(
        target_chars=target_chars,
        title=chapter.get("title") or f"Chapter {chapter.get('chapter_number')}",
        text=text[:max_input_chars],
    )

    try:
        raw_text, _, _ = await _generate_analysis_with_fallback(
            resolved,
            fallback,
            prompt=prompt,
            system_prompt=load_skill("chapter_summary", fallback=SUMMARY_SYSTEM_PROMPT),
            temperature=min(resolved.temperature, 0.5),
            max_tokens=min(resolved.max_tokens, 800),
            expect_json=False,
        )
    except LLMError as exc:
        raise AnalysisError(f"Ringkasan bab gagal: {exc}") from exc

    summary = re.sub(r"\s+", " ", raw_text).strip()
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


LOCALIZE_SYSTEM_PROMPT = (
    "You are a professional literary translator and localization editor. "
    "Translate all target/note/relationships/notes/translation_guide fields in the "
    "provided reference JSON into {target_lang}. Preserve all source/name/romanized fields. "
    "Answer with valid JSON only — no prose, no markdown fences."
)

LOCALIZE_PROMPT = """Convert the reference sheet below so that every `target`, `note`, `relationships`, `notes`, and `translation_guide` is written in {target_lang}.

[REFERENCE SHEET]
{reference_json}
"""


async def localize_reference(novel_id: int, db_path: str | None = None) -> dict[str, Any]:
    """Translate existing reference sheet entries into the novel's target language."""
    existing = load_reference(novel_id, db_path)
    has_content = any(
        [
            existing.get("characters"),
            existing.get("locations"),
            existing.get("terms"),
            (existing.get("translation_guide") or "").strip(),
        ]
    )
    if not has_content:
        return existing

    target_lang = _novel_target_lang(novel_id, db_path)
    router = TaskRouter(TASK_NAME, db_path=db_path)
    try:
        resolved = router.resolve()
    except TaskNotConfiguredError as exc:
        raise AnalysisError(
            "Task 'story_analysis' belum dikonfigurasi. Buka Settings → Model Routing "
            f"per Proses untuk memilih model analisa. ({exc})"
        ) from exc
    fallback = router.resolve_fallback()

    payload_obj = {
        "characters": existing.get("characters") or [],
        "locations": existing.get("locations") or [],
        "terms": existing.get("terms") or [],
        "translation_guide": existing.get("translation_guide") or "",
    }
    prompt = LOCALIZE_PROMPT.format(
        target_lang=target_lang,
        reference_json=json.dumps(payload_obj, ensure_ascii=False, indent=2),
    )
    system_prompt = load_skill(
        "localize_reference",
        fallback=LOCALIZE_SYSTEM_PROMPT,
        target_lang=target_lang,
    )

    try:
        raw_text, _used = await _generate_analysis_with_fallback(
            resolved,
            fallback,
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max(resolved.max_tokens, 3000),
            expect_json=True,
        )
    except LLMError as exc:
        raise AnalysisError(f"Lokalisasi referensi gagal: {exc}") from exc

    parsed = _parse_json_object(raw_text)

    def _merge_localized_items(orig_list: list[dict[str, Any]], new_list: Any, key_field: str, fields: tuple[str, ...]) -> list[dict[str, Any]]:
        if not isinstance(new_list, list):
            return orig_list
        by_key: dict[str, dict[str, Any]] = {}
        for item in new_list:
            if isinstance(item, dict):
                k = str(item.get(key_field) or "").strip()
                if k:
                    by_key[k] = item
        merged: list[dict[str, Any]] = []
        for idx, orig in enumerate(orig_list):
            copy = dict(orig)
            k = str(orig.get(key_field) or "").strip()
            match = by_key.get(k) or (new_list[idx] if idx < len(new_list) and isinstance(new_list[idx], dict) else None)
            if match:
                for f in fields:
                    val = str(match.get(f) or "").strip()
                    if val:
                        copy[f] = val
            merged.append(copy)
        return merged

    updated = {
        "characters": _merge_localized_items(
            existing.get("characters") or [],
            parsed.get("characters"),
            "name",
            ("relationships", "notes"),
        ),
        "locations": _merge_localized_items(
            existing.get("locations") or [],
            parsed.get("locations"),
            "source",
            ("target", "note"),
        ),
        "terms": _merge_localized_items(
            existing.get("terms") or [],
            parsed.get("terms"),
            "source",
            ("target", "note"),
        ),
        "translation_guide": str(parsed.get("translation_guide") or "").strip()
        or (existing.get("translation_guide") or ""),
        "chapter_context": existing.get("chapter_context") or [],
    }
    return save_reference(novel_id, updated, db_path)
