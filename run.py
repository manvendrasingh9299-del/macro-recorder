"""
run.py - launcher for Macro Recorder. Loads macro_recorder.py (the base app) and applies the
latest fixes and features on top.  Start the app with:   python run.py
"""
import base64, datetime, json, math, os, random, shutil, subprocess, threading, time
import tkinter as tk
import urllib.request
from collections import deque
from tkinter import messagebox

import cv2
import numpy as np
from AppKit import NSWorkspace
from PIL import Image, ImageDraw, ImageFilter, ImageGrab
from pynput import keyboard, mouse
from Quartz import (CGDataProviderCopyData, CGDisplayCreateImage, CGEventCreateMouseEvent, CGEventPost,
                    CGEventSetIntegerValueField, CGEventSourceCreate, CGImageGetBytesPerRow,
                    CGImageGetDataProvider, CGImageGetHeight, CGImageGetWidth, CGMainDisplayID,
                    kCGEventMouseMoved, kCGEventSourceStateHIDSystemState, kCGHIDEventTap,
                    kCGMouseEventClickState)

import macro_recorder as mr
from macro_recorder import (ACCENT, BTN, COUNTDOWN, CROP_PT, GREEN, GREY, OLLAMA_DEFAULT, RED, App, b64,
                            data_to_key, kb_ctl, mouse_ctl, save_cfg)

ctk = mr.ctk
mr.MATCH_MIN = 0.72   # a bit forgiving: hover highlights change how buttons look
WAIT_S = 5.0          # seconds to keep looking for a target before giving up


