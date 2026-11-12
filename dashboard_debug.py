"""Short diagnostic lines for the Silvia dashboard.

The sessions page shows the newest lines when Debug is on. The same lines
are appended to debug.log so a later look can see why a picture closed.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

_lock = threading.Lock()
_lines: list[str] = []
_MAX = 40


def log_path() -> Path:
    override = os.environ.get("SILVIA_DASHBOARD_DEBUG_LOG", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".grok" / "silvia-dashboard" / "debug.log"


def note(event: str, detail: str = "") -> None:
    """Record one diagnostic line. Secrets are not accepted here."""
    stamp = time.strftime("%H:%M:%S")
    text = f"{stamp} {event}"
    extra = str(detail or "").replace("\n", " ").strip()
    if extra:
        text += " " + extra[:300]
    with _lock:
        _lines.append(text)
        del _lines[:-_MAX]
    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except OSError:
        return


def recent(limit: int = 12) -> list[str]:
    keep = max(1, limit)
    with _lock:
        lines = list(_lines[-keep:])
    if lines:
        return lines
    try:
        stored = log_path().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return stored[-keep:]
