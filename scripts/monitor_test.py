r"""
monitor_test.py - for anyone with TWO OR MORE monitors. Reports how Windows describes
your screen setup, so a future version of Macro Recorder can support Smart replay across
every monitor, not just the main one.

This does not need you to judge anything by eye -- just run it and send me the output.

    python scripts\monitor_test.py

Right now, Smart replay only looks at your MAIN display (this is also true on macOS,
it is not a Windows-specific limitation). A macro still clicks the right spot on another
monitor, it just cannot re-find a moved button there. This script collects the real
numbers needed to lift that limit safely, instead of guessing at them.
"""
import ctypes


def main():
    print(__doc__)
    user32 = ctypes.windll.user32

    # SM_CXSCREEN=0, SM_CYSCREEN=1: the MAIN display only (what grab_screen() captures today)
    main_w, main_h = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

    # SM_XVIRTUALSCREEN=76, SM_YVIRTUALSCREEN=77, SM_CXVIRTUALSCREEN=78, SM_CYVIRTUALSCREEN=79:
    # the bounding box of ALL monitors combined, including its top-left origin (which can be
    # negative if a monitor is positioned above or to the left of the main one)
    vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)

    monitor_count = user32.GetSystemMetrics(80)  # SM_CMONITORS

    from PIL import ImageGrab
    shot_primary = ImageGrab.grab()
    try:
        shot_all = ImageGrab.grab(all_screens=True)
        all_screens_supported = True
        shot_all_size = shot_all.size
    except TypeError:
        all_screens_supported = False
        shot_all_size = None

    print("--- RESULTS: copy this whole block and send it back ---")
    print(f"Number of monitors Windows reports: {monitor_count}")
    print(f"Main display only (what Smart replay sees today): {main_w} x {main_h}")
    print(f"All monitors combined, origin ({vx}, {vy}), size: {vw} x {vh}")
    print(f"ImageGrab.grab() with no arguments captured: {shot_primary.size}")
    print(f"Pillow supports all_screens=True on this install: {all_screens_supported}")
    print(f"ImageGrab.grab(all_screens=True) captured: {shot_all_size}")
    print("---------------------------------------------------------")


if __name__ == "__main__":
    main()