# =====================================================================================
# Screen + Ollama helpers
# =====================================================================================
def grab_screen():
    """Fast screenshot (about 40 ms)."""
    try:
        img = CGDisplayCreateImage(CGMainDisplayID())
        w, h, bpr = CGImageGetWidth(img), CGImageGetHeight(img), CGImageGetBytesPerRow(img)
        buf = np.frombuffer(CGDataProviderCopyData(CGImageGetDataProvider(img)), np.uint8)
        return Image.fromarray(buf.reshape(h, bpr // 4, 4)[:, :w, 2::-1].copy())
    except Exception:
        return ImageGrab.grab().convert("RGB")


def ollama_up():
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1).read()
        return True
    except Exception:
        return False


def ensure_ollama(model):
    """Starts the Ollama server if needed and loads the model. Returns '' or a problem message."""
    if not ollama_up():
        exe = shutil.which("ollama") or next(
            (p for p in ("/opt/homebrew/bin/ollama", "/usr/local/bin/ollama") if os.path.exists(p)), None)
        if exe:
            subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        else:
            subprocess.run(["open", "-a", "Ollama"])
        for _ in range(30):
            if ollama_up():
                break
            time.sleep(0.5)
        else:
            return "Ollama not found. Using LOCAL"
    try:  # load the model now so the first click is fast
        body = json.dumps({"model": model, "keep_alive": "30m"}).encode()
        urllib.request.urlopen(urllib.request.Request(
            "http://localhost:11434/api/generate", body, {"content-type": "application/json"}), timeout=90).read()
    except Exception:
        return f"Run: ollama pull {model}"
    return ""


# =====================================================================================
# Reliable clicks (sent through macOS directly, with a gentle pointer glide)
# =====================================================================================
_SRC = CGEventSourceCreate(kCGEventSourceStateHIDSystemState)


def _send(kind, x, y, btn=0, n=1):
    e = CGEventCreateMouseEvent(_SRC, kind, (x, y), btn)
    CGEventSetIntegerValueField(e, kCGMouseEventClickState, n)
    CGEventPost(kCGHIDEventTap, e)


def glide_to(x, y, fast=False):
    """Move in small steps, then pause, so the Dock and menus notice the pointer."""
    sx, sy = mouse_ctl.position
    steps = 3 if fast else 6
    for i in range(1, steps + 1):
        _send(kCGEventMouseMoved, sx + (x - sx) * i / steps, sy + (y - sy) * i / steps)
        time.sleep(0.015)
    _send(kCGEventMouseMoved, x, y)
    time.sleep(0.12 if fast else 0.25)


# =====================================================================================
# Recording (saves each click picture from just BEFORE the click; supports double-clicks)
# =====================================================================================
def _begin_record(self):
    if not self.recording:
        return
    self.frames = deque(maxlen=4)
    self.t0, self.capturing = time.time(), True
    threading.Thread(target=self._watch, daemon=True).start()
    self.ui(self.set_status, RED, "Recording")
    self.mouse_listener = mouse.Listener(on_click=self.on_click, on_scroll=self.on_scroll)
    self.mouse_listener.start()


def _watch(self):
    while self.capturing:
        self.frames.append((time.time(), grab_screen()))
        time.sleep(0.15)


def grab_crop(self, x, y, when):
    try:
        frames = list(self.frames)
        old = [f for f in frames if f[0] <= when - 0.1]
        shot = (old[-1] if old else frames[0] if frames else (0, grab_screen()))[1]
        s = shot.width / self.sw
        half = int(CROP_PT * s / 2)
        cx, cy = int(x * s), int(y * s)
        left, top = max(cx - half, 0), max(cy - half, 0)
        c = shot.crop((left, top, cx + half, cy + half))
        return {"crop": b64(c), "ox": cx - left, "oy": cy - top, "s": s}
    except Exception:
        return {}


def on_click(self, x, y, button, pressed):
    if not self.capturing:
        return
    try:
        now = time.time()
        if not self.events:
            self.rec_last, self.cur_n = (0.0, (0, 0), 0), 1
        lt, lp, ln = getattr(self, "rec_last", (0.0, (0, 0), 0))
        ev = {"type": "click", "x": x, "y": y, "button": button.name, "pressed": pressed,
              "t": round(now - self.t0, 3)}
        if pressed:
            near = abs(x - lp[0]) < 8 and abs(y - lp[1]) < 8
            n = ln + 1 if now - lt < 0.5 and near else 1
            self.rec_last, self.cur_n = (now, (x, y), n), n
            if n == 1:  # repeat clicks reuse the first click's target
                ev.update(self.grab_crop(x, y, now))
        ev["n"] = getattr(self, "cur_n", 1)
        self.events.append(ev)
        self.ui(self.update_count)
    except Exception as exc:
        print("Record error:", exc)


# =====================================================================================
# Finding targets + playback (learn once, then run fast)
# =====================================================================================
def fast_delay(ev, gap):
    """How long the fast version waits before this step."""
    if ev["type"] == "click":
        if ev["pressed"] and ev.get("n", 1) == 1:
            return 0.12        # the click then waits for its target to appear
        return min(gap, 0.06)
    if ev["type"] == "key":
        return min(gap, 0.04) if gap < 0.3 else min(gap, 1.0)
    return min(gap, 0.1)       # scroll


def get_tpl(self, ev, shot_w):
    cache = self.__dict__.setdefault("tpl_cache", {})
    key = (hash(ev["crop"]), "s" in ev, shot_w)
    t = cache.get(key)
    if t is None:
        t = cv2.imdecode(np.frombuffer(base64.b64decode(ev["crop"]), np.uint8), cv2.IMREAD_GRAYSCALE)
        if "s" not in ev:
            k = shot_w / self.sent_w
            t = cv2.resize(t, None, fx=k, fy=k)
        cache[key] = t
    return t


def match_fast(self, ev, shot):
    """Look only near where the target was last found. Much quicker than the whole screen."""
    tpl = self.get_tpl(ev, shot.width)
    th, tw = tpl.shape[:2]
    s = shot.width / self.sw
    ox, oy = ev.get("ox", tw / 2), ev.get("oy", th / 2)
    fx, fy = ev.get("fx", ev["x"]), ev.get("fy", ev["y"])
    pad = int(260 * s)
    tlx, tly = int(fx * s - ox), int(fy * s - oy)
    x0, y0 = max(tlx - pad, 0), max(tly - pad, 0)
    x1, y1 = min(tlx + tw + pad, shot.width), min(tly + th + pad, shot.height)
    if x1 - x0 < tw or y1 - y0 < th:
        return None
    reg = cv2.cvtColor(np.array(shot.crop((x0, y0, x1, y1))), cv2.COLOR_RGB2GRAY)
    _, score, _, loc = cv2.minMaxLoc(cv2.matchTemplate(reg, tpl, cv2.TM_CCOEFF_NORMED))
    if score < mr.MATCH_MIN:
        return None
    return (x0 + loc[0] + ox) / s, (y0 + loc[1] + oy) / s


def find(self, ev):
    fast = "fd" in ev
    end, tries = time.time() + WAIT_S, 0
    while time.time() < end and not self.abort.is_set():
        try:
            shot = grab_screen()
            hit = (self.match_fast(ev, shot) if fast else None) or self.match_local(ev, shot)
            if hit:
                return hit
            if self.brain in ("claude", "ollama", "plugin") and tries < 2:
                tries += 1
                hit = self.model_find(ev, shot, shot.width / self.sw)
                if hit:
                    return hit
        except Exception as exc:
            print("Find error:", exc)
        if not self._sleep(0.15 if fast else 0.5):
            return None
    return None


def _play(self, repeat, speed):
    fast_macro = bool(self.events) and "fd" in self.events[0]
    self.learned = {}
    if self.brain == "ollama":
        self.ui(self.set_status, ACCENT, "Starting Ollama")
        problem = ensure_ollama(self.cfg.get("ollama_model", OLLAMA_DEFAULT))
        if problem:
            self.ui(self.set_status, ACCENT, problem)
    if not self._sleep(1 if fast_macro else COUNTDOWN):
        return self._stopped()
    for n in range(repeat):
        self.ui(self.set_status, GREEN, f"Playing {n + 1} of {repeat}" + (" FAST" if fast_macro else ""))
        prev = 0.0
        for i, ev in enumerate(self.events):
            gap = ev["fd"] if "fd" in ev else ev["t"] - prev
            if not self._sleep(gap / speed):
                return self._stopped()
            prev = ev["t"]
            self.idx = i
            self._do(ev)
        if n < repeat - 1 and not self._sleep(0.3 if fast_macro else 1):
            return self._stopped()
    self.ui(self._end, "Finished")
    if not fast_macro and self.learned and self.brain != "exact":
        self.ui(self.ask_fast)


def _do(self, ev):
    try:
        if ev["type"] == "click":
            n, fast = ev.get("n", 1), "fd" in ev
            if ev["pressed"] and n == 1:
                self.cur = (ev.get("fx", ev["x"]), ev.get("fy", ev["y"]))
                if self.brain != "exact" and ev.get("crop"):
                    self.ui(self.set_status, ACCENT, "Finding target")
                    hit = self.find(ev)
                    print(f"[find] saved=({self.cur[0]:.0f},{self.cur[1]:.0f}) found={hit}")
                    if hit:
                        self.cur = hit
                        self.learned[self.idx] = hit
                    elif self.abort.is_set():
                        return
                    elif self.strict_var.get():
                        self.fail = "Target not found. Stopped"
                        self.abort.set()
                        return
                    else:
                        self.ui(self.set_status, ACCENT, "Not found, using saved spot")
                glide_to(*self.cur, fast=fast)
            down, up, btn = BTN.get(ev["button"], BTN["left"])
            if not ev["pressed"]:
                time.sleep(0.05)  # hold the button long enough to count as a click
            _send(down if ev["pressed"] else up, self.cur[0], self.cur[1], btn, n)
            print(f"[click x{n}] {ev['button']} {'down' if ev['pressed'] else 'up'} at ({self.cur[0]:.0f}, {self.cur[1]:.0f})")
        elif ev["type"] == "scroll":
            glide_to(ev["x"], ev["y"], fast="fd" in ev)
            mouse_ctl.scroll(ev["dx"], ev["dy"])
        elif ev["type"] == "key":
            (kb_ctl.press if ev["pressed"] else kb_ctl.release)(data_to_key(ev["key"]))
    except Exception as exc:
        print("Action failed:", exc)


def ask_fast(self):
    if messagebox.askyesno(
            "Was it right?",
            "Did the macro do the task correctly?\n\n"
            "YES  = save a FAST version (next runs skip the waiting)\n"
            "NO   = keep the macro as it is",
            parent=self):
        self.make_fast()


def make_fast(self):
    prev = 0.0
    for i, ev in enumerate(self.events):
        gap = max(0.0, ev["t"] - prev)
        prev = ev["t"]
        if i in self.learned:
            ev["fx"], ev["fy"] = self.learned[i]
        ev["fd"] = fast_delay(ev, gap)
    path = mr.MACRO_DIR / f"{self.macro_name}.json"
    if path.exists():
        path.write_text(json.dumps(self.events))
        self.set_status(GREY, "Saved as FAST macro")
    else:
        self.set_status(GREY, "Name it to keep the FAST macro")
        self.save()


# =====================================================================================
# Learn from my day (optional training data)
# =====================================================================================
LEARN_DIR = mr.APP_DIR / "learn"
LEARN_CAP_GB = 3.0
SKIP_APPS = ("1password", "bitwarden", "keychain", "passwords", "lastpass", "dashlane",
             "python", "macro recorder")


def front_app():
    try:
        return NSWorkspace.sharedWorkspace().frontmostApplication().localizedName() or ""
    except Exception:
        return ""


def learn_stats():
    n, size = 0, 0
    if LEARN_DIR.exists():
        for f in LEARN_DIR.rglob("*"):
            if f.is_file():
                size += f.stat().st_size
                if f.name == "data.jsonl":
                    n += sum(1 for _ in open(f))
    return n, size / 1e9


def learn_on(self):
    if getattr(self, "learning", False):
        return
    LEARN_DIR.mkdir(parents=True, exist_ok=True)
    self.learning, self.l_paused, self.l_move, self.l_saved = True, False, 0.0, 0
    self.l_frames, self.l_last = deque(maxlen=3), (0.0, (0, 0), 1)
    threading.Thread(target=self._learn_watch, daemon=True).start()
    self.l_mouse = mouse.Listener(on_click=self._learn_click, on_move=self._learn_moved)
    self.l_mouse.start()
    self.l_keys = keyboard.Listener(on_press=self._learn_key)
    self.l_keys.start()
    self.title("Macro Recorder  ● LEARNING")
    self.set_status(GREY, "Learning on. Fn+F7 pauses")


def learn_off(self):
    self.learning = False
    for lst in (getattr(self, "l_mouse", None), getattr(self, "l_keys", None)):
        if lst:
            lst.stop()
    self.title("Macro Recorder")
    self.set_status(GREY, "Learning off")


def _learn_key(self, key):
    if key == keyboard.Key.f7:  # Fn+F7 on a MacBook
        self.l_paused = not self.l_paused
        self.ui(self.title, "Macro Recorder  ● LEARNING" + ("  (paused)" if self.l_paused else ""))
        self.ui(self.set_status, GREY, "Learning paused" if self.l_paused else "Learning resumed")


def _learn_moved(self, x, y):
    self.l_move = time.time()


def _learn_watch(self):
    """Keep the last few screenshots, but only while you are actually using the mouse."""
    while self.learning:
        if not self.l_paused and not self.playing and time.time() - self.l_move < 3:
            try:
                self.l_frames.append((time.time(), grab_screen()))
            except Exception:
                pass
        time.sleep(0.3)


def _learn_click(self, x, y, button, pressed):
    if not pressed or self.l_paused or self.playing:
        return
    now = time.time()
    app = front_app()
    if any(s in app.lower() for s in SKIP_APPS):
        return
    lt, lp, ln = self.l_last
    near = abs(x - lp[0]) < 8 and abs(y - lp[1]) < 8
    n = ln + 1 if now - lt < 0.5 and near else 1
    self.l_last = (now, (x, y), n)
    old = [f for f in self.l_frames if f[0] <= now - 0.08]
    before = old[-1][1] if old and now - old[-1][0] < 2 else None
    threading.Thread(target=self._learn_save, args=(now, x, y, button.name, n, app, before),
                     daemon=True).start()


def _learn_save(self, t, x, y, btn, n, app, before):
    try:
        day = LEARN_DIR / datetime.date.today().isoformat()
        day.mkdir(parents=True, exist_ok=True)
        sid = str(int(t * 1000))
        shot = before or grab_screen()
        time.sleep(0.8)  # let the screen react, then save what the click did
        after = grab_screen()
        shot.resize((1024, round(shot.height * 1024 / shot.width))).save(day / f"{sid}.jpg", quality=70)
        after.resize((512, round(after.height * 512 / after.width))).save(day / f"{sid}-after.jpg", quality=60)
        s = shot.width / self.sw
        half = int(CROP_PT * s / 2)
        cx, cy = int(x * s), int(y * s)
        shot.crop((max(cx - half, 0), max(cy - half, 0), cx + half, cy + half)).save(day / f"{sid}-crop.png")
        row = {"id": sid, "time": datetime.datetime.fromtimestamp(t).isoformat(timespec="seconds"),
               "app": app, "screen": [self.sw, self.sh], "click": [round(x, 1), round(y, 1)],
               "norm": [round(x / self.sw, 4), round(y / self.sh, 4)], "button": btn, "n": n,
               "image": f"{sid}.jpg", "crop": f"{sid}-crop.png", "after": f"{sid}-after.jpg"}
        with open(day / "data.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")
        self.l_saved += 1
        if self.l_saved % 50 == 0 and learn_stats()[1] > LEARN_CAP_GB:
            days = sorted(p for p in LEARN_DIR.iterdir() if p.is_dir())
            if len(days) > 1:
                shutil.rmtree(days[0])
    except Exception as exc:
        print("Learn error:", exc)


def toggle_learn(self):
    if self.learn_var.get():
        if not self.cfg.get("learn_ok"):
            ok = messagebox.askokcancel(
                "Learn from my day",
                "While this is on, the app saves a screenshot, a small picture of what you click, "
                "and the click position, on THIS Mac only.\n\n"
                "It does NOT save what you type, and it skips password managers.\n"
                "Screenshots can still show private content. Press Fn+F7 to pause any time.\n\n"
                "Turn it on?", parent=self)
            if not ok:
                self.learn_var.set(False)
                return
            self.cfg["learn_ok"] = True
        self.learn_on()
    else:
        self.learn_off()
    self.cfg["learn"] = bool(self.learn_var.get())
    save_cfg(self.cfg)


def delete_learned(self):
    if messagebox.askyesno("Delete learned data", "Delete ALL saved screenshots and click data?", parent=self):
        shutil.rmtree(LEARN_DIR, ignore_errors=True)
        self.set_status(GREY, "Learned data deleted")


def save_strict(self):
    self.cfg["strict"] = self.strict_var.get()
    save_cfg(self.cfg)


def settings_menu(self):
    n, gb = learn_stats()
    m = tk.Menu(self, tearoff=0)
    m.add_command(label="Anthropic API key…", command=self.ask_key)
    m.add_command(label="Ollama model…", command=self.ask_model)
    m.add_checkbutton(label="Stop if target not found", variable=self.strict_var, command=self.save_strict)
    m.add_separator()
    m.add_checkbutton(label="Learn from my day", variable=self.learn_var, command=self.toggle_learn)
    m.add_command(label=f"{n} examples, {gb:.2f} GB saved", state="disabled")
    m.add_command(label="Open learned data", command=lambda: (LEARN_DIR.mkdir(parents=True, exist_ok=True),
                                                              subprocess.run(["open", str(LEARN_DIR)])))
    m.add_command(label="Delete learned data…", command=self.delete_learned)
    m.add_separator()
    m.add_command(label="Open app folder", command=self.open_folder)
    m.add_command(label="Fn+F7 pause learning   Fn+F8 stop rec   Fn+F10 play", state="disabled")
    m.tk_popup(self.winfo_pointerx(), self.winfo_pointery())


_orig_init = App.__init__


def _init(self, *a, **k):
    _orig_init(self, *a, **k)
    self.strict_var = tk.BooleanVar(value=self.cfg.get("strict", False))
    self.learn_var = tk.BooleanVar(value=False)
    if self.cfg.get("learn") and self.cfg.get("learn_ok"):
        self.learn_var.set(True)
        self.after(1000, self.learn_on)


# =====================================================================================
# Clean soft UI
# =====================================================================================
FONT = "Avenir Next"     # try "Helvetica Neue" or "Noteworthy" if you prefer
INK, MUTE, LAV, WHITE = "#4A4458", "#857D98", "#F4EFF9", "#FFFFFF"
CREAM, ORANGE, PATCH, PINK, EDGE = "#FFF6EA", "#F3B27A", "#8A6A58", "#F4A7B0", "#EBDDCB"
PILLS = {"ready": ("#E7F4E4", "#7CC68C"), "rec": ("#FDE6EC", "#EE7E9E"), "play": ("#E4EEFB", "#6B9BE8")}
FRIENDLY = {"ready": "ready when you are", "stopped": "stopped. everything is safe",
            "finished": "all done ♡", "learning off": "learning is off",
            "recorded. press run": "recorded. press play"}
FOOT = "everything stays on your mac  ·  fn+f9 stops"
FOOT_LEARN = "learning is on  ·  fn+f7 pauses"
S = 2  # draw at 2x, then shrink, for smooth edges


def fnt(size, bold=False):
    return (FONT, size, "bold" if bold else "normal")


def make_bg(W=400, H=700):
    w, h, rnd = W * S, H * S, random.Random(7)
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    top = 250 * S
    for y in range(h):
        c = (mr.lerp("#63A4A8", "#4C8E94", y / top) if y < top
             else mr.lerp("#8DBB5A", "#A9D26C", (y - top) / (h - top)))
        d.line([(0, y), (w, y)], fill=c)
    for x in range(0, w, 30 * S):
        d.rectangle([x, 0, x + 2 * S, top], fill="#58989C")
    for y in (70, 190):
        d.rectangle([0, y * S, w, (y + 6) * S], fill="#478B91")
    for cx, cy, r, c in ((20, 10, 70, "#79A94B"), (385, 0, 80, "#86B455"), (200, -25, 45, "#8DBB5E")):
        d.ellipse([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], fill=c)
    im = im.filter(ImageFilter.GaussianBlur(2 * S))
    d = ImageDraw.Draw(im)
    for _ in range(26):  # daisies
        x, y = rnd.randint(0, W), rnd.randint(262, H)
        r = 4 + 7 * (y - 262) / (H - 262)
        for k in range(8):
            a = k * math.pi / 4
            px, py = x + math.cos(a) * r, y + math.sin(a) * r
            d.ellipse([(px - r * .55) * S, (py - r * .55) * S, (px + r * .55) * S, (py + r * .55) * S], fill="#FFFFFF")
        d.ellipse([(x - r * .45) * S, (y - r * .45) * S, (x + r * .45) * S, (y + r * .45) * S], fill="#F6C945")
    shade = Image.new("L", (w, h), 0)
    ImageDraw.Draw(shade).rounded_rectangle([24 * S, 98 * S, 376 * S, 672 * S], 40 * S, fill=70)
    im.paste((50, 70, 50), (0, 0, w, h), shade.filter(ImageFilter.GaussianBlur(14 * S)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([24 * S, 90 * S, 376 * S, 664 * S], 40 * S, fill=WHITE)   # the card
    for cx in (98, 200, 302):                                                    # stat chips
        d.rounded_rectangle([(cx - 46) * S, 418 * S, (cx + 46) * S, 474 * S], 18 * S, fill=LAV)
    return im.resize((W, H), Image.Resampling.LANCZOS)


def make_pill(bg, dot):
    im = Image.new("RGB", (296 * S, 36 * S), WHITE)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, 296 * S - 1, 36 * S - 1], 18 * S, fill=bg)
    d.ellipse([16 * S, 13 * S, 26 * S, 23 * S], fill=dot)
    return im.resize((296, 36), Image.Resampling.LANCZOS)


def bloom(cv, x, y):
    for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3)):
        cv.create_oval(x + dx - 2.6, y + dy - 2.6, x + dx + 2.6, y + dy + 2.6, fill="#FFD76E", outline="", tags="cat")
    cv.create_oval(x - 1.8, y - 1.8, x + 1.8, y + 1.8, fill="#F4A33B", outline="", tags="cat")


