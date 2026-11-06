"""Everything that talks to Windows: screenshots, mouse and keyboard control, the front window.
Uses only the standard library (ctypes) and pynput, so no extra install is needed on Windows."""
import ctypes
import ntpath
import time
from ctypes import wintypes

from PIL import ImageGrab
from pynput import keyboard, mouse

_mouse, _keys = mouse.Controller(), keyboard.Controller()
_BUTTONS = {"left": mouse.Button.left, "right": mouse.Button.right, "middle": mouse.Button.middle}
_user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None


def grab_screen():
    """A screenshot of the main screen."""
    return ImageGrab.grab().convert("RGB")


def front_app():
    """Title of the window in front, plus the real program behind it (such as
    "bitwarden.exe"), so a skip-list like "bitwarden" still matches even when the
    window's title alone does not mention the app -- for example a password manager
    that only shows an entry's name, or one that runs inside a browser tab."""
    try:
        hwnd = _user32.GetForegroundWindow()
    except Exception:
        return ""

    title = ""
    try:
        length = _user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
    except Exception:
        pass

    exe_name = ""
    try:
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
        if handle:
            try:
                path_buf = ctypes.create_unicode_buffer(260)
                size = wintypes.DWORD(260)
                ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, path_buf, ctypes.byref(size))
                if ok:
                    exe_name = ntpath.basename(path_buf.value)
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        pass

    return f"{title} {exe_name}".strip()


def glide_to(x, y, fast=False):
    """Move the pointer in small steps, so the app under it notices the move."""
    sx, sy = _mouse.position
    steps = 3 if fast else 6
    for i in range(1, steps + 1):
        _mouse.position = (sx + (x - sx) * i / steps, sy + (y - sy) * i / steps)
        time.sleep(0.01)
    _mouse.position = (x, y)
    time.sleep(0.05 if fast else 0.1)


def mouse_button(name, down, x, y, clicks=1):
    # clicks (the recorded click count: 1 for a single click, 2 for a double-click) is
    # unused here on purpose. Unlike macOS, Windows has no explicit "this is click #2"
    # field on a synthetic click. It recognises a double-click by timing and position
    # alone, from two separate press/release pairs at the same spot -- which is exactly
    # what the replay engine already sends. See scripts/click_test.py to confirm this
    # holds on your own PC.
    _mouse.position = (x, y)
    button = _BUTTONS.get(name, mouse.Button.left)
    (_mouse.press if down else _mouse.release)(button)


def scroll(x, y, dx, dy):
    glide_to(x, y)
    _mouse.scroll(dx, dy)


def key_to_data(key):
    if isinstance(key, keyboard.KeyCode):
        return {"char": key.char} if key.char else {"vk": key.vk}
    return {"name": key.name}


def key_event(data, down):
    if "char" in data:
        key = data["char"]
    elif "vk" in data:
        key = keyboard.KeyCode.from_vk(data["vk"])
    else:
        key = getattr(keyboard.Key, data["name"])
    (_keys.press if down else _keys.release)(key)
