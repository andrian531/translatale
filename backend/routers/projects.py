"""Novel & chapter API: manual input, batch upload, and scraper-driven fetch."""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator

import database
from core import job_runner
from core.app_settings import get_scraper_settings
from scrapers.base import ScraperError
from scrapers.registry import find_scraper, get_scraper

router = APIRouter(prefix="/api", tags=["novels"])

ChapterStatus = Literal["pending_fetch", "raw", "translating", "translated", "error"]
SourceType = Literal["scraper", "manual"]

MAX_UPLOAD_BYTES = 8 * 1024 * 1024


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class NovelCreate(BaseModel):
    title: str
    author: str = ""
    title_translated: str = ""
    source_lang: str = "zh"
    target_lang: str = "id"
    synopsis: str = ""

    @field_validator("title")
    @classmethod
    def _title_required(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("title tidak boleh kosong")
        return value


class NovelUpdate(BaseModel):
    title: str | None = None
    title_translated: str | None = None
    author: str | None = None
    source_lang: str | None = None
    target_lang: str | None = None
    synopsis: str | None = None


class NovelFromUrl(BaseModel):
    url: str
    target_lang: str = "id"
    source_lang: str | None = None

    @field_validator("url")
    @classmethod
    def _url_required(cls, value: str) -> str:
        value = (value or "").strip()
        if not value.startswith(("http://", "https://")):
            raise ValueError("url harus diawali http:// atau https://")
        return value


class ChapterManual(BaseModel):
    title: str = ""
    raw_content: str
    chapter_number: float | None = None
    title_translated: str = ""

    @field_validator("raw_content")
    @classmethod
    def _content_required(cls, value: str) -> str:
        if not (value or "").strip():
            raise ValueError("raw_content tidak boleh kosong")
        return value


class ChapterUpdate(BaseModel):
    title: str | None = None
    title_translated: str | None = None
    raw_content: str | None = None
    translated_content: str | None = None
    status: ChapterStatus | None = None
    quality_score: float | None = None


class FetchRequest(BaseModel):
    chapter_ids: list[int] = Field(default_factory=list)


class ChaptersFromUrl(BaseModel):
    urls: list[str] = Field(default_factory=list)

    @field_validator("urls")
    @classmethod
    def _clean_urls(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if not cleaned:
            raise ValueError("urls tidak boleh kosong")
        return cleaned


class SyncUrlRequest(BaseModel):
    source_url: str | None = None


class FetchJobRequest(BaseModel):
    chapter_ids: list[int] = Field(default_factory=list)
    limit: int | None = Field(default=None, ge=1, le=500)


class NovelOut(BaseModel):
    id: int
    title: str
    title_translated: str
    author: str
    source_lang: str
    target_lang: str
    source_type: str
    source_url: str
    scraper_name: str
    synopsis: str
    created_at: str
    updated_at: str
    chapter_count: int = 0
    raw_count: int = 0
    translated_count: int = 0
    pending_count: int = 0
    last_read_chapter_id: int | None = None


class ChapterOut(BaseModel):
    id: int
    novel_id: int
    chapter_number: float
    title: str
    title_translated: str
    source_url: str
    raw_content: str
    translated_content: str
    status: str
    quality_score: float | None
    created_at: str
    updated_at: str


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
NOVEL_SELECT = """
SELECT n.*,
       (SELECT COUNT(*) FROM chapters c WHERE c.novel_id = n.id) AS chapter_count,
       (SELECT COUNT(*) FROM chapters c WHERE c.novel_id = n.id AND c.status = 'raw') AS raw_count,
       (SELECT COUNT(*) FROM chapters c WHERE c.novel_id = n.id AND c.status = 'translated') AS translated_count,
       (SELECT COUNT(*) FROM chapters c WHERE c.novel_id = n.id AND c.status = 'pending_fetch') AS pending_count,
       (SELECT rp.chapter_id FROM reading_progress rp WHERE rp.novel_id = n.id) AS last_read_chapter_id
FROM novels AS n
"""


def _novel_out(row: sqlite3.Row) -> NovelOut:
    return NovelOut(**{key: row[key] for key in row.keys()})


def _chapter_out(row: sqlite3.Row) -> ChapterOut:
    return ChapterOut(**{key: row[key] for key in row.keys()})


def _get_novel(conn: sqlite3.Connection, novel_id: int) -> sqlite3.Row:
    row = conn.execute(NOVEL_SELECT + " WHERE n.id = ?", (novel_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Novel tidak ditemukan")
    return row


def _get_chapter(conn: sqlite3.Connection, chapter_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM chapters WHERE id = ?", (chapter_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Bab tidak ditemukan")
    return row


def _next_chapter_number(conn: sqlite3.Connection, novel_id: int) -> float:
    row = conn.execute(
        "SELECT MAX(chapter_number) AS max_no FROM chapters WHERE novel_id = ?", (novel_id,)
    ).fetchone()
    return float(row["max_no"] or 0) + 1


def _decode_upload(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _number_from_filename(filename: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)", filename or "")
    return float(match.group(1)) if match else None


def _title_from_upload(filename: str, text: str) -> str:
    """Prefer a short first line, else the file name without its extension."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) > 1 and len(lines[0]) <= 100:
        return lines[0]
    stem = re.sub(r"\.[^.]+$", "", filename or "").strip()
    return stem or (lines[0] if lines else "Untitled")


# --------------------------------------------------------------------------
# Novels
# --------------------------------------------------------------------------
@router.get("/novels", response_model=list[NovelOut])
def list_novels() -> list[NovelOut]:
    with database.get_conn() as conn:
        rows = conn.execute(NOVEL_SELECT + " ORDER BY n.updated_at DESC, n.id DESC").fetchall()
    return [_novel_out(row) for row in rows]


@router.post("/novels", response_model=NovelOut, status_code=201)
def create_novel(payload: NovelCreate) -> NovelOut:
    now = database.utcnow()
    with database.get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO novels (title, title_translated, author, source_lang, target_lang,
                                source_type, source_url, scraper_name, synopsis,
                                created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'manual', '', '', ?, ?, ?)
            """,
            (
                payload.title,
                payload.title_translated,
                payload.author,
                payload.source_lang,
                payload.target_lang,
                payload.synopsis,
                now,
                now,
            ),
        )
        row = _get_novel(conn, int(cursor.lastrowid or 0))
    return _novel_out(row)


@router.post("/novels/from-url", response_model=NovelOut, status_code=201)
async def create_novel_from_url(payload: NovelFromUrl) -> NovelOut:
    scraper = find_scraper(payload.url)
    try:
        info = await scraper.fetch_novel_info(payload.url)
    except ScraperError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    now = database.utcnow()
    with database.get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO novels (title, title_translated, author, source_lang, target_lang,
                                source_type, source_url, scraper_name, synopsis,
                                created_at, updated_at)
            VALUES (?, '', ?, ?, ?, 'scraper', ?, ?, ?, ?, ?)
            """,
            (
                info.title,
                info.author,
                payload.source_lang or info.source_lang,
                payload.target_lang,
                payload.url,
                scraper.name,
                info.synopsis,
                now,
                now,
            ),
        )
        novel_id = int(cursor.lastrowid or 0)

        for chapter in info.chapters:
            conn.execute(
                """
                INSERT INTO chapters (novel_id, chapter_number, title, title_translated,
                                      source_url, raw_content, translated_content, status,
                                      created_at, updated_at)
                VALUES (?, ?, ?, '', ?, '', '', 'pending_fetch', ?, ?)
                """,
                (novel_id, chapter.chapter_number, chapter.title, chapter.url, now, now),
            )

        row = _get_novel(conn, novel_id)
    return _novel_out(row)


@router.get("/novels/{novel_id}", response_model=NovelOut)
def get_novel(novel_id: int) -> NovelOut:
    with database.get_conn() as conn:
        return _novel_out(_get_novel(conn, novel_id))


@router.patch("/novels/{novel_id}", response_model=NovelOut)
def update_novel(novel_id: int, payload: NovelUpdate) -> NovelOut:
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    with database.get_conn() as conn:
        _get_novel(conn, novel_id)
        if changes:
            assignments = ", ".join(f"{key} = ?" for key in changes)
            conn.execute(
                f"UPDATE novels SET {assignments}, updated_at = ? WHERE id = ?",
                (*changes.values(), database.utcnow(), novel_id),
            )
        return _novel_out(_get_novel(conn, novel_id))


@router.delete("/novels/{novel_id}")
def delete_novel(novel_id: int) -> dict[str, Any]:
    with database.get_conn() as conn:
        _get_novel(conn, novel_id)
        conn.execute("DELETE FROM chapters WHERE novel_id = ?", (novel_id,))
        conn.execute("DELETE FROM novels WHERE id = ?", (novel_id,))
    return {"ok": True, "deleted_id": novel_id}


# --------------------------------------------------------------------------
# Chapters
# --------------------------------------------------------------------------
@router.get("/novels/{novel_id}/chapters", response_model=list[ChapterOut])
def list_chapters(novel_id: int, status: ChapterStatus | None = None) -> list[ChapterOut]:
    with database.get_conn() as conn:
        _get_novel(conn, novel_id)
        if status:
            rows = conn.execute(
                "SELECT * FROM chapters WHERE novel_id = ? AND status = ? "
                "ORDER BY chapter_number ASC, id ASC",
                (novel_id, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM chapters WHERE novel_id = ? ORDER BY chapter_number ASC, id ASC",
                (novel_id,),
            ).fetchall()
    return [_chapter_out(row) for row in rows]


@router.post("/novels/{novel_id}/chapters/manual", response_model=ChapterOut, status_code=201)
def add_manual_chapter(novel_id: int, payload: ChapterManual) -> ChapterOut:
    now = database.utcnow()
    with database.get_conn() as conn:
        _get_novel(conn, novel_id)
        number = (
            payload.chapter_number
            if payload.chapter_number is not None
            else _next_chapter_number(conn, novel_id)
        )
        title = payload.title.strip() or f"Chapter {int(number) if number == int(number) else number}"
        cursor = conn.execute(
            """
            INSERT INTO chapters (novel_id, chapter_number, title, title_translated,
                                  source_url, raw_content, translated_content, status,
                                  created_at, updated_at)
            VALUES (?, ?, ?, ?, '', ?, '', 'raw', ?, ?)
            """,
            (
                novel_id,
                float(number),
                title,
                payload.title_translated,
                payload.raw_content,
                now,
                now,
            ),
        )
        conn.execute("UPDATE novels SET updated_at = ? WHERE id = ?", (now, novel_id))
        row = _get_chapter(conn, int(cursor.lastrowid or 0))
    return _chapter_out(row)


@router.post("/novels/{novel_id}/chapters/upload", response_model=list[ChapterOut], status_code=201)
async def upload_chapters(novel_id: int, files: list[UploadFile] = File(...)) -> list[ChapterOut]:
    if not files:
        raise HTTPException(status_code=422, detail="Tidak ada file yang diunggah")

    parsed: list[tuple[float | None, str, str]] = []
    for upload in files:
        data = await upload.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413, detail=f"File {upload.filename} melebihi 8 MB"
            )
        text = _decode_upload(data)
        if not text.strip():
            continue
        parsed.append(
            (
                _number_from_filename(upload.filename or ""),
                _title_from_upload(upload.filename or "", text),
                text,
            )
        )

    if not parsed:
        raise HTTPException(status_code=422, detail="Semua file kosong")

    now = database.utcnow()
    created: list[int] = []
    with database.get_conn() as conn:
        _get_novel(conn, novel_id)
        existing = {
            float(row["chapter_number"])
            for row in conn.execute(
                "SELECT chapter_number FROM chapters WHERE novel_id = ?", (novel_id,)
            ).fetchall()
        }
        # If a filename number collides with a chapter that already exists, shift
        # the whole batch past the current maximum so relative order survives and
        # no two chapters share a number.
        numbered = [number for number, _, _ in parsed if number is not None]
        offset = max(existing) if (existing and any(n in existing for n in numbered)) else 0.0
        next_number = max(existing | {0.0}) + 1.0

        # Files with a numeric prefix keep their order; the rest follow in upload order.
        ordered = sorted(
            enumerate(parsed),
            key=lambda item: (item[1][0] is None, item[1][0] or 0, item[0]),
        )

        for _, (number, title, text) in ordered:
            if number is None:
                number = next_number
                next_number += 1
            else:
                number = number + offset
                next_number = max(next_number, number + 1)

            cursor = conn.execute(
                """
                INSERT INTO chapters (novel_id, chapter_number, title, title_translated,
                                      source_url, raw_content, translated_content, status,
                                      created_at, updated_at)
                VALUES (?, ?, ?, '', '', ?, '', 'raw', ?, ?)
                """,
                (novel_id, float(number), title, text, now, now),
            )
            created.append(int(cursor.lastrowid or 0))

        conn.execute("UPDATE novels SET updated_at = ? WHERE id = ?", (now, novel_id))
        rows = [
            _get_chapter(conn, chapter_id)
            for chapter_id in created
        ]
    return [_chapter_out(row) for row in rows]


@router.post("/novels/{novel_id}/chapters/fetch")
async def fetch_chapters(novel_id: int, payload: FetchRequest) -> dict[str, Any]:
    if not payload.chapter_ids:
        raise HTTPException(status_code=422, detail="chapter_ids kosong")

    with database.get_conn() as conn:
        novel = _get_novel(conn, novel_id)
        placeholders = ",".join("?" for _ in payload.chapter_ids)
        rows = conn.execute(
            f"SELECT * FROM chapters WHERE novel_id = ? AND id IN ({placeholders})",
            (novel_id, *payload.chapter_ids),
        ).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="Tidak ada bab yang cocok")

    scraper_name = novel["scraper_name"] or ""
    fetched, failed, errors = 0, 0, []

    for row in rows:
        url = row["source_url"]
        if not url:
            failed += 1
            errors.append({"chapter_id": row["id"], "error": "Bab tidak punya source_url"})
            continue
        try:
            scraper = get_scraper(scraper_name) if scraper_name else find_scraper(url)
            content = await scraper.fetch_chapter_content(url)
        except ScraperError as exc:
            failed += 1
            errors.append({"chapter_id": row["id"], "error": str(exc)})
            with database.get_conn() as conn:
                conn.execute(
                    "UPDATE chapters SET status = 'error', updated_at = ? WHERE id = ?",
                    (database.utcnow(), row["id"]),
                )
            continue

        with database.get_conn() as conn:
            conn.execute(
                """
                UPDATE chapters
                   SET raw_content = ?, status = 'raw',
                       title = CASE WHEN title = '' THEN ? ELSE title END,
                       updated_at = ?
                 WHERE id = ?
                """,
                (content.content, content.title, database.utcnow(), row["id"]),
            )
        fetched += 1

    with database.get_conn() as conn:
        conn.execute(
            "UPDATE novels SET updated_at = ? WHERE id = ?", (database.utcnow(), novel_id)
        )

    return {"ok": failed == 0, "fetched": fetched, "failed": failed, "errors": errors}


# --------------------------------------------------------------------------
# Chapters from URLs / TOC sync / batch fetch job
# --------------------------------------------------------------------------
def _scraper_for(url: str, novel_scraper: str):
    """Pick the module that owns the URL, falling back to the novel's scraper."""
    scraper = find_scraper(url)
    if scraper.name == "generic" and novel_scraper:
        return get_scraper(novel_scraper)
    return scraper


@router.post("/novels/{novel_id}/chapters/from-url")
async def add_chapters_from_url(novel_id: int, payload: ChaptersFromUrl) -> dict[str, Any]:
    with database.get_conn() as conn:
        novel = dict(_get_novel(conn, novel_id))
        existing = {
            row["source_url"]
            for row in conn.execute(
                "SELECT source_url FROM chapters WHERE novel_id = ? AND source_url <> ''",
                (novel_id,),
            ).fetchall()
        }
        next_number = _next_chapter_number(conn, novel_id)

    novel_scraper = (novel.get("scraper_name") or "").strip()
    added: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    skipped = 0

    for raw_url in payload.urls:
        url = raw_url.strip()
        if url in existing:
            skipped += 1
            continue

        try:
            scraper = _scraper_for(url, novel_scraper)
            content = await scraper.fetch_chapter_content(url)
        except ScraperError as exc:
            errors.append({"url": url, "error": str(exc)})
            continue

        now = database.utcnow()
        with database.get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO chapters (novel_id, chapter_number, title, title_translated,
                                      source_url, raw_content, translated_content, status,
                                      created_at, updated_at)
                VALUES (?, ?, ?, '', ?, ?, '', 'raw', ?, ?)
                """,
                (
                    novel_id,
                    float(next_number),
                    content.title or f"Bab {int(next_number)}",
                    url,
                    content.content,
                    now,
                    now,
                ),
            )
            conn.execute(
                "UPDATE novels SET updated_at = ? WHERE id = ?", (now, novel_id)
            )
        existing.add(url)
        added.append(
            {
                "id": int(cursor.lastrowid or 0),
                "chapter_number": float(next_number),
                "title": content.title,
                "url": url,
                "chars": len(content.content),
            }
        )
        next_number += 1

    return {
        "ok": not errors,
        "added": len(added),
        "skipped": skipped,
        "failed": len(errors),
        "chapters": added,
        "errors": errors,
    }


@router.post("/novels/{novel_id}/chapters/sync-url")
async def sync_chapters_from_source(
    novel_id: int, payload: SyncUrlRequest | None = None
) -> dict[str, Any]:
    with database.get_conn() as conn:
        novel = dict(_get_novel(conn, novel_id))
        rows = conn.execute(
            "SELECT chapter_number, source_url FROM chapters WHERE novel_id = ?", (novel_id,)
        ).fetchall()

    source_url = (payload.source_url if payload and payload.source_url else "").strip()
    source_url = source_url or (novel.get("source_url") or "").strip()
    if not source_url:
        raise HTTPException(
            status_code=400,
            detail=(
                "Novel ini tidak punya source_url. Isi source_url dulu atau kirim "
                "source_url pada body request."
            ),
        )

    novel_scraper = (novel.get("scraper_name") or "").strip()
    scraper = _scraper_for(source_url, novel_scraper)
    try:
        listing = await scraper.fetch_chapter_list(source_url)
    except ScraperError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    existing_urls = {row["source_url"] for row in rows if row["source_url"]}
    existing_numbers = {float(row["chapter_number"]) for row in rows}

    added: list[dict[str, Any]] = []
    skipped = 0
    now = database.utcnow()

    for meta in listing:
        url = (meta.url or "").strip()
        number = float(meta.chapter_number)
        if (url and url in existing_urls) or number in existing_numbers:
            skipped += 1
            continue

        with database.get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO chapters (novel_id, chapter_number, title, title_translated,
                                      source_url, raw_content, translated_content, status,
                                      created_at, updated_at)
                VALUES (?, ?, ?, '', ?, '', '', 'pending_fetch', ?, ?)
                """,
                (novel_id, number, meta.title, url, now, now),
            )
        existing_urls.add(url)
        existing_numbers.add(number)
        added.append(
            {
                "id": int(cursor.lastrowid or 0),
                "chapter_number": number,
                "title": meta.title,
                "url": url,
            }
        )

    if added:
        with database.get_conn() as conn:
            conn.execute("UPDATE novels SET updated_at = ? WHERE id = ?", (now, novel_id))

    return {
        "ok": True,
        "source_url": source_url,
        "scraper": scraper.name,
        "found": len(listing),
        "added": len(added),
        "skipped": skipped,
        "chapters": added,
    }


@router.post("/novels/{novel_id}/chapters/fetch-job", status_code=202)
async def start_fetch_job(novel_id: int, payload: FetchJobRequest) -> dict[str, Any]:
    """Background batch fetch with delay + circuit breaker (progress via SSE)."""
    with database.get_conn() as conn:
        _get_novel(conn, novel_id)

        if payload.chapter_ids:
            placeholders = ",".join("?" for _ in payload.chapter_ids)
            found = conn.execute(
                f"SELECT id FROM chapters WHERE novel_id = ? AND id IN ({placeholders})",
                (novel_id, *payload.chapter_ids),
            ).fetchall()
            chapter_ids = [row["id"] for row in found]
            if not chapter_ids:
                raise HTTPException(status_code=404, detail="Tidak ada bab yang cocok")
        else:
            settings = get_scraper_settings()
            limit = int(payload.limit or settings["fetch_batch_size"])
            limit = max(1, min(limit, 500))
            rows = conn.execute(
                "SELECT id FROM chapters WHERE novel_id = ? AND status = 'pending_fetch' "
                "ORDER BY chapter_number ASC, id ASC LIMIT ?",
                (novel_id, limit),
            ).fetchall()
            chapter_ids = [row["id"] for row in rows]
            if not chapter_ids:
                raise HTTPException(
                    status_code=422,
                    detail="Tidak ada bab berstatus 'pending_fetch' untuk di-fetch.",
                )

    job = await job_runner.start_job("fetch", novel_id, chapter_ids)
    job["chapter_ids"] = chapter_ids
    return job


@router.get("/chapters/{chapter_id}", response_model=ChapterOut)
def get_chapter(chapter_id: int) -> ChapterOut:
    with database.get_conn() as conn:
        return _chapter_out(_get_chapter(conn, chapter_id))


@router.patch("/chapters/{chapter_id}", response_model=ChapterOut)
def update_chapter(chapter_id: int, payload: ChapterUpdate) -> ChapterOut:
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    with database.get_conn() as conn:
        row = _get_chapter(conn, chapter_id)
        if changes:
            assignments = ", ".join(f"{key} = ?" for key in changes)
            conn.execute(
                f"UPDATE chapters SET {assignments}, updated_at = ? WHERE id = ?",
                (*changes.values(), database.utcnow(), chapter_id),
            )
            conn.execute(
                "UPDATE novels SET updated_at = ? WHERE id = ?",
                (database.utcnow(), row["novel_id"]),
            )
        return _chapter_out(_get_chapter(conn, chapter_id))


@router.delete("/chapters/{chapter_id}")
def delete_chapter(chapter_id: int) -> dict[str, Any]:
    with database.get_conn() as conn:
        row = _get_chapter(conn, chapter_id)
        conn.execute("DELETE FROM chapters WHERE id = ?", (chapter_id,))
        conn.execute(
            "UPDATE novels SET updated_at = ? WHERE id = ?",
            (database.utcnow(), row["novel_id"]),
        )
    return {"ok": True, "deleted_id": chapter_id}
