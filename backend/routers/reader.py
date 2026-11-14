"""Reading progress and novel export (txt / json backup)."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

import database
from core.reference import load_reference

router = APIRouter(prefix="/api", tags=["reader"])

#: Characters Windows forbids in a file name.
_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class ProgressPayload(BaseModel):
    chapter_id: int | None = None
    scroll_percent: float = Field(default=0.0, ge=0.0, le=100.0)


def _require_novel(novel_id: int) -> dict[str, Any]:
    with database.get_conn() as conn:
        row = conn.execute("SELECT * FROM novels WHERE id = ?", (novel_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Novel tidak ditemukan")
    return dict(row)


def _safe_filename(title: str, fallback: str = "novel") -> str:
    cleaned = _UNSAFE_FILENAME.sub("_", (title or "").strip()).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned or fallback)[:80]


def _attachment(filename: str, fallback: str = "download") -> dict[str, str]:
    """Content-Disposition that survives non-ASCII titles.

    Browsers use ``filename*``; the plain ``filename`` is only a fallback for
    old clients, so it must still be a usable name when the title is all CJK.
    """
    stem, dot, ext = filename.rpartition(".")
    if not dot:
        stem, ext = filename, ""
    ascii_stem = stem.encode("ascii", "ignore").decode().strip(" ._-")
    if not re.search(r"[A-Za-z0-9]", ascii_stem):
        ascii_name = fallback
    else:
        ascii_name = f"{ascii_stem}.{ext}" if ext else ascii_stem
    quoted = filename.replace('"', "'")
    return {
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{_quote(quoted)}"
        )
    }


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


# --------------------------------------------------------------------------
# Reading progress
# --------------------------------------------------------------------------
@router.get("/novels/{novel_id}/progress")
def get_progress(novel_id: int) -> dict[str, Any]:
    _require_novel(novel_id)
    with database.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM reading_progress WHERE novel_id = ?", (novel_id,)
        ).fetchone()
    if row is None:
        return {
            "novel_id": novel_id,
            "chapter_id": None,
            "scroll_percent": 0.0,
            "updated_at": "",
        }
    return dict(row)


@router.put("/novels/{novel_id}/progress")
def put_progress(novel_id: int, payload: ProgressPayload) -> dict[str, Any]:
    _require_novel(novel_id)

    if payload.chapter_id is not None:
        with database.get_conn() as conn:
            chapter = conn.execute(
                "SELECT id FROM chapters WHERE id = ? AND novel_id = ?",
                (payload.chapter_id, novel_id),
            ).fetchone()
        if chapter is None:
            raise HTTPException(
                status_code=404, detail="Bab tidak ditemukan pada novel ini"
            )

    now = database.utcnow()
    with database.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO reading_progress (novel_id, chapter_id, scroll_percent, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(novel_id) DO UPDATE SET
                chapter_id = excluded.chapter_id,
                scroll_percent = excluded.scroll_percent,
                updated_at = excluded.updated_at
            """,
            (novel_id, payload.chapter_id, float(payload.scroll_percent), now),
        )
        row = conn.execute(
            "SELECT * FROM reading_progress WHERE novel_id = ?", (novel_id,)
        ).fetchone()
    return dict(row)


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------
@router.get("/novels/{novel_id}/export")
def export_novel(
    novel_id: int,
    format: Literal["txt", "json"] = Query(default="txt"),
) -> Response:
    novel = _require_novel(novel_id)

    with database.get_conn() as conn:
        chapters = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM chapters WHERE novel_id = ? "
                "ORDER BY chapter_number ASC, id ASC",
                (novel_id,),
            ).fetchall()
        ]

    if format == "json":
        payload = {
            "exported_at": database.utcnow(),
            "novel": novel,
            "reference": load_reference(novel_id),
            "chapters": chapters,
        }
        body = json.dumps(payload, ensure_ascii=False, indent=2)
        filename = f"{_safe_filename(novel['title'])}.json"
        return Response(
            content=body.encode("utf-8"),
            media_type="application/json; charset=utf-8",
            headers=_attachment(filename, fallback=f"novel-{novel_id}.json"),
        )

    translated = [chapter for chapter in chapters if chapter["status"] == "translated"]
    if not translated:
        raise HTTPException(
            status_code=400,
            detail=(
                "Belum ada bab berstatus 'translated'. Terjemahkan minimal satu bab "
                "sebelum mengekspor .txt."
            ),
        )

    lines: list[str] = [novel["title"]]
    if novel.get("author"):
        lines.append(novel["author"])
    if novel.get("synopsis"):
        lines.append("")
        lines.append(novel["synopsis"])
    lines.append("=" * 60)
    lines.append("")

    for chapter in translated:
        heading = chapter.get("title_translated") or chapter.get("title") or ""
        number = chapter["chapter_number"]
        number_label = int(number) if float(number) == int(number) else number
        # A translated title often already carries its own "Bab N:" prefix.
        if re.match(r"^\s*(bab|chapter|第)\s*\d", heading, re.IGNORECASE):
            lines.append(heading)
        else:
            lines.append(f"Bab {number_label}" + (f": {heading}" if heading else ""))
        lines.append("")
        lines.append((chapter.get("translated_content") or "").strip())
        lines.append("")
        lines.append("-" * 60)
        lines.append("")

    body = "\n".join(lines).rstrip() + "\n"
    filename = f"{_safe_filename(novel['title'])}.txt"
    return Response(
        content=body.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers=_attachment(filename, fallback=f"novel-{novel_id}.txt"),
    )
