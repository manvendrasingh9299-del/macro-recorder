"""
ui_glass.py - clean frosted interface over your own day and night photos, with smooth animation.
Plain words, no emoji. Loaded by run.py (one import line).
Photos: assets/day.jpg and assets/night.jpg next to this file.
"""
import base64
import io
import math
import random
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

import macro_recorder as mr
from macro_recorder import App, save_cfg

ctk = mr.ctk
W, HH = 400, 720
NB, NT, NA, NS = 11, 13, 7, 9            # frames: sky fade, day/night switch, button fade, smart switch
SEGS = 96                                # ring is drawn as 96 small arcs
RC, RY, RR = 200, 186, 68                # ring centre and radius
WHITE = "#FFFFFF"
ACCENT = ("#2F9BFF", "#7B6BFF", "#FF5FA8")
MUTED = ("#DCE6F5", "#A9B3C9")           # small text: day, night
LERP = mr.lerp
ease = lambda x: x * x * (3 - 2 * x)

# glass panels: box, corner radius, role
PANELS = [((28, 316, 192, 372), 28, "btn"), ((208, 316, 372, 372), 28, "btn"),
          ((28, 388, 192, 436), 24, "btn2"), ((208, 388, 372, 436), 24, "btn2"),
          ((28, 460, 372, 668), 28, "card")]
TINT = {0: ("#0B2447", {"btn": .36, "btn2": .32, "card": .48}),     # day: dark blue glass
        1: ("#FFFFFF", {"btn": .10, "btn2": .08, "card": .08})}     # night: light glass
ZONES = [("theme", (296, 26, 376, 70), None), ("set", (140, 676, 260, 716), None),
         ("rec", (28, 316, 192, 372), None), ("act", (208, 316, 372, 372), None),
         ("save", (28, 388, 192, 436), (28, 388, 164, 48, 24)), ("open", (208, 388, 372, 436), (208, 388, 164, 48, 24)),
         ("rep", (28, 460, 372, 512), (36, 464, 328, 44, 14)), ("spd", (28, 512, 372, 564), (36, 516, 328, 44, 14)),
         ("method", (28, 564, 372, 616), (36, 568, 328, 44, 14)), ("tog", (28, 616, 372, 668), None)]


def ramp(stops, t):
    t = min(max(t, 0), .9999) * (len(stops) - 1)
    i = int(t)
    return LERP(stops[i], stops[i + 1], t - i)


def png_photo(im):
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return tk.PhotoImage(data=base64.b64encode(buf.getvalue()))


def sky(name, night):
    """Your photo (assets/day.jpg or night.jpg), or a plain gradient if the file is missing."""
    here = Path(__file__).parent / "assets" / f"{name}.jpg"
    for p in (here, getattr(mr, "APP_DIR", Path(".")) / f"{name}.jpg"):
        try:
            return ImageOps.fit(Image.open(p).convert("RGB"), (W, HH), Image.Resampling.LANCZOS)
        except Exception:
            pass
    im = Image.new("RGB", (W, HH))
    stops = ("#03050B", "#0A0F1B", "#15171C") if night else ("#3F78CC", "#7FB0E8", "#DCEBF9")
    d = ImageDraw.Draw(im)
    for y in range(HH):
        d.line([(0, y), (W, y)], fill=ramp(stops, y / HH))
    return im


# ---------- frosted glass ----------
def frost(img, box, r, tint, a, border, blur=14):
    """Blur what is behind the panel, tint it, add a soft sheen and a thin edge."""
    x0, y0, x1, y1 = box
    pad = blur * 3
    X0, Y0, X1, Y1 = max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(HH, y1 + pad)
    reg = img.crop((X0, Y0, X1, Y1))
    glass = Image.blend(reg.filter(ImageFilter.GaussianBlur(blur)), Image.new("RGB", reg.size, tint), a)
    sheen = Image.linear_gradient("L").resize(reg.size).point(lambda v: int((255 - v) * .14))
    glass = Image.composite(Image.new("RGB", reg.size, WHITE), glass, sheen)
    k = 4
    big = (reg.width * k, reg.height * k)
    rect = [(x0 - X0) * k, (y0 - Y0) * k, (x1 - X0) * k, (y1 - Y0) * k]
    mask = Image.new("L", big, 0)
    ImageDraw.Draw(mask).rounded_rectangle(rect, r * k, fill=255)
    img.paste(glass, (X0, Y0), mask.resize(reg.size, Image.Resampling.LANCZOS))
    edge = Image.new("RGBA", big, (255, 255, 255, 0))
    ImageDraw.Draw(edge).rounded_rectangle(rect, r * k, outline=(255, 255, 255, border), width=k)
    cur = Image.alpha_composite(img.crop((X0, Y0, X1, Y1)).convert("RGBA"), edge.resize(reg.size, Image.Resampling.LANCZOS))
    img.paste(cur.convert("RGB"), (X0, Y0))