def draw_cat(cv, x, y, blink, tail):
    cv.delete("cat")

    def o(a, b, c, d, col):
        cv.create_oval(x + a, y + b, x + c, y + d, fill=col, tags="cat", width=1.5,
                       outline=EDGE if col == CREAM else "")

    cv.create_line(x + 26, y + 42, x + 46 + tail, y + 38, x + 50 + tail, y + 20, smooth=True,
                   width=9, capstyle="round", fill=ORANGE, tags="cat")
    o(-30, 8, 30, 54, CREAM)
    o(-24, 14, -6, 40, ORANGE)
    o(-21, 46, -5, 58, CREAM)
    o(5, 46, 21, 58, CREAM)
    for s in (-1, 1):
        cv.create_polygon(x + s * 27, y - 10, x + s * 25, y - 46, x + s * 6, y - 27, fill=CREAM, outline=EDGE, width=1.5, tags="cat")
        cv.create_polygon(x + s * 23, y - 16, x + s * 22, y - 38, x + s * 10, y - 27, fill=PINK, outline="", tags="cat")
    o(-27, -32, 27, 16, CREAM)
    o(-24, -29, -5, -10, ORANGE)
    o(8, -29, 24, -15, PATCH)
    for ex in (-12, 12):
        if blink:
            cv.create_line(x + ex - 4, y - 4, x + ex + 4, y - 4, width=2, capstyle="round", fill=INK, tags="cat")
        else:
            o(ex - 3.5, -8, ex + 3.5, -1, INK)
            o(ex - 1.8, -7, ex - .2, -5.4, WHITE)
    o(-24, 1, -14, 8, "#FBD0DA")
    o(14, 1, 24, 8, "#FBD0DA")
    o(-2.5, 1, 2.5, 5, PINK)
    cv.create_line(x - 5, y + 7, x, y + 10, x + 5, y + 7, smooth=True, width=1.5, fill=INK, tags="cat")
    for bx, by in ((-15, -31), (0, -35), (15, -31)):
        bloom(cv, x + bx, y + by)


