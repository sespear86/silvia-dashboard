"""Rebuild checks against the shipped dashboard, not a copy of it."""
from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import os
import subprocess
import sys
import textwrap
import time
from argparse import Namespace
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from app import AUTO_REFRESH_MS, SilviaDashboard  # noqa: E402
from capture import render_systems_png  # noqa: E402
from live import live_snapshot, load_probes  # noqa: E402
from systems import INVENTORY, open_system, overview_systems, presence_value  # noqa: E402
from theme import DEFAULT_LAYOUT_ID  # noqa: E402
from world import build_world, page_list, page_view, select_entity, switch_page  # noqa: E402

MAIN = HERE / "__main__.py"
USAGE_NOTE = "SuperGrok Heavy weekly usage, not disk presence"


def _cli_module():
    spec = importlib.util.spec_from_file_location("silvia_dashboard_cli", MAIN)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_cli(args: list[str], *, timeout: int = 90) -> subprocess.CompletedProcess:
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


def _ns(**overrides) -> Namespace:
    base = dict(
        snapshot="",
        inventory="",
        page="",
        layout_id=DEFAULT_LAYOUT_ID,
        scheme="oled-cyan",
        collapse=[],
    )
    base.update(overrides)
    return Namespace(**base)


def _boom(*_a, **_k):
    raise AssertionError("overview path called a skipped probe")


def test_overview_probe_path_does_not_call_hub_bot_or_bus(monkeypatch):
    import live

    monkeypatch.setattr(live, "_http", _boom)
    monkeypatch.setattr(live, "_grok_bot_probe", _boom)
    monkeypatch.setattr(live, "load_source_bus", _boom)
    probes = load_probes(http=False)
    for key in ("mempalace.hub", "grok.bot", "pi.lan", "cli.source_bus"):
        row = probes[key]
        assert row.get("ok") is None
        assert row.get("ok") is not True
        assert row.get("skipped") is True
    assert probes["orchestrator"]["ok"] in (True, False)
    snap = live_snapshot(http=False)
    for key in ("mempalace.hub", "grok.bot", "pi.lan"):
        assert snap["probes"][key]["ok"] is None
        assert snap["probes"][key]["ok"] is not True


def test_unskipped_probe_path_still_calls_hub_bot_and_bus(monkeypatch):
    import live

    called = {"http": 0, "bot": 0, "bus": 0}

    def http(url, timeout=4):
        called["http"] += 1
        return {"ok": False, "url": url, "status": 0, "body": "stub"}

    def bot():
        called["bot"] += 1
        return {"ok": False, "http": {"ok": False}, "process": False}

    def bus():
        called["bus"] += 1
        return {"ok": False, "open_count": 0, "open": [], "path": str(HERE)}

    monkeypatch.setattr(live, "_http", http)
    monkeypatch.setattr(live, "_grok_bot_probe", bot)
    monkeypatch.setattr(live, "load_source_bus", bus)
    probes = load_probes()
    assert called["http"] == 4
    assert called["bot"] == 1
    assert called["bus"] == 1
    assert probes["grok.bot"]["ok"] is False
    assert probes["mempalace.hub"]["ok"] is False
    assert probes["pi.lan"]["ok"] is False


def test_bare_dump_payload_skips_health_and_selects_overview(monkeypatch):
    import live

    monkeypatch.setattr(live, "_http", _boom)
    monkeypatch.setattr(live, "_grok_bot_probe", _boom)
    monkeypatch.setattr(live, "load_source_bus", _boom)
    body = _cli_module().dump_payload(_ns())
    assert body["ok"] is True
    assert body["redirect"] is False
    assert body["page"] == "overview"
    assert body["layout_id"] == DEFAULT_LAYOUT_ID == "live-diagrams-giant-tree"
    assert [row["id"] for row in body["systems"]] == [row["id"] for row in INVENTORY]
    for shipped, row in zip(INVENTORY, body["systems"]):
        assert row["path"] == shipped["path"]
        assert row["presence"] == presence_value(shipped["path"])
        assert row["presence"] is True or row["presence"] == "absent"


