"""The family session channel accepts only bounded actions from a family address."""

from __future__ import annotations

import time

import remote_sessions


class Ops:
    def __init__(self) -> None:
        self.launched: list[str | None] = []
        self.submitted: list[tuple[str, str]] = []
        self.watched: list[str] = []
        self.keys: list[tuple[str, str]] = []
        self.plain: list[tuple[str, str]] = []

    def list_sessions(self):
        return [
            {
                "session_id": "abc123",
                "title": "one",
                "cwd": r"C:\work",
                "pid": 9,
                "updates_path": r"C:\secret\updates.jsonl",
            }
        ]

    def list_history(self):
        return [{"session_id": "old1", "title": "old", "cwd": r"C:\work", "updates_path": r"C:\secret\old.jsonl"}]

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

    def type_plain(self, session_id, text):
        self.plain.append((session_id, text))


def _server(peers, ops):
    return remote_sessions.start_test_server(peers, ops)


def test_family_peer_can_list_open_resume_and_watch_without_a_command():
    ops = Ops()
    server, port, stop = _server({"127.0.0.1"}, ops)
    try:
        listed = remote_sessions.ask_device("127.0.0.1", "list", port=port)
        assert listed["ok"] is True
        assert listed["sessions"][0]["session_id"] == "abc123"
        assert "updates_path" not in listed["sessions"][0]
        assert "secret" not in str(listed)
        opened = remote_sessions.ask_device("127.0.0.1", "new-session", port=port)
        assert opened["ok"] is True
        resumed = remote_sessions.ask_device("127.0.0.1", "resume", session_id="old1", port=port)
        assert resumed["ok"] is True
        sent = remote_sessions.ask_device("127.0.0.1", "submit", session_id="abc123", text="hello\nthere", port=port)
        assert sent["ok"] is True
        assert sent["sent"] == ["hello"]
        reader = remote_sessions.open_watch("127.0.0.1", "abc123", port=port)
        try:
            assert reader.read(4) == b"HWND"
            assert int.from_bytes(reader.read(8), "little") == 7
        finally:
            reader.close()
        rejected = remote_sessions.ask_device(
            "127.0.0.1",
            "list",
            port=port,
        )
        assert ops.launched == [None, "old1"]
        assert ops.submitted == [("abc123", "hello\nthere")]
        assert ops.watched == ["abc123"]
        assert rejected["ok"] is True
    finally:
        stop.set()
        server.close()


def test_stranger_extra_key_and_bad_id_do_no_work():
    ops = Ops()
    server, port, stop = _server({"100.1.1.1"}, ops)
    try:
        stranger = remote_sessions.ask_device("127.0.0.1", "new-session", port=port)
        assert stranger["ok"] is False
        assert stranger["reason"] == "not-family"
        assert ops.launched == []
    finally:
        stop.set()
        server.close()

    ops = Ops()
    server, port, stop = _server({"127.0.0.1"}, ops)
    try:
        import json
        import socket

        with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
            sock.sendall(json.dumps({"action": "new-session", "command": "calc.exe"}).encode() + b"\n")
            raw = sock.recv(1024)
        assert json.loads(raw.decode().splitlines()[0])["reason"] == "rejected"
        bad = remote_sessions.ask_device("127.0.0.1", "resume", session_id="bad id", port=port)
        assert bad["reason"] == "bad-session-id"
        unknown = remote_sessions.ask_device("127.0.0.1", "shell", port=port)
        assert unknown["reason"] == "unknown-action"
        assert ops.launched == []
        assert ops.submitted == []
    finally:
        stop.set()
        server.close()


def test_attach_shows_a_cached_answer_and_does_not_wait():
    remote_sessions._cache.clear()
    remote_sessions._inflight.clear()
    remote_sessions._cache["100.1.1.1"] = (
        time.time(),
        {
            "ok": True,
            "sessions": [{"session_id": "abc123", "title": "t", "cwd": "c", "updates_path": "secret"}],
            "history": [{"session_id": "old1", "title": "old", "cwd": "c"}],
        },
    )
    sections = [
        {
            "id": "a@b",
            "local": False,
            "hostname": "B",
            "tailscale_ip": "100.1.1.1",
            "sessions": [],
            "history": [],
        }
    ]
    out = remote_sessions.attach_remote_views(sections)
    assert out[0]["remote_state"] == "ok"
    assert out[0]["sessions"][0]["remote_ip"] == "100.1.1.1"
    assert "updates_path" not in out[0]["sessions"][0]
    assert out[0]["history"][0]["session_id"] == "old1"
    remote_sessions._cache.clear()

    def slow(*args, **kwargs):
        del args, kwargs
        time.sleep(2)
        return {"ok": False, "reason": "late"}

    original = remote_sessions.ask_device
    remote_sessions.ask_device = slow
    try:
        fresh = [
            {
                "id": "a@b",
                "local": False,
                "hostname": "B",
                "tailscale_ip": "100.9.9.9",
                "sessions": [{"session_id": "keep"}],
                "history": [],
            }
        ]
        started = time.time()
        checked = remote_sessions.attach_remote_views(fresh)
        assert time.time() - started < 0.5
        assert checked[0]["remote_state"] == "checking"
        assert checked[0]["sessions"] == []
    finally:
        remote_sessions.ask_device = original
        remote_sessions._cache.clear()
        remote_sessions._inflight.clear()


