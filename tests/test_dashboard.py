"""Drive shipped Silvia dashboard entry and world-builder, not a copy."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from capture import capture_world, render_graphic_png  # noqa: E402
from layout import content_extent, kind_fill, layout_tree, siblings_overlap, tree_root, viewport_overflow  # noqa: E402
from live import load_probes  # noqa: E402
from trees import expand_tree, list_overflow, search_items, update_giant  # noqa: E402
from world import build_world, evolve, page_ids, page_view, switch_page  # noqa: E402

MAIN = HERE / "__main__.py"

SNAPSHOT = {
    "resources": [
        {
            "id": "cli.resource_list",
            "name": "resource_list.py",
            "category": "CLIs",
            "description": "catalog",
        },
        {
            "id": "skill.goal-split",
            "name": "goal-split",
            "category": "Skills",
            "description": "splitter",
        },
        {
            "id": "tool.grep",
            "name": "grep",
            "category": "Tools",
            "description": "search",
        },
        {
            "id": "mcp.mempalace",
            "name": "MemPalace HTTP MCP",
            "category": "MCPs",
            "description": "hub",
        },
        {
            "id": "memory.mempalace",
            "name": "MemPalace drawers",
            "category": "Memory",
            "description": "palace",
        },
        {
            "id": "cli.orchestrator",
            "name": "bounded orchestrator",
            "category": "CLIs",
            "description": "watchers",
        },
    ],
    "running": [
        {
            "id": "task.watch",
            "name": "Orchestrator watch",
            "description": "Live stack observer",
            "preview": "Live stack observer",
            "category": "orchestrator",
            "tags": ["running", "watch"],
            "nodes": [
                {"id": "observe", "name": "Observe", "kind": "process", "children": []},
                {"id": "correct", "name": "Correct", "kind": "process", "children": []},
            ],
        }
    ],
    "available": [
        {
            "id": "tree.idle-briefing",
            "name": "Briefing pack",
            "description": "Idle briefing workflow",
            "preview": "Idle briefing workflow",
            "category": "workflow",
            "tags": ["available", "idle"],
            "nodes": [{"id": "briefing", "name": "briefing", "kind": "capability", "children": []}],
        }
    ],
    "capabilities": ["wake", "hosting", "memory.remember"],
    "probes": {
        "mempalace.hub": {"ok": True, "url": "http://127.0.0.1:8765/healthz"},
        "grok.bot": {"ok": True},
        "pi.lan": {"ok": True, "url": "http://192.168.1.235:8870/"},
        "orchestrator": {"ok": True},
        "cli.money_loop": {"ok": True, "path": r"C:\Users\Irika\.grok\money-loop\__main__.py"},
        "cli.steam_lan": {"ok": True, "path": r"C:\Users\Irika\.grok\steam-lan-host-check\SteamLanHostCheck.ps1"},
        "app.silvia_android": {"ok": True, "path": r"C:\Users\Irika\.grok\silvia-android\__main__.py"},
        "cli.source_bus": {
            "ok": True,
            "open_count": 1,
            "open": [{"id": "evt-open-1", "correlation_id": "cid-open", "body": "open work", "to_agent": "operator"}],
        },
    },
}


def run_cli(args: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess:
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


def _not_redirect(text: str) -> None:
    low = text.lower()
    assert "location:" not in low
    assert "http-equiv" not in low
    assert "window.location" not in low
    assert "http-equiv refresh" not in low


def test_page_switch_covers_four_silvia_surfaces(tmp_path):
    ids = page_ids()
    assert "overview" in ids
    assert "butler-host" in ids
    assert "memory" in ids
    assert "catalog" in ids
    assert "orchestrator" in ids
    assert len(set(ids)) >= 4
    world = build_world(SNAPSHOT)
    for pid in ids:
        switched = switch_page(world, pid)
        assert switched["page"] == pid
        view = page_view(world, pid)
        assert view["page"] == pid
        assert view.get("view_ids") is not None
    pages = run_cli(["pages"])
    assert pages.returncode == 0, pages.stderr + pages.stdout
    body = json.loads(pages.stdout)
    _not_redirect(pages.stdout)
    assert set(body["page_ids"]) >= {
        "overview",
        "butler-host",
        "memory",
        "catalog",
        "orchestrator",
        "live-diagrams",
    }
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(SNAPSHOT), encoding="utf-8")
    switched = run_cli(["switch", "--page", "memory", "--snapshot", str(snap)])
    assert switched.returncode == 0, switched.stderr
    sw = json.loads(switched.stdout)
    assert sw["page"] == "memory"
    assert sw.get("redirect") is False


def test_load_probes_source_bus_has_open_task_requests():
    probes = load_probes()
    bus = probes.get("cli.source_bus") or {}
    assert "open_count" in bus, bus
    assert isinstance(bus.get("open"), list)
    assert Path(str(bus.get("path") or "")).is_file() or bus.get("ok") in (True, False)
    snap = {
        "resources": SNAPSHOT["resources"],
        "capabilities": SNAPSHOT["capabilities"],
        "probes": SNAPSHOT["probes"],
    }
    world = build_world(snap)
    assert "cli.source_bus" in set(world["entity_ids"])
    running_ids = {t.get("id") for t in (world.get("diagrams") or {}).get("running") or []}
    assert "task.source-bus" in running_ids


def test_load_probes_grok_bot_ok_follows_http_not_process():
    probes = load_probes()
    bot = probes.get("grok.bot") or {}
    http = bot.get("http") or {}
    http_ok = bool(http.get("ok"))
    assert bot.get("ok") is http_ok, bot
    assert "process" in bot
    if bot.get("process") and not http_ok:
        assert bot.get("ok") is False


def test_jointly_built_hosting_probes_in_giant_and_world():
    probes = load_probes()
    for pid in ("cli.money_loop", "cli.steam_lan", "app.silvia_android"):
        rec = probes[pid]
        assert rec.get("ok") is True, rec
        assert rec.get("path")
        assert Path(rec["path"]).is_file()
    bus = probes["cli.source_bus"]
    assert "open_count" in bus
    assert Path(str(bus.get("path") or "")).is_file()
    world = build_world(SNAPSHOT)
    ids = set(world["entity_ids"])
    assert "cli.money_loop" in ids
    assert "cli.steam_lan" in ids
    assert "app.silvia_android" in ids
    host = next(
        c
        for c in (world["diagrams"]["giant"].get("children") or [])
        if c.get("id") == "system.hosting"
    )
    host_ids = {c.get("id") for c in host.get("children") or []}
    assert {"cli.money_loop", "cli.steam_lan", "app.silvia_android", "cli.source_bus"} <= host_ids
    names = {c.get("id"): c.get("name") for c in host.get("children") or []}
    assert names["cli.money_loop"] == "Money loop"
    assert names["cli.steam_lan"] == "Steam LAN check"
    assert names["app.silvia_android"] == "Silvia Android"
    assert names["cli.source_bus"] == "Source bus"
    pages = run_cli(["pages"])
    assert pages.returncode == 0, pages.stderr + pages.stdout
    body = json.loads(pages.stdout)
    assert body.get("ok") is True
    assert "overview" in (body.get("page_ids") or [])


def test_world_binds_and_evolves_on_add_remove(tmp_path):
    world = build_world(SNAPSHOT)
    ids = set(world["entity_ids"])
    assert "wake" in ids
    assert "hosting" in ids
    assert "cli.resource_list" in ids
    assert "skill.goal-split" in ids
    assert "tool.grep" in ids
    assert "mcp.mempalace" in ids
    snap_path = tmp_path / "snap.json"
    snap_path.write_text(json.dumps(SNAPSHOT), encoding="utf-8")
    gone = evolve(SNAPSHOT, remove=["skill.goal-split", "wake"])
    gone_ids = set(gone["entity_ids"])
    assert "skill.goal-split" not in gone_ids
    assert "wake" not in gone_ids
    assert "tool.grep" in gone_ids
    added = evolve(
        SNAPSHOT,
        add=[{"id": "cli.dashboard-fixture", "name": "fixture", "category": "CLIs"}],
        remove=[],
    )
    assert "cli.dashboard-fixture" in set(added["entity_ids"])
    cli = run_cli(
        [
            "evolve",
            "--snapshot",
            str(snap_path),
            "--remove",
            "skill.goal-split",
            "--add-id",
            "cli.dashboard-fixture",
            "--add-name",
            "fixture",
            "--add-category",
            "CLIs",
        ]
    )
    assert cli.returncode == 0, cli.stderr + cli.stdout
    body = json.loads(cli.stdout)
    _not_redirect(cli.stdout)
    assert "skill.goal-split" not in set(body["entity_ids"])
    assert "cli.dashboard-fixture" in set(body["entity_ids"])
    assert "tool.grep" in set(body["entity_ids"])
    assert "wake" in set(body["entity_ids"])


def test_launch_dump_is_not_http_redirect_and_lists_pages_and_world(tmp_path):
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(SNAPSHOT), encoding="utf-8")
    result = run_cli(["launch", "--dump", "--snapshot", str(snap), "--page", "overview"])
    assert result.returncode == 0, result.stderr + result.stdout
    _not_redirect(result.stdout)
    body = json.loads(result.stdout)
    assert body.get("redirect") is False
    assert body.get("mode") == "dump"
    names = set(body.get("page_ids") or [])
    assert len(names) >= 4
    assert {"overview", "butler-host", "memory", "catalog", "orchestrator", "live-diagrams"} <= names
    ents = set(body.get("game_entity_ids") or body.get("entity_ids") or [])
    assert "cli.resource_list" in ents
    assert "skill.goal-split" in ents
    assert "tool.grep" in ents
    assert "wake" in ents
    dump = run_cli(["dump", "--snapshot", str(snap)])
    assert dump.returncode == 0, dump.stderr
    dumped = json.loads(dump.stdout)
    assert dumped.get("redirect") is False
    assert "window.location" not in dump.stdout


def test_overview_game_pieces_are_named(tmp_path):
    world = build_world(SNAPSHOT)
    by_id = {e["id"]: e for e in world["entities"]}
    for eid in ("wake", "cli.resource_list", "skill.goal-split", "tool.grep"):
        ent = by_id[eid]
        assert ent.get("name")
        assert ent["name"] != ""
        assert ent.get("role")
        assert eid in ent.get("name") or ent["name"][0].isalpha()
    gone = evolve(SNAPSHOT, remove=["skill.goal-split"])
    assert "skill.goal-split" not in set(gone["entity_ids"])
    added = evolve(SNAPSHOT, add=[{"id": "cli.named-piece", "name": "Named Piece", "category": "CLIs"}])
    piece = {e["id"]: e for e in added["entities"]}["cli.named-piece"]
    assert piece["name"] == "Named Piece"
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(SNAPSHOT), encoding="utf-8")
    dump = run_cli(["dump", "--snapshot", str(snap)])
    body = json.loads(dump.stdout)
    labels = {row["id"]: row for row in body.get("game_labels") or []}
    assert labels["wake"]["name"]
    assert labels["tool.grep"]["role"]


USAGE_SNAP = {
    **SNAPSHOT,
    "usage": {
        "ok": True,
        "subscription_tier": "SuperGrok Heavy",
        "credit_usage_percent": 38.0,
        "remaining_percent": 62.0,
        "period_start": "2026-08-28T23:06:18Z",
        "period_end": "2026-09-04T23:06:18Z",
        "fetched_at": "2026-09-04T20:48:21Z",
        "products": [
            {"id": "usage.chat", "label": "Chat", "percent": "12%", "known": True},
            {"id": "usage.voice", "label": "Voice", "percent": "5%", "known": True},
            {"id": "usage.bot", "label": "Bot", "percent": "8%", "known": True},
            {"id": "usage.imagine", "label": "Imagine", "percent": None, "known": False},
            {"id": "usage.build", "label": "Build", "percent": "13%", "known": True},
        ],
        "breakdown": [
            {"id": "usage.tier", "label": "Plan", "value": "SuperGrok Heavy"},
            {"id": "usage.week", "label": "This week", "value": "28 Aug 2026 – 04 Sep 2026"},
            {"id": "usage.starts", "label": "Week starts", "value": "28 Aug 2026"},
            {"id": "usage.resets", "label": "Resets", "value": "04 Sep 2026"},
            {"id": "usage.as_of", "label": "As of", "value": "04 Sep 2026"},
            {"id": "usage.used", "label": "Used this week", "value": "38%"},
            {"id": "usage.left", "label": "Left this week", "value": "62%"},
            {"id": "usage.chat", "label": "Chat", "value": "12%"},
            {"id": "usage.voice", "label": "Voice", "value": "5%"},
            {"id": "usage.bot", "label": "Bot", "value": "8%"},
            {"id": "usage.build", "label": "Build", "value": "13%"},
        ],
    },
}


def test_usage_page_has_supergrok_heavy_breakdown(tmp_path):
    from usage import load_latest_billing, parse_billing_event, ticks_to_usd

    line = {
        "ts": "2026-09-04T20:48:21.020Z",
        "msg": "billing: fetched credits config",
        "ver": "1.0.21",
        "ctx": {
            "subscriptionTier": "SuperGrok Heavy",
            "config": {
                "creditUsagePercent": 38.0,
                "currentPeriod": {
                    "type": "USAGE_PERIOD_TYPE_WEEKLY",
                    "start": "2026-08-28T23:06:18Z",
                    "end": "2026-09-04T23:06:18Z",
                },
                "onDemandCap": {"val": 0},
                "onDemandUsed": {"val": 2},
                "prepaidBalance": {"val": 0},
                "isUnifiedBillingUser": True,
            },
        },
    }
    parsed = parse_billing_event(line)
    assert parsed and parsed["subscription_tier"] == "SuperGrok Heavy"
    assert parsed["credit_usage_percent"] == 38.0
    assert parsed["remaining_percent"] == 62.0
    assert parsed["on_demand_used"] == 2
    from usage import parse_products

    split = parse_products({"productUsage": {"chat": 12, "voice": 5, "bot": 8, "build": 13}})
    by_id = {r["id"]: r for r in split}
    assert by_id["usage.chat"]["percent"] == "12%"
    assert by_id["usage.voice"]["percent"] == "5%"
    assert by_id["usage.bot"]["percent"] == "8%"
    assert by_id["usage.imagine"]["known"] is False
    log = tmp_path / "unified.jsonl"
    log.write_text(json.dumps(line) + "\n", encoding="utf-8")
    billed = load_latest_billing(log)
    assert billed["ok"] is True
    assert billed["subscription_tier"] == "SuperGrok Heavy"
    assert ticks_to_usd(111082539000) == 11.1082539

    world = build_world(USAGE_SNAP)
    assert "usage" in page_ids()
    view = page_view(world, "usage")
    assert view["page"] == "usage"
    assert view["usage_tier"] == "SuperGrok Heavy"
    assert view["usage_percent"] == 38.0
    assert view["usage_remaining"] == 62.0
    ids = view["view_ids"]
    assert "usage.used" in ids
    assert "usage.left" in ids
    assert "usage.starts" in ids
    assert "usage.resets" in ids
    assert "usage.as_of" in ids
    assert "usage.chat" in ids
    assert "usage.voice" in ids
    assert "usage.bot" in ids
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(USAGE_SNAP), encoding="utf-8")
    dump = run_cli(["dump", "--snapshot", str(snap), "--page", "usage"])
    assert dump.returncode == 0, dump.stderr + dump.stdout
    body = json.loads(dump.stdout)
    assert body["page"] == "usage"
    assert body["usage_tier"] == "SuperGrok Heavy"
    assert body["usage_percent"] == 38.0
    assert body["usage_remaining"] == 62.0
    blob = json.dumps(body)
    assert "Used this week" in blob
    assert "Left this week" in blob
    assert "Chat" in blob
    assert "Voice" in blob
    assert "Bot" in blob
    labels = {r.get("label"): r.get("value") for r in body.get("usage_breakdown") or []}
    assert str(labels.get("Used this week", "")).endswith("%")
    assert str(labels.get("Left this week", "")).endswith("%")
    assert labels.get("Used this week") == "38%"
    assert labels.get("Chat") == "12%"
    assert labels.get("Week starts") == "28 Aug 2026"
    assert labels.get("Resets") == "04 Sep 2026"
    assert labels.get("As of") == "04 Sep 2026"
    assert body.get("usage_week_label") == "28 Aug 2026 – 04 Sep 2026"


def test_list_overflow_depends_on_viewport():
    small = list_overflow(40, 80, 22)
    large = list_overflow(40, 4000, 22)
    assert small["scroll_needed"] is True
    assert small["overflow"] is True
    assert large["scroll_needed"] is False or large["hidden_rows"] < small["hidden_rows"]
    cli_s = run_cli(["overflow", "--count", "40", "--viewport", "80"])
    cli_l = run_cli(["overflow", "--count", "40", "--viewport", "4000"])
    assert json.loads(cli_s.stdout)["scroll_needed"] is True
    assert json.loads(cli_l.stdout)["scroll_needed"] is False


def test_live_diagrams_running_available_giant(tmp_path):
    world = build_world(SNAPSHOT)
    assert "live-diagrams" in page_ids()
    diagrams = world["diagrams"]
    assert set(diagrams["section_ids"]) == {"running", "available", "giant"}
    running = diagrams["running"]
    assert running
    assert running[0]["minimized"] is True
    assert running[0].get("preview") or running[0].get("description")
    popped = expand_tree(running[0])
    assert popped["minimized"] is False
    assert popped["popout"] is True
    assert len(popped["nodes"]) >= 1
    idle = diagrams["available"]
    assert idle
    hit = search_items(idle, query="briefing", category="workflow", tag="idle")
    assert hit and hit[0]["id"] == "tree.idle-briefing"
    giant = diagrams["giant"]
    assert giant["minimized"] is False
    assert giant.get("has_preview") is False
    assert "preview" not in giant or giant.get("preview") in (None, "")
    blob = json.dumps(giant)
    for token in ("cli.resource_list", "tool.grep", "skill.goal-split", "mcp.mempalace", "wake", "memory.mempalace"):
        assert token in blob
    edited = update_giant(giant, edit={"id": "cli.resource_list", "name": "Catalog CLI"})
    assert "Catalog CLI" in json.dumps(edited)
    removed = update_giant(edited, remove="tool.grep")
    assert "tool.grep" not in json.dumps(removed)
    added = update_giant(removed, add={"id": "cli.new-live", "name": "New Live", "parent": "giant.active"})
    assert "cli.new-live" in json.dumps(added)
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(SNAPSHOT), encoding="utf-8")
    dg = run_cli(["diagrams", "--snapshot", str(snap), "--section", "available", "--query", "briefing", "--tag", "idle"])
    body = json.loads(dg.stdout)
    assert body["section"] == "available"
    assert any(t.get("id") == "tree.idle-briefing" for t in body.get("available") or [])
    exp = run_cli(["diagrams", "--snapshot", str(snap), "--section", "running", "--expand", "task.watch"])
    exp_body = json.loads(exp.stdout)
    assert exp_body.get("expanded", {}).get("popout") is True
    assert exp_body["expanded"]["minimized"] is False
    dump = run_cli(["launch", "--dump", "--snapshot", str(snap), "--page", "live-diagrams"])
    dumped = json.loads(dump.stdout)
    assert "live-diagrams" in dumped["page_ids"]
    assert set(dumped["diagram_sections"]) >= {"running", "available", "giant"}
    assert dumped.get("running_expanded", {}).get("nodes")
    assert dumped.get("giant_minimized") is False


def test_graphical_tree_layout_boxes_edges_fills_no_sibling_overlap(tmp_path):
    world = build_world(SNAPSHOT)
    giant = world["diagrams"]["giant"]
    graphic = layout_tree(tree_root(giant))
    nodes = graphic["nodes"]
    edges = graphic["edges"]
    assert graphic.get("graphic") is True
    assert len(nodes) >= 2
    for box in nodes:
        assert box.get("name")
        assert isinstance(box.get("x"), int)
        assert isinstance(box.get("y"), int)
        assert box.get("w") > 0 and box.get("h") > 0
        assert box.get("fill")
    assert len(edges) >= 1
    parent_ids = {e["parent"] for e in edges}
    child_ids = {e["child"] for e in edges}
    box_ids = {b["id"] for b in nodes}
    assert parent_ids <= box_ids
    assert child_ids <= box_ids
    kinds = {b["kind"] for b in nodes}
    assert len(kinds) >= 2
    fills = {kind_fill(k) for k in kinds}
    assert len(fills) >= 2
    assert siblings_overlap(graphic) == []
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(SNAPSHOT), encoding="utf-8")
    dump = run_cli(["dump", "--snapshot", str(snap), "--page", "live-diagrams"])
    body = json.loads(dump.stdout)
    g = body.get("graphic") or {}
    assert g.get("graphic") is True
    assert len(g.get("nodes") or []) >= 2
    assert (g.get("nodes") or [])[0].get("name")
    assert g.get("edges")
    chips_dump = {(n.get("kind"), n.get("chip")) for n in g.get("nodes") or []}
    kind_to_chip = {}
    for kind, chip in chips_dump:
        kind_to_chip.setdefault(kind, chip)
    if len(kind_to_chip) >= 2:
        vals = list(kind_to_chip.values())
        assert vals[0] != vals[1]
    ly = run_cli(["layout", "--snapshot", str(snap), "--section", "giant"])
    laid = json.loads(ly.stdout)
    assert laid.get("graphic") is True
    assert laid.get("edges")
    running = world["diagrams"]["running"]
    rg = layout_tree(tree_root(expand_tree(running[0])))
    assert len(rg["nodes"]) >= 2
    assert rg["edges"]


def test_giant_extent_covers_every_box_and_two_axis_overflow(tmp_path):
    world = build_world(SNAPSHOT)
    graphic = layout_tree(tree_root(world["diagrams"]["giant"]))
    ext = content_extent(graphic)
    assert ext["content_width"] > 0 and ext["content_height"] > 0
    for box in graphic["nodes"]:
        assert box["x"] + box["w"] <= ext["content_width"]
        assert box["y"] + box["h"] <= ext["content_height"]
    small = viewport_overflow(graphic, min(80, ext["content_width"] - 1), min(80, ext["content_height"] - 1))
    large = viewport_overflow(graphic, ext["content_width"] + 500, ext["content_height"] + 500)
    assert small["h_scroll_needed"] is True
    assert small["v_scroll_needed"] is True
    assert large["h_scroll_needed"] is False
    assert large["v_scroll_needed"] is False
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(SNAPSHOT), encoding="utf-8")
    dump = run_cli(["dump", "--snapshot", str(snap), "--page", "live-diagrams"])
    body = json.loads(dump.stdout)
    g = body["graphic"]
    cw, ch = body["content_width"], body["content_height"]
    for box in g["nodes"]:
        assert box["x"] + box["w"] <= cw
        assert box["y"] + box["h"] <= ch
    assert body["overflow_2axis_small"]["h_scroll_needed"] is True
    assert body["overflow_2axis_small"]["v_scroll_needed"] is True
    assert g.get("edges")
    assert (g.get("nodes") or [])[0].get("name")
    assert (g.get("nodes") or [])[0].get("fill")


def test_screenshot_writes_real_png_twice(tmp_path):
    world = build_world(SNAPSHOT)
    p1 = tmp_path / "shot-1.png"
    p2 = tmp_path / "shot-2.png"
    r1 = capture_world(world, p1)
    r2 = render_graphic_png(layout_tree(tree_root(world["diagrams"]["giant"])), p2)
    for rec, path in ((r1, p1), (r2, p2)):
        assert rec["ok"] is True
        assert path.is_file()
        data = path.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(data) > 200
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(SNAPSHOT), encoding="utf-8")
    out = tmp_path / "cli.png"
    cli = run_cli(["screenshot", "--out", str(out), "--snapshot", str(snap)])
    assert cli.returncode == 0, cli.stderr + cli.stdout
    body = json.loads(cli.stdout)
    assert body["png"] is True
    assert out.read_bytes()[:4] == b"\x89PNG"


def test_create_no_window_hides_a_console_child():
    """The flag the dashboard passes must leave no visible console on this PC."""
    import ctypes
    from ctypes import wintypes

    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(3)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        user32 = ctypes.windll.user32
        found: list[str] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def _each(hwnd, _lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == proc.pid and user32.IsWindowVisible(hwnd):
                cls = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls, 256)
                found.append(cls.value)
            return True

        user32.EnumWindows(_each, 0)
        assert found == []
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_health_checks_spawn_without_a_console(monkeypatch, tmp_path):
    import live
    import usage
    from token_history import _fetch_grok_usage

    silvia = Path.home() / ".grok" / "silvia"
    if str(silvia) not in sys.path:
        sys.path.insert(0, str(silvia))
    import hosting

    seen: list[dict] = []

    def fake_check_output(args, **kwargs):
        seen.append(kwargs)
        return "Grok Bot.exe  1 Console  1  1 K\n"

    monkeypatch.setattr(live.subprocess, "check_output", fake_check_output)
    assert live._bot_running() is True
    monkeypatch.setattr(hosting.subprocess, "check_output", fake_check_output)
    assert hosting.grok_bot_process_running() is True
    assert all(call.get("creationflags") == subprocess.CREATE_NO_WINDOW for call in seen)

    class Done:
        returncode = 0
        stdout = '{"session": {}, "turns": []}'
        stderr = ""

    runs: list[dict] = []

    def fake_run(args, **kwargs):
        runs.append(kwargs)
        return Done()

    exe = tmp_path / "grok.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("SILVIA_GROK_EXE", str(exe))
    monkeypatch.setattr(usage.subprocess, "run", fake_run)
    assert usage.load_session_usage("abc").get("ok") is True
    import token_history

    monkeypatch.setattr(token_history.subprocess, "run", fake_run)
    assert _fetch_grok_usage("abc") is not None
    assert len(runs) == 2
    assert all(call.get("creationflags") == subprocess.CREATE_NO_WINDOW for call in runs)


def test_bot_probe_does_not_scan_the_process_twice(monkeypatch):
    import live

    silvia = Path.home() / ".grok" / "silvia"
    if str(silvia) not in sys.path:
        sys.path.insert(0, str(silvia))
    import hosting

    monkeypatch.setattr(hosting, "load_config", lambda: {})
    monkeypatch.setattr(hosting, "probe_grok_bot", lambda _cfg: {"ok": True, "process": True, "http": {"ok": True}})

    def second_scan():
        raise AssertionError("process was already known")

    monkeypatch.setattr(live, "_bot_running", second_scan)
    rec = live._grok_bot_probe()
    assert rec["process"] is True
    assert rec["ok"] is True


NOTES_COMMAND_PLAN = Path(r"C:\Users\Irika\.grok\notes\goaliosis-run-20261031T182912Z.md")


def command_pairs_from_notes(path: Path = NOTES_COMMAND_PLAN) -> list[tuple[str, str]]:
    """Read command/description pairs from the stage-1 plan. The test does not keep its own copy."""
    pairs: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("- "):
            continue
        name, description = line[2:].split(": ", 1)
        pairs.append((name, description))
    return pairs


def test_window_paints_notes_command_section():
    """Build the window the launch entry paints and read the command labels it shows."""
    from app import SilviaDashboard

    expected = command_pairs_from_notes()
    assert len(expected) == 13
    assert all(name and description for name, description in expected)
    world = build_world(
        {
            "resources": [{"id": "cli.example", "name": "Example", "category": "CLIs"}],
            "capabilities": [],
            "probes": {},
            "usage": {},
        }
    )
    app = SilviaDashboard(world)
    try:
        app.update_idletasks()
        app.update()
        assert str(app.title()) == "Silvia System — Dashboard"
        for child in app.body.pack_slaves():
            assert child.pack_info().get("side") != "right"
        assert not hasattr(app, "command_section")
        page_buttons = [btn.cget("text") for btn in app.nav_buttons.values()]
        assert page_buttons[:8] == [
            "Overview",
            "Butler & Hosting",
            "Memory",
            "Catalog",
            "Orchestrator",
            "SuperGrok Heavy",
            "Live diagrams",
            "Task view",
        ]
        assert page_buttons[-1] == "Commands"
        commands_btn = app.nav_buttons["commands"]
        assert commands_btn.cget("text") == "Commands"
        assert commands_btn.winfo_ismapped()
        assert commands_btn.winfo_viewable()
        assert commands_btn.winfo_rootx() < app.main.winfo_rootx()
        commands_btn.invoke()
        app.update_idletasks()
        app.update()
        assert app.world.get("page") == "commands"
        assert app.page_heading.cget("text") == "Commands"
        assert app.canvas.winfo_ismapped()
        assert app.canvas.winfo_viewable()
        assert app.canvas.winfo_rootx() >= app.main.winfo_rootx()
        painted: list[tuple[str, str]] = []
        for item in app.canvas.find_all():
            if app.canvas.type(item) != "text":
                continue
            text = app.canvas.itemcget(item, "text")
            bbox = app.canvas.bbox(item)
            assert bbox is not None
            assert bbox[2] > bbox[0]
            assert bbox[3] > bbox[1]
            name, description = text.split(": ", 1)
            painted.append((name, description))
        assert painted == expected
        app.nav_buttons["overview"].invoke()
        app.update()
        overview_text = [
            app.canvas.itemcget(item, "text")
            for item in app.canvas.find_all()
            if app.canvas.type(item) == "text"
        ]
        assert all(line != f"{name}: {description}" for name, description in expected for line in overview_text)
    finally:
        job = app._auto_refresh_after
        if job is not None:
            app.after_cancel(job)
            app._auto_refresh_after = None
        app.destroy()
