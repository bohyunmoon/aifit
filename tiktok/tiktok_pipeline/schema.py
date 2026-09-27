"""JSON schemas for the brief and storyboard. Used both for Claude structured
outputs (headless mode) and for validating files authored in chat."""
from __future__ import annotations

HOOK_TYPES = ["curiosity", "contrarian", "result", "mistake", "question", "story", "list", "pov"]
SHOT_TYPES = ["image", "video"]
MOTIONS = ["zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "static"]

BRIEF_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "hooks", "chosen_hook", "script", "caption", "hashtags", "cta", "cover_text", "notes"],
    "properties": {
        "title": {"type": "string"},
        "hooks": {
            "type": "array",
            "minItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "type", "why"],
                "properties": {
                    "text": {"type": "string", "description": "Spoken + on-screen hook, <= 12 words"},
                    "type": {"type": "string", "enum": HOOK_TYPES},
                    "why": {"type": "string"},
                },
            },
        },
        "chosen_hook": {"type": "integer", "description": "index into hooks"},
        "script": {
            "type": "array",
            "minItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "voiceover", "on_screen_text", "visual_idea", "beat"],
                "properties": {
                    "id": {"type": "string", "description": "s01, s02, ..."},
                    "beat": {"type": "string", "enum": ["hook", "setup", "point", "proof", "payoff", "cta"]},
                    "voiceover": {"type": "string", "description": "exact words spoken, 1-2 short sentences"},
                    "on_screen_text": {"type": "string", "description": "<= 6 words, may be empty"},
                    "visual_idea": {"type": "string", "description": "what we see, plain language"},
                },
            },
        },
        "caption": {"type": "string", "description": "TikTok caption, <= 150 chars, no hashtags"},
        "hashtags": {"type": "array", "minItems": 4, "maxItems": 8, "items": {"type": "string"}},
        "cta": {"type": "string"},
        "cover_text": {"type": "string", "description": "<= 5 words for the cover frame"},
        "notes": {"type": "string"},
    },
}

STORYBOARD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["style", "scenes", "music"],
    "properties": {
        "style": {"type": "string", "description": "shared style suffix appended to every image prompt"},
        "music": {"type": "string", "description": "file name in tiktok/music or empty"},
        "scenes": {
            "type": "array",
            "minItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "type", "duration", "image_prompt", "motion", "video_prompt", "upscale"],
                "properties": {
                    "id": {"type": "string", "description": "matches the script scene id"},
                    "type": {"type": "string", "enum": SHOT_TYPES},
                    "duration": {"type": "number", "description": "seconds; overridden by voiceover length"},
                    "image_prompt": {"type": "string", "description": "full Magnific image prompt, 9:16"},
                    "motion": {"type": "string", "enum": MOTIONS},
                    "video_prompt": {"type": "string", "description": "motion prompt for image-to-video, empty if type=image"},
                    "upscale": {"type": "boolean"},
                },
            },
        },
    },
}


def _check(cond: bool, errors: list, msg: str) -> None:
    if not cond:
        errors.append(msg)


def validate_brief(b: dict) -> list[str]:
    e: list[str] = []
    for k in BRIEF_SCHEMA["required"]:
        _check(k in b, e, f"brief missing '{k}'")
    if e:
        return e
    _check(len(b["hooks"]) >= 3, e, "need at least 3 hooks")
    _check(0 <= b["chosen_hook"] < len(b["hooks"]), e, "chosen_hook out of range")
    ids = [s.get("id") for s in b["script"]]
    _check(len(ids) == len(set(ids)), e, "duplicate scene ids in script")
    for s in b["script"]:
        for k in ("id", "voiceover", "on_screen_text", "visual_idea", "beat"):
            _check(k in s, e, f"scene {s.get('id')} missing '{k}'")
    _check(b["script"] and b["script"][0].get("beat") == "hook", e, "first scene must be the hook")
    _check(all(h.startswith("#") for h in b["hashtags"]), e, "hashtags must start with #")
    return e


def validate_storyboard(sb: dict, brief: dict | None = None) -> list[str]:
    e: list[str] = []
    for k in STORYBOARD_SCHEMA["required"]:
        _check(k in sb, e, f"storyboard missing '{k}'")
    if e:
        return e
    for s in sb["scenes"]:
        for k in ("id", "type", "duration", "image_prompt", "motion"):
            _check(k in s, e, f"scene {s.get('id')} missing '{k}'")
        _check(s.get("type") in SHOT_TYPES, e, f"scene {s.get('id')} bad type")
        _check(s.get("motion") in MOTIONS, e, f"scene {s.get('id')} bad motion")
        if s.get("type") == "video":
            _check(bool(s.get("video_prompt")), e, f"scene {s.get('id')} video needs video_prompt")
    if brief:
        want = [s["id"] for s in brief["script"]]
        have = [s["id"] for s in sb["scenes"]]
        _check(want == have, e, f"storyboard scene ids {have} must match script ids {want}")
    return e
