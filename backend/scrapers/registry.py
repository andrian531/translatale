"""Auto-discovery of site modules and URL -> scraper matching."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from functools import lru_cache
from typing import Any

import scrapers.sites as sites_package
from scrapers.base import BaseScraper, ScraperError
from scrapers.generic import GenericScraper


@lru_cache(maxsize=1)
def _load_scrapers() -> tuple[BaseScraper, ...]:
    """Import every module in ``scrapers/sites/`` and instantiate its scraper.

    Adding a site is dropping a file in that directory — no registration list to
    keep in sync.
    """
    found: list[BaseScraper] = []
    for module_info in pkgutil.iter_modules(sites_package.__path__):
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"scrapers.sites.{module_info.name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, BaseScraper)
                and obj is not BaseScraper
                and obj.__module__ == module.__name__
                and not inspect.isabstract(obj)
            ):
                found.append(obj())
    found.sort(key=lambda scraper: scraper.name)
    return tuple(found)


def list_scrapers() -> list[dict[str, Any]]:
    """Metadata for the Scrapers page and ``GET /api/scrapers``."""
    return [
        {
            "name": scraper.name,
            "display_name": scraper.display_name,
            "domains": list(scraper.domains),
            "source_lang": scraper.source_lang,
            "needs_playwright": scraper.needs_playwright,
        }
        for scraper in _load_scrapers()
    ]


def get_scraper(name: str) -> BaseScraper:
    """Look up a site module by name (``generic`` included)."""
    if name == GenericScraper.name:
        return GenericScraper()
    for scraper in _load_scrapers():
        if scraper.name == name:
            return scraper
    raise ScraperError(f"Scraper tidak dikenal: {name}")


def find_scraper(url: str, allow_generic: bool = True) -> BaseScraper:
    """Return the site module that owns ``url``, else the generic fallback."""
    for scraper in _load_scrapers():
        if scraper.can_handle(url):
            return scraper
    if allow_generic:
        return GenericScraper()
    raise ScraperError(f"Tidak ada modul scraper untuk URL: {url}")


def has_dedicated_scraper(url: str) -> bool:
    return any(scraper.can_handle(url) for scraper in _load_scrapers())


def reset_cache() -> None:
    """Drop the discovery cache (used by tests that add modules)."""
    _load_scrapers.cache_clear()
