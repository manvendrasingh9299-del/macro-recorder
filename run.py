"""
run.py - launcher for Macro Recorder. Loads macro_recorder.py (the base app) and applies the
latest fixes and features on top.  Start the app with:   python run.py   (handheld game interface)
"""
import base64, datetime, json, os, shutil, subprocess, threading, time
import tkinter as tk
import urllib.request
from collections import deque
from tkinter import messagebox

import cv2
import numpy as np
from AppKit import NSWorkspace
from PIL import Image, ImageGrab
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
# Apply everything to the app
# =====================================================================================
for _fn in (_begin_record, _watch, grab_crop, on_click, get_tpl, match_fast, find, _play, _do, ask_fast,
            make_fast, learn_on, learn_off, _learn_key, _learn_moved, _learn_watch, _learn_click, _learn_save,
            toggle_learn, delete_learned, save_strict, settings_menu):
    setattr(App, _fn.__name__, _fn)
App.__init__ = _init


if __name__ == "__main__":
    App().mainloop()