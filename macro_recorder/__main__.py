"""Start the app with:  python -m macro_recorder"""
import sys


def _dpi_aware():
    """On Windows, tell the OS this app draws its own pixels, so the window and its
    text are not blurrily upscaled on a scaled display (125%, 150%, and so on).
    Must run before any window is created. Does nothing on macOS."""
    if sys.platform != "win32":
        return
    import ctypes
    for attempt in (
        lambda: ctypes.windll.user32.SetProcessDpiAwarenessContext(-4),   # per-monitor v2 (Windows 10+)
        lambda: ctypes.windll.shcore.SetProcessDpiAwareness(2),           # per-monitor
        lambda: ctypes.windll.shcore.SetProcessDpiAwareness(1),           # system DPI aware
        lambda: ctypes.windll.user32.SetProcessDPIAware(),                # old fallback
    ):
        try:
            attempt()
            return
        except Exception:
            continue


def main():
    _dpi_aware()
    from .app import App
    App().mainloop()


if __name__ == "__main__":
    main()
