"""
ui_glass.py - clean interface for Macro Recorder, built from native controls (crisp on Retina).
Loaded by run.py (one import line). Plain words, no emoji.
"""
import math
import tkinter as tk
import tkinter.font as tkfont

import macro_recorder as mr
from macro_recorder import App

ctk = mr.ctk
BG, WHITE, DARK, MUTED = "#E5EADF", "#FFFFFF", "#1D2E16", "#7A8574"
GREEN, TRACK, DISC = "#5B8A4D", "#7FA672", "#4B7A41"
CHIP, CHIP_HOVER = "#F2F5EE", "#E6ECDE"
LAV, MINT, PEACH, ROSE = "#DCD6F6", "#CFE8D5", "#F8DCC8", "#F8CFD9"
RC, RR = 95, 76   # ring centre and radius


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


class _BrainBtn:
    """Lets the existing brain-cycling code keep calling .configure(text=...)."""
    def __init__(self, btn):
        self.btn = btn

    def configure(self, **kw):
        if "text" in kw:
            self.btn.configure(text=kw["text"].title())


def _build(self):
    ctk.set_appearance_mode("light")
    fams = set(tkfont.families(self))
    self.fam = fam = next((f for f in ("Avenir Next", "Helvetica Neue", "Helvetica") if f in fams), "Helvetica")
    F = lambda size, bold=False: ctk.CTkFont(family=fam, size=size, weight="bold" if bold else "normal")
    self.title("Macro Recorder")
    self.geometry("400x704")
    self.configure(fg_color=BG)

    # hero card
    hero = ctk.CTkFrame(self, fg_color=GREEN, corner_radius=32)
    hero.pack(fill="x", padx=20, pady=(20, 12))
    top = ctk.CTkFrame(hero, fg_color="transparent")
    top.pack(fill="x", padx=24, pady=(20, 0))
    names = ctk.CTkFrame(top, fg_color="transparent")
    names.pack(side="left")
    ctk.CTkLabel(names, text="Macro Recorder", font=F(15, True), text_color="#FFFFFF").pack(anchor="w")
    self.status = ctk.CTkLabel(names, text="Ready", font=F(11), text_color="#E3EEDA", anchor="nw",
                               justify="left", wraplength=200, width=200, height=34)
    self.status.pack(anchor="w", pady=(2, 0))
    ctk.CTkButton(top, text="Settings", width=84, height=30, corner_radius=15, font=F(11, True),
                  fg_color="#7BA26D", hover_color="#6E9660", text_color="#FFFFFF",
                  command=self.settings_menu).pack(side="right", anchor="n")

    cv = self.ring = tk.Canvas(hero, width=190, height=190, bg=GREEN, highlightthickness=0, bd=0)
    cv.pack(pady=(2, 6))
    cv.create_oval(RC - RR, RC - RR, RC + RR, RC + RR, outline=TRACK, width=9)
    cv.create_arc(RC - RR, RC - RR, RC + RR, RC + RR, start=90, extent=-359.9, style="arc",
                  outline="#CFE3BF", width=9, tags="arc")
    cv.create_oval(0, 0, 0, 0, fill="#FFFFFF", outline="", state="hidden", tags="dot")
    cv.create_oval(RC - 58, RC - 58, RC + 58, RC + 58, fill=DISC, outline="")
    cv.create_text(RC, RC - 8, text="0", fill="#FFFFFF", font=(fam, 34, "bold"), tags="num")
    cv.create_text(RC, RC + 26, text="steps", fill="#D7E6CB", font=(fam, 11))

    row = ctk.CTkFrame(hero, fg_color="transparent")
    row.pack(fill="x", padx=24, pady=(4, 22))
    row.columnconfigure((0, 1), weight=1, uniform="b")
    self.btn_rec = ctk.CTkButton(row, text="Record", height=46, corner_radius=23, font=F(13, True),
                                 fg_color="#FFFFFF", hover_color="#EEF3E8", text_color=DARK,
                                 text_color_disabled="#A9B7A0", command=self.toggle_record)
    self.btn_rec.grid(row=0, column=0, sticky="ew", padx=(0, 6))
    self.btn_act = ctk.CTkButton(row, text="Play", height=46, corner_radius=23, font=F(13, True),
                                 fg_color="#1F3B14", hover_color="#2B4F1D", text_color="#FFFFFF",
                                 text_color_disabled="#7E9876", command=self.toggle_play)
    self.btn_act.grid(row=0, column=1, sticky="ew", padx=(6, 0))

    # repeat + speed
    row2 = ctk.CTkFrame(self, fg_color="transparent")
    row2.pack(fill="x", padx=20, pady=(0, 12))
    row2.columnconfigure((0, 1), weight=1, uniform="c")

    def chip_card(col, label, cmd):
        f = ctk.CTkFrame(row2, fg_color=WHITE, corner_radius=24)
        f.grid(row=0, column=col, sticky="ew", padx=(0, 6) if col == 0 else (6, 0))
        ctk.CTkLabel(f, text=label, font=F(11), text_color=MUTED, anchor="w").pack(anchor="w", padx=20, pady=(14, 4))
        b = ctk.CTkButton(f, text="", height=36, corner_radius=18, font=F(14, True), fg_color=CHIP,
                          hover_color=CHIP_HOVER, text_color=DARK, command=cmd)
        b.pack(fill="x", padx=14, pady=(0, 14))
        return b

    self.btn_rep = chip_card(0, "Repeat", self.cycle_repeat)
    self.btn_spd = chip_card(1, "Speed", self.cycle_speed)

    # macro
    mac = ctk.CTkFrame(self, fg_color=WHITE, corner_radius=24)
    mac.pack(fill="x", padx=20, pady=(0, 12))
    left = ctk.CTkFrame(mac, fg_color="transparent")
    left.pack(side="left", padx=(20, 0), pady=16)
    ctk.CTkLabel(left, text="Macro", font=F(11), text_color=MUTED, anchor="w").pack(anchor="w")
    self.lbl_name = ctk.CTkLabel(left, text="Untitled", font=F(16, True), text_color=DARK, anchor="w", width=130)
    self.lbl_name.pack(anchor="w")
    btns = ctk.CTkFrame(mac, fg_color="transparent")
    btns.pack(side="right", padx=(0, 16))
    for text, cmd, fg, hv in (("Save", self.save, LAV, "#CFC8F0"), ("Open", self.open_library, MINT, "#BEDCC6")):
        ctk.CTkButton(btns, text=text, width=64, height=34, corner_radius=17, font=F(12, True), fg_color=fg,
                      hover_color=hv, text_color=DARK, command=cmd).pack(side="left", padx=(6, 0))

    # smart replay + method
    sm = ctk.CTkFrame(self, fg_color=WHITE, corner_radius=24)
    sm.pack(fill="x", padx=20, pady=(0, 20))
    r1 = ctk.CTkFrame(sm, fg_color="transparent")
    r1.pack(fill="x", padx=20, pady=(16, 0))
    txt = ctk.CTkFrame(r1, fg_color="transparent")
    txt.pack(side="left")
    ctk.CTkLabel(txt, text="Smart replay", font=F(14, True), text_color=DARK, anchor="w").pack(anchor="w")
    ctk.CTkLabel(txt, text="Finds buttons even if windows move", font=F(10), text_color=MUTED,
                 anchor="w").pack(anchor="w")
    self.smart = ctk.CTkSwitch(r1, text="", width=50, switch_width=48, switch_height=26,
                               progress_color="#7DB88A", button_color="#FFFFFF",
                               button_hover_color="#F3F6EF", fg_color="#D5DBCF")
    self.smart.select()
    self.smart.pack(side="right")
    ctk.CTkFrame(sm, height=1, corner_radius=0, fg_color="#EDF0E8").pack(fill="x", padx=20, pady=12)
    r2 = ctk.CTkFrame(sm, fg_color="transparent")
    r2.pack(fill="x", padx=20, pady=(0, 16))
    ctk.CTkLabel(r2, text="Method", font=F(12, True), text_color=DARK).pack(side="left")
    self.btn_method = ctk.CTkButton(r2, text="Local", width=92, height=32, corner_radius=16, font=F(12, True),
                                    fg_color=PEACH, hover_color="#F0CDB5", text_color=DARK, command=self.cycle_brain)
    self.btn_method.pack(side="right")
    self.lbl_brain = _BrainBtn(self.btn_method)


