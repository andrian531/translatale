"""Scraper contract and the selector-driven base implementation.

Every site module in ``scrapers/sites/`` subclasses :class:`SelectorScraper` and
only declares its domains plus a selector map, so a site whose HTML changes is
fixed in exactly one file.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8,en;q=0.7",
}

REQUEST_TIMEOUT = 30.0

#: Links that are navigation, not chapters.
_SKIP_HREF = re.compile(r"^(#|javascript:|mailto:)", re.IGNORECASE)
_CHAPTER_HINT = re.compile(
    r"(chapter|chap[-_]?\d|episode|/read/|/\d+/\d+(\.html?)?$|/\d+_\d+\.html?$)",
    re.IGNORECASE,
)


class ScraperError(RuntimeError):
    """Raised when a page cannot be fetched or parsed."""


@dataclass
class ChapterMeta:
    """One entry of a novel's table of contents."""

    chapter_number: float
    title: str
    url: str = ""
    title_translated: str = ""


@dataclass
class NovelInfo:
    """Novel metadata plus its chapter list."""

    title: str
    author: str = ""
    synopsis: str = ""
    source_url: str = ""
    source_lang: str = "zh"
    scraper_name: str = ""
    chapters: list[ChapterMeta] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChapterContent:
    """Fetched body text of a single chapter."""

    title: str
    content: str
    url: str = ""
    chapter_number: float | None = None


def clean_text(value: str | None) -> str:
    """Collapse whitespace while keeping paragraph breaks."""
    if not value:
        return ""
    text = value.replace("\r\n", "\n").replace("\r", "\n").replace("\u3000", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


class BaseScraper(ABC):
    """Interface every site module implements."""

    name: str = "base"
    display_name: str = "Base"
    domains: tuple[str, ...] = ()
    source_lang: str = "zh"
    encoding: str = "utf-8"
    needs_playwright: bool = False

    # -- identity ---------------------------------------------------------
    def can_handle(self, url: str) -> bool:
        """True when this module owns the URL's host."""
        host = (urlparse(url).netloc or "").lower()
        if not host:
            return False
        host = host.split(":")[0]
        return any(host == domain or host.endswith(f".{domain}") for domain in self.domains)

    # -- transport --------------------------------------------------------
    async def fetch_html(self, url: str) -> str:
        """Download a page and decode it with the site's declared encoding."""
        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT, follow_redirects=True, headers=DEFAULT_HEADERS
            ) as client:
                response = await client.get(url)
        except httpx.HTTPError as exc:
            raise ScraperError(f"Gagal mengambil {url}: {exc}") from exc

        if response.status_code >= 400:
            raise ScraperError(f"HTTP {response.status_code} untuk {url}")

        raw = response.content
        for encoding in (self.encoding, response.encoding, "utf-8"):
            if not encoding:
                continue
            try:
                return raw.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def make_soup(html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "html.parser")

    # -- contract ---------------------------------------------------------
    @abstractmethod
    async def fetch_novel_info(self, url: str) -> NovelInfo:
        """Novel metadata (title/author/synopsis) for a novel page."""

    @abstractmethod
    async def fetch_chapter_list(self, url: str) -> list[ChapterMeta]:
        """Table of contents for a novel page."""

    @abstractmethod
    async def fetch_chapter_content(self, url: str) -> ChapterContent:
        """Body text of one chapter page."""


