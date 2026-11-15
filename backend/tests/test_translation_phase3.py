"""Phase 3 tests: quality helpers, analyzer, translator, job runner and API."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

import database
from core import job_runner
from core.analyzer import AnalysisError, analyze_novel, summarize_chapter_for_context
from core.quality import deduplicate_raw_text, score_translation
from core.reference import load_reference, save_reference
from core.translator import TranslationError, chunk_text, translate_chapter
from llm.base import LLMResponse, ResolvedTask


# --------------------------------------------------------------------------
# Stub provider
# --------------------------------------------------------------------------
class StubProvider:
    """Records every prompt and answers with whatever the test wired up."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.handler = None
        self.delay = 0.0

    async def generate(
        self,
        prompt,
        system_prompt=None,
        model=None,
        temperature=0.7,
        max_tokens=4096,
    ):
        self.calls.append(
            {
                "prompt": prompt,
                "system": system_prompt,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if self.delay:
            await asyncio.sleep(self.delay)
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


def _create_novel(client, title="Novel Phase 3"):
    response = client.post(
        "/api/novels",
        json={"title": title, "author": "Penulis", "source_lang": "zh", "target_lang": "id"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add_chapter(client, novel_id, title, content, number=None):
    payload = {"title": title, "raw_content": content}
    if number is not None:
        payload["chapter_number"] = number
    response = client.post(f"/api/novels/{novel_id}/chapters/manual", json=payload)
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


# --------------------------------------------------------------------------
# quality.deduplicate_raw_text
# --------------------------------------------------------------------------
def test_deduplicate_removes_duplicated_half():
    first = "Pertama. Dia berjalan ke pasar.\n\nKedua. Dia membeli apel."
    text = f"{first}\n\n{first}"
    assert deduplicate_raw_text(text) == first


def test_deduplicate_removes_repeated_tail():
    paragraphs = ["Satu.", "Dua.", "Tiga.", "Empat."]
    text = "\n\n".join(paragraphs + paragraphs[:2])
    result = deduplicate_raw_text(text)
    assert result == "\n\n".join(paragraphs)


def test_deduplicate_collapses_consecutive_paragraphs():
    text = "Baris sama.\n\nBaris sama.\n\nBaris lain."
    assert deduplicate_raw_text(text) == "Baris sama.\n\nBaris lain."


def test_deduplicate_leaves_clean_text_alone():
    text = "Satu.\n\nDua.\n\nTiga."
    assert deduplicate_raw_text(text) == text


def test_deduplicate_handles_empty():
    assert deduplicate_raw_text("") == ""
    assert deduplicate_raw_text("   ") == ""


# --------------------------------------------------------------------------
# quality.score_translation
# --------------------------------------------------------------------------
def test_score_clean_translation_is_high():
    text = "Dia berjalan ke pasar dan membeli apel merah. Xuecun Jing tersenyum."
    result = score_translation(text, "zh", [{"source": "雪村静", "target": "Xuecun Jing"}])
    assert result["score"] >= 90
    assert result["grade"] == "A"
    assert result["cjk_ratio"] == 0.0
    assert result["term_compliance"] == 50.0


def test_score_penalises_cjk_leak():
    text = "他走到市场买了苹果。" * 20
    result = score_translation(text, "zh", [])
    assert result["cjk_ratio"] > 0.5
    assert result["cjk_cleanliness"] == 0.0
    assert result["grade"] == "D"


def test_score_penalises_untranslated_term():
    text = "Dia melihat 雪村静 di sana."
    result = score_translation(text, "zh", [{"source": "雪村静", "target": "Xuecun Jing"}])
    assert result["term_compliance"] == 0.0
    assert result["term_violations"] == ["雪村静"]
    assert result["score"] < 90


def test_score_without_terms_gives_full_compliance():
    result = score_translation("Teks bersih.", "zh", [])
    assert result["term_compliance"] == 50.0
    assert result["terms_checked"] == 0


# --------------------------------------------------------------------------
# chunking
# --------------------------------------------------------------------------
def test_chunk_text_splits_on_paragraphs():
    text = "\n\n".join(["A" * 100] * 10)
    chunks = chunk_text(text, max_chars=300)
    assert len(chunks) > 1
    assert all(len(chunk) <= 300 for chunk in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")


def test_chunk_text_splits_overlong_paragraph():
    text = "。".join(["句子" * 50] * 20) + "。"
    chunks = chunk_text(text, max_chars=200)
    assert len(chunks) > 1
    assert all(len(chunk) <= 200 for chunk in chunks)


def test_chunk_text_empty():
    assert chunk_text("") == []


# --------------------------------------------------------------------------
# analyzer
# --------------------------------------------------------------------------
ANALYSIS_JSON = {
    "characters": [
        {
            "name": "雪村静",
            "romanized_name": "Xuecun Jing",
            "age": "28",
            "gender": "female",
            "aliases": ["教官"],
            "relationships": "mentor",
            "notes": "AI note",
        },
        {
            "name": "降谷零",
            "romanized_name": "Furuya Rei",
            "age": "",
            "gender": "male",
            "aliases": [],
            "relationships": "",
            "notes": "undercover",
        },
    ],
    "locations": [{"source": "东京", "target": "Tokyo", "note": ""}],
    "terms": [{"source": "教官", "target": "instruktur", "note": "rank"}],
    "translation_guide": "Gunakan nada formal, pertahankan istilah militer.",
}


def test_analyzer_extracts_and_merges_without_losing_edits(client, stub_llm):
    novel = _create_novel(client)
    _add_chapter(client, novel["id"], "Bab 1", "雪村静 走进 东京 的 教室。")

    # A hand-edited entry the model must not overwrite.
    save_reference(
        novel["id"],
        {
            "characters": [
                {
                    "name": "雪村静",
                    "romanized_name": "Xuecun Jing",
                    "age": "",
                    "gender": "female",
                    "aliases": [],
                    "relationships": "",
                    "notes": "EDIT MANUAL",
                }
            ],
            "locations": [],
            "terms": [],
            "translation_guide": "Panduan tulisan tangan.",
            "chapter_context": [],
        },
    )

    stub_llm.handler = lambda prompt, system: json.dumps(ANALYSIS_JSON, ensure_ascii=False)

    result = asyncio.run(analyze_novel(novel["id"]))

    reference = result["reference"]
    names = [character["name"] for character in reference["characters"]]
    assert names == ["雪村静", "降谷零"]

    edited = reference["characters"][0]
    assert edited["notes"] == "EDIT MANUAL"  # user edit wins
    assert edited["age"] == "28"  # blank field filled by the model
    assert edited["aliases"] == ["教官"]

    assert reference["terms"][0]["target"] == "instruktur"
    assert reference["locations"][0]["target"] == "Tokyo"
    # A hand-written guide is never replaced.
    assert reference["translation_guide"] == "Panduan tulisan tangan."

    # Persisted, not just returned.
    stored = load_reference(novel["id"])
    assert len(stored["characters"]) == 2


def test_analyzer_uses_guide_when_none_exists(client, stub_llm):
    novel = _create_novel(client)
    _add_chapter(client, novel["id"], "Bab 1", "雪村静 走进 东京。")
    stub_llm.handler = lambda prompt, system: json.dumps(ANALYSIS_JSON, ensure_ascii=False)

    result = asyncio.run(analyze_novel(novel["id"]))
    assert result["reference"]["translation_guide"].startswith("Gunakan nada formal")


def test_analyzer_requires_raw_chapters(client, stub_llm):
    novel = _create_novel(client)
    with pytest.raises(AnalysisError, match="Tidak ada bab"):
        asyncio.run(analyze_novel(novel["id"]))


def test_analyzer_reports_unconfigured_task(client):
    novel = _create_novel(client)
    _add_chapter(client, novel["id"], "Bab 1", "teks")
    with pytest.raises(AnalysisError, match="Settings"):
        asyncio.run(analyze_novel(novel["id"]))


def test_analyzer_rejects_non_json(client, stub_llm):
    novel = _create_novel(client)
    _add_chapter(client, novel["id"], "Bab 1", "teks")
    stub_llm.handler = lambda prompt, system: "maaf saya tidak bisa"
    with pytest.raises(AnalysisError, match="JSON"):
        asyncio.run(analyze_novel(novel["id"]))


def test_summarize_chapter_keeps_last_five(client, stub_llm):
    novel = _create_novel(client)
    stub_llm.handler = lambda prompt, system: "Ringkasan bab yang cukup panjang untuk konteks."

    for index in range(7):
        chapter = _add_chapter(client, novel["id"], f"Bab {index + 1}", f"isi {index}")
        asyncio.run(summarize_chapter_for_context(chapter["id"]))

    reference = load_reference(novel["id"])
    assert len(reference["chapter_context"]) == 5
    numbers = [entry["chapter_number"] for entry in reference["chapter_context"]]
    assert numbers == [3.0, 4.0, 5.0, 6.0, 7.0]


# --------------------------------------------------------------------------
# translator
# --------------------------------------------------------------------------
def test_translator_injects_reference_and_scores(client, stub_llm):
    novel = _create_novel(client)
    chapter = _add_chapter(
        client,
        novel["id"],
        "第一章 开始",
        "\n\n".join(f"第{index}段 " + "雪村静 走进教室。" * 20 for index in range(6)),
    )
    save_reference(
        novel["id"],
        {
            "characters": [
                {
                    "name": "雪村静",
                    "romanized_name": "Xuecun Jing",
                    "age": "",
                    "gender": "female",
                    "aliases": [],
                    "relationships": "",
                    "notes": "",
                }
            ],
            "locations": [],
            "terms": [{"source": "教官", "target": "instruktur", "note": ""}],
            "translation_guide": "Nada formal.",
            "chapter_context": [
                {"chapter_id": 1, "chapter_number": 1, "title": "Bab 1", "summary": "Awal cerita."}
            ],
        },
    )

    def handler(prompt, system):
        if "chapter title" in prompt.lower():
            return "Bab 1: Awal"
        return "Xuecun Jing masuk ke ruang kelas. " * 10

    stub_llm.handler = handler

    result = asyncio.run(translate_chapter(chapter["id"], max_chars=300))

    assert result["chunks"] > 1
    assert result["title_translated"] == "Bab 1: Awal"
    assert result["quality"]["score"] > 0

    body_prompts = [call["prompt"] for call in stub_llm.calls if "chapter title" not in call["prompt"].lower()]
    assert body_prompts
    first = body_prompts[0]
    assert "Nada formal." in first
    assert "Xuecun Jing" in first
    assert "instruktur" in first
    assert "Awal cerita." in first

    stored = client.get(f"/api/chapters/{chapter['id']}").json()
    assert stored["status"] == "translated"
    assert stored["translated_content"].startswith("Xuecun Jing masuk")
    assert stored["title_translated"] == "Bab 1: Awal"
    assert stored["quality_score"] == result["quality"]["score"]


def test_translator_uses_rolling_context(client, stub_llm):
    novel = _create_novel(client)
    chapter = _add_chapter(
        client,
        novel["id"],
        "Bab 1",
        "\n\n".join(f"第{index}段 " + "雪村静 走进教室。" * 20 for index in range(6)),
    )

    counter = {"n": 0}

    def handler(prompt, system):
        if "chapter title" in prompt.lower():
            return "Judul"
        counter["n"] += 1
        return f"Terjemahan chunk {counter['n']} penutup unik."

    stub_llm.handler = handler
    asyncio.run(translate_chapter(chapter["id"], max_chars=300))

    body_prompts = [call["prompt"] for call in stub_llm.calls if "chapter title" not in call["prompt"].lower()]
    assert len(body_prompts) >= 2
    assert "start of chapter" in body_prompts[0]
    assert "Terjemahan chunk 1 penutup unik." in body_prompts[1]


def test_translator_requires_raw_content(client, stub_llm):
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "Bab 1", "isi")
    with database.get_conn() as conn:
        conn.execute("UPDATE chapters SET raw_content = '' WHERE id = ?", (chapter["id"],))
    with pytest.raises(TranslationError, match="raw"):
        asyncio.run(translate_chapter(chapter["id"]))


def test_translator_reports_unconfigured_task(client):
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "Bab 1", "teks")
    with pytest.raises(TranslationError, match="Settings"):
        asyncio.run(translate_chapter(chapter["id"]))


# --------------------------------------------------------------------------
# Reference endpoints
# --------------------------------------------------------------------------
def test_reference_get_returns_empty_sheet(client):
    novel = _create_novel(client)
    response = client.get(f"/api/novels/{novel['id']}/reference")
    assert response.status_code == 200
    body = response.json()
    assert body["characters"] == []
    assert body["translation_guide"] == ""


def test_reference_put_roundtrip(client):
    novel = _create_novel(client)
    payload = {
        "characters": [
            {
                "name": "雪村静",
                "romanized_name": "Xuecun Jing",
                "age": "28",
                "gender": "female",
                "aliases": ["教官"],
                "relationships": "mentor",
                "notes": "catatan",
            }
        ],
        "locations": [{"source": "东京", "target": "Tokyo", "note": ""}],
        "terms": [{"source": "教官", "target": "instruktur", "note": ""}],
        "translation_guide": "Nada formal.",
    }
    saved = client.put(f"/api/novels/{novel['id']}/reference", json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["characters"][0]["romanized_name"] == "Xuecun Jing"

    fetched = client.get(f"/api/novels/{novel['id']}/reference").json()
    assert fetched["translation_guide"] == "Nada formal."
    assert fetched["terms"][0]["target"] == "instruktur"


def test_reference_put_keeps_context_when_omitted(client):
    novel = _create_novel(client)
    save_reference(
        novel["id"],
        {
            "characters": [],
            "locations": [],
            "terms": [],
            "translation_guide": "",
            "chapter_context": [{"chapter_id": 1, "chapter_number": 1, "summary": "x"}],
        },
    )
    client.put(
        f"/api/novels/{novel['id']}/reference",
        json={"characters": [], "locations": [], "terms": [], "translation_guide": "baru"},
    )
    fetched = client.get(f"/api/novels/{novel['id']}/reference").json()
    assert len(fetched["chapter_context"]) == 1


def test_reference_unknown_novel_404(client):
    assert client.get("/api/novels/999/reference").status_code == 404


# --------------------------------------------------------------------------
# Job endpoints
# --------------------------------------------------------------------------
def test_analyze_endpoint_requires_configured_task(client):
    novel = _create_novel(client)
    _add_chapter(client, novel["id"], "Bab 1", "teks")
    response = client.post(f"/api/novels/{novel['id']}/analyze", json={})
    assert response.status_code == 424
    assert "Settings" in response.json()["detail"]


def test_translate_endpoint_requires_configured_task(client):
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "Bab 1", "teks")
    response = client.post(
        f"/api/novels/{novel['id']}/translate", json={"chapter_ids": [chapter["id"]]}
    )
    assert response.status_code == 424
    assert "Settings" in response.json()["detail"]


def test_translate_endpoint_rejects_empty_selection(client, stub_llm):
    novel = _create_novel(client)
    response = client.post(f"/api/novels/{novel['id']}/translate", json={"chapter_ids": []})
    assert response.status_code == 422


def test_translate_endpoint_rejects_chapter_without_raw(client, stub_llm):
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "Bab 1", "isi")
    with database.get_conn() as conn:
        conn.execute("UPDATE chapters SET raw_content = '' WHERE id = ?", (chapter["id"],))
    response = client.post(
        f"/api/novels/{novel['id']}/translate", json={"chapter_ids": [chapter["id"]]}
    )
    assert response.status_code == 422
    assert "raw" in response.json()["detail"]


def test_analyze_job_completes_and_updates_reference(client, stub_llm):
    novel = _create_novel(client)
    _add_chapter(client, novel["id"], "Bab 1", "雪村静 走进 东京。")
    stub_llm.handler = lambda prompt, system: (
        json.dumps(ANALYSIS_JSON, ensure_ascii=False)
        if "reference sheet" in (system or "")
        else "Ringkasan bab satu untuk konteks."
    )

    response = client.post(f"/api/novels/{novel['id']}/analyze", json={})
    assert response.status_code == 202, response.text
    job = _wait_for_job(client, response.json()["id"])

    assert job["status"] == "completed", job
    assert job["job_type"] == "story_analysis"
    assert job["completed_items"] == job["total_items"]

    reference = client.get(f"/api/novels/{novel['id']}/reference").json()
    assert len(reference["characters"]) == 2
    assert len(reference["chapter_context"]) == 1
    assert "Ringkasan" in reference["chapter_context"][0]["summary"]


def test_translate_job_completes_for_selected_chapters(client, stub_llm):
    novel = _create_novel(client)
    first = _add_chapter(client, novel["id"], "Bab 1", "雪村静 走进教室。" * 30)
    second = _add_chapter(client, novel["id"], "Bab 2", "降谷零 看着 窗外。" * 30)
    third = _add_chapter(client, novel["id"], "Bab 3", "Tidak dipilih." * 30)

    stub_llm.handler = lambda prompt, system: (
        "Judul Terjemahan" if "chapter title" in prompt.lower() else "Terjemahan bersih tanpa CJK."
    )

    response = client.post(
        f"/api/novels/{novel['id']}/translate",
        json={"chapter_ids": [first["id"], second["id"]]},
    )
    assert response.status_code == 202, response.text
    job = _wait_for_job(client, response.json()["id"])

    assert job["status"] == "completed", job
    assert job["total_items"] == 2
    assert job["completed_items"] == 2

    for chapter_id in (first["id"], second["id"]):
        stored = client.get(f"/api/chapters/{chapter_id}").json()
        assert stored["status"] == "translated"
        assert stored["translated_content"] == "Terjemahan bersih tanpa CJK."
        assert stored["quality_score"] is not None

    untouched = client.get(f"/api/chapters/{third['id']}").json()
    assert untouched["status"] == "raw"
    assert untouched["translated_content"] == ""


def test_translate_job_marks_chapter_error(client, stub_llm):
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "Bab 1", "teks" * 50)

    def handler(prompt, system):
        if "chapter title" in prompt.lower():
            return "Judul"
        raise RuntimeError("provider meledak")

    stub_llm.handler = handler

    response = client.post(
        f"/api/novels/{novel['id']}/translate", json={"chapter_ids": [chapter["id"]]}
    )
    job = _wait_for_job(client, response.json()["id"])

    assert job["status"] == "failed"
    assert "meledak" in job["error"]
    stored = client.get(f"/api/chapters/{chapter['id']}").json()
    assert stored["status"] == "error"


def test_cancel_running_job(client, stub_llm):
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "Bab 1", "teks" * 200)
    stub_llm.delay = 0.4
    stub_llm.handler = lambda prompt, system: "Terjemahan."

    response = client.post(
        f"/api/novels/{novel['id']}/translate", json={"chapter_ids": [chapter["id"]]}
    )
    job_id = response.json()["id"]

    cancelled = client.post(f"/api/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "cancelled"

    # The interrupted chapter must not stay stuck in 'translating'.
    stored = client.get(f"/api/chapters/{chapter['id']}").json()
    assert stored["status"] == "raw"


def test_job_endpoints_404(client):
    assert client.get("/api/jobs/does-not-exist").status_code == 404
    assert client.post("/api/jobs/does-not-exist/cancel").status_code == 404
    assert client.get("/api/jobs/does-not-exist/events").status_code == 404


def test_job_events_stream_reports_completion(client, stub_llm):
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "Bab 1", "teks" * 50)
    stub_llm.handler = lambda prompt, system: (
        "Judul" if "chapter title" in prompt.lower() else "Terjemahan."
    )

    response = client.post(
        f"/api/novels/{novel['id']}/translate", json={"chapter_ids": [chapter["id"]]}
    )
    job_id = response.json()["id"]
    _wait_for_job(client, job_id)

    with client.stream("GET", f"/api/jobs/{job_id}/events") as stream:
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        body = "".join(stream.iter_text())

    events = [
        json.loads(line[len("data: ") :])
        for line in body.splitlines()
        if line.startswith("data: ")
    ]
    assert events
    assert events[0]["type"] == "status"
    assert events[-1]["type"] == "done"
    assert events[-1]["status"] == "completed"


