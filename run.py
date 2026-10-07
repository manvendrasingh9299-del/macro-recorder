"""Fixes + upgrades on top of macro_recorder.py.   Run:  python run.py"""
import json, os, shutil, subprocess, threading, time, tkinter as tk, urllib.request
from collections import deque

import numpy as np
from PIL import Image, ImageGrab
from Quartz import (CGDisplayCreateImage, CGMainDisplayID, CGImageGetWidth, CGImageGetHeight,
                    CGImageGetBytesPerRow, CGImageGetDataProvider, CGDataProviderCopyData)
from pynput import mouse

import macro_recorder as mr
from macro_recorder import (App, ACCENT, GREEN, GREY, RED, OLLAMA_DEFAULT, CROP_PT, COUNTDOWN,
                            BTN, b64, save_cfg, post_mouse, move_to, mouse_ctl, kb_ctl, data_to_key)

mr.MATCH_MIN = 0.72   # a bit more forgiving (hover highlights change how buttons look)
WAIT_S = 5.0          # seconds to keep looking for a target


# ---------- fast screenshot ----------
def grab_screen():
    try:
        img = CGDisplayCreateImage(CGMainDisplayID())
        w, h, bpr = CGImageGetWidth(img), CGImageGetHeight(img), CGImageGetBytesPerRow(img)
        buf = np.frombuffer(CGDataProviderCopyData(CGImageGetDataProvider(img)), np.uint8)
        return Image.fromarray(buf.reshape(h, bpr // 4, 4)[:, :w, 2::-1].copy())
    except Exception:
        return ImageGrab.grab().convert("RGB")


# ---------- Ollama auto-start ----------
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


# ---------- recording: save each click as it looked BEFORE the click ----------
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
    now = time.time()
    ev = {"type": "click", "x": x, "y": y, "button": button.name, "pressed": pressed,
          "t": round(now - self.t0, 3)}
    if pressed:
        ev.update(self.grab_crop(x, y, now))
    self.events.append(ev)
    self.ui(self.update_count)


# ---------- playback ----------
def find(self, ev):
    end, tries = time.time() + WAIT_S, 0
    while time.time() < end and not self.abort.is_set():
        try:
            shot = grab_screen()
            hit = self.match_local(ev, shot)
            if hit:
                return hit
            if self.brain in ("claude", "ollama", "plugin") and tries < 2:
                tries += 1
                hit = self.model_find(ev, shot, shot.width / self.sw)
                if hit:
                    return hit
        except Exception as exc:
            print("Find error:", exc)
        if not self._sleep(0.5):
            return None
    return None


def _play(self, repeat, speed):
    if self.brain == "ollama":
        self.ui(self.set_status, ACCENT, "Starting Ollama")
        problem = ensure_ollama(self.cfg.get("ollama_model", OLLAMA_DEFAULT))
        if problem:
            self.ui(self.set_status, ACCENT, problem)
    if not self._sleep(COUNTDOWN):
        return self._stopped()
    for n in range(repeat):
        self.ui(self.set_status, GREEN, f"Playing {n + 1} of {repeat}")
        prev = 0.0
        for ev in self.events:
            if not self._sleep((ev["t"] - prev) / speed):
                return self._stopped()
            prev = ev["t"]
            self._do(ev)
        if n < repeat - 1 and not self._sleep(1):
            return self._stopped()
    self.ui(self._end, "Finished")


def _do(self, ev):
    try:
        if ev["type"] == "click":
            if ev["pressed"]:
                self.cur = (ev["x"], ev["y"])
                if self.brain != "exact" and ev.get("crop"):
                    self.ui(self.set_status, ACCENT, "Finding target")
                    hit = self.find(ev)
                    print(f"[find] recorded=({ev['x']:.0f},{ev['y']:.0f}) found={hit}")
                    if hit:
                        self.cur = hit
                    elif self.abort.is_set():
                        return
                    elif self.strict_var.get():
                        self.fail = "Target not found. Stopped"
                        self.abort.set()
                        return
                    else:
                        self.ui(self.set_status, ACCENT, "Not found, using saved spot")
                now = time.time()
                near = (abs(self.cur[0] - self.last_click[1][0]) < 8
                        and abs(self.cur[1] - self.last_click[1][1]) < 8)
                self.click_n = self.click_n + 1 if now - self.last_click[0] < 0.45 and near else 1
                self.last_click = (now, self.cur)
                move_to(*self.cur)
            down, up, btn = BTN.get(ev["button"], BTN["left"])
            post_mouse(down if ev["pressed"] else up, *self.cur, btn, self.click_n)
            print(f"[click] {ev['button']} {'down' if ev['pressed'] else 'up'} at ({self.cur[0]:.0f}, {self.cur[1]:.0f})")
        elif ev["type"] == "scroll":
            move_to(ev["x"], ev["y"])
            mouse_ctl.scroll(ev["dx"], ev["dy"])
        elif ev["type"] == "key":
            (kb_ctl.press if ev["pressed"] else kb_ctl.release)(data_to_key(ev["key"]))
    except Exception as exc:
        print("Action failed:", exc)


# ---------- settings menu ----------
def save_strict(self):
    self.cfg["strict"] = self.strict_var.get()
    save_cfg(self.cfg)


def settings_menu(self):
    m = tk.Menu(self, tearoff=0)
    m.add_command(label="Anthropic API key…", command=self.ask_key)
    m.add_command(label="Ollama model…", command=self.ask_model)
    m.add_checkbutton(label="Stop if target not found", variable=self.strict_var, command=self.save_strict)
    m.add_command(label="Open app folder", command=self.open_folder)
    m.add_separator()
    m.add_command(label="Fn+F8 stop rec   Fn+F9 stop play   Fn+F10 run", state="disabled")
    m.tk_popup(self.winfo_pointerx(), self.winfo_pointery())


for fn in (_begin_record, _watch, grab_crop, on_click, find, _play, _do, save_strict, settings_menu):
    setattr(App, fn.__name__, fn)

# ---------- double-click support ----------
def on_click(self, x, y, button, pressed):
    if not self.capturing:
        return
    now = time.time()
    if not self.events:
        self.rec_last, self.cur_n = (0.0, (0, 0), 1), 1
    ev = {"type": "click", "x": x, "y": y, "button": button.name, "pressed": pressed,
          "t": round(now - self.t0, 3)}
    if pressed:
        lt, lp, ln = self.rec_last
        near = abs(x - lp[0]) < 8 and abs(y - lp[1]) < 8
        self.cur_n = ln + 1 if now - lt < 0.5 and near else 1
        self.rec_last = (now, (x, y), self.cur_n)
        if self.cur_n == 1:  # repeat clicks reuse the first click's target
            ev.update(self.grab_crop(x, y, now))
    ev["n"] = self.cur_n
    self.events.append(ev)
    self.ui(self.update_count)


def _do(self, ev):
    try:
        if ev["type"] == "click":
            n = ev.get("n", 1)
            if ev["pressed"] and n == 1:
                self.cur = (ev["x"], ev["y"])
                if self.brain != "exact" and ev.get("crop"):
                    self.ui(self.set_status, ACCENT, "Finding target")
                    hit = self.find(ev)
                    print(f"[find] recorded=({ev['x']:.0f},{ev['y']:.0f}) found={hit}")
                    if hit:
                        self.cur = hit
                    elif self.abort.is_set():
                        return
                    elif self.strict_var.get():
                        self.fail = "Target not found. Stopped"
                        self.abort.set()
                        return
                    else:
                        self.ui(self.set_status, ACCENT, "Not found, using saved spot")
                move_to(*self.cur)
            down, up, btn = BTN.get(ev["button"], BTN["left"])
            post_mouse(down if ev["pressed"] else up, *self.cur, btn, n)
            print(f"[click x{n}] {ev['button']} {'down' if ev['pressed'] else 'up'} at ({self.cur[0]:.0f}, {self.cur[1]:.0f})")
        elif ev["type"] == "scroll":
            move_to(ev["x"], ev["y"])
            mouse_ctl.scroll(ev["dx"], ev["dy"])
        elif ev["type"] == "key":
            (kb_ctl.press if ev["pressed"] else kb_ctl.release)(data_to_key(ev["key"]))
    except Exception as exc:
        print("Action failed:", exc)


App.on_click = on_click
App._do = _do

# ---------- reliable clicks (keep this ABOVE: if __name__ == "__main__":) ----------
from Quartz import (CGEventSourceCreate, kCGEventSourceStateHIDSystemState,
                    CGEventCreateMouseEvent as _mk, CGEventPost as _post,
                    CGEventSetIntegerValueField as _setf, kCGMouseEventClickState as _CS,
                    kCGEventMouseMoved as _MV, kCGHIDEventTap as _TAP)

_SRC = CGEventSourceCreate(kCGEventSourceStateHIDSystemState)


def _send(kind, x, y, btn=0, n=1):
    e = _mk(_SRC, kind, (x, y), btn)
    _setf(e, _CS, n)
    _post(_TAP, e)


def glide_to(x, y):
    """Move in small steps, then pause, so the Dock and menus notice the pointer."""
    sx, sy = mouse_ctl.position
    for i in range(1, 7):
        _send(_MV, sx + (x - sx) * i / 6, sy + (y - sy) * i / 6)
        time.sleep(0.015)
    _send(_MV, x, y)
    time.sleep(0.25)


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


def _do(self, ev):
    try:
        if ev["type"] == "click":
            n = ev.get("n", 1)
            if ev["pressed"] and n == 1:
                self.cur = (ev["x"], ev["y"])
                if self.brain != "exact" and ev.get("crop"):
                    self.ui(self.set_status, ACCENT, "Finding target")
                    hit = self.find(ev)
                    print(f"[find] recorded=({ev['x']:.0f},{ev['y']:.0f}) found={hit}")
                    if hit:
                        self.cur = hit
                    elif self.abort.is_set():
                        return
                    elif self.strict_var.get():
                        self.fail = "Target not found. Stopped"
                        self.abort.set()
                        return
                    else:
                        self.ui(self.set_status, ACCENT, "Not found, using saved spot")
                glide_to(*self.cur)
            down, up, btn = BTN.get(ev["button"], BTN["left"])
            if not ev["pressed"]:
                time.sleep(0.05)  # hold the button long enough to count as a click
            _send(down if ev["pressed"] else up, self.cur[0], self.cur[1], btn, n)
            print(f"[click x{n}] {ev['button']} {'down' if ev['pressed'] else 'up'} at ({self.cur[0]:.0f}, {self.cur[1]:.0f})")
        elif ev["type"] == "scroll":
            glide_to(ev["x"], ev["y"])
            mouse_ctl.scroll(ev["dx"], ev["dy"])
        elif ev["type"] == "key":
            (kb_ctl.press if ev["pressed"] else kb_ctl.release)(data_to_key(ev["key"]))
    except Exception as exc:
        print("Action failed:", exc)


App.on_click = on_click
App._do = _do

# ---------- learn once, then run fast (keep this ABOVE: if __name__ == "__main__":) ----------
import base64
import cv2
from tkinter import messagebox


def glide_to(x, y, fast=False):
    """Move in small steps, then pause, so the Dock and menus notice the pointer."""
    sx, sy = mouse_ctl.position
    steps = 3 if fast else 6
    for i in range(1, steps + 1):
        _send(_MV, sx + (x - sx) * i / steps, sy + (y - sy) * i / steps)
        time.sleep(0.015)
    _send(_MV, x, y)
    time.sleep(0.12 if fast else 0.25)


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


for fn in (get_tpl, match_fast, find, _play, _do, ask_fast, make_fast):
    setattr(App, fn.__name__, fn)
    
if __name__ == "__main__":
    app = App()
    app.strict_var = tk.BooleanVar(value=app.cfg.get("strict", False))
    app.mainloop()