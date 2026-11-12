"""Load live Silvia + catalog + stack probes into a world snapshot."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

from usage import load_usage

GROK = Path.home() / ".grok"
INVENTORY = GROK / "resource-list" / "inventory.json"
HUB = "http://127.0.0.1:8765/healthz"
PI = "http://192.168.1.235:8870/"
BUTLER = "http://192.168.1.235:8880/healthz"
VOICE = "http://192.168.1.235:8000/api/health"
BOT_EXE = "Grok Bot.exe"


def _http(url: str, timeout: int = 4) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read()[:200].decode("utf-8", "replace")
            ok = 200 <= getattr(resp, "status", 200) < 500
            return {"ok": ok, "url": url, "status": getattr(resp, "status", 200), "body": body}
    except Exception as exc:
        return {"ok": False, "url": url, "status": 0, "body": str(exc)}


def _no_console() -> dict[str, int]:
    """pythonw has no console, so a console child would open its own window."""
    if os.name != "nt":
        return {}
    return {"creationflags": subprocess.CREATE_NO_WINDOW}


def _bot_running() -> bool:
    if os.name != "nt":
        return False
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {BOT_EXE}", "/NH"],
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            **_no_console(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return BOT_EXE.lower() in out.lower()


def _grok_bot_probe() -> dict[str, Any]:
    """HTTP healthz decides ok. Process-up is a field, not a pass."""
    silvia = GROK / "silvia"
    if str(silvia) not in sys.path:
        sys.path.insert(0, str(silvia))
    from hosting import load_config, probe_grok_bot  # shipped Silvia host probe

    rec = probe_grok_bot(load_config())
    if "process" not in rec:
        rec["process"] = _bot_running()
    rec.setdefault("exe", r"C:\Users\Irika\AppData\Local\Programs\Grok Bot\Grok Bot.exe")
    return rec


def load_resources(path: Path | None = None) -> list[dict[str, Any]]:
    inv_path = path or INVENTORY
    if not inv_path.is_file():
        return []
    try:
        data = json.loads(inv_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = data.get("resources") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("id")]


def load_capabilities() -> list[str]:
    silvia_dir = GROK / "silvia"
    if str(silvia_dir) not in sys.path:
        sys.path.insert(0, str(silvia_dir))
    try:
        from silvia import capability_list  # type: ignore
    except Exception:
        return []
    body = capability_list()
    caps = body.get("capabilities") if isinstance(body, dict) else []
    return [str(c) for c in (caps or [])]


def _file_probe(relposix: str) -> dict[str, Any]:
    path = GROK.joinpath(*relposix.split("/"))
    return {"ok": path.is_file(), "path": str(path)}


def load_source_bus() -> dict[str, Any]:
    """Open task.request rows from the shipped bus (palace logstream, not a copy)."""
    bus_dir = GROK / "source-bus"
    if str(bus_dir) not in sys.path:
        sys.path.insert(0, str(bus_dir))
    from bus import open_work  # shipped source-bus

    rec = open_work(limit=50)
    return {
        "ok": bool(rec.get("ok")),
        "open_count": int(rec.get("open_count") or 0),
        "open": list(rec.get("open") or []),
        "path": str(bus_dir / "__main__.py"),
    }


def _skipped_health(url: str = "") -> dict[str, Any]:
    """Health was not checked. ok is None so a skip is not painted as present."""
    row: dict[str, Any] = {"ok": None, "skipped": True}
    if url:
        row["url"] = url
    return row


def load_probes(*, http: bool = True) -> dict[str, Any]:
    """File probes always run. http=False skips hub, Pi, Grok Bot, and source-bus.

    Grok Bot is `_grok_bot_probe` (hosting.probe_grok_bot), not the 4-second `_http` helper.
    """
    if http:
        hub = _http(HUB)
        pi = _http(PI)
        butler = _http(BUTLER)
        voice = _http(VOICE)
        bot = _grok_bot_probe()
        bus = load_source_bus()
    else:
        hub = _skipped_health(HUB)
        pi = _skipped_health(PI)
        butler = _skipped_health(BUTLER)
        voice = _skipped_health(VOICE)
        bot = _skipped_health()
        bus = _skipped_health()
    pi["label"] = "Source presence"
    butler["label"] = "Silvia butler"
    voice["label"] = "Silvia voice"
    orch = (GROK / "orchestrator" / "__main__.py").is_file()
    return {
        "mempalace.hub": hub,
        "grok.bot": bot,
        "pi.lan": pi,
        "silvia.butler": butler,
        "silvia.voice": voice,
        "orchestrator": {"ok": orch, "path": str(GROK / "orchestrator" / "__main__.py")},
        "cli.money_loop": _file_probe("money-loop/__main__.py"),
        "cli.steam_lan": _file_probe("steam-lan-host-check/SteamLanHostCheck.ps1"),
        "app.silvia_android": _file_probe("silvia-android/__main__.py"),
        "cli.source_bus": bus,
    }


def live_snapshot(*, inventory: Path | None = None, http: bool = True, tokens: bool = False) -> dict[str, Any]:
    return {
        "resources": load_resources(inventory),
        "capabilities": load_capabilities(),
        "probes": load_probes(http=http),
        "usage": load_usage(tokens=tokens),
    }


def load_snapshot_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("snapshot must be an object")
    return {
        "resources": list(data.get("resources") or []),
        "capabilities": list(data.get("capabilities") or []),
        "probes": dict(data.get("probes") or {}),
        "running": list(data.get("running") or []),
        "available": list(data.get("available") or []),
        "giant": data.get("giant") if isinstance(data.get("giant"), dict) else None,
        "usage": data.get("usage") if isinstance(data.get("usage"), dict) else {},
    }
