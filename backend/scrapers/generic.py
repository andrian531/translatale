"""Fallback scraper for sites without a dedicated module, plus LLM page analysis."""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from llm.base import LLMError, TaskNotConfiguredError, TaskRouter
from scrapers.base import (
    BaseScraper,
    ChapterContent,
    ChapterMeta,
    NovelInfo,
    ScraperError,
    clean_text,
    looks_like_chapter_url,
)

_CHAPTER_TEXT = re.compile(r"(第\s*\d+\s*[章节話话回]|chapter\s*\d+|^\d+[.、\s])", re.IGNORECASE)
_NOISE_TAGS = ("script", "style", "nav", "header", "footer", "aside", "form", "noscript")


class GenericScraper(BaseScraper):
    """Best-effort extraction for unknown domains.

    Deliberately heuristic: it looks for the biggest text block and the largest
    cluster of chapter-looking links. When it guesses wrong, the user can run
    the LLM analysis (``analyze_page_with_llm``) to get real selectors.
    """

    name = "generic"
    display_name = "Generic (heuristic)"
    domains = ()
    source_lang = "zh"
    encoding = "utf-8"

    def can_handle(self, url: str) -> bool:
        # Fallback: claims every http(s) URL the registry could not match.
        return urlparse(url).scheme in ("http", "https")

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _meta(soup: BeautifulSoup, *names: str) -> str:
        for name in names:
            node = soup.find("meta", attrs={"property": name}) or soup.find(
                "meta", attrs={"name": name}
            )
            if node and node.get("content"):
                return clean_text(node["content"])
        return ""

    def _title(self, soup: BeautifulSoup) -> str:
        for candidate in (
            self._meta(soup, "og:title", "twitter:title"),
            clean_text(soup.h1.get_text(" ", strip=True)) if soup.h1 else "",
            clean_text(soup.title.get_text()) if soup.title else "",
        ):
            if candidate:
                return candidate
        return ""

    def _author(self, soup: BeautifulSoup) -> str:
        meta = self._meta(soup, "author", "og:novel:author")
        if meta:
            return meta
        text = soup.get_text(" ", strip=True)[:4000]
        match = re.search(r"(?:作者|Author)\s*[:：]\s*([^\s|/]{1,40})", text)
        return match.group(1).strip() if match else ""

    def _synopsis(self, soup: BeautifulSoup) -> str:
        meta = self._meta(soup, "description", "og:description")
        if meta:
            return meta
        best = ""
        for node in soup.find_all("p"):
            text = clean_text(node.get_text(" ", strip=True))
            if len(text) > len(best):
                best = text
        return best[:2000]

    def _chapter_links(self, soup: BeautifulSoup, base_url: str) -> list[ChapterMeta]:
        candidates: list[tuple[str, str]] = []
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if not href or href.startswith(("#", "javascript:", "mailto:")):
                continue
            absolute = urljoin(base_url, href)
            if urlparse(absolute).netloc != urlparse(base_url).netloc:
                continue
            text = clean_text(anchor.get_text(" ", strip=True))
            if not text or len(text) > 120:
                continue
            if _CHAPTER_TEXT.search(text) or looks_like_chapter_url(absolute):
                candidates.append((absolute, text))

        if not candidates:
            return []

        # Keep the dominant URL shape (the TOC), dropping nav/footer stragglers.
        shapes = Counter(
            re.sub(r"\d+", "#", urlparse(url).path) for url, _ in candidates
        )
        dominant, _ = shapes.most_common(1)[0]

        chapters: list[ChapterMeta] = []
        seen: set[str] = set()
        for url, text in candidates:
            if re.sub(r"\d+", "#", urlparse(url).path) != dominant or url in seen:
                continue
            seen.add(url)
            chapters.append(
                ChapterMeta(chapter_number=float(len(chapters) + 1), title=text, url=url)
            )
        return chapters

    def _content_node(self, soup: BeautifulSoup):
        for tag in _NOISE_TAGS:
            for node in soup.find_all(tag):
                node.decompose()

        best, best_len = None, 0
        for node in soup.find_all(["article", "div", "section", "main"]):
            text = node.get_text(" ", strip=True)
            if len(text) > best_len:
                best, best_len = node, len(text)
        return best

    # -- contract ---------------------------------------------------------
    async def fetch_novel_info(self, url: str) -> NovelInfo:
        html = await self.fetch_html(url)
        soup = self.make_soup(html)
        title = self._title(soup)
        if not title:
            raise ScraperError(f"Judul tidak ditemukan di {url}")
        return NovelInfo(
            title=title,
            author=self._author(soup),
            synopsis=self._synopsis(soup),
            source_url=url,
            source_lang=self.source_lang,
            scraper_name=self.name,
            chapters=self._chapter_links(soup, url),
        )

    async def fetch_chapter_list(self, url: str) -> list[ChapterMeta]:
        html = await self.fetch_html(url)
        return self._chapter_links(self.make_soup(html), url)

    async def fetch_chapter_content(self, url: str) -> ChapterContent:
        html = await self.fetch_html(url)
        soup = self.make_soup(html)
        title = self._title(soup)
        node = self._content_node(soup)
        content = clean_text(node.get_text("\n", strip=True)) if node is not None else ""
        if not content:
            raise ScraperError(f"Konten tidak ditemukan di {url}")
        return ChapterContent(title=title, content=content, url=url)


