"""Everything that talks to macOS: screenshots, mouse and keyboard control, the front app."""
import time

import numpy as np
from AppKit import NSWorkspace
from PIL import Image, ImageGrab
from pynput import keyboard, mouse
from Quartz import (CGDataProviderCopyData, CGDisplayCreateImage, CGEventCreateMouseEvent, CGEventPost,
                    CGEventSetIntegerValueField, CGEventSourceCreate, CGImageGetBytesPerRow,
                    CGImageGetDataProvider, CGImageGetHeight, CGImageGetWidth, CGMainDisplayID,
                    kCGEventLeftMouseDown, kCGEventLeftMouseUp, kCGEventMouseMoved,
                    kCGEventOtherMouseDown, kCGEventOtherMouseUp, kCGEventRightMouseDown,
                    kCGEventRightMouseUp, kCGEventSourceStateHIDSystemState, kCGHIDEventTap,
                    kCGMouseButtonCenter, kCGMouseButtonLeft, kCGMouseButtonRight, kCGMouseEventClickState)

_mouse, _keys = mouse.Controller(), keyboard.Controller()
_source = CGEventSourceCreate(kCGEventSourceStateHIDSystemState)
_BUTTONS = {"left": (kCGEventLeftMouseDown, kCGEventLeftMouseUp, kCGMouseButtonLeft),
            "right": (kCGEventRightMouseDown, kCGEventRightMouseUp, kCGMouseButtonRight),
            "middle": (kCGEventOtherMouseDown, kCGEventOtherMouseUp, kCGMouseButtonCenter)}


def grab_screen():
    """A fast screenshot of the main screen (about 40 ms)."""
    try:
        img = CGDisplayCreateImage(CGMainDisplayID())
        w, h, row = CGImageGetWidth(img), CGImageGetHeight(img), CGImageGetBytesPerRow(img)
        data = np.frombuffer(CGDataProviderCopyData(CGImageGetDataProvider(img)), np.uint8)
        return Image.fromarray(data.reshape(h, row // 4, 4)[:, :w, 2::-1].copy())
    except Exception:
        return ImageGrab.grab().convert("RGB")


def front_app():
    """Name of the app in front, or an empty string."""
    try:
        return NSWorkspace.sharedWorkspace().frontmostApplication().localizedName() or ""
    except Exception:
        return ""


def _post(kind, x, y, button=0, clicks=1):
    event = CGEventCreateMouseEvent(_source, kind, (x, y), button)
    CGEventSetIntegerValueField(event, kCGMouseEventClickState, clicks)
    CGEventPost(kCGHIDEventTap, event)


def glide_to(x, y, fast=False):
    """Move the pointer in small steps, so the Dock and menus notice it."""
    sx, sy = _mouse.position
    steps = 3 if fast else 6
    for i in range(1, steps + 1):
        _post(kCGEventMouseMoved, sx + (x - sx) * i / steps, sy + (y - sy) * i / steps)
        time.sleep(0.015)
    _post(kCGEventMouseMoved, x, y)
    time.sleep(0.12 if fast else 0.25)


def mouse_button(name, down, x, y, clicks=1):
    press, release, button = _BUTTONS.get(name, _BUTTONS["left"])
    if not down:
        time.sleep(0.05)   # hold the button long enough to count as a click
    _post(press if down else release, x, y, button, clicks)


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
