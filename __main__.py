"""CLI: python "$HOME/.grok/silvia-dashboard/__main__.py" <command>

Windows-local Silvia dashboard. Dump/snapshot is the harness-readable entry.
`launch` opens a Tk window. Not an HTTP redirect.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from live import live_snapshot, load_snapshot_file
from capture import capture_world, render_systems_png
from layout import is_curved_edge, layout_tree, parents_left_of_children, tree_root, viewport_overflow
from theme import DEFAULT_LAYOUT_ID, DEFAULT_SCHEME, apply_selection, geometry_key, paint_tokens, select
from trees import diagrams_view, expand_tree, list_overflow, update_giant
from systems import is_system, open_system, overview_systems, pages_payload
from world import build_world, evolve, page_ids, page_list, page_view, select_entity, switch_page


def _print(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, ensure_ascii=False, default=str))
    return 0 if payload.get("ok") is not False else 2


def _explicit_page(args: argparse.Namespace) -> str:
    return str(getattr(args, "page", "") or "").strip()


def _wants_http(page: str) -> bool:
    """Overview stays a disk read. Other pages include the read-only health checks."""
    return str(page or "") not in ("", "overview")


def _snapshot(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "snapshot", None):
        return load_snapshot_file(Path(args.snapshot))
    inventory = Path(args.inventory) if getattr(args, "inventory", None) else None
    return live_snapshot(
        inventory=inventory,
        http=_wants_http(_explicit_page(args)),
        tokens=_explicit_page(args) == "usage",
    )


def refresh_world(args: argparse.Namespace, page: str = "overview") -> dict[str, Any]:
    """Reload catalog, capabilities, usage, and probes for the page on screen."""
    wanted = str(page or "overview")
    if getattr(args, "snapshot", None):
        snap = load_snapshot_file(Path(args.snapshot))
    else:
        inventory = Path(args.inventory) if getattr(args, "inventory", None) else None
        snap = live_snapshot(inventory=inventory, http=_wants_http(wanted), tokens=wanted == "usage")
    world = build_world(snap)
    world, _sel = apply_selection(
        world,
        getattr(args, "layout_id", None),
        getattr(args, "scheme", None),
    )
    return world


def dump_payload(args: argparse.Namespace) -> dict[str, Any]:
    snap = _snapshot(args)
    world = build_world(snap)
    world, sel = apply_selection(
        world,
        getattr(args, "layout_id", None) or None,
        getattr(args, "scheme", None) or None,
    )
    page = _explicit_page(args) or "overview"
    view = page_view(world, page)
    view["ok"] = True
    view["redirect"] = False
    view["entry"] = "silvia-dashboard"
    view["mode"] = "dump"
    view["page_ids"] = page_ids()
    view["page_names"] = [p["title"] for p in page_list()]
    view["game_entity_ids"] = list(view.get("entity_ids") or [])
    view["game_labels"] = list(view.get("game_labels") or [])
    diagrams = view.get("diagrams") or {}
    view["diagram_sections"] = diagrams.get("section_ids") or ["running", "available", "giant"]
    view["live_diagrams"] = diagrams
    running = list(diagrams.get("running") or [])
    available = list(diagrams.get("available") or [])
    view["running_minimized"] = [t.get("minimized") for t in running]
    view["running_previews"] = [t.get("preview") for t in running]
    if running:
        view["running_expanded"] = expand_tree(running[0])
    view["available_categories"] = sorted({str(t.get("category") or "") for t in available})
    view["available_tags"] = sorted({tag for t in available for tag in (t.get("tags") or [])})
    giant = diagrams.get("giant") or {}
    view["giant_minimized"] = giant.get("minimized")
    view["giant_has_preview"] = giant.get("has_preview")
    view["giant_id"] = giant.get("id")
    view["layout_id"] = sel["layout_id"]
    view["scheme"] = sel["scheme"]
    tokens = paint_tokens(sel["scheme"])
    view["background"] = tokens["background"]
    view["accent"] = tokens["accent"]
    view["chrome"] = tokens["chrome"]
    view["text"] = tokens["text"]
    view["outline"] = tokens["outline"]
    view["edge"] = tokens["edge"]
    view["card"] = tokens["card"]
    view["list_fill"] = tokens["card"]
    view["heading"] = tokens["heading"]
    view["muted"] = tokens["muted"]
    view["interior_header"] = tokens["interior_header"]
    view["interior_body"] = tokens["interior_body"]
    view["interior_inset"] = tokens["interior_inset"]
    view["active_border"] = tokens["active_border"]
    view["active_title"] = tokens["active_title"]
    view["paint"] = tokens
    collapsed = list(getattr(args, "collapse", None) or [])
    shown = diagrams_view(
        world.get("diagrams") or {},
        section=sel.get("section") or "giant",
        scheme=sel["scheme"],
        collapsed=collapsed,
    )
    view["graphic"] = shown.get("graphic") or layout_tree(tree_root(giant), scheme=sel["scheme"], collapsed=collapsed)
    if running:
        view["running_graphic"] = layout_tree(tree_root(view["running_expanded"]), scheme=sel["scheme"])
    view["geometry_key"] = geometry_key(view["graphic"])
    graphic = view["graphic"]
    view["radius"] = graphic.get("radius") or graphic.get("box", {}).get("radius")
    view["collapsible_ids"] = graphic.get("collapsible_ids") or []
    view["collapsed_ids"] = graphic.get("collapsed_ids") or []
    view["ltr"] = parents_left_of_children(graphic)
    view["curved_edges"] = bool(graphic.get("edges")) and all(is_curved_edge(e) for e in graphic.get("edges") or [])
    view["content_width"] = graphic.get("content_width")
    view["content_height"] = graphic.get("content_height")
    view["overflow_2axis_small"] = viewport_overflow(graphic, 200, 120)
    view["overflow_2axis_large"] = viewport_overflow(graphic, 100000, 100000)
    view["overflow_small"] = list_overflow(max(len(view.get("view_entities") or []), 40), 80)
    view["overflow_large"] = list_overflow(max(len(view.get("view_entities") or []), 40), 4000)
    systems = overview_systems()
    view["systems"] = systems
    view["system_ids"] = [row["id"] for row in systems]
    view["overview"] = {"redirect": False, "systems": systems, "system_ids": view["system_ids"]}
    view["redirect"] = False
    usage = view.get("usage") or snap.get("usage") or {}
    if isinstance(usage, dict):
        view["usage"] = usage
        view["usage_tier"] = usage.get("subscription_tier")
        view["usage_percent"] = usage.get("credit_usage_percent")
        view["usage_remaining"] = usage.get("remaining_percent")
        view["usage_breakdown"] = list(usage.get("breakdown") or [])
        view["usage_products"] = list(usage.get("products") or [])
        view["usage_week_start"] = usage.get("period_start")
        view["usage_week_end"] = usage.get("period_end")
        view["usage_period_end"] = usage.get("period_end")
        view["usage_as_of"] = usage.get("fetched_at")
        view["usage_week_start_label"] = view.get("usage_week_start_label")
        view["usage_week_end_label"] = view.get("usage_week_end_label")
        view["usage_as_of_label"] = view.get("usage_as_of_label")
        view["usage_week_label"] = view.get("usage_week_label")
    return view


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="silvia-dashboard")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_dump = sub.add_parser("dump", help="Snapshot pages + game world (no GUI)")
    p_dump.add_argument("--snapshot", default="")
    p_dump.add_argument("--inventory", default="")
    p_dump.add_argument("--page", default="")
    p_dump.add_argument("--layout-id", dest="layout_id", default=DEFAULT_LAYOUT_ID)
    p_dump.add_argument("--scheme", default=DEFAULT_SCHEME)
    p_dump.add_argument("--collapse", action="append", default=[])

    p_launch = sub.add_parser("launch", help="Windows window, or --dump for snapshot")
    p_launch.add_argument("--dump", action="store_true")
    p_launch.add_argument("--snapshot", default="")
    p_launch.add_argument("--inventory", default="")
    p_launch.add_argument("--page", default="")
    p_launch.add_argument("--layout-id", dest="layout_id", default=DEFAULT_LAYOUT_ID)
    p_launch.add_argument("--scheme", default=DEFAULT_SCHEME)
    p_launch.add_argument("--tray", action="store_true", help="Start hidden in the notification area")

    sub.add_parser("pages", help="List page ids")

    p_sw = sub.add_parser("switch")
    p_sw.add_argument("--page", required=True)
    p_sw.add_argument("--snapshot", default="")
    p_sw.add_argument("--inventory", default="")

    p_ins = sub.add_parser("inspect")
    p_ins.add_argument("--id", required=True)
    p_ins.add_argument("--snapshot", default="")
    p_ins.add_argument("--inventory", default="")

    p_ev = sub.add_parser("evolve")
    p_ev.add_argument("--snapshot", required=True)
    p_ev.add_argument("--remove", action="append", default=[])
    p_ev.add_argument("--add-id", default="")
    p_ev.add_argument("--add-name", default="")
    p_ev.add_argument("--add-category", default="CLIs")

    p_shot = sub.add_parser("screenshot")
    p_shot.add_argument("--out", required=True)
    p_shot.add_argument("--snapshot", default="")
    p_shot.add_argument("--inventory", default="")
    p_shot.add_argument("--layout-id", dest="layout_id", default=DEFAULT_LAYOUT_ID)
    p_shot.add_argument("--scheme", default=DEFAULT_SCHEME)
    p_shot.add_argument("--page", default="")

    p_ly = sub.add_parser("layout")
    p_ly.add_argument("--snapshot", default="")
    p_ly.add_argument("--inventory", default="")
    p_ly.add_argument("--section", default="giant")
    p_ly.add_argument("--expand", default="")
    p_ly.add_argument("--layout-id", dest="layout_id", default=DEFAULT_LAYOUT_ID)
    p_ly.add_argument("--scheme", default=DEFAULT_SCHEME)
    p_ly.add_argument("--collapse", action="append", default=[])

    p_ov = sub.add_parser("overflow")
    p_ov.add_argument("--count", type=int, required=True)
    p_ov.add_argument("--viewport", type=int, required=True)
    p_ov.add_argument("--row", type=int, default=22)

    p_dg = sub.add_parser("diagrams")
    p_dg.add_argument("--snapshot", default="")
    p_dg.add_argument("--inventory", default="")
    p_dg.add_argument("--section", default="running")
    p_dg.add_argument("--query", default="")
    p_dg.add_argument("--category", default="")
    p_dg.add_argument("--tag", default="")
    p_dg.add_argument("--expand", default="")

    sub.add_parser("imagine-inventory", help="Scan Imagine 5x5 layout drafts folder")
    p_open = sub.add_parser("imagine-open", help="Open Imagine drafts folder in Explorer")
    p_open.add_argument("--folder", default="")

    p_up = sub.add_parser("giant-update")
    p_up.add_argument("--snapshot", required=True)
    p_up.add_argument("--remove", default="")
    p_up.add_argument("--add-id", default="")
    p_up.add_argument("--add-name", default="")
    p_up.add_argument("--add-parent", default="giant.active")
    p_up.add_argument("--edit-id", default="")
    p_up.add_argument("--edit-name", default="")

    args = parser.parse_args(argv)

    if args.cmd in ("dump",) or (args.cmd == "launch" and args.dump):
        return _print(dump_payload(args))

    if args.cmd == "pages":
        return _print(pages_payload(page_list(), page_ids()))

    if args.cmd == "switch":
        if is_system(args.page):
            detail = open_system(args.page)
            detail["page_ids"] = page_ids()
            return _print(detail)
        world = build_world(_snapshot(args))
        view = page_view(world, args.page)
        view["ok"] = True
        view["redirect"] = False
        return _print(view)

    if args.cmd == "inspect":
        if is_system(args.id):
            detail = open_system(args.id)
            detail["page_ids"] = page_ids()
            detail["selected"] = {
                "id": detail["id"],
                "name": detail["name"],
                "title": detail["title"],
                "path": detail["path"],
                "presence": detail["presence"],
                "purpose": detail["purpose"],
                "body": detail["body"],
            }
            return _print(detail)
        world = build_world(_snapshot(args))
        world = select_entity(world, args.id)
        return _print({"ok": True, "redirect": False, "selected": world.get("selected"), "page_ids": page_ids()})

    if args.cmd == "evolve":
        snap = load_snapshot_file(Path(args.snapshot))
        added = []
        if args.add_id:
            added.append({"id": args.add_id, "name": args.add_name or args.add_id, "category": args.add_category})
        world = evolve(snap, add=added, remove=list(args.remove or []))
        world["ok"] = True
        world["redirect"] = False
        return _print(world)

    if args.cmd == "imagine-inventory":
        from imagine_inventory import load_inventory

        report = load_inventory()
        return _print({k: v for k, v in report.items() if k not in ("items", "valid")} | {"ok": report.get("count") == 25})

    if args.cmd == "imagine-open":
        from imagine_inventory import DEFAULT_DIR, open_folder

        folder = Path(args.folder) if args.folder else DEFAULT_DIR
        return _print(open_folder(folder))

    if args.cmd == "screenshot":
        page = _explicit_page(args)
        if page in ("", "overview"):
            result = render_systems_png(overview_systems(), args.out)
        else:
            world = build_world(_snapshot(args))
            world, _sel = apply_selection(
                world,
                getattr(args, "layout_id", None),
                getattr(args, "scheme", None),
            )
            result = capture_world(world, args.out)
        result["redirect"] = False
        result["page_ids"] = page_ids()
        return _print(result)

    if args.cmd == "layout":
        world = build_world(_snapshot(args))
        diagrams = world.get("diagrams") or {}
        if args.section == "giant":
            graphic = layout_tree(
                tree_root(diagrams.get("giant") or {}),
                scheme=getattr(args, "scheme", None) or DEFAULT_SCHEME,
                collapsed=list(getattr(args, "collapse", None) or []),
            )
        else:
            items = list(diagrams.get(args.section) or [])
            target = items[0] if items else {}
            if args.expand:
                for it in items:
                    if it.get("id") == args.expand:
                        target = expand_tree(it)
                        break
            else:
                target = expand_tree(target) if target else {}
            graphic = layout_tree(tree_root(target), scheme=getattr(args, "scheme", None) or DEFAULT_SCHEME)
        sel = select(getattr(args, "layout_id", None), getattr(args, "scheme", None))
        graphic["ok"] = True
        graphic["redirect"] = False
        graphic["page_ids"] = page_ids()
        graphic["layout_id"] = sel["layout_id"]
        graphic["scheme"] = sel["scheme"]
        return _print(graphic)

    if args.cmd == "overflow":
        return _print({"ok": True, **list_overflow(args.count, args.viewport, args.row)})

    if args.cmd == "diagrams":
        world = build_world(_snapshot(args))
        view = diagrams_view(
            world.get("diagrams") or {},
            section=args.section,
            query=args.query,
            category=args.category,
            tag=args.tag,
            expand_id=args.expand or None,
        )
        view["ok"] = True
        view["redirect"] = False
        view["page_ids"] = page_ids()
        return _print(view)

    if args.cmd == "giant-update":
        world = build_world(load_snapshot_file(Path(args.snapshot)))
        giant = world.get("diagrams", {}).get("giant") or {}
        add = None
        edit = None
        if args.add_id:
            add = {"id": args.add_id, "name": args.add_name or args.add_id, "parent": args.add_parent, "kind": "item"}
        if args.edit_id:
            edit = {"id": args.edit_id, "name": args.edit_name or args.edit_id}
        updated = update_giant(giant, add=add, remove=args.remove or None, edit=edit)
        return _print({"ok": True, "redirect": False, "giant": updated, "minimized": updated.get("minimized")})

    if args.cmd == "launch":
        log_path = Path(__file__).resolve().parent / "launch-debug.log"
        try:
            from app import run_window

            def _refresh(page: str = "overview") -> dict:
                return refresh_world(args, page)

            world = build_world(_snapshot(args))
            world, sel = apply_selection(
                world,
                getattr(args, "layout_id", None),
                getattr(args, "scheme", None),
            )
            page = _explicit_page(args) or "overview"
            world = switch_page(world, page)
            run_window(world, on_refresh=_refresh, start_in_tray=bool(getattr(args, "tray", False)))
            log_path.write_text("launch-ok\n", encoding="utf-8")
            return 0
        except Exception:
            import traceback

            log_path.write_text(traceback.format_exc(), encoding="utf-8")
            raise

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
