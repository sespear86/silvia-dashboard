"""Active Grok Build TUI sessions for the Silvia dashboard.

The registry at ~/.grok/active_sessions.json is not a liveness check. A row
stays only while its pid is still a running grok.exe, or while OpenProcess
fails with access denied (Win32 error 5). This module never writes the
registry. A session click opens a live picture of that session's own Grok
window. The picture is the console window itself, refreshed in place. It
does not start grok --resume, it does not paint updates.jsonl, and it does
not bring the original window forward. The original session is left unchanged until the
opened view submits copy input, which is then relayed into that console.
A view opened from Sessions is not another list row.
"""
from __future__ import annotations

import ctypes
import json
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
from ctypes import wintypes
from pathlib import Path
from typing import Any
from urllib.parse import quote

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ERROR_ACCESS_DENIED = 5


def _no_window() -> dict[str, int]:
    if os.name != "nt":
        return {}
    return {"creationflags": subprocess.CREATE_NO_WINDOW}


def default_grok_home() -> Path:
    return Path.home() / ".grok"


def default_registry() -> Path:
    return default_grok_home() / "active_sessions.json"


def session_settings_path(grok_home: Path | None = None) -> Path:
    home = grok_home if grok_home else default_grok_home()
    return home / "silvia-dashboard" / "session-settings.json"


def load_session_settings(path: Path | None = None) -> dict[str, Any]:
    target = path if path else session_settings_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def session_background(session_id: str, path: Path | None = None) -> bool:
    key = str(session_id or "").strip()
    if not key:
        return False
    row = load_session_settings(path).get(key)
    return bool(row.get("background")) if isinstance(row, dict) else False


def set_session_background(session_id: str, on: bool, path: Path | None = None) -> None:
    key = str(session_id or "").strip()
    if not key:
        return
    target = path if path else session_settings_path()
    data = load_session_settings(target)
    row = data.get(key)
    if not isinstance(row, dict):
        row = {}
    row["background"] = bool(on)
    data[key] = row
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")


def _kernel32() -> ctypes.WinDLL:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    return kernel


def _user32() -> ctypes.WinDLL:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user32.SetForegroundWindow.restype = wintypes.BOOL
    return user32


def inspect_process(pid: int) -> tuple[str, str]:
    """Return (state, image).

    state is "dead", "denied", "alive", or "unreadable".
    "denied" is OpenProcess error 5: the process exists and its image cannot be read.
    "unreadable" means the handle opened but the image name did not come back.
    """
    try:
        number = int(pid)
    except (TypeError, ValueError):
        return "dead", ""
    if number <= 0 or number > 0xFFFFFFFF:
        return "dead", ""
    if os.name != "nt":
        try:
            os.kill(number, 0)
        except OSError:
            return "dead", ""
        return "alive", ""
    kernel = _kernel32()
    handle = kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, number)
    if not handle:
        if ctypes.get_last_error() == ERROR_ACCESS_DENIED:
            return "denied", ""
        return "dead", ""
    try:
        size = wintypes.DWORD(32767)
        buf = ctypes.create_unicode_buffer(32767)
        ok = kernel.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        if not ok:
            if ctypes.get_last_error() == ERROR_ACCESS_DENIED:
                return "denied", ""
            return "unreadable", ""
        return "alive", buf.value
    finally:
        kernel.CloseHandle(handle)


def process_running(pid: int) -> bool:
    """True when the pid is still a process. Access denied counts as running."""
    state, _image = inspect_process(pid)
    return state in ("alive", "denied", "unreadable")


def _image_is_grok(image: str) -> bool:
    """True for grok.exe and for grok.exe.old after an in-place update."""
    name = Path(image).name.lower()
    return name == "grok.exe" or name.startswith("grok.exe.")


