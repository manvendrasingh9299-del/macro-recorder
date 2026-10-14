"""
ui_glass.py - clean liquid-glass interface for Macro Recorder.
Loaded by run.py (one import line). Replaces the old window layout. Plain words, no emoji.
"""
import math
import tkinter as tk
import tkinter.font as tkfont

from PIL import Image, ImageChops, ImageDraw, ImageFilter

import macro_recorder as mr
from macro_recorder import App

ctk = mr.ctk
S = 2  # draw at 2x, then shrink, for smooth edges
BG, DARK, MUTED = "#E5EADF", "#1D2E16", "#7A8574"
LAV, MINT, PEACH, ROSE = "#D8D2F4", "#CDE8D3", "#F7D9C4", "#F8D3DC"
CARDS = [(20, 20, 380, 300, 36), (20, 316, 194, 396, 26), (206, 316, 380, 396, 26),
         (20, 408, 380, 488, 26), (20, 500, 380, 620, 26)]   # hero, repeat, speed, macro, smart
PAD = 12


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def make_bg(W=400, H=660):
    w, h = W * S, H * S
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(h):
        d.line([(0, y), (w, y)], fill=mr.lerp("#E8EDE2", "#DCE3D4", y / h))
    sh = Image.new("L", (w, h), 0)
    sd = ImageDraw.Draw(sh)
    for x0, y0, x1, y1, r in CARDS:
        sd.rounded_rectangle([x0 * S, (y0 + 8) * S, x1 * S, (y1 + 8) * S], r * S, fill=70)
    im.paste((74, 96, 64), (0, 0, w, h), sh.filter(ImageFilter.GaussianBlur(14 * S)))
    d = ImageDraw.Draw(im)
    for x0, y0, x1, y1, r in CARDS[1:]:
        d.rounded_rectangle([x0 * S, y0 * S, x1 * S, y1 * S], r * S, fill="#FFFFFF")
    d.line([(44 * S, 566 * S), (356 * S, 566 * S)], fill="#EDF0E8", width=S)
    x0, y0, x1, y1, r = CARDS[0]
    hw, hh = (x1 - x0) * S, (y1 - y0) * S
    hero = Image.new("RGB", (hw, hh))
    hd = ImageDraw.Draw(hero)
    for y in range(hh):
        hd.line([(0, y), (hw, y)], fill=mr.lerp("#86AB69", "#4F7A45", y / hh))
    hd.ellipse([int(hw * .45), -int(hh * .3), int(hw * 1.15), int(hh * .5)], fill="#A9CA85")
    hd.ellipse([-int(hw * .25), int(hh * .55), int(hw * .55), int(hh * 1.25)], fill="#3E6A39")
    hero = hero.filter(ImageFilter.GaussianBlur(34 * S))
    mask = Image.new("L", (hw, hh), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, hw - 1, hh - 1], r * S, fill=255)
    im.paste(hero, (x0 * S, y0 * S), mask)
    return im.resize((W, H), Image.Resampling.LANCZOS)


