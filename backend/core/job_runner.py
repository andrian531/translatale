"""Background job runner for story analysis and batch translation.

Jobs run as ``asyncio`` tasks inside the API process. Progress is written to
``translation_jobs`` and broadcast to any SSE subscriber of that job.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import database
from core.analyzer import AnalysisError, analyze_novel, summarize_chapter_for_context
from core.translator import TranslationError, translate_chapter

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
JOB_TYPES = frozenset({"story_analysis", "translate"})

HEARTBEAT_SECONDS = 15.0


class JobError(RuntimeError):
    """Raised for unknown jobs or invalid job requests."""


@dataclass
class JobState:
    job_id: str
    task: asyncio.Task | None = None
    cancelled: bool = False
    finished: bool = False
    subscribers: list[asyncio.Queue] = field(default_factory=list)


_JOBS: dict[str, JobState] = {}


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------
def _fmt_number(value: Any) -> str:
    """Render 1.0 as "1" in user-facing messages."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(number)) if number == int(number) else str(number)


def _update_job(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = database.utcnow()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    with database.get_conn() as conn:
        conn.execute(
            f"UPDATE translation_jobs SET {assignments} WHERE id = ?",
            (*fields.values(), job_id),
        )


def get_job(job_id: str) -> dict[str, Any] | None:
    with database.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM translation_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    return dict(row) if row is not None else None


def list_jobs(novel_id: int | None = None, limit: int = 20) -> list[dict[str, Any]]:
    with database.get_conn() as conn:
        if novel_id is None:
            rows = conn.execute(
                "SELECT * FROM translation_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM translation_jobs WHERE novel_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (novel_id, limit),
            ).fetchall()
    return [dict(row) for row in rows]


# --------------------------------------------------------------------------
# Event bus
# --------------------------------------------------------------------------
def _publish(job_id: str, event: dict[str, Any]) -> None:
    state = _JOBS.get(job_id)
    if state is None:
        return
    payload = {"job_id": job_id, **event}
    for queue in list(state.subscribers):
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            # A stalled client must not block the job.
            pass


def _snapshot(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "status",
        "job_id": job["id"],
        "status": job["status"],
        "job_type": job["job_type"],
        "total_items": job["total_items"],
        "completed_items": job["completed_items"],
        "current_chapter_id": job["current_chapter_id"],
        "message": job["message"],
        "error": job["error"],
    }


async def subscribe(job_id: str) -> AsyncIterator[dict[str, Any]]:
    """Yield progress events until the job reaches a terminal state."""
    job = get_job(job_id)
    if job is None:
        raise JobError(f"Job {job_id} tidak ditemukan")

    yield _snapshot(job)
    if job["status"] in TERMINAL_STATUSES:
        yield {"type": "done", "job_id": job_id, "status": job["status"]}
        return

    state = _JOBS.get(job_id)
    if state is None:
        # The job was started by another process (or before a restart): we can
        # only report what the database says.
        yield {
            "type": "done",
            "job_id": job_id,
            "status": job["status"],
            "message": "Job tidak aktif di proses ini",
        }
        return

    queue: asyncio.Queue = asyncio.Queue(maxsize=500)
    state.subscribers.append(queue)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield {"type": "ping", "job_id": job_id}
                continue
            yield event
            if event.get("type") in ("done", "error", "cancelled"):
                break
    finally:
        if queue in state.subscribers:
            state.subscribers.remove(queue)


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------
async def start_job(
    job_type: str,
    novel_id: int,
    chapter_ids: list[int] | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Create the job row and schedule it on the running event loop."""
    if job_type not in JOB_TYPES:
        raise JobError(f"job_type tidak dikenal: {job_type}")

    job_id = str(uuid.uuid4())
    now = database.utcnow()
    total = len(chapter_ids) if chapter_ids else 1

    with database.get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO translation_jobs
                (id, novel_id, job_type, status, total_items, completed_items,
                 current_chapter_id, message, error, created_at, updated_at)
            VALUES (?, ?, ?, 'queued', ?, 0, NULL, 'Menunggu…', '', ?, ?)
            """,
            (job_id, novel_id, job_type, total, now, now),
        )

    state = JobState(job_id=job_id)
    _JOBS[job_id] = state
    state.task = asyncio.create_task(
        _run(state, job_type, novel_id, chapter_ids, db_path)
    )
    return get_job(job_id) or {}


async def cancel_job(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if job is None:
        raise JobError(f"Job {job_id} tidak ditemukan")
    if job["status"] in TERMINAL_STATUSES:
        return job

    state = _JOBS.get(job_id)
    if state is not None:
        state.cancelled = True
        if state.task is not None and not state.task.done():
            state.task.cancel()
            try:
                await state.task
            except (asyncio.CancelledError, Exception):
                pass
    else:
        _update_job(job_id, status="cancelled", message="Dibatalkan")

    return get_job(job_id) or job


def _reset_translating(chapter_ids: list[int] | None, db_path: str | None) -> None:
    """Return chapters interrupted mid-translation to 'raw'."""
    if not chapter_ids:
        return
    placeholders = ",".join("?" for _ in chapter_ids)
    with database.get_conn(db_path) as conn:
        conn.execute(
            f"UPDATE chapters SET status = 'raw', updated_at = ? "
            f"WHERE status = 'translating' AND id IN ({placeholders})",
            (database.utcnow(), *chapter_ids),
        )


async def _run(
    state: JobState,
    job_type: str,
    novel_id: int,
    chapter_ids: list[int] | None,
    db_path: str | None,
) -> None:
    job_id = state.job_id
    try:
        _update_job(job_id, status="running", message="Memulai…")
        _publish(job_id, {"type": "status", "status": "running", "message": "Memulai…"})

        if job_type == "story_analysis":
            await _run_analysis(state, novel_id, chapter_ids, db_path)
        else:
            await _run_translate(state, novel_id, chapter_ids, db_path)

        if state.cancelled:
            raise asyncio.CancelledError

        job = get_job(job_id) or {}
        _update_job(
            job_id,
            status="completed",
            message="Selesai",
            completed_items=job.get("total_items", 0),
            current_chapter_id=None,
        )
        _publish(
            job_id,
            {
                "type": "done",
                "status": "completed",
                "message": "Selesai",
                "completed_items": job.get("total_items", 0),
                "total_items": job.get("total_items", 0),
            },
        )
    except asyncio.CancelledError:
        # A cancelled job must not leave chapters stuck in 'translating'.
        _reset_translating(chapter_ids, db_path)
        _update_job(job_id, status="cancelled", message="Dibatalkan", current_chapter_id=None)
        _publish(job_id, {"type": "cancelled", "status": "cancelled", "message": "Dibatalkan"})
    except (AnalysisError, TranslationError, JobError) as exc:
        _update_job(job_id, status="failed", error=str(exc), message="Gagal")
        _publish(job_id, {"type": "error", "status": "failed", "message": str(exc)})
    except Exception as exc:  # noqa: BLE001 - a job must never crash the server
        _update_job(job_id, status="failed", error=f"{type(exc).__name__}: {exc}", message="Gagal")
        _publish(
            job_id,
            {"type": "error", "status": "failed", "message": f"{type(exc).__name__}: {exc}"},
        )
    finally:
        state.finished = True


async def _run_analysis(
    state: JobState,
    novel_id: int,
    chapter_ids: list[int] | None,
    db_path: str | None,
) -> None:
    job_id = state.job_id
    _update_job(job_id, message="Menganalisis cerita…")
    _publish(job_id, {"type": "progress", "message": "Menganalisis cerita…"})

    result = await analyze_novel(novel_id, chapter_ids, db_path)
    analyzed = result["chapters_analyzed"]

    _update_job(job_id, total_items=len(analyzed) or 1)
    _publish(
        job_id,
        {
            "type": "progress",
            "message": f"Referensi diperbarui: {result['counts']}",
            "total_items": len(analyzed) or 1,
            "completed_items": 0,
        },
    )

    completed = 0
    for chapter in analyzed:
        if state.cancelled:
            raise asyncio.CancelledError
        _update_job(job_id, current_chapter_id=chapter["id"])
        _publish(
            job_id,
            {
                "type": "chapter",
                "chapter_id": chapter["id"],
                "chapter_number": chapter["chapter_number"],
                "chapter_title": chapter["title"],
                "message": f"Merangkum bab {_fmt_number(chapter['chapter_number'])}…",
            },
        )
        try:
            await summarize_chapter_for_context(chapter["id"], db_path)
        except AnalysisError as exc:
            # A missing summary is not fatal for the reference sheet.
            _publish(
                job_id,
                {
                    "type": "warning",
                    "chapter_id": chapter["id"],
                    "message": f"Ringkasan bab {_fmt_number(chapter['chapter_number'])} dilewati: {exc}",
                },
            )
        completed += 1
        _update_job(job_id, completed_items=completed)
        _publish(
            job_id,
            {
                "type": "progress",
                "completed_items": completed,
                "total_items": len(analyzed) or 1,
                "message": f"{completed}/{len(analyzed)} bab dianalisis",
            },
        )


async def _run_translate(
    state: JobState,
    novel_id: int,
    chapter_ids: list[int] | None,
    db_path: str | None,
) -> None:
    job_id = state.job_id
    if not chapter_ids:
        raise JobError("Tidak ada bab yang dipilih untuk diterjemahkan")

    total = len(chapter_ids)
    _update_job(job_id, total_items=total, message=f"0/{total} bab")
    _publish(
        job_id,
        {"type": "progress", "total_items": total, "completed_items": 0, "message": f"0/{total} bab"},
    )

    completed = 0
    failures: list[str] = []

    for chapter_id in chapter_ids:
        if state.cancelled:
            raise asyncio.CancelledError

        with database.get_conn(db_path) as conn:
            row = conn.execute(
                "SELECT id, chapter_number, title FROM chapters WHERE id = ?", (chapter_id,)
            ).fetchone()
        if row is None:
            failures.append(f"Bab {chapter_id} tidak ditemukan")
            continue

        chapter = dict(row)
        _update_job(job_id, current_chapter_id=chapter_id)
        with database.get_conn(db_path) as conn:
            conn.execute(
                "UPDATE chapters SET status = 'translating', updated_at = ? WHERE id = ?",
                (database.utcnow(), chapter_id),
            )
        _publish(
            job_id,
            {
                "type": "chapter",
                "chapter_id": chapter_id,
                "chapter_number": chapter["chapter_number"],
                "chapter_title": chapter["title"],
                "message": f"Menerjemahkan bab {_fmt_number(chapter['chapter_number'])}: {chapter['title']}",
            },
        )

        async def on_progress(payload: dict[str, Any], _chapter=chapter) -> None:
            _publish(
                job_id,
                {
                    **payload,
                    "chapter_number": _chapter["chapter_number"],
                    "chapter_title": _chapter["title"],
                    "message": (
                        f"Bab {_fmt_number(_chapter['chapter_number'])} — chunk "
                        f"{payload.get('chunk_index')}/{payload.get('chunk_total')}"
                    ),
                },
            )

        try:
            result = await translate_chapter(chapter_id, db_path, on_progress=on_progress)
        except (TranslationError, Exception) as exc:  # noqa: BLE001
            failures.append(f"Bab {_fmt_number(chapter['chapter_number'])}: {exc}")
            with database.get_conn(db_path) as conn:
                conn.execute(
                    "UPDATE chapters SET status = 'error', updated_at = ? WHERE id = ?",
                    (database.utcnow(), chapter_id),
                )
            _publish(
                job_id,
                {
                    "type": "chapter_error",
                    "chapter_id": chapter_id,
                    "chapter_number": chapter["chapter_number"],
                    "message": f"Bab {_fmt_number(chapter['chapter_number'])} gagal: {exc}",
                },
            )
            completed += 1
            _update_job(job_id, completed_items=completed)
            continue

        completed += 1
        _update_job(job_id, completed_items=completed)
        _publish(
            job_id,
            {
                "type": "chapter_done",
                "chapter_id": chapter_id,
                "chapter_number": chapter["chapter_number"],
                "chapter_title": chapter["title"],
                "title_translated": result["title_translated"],
                "quality_score": result["quality"]["score"],
                "grade": result["quality"]["grade"],
                "chunks": result["chunks"],
                "completed_items": completed,
                "total_items": total,
                "message": (
                    f"Bab {_fmt_number(chapter['chapter_number'])} selesai — "
                    f"skor {result['quality']['score']} ({result['quality']['grade']})"
                ),
            },
        )

    if failures and len(failures) == total:
        raise TranslationError("; ".join(failures[:3]))
    if failures:
        _publish(
            job_id,
            {
                "type": "warning",
                "message": f"{len(failures)} bab gagal: {failures[0]}",
            },
        )


def reset_jobs() -> None:
    """Drop in-memory job state (tests)."""
    _JOBS.clear()