def _parse_pid(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        if not value.is_integer() or value <= 0:
            return None
        return int(value)
    text = str(value).strip()
    if not text or not text.isdigit():
        return None
    number = int(text)
    return number if number > 0 else None


def _read_rows(path: Path) -> list[dict[str, Any]]:
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _same_cwd(recorded: str, wanted: str) -> bool:
    left = recorded.strip().replace("/", "\\")
    right = wanted.strip().replace("/", "\\")
    if left == right:
        return True
    return os.path.normcase(left) == os.path.normcase(right)


def updates_path(grok_home: Path, cwd: str, session_id: str) -> Path:
    """Resolve updates.jsonl. A cwd whose encoded name exceeds 255 bytes is found via .cwd."""
    sessions = Path(grok_home) / "sessions"
    encoded = quote(str(cwd), safe="")
    too_long = len(encoded.encode("utf-8")) > 255
    direct_group = None if too_long else sessions / encoded
    if direct_group is not None and direct_group.is_dir():
        return direct_group / session_id / "updates.jsonl"
    if sessions.is_dir():
        for group in sessions.iterdir():
            if not group.is_dir():
                continue
            marker = group / ".cwd"
            if not marker.is_file():
                continue
            try:
                recorded = marker.read_text(encoding="utf-8")
            except OSError:
                continue
            if _same_cwd(recorded, cwd):
                return group / session_id / "updates.jsonl"
    if direct_group is not None:
        return direct_group / session_id / "updates.jsonl"
    return sessions / session_id / "updates.jsonl"


def _title_for(updates: Path, session_id: str) -> str:
    summary = updates.parent / "summary.json"
    try:
        data = json.loads(summary.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return session_id
    if not isinstance(data, dict):
        return session_id
    title = str(data.get("generated_title") or data.get("title") or "").strip()
    return title or session_id


def opened_view_id(session_id: str) -> str:
    """Registry id of a view opened from Sessions. It is not the original id."""
    return "view:" + str(session_id or "").strip()


_opened_view_ids: set[str] = set()


def register_opened_view(session_id: str) -> None:
    text = str(session_id or "").strip()
    if text:
        _opened_view_ids.add(opened_view_id(text))


def unregister_opened_view(session_id: str) -> None:
    _opened_view_ids.discard(opened_view_id(session_id))


def _keep_original_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per original session. A later row for that id is not a second session."""
    chosen: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in rows:
        session_id = str(row.get("session_id") or "")
        if (
            not session_id
            or session_id.startswith("view:")
            or session_id in _opened_view_ids
        ):
            continue
        current = chosen.get(session_id)
        if current is None:
            chosen[session_id] = row
            order.append(session_id)
            continue
        if str(row.get("opened_at") or "") < str(current.get("opened_at") or ""):
            chosen[session_id] = row
    return [chosen[session_id] for session_id in order]


def live_sessions(path: Path | None = None, *, grok_home: Path | None = None) -> list[dict[str, Any]]:
    """Rows whose process is still running. Does not write the registry."""
    registry = Path(path) if path is not None else default_registry()
    home = Path(grok_home) if grok_home is not None else default_grok_home()
    kept: list[dict[str, Any]] = []
    for row in _read_rows(registry):
        session_id = str(row.get("session_id") or "").strip()
        if not session_id:
            continue
        pid = _parse_pid(row.get("pid"))
        if pid is None:
            continue
        state, image = inspect_process(pid)
        if state == "denied":
            pass
        elif state == "alive" and _image_is_grok(image):
            pass
        else:
            continue
        cwd = str(row.get("cwd") or "")
        updates = updates_path(home, cwd, session_id)
        kept.append(
            {
                "session_id": session_id,
                "pid": pid,
                "cwd": cwd,
                "opened_at": row.get("opened_at") or "",
                "title": _title_for(updates, session_id),
                "updates_path": str(updates),
            }
        )
    return _keep_original_rows(kept)


def session_history(
    grok_home: Path | None = None,
    *,
    active_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Stored sessions on this device that are not currently open."""
    from urllib.parse import unquote

    home = Path(grok_home) if grok_home is not None else default_grok_home()
    root = home / "sessions"
    open_ids = set(active_ids or ())
    rows: list[dict[str, Any]] = []
    if not root.is_dir():
        return rows
    for group in os.scandir(root):
        if not group.is_dir():
            continue
        cwd = ""
        marker = Path(group.path) / ".cwd"
        if marker.is_file():
            try:
                cwd = marker.read_text(encoding="utf-8").strip()
            except OSError:
                cwd = ""
        if not cwd:
            cwd = unquote(group.name)
        for child in os.scandir(group.path):
            if not child.is_dir() or child.name.startswith("."):
                continue
            if child.name in open_ids:
                continue
            folder = Path(child.path)
            updates = folder / "updates.jsonl"
            if not updates.is_file() and not (folder / "summary.json").is_file():
                continue
            try:
                modified = child.stat().st_mtime
            except OSError:
                modified = 0.0
            rows.append(
                {
                    "session_id": child.name,
                    "pid": "",
                    "cwd": cwd,
                    "opened_at": "",
                    "title": _title_for(updates, child.name),
                    "updates_path": str(updates),
                    "history": True,
                    "mtime": modified,
                }
            )
    rows.sort(key=lambda row: float(row.get("mtime") or 0), reverse=True)
    return rows


CREATE_NEW_CONSOLE = 0x00000010
CREATE_NEW_PROCESS_GROUP = 0x00000200
_SW_SHOWNORMAL = 1
_SW_RESTORE = 9


def default_grok_exe() -> Path:
    return default_grok_home() / "bin" / "grok.exe"


def resume_argv(session_id: str, cwd: str, grok_exe: Path) -> list[str]:
    """grok --resume for this session id. No fork, no new id, no prompt."""
    argv = [str(grok_exe), "--resume", session_id]
    text = str(cwd or "").strip()
    if text:
        argv.extend(["--cwd", text])
    return argv


def alpha_launcher_path() -> Path:
    """This device's default launcher: the Alpha Grok Build TUI."""
    return Path.home() / ".grok" / "launchers" / "Launch-Grok-Build-TUI.ps1"


def devices_roster_path() -> Path:
    return Path.home() / ".grok" / "family-stack" / "central" / "devices.json"


def load_device_roster(path: Path | None = None) -> list[dict[str, Any]]:
    roster_path = Path(path) if path else devices_roster_path()
    if not roster_path.is_file():
        return []
    try:
        payload = json.loads(roster_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("devices") if isinstance(payload, dict) else None
    return [row for row in rows or [] if isinstance(row, dict)]


def family_device_catalog(path: Path | None = None) -> list[dict[str, Any]]:
    """Devices shipped in the family pack. A later join does not remove these."""
    catalog_path = Path(path) if path else Path.home() / ".grok" / "family-stack" / "family-devices.json"
    if not catalog_path.is_file():
        return []
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("devices") if isinstance(payload, dict) else None
    return [row for row in rows or [] if isinstance(row, dict)]


def incoming_device_rows() -> list[dict[str, Any]]:
    """Device joins sent back to this PC. A new install drops one file per device."""
    rows: list[dict[str, Any]] = []
    folders = (
        Path.home() / "Downloads",
        Path.home() / ".grok" / "family-stack" / "debug-reports",
    )
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in folder.glob("*-roster.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            device = payload.get("device") if isinstance(payload, dict) else None
            if isinstance(device, dict) and device.get("hostname"):
                rows.append(device)
    return rows


def merged_device_rows(
    roster_path: Path | None = None,
    catalog_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Catalog order, with the live roster filling any newer fields for the same id."""
    catalog = family_device_catalog(catalog_path)
    roster = load_device_roster(roster_path)
    incoming = incoming_device_rows() if catalog_path is None and roster_path is None else []
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in catalog + roster + incoming:
        device_id = _device_id(row)
        if not device_id:
            continue
        current = by_id.get(device_id, {})
        current.update(row)
        by_id[device_id] = current
        if device_id not in order:
            order.append(device_id)
    return [by_id[device_id] for device_id in order]


def session_pathway(resume_session: str = "") -> str:
    """Pinned launcher command, portable to any device's user profile.

    A resume id uses grok --resume=<id> inside that launcher. No positional
    prompt is added, because that would send a new turn.
    """
    script = r"%USERPROFILE%\.grok\launchers\Launch-Grok-Build-TUI.ps1"
    parameters = f'-NoExit -NoProfile -ExecutionPolicy Bypass -File "{script}"'
    session_id = str(resume_session or "").strip()
    if session_id:
        parameters += f' -ResumeSession "{session_id}"'
    return f"powershell.exe {parameters}"


def _device_id(row: dict[str, Any]) -> str:
    if row.get("id"):
        return str(row["id"]).strip().lower()
    user = str(row.get("username") or "").strip()
    host = str(row.get("hostname") or "").strip()
    return f"{user}@{host}".lower()


def local_device_id(roster: list[dict[str, Any]] | None = None) -> str:
    rows = list(roster or [])
    host = socket.gethostname().strip().lower()
    home = str((Path.home() / ".grok")).replace("/", "\\").rstrip("\\").lower()
    for row in rows:
        if str(row.get("hostname") or "").strip().lower() == host:
            return _device_id(row)
    for row in rows:
        row_home = str(row.get("grok_home") or "").replace("/", "\\").rstrip("\\").lower()
        if row_home and row_home == home:
            return _device_id(row)
    user = os.environ.get("USERNAME") or Path.home().name
    return f"{user}@{socket.gethostname()}".lower()


def device_sections(
    sessions: list[dict[str, Any]] | None = None,
    *,
    roster_path: Path | None = None,
) -> list[dict[str, Any]]:
    """One section per known device. Local sessions belong to this device."""
    roster = merged_device_rows(roster_path)
    local_id = local_device_id(roster)
    if not roster:
        roster = [{"id": local_id, "hostname": socket.gethostname(), "username": os.environ.get("USERNAME") or ""}]
    sections: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in roster:
        device_id = _device_id(row)
        if not device_id or device_id in seen:
            continue
        seen.add(device_id)
        local = device_id == local_id
        host = str(row.get("hostname") or device_id)
        name = str(row.get("name") or "").strip()
        sections.append(
            {
                "id": device_id,
                "hostname": host,
                "label": f"{name} · {host}" if name and name.lower() != host.lower() else host,
                "local": local,
                "launcher": str(alpha_launcher_path()) if local else "",
                "launcher_rel": "launchers/Launch-Grok-Build-TUI.ps1",
                "pathway": session_pathway(),
                "tailscale_ip": str(row.get("tailscale_ip") or ""),
                "rustdesk_id": str(row.get("rustdesk_id") or ""),
                "sessions": list(sessions or []) if local else [],
            }
        )
    if local_id not in seen:
        sections.insert(
            0,
            {
                "id": local_id,
                "hostname": socket.gethostname(),
                "label": socket.gethostname(),
                "local": True,
                "launcher": str(alpha_launcher_path()),
                "launcher_rel": "launchers/Launch-Grok-Build-TUI.ps1",
                "pathway": session_pathway(),
                "tailscale_ip": "",
                "rustdesk_id": "",
                "sessions": list(sessions or []),
            },
        )
    return sections


def _process_rows() -> list[tuple[int, int, str]]:
    """pid, parent pid, and executable name for the current process snapshot."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    snapshot = 0x00000002

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    handle = kernel.CreateToolhelp32Snapshot(snapshot, 0)
    entry = ProcessEntry()
    entry.dwSize = ctypes.sizeof(ProcessEntry)
    rows: list[tuple[int, int, str]] = []
    ok = kernel.Process32FirstW(handle, ctypes.byref(entry))
    while ok:
        rows.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID), entry.szExeFile))
        ok = kernel.Process32NextW(handle, ctypes.byref(entry))
    kernel.CloseHandle(handle)
    return rows


def direct_grok_child(parent_pid: int, processes: list[tuple[int, int, str]] | None = None) -> int | None:
    """The grok.exe started by the launcher process, not a hook-fixer grandchild."""
    for pid, parent, name in processes if processes is not None else _process_rows():
        if parent == int(parent_pid) and name.lower() == "grok.exe":
            return pid
    return None


def grok_descendants(root_pid: int, processes: list[tuple[int, int, str]] | None = None) -> list[int]:
    """grok.exe processes started under the launcher, including through Windows Terminal."""
    rows = processes if processes is not None else _process_rows()
    children: dict[int, list[int]] = {}
    names: dict[int, str] = {}
    for pid, parent, name in rows:
        names[pid] = name
        children.setdefault(parent, []).append(pid)
    found: list[int] = []
    stack = list(children.get(int(root_pid), []))
    seen: set[int] = set()
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        if names.get(pid, "").lower() == "grok.exe":
            found.append(pid)
        stack.extend(children.get(pid, []))
    return found


def process_command_line(pid: int) -> str:
    """Command line without starting PowerShell. A PowerShell query was launching grok."""
    if os.name != "nt" or int(pid) <= 0:
        return ""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    ntdll.NtQueryInformationProcess.argtypes = [
        wintypes.HANDLE,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    ntdll.NtQueryInformationProcess.restype = ctypes.c_long
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return ""
    try:
        needed = ctypes.c_ulong(0)
        ntdll.NtQueryInformationProcess(handle, 60, None, 0, ctypes.byref(needed))
        size = max(int(needed.value), 1024)
        raw = ctypes.create_string_buffer(size)
        status = ntdll.NtQueryInformationProcess(handle, 60, raw, size, ctypes.byref(needed))
        if status != 0:
            return ""

        class _UnicodeString(ctypes.Structure):
            _fields_ = [
                ("Length", wintypes.USHORT),
                ("MaximumLength", wintypes.USHORT),
                ("Buffer", ctypes.c_void_p),
            ]

        info = _UnicodeString.from_buffer_copy(raw)
        if not info.Buffer or info.Length <= 0:
            return ""
        return ctypes.wstring_at(info.Buffer, info.Length // 2)
    except (OSError, ValueError):
        return ""
    finally:
        kernel.CloseHandle(handle)


def place_launched_window(pid: int) -> None:
    """Move a launched session to the saved geometry. The right edge stays 1927."""
    if os.environ.get("SILVIA_CONSOLE_RELAY") != "1":
        env = os.environ.copy()
        env["SILVIA_CONSOLE_RELAY"] = "1"
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from sessions_live import place_launched_window; "
                "place_launched_window(int(sys.argv[1]))",
                str(int(pid)),
            ],
            cwd=str(Path(__file__).resolve().parent),
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
            creationflags=0x00000008,
        )
        return
    geometry = json.loads((Path.home() / ".grok" / "launchers" / "window-geometry.json").read_text(encoding="utf-8"))
    left = int(geometry["left"])
    top = int(geometry["top"])
    width = int(geometry["width"])
    height = int(geometry["height"])
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetAncestor.restype = wintypes.HWND
    user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = (
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    )
    user32.SetWindowPos.restype = wintypes.BOOL
    kernel.FreeConsole()
    if not kernel.AttachConsole(int(pid)):
        raise OSError(ctypes.get_last_error() or 1)
    try:
        hwnd = int(kernel.GetConsoleWindow() or 0)
        if hwnd == 0:
            raise OSError("the new session has no window")
        root = int(user32.GetAncestor(hwnd, 2) or hwnd)
        targets = {hwnd, root}
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        user32.IsWindowVisible.argtypes = (wintypes.HWND,)
        user32.IsWindowVisible.restype = wintypes.BOOL

        def collect(window, _lparam):
            user32.GetWindowThreadProcessId(window, ctypes.byref(process_id))
            if int(process_id.value) == int(pid) and user32.IsWindowVisible(window):
                targets.add(int(window))
            return True

        callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(collect)
        user32.EnumWindows(callback, 0)
        # SWP_NOACTIVATE | SWP_NOZORDER | SWP_NOOWNERZORDER. Move only.
        # ShowWindow(SW_RESTORE) activates the window and puts it above the user.
        flags = 0x0010 | 0x0004 | 0x0200
        for target in targets:
            user32.SetWindowPos(target, 0, left, top, width, height, flags)
    finally:
        kernel.FreeConsole()


def is_new_tui_command(command_line: str) -> bool:
    text = command_line.lower()
    if "grok.exe" not in text:
        return False
    if "--prompt-file" in text or " update" in text:
        return False
    return True


def is_resumed_tui_command(command_line: str, session_id: str) -> bool:
    """True when this grok process is resuming that session and is not an updater."""
    if not is_new_tui_command(command_line):
        return False
    wanted = str(session_id or "").strip().lower()
    if not wanted:
        return False
    text = command_line.lower().replace(" ", "")
    return f"--resume={wanted}" in text or f"--resume{wanted}" in text


class _Started:
    def __init__(self, pid: int) -> None:
        self.pid = pid


def _after_launch(previous_window: int, background: bool) -> None:
    """Return the owner's window to the front after a visible launch.

    A background launch shows no window, so it leaves the foreground alone and
    never calls SetForegroundWindow or ShowWindow for the launched copy.
    """
    if background or previous_window <= 0:
        return
    _user32().SetForegroundWindow(previous_window)


def _shell_execute(file: str, parameters: str, directory: str, background: bool = False) -> _Started:
    """Start the pinned launcher in its own console without activating it.

    powershell.exe is intercepted by the hidden-helper shim, and that shim
    would open the session in front. powershell-host.exe is the same host
    without that interception. SW_SHOWNOACTIVATE shows the window behind
    whatever the user is already using. SILVIA_NOACTIVATE tells the launcher
    script not to restore or focus itself.
    """
    if os.name != "nt":
        raise OSError("shell launch is implemented for Windows")
    host = Path(r"C:\Users\Irika\.grok\bin\powershell-host.exe")
    image = str(host) if host.is_file() and Path(file).name.lower() == "powershell.exe" else file
    command = subprocess.list2cmdline([image]) + " " + parameters

    class _StartupInfo(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.c_void_p),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class _ProcessInfo(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateProcessW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(_StartupInfo),
        ctypes.POINTER(_ProcessInfo),
    ]
    kernel.CreateProcessW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    startup = _StartupInfo()
    startup.cb = ctypes.sizeof(startup)
    startup.dwFlags = 0x00000001
    # Start hidden. The launcher shows itself with SWP_NOACTIVATE when
    # SILVIA_NOACTIVATE is set, so the window never takes the foreground.
    startup.wShowWindow = 0
    startup.lpTitle = "Grok Build TUI"
    process = _ProcessInfo()
    command_buf = ctypes.create_unicode_buffer(command)
    env = os.environ.copy()
    env["SILVIA_NOACTIVATE"] = "1"
    if background:
        env["SILVIA_HIDDEN"] = "1"
    pairs = [f"{key}={value}" for key, value in env.items() if key and "\0" not in key and "\0" not in str(value)]
    env_buf = ctypes.create_unicode_buffer("\0".join(pairs) + "\0\0")
    user32 = _user32()
    previous = int(user32.GetForegroundWindow() or 0)
    ok = kernel.CreateProcessW(
        image,
        command_buf,
        None,
        None,
        False,
        0x00000010 | 0x00000400 | 0x00000200,
        ctypes.cast(env_buf, ctypes.c_void_p),
        directory,
        ctypes.byref(startup),
        ctypes.byref(process),
    )
    if not ok:
        raise OSError(ctypes.get_last_error() or 1, "the launcher did not start")
    pid = int(process.dwProcessId or 0)
    kernel.CloseHandle(process.hThread)
    kernel.CloseHandle(process.hProcess)
    if pid <= 0:
        raise OSError("the launcher did not return a process")
    time.sleep(1.2)
    _after_launch(previous, background)
    return _Started(pid)


def launch_new_session(
    cwd: str | None = None,
    *,
    launcher: str | None = None,
    resume_session: str | None = None,
    background: bool = False,
) -> _Started:
    """Start one session with the pinned Alpha shortcut's command.

    The shortcut is powershell.exe -NoExit -NoProfile -ExecutionPolicy Bypass
    -File Launch-Grok-Build-TUI.ps1, working directory C:\\WINDOWS\\system32.
    A history launch passes -ResumeSession so the launcher runs
    grok --resume=<id> where it would otherwise run grok. No positional
    prompt is added, because that would send a new turn into the session.
    A background launch starts the copy hidden and keeps the owner's window
    in front.
    """
    del cwd
    script = Path(launcher) if launcher else alpha_launcher_path()
    powershell = r"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe"
    parameters = f'-NoExit -NoProfile -ExecutionPolicy Bypass -File "{script}"'
    session_id = str(resume_session or "").strip()
    if session_id:
        parameters += f' -ResumeSession "{session_id}"'
    options = {"background": True} if background else {}
    return _shell_execute(powershell, parameters, r"C:\WINDOWS\system32", **options)


def start_resume_process(argv: list[str], cwd: str | None) -> subprocess.Popen[Any]:
    """Start the TUI in its own console. Do not capture its screen."""
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        title = "Grok Build TUI"
        if "--resume" in argv:
            index = argv.index("--resume")
            if index + 1 < len(argv):
                title = f"Grok Build TUI {argv[index + 1]}"
        startup.lpTitle = title
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = _SW_SHOWNORMAL
        kwargs["startupinfo"] = startup
        kwargs["creationflags"] = CREATE_NEW_CONSOLE | CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(list(argv), cwd=cwd or None, **kwargs)


def _foreground_pid(pid: int) -> None:
    if os.name != "nt" or pid <= 0:
        return
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (enum_proc, wintypes.LPARAM)
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user32.SetForegroundWindow.restype = wintypes.BOOL
    found: list[Any] = []

    def _enum(hwnd: Any, _lparam: Any) -> bool:
        proc_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
        if int(proc_id.value) == int(pid) and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
            return False
        return True

    callback = enum_proc(_enum)
    user32.EnumWindows(callback, 0)
    if not found:
        return
    user32.ShowWindow(found[0], _SW_RESTORE)
    user32.SetForegroundWindow(found[0])


def _stop_clone(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
            **_no_window(),
        )
        return
    try:
        os.kill(pid, 15)
    except OSError:
        pass


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        text = content.get("text")
        return text.strip() if isinstance(text, str) else ""
    if isinstance(content, list):
        parts = [_content_text(item) for item in content]
        return " ".join(part for part in parts if part).strip()
    return ""


def _update_of(obj: Any) -> dict[str, Any] | None:
    if not isinstance(obj, dict):
        return None
    params = obj.get("params")
    if not isinstance(params, dict):
        return None
    update = params.get("update")
    if isinstance(update, dict):
        return update
    return None


def event_line(update: dict[str, Any]) -> str | None:
    """One display line for a thought, an agent spawn, or a later live event."""
    kind = str(update.get("sessionUpdate") or "")
    if kind == "agent_thought_chunk":
        text = _content_text(update.get("content"))
        return f"Thinking: {text}" if text else None
    if kind == "subagent_spawned":
        label = str(update.get("description") or update.get("subagent_id") or "agent").strip()
        return f"agent spawn: {label}" if label else None
    if kind == "agent_message_chunk":
        text = _content_text(update.get("content"))
        return f"message: {text}" if text else None
    if kind in ("tool_call", "tool_call_update"):
        title = str(update.get("title") or "").strip()
        return f"tool: {title}" if title else None
    if kind == "task_backgrounded":
        label = str(update.get("description") or update.get("task_id") or "task").strip()
        return f"later: {label}" if label else None
    if kind == "background_tasks":
        tasks = update.get("tasks")
        if isinstance(tasks, list) and tasks:
            return "later: background"
    if kind == "user_message_chunk":
        text = _content_text(update.get("content"))
        return f"user: {text}" if text else None
    return None


def user_message_texts(path: Path) -> list[str]:
    """User message text already in the session log. Does not write the log."""
    if not path.is_file():
        return []
    found: list[str] = []
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return []
    with handle:
        for raw in handle:
            text = raw.strip()
            if not text:
                continue
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                continue
            update = _update_of(obj)
            if update is None or update.get("sessionUpdate") != "user_message_chunk":
                continue
            found.append(_content_text(update.get("content")))
    return found


def read_new_event_lines(path: Path, offset: int, partial: bytes) -> tuple[int, bytes, list[str]]:
    """Read updates.jsonl from offset and return the next offset, remainder, and lines."""
    if not path.is_file():
        return offset, partial, []
    try:
        size = path.stat().st_size
    except OSError:
        return offset, partial, []
    if size < offset:
        offset = 0
        partial = b""
    if size == offset:
        return offset, partial, []
    try:
        handle = path.open("rb")
    except OSError:
        return offset, partial, []
    with handle:
        handle.seek(offset)
        data = handle.read()
    offset += len(data)
    partial += data
    lines: list[str] = []
    while b"\n" in partial:
        raw, partial = partial.split(b"\n", 1)
        text = raw.decode("utf-8", "replace").strip()
        if not text:
            continue
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            continue
        update = _update_of(obj)
        if update is None:
            continue
        line = event_line(update)
        if line:
            lines.append(line[:500])
    return offset, partial, lines


class _CharUnion(ctypes.Union):
    _fields_ = [("UnicodeChar", wintypes.WCHAR), ("AsciiChar", wintypes.CHAR)]


class _KeyEvent(ctypes.Structure):
    _fields_ = [
        ("bKeyDown", wintypes.BOOL),
        ("wRepeatCount", wintypes.WORD),
        ("wVirtualKeyCode", wintypes.WORD),
        ("wVirtualScanCode", wintypes.WORD),
        ("uChar", _CharUnion),
        ("dwControlKeyState", wintypes.DWORD),
    ]


class _InputRecord(ctypes.Structure):
    _fields_ = [("EventType", wintypes.WORD), ("KeyEvent", _KeyEvent)]


def _broker_after_denied(err: int, kind: str, pid: int, text: str = "", keys: list | None = None) -> bool:
    """Hand a refused elevated console to the broker. Same-level consoles stay direct."""
    if int(err) != 5 or os.environ.get("SILVIA_CONSOLE_BROKER") == "1":
        return False
    from console_broker import relay_input, relay_records

    if kind == "input":
        relay_input(int(pid), text)
    else:
        relay_records(int(pid), list(keys or []))
    return True


def write_console_input(pid: int, text: str) -> None:
    """Relay one submitted line into the original process console. Does not start grok."""
    if os.environ.get("SILVIA_CONSOLE_RELAY") != "1":
        env = os.environ.copy()
        env["SILVIA_CONSOLE_RELAY"] = "1"
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import os,sys; from sessions_live import write_console_input; "
                    "write_console_input(int(sys.argv[1]), sys.argv[2])",
                    str(int(pid)),
                    str(text),
                ],
                cwd=str(Path(__file__).resolve().parent),
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
                creationflags=0x00000008,
            )
        except subprocess.TimeoutExpired as exc:
            raise OSError("console relay timed out") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise OSError(detail or f"console relay exited {completed.returncode}")
        return
    if os.name != "nt":
        raise OSError("console relay is implemented for Windows")
    number = int(pid)
    if number <= 0:
        raise OSError("the original session has no process")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.FreeConsole.argtypes = ()
    kernel.FreeConsole.restype = wintypes.BOOL
    kernel.AttachConsole.argtypes = (wintypes.DWORD,)
    kernel.AttachConsole.restype = wintypes.BOOL
    kernel.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        ctypes.c_uint32,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.WriteConsoleInputW.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_InputRecord),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel.WriteConsoleInputW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    if not kernel.AttachConsole(number):
        err = ctypes.get_last_error()
        retried = err == 5 and bool(kernel.FreeConsole()) and bool(kernel.AttachConsole(number))
        if not retried:
            if _broker_after_denied(err, "input", number, text):
                return
            raise OSError(err or ctypes.get_last_error() or 1)
    handle = None
    try:
        handle = kernel.CreateFileW("CONIN$", 0xC0000000, 3, None, 3, 0, None)
        if int(ctypes.cast(handle, ctypes.c_void_p).value or 0) in (0, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
            raise OSError(ctypes.get_last_error() or 1)
        records: list[_InputRecord] = []
        characters = list(text) + ["\r"]
        for character in characters:
            for down in (1, 0):
                record = _InputRecord()
                record.EventType = 0x0001
                record.KeyEvent.bKeyDown = down
                record.KeyEvent.wRepeatCount = 1
                if character == "\r":
                    record.KeyEvent.wVirtualKeyCode = 0x0D
                record.KeyEvent.uChar.UnicodeChar = character
                records.append(record)
        array = (_InputRecord * len(records))(*records)
        written = wintypes.DWORD()
        ok = kernel.WriteConsoleInputW(handle, array, len(records), ctypes.byref(written))
        if not ok or int(written.value) != len(records):
            raise OSError(ctypes.get_last_error() or 1)
    finally:
        if handle not in (None, 0):
            kernel.CloseHandle(handle)
        kernel.FreeConsole()


def write_console_plain(pid: int, text: str) -> None:
    """Type text into the original console without pressing Enter."""
    if os.environ.get("SILVIA_CONSOLE_RELAY") != "1":
        env = os.environ.copy()
        env["SILVIA_CONSOLE_RELAY"] = "1"
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import os,sys; from sessions_live import write_console_plain; "
                    "write_console_plain(int(sys.argv[1]), sys.argv[2])",
                    str(int(pid)),
                    str(text),
                ],
                cwd=str(Path(__file__).resolve().parent),
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
                creationflags=0x00000008,
            )
        except subprocess.TimeoutExpired as exc:
            raise OSError("console text timed out") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise OSError(detail or f"console text exited {completed.returncode}")
        return
    _write_console_records(pid, [(0, character, 0) for character in str(text)])


