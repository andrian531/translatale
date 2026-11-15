"""Scraper settings, chapters-from-URL, TOC sync and batch fetch jobs."""

from __future__ import annotations

import re
import time

import pytest

import database
from scrapers.base import ScraperError

NOVEL_URL = "https://www.69shuba.com/book/123.htm"


def _chapter_url(number: int) -> str:
    return f"https://www.69shuba.com/book/123/chapter-{number}.htm"


@pytest.fixture()
def site(monkeypatch):
    """Mock the HTTP layer of the 69shuba module.

    ``state["chapters"]`` controls how many entries the TOC advertises and
    ``state["fail"]`` lists chapter URLs that should raise a 403.
    """
    state = {"chapters": 3, "fail": set(), "delay": 0.0}

    async def _fetch_html(self, url):
        if state["delay"]:
            import asyncio

            await asyncio.sleep(state["delay"])
        if url in state["fail"]:
            raise ScraperError(f"HTTP 403 untuk {url}")
        match = re.search(r"/chapter-(\d+)\.htm$", url)
        if match:
            number = match.group(1)
            return (
                "<html><body>"
                f"<h1>Bab {number}</h1>"
                f'<div class="txtnav"><p>Isi bab {number}.</p></div>'
                "</body></html>"
            )
        links = "".join(
            f'<li><a href="/book/123/chapter-{index}.htm">Bab {index}</a></li>'
            for index in range(1, state["chapters"] + 1)
        )
        return (
            "<html><body>"
            "<h1>Novel Uji Batch</h1>"
            '<div class="mybox">作者：Penulis Uji</div>'
            f'<div class="qustime"><ul>{links}</ul></div>'
            "</body></html>"
        )

    monkeypatch.setattr("scrapers.base.BaseScraper.fetch_html", _fetch_html)
    return state


def _create_scraped_novel(client) -> dict:
    response = client.post("/api/novels/from-url", json={"url": NOVEL_URL})
    assert response.status_code == 201, response.text
    return response.json()


def _chapters(client, novel_id):
    return client.get(f"/api/novels/{novel_id}/chapters").json()


def _wait_for_job(client, job_id, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} tidak selesai dalam {timeout}s")


def _fast_fetch_settings(client, **overrides):
    payload = {
        "fetch_batch_size": 50,
        "fetch_delay_seconds": 0,
        "fetch_max_consecutive_errors": 3,
    }
    payload.update(overrides)
    response = client.put("/api/settings/scraper", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------
# Scraper settings
# --------------------------------------------------------------------------
def test_scraper_settings_defaults(client):
    response = client.get("/api/settings/scraper")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "fetch_batch_size": 50,
        "fetch_delay_seconds": 1.0,
        "fetch_max_consecutive_errors": 3,
    }
    # Integer settings must not come back as floats.
    assert isinstance(body["fetch_batch_size"], int)
    assert isinstance(body["fetch_max_consecutive_errors"], int)
    assert isinstance(body["fetch_delay_seconds"], float)