def bake(img, night):
    if not night:   # a light navy veil keeps white text readable on the bright sky
        img.paste(Image.blend(img, Image.new("RGB", img.size, "#0B2447"), .12))
    tint, alphas = TINT[night]
    for box, r, role in PANELS:
        frost(img, box, r, tint, alphas[role], 85 if night else 120)
    lines = Image.new("RGBA", img.size, (255, 255, 255, 0))
    ld = ImageDraw.Draw(lines)
    for y in (512, 564, 616):
        ld.line([(52, y), (348, y)], fill=(255, 255, 255, 50))
    img.paste(Image.alpha_composite(img.convert("RGBA"), lines).convert("RGB"))


# ---------- animated pieces (transparent PNG frames) ----------
def theme_frame(t, S=4):
    """The sun and moon switch."""
    w, h = 80 * S, 44 * S
    box = [4 * S, 4 * S, 76 * S, 40 * S]
    day, night = Image.new("RGB", (w, h)), Image.new("RGB", (w, h))
    for im, (c0, c1) in ((day, ("#4F9CEB", "#BFE1F8")), (night, ("#10172B", "#2A3149"))):
        d = ImageDraw.Draw(im)
        for y in range(h):
            d.line([(0, y), (w, y)], fill=LERP(c0, c1, y / h))
    dd, nd = ImageDraw.Draw(day), ImageDraw.Draw(night)
    for cx, cy, r in ((52, 36, 9), (62, 33, 10), (44, 38, 8), (70, 38, 8)):
        dd.ellipse([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], fill="#F4FAFF")
    for sx, sy, r in ((18, 14, 1.4), (30, 25, 1), (24, 32, 1.2), (40, 12, 1)):
        nd.ellipse([(sx - r) * S, (sy - r) * S, (sx + r) * S, (sy + r) * S], fill=WHITE)
    track = Image.blend(day, night, t).convert("RGBA")
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, 18 * S, fill=255)
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([box[0], box[1] + 3 * S, box[2], box[3] + 3 * S], 18 * S, fill=(0, 0, 0, 60))
    out = Image.alpha_composite(Image.new("RGBA", (w, h), (0, 0, 0, 0)), shadow.filter(ImageFilter.GaussianBlur(3 * S)))
    out.paste(track, (0, 0), mask)
    cx, cy, r = (4 + 3 + 15 + t * 36) * S, 22 * S, 15 * S
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([cx - r, cy - r + 2 * S, cx + r, cy + r + 2 * S], fill=(0, 0, 0, 90))
    out = Image.alpha_composite(out, sh.filter(ImageFilter.GaussianBlur(2 * S)))
    sun, moon = Image.new("RGBA", (w, h), (0, 0, 0, 0)), Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(sun).ellipse([cx - r, cy - r, cx + r, cy + r], fill="#FFD233", outline="#FFE680", width=S)
    md = ImageDraw.Draw(moon)
    md.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#D5D8DF", outline="#EEF0F4", width=S)
    for ox, oy, cr in ((-5, -4, 4), (5, 3, 3.2), (-2, 7, 2.4)):
        md.ellipse([cx + (ox - cr) * S, cy + (oy - cr) * S, cx + (ox + cr) * S, cy + (oy + cr) * S], fill="#AEB5C4")
    out = Image.alpha_composite(out, Image.blend(sun, moon, t))
    edge = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    ImageDraw.Draw(edge).rounded_rectangle(box, 18 * S, outline=(255, 255, 255, 150), width=S)
    return Image.alpha_composite(out, edge).resize((80, 44), Image.Resampling.LANCZOS)


