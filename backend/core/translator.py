"""Chunked chapter translation with reference injection and rolling context."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from typing import Any, Awaitable, Callable

import database
from core.quality import deduplicate_raw_text, score_translation
from core.reference import load_reference, reference_to_prompt
from core.skills import load_editor_skill, load_skill
from llm.base import LLMError, ResolvedTask, TaskNotConfiguredError, TaskRouter, looks_like_refusal

logger = logging.getLogger(__name__)

TASK_NAME = "translate"

CHUNK_MAX_CHARS = 4500
ROLLING_CONTEXT_CHARS = 300
CHUNK_MAX_RETRIES = 3
CHUNK_RETRY_DELAY = 1.0

LANG_NAMES = {
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "en": "English",
    "id": "Indonesian",
}

TRANSLATE_SYSTEM_PROMPT = (
    "You are a professional literary translator working on web novels. "
    "Translate {source} into {target}. Rules: translate faithfully and completely; "
    "keep the paragraph breaks of the source; never leave {source} characters in the "
    "output; follow the glossary and character spellings exactly; output only the "
    "translation, with no notes or commentary."
)

TITLE_PROMPT = """Translate this chapter title into {target}. Output only the title.

Title: {title}
"""

CHUNK_PROMPT = """{reference}

[PREVIOUS CHUNK ENDING — continue smoothly, do not repeat it]
{rolling}

[SOURCE TEXT]
{text}
"""

APPLY_REFERENCE_SYSTEM_PROMPT = (
    "You are a professional literary editor working on web novel translations in {target}. "
    "Update ONLY character names, aliases, locations, and glossary/terms in the existing "
    "translation so they strictly match the [REFERENCE SHEET] (including exact 'Latin (Terjemahan)' "
    "forms when specified). Preserve the existing prose, sentence flow, and paragraph breaks; "
    "do not summarize, omit, or add commentary. Output only the updated {target} text."
)

APPLY_REFERENCE_PROMPT = """{reference}

