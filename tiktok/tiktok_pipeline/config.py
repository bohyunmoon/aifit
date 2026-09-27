"""Paths and brand configuration."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # tiktok/
CONCEPTS = ROOT / "concepts"
PROMPTS = ROOT / "prompts"
WORK = ROOT / "work"
OUTPUT = ROOT / "output"
MUSIC = ROOT / "music"
BRAND_FILE = ROOT / "brand.json"
MAGNIFIC_FILE = ROOT / "magnific.json"
MAGNIFIC_TOOLS_CACHE = ROOT / "magnific_tools.json"
MAGNIFIC_TOKENS = ROOT / ".magnific_tokens.json"

ENV_FILE = ROOT / ".env"


def load_env(path: Path = ENV_FILE) -> None:
    """Load KEY=VALUE lines from tiktok/.env (gitignored) without overriding real env vars."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()
MAGNIFIC_MCP_URL = os.environ.get("MAGNIFIC_MCP_URL", "https://mcp.magnific.com")


def load_json(path: Path, default=None):
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


def brand() -> dict:
    return load_json(BRAND_FILE)


def slugify(text: str, max_len: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len].rstrip("-") or "concept"


class Project:
    """All files for one piece of content live under work/<slug>/."""

    def __init__(self, slug: str):
        self.slug = slug
        self.dir = WORK / slug
        self.assets_dir = self.dir / "assets"
        self.audio_dir = self.dir / "audio"
        self.build_dir = self.dir / "build"
        self.concept_file = self.dir / "concept.json"
        self.brief_file = self.dir / "brief.json"
        self.storyboard_file = self.dir / "storyboard.json"
        self.manifest_file = self.assets_dir / "manifest.json"
        self.timeline_file = self.build_dir / "timeline.json"
        self.captions_file = self.build_dir / "captions.ass"
        self.final_video = self.build_dir / f"{slug}.mp4"
        self.output_dir = OUTPUT / slug

    def ensure(self) -> "Project":
        for d in (self.dir, self.assets_dir, self.audio_dir, self.build_dir):
            d.mkdir(parents=True, exist_ok=True)
        return self

    @property
    def exists(self) -> bool:
        return self.concept_file.exists()

    def concept(self) -> dict:
        return load_json(self.concept_file)

    def brief(self) -> dict:
        return load_json(self.brief_file)

    def storyboard(self) -> dict:
        return load_json(self.storyboard_file)

    def manifest(self) -> dict:
        return load_json(self.manifest_file, default={"scenes": []})

    @staticmethod
    def resolve(name_or_slug: str) -> "Project":
        p = Project(name_or_slug)
        if p.exists:
            return p
        p = Project(slugify(name_or_slug))
        if p.exists:
            return p
        raise SystemExit(f"No project '{name_or_slug}' under {WORK}. Run `ttk new` first or `ttk list`.")
