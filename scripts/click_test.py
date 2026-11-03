"""
click_test.py - checks, on your own Windows PC, whether synthetic clicks actually work.
Run it on its own, with no other setup needed beyond:  pip install pynput

    python scripts\\click_test.py

It opens Notepad (or asks you to), then tries a single click, a double-click, and a
right-click, each with a 3-second countdown so you can watch it happen. After each one
it asks whether it worked. Send me the printed PASS/FAIL summary at the end.
"""
import subprocess
import time

from pynput import mouse

_mouse = mouse.Controller()


def countdown(label, seconds=3):
    print(f"\n{label} in...", end=" ", flush=True)
    for n in range(seconds, 0, -1):
        print(n, end=" ", flush=True)
        time.sleep(1)
    print("GO")


def ask(question):
    return input(f"{question} (y/n): ").strip().lower().startswith("y")


def click_at(x, y, button=mouse.Button.left, count=1):
    _mouse.position = (x, y)
    time.sleep(0.1)  # let the app under the pointer notice it moved
    if count == 1:
        _mouse.click(button)
    else:
        _mouse.click(button, count)


def main():
    print(__doc__)
    input("Press Enter, then click into Notepad's text area within 3 seconds so it has focus...")
    countdown("Getting your pointer position")
    x, y = _mouse.position
    print(f"Will click at ({x}, {y}) -- wherever your pointer is right now.")

    results = {}

    countdown("Single left-click")
    click_at(x, y)
    results["single click"] = ask("Did a single click happen there (cursor blinking, nothing selected)?")

    countdown("Double-click (should select the nearest word)")
    click_at(x, y, count=2)
    results["double-click"] = ask("Did it select a word, like a real double-click?")

    countdown("Right-click (should open a context menu)")
    click_at(x, y, button=mouse.Button.right)
    results["right-click"] = ask("Did a right-click menu appear? (press Escape to close it, then answer)")

    print("\n--- RESULTS: copy this whole block and send it back ---")
    for name, ok in results.items():
        print(f"{'PASS' if ok else 'FAIL'}: {name}")
    print("---------------------------------------------------------")


if __name__ == "__main__":
    try:
        subprocess.Popen(["notepad.exe"])
        time.sleep(1)
    except Exception:
        print("Could not open Notepad automatically. Open it yourself, then press Enter.")
    main()
