"""Drive shipped LTR layout, collapse, rounded boxes, and curved edges."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from layout import is_curved_edge, layout_tree, parents_left_of_children, tree_root  # noqa: E402
from theme import geometry_key, palette  # noqa: E402
from trees import diagrams_view  # noqa: E402
from world import build_world  # noqa: E402

MAIN = HERE / "__main__.py"
SNAP = {
    "resources": [
        {"id": "cli.resource_list", "name": "resource_list.py", "category": "CLIs"},
        {"id": "skill.goal-split", "name": "goal-split", "category": "Skills"},
        {"id": "tool.grep", "name": "grep", "category": "Tools"},
        {"id": "mcp.mempalace", "name": "MemPalace", "category": "MCPs"},
    ],
    "capabilities": ["wake", "hosting"],
    "probes": {
        "mempalace.hub": {"ok": True},
        "grok.bot": {"ok": True},
        "pi.lan": {"ok": True},
        "orchestrator": {"ok": True},
    },
}


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


def test_ltr_collapse_radius_curves_and_scheme(tmp_path):
    world = build_world(SNAP)
    root = tree_root(world["diagrams"]["giant"])
    full = layout_tree(root, scheme="oled-cyan")
    assert parents_left_of_children(full) is True
    assert full.get("radius", 0) > 0
    assert all(int(n.get("radius") or 0) > 0 for n in full["nodes"])
    assert full.get("edges")
    assert all(is_curved_edge(e) for e in full["edges"])
    collapsible = full.get("collapsible_ids") or []
    assert collapsible
    branch = next(cid for cid in collapsible if cid != full["nodes"][0]["id"])
    collapsed = layout_tree(root, scheme="oled-cyan", collapsed=[branch])
    assert branch in (collapsed.get("collapsed_ids") or [])
    assert len(collapsed["nodes"]) < len(full["nodes"])
    assert collapsed["content_width"] <= full["content_width"]
    remaining = {n["id"] for n in collapsed["nodes"]}
    assert branch in remaining
    cream = layout_tree(root, scheme="cream-paper")
    assert geometry_key(full) == geometry_key(cream)
    assert cream["background"] != full["background"]
    assert all(int(n.get("radius") or 0) > 0 for n in cream["nodes"])
    assert all(is_curved_edge(e) for e in cream["edges"])
    shown = diagrams_view(world["diagrams"], section="giant", scheme="oled-cyan", collapsed=[branch])
    assert len(shown["graphic"]["nodes"]) == len(collapsed["nodes"])
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(SNAP), encoding="utf-8")
    dump = run_cli(["dump", "--snapshot", str(snap), "--page", "live-diagrams"])
    body = json.loads(dump.stdout)
    assert body["ltr"] is True
    assert body["radius"] > 0
    assert body["curved_edges"] is True
    assert body["collapsible_ids"]
    assert body["scheme"] == "oled-cyan"
    col = run_cli(
        ["dump", "--snapshot", str(snap), "--page", "live-diagrams", "--collapse", branch]
    )
    folded = json.loads(col.stdout)
    assert len(folded["graphic"]["nodes"]) < len(body["graphic"]["nodes"])
    assert folded["content_width"] <= body["content_width"]
    assert branch in folded["collapsed_ids"]