def write_console_chord(pid: int, virtual_key: int, character: str, control: int) -> None:
    """Send one key chord to the original console. Does not start grok."""
    if os.environ.get("SILVIA_CONSOLE_RELAY") != "1":
        env = os.environ.copy()
        env["SILVIA_CONSOLE_RELAY"] = "1"
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import os,sys; from sessions_live import write_console_chord; "
                    "write_console_chord(int(sys.argv[1]), int(sys.argv[2]), chr(int(sys.argv[3])), int(sys.argv[4]))",
                    str(int(pid)),
                    str(int(virtual_key)),
                    str(ord(character or "\0")),
                    str(int(control)),
                ],
                cwd=str(Path(__file__).resolve().parent),
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
                creationflags=0x00000008,
            )
        except subprocess.TimeoutExpired as exc:
            raise OSError("console chord timed out") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise OSError(detail or f"console chord exited {completed.returncode}")
        return
    _write_console_records(pid, [(int(virtual_key), character or "\0", int(control))])


def _write_console_records(pid: int, keys: list[tuple[int, str, int]]) -> None:
    if os.name != "nt":
        raise OSError("console relay is implemented for Windows")
    number = int(pid)
    if number <= 0:
        raise OSError("the original session has no process")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.FreeConsole.argtypes = ()
    kernel.FreeConsole.restype = wintypes.BOOL
    kernel.AttachConsole.argtypes = (wintypes.DWORD,)
    kernel.AttachConsole.restype = wintypes.BOOL
    kernel.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        ctypes.c_uint32,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.WriteConsoleInputW.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_InputRecord),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel.WriteConsoleInputW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    if not kernel.AttachConsole(number):
        err = ctypes.get_last_error()
        retried = err == 5 and bool(kernel.FreeConsole()) and bool(kernel.AttachConsole(number))
        if not retried:
            if _broker_after_denied(err, "records", number, keys=keys):
                return
            raise OSError(err or ctypes.get_last_error() or 1)
    handle = None
    try:
        handle = kernel.CreateFileW("CONIN$", 0xC0000000, 3, None, 3, 0, None)
        if int(ctypes.cast(handle, ctypes.c_void_p).value or 0) in (0, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
            raise OSError(ctypes.get_last_error() or 1)
        records: list[_InputRecord] = []
        for virtual_key, character, control in keys:
            for down in (1, 0):
                record = _InputRecord()
                record.EventType = 0x0001
                record.KeyEvent.bKeyDown = down
                record.KeyEvent.wRepeatCount = 1
                record.KeyEvent.wVirtualKeyCode = int(virtual_key)
                record.KeyEvent.dwControlKeyState = int(control)
                record.KeyEvent.uChar.UnicodeChar = character or "\0"
                records.append(record)
        array = (_InputRecord * len(records))(*records)
        written = wintypes.DWORD()
        ok = kernel.WriteConsoleInputW(handle, array, len(records), ctypes.byref(written))
        if not ok or int(written.value) != len(records):
            raise OSError(ctypes.get_last_error() or 1)
    finally:
        if handle not in (None, 0):
            kernel.CloseHandle(handle)
        kernel.FreeConsole()


class _Coord(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class _SmallRect(ctypes.Structure):
    _fields_ = [
        ("Left", ctypes.c_short),
        ("Top", ctypes.c_short),
        ("Right", ctypes.c_short),
        ("Bottom", ctypes.c_short),
    ]


class _ConsoleInfo(ctypes.Structure):
    _fields_ = [
        ("dwSize", _Coord),
        ("dwCursorPosition", _Coord),
        ("wAttributes", wintypes.WORD),
        ("srWindow", _SmallRect),
        ("dwMaximumWindowSize", _Coord),
    ]


class _CharInfo(ctypes.Structure):
    _fields_ = [("UnicodeChar", wintypes.WCHAR), ("Attributes", wintypes.WORD)]


def _attached_call(pid: int, action: str) -> subprocess.CompletedProcess[bytes]:
    """Run one console action in a process that is free to AttachConsole."""
    env = os.environ.copy()
    env["SILVIA_CONSOLE_RELAY"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from sessions_live import _console_action; "
            "sys.stdout.buffer.write(_console_action(sys.argv[1], int(sys.argv[2])))",
            action,
            str(int(pid)),
        ],
        cwd=str(Path(__file__).resolve().parent),
        env=env,
        capture_output=True,
        check=False,
        timeout=20,
        creationflags=0x00000008,
    )


def _console_action(action: str, pid: int) -> bytes:
    """Attach to pid and either show its console or return its visible screen."""
    if os.name != "nt":
        raise OSError("console attach is implemented for Windows")
    number = int(pid)
    if number <= 0:
        raise OSError("the original session has no process")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel.FreeConsole.argtypes = ()
    kernel.FreeConsole.restype = wintypes.BOOL
    kernel.AttachConsole.argtypes = (wintypes.DWORD,)
    kernel.AttachConsole.restype = wintypes.BOOL
    kernel.GetConsoleWindow.restype = wintypes.HWND
    kernel.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        ctypes.c_uint32,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetConsoleScreenBufferInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ConsoleInfo))
    kernel.GetConsoleScreenBufferInfo.restype = wintypes.BOOL
    kernel.ReadConsoleOutputW.argtypes = (
        wintypes.HANDLE,
        ctypes.c_void_p,
        _Coord,
        _Coord,
        ctypes.POINTER(_SmallRect),
    )
    kernel.ReadConsoleOutputW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user32.SetForegroundWindow.restype = wintypes.BOOL
    kernel.FreeConsole()
    if not kernel.AttachConsole(number):
        raise OSError(ctypes.get_last_error() or 1)
    try:
        hwnd = kernel.GetConsoleWindow()
        if action == "show":
            # Report the handle only. Restoring or focusing here pulls the
            # original session above whatever the user is doing.
            return str(int(hwnd or 0)).encode("ascii")
        handle = kernel.CreateFileW("CONOUT$", 0x80000000, 3, None, 3, 0, None)
        value = int(ctypes.cast(handle, ctypes.c_void_p).value or 0)
        if value in (0, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
            raise OSError(ctypes.get_last_error() or 1)
        try:
            info = _ConsoleInfo()
            if not kernel.GetConsoleScreenBufferInfo(handle, ctypes.byref(info)):
                raise OSError(ctypes.get_last_error() or 1)
            left = int(info.srWindow.Left)
            top = int(info.srWindow.Top)
            right = int(info.srWindow.Right)
            bottom = int(info.srWindow.Bottom)
            width = max(1, min(200, right - left + 1))
            height = max(1, min(40, bottom - top + 1))
            buffer = (_CharInfo * (width * height))()
            rect = _SmallRect(left, top, left + width - 1, top + height - 1)
            ok = kernel.ReadConsoleOutputW(
                handle,
                buffer,
                _Coord(width, height),
                _Coord(0, 0),
                ctypes.byref(rect),
            )
            if not ok:
                raise OSError(ctypes.get_last_error() or 1)
            rows: list[str] = []
            for y in range(height):
                chars: list[str] = []
                for x in range(width):
                    char = buffer[y * width + x].UnicodeChar
                    chars.append(char if char and char != "\x00" else " ")
                rows.append("".join(chars).rstrip())
            return "\n".join(rows).encode("utf-8")
        finally:
            kernel.CloseHandle(handle)
    finally:
        kernel.FreeConsole()


def show_session_console(pid: int) -> int:
    """Restore the original Grok console window. Does not start a process."""
    if os.environ.get("SILVIA_CONSOLE_RELAY") == "1":
        raise OSError("show_session_console is the outer call")
    try:
        completed = _attached_call(pid, "show")
    except subprocess.TimeoutExpired as exc:
        raise OSError("console show timed out") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or b"").decode("utf-8", "replace").strip()
        raise OSError(detail or f"console show exited {completed.returncode}")
    text = completed.stdout.decode("ascii", "replace").strip()
    return int(text or "0")