def test_scraper_settings_roundtrip(client):
    saved = client.put(
        "/api/settings/scraper",
        json={
            "fetch_batch_size": 12,
            "fetch_delay_seconds": 2.5,
            "fetch_max_consecutive_errors": 5,
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json() == {
        "fetch_batch_size": 12,
        "fetch_delay_seconds": 2.5,
        "fetch_max_consecutive_errors": 5,
    }

    fetched = client.get("/api/settings/scraper").json()
    assert fetched["fetch_batch_size"] == 12
    assert fetched["fetch_delay_seconds"] == 2.5


@pytest.mark.parametrize(
    "payload",
    [
        {"fetch_batch_size": 0, "fetch_delay_seconds": 1, "fetch_max_consecutive_errors": 3},
        {"fetch_batch_size": 501, "fetch_delay_seconds": 1, "fetch_max_consecutive_errors": 3},
        {"fetch_batch_size": 50, "fetch_delay_seconds": -0.5, "fetch_max_consecutive_errors": 3},
        {"fetch_batch_size": 50, "fetch_delay_seconds": 10.5, "fetch_max_consecutive_errors": 3},
        {"fetch_batch_size": 50, "fetch_delay_seconds": 1, "fetch_max_consecutive_errors": 0},
        {"fetch_batch_size": 50, "fetch_delay_seconds": 1, "fetch_max_consecutive_errors": 21},
    ],
)
def test_scraper_settings_validation(client, payload):
    assert client.put("/api/settings/scraper", json=payload).status_code == 422
    # Nothing was persisted.
    assert client.get("/api/settings/scraper").json()["fetch_batch_size"] == 50


def test_scraper_settings_stored_as_a_single_row(client):
    client.put(
        "/api/settings/scraper",
        json={
            "fetch_batch_size": 7,
            "fetch_delay_seconds": 0.5,
            "fetch_max_consecutive_errors": 2,
        },
    )
    with database.get_conn() as conn:
        rows = conn.execute("SELECT key FROM app_settings").fetchall()
    assert [row["key"] for row in rows] == ["scraper"]


# --------------------------------------------------------------------------
# Add chapters from URL
# --------------------------------------------------------------------------
def test_add_chapters_from_url(client, site):
    novel = _create_scraped_novel(client)

    response = client.post(
        f"/api/novels/{novel['id']}/chapters/from-url",
        json={"urls": [_chapter_url(10), _chapter_url(11)]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["added"] == 2
    assert body["skipped"] == 0
    assert body["failed"] == 0

    chapters = _chapters(client, novel["id"])
    # The novel already had 3 chapters from the scraper, so these are 4 and 5.
    assert [chapter["chapter_number"] for chapter in chapters] == [1.0, 2.0, 3.0, 4.0, 5.0]
    added = chapters[-2:]
    assert all(chapter["status"] == "raw" for chapter in added)
    assert "Isi bab 10." in added[0]["raw_content"]
    assert added[0]["source_url"] == _chapter_url(10)


def test_add_chapters_from_url_skips_duplicates(client, site):
    novel = _create_scraped_novel(client)
    payload = {"urls": [_chapter_url(10)]}

    first = client.post(f"/api/novels/{novel['id']}/chapters/from-url", json=payload).json()
    assert first["added"] == 1

    second = client.post(f"/api/novels/{novel['id']}/chapters/from-url", json=payload).json()
    assert second["added"] == 0
    assert second["skipped"] == 1

    # Also skips a URL that the scraper import already created.
    third = client.post(
        f"/api/novels/{novel['id']}/chapters/from-url", json={"urls": [_chapter_url(1)]}
    ).json()
    assert third["added"] == 0
    assert third["skipped"] == 1


def test_add_chapters_from_url_reports_failures(client, site):
    novel = _create_scraped_novel(client)
    site["fail"] = {_chapter_url(99)}

    body = client.post(
        f"/api/novels/{novel['id']}/chapters/from-url",
        json={"urls": [_chapter_url(99), _chapter_url(10)]},
    ).json()
    assert body["ok"] is False
    assert body["added"] == 1
    assert body["failed"] == 1
    assert "403" in body["errors"][0]["error"]


def test_add_chapters_from_url_requires_urls(client, site):
    novel = _create_scraped_novel(client)
    assert (
        client.post(f"/api/novels/{novel['id']}/chapters/from-url", json={"urls": []}).status_code
        == 422
    )


# --------------------------------------------------------------------------
# Sync URL
# --------------------------------------------------------------------------
def test_sync_url_adds_only_new_chapters(client, site):
    novel = _create_scraped_novel(client)
    chapters = _chapters(client, novel["id"])
    # Promote the first chapter so its body must survive the sync.
    with database.get_conn() as conn:
        conn.execute(
            "UPDATE chapters SET status = 'raw', raw_content = 'isi lama' WHERE id = ?",
            (chapters[0]["id"],),
        )

    site["chapters"] = 5  # the site published two more chapters
    response = client.post(f"/api/novels/{novel['id']}/chapters/sync-url", json={})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["found"] == 5
    assert body["added"] == 2
    assert body["skipped"] == 3

    after = _chapters(client, novel["id"])
    assert len(after) == 5
    assert after[0]["status"] == "raw"
    assert after[0]["raw_content"] == "isi lama"
    assert all(chapter["status"] == "pending_fetch" for chapter in after[2:])


def test_sync_url_does_not_overwrite_translated_chapter(client, site):
    novel = _create_scraped_novel(client)
    chapters = _chapters(client, novel["id"])
    with database.get_conn() as conn:
        conn.execute(
            "UPDATE chapters SET status = 'translated', translated_content = 'terjemahan', "
            "raw_content = 'raw asli' WHERE id = ?",
            (chapters[0]["id"],),
        )

    site["chapters"] = 4
    body = client.post(f"/api/novels/{novel['id']}/chapters/sync-url", json={}).json()
    assert body["added"] == 1

    after = _chapters(client, novel["id"])
    assert after[0]["status"] == "translated"
    assert after[0]["translated_content"] == "terjemahan"
    assert after[0]["raw_content"] == "raw asli"


def test_sync_url_without_source_url_returns_400(client):
    novel = client.post("/api/novels", json={"title": "Manual"}).json()
    response = client.post(f"/api/novels/{novel['id']}/chapters/sync-url", json={})
    assert response.status_code == 400
    assert "source_url" in response.json()["detail"]


def test_sync_url_accepts_explicit_source_url(client, site):
    novel = client.post("/api/novels", json={"title": "Manual"}).json()
    body = client.post(
        f"/api/novels/{novel['id']}/chapters/sync-url", json={"source_url": NOVEL_URL}
    ).json()
    assert body["added"] == 3
    assert body["scraper"] == "69shuba"


# --------------------------------------------------------------------------
# Batch fetch job
# --------------------------------------------------------------------------
def test_fetch_job_processes_batch_and_saves_each_chapter(client, site):
    novel = _create_scraped_novel(client)
    _fast_fetch_settings(client)
    assert all(chapter["status"] == "pending_fetch" for chapter in _chapters(client, novel["id"]))

    response = client.post(
        f"/api/novels/{novel['id']}/chapters/fetch-job", json={"limit": 2}
    )
    assert response.status_code == 202, response.text
    job = _wait_for_job(client, response.json()["id"])

    assert job["status"] == "completed", job
    assert job["job_type"] == "fetch"
    assert job["total_items"] == 2
    assert job["completed_items"] == 2

    chapters = _chapters(client, novel["id"])
    assert [c["status"] for c in chapters] == ["raw", "raw", "pending_fetch"]
    assert "Isi bab 1." in chapters[0]["raw_content"]


def test_fetch_job_uses_batch_size_setting(client, site):
    novel = _create_scraped_novel(client)
    site["chapters"] = 6
    client.post(f"/api/novels/{novel['id']}/chapters/sync-url", json={})
    _fast_fetch_settings(client, fetch_batch_size=4)

    response = client.post(f"/api/novels/{novel['id']}/chapters/fetch-job", json={})
    job = _wait_for_job(client, response.json()["id"])

    assert job["status"] == "completed"
    assert job["total_items"] == 4
    assert len(response.json()["chapter_ids"]) == 4


def test_fetch_job_with_explicit_chapter_ids(client, site):
    novel = _create_scraped_novel(client)
    _fast_fetch_settings(client)
    chapters = _chapters(client, novel["id"])

    response = client.post(
        f"/api/novels/{novel['id']}/chapters/fetch-job",
        json={"chapter_ids": [chapters[1]["id"]]},
    )
    job = _wait_for_job(client, response.json()["id"])

    assert job["status"] == "completed"
    assert job["total_items"] == 1
    after = _chapters(client, novel["id"])
    assert after[1]["status"] == "raw"
    assert after[0]["status"] == "pending_fetch"


def test_fetch_job_circuit_breaker_stops_after_consecutive_errors(client, site):
    novel = _create_scraped_novel(client)
    _fast_fetch_settings(client, fetch_max_consecutive_errors=2)
    site["fail"] = {_chapter_url(1), _chapter_url(2), _chapter_url(3)}

    response = client.post(f"/api/novels/{novel['id']}/chapters/fetch-job", json={"limit": 3})
    job = _wait_for_job(client, response.json()["id"])

    assert job["status"] == "failed"
    assert "error beruntun" in job["error"]
    assert "403" in job["error"] or "diblokir" in job["error"]

    chapters = _chapters(client, novel["id"])
    # Only two chapters were attempted before the breaker tripped.
    assert [c["status"] for c in chapters] == ["error", "error", "pending_fetch"]


def test_fetch_job_keeps_successes_before_the_breaker(client, site):
    novel = _create_scraped_novel(client)
    _fast_fetch_settings(client, fetch_max_consecutive_errors=2)
    site["fail"] = {_chapter_url(2), _chapter_url(3)}

    response = client.post(f"/api/novels/{novel['id']}/chapters/fetch-job", json={"limit": 3})
    job = _wait_for_job(client, response.json()["id"])

    assert job["status"] == "failed"
    chapters = _chapters(client, novel["id"])
    assert chapters[0]["status"] == "raw"
    assert "Isi bab 1." in chapters[0]["raw_content"]


def test_fetch_job_can_be_cancelled(client, site):
    novel = _create_scraped_novel(client)
    site["chapters"] = 8
    client.post(f"/api/novels/{novel['id']}/chapters/sync-url", json={})
    _fast_fetch_settings(client, fetch_delay_seconds=0.5, fetch_batch_size=8)

    response = client.post(f"/api/novels/{novel['id']}/chapters/fetch-job", json={})
    job_id = response.json()["id"]
    time.sleep(0.4)

    cancelled = client.post(f"/api/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    # Whatever finished before the cancel is still stored.
    chapters = _chapters(client, novel["id"])
    assert any(chapter["status"] == "raw" for chapter in chapters)


def test_fetch_job_without_pending_chapters(client, site):
    novel = _create_scraped_novel(client)
    _fast_fetch_settings(client)

    first = client.post(f"/api/novels/{novel['id']}/chapters/fetch-job", json={}).json()
    assert _wait_for_job(client, first["id"])["status"] == "completed"

    response = client.post(f"/api/novels/{novel['id']}/chapters/fetch-job", json={})
    assert response.status_code == 422
    assert "pending_fetch" in response.json()["detail"]


def test_fetch_job_unknown_novel_404(client):
    assert (
        client.post("/api/novels/999/chapters/fetch-job", json={"limit": 1}).status_code == 404
    )