def test_novel_jobs_listing(client, stub_llm):
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "Bab 1", "teks" * 20)
    stub_llm.handler = lambda prompt, system: (
        "Judul" if "chapter title" in prompt.lower() else "Terjemahan."
    )
    client.post(f"/api/novels/{novel['id']}/translate", json={"chapter_ids": [chapter["id"]]})

    jobs = client.get(f"/api/novels/{novel['id']}/jobs").json()
    assert len(jobs) == 1
    assert jobs[0]["job_type"] == "translate"


def test_term_romanized_and_keep_romanized_prompt_and_quality():
    from core.quality import score_translation
    from core.reference import format_term_target, reference_to_prompt

    term_keep = {
        "source": "丹田",
        "romanized": "Dantian",
        "target": "Pusat Energi",
        "keep_romanized": True,
    }
    term_plain = {
        "source": "灵气",
        "romanized": "Lingqi",
        "target": "Energi Spiritual",
        "keep_romanized": False,
    }
    assert format_term_target(term_keep) == "Dantian (Pusat Energi)"
    assert format_term_target(term_plain) == "Energi Spiritual"

    prompt = reference_to_prompt(
        {
            "characters": [
                {
                    "name": "林风",
                    "romanized_name": "Lin Feng",
                    "relationships": "Kakak seperguruan Su Mei",
                }
            ],
            "terms": [term_keep, term_plain],
        }
    )
    assert "Dantian (Pusat Energi)" in prompt
    assert "relasi: Kakak seperguruan Su Mei" in prompt
    assert "灵气 (Lingqi) → Energi Spiritual" in prompt

    good = score_translation(
        "Ia memusatkan Energi Spiritual di dalam Dantian (Pusat Energi).",
        "zh",
        [term_keep, term_plain],
    )
    assert good["term_compliance"] == 50.0


