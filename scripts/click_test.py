r"""
click_test.py - checks, on your own Windows PC, whether Macro Recorder's OWN click code
works -- not just pynput in general. It calls osapi.glide_to() and osapi.mouse_button(),
the exact functions app.py uses to replay a macro, with the exact same arguments a real
double-click replay would use (two separate clicks, click count 1 then 2).

Run it from the project folder, with the environment already set up:

    python scripts\click_test.py

It opens Notepad, gives a 3-second countdown before each action, then tries a single
click, a double-click, and a right-click. After each one it asks whether it worked.
Send me the printed PASS/FAIL block at the end.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from macro_recorder import osapi  # noqa: E402 - the real module app.py replays through


def countdown(label, seconds=3):
    print(f"\n{label} in...", end=" ", flush=True)
    for n in range(seconds, 0, -1):
        print(n, end=" ", flush=True)
        time.sleep(1)
    print("GO")


def ask(question):
    return input(f"{question} (y/n): ").strip().lower().startswith("y")


def do_click(x, y, button="left", n=1, gap=0.0):
    """One click event, exactly as app.py's _do() sends it during replay."""
    if n == 1:
        osapi.glide_to(x, y, fast=False)
    osapi.mouse_button(button, True, x, y, n)
    if gap:
        time.sleep(gap)
    osapi.mouse_button(button, False, x, y, n)


def main():
    print(__doc__)
    input("Press Enter, then click into Notepad's text area within 3 seconds so it has focus...")
    countdown("Getting your pointer position")

    from pynput import mouse
    x, y = mouse.Controller().position
    print(f"Will click at ({x}, {y}) -- wherever your pointer is right now.")

    results = {}

    countdown("Single left-click")
    do_click(x, y, "left", n=1)
    results["single click"] = ask("Did a single click happen there (cursor blinking, nothing selected)?")

    countdown("Double-click (two real click events, 30ms apart, like a fast-replayed macro)")
    do_click(x, y, "left", n=1, gap=0.03)
    do_click(x, y, "left", n=2, gap=0.03)
    results["double-click"] = ask("Did it select a word, like a real double-click?")

    countdown("Right-click (should open a context menu)")
    do_click(x, y, "right", n=1)
    results["right-click"] = ask("Did a right-click menu appear? (press Escape to close it, then answer)")

    print("\n--- RESULTS: copy this whole block and send it back ---")
    for name, ok in results.items():
        print(f"{'PASS' if ok else 'FAIL'}: {name}")
    print("---------------------------------------------------------")


if __name__ == "__main__":
    import subprocess
    try:
        subprocess.Popen(["notepad.exe"])
        time.sleep(1)
    except Exception:
        print("Could not open Notepad automatically. Open it yourself, then press Enter.")
    main()
