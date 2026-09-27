---
name: tiktok
description: Repeatable TikTok production process. Use when the user brings a content idea/concept and wants hooks, a script, caption, hashtags, Magnific visuals, voiceover and a finished 9:16 video dropped in tiktok/output/<slug>/. Also for "make a TikTok about X", "new video concept", "regenerate scene 3", "browse my Magnific creations".
---

# TikTok pipeline (chat-driven)

You drive `python tiktok/ttk.py` (alias below: `ttk`) and call the **Magnific MCP tools yourself**
for every visual, so generations run on the user's Magnific plan credits. Python + ffmpeg do
everything around the assets. Read `tiktok/README.md` once if anything here is unclear.

Preconditions: the `magnific` MCP server is connected (`claude mcp add --transport http magnific https://mcp.magnific.com`);
`ffmpeg` on PATH; `pip install -r tiktok/requirements.txt`. If Magnific tools are not in your tool list, say so and stop
after the brief/storyboard steps (they don't need Magnific).

## Process

1. **Ideate** with the user. Restate the concept in one line, propose 3 angles (contrarian / list / story), and
   ask which one to build unless they already decided. Keep this short.
2. **Create the project**: `ttk new "<title>" --idea "<one paragraph>" --angle "<angle>"` → prints `<slug>`.
   Optionally edit `tiktok/work/<slug>/concept.json` (key_points, must_include, avoid, cta).
3. **Write the brief** yourself: run `ttk brief <slug>` to print the system prompt, brand, concept and JSON
   schema, then author `tiktok/work/<slug>/brief.json` exactly to that schema (5 hooks, pick one, 5-8 scenes,
   caption, hashtags, cover_text). `ttk validate <slug>` must pass. Show the user the 5 hooks and the script
   as a short table and ask for a pick/edits before generating any assets (assets cost credits).
4. **Write the storyboard**: `ttk storyboard <slug>` prints the prompt; author `storyboard.json`
   (one shot per script scene, image prompts with no text in them, at most 2 `video` scenes, `upscale` on the hook
   scene). `ttk validate <slug>` again.
5. **Generate assets with Magnific**: `ttk assets plan <slug>` writes the manifest and prints a checklist.
   For each scene, in order:
   - call the Magnific image tool (`images_generate`) with the scene's `image prompt`, aspect ratio 9:16
     (portrait), 1 image. Use the brand negative prompt if the tool accepts one.
   - if the checklist says `images_upscale`, upscale that creation (2x is enough).
   - if the scene is `video`, call `video_generate` from the (upscaled) image with the `video prompt`, ~5 s, 9:16.
   - record every result: `ttk assets set <slug> <scene> --kind image|upscaled|video --url <url> --id <creation_id>`.
     If a tool returns no URL, use `creations_show`/`creations_search` to find it. If a result looks wrong
     (text baked in, extra limbs, wrong framing), regenerate that one scene before moving on.
   Then `ttk assets fetch <slug>` (downloads everything) and confirm `ttk status <slug>` says assets ready.
   Headless alternative when the user asks for it: `ttk assets generate <slug>` (Python talks to the same MCP server).
6. **Voice**: `ttk voice <slug>` (auto: Magnific TTS if the MCP has it, else edge-tts; `--provider none` for silent).
7. **Assemble**: `ttk assemble <slug>` → 1080x1920 H.264, burned-in captions, VO, ducked music from `tiktok/music/`.
8. **Publish**: `ttk publish <slug>` → `tiktok/output/<slug>/` with `<slug>.mp4`, `cover.jpg`, `caption.txt`,
   `hashtags.txt`, `brief.md`, `captions.ass`, `metadata.json` (includes Magnific creation ids).
9. **Report**: the output folder, runtime, the hook used, the caption + hashtags ready to paste, and anything
   you'd redo. Offer the obvious next iterations (swap hook, re-shoot a scene, different voice).

## Iterating
- New hook or script change → edit `brief.json`, re-run `ttk voice --force`, `ttk assemble`, `ttk publish`.
- Redo one visual → regenerate in Magnific, `ttk assets set ...` for that scene, `ttk assets fetch`, `ttk assemble`.
- Browse past work: use `creations_search` / `creations_show` in chat, or `ttk magnific search "<query>"`.
- `ttk list` / `ttk status <slug>` show where every project is.

## Rules
- Never bake text into generated images; captions are rendered by the pipeline.
- Keep the user's brand voice (`tiktok/brand.json`), respect `banned_words`, no medical/guaranteed claims.
- Ask before spending credits on more than ~10 generations for one video.
- Don't commit `tiktok/work/`, `tiktok/output/`, `.env` or token files (already gitignored).
