"""Pure graphical tree layout: named boxes, kind fills, parent–child edges.

No Tk. Tests and dump consume the same geometry the canvas draws.
"""
from __future__ import annotations

import hashlib
from typing import Any

from theme import DEFAULT_SCHEME, apply_scheme, kind_fill as theme_kind_fill

BOX_W = 168
BOX_H = 58
LIVE_IDS = {"grok.bot", "pi.lan", "mempalace.hub", "orchestrator"}
GAP_X = 72
GAP_Y = 14
CORNER_RADIUS = 12


def kind_fill(kind: str | None, scheme: str | None = None) -> str:
    return theme_kind_fill(kind, scheme)


def sparkline(nid: str, n: int = 8) -> list[float]:
    digest = hashlib.md5(str(nid).encode("utf-8")).digest()
    return [digest[i] / 255.0 for i in range(n)]


def tree_root(tree: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize running-tree `nodes` and giant `children` to one child list."""
    if not isinstance(tree, dict):
        return {"id": "empty", "name": "empty", "kind": "item", "children": []}
    kids = tree.get("children") or tree.get("nodes") or []
    return {
        "id": tree.get("id") or "root",
        "name": tree.get("name") or tree.get("id") or "root",
        "kind": tree.get("kind") or "system",
        "children": [c for c in kids if isinstance(c, dict)],
    }


def _kids(node: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in (node.get("children") or node.get("nodes") or []) if isinstance(c, dict)]


def _visible_kids(node: dict[str, Any], collapsed: set[str]) -> list[dict[str, Any]]:
    if str(node.get("id") or "") in collapsed:
        return []
    return _kids(node)


def _subtree_height(node: dict[str, Any], collapsed: set[str]) -> int:
    kids = _visible_kids(node, collapsed)
    if not kids:
        return BOX_H
    return max(BOX_H, sum(_subtree_height(c, collapsed) for c in kids) + GAP_Y * (len(kids) - 1))


def _walk_collapsible(node: dict[str, Any], out: list[str]) -> None:
    if _kids(node):
        nid = str(node.get("id") or "")
        if nid:
            out.append(nid)
        for child in _kids(node):
            _walk_collapsible(child, out)


def layout_tree(
    root: dict[str, Any] | None,
    *,
    origin: tuple[int, int] = (28, 28),
    scheme: str | None = None,
    collapsed: list[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Left-to-right boxed tree: rounded nodes, cubic curves, optional collapse."""
    node = tree_root(root)
    collapsed_set = {str(x) for x in (collapsed or []) if str(x)}
    boxes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    ox, oy = origin
    collapsible: list[str] = []
    _walk_collapsible(node, collapsible)

    def place(cur: dict[str, Any], x: int, top: int) -> dict[str, Any]:
        kids = _visible_kids(cur, collapsed_set)
        height = _subtree_height(cur, collapsed_set)
        y = top + max(0, (height - BOX_H) // 2)
        nid = str(cur.get("id") or "")
        name = str(cur.get("name") or nid)
        kind = str(cur.get("kind") or "item")
        has_kids = bool(_kids(cur))
        active = nid in LIVE_IDS or kind in ("process", "probe")
        box = {
            "id": nid,
            "name": name,
            "kind": kind,
            "fill": kind_fill(kind, scheme or DEFAULT_SCHEME),
            "x": int(x),
            "y": int(y),
            "w": BOX_W,
            "h": BOX_H,
            "radius": CORNER_RADIUS,
            "collapsible": has_kids,
            "collapsed": nid in collapsed_set,
            "active": active,
            "feed": sparkline(nid) if active else [],
        }
        boxes.append(box)
        child_top = top
        for child in kids:
            ch = _subtree_height(child, collapsed_set)
            child_box = place(child, x + BOX_W + GAP_X, child_top)
            x1 = box["x"] + BOX_W
            y1 = box["y"] + BOX_H // 2
            x2 = child_box["x"]
            y2 = child_box["y"] + BOX_H // 2
            cx = (x1 + x2) / 2.0
            edges.append(
                {
                    "parent": box["id"],
                    "child": child_box["id"],
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "curve": True,
                    "kind": "cubic",
                    "controls": [{"x": cx, "y": y1}, {"x": cx, "y": y2}],
                    "path": [
                        {"x": x1, "y": y1},
                        {"x": cx, "y": y1},
                        {"x": cx, "y": y2},
                        {"x": x2, "y": y2},
                    ],
                }
            )
            child_top += ch + GAP_Y
        return box

    place(node, ox, oy)
    graphic = {
        "graphic": True,
        "nodes": boxes,
        "edges": edges,
        "fills": {b["kind"]: b["fill"] for b in boxes},
        "box": {"w": BOX_W, "h": BOX_H, "gap_x": GAP_X, "gap_y": GAP_Y, "radius": CORNER_RADIUS},
        "radius": CORNER_RADIUS,
        "collapsible_ids": collapsible,
        "collapsed_ids": sorted(collapsed_set),
        "direction": "ltr",
    }
    graphic.update(content_extent(graphic))
    return apply_scheme(graphic, scheme or DEFAULT_SCHEME)


def content_extent(graphic: dict[str, Any]) -> dict[str, int]:
    """Content size that covers every node box (and edge endpoints)."""
    max_x = 0
    max_y = 0
    for box in graphic.get("nodes") or []:
        max_x = max(max_x, int(box.get("x") or 0) + int(box.get("w") or 0))
        max_y = max(max_y, int(box.get("y") or 0) + int(box.get("h") or 0))
    for edge in graphic.get("edges") or []:
        max_x = max(max_x, int(edge.get("x1") or 0), int(edge.get("x2") or 0))
        max_y = max(max_y, int(edge.get("y1") or 0), int(edge.get("y2") or 0))
        for pt in list(edge.get("path") or []) + list(edge.get("controls") or []):
            max_x = max(max_x, int(pt.get("x") or 0))
            max_y = max(max_y, int(pt.get("y") or 0))
    pad = 28
    return {"content_width": int(max_x + pad), "content_height": int(max_y + pad)}


def viewport_overflow(graphic: dict[str, Any], viewport_width: int, viewport_height: int) -> dict[str, Any]:
    """Two-axis overflow: a viewport smaller than the layout needs both scrollbars."""
    ext = content_extent(graphic)
    vw = max(0, int(viewport_width))
    vh = max(0, int(viewport_height))
    cw, ch = ext["content_width"], ext["content_height"]
    h_need = cw > vw
    v_need = ch > vh
    return {
        **ext,
        "viewport_width": vw,
        "viewport_height": vh,
        "overflow_x": h_need,
        "overflow_y": v_need,
        "h_scroll_needed": h_need,
        "v_scroll_needed": v_need,
        "scroll_needed": h_need or v_need,
    }


def siblings_overlap(graphic: dict[str, Any]) -> list[tuple[str, str]]:
    """Axis-aligned overlap among boxes that share an x (LTR siblings)."""
    hits: list[tuple[str, str]] = []
    nodes = list(graphic.get("nodes") or [])
    for i, a in enumerate(nodes):
        for b in nodes[i + 1 :]:
            if int(a["x"]) != int(b["x"]):
                continue
            ay2, by2 = a["y"] + a["h"], b["y"] + b["h"]
            if a["y"] < by2 and b["y"] < ay2:
                hits.append((str(a.get("id")), str(b.get("id"))))
    return hits


def parents_left_of_children(graphic: dict[str, Any]) -> bool:
    by_id = {n.get("id"): n for n in (graphic.get("nodes") or [])}
    for edge in graphic.get("edges") or []:
        parent = by_id.get(edge.get("parent"))
        child = by_id.get(edge.get("child"))
        if not parent or not child:
            return False
        if int(parent["x"]) >= int(child["x"]):
            return False
    return True


def is_curved_edge(edge: dict[str, Any]) -> bool:
    """True when the connector is a cubic/path curve, not an orthogonal elbow."""
    if edge.get("curve") and edge.get("kind") == "cubic" and edge.get("controls"):
        path = edge.get("path") or []
        if len(path) >= 4:
            xs = [p.get("x") for p in path]
            ys = [p.get("y") for p in path]
            elbow = len(set(xs)) <= 2 and len(set(ys)) <= 2 and xs[0] == xs[1] and xs[-1] == xs[-2]
            return not elbow
    return False
