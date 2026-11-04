r"""
scale_test.py - checks, on your own Windows PC, whether a screenshot's pixels line up
with where clicks actually land. This matters because Windows display scaling (125%,
150%, and so on) can make a window-size reading and a screenshot disagree about how big
the screen is, in which case Macro Recorder would click the wrong spot even when it
correctly SEES the right button in a screenshot.

Run it from the project folder, with the environment already set up:

    python scripts\scale_test.py

It reports three independent readings of your screen size, then moves the pointer to
two points computed the exact same way matching.py converts a found picture into a
click position. You just confirm by eye whether the pointer landed where it should.
Send me the whole printed block at the end.
"""
import os
import sys
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from macro_recorder.__main__ import _dpi_aware  # noqa: E402 - same call app.py makes first
from macro_recorder import osapi  # noqa: E402 - the real module app.py replays through


def ask(question):
    return input(f"{question} (y/n): ").strip().lower().startswith("y")


def countdown(label, seconds=2):
    print(f"\n{label} in...", end=" ", flush=True)
    for n in range(seconds, 0, -1):
        print(n, end=" ", flush=True)
        time.sleep(1)
    print("GO")


def main():
    print(__doc__)
    _dpi_aware()  # must run before any window or screenshot, exactly like __main__.py

    root = tk.Tk()
    root.withdraw()
    root.update_idletasks()
    tk_w, tk_h = root.winfo_screenwidth(), root.winfo_screenheight()
    root.destroy()

    shot = osapi.grab_screen()
    shot_w, shot_h = shot.size

    metrics_w = metrics_h = dpi = None
    try:
        import ctypes
        metrics_w = ctypes.windll.user32.GetSystemMetrics(0)   # SM_CXSCREEN
        metrics_h = ctypes.windll.user32.GetSystemMetrics(1)   # SM_CYSCREEN
        dpi = ctypes.windll.user32.GetDpiForSystem()           # 96 = 100%, 144 = 150%, ...
    except Exception:
        pass

    print("\n--- RAW NUMBERS ---")
    print(f"Tk reports the screen as:         {tk_w} x {tk_h}")
    print(f"A screenshot actually captured:   {shot_w} x {shot_h}")
    print(f"Windows GetSystemMetrics reports: {metrics_w} x {metrics_h}")
    print(f"Windows system DPI:               {dpi}  (96 = 100%, 120 = 125%, 144 = 150%)")
    s = shot_w / tk_w if tk_w else 0
    print(f"Scale ratio matching.py would use (shot.width / tk width): {s:.4f}")
    print("If every width above matches, this ratio should be 1.0000 -- that is correct.")

    # The functional test: pick a point IN the screenshot, convert it to a click position
    # using the exact formula matching.py uses, then check it lands in the right place.
    results = {}
    for label, frac in (("the exact centre of your screen", (0.5, 0.5)),
                        ("one quarter in, three quarters down", (0.25, 0.75))):
        px, py = shot_w * frac[0], shot_h * frac[1]
        click_x, click_y = px / s, py / s
        countdown(f"Moving the pointer to {label}")
        osapi.glide_to(click_x, click_y, fast=False)
        results[label] = ask(f"Is the pointer now at {label}?")

    print("\n--- RESULTS: copy this whole block and send it back ---")
    print(f"tk={tk_w}x{tk_h} shot={shot_w}x{shot_h} metrics={metrics_w}x{metrics_h} dpi={dpi} ratio={s:.4f}")
    for name, ok in results.items():
        print(f"{'PASS' if ok else 'FAIL'}: {name}")
    print("---------------------------------------------------------")


if __name__ == "__main__":
    main()
