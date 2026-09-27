"""Asset manifest: what every scene needs from Magnific, and where it ended up.

manifest.json shape:
{
  "scenes": [
    {"id": "s01", "type": "image"|"video", "image_prompt": ..., "video_prompt": ..., "upscale": true,
     "image": {"status": "pending"|"done", "url": ..., "creation_id": ..., "file": ...},
     "upscaled": {...same...},
     "video": {...same...}}
  ]
}

Two ways to fill it:
  * chat mode: Claude calls the Magnific MCP tools in the conversation and records results with
    `ttk assets set <slug> <scene> --kind image --url ... [--id ...]`, then `ttk assets fetch`.
  * headless: `ttk assets generate <slug>` drives the same MCP server from Python.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from . import config
from .magnific import MagnificClient, download, run

KINDS = ("image", "upscaled", "video")


def _slot() -> dict:
    return {"status": "pending", "url": "", "creation_id": "", "file": ""}


def plan(project: config.Project, force: bool = False) -> dict:
    """Create/refresh manifest.json from the storyboard, keeping any results already recorded."""
    sb = project.storyboard()
    brand = config.brand()
    old = {s["id"]: s for s in project.manifest().get("scenes", [])} if not force else {}
    scenes = []
    for s in sb["scenes"]:
        prev = old.get(s["id"], {})
        prompt = s["image_prompt"].strip()
        style = (sb.get("style") or "").strip()
        if style and style.lower() not in prompt.lower():
            prompt = f"{prompt} {style}"
        entry = {
            "id": s["id"],
            "type": s["type"],
            "image_prompt": prompt,
            "negative_prompt": brand.get("negative_prompt", ""),
            "video_prompt": s.get("video_prompt", ""),
            "upscale": bool(s.get("upscale")),
            "image": prev.get("image", _slot()),
            "upscaled": prev.get("upscaled", _slot()),
            "video": prev.get("video", _slot()),
        }
        scenes.append(entry)
    manifest = {"scenes": scenes}
    config.save_json(project.manifest_file, manifest)
    return manifest


def checklist(project: config.Project) -> str:
    """Human/Claude readable to-do list of Magnific calls still needed."""
    m = project.manifest()
    lines = [f"Magnific asset checklist for {project.slug} (aspect 9:16):"]
    for s in m["scenes"]:
        need = []
        if s["image"]["status"] != "done":
            need.append("images_generate")
        if s["upscale"] and s["upscaled"]["status"] != "done":
            need.append("images_upscale")
        if s["type"] == "video" and s["video"]["status"] != "done":
            need.append("video_generate")
        state = "READY" if not need else "TODO " + " -> ".join(need)
        lines.append(f"\n[{s['id']}] {state}")
        if s["image"]["status"] != "done":
            lines.append(f"  image prompt: {s['image_prompt']}")
            if s["negative_prompt"]:
                lines.append(f"  negative: {s['negative_prompt']}")
        if s["type"] == "video" and s["video"]["status"] != "done":
            lines.append(f"  video prompt: {s['video_prompt']}")
    lines.append(f"\nRecord each result with: ttk assets set {project.slug} <scene> --kind image|upscaled|video --url <url> [--id <creation_id>]")
    lines.append(f"Then download everything:  ttk assets fetch {project.slug}")
    return "\n".join(lines)


def set_result(project: config.Project, scene_id: str, kind: str, url: str = "", creation_id: str = "", file: str = "") -> None:
    if kind not in KINDS:
        raise SystemExit(f"kind must be one of {KINDS}")
    m = project.manifest()
    for s in m["scenes"]:
        if s["id"] == scene_id:
            slot = s[kind]
            if url:
                slot["url"] = url
            if creation_id:
                slot["creation_id"] = creation_id
            if file:
                slot["file"] = str(Path(file).resolve())
            slot["status"] = "done" if (slot["url"] or slot["file"]) else "pending"
            config.save_json(project.manifest_file, m)
            return
    raise SystemExit(f"scene {scene_id} not in manifest")


def _ext_for(url: str, kind: str) -> str:
    path = url.split("?")[0].lower()
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm"):
        if path.endswith(ext):
            return ext
    guess = mimetypes.guess_extension(mimetypes.guess_type(path)[0] or "") or ""
    return guess or (".mp4" if kind == "video" else ".png")


def fetch(project: config.Project) -> dict:
    """Download every recorded URL that has no local file yet."""
    m = project.manifest()
    for s in m["scenes"]:
        for kind in KINDS:
            slot = s[kind]
            if slot["status"] != "done":
                continue
            if slot["file"] and Path(slot["file"]).exists():
                continue
            if not slot["url"]:
                continue
            dest = project.assets_dir / f"{s['id']}_{kind}{_ext_for(slot['url'], kind)}"
            print(f"[assets] downloading {s['id']} {kind} -> {dest.name}")
            download(slot["url"], dest)
            slot["file"] = str(dest)
    config.save_json(project.manifest_file, m)
    return m


def best_visual(scene: dict) -> tuple[str, Path] | None:
    """(type, path) to use in the edit: video > upscaled image > image."""
    for kind, t in (("video", "video"), ("upscaled", "image"), ("image", "image")):
        slot = scene[kind]
        if slot["status"] == "done" and slot["file"] and Path(slot["file"]).exists():
            return t, Path(slot["file"])
    return None


def missing(project: config.Project) -> list[str]:
    return [s["id"] for s in project.manifest()["scenes"] if best_visual(s) is None]


# ------------------------------------------------------------------ headless generation over MCP

async def _generate_all(project: config.Project, only: list[str] | None, do_upscale: bool, do_video: bool) -> None:
    m = project.manifest()
    async with MagnificClient() as mc:
        for s in m["scenes"]:
            if only and s["id"] not in only:
                continue
            sid = s["id"]
            # 1. base image
            if s["image"]["status"] != "done":
                r = await mc.generate_image(s["image_prompt"], s["negative_prompt"], save_dir=project.assets_dir)
                if not (r.url or r.files):
                    raise RuntimeError(f"{sid}: no image URL in Magnific response: {r.text[:300]}")
                s["image"].update({"status": "done", "url": r.url or "", "creation_id": r.id or "",
                                   "file": r.files[0] if r.files else ""})
                config.save_json(project.manifest_file, m)
                print(f"[assets] {sid} image ok {r.url or r.files[0]}")
            src_url, src_id = s["image"]["url"], s["image"]["creation_id"]
            # 2. optional upscale
            if do_upscale and s["upscale"] and s["upscaled"]["status"] != "done" and src_url:
                r = await mc.upscale(src_url, src_id, save_dir=project.assets_dir)
                if r.url or r.files:
                    s["upscaled"].update({"status": "done", "url": r.url or "", "creation_id": r.id or "",
                                          "file": r.files[0] if r.files else ""})
                    src_url, src_id = s["upscaled"]["url"] or src_url, s["upscaled"]["creation_id"] or src_id
                    config.save_json(project.manifest_file, m)
                    print(f"[assets] {sid} upscaled ok")
            # 3. optional image-to-video
            if do_video and s["type"] == "video" and s["video"]["status"] != "done" and src_url:
                r = await mc.generate_video(src_url, s["video_prompt"], src_id, save_dir=project.assets_dir)
                if r.url or r.files:
                    s["video"].update({"status": "done", "url": r.url or "", "creation_id": r.id or "",
                                       "file": r.files[0] if r.files else ""})
                    config.save_json(project.manifest_file, m)
                    print(f"[assets] {sid} video ok")
                else:
                    print(f"[assets] {sid} video returned nothing usable; falling back to the still")
    fetch(project)


def generate(project: config.Project, only: list[str] | None = None, do_upscale: bool = True, do_video: bool = True) -> None:
    if not project.manifest_file.exists():
        plan(project)
    run(_generate_all(project, only, do_upscale, do_video))