# --------------------------------------------------------------------------
# LLM-assisted page analysis (uses the "scrape_analysis" task model)
# --------------------------------------------------------------------------
ANALYSIS_SYSTEM_PROMPT = (
    "You are a web scraping analyst. You receive the HTML of a novel website page "
    "and return a compact JSON description of how to extract data from it. "
    "Answer with JSON only, no prose, no markdown fences."
)

ANALYSIS_PROMPT = """Analyse this page and return JSON with exactly these keys:
{{
  "page_type": "novel" | "chapter" | "listing" | "unknown",
  "title_selector": "CSS selector or empty string",
  "author_selector": "CSS selector or empty string",
  "synopsis_selector": "CSS selector or empty string",
  "chapter_list_selector": "CSS selector for the table-of-contents links or empty string",
  "chapter_content_selector": "CSS selector for the chapter body or empty string",
  "remove_selectors": ["CSS selectors of elements to strip"],
  "notes": "one short sentence"
}}

URL: {url}

HTML (truncated):
{html}
"""


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_json(text: str) -> dict[str, Any] | None:
    candidate = _strip_code_fence(text)
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", candidate, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
    return None


async def analyze_page_with_llm(
    url: str,
    html_snippet: str,
    task_name: str = "scrape_analysis",
    max_chars: int = 12000,
) -> dict[str, Any]:
    """Ask the configured ``scrape_analysis`` model how to scrape this page.

    Raises :class:`ScraperError` with an actionable message when the task has no
    provider/model configured in Settings.
    """
    router = TaskRouter(task_name)
    try:
        resolved = router.resolve()
    except TaskNotConfiguredError as exc:
        raise ScraperError(
            f"Task '{task_name}' belum dikonfigurasi. Buka Settings → Model Routing "
            f"per Proses dan pilih provider + model untuk Scraping / Site Analysis. ({exc})"
        ) from exc

    prompt = ANALYSIS_PROMPT.format(url=url, html=html_snippet[:max_chars])
    try:
        response = await resolved.provider.generate(
            prompt=prompt,
            system_prompt=ANALYSIS_SYSTEM_PROMPT,
            model=resolved.model,
            temperature=resolved.temperature,
            max_tokens=resolved.max_tokens,
        )
    except LLMError as exc:
        raise ScraperError(f"Analisis LLM gagal: {exc}") from exc

    analysis = _parse_json(response.text)
    return {
        "ok": True,
        "url": url,
        "provider_type": resolved.provider_type,
        "model": resolved.model,
        "analysis": analysis,
        "raw": None if analysis else response.text,
    }