def console_screen_text(pid: int) -> str:
    """Visible characters on the original Grok TUI. Does not read updates.jsonl."""
    if os.environ.get("SILVIA_CONSOLE_RELAY") == "1":
        return _console_action("screen", pid).decode("utf-8", "replace")
    try:
        completed = _attached_call(pid, "screen")
    except subprocess.TimeoutExpired as exc:
        raise OSError("console screen read timed out") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or b"").decode("utf-8", "replace").strip()
        raise OSError(detail or f"console screen read exited {completed.returncode}")
    return completed.stdout.decode("utf-8", "replace")


def session_screen_text(pid: int) -> str:
    """Visible console text. An elevated session is read by the broker."""
    try:
        return console_screen_text(pid)
    except OSError:
        from console_broker import relay_screen

        return relay_screen(int(pid))


def _ppm_is_blank(ppm: bytes) -> bool:
    """True when a capture has no readable console text."""
    if ppm.startswith(b"\x89PNG"):
        return False
    if not ppm.startswith(b"P6"):
        return True
    _header, _, rest = ppm.partition(b"\n")
    _size, _, pixels = rest.partition(b"\n")
    _max, _, body = pixels.partition(b"\n")
    if len(body) < 30:
        return True
    lit = seen = 0
    for index in range(0, len(body) - 3, 60):
        seen += 1
        if max(body[index], body[index + 1], body[index + 2]) > 60:
            lit += 1
    return seen == 0 or (lit / seen) < 0.01


