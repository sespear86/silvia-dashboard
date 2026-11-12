"""Drive the shipped session list and the shipped session popout."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

import pytest

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from sessions_live import inspect_process, live_sessions, updates_path  # noqa: E402
from world import page_ids  # noqa: E402

EXPECTED_PAGES = [
    "overview",
    "butler-host",
    "memory",
    "catalog",
    "orchestrator",
    "usage",
    "live-diagrams",
    "task-view",
    "sessions",
    "commands",
]


def _grok_pids() -> list[int]:
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-Process grok -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    found: list[int] = []
    for line in (completed.stdout or "").splitlines():
        text = line.strip()
        if text.isdigit():
            found.append(int(text))
    return found


def _open_state(pid: int) -> str:
    """Independent OpenProcess oracle for fixture selection. Not the list filter."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.K32EnumProcesses.argtypes = (
        ctypes.POINTER(wintypes.DWORD),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel.K32EnumProcesses.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if handle:
        kernel.CloseHandle(handle)
        return "open"
    if ctypes.get_last_error() == 5:
        return "denied"
    return "dead"


def _denied_pid() -> int:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.K32EnumProcesses.argtypes = (
        ctypes.POINTER(wintypes.DWORD),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel.K32EnumProcesses.restype = wintypes.BOOL
    slots = (wintypes.DWORD * 8192)()
    needed = wintypes.DWORD()
    ok = kernel.K32EnumProcesses(slots, ctypes.sizeof(slots), ctypes.byref(needed))
    assert ok, "EnumProcesses failed"
    count = min(needed.value // ctypes.sizeof(wintypes.DWORD), 8192)
    for index in range(count):
        pid = int(slots[index])
        if pid <= 0:
            continue
        if _open_state(pid) == "denied":
            return pid
    pytest.fail("no pid returned OpenProcess error 5")


def _dead_pid() -> int:
    for candidate in range(3_000_000, 3_002_000):
        if _open_state(candidate) != "dead":
            continue
        assert inspect_process(candidate)[0] == "dead"
        return candidate
    pytest.fail("no dead pid")


def _grok_children(parent: int) -> set[int]:
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Get-CimInstance Win32_Process -Filter \"Name = 'grok.exe'\" | "
                f"Where-Object {{ $_.ParentProcessId -eq {int(parent)} }} | "
                "Select-Object -ExpandProperty ProcessId"
            ),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    found: set[int] = set()
    for line in (completed.stdout or "").splitlines():
        text = line.strip()
        if text.isdigit():
            found.add(int(text))
    return found


def test_page_ids_keep_the_eight_and_add_sessions():
    assert page_ids() == EXPECTED_PAGES


def _debug_privilege(enable: bool) -> None:
    """SeDebugPrivilege hides Win32 error 5. The dashboard path must see that error."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
    kernel.OpenProcessToken.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class LuidAttr(ctypes.Structure):
        _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]

    class TokenPrivileges(ctypes.Structure):
        _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", LuidAttr * 1)]

    advapi.LookupPrivilegeValueW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(LUID))
    advapi.LookupPrivilegeValueW.restype = wintypes.BOOL
    advapi.AdjustTokenPrivileges.argtypes = (
        wintypes.HANDLE,
        wintypes.BOOL,
        ctypes.POINTER(TokenPrivileges),
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )
    advapi.AdjustTokenPrivileges.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    opened = kernel.OpenProcessToken(kernel.GetCurrentProcess(), 0x0020 | 0x0008, ctypes.byref(token))
    if not opened:
        return
    try:
        luid = LUID()
        if not advapi.LookupPrivilegeValueW(None, "SeDebugPrivilege", ctypes.byref(luid)):
            return
        privileges = TokenPrivileges()
        privileges.PrivilegeCount = 1
        privileges.Privileges[0].Luid = luid
        privileges.Privileges[0].Attributes = 0x00000002 if enable else 0
        advapi.AdjustTokenPrivileges(token, False, ctypes.byref(privileges), 0, None, None)
    finally:
        kernel.CloseHandle(token)


def test_live_sessions_filters_registry(tmp_path: Path):
    _debug_privilege(False)
    try:
        _assert_live_filter(tmp_path)
    finally:
        _debug_privilege(True)


def _assert_live_filter(tmp_path: Path):
    grok_pids = _grok_pids()
    assert grok_pids, "a running grok.exe is required"
    grok_pid = grok_pids[0]
    assert _open_state(grok_pid) == "open"
    state, image = inspect_process(grok_pid)
    assert state == "alive"
    assert Path(image).name.lower() == "grok.exe"

    denied = _denied_pid()
    assert _open_state(denied) == "denied"
    dead = _dead_pid()
    registry = tmp_path / "active_sessions.json"
    rows = [
        {"session_id": "missing-pid", "cwd": r"C:\missing", "opened_at": "t0"},
        {"session_id": "blank-pid", "pid": "", "cwd": r"C:\blank", "opened_at": "t1"},
        {"session_id": "dead-pid", "pid": dead, "cwd": r"C:\dead", "opened_at": "t2"},
        {"session_id": "python-pid", "pid": os.getpid(), "cwd": r"C:\python", "opened_at": "t3"},
        {"session_id": "grok-pid", "pid": grok_pid, "cwd": r"C:\Windows\System32", "opened_at": "t4"},
        {"session_id": "denied-pid", "pid": denied, "cwd": r"C:\denied", "opened_at": "t5"},
        {"pid": grok_pid, "cwd": r"C:\no-id", "opened_at": "t6"},
    ]
    rows.append(
        {
            "session_id": "grok-pid",
            "pid": grok_pid,
            "cwd": r"C:\Windows\System32",
            "opened_at": "t7",
        }
    )
    rows.append(
        {
            "session_id": "view:grok-pid",
            "pid": grok_pid,
            "cwd": r"C:\view",
            "opened_at": "t8",
        }
    )
    registry.write_text(json.dumps(rows), encoding="utf-8")
    before = registry.read_bytes()
    home = tmp_path / "grok-home"
    from sessions_live import register_opened_view, unregister_opened_view

    register_opened_view("grok-pid")
    try:
        found = live_sessions(registry, grok_home=home)
    finally:
        unregister_opened_view("grok-pid")
    after = registry.read_bytes()
    assert after == before
    ids = [row["session_id"] for row in found]
    assert "missing-pid" not in ids
    assert "blank-pid" not in ids
    assert "dead-pid" not in ids
    assert "python-pid" not in ids
    assert ids.count("grok-pid") == 1
    assert "view:grok-pid" not in ids
    assert "denied-pid" in ids
    assert "" not in ids
    grok_row = next(row for row in found if row["session_id"] == "grok-pid")
    assert grok_row["pid"] == grok_pid
    assert grok_row["opened_at"] == "t4"
    assert grok_row["updates_path"]


class _Click:
    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y


_TUI_DOUBLE = """
import os
import sys
import threading
import time
from pathlib import Path

phase_path = Path(sys.argv[1])
inbox_path = Path(sys.argv[2])
extra = []
lock = threading.Lock()


def frame() -> str:
    phase = "0"
    try:
        phase = phase_path.read_text(encoding="utf-8").strip() or "0"
    except OSError:
        phase = "0"
    lines = ["Grok Build TUI", ""]
    if phase >= "1":
        lines.append("Thinking: checking the live view")
    if phase >= "2":
        lines.append("agent spawn: checker")
        lines.append("later: background")
    with lock:
        lines.extend(extra)
    return "\\n".join(lines)


def paint() -> None:
    os.system("cls")
    sys.stdout.write(frame() + "\\n")
    sys.stdout.flush()


def reader() -> None:
    while True:
        line = sys.stdin.readline()
        if line == "":
            time.sleep(0.05)
            continue
        text = line.strip()
        if not text:
            continue
        with lock:
            extra.append("message: still live after " + text)
        with inbox_path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\\n")
        paint()


threading.Thread(target=reader, daemon=True).start()
seen = ""
while True:
    current = frame()
    if current != seen:
        paint()
        seen = current
    time.sleep(0.05)
"""


def _session_dir_ids(home: Path) -> set[str]:
    root = home / "sessions"
    if not root.is_dir():
        return set()
    found: set[str] = set()
    for group in root.iterdir():
        if not group.is_dir():
            continue
        for child in group.iterdir():
            if child.is_dir():
                found.add(child.name)
    return found


def _session_event(kind: str, **fields: object) -> bytes:
    update = {"sessionUpdate": kind, **fields}
    payload = {"jsonrpc": "2.0", "method": "session/update", "params": {"update": update}}
    return (json.dumps(payload) + "\n").encode("utf-8")


def _wait_popout(pop, needle: str, timeout: float = 12.0, require_change: bool = False) -> bytes:
    """Wait until the original console shows needle and the picture is on screen."""
    from sessions_live import console_screen_text

    deadline = time.time() + timeout
    previous = pop.frame_bytes if require_change else b""
    last = ""
    while time.time() < deadline:
        pop.poll()
        frame = pop.frame_bytes
        try:
            last = console_screen_text(pop._original_pid)
        except OSError as exc:
            last = str(exc)
        photo = pop._photo
        wide = photo is not None and photo.width() > 40 and photo.height() > 20
        changed = (not previous) or frame != previous
        if needle in last and frame and changed and len(frame) > 500 and wide:
            return frame
        time.sleep(0.1)
    raise AssertionError(needle + " not on the live Grok window:\n" + last)


def test_popout_shows_console_tui_and_relays_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A listed-session click shows that process's console and relays every copy line.

    The opened view is the console screen, not a text log of updates.jsonl.
    The click must not start grok --resume. The original stays unchanged until
    the copy submits. Three inputs, including a line after the first, are
    relayed in order, and the console screen still updates after each one.
    """
    import sessions_live
    from app import SilviaDashboard
    from sessions_live import console_screen_text, inspect_process as real_inspect
    from sessions_live import live_sessions
    from world import build_world, switch_page

    _debug_privilege(False)

    def boom(*_args, **_kwargs):
        raise AssertionError("click started grok --resume")

    monkeypatch.setattr(sessions_live, "start_resume_process", boom)
    before_grok = set(_grok_pids())
    phase = tmp_path / "phase.txt"
    inbox = tmp_path / "inbox.txt"
    phase.write_text("0", encoding="utf-8")
    script = tmp_path / "tui_double.py"
    script.write_text(_TUI_DOUBLE, encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-u", str(script), str(phase), str(inbox)],
        cwd=str(tmp_path),
        creationflags=0x00000010,
    )
    cwd = "D:\\" + ("session-path-" * 30)
    assert len(quote(cwd, safe="").encode("utf-8")) > 255
    home = tmp_path / "grokhome"
    group = home / "sessions" / "hashed-group"
    (group / "long-session").mkdir(parents=True)
    (group / ".cwd").write_text(cwd + "\n", encoding="utf-8")
    updates = group / "long-session" / "updates.jsonl"
    updates.write_bytes(b"already-in-file-line\n")
    resolved = updates_path(home, cwd, "long-session")
    assert resolved.resolve() == updates.resolve()
    before_ids = _session_dir_ids(home)
    assert before_ids == {"long-session"}
    session_id = "long-session"
    registry = tmp_path / "active_sessions.json"

    def patched_inspect(pid: int):
        if int(pid) == int(proc.pid):
            return "alive", r"C:\Grok\grok.exe"
        return real_inspect(pid)

    monkeypatch.setattr(sessions_live, "inspect_process", patched_inspect)
    registry.write_text(
        json.dumps(
            [
                {
                    "session_id": session_id,
                    "pid": proc.pid,
                    "cwd": cwd,
                    "opened_at": "now",
                }
            ]
        ),
        encoding="utf-8",
    )

    def quiet_world() -> dict:
        built = build_world({"resources": [], "capabilities": [], "probes": {}, "usage": {}})
        built["sessions_registry"] = str(registry)
        built["sessions_home"] = str(home)
        return built

    app = None
    try:
        deadline = time.time() + 8
        screen = ""
        while time.time() < deadline:
            try:
                screen = console_screen_text(proc.pid)
            except OSError:
                screen = ""
            if "Grok Build TUI" in screen:
                break
            time.sleep(0.1)
        assert "Grok Build TUI" in screen
        assert "Thinking:" not in screen
        opened = switch_page(quiet_world(), "sessions")
        app = SilviaDashboard(opened, on_refresh=lambda page="overview": quiet_world())
        job = app._auto_refresh_after
        if job is not None:
            app.after_cancel(job)
            app._auto_refresh_after = None
        app.update_idletasks()
        app.update()
        device = next(item for item in app.hits if str(item.get("id") or "").startswith("device:"))
        app._click(_Click((device["x0"] + device["x1"]) / 2, (device["y0"] + device["y1"]) / 2))
        active = next(item for item in app.hits if str(item.get("id") or "").startswith("active:"))
        app._click(_Click((active["x0"] + active["x1"]) / 2, (active["y0"] + active["y1"]) / 2))
        hit = next(item for item in app.hits if item.get("id") == f"session:{session_id}")
        rows_before = [row["session_id"] for row in live_sessions(registry, grok_home=home)]
        app._click(_Click((hit["x0"] + hit["x1"]) / 2, (hit["y0"] + hit["y1"]) / 2))
        pop = app._session_popouts[session_id]
        assert pop.session_id == session_id
        assert pop.argv == []
        assert pop.pid == 0
        assert pop.reads_transcript is False
        assert pop.shows_console_tui is True
        assert pop.shows_live_window is True
        assert pop.console_hwnd == 0
        assert pop._text is None
        assert pop._entry.get("1.0", "end-1c") == "Enter remotely here."
        assert "--resume" not in " ".join(pop.argv)
        _wait_popout(pop, "Grok Build TUI")
        app.update_idletasks()
        assert pop.window.winfo_height() >= 480
        assert pop.window.winfo_width() >= 640
        assert b"already-in-file-line" not in pop.frame_bytes
        with updates.open("ab") as handle:
            handle.write(
                _session_event(
                    "agent_thought_chunk",
                    content={"type": "text", "text": "jsonl-only-thought"},
                )
            )
        pop.poll()
        assert b"jsonl-only-thought" not in pop.frame_bytes
        phase.write_text("1", encoding="utf-8")
        _wait_popout(pop, "Thinking: checking the live view", require_change=True)
        phase.write_text("2", encoding="utf-8")
        _wait_popout(pop, "agent spawn: checker", require_change=True)
        assert "later: background" in console_screen_text(pop._original_pid)
        assert pop.original_unchanged()
        assert pop.relayed_lines == []
        assert inbox.exists() is False or inbox.read_text(encoding="utf-8") == ""

        def send(text: str) -> None:
            pop._set_draft(text)
            pop._on_submit()

        send("relay-one")
        _wait_popout(pop, "message: still live after relay-one", require_change=True)
        send("relay-two\nrelay-two-next")
        _wait_popout(pop, "message: still live after relay-two-next", require_change=True)
        send("relay-three")
        _wait_popout(pop, "message: still live after relay-three", require_change=True)
        assert "Thinking: checking the live view" in console_screen_text(pop._original_pid)
        assert "agent spawn: checker" in console_screen_text(pop._original_pid)
        arrived = inbox.read_text(encoding="utf-8").splitlines()
        assert arrived == ["relay-one", "relay-two", "relay-two-next", "relay-three"]
        assert pop.relayed_lines == arrived
        assert pop.original_unchanged() is False
        listed = [row["session_id"] for row in live_sessions(registry, grok_home=home)]
        assert listed == rows_before == [session_id]
        registry.write_text(
            json.dumps(
                [
                    {
                        "session_id": session_id,
                        "pid": proc.pid,
                        "cwd": cwd,
                        "opened_at": "now",
                    },
                    {
                        "session_id": session_id,
                        "pid": proc.pid,
                        "cwd": cwd,
                        "opened_at": "later",
                    },
                    {
                        "session_id": f"view:{session_id}",
                        "pid": proc.pid,
                        "cwd": cwd,
                        "opened_at": "later",
                    },
                ]
            ),
            encoding="utf-8",
        )
        listed = [row["session_id"] for row in live_sessions(registry, grok_home=home)]
        assert listed == [session_id]
        assert _session_dir_ids(home) == before_ids
        assert set(_grok_pids()) == before_grok
        app._click(_Click((hit["x0"] + hit["x1"]) / 2, (hit["y0"] + hit["y1"]) / 2))
        assert list(app._session_popouts) == [session_id]
        assert pop.alive()
    finally:
        if app is not None:
            job = app._auto_refresh_after
            if job is not None:
                try:
                    app.after_cancel(job)
                except Exception:
                    pass
                app._auto_refresh_after = None
            app.destroy()
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    assert set(_grok_pids()) == before_grok


def _click_hit(app, hit_id: str):
    hit = next(item for item in app.hits if item.get("id") == hit_id)

    class _Click:
        def __init__(self) -> None:
            self.x = (hit["x0"] + hit["x1"]) / 2
            self.y = (hit["y0"] + hit["y1"]) / 2

    app._click(_Click())


def test_sessions_are_grouped_by_device_and_new_session_uses_alpha(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """A device click lists only that device's sessions, and New session uses the Alpha launcher."""
    from app import SilviaDashboard
    import sessions_live
    from world import build_world, switch_page

    started: list[tuple[str, str, str]] = []

    def record(file: str, parameters: str, directory: str):
        started.append((file, parameters, directory))

        class Started:
            pid = 1

        return Started()

    monkeypatch.setattr(sessions_live, "_shell_execute", record)
    alpha = tmp_path / "Launch-Grok-Build-TUI.ps1"
    devices = [
        {
            "id": "irika@desktop-aqoetjb",
            "label": "DESKTOP-AQOETJB",
            "hostname": "DESKTOP-AQOETJB",
            "local": True,
            "launcher": str(alpha),
            "sessions": [],
        },
        {
            "id": "other@pc",
            "label": "OTHER-PC",
            "hostname": "OTHER-PC",
            "local": False,
            "launcher": "",
            "sessions": [],
        },
    ]
    monkeypatch.setattr(sessions_live, "device_sections", lambda sessions, **kwargs: devices)
    monkeypatch.setattr(sessions_live, "live_sessions", lambda *args, **kwargs: list(devices[0]["sessions"]))
    local = {
        "session_id": "local-session",
        "pid": 11,
        "cwd": r"C:\Users\Irika",
        "title": "local-session",
    }
    devices[0]["sessions"] = [local]
    devices[0]["launcher"] = str(alpha)
    world = switch_page(build_world({"resources": [], "capabilities": [], "probes": {}, "usage": {}}), "sessions")
    app = SilviaDashboard(world, on_refresh=lambda page="overview": world)
    try:
        app.withdraw()
        app.update_idletasks()
        app.render()
        assert any(item.get("id") == "device:irika@desktop-aqoetjb" for item in app.hits)
        assert any(item.get("id") == "device:other@pc" for item in app.hits)
        assert not any(str(item.get("id") or "").startswith("session:") for item in app.hits)
        devices[0]["history"] = [
            {"session_id": "old-session", "title": "old-session", "cwd": r"C:\Users\Irika", "pid": ""}
        ]
        _click_hit(app, "device:irika@desktop-aqoetjb")
        assert any(item.get("id") == "active:irika@desktop-aqoetjb" for item in app.hits)
        assert any(item.get("id") == "history:irika@desktop-aqoetjb" for item in app.hits)
        assert not any(item.get("id") == "session:local-session" for item in app.hits)
        _click_hit(app, "active:irika@desktop-aqoetjb")
        assert any(item.get("id") == "session:local-session" for item in app.hits)
        assert not any("old-session" in app.canvas.itemcget(item, "text") for item in app.canvas.find_all() if app.canvas.type(item) == "text")
        assert any(item.get("id") == "new-session" for item in app.hits)
        _click_hit(app, "history:irika@desktop-aqoetjb")
        assert any("old-session" in app.canvas.itemcget(item, "text") for item in app.canvas.find_all() if app.canvas.type(item) == "text")
        assert any(item.get("id") == "resume:old-session" for item in app.hits)
        assert not any(item.get("id") == "session:local-session" for item in app.hits)
        _click_hit(app, "device:other@pc")
        assert not any(item.get("id") == "session:local-session" for item in app.hits)
        assert not any(item.get("id") == "new-session" for item in app.hits)
        _click_hit(app, "device:irika@desktop-aqoetjb")
        before = len(app._session_popouts)
        _click_hit(app, "new-session")
        assert started, "New session did not launch"
        file, parameters, directory = started[-1]
        assert file.lower().endswith("powershell.exe")
        assert f'-File "{alpha}"' in parameters
        assert parameters.startswith("-NoExit ")
        assert "-SessionOnly" not in parameters
        assert "--resume" not in parameters
        assert directory.lower() == r"c:\windows\system32"
        assert len(app._session_popouts) == before
        fresh = dict(local)
        fresh["session_id"] = "brand-new"
        fresh["pid"] = 99
        devices[0]["sessions"] = [local, fresh]
        monkeypatch.setattr(sessions_live, "grok_descendants", lambda parent, processes=None: [99])
        monkeypatch.setattr(sessions_live, "process_command_line", lambda pid: r"C:\Users\Irika\.grok\bin\grok.exe")
        app._show_launched_session(fresh)
        assert "brand-new" in app._session_popouts
        pop = app._session_popouts["brand-new"]
        pop.close_popout()
    finally:
        job = app._auto_refresh_after
        if job is not None:
            app.after_cancel(job)
            app._auto_refresh_after = None
        app.destroy()


def test_family_devices_are_listed_and_remote_new_session_stays_here(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """The pack catalog lists every family device. A remote New session asks that device and does not launch here."""
    from app import SilviaDashboard
    import sessions_live
    from world import build_world, switch_page

    catalog = {
        "devices": [
            {"id": "irika@desktop-aqoetjb", "hostname": "DESKTOP-AQOETJB", "username": "Irika", "name": "desktop"},
            {
                "id": "spear@oregon-symbiosis",
                "hostname": "oregon-symbiosis",
                "username": "spear",
                "name": "stinky",
                "tailscale_ip": "100.105.49.78",
                "rustdesk_id": "39008633",
            },
        ]
    }
    roster = tmp_path / "devices.json"
    catalog_path = tmp_path / "family-devices.json"
    roster.write_text(json.dumps({"devices": [catalog["devices"][0]]}), encoding="utf-8")
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    sections = sessions_live.device_sections(
        [{"session_id": "local-session", "pid": 11, "cwd": r"C:\Users\Irika", "title": "local"}],
        roster_path=roster,
    )
    # The live catalog is the shipped file. This unit check uses the temp catalog through merged rows.
    rows = sessions_live.merged_device_rows(roster, catalog_path)
    assert [row["id"] for row in rows] == ["irika@desktop-aqoetjb", "spear@oregon-symbiosis"]
    monkeypatch.setattr(sessions_live, "merged_device_rows", lambda roster_path=None, catalog_path=None: rows)
    monkeypatch.setattr(sessions_live, "local_device_id", lambda roster=None: "irika@desktop-aqoetjb")
    sections = sessions_live.device_sections([{"session_id": "local-session", "pid": 11, "title": "local"}])
    local = next(item for item in sections if item["id"] == "irika@desktop-aqoetjb")
    remote = next(item for item in sections if item["id"] == "spear@oregon-symbiosis")
    assert local["local"] is True
    assert local["sessions"]
    assert remote["local"] is False
    assert remote["sessions"] == []
    assert remote["launcher"] == ""
    assert "-NoExit " in remote["pathway"]
    assert "Launch-Grok-Build-TUI.ps1" in remote["pathway"]
    assert remote["tailscale_ip"] == "100.105.49.78"
    started: list[str] = []
    asked: list[tuple[str, str, str]] = []

    def fake_ask(ip: str, action: str, session_id: str = "", text: str = "", timeout: float = 3.0, port: int = 54731):
        del text, timeout, port
        asked.append((ip, action, session_id))
        return {"ok": True}

    import remote_sessions

    monkeypatch.setattr(sessions_live, "_shell_execute", lambda *args: started.append(args) or type("S", (), {"pid": 1})())
    monkeypatch.setattr(sessions_live, "device_sections", lambda sessions, **kwargs: sections)
    monkeypatch.setattr(remote_sessions, "attach_remote_views", lambda rows, timeout=0.7: rows)
    monkeypatch.setattr(remote_sessions, "ask_device", fake_ask)
    world = switch_page(build_world({"resources": [], "capabilities": [], "probes": {}, "usage": {}}), "sessions")
    app = SilviaDashboard(world, on_refresh=lambda page="overview": world)
    try:
        app.withdraw()
        app.update_idletasks()
        _click_hit(app, "device:spear@oregon-symbiosis")
        _click_hit(app, "new-session")
        assert started == []
        assert asked == [("100.105.49.78", "new-session", "")]
        assert app._sessions_pathway["device"] == "spear@oregon-symbiosis"
        assert app._sessions_pathway["text"] == "Asked oregon-symbiosis to open a new session."
        assert "not on this PC" not in app._sessions_pathway["text"]
        assert app._sessions_pathway["command"] == ""
    finally:
        app._pending_session = None
        app.destroy()


def test_remote_history_and_picture_stay_on_that_device(monkeypatch: pytest.MonkeyPatch):
    """History resume and an open picture ask the other device. Neither starts a process here."""
    from app import SilviaDashboard
    import sessions_live
    import remote_sessions
    from world import build_world, switch_page

    opened: list[dict] = []

    class FakePopout:
        def __init__(self, master, row, grok_exe=None):
            del master, grok_exe
            opened.append(dict(row))

        def alive(self) -> bool:
            return True

    started: list[str] = []
    asked: list[tuple[str, str, str]] = []

    def fake_ask(ip: str, action: str, session_id: str = "", text: str = "", timeout: float = 3.0, port: int = 54731):
        del text, timeout, port
        asked.append((ip, action, session_id))
        return {"ok": True}

    sections = [
        {
            "id": "spear@oregon-symbiosis",
            "hostname": "oregon-symbiosis",
            "label": "stinky · oregon-symbiosis",
            "local": False,
            "launcher": "",
            "pathway": "powershell.exe -NoExit -File launcher.ps1",
            "tailscale_ip": "100.105.49.78",
            "rustdesk_id": "39008633",
            "sessions": [
                {
                    "session_id": "live1",
                    "title": "live",
                    "cwd": r"C:\work",
                    "pid": 77,
                    "remote": True,
                    "remote_ip": "100.105.49.78",
                    "remote_host": "oregon-symbiosis",
                }
            ],
            "history": [
                {
                    "session_id": "old1",
                    "title": "old",
                    "cwd": r"C:\work",
                    "pid": "",
                    "history": True,
                    "remote": True,
                    "remote_ip": "100.105.49.78",
                    "remote_host": "oregon-symbiosis",
                }
            ],
        }
    ]
    monkeypatch.setattr(sessions_live, "_shell_execute", lambda *args: started.append(args) or type("S", (), {"pid": 1})())
    monkeypatch.setattr(sessions_live, "device_sections", lambda sessions, **kwargs: sections)
    monkeypatch.setattr(sessions_live, "SessionPopout", FakePopout)
    monkeypatch.setattr(remote_sessions, "attach_remote_views", lambda rows, timeout=0.7: rows)
    monkeypatch.setattr(remote_sessions, "ask_device", fake_ask)
    world = switch_page(build_world({"resources": [], "capabilities": [], "probes": {}, "usage": {}}), "sessions")
    app = SilviaDashboard(world, on_refresh=lambda page="overview": world)
    try:
        app.withdraw()
        app.update_idletasks()
        _click_hit(app, "device:spear@oregon-symbiosis")
        _click_hit(app, "active:spear@oregon-symbiosis")
        _click_hit(app, "session:live1")
        _click_hit(app, "history:spear@oregon-symbiosis")
        _click_hit(app, "resume:old1")
        assert started == []
        assert opened and opened[0]["remote_ip"] == "100.105.49.78"
        assert opened[0]["session_id"] == "live1"
        assert asked == [("100.105.49.78", "resume", "old1")]
        assert "Asked oregon-symbiosis to resume old1." in app._sessions_pathway["text"]
        assert "not on this PC" not in app._sessions_pathway["text"]
    finally:
        app._pending_session = None
        app.destroy()


def test_history_resume_uses_the_pinned_launcher_and_waits_for_the_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """A history row uses the pinned launcher to resume, and the copy opens after that session is up."""
    from app import SilviaDashboard
    import sessions_live
    from world import build_world, switch_page

    started: list[tuple[str, str, str]] = []
    loaded = {"ready": False}

    def record(file: str, parameters: str, directory: str):
        started.append((file, parameters, directory))

        class Started:
            pid = 42

        return Started()

    resumed = {
        "session_id": "old-session",
        "pid": 99,
        "cwd": r"C:\Users\Irika",
        "title": "old-session",
        "updates_path": "",
    }
    alpha = tmp_path / "Launch-Grok-Build-TUI.ps1"
    devices = [
        {
            "id": "irika@desktop-aqoetjb",
            "label": "DESKTOP-AQOETJB",
            "local": True,
            "launcher": str(alpha),
            "sessions": [],
            "history": [dict(resumed, pid="")],
        }
    ]
    monkeypatch.setattr(sessions_live, "_shell_execute", record)
    monkeypatch.setattr(sessions_live, "device_sections", lambda sessions, **kwargs: devices)
    monkeypatch.setattr(sessions_live, "grok_descendants", lambda parent, processes=None: [99])
    monkeypatch.setattr(sessions_live, "place_launched_window", lambda pid: None)
    monkeypatch.setattr(
        sessions_live,
        "process_command_line",
        lambda pid: r"C:\Users\Irika\.grok\bin\grok.exe --resume=old-session",
    )
    monkeypatch.setattr(sessions_live, "live_sessions", lambda *args, **kwargs: [resumed] if loaded["ready"] else [])
    world = switch_page(build_world({"resources": [], "capabilities": [], "probes": {}, "usage": {}}), "sessions")
    app = SilviaDashboard(world, on_refresh=lambda page="overview": world)
    try:
        app.withdraw()
        app.update_idletasks()
        _click_hit(app, "device:irika@desktop-aqoetjb")
        _click_hit(app, "history:irika@desktop-aqoetjb")
        _click_hit(app, "resume:old-session")
        assert started, "history did not launch"
        _file, parameters, directory = started[-1]
        assert parameters.startswith("-NoExit ")
        assert f'-File "{alpha}"' in parameters
        assert '-ResumeSession "old-session"' in parameters
        assert "-SessionOnly" not in parameters
        assert directory.lower() == r"c:\windows\system32"
        app.update()
        assert "old-session" not in app._session_popouts
        loaded["ready"] = True
        deadline = time.time() + 3
        while time.time() < deadline and "old-session" not in app._session_popouts:
            app.update()
            time.sleep(0.05)
        assert "old-session" in app._session_popouts
        launcher = Path(r"C:\Users\Irika\.grok\launchers\Launch-Grok-Build-TUI.ps1").read_text(encoding="utf-8")
        assert "& $GrokExe --resume=$ResumeSession" in launcher
    finally:
        for pop in list(getattr(app, "_session_popouts", {}).values()):
            try:
                pop.close_popout()
            except Exception:
                pass
        job = app._auto_refresh_after
        if job is not None:
            try:
                app.after_cancel(job)
            except Exception:
                pass
        app._pending_session = None
        app.destroy()


def test_new_session_ignores_the_hook_fixer_grok():
    """The copy follows the launcher's own grok.exe, not update or a prompt-file fixer."""
    from sessions_live import direct_grok_child, grok_descendants, is_new_tui_command

    processes = [
        (10, 1, "powershell.exe"),
        (20, 10, "python.exe"),
        (21, 20, "grok.exe"),
        (22, 10, "grok.exe"),
    ]
    assert direct_grok_child(10, processes) == 22
    assert set(grok_descendants(10, processes)) == {21, 22}
    assert is_new_tui_command(r"C:\Users\Irika\.grok\bin\grok.exe")
    assert not is_new_tui_command(r"C:\Users\Irika\.grok\bin\grok.exe update --alpha")
    assert not is_new_tui_command(r"C:\Users\Irika\.grok\bin\grok.exe --prompt-file C:\fix.txt")


def test_session_history_lists_closed_sessions_only(tmp_path: Path):
    """History is stored sessions on this device, without the ones still open."""
    from sessions_live import session_history

    home = tmp_path / "grok"
    closed = home / "sessions" / "C%3A%5Cwork" / "closed-one"
    opened = home / "sessions" / "C%3A%5Cwork" / "open-one"
    closed.mkdir(parents=True)
    opened.mkdir(parents=True)
    (closed / "summary.json").write_text('{"generated_title": "Closed"}', encoding="utf-8")
    (opened / "summary.json").write_text('{"generated_title": "Open"}', encoding="utf-8")
    rows = session_history(home, active_ids={"open-one"})
    assert [row["session_id"] for row in rows] == ["closed-one"]
    assert rows[0]["title"] == "Closed"
    assert rows[0]["cwd"] == r"C:\work"


def test_launch_window_lists_sessions_and_does_not_open_a_popout():
    """The launch window's left nav gains Sessions. Opening that page does not open a popout."""
    from app import SilviaDashboard
    from world import build_world

    world = build_world({"resources": [], "capabilities": [], "probes": {}, "usage": {}})
    app = SilviaDashboard(world)
    try:
        app.update_idletasks()
        app.update()
        expected = {
            "overview": "Overview",
            "butler-host": "Butler & Hosting",
            "memory": "Memory",
            "catalog": "Catalog",
            "orchestrator": "Orchestrator",
            "usage": "SuperGrok Heavy",
            "live-diagrams": "Live diagrams",
            "task-view": "Task view",
            "sessions": "Sessions",
            "commands": "Commands",
        }
        assert list(app.nav_buttons) == list(expected)
        for pid, title in expected.items():
            button = app.nav_buttons[pid]
            assert button.cget("text") == title
            assert button.winfo_ismapped()
        assert app._session_popouts == {}
        app.nav_buttons["sessions"].invoke()
        app.update()
        assert app.world.get("page") == "sessions"
        assert app._session_popouts == {}
        app.render()
        app.update()
        assert app._session_popouts == {}
    finally:
        job = app._auto_refresh_after
        if job is not None:
            app.after_cancel(job)
            app._auto_refresh_after = None
        app.destroy()


def _painted(app) -> str:
    parts: list[str] = []
    for item in app.canvas.find_all():
        if app.canvas.type(item) == "text":
            parts.append(app.canvas.itemcget(item, "text"))
    return "\n".join(parts)


def test_quiet_refresh_drops_an_exited_session(tmp_path: Path):
    """A same-stamp reload still repaints Sessions after the listed pid has exited."""
    from app import SilviaDashboard
    from world import build_world, switch_page

    grok_pids = _grok_pids()
    assert grok_pids, "a running grok.exe is required"
    grok_pid = grok_pids[0]
    dead = _dead_pid()
    assert dead != grok_pid
    registry = tmp_path / "active_sessions.json"
    session_id = "quiet-refresh-session"
    row = {"session_id": session_id, "pid": grok_pid, "cwd": r"C:\Windows\System32", "opened_at": "t0"}
    registry.write_text(json.dumps([row]), encoding="utf-8")
    snap = {"resources": [], "capabilities": [], "probes": {}, "usage": {}}

    def quiet_world() -> dict:
        built = build_world(snap)
        built["sessions_registry"] = str(registry)
        built["sessions_home"] = str(tmp_path / "grok-home")
        return built

    opened = switch_page(quiet_world(), "sessions")
    app = SilviaDashboard(opened, on_refresh=lambda page="overview": quiet_world())
    try:
        app.withdraw()
        job = app._auto_refresh_after
        if job is not None:
            app.after_cancel(job)
            app._auto_refresh_after = None
        app.update_idletasks()
        app.update()
        device = next(item for item in app.hits if str(item.get("id") or "").startswith("device:"))
        app._click(_Click((device["x0"] + device["x1"]) / 2, (device["y0"] + device["y1"]) / 2))
        active = next(item for item in app.hits if str(item.get("id") or "").startswith("active:"))
        app._click(_Click((active["x0"] + active["x1"]) / 2, (active["y0"] + active["y1"]) / 2))
        assert session_id in _painted(app)
        dead_row = dict(row)
        dead_row["pid"] = dead
        registry.write_text(json.dumps([dead_row]), encoding="utf-8")
        preview = quiet_world()
        assert app._world_stamp(preview) == app._world_stamp(app.world)
        app.page_heading.configure(text="SENTINEL")
        app._start_refresh_read()
        for _ in range(100):
            if app._pending is not None:
                break
            time.sleep(0.02)
        assert app._pending is not None
        app._apply_pending()
        app.update_idletasks()
        painted = _painted(app)
        assert session_id not in painted
        assert "No open sessions" in painted
        assert app.page_heading.cget("text") == "Sessions"
        assert app._session_popouts == {}
        assert registry.read_bytes() == json.dumps([{**row, "pid": dead}]).encode("utf-8")
    finally:
        job = app._auto_refresh_after
        if job is not None:
            try:
                app.after_cancel(job)
            except Exception:
                pass
        app.destroy()


def test_remote_field_queues_sends_and_clears_placeholder(monkeypatch: pytest.MonkeyPatch):
    """Enter sends the draft and does not insert a line. Alt+Enter inserts a line."""
    import tkinter as tk

    import sessions_live
    from sessions_live import SessionPopout

    queued: list[str] = []
    chords: list[tuple[int, str, int]] = []
    monkeypatch.setattr(sessions_live, "write_console_input", lambda pid, text: queued.append(text))
    monkeypatch.setattr(
        sessions_live,
        "write_console_chord",
        lambda pid, virtual_key, character, control: chords.append((virtual_key, character, control)),
    )
    monkeypatch.setattr(
        sessions_live,
        "write_console_plain",
        lambda pid, text: queued.append("plain:" + text),
    )
    root = tk.Tk()
    root.withdraw()
    pop = SessionPopout(root, {"session_id": "remote-field", "pid": 0, "cwd": "", "updates_path": ""})
    pop._original_pid = 1
    try:
        assert pop._entry.get("1.0", "end-1c") == "Enter remotely here."
        assert pop._entry.cget("background") == "#1c1c1c"
        pop._apply_chrome(0x11, 0x12, 0x13)
        assert pop._entry.cget("background") == "#111213"
        pop._set_draft("first line")
        pop._on_return()
        assert queued == ["first line"]
        assert pop._entry.get("1.0", "end-1c") == "Enter remotely here."
        pop._on_return()
        assert chords[-1][0] == 0x0D
        pop._set_draft("send this now")
        pop._on_send_now()
        assert queued[-1] == "plain:send this now"
        assert chords[-1] == (0x49, "\t", 0x0008)
        pop._set_draft("stash me")
        pop._on_stash()
        assert pop._entry.get("1.0", "end-1c") == "Enter remotely here."
        pop._on_stash()
        assert pop._draft() == "stash me"
        pop._on_ctrl_c()
        assert pop._draft() == ""
        pop._forward_chord(0x50, "\x10", 0x0008)
        assert chords[-1] == (0x50, "\x10", 0x0008)
        pop._set_draft("from the key")
        pop._entry.focus_set()
        pop.window.update()
        pop._entry.event_generate("<Return>")
        pop.window.update()
        assert queued[-1] == "from the key"
        assert pop._entry.get("1.0", "end-1c") == "Enter remotely here."
        pop._set_draft("keep me")

        def _deny(_pid: int, _text: str) -> None:
            raise OSError(5, "Access is denied", None, 5)

        monkeypatch.setattr(sessions_live, "write_console_input", _deny)
        pop._entry.event_generate("<Return>")
        pop.window.update()
        assert pop._entry.get("1.0", "end-1c") == "keep me"
        assert "could not send" in pop._status.cget("text").lower()
        monkeypatch.setattr(sessions_live, "write_console_input", lambda pid, text: queued.append("again:" + text))
        pop._set_draft("line")
        pop._entry.event_generate("<Alt-Return>")
        pop.window.update()
        assert pop._draft() == "line\n"
        pop._entry.event_generate("<Shift-Return>")
        pop.window.update()
        assert pop._draft() == "line\n\n"
        assert queued[-1] == "from the key"
    finally:
        pop.close_popout()
        root.destroy()


def test_copy_closes_with_the_terminal_window_and_exit_stays_input(monkeypatch: pytest.MonkeyPatch):
    """Closing the original terminal closes the copy. Submitting exit does not."""
    import tkinter as tk

    import sessions_live
    from sessions_live import SessionPopout

    sent: list[str] = []
    monkeypatch.setattr(sessions_live, "write_console_input", lambda pid, text: sent.append(text))
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        creationflags=0x00000010,
    )
    root = tk.Tk()
    root.withdraw()
    pop = None
    try:
        pop = SessionPopout(
            root,
            {"session_id": "close-with-window", "pid": proc.pid, "cwd": "", "updates_path": ""},
        )
        deadline = time.time() + 8
        while time.time() < deadline and not pop.console_hwnd:
            root.update()
            time.sleep(0.05)
        assert pop.console_hwnd, "the copy never saw the original terminal window"
        pop._set_draft("exit")
        pop._on_return()
        assert sent == ["exit"]
        assert pop.alive()
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, text=True)
        proc.wait(timeout=5)
        deadline = time.time() + 4
        while time.time() < deadline and pop.alive():
            root.update()
            time.sleep(0.05)
        assert not pop.alive()
    finally:
        if proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, text=True)
        if pop is not None:
            try:
                pop.close_popout()
            except Exception:
                pass
        root.destroy()


