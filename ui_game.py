"""
ui_game.py - takes the clutter off the handheld game screen. Loaded by run.py (one import line).
Removes: gem button, info button, heart counter, REC / PLAY badge, small grey cat on the screen,
and both footer lines. Stop hints now appear in the status line only when they matter.
"""
import macro_recorder as mr
from macro_recorder import App

_orig_build = App._build


def _text(w):
    try:
        return w.cget("text")
    except Exception:
        return None


def _build(self):
    _orig_build(self)
    for w in self.winfo_children():                       # footer lines
        t = _text(w) or ""
        if t.startswith("BUILD ANYTHING") or t.startswith("F8 STOP"):
            w.destroy()
    for w in self.scene.master.winfo_children():          # gem and info buttons (the gear stays)
        if _text(w) in ("\u25c6", "i"):
            w.destroy()
    self.scene.delete("hearts", "badge")                  # heart counter and the REC / PLAY badge
    self.lcd.delete("icon")                               # small grey cat on the screen
    self.lcd.coords("name", 20, 52)                       # with the icon gone, the name moves up
    self.lcd.itemconfigure("name", font=mr.mono(14, True))
    self.lcd.coords("status", 20, 96)
    self.lcd.itemconfigure("status", font=mr.mono(10), width=164)


def set_status(self, color, text):
    t = text.strip()
    if t == "Recording":
        t += ". FN+F8 STOPS"
    elif t.startswith("Playing"):
        t = t.replace(" FAST", "") + ". FN+F9 STOPS"
    self.lcd.itemconfigure("status", text=t.upper())


for _fn in (_build, set_status):
    setattr(App, _fn.__name__, _fn)