def glass(bg, x, y, w, h, tint, body_a=235, hl_a=110, glow_a=95):
    """A liquid-glass pill, drawn over the exact background it sits on. Returns a PIL image."""
    base = bg.crop((x - PAD, y - PAD, x + w + PAD, y + h + PAD)).convert("RGBA")
    W, H = w + 2 * PAD, h + 2 * PAD
    ov = Image.new("RGBA", (W * S, H * S), _rgb(tint) + (0,))
    rect = [PAD * S, PAD * S, (PAD + w) * S, (PAD + h) * S]
    r = h * S // 2
    if glow_a:  # soft coloured glow under the pill
        m = Image.new("L", ov.size, 0)
        ImageDraw.Draw(m).rounded_rectangle([rect[0], rect[1] + 2 * S, rect[2], rect[3] + 4 * S], r, fill=glow_a)
        g = Image.new("RGBA", ov.size, _rgb(tint) + (0,))
        g.putalpha(m.filter(ImageFilter.GaussianBlur(4 * S)))
        ov = Image.alpha_composite(ov, g)
    grad = Image.new("RGBA", ov.size, (0, 0, 0, 0))   # body: lighter at the top, tint at the bottom
    gd = ImageDraw.Draw(grad)
    top, bot = _rgb(mr.lerp(tint, "#FFFFFF", .5)), _rgb(tint)
    for yy in range(rect[1], rect[3] + 1):
        t = (yy - rect[1]) / max(1, rect[3] - rect[1])
        gd.line([(rect[0], yy), (rect[2], yy)], fill=tuple(round(p + (q - p) * t) for p, q in zip(top, bot)) + (body_a,))
    shape = Image.new("L", ov.size, 0)
    ImageDraw.Draw(shape).rounded_rectangle(rect, r, fill=255)
    grad.putalpha(ImageChops.multiply(grad.getchannel("A"), shape))
    ov = Image.alpha_composite(ov, grad)
    m = Image.new("L", ov.size, 0)   # soft white sheen across the top
    ImageDraw.Draw(m).rounded_rectangle([rect[0] + 10 * S, rect[1] + 3 * S, rect[2] - 10 * S, rect[1] + int(h * S * .42)],
                                        int(r * .6), fill=hl_a)
    sheen = Image.new("RGBA", ov.size, (255, 255, 255, 0))
    sheen.putalpha(m.filter(ImageFilter.GaussianBlur(1.5 * S)))
    ov = Image.alpha_composite(ov, sheen)
    edge = Image.new("RGBA", ov.size, (255, 255, 255, 0))   # thin glass edge
    ImageDraw.Draw(edge).rounded_rectangle(rect, r, outline=(255, 255, 255, 190), width=int(1.4 * S))
    ov = Image.alpha_composite(ov, edge).resize((W, H), Image.Resampling.LANCZOS)
    return Image.alpha_composite(base, ov).convert("RGB")


def toggle_img(bg, x, y, on):
    img = glass(bg, x, y, 56, 32, "#BFE3C4" if on else "#DCE1D6", 255, 90, 70 if on else 0)
    k = 4
    layer = Image.new("RGBA", (img.width * k, img.height * k), (0, 0, 0, 0))
    cx, cy, r = (PAD + (40 if on else 16)) * k, (PAD + 16) * k, 12 * k
    sh = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([cx - r, cy - r + 3 * k, cx + r, cy + r + 3 * k], fill=(40, 60, 30, 70))
    layer = Image.alpha_composite(layer, sh.filter(ImageFilter.GaussianBlur(3 * k)))
    ImageDraw.Draw(layer).ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 255),
                                  outline=(232, 238, 228, 255), width=k)
    layer = layer.resize(img.size, Image.Resampling.LANCZOS)
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


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


