"""Independent layout_id and color scheme. Default: giant-tree + oled-cyan."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_LAYOUT_ID = "live-diagrams-giant-tree"
DEFAULT_SCHEME = "oled-cyan"

LAYOUT_PAGES = {
    "live-diagrams-giant-tree": {"page": "live-diagrams", "section": "giant"},
    "overview-named-cards": {"page": "overview", "section": None},
    "command-center-hud": {"page": "butler-host", "section": None},
    "split-host-catalog": {"page": "catalog", "section": None},
    "memory-archipelago": {"page": "memory", "section": None},
}

# Palettes keyed by Imagine inventory scheme names. Geometry never lives here.
_PALETTES: dict[str, dict[str, Any]] = {
    "oled-cyan": {
        "background": "#05080a",
        "chrome": "#071016",
        "accent": "#00e5ff",
        "edge": "#00e5ff",
        "outline": "#7ef9ff",
        "text": "#d7f6ff",
        "text_on_fill": "#031014",
        "muted": "#7aa8b4",
        "card": "#071016",
        "card_outline": "#7ef9ff",
        "interior_header": "#07080a",
        "interior_body": "#14161a",
        "interior_inset": "#2c3036",
        "active_border": "#a855f7",
        "active_title": "#7e22ce",
        "title_text": "#ffffff",
        "title_stroke": "#ffffff",
        "fills": {
            "system": "#00e5ff",
            "subsystem": "#1496b8",
            "capability": "#2ee6d6",
            "process": "#3aa0c8",
            "cli": "#5ad4ff",
            "clis": "#5ad4ff",
            "skill": "#7ef9ff",
            "skills": "#7ef9ff",
            "tool": "#00bbf9",
            "tools": "#00bbf9",
            "mcp": "#4cc9f0",
            "mcps": "#4cc9f0",
            "memory": "#80e8ff",
            "workflow": "#00c2d4",
            "workflows": "#00c2d4",
            "category": "#1b4d5c",
            "hosting": "#1ecad3",
            "item": "#3d6b78",
            "resource": "#5ad4ff",
            "probe": "#4cc9f0",
        },
    },
    "cream-paper": {
        "background": "#f4efe4",
        "chrome": "#e8dfd0",
        "accent": "#b85c38",
        "edge": "#5c4033",
        "outline": "#3b2a22",
        "text": "#2a211c",
        "text_on_fill": "#f7f1e8",
        "muted": "#7a6554",
        "card": "#e8dfd0",
        "card_outline": "#3b2a22",
        "interior_header": "#3a3228",
        "interior_body": "#5c5348",
        "interior_inset": "#8a7f72",
        "active_border": "#b85c38",
        "active_title": "#9a4f32",
        "title_text": "#f7f1e8",
        "title_stroke": "#f7f1e8",
        "fills": {
            "system": "#b85c38",
            "subsystem": "#8c6a4a",
            "capability": "#c48a3a",
            "process": "#9a4f32",
            "cli": "#d4a574",
            "clis": "#d4a574",
            "skill": "#a67c52",
            "skills": "#a67c52",
            "tool": "#c47a4a",
            "tools": "#c47a4a",
            "mcp": "#8b5a3c",
            "mcps": "#8b5a3c",
            "memory": "#c9b896",
            "workflow": "#b07d4a",
            "workflows": "#b07d4a",
            "category": "#7a6554",
            "hosting": "#c47a4a",
            "item": "#8a7a6a",
            "resource": "#d4a574",
            "probe": "#a67c52",
        },
    },
    "parchment-bronze": {
        "background": "#2b2418",
        "chrome": "#3a3122",
        "accent": "#c9a227",
        "edge": "#d4b45a",
        "outline": "#f0e0a8",
        "text": "#f2ead4",
        "text_on_fill": "#1e180e",
        "muted": "#b8a878",
        "card": "#3a3122",
        "card_outline": "#f0e0a8",
        "interior_header": "#1e180e",
        "interior_body": "#3a3122",
        "interior_inset": "#5c4e32",
        "active_border": "#c9a227",
        "active_title": "#8c7340",
        "title_text": "#f2ead4",
        "title_stroke": "#f2ead4",
        "fills": {
            "system": "#c9a227",
            "subsystem": "#8c7340",
            "capability": "#d4b45a",
            "process": "#a67c2a",
            "cli": "#e9c46a",
            "clis": "#e9c46a",
            "skill": "#b8953d",
            "skills": "#b8953d",
            "tool": "#c9a227",
            "tools": "#c9a227",
            "mcp": "#8c7340",
            "mcps": "#8c7340",
            "memory": "#d4c48a",
            "workflow": "#c9a227",
            "workflows": "#c9a227",
            "category": "#5c4e32",
            "hosting": "#d4b45a",
            "item": "#7a6a44",
            "resource": "#e9c46a",
            "probe": "#d4b45a",
        },
    },
    "magenta-night": {
        "background": "#14010e",
        "chrome": "#1e0616",
        "accent": "#ff2bd6",
        "edge": "#ff2bd6",
        "outline": "#ff9ae8",
        "text": "#ffd6f5",
        "text_on_fill": "#1a0212",
        "muted": "#c97ab0",
        "card": "#1e0616",
        "card_outline": "#ff9ae8",
        "interior_header": "#0e010a",
        "interior_body": "#1e0616",
        "interior_inset": "#3a1430",
        "active_border": "#ff2bd6",
        "active_title": "#b31f96",
        "title_text": "#ffffff",
        "title_stroke": "#ffffff",
        "fills": {
            "system": "#ff2bd6",
            "subsystem": "#b31f96",
            "capability": "#ff6ae0",
            "process": "#d94ab8",
            "cli": "#ff9ae8",
            "clis": "#ff9ae8",
            "skill": "#e85ad0",
            "skills": "#e85ad0",
            "tool": "#ff2bd6",
            "tools": "#ff2bd6",
            "mcp": "#c93aad",
            "mcps": "#c93aad",
            "memory": "#ffb3ef",
            "workflow": "#ff2bd6",
            "workflows": "#ff2bd6",
            "category": "#5c1a4a",
            "hosting": "#ff6ae0",
            "item": "#8a3a72",
            "resource": "#ff9ae8",
            "probe": "#ff6ae0",
        },
    },
    "arctic-white": {
        "background": "#eef4f8",
        "chrome": "#d9e6ee",
        "accent": "#2a7ab8",
        "edge": "#3d7ea6",
        "outline": "#1b4d6b",
        "text": "#163044",
        "text_on_fill": "#f7fbff",
        "muted": "#5c7a8a",
        "card": "#d9e6ee",
        "card_outline": "#1b4d6b",
        "interior_header": "#c5d4de",
        "interior_body": "#d9e6ee",
        "interior_inset": "#eef4f8",
        "active_border": "#2a7ab8",
        "active_title": "#1b4d6b",
        "title_text": "#f7fbff",
        "title_stroke": "#f7fbff",
        "fills": {
            "system": "#2a7ab8",
            "subsystem": "#3d7ea6",
            "capability": "#4aa3c8",
            "process": "#5aa0c0",
            "cli": "#7ec8ff",
            "clis": "#7ec8ff",
            "skill": "#4cc9f0",
            "skills": "#4cc9f0",
            "tool": "#00bbf9",
            "tools": "#00bbf9",
            "mcp": "#3d7ea6",
            "mcps": "#3d7ea6",
            "memory": "#a8d8ea",
            "workflow": "#2a7ab8",
            "workflows": "#2a7ab8",
            "category": "#5c6778",
            "hosting": "#4aa3c8",
            "item": "#6c757d",
            "resource": "#7ec8ff",
            "probe": "#4cc9f0",
        },
    },
}


def inventory_path() -> Path:
    return Path.home() / ".grok" / "silvia-dashboard" / "imagine-drafts" / "inventory.json"


def inventory_identities() -> dict[str, Any]:
    path = inventory_path()
    layouts: set[str] = set()
    schemes: set[str] = set()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for rec in data.get("items") or []:
                if rec.get("layout_id"):
                    layouts.add(str(rec["layout_id"]))
                if rec.get("scheme"):
                    schemes.add(str(rec["scheme"]))
        except (OSError, json.JSONDecodeError):
            pass
    layouts.update(LAYOUT_PAGES)
    schemes.update(_PALETTES)
    return {"layout_ids": sorted(layouts), "schemes": sorted(schemes)}


def palette(scheme: str | None = None) -> dict[str, Any]:
    name = (scheme or DEFAULT_SCHEME).strip() or DEFAULT_SCHEME
    pal = _PALETTES.get(name) or _PALETTES[DEFAULT_SCHEME]
    out = dict(pal)
    out["id"] = name if name in _PALETTES else DEFAULT_SCHEME
    out["fills"] = dict(pal.get("fills") or {})
    return out


def kind_fill(kind: str | None, scheme: str | None = None) -> str:
    pal = palette(scheme)
    fills = pal.get("fills") or {}
    key = str(kind or "item").strip().lower()
    if key in fills:
        return str(fills[key])
    for token, fill in fills.items():
        if token and token in key:
            return str(fill)
    return str(fills.get("item") or pal.get("accent") or pal.get("edge") or pal["background"])


def paint_tokens(scheme: str | None = None) -> dict[str, Any]:
    """One token set for chrome, lists, cards, boxes, edges, and dump."""
    pal = palette(scheme)
    fills = dict(pal.get("fills") or {})
    fallback_fill = str(fills.get("item") or pal.get("accent") or pal["background"])
    return {
        "scheme": pal["id"],
        "background": pal["background"],
        "chrome": pal["chrome"],
        "accent": pal["accent"],
        "edge": pal["edge"],
        "outline": pal["outline"],
        "text": pal["text"],
        "text_on_fill": pal["text_on_fill"],
        "muted": pal.get("muted") or pal["text"],
        "card": pal.get("card") or pal["chrome"],
        "card_outline": pal.get("card_outline") or pal["outline"],
        "heading": pal["text"],
        "fallback_fill": fallback_fill,
        "fallback_stroke": pal["edge"],
        "fills": fills,
        "interior_header": pal.get("interior_header") or pal["chrome"],
        "interior_body": pal.get("interior_body") or pal["chrome"],
        "interior_inset": pal.get("interior_inset") or pal["card"],
        "active_border": pal.get("active_border") or pal["accent"],
        "active_title": pal.get("active_title") or pal["accent"],
        "title_text": pal.get("title_text") or pal["text"],
        "title_stroke": pal.get("title_stroke") or pal["text"],
    }


def select(layout_id: str | None = None, scheme: str | None = None) -> dict[str, Any]:
    """Independent axes. Default is the liked Imagine pair."""
    ids = inventory_identities()
    layout = (layout_id or DEFAULT_LAYOUT_ID).strip() or DEFAULT_LAYOUT_ID
    color = (scheme or DEFAULT_SCHEME).strip() or DEFAULT_SCHEME
    if layout not in ids["layout_ids"]:
        layout = DEFAULT_LAYOUT_ID
    if color not in ids["schemes"] and color not in _PALETTES:
        color = DEFAULT_SCHEME
    page = LAYOUT_PAGES.get(layout) or LAYOUT_PAGES[DEFAULT_LAYOUT_ID]
    pal = palette(color)
    return {
        "layout_id": layout,
        "scheme": pal["id"],
        "page": page["page"],
        "section": page.get("section"),
        "background": pal["background"],
        "accent": pal["accent"],
        "chrome": pal["chrome"],
        "edge": pal["edge"],
        "outline": pal["outline"],
        "text": pal["text"],
        "text_on_fill": pal["text_on_fill"],
        "paint": paint_tokens(pal["id"]),
    }


def apply_scheme(graphic: dict[str, Any], scheme: str | None = None) -> dict[str, Any]:
    """Recolor boxes/chrome; leave x/y/w/h and edge endpoints unchanged."""
    pal = palette(scheme)
    out = dict(graphic)
    nodes = []
    for box in graphic.get("nodes") or []:
        rec = dict(box)
        rec["fill"] = kind_fill(rec.get("kind"), pal["id"])
        rec["x"], rec["y"], rec["w"], rec["h"] = box["x"], box["y"], box["w"], box["h"]
        nodes.append(rec)
    out["nodes"] = nodes
    out["edges"] = [dict(e) for e in (graphic.get("edges") or [])]
    out["fills"] = {n["kind"]: n["fill"] for n in nodes}
    out["scheme"] = pal["id"]
    tokens = paint_tokens(pal["id"])
    out.update({k: tokens[k] for k in (
        "background", "accent", "edge", "outline", "chrome", "text", "text_on_fill",
        "muted", "card", "card_outline", "heading", "fallback_fill", "fallback_stroke",
        "interior_header", "interior_body", "interior_inset",
        "active_border", "active_title", "title_text", "title_stroke",
    )})
    for rec in nodes:
        active = bool(rec.get("active"))
        rec["interior_header"] = tokens["interior_header"]
        rec["interior_body"] = tokens["interior_body"]
        rec["interior_inset"] = tokens["interior_inset"]
        rec["title_fill"] = tokens["active_title"] if active else tokens["interior_header"]
        rec["title_text"] = tokens["active_title"] if active else tokens["text"]
        rec["title_stroke"] = tokens["title_text"] if active else tokens["interior_header"]
        rec["border"] = tokens["active_border"] if active else tokens["outline"]
        rec["chip"] = kind_fill(rec.get("kind"), pal["id"])
        rec["fill"] = tokens["interior_body"]
    return out


def apply_selection(world: dict[str, Any], layout_id: str | None = None, scheme: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Stamp layout_id + scheme onto world and nested diagrams so dump, window, and diagrams_view agree."""
    sel = select(layout_id, scheme)
    out = dict(world)
    out["layout_id"] = sel["layout_id"]
    out["scheme"] = sel["scheme"]
    out["background"] = sel["background"]
    out["accent"] = sel["accent"]
    out["chrome"] = sel["chrome"]
    out["edge"] = sel["edge"]
    out["outline"] = sel["outline"]
    out["text"] = sel["text"]
    out["paint"] = paint_tokens(sel["scheme"])
    diagrams = dict(out.get("diagrams") or {})
    diagrams["scheme"] = sel["scheme"]
    diagrams["layout_id"] = sel["layout_id"]
    out["diagrams"] = diagrams
    return out, sel


def geometry_key(graphic: dict[str, Any]) -> list[tuple]:
    return [
        (n.get("id"), int(n.get("x") or 0), int(n.get("y") or 0), int(n.get("w") or 0), int(n.get("h") or 0))
        for n in (graphic.get("nodes") or [])
    ]
