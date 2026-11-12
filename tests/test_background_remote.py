"""A per-session background toggle hides the copy a family peer launches.

The toggle is stored on this PC and read only here. A peer never sends it.
These tests use fakes and never open a real Grok window.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import remote_sessions
import sessions_live


class Ops:
    def __init__(self) -> None:
        self.launched: list[str | None] = []
        self.submitted: list[tuple[str, str]] = []
        self.watched: list[str] = []
        self.keys: list[tuple[str, str]] = []

    def list_sessions(self):
        return [{"session_id": "abc123", "title": "one", "cwd": r"C:\work", "pid": 9}]

    def list_history(self):
        return [{"session_id": "old1", "title": "old", "cwd": r"C:\work"}]

    def launch(self, session_id):
        self.launched.append(session_id)

    def submit(self, session_id, text):
        self.submitted.append((session_id, text))
        return ["hello"]

    def stream(self, session_id, conn, compress=False):
        self.watched.append(session_id)
        conn.sendall(b"HWND" + (7).to_bytes(8, "little"))

    def press_key(self, session_id, name):
        self.keys.append((session_id, name))


def test_background_toggle_defaults_off_and_persists_per_session(tmp_path: Path):
    settings = tmp_path / "session-settings.json"
    assert sessions_live.session_background("s1", settings) is False
    sessions_live.set_session_background("s1", True, settings)
    assert sessions_live.session_background("s1", settings) is True
    # A fresh read still sees the stored value.
    assert sessions_live.session_background("s1", settings) is True
    # The choice is per session, so another session stays off.
    assert sessions_live.session_background("s2", settings) is False
    sessions_live.set_session_background("s1", False, settings)
    assert sessions_live.session_background("s1", settings) is False


def test_after_launch_restores_the_owner_only_for_a_visible_launch(monkeypatch):
    calls: list[int] = []

    class FakeUser32:
        def SetForegroundWindow(self, hwnd):
            calls.append(int(hwnd))
            return True

    monkeypatch.setattr(sessions_live, "_user32", lambda: FakeUser32())
    sessions_live._after_launch(123, background=False)
    assert calls == [123]
    calls.clear()
    # A background launch shows no window, so it never touches the foreground.
    sessions_live._after_launch(123, background=True)
    assert calls == []
    sessions_live._after_launch(0, background=False)
    assert calls == []


def test_toggle_on_peer_launch_is_hidden_and_resumes_the_session(monkeypatch, tmp_path: Path):
    settings = tmp_path / "session-settings.json"
    monkeypatch.setattr(sessions_live, "session_settings_path", lambda grok_home=None: settings)
    monkeypatch.setattr(sessions_live, "alpha_launcher_path", lambda: Path(r"C:\x\Launch-Grok-Build-TUI.ps1"))
    sessions_live.set_session_background("sess1", True)

    recorded: dict[str, object] = {}

    def fake_shell(file, parameters, directory, background=False):
        recorded.update(file=file, parameters=parameters, directory=directory, background=background)

        class Started:
            pid = 7

        return Started()

    monkeypatch.setattr(sessions_live, "_shell_execute", fake_shell)

    def no_foreground():
        raise AssertionError("the background launch touched the foreground")

    monkeypatch.setattr(sessions_live, "_user32", no_foreground)
    remote_sessions.LiveOps().launch("sess1")
    assert recorded["background"] is True
    assert '-ResumeSession "sess1"' in recorded["parameters"]


def test_toggle_off_peer_launch_uses_the_visible_path(monkeypatch, tmp_path: Path):
    settings = tmp_path / "session-settings.json"
    monkeypatch.setattr(sessions_live, "session_settings_path", lambda grok_home=None: settings)
    monkeypatch.setattr(sessions_live, "alpha_launcher_path", lambda: Path(r"C:\x\Launch-Grok-Build-TUI.ps1"))

    recorded: dict[str, object] = {}

    def fake_shell(file, parameters, directory, background=False):
        recorded.update(background=background, parameters=parameters)

        class Started:
            pid = 7

        return Started()

    monkeypatch.setattr(sessions_live, "_shell_execute", fake_shell)
    remote_sessions.LiveOps().launch("sess2")
    assert recorded["background"] is False
    assert '-ResumeSession "sess2"' in recorded["parameters"]


def test_a_peer_cannot_send_a_background_flag(monkeypatch, tmp_path: Path):
    settings = tmp_path / "session-settings.json"
    monkeypatch.setattr(sessions_live, "session_settings_path", lambda grok_home=None: settings)
    ops = Ops()
    server, port, stop = remote_sessions.start_test_server({"127.0.0.1"}, ops)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
            sock.sendall(json.dumps({"action": "resume", "session_id": "abc123", "background": True}).encode() + b"\n")
            raw = sock.recv(1024)
        assert json.loads(raw.decode().splitlines()[0])["reason"] == "rejected"
        assert ops.launched == []
        # The stored setting is untouched by the peer.
        assert sessions_live.session_background("abc123", settings) is False
    finally:
        stop.set()
        server.close()


def test_a_non_family_peer_is_rejected(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sessions_live, "session_settings_path", lambda grok_home=None: tmp_path / "session-settings.json")
    ops = Ops()
    server, port, stop = remote_sessions.start_test_server({"100.1.1.1"}, ops)
    try:
        answer = remote_sessions.ask_device("127.0.0.1", "resume", session_id="abc123", port=port)
        assert answer["ok"] is False
        assert answer["reason"] == "not-family"
        assert ops.launched == []
    finally:
        stop.set()
        server.close()


def test_remote_list_submit_key_and_watch_work_for_a_background_session(monkeypatch, tmp_path: Path):
    settings = tmp_path / "session-settings.json"
    monkeypatch.setattr(sessions_live, "session_settings_path", lambda grok_home=None: settings)
    sessions_live.set_session_background("abc123", True)
    ops = Ops()
    server, port, stop = remote_sessions.start_test_server({"127.0.0.1"}, ops)
    try:
        listed = remote_sessions.ask_device("127.0.0.1", "list", port=port)
        assert listed["ok"] is True
        assert listed["sessions"][0]["session_id"] == "abc123"
        sent = remote_sessions.ask_device("127.0.0.1", "submit", session_id="abc123", text="hello", port=port)
        assert sent["ok"] is True
        pressed = remote_sessions.ask_device("127.0.0.1", "key", session_id="abc123", text="enter", port=port)
        assert pressed["ok"] is True
        reader = remote_sessions.open_watch("127.0.0.1", "abc123", port=port)
        try:
            assert reader.read(4) == b"HWND"
        finally:
            reader.close()
        assert ops.submitted == [("abc123", "hello")]
        assert ops.keys == [("abc123", "enter")]
        assert ops.watched == ["abc123"]
    finally:
        stop.set()
        server.close()