def _tick(self):
    self.anim += 1
    cv = self.ring
    if self.recording:
        start, extent, col = (90 - self.anim * 10) % 360, -80, "#FFFFFF"
    elif self.playing:
        p = min(1.0, getattr(self, "idx", 0) / max(1, len(self.events)))
        start, extent, col = 90, -max(3.0, 359.9 * p), "#FFFFFF"
    else:
        self.idx = 0
        start, extent, col = 90, -359.9, "#CFE3BF"
    cv.itemconfigure("arc", start=start, extent=extent, outline=col)
    if self.recording or self.playing:
        ang = math.radians(start + extent)
        x, y = RC + RR * math.cos(ang), RC - RR * math.sin(ang)
        cv.coords("dot", x - 6, y - 6, x + 6, y + 6)
        cv.itemconfigure("dot", state="normal")
    else:
        cv.itemconfigure("dot", state="hidden")
    self.after(100, self._tick)


def set_status(self, color, text):
    self.status.configure(text=plain(text))


def refresh_lcd(self):
    n = self.repeat_n
    self.btn_rep.configure(text=f"{n} time" if n == 1 else f"{n} times")
    self.btn_spd.configure(text=f"{self.speed_v:g}x")
    name = "Untitled" if self.macro_name == "UNTITLED" else self.macro_name
    self.lbl_name.configure(text=name if len(name) <= 14 else name[:13] + "...")
    self.ring.itemconfigure("num", text=str(self.nsteps))


