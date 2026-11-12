"""Notification-area icon for the Silvia dashboard.

The icon sits in the bottom-right tray. Left click or Open shows the window.
Start at boot is the same logon switch as the button in the window. Exit quits.
"""
from __future__ import annotations

import ctypes
import queue
import threading
from ctypes import wintypes
from pathlib import Path

WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_LBUTTONDBLCLK = 0x0203
WM_NULL = 0x0000
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_APP = 0x8000
CALLBACK_MESSAGE = WM_APP + 1
NIM_ADD = 0x00000000
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
MF_STRING = 0x00000000
MF_CHECKED = 0x00000008
TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002
WS_POPUP = 0x80000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
MUTEX_NAME = "Local\\SilviaDashboard"
SHOW_EVENT_NAME = "Local\\SilviaDashboardShow"
CLASS_NAME = "SilviaDashboardTray"

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel = ctypes.WinDLL("kernel32", use_last_error=True)
_instances: dict[int, "TrayIcon"] = {}
_class_ready = False


class _WndClass(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class _NotifyIconData(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
    ]


class _Point(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _Msg(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", _Point),
    ]


_LRESULT = ctypes.c_ssize_t
_WNDPROC = ctypes.WINFUNCTYPE(_LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


def _configure() -> None:
    _user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.DefWindowProcW.restype = _LRESULT
    _user32.RegisterClassW.argtypes = [ctypes.POINTER(_WndClass)]
    _user32.RegisterClassW.restype = wintypes.ATOM
    _user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        ctypes.c_void_p,
    ]
    _user32.CreateWindowExW.restype = wintypes.HWND
    _user32.DestroyWindow.argtypes = [wintypes.HWND]
    _user32.DestroyWindow.restype = wintypes.BOOL
    _user32.GetMessageW.argtypes = [ctypes.POINTER(_Msg), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    _user32.GetMessageW.restype = ctypes.c_int
    _user32.TranslateMessage.argtypes = [ctypes.POINTER(_Msg)]
    _user32.TranslateMessage.restype = wintypes.BOOL
    _user32.DispatchMessageW.argtypes = [ctypes.POINTER(_Msg)]
    _user32.DispatchMessageW.restype = _LRESULT
    _user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.PostMessageW.restype = wintypes.BOOL
    _user32.PostQuitMessage.argtypes = [ctypes.c_int]
    _user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE,
        wintypes.LPCWSTR,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    _user32.LoadImageW.restype = wintypes.HANDLE
    _user32.DestroyIcon.argtypes = [wintypes.HICON]
    _user32.DestroyIcon.restype = wintypes.BOOL
    _user32.Shell_NotifyIconW = ctypes.WinDLL("shell32", use_last_error=True).Shell_NotifyIconW
    _user32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(_NotifyIconData)]
    _user32.Shell_NotifyIconW.restype = wintypes.BOOL
    _user32.CreatePopupMenu.argtypes = []
    _user32.CreatePopupMenu.restype = wintypes.HMENU
    _user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_uint, wintypes.LPCWSTR]
    _user32.AppendMenuW.restype = wintypes.BOOL
    _user32.TrackPopupMenu.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        ctypes.c_void_p,
    ]
    _user32.TrackPopupMenu.restype = wintypes.BOOL
    _user32.DestroyMenu.argtypes = [wintypes.HMENU]
    _user32.DestroyMenu.restype = wintypes.BOOL
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.restype = wintypes.BOOL
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(_Point)]
    _user32.GetCursorPos.restype = wintypes.BOOL
    _kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    _kernel.GetModuleHandleW.restype = wintypes.HINSTANCE


def _proc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
    icon = _instances.get(int(hwnd))
    if icon is not None and int(msg) == CALLBACK_MESSAGE:
        icon.handle_mouse(int(lparam))
        return 0
    if int(msg) == WM_DESTROY:
        _user32.PostQuitMessage(0)
        return 0
    return int(_user32.DefWindowProcW(hwnd, msg, wparam, lparam))


_PROC_REF = _WNDPROC(_proc)


