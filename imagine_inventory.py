"""Scan the Imagine drafts folder: 25 rasters grouped 5 layouts x 5 schemes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path.home() / ".grok" / "silvia-dashboard" / "imagine-drafts"


def _magic(path: Path) -> str:
    data = path.read_bytes()[:8]
    if data[:2] == b"\xff\xd8":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return "unknown"


def load_inventory(folder: Path | None = None) -> dict[str, Any]:
    root = Path(folder) if folder else DEFAULT_DIR
    sidecar = root / "inventory.json"
    if not sidecar.is_file():
        return {"ok": False, "folder": str(root), "count": 0, "items": [], "error": "missing inventory.json"}
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    items = []
    for rec in data.get("items") or []:
        path = root / str(rec.get("file") or "")
        kind = _magic(path) if path.is_file() else "missing"
        items.append(
            {
                **rec,
                "path": str(path),
                "exists": path.is_file(),
                "bytes": path.stat().st_size if path.is_file() else 0,
                "kind": kind,
            }
        )
    layouts = {it.get("layout_id") for it in items}
    pairs = {(it.get("layout_n"), it.get("scheme_n")) for it in items}
    valid = [it for it in items if it["exists"] and it["kind"] in ("jpeg", "png") and it["bytes"] > 100]
    return {
        "ok": True,
        "folder": str(root),
        "count": len(valid),
        "listed": len(items),
        "layouts": len(layouts),
        "pairs": len(pairs),
        "grid_5x5": len(layouts) == 5 and len(pairs) == 25,
        "items": items,
        "valid": valid,
    }


def open_folder(folder: Path | None = None) -> dict[str, Any]:
    import subprocess

    root = Path(folder) if folder else DEFAULT_DIR
    proc = subprocess.run(
        ["explorer.exe", str(root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )
    return {
        "ok": proc.returncode in (0, 1),
        "folder": str(root),
        "exit": proc.returncode,
        "out": (proc.stdout or "")[:200],
        "err": (proc.stderr or "")[:200],
    }
