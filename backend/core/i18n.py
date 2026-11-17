"""Request-scoped UI language context and bilingual backend messages."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

_ui_lang: ContextVar[str] = ContextVar("ui_lang", default="id")


def normalize_lang(lang: str | None) -> str:
    """Normalise an incoming UI language code to 'en' or 'id'."""
    value = (lang or "").strip().lower()
    if value.startswith("en"):
        return "en"
    return "id"


def set_ui_lang(lang: str | None) -> Token[str]:
    return _ui_lang.set(normalize_lang(lang))


def reset_ui_lang(token: Token[str]) -> None:
    _ui_lang.reset(token)


def get_ui_lang() -> str:
    return _ui_lang.get()


JOB_MESSAGES: dict[str, dict[str, str]] = {
    "queued": {
        "en": "Queued…",
        "id": "Menunggu…",
    },
    "starting": {
        "en": "Starting…",
        "id": "Memulai…",
    },
    "completed": {
        "en": "Completed",
        "id": "Selesai",
    },
    "cancelled": {
        "en": "Cancelled",
        "id": "Dibatalkan",
    },
    "failed": {
        "en": "Failed",
        "id": "Gagal",
    },
    "not_active": {
        "en": "Job is no longer active in this process",
        "id": "Job tidak aktif di proses ini",
    },
    "analyzing_story": {
        "en": "Analysing story…",
        "id": "Menganalisis cerita…",
    },
    "reference_updated": {
        "en": "Reference updated: {counts}",
        "id": "Referensi diperbarui: {counts}",
    },
    "summarizing_chapter": {
        "en": "Summarising chapter {number}…",
        "id": "Merangkum bab {number}…",
    },
    "summary_skipped": {
        "en": "Skipped summary for chapter {number}: {error}",
        "id": "Ringkasan bab {number} dilewati: {error}",
    },
    "chapters_analyzed": {
        "en": "{completed}/{total} chapters analysed",
        "id": "{completed}/{total} bab dianalisis",
    },
    "zero_of_total": {
        "en": "0/{total} chapters",
        "id": "0/{total} bab",
    },
    "fetching_chapter": {
        "en": "Fetching chapter {index}/{total}: {title}",
        "id": "Fetch bab {index}/{total}: {title}",
    },
    "chapter_failed": {
        "en": "Chapter {label} failed: {error}",
        "id": "Bab {label} gagal: {error}",
    },
    "chapter_saved": {
        "en": "Chapter {label} saved ({chars} characters)",
        "id": "Bab {label} tersimpan ({chars} karakter)",
    },
    "failures_warning": {
        "en": "{count} chapters failed: {first}",
        "id": "{count} bab gagal: {first}",
    },
    "analyzing_ref": {
        "en": "Chapter {label}: analysing new references ({completed}/{total})…",
        "id": "Bab {label}: menganalisa referensi baru ({completed}/{total})…",
    },
    "new_ref_found": {
        "en": "Chapter {label}: {summary} discovered",
        "id": "Bab {label}: {summary} baru ditemukan",
    },
    "translating_chapter": {
        "en": "Translating Chapter {label}: {title} ({completed}/{total})",
        "id": "Menerjemahkan Bab {label}: {title} ({completed}/{total})",
    },
    "translating_title": {
        "en": "Chapter {label} — translating title…",
        "id": "Bab {label} — menerjemahkan judul…",
    },
    "chunk_progress": {
        "en": "Chapter {label} — chunk {index}/{total} ({chars} chars)",
        "id": "Bab {label} — chunk {index}/{total} ({chars} kar)",
    },
    "chapter_done_score": {
        "en": "Chapter {label} done ({completed}/{total}) — score {score} ({grade})",
        "id": "Bab {label} selesai ({completed}/{total}) — skor {score} ({grade})",
    },
    "init_apply_ref": {
        "en": "0/{total} chapters (parallel {workers}x)",
        "id": "0/{total} bab (paralel {workers}x)",
    },
    "aligning_chapter": {
        "en": "Aligning chapter {label}: {title}",
        "id": "Menyesuaikan bab {label}: {title}",
    },
    "chunk_short": {
        "en": "Chapter {label} — chunk {index}/{total}",
        "id": "Bab {label} — chunk {index}/{total}",
    },
    "align_failed": {
        "en": "Chapter {label} failed to align: {error}",
        "id": "Bab {label} gagal disesuaikan: {error}",
    },
    "chapter_aligned_score": {
        "en": "Chapter {label} updated ({completed}/{total}) — score {score} ({grade})",
        "id": "Bab {label} diperbarui ({completed}/{total}) — skor {score} ({grade})",
    },
}


def tr(key: str, lang: str | None = None, **params: Any) -> str:
    """Format a backend message for the requested UI language."""
    target = normalize_lang(lang or get_ui_lang())
    entry = JOB_MESSAGES.get(key) or {}
    template = entry.get(target) or entry.get("en") or key
    return template.format(**params) if params else template