def _ensure_class() -> None:
    global _class_ready
    if _class_ready:
        return
    _configure()
    window_class = _WndClass()
    window_class.lpfnWndProc = ctypes.cast(_PROC_REF, ctypes.c_void_p)
    window_class.hInstance = _kernel.GetModuleHandleW(None)
    window_class.lpszClassName = CLASS_NAME
    if not _user32.RegisterClassW(ctypes.byref(window_class)):
        err = ctypes.get_last_error()
        if err not in (1410,):  # class already exists
            raise OSError(err or 1)
    _class_ready = True


def icon_path() -> Path:
    return Path(__file__).resolve().parent / "silvia.ico"


def draw_phone_icon(size: int):
    """The phone launcher: purple field, light ring, purple center. Viewport 108."""
    from PIL import Image, ImageDraw

    purple = (0x5B, 0x3A, 0x82, 255)
    ring = (0xF4, 0xE8, 0xFF, 255)
    image = Image.new("RGBA", (size, size), purple)
    draw = ImageDraw.Draw(image)
    center = size / 2
    outer = 30 / 108 * size
    inner = 18 / 108 * size
    draw.ellipse((center - outer, center - outer, center + outer, center + outer), fill=ring)
    draw.ellipse((center - inner, center - inner, center + inner, center + inner), fill=purple)
    return image


def ensure_icon() -> Path:
    path = icon_path()
    if path.is_file() and path.stat().st_size > 0:
        return path
    image = draw_phone_icon(256)
    image.save(path, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])
    return path


def claim_or_signal() -> bool:
    """Own the dashboard mutex, or ask the running one to open and return False."""
    _kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel.CreateMutexW.restype = wintypes.HANDLE
    _kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel.OpenEventW.restype = wintypes.HANDLE
    _kernel.SetEvent.argtypes = [wintypes.HANDLE]
    _kernel.SetEvent.restype = wintypes.BOOL
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL
    mutex = _kernel.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        if mutex:
            _kernel.CloseHandle(mutex)
        deadline = __import__("time").monotonic() + 2
        while __import__("time").monotonic() < deadline:
            event = _kernel.OpenEventW(EVENT_MODIFY_STATE, False, SHOW_EVENT_NAME)
            if event:
                _kernel.SetEvent(event)
                _kernel.CloseHandle(event)
                return False
            __import__("time").sleep(0.05)
        return False
    global _OWNER_MUTEX
    _OWNER_MUTEX = mutex
    return True


_OWNER_MUTEX = None


