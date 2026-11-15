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


_URL_RE = re.compile(r"(?:https?://\S+|www\.[a-z0-9-]+(?:\.[a-z]{2,})+)", re.IGNORECASE)
_ZH_PROMO_RE = re.compile(
    r"(记住本站|最新章节|无弹窗|笔趣阁|请收藏|加入书签|投推荐票|下载.{0,12}(?:APP|客户端)|本章未完|点击下一页|继续阅读|首发域名|手机版阅读)"
)
_TRANS_PROMO_RE = re.compile(
    r"\b(?:baca\s+bab\s+terbaru|kunjungi\s+situs|bookmark\s+situs|ingat\s+nama\s+domain|"
    r"tanpa\s+pop-?up|update\s+tercepat|klik\s+untuk\s+melanjutkan|bab\s+ini\s+belum\s+selesai|"
    r"read\s+latest\s+chapters?|visit\s+our\s+website|please\s+bookmark)\b",
    re.IGNORECASE,
)
_NAV_LINE_RE = re.compile(
    r"^\s*(?:上一章|下一章|返回目录|目录|上一页|下一页|第\s*\d+\s*/\s*\d+\s*页|"
    r"halaman\s+(?:sebelumnya|selanjutnya|\d+\s*/\s*\d+)|"
    r"bab\s+(?:sebelumnya|selanjutnya|berikutnya)|daftar\s+isi|"
    r"previous\s+(?:chapter|page)|next\s+(?:chapter|page)|"
    r"page\s+\d+\s*/\s*\d+|table\s+of\s+contents)\s*$",
    re.IGNORECASE,
)
_PAGE_FRACTION_RE = re.compile(
    r"(?:第\s*\d+\s*/\s*\d+\s*页|\b(?:Halaman|Page)\s+\d+\s*/\s*\d+\b)",
    re.IGNORECASE,
)
_HTML_NOISE_RE = re.compile(
    r"(?:<script|</script>|<iframe|<div\b|&nbsp;|Just a moment\.\.\.|Access denied|404 Not Found|章节不存在)",
    re.IGNORECASE,
)


def _snippet(line: str, limit: int = 90) -> str:
    cleaned = re.sub(r"\s+", " ", line).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def inspect_chapter_cleanliness(
    raw_content: str | None,
    translated_content: str | None,
    status: str | None = None,
    source_lang: str = "zh",
    max_issues: int = 10,
) -> dict[str, Any]:
    """Detect scrape noise, promo/navigation leftovers, or CJK remnants in a chapter."""
    issues: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()

    def _add(code: str, field: str, line_no: int, text: str) -> None:
        key = (code, field, line_no)
        if key in seen or len(issues) >= max_issues:
            return
        seen.add(key)
        issues.append(
            {
                "code": code,
                "field": field,
                "line": line_no,
                "snippet": _snippet(text),
            }
        )

    def _scan_text(field: str, content: str) -> None:
        if not content:
            return
        for idx, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            if _HTML_NOISE_RE.search(stripped):
                _add("html_noise", field, idx, stripped)
            if _URL_RE.search(stripped) or _ZH_PROMO_RE.search(stripped) or _TRANS_PROMO_RE.search(stripped):
                _add("promo", field, idx, stripped)
            if len(stripped) <= 80 and (
                _NAV_LINE_RE.match(stripped) or _PAGE_FRACTION_RE.search(stripped)
            ):
                _add("navigation", field, idx, stripped)

    raw = raw_content or ""
    translated = translated_content or ""

    if status == "translated" and translated.strip():
        _scan_text("translated", translated)
    else:
        _scan_text("raw", raw)
        if translated.strip():
            _scan_text("translated", translated)

    if status == "raw" and raw.strip():
        if len(re.sub(r"\s+", "", raw)) < 80:
            _add("short_text", "raw", 1, raw)

    if translated.strip():
        if status == "translated" and len(re.sub(r"\s+", "", translated)) < 50:
            _add("short_text", "translated", 1, translated)
        if source_lang in CJK_SOURCE_LANGS:
            cjk_count = len(CJK_RE.findall(translated))
            total_chars = len(re.sub(r"\s+", "", translated))
            if cjk_count >= 3 or (total_chars and cjk_count / total_chars > 0.01):
                for idx, line in enumerate(translated.splitlines(), start=1):
                    if CJK_RE.search(line):
                        _add("cjk_leftover", "translated", idx, line)
                        break

    counts: dict[str, int] = {}
    for item in issues:
        counts[item["code"]] = counts.get(item["code"], 0) + 1
    summary = ", ".join(f"{code} ({cnt})" for code, cnt in counts.items())

    return {
        "needs_review": bool(issues),
        "review_issues": issues,
        "review_summary": summary,
    }
