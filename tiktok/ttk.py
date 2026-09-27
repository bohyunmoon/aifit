#!/usr/bin/env python3
"""ttk - TikTok content pipeline CLI.  Run from anywhere: python tiktok/ttk.py <command> ...

  new "<title>" [--idea ...] [--notes ...]   create a concept + work folder
  list                                       list projects and their stage
  status <slug>                              what's done / what's next
  brief <slug> [--llm] [--feedback ...]      show the brief prompt (chat mode) or generate via Claude API
  storyboard <slug> [--llm] [--feedback ...] same for the storyboard
  validate <slug>                            validate brief.json / storyboard.json
  assets plan|checklist|set|fetch|generate   Magnific asset manifest management
  voice <slug> [--provider auto|magnific|edge|none] [--force]
  assemble <slug> [--no-captions]            render the 9:16 video
  publish <slug>                             drop finished files into tiktok/output/<slug>/
  run <slug> [--llm]                         everything after the concept, headless
  magnific discover|search|show              talk to the Magnific MCP server directly
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tiktok_pipeline import assets, brief as briefmod, config  # noqa: E402
from tiktok_pipeline.schema import validate_brief, validate_storyboard  # noqa: E402


def cmd_new(a):
    slug = config.slugify(a.slug or a.title)
    p = config.Project(slug).ensure()
    if p.concept_file.exists() and not a.force:
        raise SystemExit(f"{p.concept_file} exists (use --force to overwrite)")
    concept = {"title": a.title, "idea": a.idea or "", "angle": a.angle or "", "audience_pain": "", "key_points": [],
               "cta": "", "tone": "", "references": [], "must_include": [], "avoid": [], "notes": a.notes or ""}
    if a.from_file:
        concept.update(config.load_json(Path(a.from_file)))
        concept["title"] = concept.get("title") or a.title
    config.save_json(p.concept_file, concept)
    print(f"created {slug}\n  {p.concept_file}\nnext: ttk brief {slug}")


def _stage(p: config.Project) -> str:
    if (p.output_dir / f"{p.slug}.mp4").exists():
        return "published"
    if p.final_video.exists():
        return "rendered"
    if p.manifest_file.exists() and not assets.missing(p):
        return "assets ready"
    if p.storyboard_file.exists():
        return "storyboarded"
    if p.brief_file.exists():
        return "briefed"
    return "concept"


def cmd_list(a):
    if not config.WORK.exists():
        print("no projects yet")
        return
    for d in sorted(config.WORK.iterdir()):
        p = config.Project(d.name)
        if p.exists:
            print(f"{d.name:40s} {_stage(p)}")


def cmd_status(a):
    p = config.Project.resolve(a.slug)
    print(f"{p.slug}: {_stage(p)}")
    print(f"  concept:    {p.concept_file}")
    print(f"  brief:      {'ok' if p.brief_file.exists() else 'missing'}")
    print(f"  storyboard: {'ok' if p.storyboard_file.exists() else 'missing'}")
    if p.manifest_file.exists():
        miss = assets.missing(p)
        print(f"  assets:     {'all downloaded' if not miss else 'missing ' + ', '.join(miss)}")
    audio = sorted(p.audio_dir.glob("*.mp3")) if p.audio_dir.exists() else []
    print(f"  voice:      {len(audio)} clips")
    print(f"  video:      {p.final_video if p.final_video.exists() else 'not rendered'}")
    print(f"  output:     {p.output_dir if p.output_dir.exists() else '-'}")


def cmd_brief(a):
    p = config.Project.resolve(a.slug)
    if a.llm:
        b = briefmod.generate_brief(p, a.feedback or "")
        print(briefmod.brief_markdown(b, config.brand()))
    else:
        briefmod.print_brief_prompt(p, a.feedback or "")


def cmd_storyboard(a):
    p = config.Project.resolve(a.slug)
    if a.llm:
        briefmod.generate_storyboard(p, a.feedback or "")
        print(json.dumps(p.storyboard(), indent=2))
    else:
        briefmod.print_storyboard_prompt(p, a.feedback or "")


def cmd_validate(a):
    p = config.Project.resolve(a.slug)
    ok = True
    if p.brief_file.exists():
        e = validate_brief(p.brief())
        print("brief:", "ok" if not e else "\n  - " + "\n  - ".join(e))
        ok &= not e
        if p.storyboard_file.exists():
            e = validate_storyboard(p.storyboard(), p.brief())
            print("storyboard:", "ok" if not e else "\n  - " + "\n  - ".join(e))
            ok &= not e
    else:
        print("brief: missing")
        ok = False
    sys.exit(0 if ok else 1)


def cmd_assets(a):
    p = config.Project.resolve(a.slug)
    if a.action == "plan":
        assets.plan(p, force=a.force)
        print(assets.checklist(p))
    elif a.action == "checklist":
        if not p.manifest_file.exists():
            assets.plan(p)
        print(assets.checklist(p))
    elif a.action == "set":
        assets.set_result(p, a.scene, a.kind, url=a.url or "", creation_id=a.id or "", file=a.file or "")
        print(f"recorded {a.scene} {a.kind}")
    elif a.action == "fetch":
        assets.fetch(p)
        miss = assets.missing(p)
        print("all assets downloaded" if not miss else f"still missing: {', '.join(miss)}")
    elif a.action == "generate":
        assets.generate(p, only=a.only, do_upscale=not a.no_upscale, do_video=not a.no_video)
        print("all assets downloaded" if not assets.missing(p) else f"still missing: {', '.join(assets.missing(p))}")


def cmd_voice(a):
    from tiktok_pipeline.tts import synthesize
    p = config.Project.resolve(a.slug)
    res = synthesize(p, provider=a.provider, force=a.force)
    for sid, m in res.items():
        print(f"  {sid}: {m['duration']:.2f}s via {m.get('provider')}")


def cmd_assemble(a):
    from tiktok_pipeline.assemble import render
    p = config.Project.resolve(a.slug)
    print(render(p, no_captions=a.no_captions))


def cmd_publish(a):
    from tiktok_pipeline.publish import publish
    publish(config.Project.resolve(a.slug))


def cmd_run(a):
    from tiktok_pipeline.assemble import render
    from tiktok_pipeline.publish import publish
    from tiktok_pipeline.tts import synthesize
    p = config.Project.resolve(a.slug)
    if not p.brief_file.exists():
        if not a.llm:
            raise SystemExit("No brief.json yet. Either write it in chat (ttk brief <slug>) or pass --llm.")
        briefmod.generate_brief(p)
    if not p.storyboard_file.exists():
        if not a.llm:
            raise SystemExit("No storyboard.json yet. Either write it in chat (ttk storyboard <slug>) or pass --llm.")
        briefmod.generate_storyboard(p)
    e = validate_brief(p.brief()) + validate_storyboard(p.storyboard(), p.brief())
    if e:
        raise SystemExit("validation: " + "; ".join(e))
    assets.plan(p)
    if assets.missing(p):
        assets.generate(p)
    synthesize(p, provider=a.provider)
    render(p)
    publish(p)


def cmd_magnific(a):
    from tiktok_pipeline.magnific import MagnificClient, run

    async def go():
        async with MagnificClient() as mc:
            if a.action == "discover":
                tools = mc.dump_tools()
                print(f"saved {len(tools)} tool schemas to {config.MAGNIFIC_TOOLS_CACHE}")
                for op in ("image", "video", "upscale", "remove_bg", "search", "show", "tts", "status"):
                    try:
                        print(f"  {op:10s} -> {mc.tool_for(op)}")
                    except SystemExit:
                        print(f"  {op:10s} -> (none)")
            elif a.action == "search":
                r = await mc.search(a.query or "", a.limit)
                print(r.text or json.dumps(r.raw, indent=2)[:4000])
                for u in r.urls:
                    print(u)
            elif a.action == "show":
                r = await mc.show(a.id)
                print(r.text or json.dumps(r.raw, indent=2)[:4000])
                for u in r.urls:
                    print(u)
    run(go())


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ttk", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("new"); s.add_argument("title"); s.add_argument("--slug"); s.add_argument("--idea"); s.add_argument("--angle")
    s.add_argument("--notes"); s.add_argument("--from-file"); s.add_argument("--force", action="store_true"); s.set_defaults(fn=cmd_new)
    s = sub.add_parser("list"); s.set_defaults(fn=cmd_list)
    s = sub.add_parser("status"); s.add_argument("slug"); s.set_defaults(fn=cmd_status)
    for name, fn in (("brief", cmd_brief), ("storyboard", cmd_storyboard)):
        s = sub.add_parser(name); s.add_argument("slug"); s.add_argument("--llm", action="store_true", help="generate via Claude API")
        s.add_argument("--feedback", help="revision notes"); s.set_defaults(fn=fn)
    s = sub.add_parser("validate"); s.add_argument("slug"); s.set_defaults(fn=cmd_validate)
    s = sub.add_parser("assets"); s.add_argument("action", choices=["plan", "checklist", "set", "fetch", "generate"]); s.add_argument("slug")
    s.add_argument("scene", nargs="?"); s.add_argument("--kind", choices=["image", "upscaled", "video"], default="image")
    s.add_argument("--url"); s.add_argument("--id"); s.add_argument("--file"); s.add_argument("--force", action="store_true")
    s.add_argument("--only", nargs="*"); s.add_argument("--no-upscale", action="store_true"); s.add_argument("--no-video", action="store_true")
    s.set_defaults(fn=cmd_assets)
    s = sub.add_parser("voice"); s.add_argument("slug"); s.add_argument("--provider", choices=["auto", "magnific", "edge", "none"])
    s.add_argument("--force", action="store_true"); s.set_defaults(fn=cmd_voice)
    s = sub.add_parser("assemble"); s.add_argument("slug"); s.add_argument("--no-captions", action="store_true"); s.set_defaults(fn=cmd_assemble)
    s = sub.add_parser("publish"); s.add_argument("slug"); s.set_defaults(fn=cmd_publish)
    s = sub.add_parser("run"); s.add_argument("slug"); s.add_argument("--llm", action="store_true")
    s.add_argument("--provider", choices=["auto", "magnific", "edge", "none"]); s.set_defaults(fn=cmd_run)
    s = sub.add_parser("magnific"); s.add_argument("action", choices=["discover", "search", "show"]); s.add_argument("query", nargs="?")
    s.add_argument("--id"); s.add_argument("--limit", type=int, default=20); s.set_defaults(fn=cmd_magnific)

    a = ap.parse_args(argv)
    if a.cmd == "assets" and a.action == "set" and not a.scene:
        ap.error("assets set needs <slug> <scene>")
    if a.cmd == "magnific" and a.action == "show" and not (a.id or a.query):
        ap.error("magnific show needs --id <creation_id>")
    if a.cmd == "magnific" and a.action == "show" and not a.id:
        a.id = a.query
    a.fn(a)


if __name__ == "__main__":
    main()