def test_non_overview_dump_still_runs_health_helpers(monkeypatch):
    import live

    called = {"http": 0, "bot": 0, "bus": 0}

    def http(url, timeout=4):
        called["http"] += 1
        return {"ok": False, "url": url, "status": 0, "body": "stub"}

    def bot():
        called["bot"] += 1
        return {"ok": False, "http": {"ok": False}, "process": False}

    def bus():
        called["bus"] += 1
        return {"ok": True, "open_count": 0, "open": [], "path": str(HERE / "__main__.py")}

    monkeypatch.setattr(live, "_http", http)
    monkeypatch.setattr(live, "_grok_bot_probe", bot)
    monkeypatch.setattr(live, "load_source_bus", bus)
    body = _cli_module().dump_payload(_ns(page="butler-host"))
    assert called == {"http": 4, "bot": 1, "bus": 1}
    assert body["page"] == "butler-host"
    health = {row["id"]: row for row in body["health"]}
    assert health["mempalace.hub"]["ok"] is False
    assert health["grok.bot"]["ok"] is False
    assert health["pi.lan"]["ok"] is False


def test_launch_dump_without_page_is_overview_and_live_diagrams_keep_sections(tmp_path):
    snap = tmp_path / "snap.json"
    snap.write_text(
        json.dumps(
            {
                "resources": [{"id": "cli.example", "name": "Example", "category": "CLIs"}],
                "capabilities": ["wake"],
                "probes": {"orchestrator": {"ok": False, "path": r"C:\Users\Irika\.grok\orchestrator\__main__.py"}},
                "running": [],
                "available": [],
                "usage": {"subscription_tier": "SuperGrok Heavy", "credit_usage_percent": 12},
            }
        ),
        encoding="utf-8",
    )
    bare = run_cli(["launch", "--dump", "--snapshot", str(snap)])
    assert bare.returncode == 0, bare.stderr + bare.stdout
    body = json.loads(bare.stdout)
    assert body["page"] == "overview"
    assert body["redirect"] is False
    assert body["layout_id"] == "live-diagrams-giant-tree"
    live = run_cli(["dump", "--snapshot", str(snap), "--page", "live-diagrams"])
    assert live.returncode == 0, live.stderr + live.stdout
    live_body = json.loads(live.stdout)
    assert live_body["page"] == "live-diagrams"
    assert set(live_body["diagram_sections"]) >= {"running", "available", "giant"}


def test_overview_model_and_drawing_are_two_surfaces():
    world = build_world({"resources": [{"id": "cli.example", "name": "Example", "category": "CLIs"}], "capabilities": ["wake"]})
    view = page_view(world, "overview")
    assert view["system_ids"] == [row["id"] for row in INVENTORY]
    assert view["systems"] is not view["view_entities"]
    assert [row["id"] for row in view["systems"]] == view["system_ids"]
    assert "cli.example" in view["view_ids"]
    assert "resource-list" not in view["view_ids"]
    src = textwrap.dedent(inspect.getsource(SilviaDashboard._draw_named_game))
    tree = ast.parse(src)
    counts = {"Canvas": 0, "Scrollbar": 0, "PanedWindow": 0}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in counts:
                counts[node.func.attr] += 1
    assert counts["Canvas"] >= 2
    assert counts["Scrollbar"] >= 2
    assert counts["PanedWindow"] >= 1


def test_butler_and_voice_health_stay_off_path_presence():
    from live import load_probes

    probes = load_probes(http=False)
    assert probes["pi.lan"]["url"] == "http://192.168.1.235:8870/"
    assert probes["pi.lan"]["label"] == "Source presence"
    assert probes["silvia.butler"]["url"] == "http://192.168.1.235:8880/healthz"
    assert probes["silvia.voice"]["url"] == "http://192.168.1.235:8000/api/health"
    assert len({probes["pi.lan"]["url"], probes["silvia.butler"]["url"], probes["silvia.voice"]["url"]}) == 3
    assert probes["pi.lan"]["skipped"] is True
    mem = next(row for row in INVENTORY if row["id"] == "mempalace")
    assert presence_value(mem["path"]) != probes["silvia.butler"]["ok"]


