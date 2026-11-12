"""Live-diagram trees: running, available/inactive, giant active system tree.

Pure functions — snapshot in, searchable lists and nested trees out.
"""
from __future__ import annotations

from typing import Any

from layout import layout_tree, tree_root

ROW_PX = 22
DIAGRAM_SECTIONS = (
    {"id": "running", "title": "Running work trees", "has_preview": True},
    {"id": "available", "title": "Available (not active)", "has_preview": True},
    {"id": "giant", "title": "Giant active system tree", "has_preview": False},
)


def list_overflow(item_count: int, viewport_height: int, row_height: int = ROW_PX) -> dict[str, Any]:
    """Window-size-aware overflow: same list may need scroll in a small viewport."""
    rows = max(0, int(item_count))
    row_h = max(1, int(row_height))
    view = max(0, int(viewport_height))
    content = rows * row_h
    visible = view // row_h if row_h else 0
    overflow = content > view
    return {
        "overflow": overflow,
        "scroll_needed": overflow,
        "item_count": rows,
        "viewport_height": view,
        "row_height": row_h,
        "content_height": content,
        "visible_rows": visible,
        "hidden_rows": max(0, rows - visible),
    }


def _tags(rec: dict[str, Any]) -> list[str]:
    raw = rec.get("tags") or []
    if isinstance(raw, str):
        return [raw]
    return [str(t) for t in raw if str(t).strip()]


def _node(nid: str, name: str, kind: str, *, children: list | None = None, extra: dict | None = None) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "id": nid,
        "name": name,
        "kind": kind,
        "children": list(children or []),
    }
    if extra:
        rec.update(extra)
    return rec


def _match(rec: dict[str, Any], query: str = "", category: str = "", tag: str = "") -> bool:
    if category and str(rec.get("category") or "").lower() != category.lower():
        return False
    if tag:
        tags = [t.lower() for t in _tags(rec)]
        if tag.lower() not in tags:
            return False
    q = (query or "").strip().lower()
    if not q:
        return True
    blob = " ".join(
        [
            str(rec.get("id") or ""),
            str(rec.get("name") or ""),
            str(rec.get("description") or ""),
            str(rec.get("category") or ""),
            " ".join(_tags(rec)),
            str(rec.get("kind") or ""),
        ]
    ).lower()
    return q in blob


def _walk_match(node: dict[str, Any], query: str) -> bool:
    if _match(node, query=query):
        return True
    return any(_walk_match(c, query) for c in (node.get("children") or []) if isinstance(c, dict))


def expand_tree(tree: dict[str, Any]) -> dict[str, Any]:
    """Click popout: full tree, no longer minimized."""
    out = dict(tree)
    out["minimized"] = False
    out["popout"] = True
    out["expanded"] = True
    out["nodes"] = list(tree.get("nodes") or tree.get("children") or [])
    return out


def popout_node(node: dict[str, Any]) -> dict[str, Any]:
    """Giant-tree click: nested popout of that subtree."""
    out = dict(node)
    out["popout"] = True
    out["children"] = list(node.get("children") or [])
    return out


def search_items(items: list[dict[str, Any]], *, query: str = "", category: str = "", tag: str = "") -> list[dict[str, Any]]:
    return [it for it in items if _match(it, query=query, category=category, tag=tag)]


def search_giant(root: dict[str, Any], query: str = "") -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return dict(root)

    def keep(node: dict[str, Any]) -> dict[str, Any] | None:
        kids = [keep(c) for c in (node.get("children") or []) if isinstance(c, dict)]
        kids = [k for k in kids if k]
        if kids or _match(node, query=q):
            out = dict(node)
            out["children"] = kids
            return out
        return None

    kept = keep(root)
    return kept if kept is not None else {**root, "children": []}


