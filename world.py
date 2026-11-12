"""Pure Silvia dashboard model: pages + overview game world.

No window I/O. Snapshot in → pages, entities, inspect payloads out.
Entity ids for catalog rows equal catalog ids; capability ids equal Silvia
capability strings so add/remove on the live sources evolves the world.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from systems import is_system, open_system, overview_systems
from theme import DEFAULT_LAYOUT_ID, DEFAULT_SCHEME, select
from trees import build_diagrams, list_overflow


def command_pairs() -> tuple[tuple[str, str], ...]:
    """Entry-point command names and the descriptions the Commands page paints."""
    return (
        ("dump", "Snapshot pages + game world (no GUI)."),
        ("launch", "Windows window, or --dump for snapshot."),
        ("pages", "List page ids."),
        ("switch", "Switch the printed view to the required page, or open that system when the page id is a system."),
        ("inspect", "Show one system, or the selected world entity, for the required id."),
        ("evolve", "Load the required snapshot and return the world after the requested removals and optional added entity."),
        ("screenshot", "Write a PNG of the overview systems, or of another page's world, to the required output path."),
        ("layout", "Print the laid-out diagram graphic for a section, giant by default, including its layout id and scheme."),
        ("overflow", "Report whether a list of the required item count overflows a viewport of the required size."),
        ("diagrams", "Print the diagrams view for a section, with optional query, category, tag, and expand filters."),
        ("imagine-inventory", "Scan Imagine 5x5 layout drafts folder."),
        ("imagine-open", "Open Imagine drafts folder in Explorer."),
        ("giant-update", "Update the giant diagram in the required snapshot by adding, removing, or renaming a node, and print the updated tree."),
    )


PAGES: tuple[dict[str, str], ...] = (
    {"id": "overview", "title": "Overview", "kind": "game"},
    {"id": "butler-host", "title": "Butler & Hosting", "kind": "host"},
    {"id": "memory", "title": "Memory", "kind": "memory"},
    {"id": "catalog", "title": "Catalog", "kind": "catalog"},
    {"id": "orchestrator", "title": "Orchestrator", "kind": "watch"},
    {"id": "usage", "title": "SuperGrok Heavy", "kind": "usage"},
    {"id": "live-diagrams", "title": "Live diagrams", "kind": "diagrams"},
    {"id": "task-view", "title": "Task view", "kind": "task-view"},
    {"id": "sessions", "title": "Sessions", "kind": "sessions"},
    {"id": "commands", "title": "Commands", "kind": "commands"},
)

REGION_OFFSET = {
    "hostlands": (0, 0),
    "silvia-precinct": (16, 0),
    "memory-archipelago": (0, 12),
    "catalog-continents": (16, 12),
    "watch-range": (8, 6),
    "usage-bay": (0, 20),
}

CATEGORY_REGION = {
    "MCPs": "catalog-continents",
    "CLIs": "catalog-continents",
    "Tools": "catalog-continents",
    "Skills": "catalog-continents",
    "Grok Bots": "catalog-continents",
    "Hooks": "catalog-continents",
    "Docs": "catalog-continents",
    "Agents": "catalog-continents",
    "Workflows": "catalog-continents",
    "accounts": "catalog-continents",
    "System Hardware and Software": "hostlands",
    "Memory": "memory-archipelago",
}

TILE_W = 24
TILE_H = 16


def page_list() -> list[dict[str, str]]:
    return [dict(p) for p in PAGES]


def page_ids() -> list[str]:
    return [p["id"] for p in PAGES]


def switch_page(state: dict[str, Any], page_id: str) -> dict[str, Any]:
    """Shipped page switch: returns a new state with the named page selected."""
    wanted = str(page_id or "").strip()
    known = page_ids()
    if wanted not in known:
        raise ValueError(f"unknown page: {wanted}; known={known}")
    out = dict(state)
    out["page"] = wanted
    page = next(p for p in PAGES if p["id"] == wanted)
    out["page_title"] = page["title"]
    out["page_kind"] = page["kind"]
    return out


def pretty_name(eid: str, name: str | None = None) -> str:
    text = (name or "").strip()
    if text and text != eid:
        return text
    raw = (eid or "").replace("_", " ").replace("-", " ").replace(".", " · ")
    return raw[:1].upper() + raw[1:] if raw else eid


def role_for(kind: str, category: str = "") -> str:
    kind = (kind or "item").strip()
    if kind == "capability":
        return "Silvia capability"
    if kind == "probe":
        return "Stack probe"
    if kind == "usage":
        return "SuperGrok Heavy usage"
    if category:
        return f"{category} · {kind}"
    return kind


def _layout_slots(region: str, index: int) -> tuple[int, int]:
    """Readable grid per region — sequential slots, not hash-scattered blobs."""
    ox, oy = REGION_OFFSET.get(region, (0, 0))
    cols = 4
    return ox + (index % cols) * 3, oy + (index // cols) * 2


def _entity(
    eid: str,
    *,
    name: str,
    kind: str,
    region: str,
    category: str = "",
    description: str = "",
    ok: bool | None = None,
    source: str = "",
) -> dict[str, Any]:
    label = pretty_name(eid, name)
    role = role_for(kind, category)
    return {
        "id": eid,
        "name": label,
        "label": label,
        "role": role,
        "kind": kind,
        "region": region,
        "category": category,
        "description": description,
        "ok": ok,
        "source": source,
        "x": 0,
        "y": 0,
        "inspect": {
            "id": eid,
            "name": label,
            "role": role,
            "kind": kind,
            "region": region,
            "category": category,
            "ok": ok,
            "description": description,
        },
    }


def build_world(snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build pages + inspectable game entities from a representative snapshot."""
    snap = snapshot if isinstance(snapshot, dict) else {}
    resources = [r for r in (snap.get("resources") or []) if isinstance(r, dict) and r.get("id")]
    capabilities = [str(c) for c in (snap.get("capabilities") or []) if str(c).strip()]
    probes = snap.get("probes") if isinstance(snap.get("probes"), dict) else {}
    entities: list[dict[str, Any]] = []

    for cap in capabilities:
        entities.append(
            _entity(
                cap,
                name=pretty_name(cap, cap.replace(".", " ").title()),
                kind="capability",
                region="silvia-precinct",
                category="Silvia",
                description=f"Silvia butler capability {cap}",
                ok=True,
                source="silvia.capabilities",
            )
        )

    for rec in resources:
        rid = str(rec["id"])
        category = str(rec.get("category") or "")
        region = CATEGORY_REGION.get(category, "catalog-continents")
        entities.append(
            _entity(
                rid,
                name=str(rec.get("name") or rid),
                kind="resource",
                region=region,
                category=category,
                description=str(rec.get("description") or rec.get("invoke") or ""),
                ok=True,
                source="resource-list",
            )
        )

    # Probe dict key stays `orchestrator` (snapshots and diagram nodes). The
    # entity id is `probe.orchestrator` so it does not cover the system id.
    probe_meta = (
        ("mempalace.hub", "mempalace.hub", "MemPalace hub", "hostlands"),
        ("grok.bot", "grok.bot", "Grok Bot", "hostlands"),
        ("pi.lan", "pi.lan", "Pi LAN", "hostlands"),
        ("orchestrator", "probe.orchestrator", "Orchestrator probe", "watch-range"),
        ("cli.money_loop", "cli.money_loop", "Money loop", "hostlands"),
        ("cli.steam_lan", "cli.steam_lan", "Steam LAN check", "hostlands"),
        ("app.silvia_android", "app.silvia_android", "Silvia Android", "hostlands"),
        ("cli.source_bus", "cli.source_bus", "Source bus", "hostlands"),
    )
    for probe_key, eid, pname, region in probe_meta:
        body = probes.get(probe_key) if isinstance(probes.get(probe_key), dict) else {}
        entities.append(
            _entity(
                eid,
                name=pname,
                kind="probe",
                region=region,
                category="stack",
                description=str(body.get("url") or body.get("path") or body.get("action") or pname),
                ok=body.get("ok") if body else None,
                source="stack.probe",
            )
        )

    slots: dict[str, int] = {}
    for ent in entities:
        region = str(ent.get("region") or "catalog-continents")
        idx = slots.get(region, 0)
        ent["x"], ent["y"] = _layout_slots(region, idx)
        slots[region] = idx + 1

    usage = snap.get("usage") if isinstance(snap.get("usage"), dict) else {}
    for idx, row in enumerate(usage.get("breakdown") or []):
        if not isinstance(row, dict) or not row.get("id"):
            continue
        entities.append(
            _entity(
                str(row.get("id")),
                name=str(row.get("label") or row.get("id")),
                kind="usage",
                region="usage-bay",
                category="SuperGrok Heavy",
                description=str(row.get("value") if row.get("value") is not None else ""),
                ok=True,
                source="usage",
            )
        )
        entities[-1]["x"], entities[-1]["y"] = _layout_slots("usage-bay", idx)

    diagrams = build_diagrams(snap)
    sel = select()
    diagrams["scheme"] = sel["scheme"]
    diagrams["layout_id"] = sel["layout_id"]
    labels = [{"id": e["id"], "name": e.get("name"), "role": e.get("role"), "kind": e.get("kind")} for e in entities]
    systems = overview_systems()

    state = {
        "ok": True,
        "redirect": False,
        "pages": page_list(),
        "page": "overview",
        "page_title": "Overview",
        "page_kind": "game",
        "entities": entities,
        "entity_ids": [e["id"] for e in entities],
        "regions": list(REGION_OFFSET),
        "tile": {"w": TILE_W, "h": TILE_H},
        "selected": None,
        "game_labels": labels,
        "diagrams": diagrams,
        "diagram_sections": diagrams.get("section_ids") or [],
        "layout_id": sel["layout_id"],
        "scheme": sel["scheme"],
        "background": sel["background"],
        "accent": sel["accent"],
        "usage": usage,
        "probes": probes,
        "systems": systems,
        "system_ids": [row["id"] for row in systems],
        "overview": {"redirect": False, "systems": systems, "system_ids": [row["id"] for row in systems]},
    }
    return state