def test_health_is_separate_from_path_presence_and_pages_keep_systems():
    mem_spec = next(row for row in INVENTORY if row["id"] == "mempalace")
    orch_spec = next(row for row in INVENTORY if row["id"] == "orchestrator")
    missing = open_system("silvia", path=r"C:\Users\Irika\.grok\silvia-dashboard\no-such-rebuild-path")
    assert missing["presence"] == "absent"
    assert "presence: absent" in missing["body"]
    world = build_world(
        {
            "resources": [
                {"id": "cli.example", "name": "Example", "category": "CLIs", "description": "row"},
                {"id": "memory.mempalace", "name": "MemPalace drawers", "category": "Memory"},
            ],
            "capabilities": [],
            "probes": {
                "mempalace.hub": {"ok": False, "url": "http://127.0.0.1:8765/healthz"},
                "grok.bot": {"ok": None, "skipped": True},
                "pi.lan": {"ok": None, "skipped": True, "url": "http://192.168.1.235:8870/"},
                "orchestrator": {"ok": False, "path": orch_spec["path"] + r"\__main__.py"},
            },
            "usage": {"subscription_tier": "SuperGrok Heavy", "credit_usage_percent": 12, "remaining_percent": 88},
        }
    )
    host = page_view(world, "butler-host")
    health = {row["id"]: row for row in host["health"]}
    assert health["mempalace.hub"]["ok"] is False
    assert health["grok.bot"]["ok"] is None
    assert health["grok.bot"]["ok"] is not True
    assert health["pi.lan"]["ok"] is not True
    memory = page_view(world, "memory")
    assert memory["system"]["id"] == "mempalace"
    assert memory["system"]["presence"] == presence_value(mem_spec["path"])
    assert memory["system"]["presence"] != health["mempalace.hub"]["ok"] or memory["system"]["presence"] is True
    catalog = page_view(world, "catalog")
    assert all(ent.get("kind") == "resource" for ent in catalog["view_entities"])
    assert catalog["system"]["id"] == "resource-list"
    assert "resource-list" not in catalog["view_ids"]
    orch = page_view(world, "orchestrator")
    assert orch["system"]["id"] == "orchestrator"
    assert orch["system"]["title"] == "Orchestrator"
    assert orch["system"]["path"] == orch_spec["path"]
    assert "orchestrator" in orch["system"]["purpose"]
    assert orch["system"]["presence"] == presence_value(orch_spec["path"])
    probe = next(ent for ent in orch["view_entities"] if ent["id"] == "probe.orchestrator")
    assert probe["ok"] is False
    assert orch["system"]["presence"] != probe["ok"]
    selected = select_entity(world, "probe.orchestrator")["selected"]
    assert selected["id"] == "probe.orchestrator"
    assert selected["kind"] == "probe"
    assert selected["ok"] is False
    system = select_entity(world, "orchestrator")["selected"]
    assert system["title"] == "Orchestrator"
    assert system["presence"] == presence_value(orch_spec["path"])
    usage = page_view(world, "usage")
    assert usage["usage_tier"] == "SuperGrok Heavy"
    assert usage["usage_percent"] == 12
    assert usage["usage_note"] == USAGE_NOTE


def test_inspect_system_and_probe_stay_distinct(tmp_path):
    orch_spec = next(row for row in INVENTORY if row["id"] == "orchestrator")
    silvia_spec = next(row for row in INVENTORY if row["id"] == "silvia")
    snap = tmp_path / "snap.json"
    snap.write_text(
        json.dumps({"probes": {"orchestrator": {"ok": False, "path": orch_spec["path"]}}, "resources": [], "capabilities": []}),
        encoding="utf-8",
    )
    silvia = run_cli(["inspect", "--id", "silvia"])
    assert silvia.returncode == 0, silvia.stderr + silvia.stdout
    body = json.loads(silvia.stdout)
    assert body["title"] == "Silvia"
    assert body["path"] == silvia_spec["path"]
    assert body["presence"] == presence_value(silvia_spec["path"])
    assert "butler" in body["purpose"]
    system = run_cli(["inspect", "--id", "orchestrator"])
    assert system.returncode == 0, system.stderr + system.stdout
    sys_body = json.loads(system.stdout)
    assert sys_body["title"] == "Orchestrator"
    assert sys_body["path"] == orch_spec["path"]
    assert "orchestrator" in sys_body["purpose"]
    assert sys_body["presence"] == presence_value(orch_spec["path"])
    probe = run_cli(["inspect", "--id", "probe.orchestrator", "--snapshot", str(snap)])
    assert probe.returncode == 0, probe.stderr + probe.stdout
    probe_body = json.loads(probe.stdout)
    selected = probe_body["selected"]
    assert selected["id"] == "probe.orchestrator"
    assert selected["kind"] == "probe"
    assert selected["ok"] is False
    assert sys_body["presence"] != selected["ok"]


