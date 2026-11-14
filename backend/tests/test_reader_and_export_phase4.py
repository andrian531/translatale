"""Phase 4 tests: reading progress, last-read tracking and novel export."""

from __future__ import annotations

import json

import database


def _create_novel(client, title="Novel Reader"):
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


def _mark_translated(chapter_id, text, title_translated="Judul Terjemahan", score=95.0):
    with database.get_conn() as conn:
        conn.execute(
            "UPDATE chapters SET status = 'translated', translated_content = ?, "
            "title_translated = ?, quality_score = ? WHERE id = ?",
            (text, title_translated, score, chapter_id),
        )


# --------------------------------------------------------------------------
# Reading progress
# --------------------------------------------------------------------------
def test_progress_defaults_when_never_read(client):
    novel = _create_novel(client)
    response = client.get(f"/api/novels/{novel['id']}/progress")
    assert response.status_code == 200
    body = response.json()
    assert body["chapter_id"] is None
    assert body["scroll_percent"] == 0.0


def test_progress_roundtrip(client):
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "Bab 1", "isi")

    saved = client.put(
        f"/api/novels/{novel['id']}/progress",
        json={"chapter_id": chapter["id"], "scroll_percent": 42.5},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["chapter_id"] == chapter["id"]
    assert saved.json()["scroll_percent"] == 42.5

    fetched = client.get(f"/api/novels/{novel['id']}/progress").json()
    assert fetched["chapter_id"] == chapter["id"]
    assert fetched["scroll_percent"] == 42.5
    assert fetched["updated_at"]


def test_progress_update_overwrites(client):
    novel = _create_novel(client)
    first = _add_chapter(client, novel["id"], "Bab 1", "isi")
    second = _add_chapter(client, novel["id"], "Bab 2", "isi")

    client.put(
        f"/api/novels/{novel['id']}/progress",
        json={"chapter_id": first["id"], "scroll_percent": 10},
    )
    client.put(
        f"/api/novels/{novel['id']}/progress",
        json={"chapter_id": second["id"], "scroll_percent": 80},
    )

    fetched = client.get(f"/api/novels/{novel['id']}/progress").json()
    assert fetched["chapter_id"] == second["id"]
    assert fetched["scroll_percent"] == 80.0


def test_progress_rejects_foreign_chapter(client):
    novel = _create_novel(client)
    other = _create_novel(client, title="Novel Lain")
    foreign = _add_chapter(client, other["id"], "Bab 1", "isi")

    response = client.put(
        f"/api/novels/{novel['id']}/progress",
        json={"chapter_id": foreign["id"], "scroll_percent": 5},
    )
    assert response.status_code == 404


def test_progress_rejects_out_of_range_percent(client):
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "Bab 1", "isi")
    response = client.put(
        f"/api/novels/{novel['id']}/progress",
        json={"chapter_id": chapter["id"], "scroll_percent": 150},
    )
    assert response.status_code == 422


def test_progress_unknown_novel_404(client):
    assert client.get("/api/novels/999/progress").status_code == 404
    assert (
        client.put("/api/novels/999/progress", json={"scroll_percent": 1}).status_code == 404
    )


def test_last_read_chapter_id_in_novel_responses(client):
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "Bab 1", "isi")

    listed = client.get("/api/novels").json()[0]
    assert listed["last_read_chapter_id"] is None

    client.put(
        f"/api/novels/{novel['id']}/progress",
        json={"chapter_id": chapter["id"], "scroll_percent": 33},
    )

    listed = client.get("/api/novels").json()[0]
    assert listed["last_read_chapter_id"] == chapter["id"]

    detail = client.get(f"/api/novels/{novel['id']}").json()
    assert detail["last_read_chapter_id"] == chapter["id"]


def test_deleting_chapter_clears_progress_pointer(client):
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "Bab 1", "isi")
    client.put(
        f"/api/novels/{novel['id']}/progress",
        json={"chapter_id": chapter["id"], "scroll_percent": 50},
    )

    client.delete(f"/api/chapters/{chapter['id']}")

    progress = client.get(f"/api/novels/{novel['id']}/progress").json()
    assert progress["chapter_id"] is None


def test_deleting_novel_removes_progress(client):
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "Bab 1", "isi")
    client.put(
        f"/api/novels/{novel['id']}/progress",
        json={"chapter_id": chapter["id"], "scroll_percent": 50},
    )

    client.delete(f"/api/novels/{novel['id']}")

    with database.get_conn() as conn:
        remaining = conn.execute("SELECT COUNT(*) AS n FROM reading_progress").fetchone()["n"]
    assert remaining == 0


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------
def test_export_txt_requires_translated_chapter(client):
    novel = _create_novel(client)
    _add_chapter(client, novel["id"], "Bab 1", "isi mentah")

    response = client.get(f"/api/novels/{novel['id']}/export?format=txt")
    assert response.status_code == 400
    assert "translated" in response.json()["detail"]


