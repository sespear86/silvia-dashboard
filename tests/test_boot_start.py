"""Start at boot is one Run value. The tray icon opens the dashboard."""
from __future__ import annotations

import time

from boot_start import enabled, launch_command, set_enabled


def test_phone_icon_is_the_purple_ring():
    from tray_icon import draw_phone_icon

    image = draw_phone_icon(108)
    assert image.getpixel((0, 0)) == (0x5B, 0x3A, 0x82, 255)
    assert image.getpixel((54, 54)) == (0x5B, 0x3A, 0x82, 255)
    assert image.getpixel((54, 30)) == (0xF4, 0xE8, 0xFF, 255)


def test_launch_command_is_hidden_pythonw():
    command = launch_command()
    assert "pythonw.exe" in command.lower()
    assert "__main__.py" in command
    assert command.endswith("launch --tray")


def test_start_at_boot_toggle_writes_one_run_value():
    try:
        set_enabled(False)
        assert enabled() is False
        set_enabled(True)
        assert enabled() is True
        assert "launch --tray" in launch_command()
    finally:
        set_enabled(True)


def test_tray_left_click_opens_and_menu_toggles_boot():
    import ctypes
    from ctypes import wintypes

    from tray_icon import CALLBACK_MESSAGE, WM_LBUTTONUP, TrayIcon

    opened: list[str] = []
    toggled: list[str] = []
    icon = TrayIcon(
        lambda: opened.append("open"),
        lambda: opened.append("exit"),
        lambda: toggled.append("boot"),
    )
    icon.start()
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    try:
        assert icon.hwnd
        assert user32.PostMessageW(icon.hwnd, CALLBACK_MESSAGE, 1, WM_LBUTTONUP)
        deadline = time.time() + 3
        while time.time() < deadline and not opened:
            time.sleep(0.05)
        assert opened == ["open"]
        icon.handle_command(2)
        assert toggled == ["boot"]
        icon.handle_command(1)
        assert opened == ["open", "open"]
    finally:
        icon.close()


def test_dashboard_button_toggles_start_at_boot():
    from app import SilviaDashboard
    from world import build_world

    world = build_world(
        {"resources": [{"id": "cli.example", "name": "Example", "category": "CLIs"}], "capabilities": [], "probes": {}, "usage": {}}
    )
    app = SilviaDashboard(world)
    try:
        app.update_idletasks()
        set_enabled(False)
        app.boot_btn.configure(text=app._boot_label())
        assert app.boot_btn.cget("text") == "Start at boot: Off"
        app.boot_btn.invoke()
        assert enabled() is True
        assert app.boot_btn.cget("text") == "Start at boot: On"
        app.boot_btn.invoke()
        assert enabled() is False
        assert app.boot_btn.cget("text") == "Start at boot: Off"
    finally:
        set_enabled(True)
        app.destroy()
