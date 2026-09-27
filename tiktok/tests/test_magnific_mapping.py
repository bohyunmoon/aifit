"""Offline tests for the schema-adaptive Magnific argument mapping and result parsing.
Run: python -m pytest tiktok/tests -q   (or python tiktok/tests/test_magnific_mapping.py)"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tiktok_pipeline.magnific import _fill, parse_result  # noqa: E402


def test_fill_maps_prompt_and_portrait_enum():
    schema = {"type": "object", "required": ["prompt"], "properties": {
        "prompt": {"type": "string"},
        "aspect_ratio": {"type": "string", "enum": ["square_1_1", "widescreen_16_9", "social_story_9_16"]},
        "num_images": {"type": "integer"},
        "negative_prompt": {"type": "string"},
        "model": {"type": "string"},
    }}
    args = _fill(schema, {"prompt": "a cat", "aspect_ratio": "9:16", "num_images": 1, "negative_prompt": "", "model": ""})
    assert args == {"prompt": "a cat", "aspect_ratio": "social_story_9_16", "num_images": 1}


def test_fill_nested_and_duration_enum():
    schema = {"type": "object", "properties": {
        "image": {"type": "string"},
        "prompt": {"type": "string"},
        "settings": {"type": "object", "properties": {"duration": {"type": "string", "enum": ["5", "10"]},
                                                      "ratio": {"type": "string", "enum": ["16:9", "9:16"]}}},
    }}
    args = _fill(schema, {"image_url": "https://x/y.png", "prompt": "move", "duration": 6, "aspect_ratio": "9:16"})
    assert args == {"image": "https://x/y.png", "prompt": "move", "settings": {"duration": "5", "ratio": "9:16"}}


def test_fill_skips_non_url_image():
    schema = {"type": "object", "properties": {"image_url": {"type": "string"}}}
    assert _fill(schema, {"image_url": "/local/file.png"}) == {}


def _res(content=None, structured=None, is_error=False):
    return SimpleNamespace(content=content or [], structured_content=structured, is_error=is_error)


def test_parse_structured_result():
    r = parse_result(_res(structured={"data": [{"id": "abc123", "status": "completed",
                                                "generated": [{"url": "https://cdn.magnific.com/a.png"}]}]}))
    assert r.url == "https://cdn.magnific.com/a.png"
    assert r.id == "abc123"
    assert r.status == "completed"


def test_parse_text_json_and_plain_urls():
    r = parse_result(_res(content=[SimpleNamespace(type="text", text='{"task_id": "t1", "status": "IN_PROGRESS"}')]))
    assert r.id == "t1" and r.status == "in_progress" and r.urls == []
    r = parse_result(_res(content=[SimpleNamespace(type="text", text="Done! https://files.magnific.com/v/1.mp4 enjoy")]))
    assert r.urls == ["https://files.magnific.com/v/1.mp4"]


def test_parse_resource_link():
    r = parse_result(_res(content=[SimpleNamespace(type="resource_link", uri="https://cdn/x.jpg")]))
    assert r.urls == ["https://cdn/x.jpg"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
