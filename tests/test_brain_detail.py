"""Silvia detail lists the brain registry and does not write it."""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from app import SilviaDashboard, _brain_detail_lines  # noqa: E402
from systems import INVENTORY  # noqa: E402


def test_silvia_detail_lists_a_brain_and_an_empty_registry(tmp_path, monkeypatch):
    directory = tmp_path / "brains"
    directory.mkdir()
    seats = tmp_path / "seats.json"
    (directory / "local-qwen.json").write_text(
        json.dumps(
            {
                "id": "local-qwen",
                "kind": "model",
                "enabled": True,
                "wire": "openai-chat",
                "base_url": "http://127.0.0.1:11434/v1",
                "model": "qwen3.5:2b",
                "auth": {"kind": "none"},
                "residency": "local",
                "capabilities": ["text"],
                "when": "always",
                "timeout_s": 30,
            }
        ),
        encoding="utf-8",
    )
    seats.write_text(json.dumps({"talk": "local-qwen", "voice": None, "specialist": None}), encoding="utf-8")
    monkeypatch.setenv("SILVIA_BRAINS", str(directory))
    monkeypatch.setenv("SILVIA_SEATS", str(seats))
    selected = {
        "id": "silvia",
        "title": "Silvia",
        "name": "Silvia",
        "path": r"C:\Users\Irika\.grok\silvia",
        "purpose": "Standing butler for the local Silvia stack.",
        "presence": True,
    }
    text = SilviaDashboard._format_selected(object(), selected)
    assert "Standing butler" in text
    assert "local-qwen on local openai-chat seat talk" in text
    other = dict(selected, id="resource-list", purpose="Durable resource catalog of tools on this machine.")
    plain = SilviaDashboard._format_selected(object(), other)
    assert "local-qwen" not in plain
    empty = tmp_path / "none"
    empty.mkdir()
    monkeypatch.setenv("SILVIA_BRAINS", str(empty))
    monkeypatch.setenv("SILVIA_SEATS", str(tmp_path / "missing-seats.json"))
    assert _brain_detail_lines() == ["Brains: none"]


def test_silvia_detail_shows_task_result_and_inventory_stays_24(tmp_path, monkeypatch):
    assert len(INVENTORY) == 24
    task = tmp_path / "task.json"
    task.write_text(
        json.dumps({"id": "task-1", "status": "done", "result": "parcel logged"}),
        encoding="utf-8",
    )
    empty = tmp_path / "brains"
    empty.mkdir()
    monkeypatch.setenv("SILVIA_TASK", str(task))
    monkeypatch.setenv("SILVIA_BRAINS", str(empty))
    monkeypatch.setenv("SILVIA_SEATS", str(tmp_path / "seats.json"))
    lines = _brain_detail_lines()
    assert "Task task-1 done: parcel logged" in lines
    selected = {
        "id": "silvia",
        "title": "Silvia",
        "name": "Silvia",
        "path": r"C:\Users\Irika\.grok\silvia",
        "purpose": "Standing butler for the local Silvia stack.",
        "presence": True,
    }
    text = SilviaDashboard._format_selected(object(), selected)
    assert "parcel logged" in text
    assert len(INVENTORY) == 24