def _running_from_snapshot(snap: dict[str, Any]) -> list[dict[str, Any]]:
    given = snap.get("running") or snap.get("running_trees") or []
    if isinstance(given, list) and given:
        out = []
        for rec in given:
            if not isinstance(rec, dict) or not rec.get("id"):
                continue
            nodes = list(rec.get("nodes") or rec.get("children") or [])
            out.append(
                {
                    "id": str(rec["id"]),
                    "name": str(rec.get("name") or rec["id"]),
                    "description": str(rec.get("description") or rec.get("preview") or rec.get("name") or rec["id"]),
                    "preview": str(rec.get("preview") or rec.get("description") or rec.get("name") or rec["id"]),
                    "category": str(rec.get("category") or "running"),
                    "tags": _tags(rec) or ["running"],
                    "minimized": True,
                    "active": True,
                    "nodes": nodes,
                }
            )
        return out
    trees = []
    probes = snap.get("probes") if isinstance(snap.get("probes"), dict) else {}
    if (probes.get("orchestrator") or {}).get("ok"):
        trees.append(
            {
                "id": "task.orchestrator",
                "name": "Orchestrator watch",
                "description": "Live stack observer + correct/re-task loop",
                "preview": "Orchestrator watch — stack observer + correct/re-task",
                "category": "orchestrator",
                "tags": ["running", "watch"],
                "minimized": True,
                "active": True,
                "nodes": [
                    _node("observe", "Observe", "process"),
                    _node("correct", "Correct", "process"),
                    _node("retask", "Retask", "process"),
                ],
            }
        )
    bus = probes.get("cli.source_bus") if isinstance(probes.get("cli.source_bus"), dict) else {}
    if bus.get("ok") or int(bus.get("open_count") or 0) > 0:
        opens = list(bus.get("open") or [])
        nodes = [_node("cli.source_bus", "Source bus", "process")]
        for rec in opens[:8]:
            if not isinstance(rec, dict):
                continue
            nid = str(rec.get("id") or rec.get("correlation_id") or "open")
            nodes.append(
                _node(
                    nid,
                    str(rec.get("correlation_id") or nid)[:24],
                    "task",
                    extra={"body": rec.get("body"), "to_agent": rec.get("to_agent")},
                )
            )
        trees.append(
            {
                "id": "task.source-bus",
                "name": "Source bus",
                "description": f"{int(bus.get('open_count') or 0)} open task.request",
                "preview": f"Source bus — {int(bus.get('open_count') or 0)} open",
                "category": "hosting",
                "tags": ["running", "bus"],
                "minimized": True,
                "active": int(bus.get("open_count") or 0) > 0,
                "nodes": nodes,
            }
        )
    if (probes.get("grok.bot") or {}).get("ok"):
        trees.append(
            {
                "id": "task.grok-bot",
                "name": "Grok Bot host",
                "description": "24/7 primary host for Silvia",
                "preview": "Grok Bot — primary 24/7 host",
                "category": "hosting",
                "tags": ["running", "host"],
                "minimized": True,
                "active": True,
                "nodes": [_node("grok.bot", "Grok Bot", "process")],
            }
        )
    if (probes.get("mempalace.hub") or {}).get("ok"):
        trees.append(
            {
                "id": "task.mempalace-hub",
                "name": "MemPalace hub",
                "description": "HTTP MCP writer on :8765",
                "preview": "MemPalace hub — HTTP MCP :8765",
                "category": "memory",
                "tags": ["running", "memory"],
                "minimized": True,
                "active": True,
                "nodes": [_node("mempalace.hub", "MemPalace hub", "process")],
            }
        )
    return trees