def test_second_enter_is_a_key_and_an_unknown_key_is_rejected():
    ops = Ops()
    server, port, stop = _server({"127.0.0.1"}, ops)
    try:
        pressed = remote_sessions.ask_device("127.0.0.1", "key", session_id="abc123", text="enter", port=port)
        assert pressed["ok"] is True
        assert ops.keys == [("abc123", "enter")]
        rejected = remote_sessions.ask_device("127.0.0.1", "key", session_id="abc123", text="calc.exe", port=port)
        assert rejected["ok"] is False
        assert rejected["reason"] == "rejected"
        assert ops.keys == [("abc123", "enter")]
    finally:
        stop.set()
        server.close()


def test_remote_second_enter_goes_to_the_owning_computer(monkeypatch):
    import io
    import tkinter as tk

    import sessions_live
    from sessions_live import SessionPopout

    lines: list[tuple[str, str, str]] = []
    keys: list[tuple[str, str, str]] = []

    def fake_submit(ip, session_id, text):
        lines.append((ip, session_id, text))
        return [text]

    def fake_key(ip, session_id, name):
        keys.append((ip, session_id, name))

    def local_chord(*_args):
        raise AssertionError("the second enter stayed on this computer")

    monkeypatch.setattr(remote_sessions, "open_watch", lambda *_args, **_kwargs: io.BytesIO(b""))
    monkeypatch.setattr(remote_sessions, "submit_remote", fake_submit)
    monkeypatch.setattr(remote_sessions, "press_remote_key", fake_key)
    monkeypatch.setattr(sessions_live, "write_console_chord", local_chord)
    root = tk.Tk()
    root.withdraw()
    pop = SessionPopout(
        root,
        {"session_id": "pic", "pid": 9, "cwd": "", "updates_path": "", "remote_ip": "100.75.223.22"},
    )
    try:
        pop._set_draft("hello")
        pop._on_return()
        pop._on_return()
        assert lines == [("100.75.223.22", "pic", "hello")]
        assert keys == [("100.75.223.22", "pic", "enter")]
        assert pop._queued is False
    finally:
        pop.close_popout()
        root.destroy()


def test_a_real_screen_change_redraws_and_a_cursor_blink_does_not():
    from sessions_live import SessionPopout

    width, height = 320, 180
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    body = bytes(width * height * 3)
    pop = SessionPopout.__new__(SessionPopout)
    pop._shown = header + body
    cursor = bytearray(body)
    cursor[300] = 220
    assert pop._frame_changed(header + bytes(cursor)) is False
    reply = bytearray(body)
    reply[0 : len(reply) // 5] = b"\xe8" * (len(reply) // 5)
    assert pop._frame_changed(header + bytes(reply)) is True


def test_a_dropped_picture_reconnects_and_a_peek_does_not_stall():
    import socket
    import threading

    from sessions_live import SessionPopout

    pop = SessionPopout.__new__(SessionPopout)
    pop._remote_ip = "100.75.223.22"
    pop._remote_reader = None
    pop._remote_connect_started = True
    pop.window = None
    pop._mirror_stdout = __import__("io").BytesIO(b"")
    before = time.monotonic()
    pop._read_mirror()
    assert pop._remote_connect_started is False
    assert pop._remote_retry_at >= before
    # The retry wait is still ahead, so another open does not start yet.
    pop.window = object()
    pop._closed = False
    pop._start_remote_mirror()
    assert pop._remote_connect_started is False

    left, right = socket.socketpair()
    try:
        def pump() -> None:
            blob = b"x" * 100000
            deadline = time.time() + 1.2
            while time.time() < deadline:
                try:
                    left.send(blob)
                except OSError:
                    return

        threading.Thread(target=pump, daemon=True).start()
        time.sleep(0.05)
        reader = remote_sessions._Reader(right, b"")
        started = time.time()
        waiting = reader.pending()
        assert time.time() - started < 0.5
        assert waiting > 0
    finally:
        left.close()
        right.close()


def test_a_buffered_remote_frame_is_skipped_for_the_newest():
    from sessions_live import (
        MIRROR_INTERVAL_S,
        REMOTE_MIRROR_INTERVAL_S,
        REMOTE_POLL_MS,
        SessionPopout,
        png_from_ppm,
        ppm_from_png,
    )

    assert MIRROR_INTERVAL_S == 0.2
    assert REMOTE_MIRROR_INTERVAL_S == 0.1
    assert remote_sessions.remote_mirror_settings("") == (MIRROR_INTERVAL_S, False)
    assert remote_sessions.remote_mirror_settings("png") == (MIRROR_INTERVAL_S, False)
    assert remote_sessions.remote_mirror_settings("png2") == (REMOTE_MIRROR_INTERVAL_S, True)
    assert REMOTE_POLL_MS == 100
    width, height = 800, 40
    body = b"\x1c\x1c\x1c" * (width * height)
    original = f"P6\n{width} {height}\n255\n".encode("ascii") + body
    compressed = png_from_ppm(original)
    assert compressed.startswith(b"\x89PNG")
    assert len(compressed) < len(original)
    restored = ppm_from_png(compressed)
    assert restored == original
    from sessions_live import _ppm_is_blank

    assert _ppm_is_blank(compressed) is False
    newest = b"P6\n1 1\n255\nnew"
    packet = len(newest).to_bytes(4, "little") + newest

    class Stream:
        def __init__(self) -> None:
            self._buf = packet

        def read(self, count: int) -> bytes:
            out = self._buf[:count]
            self._buf = self._buf[count:]
            return out

        def pending(self) -> int:
            return len(self._buf)

        def unread(self, data: bytes) -> None:
            self._buf = data + self._buf

    pop = SessionPopout.__new__(SessionPopout)
    pop._remote_ip = "100.75.223.22"
    assert pop._latest_buffered_frame(Stream(), b"old") == newest