def test_export_txt_contains_only_translated_chapters(client):
    novel = _create_novel(client, title="Judul Uji Ekspor")
    first = _add_chapter(client, novel["id"], "Bab 1", "raw satu", number=1)
    second = _add_chapter(client, novel["id"], "Bab 2", "raw dua", number=2)
    third = _add_chapter(client, novel["id"], "Bab 3", "raw tiga", number=3)

    _mark_translated(first["id"], "Terjemahan bab satu.", "Bab Satu")
    _mark_translated(third["id"], "Terjemahan bab tiga.", "Bab Tiga")

    response = client.get(f"/api/novels/{novel['id']}/export?format=txt")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "attachment" in response.headers["content-disposition"]
    assert ".txt" in response.headers["content-disposition"]

    body = response.text
    assert "Judul Uji Ekspor" in body
    assert "Terjemahan bab satu." in body
    assert "Terjemahan bab tiga." in body
    assert "Terjemahan bab dua" not in body
    assert "raw dua" not in body
    # Ordered by chapter_number.
    assert body.index("Terjemahan bab satu.") < body.index("Terjemahan bab tiga.")


def test_export_txt_defaults_to_txt(client):
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "Bab 1", "raw")
    _mark_translated(chapter["id"], "Isi terjemahan.")
    response = client.get(f"/api/novels/{novel['id']}/export")
    assert response.status_code == 200
    assert "Isi terjemahan." in response.text


def test_export_json_is_full_backup(client):
    novel = _create_novel(client, title="Backup Uji")
    chapter = _add_chapter(client, novel["id"], "Bab 1", "raw satu")
    _mark_translated(chapter["id"], "Terjemahan.")

    client.put(
        f"/api/novels/{novel['id']}/reference",
        json={
            "characters": [{"name": "雪村静", "romanized_name": "Xuecun Jing"}],
            "locations": [],
            "terms": [{"source": "教官", "target": "instruktur"}],
            "translation_guide": "Nada formal.",
        },
    )

    response = client.get(f"/api/novels/{novel['id']}/export?format=json")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "attachment" in response.headers["content-disposition"]
    assert ".json" in response.headers["content-disposition"]

    payload = json.loads(response.text)
    assert payload["novel"]["title"] == "Backup Uji"
    assert payload["reference"]["translation_guide"] == "Nada formal."
    assert payload["reference"]["terms"][0]["target"] == "instruktur"
    assert len(payload["chapters"]) == 1
    assert payload["chapters"][0]["translated_content"] == "Terjemahan."
    assert payload["exported_at"]


def test_export_json_works_without_translations(client):
    novel = _create_novel(client)
    _add_chapter(client, novel["id"], "Bab 1", "raw")
    response = client.get(f"/api/novels/{novel['id']}/export?format=json")
    assert response.status_code == 200
    assert len(json.loads(response.text)["chapters"]) == 1


def test_export_unknown_novel_404(client):
    assert client.get("/api/novels/999/export?format=txt").status_code == 404


def test_export_invalid_format_rejected(client):
    novel = _create_novel(client)
    assert client.get(f"/api/novels/{novel['id']}/export?format=pdf").status_code == 422


def test_export_filename_is_sanitised(client):
    novel = _create_novel(client, title='Judul: "aneh"/<x>')
    chapter = _add_chapter(client, novel["id"], "Bab 1", "raw")
    _mark_translated(chapter["id"], "Isi.")

    response = client.get(f"/api/novels/{novel['id']}/export?format=txt")
    disposition = response.headers["content-disposition"]
    assert "/" not in disposition.split("filename=")[1].split(";")[0]
    assert "<" not in disposition


def test_export_ascii_fallback_for_cjk_title(client):
    novel = _create_novel(client, title="失温共感")
    chapter = _add_chapter(client, novel["id"], "Bab 1", "raw")
    _mark_translated(chapter["id"], "Isi.")

    response = client.get(f"/api/novels/{novel['id']}/export?format=txt")
    disposition = response.headers["content-disposition"]
    plain = disposition.split('filename="')[1].split('"')[0]
    # The ASCII fallback must still be a usable file name, not "[] _ +.txt".
    assert plain == f"novel-{novel['id']}.txt"
    assert "filename*=UTF-8''" in disposition


def test_export_txt_does_not_double_chapter_prefix(client):
    novel = _create_novel(client)
    chapter = _add_chapter(client, novel["id"], "第1页", "raw", number=1)
    _mark_translated(chapter["id"], "Isi terjemahan.", "Bab 1: Awal")

    body = client.get(f"/api/novels/{novel['id']}/export?format=txt").text
    assert "Bab 1: Bab 1: Awal" not in body
    assert "Bab 1: Awal" in body
