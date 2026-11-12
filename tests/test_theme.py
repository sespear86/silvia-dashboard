"""Drive shipped layout_id / scheme selection. No hardcoded palette oracle."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from layout import layout_tree, tree_root  # noqa: E402
from theme import (  # noqa: E402
    DEFAULT_LAYOUT_ID,
    DEFAULT_SCHEME,
    apply_selection,
    geometry_key,
    inventory_identities,
    palette,
    select,
)
from trees import diagrams_view  # noqa: E402
from world import build_world  # noqa: E402

MAIN = HERE / "__main__.py"
SNAP = {
    "resources": [
        {"id": "cli.resource_list", "name": "resource_list.py", "category": "CLIs"},
        {"id": "skill.goal-split", "name": "goal-split", "category": "Skills"},
        {"id": "tool.grep", "name": "grep", "category": "Tools"},
    ],
    "capabilities": ["wake", "hosting"],
    "probes": {
        "mempalace.hub": {"ok": True},
        "grok.bot": {"ok": True},
        "pi.lan": {"ok": True},
        "orchestrator": {"ok": True},
    },
}


def _rgb(hex_color: str) -> tuple[int, int, int]:
    text = hex_color.lstrip("#")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _luma(hex_color: str) -> float:
    r, g, b = _rgb(hex_color)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def _is_cyan_dominant(hex_color: str) -> bool:
    r, g, b = _rgb(hex_color)
    return b > r and g >= r


def run_cli(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(HERE) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
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


def test_default_pair_is_liked_oled_cyan_giant_tree():
    sel = select()
    assert sel["layout_id"] == DEFAULT_LAYOUT_ID == "live-diagrams-giant-tree"
    assert sel["scheme"] == DEFAULT_SCHEME == "oled-cyan"
    pal = palette(sel["scheme"])
    assert _luma(pal["background"]) < 0.12
    assert _is_cyan_dominant(pal["accent"])
    ids = inventory_identities()
    assert "live-diagrams-giant-tree" in ids["layout_ids"]
    assert "oled-cyan" in ids["schemes"]
    other_layouts = [x for x in ids["layout_ids"] if x != DEFAULT_LAYOUT_ID]
    other_schemes = [x for x in ids["schemes"] if x != DEFAULT_SCHEME and x in ("cream-paper", "parchment-bronze", "magenta-night", "arctic-white")]
    assert other_layouts
    assert other_schemes


def test_scheme_swap_keeps_geometry_layout_swap_keeps_scheme():
    world = build_world(SNAP)
    root = tree_root(world["diagrams"]["giant"])
    a = layout_tree(root, scheme="oled-cyan")
    b = layout_tree(root, scheme="cream-paper")
    assert geometry_key(a) == geometry_key(b)
    assert a["scheme"] == "oled-cyan"
    assert b["scheme"] == "cream-paper"
    assert a["background"] != b["background"]
    fills_a = {n["id"]: n["fill"] for n in a["nodes"]}
    fills_b = {n["id"]: n["fill"] for n in b["nodes"]}
    assert fills_a != fills_b
    same = select("overview-named-cards", "oled-cyan")
    assert same["scheme"] == "oled-cyan"
    assert same["layout_id"] == "overview-named-cards"
    assert same["layout_id"] != DEFAULT_LAYOUT_ID


def test_dump_reports_layout_and_scheme_and_cross_swap(tmp_path):
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(SNAP), encoding="utf-8")
    d1 = run_cli(["dump", "--snapshot", str(snap), "--page", "live-diagrams"])
    assert d1.returncode == 0, d1.stderr + d1.stdout
    body = json.loads(d1.stdout)
    assert body["layout_id"] == "live-diagrams-giant-tree"
    assert body["scheme"] == "oled-cyan"
    assert body.get("redirect") is False
    assert body["graphic"]["nodes"]
    pal = palette("oled-cyan")
    assert _luma(body["background"]) < 0.12
    assert _is_cyan_dominant(body["accent"])
    assert body["graphic"]["background"] == pal["background"]
    alt_scheme = run_cli(
        ["dump", "--snapshot", str(snap), "--page", "live-diagrams", "--scheme", "cream-paper"]
    )
    other = json.loads(alt_scheme.stdout)
    assert other["scheme"] == "cream-paper"
    assert other["layout_id"] == "live-diagrams-giant-tree"
    assert other["geometry_key"] == body["geometry_key"]
    assert other["graphic"]["background"] != body["graphic"]["background"]
    alt_layout = run_cli(
        ["dump", "--snapshot", str(snap), "--layout-id", "overview-named-cards", "--scheme", "oled-cyan"]
    )
    lay = json.loads(alt_layout.stdout)
    assert lay["scheme"] == "oled-cyan"
    assert lay["layout_id"] == "overview-named-cards"


def test_diagrams_view_and_chrome_follow_applied_scheme_not_default():
    world = build_world(SNAP)
    world, sel = apply_selection(world, DEFAULT_LAYOUT_ID, "cream-paper")
    assert sel["scheme"] == "cream-paper"
    assert world["scheme"] == "cream-paper"
    assert world["diagrams"]["scheme"] == "cream-paper"
    shown = diagrams_view(world["diagrams"], section="giant", scheme=world["scheme"])
    graphic = shown["graphic"]
    pal = palette("cream-paper")
    default_pal = palette("oled-cyan")
    assert graphic["scheme"] == "cream-paper"
    assert graphic["background"] == pal["background"]
    assert graphic["background"] != default_pal["background"]
    assert graphic["accent"] == pal["accent"]
    interiors = {n.get("interior_body") for n in graphic["nodes"]}
    assert pal["interior_body"] in interiors
    assert default_pal["interior_body"] not in interiors
    chips = {n.get("chip") for n in graphic["nodes"]}
    assert pal["fills"]["system"] in chips or pal["accent"] in chips
    chrome = palette(world["scheme"])
    assert chrome["background"] == pal["background"]
    assert chrome["chrome"] == pal["chrome"]
    assert chrome["text"] == pal["text"]
    baseline = build_world(SNAP)
    default_shown = diagrams_view(baseline["diagrams"], section="giant")
    assert default_shown["graphic"]["scheme"] == "oled-cyan"
    assert geometry_key(graphic) == geometry_key(default_shown["graphic"])
