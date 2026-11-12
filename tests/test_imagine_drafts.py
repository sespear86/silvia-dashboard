"""Drive shipped Imagine-drafts inventory on the real folder, not mocks."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from imagine_inventory import DEFAULT_DIR, load_inventory  # noqa: E402


def test_imagine_drafts_folder_is_5x5_valid_rasters():
    report = load_inventory(DEFAULT_DIR)
    assert report["ok"] is True
    assert Path(report["folder"]).is_dir()
    assert report["count"] == 25
    assert report["listed"] == 25
    assert report["layouts"] == 5
    assert report["pairs"] == 25
    assert report["grid_5x5"] is True
    kinds = {it["kind"] for it in report["valid"]}
    assert kinds <= {"jpeg", "png"}
    assert kinds
    files = {it["file"] for it in report["valid"]}
    assert all(name.startswith("layout-") for name in files)
    layout_ns = {it["layout_n"] for it in report["valid"]}
    scheme_ns = {it["scheme_n"] for it in report["valid"]}
    assert layout_ns == {1, 2, 3, 4, 5}
    assert scheme_ns == {1, 2, 3, 4, 5}
    for it in report["valid"]:
        assert it["bytes"] > 1000
        header = Path(it["path"]).read_bytes()[:3]
        assert header[:2] == b"\xff\xd8" or header[:4] == b"\x89PNG"


def test_imagine_inventory_cli_if_present():
    main = HERE / "__main__.py"
    if not main.is_file():
        return
    env = os.environ.copy()
    env["PYTHONPATH"] = str(HERE) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, str(main), "imagine-inventory"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        cwd=str(HERE),
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "25" in proc.stdout
