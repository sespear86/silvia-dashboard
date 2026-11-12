"""Elevated relay for Grok console input.

The dashboard runs at medium integrity. An elevated Grok console refuses
AttachConsole from that process, and the copy's Enter then never submits.
This process runs elevated, checks that the target is a Grok session, and
writes the keys. A medium caller reaches it through a medium-integrity pipe.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

PIPE_NAME = r"\\.\pipe\SilviaGrokConsoleRelay"
MUTEX_NAME = "Local\\SilviaGrokConsoleRelay"
TASK_NAME = "SilviaGrokConsoleRelay"
_MAX_TEXT = 200_000

_kernel = ctypes.WinDLL("kernel32", use_last_error=True)
_advapi = ctypes.WinDLL("advapi32", use_last_error=True)


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


def _ready_path() -> Path:
    return Path(os.environ.get("TEMP", ".")) / "silvia-console-broker.ready"


def _log_path() -> Path:
    return Path(os.environ.get("TEMP", ".")) / "silvia-console-broker.log"


def _log(line: str) -> None:
    try:
        with _log_path().open("a", encoding="utf-8") as handle:
            handle.write(line.rstrip() + "\n")
    except OSError:
        return


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    _kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel.OpenProcess.restype = wintypes.HANDLE
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL
    handle = _kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return False
    _kernel.CloseHandle(handle)
    return True


def broker_pid() -> int:
    try:
        return int(_ready_path().read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        return 0


def _user_sid() -> str:
    _advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    _advapi.OpenProcessToken.restype = wintypes.BOOL
    _advapi.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _advapi.GetTokenInformation.restype = wintypes.BOOL
    _advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    _advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    _kernel.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    if not _advapi.OpenProcessToken(_kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise OSError(ctypes.get_last_error() or 1)
    try:
        needed = wintypes.DWORD(0)
        _advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
        raw = ctypes.create_string_buffer(max(int(needed.value), ctypes.sizeof(_SidAndAttributes)))
        if not _advapi.GetTokenInformation(token, 1, raw, len(raw), ctypes.byref(needed)):
            raise OSError(ctypes.get_last_error() or 1)
        info = _SidAndAttributes.from_buffer(raw)
        text = ctypes.c_wchar_p()
        if not _advapi.ConvertSidToStringSidW(info.Sid, ctypes.byref(text)) or not text.value:
            raise OSError(ctypes.get_last_error() or 1)
        return str(text.value)
    finally:
        _kernel.CloseHandle(token)


def _pipe_security() -> _SecurityAttributes:
    sid = _user_sid()
    sddl = f"D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;{sid})S:(ML;;NW;;;ME)"
    _advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.ULONG),
    ]
    _advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    descriptor = ctypes.c_void_p()
    if not _advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
        raise OSError(ctypes.get_last_error() or 1)
    attributes = _SecurityAttributes()
    attributes.nLength = ctypes.sizeof(attributes)
    attributes.lpSecurityDescriptor = descriptor
    attributes.bInheritHandle = 0
    return attributes


def target_allowed(pid: int) -> bool:
    """True for a Grok session console, or the hidden relay probe."""
    from sessions_live import _process_rows, process_command_line

    number = int(pid)
    name = ""
    for row_pid, _parent, exe in _process_rows():
        if int(row_pid) == number:
            name = str(exe).lower()
            break
    if name == "grok.exe":
        return True
    command = process_command_line(number).lower()
    if name in {"powershell.exe", "powershell-host.exe"} and "launch-grok-build-tui.ps1" in command:
        return True
    tokens = command.split()
    if name in {"python.exe", "pythonw.exe"} and "--silvia-relay-probe" in tokens:
        return True
    return False


def _dispatch(payload: dict) -> dict:
    op = str(payload.get("op") or "")
    pid = int(payload.get("pid") or 0)
    if pid <= 0:
        return {"ok": False, "error": "the original session has no process"}
    if not target_allowed(pid):
        _log(f"refused pid {pid}")
        return {"ok": False, "error": "that process is not a Grok session"}
    os.environ["SILVIA_CONSOLE_BROKER"] = "1"
    os.environ["SILVIA_CONSOLE_RELAY"] = "1"
    if op == "input":
        text = str(payload.get("text") or "")
        if len(text) > _MAX_TEXT:
            return {"ok": False, "error": "that line is too long to send"}
        from sessions_live import write_console_input

        write_console_input(pid, text)
        _log(f"relayed input pid {pid} chars {len(text)}")
        return {"ok": True}
    if op == "records":
        raw = payload.get("keys") or []
        if not isinstance(raw, list) or len(raw) > _MAX_TEXT:
            return {"ok": False, "error": "those keys cannot be sent"}
        keys: list[tuple[int, str, int]] = []
        for item in raw:
            if not isinstance(item, list) or len(item) != 3:
                return {"ok": False, "error": "those keys cannot be sent"}
            character = str(item[1])
            if len(character) != 1:
                return {"ok": False, "error": "those keys cannot be sent"}
            keys.append((int(item[0]), character, int(item[2])))
        from sessions_live import _write_console_records

        _write_console_records(pid, keys)
        _log(f"relayed records pid {pid} keys {len(keys)}")
        return {"ok": True}
    if op == "screen":
        from sessions_live import _console_action

        text = _console_action("screen", pid).decode("utf-8", "replace")
        _log(f"read screen pid {pid} chars {len(text)}")
        return {"ok": True, "text": text}
    return {"ok": False, "error": "the console relay does not know that request"}


def _create_pipe(security: _SecurityAttributes) -> int:
    _kernel.CreateNamedPipeW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_SecurityAttributes),
    ]
    _kernel.CreateNamedPipeW.restype = wintypes.HANDLE
    # PIPE_ACCESS_DUPLEX, message mode, blocking.
    handle = _kernel.CreateNamedPipeW(
        PIPE_NAME,
        0x00000003,
        0x00000004 | 0x00000002,
        4,
        1 << 20,
        1 << 20,
        0,
        ctypes.byref(security),
    )
    value = int(ctypes.cast(handle, ctypes.c_void_p).value or 0)
    if value in (0, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
        raise OSError(ctypes.get_last_error() or 1)
    return value


def _read_message(handle: int) -> bytes:
    _kernel.ReadFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    _kernel.ReadFile.restype = wintypes.BOOL
    buffer = ctypes.create_string_buffer(1 << 20)
    read = wintypes.DWORD()
    ok = _kernel.ReadFile(handle, buffer, len(buffer), ctypes.byref(read), None)
    if not ok:
        raise OSError(ctypes.get_last_error() or 1)
    return buffer.raw[: int(read.value)]


def _write_message(handle: int, payload: bytes) -> None:
    _kernel.WriteFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    _kernel.WriteFile.restype = wintypes.BOOL
    written = wintypes.DWORD()
    raw = ctypes.create_string_buffer(payload)
    ok = _kernel.WriteFile(handle, raw, len(payload), ctypes.byref(written), None)
    if not ok or int(written.value) != len(payload):
        raise OSError(ctypes.get_last_error() or 1)


def _handle_client(handle: int) -> None:
    try:
        raw = _read_message(handle)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            result = {"ok": False, "error": "the console relay got a bad request"}
        else:
            result = _dispatch(payload)
    except Exception as exc:
        result = {"ok": False, "error": str(exc) or "the console relay failed"}
    try:
        _write_message(handle, json.dumps(result).encode("utf-8"))
    except OSError:
        return


def serve() -> None:
    """Listen until the process is stopped. A second copy exits."""
    _kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel.CreateMutexW.restype = wintypes.HANDLE
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL
    mutex = _kernel.CreateMutexW(None, True, MUTEX_NAME)
    if ctypes.get_last_error() == 183:
        if mutex:
            _kernel.CloseHandle(mutex)
        _log("already running")
        return
    os.environ["SILVIA_CONSOLE_BROKER"] = "1"
    os.environ["SILVIA_CONSOLE_RELAY"] = "1"
    security = _pipe_security()
    _kernel.ConnectNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    _kernel.ConnectNamedPipe.restype = wintypes.BOOL
    _kernel.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
    _kernel.DisconnectNamedPipe.restype = wintypes.BOOL
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL
    _ready_path().write_text(str(os.getpid()), encoding="utf-8")
    _log(f"listening pid {os.getpid()}")
    try:
        while True:
            handle = _create_pipe(security)
            connected = bool(_kernel.ConnectNamedPipe(handle, None))
            if not connected and ctypes.get_last_error() != 535:
                _kernel.CloseHandle(handle)
                _log(f"connect failed {ctypes.get_last_error()}")
                continue
            try:
                _handle_client(handle)
            finally:
                _kernel.DisconnectNamedPipe(handle)
                _kernel.CloseHandle(handle)
    finally:
        try:
            if broker_pid() == os.getpid():
                _ready_path().unlink(missing_ok=True)
        except OSError:
            pass


def _start_broker() -> None:
    flags = 0x08000000 if os.name == "nt" else 0
    subprocess.run(
        ["schtasks", "/Run", "/TN", TASK_NAME],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
        creationflags=flags,
    )


def ensure_started() -> None:
    """Start the elevated broker when the ready pid is gone."""
    if _pid_alive(broker_pid()):
        return
    try:
        _ready_path().unlink(missing_ok=True)
    except OSError:
        pass
    _start_broker()


def _transact(payload: dict) -> None:
    _kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _kernel.CreateFileW.restype = wintypes.HANDLE
    _kernel.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    _kernel.WaitNamedPipeW.restype = wintypes.BOOL
    _kernel.SetNamedPipeHandleState.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    _kernel.SetNamedPipeHandleState.restype = wintypes.BOOL
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL
    deadline = __import__("time").monotonic() + 8
    started = False
    last = "the elevated console relay is not running"
    while __import__("time").monotonic() < deadline:
        handle = _kernel.CreateFileW(PIPE_NAME, 0xC0000000, 0, None, 3, 0, None)
        value = int(ctypes.cast(handle, ctypes.c_void_p).value or 0)
        if value not in (0, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
            try:
                mode = wintypes.DWORD(2)
                _kernel.SetNamedPipeHandleState(handle, ctypes.byref(mode), None, None)
                _write_message(handle, json.dumps(payload).encode("utf-8"))
                raw = _read_message(handle)
            finally:
                _kernel.CloseHandle(handle)
            try:
                result = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise OSError("the console relay sent a bad reply") from exc
            if not result.get("ok"):
                raise OSError(str(result.get("error") or "the console relay failed"))
            return result
        last = str(ctypes.get_last_error() or last)
        if not started:
            started = True
            try:
                ensure_started()
            except (OSError, subprocess.TimeoutExpired):
                pass
        _kernel.WaitNamedPipeW(PIPE_NAME, 400)
    raise OSError(last)


def relay_input(pid: int, text: str) -> None:
    _transact({"op": "input", "pid": int(pid), "text": str(text)})


def relay_screen(pid: int) -> str:
    """Read the visible console text through the elevated broker."""
    result = _transact({"op": "screen", "pid": int(pid)})
    return str((result or {}).get("text") or "")


def relay_records(pid: int, keys: list[tuple[int, str, int]]) -> None:
    _transact(
        {
            "op": "records",
            "pid": int(pid),
            "keys": [[int(virtual), str(character), int(control)] for virtual, character, control in keys],
        }
    )


if __name__ == "__main__":
    try:
        serve()
    except Exception:
        import traceback

        _log(traceback.format_exc())
        raise
