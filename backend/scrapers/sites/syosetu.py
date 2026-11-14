"""Shousetsuka ni Narou (syosetu.com) — Japanese web novels."""

from __future__ import annotations

from scrapers.base import SelectorScraper


class SyosetuScraper(SelectorScraper):
    name = "syosetu"
    display_name = "Shousetsuka ni Narou (小説家になろう)"
    domains = ("syosetu.com", "ncode.syosetu.com", "yomou.syosetu.com")
    source_lang = "ja"
    encoding = "utf-8"

    selectors = {
        "novel_title": [
            ".p-novel__title",
            "h1.p-novel__title",
            ".novel_title",
            "h1",
        ],
        "novel_author_selectors": [
            ".p-novel__author",
            ".novel_writername",
        ],
        "novel_author_keyword": "作者",
        "novel_synopsis": [
            ".p-novel__summary",
            "#novel_ex",
            ".novel_ex",
        ],
        "chapter_list": [
            ".p-eplist__sublist a",
            ".p-eplist a",
            ".novel_sublist dd.subtitle a",
            ".index_box a",
        ],
        "chapter_content": [
            ".p-novel__body",
            "#novel_honbun",
            "#novel_p",
            "#novel_a",
        ],
        "chapter_content_remove": [
            "script",
            "style",
            ".p-novel__text--preface",
            ".p-novel__text--afterword",
            ".novel_bn",
            ".ad",
        ],
    }