class SelectorScraper(BaseScraper):
    """BaseScraper driven entirely by a CSS-selector map.

    Subclasses set ``selectors`` (see ``scrapers/sites/*.py``) and inherit the
    parsing logic, so adding a site is a data change, not a code change.
    """

    selectors: dict[str, Any] = {}

    # -- selector helpers -------------------------------------------------
    def _first(self, soup: BeautifulSoup, key: str):
        for selector in self.selectors.get(key) or []:
            try:
                node = soup.select_one(selector)
            except Exception:  # invalid selector in a site config
                continue
            if node is not None:
                return node
        return None

    def _first_text(self, soup: BeautifulSoup, key: str, min_length: int = 1) -> str:
        """First non-empty text for a selector list, skipping stub labels."""
        for selector in self.selectors.get(key) or []:
            try:
                node = soup.select_one(selector)
            except Exception:  # invalid selector in a site config
                continue
            if node is None:
                continue
            text = clean_text(node.get_text(" ", strip=True))
            if len(text) >= min_length:
                return text
        return ""

    def _all(self, soup: BeautifulSoup, key: str) -> list:
        for selector in self.selectors.get(key) or []:
            try:
                nodes = soup.select(selector)
            except Exception:
                continue
            if nodes:
                return nodes
        return []

    def _author(self, soup: BeautifulSoup) -> str:
        keyword = self.selectors.get("novel_author_keyword", "作者")
        for selector in self.selectors.get("novel_author_selectors") or []:
            try:
                nodes = soup.select(selector)
            except Exception:
                continue
            for node in nodes:
                text = clean_text(node.get_text(" ", strip=True))
                if not text:
                    continue
                if keyword and keyword in text:
                    match = re.search(rf"{keyword}\s*[:：]\s*([^\s|/]+)", text)
                    if match:
                        return match.group(1).strip()
                if len(text) <= 40:
                    return text
        return ""

    def _synopsis(self, soup: BeautifulSoup) -> str:
        """Default: first selector hit that is not a stub label."""
        return self._first_text(soup, "novel_synopsis", min_length=8)

    # -- contract ---------------------------------------------------------
    async def fetch_novel_info(self, url: str) -> NovelInfo:
        html = await self.fetch_html(url)
        soup = self.make_soup(html)

        title = self._first_text(soup, "novel_title")
        if not title:
            title = clean_text(soup.title.get_text()) if soup.title else ""
        if not title:
            raise ScraperError(f"Judul novel tidak ditemukan di {url}")

        chapters = self._extract_chapters(soup, url)
        return NovelInfo(
            title=title,
            author=self._author(soup),
            synopsis=self._synopsis(soup),
            source_url=url,
            source_lang=self.source_lang,
            scraper_name=self.name,
            chapters=chapters,
        )

    async def fetch_chapter_list(self, url: str) -> list[ChapterMeta]:
        html = await self.fetch_html(url)
        return self._extract_chapters(self.make_soup(html), url)

    def _extract_chapters(self, soup: BeautifulSoup, base_url: str) -> list[ChapterMeta]:
        chapters: list[ChapterMeta] = []
        seen: set[str] = set()

        for node in self._all(soup, "chapter_list"):
            href = node.get("href") or ""
            if not href or _SKIP_HREF.match(href):
                continue
            absolute = urljoin(base_url, href)
            if absolute in seen:
                continue
            title = clean_text(node.get_text(" ", strip=True))
            if not title:
                continue
            seen.add(absolute)
            chapters.append(
                ChapterMeta(
                    chapter_number=float(len(chapters) + 1),
                    title=title,
                    url=absolute,
                )
            )
        return chapters

    async def fetch_chapter_content(self, url: str) -> ChapterContent:
        html = await self.fetch_html(url)
        soup = self.make_soup(html)

        for selector in self.selectors.get("chapter_content_remove") or []:
            try:
                for node in soup.select(selector):
                    node.decompose()
            except Exception:
                continue

        node = self._first(soup, "chapter_content")
        if node is None:
            raise ScraperError(f"Konten bab tidak ditemukan di {url}")

        content = clean_text(node.get_text("\n", strip=True))
        if not content:
            raise ScraperError(f"Konten bab kosong di {url}")

        title = self._first_text(soup, "novel_title")
        if not title and soup.title:
            title = clean_text(soup.title.get_text())
        return ChapterContent(title=title, content=content, url=url)


def looks_like_chapter_url(url: str) -> bool:
    """Heuristic used by the generic scraper and the preview endpoint."""
    return bool(_CHAPTER_HINT.search(urlparse(url).path or ""))


def iter_unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
