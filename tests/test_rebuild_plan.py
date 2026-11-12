"""The rebuild plan matches the shipped pages and inventory, and does not change them."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from systems import INVENTORY  # noqa: E402
from world import page_list  # noqa: E402

PLAN = HERE / "REBUILD-PLAN.md"
MAIN = HERE / "__main__.py"

FORBIDDEN = (
    "second dashboard app",
    "new listen port",
    "new tcp listener",
    "host this ui on the pi",
)


def _text() -> str:
    return PLAN.read_text(encoding="utf-8")


def test_rebuild_plan_matches_shipped_surface_and_forbids_a_second_app():
    assert PLAN.is_file()
    text = _text()
    opening = "\n".join(text.splitlines()[:12])
    assert "C:\\Users\\Irika\\.grok\\silvia-dashboard\\REBUILD-PLAN.md" in opening
    assert "Silvia Dashboard rebuild plan" in opening
    assert "later prompt" in opening.lower()
    assert 'python "$HOME/.grok/silvia-dashboard/__main__.py"' in text
    for token in ("dump", "pages", "switch", "inspect", "launch", "redirect", "absent", "orchestrator"):
        assert token in text
    assert r"C:\Users\Irika\OneDrive\Desktop\Silvia Dashboard.lnk" in text
    for page in page_list():
        assert page["title"] in text
        assert page["id"] in text
    for row in INVENTORY:
        assert row["id"] in text
        assert row["name"] in text
    blob = text.lower()
    assert "does not choose a second dashboard app" in blob
    assert "does not choose" in blob and "new tcp listener" in blob
    assert "hosting this ui on the pi" in blob
    for line in text.splitlines():
        low = line.lower()
        if any(mark in low for mark in ("do not", "does not choose", "must not", "never")):
            continue
        for needle in FORBIDDEN:
            assert needle not in low, line


def test_pages_and_silvia_inspect_are_unchanged():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(HERE) + os.pathsep + env.get("PYTHONPATH", "")

    def run(args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(MAIN), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
            cwd=str(HERE),
            env=env,
        )

    pages = run(["pages"])
    assert pages.returncode == 0, pages.stderr + pages.stdout
    body = json.loads(pages.stdout)
    assert body.get("redirect") is False
    titles = {page["title"] for page in page_list()}
    assert titles <= {page["title"] for page in body["pages"]}
    inspected = run(["inspect", "--id", "silvia"])
    assert inspected.returncode == 0, inspected.stderr + inspected.stdout
    detail = json.loads(inspected.stdout)
    silvia = next(row for row in INVENTORY if row["id"] == "silvia")
    assert detail["title"] == silvia["name"]
    assert detail["path"] == silvia["path"]
    assert detail["presence"] is True
    assert "butler" in detail["purpose"]
