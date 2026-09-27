"""Brief (hooks, script, caption, hashtags) and storyboard generation.

Two ways to author these files:
  1. In chat: Claude (with the tiktok skill loaded) writes brief.json / storyboard.json
     directly, following prompts/*.md and the schema. `ttk brief --print-prompt` shows
     exactly what to follow.
  2. Headless: `ttk brief <slug> --llm` calls the Claude API with structured outputs.
"""
from __future__ import annotations

import json
import os

from . import config
from .schema import BRIEF_SCHEMA, STORYBOARD_SCHEMA, validate_brief, validate_storyboard

DEFAULT_MODEL = os.environ.get("TTK_CLAUDE_MODEL", "claude-opus-5")


def _prompt(name: str) -> str:
    return (config.PROMPTS / name).read_text(encoding="utf-8")


def brief_user_message(concept: dict, brand: dict, feedback: str = "") -> str:
    msg = (
        f"BRAND:\n{json.dumps(brand, indent=2)}\n\n"
        f"CONCEPT:\n{json.dumps(concept, indent=2)}\n\n"
        "Write the brief."
    )
    if feedback:
        msg += f"\n\nREVISION NOTES FROM THE CREATOR (apply them):\n{feedback}"
    return msg


def storyboard_user_message(concept: dict, brief: dict, brand: dict, feedback: str = "") -> str:
    msg = (
        f"BRAND VISUAL STYLE: {brand.get('visual_style','')}\n"
        f"NEGATIVE (never in image): {brand.get('negative_prompt','')}\n\n"
        f"CONCEPT TITLE: {concept.get('title')}\n\n"
        f"SCRIPT:\n{json.dumps(brief['script'], indent=2)}\n\n"
        f"COVER TEXT: {brief.get('cover_text','')}\n\n"
        "Write the storyboard."
    )
    if feedback:
        msg += f"\n\nREVISION NOTES FROM THE CREATOR (apply them):\n{feedback}"
    return msg


def print_brief_prompt(project: config.Project, feedback: str = "") -> None:
    print("=== SYSTEM ===\n" + _prompt("brief_system.md"))
    print("=== USER ===\n" + brief_user_message(project.concept(), config.brand(), feedback))
    print("=== JSON SCHEMA ===\n" + json.dumps(BRIEF_SCHEMA, indent=2))
    print(f"\nWrite the result to: {project.brief_file}")


def print_storyboard_prompt(project: config.Project, feedback: str = "") -> None:
    print("=== SYSTEM ===\n" + _prompt("storyboard_system.md"))
    print("=== USER ===\n" + storyboard_user_message(project.concept(), project.brief(), config.brand(), feedback))
    print("=== JSON SCHEMA ===\n" + json.dumps(STORYBOARD_SCHEMA, indent=2))
    print(f"\nWrite the result to: {project.storyboard_file}")


# ---------------------------------------------------------------- headless (Claude API)

def _claude_json(system: str, user: str, schema: dict, model: str = DEFAULT_MODEL) -> dict:
    """One structured-output call to the Claude API. Requires ANTHROPIC_API_KEY (or an
    `ant auth login` profile)."""
    import anthropic  # imported lazily so chat-mode users don't need it

    client = anthropic.Anthropic()
    with client.messages.stream(
        model=model,
        max_tokens=16000,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        thinking={"type": "adaptive"},
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": schema}},
    ) as stream:
        response = stream.get_final_message()
    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        raise SystemExit(f"Claude declined the request: {details}")
    text = "".join(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def generate_brief(project: config.Project, feedback: str = "", model: str = DEFAULT_MODEL) -> dict:
    data = _claude_json(_prompt("brief_system.md"),
                        brief_user_message(project.concept(), config.brand(), feedback),
                        BRIEF_SCHEMA, model)
    errors = validate_brief(data)
    if errors:
        raise SystemExit("Generated brief failed validation: " + "; ".join(errors))
    config.save_json(project.brief_file, data)
    return data


def generate_storyboard(project: config.Project, feedback: str = "", model: str = DEFAULT_MODEL) -> dict:
    brief = project.brief()
    data = _claude_json(_prompt("storyboard_system.md"),
                        storyboard_user_message(project.concept(), brief, config.brand(), feedback),
                        STORYBOARD_SCHEMA, model)
    errors = validate_storyboard(data, brief)
    if errors:
        raise SystemExit("Generated storyboard failed validation: " + "; ".join(errors))
    config.save_json(project.storyboard_file, data)
    return data


# ---------------------------------------------------------------- derived text

def brief_markdown(brief: dict, brand: dict) -> str:
    hook = brief["hooks"][brief["chosen_hook"]]
    lines = [f"# {brief['title']}", "", f"**Hook ({hook['type']}):** {hook['text']}", "", "## Alternate hooks"]
    for i, h in enumerate(brief["hooks"]):
        mark = " (chosen)" if i == brief["chosen_hook"] else ""
        lines.append(f"- [{h['type']}] {h['text']}{mark}")
    lines += ["", "## Script", "", "| # | Beat | Voiceover | On screen | Visual |", "|---|---|---|---|---|"]
    for s in brief["script"]:
        lines.append(f"| {s['id']} | {s['beat']} | {s['voiceover']} | {s['on_screen_text']} | {s['visual_idea']} |")
    lines += ["", "## Caption", "", brief["caption"], "", " ".join(brief["hashtags"]), "",
              f"**CTA:** {brief['cta']}  ", f"**Cover text:** {brief['cover_text']}", "", "## Notes", "", brief.get("notes", "")]
    return "\n".join(lines) + "\n"


def caption_text(brief: dict) -> str:
    return brief["caption"].strip() + "\n\n" + " ".join(brief["hashtags"]) + "\n"
