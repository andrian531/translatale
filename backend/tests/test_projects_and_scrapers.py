"""Tests for Phase 2: novel/chapter CRUD, batch upload, and the scraper layer."""

from __future__ import annotations

import pytest

import database
from llm.base import LLMResponse, ResolvedTask
from scrapers.base import ScraperError
from scrapers.registry import find_scraper, get_scraper, list_scrapers

NOVEL_HTML = """
<html><head><title>测试小说 - 69书吧</title></head><body>
  <h1>测试小说</h1>
  <div class="mybox">作者：张三</div>
  <div class="navtxt">这是一个用于测试的简介。</div>
  <div class="qustime"><ul>
    <li><a href="/book/123/1.htm">第1章 开始</a></li>
    <li><a href="/book/123/2.htm">第2章 继续</a></li>
    <li><a href="/book/123/3.htm">第3章 结束</a></li>
  </ul></div>
</body></html>
"""

CHAPTER_HTML = """
<html><head><title>第1章 开始</title></head><body>
  <div class="txtnav">
    <h1>第1章 开始</h1>
    <p>正文第一段。</p>
    <p>正文第二段。</p>
  </div>
</body></html>
"""


@pytest.fixture()
def fake_html(monkeypatch):
    """Serve fixture HTML instead of hitting the network."""
    import re

    async def _fetch_html(self, url):
        # /book/123/1.htm is a chapter page; /book/123.htm is the novel page.
        if re.search(r"/\d+/\d+\.htm$", url):
            return CHAPTER_HTML
        return NOVEL_HTML

    monkeypatch.setattr("scrapers.base.BaseScraper.fetch_html", _fetch_html)
    return _fetch_html