def test_apply_reference_endpoint_updates_translated_chapters(client, stub_llm):
    novel = _create_novel(client)
    ch = _add_chapter(client, novel["id"], "Bab 1", "丹田里的灵气")

    # Rejects when no translated chapters exist yet.
    empty_resp = client.post(f"/api/novels/{novel['id']}/reference/apply")
    assert empty_resp.status_code == 422

    # Populate translation & updated reference.
    client.patch(
        f"/api/chapters/{ch['id']}",
        json={"translated_content": "Energi di dalam Pusat Energi.", "status": "translated"},
    )
    client.put(
        f"/api/novels/{novel['id']}/reference",
        json={
            "terms": [
                {
                    "source": "丹田",
                    "romanized": "Dantian",
                    "target": "Pusat Energi",
                    "keep_romanized": True,
                }
            ]
        },
    )

    stub_llm.handler = lambda prompt, system: "Energi di dalam Dantian (Pusat Energi)."
    resp = client.post(f"/api/novels/{novel['id']}/reference/apply")
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["job_type"] == "apply_reference"

    # Wait briefly for background job completion via polling.
    for _ in range(30):
        state = client.get(f"/api/jobs/{job['id']}").json()
        if state["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)

    assert state["status"] == "completed"
    updated = client.get(f"/api/chapters/{ch['id']}").json()
    assert "Dantian (Pusat Energi)" in updated["translated_content"]


def test_translate_falls_back_to_secondary_model_on_refusal(client, stub_llm, monkeypatch):
    from llm.base import ResolvedTask, TaskRouter

    # Verify settings API persists fallback fields cleanly.
    tasks = {t["task_name"]: t for t in client.get("/api/settings/tasks").json()}
    translate_task = tasks["translate"]
    resp = client.put(
        "/api/settings/tasks/translate",
        json={
            "provider_id": translate_task["provider_id"],
            "model_name": "primary-censored",
            "fallback_provider_id": translate_task["provider_id"],
            "fallback_model_name": "secondary-uncensored",
            "temperature": translate_task["temperature"],
            "max_tokens": translate_task["max_tokens"],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["fallback_model_name"] == "secondary-uncensored"

    monkeypatch.setattr(
        TaskRouter,
        "resolve_fallback",
        lambda self: ResolvedTask(
            task_name=self.task_name,
            provider=stub_llm,
            provider_id=1,
            provider_type="stub",
            model="secondary-uncensored",
            temperature=0.3,
            max_tokens=4096,
        ),
    )

    novel = _create_novel(client)
    ch = _add_chapter(client, novel["id"], "Bab 1", "Adegan pertarungan intens.")

    calls = []

    def handler(prompt, system):
        calls.append(prompt)
        if "chapter title" in prompt.lower():
            return "Bab 1"
        if len(calls) == 2:
            return "I'm sorry, I cannot translate this content."
        return "Terjemahan berhasil oleh model cadangan."

    stub_llm.handler = handler
    result = asyncio.run(translate_chapter(ch["id"]))
    assert "Terjemahan berhasil oleh model cadangan." in (
        client.get(f"/api/chapters/{ch['id']}").json()["translated_content"]
    )
    assert result["chunks"] == 1


def test_analyze_falls_back_to_secondary_model_on_refusal(client, stub_llm, monkeypatch):
    from llm.base import ResolvedTask, TaskRouter

    monkeypatch.setattr(
        TaskRouter,
        "resolve_fallback",
        lambda self: ResolvedTask(
            task_name=self.task_name,
            provider=stub_llm,
            provider_id=1,
            provider_type="stub",
            model="secondary-uncensored",
            temperature=0.3,
            max_tokens=4096,
        ),
    )

    novel = _create_novel(client)
    _add_chapter(client, novel["id"], "Bab 1", "林风来到青云宗。")

    calls = []

    def handler(prompt, system):
        calls.append(prompt)
        if len(calls) == 1:
            return "I'm sorry, I cannot assist with that request."
        return json.dumps(
            {
                "characters": [{"name": "林风", "romanized_name": "Lin Feng"}],
                "locations": [],
                "terms": [],
                "translation_guide": "Formal tone.",
            }
        )

    stub_llm.handler = handler
    result = asyncio.run(analyze_novel(novel["id"]))
    assert result["counts"]["characters"] == 1


def test_cover_prompt_returns_text_negative_and_json_prompt(client, stub_llm):
    novel = _create_novel(client)
    stub_llm.handler = lambda prompt, system: json.dumps(
        {
            "positive_prompt": "A young cultivator in flowing azure robes on a misty cliff",
            "negative_prompt": "text, watermark, blurry, bad anatomy",
            "json_prompt": {
                "title_concept": "Azure Peak",
                "art_style": "xianxia fantasy",
                "aspect_ratio": "2:3",
                "subject": "Lin Feng",
                "negative_prompt": "text, watermark, blurry",
            },
        }
    )

    resp = client.post(
        f"/api/novels/{novel['id']}/cover-prompt",
        json={"style": "xianxia_ink", "mood": "epic", "extra_notes": "jade sword"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "azure robes" in body["positive_prompt"]
    assert "watermark" in body["negative_prompt"]
    assert body["json_prompt"]["aspect_ratio"] == "2:3"
    assert body["json_prompt"]["subject"] == "Lin Feng"