def test_usage_dump_contains_note_and_screenshot_splits(tmp_path):
    snap = tmp_path / "snap.json"
    snap.write_text(
        json.dumps(
            {
                "resources": [],
                "capabilities": [],
                "probes": {},
                "usage": {"subscription_tier": "SuperGrok Heavy", "credit_usage_percent": 41, "remaining_percent": 59},
            }
        ),
        encoding="utf-8",
    )
    usage = run_cli(["dump", "--snapshot", str(snap), "--page", "usage"])
    assert usage.returncode == 0, usage.stderr + usage.stdout
    body = json.loads(usage.stdout)
    assert body["usage_tier"] == "SuperGrok Heavy"
    assert body["usage_percent"] == 41
    assert USAGE_NOTE in json.dumps(body)
    titles = [page["title"] for page in page_list()]
    assert titles == [
        "Overview",
        "Butler & Hosting",
        "Memory",
        "Catalog",
        "Orchestrator",
        "SuperGrok Heavy",
        "Live diagrams",
        "Task view",
        "Sessions",
        "Commands",
    ]
    overview_png = tmp_path / "overview.png"
    shot = render_systems_png(overview_systems(), overview_png)
    names = [row["name"] for row in INVENTORY]
    assert shot["labels"] == names
    for name in names:
        assert name in shot["labels"]
    assert overview_png.stat().st_size > 0
    assert shot["png"] is True
    cli_png = tmp_path / "cli-overview.png"
    cli = run_cli(["screenshot", "--out", str(cli_png), "--snapshot", str(snap)])
    assert cli.returncode == 0, cli.stderr + cli.stdout
    cli_body = json.loads(cli.stdout)
    for name in names:
        assert name in cli_body["labels"]
    assert cli_png.stat().st_size > 0
    assert cli_png.read_bytes()[:4] == b"\x89PNG"
    live_png = tmp_path / "live.png"
    live = run_cli(["screenshot", "--page", "live-diagrams", "--out", str(live_png), "--snapshot", str(snap)])
    assert live.returncode == 0, live.stderr + live.stdout
    live_body = json.loads(live.stdout)
    assert live_body["graphic"] is True
    assert live_png.stat().st_size > 0


def test_skipped_health_is_not_present_on_the_host_page(monkeypatch):
    import live

    monkeypatch.setattr(live, "_http", _boom)
    monkeypatch.setattr(live, "_grok_bot_probe", _boom)
    monkeypatch.setattr(live, "load_source_bus", _boom)
    probes = load_probes(http=False)
    world = build_world({"resources": [], "capabilities": [], "probes": probes})
    host = page_view(world, "butler-host")
    for key in ("mempalace.hub", "grok.bot", "pi.lan"):
        row = next(item for item in host["health"] if item["id"] == key)
        assert row["ok"] is None
        assert row["ok"] is not True
        assert row.get("skipped") is True


def _wait_pending(app: SilviaDashboard) -> None:
    for _ in range(50):
        if app._pending is not None or not app._refresh_busy:
            if app._pending is not None:
                return
        time.sleep(0.02)
    assert app._pending is not None


def test_overview_refresh_world_skips_health_helpers(monkeypatch):
    import live

    monkeypatch.setattr(live, "_http", _boom)
    monkeypatch.setattr(live, "_grok_bot_probe", _boom)
    monkeypatch.setattr(live, "load_source_bus", _boom)
    world = _cli_module().refresh_world(_ns(), "overview")
    for key in ("mempalace.hub", "grok.bot", "pi.lan", "cli.source_bus"):
        row = world["probes"][key]
        assert row["ok"] is None
        assert row.get("skipped") is True
    assert world["probes"]["orchestrator"]["ok"] in (True, False)


def test_health_page_refresh_world_runs_helpers(monkeypatch):
    import live

    called = {"http": 0, "bot": 0, "bus": 0}

    def http(url, timeout=4):
        called["http"] += 1
        return {"ok": False, "url": url, "status": 0, "body": "stub"}

    def bot():
        called["bot"] += 1
        return {"ok": False, "http": {"ok": False}, "process": False}

    def bus():
        called["bus"] += 1
        return {"ok": False, "open_count": 0, "open": [], "path": str(HERE)}

    monkeypatch.setattr(live, "_http", http)
    monkeypatch.setattr(live, "_grok_bot_probe", bot)
    monkeypatch.setattr(live, "load_source_bus", bus)
    world = _cli_module().refresh_world(_ns(), "butler-host")
    assert called == {"http": 4, "bot": 1, "bus": 1}
    assert world["probes"]["mempalace.hub"]["ok"] is False