[EXISTING TRANSLATION TO ALIGN WITH REFERENCE]
{text}
"""

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


class TranslationError(RuntimeError):
    """Raised when a chapter cannot be translated."""


def _lang_name(code: str) -> str:
    return LANG_NAMES.get((code or "").lower(), code or "the target language")


def _split_long_paragraph(paragraph: str, max_chars: int) -> list[str]:
    """Break an over-long paragraph on sentence boundaries."""
    sentences = re.split(r"(?<=[。！？!?；;\.])\s*", paragraph)
    pieces: list[str] = []
    buffer = ""
    for sentence in sentences:
        if not sentence:
            continue
        if len(buffer) + len(sentence) <= max_chars:
            buffer += sentence
            continue
        if buffer:
            pieces.append(buffer)
        while len(sentence) > max_chars:
            pieces.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        buffer = sentence
    if buffer:
        pieces.append(buffer)
    return pieces


def chunk_text(text: str, max_chars: int = CHUNK_MAX_CHARS) -> list[str]:
    """Split text into chunks on paragraph boundaries, never mid-sentence if avoidable."""
    if not text or not text.strip():
        return []

    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    if not paragraphs:
        paragraphs = [line.strip() for line in text.splitlines() if line.strip()]

    chunks: list[str] = []
    buffer = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if buffer:
                chunks.append(buffer)
                buffer = ""
            chunks.extend(_split_long_paragraph(paragraph, max_chars))
            continue
        candidate = f"{buffer}\n\n{paragraph}" if buffer else paragraph
        if len(candidate) <= max_chars:
            buffer = candidate
        else:
            chunks.append(buffer)
            buffer = paragraph
    if buffer:
        chunks.append(buffer)
    return chunks


async def _emit(callback: ProgressCallback | None, payload: dict[str, Any]) -> None:
    if callback is None:
        return
    result = callback(payload)
    if inspect.isawaitable(result):
        await result


def _tail(text: str, limit: int = ROLLING_CONTEXT_CHARS) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    return cleaned[-limit:] if len(cleaned) > limit else cleaned


async def _try_resolved_chunk(
    resolved: ResolvedTask,
    prompt: str,
    system_prompt: str,
    index: int,
    total_chunks: int,
) -> str:
    """Run one chunk against a single ResolvedTask with retries."""
    last_error: LLMError | None = None
    refused = False
    for attempt in range(CHUNK_MAX_RETRIES + 1):
        try:
            response = await resolved.provider.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                model=resolved.model,
                temperature=resolved.temperature,
                max_tokens=resolved.max_tokens,
            )
        except LLMError as exc:
            last_error = exc
            if attempt < CHUNK_MAX_RETRIES:
                await asyncio.sleep(CHUNK_RETRY_DELAY)
                continue
            raise TranslationError(
                f"Chunk {index}/{total_chunks} gagal setelah {CHUNK_MAX_RETRIES}x retry: {exc}"
            ) from exc

        text = (response.text or "").strip()
        if text and not looks_like_refusal(text):
            return text
        if text and looks_like_refusal(text):
            refused = True
            break
        if attempt < CHUNK_MAX_RETRIES:
            await asyncio.sleep(CHUNK_RETRY_DELAY)

    if refused:
        raise TranslationError(
            f"Chunk {index}/{total_chunks} ditolak oleh model ({resolved.model})"
        )
    if last_error is not None:
        raise TranslationError(
            f"Chunk {index}/{total_chunks} gagal setelah {CHUNK_MAX_RETRIES}x retry: {last_error}"
        )
    raise TranslationError(
        f"Chunk {index}/{total_chunks} kosong dari model ({resolved.model}) "
        f"setelah {CHUNK_MAX_RETRIES}x retry. Coba naikkan Max Tokens di Settings."
    )


async def _generate_chunk_with_retries(
    resolved: ResolvedTask,
    prompt: str,
    system_prompt: str,
    index: int,
    total_chunks: int,
    fallback: ResolvedTask | None = None,
) -> str:
    """Call primary LLM for a chunk; fall back to secondary model if primary fails/refuses."""
    try:
        return await _try_resolved_chunk(resolved, prompt, system_prompt, index, total_chunks)
    except TranslationError as primary_exc:
        if fallback is None:
            raise
        logger.warning(
            "Chunk %d/%d primary model (%s) gagal/menolak (%s); mencoba fallback (%s)",
            index,
            total_chunks,
            resolved.model,
            primary_exc,
            fallback.model,
        )
        return await _try_resolved_chunk(fallback, prompt, system_prompt, index, total_chunks)


async def translate_chapter(
    chapter_id: int,
    db_path: str | None = None,
    on_progress: ProgressCallback | None = None,
    max_chars: int = CHUNK_MAX_CHARS,
) -> dict[str, Any]:
    """Translate one chapter, store the result and score it."""
    with database.get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM chapters WHERE id = ?", (chapter_id,)).fetchone()
        if row is None:
            raise TranslationError(f"Bab {chapter_id} tidak ditemukan")
        chapter = dict(row)
        novel_row = conn.execute(
            "SELECT * FROM novels WHERE id = ?", (chapter["novel_id"],)
        ).fetchone()
    if novel_row is None:
        raise TranslationError(f"Novel untuk bab {chapter_id} tidak ditemukan")
    novel = dict(novel_row)

    raw = deduplicate_raw_text(chapter.get("raw_content") or "")
    if not raw.strip():
        raise TranslationError(f"Bab {chapter_id} belum punya isi raw")

    reference = load_reference(chapter["novel_id"], db_path)
    reference_block = reference_to_prompt(reference)

    router = TaskRouter(TASK_NAME, db_path=db_path)
    try:
        resolved = router.resolve()
    except TaskNotConfiguredError as exc:
        raise TranslationError(
            "Task 'translate' belum dikonfigurasi. Buka Settings → Model Routing "
            f"per Proses dan pilih provider + model untuk Translate. ({exc})"
        ) from exc
    fallback = router.resolve_fallback()

    source_lang = novel.get("source_lang") or "zh"
    target_lang = novel.get("target_lang") or "id"
    base_skill = load_skill(
        "translate",
        fallback=TRANSLATE_SYSTEM_PROMPT,
        source=_lang_name(source_lang),
        target=_lang_name(target_lang),
    )
    editor_skill = load_editor_skill(target_lang)
    system_prompt = f"{base_skill}\n\n{editor_skill}".strip() if editor_skill else base_skill

    chunks = chunk_text(raw, max_chars)
    if not chunks:
        raise TranslationError(f"Bab {chapter_id} tidak menghasilkan chunk")

    # -- title ---------------------------------------------------------
    title_translated = chapter.get("title_translated") or ""
    title = (chapter.get("title") or "").strip()
    if title:
        await _emit(
            on_progress,
            {"type": "title", "chapter_id": chapter_id},
        )
        try:
            title_response = await resolved.provider.generate(
                prompt=TITLE_PROMPT.format(target=_lang_name(target_lang), title=title),
                system_prompt=system_prompt,
                model=resolved.model,
                temperature=min(resolved.temperature, 0.3),
                max_tokens=800,
            )
            title_translated = re.sub(r"\s+", " ", title_response.text or "").strip()[:300]
        except LLMError:
            # A failed title must not lose the body translation.
            title_translated = title_translated or title

    # -- body ----------------------------------------------------------
    translated_chunks: list[str] = []
    rolling = ""
    for index, chunk in enumerate(chunks, start=1):
        await _emit(
            on_progress,
            {
                "type": "chunk",
                "chapter_id": chapter_id,
                "chunk_index": index,
                "chunk_total": len(chunks),
                "chunk_chars": len(chunk),
            },
        )
        prompt = CHUNK_PROMPT.format(
            reference=reference_block or "(no reference sheet yet)",
            rolling=rolling or "(start of chapter)",
            text=chunk,
        )
        text = await _generate_chunk_with_retries(
            resolved, prompt, system_prompt, index, len(chunks), fallback=fallback
        )
        translated_chunks.append(text)
        rolling = _tail(text)

    translated = "\n\n".join(translated_chunks)
    quality = score_translation(translated, source_lang, reference.get("terms") or [])

    now = database.utcnow()
    with database.get_conn(db_path) as conn:
        conn.execute(
            """
            UPDATE chapters
               SET translated_content = ?, title_translated = ?, quality_score = ?,
                   status = 'translated', updated_at = ?
             WHERE id = ?
            """,
            (translated, title_translated, quality["score"], now, chapter_id),
        )
        conn.execute(
            "UPDATE novels SET updated_at = ? WHERE id = ?", (now, chapter["novel_id"])
        )

    return {
        "chapter_id": chapter_id,
        "chapter_number": chapter["chapter_number"],
        "title": chapter.get("title") or "",
        "title_translated": title_translated,
        "chunks": len(chunks),
        "translated_chars": len(translated),
        "quality": quality,
        "provider_type": resolved.provider_type,
        "model": resolved.model,
    }


async def apply_reference_to_chapter(
    chapter_id: int,
    db_path: str | None = None,
    on_progress: ProgressCallback | None = None,
    max_chars: int = CHUNK_MAX_CHARS,
) -> dict[str, Any]:
    """Align an already-translated chapter with the latest reference sheet."""
    with database.get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM chapters WHERE id = ?", (chapter_id,)).fetchone()
        if row is None:
            raise TranslationError(f"Bab {chapter_id} tidak ditemukan")
        chapter = dict(row)
        novel_row = conn.execute(
            "SELECT * FROM novels WHERE id = ?", (chapter["novel_id"],)
        ).fetchone()
    if novel_row is None:
        raise TranslationError(f"Novel untuk bab {chapter_id} tidak ditemukan")
    novel = dict(novel_row)

    existing_translation = (chapter.get("translated_content") or "").strip()
    if not existing_translation:
        raise TranslationError(f"Bab {chapter_id} belum memiliki terjemahan")

    reference = load_reference(chapter["novel_id"], db_path)
    reference_block = reference_to_prompt(reference)
    if not reference_block.strip():
        raise TranslationError("Reference sheet masih kosong")

    router = TaskRouter(TASK_NAME, db_path=db_path)
    try:
        resolved = router.resolve()
    except TaskNotConfiguredError as exc:
        raise TranslationError(
            "Task 'translate' belum dikonfigurasi. Buka Settings → Model Routing "
            f"per Proses dan pilih provider + model untuk Translate. ({exc})"
        ) from exc
    fallback = router.resolve_fallback()

    source_lang = novel.get("source_lang") or "zh"
    target_lang = novel.get("target_lang") or "id"
    system_prompt = load_skill(
        "apply_reference",
        fallback=APPLY_REFERENCE_SYSTEM_PROMPT,
        target=_lang_name(target_lang),
    )

    chunks = chunk_text(existing_translation, max_chars)
    updated_chunks: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        await _emit(
            on_progress,
            {
                "type": "chunk",
                "chapter_id": chapter_id,
                "chunk_index": index,
                "chunk_total": len(chunks),
                "chunk_chars": len(chunk),
            },
        )
        prompt = APPLY_REFERENCE_PROMPT.format(reference=reference_block, text=chunk)
        text = await _generate_chunk_with_retries(
            resolved, prompt, system_prompt, index, len(chunks), fallback=fallback
        )
        updated_chunks.append(text)

    updated_translation = "\n\n".join(updated_chunks)
    quality = score_translation(
        updated_translation, source_lang, reference.get("terms") or []
    )

    now = database.utcnow()
    with database.get_conn(db_path) as conn:
        conn.execute(
            """
            UPDATE chapters
               SET translated_content = ?, quality_score = ?, updated_at = ?
             WHERE id = ?
            """,
            (updated_translation, quality["score"], now, chapter_id),
        )
        conn.execute(
            "UPDATE novels SET updated_at = ? WHERE id = ?", (now, chapter["novel_id"])
        )

    return {
        "chapter_id": chapter_id,
        "chapter_number": chapter["chapter_number"],
        "title": chapter.get("title") or "",
        "title_translated": chapter.get("title_translated") or "",
        "chunks": len(chunks),
        "translated_chars": len(updated_translation),
        "quality": quality,
        "provider_type": resolved.provider_type,
        "model": resolved.model,
    }