class _Toggle:
    """Stands in for the old switch: .get() / .select() / .deselect()."""
    def __init__(self, app):
        self.app, self.on = app, True

    def get(self):
        return self.on

    def set(self, v):
        self.on = bool(v)
        self.app.cv.itemconfigure("img_tog", image=self.app.gimg["tog_on" if self.on else "tog_off"])

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
    ctk.set_appearance_mode("light")
    fams = set(tkfont.families(self))
    self.fn = next((f for f in ("Avenir Next", "Helvetica Neue", "Helvetica") if f in fams), "Helvetica")
    F = lambda size, bold=False: (self.fn, size, "bold" if bold else "normal")
    self.title("Macro Recorder")
    self.geometry("400x660")
    self.configure(fg_color=BG)
    cv = self.cv = tk.Canvas(self, width=400, height=660, highlightthickness=0, bd=0, bg=BG)
    cv.place(x=0, y=0)

    pills = {  # name: x, y, w, h, tint, body alpha, highlight alpha, glow alpha
        "set": (266, 34, 94, 28, "#3F6B35", 150, 70, 0),
        "save": (226, 431, 64, 34, LAV, 255, 110, 100),
        "open": (298, 431, 64, 34, MINT, 255, 110, 100),
        "method": (282, 578, 82, 30, PEACH, 255, 110, 100),
        "rec": (40, 240, 130, 44, "#FFFFFF", 225, 120, 60),
        "rec_on": (40, 240, 130, 44, ROSE, 235, 120, 60),
        "act": (230, 240, 130, 44, "#1F3B14", 245, 45, 60),
        "act_on": (230, 240, 130, 44, ROSE, 235, 120, 60)}
    bg = make_bg()
    for key in ("set", "save", "open", "method"):
        bg.paste(glass(bg, *pills[key]), (pills[key][0] - PAD, pills[key][1] - PAD))
    self.bg_img = mr.to_photo(bg)
    cv.create_image(0, 0, anchor="nw", image=self.bg_img)
    self.gimg = {k: mr.to_photo(glass(bg, *pills[k])) for k in ("rec", "rec_on", "act", "act_on")}
    self.gimg["tog_on"] = mr.to_photo(toggle_img(bg, 308, 518, True))
    self.gimg["tog_off"] = mr.to_photo(toggle_img(bg, 308, 518, False))
    for key, tag in (("rec", "img_rec"), ("act", "img_act")):
        cv.create_image(pills[key][0] - PAD, pills[key][1] - PAD, anchor="nw", image=self.gimg[key], tags=tag)
    cv.create_image(308 - PAD, 518 - PAD, anchor="nw", image=self.gimg["tog_on"], tags="img_tog")

    # hero card
    cv.create_text(44, 50, anchor="w", text="Macro Recorder", fill="#FFFFFF", font=F(15, True))
    cv.create_text(44, 74, anchor="w", text="Ready", fill="#E3EEDA", font=F(11), width=215, tags="status")
    cv.create_text(313, 48, text="Settings", fill="#FFFFFF", font=F(11, True))
    cx, cy, R = 200, 168, 64
    self.ring = (cx, cy, R)
    cv.create_oval(cx - R, cy - R, cx + R, cy + R, outline="#A9C98F", width=8)
    cv.create_arc(cx - R, cy - R, cx + R, cy + R, start=90, extent=-359.9, style="arc",
                  outline="#C9DDB7", width=8, tags="ring_arc")
    cv.create_oval(0, 0, 0, 0, fill="#FFFFFF", outline="", state="hidden", tags="ring_dot")
    cv.create_oval(cx - 50, cy - 50, cx + 50, cy + 50, fill="#557F4B", outline="")
    cv.create_text(cx, cy - 6, text="0", fill="#FFFFFF", font=F(32, True), tags="steps_num")
    cv.create_text(cx, cy + 24, text="steps", fill="#DCE9D1", font=F(11))
    cv.create_text(105, 262, text="Record", fill=DARK, font=F(13, True), tags="txt_rec")
    cv.create_text(295, 262, text="Play", fill="#FFFFFF", font=F(13, True), tags="txt_act")

    # cards
    cv.create_text(44, 340, anchor="w", text="Repeat", fill=MUTED, font=F(11))
    cv.create_text(44, 368, anchor="w", text="", fill=DARK, font=F(22, True), tags="v_rep")
    cv.create_text(230, 340, anchor="w", text="Speed", fill=MUTED, font=F(11))
    cv.create_text(230, 368, anchor="w", text="", fill=DARK, font=F(22, True), tags="v_spd")
    cv.create_text(44, 436, anchor="w", text="Macro", fill=MUTED, font=F(11))
    cv.create_text(44, 462, anchor="w", text="", fill=DARK, font=F(16, True), width=170, tags="name")
    cv.create_text(258, 448, text="Save", fill=DARK, font=F(12, True))
    cv.create_text(330, 448, text="Open", fill=DARK, font=F(12, True))
    cv.create_text(44, 526, anchor="w", text="Smart replay", fill=DARK, font=F(14, True))
    cv.create_text(44, 548, anchor="w", text="Finds buttons even if windows move", fill=MUTED, font=F(10))
    cv.create_text(44, 593, anchor="w", text="Method", fill=DARK, font=F(12, True))
    cv.create_text(323, 593, text="Local", fill=DARK, font=F(12, True), tags="txt_method")

    self.smart = _Toggle(self)
    self.lbl_brain = _BrainBtn(self)
    self.btn_rec = self.btn_act = None
    self.zones = [(266, 34, 360, 62, "set"), (40, 240, 170, 284, "rec"), (230, 240, 360, 284, "act"),
                  (20, 316, 194, 396, "rep"), (206, 316, 380, 396, "spd"), (226, 431, 290, 465, "save"),
                  (298, 431, 362, 465, "open"), (300, 510, 372, 558, "tog"), (282, 578, 364, 608, "method")]
    self.acts = {"set": self.settings_menu,
                 "rec": lambda: None if self.playing else self.toggle_record(),
                 "act": lambda: None if self.recording else self.toggle_play(),
                 "rep": self.cycle_repeat, "spd": self.cycle_speed, "save": self.save,
                 "open": self.open_library, "tog": lambda: self.smart.set(not self.smart.get()),
                 "method": self.cycle_brain}
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
    if self.recording:
        start, extent, col = (90 - self.anim * 10) % 360, -80, "#FFFFFF"
    elif self.playing:
        p = min(1.0, getattr(self, "idx", 0) / max(1, len(self.events)))
        start, extent, col = 90, -max(3.0, 359.9 * p), "#FFFFFF"
    else:
        self.idx = 0
        start, extent, col = 90, -359.9, "#C9DDB7"
    self.cv.itemconfigure("ring_arc", start=start, extent=extent, outline=col)
    if self.recording or self.playing:
        ang = math.radians(start + extent)
        x, y = cx + R * math.cos(ang), cy - R * math.sin(ang)
        self.cv.coords("ring_dot", x - 5, y - 5, x + 5, y + 5)
        self.cv.itemconfigure("ring_dot", state="normal")
    else:
        self.cv.itemconfigure("ring_dot", state="hidden")
    self.after(100, self._tick)