def test_open_window_timer_reloads_catalog_and_keeps_overview_health():
    assert AUTO_REFRESH_MS == 3000
    base = {
        "resources": [{"id": "cli.example", "name": "Example", "category": "CLIs"}],
        "capabilities": ["wake"],
        "probes": {"mempalace.hub": {"ok": True, "url": "http://127.0.0.1:8765/healthz"}},
        "usage": {"credit_usage_percent": 12, "remaining_percent": 88, "subscription_tier": "SuperGrok Heavy"},
    }
    calls: list[str] = []

    def on_refresh(page: str = "overview") -> dict:
        calls.append(page)
        renamed = dict(base)
        renamed["resources"] = [{"id": "cli.example", "name": "Example renamed", "category": "CLIs"}]
        renamed["probes"] = {"mempalace.hub": {"ok": None, "skipped": True, "url": "http://127.0.0.1:8765/healthz"}}
        return build_world(renamed)

    app = SilviaDashboard(build_world(base), on_refresh=on_refresh)
    try:
        app.withdraw()
        assert app._auto_refresh_after is not None
        app.after_cancel(app._auto_refresh_after)
        app._auto_refresh_after = None
        app._start_refresh_read()
        _wait_pending(app)
        assert calls == ["overview"]
        app._apply_pending()
        names = [ent.get("name") for ent in app.world["entities"] if ent.get("id") == "cli.example"]
        assert names == ["Example renamed"]
        hub = next(ent for ent in app.world["entities"] if ent.get("id") == "mempalace.hub")
        assert hub.get("ok") is True
        assert app.world["probes"]["mempalace.hub"]["ok"] is True
        app.page_heading.configure(text="SENTINEL")
        app._start_refresh_read()
        _wait_pending(app)
        app._apply_pending()
        assert app.page_heading.cget("text") == "SENTINEL"
        app._systems_mtime = 0
        app._reload_systems()
        import world as world_mod

        assert len(world_mod.overview_systems()) == 24
        assert world_mod.overview_systems()[0]["id"] == "silvia"
    finally:
        app.destroy()


def _quiet_dashboard(world: dict) -> SilviaDashboard:
    app = SilviaDashboard(world)
    app.withdraw()
    job = app._auto_refresh_after
    if job is not None:
        app.after_cancel(job)
        app._auto_refresh_after = None
    return app


def test_find_reports_count_and_scrolls_first_match_into_view():
    resources = [{"id": f"mcp.pad.{i:03d}", "name": f"Pad {i:03d}", "category": "MCPs"} for i in range(40)]
    resources.append({"id": "mcp.alpha-needle", "name": "Alpha Needle", "category": "MCPs"})
    resources.append({"id": "mcp.beta-needle", "name": "Beta Needle", "category": "MCPs"})
    resources += [{"id": f"mcp.tail.{i:03d}", "name": f"Tail {i:03d}", "category": "MCPs"} for i in range(30)]
    resources.append({"id": "mcp.zz-find-late", "name": "Zz Find Late", "category": "MCPs"})
    world = build_world(
        {
            "resources": resources,
            "capabilities": [],
            "probes": {},
            "usage": {
                "subscription_tier": "SuperGrok Heavy",
                "credit_usage_percent": 10,
                "remaining_percent": 90,
                "products": [
                    {"id": "usage.chat", "label": "Chat", "percent": 4, "known": True},
                    {"id": "usage.imagine", "label": "Imagine", "percent": 6, "known": True},
                ],
            },
        }
    )
    app = _quiet_dashboard(world)
    try:
        app.game_canvas.configure(width=900, height=180)
        app.update()
        assert "on disk" in app.page_sub.cget("text")
        assert app.search_count.cget("text") == ""

        app.search_var.set("needle")
        app.update()
        assert app.search_count.cget("text") == "2 matches"
        assert "on disk" in app.page_sub.cget("text")
        assert "match" not in app.page_sub.cget("text")

        app.search_var.set("alpha needle")
        app.update()
        assert app.search_count.cget("text") == "1 match"

        app.search_var.set("not-a-real-name")
        app.update()
        assert app.search_count.cget("text") == "No matches"

        app.search_var.set("")
        app.update()
        assert app.search_count.cget("text") == ""

        app.game_canvas.yview_moveto(1)
        app.update()
        bottom = float(app.game_canvas.yview()[0])
        assert bottom > 0.5
        app.search_var.set("zz find late")
        app.update()
        assert app.search_count.cget("text") == "1 match"
        assert app._find_targets
        assert app._find_targets[0][0] is app.game_canvas
        assert int(app._find_targets[0][1]) < 90
        assert float(app.game_canvas.yview()[0]) < bottom

        app.search_var.set("pad")
        app.update()
        assert app.search_count.cget("text") == "40 matches"
        app.game_canvas.yview_moveto(1)
        app.update()
        held = float(app.game_canvas.yview()[0])
        assert held > 0.5
        app.render()
        app.update()
        assert abs(float(app.game_canvas.yview()[0]) - held) < 0.08

        app.world = switch_page(app.world, "catalog")
        app.search_var.set("needle")
        app.update()
        assert app.search_count.cget("text") == "2 matches"

        app.world = switch_page(app.world, "usage")
        app.render()
        app.search_var.set("imagine")
        app.update()
        assert app.search_count.cget("text") == "1 match"
        assert app.page_sub.cget("text") == USAGE_NOTE
        app.search_var.set("weekly")
        app.update()
        assert app.search_count.cget("text") == "No matches"
        app.search_var.set("heavy")
        app.update()
        assert app.search_count.cget("text") == "1 match"

        app.world = switch_page(app.world, "live-diagrams")
        app.diagram_section = "giant"
        app.search_var.set("zz find late")
        app.update()
        assert app.search_count.cget("text") == "1 match"
        assert len(app.hits) > 1

        app.diagram_section = "available"
        app.render()
        app.update()
        assert app.search_count.cget("text") == "1 match"
    finally:
        app.destroy()


