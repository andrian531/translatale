"""Modular per-site scrapers."""

from scrapers.base import (
    BaseScraper,
    ChapterContent,
    ChapterMeta,
    NovelInfo,
    ScraperError,
    SelectorScraper,
)
from scrapers.registry import find_scraper, get_scraper, list_scrapers

__all__ = [
    "BaseScraper",
    "ChapterContent",
    "ChapterMeta",
    "NovelInfo",
    "ScraperError",
    "SelectorScraper",
    "find_scraper",
    "get_scraper",
    "list_scrapers",
]
