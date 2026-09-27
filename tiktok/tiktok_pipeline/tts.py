"""Voiceover per scene with word timings.

Providers (brand.json voice.provider):
  auto      -> magnific (if the MCP exposes a TTS tool and MAGNIFIC_MCP_TOKEN/OAuth works) else edge
  magnific  -> Magnific MCP audio_tts on plan credits (word timings estimated)
  edge      -> Microsoft Edge neural voices via edge-tts (free, exact word timings)
  none      -> silent; captions are timed proportionally

Writes audio/<scene>.mp3 and audio/<scene>.json = {"duration": s, "words": [{"w","start","end"}]}.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
from pathlib import Path

from . import config
from .magnific import MagnificClient, download, run


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out or 0)


def tokenize(text: str) -> list[str]:
    return [w for w in re.split(r"\s+", text.strip()) if w]


def estimate_words(text: str, duration: float, lead: float = 0.05) -> list[dict]:
    """Spread words over `duration` proportionally to their length (used when the
    provider gives no word boundaries)."""
    words = tokenize(text)
    if not words:
        return []
    weights = [len(re.sub(r"[^\w]", "", w)) + 1.5 + (1.5 if w[-1] in ".,!?;:" else 0) for w in words]
    total = sum(weights)
    t = lead
    usable = max(duration - lead - 0.05, 0.2)
    out = []
    for w, wt in zip(words, weights):
        d = usable * wt / total
        out.append({"w": w, "start": round(t, 3), "end": round(t + d, 3)})
        t += d
    return out


async def _edge(text: str, mp3: Path, voice: str, rate: str) -> dict:
    import edge_tts
    comm = edge_tts.Communicate(text, voice, rate=rate or "+0%")
    words = []
    with open(mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append({"w": chunk["text"], "start": round(start, 3), "end": round(start + chunk["duration"] / 1e7, 3)})
    dur = ffprobe_duration(mp3)
    if not words:
        words = estimate_words(text, dur)
    return {"duration": dur, "words": words, "provider": "edge", "voice": voice}


async def _magnific_all(items: list[tuple[str, str, Path]], voice: str) -> dict[str, dict]:
    out = {}
    async with MagnificClient() as mc:
        for sid, text, mp3 in items:
            r = await mc.tts(text, voice, save_dir=mp3.parent)
            if r.files:
                Path(r.files[0]).replace(mp3)
            elif r.url:
                download(r.url, mp3)
            else:
                raise RuntimeError(f"{sid}: Magnific TTS returned no audio: {r.text[:300]}")
            dur = ffprobe_duration(mp3)
            out[sid] = {"duration": dur, "words": estimate_words(text, dur), "provider": "magnific", "voice": voice}
    return out


def synthesize(project: config.Project, provider: str | None = None, force: bool = False) -> dict[str, dict]:
    brand = config.brand()
    vcfg = brand.get("voice", {})
    provider = provider or vcfg.get("provider", "auto")
    brief = project.brief()
    project.ensure()
    todo = []
    results: dict[str, dict] = {}
    for s in brief["script"]:
        mp3 = project.audio_dir / f"{s['id']}.mp3"
        meta = project.audio_dir / f"{s['id']}.json"
        if not force and mp3.exists() and meta.exists():
            results[s["id"]] = config.load_json(meta)
            continue
        todo.append((s["id"], s["voiceover"].strip(), mp3))

    if provider == "none":
        for sid, text, mp3 in todo:
            results[sid] = {"duration": 0.0, "words": [], "provider": "none"}
            config.save_json(project.audio_dir / f"{sid}.json", results[sid])
        return results

    if todo and provider in ("auto", "magnific"):
        try:
            got = run(_magnific_all(todo, vcfg.get("magnific_voice", "")))
            for sid, meta in got.items():
                results[sid] = meta
                config.save_json(project.audio_dir / f"{sid}.json", meta)
            todo = []
        except BaseException as e:  # noqa: BLE001 - fall back on any failure in auto mode
            if provider == "magnific":
                raise
            print(f"[voice] Magnific TTS unavailable ({type(e).__name__}: {str(e)[:120]}); using edge-tts")

    if todo:
        async def go():
            for sid, text, mp3 in todo:
                print(f"[voice] edge-tts {sid}: {text[:60]}")
                meta = await _edge(text, mp3, vcfg.get("edge_voice", "en-US-AndrewMultilingualNeural"), vcfg.get("rate", "+0%"))
                results[sid] = meta
                config.save_json(project.audio_dir / f"{sid}.json", meta)
        run(go())
    return results
