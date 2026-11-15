"""Synopsis translation: schema migration, creation-time auto-translate, refine."""

from __future__ import annotations

import sqlite3

import pytest

import database
from core.reference import save_reference
from llm.base import LLMError, LLMResponse, ResolvedTask

REFINE_REJECT = "Lakukan Analisa Cerita awal terlebih dahulu sebelum memperbaiki sinopsis."


class StubProvider:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.handler = None
        self.fail = False

    async def generate(
        self,
        prompt,
        system_prompt=None,
        model=None,
        temperature=0.7,
        max_tokens=4096,
    ):
        self.calls.append({"prompt": prompt, "system": system_prompt, "model": model})
        if self.fail:
            raise LLMError("provider sedang down")
        text = self.handler(prompt, system_prompt) if self.handler else "stub"
        return LLMResponse(text=text, model=model or "stub-model")

    async def test_connection(self, model=None):
        return {"ok": True, "message": "stub"}


@pytest.fixture()
def stub_llm(monkeypatch):
    provider = StubProvider()

    def _resolve(self):
        return ResolvedTask(
            task_name=self.task_name,
            provider=provider,
            provider_id=1,
            provider_type="stub",
            model="stub-model",
            temperature=0.3,
            max_tokens=4096,
        )

    monkeypatch.setattr("llm.base.TaskRouter.resolve", _resolve)
    return provider


def _default_handler(prompt: str, system: str | None) -> str:
    low = prompt.lower()
    if "novel title" in low:
        return "Judul Terjemahan"
    if "novel synopsis" in low:
        return "Sinopsis terjemahan draf pertama."
    if "rewrite the synopsis" in low:
        return "Sinopsis hasil perbaikan yang lebih rapi."
    return "stub"


@pytest.fixture()
def handler(stub_llm):
    stub_llm.handler = _default_handler
    return stub_llm


