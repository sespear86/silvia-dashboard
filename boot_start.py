"""One logon entry for the Silvia dashboard. It starts hidden in the tray."""
from __future__ import annotations

import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "SilviaDashboard"


def _pythonw() -> Path:
    exe = Path(sys.executable)
    if exe.name.lower() in {"python.exe", "pythonw.exe"}:
        sibling = exe.with_name("pythonw.exe")
        if sibling.is_file():
            return sibling
    return exe


def launch_command() -> str:
    """pythonw, no console, hidden in the tray until the icon is opened."""
    script = Path(__file__).resolve().parent / "__main__.py"
    return f'"{_pythonw()}" "{script}" launch'


def enabled() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, RUN_VALUE)
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return bool(str(value).strip())


def set_enabled(on: bool) -> None:
    if sys.platform != "win32":
        raise OSError("Start at boot is implemented for Windows")
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if on:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, launch_command())
            return
        try:
            winreg.DeleteValue(key, RUN_VALUE)
        except FileNotFoundError:
            return