def _available_from_snapshot(snap: dict[str, Any], running_ids: set[str]) -> list[dict[str, Any]]:
    given = snap.get("available") or snap.get("available_trees") or []
    if isinstance(given, list) and given:
        out = []
        for rec in given:
            if not isinstance(rec, dict) or not rec.get("id"):
                continue
            tid = str(rec["id"])
            if tid in running_ids:
                continue
            out.append(
                {
                    "id": tid,
                    "name": str(rec.get("name") or tid),
                    "description": str(rec.get("description") or rec.get("preview") or rec.get("name") or tid),
                    "preview": str(rec.get("preview") or rec.get("description") or rec.get("name") or tid),
                    "category": str(rec.get("category") or "available"),
                    "tags": _tags(rec) or ["available"],
                    "minimized": True,
                    "active": False,
                    "nodes": list(rec.get("nodes") or rec.get("children") or []),
                }
            )
        return out
    trees = []
    for cap in snap.get("capabilities") or []:
        cid = str(cap)
        tid = f"cap.{cid}"
        if tid in running_ids:
            continue
        trees.append(
            {
                "id": tid,
                "name": f"Silvia {cid}",
                "description": f"Butler capability {cid} (idle)",
                "preview": f"Silvia {cid} — idle capability",
                "category": "capability",
                "tags": ["available", "silvia", "capability"],
                "minimized": True,
                "active": False,
                "nodes": [_node(cid, cid, "capability")],
            }
        )
    for rec in snap.get("resources") or []:
        if not isinstance(rec, dict) or not rec.get("id"):
            continue
        rid = str(rec["id"])
        tid = f"res.{rid}"
        if tid in running_ids:
            continue
        cat = str(rec.get("category") or "CLIs")
        trees.append(
            {
                "id": tid,
                "name": str(rec.get("name") or rid),
                "description": str(rec.get("description") or cat),
                "preview": f"{rec.get('name') or rid} — {cat}",
                "category": cat,
                "tags": _tags(rec) or ["available", cat.lower().replace(" ", "-")],
                "minimized": True,
                "active": False,
                "nodes": [_node(rid, str(rec.get("name") or rid), cat)],
            }
        )
    return trees


def _giant_from_snapshot(snap: dict[str, Any]) -> dict[str, Any]:
    given = snap.get("giant") if isinstance(snap.get("giant"), dict) else None
    if given and given.get("id"):
        root = dict(given)
        root["minimized"] = False
        root.pop("preview", None)
        root["has_preview"] = False
        return root

    probes = snap.get("probes") if isinstance(snap.get("probes"), dict) else {}
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for rec in snap.get("resources") or []:
        if not isinstance(rec, dict) or not rec.get("id"):
            continue
        cat = str(rec.get("category") or "Other")
        by_cat.setdefault(cat, []).append(
            _node(str(rec["id"]), str(rec.get("name") or rec["id"]), cat.lower())
        )
    cap_nodes = [_node(str(c), str(c), "capability") for c in (snap.get("capabilities") or [])]
    host_kids = []
    for pid, pname in (
        ("grok.bot", "Grok Bot"),
        ("pi.lan", "Pi LAN"),
        ("mempalace.hub", "MemPalace hub"),
        ("orchestrator", "Orchestrator"),
        ("cli.money_loop", "Money loop"),
        ("cli.steam_lan", "Steam LAN check"),
        ("app.silvia_android", "Silvia Android"),
        ("cli.source_bus", "Source bus"),
    ):
        body = probes.get(pid) if isinstance(probes.get(pid), dict) else {}
        host_kids.append(_node(pid, pname, "process", extra={"ok": body.get("ok")}))

    catalog_kids = [
        _node(f"cat.{cat}", cat, "category", children=kids)
        for cat, kids in sorted(by_cat.items())
        if cat not in ("Memory", "Workflows")
    ]
    children = [
        _node("system.hosting", "Hosting", "subsystem", children=host_kids),
        _node("system.memory", "Memory", "subsystem", children=by_cat.get("Memory") or []),
        _node("system.catalog", "Catalog", "subsystem", children=catalog_kids),
        _node("system.capabilities", "Silvia capabilities", "subsystem", children=cap_nodes),
        _node(
            "system.workflows",
            "Workflows",
            "subsystem",
            children=by_cat.get("Workflows") or [],
        ),
    ]
    return {
        "id": "giant.active",
        "name": "Active Silvia System",
        "kind": "system",
        "minimized": False,
        "has_preview": False,
        "children": children,
    }


