"""
ui_glass.py - frosted glass interface with a day / night sky and smooth animation.
Plain words, no emoji. Loaded by run.py (one import line).
"""
import base64
import io
import math
import random
import time
import tkinter as tk
import tkinter.font as tkfont

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

import macro_recorder as mr
from macro_recorder import App, save_cfg

ctk = mr.ctk
W, HH = 400, 690
NB, NT, NA, NS = 11, 13, 7, 9            # frames: sky blend, day/night switch, button fade, smart switch
SEGS = 96                                # ring is drawn as 96 small arcs
RC, RY, RR = 200, 205, 74                # ring centre and radius
ACCENT = ("#2F9BFF", "#7B6BFF", "#FF5FA8")
TEXT = {"ink": ("#0F2747", "#FFFFFF"), "muted": ("#2B4A75", "#A9B3C9"), "top_muted": ("#E4EEFB", "#A9B3C9")}
LERP = mr.lerp
ease = lambda x: x * x * (3 - 2 * x)

SHAPES = [("disc", (100, 105, 300, 305), 100), ("pill", (216, 28, 284, 64), 18),
          ("pill", (32, 342, 192, 394), 26), ("pill", (208, 342, 368, 394), 26),
          ("card", (32, 418, 368, 658), 28), ("chip", (268, 428, 352, 456), 14),
          ("chip", (268, 476, 352, 504), 14), ("chip", (268, 524, 352, 552), 14),
          ("chip", (216, 572, 280, 600), 14), ("chip", (288, 572, 352, 600), 14)]
TINT = {0: {"disc": .26, "pill": .30, "card": .30, "chip": .45},     # day
        1: {"disc": .05, "pill": .09, "card": .07, "chip": .15}}     # night


def ramp(stops, t):
    t = min(max(t, 0), .9999) * (len(stops) - 1)
    i = int(t)
    return LERP(stops[i], stops[i + 1], t - i)


def png_photo(im):
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return tk.PhotoImage(data=base64.b64encode(buf.getvalue()))


# ---------- skies ----------
def photo_sky(name):
    """Use your own wallpaper if day.jpg / night.jpg is in the app folder."""
    try:
        return ImageOps.fit(Image.open(mr.APP_DIR / f"{name}.jpg").convert("RGB"), (W, HH), Image.Resampling.LANCZOS)
    except Exception:
        return None


def sky_day():
    im = Image.new("RGB", (W, HH))
    d = ImageDraw.Draw(im)
    for y in range(HH):
        d.line([(0, y), (W, y)], fill=ramp(("#3F78CC", "#7FB0E8", "#DCEBF9"), y / HH))
    rnd = random.Random(3)
    wisp, haze = Image.new("L", (W, HH), 0), Image.new("L", (W, HH), 0)
    wd, hd = ImageDraw.Draw(wisp), ImageDraw.Draw(haze)
    for _ in range(50):
        x, y = rnd.uniform(-40, W), HH * (.3 + .7 * rnd.random() ** .7)
        wd.line([(x, y), (x + rnd.uniform(60, 170), y - rnd.uniform(4, 40))], fill=rnd.randint(90, 200),
                width=rnd.randint(3, 9))
    for _ in range(16):
        x, y = rnd.uniform(0, W), HH * (.55 + .45 * rnd.random())
        hd.ellipse([x - 90, y - 18, x + 90, y + 18], fill=90)
    cloud = ImageChops.add(wisp.filter(ImageFilter.GaussianBlur(4)), haze.filter(ImageFilter.GaussianBlur(22)))
    return Image.composite(Image.new("RGB", (W, HH), "#FFFFFF"), im, cloud.point(lambda v: int(v * .7)))


