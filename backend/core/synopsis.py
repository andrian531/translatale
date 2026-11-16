"""Synopsis translation: at project creation and the "perbaiki sinopsis" pass."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

import database
from core.quality import CJK_RE
from core.reference import load_reference, reference_to_prompt
from core.skills import load_skill
from core.translator import LANG_NAMES
from llm.base import LLMError, TaskNotConfiguredError, TaskRouter

TASK_NAME = "translate"

#: Project creation must not hang indefinitely on a slow provider.
METADATA_TIMEOUT = 60.0

CJK_LANGS = frozenset({"zh", "ja", "ko", "chinese", "japanese", "korean"})

SYSTEM_PROMPT = (
    "You are a professional literary translator working on web novels. "
    "Translate {source} into {target}. Keep the meaning and tone, keep paragraph "
    "breaks, never leave {source} characters in the output, and output only the "
    "translation with no notes."
)

TITLE_PROMPT = """Translate this novel title into {target}.
Output only the translated title, without quotes.

Title: {title}
"""

SYNOPSIS_PROMPT = """Translate this novel synopsis into {target}.
Keep the tone and the paragraph breaks. Output only the translation.

Synopsis:
{synopsis}
"""

CONCISE_SYNOPSIS_PROMPT = """Summarize and translate this novel synopsis into {target} in 2-4 clear, engaging sentences.
Ignore website ads, author notes, tags, and promotional URLs. Output only the translated summary.

Synopsis:
{synopsis}
"""

REFINE_PROMPT = """Rewrite the synopsis translation below so it reads naturally in {target}.

Rules:
- Keep every plot point of the original synopsis.
- Fix grammar, flow and sentence order — this is a polish pass, not a new summary.
- Use the glossary and character spellings exactly as given.
- Keep the length close to the draft. Output only the final synopsis.

{reference}

[ORIGINAL SYNOPSIS — {source}]
{original}

[PREVIOUS DRAFT — {target}]
{draft}
"""


class SynopsisError(RuntimeError):
    """The model returned nothing usable."""


def _lang_name(code: str | None, fallback: str) -> str:
    return LANG_NAMES.get((code or "").lower(), fallback)


def _needs_translation(text: str, source_lang: str) -> bool:
    """Skip text that is already Latin-script for a CJK source.

    A zh/ja/ko project whose title is pure Latin was typed that way on purpose
    (or scraped as a romanised title) — translating it burns tokens for nothing.
    """
    text = (text or "").strip()
    if not text:
        return False
    if (source_lang or "").lower() in CJK_LANGS and not CJK_RE.search(text):
        return False
    return True


async def _generate(resolved: Any, prompt: str, system: str, max_tokens: int) -> str:
    response = await resolved.provider.generate(
        prompt=prompt,
        system_prompt=system,
        model=resolved.model,
        temperature=min(resolved.temperature, 0.4),
        max_tokens=max_tokens,
    )
    return (response.text or "").strip()


async def translate_metadata(
    title: str,
    synopsis: str,
    source_lang: str = "zh",
    target_lang: str = "id",
    db_path: str | None = None,
    need_title: bool = True,
    concise_synopsis: bool = False,
) -> dict[str, str]:
    """Best-effort title/synopsis translation for a newly created project.

    Never raises: a missing ``translate`` task or a provider error simply leaves
    the fields empty so project creation still succeeds.
    """
    result = {"title_translated": "", "synopsis_translated": ""}
    if not _needs_translation(title, source_lang) and not _needs_translation(
        synopsis, source_lang
    ):
        return result

    try:
        resolved = TaskRouter(TASK_NAME, db_path=db_path).resolve()
    except TaskNotConfiguredError:
        return result

    system = load_skill(
        "synopsis",
        fallback=SYSTEM_PROMPT,
        source=_lang_name(source_lang, "the source language"),
        target=_lang_name(target_lang, "the target language"),
    )
    target = _lang_name(target_lang, "the target language")

    async def _translate_title() -> str:
        try:
            text = await asyncio.wait_for(
                _generate(
                    resolved,
                    TITLE_PROMPT.format(target=target, title=title.strip()),
                    system,
                    800,
                ),
                timeout=METADATA_TIMEOUT,
            )
            return re.sub(r"\s+", " ", text)[:300]
        except (LLMError, asyncio.TimeoutError) as exc:
            logger.warning("translate_metadata title failed: %s", exc)
            return ""

    async def _translate_synopsis() -> str:
        prompt_tpl = CONCISE_SYNOPSIS_PROMPT if concise_synopsis else SYNOPSIS_PROMPT
        max_tok = 900 if concise_synopsis else 1500
        try:
            return await asyncio.wait_for(
                _generate(
                    resolved,
                    prompt_tpl.format(target=target, synopsis=synopsis.strip()),
                    system,
                    max_tok,
                ),
                timeout=METADATA_TIMEOUT,
            )
        except (LLMError, asyncio.TimeoutError) as exc:
            logger.warning("translate_metadata synopsis failed: %s", exc)
            return ""

    run_title = need_title and _needs_translation(title, source_lang)
    run_synopsis = _needs_translation(synopsis, source_lang)

    if run_title and run_synopsis:
        t_res, s_res = await asyncio.gather(_translate_title(), _translate_synopsis())
        result["title_translated"] = t_res
        result["synopsis_translated"] = s_res
    elif run_title:
        result["title_translated"] = await _translate_title()
    elif run_synopsis:
        result["synopsis_translated"] = await _translate_synopsis()

    return result


async def refine_synopsis(novel_id: int, db_path: str | None = None) -> str:
    """Polish the stored synopsis translation using the reference sheet.

    Returns the new ``synopsis_translated``. Raises
    :class:`TaskNotConfiguredError` when routing is not set up and
    :class:`SynopsisError` when the model produces nothing.
    """
    with database.get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM novels WHERE id = ?", (novel_id,)).fetchone()
    if row is None:
        raise SynopsisError(f"Novel {novel_id} tidak ditemukan")

    novel = dict(row)
    reference = load_reference(novel_id, db_path)
    reference_block = reference_to_prompt(reference) or "(no reference sheet yet)"

    resolved = TaskRouter(TASK_NAME, db_path=db_path).resolve()

    system = load_skill(
        "synopsis",
        fallback=SYSTEM_PROMPT,
        source=_lang_name(novel.get("source_lang"), "the source language"),
        target=_lang_name(novel.get("target_lang"), "the target language"),
    )
    prompt = REFINE_PROMPT.format(
        target=_lang_name(novel.get("target_lang"), "the target language"),
        source=_lang_name(novel.get("source_lang"), "the source language"),
        reference=reference_block,
        original=(novel.get("synopsis") or "").strip(),
        draft=(novel.get("synopsis_translated") or "").strip() or "(no draft yet)",
    )

    try:
        text = await _generate(resolved, prompt, system, 1500)
    except LLMError as exc:
        raise SynopsisError(f"Gagal memperbaiki sinopsis: {exc}") from exc

    if not text:
        raise SynopsisError("Model mengembalikan sinopsis kosong.")

    with database.get_conn(db_path) as conn:
        conn.execute(
            "UPDATE novels SET synopsis_translated = ?, updated_at = ? WHERE id = ?",
            (text, database.utcnow(), novel_id),
        )
    return text