class _BrainBtn:
    """Lets the existing brain-cycling code keep calling .configure(text=...)."""
    def __init__(self, btn):
        self.btn = btn

    def configure(self, **kw):
        if "text" in kw:
            self.btn.configure(text="brain: " + kw["text"].lower())


def _build(self):
    ctk.set_appearance_mode("light")
    self.title("Macro Recorder")
    self.geometry("400x700")
    self.configure(fg_color="#8DBB5A")
    cv = self.cv = tk.Canvas(self, width=400, height=700, highlightthickness=0, bd=0)
    cv.place(x=0, y=0)
    self.bg_img = mr.to_photo(make_bg())
    cv.create_image(0, 0, anchor="nw", image=self.bg_img)
    self.pill_img = {k: mr.to_photo(make_pill(*v)) for k, v in PILLS.items()}

    def btn(text, cmd, w, h, fg, hover, size, x, y):
        b = ctk.CTkButton(cv, text=text, command=cmd, width=w, height=h, corner_radius=h // 2,
                          fg_color=fg, hover_color=hover, text_color=INK, text_color_disabled="#B9B2C4",
                          font=fnt(size, True), bg_color=WHITE, border_width=0)
        cv.create_window(x, y, window=b)
        return b

    btn("⚙", self.settings_menu, 32, 32, LAV, "#EBE3F4", 14, 346, 118)
    btn("i", lambda: self.set_status(None, "hold fn: f8 stops rec, f9 stops, f10 plays"),
        32, 32, LAV, "#EBE3F4", 13, 306, 118)

    cv.create_text(200, 240, text="macro recorder", fill=INK, font=fnt(22, True))
    cv.create_text(200, 264, text="record once  ·  replay anytime", fill=MUTE, font=fnt(11))

    cv.create_image(52, 288, anchor="nw", image=self.pill_img["ready"], tags="pill")
    cv.create_text(90, 306, text="ready when you are", anchor="w", fill=INK, font=fnt(12), width=240, tags="status")
    cv.create_line(70, 338, 330, 338, width=6, capstyle="round", fill="#EEE9F4")
    self.prog_line = cv.create_line(70, 338, 70, 338, width=6, capstyle="round", fill="#EE9DB5", state="hidden")

    self.btn_rec = btn("● record", self.toggle_record, 140, 48, "#F7B6C8", "#F2A2B9", 14, 124, 380)
    self.btn_act = btn("▶ play", self.toggle_play, 140, 48, "#BFE3C6", "#A6D6B0", 14, 276, 380)

    for cx, label, tag in ((98, "steps", "c_steps_v"), (200, "repeat · tap", "c_rep_v"), (302, "speed · tap", "c_spd_v")):
        cv.create_text(cx, 433, text=label, fill=MUTE, font=fnt(9))
        cv.create_text(cx, 456, text="", fill=INK, font=fnt(15, True), tags=tag)
    cv.create_text(200, 492, text="", fill=MUTE, font=fnt(12), tags="name")

    self.smart = ctk.CTkSwitch(cv, text="smart replay", font=fnt(12, True), text_color=INK,
                               progress_color="#EE9DB5", button_color=WHITE, button_hover_color="#FBEFF3",
                               fg_color="#DCD6E6", bg_color=WHITE)
    self.smart.select()
    cv.create_window(200, 528, window=self.smart)
    cv.create_text(200, 551, text="finds buttons even if windows move", fill=MUTE, font=fnt(10))

    btn("macros ▾", self.open_library, 140, 34, LAV, "#EBE3F4", 12, 124, 592)
    self.lbl_brain = _BrainBtn(btn("brain: local", self.cycle_brain, 140, 34, LAV, "#EBE3F4", 12, 276, 592))

    cv.create_text(200, 636, text=FOOT, fill=MUTE, font=fnt(10), tags="foot")
    cv.bind("<Motion>", lambda e: cv.config(cursor="hand2" if self._zone(e.x, e.y) else ""))
    cv.bind("<Button-1>", lambda e: (self._zone(e.x, e.y) or (lambda: None))())
    self._foot = FOOT


