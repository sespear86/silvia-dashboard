"""Read-only inventory of the jointly built systems.

Presence is only Path.exists on that system's tree. A missing path reports
absent. This module does not start those systems and does not bind a port.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

# id, display name, absolute tree, purpose token. Presence is not stored here.
INVENTORY: tuple[dict[str, str], ...] = (
    {
        "id": "silvia",
        "name": "Silvia",
        "path": r"C:\Users\Irika\.grok\silvia",
        "token": "butler",
        "purpose": "Standing butler for the local Silvia stack.",
    },
    {
        "id": "si-butler",
        "name": "SI Butler voice",
        "path": r"C:\Users\Irika\si-butler",
        "token": "voice",
        "purpose": "Separate voice stack beside the butler.",
    },
    {
        "id": "silvia-android",
        "name": "Silvia Android",
        "path": r"C:\Users\Irika\.grok\silvia-android",
        "token": "Android",
        "purpose": "Silvia Android remake of the client.",
    },
    {
        "id": "mempalace",
        "name": "MemPalace",
        "path": r"C:\Users\Irika\.grok\mempalace-stack",
        "token": "memory",
        "purpose": "Lossless memory drawers for quotes and decisions.",
    },
    {
        "id": "resource-list",
        "name": "Resource catalog",
        "path": r"C:\Users\Irika\.grok\resource-list",
        "token": "catalog",
        "purpose": "Durable resource catalog of tools on this machine.",
    },
    {
        "id": "workflow-memory",
        "name": "Workflow memory",
        "path": r"C:\Users\Irika\.grok\workflow-memory",
        "token": "playbook",
        "purpose": "Stored playbook of task workflows that worked.",
    },
    {
        "id": "orchestrator",
        "name": "Orchestrator",
        "path": r"C:\Users\Irika\.grok\orchestrator",
        "token": "orchestrator",
        "purpose": "Bounded orchestrator that watches the local stack.",
    },
    {
        "id": "pi-device",
        "name": "Pi device",
        "path": r"C:\Users\Irika\.grok\pi-device",
        "token": "Pi",
        "purpose": "Pi device relay. New hosting goes through the Pi.",
    },
    {
        "id": "money-loop",
        "name": "Source Supply money-loop",
        "path": r"C:\Users\Irika\.grok\money-loop",
        "token": "money-loop",
        "purpose": "Source Supply money-loop for the legal income cycle.",
    },
    {
        "id": "source-supply-site",
        "name": "Source Supply site",
        "path": r"C:\Users\Irika\.grok\source-supply-site",
        "token": "site",
        "purpose": "Public Source Supply site for the income loop.",
    },
    {
        "id": "grok-bots",
        "name": "Grok bots",
        "path": r"C:\Users\Irika\.grok\grok-bot-roster",
        "token": "bots",
        "purpose": "Roster of Grok bots on this machine.",
    },
    {
        "id": "goal-split",
        "name": "Goal split",
        "path": r"C:\Users\Irika\.grok\goal-split",
        "token": "goal-split",
        "purpose": "Shipped goal-split parser for one prompt or several goals.",
    },
    {
        "id": "portion-plan",
        "name": "Portion plan",
        "path": r"C:\Users\Irika\.grok\portion-plan",
        "token": "portion",
        "purpose": "Splits a large project into a work portion.",
    },
    {
        "id": "family-stack",
        "name": "Family Grok stack",
        "path": r"C:\Users\Irika\.grok\family-stack",
        "token": "family",
        "purpose": "Published family stack for other family PCs.",
    },
    {
        "id": "dualboot-memory",
        "name": "Dual-boot memory share",
        "path": r"C:\Users\Irika\.grok\dualboot-memory",
        "token": "dual-boot",
        "purpose": "Windows and Fedora dual-boot memory share.",
    },
    {
        "id": "steam-lan",
        "name": "Steam LAN host check",
        "path": r"C:\Users\Irika\.grok\steam-lan-host-check",
        "token": "Steam",
        "purpose": "Steam LAN host check for port 27040.",
    },
    {
        "id": "source-bus",
        "name": "Source bus",
        "path": r"C:\Users\Irika\.grok\source-bus",
        "token": "bus",
        "purpose": "Source bus for Operator, Scribe, Herald, Treasurer, and Counsel.",
    },
    {
        "id": "desk",
        "name": "Desk",
        "path": r"C:\Users\Irika\.grok\desk",
        "token": "bench",
        "purpose": "Desk bench for the local work surface.",
    },
    {
        "id": "edge-check",
        "name": "Edge check",
        "path": r"C:\Users\Irika\.grok\edge-check",
        "token": "edge-check",
        "purpose": "Local edge-check ledger before a fast-moving dependency is used.",
    },
    {
        "id": "review-board",
        "name": "Review board",
        "path": r"C:\Users\Irika\.grok\review-board-phase0",
        "token": "review",
        "purpose": "Phase 0 review sidecar in front of the agent.",
    },
    {
        "id": "specialist-models",
        "name": "Specialist models",
        "path": r"C:\Users\Irika\.grok\specialist-models",
        "token": "specialist",
        "purpose": "Local specialist model workshop.",
    },
    {
        "id": "afterfive",
        "name": "AfterFive",
        "path": r"C:\Users\Irika\afterfive",
        "token": "AfterFive",
        "purpose": "AfterFive garage-door directory, isolated from Source Supply.",
    },
    {
        "id": "sable",
        "name": "Sable",
        "path": r"C:\Users\Irika\sable",
        "token": "Sable",
        "purpose": "Sable index of robots-first public manufacturers.",
    },
    {
        "id": "ridgeready",
        "name": "RidgeReady",
        "path": r"C:\Users\Irika\RidgeReady",
        "token": "RidgeReady",
        "purpose": "RidgeReady local HTML app.",
    },
)

_BY_ID: dict[str, dict[str, str]] = {row["id"]: row for row in INVENTORY}
if len(_BY_ID) != len(INVENTORY):
    raise RuntimeError("duplicate system id in inventory")
for _spec in INVENTORY:
    if _spec["token"] not in _spec["purpose"]:
        raise RuntimeError(f"purpose for {_spec['id']} does not contain {_spec['token']}")


def probe_presence(path: str | Path) -> str:
    """Read-only. 'present' when the path is on disk, otherwise 'absent'."""
    if Path(path).exists():
        return "present"
    return "absent"


def presence_value(path: str | Path) -> bool | str:
    """True only when the path exists. A missing path reports absent."""
    if probe_presence(path) == "present":
        return True
    return "absent"


def system_ids() -> list[str]:
    return [row["id"] for row in INVENTORY]


def is_system(system_id: str) -> bool:
    return str(system_id or "") in _BY_ID


def overview_systems() -> list[dict[str, Any]]:
    """One overview row per inventory id. Presence comes from probe_presence."""
    rows: list[dict[str, Any]] = []
    for spec in INVENTORY:
        presence = presence_value(spec["path"])
        rows.append(
            {
                "id": spec["id"],
                "name": spec["name"],
                "display_name": spec["name"],
                "title": spec["name"],
                "path": spec["path"],
                "presence": presence,
                "purpose": spec["purpose"],
                "token": spec["token"],
                "target": spec["id"],
                "nav": spec["id"],
            }
        )
    return rows


def open_system(system_id: str, *, path: str | Path | None = None) -> dict[str, Any]:
    """Detail view for one system. `path` overrides the inventory tree (absent case)."""
    spec = _BY_ID.get(str(system_id or ""))
    if spec is None:
        known = system_ids()
        raise KeyError(f"unknown system: {system_id}; known={known}")
    reported = spec["path"] if path is None else str(Path(path))
    presence = presence_value(reported)
    purpose = spec["purpose"]
    presence_line = "absent" if presence == "absent" else "true"
    body = "\n".join(
        [
            spec["name"],
            reported,
            f"presence: {presence_line}",
            f"purpose: {purpose}",
        ]
    )
    return {
        "ok": True,
        "redirect": False,
        "id": spec["id"],
        "name": spec["name"],
        "display_name": spec["name"],
        "title": spec["name"],
        "page_title": spec["name"],
        "path": reported,
        "presence": presence,
        "purpose": purpose,
        "token": spec["token"],
        "body": body,
    }


def navigation_targets() -> list[dict[str, str]]:
    """Each system can be selected with inspect --id <target>."""
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "title": row["name"],
            "target": row["id"],
            "via": "inspect",
            "select": row["id"],
            "command": "inspect",
        }
        for row in INVENTORY
    ]


def pages_payload(pages: list[dict[str, Any]], page_ids: list[str]) -> dict[str, Any]:
    """Pages command body: existing Silvia pages plus a target per system."""
    systems = overview_systems()
    navigation = navigation_targets()
    enriched: list[dict[str, Any]] = []
    for page in pages:
        item = dict(page)
        if item.get("id") == "overview":
            item["systems"] = [row["id"] for row in systems]
            item["navigation"] = navigation
        enriched.append(item)
    return {
        "ok": True,
        "redirect": False,
        "pages": enriched,
        "page_ids": list(page_ids),
        "systems": systems,
        "system_ids": [row["id"] for row in systems],
        "navigation": navigation,
    }
