"""Text quality helpers: raw-text de-duplication and translation scoring."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Iterable

from core.reference import format_term_target

#: Han, Hiragana, Katakana, Hangul and CJK compatibility ideographs.
CJK_RE = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af\uf900-\ufaff]"
)

#: Languages whose script must not survive into an id/en translation.
CJK_SOURCE_LANGS = frozenset({"zh", "ja", "ko", "chinese", "japanese", "korean"})

SIMILARITY_THRESHOLD = 0.90


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def _similar(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _split_paragraphs(text: str) -> list[str]:
    """Split on blank lines, falling back to single newlines."""
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    if len(blocks) <= 1:
        blocks = [line.strip() for line in text.splitlines() if line.strip()]
    return blocks


def deduplicate_raw_text(text: str) -> str:
    """Strip the half-chapter duplication that copy-paste scraping produces.

    Three shapes are handled: the whole text repeated twice, a repeated tail
    block, and consecutive identical paragraphs. Anything that is not a clear
    duplicate is returned untouched — losing real content is worse than keeping
    a repeated paragraph.
    """
    if not text or not text.strip():
        return ""

    paragraphs = _split_paragraphs(text)

    # 1. Collapse consecutive identical paragraphs.
    collapsed: list[str] = []
    for paragraph in paragraphs:
        if collapsed and _normalize(collapsed[-1]) == _normalize(paragraph):
            continue
        collapsed.append(paragraph)
    paragraphs = collapsed

    # 2. Whole text duplicated: A + A (or A + A with a small drift).
    if len(paragraphs) >= 4:
        half = len(paragraphs) // 2
        first = _normalize("".join(paragraphs[:half]))
        second = _normalize("".join(paragraphs[half : half * 2]))
        if _similar(first, second) >= SIMILARITY_THRESHOLD:
            paragraphs = paragraphs[:half]

    # 3. Repeated tail: the last k paragraphs repeat the first k.
    if len(paragraphs) >= 4:
        for k in range(len(paragraphs) // 2, 0, -1):
            head = _normalize("".join(paragraphs[:k]))
            tail = _normalize("".join(paragraphs[-k:]))
            if _similar(head, tail) >= SIMILARITY_THRESHOLD:
                paragraphs = paragraphs[:-k]
                break

    # 4. Single giant paragraph duplicated in place.
    if len(paragraphs) == 1 and len(paragraphs[0]) > 200:
        body = paragraphs[0]
        half = len(body) // 2
        if _similar(_normalize(body[:half]), _normalize(body[half:])) >= SIMILARITY_THRESHOLD:
            paragraphs = [body[:half].strip()]

    return "\n\n".join(paragraphs).strip()


def _grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def score_translation(
    translated_text: str,
    source_lang: str = "zh",
    terms: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Score a translation 0-100: CJK cleanliness (50) + term compliance (50).

    ``terms`` entries are ``{"source": ..., "target": ...}``. A term counts as
    relevant when either side appears in the translation; it is compliant when
    the target is used and the source is gone.
    """
    text = translated_text or ""
    stripped = re.sub(r"\s+", "", text)
    total_chars = len(stripped)

    cjk_chars = len(CJK_RE.findall(stripped))
    cjk_ratio = (cjk_chars / total_chars) if total_chars else 0.0

    if source_lang not in CJK_SOURCE_LANGS:
        # Nothing to clean up when the source script is Latin.
        cleanliness = 50.0
    elif cjk_ratio <= 0.01:
        cleanliness = 50.0
    else:
        cleanliness = max(0.0, 50.0 - (cjk_ratio - 0.01) * 400.0)

    relevant: list[tuple[str, str]] = []
    for term in terms or []:
        source = str(term.get("source") or "").strip()
        target = format_term_target(term)
        if not target:
            continue
        if (source and source in text) or target in text:
            relevant.append((source, target))

    violations: list[str] = []
    if not relevant:
        compliance = 50.0
    else:
        compliant = 0
        for source, target in relevant:
            if target in text and (not source or source not in text):
                compliant += 1
            else:
                violations.append(source or target)
        compliance = 50.0 * compliant / len(relevant)

    score = round(cleanliness + compliance, 1)
    return {
        "score": score,
        "grade": _grade(score),
        "cjk_ratio": round(cjk_ratio, 4),
        "cjk_cleanliness": round(cleanliness, 1),
        "term_compliance": round(compliance, 1),
        "terms_checked": len(relevant),
        "term_violations": violations[:20],
        "characters": total_chars,
    }