_HEALTH_KEYS = (
    "mempalace.hub",
    "grok.bot",
    "pi.lan",
    "silvia.butler",
    "silvia.voice",
    "orchestrator",
    "cli.money_loop",
    "cli.steam_lan",
    "app.silvia_android",
    "cli.source_bus",
)


def _health_rows(probes: dict[str, Any]) -> list[dict[str, Any]]:
    """Health rows keep their own ok. They do not write system presence."""
    rows: list[dict[str, Any]] = []
    for key in _HEALTH_KEYS:
        body = probes.get(key) if isinstance(probes.get(key), dict) else {}
        row: dict[str, Any] = {"id": key, "ok": body.get("ok")}
        if body.get("skipped"):
            row["skipped"] = True
        if body.get("label"):
            row["label"] = body.get("label")
        if body.get("url"):
            row["url"] = body.get("url")
        if body.get("path"):
            row["path"] = body.get("path")
        rows.append(row)
    return rows


def evolve(snapshot: dict[str, Any], *, add: list[dict[str, Any]] | None = None, remove: list[str] | None = None) -> dict[str, Any]:
    """Rebuild the world after catalog/capability add or remove (live evolution)."""
    snap = {
        "resources": list(snapshot.get("resources") or []),
        "capabilities": list(snapshot.get("capabilities") or []),
        "probes": dict(snapshot.get("probes") or {}),
        "running": list(snapshot.get("running") or []),
        "available": list(snapshot.get("available") or []),
        "usage": dict(snapshot.get("usage") or {}) if isinstance(snapshot.get("usage"), dict) else {},
    }
    drop = {str(x) for x in (remove or [])}
    snap["resources"] = [r for r in snap["resources"] if str(r.get("id")) not in drop]
    snap["capabilities"] = [c for c in snap["capabilities"] if str(c) not in drop]
    for rec in add or []:
        if not isinstance(rec, dict):
            continue
        rid = str(rec.get("id") or "")
        if not rid or rid in drop:
            continue
        if rec.get("kind") == "capability" or rec.get("as") == "capability":
            if rid not in snap["capabilities"]:
                snap["capabilities"].append(rid)
        else:
            existing = [r for r in snap["resources"] if str(r.get("id")) == rid]
            if existing:
                existing[0].update(rec)
            else:
                snap["resources"].append(rec)
    return build_world(snap)