def sky_night():
    im = Image.new("RGB", (W, HH))
    d = ImageDraw.Draw(im)
    for y in range(HH):
        d.line([(0, y), (W, y)], fill=ramp(("#03050B", "#0A0F1B", "#15171C"), y / HH))
    cl = Image.new("L", (W, HH), 0)
    cd = ImageDraw.Draw(cl)
    for box in ((-60, HH - 170, 200, HH + 30), (240, HH - 120, 480, HH + 40), (110, HH - 60, 330, HH + 60)):
        cd.ellipse(box, fill=170)
    im = Image.composite(Image.new("RGB", (W, HH), "#34312F"), im, cl.filter(ImageFilter.GaussianBlur(26)).point(lambda v: int(v * .5)))
    rnd = random.Random(8)
    st = Image.new("L", (W, HH), 0)
    sd = ImageDraw.Draw(st)
    for _ in range(190):
        x, y, r = rnd.uniform(0, W), rnd.uniform(0, HH), rnd.uniform(.6, 1.5)
        sd.ellipse([x - r, y - r, x + r, y + r], fill=rnd.randint(110, 255))
    return Image.composite(Image.new("RGB", (W, HH), "#EDEFFF"), im, st.filter(ImageFilter.GaussianBlur(.5)))


# ---------- frosted glass ----------
def frost(img, box, r, a, border, blur=9):
    """Blur what is behind the panel, tint it, add a soft sheen and a thin edge."""
    x0, y0, x1, y1 = box
    pad = blur * 3
    X0, Y0, X1, Y1 = max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(HH, y1 + pad)
    reg = img.crop((X0, Y0, X1, Y1))
    glass = Image.blend(reg.filter(ImageFilter.GaussianBlur(blur)), Image.new("RGB", reg.size, "#FFFFFF"), a)
    sheen = Image.linear_gradient("L").resize(reg.size).point(lambda v: int((255 - v) * .16))
    glass = Image.composite(Image.new("RGB", reg.size, "#FFFFFF"), glass, sheen)
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
    for role, box, r in SHAPES:
        frost(img, box, r, TINT[night][role], 80 if night else 170)
    lines = Image.new("RGBA", img.size, (255, 255, 255, 0))
    ld = ImageDraw.Draw(lines)
    for y in (466, 514, 562, 610):
        ld.line([(52, y), (348, y)], fill=(255, 255, 255, 38 if night else 70))
    img.paste(Image.alpha_composite(img.convert("RGBA"), lines).convert("RGB"))


# ---------- animated small pieces (transparent PNG frames) ----------
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
        nd.ellipse([(sx - r) * S, (sy - r) * S, (sx + r) * S, (sy + r) * S], fill="#FFFFFF")
    track = Image.blend(day, night, t).convert("RGBA")
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, 18 * S, fill=255)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([box[0], box[1] + 3 * S, box[2], box[3] + 3 * S], 18 * S, fill=(0, 0, 0, 60))
    out = Image.alpha_composite(out, shadow.filter(ImageFilter.GaussianBlur(3 * S)))
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


