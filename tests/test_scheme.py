"""Dump/view paint tokens follow palette(scheme) in every area. No hex-table oracle."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from theme import geometry_key, paint_tokens  # noqa: E402

MAIN = HERE / "__main__.py"
LEFTOVERS = {"#f2efe6", "#d7d2c4", "#8a93a3", "#1a1e27", "#3a4150", "#111", "#6c757d", "#b7c0c9"}
TOKEN_KEYS = ("background", "chrome", "text", "accent", "outline", "edge", "card", "heading")


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


def _luma(hex_color: str) -> float:
    t = hex_color.lstrip("#")
    r, g, b = int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def _is_cyan(hex_color: str) -> bool:
    t = hex_color.lstrip("#")
    r, g, b = int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16)
    return b > r and g >= r


def test_default_dump_oled_cyan_tokens_match_palette_not_leftovers(tmp_path):
    snap = tmp_path / "s.json"
    snap.write_text("{}", encoding="utf-8")
    body = run_cli(["dump", "--snapshot", str(snap), "--page", "live-diagrams"])
    pal = paint_tokens("oled-cyan")
    assert body["layout_id"] == "live-diagrams-giant-tree"
    assert body["scheme"] == "oled-cyan"
    assert body.get("redirect") is False
    for key in TOKEN_KEYS:
        assert body[key] == pal[key], key
        assert str(body[key]).lower() not in LEFTOVERS
    graphic = body["graphic"]
    assert graphic["background"] == pal["background"]
    assert graphic["outline"] == pal["outline"]
    assert graphic["edge"] == pal["edge"]
    assert _luma(body["background"]) < 0.12
    assert _is_cyan(body["accent"])
    for box in graphic["nodes"]:
        assert box.get("interior_body") == pal["interior_body"]
        assert box.get("interior_header") == pal["interior_header"]
        assert box.get("interior_inset") == pal["interior_inset"]
    cream = run_cli(["dump", "--snapshot", str(snap), "--page", "live-diagrams", "--scheme", "cream-paper"])
    cream_pal = paint_tokens("cream-paper")
    assert cream["scheme"] == "cream-paper"
    assert cream["background"] == cream_pal["background"]
    assert cream["chrome"] == cream_pal["chrome"]
    assert cream["text"] == cream_pal["text"]
    assert cream["geometry_key"] == body["geometry_key"]
    overview = run_cli(["dump", "--snapshot", str(snap), "--layout-id", "overview-named-cards"])
    assert overview["scheme"] == "oled-cyan"
    assert overview["chrome"] == pal["chrome"]
    assert overview["text"] == pal["text"]
    assert overview["heading"] == pal["heading"]