def select_entity(world: dict[str, Any], entity_id: str) -> dict[str, Any]:
    eid = str(entity_id or "")
    if is_system(eid):
        detail = open_system(eid)
        out = dict(world)
        out["selected"] = detail
        out["detail"] = detail
        return out
    for ent in world.get("entities") or []:
        if ent.get("id") == eid:
            out = dict(world)
            out["selected"] = ent.get("inspect")
            return out
    out = dict(world)
    out["selected"] = None
    return out


def _task_spine() -> dict[str, Any]:
    import importlib.util
    from pathlib import Path

    path = Path.home() / ".grok" / "task-view" / "task_view.py"
    if not path.is_file():
        return {"hidden": False, "current_step": "", "path_taken": [], "choices": [], "opened": None, "tasks": []}
    spec = importlib.util.spec_from_file_location("task_view_runtime", path)
    if spec is None or spec.loader is None:
        return {"hidden": False, "current_step": "", "path_taken": [], "choices": [], "opened": None, "tasks": []}
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.spine_view()


def page_view(world: dict[str, Any], page_id: str | None = None) -> dict[str, Any]:
    """Named page payload for dump/UI: filter entities to that Silvia surface."""
    state = switch_page(world, page_id or world.get("page") or "overview")
    pid = state["page"]
    ents = list(state.get("entities") or [])
    if pid == "overview":
        shown = ents
        systems = overview_systems()
        state["systems"] = systems
        state["system_ids"] = [row["id"] for row in systems]
        state["overview"] = {"redirect": False, "systems": systems, "system_ids": state["system_ids"]}
    elif pid == "butler-host":
        shown = [e for e in ents if e.get("region") in ("hostlands", "silvia-precinct") or e.get("kind") in ("capability", "probe")]
        state["health"] = _health_rows(state.get("probes") or {})
    elif pid == "memory":
        shown = [e for e in ents if e.get("region") == "memory-archipelago" or str(e.get("category")) == "Memory"]
        state["system"] = open_system("mempalace")
    elif pid == "catalog":
        shown = [e for e in ents if e.get("kind") == "resource"]
        state["system"] = open_system("resource-list")
    elif pid == "orchestrator":
        shown = [
            e
            for e in ents
            if e.get("region") == "watch-range" or e.get("id") in ("probe.orchestrator", "cli.orchestrator", "orchestrator")
        ]
        state["system"] = open_system("orchestrator")
    elif pid == "usage":
        shown = [e for e in ents if e.get("kind") == "usage" or e.get("region") == "usage-bay"]
        state["usage"] = state.get("usage") or {}
        state["usage_tier"] = (state.get("usage") or {}).get("subscription_tier")
        state["usage_percent"] = (state.get("usage") or {}).get("credit_usage_percent")
        state["usage_remaining"] = (state.get("usage") or {}).get("remaining_percent")
        state["usage_breakdown"] = list((state.get("usage") or {}).get("breakdown") or [])
        state["usage_products"] = list((state.get("usage") or {}).get("products") or [])
        state["usage_week_start"] = (state.get("usage") or {}).get("period_start")
        state["usage_week_end"] = (state.get("usage") or {}).get("period_end")
        state["usage_as_of"] = (state.get("usage") or {}).get("fetched_at")
        state["usage_note"] = "SuperGrok Heavy weekly usage, not disk presence"
        from usage import _short_when

        start_l = _short_when(state["usage_week_start"])
        end_l = _short_when(state["usage_week_end"])
        as_of_l = _short_when(state["usage_as_of"])
        state["usage_week_start_label"] = start_l
        state["usage_week_end_label"] = end_l
        state["usage_as_of_label"] = as_of_l
        if start_l and end_l:
            state["usage_week_label"] = f"{start_l} – {end_l}"
        else:
            state["usage_week_label"] = start_l or end_l
        from token_history import empty_report

        history = state["usage"].get("tokens") if isinstance(state["usage"].get("tokens"), dict) else None
        if history is None:
            history = empty_report()
        state["token_total"] = history.get("total")
        state["token_input"] = history.get("input")
        state["token_output"] = history.get("output")
        cost = history.get("cost") if isinstance(history.get("cost"), dict) else {}
        state["token_cost"] = cost
        state["token_api_usd"] = cost.get("api")
        state["token_subscription_usd"] = cost.get("subscription")
        state["token_cost_difference"] = cost.get("difference")
        state["token_plans"] = list(history.get("plans") or [])
        state["token_sources"] = list(history.get("sources") or [])
        state["token_charts"] = history.get("charts") or {}
        state["token_series"] = list(history.get("series") or [])
        state["token_window"] = history.get("window") or {}
        state["token_earliest"] = history.get("earliest")
        state["token_events"] = list(state["usage"].get("token_events") or history.get("events") or [])
        state["token_sessions"] = list(history.get("sessions") or [])
        state["token_loaded"] = bool(history.get("loaded"))
    elif pid == "live-diagrams":
        shown = ents
        state["diagrams"] = state.get("diagrams") or build_diagrams({})
        state["diagram_sections"] = (state.get("diagrams") or {}).get("section_ids") or []
    elif pid == "task-view":
        shown = []
        spine = _task_spine()
        state["task_view"] = spine
        state["current_step"] = spine.get("current_step")
        state["path_taken"] = list(spine.get("path_taken") or [])
        state["choices"] = list(spine.get("choices") or [])
        state["opened"] = spine.get("opened")
    elif pid == "sessions":
        shown = []
        from sessions_live import device_sections, live_sessions

        registry = state.get("sessions_registry")
        home = state.get("sessions_home")
        state["sessions"] = live_sessions(
            registry if registry else None,
            grok_home=home if home else None,
        )
        roster = state.get("devices_roster")
        from remote_sessions import attach_remote_views

        state["devices"] = attach_remote_views(
            device_sections(
                state["sessions"],
                roster_path=Path(roster) if roster else None,
            )
        )
    elif pid == "commands":
        shown = []
        state["commands"] = [
            {"name": name, "description": description} for name, description in command_pairs()
        ]
    else:
        shown = ents
    state["view_entities"] = shown
    state["view_ids"] = [e["id"] for e in shown]
    state["overflow"] = list_overflow(len(shown), 400)
    return state
