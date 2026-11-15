"""Auto-update of the reference sheet per chapter during translation."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

import database
from core import job_runner
from core.analyzer import update_reference_from_chapter
from core.reference import load_reference, save_reference
from llm.base import LLMError, LLMResponse, ResolvedTask

NEW_CHAPTER_PROMPT_MARKER = "extract ONLY what is new"

MODEL_REPLY = {
    "characters": [
        # Existing one, returned with a different note: must NOT overwrite.
        {"name": "降谷零", "romanized_name": "Furuya Rei", "notes": "versi model"},
        {"name": "雪村静", "romanized_name": "Xuecun Jing", "aliases": ["教官"], "relationships": "mentor"},
    ],
    "locations": [{"source": "东京", "target": "Tokyo", "note": ""}],
    "terms": [{"source": "卧底", "target": "agen penyamaran", "note": ""}],
}


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
        text = self.handler(prompt, system_prompt) if self.handler else "stub output"
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


@pytest.fixture(autouse=True)
def _clean_jobs():
    job_runner.reset_jobs()
    yield
    job_runner.reset_jobs()


def _handler(prompt: str, system: str | None) -> str:
    low = prompt.lower()
    if NEW_CHAPTER_PROMPT_MARKER.lower() in low:
        return json.dumps(MODEL_REPLY, ensure_ascii=False)
    if "translate this chapter title" in low:
        return "Bab 1: Judul Terjemahan"
    if "summarise this chapter" in low:
        return "Ringkasan bab singkat."
    return "Terjemahan isi bab."


def _create_novel(client):
    response = client.post(
        "/api/novels",
        json={"title": "Auto Ref Novel", "author": "Penulis", "source_lang": "zh", "target_lang": "id"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add_chapter(client, novel_id, title, content):
    response = client.post(
        f"/api/novels/{novel_id}/chapters/manual",
        json={"title": title, "raw_content": content},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _wait_for_job(client, job_id, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} tidak selesai dalam {timeout}s")


def _seed(client, novel_id):
    save_reference(
        novel_id,
        {
            "characters": [
                {
                    "name": "降谷零",
                    "romanized_name": "Furuya Rei",
                    "age": "29",
                    "gender": "male",
                    "aliases": ["零"],
                    "relationships": "rekan kerja",
                    "notes": "detektif — editan manual user",
                }
            ],
            "locations": [],
            "terms": [],
            "translation_guide": "Gunakan nada formal.",
            "chapter_context": [],
        },
    )


def _update_prompts(provider) -> list[str]:
    return [
        call["prompt"]
        for call in provider.calls
        if NEW_CHAPTER_PROMPT_MARKER.lower() in call["prompt"].lower()
    ]


# --------------------------------------------------------------------------
# update_reference_from_chapter()
# --------------------------------------------------------------------------
def test_update_sends_existing_reference_and_only_adds_new(client, stub_llm):
    stub_llm.handler = _handler
    novel = _create_novel(client)
    _seed(client, novel["id"])
    chapter = _add_chapter(client, novel["id"], "第1章", "雪村静走进教室，看着降谷零。")

    counts = asyncio.run(update_reference_from_chapter(chapter["id"]))

    # 降谷零 already existed → only 雪村静 is new.
    assert counts["characters_added"] == 1
    assert counts["locations_added"] == 1
    assert counts["terms_added"] == 1

    prompt = _update_prompts(stub_llm)[0]
    assert "Furuya Rei" in prompt, "existing characters must be in the prompt"
    assert "detektif — editan manual user" in prompt, "existing notes must be in the prompt"
    assert "雪村静走进教室" in prompt

    reference = load_reference(novel["id"])
    names = [c["name"] for c in reference["characters"]]
    assert names == ["降谷零", "雪村静"]

    # The manual edit survived; the model's replacement note did not win.
    kept = reference["characters"][0]
    assert kept["notes"] == "detektif — editan manual user"
    assert kept["romanized_name"] == "Furuya Rei"
    assert reference["translation_guide"] == "Gunakan nada formal."
    assert reference["terms"][0]["target"] == "agen penyamaran"


def test_update_is_noop_when_nothing_new(client, stub_llm):
    stub_llm.handler = lambda prompt, system: json.dumps(
        {"characters": [], "locations": [], "terms": []}
    )
    novel = _create_novel(client)
    _seed(client, novel["id"])
    chapter = _add_chapter(client, novel["id"], "第1章", "降谷零沉默。")

    before = load_reference(novel["id"])["updated_at"]
    counts = asyncio.run(update_reference_from_chapter(chapter["id"]))

    assert counts == {"characters_added": 0, "locations_added": 0, "terms_added": 0}
    assert load_reference(novel["id"])["updated_at"] == before


def test_update_returns_zeros_when_task_not_configured(client):
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "第1章", "雪村静走进教室。")

    counts = asyncio.run(update_reference_from_chapter(chapter["id"]))
    assert counts == {"characters_added": 0, "locations_added": 0, "terms_added": 0}


def test_update_returns_zeros_on_provider_error(client, stub_llm):
    stub_llm.handler = _handler
    stub_llm.fail = True
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "第1章", "雪村静走进教室。")

    counts = asyncio.run(update_reference_from_chapter(chapter["id"]))
    assert counts == {"characters_added": 0, "locations_added": 0, "terms_added": 0}


def test_update_returns_zeros_on_invalid_json(client, stub_llm):
    stub_llm.handler = lambda prompt, system: "maaf, saya tidak bisa"
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "第1章", "雪村静走进教室。")

    counts = asyncio.run(update_reference_from_chapter(chapter["id"]))
    assert counts == {"characters_added": 0, "locations_added": 0, "terms_added": 0}


def test_update_skips_chapter_without_raw_content(client, stub_llm):
    stub_llm.handler = _handler
    novel = _create_novel(client)
    with database.get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO chapters (novel_id, chapter_number, title, raw_content, status, "
            "created_at, updated_at) VALUES (?, 1, 'Kosong', '', 'pending_fetch', ?, ?)",
            (novel["id"], database.utcnow(), database.utcnow()),
        )
        chapter_id = int(cursor.lastrowid)

    counts = asyncio.run(update_reference_from_chapter(chapter_id))
    assert counts == {"characters_added": 0, "locations_added": 0, "terms_added": 0}
    assert not _update_prompts(stub_llm)


# --------------------------------------------------------------------------
# Translation pipeline integration
# --------------------------------------------------------------------------
def test_translate_job_injects_new_character_into_same_chapter(client, stub_llm):
    stub_llm.handler = _handler
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "第1章", "雪村静走进教室，看着降谷零。")

    started = client.post(
        f"/api/novels/{novel['id']}/translate",
        json={"chapter_ids": [chapter["id"]], "auto_update_reference": True},
    )
    assert started.status_code == 202, started.text
    job = _wait_for_job(client, started.json()["id"])
    assert job["status"] == "completed", job

    # The reference was extended…
    reference = load_reference(novel["id"])
    assert [c["name"] for c in reference["characters"]] == ["降谷零", "雪村静"]
    assert reference["terms"][0]["source"] == "卧底"

    # …and chapter 1's own translation prompt already used it.
    chunk_prompts = [c["prompt"] for c in stub_llm.calls if "[SOURCE TEXT]" in c["prompt"]]
    assert chunk_prompts
    assert "Xuecun Jing" in chunk_prompts[0]
    assert "agen penyamaran" in chunk_prompts[0]

    # The chapter was translated normally.
    detail = client.get(f"/api/chapters/{chapter['id']}").json()
    assert detail["status"] == "translated"


def test_translate_job_without_auto_update_never_calls_story_analysis(client, stub_llm):
    stub_llm.handler = _handler
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "第1章", "雪村静走进教室。")

    started = client.post(
        f"/api/novels/{novel['id']}/translate",
        json={"chapter_ids": [chapter["id"]], "auto_update_reference": False},
    )
    assert started.status_code == 202, started.text
    job = _wait_for_job(client, started.json()["id"])
    assert job["status"] == "completed", job

    assert not _update_prompts(stub_llm), "story_analysis must not be called"
    assert load_reference(novel["id"])["characters"] == []
    chunk_prompts = [c["prompt"] for c in stub_llm.calls if "[SOURCE TEXT]" in c["prompt"]]
    assert chunk_prompts and "Xuecun Jing" not in chunk_prompts[0]


def test_translate_defaults_to_auto_update_enabled(client, stub_llm):
    stub_llm.handler = _handler
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "第1章", "雪村静走进教室。")

    started = client.post(
        f"/api/novels/{novel['id']}/translate", json={"chapter_ids": [chapter["id"]]}
    )
    assert started.status_code == 202, started.text
    _wait_for_job(client, started.json()["id"])
    assert _update_prompts(stub_llm)


def test_translate_job_survives_broken_auto_update(client, stub_llm):
    """A failing analyser must not stop the batch translation."""
    stub_llm.handler = _handler
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "第1章", "雪村静走进教室。")

    calls = {"n": 0}
    original = stub_llm.generate

    async def flaky(prompt, system_prompt=None, model=None, temperature=0.7, max_tokens=4096):
        if NEW_CHAPTER_PROMPT_MARKER.lower() in prompt.lower():
            calls["n"] += 1
            raise RuntimeError("analyser meledak")
        return await original(prompt, system_prompt, model, temperature, max_tokens)

    stub_llm.generate = flaky

    started = client.post(
        f"/api/novels/{novel['id']}/translate",
        json={"chapter_ids": [chapter["id"]], "auto_update_reference": True},
    )
    job = _wait_for_job(client, started.json()["id"])

    assert calls["n"] == 1
    assert job["status"] == "completed", job
    assert client.get(f"/api/chapters/{chapter['id']}").json()["status"] == "translated"


def test_translate_job_with_unconfigured_story_analysis_still_translates(client):
    """No stub at all: routing is missing for every task."""
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "第1章", "雪村静走进教室。")

    # Without a stub the translate task is missing too, so the API refuses (424).
    response = client.post(
        f"/api/novels/{novel['id']}/translate",
        json={"chapter_ids": [chapter["id"]], "auto_update_reference": True},
    )
    assert response.status_code == 424


def test_describe_added_formats_message():
    from core.job_runner import _describe_added

    assert _describe_added({"characters_added": 2, "locations_added": 0, "terms_added": 1}) == (
        "+2 karakter, +1 istilah"
    )
    assert _describe_added({"characters_added": 0, "locations_added": 0, "terms_added": 0}) == ""