def set_status(self, color, text):
    self.cv.itemconfigure("status", text=plain(text))


def refresh_lcd(self):
    n = self.repeat_n
    self.cv.itemconfigure("v_rep", text=f"{n} time" if n == 1 else f"{n} times")
    self.cv.itemconfigure("v_spd", text=f"{self.speed_v:g}x")
    self.cv.itemconfigure("name", text="Untitled" if self.macro_name == "UNTITLED" else self.macro_name)
    self.cv.itemconfigure("steps_num", text=str(self.nsteps))


def update_count(self):
    self.nsteps = sum(1 for e in self.events if e["type"] in ("click", "key") and e["pressed"])
    self.cv.itemconfigure("steps_num", text=str(self.nsteps))


def refresh_buttons(self):
    cv, g = self.cv, self.gimg
    cv.itemconfigure("img_rec", image=g["rec_on" if self.recording else "rec"])
    cv.itemconfigure("txt_rec", text="Stop" if self.recording else "Record",
                     fill="#A9B7A0" if self.playing else DARK)
    cv.itemconfigure("img_act", image=g["act_on" if self.playing else "act"])
    cv.itemconfigure("txt_act", text="Stop" if self.playing else "Play",
                     fill=DARK if self.playing else ("#6F8A64" if self.recording else "#FFFFFF"))


def open_library(self):
    names = sorted(p.stem for p in mr.MACRO_DIR.glob("*.json"))
    win = ctk.CTkToplevel(self)
    win.title("Open macro")
    win.geometry("340x420")
    win.configure(fg_color=BG)
    win.after(100, win.lift)
    f = lambda s, b=False: (self.fn, s, "bold" if b else "normal")
    ctk.CTkLabel(win, text="Open macro", font=f(16, True), text_color=DARK).pack(pady=(18, 10))
    box = ctk.CTkScrollableFrame(win, fg_color="#FFFFFF", corner_radius=22)
    box.pack(fill="both", expand=True, padx=18, pady=(0, 18))
    if not names:
        ctk.CTkLabel(box, text="No saved macros yet.\nRecord one, then press Save.",
                     font=f(11), text_color=MUTED).pack(pady=28)
    for n in names:
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", pady=3)
        ctk.CTkButton(row, text=n, anchor="w", font=f(12), fg_color="#F3F6EF", hover_color="#E7EDDF",
                      text_color=DARK, corner_radius=14, height=34,
                      command=lambda n=n: (self.load_named(n), win.destroy())).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(row, text="Delete", width=64, height=34, font=f(11), fg_color="transparent",
                      hover_color="#F3F6EF", text_color=MUTED,
                      command=lambda n=n: (self.delete_named(n), win.destroy())).pack(side="left", padx=(6, 0))


for _fn in (_build, _zone, _tick, set_status, refresh_lcd, update_count, refresh_buttons, open_library):
    setattr(App, _fn.__name__, _fn)