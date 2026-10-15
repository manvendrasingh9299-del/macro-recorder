"""
ui_glass.py - technical-drawing interface for Macro Recorder.
White paper, navy hairlines, orange accents, italic labels. Plain words, no emoji.
Loaded by run.py (one import line).
"""
import math
import random
import tkinter as tk
import tkinter.font as tkfont

import macro_recorder as mr
from macro_recorder import App

ctk = mr.ctk
PAPER, NAVY, ORANGE = "#FFFFFF", "#2B3590", "#E8552B"
SOFT, FAINT = "#8E96D4", "#BCC1E8"


def plain(t):
    """Short, plain wording for every status message."""
    k = t.lower().strip()
    exact = {"ready": "Ready", "stopped": "Stopped", "finished": "Done", "learning off": "Learning is off"}
    if k in exact:
        return exact[k]
    for start, text in (("recording in", "Starting in 3 seconds"), ("recording", "Recording. Press Fn+F8 to finish"),
                        ("recorded", "Recorded. Press Play"), ("starting in", "Starting in 3 seconds"),
                        ("finding target", "Finding the button"), ("target not found", "Button not found. Stopped"),
                        ("not found", "Button not found. Using saved spot"),
                        ("record or load", "Record or load a macro first")):
        if k.startswith(start):
            return text
    if k.startswith("playing"):
        return t.replace(" FAST", "") + ". Fn+F9 stops"
    return t[:1].upper() + t[1:]


# ---------- drawing helpers ----------
def line(cv, *pts, color=NAVY, width=1, dash=None, smooth=False, tags=()):
    return cv.create_line(*pts, fill=color, width=width, dash=dash, smooth=smooth, tags=tags)


def box(cv, x0, y0, x1, y1, color=NAVY, dash=None, fill="", tags=()):
    return cv.create_rectangle(x0 + .5, y0 + .5, x1 + .5, y1 + .5, outline=color, dash=dash, fill=fill, tags=tags)


def cross(cv, x, y, r=9):
    line(cv, x - r, y, x + r, y, color=ORANGE, width=2)
    line(cv, x, y - r, x, y + r, color=ORANGE, width=2)


def terrain(cv):
    """Contour lines, a dashed ridge and a dotted ground, like the reference."""
    rnd = random.Random(5)
    top = lambda x: 652 + 9 * math.sin(x / 38) + 5 * math.sin(x / 13 + 1)
    for k in range(5):
        pts = []
        for x in range(-10, 420, 18):
            pts += [x, top(x) - 6 + k * 7 + 4 * math.sin(x / 55 + k)]
        line(cv, *pts, color=FAINT, smooth=True)
    pts = []
    for x in range(-10, 420, 12):
        pts += [x, top(x) - 12]
    line(cv, *pts, color=NAVY, dash=(5, 3), smooth=True)
    for x in range(0, 400, 5):
        for y in range(int(top(x)) + 14, 704, 5):
            if rnd.random() < .6:
                cv.create_oval(x - .8, y - .8, x + .8, y + .8, fill=SOFT, outline="")


def person(cv, x, y, s=1.0):
    pts = [(-8, 13), (8, 13), (10, 38), (6, 38), (5, 62), (1, 62), (0, 42), (-1, 62), (-5, 62), (-6, 38), (-10, 38)]
    cv.create_polygon([c for px, py in pts for c in (x + px * s, y + py * s)], fill=ORANGE, outline="")
    cv.create_oval(x - 5 * s, y + 1 * s, x + 5 * s, y + 11 * s, fill=ORANGE, outline="")


class _Toggle:
    """Stands in for the old switch: .get() / .select() / .deselect()."""
    def __init__(self, app):
        self.app, self.on = app, True

    def get(self):
        return self.on

    def set(self, v):
        self.on = bool(v)
        cv = self.app.cv
        if self.on:
            cv.coords("tog_knob", 332, 567, 350, 587)
            cv.itemconfigure("tog_knob", fill=ORANGE, outline=ORANGE)
        else:
            cv.coords("tog_knob", 302, 567, 320, 587)
            cv.itemconfigure("tog_knob", fill=PAPER, outline=NAVY)

    select = lambda self: self.set(True)
    deselect = lambda self: self.set(False)


class _BrainBtn:
    """Lets the existing brain-cycling code keep calling .configure(text=...)."""
    def __init__(self, app):
        self.app = app

    def configure(self, **kw):
        if "text" in kw:
            self.app.cv.itemconfigure("txt_method", text=kw["text"].title())