def _zone(self, x, y):
    if 418 <= y <= 474:
        if 154 <= x <= 246:
            return self.cycle_repeat
        if 256 <= x <= 348:
            return self.cycle_speed
    if 480 <= y <= 504 and 110 <= x <= 290:
        return self.save
    return None


def _tick(self):
    self.anim += 1
    a, x, y = self.anim, 200, 160
    if self.recording:
        x += 4 * math.sin(a / 4)
    elif self.playing:
        y -= abs(math.sin(a / 2)) * 7
    elif a % 20 < 10:
        y += 1
    draw_cat(self.cv, x, y, a % 26 < 2, 3 * math.sin(a / 5))
    if self.playing:
        p = min(1.0, getattr(self, "idx", 0) / max(1, len(self.events)))
        self.cv.coords(self.prog_line, 70, 338, 70 + 260 * p, 338)
        self.cv.itemconfigure(self.prog_line, state="normal")
    else:
        self.cv.itemconfigure(self.prog_line, state="hidden")
    foot = FOOT_LEARN if getattr(self, "learning", False) else FOOT
    if foot != self._foot:
        self._foot = foot
        self.cv.itemconfigure("foot", text=foot)
    self.after(150, self._tick)


def _pill_style(self):
    k = "rec" if self.recording else ("play" if self.playing else "ready")
    self.cv.itemconfigure("pill", image=self.pill_img[k])


