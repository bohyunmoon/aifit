"""ffmpeg assembly: stills with camera motion + Magnific video clips -> 9:16 H.264 with
burned-in captions, voiceover and ducked music."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from . import assets, config
from .captions import build_ass
from .tts import ffprobe_duration

ZOOM = 0.12


def sh(cmd: list[str], quiet: bool = True) -> None:
    res = subprocess.run(cmd, capture_output=quiet, text=True)
    if res.returncode != 0:
        raise SystemExit(f"ffmpeg failed ({res.returncode}):\n{' '.join(cmd)}\n{res.stderr[-3000:] if res.stderr else ''}")


def _motion_filter(motion: str, dur: float, w: int, h: int) -> str:
    d = max(dur, 0.1)
    z_in = f"(1+{ZOOM}*t/{d:.3f})"
    z_out = f"(1+{ZOOM}-{ZOOM}*t/{d:.3f})"
    z_fix = f"(1+{ZOOM})"
    cx, cy = "(iw-ow)/2", "(ih-oh)/2"
    table = {
        "zoom_in": (z_in, cx, cy),
        "zoom_out": (z_out, cx, cy),
        "pan_right": (z_fix, f"(iw-ow)*t/{d:.3f}", cy),
        "pan_left": (z_fix, f"(iw-ow)*(1-t/{d:.3f})", cy),
        "pan_down": (z_fix, cx, f"(ih-oh)*t/{d:.3f}"),
        "pan_up": (z_fix, cx, f"(ih-oh)*(1-t/{d:.3f})"),
        "static": ("1", cx, cy),
    }
    z, x, y = table.get(motion, table["zoom_in"])
    return (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
            f"scale=w='trunc(iw*{z}/2)*2':h='trunc(ih*{z}/2)*2':eval=frame:flags=bicubic,"
            f"crop={w}:{h}:x='{x}':y='{y}',setsar=1,format=yuv420p")


def build_timeline(project: config.Project) -> dict:
    brand = config.brand()
    vcfg = brand.get("video", {})
    min_s = float(vcfg.get("min_scene_seconds", 2.0))
    max_s = float(vcfg.get("max_scene_seconds", 7.0))
    brief = project.brief()
    sb = {s["id"]: s for s in project.storyboard()["scenes"]}
    man = {s["id"]: s for s in project.manifest()["scenes"]}
    t = 0.0
    scenes = []
    n = len(brief["script"])
    for i, s in enumerate(brief["script"]):
        sid = s["id"]
        meta_file = project.audio_dir / f"{sid}.json"
        meta = config.load_json(meta_file) if meta_file.exists() else {"duration": 0.0, "words": []}
        vo = float(meta.get("duration") or 0.0)
        floor = max(float(sb[sid].get("duration", 3)), min_s)
        tail = 0.9 if i == n - 1 else 0.35
        if vo > 0:
            dur = max(vo + tail, min(floor, max_s))
        else:
            dur = min(max(floor, min_s), max_s)
        visual = assets.best_visual(man[sid]) if sid in man else None
        if visual is None:
            raise SystemExit(f"scene {sid} has no downloaded asset. Run `ttk assets fetch` / `ttk assets generate` first.")
        words = meta.get("words") or []
        if not words and s["voiceover"].strip():
            from .tts import estimate_words
            words = estimate_words(s["voiceover"], dur - tail)
        scenes.append({
            "id": sid, "beat": s["beat"], "start": round(t, 3), "duration": round(dur, 3),
            "type": visual[0], "file": str(visual[1]), "motion": sb[sid].get("motion", "zoom_in"),
            "voiceover": s["voiceover"], "on_screen_text": s.get("on_screen_text", ""),
            "audio": str(project.audio_dir / f"{sid}.mp3") if vo > 0 else "", "words": words,
        })
        t += dur
    timeline = {"total": round(t, 3), "scenes": scenes, "music": project.storyboard().get("music", "")}
    config.save_json(project.timeline_file, timeline)
    return timeline


def _pick_music(name: str) -> Path | None:
    if name:
        p = config.MUSIC / name
        if p.exists():
            return p
        print(f"[assemble] music '{name}' not found in {config.MUSIC}; continuing without it")
        return None
    for p in sorted(config.MUSIC.glob("*")):
        if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"):
            return p
    return None


def render(project: config.Project, no_captions: bool = False) -> Path:
    brand = config.brand()
    vcfg = brand.get("video", {})
    W, H, FPS = int(vcfg.get("width", 1080)), int(vcfg.get("height", 1920)), int(vcfg.get("fps", 30))
    project.ensure()
    tl = build_timeline(project)
    build = project.build_dir
    for old in build.glob("seg_*.mp4"):
        old.unlink()

    # 1. one normalized segment per scene
    seg_files = []
    for i, s in enumerate(tl["scenes"]):
        seg = build / f"seg_{i:02d}.mp4"
        d = s["duration"]
        common = ["-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-an", str(seg)]
        if s["type"] == "video":
            vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},setsar=1,format=yuv420p"
            sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-stream_loop", "-1", "-i", s["file"], "-t", f"{d:.3f}", "-vf", vf] + common)
        else:
            vf = _motion_filter(s["motion"], d, W, H)
            sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-framerate", str(FPS), "-i", s["file"], "-t", f"{d:.3f}", "-vf", vf] + common)
        seg_files.append(seg)
        print(f"[assemble] {s['id']} {s['type']} {d:.2f}s {s['motion'] if s['type']=='image' else ''}")

    concat_list = build / "concat.txt"
    concat_list.write_text("".join(f"file '{p.as_posix()}'\n" for p in seg_files), encoding="utf-8")
    silent = build / "video_silent.mp4"
    sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(silent)])

    # 2. captions
    ass = build_ass(tl["scenes"], brand, project.captions_file, W, H)

    # 3. audio graph: voiceover clips placed at scene starts, music ducked underneath
    total = tl["total"]
    inputs = ["-i", str(silent)]
    graph = []
    vo_inputs = []
    idx = 1
    for s in tl["scenes"]:
        if s["audio"] and Path(s["audio"]).exists():
            inputs += ["-i", s["audio"]]
            ms = int(round(s["start"] * 1000))
            graph.append(f"[{idx}:a]aresample=44100,aformat=channel_layouts=stereo,adelay={ms}|{ms}[vo{idx}]")
            vo_inputs.append(f"[vo{idx}]")
            idx += 1
    if vo_inputs:
        graph.append("".join(vo_inputs) + f"amix=inputs={len(vo_inputs)}:normalize=0:dropout_transition=0,apad,atrim=0:{total:.3f},asetpts=N/SR/TB[vo]")
    else:
        graph.append(f"anullsrc=r=44100:cl=stereo,atrim=0:{total:.3f}[vo]")

    music = _pick_music(tl.get("music", ""))
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        mdb = float(brand.get("music_volume_db", -18))
        graph.append(f"[{idx}:a]aresample=44100,aformat=channel_layouts=stereo,atrim=0:{total:.3f},asetpts=N/SR/TB,"
                     f"volume={mdb}dB,afade=t=out:st={max(total-1.2,0):.3f}:d=1.2[m]")
        graph.append("[vo]asplit=2[vo_a][vo_sc]")
        graph.append("[m][vo_sc]sidechaincompress=threshold=0.015:ratio=8:attack=20:release=600:makeup=1[duck]")
        graph.append("[vo_a][duck]amix=inputs=2:normalize=0:duration=first[mix]")
        audio_src = "[mix]"
    else:
        audio_src = "[vo]"
    graph.append(f"{audio_src}loudnorm=I=-14:TP=-1.5:LRA=11[aout]")

    fade_out = max(total - 0.4, 0)
    vchain = f"[0:v]fade=t=in:st=0:d=0.25,fade=t=out:st={fade_out:.3f}:d=0.4"
    if not no_captions:
        vchain += f",ass='{ass.as_posix()}'"
    graph.insert(0, vchain + "[vout]")

    final = project.final_video
    sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + inputs + [
        "-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high", "-level", "4.1",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        "-movflags", "+faststart", "-t", f"{total:.3f}", str(final)])
    print(f"[assemble] final {final.name}: {ffprobe_duration(final):.2f}s")
    return final


def make_cover(project: config.Project, out: Path) -> Path:
    """Cover: hook-scene image with the brief's cover_text, drawn with Pillow."""
    from PIL import Image, ImageDraw, ImageFont
    from .captions import font_file

    brand = config.brand()
    W, H = int(brand.get("video", {}).get("width", 1080)), int(brand.get("video", {}).get("height", 1920))
    brief = project.brief()
    tl = config.load_json(project.timeline_file)
    first = tl["scenes"][0]
    if first["type"] == "video":
        frame = project.build_dir / "cover_src.png"
        sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "0.3", "-i", first["file"], "-frames:v", "1", str(frame)])
        src = frame
    else:
        src = Path(first["file"])
    img = Image.open(src).convert("RGB")
    scale = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1))
    left, top = (img.width - W) // 2, (img.height - H) // 2
    img = img.crop((left, top, left + W, top + H))
    draw = ImageDraw.Draw(img, "RGBA")
    draw.rectangle([0, int(H * 0.55), W, H], fill=(0, 0, 0, 90))
    text = brief.get("cover_text") or brief["hooks"][brief["chosen_hook"]]["text"]
    if brand.get("caption_style", {}).get("uppercase", True):
        text = text.upper()
    ff = font_file(brand.get("font", "DejaVu Sans"))
    size = 120
    font = ImageFont.truetype(ff, size) if ff else ImageFont.load_default()
    # wrap to ~3 lines
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) > W - 160 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    y = int(H * 0.62)
    hi = brand.get("colors", {}).get("highlight", "#FFD166")
    for i, line in enumerate(lines):
        tw = draw.textlength(line, font=font)
        x = (W - tw) / 2
        draw.text((x, y), line, font=font, fill=hi if i == 0 else "#FFFFFF", stroke_width=8, stroke_fill="#000000")
        y += int(size * 1.15)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=92)
    return out