class TrayIcon:
    """One tray icon. Callbacks run on the tray thread."""

    def __init__(self, on_open, on_exit, on_toggle_boot) -> None:
        self.on_open = on_open
        self.on_exit = on_exit
        self.on_toggle_boot = on_toggle_boot
        self.hwnd = 0
        self._icon = 0
        self._ready = threading.Event()
        self._error: Exception | None = None
        self._thread = threading.Thread(target=self._run, name="silvia-tray", daemon=True)
        self._show_event = 0
        self._stop = False

    def start(self) -> None:
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise OSError("the tray icon did not start")
        if self._error is not None:
            raise self._error

    def close(self) -> None:
        hwnd = int(self.hwnd or 0)
        if hwnd:
            _user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        if self._thread.is_alive():
            self._thread.join(timeout=3)

    def handle_mouse(self, mouse: int) -> None:
        if mouse in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
            self.on_open()
            return
        if mouse == WM_RBUTTONUP:
            command = self._popup()
            self.handle_command(command)

    def handle_command(self, command: int) -> None:
        if command == 1:
            self.on_open()
        elif command == 2:
            self.on_toggle_boot()
        elif command == 3:
            self.on_exit()

    def _popup(self) -> int:
        from boot_start import enabled

        menu = _user32.CreatePopupMenu()
        if not menu:
            return 0
        try:
            _user32.AppendMenuW(menu, MF_STRING, 1, "Open")
            flag = MF_STRING | (MF_CHECKED if enabled() else 0)
            _user32.AppendMenuW(menu, flag, 2, "Start at boot")
            _user32.AppendMenuW(menu, MF_STRING, 3, "Exit")
            _user32.SetForegroundWindow(self.hwnd)
            point = _Point()
            _user32.GetCursorPos(ctypes.byref(point))
            command = int(
                _user32.TrackPopupMenu(
                    menu,
                    TPM_RETURNCMD | TPM_RIGHTBUTTON,
                    int(point.x),
                    int(point.y),
                    0,
                    self.hwnd,
                    None,
                )
                or 0
            )
            _user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
            return command
        finally:
            _user32.DestroyMenu(menu)

    def _run(self) -> None:
        try:
            _ensure_class()
            _kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
            _kernel.CreateEventW.restype = wintypes.HANDLE
            _kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            _kernel.WaitForSingleObject.restype = wintypes.DWORD
            self._show_event = _kernel.CreateEventW(None, False, False, SHOW_EVENT_NAME)
            hwnd = _user32.CreateWindowExW(
                WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                CLASS_NAME,
                CLASS_NAME,
                WS_POPUP,
                0,
                0,
                0,
                0,
                None,
                None,
                _kernel.GetModuleHandleW(None),
                None,
            )
            if not hwnd:
                raise OSError(ctypes.get_last_error() or 1)
            self.hwnd = hwnd
            _instances[int(hwnd)] = self
            self._icon = _user32.LoadImageW(None, str(ensure_icon()), IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
            if not self._icon:
                raise OSError(ctypes.get_last_error() or 1)
            data = _NotifyIconData()
            data.cbSize = ctypes.sizeof(data)
            data.hWnd = hwnd
            data.uID = 1
            data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            data.uCallbackMessage = CALLBACK_MESSAGE
            data.hIcon = self._icon
            data.szTip = "Silvia Dashboard"
            if not _user32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)):
                raise OSError(ctypes.get_last_error() or 1)
            self._ready.set()
            waiter = threading.Thread(target=self._wait_show, name="silvia-tray-show", daemon=True)
            waiter.start()
            message = _Msg()
            while True:
                result = int(_user32.GetMessageW(ctypes.byref(message), None, 0, 0))
                if result <= 0:
                    break
                if int(message.message) == WM_CLOSE:
                    break
                _user32.TranslateMessage(ctypes.byref(message))
                _user32.DispatchMessageW(ctypes.byref(message))
        except Exception as exc:
            self._error = exc
            self._ready.set()
        finally:
            self._remove()

    def _wait_show(self) -> None:
        event = self._show_event
        if not event:
            return
        while not self._stop:
            result = int(_kernel.WaitForSingleObject(event, 400))
            if result == 0 and self.on_open is not None and not self._stop:
                self.on_open()

    def _remove(self) -> None:
        self._stop = True
        hwnd = int(self.hwnd or 0)
        if hwnd:
            data = _NotifyIconData()
            data.cbSize = ctypes.sizeof(data)
            data.hWnd = hwnd
            data.uID = 1
            _user32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))
            _instances.pop(hwnd, None)
            _user32.DestroyWindow(hwnd)
            self.hwnd = 0
        if self._icon:
            _user32.DestroyIcon(self._icon)
            self._icon = 0
        handle = self._show_event
        self._show_event = 0
        self._stop = True
        if handle:
            _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            _kernel.CloseHandle.restype = wintypes.BOOL
            _kernel.CloseHandle(handle)


class TrayBridge:
    """Marshal tray clicks onto the Tk thread."""

    def __init__(self, schedule) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._schedule = schedule
        self.icon: TrayIcon | None = None

    def start(self, on_open, on_exit, on_toggle_boot) -> None:
        def wrap(fn):
            def queued() -> None:
                self._queue.put(fn)
                self._schedule(0, self.drain)

            return queued

        self.icon = TrayIcon(wrap(on_open), wrap(on_exit), wrap(on_toggle_boot))
        self.icon.start()

    def drain(self) -> None:
        try:
            while True:
                self._queue.get_nowait()()
        except queue.Empty:
            return

    def close(self) -> None:
        icon = self.icon
        self.icon = None
        if icon is not None:
            icon.close()
