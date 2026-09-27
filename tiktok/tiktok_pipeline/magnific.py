"""Client for the official Magnific MCP server (https://mcp.magnific.com).

Everything goes through the MCP tools so generations run on the user's Magnific plan
credits. Tool names and argument shapes are discovered from the server at runtime
(`list_tools`) and mapped adaptively, with overrides in tiktok/magnific.json.

Auth: OAuth (browser login, tokens cached in tiktok/.magnific_tokens.json), or a
bearer token via MAGNIFIC_MCP_TOKEN / MAGNIFIC_API_KEY (tiktok/.env).
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import config

OPS = ("image", "video", "upscale", "remove_bg", "search", "show", "tts", "status")

# Candidate tool-name patterns per operation, most specific first.
TOOL_PATTERNS: dict[str, list[str]] = {
    "image": [r"^images?_generate$", r"^generate_image", r"^create_image", r"image.*gen", r"text.?to.?image"],
    "video": [r"^video_generate$", r"^videos?_generate", r"^generate_video", r"^create_video", r"image.?to.?video", r"video.*gen"],
    "upscale": [r"^images?_upscale$", r"upscale"],
    "remove_bg": [r"remove_background", r"remove_bg", r"background"],
    "search": [r"^creations?_search$", r"creations?_list", r"search"],
    "show": [r"^creations?_show$", r"^creations?_get$", r"creations?_show", r"^get_creation"],
    "tts": [r"^audio_tts$", r"text.?to.?speech", r"tts", r"speech"],
    "status": [r"task_status", r"get_status", r"_status$", r"^creations?_show$", r"^creations?_get$"],
}

MEDIA_EXT = (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm", ".mp3", ".wav", ".m4a", ".ogg")
PENDING_STATES = {"pending", "processing", "in_progress", "queued", "running", "created", "generating", "starting"}
FAILED_STATES = {"failed", "error", "cancelled", "canceled"}


@dataclass
class GenResult:
    urls: list[str] = field(default_factory=list)
    ids: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)   # local files written from inline base64
    status: str = ""
    raw: Any = None
    text: str = ""

    @property
    def url(self) -> str | None:
        return self.urls[0] if self.urls else None

    @property
    def id(self) -> str | None:
        return self.ids[0] if self.ids else None


def settings() -> dict:
    return config.load_json(config.MAGNIFIC_FILE, default={})


# ----------------------------------------------------------------------------- OAuth plumbing

class _FileTokenStorage:
    """Persists OAuth tokens + client registration next to the pipeline (gitignored)."""

    def __init__(self, path: Path):
        self.path = path

    def _read(self) -> dict:
        return config.load_json(self.path, default={})

    def _write(self, data: dict) -> None:
        config.save_json(self.path, data)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    async def get_tokens(self):
        from mcp.shared.auth import OAuthToken
        d = self._read().get("tokens")
        return OAuthToken.model_validate(d) if d else None

    async def set_tokens(self, tokens) -> None:
        d = self._read()
        d["tokens"] = tokens.model_dump(mode="json", exclude_none=True)
        self._write(d)

    async def get_client_info(self):
        from mcp.shared.auth import OAuthClientInformationFull
        d = self._read().get("client_info")
        return OAuthClientInformationFull.model_validate(d) if d else None

    async def set_client_info(self, client_info) -> None:
        d = self._read()
        d["client_info"] = client_info.model_dump(mode="json", exclude_none=True)
        self._write(d)


class _CallbackServer:
    """Tiny localhost HTTP server that catches the OAuth redirect."""

    def __init__(self, port: int):
        self.port = port
        self.result: dict | None = None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                q = parse_qs(urlparse(self.path).query)
                outer.result = {k: v[0] for k, v in q.items()}
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h2>Magnific connected. You can close this tab.</h2>")

            def log_message(self, *a):  # silence
                pass

        self.server = HTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()

    def wait(self, timeout: float = 300) -> dict:
        t0 = time.time()
        while self.result is None and time.time() - t0 < timeout:
            time.sleep(0.2)
        self.server.shutdown()
        if self.result is None:
            raise TimeoutError("Timed out waiting for the Magnific OAuth redirect")
        return self.result


def _oauth_provider(server_url: str):
    from mcp.client.auth import OAuthClientProvider
    from mcp.shared.auth import AuthorizationCodeResult, OAuthClientMetadata

    port = int(os.environ.get("MAGNIFIC_OAUTH_PORT", "8765"))
    redirect = f"http://localhost:{port}/callback"
    cb = _CallbackServer(port)

    async def redirect_handler(url: str) -> None:
        cb.start()
        print(f"\nOpen this URL to connect Magnific (a browser tab should open):\n{url}\n")
        webbrowser.open(url)

    async def callback_handler():
        res = await asyncio.to_thread(cb.wait)
        if "error" in res:
            raise RuntimeError(f"OAuth error: {res.get('error')} {res.get('error_description','')}")
        return AuthorizationCodeResult(code=res["code"], state=res.get("state"))

    metadata = OAuthClientMetadata(
        client_name="AIFit TikTok Pipeline",
        redirect_uris=[redirect],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
    )
    return OAuthClientProvider(
        server_url=server_url,
        client_metadata=metadata,
        storage=_FileTokenStorage(config.MAGNIFIC_TOKENS),
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )


# ----------------------------------------------------------------------------- client

class MagnificClient:
    """`async with MagnificClient() as m:` then m.generate_image(...), m.search(...), ..."""

    def __init__(self, url: str | None = None, verbose: bool = True):
        self.cfg = settings()
        self.url = url or os.environ.get("MAGNIFIC_MCP_URL") or self.cfg.get("url") or config.MAGNIFIC_MCP_URL
        self.verbose = verbose
        self.tools: dict[str, Any] = {}
        self._stack = None
        self.session = None

    # -- lifecycle
    async def __aenter__(self):
        import httpx2 as httpx
        from contextlib import AsyncExitStack
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        token = os.environ.get("MAGNIFIC_MCP_TOKEN") or os.environ.get("MAGNIFIC_API_KEY")
        if token:
            # Bearer token / plan API key. If the server insists on OAuth, unset both vars and
            # the browser login flow below is used instead.
            headers = {"Authorization": f"Bearer {token}", "x-magnific-api-key": token, "x-freepik-api-key": token}
            http = httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(60, read=300))
        else:
            http = httpx.AsyncClient(auth=_oauth_provider(self.url), timeout=httpx.Timeout(60, read=300))

        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        await self._stack.enter_async_context(http)
        streams = await self._stack.enter_async_context(streamable_http_client(self.url, http_client=http))
        read, write = streams[0], streams[1]
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        result = await self.session.list_tools()
        self.tools = {t.name: t for t in result.tools}
        self._log(f"Connected to {self.url}: {len(self.tools)} tools")
        return self

    async def __aexit__(self, *exc):
        if self._stack:
            await self._stack.__aexit__(*exc)

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"[magnific] {msg}")

    # -- discovery
    def dump_tools(self) -> dict:
        data = {name: {"description": t.description, "input_schema": t.input_schema} for name, t in self.tools.items()}
        config.save_json(config.MAGNIFIC_TOOLS_CACHE, data)
        return data

    def tool_for(self, op: str) -> str:
        override = (self.cfg.get("tools") or {}).get(op)
        if override:
            if override not in self.tools:
                raise SystemExit(f"magnific.json names tool '{override}' for {op}, but the server has: {sorted(self.tools)}")
            return override
        for pat in TOOL_PATTERNS[op]:
            for name in self.tools:
                if re.search(pat, name, re.I):
                    return name
        raise SystemExit(f"No Magnific tool found for '{op}'. Server tools: {sorted(self.tools)}. "
                         f"Set tools.{op} in {config.MAGNIFIC_FILE}.")

    def has(self, op: str) -> bool:
        try:
            self.tool_for(op)
            return True
        except SystemExit:
            return False

    # -- argument mapping (schema adaptive)
    def build_args(self, op: str, intent: dict) -> dict:
        tool = self.tools[self.tool_for(op)]
        schema = tool.input_schema or {}
        args = _fill(schema, intent)
        args.update((self.cfg.get("args") or {}).get(op) or {})
        missing = [k for k in schema.get("required", []) if k not in args]
        if missing:
            raise SystemExit(
                f"Tool {tool.name} requires {missing} which the pipeline can't infer. "
                f"Add them under args.{op} in {config.MAGNIFIC_FILE}. Schema:\n{json.dumps(schema, indent=2)}")
        return args

    # -- calls
    async def call(self, op: str, intent: dict, wait: bool = True) -> GenResult:
        name = self.tool_for(op)
        args = self.build_args(op, intent)
        self._log(f"{name} {json.dumps(args)[:300]}")
        res = await self.session.call_tool(name, args, read_timeout_seconds=600)
        out = parse_result(res, save_dir=intent.get("save_dir"))
        if res.is_error:
            raise RuntimeError(f"Magnific {name} failed: {out.text[:500]}")
        if wait and out.status in PENDING_STATES and not out.urls:
            out = await self._poll(out)
        return out

    async def _poll(self, first: GenResult) -> GenResult:
        if not first.id or not self.has("status"):
            return first
        every = float(self.cfg.get("poll_seconds", 6))
        deadline = time.time() + float(self.cfg.get("poll_timeout_seconds", 600))
        name = self.tool_for("status")
        while time.time() < deadline:
            await asyncio.sleep(every)
            args = self.build_args("status", {"id": first.id, "task_id": first.id})
            res = await self.session.call_tool(name, args, read_timeout_seconds=120)
            out = parse_result(res)
            self._log(f"poll {first.id}: {out.status or 'unknown'} urls={len(out.urls)}")
            if out.urls or out.files:
                out.ids = out.ids or first.ids
                return out
            if out.status in FAILED_STATES:
                raise RuntimeError(f"Magnific task {first.id} failed: {out.text[:400]}")
        raise TimeoutError(f"Magnific task {first.id} did not finish in time")

    async def generate_image(self, prompt: str, negative: str = "", model: str = "", save_dir: Path | None = None) -> GenResult:
        return await self.call("image", {
            "prompt": prompt, "negative_prompt": negative,
            "aspect_ratio": self.cfg.get("aspect_ratio", "9:16"),
            "model": model or self.cfg.get("image_model", ""), "num_images": 1, "save_dir": save_dir})

    async def upscale(self, image_url: str, image_id: str = "", save_dir: Path | None = None) -> GenResult:
        return await self.call("upscale", {"image_url": image_url, "image_id": image_id,
                                           "scale": self.cfg.get("upscale_factor", "2x"), "save_dir": save_dir})

    async def generate_video(self, image_url: str, prompt: str, image_id: str = "", seconds: int | None = None,
                             model: str = "", save_dir: Path | None = None) -> GenResult:
        return await self.call("video", {
            "image_url": image_url, "image_id": image_id, "prompt": prompt,
            "duration": seconds or self.cfg.get("video_seconds", 5),
            "aspect_ratio": self.cfg.get("aspect_ratio", "9:16"),
            "model": model or self.cfg.get("video_model", ""), "save_dir": save_dir})

    async def tts(self, text: str, voice: str = "", save_dir: Path | None = None) -> GenResult:
        return await self.call("tts", {"text": text, "voice": voice, "save_dir": save_dir})

    async def search(self, query: str = "", limit: int = 20) -> GenResult:
        return await self.call("search", {"query": query, "limit": limit}, wait=False)

    async def show(self, creation_id: str) -> GenResult:
        return await self.call("show", {"id": creation_id}, wait=False)


# ----------------------------------------------------------------------------- schema-adaptive arg fill

_KEYS = {
    "prompt": ["prompt", "description", "text_prompt"],
    "text": ["text", "input", "input_text", "content"],
    "negative_prompt": ["negative_prompt", "negativeprompt", "negative"],
    "aspect_ratio": ["aspect_ratio", "aspectratio", "ratio", "aspect", "orientation", "image_size", "size", "resolution", "format"],
    "image_url": ["image_url", "imageurl", "image", "source_image", "input_image", "reference_image", "start_image",
                  "first_frame", "init_image", "url", "source_url", "file_url", "reference"],
    "image_id": ["image_id", "creation_id", "creationid", "source_id", "asset_id", "reference_id"],
    "duration": ["duration", "duration_seconds", "seconds", "length"],
    "model": ["model", "model_id", "engine", "model_name"],
    "num_images": ["num_images", "number_of_images", "n", "count", "num_outputs", "samples"],
    "scale": ["scale", "scale_factor", "upscale_factor", "factor"],
    "query": ["query", "q", "search", "term", "keyword"],
    "limit": ["limit", "page_size", "per_page", "max_results", "top_k"],
    "id": ["id", "creation_id", "creationid", "task_id", "taskid", "job_id", "generation_id"],
    "task_id": ["task_id", "taskid", "job_id", "id"],
    "voice": ["voice", "voice_id", "voiceid", "speaker", "voice_name"],
}

_PORTRAIT_HINTS = ("9:16", "9_16", "9x16", "portrait", "vertical", "1080x1920", "tall", "story")


def _pick_enum(enum: list, want: Any, key_kind: str) -> Any:
    opts = [e for e in enum]
    if key_kind == "aspect_ratio":
        for o in opts:
            s = str(o).lower()
            if any(h in s for h in _PORTRAIT_HINTS):
                return o
        return None
    if key_kind == "duration":
        nums = []
        for o in opts:
            m = re.search(r"\d+(\.\d+)?", str(o))
            if m:
                nums.append((abs(float(m.group()) - float(want)), o))
        return min(nums)[1] if nums else opts[0]
    if key_kind == "scale":
        for o in opts:
            if str(want).rstrip("x") in str(o):
                return o
        return opts[0]
    for o in opts:
        if str(o).lower() == str(want).lower():
            return o
    return None


def _coerce(prop: dict, value: Any, kind: str) -> Any:
    t = prop.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), None)
    if "enum" in prop:
        return _pick_enum(prop["enum"], value, kind)
    if t in ("integer", "number"):
        try:
            return int(value) if t == "integer" else float(value)
        except (TypeError, ValueError):
            return None
    if t == "boolean":
        return bool(value)
    if t == "array":
        return value if isinstance(value, list) else [value]
    if t == "string":
        return str(value)
    return value


def _fill(schema: dict, intent: dict) -> dict:
    """Map intent values (prompt, aspect_ratio, image_url, ...) onto a tool's JSON schema
    by property name, one nested level deep. Empty values are skipped."""
    out: dict = {}
    props = schema.get("properties") or {}
    for name, prop in props.items():
        lname = name.lower()
        if prop.get("type") == "object" and prop.get("properties"):
            nested = _fill(prop, intent)
            if nested:
                out[name] = nested
            continue
        for kind, aliases in _KEYS.items():
            if lname not in aliases or kind not in intent:
                continue
            val = intent[kind]
            if val in ("", None, []):
                break
            if kind == "image_url" and not str(val).startswith(("http://", "https://", "data:")):
                break
            coerced = _coerce(prop, val, kind)
            if coerced is not None:
                out[name] = coerced
            break
    return out


# ----------------------------------------------------------------------------- result parsing

_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+")


def _walk(obj: Any, urls: list, ids: list, states: list) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = k.lower()
            if isinstance(v, str):
                if v.startswith(("http://", "https://")) and (lk.endswith("url") or lk in ("image", "video", "audio", "file", "src", "href", "download", "output", "result")
                                                            or v.lower().split("?")[0].endswith(MEDIA_EXT)):
                    urls.append(v)
                elif lk in ("id", "creation_id", "creationid", "task_id", "taskid", "job_id", "generation_id", "uuid"):
                    ids.append(v)
                elif lk in ("status", "state"):
                    states.append(v.lower())
            else:
                _walk(v, urls, ids, states)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, urls, ids, states)


def parse_result(res, save_dir: Path | None = None) -> GenResult:
    """Extract media URLs, ids, status from a CallToolResult, whatever shape Magnific uses."""
    out = GenResult(raw=None)
    urls: list[str] = []
    ids: list[str] = []
    states: list[str] = []
    texts: list[str] = []
    raw: list = []

    if res.structured_content:
        raw.append(res.structured_content)
        _walk(res.structured_content, urls, ids, states)

    for i, c in enumerate(res.content or []):
        ctype = getattr(c, "type", "")
        if ctype == "text":
            texts.append(c.text)
            try:
                data = json.loads(c.text)
                raw.append(data)
                _walk(data, urls, ids, states)
            except (json.JSONDecodeError, TypeError):
                urls.extend(u for u in _URL_RE.findall(c.text) if u.lower().split("?")[0].endswith(MEDIA_EXT) or "magnific" in u or "freepik" in u or "cdn" in u)
        elif ctype in ("image", "audio"):
            if save_dir is not None:
                ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "audio/mpeg": ".mp3", "audio/wav": ".wav"}.get(c.mime_type, "")
                p = Path(save_dir) / f"inline_{int(time.time())}_{i}{ext}"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(base64.b64decode(c.data))
                out.files.append(str(p))
        elif ctype == "resource_link":
            urls.append(str(c.uri))
        elif ctype == "resource":
            r = c.resource
            if getattr(r, "blob", None) and save_dir is not None:
                p = Path(save_dir) / f"inline_{int(time.time())}_{i}"
                p.write_bytes(base64.b64decode(r.blob))
                out.files.append(str(p))
            elif getattr(r, "text", None):
                texts.append(r.text)
                urls.extend(_URL_RE.findall(r.text))

    # de-dupe, keep order
    out.urls = list(dict.fromkeys(u.rstrip(".,") for u in urls))
    out.ids = list(dict.fromkeys(ids))
    out.status = states[0] if states else ""
    out.text = "\n".join(texts)
    out.raw = raw[0] if len(raw) == 1 else raw
    return out


# ----------------------------------------------------------------------------- sync helpers

def run(coro):
    return asyncio.run(coro)


def download(url: str, dest: Path, timeout: int = 300) -> Path:
    import urllib.request
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "aifit-tiktok-pipeline/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
    return dest
