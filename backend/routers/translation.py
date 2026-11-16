"""Reference sheet, analysis/translation jobs and the SSE progress stream."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import database
from core import job_runner
from core.analyzer import AnalysisError, localize_reference
from core.cover_prompt import CoverPromptError, generate_cover_prompt
from core.translator import TranslationError, polish_translation_text
from core.reference import load_reference, save_reference
from llm.base import TaskNotConfiguredError, TaskRouter

router = APIRouter(prefix="/api", tags=["translation"])


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class CharacterEntry(BaseModel):
    name: str
    romanized_name: str = ""
    age: str = ""
    gender: str = ""
    aliases: list[str] = Field(default_factory=list)
    relationships: str = ""
    notes: str = ""


class TermEntry(BaseModel):
    source: str
    romanized: str = ""
    target: str = ""
    note: str = ""
    keep_romanized: bool = False


class ReferencePayload(BaseModel):
    characters: list[CharacterEntry] = Field(default_factory=list)
    locations: list[TermEntry] = Field(default_factory=list)
    terms: list[TermEntry] = Field(default_factory=list)
    translation_guide: str = ""
    chapter_context: list[dict[str, Any]] | None = None


class AnalyzePayload(BaseModel):
    chapter_ids: list[int] | None = None


class TranslatePayload(BaseModel):
    chapter_ids: list[int] = Field(default_factory=list)
    auto_update_reference: bool = True


class CoverPromptPayload(BaseModel):
    style: str = "webnovel_cover"
    mood: str = ""
    extra_notes: str = ""


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _require_novel(novel_id: int) -> dict[str, Any]:
    with database.get_conn() as conn:
        row = conn.execute("SELECT * FROM novels WHERE id = ?", (novel_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Novel tidak ditemukan")
    return dict(row)


def _require_task(task_name: str) -> None:
    """Fail fast with an actionable message when routing is not configured."""
    try:
        TaskRouter(task_name).resolve()
    except TaskNotConfiguredError as exc:
        label = "Analisa Cerita" if task_name == "story_analysis" else "Translate"
        raise HTTPException(
            status_code=424,
            detail=(
                f"Task '{task_name}' belum dikonfigurasi. Buka Settings → Model Routing "
                f"per Proses dan pilih provider + model untuk {label}. ({exc})"
            ),
        ) from exc


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


# --------------------------------------------------------------------------
# Reference sheet
# --------------------------------------------------------------------------
@router.get("/novels/{novel_id}/reference")
def get_reference(novel_id: int) -> dict[str, Any]:
    _require_novel(novel_id)
    return load_reference(novel_id)


@router.put("/novels/{novel_id}/reference")
def put_reference(novel_id: int, payload: ReferencePayload) -> dict[str, Any]:
    _require_novel(novel_id)
    existing = load_reference(novel_id)
    data = payload.model_dump()
    if data.get("chapter_context") is None:
        data["chapter_context"] = existing.get("chapter_context") or []
    return save_reference(novel_id, data)


@router.post("/novels/{novel_id}/reference/localize")
async def localize_novel_reference(novel_id: int) -> dict[str, Any]:
    _require_novel(novel_id)
    _require_task("story_analysis")
    try:
        return await localize_reference(novel_id)
    except AnalysisError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------
@router.post("/novels/{novel_id}/analyze", status_code=202)
async def start_analysis(novel_id: int, payload: AnalyzePayload | None = None) -> dict[str, Any]:
    _require_novel(novel_id)
    _require_task("story_analysis")

    chapter_ids = payload.chapter_ids if payload else None
    if chapter_ids:
        with database.get_conn() as conn:
            placeholders = ",".join("?" for _ in chapter_ids)
            found = conn.execute(
                f"SELECT COUNT(*) AS n FROM chapters WHERE novel_id = ? AND id IN ({placeholders})",
                (novel_id, *chapter_ids),
            ).fetchone()["n"]
        if not found:
            raise HTTPException(status_code=404, detail="Tidak ada bab yang cocok")

    job = await job_runner.start_job("story_analysis", novel_id, chapter_ids)
    return job


@router.post("/novels/{novel_id}/reference/apply", status_code=202)
async def apply_reference(
    novel_id: int, payload: AnalyzePayload | None = None
) -> dict[str, Any]:
    _require_novel(novel_id)
    _require_task("translate")
    requested_ids = payload.chapter_ids if payload and payload.chapter_ids else None
    with database.get_conn() as conn:
        if requested_ids:
            placeholders = ",".join("?" for _ in requested_ids)
            rows = conn.execute(
                f"SELECT id FROM chapters WHERE novel_id = ? AND id IN ({placeholders}) "
                "AND translated_content <> '' ORDER BY chapter_number ASC",
                (novel_id, *requested_ids),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM chapters WHERE novel_id = ? AND translated_content <> '' "
                "ORDER BY chapter_number ASC",
                (novel_id,),
            ).fetchall()
    chapter_ids = [row["id"] for row in rows]
    if not chapter_ids:
        raise HTTPException(
            status_code=422,
            detail="Belum ada bab yang sudah diterjemahkan untuk diperbarui.",
        )
    return await job_runner.start_job("apply_reference", novel_id, chapter_ids)


@router.post("/novels/{novel_id}/cover-prompt")
async def create_cover_prompt(
    novel_id: int, payload: CoverPromptPayload | None = None
) -> dict[str, Any]:
    _require_novel(novel_id)
    try:
        TaskRouter("cover_prompt").resolve()
    except TaskNotConfiguredError:
        _require_task("story_analysis")
    opts = payload or CoverPromptPayload()
    try:
        return await generate_cover_prompt(
            novel_id,
            style=opts.style,
            mood=opts.mood,
            extra_notes=opts.extra_notes,
        )
    except CoverPromptError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/novels/{novel_id}/translate", status_code=202)
async def start_translation(novel_id: int, payload: TranslatePayload) -> dict[str, Any]:
    _require_novel(novel_id)
    if not payload.chapter_ids:
        raise HTTPException(status_code=422, detail="chapter_ids kosong")
    _require_task("translate")

    with database.get_conn() as conn:
        placeholders = ",".join("?" for _ in payload.chapter_ids)
        rows = conn.execute(
            f"SELECT id, raw_content FROM chapters WHERE novel_id = ? AND id IN ({placeholders})",
            (novel_id, *payload.chapter_ids),
        ).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="Tidak ada bab yang cocok")
    empty = [row["id"] for row in rows if not (row["raw_content"] or "").strip()]
    if empty:
        raise HTTPException(
            status_code=422,
            detail=f"Bab {empty} belum punya isi raw. Fetch atau paste isinya dulu.",
        )

    job = await job_runner.start_job(
        "translate",
        novel_id,
        payload.chapter_ids,
        auto_update_reference=payload.auto_update_reference,
    )
    return job


@router.get("/novels/{novel_id}/jobs")
def get_novel_jobs(novel_id: int, limit: int = 20) -> list[dict[str, Any]]:
    _require_novel(novel_id)
    return job_runner.list_jobs(novel_id, limit)


class PolishPayload(BaseModel):
    translated_content: str | None = None


@router.post("/chapters/{chapter_id}/polish")
async def polish_chapter_endpoint(
    chapter_id: int, payload: PolishPayload | None = None
) -> dict[str, Any]:
    _require_task("translate")
    try:
        polished = await polish_translation_text(
            chapter_id,
            payload.translated_content if payload else None,
        )
    except TranslationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"chapter_id": chapter_id, "polished_content": polished}


@router.post("/chapters/{chapter_id}/polish/stream")
async def polish_chapter_stream_endpoint(
    chapter_id: int, payload: PolishPayload | None = None
) -> StreamingResponse:
    _require_task("translate")
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def on_progress(event: dict[str, Any]) -> None:
        await queue.put(event)

    async def runner() -> None:
        try:
            polished = await polish_translation_text(
                chapter_id,
                payload.translated_content if payload else None,
                on_progress=on_progress,
            )
            await queue.put(
                {
                    "type": "done",
                    "chapter_id": chapter_id,
                    "polished_content": polished,
                }
            )
        except Exception as exc:
            await queue.put({"type": "error", "message": str(exc)})
        finally:
            await queue.put(None)

    async def stream() -> AsyncIterator[str]:
        task = asyncio.create_task(runner())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield json.dumps(item, ensure_ascii=False) + "\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = job_runner.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan")
    return job


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    if job_runner.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan")

    async def stream() -> AsyncIterator[str]:
        try:
            async for event in job_runner.subscribe(job_id):
                yield _sse(event)
        except job_runner.JobError:
            yield _sse({"type": "error", "job_id": job_id, "message": "Job tidak ditemukan"})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/jobs/{job_id}/cancel")
async def cancel(job_id: str) -> dict[str, Any]:
    try:
        return await job_runner.cancel_job(job_id)
    except job_runner.JobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