def _create_novel(client, **overrides):
    payload = {
        "title": "Novel Uji",
        "author": "Penulis",
        "source_lang": "zh",
        "target_lang": "id",
        "synopsis": "Sinopsis uji.",
    }
    payload.update(overrides)
    response = client.post("/api/novels", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------
# Novel CRUD
# --------------------------------------------------------------------------
def test_create_and_list_novel(client):
    novel = _create_novel(client)
    assert novel["id"] > 0
    assert novel["source_type"] == "manual"
    assert novel["chapter_count"] == 0

    listed = client.get("/api/novels").json()
    assert len(listed) == 1
    assert listed[0]["title"] == "Novel Uji"


def test_create_novel_requires_title(client):
    assert client.post("/api/novels", json={"title": "   "}).status_code == 422


def test_get_patch_delete_novel(client):
    novel = _create_novel(client)

    patched = client.patch(
        f"/api/novels/{novel['id']}",
        json={"title": "Judul Baru", "author": "Penulis Baru"},
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "Judul Baru"
    assert patched.json()["author"] == "Penulis Baru"

    assert client.delete(f"/api/novels/{novel['id']}").status_code == 200
    assert client.get(f"/api/novels/{novel['id']}").status_code == 404


def test_delete_novel_cascades_chapters(client):
    novel = _create_novel(client)
    client.post(
        f"/api/novels/{novel['id']}/chapters/manual",
        json={"title": "Bab 1", "raw_content": "isi"},
    )
    client.delete(f"/api/novels/{novel['id']}")

    with database.get_conn() as conn:
        remaining = conn.execute("SELECT COUNT(*) AS n FROM chapters").fetchone()["n"]
    assert remaining == 0


def test_missing_novel_returns_404(client):
    assert client.get("/api/novels/999").status_code == 404
    assert client.get("/api/novels/999/chapters").status_code == 404


# --------------------------------------------------------------------------
# Manual chapters
# --------------------------------------------------------------------------
def test_add_manual_chapter_autonumbers(client):
    novel = _create_novel(client)
    first = client.post(
        f"/api/novels/{novel['id']}/chapters/manual",
        json={"title": "Bab Satu", "raw_content": "Isi bab satu."},
    )
    assert first.status_code == 201
    assert first.json()["chapter_number"] == 1.0
    assert first.json()["status"] == "raw"

    second = client.post(
        f"/api/novels/{novel['id']}/chapters/manual",
        json={"raw_content": "Isi bab dua."},
    ).json()
    assert second["chapter_number"] == 2.0
    assert second["title"] == "Chapter 2"

    chapters = client.get(f"/api/novels/{novel['id']}/chapters").json()
    assert [c["chapter_number"] for c in chapters] == [1.0, 2.0]

    novel_after = client.get(f"/api/novels/{novel['id']}").json()
    assert novel_after["chapter_count"] == 2
    assert novel_after["raw_count"] == 2


def test_manual_chapter_rejects_empty_content(client):
    novel = _create_novel(client)
    response = client.post(
        f"/api/novels/{novel['id']}/chapters/manual",
        json={"title": "Kosong", "raw_content": "   "},
    )
    assert response.status_code == 422


def test_update_and_delete_chapter(client):
    novel = _create_novel(client)
    chapter = client.post(
        f"/api/novels/{novel['id']}/chapters/manual",
        json={"title": "Bab 1", "raw_content": "isi lama"},
    ).json()

    patched = client.patch(
        f"/api/chapters/{chapter['id']}",
        json={"title": "Bab 1 (edit)", "raw_content": "isi baru"},
    )
    assert patched.status_code == 200
    assert patched.json()["raw_content"] == "isi baru"

    assert client.delete(f"/api/chapters/{chapter['id']}").status_code == 200
    assert client.get(f"/api/chapters/{chapter['id']}").status_code == 404


def test_chapter_status_filter(client):
    novel = _create_novel(client)
    client.post(
        f"/api/novels/{novel['id']}/chapters/manual",
        json={"title": "Bab 1", "raw_content": "isi"},
    )
    raw = client.get(f"/api/novels/{novel['id']}/chapters?status=raw").json()
    assert len(raw) == 1
    pending = client.get(f"/api/novels/{novel['id']}/chapters?status=pending_fetch").json()
    assert pending == []


# --------------------------------------------------------------------------
# Batch upload
# --------------------------------------------------------------------------
def test_upload_txt_batch_orders_by_filename(client):
    novel = _create_novel(client)
    files = [
        ("files", ("002_kedua.txt", "Judul Kedua\nIsi kedua.".encode(), "text/plain")),
        ("files", ("001_pertama.txt", "Judul Pertama\nIsi pertama.".encode(), "text/plain")),
        ("files", ("tanpa_nomor.txt", "Isi tanpa nomor.".encode(), "text/plain")),
    ]
    response = client.post(f"/api/novels/{novel['id']}/chapters/upload", files=files)
    assert response.status_code == 201, response.text
    created = response.json()
    assert len(created) == 3

    chapters = client.get(f"/api/novels/{novel['id']}/chapters").json()
    numbers = [c["chapter_number"] for c in chapters]
    assert numbers == sorted(numbers)
    assert chapters[0]["title"] == "Judul Pertama"
    assert chapters[1]["title"] == "Judul Kedua"
    assert chapters[0]["status"] == "raw"
    assert "Isi pertama." in chapters[0]["raw_content"]


def test_upload_continues_numbering_after_existing(client):
    novel = _create_novel(client)
    client.post(
        f"/api/novels/{novel['id']}/chapters/manual",
        json={"title": "Bab 1", "raw_content": "isi"},
    )
    response = client.post(
        f"/api/novels/{novel['id']}/chapters/upload",
        files=[("files", ("tanpa_nomor.txt", "Isi.".encode(), "text/plain"))],
    )
    assert response.status_code == 201
    assert response.json()[0]["chapter_number"] == 2.0


def test_upload_shifts_batch_when_numbers_collide(client):
    novel = _create_novel(client)
    client.post(
        f"/api/novels/{novel['id']}/chapters/manual",
        json={"title": "Bab 1", "raw_content": "isi"},
    )
    response = client.post(
        f"/api/novels/{novel['id']}/chapters/upload",
        files=[
            ("files", ("001_a.txt", "A\nisi a".encode(), "text/plain")),
            ("files", ("002_b.txt", "B\nisi b".encode(), "text/plain")),
        ],
    )
    assert response.status_code == 201
    chapters = client.get(f"/api/novels/{novel['id']}/chapters").json()
    numbers = [c["chapter_number"] for c in chapters]
    assert numbers == [1.0, 2.0, 3.0]
    assert len(set(numbers)) == len(numbers)


def test_upload_rejects_empty_files(client):
    novel = _create_novel(client)
    response = client.post(
        f"/api/novels/{novel['id']}/chapters/upload",
        files=[("files", ("kosong.txt", b"   ", "text/plain"))],
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Scraper registry
# --------------------------------------------------------------------------
def test_registry_lists_all_site_modules():
    names = {scraper["name"] for scraper in list_scrapers()}
    assert {"69shuba", "syosetu", "bq730", "52shuku"} <= names


def test_registry_matches_domains():
    assert find_scraper("https://www.69shuba.com/book/1.htm").name == "69shuba"
    assert find_scraper("https://ncode.syosetu.com/n1234ab/").name == "syosetu"
    assert find_scraper("https://www.bq730.cc/book/1/").name == "bq730"
    assert find_scraper("https://www.52shuku.net/novel/1.html").name == "52shuku"
    # Unknown host falls back to the generic scraper.
    assert find_scraper("https://unknown-site.example/book/1").name == "generic"


def test_registry_unknown_name_raises():
    with pytest.raises(ScraperError):
        get_scraper("does-not-exist")


def test_scrapers_endpoint(client):
    response = client.get("/api/scrapers")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) >= 4
    entry = next(item for item in payload if item["name"] == "69shuba")
    assert "69shuba.com" in entry["domains"]


# --------------------------------------------------------------------------
# Scraper-driven novel creation (network mocked)
# --------------------------------------------------------------------------
def test_create_novel_from_url_saves_pending_chapters(client, fake_html):
    response = client.post(
        "/api/novels/from-url", json={"url": "https://www.69shuba.com/book/123.htm"}
    )
    assert response.status_code == 201, response.text
    novel = response.json()
    assert novel["title"] == "测试小说"
    assert novel["author"] == "张三"
    assert novel["source_type"] == "scraper"
    assert novel["scraper_name"] == "69shuba"
    assert novel["chapter_count"] == 3
    assert novel["pending_count"] == 3

    chapters = client.get(f"/api/novels/{novel['id']}/chapters").json()
    assert chapters[0]["status"] == "pending_fetch"
    assert chapters[0]["source_url"].endswith("/book/123/1.htm")
    assert chapters[0]["raw_content"] == ""


def test_fetch_chapters_fills_raw_content(client, fake_html):
    novel = client.post(
        "/api/novels/from-url", json={"url": "https://www.69shuba.com/book/123.htm"}
    ).json()
    chapters = client.get(f"/api/novels/{novel['id']}/chapters").json()
    ids = [chapters[0]["id"], chapters[1]["id"]]

    response = client.post(
        f"/api/novels/{novel['id']}/chapters/fetch", json={"chapter_ids": ids}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["fetched"] == 2
    assert body["failed"] == 0

    refreshed = client.get(f"/api/novels/{novel['id']}/chapters").json()
    assert refreshed[0]["status"] == "raw"
    assert "正文第一段" in refreshed[0]["raw_content"]
    # The h1 inside .txtnav is stripped by chapter_content_remove.
    assert "第1章 开始" not in refreshed[0]["raw_content"]
    assert refreshed[2]["status"] == "pending_fetch"


def test_fetch_chapters_reports_errors(client):
    novel = _create_novel(client)

    chapter = client.post(
        f"/api/novels/{novel['id']}/chapters/manual",
        json={"title": "Bab 1", "raw_content": "isi"},
    ).json()

    # Manual chapters have no source_url, so fetching must fail cleanly.
    response = client.post(
        f"/api/novels/{novel['id']}/chapters/fetch", json={"chapter_ids": [chapter["id"]]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["failed"] == 1
    assert "source_url" in body["errors"][0]["error"]


def test_fetch_chapters_marks_error_status(client, monkeypatch):
    async def _boom(self, url):
        raise ScraperError("HTTP 500 untuk halaman")

    monkeypatch.setattr("scrapers.base.BaseScraper.fetch_html", _boom)

    novel = client.post(
        "/api/novels/from-url", json={"url": "https://www.69shuba.com/book/123.htm"}
    )
    # Novel creation itself fails because the page cannot be fetched.
    assert novel.status_code == 422
    assert "HTTP 500" in novel.json()["detail"]


def test_from_url_rejects_bad_url(client):
    assert client.post("/api/novels/from-url", json={"url": "not-a-url"}).status_code == 422


# --------------------------------------------------------------------------
# Scraper preview / analyze endpoints
# --------------------------------------------------------------------------
def test_preview_novel_url(client, fake_html):
    response = client.post(
        "/api/scrapers/preview", json={"url": "https://www.69shuba.com/book/123.htm"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "novel"
    assert body["scraper"] == "69shuba"
    assert body["dedicated"] is True
    assert body["chapter_count"] == 3
    assert body["chapters"][0]["title"] == "第1章 开始"


def test_preview_chapter_url(client, fake_html):
    response = client.post(
        "/api/scrapers/preview", json={"url": "https://www.69shuba.com/book/123/1.htm"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "chapter"
    assert "正文第一段" in body["content_preview"]


def test_analyze_without_configured_task_returns_424(client):
    response = client.post(
        "/api/scrapers/analyze",
        json={"url": "https://www.69shuba.com/book/123.htm", "html_snippet": "<html></html>"},
    )
    assert response.status_code == 424
    assert "Settings" in response.json()["detail"]


def test_analyze_uses_configured_task_model(client, monkeypatch):
    captured = {}

    class StubProvider:
        async def generate(self, prompt, system_prompt=None, model=None, temperature=0.7, max_tokens=4096):
            captured["model"] = model
            captured["prompt"] = prompt
            return LLMResponse(
                text='```json\n{"page_type": "novel", "title_selector": "h1", '
                '"chapter_list_selector": ".qustime a", "chapter_content_selector": ".txtnav", '
                '"remove_selectors": ["script"], "notes": "ok"}\n```'
            )

    def _resolve(self):
        return ResolvedTask(
            task_name="scrape_analysis",
            provider=StubProvider(),
            provider_id=1,
            provider_type="deepseek",
            model="deepseek-chat",
            temperature=0.2,
            max_tokens=2048,
        )

    monkeypatch.setattr("llm.base.TaskRouter.resolve", _resolve)

    response = client.post(
        "/api/scrapers/analyze",
        json={"url": "https://www.69shuba.com/book/123.htm", "html_snippet": "<h1>x</h1>"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["model"] == "deepseek-chat"
    assert body["analysis"]["chapter_content_selector"] == ".txtnav"
    assert captured["model"] == "deepseek-chat"


def test_clear_chapter_translations_preserves_raw_and_resets_status(client):
    novel_a = client.post("/api/novels", json={"title": "Novel A"}).json()
    novel_b = client.post("/api/novels", json={"title": "Novel B"}).json()

    ch_raw = client.post(
        f"/api/novels/{novel_a['id']}/chapters/manual",
        json={"chapter_number": 1, "title": "Bab 1", "raw_content": "Isi mentah bab 1"},
    ).json()
    ch_empty = client.post(
        f"/api/novels/{novel_a['id']}/chapters/manual",
        json={"chapter_number": 2, "title": "Bab 2", "raw_content": "sementara"},
    ).json()
    ch_other = client.post(
        f"/api/novels/{novel_b['id']}/chapters/manual",
        json={"chapter_number": 1, "title": "Other 1", "raw_content": "Other raw"},
    ).json()

    # Mark them as translated / error with translated fields populated.
    client.patch(
        f"/api/chapters/{ch_raw['id']}",
        json={
            "title_translated": "Bab 1 TL",
            "translated_content": "Hasil terjemahan 1",
            "status": "translated",
            "quality_score": 95.0,
        },
    )
    client.patch(
        f"/api/chapters/{ch_empty['id']}",
        json={
            "raw_content": "",
            "title_translated": "Bab 2 TL",
            "translated_content": "Sisa error",
            "status": "error",
        },
    )
    client.patch(
        f"/api/chapters/{ch_other['id']}",
        json={
            "title_translated": "Other TL",
            "translated_content": "Harus tetap ada",
            "status": "translated",
        },
    )

    resp = client.post(
        f"/api/novels/{novel_a['id']}/chapters/clear-translation",
        json={"chapter_ids": [ch_raw["id"], ch_empty["id"], ch_other["id"]]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "cleared": 2}

    updated_raw = client.get(f"/api/chapters/{ch_raw['id']}").json()
    assert updated_raw["raw_content"] == "Isi mentah bab 1"
    assert updated_raw["translated_content"] == ""
    assert updated_raw["title_translated"] == ""
    assert updated_raw["quality_score"] is None
    assert updated_raw["status"] == "raw"

    updated_empty = client.get(f"/api/chapters/{ch_empty['id']}").json()
    assert updated_empty["translated_content"] == ""
    assert updated_empty["title_translated"] == ""
    assert updated_empty["status"] == "pending_fetch"

    untouched_other = client.get(f"/api/chapters/{ch_other['id']}").json()
    assert untouched_other["translated_content"] == "Harus tetap ada"
    assert untouched_other["status"] == "translated"


def test_clear_chapter_translations_rejects_empty_list(client):
    novel = client.post("/api/novels", json={"title": "Novel Empty"}).json()
    resp = client.post(
        f"/api/novels/{novel['id']}/chapters/clear-translation",
        json={"chapter_ids": []},
    )
    assert resp.status_code == 422


def test_upload_get_and_delete_novel_cover(client):
    novel = client.post("/api/novels", json={"title": "Cover Novel"}).json()
    assert novel["cover_url"] == ""

    # Rejects non-image extension
    bad = client.post(
        f"/api/novels/{novel['id']}/cover",
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    assert bad.status_code == 422

    # Upload valid PNG bytes
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    up = client.post(
        f"/api/novels/{novel['id']}/cover",
        files={"file": ("cover.png", png_bytes, "image/png")},
    )
    assert up.status_code == 200, up.text
    assert up.json()["cover_url"].startswith(f"/api/novels/{novel['id']}/cover")

    # Fetch cover image
    fetched = client.get(f"/api/novels/{novel['id']}/cover")
    assert fetched.status_code == 200
    assert fetched.content == png_bytes

    # Delete cover
    deleted = client.delete(f"/api/novels/{novel['id']}/cover")
    assert deleted.status_code == 200
    assert deleted.json()["cover_url"] == ""
    assert client.get(f"/api/novels/{novel['id']}/cover").status_code == 404