def set_status(self, color, text):
    t = text.lower().strip()
    self.cv.itemconfigure("status", text=FRIENDLY.get(t, t))
    self._pill_style()


def refresh_lcd(self):
    self.cv.itemconfigure("name", text=f"{self.macro_name.lower()}  ✎")
    self.cv.itemconfigure("c_steps_v", text=str(self.nsteps))
    self.cv.itemconfigure("c_rep_v", text=f"×{self.repeat_n}")
    self.cv.itemconfigure("c_spd_v", text=f"{self.speed_v:g}×")


def update_count(self):
    self.nsteps = sum(1 for e in self.events if e["type"] in ("click", "key") and e["pressed"])
    self.cv.itemconfigure("c_steps_v", text=str(self.nsteps))


def refresh_buttons(self):
    self.btn_rec.configure(text="■ stop" if self.recording else "● record",
                           fg_color="#F28DA6" if self.recording else "#F7B6C8",
                           state="disabled" if self.playing else "normal")
    self.btn_act.configure(text="■ stop" if self.playing else "▶ play",
                           fg_color="#8FD0A0" if self.playing else "#BFE3C6",
                           state="disabled" if self.recording else "normal")
    self._pill_style()


def open_library(self):
    names = sorted(p.stem for p in mr.MACRO_DIR.glob("*.json"))
    win = ctk.CTkToplevel(self)
    win.title("my macros")
    win.geometry("320x400")
    win.configure(fg_color=WHITE)
    win.after(100, win.lift)
    ctk.CTkLabel(win, text="my macros ♡", font=fnt(16, True), text_color=INK).pack(pady=(16, 8))
    box = ctk.CTkScrollableFrame(win, fg_color=LAV, corner_radius=18)
    box.pack(fill="both", expand=True, padx=16, pady=(0, 16))
    if not names:
        ctk.CTkLabel(box, text="nothing saved yet.\ntap the macro name to save one.",
                     font=fnt(11), text_color=MUTE).pack(pady=24)
    for n in names:
        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x", pady=3)
        ctk.CTkButton(row, text=n.lower(), anchor="w", font=fnt(12), fg_color=WHITE, hover_color="#FBEFF3",
                      text_color=INK, corner_radius=14,
                      command=lambda n=n: (self.load_named(n), win.destroy())).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(row, text="✕", width=32, font=fnt(12, True), fg_color="transparent", hover_color="#FBEFF3",
                      text_color=MUTE, command=lambda n=n: (self.delete_named(n), win.destroy())).pack(side="left", padx=(6, 0))


# =====================================================================================
# Apply everything to the app
# =====================================================================================
for _fn in (_begin_record, _watch, grab_crop, on_click, get_tpl, match_fast, find, _play, _do, ask_fast,
            make_fast, learn_on, learn_off, _learn_key, _learn_moved, _learn_watch, _learn_click, _learn_save,
            toggle_learn, delete_learned, save_strict, settings_menu, _build, _zone, _tick, _pill_style,
            set_status, refresh_lcd, update_count, refresh_buttons, open_library):
    setattr(App, _fn.__name__, _fn)
App.__init__ = _init


if __name__ == "__main__":
    App().mainloop()