def update_giant(
    root: dict[str, Any],
    *,
    add: dict[str, Any] | None = None,
    remove: str | None = None,
    edit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Live add / remove / edit of giant-tree items."""
    tree = json_clone(root)

    def drop(node: dict[str, Any], eid: str) -> dict[str, Any] | None:
        if str(node.get("id")) == eid:
            return None
        kids = []
        for c in node.get("children") or []:
            if not isinstance(c, dict):
                continue
            kept = drop(c, eid)
            if kept is not None:
                kids.append(kept)
        node["children"] = kids
        return node

    def patch(node: dict[str, Any], eid: str, fields: dict[str, Any]) -> None:
        if str(node.get("id")) == eid:
            node.update({k: v for k, v in fields.items() if k != "id"})
            return
        for c in node.get("children") or []:
            if isinstance(c, dict):
                patch(c, eid, fields)

    def insert(node: dict[str, Any], parent_id: str, child: dict[str, Any]) -> bool:
        if str(node.get("id")) == parent_id:
            kids = list(node.get("children") or [])
            kids.append(child)
            node["children"] = kids
            return True
        for c in node.get("children") or []:
            if isinstance(c, dict) and insert(c, parent_id, child):
                return True
        return False

    if remove:
        dropped = drop(tree, str(remove))
        tree = dropped if dropped is not None else tree
    if edit and edit.get("id"):
        patch(tree, str(edit["id"]), edit)
    if add and add.get("id"):
        child = _node(
            str(add["id"]),
            str(add.get("name") or add["id"]),
            str(add.get("kind") or "item"),
            children=list(add.get("children") or []),
        )
        parent = str(add.get("parent") or tree.get("id") or "giant.active")
        if not insert(tree, parent, child):
            tree.setdefault("children", []).append(child)
    tree["minimized"] = False
    tree.pop("preview", None)
    tree["has_preview"] = False
    return tree


def json_clone(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: json_clone(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [json_clone(v) for v in obj]
    return obj


def build_diagrams(snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    snap = snapshot if isinstance(snapshot, dict) else {}
    running = _running_from_snapshot(snap)
    run_ids = {t["id"] for t in running}
    available = _available_from_snapshot(snap, run_ids)
    giant = _giant_from_snapshot(snap)
    return {
        "page": "live-diagrams",
        "sections": [dict(s) for s in DIAGRAM_SECTIONS],
        "section_ids": [s["id"] for s in DIAGRAM_SECTIONS],
        "running": running,
        "available": available,
        "giant": giant,
        "search": {"running": "", "available": "", "giant": ""},
    }


def diagrams_view(
    diagrams: dict[str, Any],
    *,
    section: str = "running",
    query: str = "",
    category: str = "",
    tag: str = "",
    expand_id: str | None = None,
    popout_id: str | None = None,
    scheme: str | None = None,
    collapsed: list[str] | None = None,
) -> dict[str, Any]:
    sid = section if section in ("running", "available", "giant") else "running"
    out = dict(diagrams)
    out["section"] = sid
    color = scheme or diagrams.get("scheme")
    out["scheme"] = color
    if sid == "giant":
        giant = search_giant(diagrams.get("giant") or {}, query=query)
        collapsed_ids = list(collapsed if collapsed is not None else diagrams.get("collapsed") or [])
        out["graphic"] = layout_tree(tree_root(giant), scheme=color, collapsed=collapsed_ids)
        if popout_id:
            def find(node: dict[str, Any]) -> dict[str, Any] | None:
                if str(node.get("id")) == popout_id:
                    return popout_node(node)
                for c in node.get("children") or []:
                    if isinstance(c, dict):
                        hit = find(c)
                        if hit:
                            return hit
                return None

            out["popout"] = find(giant)
        out["giant"] = giant
        out["preview"] = None
        out["has_preview"] = False
        return out
    items = list(diagrams.get(sid) or [])
    filtered = search_items(items, query=query, category=category, tag=tag)
    expanded = None
    if expand_id:
        for it in filtered:
            if it.get("id") == expand_id:
                expanded = expand_tree(it)
                break
    out[sid] = filtered
    out["expanded"] = expanded
    out["has_preview"] = True
    if expanded:
        collapsed_ids = list(collapsed if collapsed is not None else diagrams.get("collapsed") or [])
        out["graphic"] = layout_tree(tree_root(expanded), scheme=color, collapsed=collapsed_ids)
    return out