def update_count(self):
    self.nsteps = sum(1 for e in self.events if e["type"] in ("click", "key") and e["pressed"])
    self.ring.itemconfigure("num", text=str(self.nsteps))


def refresh_buttons(self):
    self.btn_rec.configure(text="Stop" if self.recording else "Record",
                           fg_color=ROSE if self.recording else "#FFFFFF",
                           hover_color="#F4BFCB" if self.recording else "#EEF3E8",
                           state="disabled" if self.playing else "normal")
    self.btn_act.configure(text="Stop" if self.playing else "Play",
                           fg_color=ROSE if self.playing else "#1F3B14",
                           hover_color="#F4BFCB" if self.playing else "#2B4F1D",
                           text_color=DARK if self.playing else "#FFFFFF",
                           state="disabled" if self.recording else "normal")


def open_library(self):
    names = sorted(p.stem for p in mr.MACRO_DIR.glob("*.json"))
    win = ctk.CTkToplevel(self)
    win.title("Open macro")
    win.geometry("340x420")
    win.configure(fg_color=BG)
    win.after(100, win.lift)
    f = lambda s, b=False: (self.fam, s, "bold" if b else "normal")
    ctk.CTkLabel(win, text="Open macro", font=f(16, True), text_color=DARK).pack(pady=(18, 10))
    box = ctk.CTkScrollableFrame(win, fg_color=WHITE, corner_radius=22)
    box.pack(fill="both", expand=True, padx=18, pady=(0, 18))
    if not names:
        ctk.CTkLabel(box, text="No saved macros yet.\nRecord one, then press Save.",
                     font=f(11), text_color=MUTED).pack(pady=28)
    for n in names:
        r = ctk.CTkFrame(box, fg_color="transparent")
        r.pack(fill="x", pady=3)
        ctk.CTkButton(r, text=n, anchor="w", font=f(12), fg_color=CHIP, hover_color=CHIP_HOVER, text_color=DARK,
                      corner_radius=14, height=34,
                      command=lambda n=n: (self.load_named(n), win.destroy())).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(r, text="Delete", width=64, height=34, font=f(11), fg_color="transparent",
                      hover_color=CHIP, text_color=MUTED,
                      command=lambda n=n: (self.delete_named(n), win.destroy())).pack(side="left", padx=(6, 0))


for _fn in (_build, _tick, set_status, refresh_lcd, update_count, refresh_buttons, open_library):
    setattr(App, _fn.__name__, _fn)