def _build(self):
    fams = set(tkfont.families(self))
    self.fam = fam = next((f for f in ("Futura", "Avenir Next", "Helvetica Neue", "Helvetica") if f in fams), "Helvetica")
    T = lambda size, style="normal": (fam, size, style)
    self.title("Macro Recorder")
    self.geometry("400x704")
    self.configure(fg_color=PAPER)
    cv = self.cv = tk.Canvas(self, width=400, height=704, bg=PAPER, highlightthickness=0, bd=0)
    cv.place(x=0, y=0)
    terrain(cv)
    person(cv, 338, 628)

    # header
    cv.create_text(28, 38, anchor="w", text="Macro Recorder", fill=NAVY, font=T(17, "bold"))
    cv.create_text(28, 60, anchor="w", text="Record once. Replay anytime.", fill=ORANGE, font=T(10, "italic"))
    box(cv, 290, 26, 372, 54)
    cv.create_text(331, 40, text="Settings", fill=NAVY, font=T(11))

    # main frame with crosshair corners
    box(cv, 40, 96, 360, 330, dash=(6, 4))
    for x, y in ((40, 96), (360, 96), (40, 330), (360, 330)):
        cross(cv, x + .5, y + .5)
    cv.create_text(58, 118, anchor="w", text="Ready", fill=ORANGE, font=T(12, "italic"), width=270, tags="status")
    cx, cy, R = 200, 214, 62
    self.ring = (cx, cy, R)
    cv.create_oval(cx - R, cy - R, cx + R, cy + R, outline=NAVY, dash=(2, 4))
    cv.create_arc(cx - R, cy - R, cx + R, cy + R, start=90, extent=-80, style="arc", outline=ORANGE,
                  width=5, state="hidden", tags="arc")
    cv.create_oval(0, 0, 0, 0, fill=ORANGE, outline="", state="hidden", tags="dot")
    cv.create_text(cx, cy - 6, text="0", fill=NAVY, font=T(36), tags="num")
    cv.create_text(cx, cy + 28, text="steps", fill=ORANGE, font=T(11, "italic"))

    # record + play
    cv.create_rectangle(40, 350, 196, 394, fill=ORANGE, outline=ORANGE, tags="r_rec")
    cv.create_text(118, 372, text="Record", fill="#FFFFFF", font=T(13, "bold"), tags="t_rec")
    cv.create_rectangle(204.5, 350.5, 360.5, 394.5, fill=PAPER, outline=NAVY, tags="r_act")
    cv.create_text(282, 372, text="Play", fill=NAVY, font=T(13, "bold"), tags="t_act")

    # repeat / speed / method
    box(cv, 40, 420, 360, 470)
    line(cv, 146.5, 420, 146.5, 470)
    line(cv, 253.5, 420, 253.5, 470)
    for x, label, tag in ((93, "Repeat", "v_rep"), (200, "Speed", "v_spd"), (307, "Method", "txt_method")):
        cv.create_text(x, 433, text=label, fill=ORANGE, font=T(10, "italic"))
        cv.create_text(x, 454, text="", fill=NAVY, font=T(14, "bold"), tags=tag)

    # macro
    box(cv, 40, 486, 360, 536)
    cv.create_text(54, 502, anchor="w", text="Macro", fill=ORANGE, font=T(10, "italic"))
    cv.create_text(54, 522, anchor="w", text="", fill=NAVY, font=T(15, "bold"), tags="name")
    for x0, label in ((226, "Save"), (292, "Open")):
        box(cv, x0, 498, x0 + 60, 524)
        cv.create_text(x0 + 30, 511, text=label, fill=NAVY, font=T(11))

    # smart replay
    box(cv, 40, 552, 360, 602)
    cv.create_text(54, 569, anchor="w", text="Smart replay", fill=NAVY, font=T(13, "bold"))
    cv.create_text(54, 588, anchor="w", text="Finds buttons even if windows move", fill=ORANGE, font=T(9, "italic"))
    box(cv, 300, 565, 352, 589)
    cv.create_rectangle(332, 567, 350, 587, fill=ORANGE, outline=ORANGE, tags="tog_knob")

    self.smart = _Toggle(self)
    self.lbl_brain = _BrainBtn(self)
    self.zones = [(290, 26, 372, 54, "set"), (40, 350, 196, 394, "rec"), (204, 350, 360, 394, "act"),
                  (40, 420, 146, 470, "rep"), (147, 420, 253, 470, "spd"), (254, 420, 360, 470, "method"),
                  (226, 498, 286, 524, "save"), (292, 498, 352, 524, "open"), (296, 556, 356, 598, "tog")]
    self.acts = {"set": self.settings_menu,
                 "rec": lambda: None if self.playing else self.toggle_record(),
                 "act": lambda: None if self.recording else self.toggle_play(),
                 "rep": self.cycle_repeat, "spd": self.cycle_speed, "method": self.cycle_brain,
                 "save": self.save, "open": self.open_library,
                 "tog": lambda: self.smart.set(not self.smart.get())}
    cv.bind("<Motion>", lambda e: cv.config(cursor="pointinghand" if self._zone(e.x, e.y) else ""))
    cv.bind("<Button-1>", lambda e: (lambda f: f and f())(self._zone(e.x, e.y)))


