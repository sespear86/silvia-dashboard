"""A dashboard update replaces program files and leaves user folders alone."""

from __future__ import annotations

import http.client
import importlib.util
import json
import os
import threading
import urllib.request
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
import sys

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import dashboard_update


def _tree(root: Path, text: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "app.py").write_text(text, encoding="utf-8")
    (root / "silvia.ico").write_bytes(b"icon")


def test_matching_files_show_no_update(tmp_path: Path):
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    _tree(local, "same\n")
    _tree(remote, "same\n")
    diff = dashboard_update.compare_manifests(
        dashboard_update.build_manifest(local),
        dashboard_update.build_manifest(remote),
    )
    assert diff["available"] is False
    assert diff["files"] == []


def test_a_running_dashboard_still_sees_an_update_when_the_saved_address_is_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "dash"
    _tree(root, "old\n")
    (root / "update-source.json").write_text(
        json.dumps(
            {
                "manifest_url": "https://desktop-aqoetjb.tail69d8db.ts.net/family-installer/dashboard-update/manifest.json"
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard_update, "is_publisher", lambda: False)
    called: list[str] = []

    def fake_fetch(url: str, timeout: float = 20) -> bytes:
        called.append(url)
        if "100.83.70.107" not in url:
            raise OSError("down")
        remote = dashboard_update.build_manifest(root)
        remote["files"][0]["sha256"] = "ab" * 32
        return json.dumps(remote).encode("utf-8")

    monkeypatch.setattr(dashboard_update, "fetch_bytes", fake_fetch)
    result = dashboard_update.check_for_update(root)
    assert dashboard_update.CHECK_INTERVAL_MS <= 30_000
    assert result["available"] is True
    assert result["manifest_url"] == dashboard_update.DEFAULT_MANIFEST_URL
    assert called[0] == dashboard_update.DEFAULT_MANIFEST_URL


def test_a_changed_program_file_is_the_update(tmp_path: Path):
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    _tree(local, "old\n")
    _tree(remote, "new\n")
    diff = dashboard_update.compare_manifests(
        dashboard_update.build_manifest(local),
        dashboard_update.build_manifest(remote),
    )
    assert diff["available"] is True
    assert diff["files"] == ["app.py"]


def test_apply_copies_the_changed_file_and_records_the_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(dashboard_update, "is_publisher", lambda: False)
    local = tmp_path / "local"
    remote_root = tmp_path / "remote"
    _tree(local, "old\n")
    _tree(remote_root, "new\n")
    (local / "notes.txt").write_text("keep me\n", encoding="utf-8")
    remote = dashboard_update.build_manifest(remote_root)
    files = {item["path"]: (remote_root / item["path"]).read_bytes() for item in remote["files"]}
    result = dashboard_update.apply_update(local, remote, lambda rel: files[rel])
    assert result["ok"] is True
    assert result["files"] == ["app.py"]
    assert (local / "app.py").read_text(encoding="utf-8") == "new\n"
    assert (local / "notes.txt").read_text(encoding="utf-8") == "keep me\n"
    applied = json.loads((local / "update-applied.json").read_text(encoding="utf-8"))
    assert applied["version"] == remote["version"]
    assert applied["files"] == ["app.py"]
    again = dashboard_update.compare_manifests(dashboard_update.build_manifest(local), remote)
    assert again["available"] is False


def test_apply_refuses_a_bad_hash_and_a_protected_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(dashboard_update, "is_publisher", lambda: False)
    local = tmp_path / "local"
    _tree(local, "old\n")
    remote = dashboard_update.build_manifest(local)
    remote["files"][0]["sha256"] = "0" * 64
    result = dashboard_update.apply_update(local, remote, lambda rel: b"tampered\n")
    assert result["ok"] is False
    assert result["reason"] == "hash mismatch"
    assert (local / "app.py").read_text(encoding="utf-8") == "old\n"

    docs = tmp_path / "Documents" / "silvia-dashboard"
    _tree(docs, "old\n")
    remote_docs = dashboard_update.build_manifest(docs)
    remote_docs["files"][0]["sha256"] = "1" * 64
    refused = dashboard_update.apply_update(docs, remote_docs, lambda rel: b"nope\n")
    assert refused["ok"] is False
    assert refused["reason"] == "refused path"
    assert (docs / "app.py").read_text(encoding="utf-8") == "old\n"
    assert not (tmp_path / "auth.json").exists()


def test_publisher_does_not_apply_an_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(dashboard_update, "is_publisher", lambda: True)
    local = tmp_path / "local"
    _tree(local, "mine\n")
    remote = dashboard_update.build_manifest(local)
    for item in remote["files"]:
        if item["path"] == "app.py":
            item["sha256"] = "2" * 64
    result = dashboard_update.apply_update(local, remote, lambda rel: b"theirs\n")
    assert result["ok"] is False
    assert (local / "app.py").read_text(encoding="utf-8") == "mine\n"
    checked = dashboard_update.check_for_update(local)
    assert checked["available"] is False
    assert checked["reason"] == "publisher"


def test_escape_paths_are_not_program_files():
    assert dashboard_update.allowed_rel("app.py")
    assert dashboard_update.allowed_rel("tests/test_dashboard_update.py")
    assert not dashboard_update.allowed_rel("../auth.json")
    assert not dashboard_update.allowed_rel("auth.json")
    assert not dashboard_update.allowed_rel("state/token-history.json")
    assert not dashboard_update.allowed_rel("update-applied.json")


def _serve(tmp_path: Path):
    dash = tmp_path / "served"
    _tree(dash, "from-publisher\n")
    exe = tmp_path / "FamilyGrokStack-Setup.exe"
    exe.write_bytes(b"exe-bytes")
    path = Path.home() / "AppData" / "Local" / "family-installer-serve.py"
    spec = importlib.util.spec_from_file_location("family_installer_serve_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    module.os.environ["SILVIA_UPDATE_ROOT"] = str(dash)
    module.os.environ["FAMILY_INSTALLER_EXE"] = str(exe)
    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return module, server, dash


def test_the_update_link_serves_the_manifest_and_the_installer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(dashboard_update, "is_publisher", lambda: False)
    module, server, served = _serve(tmp_path)
    try:
        port = server.server_address[1]
        base = f"http://127.0.0.1:{port}"
        installer = urllib.request.urlopen(base + "/FamilyGrokStack-Setup.exe", timeout=5).read()
        assert installer == b"exe-bytes"
        manifest = json.loads(urllib.request.urlopen(base + "/dashboard-update/manifest.json", timeout=5).read())
        assert manifest["product"] == "silvia-dashboard"
        body = urllib.request.urlopen(base + "/dashboard-update/file/app.py", timeout=5).read()
        assert body == (served / "app.py").read_bytes()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/dashboard-update/file/../auth.json")
        denied = conn.getresponse()
        denied.read()
        assert denied.status == 404
        assert not (served / "auth.json").exists()
    finally:
        server.shutdown()
        module.os.environ.pop("SILVIA_UPDATE_ROOT", None)
        module.os.environ.pop("FAMILY_INSTALLER_EXE", None)


def test_a_client_applies_the_served_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(dashboard_update, "is_publisher", lambda: False)
    _module, server, _served = _serve(tmp_path)
    local = tmp_path / "client"
    _tree(local, "old\n")
    try:
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}/dashboard-update/manifest.json"
        (local / "update-source.json").write_text(json.dumps({"manifest_url": url}), encoding="utf-8")
        checked = dashboard_update.check_for_update(local)
        assert checked["available"] is True
        assert checked["files"] == ["app.py"]
        applied = dashboard_update.apply_available(local)
        assert applied["ok"] is True
        assert (local / "app.py").read_text(encoding="utf-8") == "from-publisher\n"
        assert (local / "silvia.ico").read_bytes() == b"icon"
        assert dashboard_update.check_for_update(local)["available"] is False
        record = json.loads((local / "update-applied.json").read_text(encoding="utf-8"))
        assert "app.py" in record["files"]
    finally:
        server.shutdown()


def test_schedule_restart_waits_until_this_process_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "dash"
    root.mkdir()
    (root / "__main__.py").write_text("print(1)\n", encoding="utf-8")
    seen: dict[str, object] = {}

    class Started:
        pid = 5

    def fake_popen(args, **kwargs):
        seen["args"] = list(args)
        seen["flags"] = kwargs.get("creationflags")
        return Started()

    monkeypatch.setattr(dashboard_update.subprocess, "Popen", fake_popen)
    result = dashboard_update.schedule_restart(root)
    assert result["ok"] is True
    args = seen["args"]
    assert isinstance(args, list)
    assert args[-4:] == [str(os.getpid()), args[0], str(root / "__main__.py"), str(root)]
    assert "launch" in str(args[2])
    assert seen["flags"] == 0x00000008 | 0x00000200 | 0x08000000


def test_update_button_appears_only_when_an_update_is_offered():
    from app import SilviaDashboard
    from world import build_world

    world = build_world(
        {"resources": [{"id": "cli.example", "name": "Example", "category": "CLIs"}], "capabilities": [], "probes": {}, "usage": {}}
    )
    app = SilviaDashboard(world)
    try:
        app.update_idletasks()
        assert app.update_btn.cget("text") == "Update"
        assert not app.update_btn.winfo_ismapped()
        app._show_update_button(True)
        app.update_idletasks()
        assert app.update_btn.winfo_ismapped()
        app._show_update_button(False)
        app.update_idletasks()
        assert not app.update_btn.winfo_ismapped()
    finally:
        app.destroy()