def _create_novel(client, **overrides):
    payload = {
        "title": "失温共感",
        "author": "醒野",
        "source_lang": "zh",
        "target_lang": "id",
        "synopsis": "雪村静拒绝了新的任务。",
    }
    payload.update(overrides)
    response = client.post("/api/novels", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------
# Schema migration
# --------------------------------------------------------------------------
OLD_NOVELS_SCHEMA = """
CREATE TABLE novels (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    title            TEXT    NOT NULL,
    title_translated TEXT    NOT NULL DEFAULT '',
    author           TEXT    NOT NULL DEFAULT '',
    source_lang      TEXT    NOT NULL DEFAULT 'zh',
    target_lang      TEXT    NOT NULL DEFAULT 'id',
    source_type      TEXT    NOT NULL DEFAULT 'manual',
    source_url       TEXT    NOT NULL DEFAULT '',
    scraper_name     TEXT    NOT NULL DEFAULT '',
    synopsis         TEXT    NOT NULL DEFAULT '',
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL
);
"""


def test_synopsis_translated_column_is_added_to_an_old_database(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute(OLD_NOVELS_SCHEMA)
    conn.execute(
        "INSERT INTO novels (title, created_at, updated_at) "
        "VALUES ('Novel Lama', '2026-01-01', '2026-01-01')"
    )
    conn.commit()
    conn.close()

    with sqlite3.connect(path) as check:
        before = {row[1] for row in check.execute("PRAGMA table_info(novels)")}
    assert "synopsis_translated" not in before

    database.init_db(path)

    with sqlite3.connect(path) as check:
        after = {row[1] for row in check.execute("PRAGMA table_info(novels)")}
        stored = check.execute("SELECT synopsis_translated FROM novels").fetchone()[0]
    assert "synopsis_translated" in after
    assert stored == ""

    # Idempotent on a second run.
    database.init_db(path)
    with sqlite3.connect(path) as check:
        columns = [row[1] for row in check.execute("PRAGMA table_info(novels)")]
    assert columns.count("synopsis_translated") == 1


# --------------------------------------------------------------------------
# Creation without a configured translate task
# --------------------------------------------------------------------------
def test_create_novel_without_translate_task_still_succeeds(client):
    novel = _create_novel(client)
    assert novel["title"] == "失温共感"
    assert novel["synopsis"] == "雪村静拒绝了新的任务。"
    assert novel["synopsis_translated"] == ""
    assert novel["title_translated"] == ""


def test_create_from_url_without_translate_task_still_succeeds(client, monkeypatch):
    async def _fetch_html(self, url):
        return (
            "<html><body><h1>测试小说</h1>"
            '<div class="mybox">作者：张三</div>'
            '<div class="navtxt">这是一个中文简介。</div>'
            '<div class="qustime"><ul>'
            '<li><a href="/book/1/2.htm">第1章</a></li>'
            "</ul></div></body></html>"
        )

    monkeypatch.setattr("scrapers.base.BaseScraper.fetch_html", _fetch_html)

    response = client.post(
        "/api/novels/from-url", json={"url": "https://www.69shuba.com/book/1.htm"}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["synopsis_translated"] == ""
    assert body["title_translated"] == ""


# --------------------------------------------------------------------------
# Creation with the translate task configured
# --------------------------------------------------------------------------
def test_create_novel_translates_synopsis_and_title(client, handler):
    novel = _create_novel(client)
    assert novel["synopsis_translated"] == "Sinopsis terjemahan draf pertama."
    assert novel["title_translated"] == "Judul Terjemahan"

    # Persisted, not just returned.
    fetched = client.get(f"/api/novels/{novel['id']}").json()
    assert fetched["synopsis_translated"] == "Sinopsis terjemahan draf pertama."


def test_create_novel_without_synopsis_skips_synopsis_call(client, handler):
    novel = _create_novel(client, synopsis="")
    assert novel["synopsis_translated"] == ""
    assert novel["title_translated"] == "Judul Terjemahan"
    assert not any("novel synopsis" in call["prompt"].lower() for call in handler.calls)


def test_create_novel_keeps_manual_title_translation(client, handler):
    novel = _create_novel(client, title_translated="Judul Manual")
    assert novel["title_translated"] == "Judul Manual"
    assert not any("novel title" in call["prompt"].lower() for call in handler.calls)


def test_create_novel_survives_provider_failure(client, stub_llm):
    stub_llm.handler = _default_handler
    stub_llm.fail = True
    novel = _create_novel(client)
    assert novel["id"] > 0
    assert novel["synopsis_translated"] == ""
    assert novel["title_translated"] == ""


def test_latin_title_for_cjk_source_is_not_translated(client, handler):
    novel = _create_novel(client, title="Kenari Notes")
    assert novel["title_translated"] == ""
    # The Chinese synopsis is still translated.
    assert novel["synopsis_translated"] == "Sinopsis terjemahan draf pertama."


# --------------------------------------------------------------------------
# has_story_analysis
# --------------------------------------------------------------------------
def test_has_story_analysis_flag(client):
    novel = _create_novel(client)
    assert novel["has_story_analysis"] is False

    save_reference(
        novel["id"],
        {
            "characters": [{"name": "雪村静", "romanized_name": "Xuecun Jing"}],
            "locations": [],
            "terms": [],
            "translation_guide": "",
            "chapter_context": [],
        },
    )

    detail = client.get(f"/api/novels/{novel['id']}").json()
    assert detail["has_story_analysis"] is True
    listed = client.get("/api/novels").json()[0]
    assert listed["has_story_analysis"] is True


def test_has_story_analysis_ignores_an_empty_reference(client):
    novel = _create_novel(client)
    save_reference(
        novel["id"],
        {
            "characters": [],
            "locations": [],
            "terms": [],
            "translation_guide": "   ",
            "chapter_context": [{"chapter_id": 1, "chapter_number": 1, "summary": "x"}],
        },
    )
    assert client.get(f"/api/novels/{novel['id']}").json()["has_story_analysis"] is False


# --------------------------------------------------------------------------
# Refine synopsis
# --------------------------------------------------------------------------
def _seed_reference(novel_id):
    save_reference(
        novel_id,
        {
            "characters": [
                {
                    "name": "雪村静",
                    "romanized_name": "Xuecun Jing",
                    "age": "28",
                    "gender": "female",
                    "aliases": ["教官"],
                    "relationships": "mentor",
                    "notes": "",
                }
            ],
            "locations": [{"source": "东京", "target": "Tokyo", "note": ""}],
            "terms": [{"source": "卧底", "target": "agen penyamaran", "note": "intelijen"}],
            "translation_guide": "Gunakan nada formal dan tenang.",
            "chapter_context": [],
        },
    )


def test_refine_before_analysis_is_rejected(client, handler):
    novel = _create_novel(client)
    response = client.post(f"/api/novels/{novel['id']}/synopsis/refine")
    assert response.status_code == 400
    assert response.json()["detail"] == REFINE_REJECT
    # No model call happened.
    assert not any("rewrite the synopsis" in call["prompt"].lower() for call in handler.calls)


def test_refine_without_synopsis_is_rejected(client, handler):
    novel = _create_novel(client, synopsis="")
    _seed_reference(novel["id"])

    response = client.post(f"/api/novels/{novel['id']}/synopsis/refine")
    assert response.status_code == 400
    assert "sinopsis" in response.json()["detail"].lower()


def test_refine_uses_reference_and_updates_synopsis(client, handler):
    novel = _create_novel(client)
    _seed_reference(novel["id"])
    handler.calls.clear()

    response = client.post(f"/api/novels/{novel['id']}/synopsis/refine")
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["synopsis_translated"] == "Sinopsis hasil perbaikan yang lebih rapi."
    assert body["has_story_analysis"] is True

    # The prompt carried the reference sheet and the original text.
    refine_prompts = [
        call["prompt"] for call in handler.calls if "rewrite the synopsis" in call["prompt"].lower()
    ]
    assert len(refine_prompts) == 1
    prompt = refine_prompts[0]
    assert "Gunakan nada formal dan tenang." in prompt
    assert "Xuecun Jing" in prompt
    assert "agen penyamaran" in prompt
    assert "Tokyo" in prompt
    assert "雪村静拒绝了新的任务。" in prompt
    assert "Sinopsis terjemahan draf pertama." in prompt

    # Stored in SQLite.
    with database.get_conn() as conn:
        stored = conn.execute(
            "SELECT synopsis_translated FROM novels WHERE id = ?", (novel["id"],)
        ).fetchone()[0]
    assert stored == "Sinopsis hasil perbaikan yang lebih rapi."


def test_refine_works_from_original_synopsis_only(client, handler):
    novel = _create_novel(client)
    # Wipe the draft translation so the endpoint must fall back to `synopsis`.
    client.patch(f"/api/novels/{novel['id']}", json={"synopsis_translated": ""})
    _seed_reference(novel["id"])

    response = client.post(f"/api/novels/{novel['id']}/synopsis/refine")
    assert response.status_code == 200
    assert response.json()["synopsis_translated"]


def test_refine_without_translate_task_returns_424(client):
    novel = _create_novel(client)
    _seed_reference(novel["id"])

    response = client.post(f"/api/novels/{novel['id']}/synopsis/refine")
    assert response.status_code == 424
    assert "Settings" in response.json()["detail"]


def test_refine_provider_failure_returns_502(client, stub_llm):
    novel = _create_novel(client)
    _seed_reference(novel["id"])
    stub_llm.handler = _default_handler
    stub_llm.fail = True

    response = client.post(f"/api/novels/{novel['id']}/synopsis/refine")
    assert response.status_code == 502
    assert "sinopsis" in response.json()["detail"].lower()


def test_refine_unknown_novel_404(client):
    assert client.post("/api/novels/999/synopsis/refine").status_code == 404


# --------------------------------------------------------------------------
# Manual editing
# --------------------------------------------------------------------------
def test_patch_synopsis_translated(client):
    novel = _create_novel(client)
    response = client.patch(
        f"/api/novels/{novel['id']}",
        json={"synopsis_translated": "Sinopsis editan manual."},
    )
    assert response.status_code == 200
    assert response.json()["synopsis_translated"] == "Sinopsis editan manual."