def pill_overlay(alpha, S=4):
    """Blue-violet pill that fades in over a button when it is active."""
    w, h = 160 * S, 52 * S
    grad = Image.new("RGB", (w, h))
    gd = ImageDraw.Draw(grad)
    for x in range(w):
        gd.line([(x, 0), (x, h)], fill=ramp(ACCENT[:2], x / w))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], 26 * S, fill=int(255 * alpha))
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    return out.resize((160, 52), Image.Resampling.LANCZOS)


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
    ImageDraw.Draw(out).ellipse([cx - r, cy - r, cx + r, cy + r], fill="#FFFFFF")
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

    day, night = photo_sky("day") or sky_day(), photo_sky("night") or sky_night()
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

    # twinkling stars (only in the gaps between the glass panels)
    rnd = random.Random(21)
    self.stars = []
    while len(self.stars) < 26:
        x, y = rnd.uniform(6, W - 6), rnd.uniform(6, HH - 6)
        if any(b[0] - 14 <= x <= b[2] + 14 and b[1] - 14 <= y <= b[3] + 14 for _, b, _ in SHAPES):
            continue
        r = rnd.uniform(.9, 1.8)
        self.stars.append((cv.create_oval(x - r, y - r, x + r, y + r, fill="#0A0E1A", outline="", state="hidden"),
                           rnd.uniform(.8, 2.2), rnd.uniform(0, 6.3)))

    # header
    cv.create_text(32, 46, anchor="w", text="Macro Recorder", fill="#FFFFFF", font=T(16, True))
    cv.create_text(32, 68, anchor="w", text="Record once. Replay anytime.", font=T(10), tags="top_muted")
    cv.create_text(250, 46, text="Settings", font=T(11), tags="ink")
    cv.create_image(292, 24, anchor="nw", tags="img_theme")

    # ring
    cv.create_oval(RC - RR, RY - RR, RC + RR, RY + RR, outline="#FFFFFF", width=1, tags="track")
    self.segcol = [ramp(ACCENT, i / SEGS) for i in range(SEGS)]
    self.segvis = [False] * SEGS
    for i in range(SEGS):
        cv.create_arc(RC - RR, RY - RR, RC + RR, RY + RR, start=90 - i * 360 / SEGS, extent=-(360 / SEGS + .6),
                      style="arc", outline=self.segcol[i], width=7, state="hidden", tags=f"s{i}")
    cv.create_arc(RC - RR, RY - RR, RC + RR, RY + RR, start=90, extent=-1, style="arc", width=7, state="hidden", tags="head")
    cv.create_text(RC, RY - 8, text="0", font=T(46), tags=("ink", "num"))
    cv.create_text(RC, RY + 32, text="steps", font=T(12), tags="muted")
    cv.create_text(RC, 322, text="Ready", font=T(12), width=330, tags=("ink", "status"))

    # record + play
    for name, x in (("rec", 32), ("act", 208)):
        cv.create_image(x, 342, anchor="nw", tags=f"ov_{name}")
    cv.create_text(112, 368, text="Record", font=T(14, True), tags="t_rec")
    cv.create_text(288, 368, text="Play", font=T(14, True), tags="t_act")

    # settings card
    for y, label, tag in ((442, "Repeat", "v_rep"), (490, "Speed", "v_spd"), (538, "Method", "txt_method")):
        cv.create_text(52, y, anchor="w", text=label, font=T(13), tags="ink")
        cv.create_text(310, y, text="", font=T(12, True), tags=("ink", tag))
    cv.create_text(52, 575, anchor="w", text="Macro", font=T(9), tags="muted")
    cv.create_text(52, 595, anchor="w", text="", font=T(14, True), tags=("ink", "name"))
    cv.create_text(248, 586, text="Save", font=T(11), tags="ink")
    cv.create_text(320, 586, text="Open", font=T(11), tags="ink")
    cv.create_text(52, 628, anchor="w", text="Smart replay", font=T(13), tags="ink")
    cv.create_text(52, 646, anchor="w", text="Finds buttons even if windows move", font=T(9), tags="muted")
    cv.create_image(292, 615, anchor="nw", tags="img_sw")

    self.smart = _Toggle()
    self.lbl_brain = _BrainBtn(self)
    self.th_val = self.th_from = self.th_to = 1.0 if self.cfg.get("theme", "night") == "night" else 0.0
    self.th_t0, self.th_dirty = 0.0, True
    self.shown, self.shown_i, self._head_p = 0.0, -1, 0.0
    self.zones = [(296, 28, 368, 64, "theme"), (216, 28, 284, 64, "set"), (32, 342, 192, 394, "rec"),
                  (208, 342, 368, 394, "act"), (32, 418, 368, 466, "rep"), (32, 466, 368, 514, "spd"),
                  (32, 514, 368, 562, "method"), (216, 572, 280, 600, "save"), (288, 572, 352, 600, "open"),
                  (292, 618, 356, 650, "tog")]
    self.acts = {"theme": self._flip_theme, "set": self.settings_menu,
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
    for tag, (a, b) in TEXT.items():
        cv.itemconfigure(tag, fill=LERP(a, b, val))
    cv.itemconfigure("track", outline=LERP("#FFFFFF", "#BCC3D2", val))
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
    # twinkling stars
    f = self.star_f
    for item, sp, ph in self.stars:
        if f <= 0:
            cv.itemconfigure(item, state="hidden")
        else:
            b = (.25 + .75 * (.5 + .5 * math.sin(now * sp + ph))) * f
            cv.itemconfigure(item, state="normal", fill=LERP("#0A0E1A", "#FFFFFF", b))
    # buttons fade between normal and active
    for name, active, busy_other, label in (("rec", self.recording, self.playing, "t_rec"),
                                            ("act", self.playing, self.recording, "t_act")):
        cur = self.lvl[name]
        cur += ((1.0 if active else 0.0) - cur) * .3
        cur = round(cur, 3) if abs(cur - active) > .01 else float(active)
        self.lvl[name] = cur
        idx = round(cur * (NA - 1))
        if idx != self._ov_i[name]:
            self._ov_i[name] = idx
            cv.itemconfigure(f"ov_{name}", image=self.ov_frames[idx])
        base = LERP(*TEXT["muted" if busy_other else "ink"], val)
        cv.itemconfigure(label, fill=LERP(base, "#FFFFFF", cur))
    # smart switch slides
    sw = self.smart
    sw.pos += ((1.0 if sw.on else 0.0) - sw.pos) * .3
    if abs(sw.pos - sw.on) < .01:
        sw.pos = float(sw.on)
    k = round(sw.pos * (NS - 1))
    if k != self._sw_i:
        self._sw_i = k
        cv.itemconfigure("img_sw", image=self.sw_frames[k])
    # step count counts up smoothly
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
    track = LERP("#FFFFFF", "#BCC3D2", self.th_val)
    want, head = {}, None
    if self.recording:
        pos, tail = (now * 1.5 % 1.0) * N, 36
        for i in range(N):
            d = (pos - i) % N
            if d < tail:
                want[i] = LERP(track, self.segcol[i], (1 - d / tail) ** 1.5)
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
    cv.itemconfigure("name", text=name if len(name) <= 14 else name[:13] + "...")


def update_count(self):
    self.nsteps = sum(1 for e in self.events if e["type"] in ("click", "key") and e["pressed"])


def refresh_buttons(self):
    self.cv.itemconfigure("t_rec", text="Stop" if self.recording else "Record")
    self.cv.itemconfigure("t_act", text="Stop" if self.playing else "Play")


def open_library(self):
    night = self.th_to > .5
    bg, card, ink, muted, edge = (("#0A0E1A", "#151B2B", "#FFFFFF", "#A9B3C9", "#2A3350") if night
                                  else ("#DCEBF9", "#FFFFFF", "#0F2747", "#2B4A75", "#B9D2EE"))
    names = sorted(p.stem for p in mr.MACRO_DIR.glob("*.json"))
    win = ctk.CTkToplevel(self)
    win.title("Open macro")
    win.geometry("340x420")
    win.configure(fg_color=bg)
    win.after(100, win.lift)
    f = lambda s, b=False: (self.fam, s, "bold" if b else "normal")
    ctk.CTkLabel(win, text="Open macro", font=f(16, True), text_color=ink).pack(pady=(18, 10))
    box = ctk.CTkScrollableFrame(win, fg_color=bg, corner_radius=0)
    box.pack(fill="both", expand=True, padx=18, pady=(0, 18))
    if not names:
        ctk.CTkLabel(box, text="No saved macros yet.\nRecord one, then press Save.",
                     font=f(11), text_color=muted).pack(pady=28)
    for n in names:
        r = ctk.CTkFrame(box, fg_color="transparent")
        r.pack(fill="x", pady=3)
        ctk.CTkButton(r, text=n, anchor="w", font=f(12), fg_color=card, hover_color=edge, text_color=ink,
                      border_width=1, border_color=edge, corner_radius=17, height=34,
                      command=lambda n=n: (self.load_named(n), win.destroy())).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(r, text="Delete", width=64, height=34, font=f(11), fg_color="transparent",
                      hover_color=edge, text_color=muted, corner_radius=17,
                      command=lambda n=n: (self.delete_named(n), win.destroy())).pack(side="left", padx=(6, 0))


for _fn in (_build, _zone, _flip_theme, _apply_theme, _tick, _ring, set_status, refresh_lcd, update_count,
            refresh_buttons, open_library):
    setattr(App, _fn.__name__, _fn)