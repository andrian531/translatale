"""69书吧 (69shuba.com and mirrors) — Chinese web novels, GBK encoded."""

from __future__ import annotations

from scrapers.base import SelectorScraper


class Shuba69Scraper(SelectorScraper):
    name = "69shuba"
    display_name = "69书吧 (69shuba)"
    domains = ("69shuba.com", "69shux.com", "69shu.me")
    source_lang = "zh"
    # The site serves GBK; decoding as UTF-8 produces mojibake.
    encoding = "gbk"
    needs_playwright = False

    selectors = {
        "novel_title": ["h1", ".bookname h1"],
        "novel_author_selectors": [".mybox", ".bookinfo .mybox"],
        "novel_author_keyword": "作者",
        "novel_synopsis": [".navtxt", "#intro"],
        "chapter_list": [
            ".qustime ul li a",
            ".tabsnav ul li a",
            "#catalog ul li a",
        ],
        "chapter_content": [".txtnav", "#content", "#chaptercontent"],
        "chapter_content_remove": [
            "script",
            "style",
            ".yuedutuijian",
            "div.txtnav > h1",
            ".ads",
        ],
    }
