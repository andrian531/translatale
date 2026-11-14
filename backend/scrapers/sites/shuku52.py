"""52书库 (52shuku.net) — Chinese web novels.

The site splits a novel into numbered "pages" (第1页, 第2页, …) rather than
chapters; each page is a fetchable content unit, so they map onto chapters.
"""

from __future__ import annotations

import re

from scrapers.base import SelectorScraper, clean_text


class Shuku52Scraper(SelectorScraper):
    name = "52shuku"
    display_name = "52书库 (52shuku)"
    domains = ("52shuku.net",)
    source_lang = "zh"
    encoding = "utf-8"

    selectors = {
        "novel_title": ["h1.article-title", "h1.article-title#nr_title", "h1"],
        # The page has no author element; the name is embedded in the title
        # ("[tag] 书名_作者 【status】"), so _author() parses it from there.
        "novel_author_selectors": [".article-meta .author", "span.author"],
        "novel_author_keyword": "作者",
        "novel_synopsis": [
            "article.article-content blockquote",
            "article.article-content p:first-child",
            "div.article-content blockquote",
        ],
        "chapter_list": [
            "ul.list li.mulu a",
            "ul.article-vlist li a",
        ],
        "chapter_content": ["article.article-content", "div.article-content"],
        "chapter_content_remove": [
            "script",
            "style",
            ".ads",
            ".pagination",
            ".article-social",
            ".article-tags",
            ".post-navigation",
            "article.article-content > h1",
        ],
    }

    def _author(self, soup) -> str:
        author = super()._author(soup)
        if author:
            return author
        title = self._first_text(soup, "novel_title")
        match = re.search(r"_([^_【\[\]]{1,20}?)\s*(?:【|\[|$)", title)
        return match.group(1).strip() if match else ""

    def _synopsis(self, soup) -> str:
        """The blurb sits in the paragraphs after the "简介：" label."""
        node = soup.select_one("article.article-content")
        if node is None:
            return super()._first_text(soup, "novel_synopsis", min_length=8)

        collected: list[str] = []
        started = False
        for paragraph in node.find_all("p"):
            text = clean_text(paragraph.get_text(" ", strip=True))
            if not text:
                continue
            if not started:
                if "简介" in text and len(text) <= 12:
                    started = True
                continue
            if text.startswith(("内容标签", "主角", "一句话简介", "立意", "第1章", "第1页")):
                break
            collected.append(text)
            if len(collected) >= 3:
                break
        return " ".join(collected)[:1000]
