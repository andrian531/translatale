"""Read/write helpers for the per-novel reference sheet.

Kept separate from the analyzer so the router, the translator and the job runner
all share one definition of "what a reference looks like" and one merge rule.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import database

LIST_FIELDS = ("characters", "locations", "terms", "chapter_context")
TEXT_FIELDS = ("translation_guide",)

#: Field used to decide whether two entries are "the same thing".
KEY_FIELDS = {
    "characters": "name",
    "locations": "source",
    "terms": "source",
}

MAX_CONTEXT_ENTRIES = 5


def empty_reference(novel_id: int | None = None) -> dict[str, Any]:
    return {
        "novel_id": novel_id,
        "characters": [],
        "locations": [],
        "terms": [],
        "translation_guide": "",
        "chapter_context": [],
        "updated_at": "",
    }


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def load_reference(novel_id: int, db_path: str | None = None) -> dict[str, Any]:
    """Return the stored reference, or an empty one when nothing is saved yet."""
    with database.get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM novel_references WHERE novel_id = ?", (novel_id,)
        ).fetchone()

    if row is None:
        return empty_reference(novel_id)

    return {
        "novel_id": novel_id,
        "characters": _loads(row["characters_json"], []),
        "locations": _loads(row["locations_json"], []),
        "terms": _loads(row["terms_json"], []),
        "translation_guide": row["translation_guide"] or "",
        "chapter_context": _loads(row["chapter_context_json"], []),
        "updated_at": row["updated_at"],
    }


def save_reference(
    novel_id: int, data: dict[str, Any], db_path: str | None = None
) -> dict[str, Any]:
    """Upsert the reference. Unknown keys are ignored."""
    now = database.utcnow()
    characters = data.get("characters") or []
    locations = data.get("locations") or []
    terms = data.get("terms") or []
    guide = data.get("translation_guide") or ""
    context = (data.get("chapter_context") or [])[-MAX_CONTEXT_ENTRIES:]

    with database.get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO novel_references
                (novel_id, characters_json, locations_json, terms_json,
                 translation_guide, chapter_context_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(novel_id) DO UPDATE SET
                characters_json = excluded.characters_json,
                locations_json = excluded.locations_json,
                terms_json = excluded.terms_json,
                translation_guide = excluded.translation_guide,
                chapter_context_json = excluded.chapter_context_json,
                updated_at = excluded.updated_at
            """,
            (
                novel_id,
                json.dumps(characters, ensure_ascii=False),
                json.dumps(locations, ensure_ascii=False),
                json.dumps(terms, ensure_ascii=False),
                guide,
                json.dumps(context, ensure_ascii=False),
                now,
            ),
        )
    return load_reference(novel_id, db_path)


def _key(field: str, entry: dict[str, Any]) -> str:
    key_field = KEY_FIELDS.get(field, "source")
    return str(entry.get(key_field) or "").strip().casefold()


def merge_entries(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]], field: str
) -> list[dict[str, Any]]:
    """Merge LLM output into user-edited entries without losing either side.

    Existing values win when they are non-empty (the user may have corrected
    them); the LLM only fills blanks and appends genuinely new entries.
    """
    merged: list[dict[str, Any]] = [dict(entry) for entry in existing]
    index = {_key(field, entry): position for position, entry in enumerate(merged)}

    for entry in incoming:
        if not isinstance(entry, dict):
            continue
        key = _key(field, entry)
        if not key:
            continue
        if key not in index:
            index[key] = len(merged)
            merged.append(dict(entry))
            continue

        target = merged[index[key]]
        for name, value in entry.items():
            if value in (None, "", [], {}):
                continue
            if target.get(name) in (None, "", [], {}):
                target[name] = value
    return merged


def merge_reference(
    existing: dict[str, Any], incoming: dict[str, Any]
) -> dict[str, Any]:
    """Merge a freshly extracted reference into the stored one."""
    merged = dict(existing)
    for field in ("characters", "locations", "terms"):
        merged[field] = merge_entries(
            existing.get(field) or [], incoming.get(field) or [], field
        )

    # A hand-written guide is never overwritten by the model.
    if not (existing.get("translation_guide") or "").strip():
        merged["translation_guide"] = (incoming.get("translation_guide") or "").strip()

    merged["chapter_context"] = existing.get("chapter_context") or []
    return merged


def append_chapter_context(
    novel_id: int, entry: dict[str, Any], db_path: str | None = None
) -> dict[str, Any]:
    """Append a chapter summary, keeping only the last ``MAX_CONTEXT_ENTRIES``."""
    reference = load_reference(novel_id, db_path)
    context = [
        item
        for item in reference.get("chapter_context") or []
        if item.get("chapter_id") != entry.get("chapter_id")
    ]
    context.append(entry)
    reference["chapter_context"] = context[-MAX_CONTEXT_ENTRIES:]
    return save_reference(novel_id, reference, db_path)


def reference_to_prompt(reference: dict[str, Any], max_characters: int = 40) -> str:
    """Render the reference as the prompt block the translator injects."""
    parts: list[str] = []

    guide = (reference.get("translation_guide") or "").strip()
    if guide:
        parts.append(f"[TRANSLATION GUIDE]\n{guide}")

    characters = reference.get("characters") or []
    if characters:
        lines = []
        for character in characters[:max_characters]:
            name = character.get("name") or ""
            romanized = character.get("romanized_name") or ""
            extras = [
                str(character.get(field))
                for field in ("gender", "age", "notes")
                if character.get(field)
            ]
            aliases = character.get("aliases") or []
            if aliases:
                extras.append("alias: " + ", ".join(str(alias) for alias in aliases))
            label = f"{name} → {romanized}" if romanized else name
            lines.append(f"- {label}" + (f" ({'; '.join(extras)})" if extras else ""))
        parts.append("[CHARACTERS — keep these spellings]\n" + "\n".join(lines))

    terms = reference.get("terms") or []
    if terms:
        lines = [
            f"- {term.get('source')} → {term.get('target')}"
            + (f" ({term.get('note')})" if term.get("note") else "")
            for term in terms[:80]
            if term.get("source") and term.get("target")
        ]
        if lines:
            parts.append("[GLOSSARY — mandatory]\n" + "\n".join(lines))

    locations = reference.get("locations") or []
    if locations:
        lines = [
            f"- {item.get('source')} → {item.get('target')}"
            for item in locations[:40]
            if item.get("source") and item.get("target")
        ]
        if lines:
            parts.append("[PLACES]\n" + "\n".join(lines))

    context = reference.get("chapter_context") or []
    if context:
        lines = [
            f"- Ch.{item.get('chapter_number', '?')}: {item.get('summary', '')}"
            for item in context[-MAX_CONTEXT_ENTRIES:]
            if item.get("summary")
        ]
        if lines:
            parts.append("[STORY SO FAR]\n" + "\n".join(lines))

    return "\n\n".join(parts)


def has_story_analysis(novel_id: int, db_path: str | None = None) -> bool:
    """True once the reference sheet holds anything the analyst produced."""
    with database.get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT characters_json, locations_json, terms_json, translation_guide "
            "FROM novel_references WHERE novel_id = ?",
            (novel_id,),
        ).fetchone()
    if row is None:
        return False
    for field in ("characters_json", "locations_json", "terms_json"):
        if _loads(row[field], []):
            return True
    return bool((row["translation_guide"] or "").strip())


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None
