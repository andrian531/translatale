"""Generate detailed cover image prompts (Text+Negative & structured JSON)."""

from __future__ import annotations

import json
import re
from typing import Any

import database
from core.analyzer import _generate_analysis_with_fallback
from core.reference import load_reference
from llm.base import LLMError, TaskNotConfiguredError, TaskRouter

TASK_NAME = "cover_prompt"
FALLBACK_TASK_NAME = "story_analysis"

COVER_STYLE_PRESETS = {
    "webnovel_cover": "polished commercial webnovel cover illustration, dramatic painterly anime-fantasy rendering, intricate costume & environment details",
    "anime_illustration": "high-budget modern anime key visual, crisp cel-shaded lighting, vibrant atmospheric effects, cinematic depth of field",
    "xianxia_ink": "Chinese xianxia & wuxia fantasy art blending luminous digital painting with traditional ink-wash mist, flowing silk robes, ethereal qi aura",
    "dark_fantasy": "dark fantasy oil & digital painting, dramatic chiaroscuro lighting, rich textures, ominous epic atmosphere",
    "semi_realistic": "semi-realistic fantasy concept art, detailed facial features, volumetric rim lighting, painterly brushwork",
}

COVER_SYSTEM_PROMPT = (
    "You are an expert art director and prompt engineer for book and webnovel covers. "
    "You read novel metadata, synopsis, and character/location references and output a "
    "highly detailed visual illustration specification in English. "
    "Answer with valid JSON only — no prose, no markdown fences."
)

COVER_PROMPT_TEMPLATE = """Design a highly detailed vertical book cover illustration (2:3 aspect ratio) for the novel below.
Do NOT include any book title, text, typography, watermarks, or logos inside the image itself.

Return JSON with exactly these keys:
{{
  "positive_prompt": "One rich, highly detailed English prompt (80-160 words) describing main character(s) appearance, facial expression, hair, eyes, outfit/armor/accessories, dynamic pose, foreground props, background environment, lighting, color palette, camera angle/framing, art style, and quality tags.",
  "negative_prompt": "Comma-separated negative keywords: text, title, watermark, signature, logo, speech bubble, blurry, lowres, worst quality, bad anatomy, extra fingers, deformed hands, fused limbs, cropped head, jpeg artifacts",
  "json_prompt": {{
    "title_concept": "short visual concept name",
    "art_style": "specific rendering style",
    "aspect_ratio": "2:3",
    "subject": "who is the focal point",
    "appearance": "hair, eyes, age, build, distinguishing features",
    "outfit": "detailed clothing, fabric, armor, accessories",
    "pose_and_expression": "body posture, hand action, gaze, emotion",
    "setting_and_background": "foreground, midground, distant background architecture/nature",
    "lighting_and_atmosphere": "key light, rim light, particles, weather, mood",
    "color_palette": ["dominant color 1", "accent color 2", "shadow tone 3"],
    "composition_and_camera": "shot type, lens angle, depth of field, focal hierarchy",
    "quality_tags": ["masterpiece", "ultra-detailed", "book cover composition", "no text"],
    "negative_prompt": "same negative keywords string"
  }}
}}

Requested Art Style: {style_desc}
Requested Mood: {mood}
Extra User Notes: {extra_notes}

[NOVEL]
Title: {title}
Author: {author}
Synopsis: {synopsis}

[KEY CHARACTERS]
{characters}

[KEY LOCATIONS / WORLD]
{locations}
"""


class CoverPromptError(RuntimeError):
    """Raised when cover prompt generation fails."""


def _summarize_characters(reference: dict[str, Any]) -> str:
    chars = reference.get("characters") or []
    if not chars:
        return "(none extracted yet — infer protagonist visually from synopsis)"
    lines = []
    for char in chars[:6]:
        name = char.get("romanized_name") or char.get("name") or "Unknown"
        bits = [str(char.get(k)) for k in ("gender", "age", "relationships", "notes") if char.get(k)]
        lines.append(f"- {name}" + (f" ({'; '.join(bits)})" if bits else ""))
    return "\n".join(lines)


