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

if __name__ == "__main__":
    app = App()
    app.strict_var = tk.BooleanVar(value=app.cfg.get("strict", False))
    app.mainloop()