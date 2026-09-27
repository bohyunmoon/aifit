"""Drop the finished files into tiktok/output/<slug>/."""
from __future__ import annotations

import datetime as dt
import shutil

from . import config
from .assemble import make_cover
from .brief import brief_markdown, caption_text
from .tts import ffprobe_duration


def publish(project: config.Project) -> config.Project:
    out = project.output_dir
    out.mkdir(parents=True, exist_ok=True)
    brief = project.brief()
    brand = config.brand()
    if not project.final_video.exists():
        raise SystemExit("No rendered video. Run `ttk assemble` first.")
    video = out / f"{project.slug}.mp4"
    shutil.copy2(project.final_video, video)
    make_cover(project, out / "cover.jpg")
    (out / "caption.txt").write_text(caption_text(brief), encoding="utf-8")
    (out / "hashtags.txt").write_text(" ".join(brief["hashtags"]) + "\n", encoding="utf-8")
    (out / "brief.md").write_text(brief_markdown(brief, brand), encoding="utf-8")
    shutil.copy2(project.captions_file, out / "captions.ass")
    manifest = project.manifest()
    meta = {
        "slug": project.slug,
        "title": brief["title"],
        "hook": brief["hooks"][brief["chosen_hook"]]["text"],
        "duration_seconds": round(ffprobe_duration(video), 2),
        "published_files": sorted(p.name for p in out.iterdir()),
        "magnific_creations": [
            {"scene": s["id"], "kind": k, "creation_id": s[k]["creation_id"], "url": s[k]["url"]}
            for s in manifest["scenes"] for k in ("image", "upscaled", "video") if s[k]["status"] == "done"
        ],
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    config.save_json(out / "metadata.json", meta)
    print(f"[publish] {out}")
    for p in sorted(out.iterdir()):
        print(f"  {p.name}")
    return project
