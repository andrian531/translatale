"""笔趣阁 (bq730.cc and mirrors) — Chinese web novels."""

from __future__ import annotations

from scrapers.base import SelectorScraper


class Bq730Scraper(SelectorScraper):
    name = "bq730"
    display_name = "笔趣阁 (bq730)"
    domains = ("bq730.cc", "bqg265.top", "bqg291.cc")
    source_lang = "zh"
    encoding = "utf-8"

    selectors = {
        "novel_title": ["h1", ".book h1"],
        "novel_author_selectors": ["div.info p", ".book .info p"],
        "novel_author_keyword": "作者",
        "novel_synopsis": ["div.intro", "#intro"],
        "chapter_list": [
            "div.listmain dd a",
            "div#list dd a",
            "ul.lis li a",
        ],
        "chapter_content": ["div#content", "div#chaptercontent"],
        "chapter_content_remove": [
            "script",
            "style",
            ".ad",
            "div.footer",
            "div.read-pro-inner",
        ],
    }
