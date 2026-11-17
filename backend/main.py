"""Translatale backend entrypoint.

Run from the ``backend`` directory:

    uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

import config
import database
from core import job_runner
from core.i18n import reset_ui_lang, set_ui_lang
from routers import projects, reader, scrapers, settings, translation

__version__ = "0.2.0"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create the data directory and initialise the SQLite schema."""
    config.ensure_data_dir()
    database.init_db()
    job_runner.cleanup_orphaned_jobs()
    yield


app = FastAPI(
    title="Translatale API",
    description="Web-based AI novel translator — Phase 1 (foundation & settings).",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def ui_language_middleware(request: Request, call_next):
    lang = request.headers.get("x-ui-lang") or request.query_params.get("lang")
    token = set_ui_lang(lang)
    try:
        return await call_next(request)
    finally:
        reset_ui_lang(token)

app.include_router(settings.router)
app.include_router(projects.router)
app.include_router(scrapers.router)
app.include_router(translation.router)
app.include_router(reader.router)


@app.get("/api/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "version": __version__,
        "database": str(database.get_db_path()),
        "tasks": list(config.TASKS),
    }