def _zone(self, x, y):
    for x0, y0, x1, y1, key in self.zones:
        if x0 <= x <= x1 and y0 <= y <= y1:
            return self.acts[key]
    return None


def _tick(self):
    self.anim += 1
    cx, cy, R = self.ring
    cv = self.cv
    if self.recording:
        start, extent = (90 - self.anim * 10) % 360, -80
    elif self.playing:
        p = min(1.0, getattr(self, "idx", 0) / max(1, len(self.events)))
        start, extent = 90, -max(3.0, 359.9 * p)
    else:
        self.idx = 0
        start = None
    if start is None:
        cv.itemconfigure("arc", state="hidden")
        cv.itemconfigure("dot", state="hidden")
    else:
        cv.itemconfigure("arc", state="normal", start=start, extent=extent)
        ang = math.radians(start + extent)
        x, y = cx + R * math.cos(ang), cy - R * math.sin(ang)
        cv.coords("dot", x - 5, y - 5, x + 5, y + 5)
        cv.itemconfigure("dot", state="normal")
    self.after(100, self._tick)


def set_status(self, color, text):
    self.cv.itemconfigure("status", text=plain(text))


def refresh_lcd(self):
    n, cv = self.repeat_n, self.cv
    cv.itemconfigure("v_rep", text=f"{n} time" if n == 1 else f"{n} times")
    cv.itemconfigure("v_spd", text=f"{self.speed_v:g}x")
    name = "Untitled" if self.macro_name == "UNTITLED" else self.macro_name
    cv.itemconfigure("name", text=name if len(name) <= 13 else name[:12] + "...")
    cv.itemconfigure("num", text=str(self.nsteps))


def update_count(self):
    self.nsteps = sum(1 for e in self.events if e["type"] in ("click", "key") and e["pressed"])
    self.cv.itemconfigure("num", text=str(self.nsteps))


def refresh_buttons(self):
    cv = self.cv
    if self.recording:
        cv.itemconfigure("r_rec", fill=PAPER, outline=ORANGE)
        cv.itemconfigure("t_rec", text="Stop", fill=ORANGE)
    else:
        col = FAINT if self.playing else ORANGE
        cv.itemconfigure("r_rec", fill=col, outline=col)
        cv.itemconfigure("t_rec", text="Record", fill="#FFFFFF")
    if self.playing:
        cv.itemconfigure("r_act", fill=NAVY, outline=NAVY)
        cv.itemconfigure("t_act", text="Stop", fill="#FFFFFF")
    else:
        col = FAINT if self.recording else NAVY
        cv.itemconfigure("r_act", fill=PAPER, outline=col)
        cv.itemconfigure("t_act", text="Play", fill=col)


def open_library(self):
    names = sorted(p.stem for p in mr.MACRO_DIR.glob("*.json"))
    win = ctk.CTkToplevel(self)
    win.title("Open macro")
    win.geometry("340x420")
    win.configure(fg_color=PAPER)
    win.after(100, win.lift)
    f = lambda s, st="normal": (self.fam, s, st)
    ctk.CTkLabel(win, text="Open macro", font=f(16, "bold"), text_color=NAVY).pack(pady=(18, 4))
    ctk.CTkLabel(win, text="Choose a saved macro", font=f(10, "italic"), text_color=ORANGE).pack(pady=(0, 10))
    box_ = ctk.CTkScrollableFrame(win, fg_color=PAPER, corner_radius=0, border_width=1, border_color=NAVY)
    box_.pack(fill="both", expand=True, padx=18, pady=(0, 18))
    if not names:
        ctk.CTkLabel(box_, text="No saved macros yet.\nRecord one, then press Save.",
                     font=f(11), text_color=NAVY).pack(pady=28)
    for n in names:
        r = ctk.CTkFrame(box_, fg_color="transparent")
        r.pack(fill="x", pady=3)
        ctk.CTkButton(r, text=n, anchor="w", font=f(12), fg_color=PAPER, hover_color="#EEF0FA", text_color=NAVY,
                      border_width=1, border_color=NAVY, corner_radius=0, height=32,
                      command=lambda n=n: (self.load_named(n), win.destroy())).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(r, text="Delete", width=64, height=32, font=f(11, "italic"), fg_color="transparent",
                      hover_color="#EEF0FA", text_color=ORANGE, corner_radius=0,
                      command=lambda n=n: (self.delete_named(n), win.destroy())).pack(side="left", padx=(6, 0))


for _fn in (_build, _zone, _tick, set_status, refresh_lcd, update_count, refresh_buttons, open_library):
    setattr(App, _fn.__name__, _fn)