"""Shipped system inventory: probe, overview, and detail navigation.

Calls systems.probe_presence, overview_systems, and open_system. Presence is
compared to Path.exists, not a fixed literal.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from systems import (  # noqa: E402
    INVENTORY,
    is_system,
    navigation_targets,
    open_system,
    overview_systems,
    pages_payload,
    presence_value,
    probe_presence,
)
from world import build_world, page_ids, page_list, page_view, select_entity  # noqa: E402

MAIN = HERE / "__main__.py"

# Assumed scope. The dashboard must name each of these, not a private copy of the probe.
EXPECTED: tuple[tuple[str, str, str, str], ...] = (
    ("silvia", "Silvia", r"C:\Users\Irika\.grok\silvia", "butler"),
    ("si-butler", "SI Butler voice", r"C:\Users\Irika\si-butler", "voice"),
    ("silvia-android", "Silvia Android", r"C:\Users\Irika\.grok\silvia-android", "Android"),
    ("mempalace", "MemPalace", r"C:\Users\Irika\.grok\mempalace-stack", "memory"),
    ("resource-list", "Resource catalog", r"C:\Users\Irika\.grok\resource-list", "catalog"),
    ("workflow-memory", "Workflow memory", r"C:\Users\Irika\.grok\workflow-memory", "playbook"),
    ("orchestrator", "Orchestrator", r"C:\Users\Irika\.grok\orchestrator", "orchestrator"),
    ("pi-device", "Pi device", r"C:\Users\Irika\.grok\pi-device", "Pi"),
    ("money-loop", "Source Supply money-loop", r"C:\Users\Irika\.grok\money-loop", "money-loop"),
    ("source-supply-site", "Source Supply site", r"C:\Users\Irika\.grok\source-supply-site", "site"),
    ("grok-bots", "Grok bots", r"C:\Users\Irika\.grok\grok-bot-roster", "bots"),
    ("goal-split", "Goal split", r"C:\Users\Irika\.grok\goal-split", "goal-split"),
    ("portion-plan", "Portion plan", r"C:\Users\Irika\.grok\portion-plan", "portion"),
    ("family-stack", "Family Grok stack", r"C:\Users\Irika\.grok\family-stack", "family"),
    ("dualboot-memory", "Dual-boot memory share", r"C:\Users\Irika\.grok\dualboot-memory", "dual-boot"),
    ("steam-lan", "Steam LAN host check", r"C:\Users\Irika\.grok\steam-lan-host-check", "Steam"),
    ("source-bus", "Source bus", r"C:\Users\Irika\.grok\source-bus", "bus"),
    ("desk", "Desk", r"C:\Users\Irika\.grok\desk", "bench"),
    ("edge-check", "Edge check", r"C:\Users\Irika\.grok\edge-check", "edge-check"),
    ("review-board", "Review board", r"C:\Users\Irika\.grok\review-board-phase0", "review"),
    ("specialist-models", "Specialist models", r"C:\Users\Irika\.grok\specialist-models", "specialist"),
    ("afterfive", "AfterFive", r"C:\Users\Irika\afterfive", "AfterFive"),
    ("sable", "Sable", r"C:\Users\Irika\sable", "Sable"),
    ("ridgeready", "RidgeReady", r"C:\Users\Irika\RidgeReady", "RidgeReady"),
)

SILVIA_PAGES = {
    "overview",
    "butler-host",
    "memory",
    "catalog",
    "orchestrator",
    "usage",
    "live-diagrams",
}


def run_cli(args: list[str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(HERE) + os.pathsep + env.get("PYTHONPATH", "")
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


def _assert_detail(detail: dict, eid: str, name: str, path: str, token: str, presence: object) -> None:
    assert detail["title"] == name
    assert detail["name"] == name
    assert detail["display_name"] == name
    assert detail["path"] == path
    assert detail["presence"] == presence
    assert detail["purpose"]
    assert token in detail["purpose"]
    assert path in detail["body"]
    assert token in detail["body"]
    assert detail.get("redirect") is False
    if presence == "absent":
        assert "absent" in detail["body"]
    else:
        assert presence is True
        assert "presence: true" in detail["body"]


def test_24_row_inventory_is_the_assumed_scope():
    assert len(INVENTORY) == len(EXPECTED) == 24
    assert [row["id"] for row in INVENTORY] == [row[0] for row in EXPECTED]
    for spec, expected in zip(INVENTORY, EXPECTED):
        eid, name, path, token = expected
        assert spec["id"] == eid
        assert spec["name"] == name
        assert spec["path"] == path
        assert spec["token"] == token
        assert token in spec["purpose"]
        assert is_system(eid)


def test_probe_reports_absent_only_when_path_is_missing(tmp_path: Path):
    present = tmp_path / "on-disk"
    present.mkdir()
    missing = tmp_path / "not-a-system-tree"
    assert present.exists()
    assert not missing.exists()
    assert probe_presence(present) == "present"
    assert presence_value(present) is True
    assert probe_presence(missing) == "absent"
    assert presence_value(missing) == "absent"
    detail = open_system("silvia", path=missing)
    _assert_detail(detail, "silvia", "Silvia", str(missing), "butler", "absent")


def test_overview_and_detail_follow_the_probe():
    rows = overview_systems()
    assert [row["id"] for row in rows] == [row[0] for row in EXPECTED]
    by_id = {row["id"]: row for row in rows}
    for eid, name, path, token in EXPECTED:
        row = by_id[eid]
        on_disk = Path(path).exists()
        probed = probe_presence(path)
        assert probed == ("present" if on_disk else "absent")
        presence = True if on_disk else "absent"
        assert presence_value(path) == presence
        assert row["presence"] == presence
        assert row["name"] == name
        assert row["title"] == name
        assert row["path"] == path
        assert token in row["purpose"]
        assert row["target"] == eid
        detail = open_system(eid)
        _assert_detail(detail, eid, name, path, token, presence)
        again = open_system(eid)
        assert again["title"] == detail["title"]
        assert again["path"] == detail["path"]
        assert again["presence"] == detail["presence"]


def test_overview_page_names_every_system_and_selects_detail():
    world = build_world({})
    view = page_view(world, "overview")
    assert view["page"] == "overview"
    assert view.get("redirect") is False
    assert view["system_ids"] == [row[0] for row in EXPECTED]
    ids = {row["id"] for row in view["systems"]}
    assert ids == {row[0] for row in EXPECTED}
    for eid, name, path, token in EXPECTED:
        picked = select_entity(world, eid)
        detail = picked["detail"]
        assert detail["title"] == name
        assert detail["path"] == path
        assert token in detail["purpose"]
        assert detail["presence"] == presence_value(path)
    assert SILVIA_PAGES <= set(page_ids())
    targets = {item["target"] for item in navigation_targets()}
    assert targets == {row[0] for row in EXPECTED}
    payload = pages_payload(page_list(), page_ids())
    assert payload["redirect"] is False
    assert SILVIA_PAGES <= set(payload["page_ids"])
    overview = next(page for page in payload["pages"] if page["id"] == "overview")
    assert set(overview["systems"]) == targets


def test_cli_pages_and_navigation_are_one_shot():
    pages = run_cli(["pages"])
    assert pages.returncode == 0, pages.stderr + pages.stdout
    body = json.loads(pages.stdout)
    assert body["redirect"] is False
    assert SILVIA_PAGES <= set(body["page_ids"])
    assert [row["id"] for row in body["systems"]] == [row[0] for row in EXPECTED]
    targets = {item["target"] for item in body["navigation"]}
    assert targets == {row[0] for row in EXPECTED}
    for eid, name, path, token in EXPECTED:
        inspected = run_cli(["inspect", "--id", eid])
        assert inspected.returncode == 0, inspected.stderr + inspected.stdout
        detail = json.loads(inspected.stdout)
        _assert_detail(detail, eid, name, path, token, presence_value(path))
        switched = run_cli(["switch", "--page", eid])
        assert switched.returncode == 0, switched.stderr + switched.stdout
        via_switch = json.loads(switched.stdout)
        assert via_switch["title"] == detail["title"]
        assert via_switch["path"] == detail["path"]
        assert via_switch["presence"] == detail["presence"]
        assert token in via_switch["purpose"]
        assert via_switch["redirect"] is False
