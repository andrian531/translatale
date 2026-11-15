"""Scraper discovery, preview and LLM page-analysis endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from core.synopsis import translate_metadata
from scrapers.base import ScraperError
from scrapers.generic import analyze_page_with_llm
from scrapers.registry import find_scraper, has_dedicated_scraper, list_scrapers

router = APIRouter(prefix="/api/scrapers", tags=["scrapers"])

HTML_SNIPPET_CHARS = 12000


class UrlPayload(BaseModel):
    url: str
    target_lang: str = "id"

    @field_validator("url")
    @classmethod
    def _url_required(cls, value: str) -> str:
        value = (value or "").strip()
        if not value.startswith(("http://", "https://")):
            raise ValueError("url harus diawali http:// atau https://")
        return value


class AnalyzePayload(UrlPayload):
    html_snippet: str | None = None


@router.get("")
def get_scrapers() -> list[dict[str, Any]]:
    return list_scrapers()


@router.post("/preview")
async def preview(payload: UrlPayload) -> dict[str, Any]:
    """Scrape one URL without touching the database.

    The page structure decides what it is: a table of contents means a novel
    page, otherwise we try to read it as a single chapter.
    """
    scraper = find_scraper(payload.url)
    dedicated = has_dedicated_scraper(payload.url)

    try:
        info = await scraper.fetch_novel_info(payload.url)
    except ScraperError as exc:
        info = None
        novel_error = str(exc)
    else:
        novel_error = ""

    if info is not None and info.chapters:
        translated = await translate_metadata(
            title=info.title,
            synopsis=info.synopsis[:1200],
            source_lang=info.source_lang,
            target_lang=payload.target_lang,
            concise_synopsis=True,
        )
        return {
            "ok": True,
            "url": payload.url,
            "scraper": scraper.name,
            "display_name": scraper.display_name,
            "dedicated": dedicated,
            "kind": "novel",
            "title": info.title,
            "title_translated": translated["title_translated"],
            "author": info.author,
            "synopsis": info.synopsis[:800],
            "synopsis_translated": translated["synopsis_translated"][:800],
            "source_lang": info.source_lang,
            "chapter_count": len(info.chapters),
            "chapters": [
                {
                    "chapter_number": chapter.chapter_number,
                    "title": chapter.title,
                    "url": chapter.url,
                }
                for chapter in info.chapters[:20]
            ],
        }

    try:
        content = await scraper.fetch_chapter_content(payload.url)
    except ScraperError as exc:
        detail = novel_error or str(exc)
        raise HTTPException(status_code=422, detail=detail) from exc

    return {
        "ok": True,
        "url": payload.url,
        "scraper": scraper.name,
        "display_name": scraper.display_name,
        "dedicated": dedicated,
        "kind": "chapter",
        "title": content.title,
        "chapter_count": 0,
        "content_preview": content.content[:1500],
        "content_length": len(content.content),
    }


@router.post("/analyze")
async def analyze(payload: AnalyzePayload) -> dict[str, Any]:
    """Ask the configured ``scrape_analysis`` model to describe the page structure."""
    html = payload.html_snippet
    if not html:
        scraper = find_scraper(payload.url)
        try:
            html = await scraper.fetch_html(payload.url)
        except ScraperError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        return await analyze_page_with_llm(payload.url, html)
    except ScraperError as exc:
        # 424: the request is fine, the required task model is not configured.
        raise HTTPException(status_code=424, detail=str(exc)) from exc