def pill_overlay(alpha, w=164, h=56, S=4):
    """Blue-violet pill that fades in over Record / Play when active."""
    grad = Image.new("RGB", (w * S, h * S))
    gd = ImageDraw.Draw(grad)
    for x in range(w * S):
        gd.line([(x, 0), (x, h * S)], fill=ramp(ACCENT[:2], x / (w * S)))
    mask = Image.new("L", (w * S, h * S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w * S - 1, h * S - 1], h * S // 2, fill=int(255 * alpha))
    out = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    return out.resize((w, h), Image.Resampling.LANCZOS)


def flash_frames(w, h, r, S=4):
    """A soft white glow that fades out after a tap."""
    frames = []
    for a in (.30, .24, .17, .10, .05):
        m = Image.new("RGBA", (w * S, h * S), (255, 255, 255, 0))
        ImageDraw.Draw(m).rounded_rectangle([0, 0, w * S - 1, h * S - 1], r * S, fill=(255, 255, 255, int(255 * a)))
        frames.append(png_photo(m.resize((w, h), Image.Resampling.LANCZOS)))
    return frames


def switch_frame(t, S=4):
    """The Smart replay switch."""
    w, h = 64 * S, 38 * S
    box = [4 * S, 4 * S, 60 * S, 34 * S]
    off, on = (255, 255, 255, 70), (61, 139, 255, 255)
    col = tuple(round(a + (b - a) * t) for a, b in zip(off, on))
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(out).rounded_rectangle(box, 15 * S, fill=col, outline=(255, 255, 255, 140), width=S)
    cx, cy, r = (4 + 3 + 12 + t * 26) * S, 19 * S, 12 * S
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([cx - r, cy - r + 2 * S, cx + r, cy + r + 2 * S], fill=(0, 0, 0, 80))
    out = Image.alpha_composite(out, sh.filter(ImageFilter.GaussianBlur(2 * S)))
    ImageDraw.Draw(out).ellipse([cx - r, cy - r, cx + r, cy + r], fill=WHITE)
    return out.resize((64, 38), Image.Resampling.LANCZOS)


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
    """Stands in for the old switch: .get() / .select() / .deselect(). Slides smoothly."""
    def __init__(self):
        self.on, self.pos = True, 1.0

    def get(self):
        return self.on

    def set(self, v):
        self.on = bool(v)

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
    self.fam = fam = next((f for f in ("Helvetica Neue", "Avenir Next", "Helvetica") if f in fams), "Helvetica")
    T = lambda size, bold=False: (fam, size, "bold" if bold else "normal")
    self.title("Macro Recorder")
    self.geometry(f"{W}x{HH}")
    self.configure(fg_color="#0A0E1A")
    cv = self.cv = tk.Canvas(self, width=W, height=HH, bg="#0A0E1A", highlightthickness=0, bd=0)
    cv.place(x=0, y=0)

    day, night = sky("day", False), sky("night", True)
    bake(day, 0)
    bake(night, 1)
    self.bg_raw = [Image.blend(day, night, i / (NB - 1)).tobytes() for i in range(NB)]
    self.th_frames = [png_photo(theme_frame(i / (NT - 1))) for i in range(NT)]
    self.ov_frames = [png_photo(pill_overlay(i / (NA - 1))) for i in range(NA)]
    self.sw_frames = [png_photo(switch_frame(i / (NS - 1))) for i in range(NS)]
    self.bg_item = cv.create_image(0, 0, anchor="nw")
    self._bg_i = self._th_i = self._sw_i = None
    self._ov_i = {"rec": -1, "act": -1}
    self.lvl = {"rec": 0.0, "act": 0.0}
    self._flash_sets, self._fl = {}, None

    # a few twinkling stars, only where there is open sky
    rnd = random.Random(21)
    self.stars = []
    while len(self.stars) < 18:
        x, y = rnd.uniform(6, W - 6), rnd.uniform(6, HH - 6)
        if any(b[0] - 14 <= x <= b[2] + 14 and b[1] - 14 <= y <= b[3] + 14 for b, _, _ in PANELS) \
                or math.hypot(x - RC, y - RY) < RR + 26 or y < 80:
            continue
        r = rnd.uniform(.9, 1.7)
        self.stars.append((cv.create_oval(x - r, y - r, x + r, y + r, fill="#0A0E1A", outline="", state="hidden"),
                           rnd.uniform(.8, 2.2), rnd.uniform(0, 6.3)))

    # header
    cv.create_text(28, 48, anchor="w", text="Macro Recorder", fill=WHITE, font=T(20, True))
    cv.create_text(28, 72, anchor="w", text="Untitled", font=T(12), tags=("muted", "name"))
    cv.create_image(296, 26, anchor="nw", tags="img_theme")

    # ring, step count, status
    cv.create_oval(RC - RR, RY - RR, RC + RR, RY + RR, outline="#E6EAF2", width=1)
    self.segcol = [ramp(ACCENT, i / SEGS) for i in range(SEGS)]
    self.segvis = [False] * SEGS
    for i in range(SEGS):
        cv.create_arc(RC - RR, RY - RR, RC + RR, RY + RR, start=90 - i * 360 / SEGS, extent=-(360 / SEGS + .6),
                      style="arc", outline=self.segcol[i], width=7, state="hidden", tags=f"s{i}")
    cv.create_arc(RC - RR, RY - RR, RC + RR, RY + RR, start=90, extent=-1, style="arc", width=7, state="hidden", tags="head")
    cv.create_text(RC, RY - 8, text="0", fill=WHITE, font=T(54), tags="num")
    cv.create_text(RC, RY + 38, text="steps", font=T(13), tags="muted")
    cv.create_text(RC, 284, text="Ready", fill=WHITE, font=T(13), width=340, tags="status")

    # buttons
    for name, x in (("rec", 28), ("act", 208)):
        cv.create_image(x, 316, anchor="nw", tags=f"ov_{name}")
    cv.create_text(110, 344, text="Record", fill=WHITE, font=T(16, True), tags="t_rec")
    cv.create_text(290, 344, text="Play", fill=WHITE, font=T(16, True), tags="t_act")
    cv.create_text(110, 412, text="Save", fill=WHITE, font=T(15))
    cv.create_text(290, 412, text="Open", fill=WHITE, font=T(15))

    # settings card: label left, value right, same edges
    for y, label, tag in ((486, "Repeat", "v_rep"), (538, "Speed", "v_spd"), (590, "Method", "txt_method")):
        cv.create_text(52, y, anchor="w", text=label, fill=WHITE, font=T(15))
        cv.create_text(348, y, anchor="e", text="", fill=WHITE, font=T(15, True), tags=tag)
    cv.create_text(52, 642, anchor="w", text="Smart replay", fill=WHITE, font=T(15))
    cv.create_image(288, 623, anchor="nw", tags="img_sw")
    cv.create_text(200, 696, text="Settings", font=T(13), tags="muted")
    cv.create_image(0, 0, anchor="nw", state="hidden", tags="flash")

    self.smart = _Toggle()
    self.lbl_brain = _BrainBtn(self)
    self.th_val = self.th_from = self.th_to = 1.0 if self.cfg.get("theme", "night") == "night" else 0.0
    self.th_t0, self.th_dirty = 0.0, True
    self.shown, self.shown_i, self._head_p = 0.0, -1, 0.0
    self.acts = {"theme": self._flip_theme, "set": self.settings_menu,
                 "rec": lambda: None if self.playing else self.toggle_record(),
                 "act": lambda: None if self.recording else self.toggle_play(),
                 "rep": self.cycle_repeat, "spd": self.cycle_speed, "method": self.cycle_brain,
                 "save": self.save, "open": self.open_library,
                 "tog": lambda: self.smart.set(not self.smart.get())}
    cv.bind("<Motion>", lambda e: cv.config(cursor="pointinghand" if self._zone(e.x, e.y) else ""))
    cv.bind("<Button-1>", self._click)


def _zone(self, x, y):
    for key, (x0, y0, x1, y1), flash in ZONES:
        if x0 <= x <= x1 and y0 <= y <= y1:
            return key, flash
    return None


def _click(self, e):
    hit = self._zone(e.x, e.y)
    if not hit:
        return
    key, flash = hit
    if flash:
        x, y, w, h, r = flash
        if (w, h, r) not in self._flash_sets:
            self._flash_sets[(w, h, r)] = flash_frames(w, h, r)
        self._fl = [self._flash_sets[(w, h, r)], 0]
        self.cv.coords("flash", x, y)
        self.cv.itemconfigure("flash", image=self._fl[0][0], state="normal")
    self.acts[key]()


def _flip_theme(self):
    self.th_from, self.th_to = self.th_val, 1.0 - round(self.th_to)
    self.th_t0 = time.perf_counter()
    self.cfg["theme"] = "night" if self.th_to > .5 else "day"
    save_cfg(self.cfg)


def _apply_theme(self, val):
    cv = self.cv
    i = round(val * (NB - 1))
    if i != self._bg_i:
        self._bg_i = i
        self._bg_photo = tk.PhotoImage(data=b"P6 %d %d 255\n" % (W, HH) + self.bg_raw[i], format="PPM")
        cv.itemconfigure(self.bg_item, image=self._bg_photo)
    j = round(val * (NT - 1))
    if j != self._th_i:
        self._th_i = j
        cv.itemconfigure("img_theme", image=self.th_frames[j])
    cv.itemconfigure("muted", fill=LERP(MUTED[0], MUTED[1], val))
    self.star_f = max(0.0, (val - .55) / .45)


def _tick(self):
    now = time.perf_counter()
    self.anim += 1
    cv = self.cv
    x = min(1.0, (now - self.th_t0) / .5)
    val = self.th_from + (self.th_to - self.th_from) * ease(x)
    if self.th_dirty or abs(val - self.th_val) > 1e-4:
        self.th_val, self.th_dirty = val, False
        self._apply_theme(val)
    f = self.star_f
    for item, sp, ph in self.stars:
        if f <= 0:
            cv.itemconfigure(item, state="hidden")
        else:
            b = (.25 + .75 * (.5 + .5 * math.sin(now * sp + ph))) * f
            cv.itemconfigure(item, state="normal", fill=LERP("#0A0E1A", WHITE, b))
    for name, active, label in (("rec", self.recording, "t_rec"), ("act", self.playing, "t_act")):
        cur = self.lvl[name]
        cur += ((1.0 if active else 0.0) - cur) * .3
        cur = round(cur, 3) if abs(cur - active) > .01 else float(active)
        self.lvl[name] = cur
        idx = round(cur * (NA - 1))
        if idx != self._ov_i[name]:
            self._ov_i[name] = idx
            cv.itemconfigure(f"ov_{name}", image=self.ov_frames[idx])
    busy = {"t_rec": self.playing, "t_act": self.recording}
    for label, dim in busy.items():
        cv.itemconfigure(label, fill=LERP(WHITE, "#7F8AA3", 1.0 if dim else 0.0))
    sw = self.smart
    sw.pos += ((1.0 if sw.on else 0.0) - sw.pos) * .3
    if abs(sw.pos - sw.on) < .01:
        sw.pos = float(sw.on)
    k = round(sw.pos * (NS - 1))
    if k != self._sw_i:
        self._sw_i = k
        cv.itemconfigure("img_sw", image=self.sw_frames[k])
    if self._fl:
        self._fl[1] += 1
        if self._fl[1] >= len(self._fl[0]):
            cv.itemconfigure("flash", state="hidden")
            self._fl = None
        else:
            cv.itemconfigure("flash", image=self._fl[0][self._fl[1]])
    self.shown += (self.nsteps - self.shown) * .25
    if abs(self.shown - self.nsteps) < .5:
        self.shown = float(self.nsteps)
    if round(self.shown) != self.shown_i:
        self.shown_i = round(self.shown)
        cv.itemconfigure("num", text=str(self.shown_i))
    self._ring(now)
    self.after(33, self._tick)


def _ring(self, now):
    cv, N = self.cv, SEGS
    want, head = {}, None
    if self.recording:
        pos, tail = (now * 1.5 % 1.0) * N, 36
        for i in range(N):
            d = (pos - i) % N
            if d < tail:
                want[i] = LERP("#E6EAF2", self.segcol[i], (1 - d / tail) ** 1.5)
    elif self.playing:
        self._head_p += (min(1.0, getattr(self, "idx", 0) / max(1, len(self.events))) - self._head_p) * .15
        full, frac = divmod(self._head_p * N, 1.0)
        for i in range(int(full)):
            want[i] = self.segcol[i]
        head = (int(full) % N, frac)
    else:
        self.idx = 0
        self._head_p = 0.0
    for i in range(N):
        col = want.get(i)
        if col is None:
            if self.segvis[i]:
                cv.itemconfigure(f"s{i}", state="hidden")
                self.segvis[i] = False
        else:
            cv.itemconfigure(f"s{i}", state="normal", outline=col)
            self.segvis[i] = True
    if head and head[1] > .02:
        cv.itemconfigure("head", state="normal", start=90 - head[0] * 360 / N, extent=-head[1] * 360 / N,
                         outline=self.segcol[min(head[0], N - 1)])
    else:
        cv.itemconfigure("head", state="hidden")


def set_status(self, color, text):
    self.cv.itemconfigure("status", text=plain(text))


def refresh_lcd(self):
    n, cv = self.repeat_n, self.cv
    cv.itemconfigure("v_rep", text=f"{n} time" if n == 1 else f"{n} times")
    cv.itemconfigure("v_spd", text=f"{self.speed_v:g}x")
    name = "Untitled" if self.macro_name == "UNTITLED" else self.macro_name
    cv.itemconfigure("name", text=name if len(name) <= 24 else name[:23] + "...")


def update_count(self):
    self.nsteps = sum(1 for e in self.events if e["type"] in ("click", "key") and e["pressed"])


def refresh_buttons(self):
    self.cv.itemconfigure("t_rec", text="Stop" if self.recording else "Record")
    self.cv.itemconfigure("t_act", text="Stop" if self.playing else "Play")


def open_library(self):
    night = self.th_to > .5
    bg, card, ink, muted, edge = (("#0A0E1A", "#151B2B", "#FFFFFF", "#A9B3C9", "#2A3350") if night
                                  else ("#1F4E8F", "#2B63AE", "#FFFFFF", "#DCE6F5", "#5C8BC8"))
    names = sorted(p.stem for p in mr.MACRO_DIR.glob("*.json"))
    win = ctk.CTkToplevel(self)
    win.title("Open macro")
    win.geometry("340x420")
    win.configure(fg_color=bg)
    win.after(100, win.lift)
    f = lambda s, b=False: (self.fam, s, "bold" if b else "normal")
    ctk.CTkLabel(win, text="Open macro", font=f(18, True), text_color=ink).pack(pady=(18, 10))
    box = ctk.CTkScrollableFrame(win, fg_color=bg, corner_radius=0)
    box.pack(fill="both", expand=True, padx=18, pady=(0, 18))
    if not names:
        ctk.CTkLabel(box, text="No saved macros yet.\nRecord one, then press Save.",
                     font=f(12), text_color=muted).pack(pady=28)
    for n in names:
        r = ctk.CTkFrame(box, fg_color="transparent")
        r.pack(fill="x", pady=4)
        ctk.CTkButton(r, text=n, anchor="w", font=f(14), fg_color=card, hover_color=edge, text_color=ink,
                      corner_radius=18, height=40,
                      command=lambda n=n: (self.load_named(n), win.destroy())).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(r, text="Delete", width=70, height=40, font=f(12), fg_color="transparent",
                      hover_color=edge, text_color=muted, corner_radius=18,
                      command=lambda n=n: (self.delete_named(n), win.destroy())).pack(side="left", padx=(6, 0))


for _fn in (_build, _zone, _click, _flip_theme, _apply_theme, _tick, _ring, set_status, refresh_lcd,
            update_count, refresh_buttons, open_library):
    setattr(App, _fn.__name__, _fn)