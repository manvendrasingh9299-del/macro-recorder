"""Picks the right system backend for this computer.
Every other file calls osapi.grab_screen(), osapi.mouse_button(), and so on,
without needing to know whether it is running on macOS or Windows."""
import sys

if sys.platform == "darwin":
    from .macos import *  # noqa: F401,F403
else:
    from .windows import *  # noqa: F401,F403