def test_console_broker_allows_grok_and_the_probe_only(monkeypatch: pytest.MonkeyPatch):
    """The elevated relay types into a Grok session, not into an arbitrary process."""
    import console_broker

    rows = [
        (10, 1, "grok.exe"),
        (11, 1, "powershell-host.exe"),
        (12, 1, "powershell.exe"),
        (13, 1, "python.exe"),
        (14, 1, "notepad.exe"),
    ]
    commands = {
        11: "powershell-host.exe -NoExit -File C:\\Users\\Irika\\.grok\\launchers\\Launch-Grok-Build-TUI.ps1",
        12: "powershell.exe -File C:\\somewhere\\other.ps1",
        13: "C:\\Python314\\python.exe C:\\Temp\\probe.py --silvia-relay-probe C:\\Temp\\out.txt",
        14: "notepad.exe",
    }
    monkeypatch.setattr("sessions_live._process_rows", lambda: rows)
    monkeypatch.setattr("sessions_live.process_command_line", lambda pid: commands.get(int(pid), ""))
    assert console_broker.target_allowed(10)
    assert console_broker.target_allowed(11)
    assert console_broker.target_allowed(13)
    assert not console_broker.target_allowed(12)
    assert not console_broker.target_allowed(14)


def test_a_missing_process_and_a_bad_frame_are_named():
    """A copy with nothing to draw says why. It does not stay a silent black pane."""
    import tkinter as tk

    from sessions_live import SessionPopout

    root = tk.Tk()
    root.withdraw()
    pop = SessionPopout(root, {"session_id": "no-such-session", "pid": 0, "cwd": "", "updates_path": ""})
    try:
        assert pop._mirror is None
        assert "no running process" in pop._status.cget("text")
        pop._original_pid = 1
        pop._show_frame(b"not a picture")
        assert "did not draw" in pop._status.cget("text")
        assert pop._status.winfo_manager() == "pack"
    finally:
        pop.close_popout()
        root.destroy()


