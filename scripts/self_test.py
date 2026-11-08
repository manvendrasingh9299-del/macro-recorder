r"""
self_test.py - one command that checks the three things Macro Recorder actually needs
to work: taking a screenshot, sending clicks, and sending keys. Fully automatic -- it
does not need you to click into Notepad or judge anything by eye. Just run it and send
me the printed block at the end.

    python scripts\self_test.py

It briefly opens a tiny test window of its own (with one button and one text box),
clicks and types into it itself, then checks what actually happened -- so the result
is a plain, honest PASS or FAIL, not your own judgement of whether something looked right.
"""
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from macro_recorder import osapi  # noqa: E402 - the real module app.py replays through


def test_screenshot():
    try:
        import numpy as np
        shot = osapi.grab_screen()
        detail = float(np.asarray(shot.convert("L")).std())
        ok = shot.width > 0 and shot.height > 0 and detail > 1.0
        return ok, f"{shot.width}x{shot.height}, detail score {detail:.1f}"
    except Exception as exc:
        return False, f"error: {exc}"


def run():
    results = {"screenshot": test_screenshot()}

    root = tk.Tk()
    root.title("Macro Recorder self-test (closes itself)")
    root.geometry("240x140+80+80")
    clicks = {"single": 0, "double": 0, "right": 0}

    btn = tk.Button(root, text="target", width=20, height=4)
    btn.pack(padx=10, pady=10)
    btn.bind("<Button-1>", lambda e: clicks.__setitem__("single", clicks["single"] + 1))
    btn.bind("<Double-Button-1>", lambda e: clicks.__setitem__("double", clicks["double"] + 1))
    btn.bind("<Button-3>", lambda e: clicks.__setitem__("right", clicks["right"] + 1))

    entry = tk.Entry(root, width=22)
    entry.pack(padx=10, pady=10)

    def button_centre():
        root.update_idletasks()
        return (btn.winfo_rootx() + btn.winfo_width() // 2,
                btn.winfo_rooty() + btn.winfo_height() // 2)

    def do_click(button="left", n=1):
        x, y = button_centre()
        if n == 1:
            osapi.glide_to(x, y, fast=True)
        osapi.mouse_button(button, True, x, y, n)
        osapi.mouse_button(button, False, x, y, n)
        root.update()

    def step_single():
        do_click("left", 1)

    def step_double():
        do_click("left", 1)
        do_click("left", 2)

    def step_right():
        do_click("right", 1)

    def step_type():
        entry.focus_force()
        root.update()
        for ch in "hi7":
            osapi.key_event({"char": ch}, True)
            osapi.key_event({"char": ch}, False)
            root.update()

    def finish():
        results["single click"] = (clicks["single"] >= 1, f"count={clicks['single']}")
        results["double-click"] = (clicks["double"] >= 1, f"count={clicks['double']}")
        results["right-click"] = (clicks["right"] >= 1, f"count={clicks['right']}")
        typed = entry.get()
        results["key sending"] = (typed == "hi7", f"typed back: {typed!r}")
        root.destroy()

    root.after(300, step_single)
    root.after(600, step_double)
    root.after(900, step_right)
    root.after(1200, step_type)
    root.after(1600, finish)
    root.mainloop()

    print("\n--- RESULTS: copy this whole block and send it back ---")
    for name, (ok, detail) in results.items():
        print(f"{'PASS' if ok else 'FAIL'}: {name}  ({detail})")
    print("---------------------------------------------------------")


if __name__ == "__main__":
    print(__doc__)
    run()