def test_find_selects_first_match_into_the_detail():
    world = build_world(
        {
            "resources": [
                {"id": "mcp.alpha-needle", "name": "Alpha Needle", "category": "MCPs"},
                {"id": "mcp.beta-needle", "name": "Beta Needle", "category": "MCPs"},
            ],
            "capabilities": [],
            "probes": {},
        }
    )
    app = _quiet_dashboard(world)
    try:
        app.search_var.set("resource catalog")
        app.update()
        detail = app.detail.get("1.0", "end-1c")
        assert app.selected_id == "resource-list"
        assert "Resource catalog" in detail
        assert r"C:\Users\Irika\.grok\resource-list" in detail
        assert "Durable resource catalog of tools on this machine." in detail

        app.search_var.set("alpha needle")
        app.update()
        detail = app.detail.get("1.0", "end-1c")
        assert app.selected_id == "mcp.alpha-needle"
        assert "Alpha Needle" in detail
        assert "Select a name to read where it lives." not in detail

        app.world = select_entity(app.world, "mcp.beta-needle")
        app.selected_id = "mcp.beta-needle"
        app.render()
        assert "Beta Needle" in app.detail.get("1.0", "end-1c")

        app.search_var.set("not-a-real-name")
        app.update()
        assert app.search_count.cget("text") == "No matches"
        assert app.selected_id == "mcp.beta-needle"
        assert "Beta Needle" in app.detail.get("1.0", "end-1c")

        app.world = switch_page(app.world, "catalog")
        app.search_var.set("needle")
        app.update()
        assert app.search_count.cget("text") == "2 matches"
        assert app.selected_id == "mcp.alpha-needle"
        assert "Alpha Needle" in app.detail.get("1.0", "end-1c")
    finally:
        app.destroy()


def _selected_marks(canvas) -> list[tuple[int, int, int, int]]:
    marks = []
    for item in canvas.find_withtag("selected-mark"):
        marks.append(tuple(int(float(v)) for v in canvas.coords(item)))
    return marks


