"""Three-tone interiors, purple active chrome, live graph feeds where applicable."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from capture import render_graphic_png, sample_box_corners  # noqa: E402
from theme import paint_tokens  # noqa: E402

MAIN = HERE / "__main__.py"


def run_cli(args: list[str], timeout: int = 60) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(HERE) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, str(MAIN), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        cwd=str(HERE),
        env=env,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    return json.loads(proc.stdout)


def _rgb(hex_color: str) -> tuple[int, int, int]:
    t = hex_color.lstrip("#")
    return int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16)


def _luma(hex_color: str) -> float:
    r, g, b = _rgb(hex_color)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def _is_cyan(hex_color: str) -> bool:
    r, g, b = _rgb(hex_color)
    return b > r + 30 and g > r + 10


def _is_purple(hex_color: str) -> bool:
    r, g, b = _rgb(hex_color)
    return r > g and b > g


def test_tree_items_have_three_tone_active_purple_and_feeds():
    body = run_cli(["dump", "--page", "live-diagrams"])
    pal = paint_tokens("oled-cyan")
    assert body["scheme"] == "oled-cyan"
    nodes = body["graphic"]["nodes"]
    assert nodes
    for n in nodes:
        h, b, i = n["interior_header"], n["interior_body"], n["interior_inset"]
        assert h != b != i
        assert h != i
        assert _luma(h) < _luma(i)
        assert not _is_cyan(h) and not _is_cyan(b) and not _is_cyan(i)
        assert h == pal["interior_header"]
        assert b == pal["interior_body"]
        assert i == pal["interior_inset"]
    actives = [n for n in nodes if n.get("active")]
    inactives = [n for n in nodes if not n.get("active")]
    assert actives and inactives
    for n in actives:
        assert _is_purple(n["border"])
        assert n["border"] == pal["active_border"]
        assert _is_purple(n["title_fill"])
        assert n["title_fill"] == pal["active_title"]
        assert _is_purple(n["title_text"])
        assert n["title_text"] == pal["active_title"]
        assert _luma(n["title_stroke"]) > 0.85
        assert n["title_stroke"] == pal["title_text"]
        assert len(n.get("feed") or []) >= 2
    for n in inactives:
        assert n["border"] == pal["outline"]
        assert not _is_purple(n["border"])
        assert not _is_purple(n["title_text"])
        assert n.get("feed") in ([], None)
    cream = run_cli(["dump", "--page", "live-diagrams", "--scheme", "cream-paper"])
    cream_pal = paint_tokens("cream-paper")
    assert cream["geometry_key"] == body["geometry_key"]
    cnode = cream["graphic"]["nodes"][0]
    assert cnode["interior_body"] == cream_pal["interior_body"]
    assert cnode["interior_body"] != pal["interior_body"]
    c_active = next(n for n in cream["graphic"]["nodes"] if n.get("active"))
    assert c_active["border"] == cream_pal["active_border"]
    assert c_active["border"] != pal["active_border"]
    assert c_active["title_text"] == cream_pal["active_title"]
    assert c_active["title_fill"] == cream_pal["active_title"]
    assert c_active["title_stroke"] == cream_pal["title_text"]


def _rgb_dist(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return (sum((x - y) ** 2 for x, y in zip(a, b))) ** 0.5


def test_rounded_corners_match_box_border_not_title_strip(tmp_path):
    body = run_cli(["dump", "--page", "live-diagrams", "--collapse", "system.catalog"])
    graphic = body["graphic"]
    png = tmp_path / "corners.png"
    max_side = max(int(graphic["content_width"]), int(graphic["content_height"]), 400)
    rec = render_graphic_png(graphic, png, max_side=max_side)
    assert rec["png"] is True
    active = next(n for n in graphic["nodes"] if n.get("active"))
    inactive = next(n for n in graphic["nodes"] if not n.get("active"))
    for box in (active, inactive):
        sampled = sample_box_corners(png, graphic, box)
        border = _rgb(box["border"])
        title = _rgb(box["title_fill"])
        body_c = _rgb(box["interior_body"])
        for sample in sampled["samples"]:
            rgb = tuple(sample["rgb"])
            assert _rgb_dist(rgb, border) < 80
            assert _rgb_dist(rgb, body_c) > 25
            if _rgb_dist(border, title) > 40:
                assert _rgb_dist(rgb, title) > 25
    app_src = (HERE / "app.py").read_text(encoding="utf-8")
    header_at = app_src.find("self._round_header(")
    stroke_at = app_src.find('self._round_rect(x, y, x + w, y + h, radius, "", border, width=3)')
    assert header_at != -1 and stroke_at != -1 and stroke_at > header_at
    cap_src = (HERE / "capture.py").read_text(encoding="utf-8")
    paste_at = cap_src.find("img.paste(header_layer")
    outline_at = cap_src.find("outline=border")
    assert paste_at != -1 and outline_at != -1 and outline_at > paste_at
