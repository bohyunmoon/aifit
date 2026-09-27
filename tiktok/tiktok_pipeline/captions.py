"""Build an ASS subtitle file: word-highlighted phrase captions in the TikTok safe
zone plus an on-screen title per scene."""
from __future__ import annotations

import subprocess
from pathlib import Path

from . import config


def _ass_color(hex_color: str, alpha: int = 0) -> str:
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ts(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def font_file(name: str) -> str | None:
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}", name], capture_output=True, text=True).stdout.strip()
        return out or None
    except FileNotFoundError:
        return None


def build_ass(timeline: list[dict], brand: dict, out: Path, width: int = 1080, height: int = 1920) -> Path:
    """timeline: [{id, start, duration, words:[{w,start,end}] (scene-relative), on_screen_text, beat}]"""
    cs = brand.get("caption_style", {})
    font = brand.get("font", "DejaVu Sans")
    size = int(cs.get("font_size", 78))
    per_line = int(cs.get("words_per_line", 3))
    upper = bool(cs.get("uppercase", True))
    colors = brand.get("colors", {})
    white = _ass_color(colors.get("caption", "#FFFFFF"))
    hi = _ass_color(colors.get("highlight", "#FFD166"))
    black = _ass_color("#000000")
    shadow = _ass_color("#000000", 0x60)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},{size},{white},{white},{black},{shadow},-1,0,0,0,100,100,0,0,1,6,3,2,90,90,560,1
Style: Title,{font},{int(size * 1.05)},{white},{white},{black},{shadow},-1,0,0,0,100,100,0,0,1,7,3,8,80,80,280,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []

    for scene in timeline:
        s0 = scene["start"]
        dur = scene["duration"]
        title = (scene.get("on_screen_text") or "").strip()
        if title:
            t = _esc(title.upper() if upper else title)
            events.append(f"Dialogue: 1,{_ts(s0)},{_ts(s0 + dur)},Title,,0,0,0,,"
                          f"{{\\fad(120,120)\\fscx92\\fscy92\\t(0,120,\\fscx100\\fscy100)}}{t}")

        words = scene.get("words") or []
        if not words:
            continue
        # group into phrases; break early on punctuation
        phrases: list[list[dict]] = []
        cur: list[dict] = []
        for w in words:
            cur.append(w)
            if len(cur) >= per_line or w["w"][-1] in ".!?":
                phrases.append(cur)
                cur = []
        if cur:
            phrases.append(cur)

        for ph in phrases:
            p_start = s0 + ph[0]["start"]
            p_end = s0 + ph[-1]["end"] + 0.12
            # one event per highlighted word, phrase text stays put
            for i, w in enumerate(ph):
                w_start = s0 + w["start"] if i > 0 else p_start
                w_end = s0 + ph[i + 1]["start"] if i + 1 < len(ph) else p_end
                if w_end <= w_start:
                    continue
                parts = []
                for j, ww in enumerate(ph):
                    txt = _esc(ww["w"].upper() if upper else ww["w"])
                    parts.append(f"{{\\c{hi}}}{txt}{{\\c{white}}}" if j == i else txt)
                pop = "{\\fscx88\\fscy88\\t(0,70,\\fscx100\\fscy100)}" if i == 0 else ""
                events.append(f"Dialogue: 0,{_ts(w_start)},{_ts(w_end)},Caption,,0,0,0,,{pop}{' '.join(parts)}")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return out