def _ppm_from_screen_text(text: str) -> bytes:
    """Draw console text when the window bitmap itself is black."""
    from PIL import Image, ImageDraw, ImageFont

    width, height = 960, 540
    image = Image.new("RGB", (width, height), (28, 28, 28))
    draw = ImageDraw.Draw(image)
    font_path = Path(r"C:\Windows\Fonts\consola.ttf")
    font = ImageFont.truetype(str(font_path), 15) if font_path.is_file() else ImageFont.load_default()
    draw.text((12, 10), text[:8000], fill=(232, 232, 232), font=font)
    return f"P6\n{width} {height}\n255\n".encode("ascii") + image.tobytes()


def _window_class(user32: Any, hwnd: int) -> str:
    user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetClassNameW.restype = ctypes.c_int
    name = ctypes.create_unicode_buffer(160)
    user32.GetClassNameW(hwnd, name, 160)
    return str(name.value)


def _picture_hwnd(user32: Any, hwnd: int) -> int:
    """The window that actually draws this session.

    A ConPTY host exposes a PseudoConsoleWindow whose own bitmap is black.
    Its owner is the Windows Terminal window, and that window has the picture.
    """
    if hwnd <= 0:
        return 0
    if _window_class(user32, hwnd) != "PseudoConsoleWindow":
        return hwnd
    user32.GetParent.argtypes = (wintypes.HWND,)
    user32.GetParent.restype = wintypes.HWND
    parent = int(user32.GetParent(hwnd) or 0)
    if parent and _window_class(user32, parent) == "CASCADIA_HOSTING_WINDOW_CLASS":
        return parent
    return hwnd