def test_selected_match_wears_the_accent_outline():
    world = build_world(
        {
            "resources": [
                {"id": "mcp.alpha-needle", "name": "Alpha Needle", "category": "MCPs"},
                {"id": "mcp.beta-needle", "name": "Beta Needle", "category": "MCPs"},
            ],
            "capabilities": [],
            "probes": {},
        }
    )
    app = _quiet_dashboard(world)
    try:
        accent = app._pal()["accent"]
        assert _selected_marks(app.systems_canvas) == []
        assert _selected_marks(app.game_canvas) == []

        app.search_var.set("resource catalog")
        app.update()
        hit = next(row for row in app.system_hits if row["id"] == "resource-list")
        mark = (hit["x0"], hit["y0"], hit["x1"], hit["y1"])
        assert _selected_marks(app.systems_canvas) == [mark]
        assert _selected_marks(app.game_canvas) == []
        assert accent.lower() in app.systems_canvas.itemcget(app.systems_canvas.find_withtag("selected-mark")[0], "outline").lower()
        assert r"C:\Users\Irika\.grok\resource-list" in app.detail.get("1.0", "end-1c")

        app.search_var.set("needle")
        app.update()
        alpha = next(row for row in app.game_hits if row["id"] == "mcp.alpha-needle")
        beta = next(row for row in app.game_hits if row["id"] == "mcp.beta-needle")
        alpha_box = (alpha["x0"], alpha["y0"], alpha["x1"], alpha["y1"])
        beta_box = (beta["x0"], beta["y0"], beta["x1"], beta["y1"])
        assert _selected_marks(app.game_canvas) == [alpha_box]
        assert beta_box not in _selected_marks(app.game_canvas)
        assert _selected_marks(app.systems_canvas) == []
        assert "Alpha Needle" in app.detail.get("1.0", "end-1c")

        app.world = select_entity(app.world, "mcp.beta-needle")
        app.selected_id = "mcp.beta-needle"
        app.render()
        assert _selected_marks(app.game_canvas) == [beta_box]
        assert "Beta Needle" in app.detail.get("1.0", "end-1c")

        app.world = switch_page(app.world, "catalog")
        app.search_var.set("beta needle")
        app.update()
        chip = next(row for row in app.hits if row["id"] == "mcp.beta-needle")
        assert _selected_marks(app.canvas) == [(chip["x0"], chip["y0"], chip["x1"], chip["y1"])]
        assert "Beta Needle" in app.detail.get("1.0", "end-1c")
    finally:
        app.destroy()


def test_enter_in_find_moves_to_the_next_match():
    world = build_world(
        {
            "resources": [
                {"id": "mcp.alpha-needle", "name": "Alpha Needle", "category": "MCPs"},
                {"id": "mcp.beta-needle", "name": "Beta Needle", "category": "MCPs"},
                {"id": "mcp.catalog-twin", "name": "Resource catalog twin", "category": "MCPs"},
            ],
            "capabilities": [],
            "probes": {},
        }
    )
    app = _quiet_dashboard(world)
    try:
        app.search_var.set("needle")
        app.update()
        assert app.selected_id == "mcp.alpha-needle"
        assert app.search_count.cget("text") == "2 matches"
        assert "<Key-Return>" in app.search_entry.bind()

        app._find_next()
        app.update()
        assert app.selected_id == "mcp.beta-needle"
        assert "Beta Needle" in app.detail.get("1.0", "end-1c")
        beta = next(row for row in app.game_hits if row["id"] == "mcp.beta-needle")
        assert _selected_marks(app.game_canvas) == [(beta["x0"], beta["y0"], beta["x1"], beta["y1"])]
        assert app.search_count.cget("text") == "2 matches"

        app._find_next()
        app.update()
        assert app.selected_id == "mcp.alpha-needle"
        assert "Alpha Needle" in app.detail.get("1.0", "end-1c")

        app.world = select_entity(app.world, "mcp.beta-needle")
        app.selected_id = "mcp.beta-needle"
        app.render()
        app._find_next()
        app.update()
        assert app.selected_id == "mcp.alpha-needle"

        app.search_var.set("")
        app.update()
        held = app.detail.get("1.0", "end-1c")
        app._find_next()
        app.update()
        assert app.detail.get("1.0", "end-1c") == held
        assert app.selected_id == "mcp.alpha-needle"

        app.search_var.set("resource catalog")
        app.update()
        assert app.selected_id == "resource-list"
        assert r"C:\Users\Irika\.grok\resource-list" in app.detail.get("1.0", "end-1c")
        app._find_next()
        app.update()
        assert app.selected_id == "mcp.catalog-twin"
        assert "Resource catalog twin" in app.detail.get("1.0", "end-1c")
        twin = next(row for row in app.game_hits if row["id"] == "mcp.catalog-twin")
        assert _selected_marks(app.game_canvas) == [(twin["x0"], twin["y0"], twin["x1"], twin["y1"])]
        assert _selected_marks(app.systems_canvas) == []
    finally:
        app.destroy()
