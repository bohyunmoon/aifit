# TikTok content pipeline

Concept → hooks/script/caption/hashtags → storyboard → Magnific visuals → voiceover →
9:16 video with burned-in captions → finished files in `tiktok/output/<slug>/`.

Python + ffmpeg handle everything except the visuals; those come from your Magnific
account through the **official Magnific MCP server** (`https://mcp.magnific.com`), so
every image, upscale and video runs on your plan's credits and shows up in your Magnific history.

## Setup (once)

```bash
pip install -r tiktok/requirements.txt          # mcp, pillow, edge-tts, anthropic, ...
brew install ffmpeg   # or apt install ffmpeg     # needs libass + libx264 (default builds have them)
claude mcp add --transport http magnific https://mcp.magnific.com   # Magnific in Claude Code (OAuth on first use)
cp tiktok/.env.example tiktok/.env               # optional: API key for headless mode, Anthropic key for --llm
```

Edit `tiktok/brand.json` (voice, hashtags, colours, font, caption style, TTS voice) and drop
royalty-free music into `tiktok/music/`.

## Two ways to run it

**From chat (recommended).** In Claude Code type `/tiktok <your idea>`. The skill in
`.claude/skills/tiktok/SKILL.md` makes Claude ideate with you, write `brief.json` and
`storyboard.json`, call the Magnific MCP tools for each scene, record the results, and run
voice → assemble → publish. You review hooks before any credits are spent.

**Headless.** With `MAGNIFIC_API_KEY` (or the OAuth login) and `ANTHROPIC_API_KEY` in `tiktok/.env`:

```bash
python tiktok/ttk.py new "The 2-minute morning mobility reset" --from-file tiktok/concepts/example-2-minute-mobility.json
python tiktok/ttk.py run the-2-minute-morning-mobility-reset --llm
```

## Commands

| Command | What it does |
|---|---|
| `ttk new "<title>" [--idea ..] [--angle ..] [--from-file concept.json]` | create `work/<slug>/concept.json` |
| `ttk brief <slug> [--llm] [--feedback ..]` | print the brief prompt + schema (chat mode) or generate with the Claude API |
| `ttk storyboard <slug> [--llm]` | same for the storyboard |
| `ttk validate <slug>` | check both JSON files against the schema |
| `ttk assets plan <slug>` | build `assets/manifest.json` and print the Magnific checklist |
| `ttk assets set <slug> <scene> --kind image\|upscaled\|video --url .. --id ..` | record a Magnific result (chat mode) |
| `ttk assets fetch <slug>` | download recorded URLs |
| `ttk assets generate <slug> [--only s01 s02] [--no-upscale] [--no-video]` | headless: generate everything over the MCP server |
| `ttk voice <slug> [--provider auto\|magnific\|edge\|none] [--force]` | voiceover + word timings per scene |
| `ttk assemble <slug> [--no-captions]` | render 1080x1920/30fps H.264 + AAC |
| `ttk publish <slug>` | copy deliverables to `output/<slug>/` |
| `ttk run <slug> [--llm]` | brief → publish in one go |
| `ttk magnific discover` | connect to the MCP server, cache tool schemas to `magnific_tools.json`, show the op → tool mapping |
| `ttk magnific search "<q>"` / `ttk magnific show --id <creation>` | browse your creations |
| `ttk list` / `ttk status <slug>` | where each project is |

`ttk` = `python tiktok/ttk.py` (add an alias).

## How Magnific is used

`tiktok_pipeline/magnific.py` is an MCP client (streamable HTTP) for `mcp.magnific.com`:

- Auth: browser OAuth on first run (tokens cached in `tiktok/.magnific_tokens.json`, gitignored), or a
  bearer token from `MAGNIFIC_MCP_TOKEN` / `MAGNIFIC_API_KEY`.
- Tools are discovered at runtime and matched to operations by name (`images_generate`, `images_upscale`,
  `video_generate`, `creations_search`, `creations_show`, `audio_tts`, ...). Arguments are filled by matching the
  tool's JSON schema (prompt, aspect ratio → the 9:16/portrait enum value, image url/id, duration, model).
  If a mapping is wrong, pin names and extra args in `tiktok/magnific.json` (`tools.*`, `args.*`) after running
  `ttk magnific discover` and reading `magnific_tools.json`.
- Results are parsed for media URLs, creation ids and status; pending tasks are polled.

## Output

```
tiktok/output/<slug>/
  <slug>.mp4      1080x1920, 30 fps, H.264 + AAC, captions burned in, loudness -14 LUFS
  cover.jpg       hook frame with cover_text
  caption.txt     caption + hashtags ready to paste
  hashtags.txt
  brief.md        hooks, script table, notes
  captions.ass    editable subtitle file
  metadata.json   durations + Magnific creation ids
```

## Layout

```
tiktok/
  ttk.py                 CLI
  tiktok_pipeline/       config, schema, brief, magnific, assets, tts, captions, assemble, publish
  prompts/               system prompts for the brief and storyboard
  concepts/              your concept files (examples included)
  brand.json  magnific.json  .env.example
  music/                 background tracks (gitignored except README)
  work/<slug>/           concept.json brief.json storyboard.json assets/ audio/ build/   (gitignored)
  output/<slug>/         deliverables (gitignored)
```