def _ppm_of_window(user32: Any, gdi: Any, hwnd: int) -> bytes:
    """One PPM image of the session client area. Does not move, focus, or resize it."""
    hwnd = _picture_hwnd(user32, hwnd)
    user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user32.GetClientRect.restype = wintypes.BOOL
    client = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(client)):
        raise OSError(ctypes.get_last_error() or 1)
    width = int(client.right - client.left)
    height = int(client.bottom - client.top)
    if width < 2 or height < 2:
        raise OSError("the Grok window has no visible size")
    source_dc = user32.GetDC(None if _window_class(user32, hwnd) == "CASCADIA_HOSTING_WINDOW_CLASS" else hwnd)
    if not source_dc:
        raise OSError(ctypes.get_last_error() or 1)
    hdc_window = source_dc
    mem_dc = gdi.CreateCompatibleDC(source_dc)
    bitmap = gdi.CreateCompatibleBitmap(source_dc, width, height)
    old = gdi.SelectObject(mem_dc, bitmap)
    try:
        # BitBlt copies the window without activating it. PrintWindow with
        # PW_RENDERFULLCONTENT asks the console to render and pulls that
        # session to the front, so a live copy kept an older session on top.
        gdi.BitBlt.argtypes = (
            wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.DWORD,
        )
        gdi.BitBlt.restype = wintypes.BOOL
        use_full = _window_class(user32, hwnd) == "CASCADIA_HOSTING_WINDOW_CLASS"
        if use_full:
            # The terminal surface is not in the window DC. Flag 2 renders it
            # and, unlike ShowWindow, does not pull the session forward.
            copied = bool(user32.PrintWindow(hwnd, mem_dc, 2))
        else:
            copied = bool(gdi.BitBlt(mem_dc, 0, 0, width, height, hdc_window, 0, 0, 0x00CC0020))
            if not copied:
                copied = bool(user32.PrintWindow(hwnd, mem_dc, 1))
        if not copied:
            raise OSError(ctypes.get_last_error() or 1)

        class _BitmapInfoHeader(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        header = _BitmapInfoHeader()
        header.biSize = ctypes.sizeof(_BitmapInfoHeader)
        header.biWidth = width
        header.biHeight = height
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0
        pixels = ctypes.create_string_buffer(width * height * 4)
        if gdi.GetDIBits(mem_dc, bitmap, 0, height, pixels, ctypes.byref(header), 0) == 0:
            raise OSError(ctypes.get_last_error() or 1)
    finally:
        gdi.SelectObject(mem_dc, old)
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(mem_dc)
        release = None if _window_class(user32, hwnd) == "CASCADIA_HOSTING_WINDOW_CLASS" else hwnd
        user32.ReleaseDC(release, hdc_window)
    rgb = bytearray(width * height * 3)
    source = pixels.raw
    for y in range(height):
        src_row = (height - 1 - y) * width * 4
        dst_row = y * width * 3
        for x in range(width):
            src = src_row + x * 4
            dst = dst_row + x * 3
            rgb[dst] = source[src + 2]
            rgb[dst + 1] = source[src + 1]
            rgb[dst + 2] = source[src]
    header_text = f"P6\n{width} {height}\n255\n".encode("ascii")
    return header_text + bytes(rgb)


def _write_mirror(payload: bytes) -> None:
    """Write one mirror message. A Windows pipe rejects one write above 32KB."""
    raw = getattr(sys.stdout.buffer, "raw", sys.stdout.buffer)
    view = memoryview(payload)
    offset = 0
    while offset < len(view):
        end = min(len(view), offset + 4000)
        raw.write(view[offset:end])
        offset = end
    flush = getattr(raw, "flush", None)
    if flush is not None:
        flush()


def _parent_pid(pid: int) -> int:
    if os.name != "nt" or int(pid) <= 0:
        return 0
    class _Basic(ctypes.Structure):
        _fields_ = [
            ("ExitStatus", ctypes.c_long),
            ("PebBaseAddress", ctypes.c_void_p),
            ("AffinityMask", ctypes.c_void_p),
            ("BasePriority", ctypes.c_void_p),
            ("UniqueProcessId", ctypes.c_void_p),
            ("InheritedFromUniqueProcessId", ctypes.c_void_p),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    ntdll.NtQueryInformationProcess.argtypes = [
        wintypes.HANDLE,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    ntdll.NtQueryInformationProcess.restype = ctypes.c_long
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return 0
    try:
        info = _Basic()
        needed = ctypes.c_ulong(0)
        status = ntdll.NtQueryInformationProcess(
            handle, 0, ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(needed)
        )
        if status != 0:
            return 0
        return int(info.InheritedFromUniqueProcessId or 0)
    finally:
        kernel.CloseHandle(handle)


def _visible_session_hwnd(pid: int) -> int:
    """The on-screen console for this process, without attaching to it.

    An elevated session refuses AttachConsole from the normal dashboard.
    The window can still be photographed from outside.
    """
    pids: set[int] = set()
    current = int(pid)
    for _ in range(8):
        if current <= 0 or current in pids:
            break
        pids.add(current)
        current = _parent_pid(current)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindowVisible.restype = wintypes.BOOL
    found: list[tuple[int, int]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(160)
        user32.GetClassNameW(hwnd, cls, 160)
        if cls.value not in {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"}:
            return True
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if int(owner.value) not in pids:
            return True
        rank = 0 if cls.value == "ConsoleWindowClass" else 1
        found.append((rank, int(hwnd)))
        return True

    user32.EnumWindows(_cb, 0)
    if not found:
        return 0
    found.sort()
    return found[0][1]


MIRROR_INTERVAL_S = 0.2
REMOTE_MIRROR_INTERVAL_S = 0.1
REMOTE_MIRROR_MAX_WIDTH = 640
REMOTE_POLL_MS = 100


def scale_ppm(ppm: bytes, max_width: int) -> bytes:
    """A smaller whole picture. The header still matches the pixel count."""
    if max_width <= 0 or not ppm.startswith(b"P6\n"):
        return ppm
    header, marker, body = ppm.partition(b"\n255\n")
    if marker != b"\n255\n":
        return ppm
    try:
        width, height = (int(part) for part in header.split()[1:3])
    except (ValueError, IndexError):
        return ppm
    if width <= max_width or width < 2 or height < 2 or len(body) < width * height * 3:
        return ppm
    new_width = max_width
    new_height = max(1, int(round(height * new_width / width)))
    from PIL import Image

    image = Image.frombytes("RGB", (width, height), body[: width * height * 3])
    image = image.resize((new_width, new_height), Image.BILINEAR)
    scaled = image.tobytes()
    return f"P6\n{new_width} {new_height}\n255\n".encode("ascii") + scaled


def _ppm_size(ppm: bytes) -> tuple[int, int, bytes] | None:
    header, marker, body = ppm.partition(b"\n255\n")
    if marker != b"\n255\n" or not header.startswith(b"P6"):
        return None
    try:
        width, height = (int(part) for part in header.split()[1:3])
    except (ValueError, IndexError):
        return None
    count = width * height * 3
    if width < 1 or height < 1 or len(body) < count:
        return None
    return width, height, body[:count]


def png_from_ppm(ppm: bytes) -> bytes:
    """Lossless full-size picture, smaller on the wire than raw pixels."""
    parsed = _ppm_size(ppm)
    if parsed is None:
        return ppm
    width, height, body = parsed
    from PIL import Image
    import io

    image = Image.frombytes("RGB", (width, height), body)
    out = io.BytesIO()
    image.save(out, format="PNG", compress_level=1)
    return out.getvalue()


def ppm_from_png(png: bytes) -> bytes:
    """Decode one compressed picture back to a whole PPM frame."""
    from PIL import Image
    import io

    image = Image.open(io.BytesIO(png)).convert("RGB")
    width, height = image.size
    return f"P6\n{width} {height}\n255\n".encode("ascii") + image.tobytes()


def serve_console_mirror(
    pid: int,
    interval: float = MIRROR_INTERVAL_S,
    max_width: int = 0,
    compress: bool = False,
) -> None:
    """Write PPM frames of the original Grok window to stdout. Does not show it."""
    pace = interval if interval > 0 else MIRROR_INTERVAL_S
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel.FreeConsole.argtypes = ()
    kernel.FreeConsole.restype = wintypes.BOOL
    kernel.AttachConsole.argtypes = (wintypes.DWORD,)
    kernel.AttachConsole.restype = wintypes.BOOL
    kernel.GetConsoleWindow.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetDC.argtypes = (wintypes.HWND,)
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
    user32.ReleaseDC.restype = ctypes.c_int
    user32.PrintWindow.argtypes = (wintypes.HWND, wintypes.HDC, wintypes.UINT)
    user32.PrintWindow.restype = wintypes.BOOL
    gdi.CreateCompatibleDC.argtypes = (wintypes.HDC,)
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateCompatibleBitmap.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int)
    gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)
    gdi.SelectObject.restype = wintypes.HGDIOBJ
    gdi.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
    gdi.DeleteObject.restype = wintypes.BOOL
    gdi.DeleteDC.argtypes = (wintypes.HDC,)
    gdi.DeleteDC.restype = wintypes.BOOL
    gdi.GetDIBits.argtypes = (
        wintypes.HDC,
        wintypes.HBITMAP,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.UINT,
    )
    gdi.GetDIBits.restype = ctypes.c_int
    kernel.FreeConsole()
    attached = bool(kernel.AttachConsole(int(pid)))
    hwnd = int(kernel.GetConsoleWindow() or 0) if attached else 0
    if hwnd == 0:
        hwnd = _visible_session_hwnd(int(pid))
    if hwnd == 0:
        if attached:
            kernel.FreeConsole()
        raise OSError(ctypes.get_last_error() or 1, "the original session has no Grok window")
    if sys.stdout is None or not hasattr(sys.stdout, "buffer"):
        if attached:
            kernel.FreeConsole()
        raise OSError("the mirror has no stdout pipe")
    user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetAncestor.restype = wintypes.HWND
    hwnd = _picture_hwnd(user32, hwnd)
    root = int(user32.GetAncestor(hwnd, 2) or hwnd)
    try:
        _write_mirror(b"HWND" + int(root).to_bytes(8, "little"))
        while True:
            try:
                frame = _ppm_of_window(user32, gdi, hwnd)
                if max_width > 0:
                    frame = scale_ppm(frame, max_width)
                if compress:
                    frame = png_from_ppm(frame)
            except Exception:
                # One missed capture used to kill the mirror and leave the copy black.
                traceback.print_exc()
                time.sleep(pace)
                continue
            try:
                _write_mirror(len(frame).to_bytes(4, "little") + frame)
            except Exception:
                traceback.print_exc()
                return
            time.sleep(pace)
    finally:
        kernel.FreeConsole()


class SessionPopout:
    """Live picture of one original Grok window.

    The window shows that process's console window. It does not start
    grok --resume, it does not follow updates.jsonl, and it does not bring
    the original window forward. Copy input is relayed only when this view
    submits it.
    """

    def __init__(self, master: Any, row: dict[str, Any], *, grok_exe: Path | None = None):
        del grok_exe
        self.session_id = str(row.get("session_id") or "").strip()
        self._remote_ip = str(row.get("remote_ip") or "").strip()
        self._remote_reader: Any = None
        self._remote_connect_started = False
        self._original_pid = _parse_pid(row.get("pid")) or 0
        self._cwd = str(row.get("cwd") or "")
        self.argv: list[str] = []
        self.pid = 0
        self.process: Any = None
        self.reads_transcript = False
        self.shows_console_tui = True
        self.shows_live_window = True
        self.console_hwnd = 0
        self.relayed_lines: list[str] = []
        self.visible_screen = ""
        self._placeholder_on = False
        self._multiline = False
        self._queued = False
        self._stash = ""
        self._stash_on_send = False
        self._restore_armed = False
        self._last_esc = 0.0
        self._history: list[str] = []
        self._history_at: int | None = None
        self._chrome = (0x1C, 0x1C, 0x1C)
        self._text_fg = "#e8e8e8"
        self._placeholder_fg = "#8d8d8d"
        self.frame_bytes = b""
        self._frame_lock = threading.Lock()
        self._mirror: Any = None
        self._mirror_thread: threading.Thread | None = None
        self._mirror_attempts = 0
        self._mirror_log: Any = None
        self._mirror_log_path: Path | None = None
        self._pid_looked = False
        self._closed = False
        self._status: Any = None
        self._after_id: str | None = None
        self.window: Any = None
        self._text: Any = None
        self._image: Any = None
        self._photo: Any = None
        self._entry: Any = None
        self._frame_path: Path | None = None
        self._master = master
        updates = row.get("updates_path")
        self.updates = Path(updates) if updates else Path()
        if not self.session_id:
            self._user_baseline: list[str] = []
            return
        register_opened_view(self.session_id)
        self._open_window(master)
        try:
            self._user_baseline = user_message_texts(self.updates)
        except Exception:
            self._user_baseline = []
        self._start_mirror()

    def _resolve_pid(self) -> None:
        if self._original_pid:
            return
        try:
            rows = live_sessions()
        except Exception:
            return
        for row in rows:
            if str(row.get("session_id") or "") != self.session_id:
                continue
            self._original_pid = _parse_pid(row.get("pid")) or 0
            updates = row.get("updates_path")
            if updates and not self.updates.is_file():
                self.updates = Path(str(updates))
            return

    def _mirror_log_text(self) -> str:
        path = self._mirror_log_path
        if path is None or not path.is_file():
            return ""
        try:
            data = path.read_bytes()[-2000:]
        except OSError:
            return ""
        return " ".join(data.decode("utf-8", "replace").split())

    def _set_status(self, text: str) -> None:
        label = self._status
        if label is None:
            return
        message = " ".join(str(text or "").split())
        if message == getattr(self, "_status_text", None):
            return
        self._status_text = message
        try:
            if not message:
                label.pack_forget()
                return
            label.configure(text=message[:500])
            if not label.winfo_ismapped():
                label.pack(side="top", fill="x", before=self._image)
        except Exception:
            return

    def _start_mirror(self) -> None:
        if self._closed:
            return
        if self._remote_ip:
            self._start_remote_mirror()
            return
        mirror = self._mirror
        if mirror is not None and mirror.poll() is None:
            return
        if not self._original_pid and not self._pid_looked:
            self._pid_looked = True
            self._resolve_pid()
        if not self._original_pid or self.window is None:
            self._set_status("This session has no running process, so there is no picture.")
            return
        if self._mirror_attempts >= 5:
            detail = self._mirror_log_text()
            self._set_status(detail or "The session picture stopped.")
            return
        mirror_python = sys.executable
        exe = Path(sys.executable)
        if exe.name.lower() in ("pythonw.exe", "pyw.exe"):
            sibling = exe.with_name("python.exe")
            if not sibling.is_file():
                sibling = exe.with_name("py.exe")
            if sibling.is_file():
                mirror_python = str(sibling)
            else:
                self._set_status("The session picture needs python.exe beside pythonw.exe.")
                return
        log_path = Path(os.environ.get("TEMP", ".")) / f"silvia-mirror-{self.session_id}.log"
        self._mirror_log_path = log_path
        previous = self._mirror_log
        self._mirror_log = None
        if previous is not None:
            try:
                previous.close()
            except Exception:
                pass
        try:
            log_handle = open(log_path, "ab", buffering=0)
        except OSError as exc:
            self._set_status(f"The session picture could not be logged: {exc}")
            return
        env = os.environ.copy()
        env["SILVIA_CONSOLE_RELAY"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        self._mirror_attempts += 1
        try:
            self._mirror = subprocess.Popen(
                [
                    mirror_python,
                    "-c",
                    "import sys,traceback\n"
                    "try:\n"
                    " from sessions_live import serve_console_mirror\n"
                    " serve_console_mirror(int(sys.argv[1]))\n"
                    "except Exception:\n"
                    " traceback.print_exc()\n"
                    " raise\n",
                    str(self._original_pid),
                ],
                cwd=str(Path(__file__).resolve().parent),
                env=env,
                stdout=subprocess.PIPE,
                stderr=log_handle,
                creationflags=0x00000008,
            )
        except Exception as exc:
            self._mirror_log = log_handle
            self._set_status(f"The session picture did not start: {exc}")
            return
        self._mirror_log = log_handle
        self._set_status("Opening the session picture...")
        self._mirror_thread = threading.Thread(target=self._read_mirror, daemon=True)
        self._mirror_thread.start()

    def _start_remote_mirror(self) -> None:
        """Show the picture from the device that owns the session."""
        if self._closed or self.window is None or self._remote_connect_started:
            return
        if time.monotonic() < float(getattr(self, "_remote_retry_at", 0) or 0):
            return
        self._remote_connect_started = True
        from dashboard_debug import note

        note("picture-open", f"{self._remote_ip} {self.session_id}")
        self._set_status(f"Opening the session picture on {self._remote_ip}...")
        threading.Thread(target=self._connect_remote_mirror, daemon=True).start()

    def _connect_remote_mirror(self) -> None:
        from remote_sessions import open_watch

        try:
            reader = open_watch(self._remote_ip, self.session_id)
        except OSError as exc:
            from dashboard_debug import note

            note("picture-failed", str(exc))
            self._remote_connect_started = False
            self._remote_retry_at = time.monotonic() + 1.0
            message = f"This computer did not show the picture: {exc}"

            def fail() -> None:
                if not self._closed:
                    self._set_status(message)

            window = self.window
            if window is not None:
                try:
                    window.after(0, fail)
                except Exception:
                    pass
            return
        if self._closed:
            reader.close()
            return
        from dashboard_debug import note

        note("picture-connected", self.session_id)
        self._remote_reader = reader
        self._mirror_stdout = reader
        self._mirror_thread = threading.Thread(target=self._read_mirror, daemon=True)
        self._mirror_thread.start()

    def _read_mirror(self) -> None:
        stream = getattr(self, "_mirror_stdout", None)
        if stream is None:
            mirror = self._mirror
            if mirror is None or mirror.stdout is None:
                return
            stream = mirror.stdout
        while True:
            header = stream.read(4)
            if len(header) < 4:
                if self._remote_ip:
                    self._arm_remote_reconnect("the picture stream ended")
                return
            if header == b"HWND":
                raw = stream.read(8)
                if len(raw) < 8:
                    if self._remote_ip:
                        self._arm_remote_reconnect("the window id was cut off")
                    return
                hwnd = int.from_bytes(raw, "little")
                if hwnd > 0 and not self._remote_ip:
                    self.console_hwnd = hwnd
                elif hwnd > 0 and self._remote_ip:
                    from dashboard_debug import note

                    note(
                        "picture-hwnd",
                        f"kept open; ignored window {hwnd} from the other computer",
                    )
                continue
            size = int.from_bytes(header, "little")
            if size <= 0 or size > 40_000_000:
                if self._remote_ip:
                    self._arm_remote_reconnect(f"bad frame size {size}")
                return
            frame = stream.read(size)
            if len(frame) < size:
                if self._remote_ip:
                    self._arm_remote_reconnect("a frame was cut off")
                return
            with self._frame_lock:
                self.frame_bytes = frame

    def _latest_buffered_frame(self, stream: Any, frame: bytes) -> bytes:
        """Show the newest picture already waiting, so a slow link does not replay old ones."""
        pending = getattr(stream, "pending", None)
        unread = getattr(stream, "unread", None)
        if not callable(pending) or not callable(unread):
            return frame
        latest = frame
        for _ in range(8):
            if int(pending() or 0) < 4:
                break
            header = stream.read(4)
            if len(header) < 4:
                unread(header)
                break
            if header == b"HWND":
                if int(pending() or 0) < 8:
                    unread(header)
                    break
                raw = stream.read(8)
                if len(raw) < 8:
                    unread(header + raw)
                    break
                continue
            size = int.from_bytes(header, "little")
            if size <= 0 or size > 40_000_000 or int(pending() or 0) < size:
                unread(header)
                break
            nxt = stream.read(size)
            if len(nxt) < size:
                unread(header + nxt)
                break
            latest = nxt
        return latest

    def _arm_remote_reconnect(self, reason: str) -> None:
        """The picture stream ended. Open it again instead of staying blank."""
        from dashboard_debug import note

        note("picture-reconnect", reason)
        reader = getattr(self, "_remote_reader", None)
        self._remote_reader = None
        if reader is not None:
            try:
                reader.close()
            except Exception:
                pass
        self._remote_connect_started = False
        self._remote_retry_at = time.monotonic() + 1.0
        self._status_later("The picture stopped. Reconnecting...")

    def _open_window(self, master: Any) -> None:
        import tkinter as tk

        self.window = tk.Toplevel(master)
        self.window.title(f"Grok TUI {self.session_id}")
        self.window.configure(background="#1c1c1c")
        self.window.geometry("990x633+937+40")
        self._raise_copy()
        self._image = tk.Label(self.window, background="#1c1c1c")
        self._image.pack(side="top", fill="both", expand=True)
        self._status = tk.Label(
            self.window,
            text="",
            background="#1c1c1c",
            foreground="#f2d2d2",
            anchor="w",
            justify="left",
            wraplength=920,
            font=("Segoe UI", 12),
        )
        self._entry = tk.Text(
            self.window,
            height=3,
            wrap="word",
            undo=True,
            background="#1c1c1c",
            foreground=self._placeholder_fg,
            insertbackground=self._text_fg,
            relief="flat",
            borderwidth=8,
            highlightthickness=0,
            font=("Consolas", 11),
        )
        self._entry.pack(side="bottom", fill="x")
        self._show_placeholder()
        self._entry.bind("<KeyPress>", self._before_type)
        self._entry.bind("<KeyRelease>", self._after_type)
        self._entry.bind("<Return>", self._on_return)
        self._entry.bind("<KP_Enter>", self._on_return)
        self._entry.bind("<Shift-Return>", self._on_shift_return)
        self._entry.bind("<Alt-Return>", self._on_shift_return)
        self._entry.bind("<Control-Return>", self._on_send_now)
        self._entry.bind("<Control-i>", self._on_send_now)
        self._entry.bind("<Control-c>", self._on_ctrl_c)
        self._entry.bind("<Escape>", self._on_escape)
        self._entry.bind("<Control-s>", self._on_stash)
        self._entry.bind("<Alt-s>", self._on_stash)
        self._entry.bind("<Control-z>", self._on_undo)
        self._entry.bind("<Control-m>", self._on_multiline)
        self._entry.bind("<Up>", self._on_history_up)
        self._entry.bind("<Down>", self._on_history_down)
        self._entry.bind("<Shift-Tab>", lambda _event: self._forward_chord(0x09, "\t", 0x0010))
        self._entry.bind("<Control-p>", lambda _event: self._forward_chord(0x50, "\x10", 0x0008))
        self._entry.bind("<Control-o>", lambda _event: self._forward_chord(0x4F, "\x0f", 0x0008))
        self._entry.bind("<Control-r>", lambda _event: self._forward_chord(0x52, "\x12", 0x0008))
        self._entry.bind("<Control-b>", lambda _event: self._forward_chord(0x42, "\x02", 0x0008))
        self._entry.bind("<Control-t>", lambda _event: self._forward_chord(0x54, "\x14", 0x0008))
        self._entry.bind("<Control-g>", lambda _event: self._forward_chord(0x47, "\x07", 0x0008))
        self._entry.bind("<Control-l>", lambda _event: self._forward_chord(0x4C, "\x0c", 0x0008))
        self._entry.bind("<Control-n>", lambda _event: self._forward_chord(0x4E, "\x0e", 0x0008))
        self._entry.bind("<Control-q>", lambda _event: self._forward_chord(0x51, "\x11", 0x0008))
        self._entry.bind("<Control-x>", lambda _event: self._forward_chord(0x58, "\x18", 0x0008))
        self._entry.bind("<Control-period>", lambda _event: self._forward_chord(0xBE, ".", 0x0008))
        self._entry.bind("<F2>", lambda _event: self._forward_chord(0x71, "\0", 0))
        self._entry.bind("<Control-semicolon>", lambda _event: self._forward_chord(0xBA, ";", 0x0008))
        self._entry.bind("<Control-apostrophe>", lambda _event: self._forward_chord(0xDE, "'", 0x0008))
        self._entry.bind("<Control-backslash>", lambda _event: self._forward_chord(0xDC, "\\", 0x0008))
        self._entry.bind("<Alt-v>", self._on_alt_v)
        self.window.protocol("WM_DELETE_WINDOW", self.close_popout)
        self.window.after(50, self._paint_caption)
        self._schedule()

    def _schedule(self) -> None:
        self.poll()
        window = self.window
        if window is None:
            return
        try:
            delay = REMOTE_POLL_MS if self._remote_ip else 200
            self._after_id = window.after(delay, self._schedule)
        except Exception:
            self._after_id = None

    def _original_window_gone(self) -> bool:
        """True when the full original terminal window has been closed.

        Typing exit into the copy is input. It does not close this view.
        A minimized original window is still open.
        """
        if self._remote_ip:
            # That window id belongs to the other computer. Checking it here
            # closes the picture as soon as the first frame arrives.
            return False
        hwnd = int(self.console_hwnd or 0)
        if hwnd <= 0 or os.name != "nt" or self.window is None:
            return False
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.IsWindow.argtypes = (wintypes.HWND,)
        user32.IsWindow.restype = wintypes.BOOL
        return not bool(user32.IsWindow(hwnd))

    def poll(self) -> str:
        """Refresh the opened view from the latest picture of the Grok window."""
        if self._original_window_gone():
            self.close_popout()
            return ""
        self._start_mirror()
        with self._frame_lock:
            frame = self.frame_bytes
        if frame and not _ppm_is_blank(frame) and self._frame_changed(frame):
            self._show_frame(frame)
            return ""
        mirror = self._mirror
        if (
            not getattr(self, "_text_once", False)
            and mirror is not None
            and mirror.poll() is not None
            and self._mirror_attempts >= 5
            and self._original_pid
        ):
            self._text_once = True
            try:
                text = session_screen_text(self._original_pid)
            except OSError as exc:
                self._set_status(f"The session text could not be read: {exc}")
                return ""
            if text.strip():
                self._show_frame(_ppm_from_screen_text(text))
            return ""
        return ""

    def _frame_changed(self, frame: bytes) -> bool:
        """Ignore a blinking cursor. A real screen change still redraws."""
        previous = self._shown_frame()
        if frame.startswith(b"\x89PNG"):
            return previous != frame
        if not previous or len(previous) != len(frame):
            return True
        changed = seen = 0
        for index in range(0, len(frame) - 3, 180):
            seen += 1
            if frame[index:index + 3] != previous[index:index + 3]:
                changed += 1
        return seen == 0 or (changed / seen) > 0.02

    def _shown_frame(self) -> bytes:
        return getattr(self, "_shown", b"")

    def _show_frame(self, frame: bytes) -> None:
        import tkinter as tk

        window = self.window
        view = self._image
        if window is None or view is None:
            return
        try:
            suffix = ".png" if frame.startswith(b"\x89PNG") else ".ppm"
            if self._frame_path is None or self._frame_path.suffix != suffix:
                self._frame_path = Path(os.environ.get("TEMP", ".")) / f"silvia-session-{self.session_id}{suffix}"
            self._frame_path.write_bytes(frame)
            self._photo = tk.PhotoImage(file=str(self._frame_path))
            view.configure(image=self._photo)
            self._shown = frame
            size = (int(self._photo.width()), int(self._photo.height()))
            if getattr(self, "_fitted_size", None) != size:
                self._fit_copy_window()
                self._fitted_size = size
                self._placed = True
            self._sample_background(frame)
            self._set_status("")
        except Exception as exc:
            self._set_status(f"The session picture did not draw: {exc}")
            return

    def _fit_copy_window(self) -> None:
        window = self.window
        photo = self._photo
        if window is None or photo is None:
            return
        screen_w = max(int(window.winfo_screenwidth()) - 40, 640)
        screen_h = max(int(window.winfo_screenheight()) - 80, 480)
        width = min(max(int(photo.width()) + 16, 640), screen_w, 900)
        height = min(max(int(photo.height()) + 110, 480), screen_h)
        x = 16
        y = 40
        window.geometry(f"{width}x{height}+{x}+{y}")
        if not getattr(self, "_brought_forward", False):
            self._brought_forward = True
            self._raise_copy()

    def _raise_copy(self) -> None:
        window = self.window
        if window is None:
            return
        try:
            window.deiconify()
            window.lift()
            # A Toplevel stays behind its dashboard parent unless it is briefly topmost.
            window.attributes("-topmost", True)
            window.update_idletasks()
            window.attributes("-topmost", False)
            window.lift()
        except Exception:
            return

    def _drop_topmost(self) -> None:
        window = self.window
        if window is None:
            return
        try:
            window.attributes("-topmost", False)
        except Exception:
            return

    def original_unchanged(self) -> bool:
        return not self.relayed_lines and user_message_texts(self.updates) == self._user_baseline

    def submit_copy_input(self, text: str) -> list[str]:
        """Relay every submitted line, in order. Later lines are not dropped.

        Until this runs, the original log is not given those lines.
        A remote session is typed on the device that owns the console.
        """
        raw = str(text).replace("\r\n", "\n").replace("\r", "\n")
        if self._remote_ip:
            from remote_sessions import submit_remote

            sent = submit_remote(self._remote_ip, self.session_id, raw)
            self.relayed_lines.extend(sent)
            return sent
        sent: list[str] = []
        for line in raw.split("\n"):
            body = line.strip()
            if body == "":
                continue
            write_console_input(self._original_pid, body)
            self.relayed_lines.append(body)
            sent.append(body)
        return sent

    def _paint_caption(self) -> None:
        window = self.window
        if window is None or os.name != "nt":
            return
        try:
            window.update_idletasks()
            hwnd = int(window.winfo_id())
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            root = int(user32.GetAncestor(hwnd, 2) or hwnd)
            red, green, blue = self._chrome
            color = ctypes.c_uint(red | (green << 8) | (blue << 16))
            text = ctypes.c_uint(0x00E8E8E8)
            dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
            dwm.DwmSetWindowAttribute(root, 35, ctypes.byref(color), 4)
            dwm.DwmSetWindowAttribute(root, 36, ctypes.byref(text), 4)
            dwm.DwmSetWindowAttribute(root, 34, ctypes.byref(color), 4)
        except Exception:
            return

    def _apply_chrome(self, red: int, green: int, blue: int) -> None:
        self._chrome = (red, green, blue)
        color = f"#{red:02x}{green:02x}{blue:02x}"
        window = self.window
        if window is not None:
            try:
                window.configure(background=color)
            except Exception:
                pass
        if self._image is not None:
            try:
                self._image.configure(background=color)
            except Exception:
                pass
        entry = self._entry
        if entry is not None:
            try:
                entry.configure(background=color)
            except Exception:
                pass
        self._paint_caption()

    def _sample_background(self, frame: bytes) -> None:
        if getattr(self, "_chrome_sampled", False) or not frame.startswith(b"P6\n"):
            return
        try:
            header, _, body = frame.partition(b"\n255\n")
            width, height = (int(part) for part in header.split()[1:3])
        except (ValueError, IndexError):
            return
        if width < 2 or height < 2 or len(body) < width * height * 3:
            return
        counts: dict[tuple[int, int, int], int] = {}
        step = max(1, (width * height) // 4000)
        for index in range(0, width * height, step):
            offset = index * 3
            pixel = (body[offset], body[offset + 1], body[offset + 2])
            if pixel[0] < 48 and pixel[1] < 48 and pixel[2] < 48:
                counts[pixel] = counts.get(pixel, 0) + 1
        if not counts:
            return
        red, green, blue = max(counts, key=counts.get)
        self._chrome_sampled = True
        self._apply_chrome(red, green, blue)

    def _show_placeholder(self) -> None:
        entry = self._entry
        if entry is None:
            return
        self._placeholder_on = True
        entry.configure(foreground=self._placeholder_fg)
        entry.delete("1.0", "end")
        entry.insert("1.0", "Enter remotely here.")

    def _clear_placeholder(self) -> None:
        entry = self._entry
        if entry is None or not self._placeholder_on:
            return
        self._placeholder_on = False
        entry.configure(foreground=self._text_fg)
        entry.delete("1.0", "end")

    def _draft(self) -> str:
        if self._placeholder_on or self._entry is None:
            return ""
        return self._entry.get("1.0", "end-1c")

    def _set_draft(self, text: str) -> None:
        entry = self._entry
        if entry is None:
            return
        if text == "":
            self._show_placeholder()
            return
        self._placeholder_on = False
        entry.configure(foreground=self._text_fg)
        entry.delete("1.0", "end")
        entry.insert("1.0", text)
        entry.mark_set("insert", "end")

    def _before_type(self, event: Any) -> str | None:
        if not self._placeholder_on:
            return None
        if event.keysym in {"BackSpace", "Delete", "Return", "Escape", "Tab", "Up", "Down"}:
            return None
        if event.char and event.char.isprintable():
            self._clear_placeholder()
            self._history_at = None
            self._restore_armed = False
        return None

    def _after_type(self, _event: Any) -> None:
        if self._placeholder_on or self._entry is None:
            return
        if self._entry.get("1.0", "end-1c") == "":
            self._show_placeholder()

    def _insert_line(self, _event: Any = None) -> str:
        self._clear_placeholder()
        entry = self._entry
        if entry is not None:
            entry.insert("insert", "\n")
        return "break"

    def _on_shift_return(self, _event: Any = None) -> str:
        if self._multiline:
            return self._queue_draft()
        return self._insert_line()

    def _on_return(self, _event: Any = None) -> str:
        if self._multiline and self._draft() != "":
            return self._insert_line()
        return self._queue_draft()

    def _on_submit(self, _event: Any = None) -> str:
        return self._queue_draft()

    def _queue_draft(self, _event: Any = None) -> str:
        body = self._draft()
        if body.strip() == "":
            self._send_queued_now()
            return "break"
        try:
            self.submit_copy_input(body)
        except OSError as exc:
            self._set_status(f"The copy could not send that line: {exc}")
            return "break"
        self._set_status("")
        self._history.append(body)
        self._history_at = None
        self._queued = True
        if self._stash_on_send and self._stash:
            restore = self._stash
            self._stash = ""
            self._stash_on_send = False
            self._set_draft(restore)
        else:
            self._show_placeholder()
        return "break"

    def _send_queued_now(self) -> None:
        if self._remote_ip:
            try:
                from remote_sessions import press_remote_key

                press_remote_key(self._remote_ip, self.session_id, "enter")
            except OSError as exc:
                self._set_status(f"The copy could not send that line: {exc}")
                return
            self._queued = False
            return
        if not self._original_pid:
            self._queued = False
            return
        try:
            write_console_chord(self._original_pid, 0x0D, "\r", 0)
        except OSError:
            return
        self._queued = False

    def _on_send_now(self, _event: Any = None) -> str:
        body = self._draft()
        if self._remote_ip:
            try:
                from remote_sessions import press_remote_key, send_remote_plain

                if body.strip() == "":
                    if self._queued:
                        press_remote_key(self._remote_ip, self.session_id, "ctrl-i")
                        self._queued = False
                    return "break"
                send_remote_plain(self._remote_ip, self.session_id, body)
                press_remote_key(self._remote_ip, self.session_id, "ctrl-i")
            except OSError as exc:
                self._set_status(f"The copy could not send that line: {exc}")
                return "break"
            self.relayed_lines.append(body)
            self._history.append(body)
            self._history_at = None
            self._show_placeholder()
            return "break"
        if body.strip() == "":
            if not self._queued or not self._original_pid:
                return "break"
            try:
                write_console_chord(self._original_pid, 0x49, "\t", 0x0008)
            except OSError:
                return "break"
            self._queued = False
            return "break"
        if not self._original_pid:
            return "break"
        try:
            write_console_plain(self._original_pid, body)
            write_console_chord(self._original_pid, 0x49, "\t", 0x0008)
        except OSError:
            return "break"
        self.relayed_lines.append(body)
        self._history.append(body)
        self._history_at = None
        self._show_placeholder()
        return "break"

    def _on_ctrl_c(self, _event: Any = None) -> str:
        body = self._draft()
        if body != "":
            self._undo_draft = body
            self._restore_armed = True
            self._show_placeholder()
            return "break"
        self._forward_chord(0x43, "\x03", 0x0008)
        return "break"

    def _on_escape(self, _event: Any = None) -> str:
        now = time.monotonic()
        second = (now - self._last_esc) <= 0.8
        self._last_esc = 0.0 if second else now
        if not second:
            return "break"
        body = self._draft()
        if body != "":
            self._stash = body
            self._stash_on_send = False
            self._restore_armed = True
            self._show_placeholder()
            return "break"
        self._forward_chord(0x1B, "\x1b", 0)
        self._forward_chord(0x1B, "\x1b", 0)
        return "break"

    def _on_stash(self, _event: Any = None) -> str:
        body = self._draft()
        if body != "":
            self._stash = body
            self._stash_on_send = True
            self._restore_armed = True
            self._show_placeholder()
            return "break"
        if self._stash:
            self._set_draft(self._stash)
            self._stash = ""
            self._stash_on_send = False
        return "break"

    def _on_undo(self, _event: Any = None) -> str:
        if self._restore_armed and getattr(self, "_undo_draft", ""):
            self._set_draft(self._undo_draft)
            self._undo_draft = ""
            self._restore_armed = False
            return "break"
        if self._restore_armed and self._stash:
            self._set_draft(self._stash)
            self._restore_armed = False
            return "break"
        entry = self._entry
        if entry is not None:
            try:
                entry.edit_undo()
            except Exception:
                return "break"
        return "break"

    def _on_multiline(self, _event: Any = None) -> str:
        self._multiline = not self._multiline
        return "break"

    def _on_history_up(self, _event: Any = None) -> str | None:
        if self._draft() or not self._history:
            return None
        if self._history_at is None:
            self._history_at = len(self._history) - 1
        else:
            self._history_at = max(0, self._history_at - 1)
        self._set_draft(self._history[self._history_at])
        return "break"

    def _on_history_down(self, _event: Any = None) -> str | None:
        if self._history_at is None:
            return None
        self._history_at += 1
        if self._history_at >= len(self._history):
            self._history_at = None
            self._show_placeholder()
            return "break"
        self._set_draft(self._history[self._history_at])
        return "break"

    def _forward_chord(self, virtual_key: int, character: str, control: int) -> str:
        if self._remote_ip:
            from remote_sessions import press_remote_key, remote_key_name

            name = remote_key_name(virtual_key, control)
            if not name:
                return "break"
            try:
                press_remote_key(self._remote_ip, self.session_id, name)
            except OSError as exc:
                self._set_status(f"The copy could not send that line: {exc}")
            return "break"
        if self._original_pid:
            try:
                write_console_chord(self._original_pid, virtual_key, character, control)
            except OSError:
                return "break"
        return "break"

    def _on_alt_v(self, _event: Any = None) -> str:
        entry = self._entry
        if entry is None:
            return "break"
        try:
            pasted = entry.clipboard_get()
        except Exception:
            pasted = ""
        if pasted:
            self._clear_placeholder()
            entry.insert("insert", pasted)
        return "break"

    def popout_text(self) -> str:
        return self.visible_screen

    def alive(self) -> bool:
        window = self.window
        if window is None:
            return False
        try:
            return bool(window.winfo_exists())
        except Exception:
            return False

    def lift(self) -> None:
        window = self.window
        if window is None:
            return
        try:
            window.deiconify()
            window.lift()
        except Exception:
            return

    def _status_later(self, message: str) -> None:
        def show() -> None:
            if not self._closed:
                self._set_status(message)

        window = self.window
        if window is None:
            return
        try:
            window.after(0, show)
        except Exception:
            return

    def close_popout(self) -> None:
        if self._remote_ip and not self._closed:
            from dashboard_debug import note

            note("picture-closed", self.session_id)
        self._closed = True
        unregister_opened_view(self.session_id)
        reader = getattr(self, "_remote_reader", None)
        self._remote_reader = None
        if reader is not None:
            try:
                reader.close()
            except Exception:
                pass
        mirror = self._mirror
        self._mirror = None
        if mirror is not None:
            try:
                mirror.kill()
            except Exception:
                pass
        log = self._mirror_log
        self._mirror_log = None
        if log is not None:
            try:
                log.close()
            except Exception:
                pass
        window = self.window
        self.window = None
        self._text = None
        self._image = None
        self._entry = None
        if window is None:
            return
        after_id = self._after_id
        self._after_id = None
        if after_id:
            try:
                window.after_cancel(after_id)
            except Exception:
                pass
        try:
            window.destroy()
        except Exception:
            return