def _summarize_locations(reference: dict[str, Any]) -> str:
    locs = reference.get("locations") or []
    if not locs:
        return "(none extracted yet)"
    return "\n".join(
        f"- {loc.get('target') or loc.get('romanized') or loc.get('source')}"
        + (f" ({loc.get('note')})" if loc.get("note") else "")
        for loc in locs[:6]
    )


async def generate_cover_prompt(
    novel_id: int,
    *,
    style: str = "webnovel_cover",
    mood: str = "",
    extra_notes: str = "",
    db_path: str | None = None,
) -> dict[str, Any]:
    """Generate both Text+Negative and structured JSON cover prompts."""
    with database.get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM novels WHERE id = ?", (novel_id,)).fetchone()
    if row is None:
        raise CoverPromptError(f"Novel {novel_id} tidak ditemukan")
    novel = dict(row)

    router = TaskRouter(TASK_NAME, db_path=db_path)
    try:
        resolved = router.resolve()
        fallback = router.resolve_fallback()
    except TaskNotConfiguredError:
        fb_router = TaskRouter(FALLBACK_TASK_NAME, db_path=db_path)
        try:
            resolved = fb_router.resolve()
            fallback = fb_router.resolve_fallback()
        except TaskNotConfiguredError as exc:
            raise CoverPromptError(
                "Task 'cover_prompt' (atau 'story_analysis') belum dikonfigurasi. "
                "Buka Settings → Model Routing per Proses atau set Default Provider & Model. "
                f"({exc})"
            ) from exc

    reference = load_reference(novel_id, db_path)
    title = (novel.get("title_translated") or novel.get("title") or "").strip()
    synopsis = (novel.get("synopsis_translated") or novel.get("synopsis") or "").strip()
    style_desc = COVER_STYLE_PRESETS.get(style, style or COVER_STYLE_PRESETS["webnovel_cover"])

    prompt = COVER_PROMPT_TEMPLATE.format(
        style_desc=style_desc,
        mood=mood.strip() or "epic, cinematic, evocative",
        extra_notes=extra_notes.strip() or "(none)",
        title=title or "(untitled)",
        author=(novel.get("author") or "Unknown").strip(),
        synopsis=(synopsis[:2000] if synopsis else "(no synopsis yet)"),
        characters=_summarize_characters(reference),
        locations=_summarize_locations(reference),
    )

    try:
        raw_text, parsed, used = await _generate_analysis_with_fallback(
            resolved,
            fallback,
            prompt=prompt,
            system_prompt=COVER_SYSTEM_PROMPT,
            temperature=min(max(resolved.temperature, 0.5), 0.9),
            max_tokens=max(resolved.max_tokens, 1600),
            expect_json=True,
        )
    except LLMError as exc:
        raise CoverPromptError(f"Gagal membuat cover prompt: {exc}") from exc

    if parsed is None:
        preview = re.sub(r"\s+", " ", raw_text.strip())[:160]
        raise CoverPromptError(
            f"Model ({used.model}) tidak mengembalikan JSON yang valid untuk cover prompt: {preview}"
        )

    positive = str(parsed.get("positive_prompt") or "").strip()
    negative = str(parsed.get("negative_prompt") or "").strip()
    json_prompt = parsed.get("json_prompt")
    if not isinstance(json_prompt, dict):
        json_prompt = {
            "art_style": style_desc,
            "aspect_ratio": "2:3",
            "prompt": positive,
            "negative_prompt": negative,
        }

    if not positive:
        # Synthesize a fallback positive prompt from json_prompt fields if needed.
        positive = ", ".join(
            str(v)
            for k, v in json_prompt.items()
            if k != "negative_prompt" and v and not isinstance(v, (dict, list))
        )

    return {
        "positive_prompt": positive,
        "negative_prompt": negative,
        "json_prompt": json_prompt,
        "provider_type": used.provider_type,
        "model": used.model,
    }