def test_remote_picture_stays_open_when_the_other_window_id_is_not_local(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """A window id from the owning computer is not a window here. The picture stays open."""
    import io
    import tkinter as tk

    import dashboard_debug
    import remote_sessions
    from sessions_live import SessionPopout

    log = tmp_path / "debug.log"
    monkeypatch.setenv("SILVIA_DASHBOARD_DEBUG_LOG", str(log))
    with dashboard_debug._lock:
        dashboard_debug._lines.clear()
    foreign = 0x0FFFFFFF
    calls: list[tuple[str, str]] = []

    def fake_open(ip: str, session_id: str):
        calls.append((ip, session_id))
        return io.BytesIO(b"HWND" + foreign.to_bytes(8, "little"))

    monkeypatch.setattr(remote_sessions, "open_watch", fake_open)
    root = tk.Tk()
    root.withdraw()
    pop = SessionPopout(
        root,
        {
            "session_id": "pic-stay-open",
            "pid": 4242,
            "cwd": "",
            "updates_path": "",
            "remote_ip": "100.75.223.22",
        },
    )
    try:
        deadline = time.time() + 3
        seen = ""
        while time.time() < deadline and "picture-stopped" not in seen:
            root.update()
            seen = " ".join(dashboard_debug.recent(20))
            time.sleep(0.05)
        assert pop.console_hwnd == 0
        assert "picture-open" in seen
        assert "picture-hwnd" in seen
        assert "kept open" in seen
        assert "picture-closed" not in seen
        assert calls == [("100.75.223.22", "pic-stay-open")]
        with dashboard_debug._lock:
            dashboard_debug._lines.clear()
        assert "picture-hwnd" in " ".join(dashboard_debug.recent(20))
        pop.console_hwnd = foreign
        pop.poll()
        root.update()
        assert pop.alive()
        assert not pop._closed
        assert calls == [("100.75.223.22", "pic-stay-open")]
        pop.close_popout()
        closed = " ".join(dashboard_debug.recent(20))
        assert "picture-closed" in closed
        assert "pic-stay-open" in log.read_text(encoding="utf-8")
    finally:
        try:
            pop.close_popout()
        except Exception:
            pass
        root.destroy()
