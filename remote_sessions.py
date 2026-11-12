"""Ask another family device to open, show, and take a line for its own session.

The listener binds to this PC's Tailscale address only. A peer is accepted
only when its address is in the family roster. The peer names an action.
It does not send a program, a path, or a process id. A new session and a
history resume use the pinned launcher. A submitted line is typed into
that device's own console. A watch streams the picture of that console.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

PORT = 54731
_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_ALLOWED_KEYS = {"action", "session_id", "text"}
_TEXT_LIMIT = 8000
# Names the remote copy may press. A peer cannot send its own key code.
REMOTE_KEYS: dict[str, tuple[int, str, int]] = {
    "enter": (0x0D, "\r", 0),
    "ctrl-i": (0x49, "\t", 0x0008),
    "ctrl-c": (0x43, "\x03", 0x0008),
    "escape": (0x1B, "\x1b", 0),
    "shift-tab": (0x09, "\t", 0x0010),
    "ctrl-p": (0x50, "\x10", 0x0008),
    "ctrl-o": (0x4F, "\x0f", 0x0008),
    "ctrl-r": (0x52, "\x12", 0x0008),
    "ctrl-b": (0x42, "\x02", 0x0008),
    "ctrl-t": (0x54, "\x14", 0x0008),
    "ctrl-g": (0x47, "\x07", 0x0008),
    "ctrl-l": (0x4C, "\x0c", 0x0008),
    "ctrl-n": (0x4E, "\x0e", 0x0008),
    "ctrl-q": (0x51, "\x11", 0x0008),
    "ctrl-x": (0x58, "\x18", 0x0008),
    "ctrl-period": (0xBE, ".", 0x0008),
    "f2": (0x71, "\0", 0),
    "ctrl-semicolon": (0xBA, ";", 0x0008),
    "ctrl-apostrophe": (0xDE, "'", 0x0008),
    "ctrl-backslash": (0xDC, "\\", 0x0008),
}
_CACHE_SECONDS = 4.0
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_cache_lock = threading.Lock()
_inflight: set[str] = set()
_mutex_handle: int = 0


def _log(text: str) -> None:
    path = Path.home() / ".grok" / "silvia-dashboard" / "remote-sessions.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {text[:500]}\n")
    except OSError:
        return


def _send(conn: socket.socket, payload: dict[str, Any]) -> None:
    conn.sendall((json.dumps(payload, ensure_ascii=True) + "\n").encode("utf-8"))


def _read_line(conn: socket.socket, limit: int) -> bytes:
    data = b""
    while b"\n" not in data and len(data) < limit:
        chunk = conn.recv(min(65536, limit - len(data)))
        if not chunk:
            break
        data += chunk
    line, _, _rest = data.partition(b"\n")
    return line


def _public_row(row: dict[str, Any], *, history: bool) -> dict[str, Any] | None:
    session_id = str(row.get("session_id") or "")
    if not _SESSION_ID.fullmatch(session_id):
        return None
    item: dict[str, Any] = {
        "session_id": session_id,
        "title": str(row.get("title") or "")[:200],
        "cwd": str(row.get("cwd") or "")[:500],
    }
    if not history:
        try:
            item["pid"] = int(row.get("pid") or 0)
        except (TypeError, ValueError):
            item["pid"] = 0
    return item


def _rows(raw: Any, *, history: bool) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    kept: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        item = _public_row(row, history=history)
        if item is not None:
            kept.append(item)
    return kept


class LiveOps:
    """The actions this PC can perform for a family peer."""

    def list_sessions(self) -> list[dict[str, Any]]:
        from sessions_live import live_sessions

        return _rows(live_sessions(), history=False)

    def list_history(self) -> list[dict[str, Any]]:
        from sessions_live import session_history

        active = {str(row.get("session_id") or "") for row in self.list_sessions()}
        # Newest first. A full history can be hundreds of kilobytes on one line.
        return _rows(session_history(active_ids=active), history=True)[:100]

    def launch(self, session_id: str | None) -> None:
        from sessions_live import launch_new_session

        launch_new_session(resume_session=session_id or None)

    def submit(self, session_id: str, text: str) -> list[str]:
        from sessions_live import live_sessions, write_console_input

        pid = 0
        for row in live_sessions():
            if str(row.get("session_id") or "") == session_id:
                pid = int(row.get("pid") or 0)
                break
        if pid <= 0:
            raise OSError("that session is not open")
        sent: list[str] = []
        for line in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            body = line.strip()
            if body == "":
                continue
            write_console_input(pid, body)
            sent.append(body)
        return sent

    def press_key(self, session_id: str, name: str) -> None:
        from sessions_live import live_sessions, write_console_chord

        chord = REMOTE_KEYS.get(str(name or ""))
        if chord is None:
            raise OSError("rejected")
        pid = 0
        for row in live_sessions():
            if str(row.get("session_id") or "") == session_id:
                pid = int(row.get("pid") or 0)
                break
        if pid <= 0:
            raise OSError("that session is not open")
        virtual_key, character, control = chord
        write_console_chord(pid, virtual_key, character, control)

    def type_plain(self, session_id: str, text: str) -> None:
        from sessions_live import live_sessions, write_console_plain

        pid = 0
        for row in live_sessions():
            if str(row.get("session_id") or "") == session_id:
                pid = int(row.get("pid") or 0)
                break
        if pid <= 0:
            raise OSError("that session is not open")
        write_console_plain(pid, text)

    def session_open(self, session_id: str) -> bool:
        from sessions_live import live_sessions

        for row in live_sessions():
            if str(row.get("session_id") or "") == session_id and int(row.get("pid") or 0) > 0:
                return True
        return False

    def stream(self, session_id: str, conn: socket.socket, compress: bool = False) -> None:
        from sessions_live import live_sessions

        pid = 0
        for row in live_sessions():
            if str(row.get("session_id") or "") == session_id:
                pid = int(row.get("pid") or 0)
                break
        if pid <= 0:
            raise OSError("that session is not open")
        python = sys.executable
        if python.lower().endswith("pythonw.exe"):
            sibling = Path(python).with_name("python.exe")
            if sibling.is_file():
                python = str(sibling)
        interval, use_png = remote_mirror_settings("png2" if compress else "")
        proc = subprocess.Popen(
            [
                python,
                "-c",
                "import sys; from sessions_live import serve_console_mirror; "
                "serve_console_mirror(int(sys.argv[1]), float(sys.argv[2]), int(sys.argv[3]), bool(int(sys.argv[4])))",
                str(pid),
                str(interval),
                "0",
                "1" if use_png else "0",
            ],
            cwd=str(Path(__file__).resolve().parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        try:
            output = proc.stdout
            if output is None:
                return
            # A picture stays open for the whole session. The short request
            # timeout would cut it off while a frame is still going out.
            conn.settimeout(None)
            while True:
                chunk = output.read(65536)
                if not chunk:
                    break
                conn.sendall(chunk)
        finally:
            try:
                proc.kill()
            except OSError:
                pass


def handle_client(conn: socket.socket, peer: str, peers: set[str], ops: Any) -> None:
    """Answer one connection. Unknown keys and unknown actions do no work."""
    try:
        conn.settimeout(8)
        if peer not in peers:
            _send(conn, {"ok": False, "reason": "not-family"})
            _log(f"{peer} rejected")
            return
        try:
            raw = _read_line(conn, 65536)
            payload = json.loads(raw.decode("utf-8")) if raw else None
        except (OSError, UnicodeError, json.JSONDecodeError):
            _send(conn, {"ok": False, "reason": "rejected"})
            return
        if not isinstance(payload, dict) or set(payload) - _ALLOWED_KEYS:
            _send(conn, {"ok": False, "reason": "rejected"})
            _log(f"{peer} rejected keys")
            return
        action = payload.get("action")
        if action == "list":
            try:
                sessions = _rows(ops.list_sessions(), history=False)
                history = _rows(ops.list_history(), history=True)
            except Exception as exc:
                _log(f"{peer} list failed {type(exc).__name__}")
                _send(conn, {"ok": False, "reason": "the session list did not answer"})
                return
            _send(conn, {"ok": True, "sessions": sessions, "history": history})
            return
        if action == "new-session":
            try:
                ops.launch(None)
            except Exception as exc:
                _log(f"{peer} new-session failed {type(exc).__name__}")
                _send(conn, {"ok": False, "reason": "the session did not start"})
                return
            _send(conn, {"ok": True, "action": "new-session"})
            _log(f"{peer} new-session")
            return
        if action in {"resume", "submit", "watch", "key", "plain"}:
            session_id = str(payload.get("session_id") or "")
            if not _SESSION_ID.fullmatch(session_id):
                _send(conn, {"ok": False, "reason": "bad-session-id"})
                return
            if action == "resume":
                try:
                    ops.launch(session_id)
                except Exception as exc:
                    _log(f"{peer} resume failed {type(exc).__name__}")
                    _send(conn, {"ok": False, "reason": "the session did not start"})
                    return
                _send(conn, {"ok": True, "action": "resume", "session_id": session_id})
                _log(f"{peer} resume")
                return
            if action == "submit":
                text = payload.get("text")
                if not isinstance(text, str) or len(text) > _TEXT_LIMIT:
                    _send(conn, {"ok": False, "reason": "rejected"})
                    return
                try:
                    sent = list(ops.submit(session_id, text) or [])
                except Exception as exc:
                    _log(f"{peer} submit failed {type(exc).__name__}")
                    _send(conn, {"ok": False, "reason": "the line was not delivered"})
                    return
                _send(conn, {"ok": True, "action": "submit", "sent": [str(item) for item in sent]})
                _log(f"{peer} submit")
                return
            if action == "key":
                name = payload.get("text")
                if not isinstance(name, str) or name not in REMOTE_KEYS:
                    _send(conn, {"ok": False, "reason": "rejected"})
                    return
                try:
                    ops.press_key(session_id, name)
                except Exception as exc:
                    _log(f"{peer} key failed {type(exc).__name__}")
                    _send(conn, {"ok": False, "reason": "the key was not delivered"})
                    return
                _send(conn, {"ok": True, "action": "key"})
                _log(f"{peer} key {name}")
                return
            if action == "plain":
                text = payload.get("text")
                if not isinstance(text, str) or text == "" or len(text) > _TEXT_LIMIT:
                    _send(conn, {"ok": False, "reason": "rejected"})
                    return
                try:
                    ops.type_plain(session_id, text)
                except Exception as exc:
                    _log(f"{peer} plain failed {type(exc).__name__}")
                    _send(conn, {"ok": False, "reason": "the line was not delivered"})
                    return
                _send(conn, {"ok": True, "action": "plain"})
                _log(f"{peer} plain")
                return
            checker = getattr(ops, "session_open", None)
            if callable(checker) and not checker(session_id):
                _send(conn, {"ok": False, "reason": "that session is not open"})
                return
            try:
                _send(conn, {"ok": True, "action": "watch", "session_id": session_id})
                ops.stream(session_id, conn, payload.get("text") == "png2")
            except Exception as exc:
                _log(f"{peer} watch failed {type(exc).__name__}")
            return
        _send(conn, {"ok": False, "reason": "unknown-action"})
    finally:
        try:
            conn.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        try:
            conn.close()
        except OSError:
            pass


def ask_device(
    ip: str,
    action: str,
    *,
    session_id: str = "",
    text: str = "",
    timeout: float = 3.0,
    port: int = PORT,
) -> dict[str, Any]:
    """One request to another device. A failure is a result, not a raised error."""
    payload: dict[str, Any] = {"action": action}
    if session_id:
        payload["session_id"] = session_id
    if text:
        payload["text"] = text
    try:
        with socket.create_connection((ip, int(port)), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            data = b""
            while b"\n" not in data and len(data) < 1_000_000:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
        line = data.split(b"\n", 1)[0]
        if not line:
            return {"ok": False, "reason": "no-answer"}
        parsed = json.loads(line.decode("utf-8"))
        if not isinstance(parsed, dict):
            return {"ok": False, "reason": "bad-answer"}
        return parsed
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"ok": False, "reason": type(exc).__name__}


class _Reader:
    """Bytes already read, then the rest of the socket. Same shape as a pipe."""

    def __init__(self, sock: socket.socket, pending: bytes) -> None:
        self._sock = sock
        self._buf = pending

    def read(self, count: int) -> bytes:
        while len(self._buf) < count:
            try:
                chunk = self._sock.recv(max(65536, count - len(self._buf)))
            except OSError:
                break
            if not chunk:
                break
            self._buf += chunk
        out = self._buf[:count]
        self._buf = self._buf[count:]
        return out

    def pending(self) -> int:
        """Bytes already here, plus one non-blocking read. Do not drain forever."""
        self._sock.setblocking(False)
        try:
            try:
                chunk = self._sock.recv(65536)
            except (BlockingIOError, TimeoutError, OSError):
                chunk = b""
            if chunk:
                self._buf += chunk
        finally:
            self._sock.settimeout(None)
        return len(self._buf)

    def unread(self, data: bytes) -> None:
        if data:
            self._buf = bytes(data) + self._buf

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


def remote_mirror_settings(offered: object) -> tuple[float, bool]:
    """Raw pictures load on the copies already installed.

    png2 is the copy that draws a compressed frame itself. The earlier png
    request could not open those frames and kept reconnecting.
    """
    from sessions_live import MIRROR_INTERVAL_S, REMOTE_MIRROR_INTERVAL_S

    if offered == "png2":
        return REMOTE_MIRROR_INTERVAL_S, True
    return MIRROR_INTERVAL_S, False


def open_watch(ip: str, session_id: str, *, timeout: float = 5.0, port: int = PORT) -> _Reader:
    """Connect to a device and return the live picture stream."""
    sock = socket.create_connection((ip, int(port)), timeout=timeout)
    try:
        sock.settimeout(timeout)
        payload = {"action": "watch", "session_id": session_id, "text": "png2"}
        sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        data = b""
        while b"\n" not in data and len(data) < 1_000_000:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
        line, _, rest = data.partition(b"\n")
        ack = json.loads(line.decode("utf-8")) if line else {"ok": False, "reason": "no-answer"}
        if not isinstance(ack, dict) or not ack.get("ok"):
            raise OSError(str((ack or {}).get("reason") or "the picture did not open"))
        sock.settimeout(None)
        return _Reader(sock, rest)
    except Exception:
        try:
            sock.close()
        except OSError:
            pass
        raise


def submit_remote(ip: str, session_id: str, text: str) -> list[str]:
    result = ask_device(ip, "submit", session_id=session_id, text=text, timeout=8)
    if not result.get("ok"):
        raise OSError(str(result.get("reason") or "the line was not delivered"))
    sent = result.get("sent")
    if not isinstance(sent, list):
        return []
    return [str(item) for item in sent]


def remote_key_name(virtual_key: int, control: int) -> str:
    """The allowlisted name for a chord the copy already sends locally."""
    for name, (key, _character, flags) in REMOTE_KEYS.items():
        if key == int(virtual_key) and flags == int(control):
            return name
    return ""


def press_remote_key(ip: str, session_id: str, name: str) -> None:
    """Press one allowlisted key on the computer that owns the session."""
    if name not in REMOTE_KEYS:
        raise OSError("rejected")
    result = ask_device(ip, "key", session_id=session_id, text=name, timeout=8)
    if not result.get("ok"):
        raise OSError(str(result.get("reason") or "the key was not delivered"))


def send_remote_plain(ip: str, session_id: str, text: str) -> None:
    """Type text on the owning computer without adding Enter."""
    result = ask_device(ip, "plain", session_id=session_id, text=text, timeout=8)
    if not result.get("ok"):
        raise OSError(str(result.get("reason") or "the line was not delivered"))


def _marked(row: dict[str, Any], ip: str, host: str, *, history: bool) -> dict[str, Any] | None:
    item = _public_row(row, history=history)
    if item is None:
        return None
    item["remote"] = True
    item["remote_ip"] = ip
    item["remote_host"] = host
    if history:
        item["history"] = True
        item["pid"] = ""
    return item


def _kick(ip: str, timeout: float) -> None:
    with _cache_lock:
        if ip in _inflight:
            return
        _inflight.add(ip)

    def run() -> None:
        try:
            result = ask_device(ip, "list", timeout=timeout)
            with _cache_lock:
                _cache[ip] = (time.time(), result if isinstance(result, dict) else {"ok": False, "reason": "bad-answer"})
        finally:
            with _cache_lock:
                _inflight.discard(ip)

    threading.Thread(target=run, name="silvia-remote-list", daemon=True).start()


def attach_remote_views(sections: list[dict[str, Any]], timeout: float = 0.7) -> list[dict[str, Any]]:
    """Fill remote rows from the last answer. Do not wait on the network."""
    now = time.time()
    for section in sections:
        if section.get("local") or not section.get("tailscale_ip"):
            continue
        ip = str(section.get("tailscale_ip") or "")
        host = str(section.get("hostname") or "")
        with _cache_lock:
            cached = _cache.get(ip)
        age = None if cached is None else now - cached[0]
        if cached is not None and age is not None and age < _CACHE_SECONDS:
            _apply_cached(section, cached[1], ip, host)
            continue
        if cached is not None:
            _apply_cached(section, cached[1], ip, host)
        else:
            section["remote_state"] = "checking"
            section["sessions"] = []
            section["history"] = []
        _kick(ip, timeout)
    return sections


def _apply_cached(section: dict[str, Any], result: dict[str, Any], ip: str, host: str) -> None:
    if not result.get("ok"):
        section["remote_state"] = "offline"
        section["sessions"] = []
        section["history"] = []
        return
    sessions = []
    for row in result.get("sessions") or []:
        if isinstance(row, dict):
            item = _marked(row, ip, host, history=False)
            if item is not None:
                sessions.append(item)
    history = []
    for row in result.get("history") or []:
        if isinstance(row, dict):
            item = _marked(row, ip, host, history=True)
            if item is not None:
                history.append(item)
    section["remote_state"] = "ok"
    section["sessions"] = sessions
    section["history"] = history


def family_peer_ips() -> set[str]:
    """Tailscale addresses from the roster and from device-join files."""
    ips: set[str] = set()
    files = [
        Path.home() / ".grok" / "family-stack" / "family-devices.json",
        Path.home() / ".grok" / "family-stack" / "central" / "devices.json",
    ]
    for folder in (
        Path.home() / "Downloads",
        Path.home() / ".grok" / "family-stack" / "debug-reports",
    ):
        if folder.is_dir():
            files.extend(folder.glob("*-roster.json"))
    for path in files:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows: list[Any] = []
        if isinstance(payload, dict) and isinstance(payload.get("devices"), list):
            rows = payload["devices"]
        elif isinstance(payload, dict) and isinstance(payload.get("device"), dict):
            rows = [payload["device"]]
        for row in rows:
            if not isinstance(row, dict):
                continue
            ip = str(row.get("tailscale_ip") or "").strip()
            if ip.count(".") == 3:
                ips.add(ip)
    return ips


def tailscale_ipv4() -> str:
    program_files = os.environ.get("ProgramFiles") or r"C:\Program Files"
    exe = Path(program_files) / "Tailscale" / "tailscale.exe"
    if not exe.is_file():
        return ""
    try:
        proc = subprocess.run(
            [str(exe), "ip", "-4"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    for line in (proc.stdout or "").splitlines():
        text = line.strip()
        if text.count(".") == 3:
            return text
    return ""


def _claim_single_instance() -> bool:
    global _mutex_handle
    if os.name != "nt":
        return True
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel.CreateMutexW(None, False, "Local\\SilviaRemoteSessions")
    if not handle:
        return False
    if ctypes.get_last_error() == 183:
        return False
    _mutex_handle = int(handle)
    return True


def serve_forever() -> None:
    """Listen on the Tailscale address. Never on every interface."""
    if not _claim_single_instance():
        _log("already running")
        return
    _log("started")
    while True:
        ip = tailscale_ipv4()
        if not ip:
            _log("waiting for tailscale")
            time.sleep(15)
            continue
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Tailscale forwards the tailnet port to localhost. Binding every
            # interface would accept the wider network, so this stays on loopback.
            server.bind(("127.0.0.1", PORT))
            server.listen(8)
            server.settimeout(5)
        except OSError as exc:
            _log(f"bind failed {type(exc).__name__}")
            time.sleep(15)
            continue
        _log(f"listening 127.0.0.1:{PORT} for {ip}")
        try:
            while True:
                if tailscale_ipv4() != ip:
                    break
                try:
                    conn, addr = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                peer = str(addr[0])
                allowed = family_peer_ips() | {"127.0.0.1", ip}
                threading.Thread(
                    target=handle_client,
                    args=(conn, peer, allowed, LiveOps()),
                    name="silvia-remote-client",
                    daemon=True,
                ).start()
        finally:
            try:
                server.close()
            except OSError:
                pass


def start_test_server(peers: set[str], ops: Any) -> tuple[socket.socket, int, threading.Event]:
    """Loopback listener for tests. It is not the family listener."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(16)
    server.settimeout(0.2)
    port = int(server.getsockname()[1])
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(
                target=handle_client,
                args=(conn, str(addr[0]), peers, ops),
                daemon=True,
            ).start()

    threading.Thread(target=loop, daemon=True).start()
    return server, port, stop


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["serve"]:
        serve_forever()
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
