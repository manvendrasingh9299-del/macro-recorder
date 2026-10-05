"""
Macro Recorder v5 - dot-matrix dark UI + pluggable "brains".
Hotkeys (work from any app):  F8 stop recording   F9 stop playback   F10 activate

Brains:  Exact positions | Smart local (OpenCV, free) | + Claude | + Ollama (local small model) | + my model
"""
import base64, importlib.util, io, json, math, os, queue, re, subprocess, threading, time
import tkinter as tk, urllib.request
from pathlib import Path

import cv2
import customtkinter as ctk
import numpy as np
from PIL import Image, ImageGrab
from pynput import keyboard, mouse

APP_DIR = Path.home() / "Library" / "Application Support" / "MacroRecorder"
MACRO_DIR = APP_DIR / "macros"
MACRO_DIR.mkdir(parents=True, exist_ok=True)
CONFIG, PLUGIN = APP_DIR / "config.json", APP_DIR / "my_model.py"

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
BRAINS = {"Exact positions": "exact", "Smart local": "local", "Smart + Claude": "claude",
          "Smart + Ollama": "ollama", "Smart + my model": "plugin"}
K_STOP_REC, K_STOP_PLAY, K_PLAY = keyboard.Key.f8, keyboard.Key.f9, keyboard.Key.f10

BG, CARD, EDGE, FIELD, DIM = "#0D0D0F", "#19191B", "#2A2A2D", "#111113", "#37373B"
TEXT, MUTED, ACCENT = "#EDEDED", "#7C7C82", "#FF4B1F"
RED = GREEN = ACCENT
GREY = MUTED
COUNTDOWN, CROP_PT, SENT_W, DOTS = 3, 140, 1280, 36
MATCH_MIN, WAIT_S = 0.80, 8.0   # local match confidence, seconds to wait for a target

PLUGIN_TEMPLATE = '''"""Your own model. Called when local matching fails (brain: "Smart + my model").

crop   : PIL RGB image of what was clicked (screen pixels)
screen : PIL RGB image of the current screen (screen pixels)
hint   : (x, y) where it was when recorded (screen pixels)
Return (x, y) of the target in screen pixels, or None if not found.
"""
def find(crop, screen, hint):
    # Example: load your ONNX / PyTorch / CoreML model here and run it.
    return None
'''

mouse_ctl, kb_ctl = mouse.Controller(), keyboard.Controller()


def mono(size, bold=False):
    return ("Menlo", size, "bold" if bold else "normal")


def lerp(a, b, t):
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(pa, pb))


TAIL = [lerp(ACCENT, DIM, k / 9) for k in range(9)]


def key_to_data(k):
    if isinstance(k, keyboard.KeyCode):
        return {"char": k.char} if k.char else {"vk": k.vk}
    return {"name": k.name}


def data_to_key(d):
    if "char" in d:
        return d["char"]
    if "vk" in d:
        return keyboard.KeyCode.from_vk(d["vk"])
    return getattr(keyboard.Key, d["name"])


def b64(img, fmt="PNG", **kw):
    buf = io.BytesIO()
    img.save(buf, fmt, **kw)
    return base64.b64encode(buf.getvalue()).decode()


def load_cfg():
    try:
        return json.loads(CONFIG.read_text())
    except Exception:
        return {}


def save_cfg(cfg):
    CONFIG.write_text(json.dumps(cfg))
    CONFIG.chmod(0o600)


def parse_json(text):
    return json.loads(re.search(r"\{.*\}", text, re.S).group())


def ask_claude(key, crop_b64, shot_b64, prompt):
    img = lambda m, d: {"type": "image", "source": {"type": "base64", "media_type": m, "data": d}}
    body = {"model": CLAUDE_MODEL, "max_tokens": 60, "messages": [{"role": "user", "content": [
        img("image/png", crop_b64), img("image/jpeg", shot_b64), {"type": "text", "text": prompt}]}]}
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", json.dumps(body).encode(),
        {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return parse_json(json.load(r)["content"][0]["text"])


def ask_ollama(model, crop_b64, shot_b64, prompt):
    body = {"model": model, "stream": False, "options": {"temperature": 0},
            "messages": [{"role": "user", "content": prompt, "images": [crop_b64, shot_b64]}]}
    req = urllib.request.Request("http://localhost:11434/api/chat", json.dumps(body).encode(),
                                 {"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return parse_json(json.load(r)["message"]["content"])


def load_plugin():
    spec = importlib.util.spec_from_file_location("my_model", PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("Macro Recorder")
        self.configure(fg_color=BG)
        self.geometry("400x720")
        self.resizable(False, False)
        self.update_idletasks()
        self.sw, self.sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.sent_w = min(self.sw, SENT_W)

        self.q = queue.Queue()
        self.events, self.t0, self.cur = [], 0.0, (0, 0)
        self.recording = self.capturing = self.playing = False
        self.abort = threading.Event()
        self.mouse_listener = None
        self.cfg = load_cfg()
        self.api_key = os.environ.get("ANTHROPIC_API_KEY") or self.cfg.get("api_key", "")
        self.brain, self.plugin, self.fail = "local", None, ""
        self.nsteps, self.prog, self.anim = 0, 0.0, 0
        self.cols = [None] * DOTS

        self._build()
        self.refresh_library()
        self.after(50, self._pump)
        self.after(90, self._tick)
        keyboard.Listener(on_press=self.on_press, on_release=self.on_release).start()

    # ---------- UI ----------
    def _card(self, num, title):
        f = ctk.CTkFrame(self, fg_color=CARD, corner_radius=18, border_width=1, border_color=EDGE)
        f.pack(fill="x", padx=18, pady=6)
        ctk.CTkLabel(f, text=f"{num}  {title}", font=mono(10), text_color=MUTED).pack(anchor="w", padx=16, pady=(12, 6))
        return f

    def _small_btn(self, parent, text, cmd):
        return ctk.CTkButton(parent, text=text, width=64, height=26, corner_radius=13, font=mono(10),
                             fg_color="transparent", border_width=1, border_color=EDGE,
                             text_color=MUTED, hover_color=CARD, command=cmd)

    def _build(self):
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=22, pady=(20, 8))
        titles = ctk.CTkFrame(head, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text="MACRO RECORDER", font=mono(20, True), text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(titles, text="RECORD ONCE. REPLAY ANYTIME.", font=mono(9), text_color=MUTED).pack(anchor="w")
        btns = ctk.CTkFrame(head, fg_color="transparent")
        btns.pack(side="right", anchor="n")
        self._small_btn(btns, "KEY", self.ask_key).pack(side="left", padx=2)
        self._small_btn(btns, "FOLDER", lambda: subprocess.run(["open", str(APP_DIR)])).pack(side="left", padx=2)

        # 01 status
        c1 = self._card("01", "STATUS")
        body = ctk.CTkFrame(c1, fg_color="transparent")
        body.pack(fill="x", padx=16, pady=(0, 14))
        self.ring = tk.Canvas(body, width=132, height=132, bg=CARD, highlightthickness=0)
        self.ring.pack(side="left")
        self.dots = []
        for i in range(DOTS):
            a = 2 * math.pi * i / DOTS - math.pi / 2
            x, y = 66 + 56 * math.cos(a), 66 + 56 * math.sin(a)
            self.dots.append(self.ring.create_oval(x - 2.4, y - 2.4, x + 2.4, y + 2.4, fill=DIM, outline=""))
        self.num_id = self.ring.create_text(66, 62, text="0", fill=TEXT, font=mono(26, True))
        self.ring.create_text(66, 88, text="STEPS", fill=MUTED, font=mono(9))

        info = ctk.CTkFrame(body, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=(16, 0))
        row = ctk.CTkFrame(info, fg_color="transparent")
        row.pack(anchor="w", pady=(24, 0))
        self.dot = ctk.CTkLabel(row, text="●", text_color=MUTED, font=mono(12))
        self.dot.pack(side="left")
        self.status = ctk.CTkLabel(row, text="READY", font=mono(13, True), text_color=TEXT,
                                   wraplength=150, justify="left")
        self.status.pack(side="left", padx=(6, 0))
        ctk.CTkLabel(info, text="PRESS F10 TO ACTIVATE FROM ANY APP", font=mono(9), text_color=MUTED,
                     wraplength=160, justify="left").pack(anchor="w", pady=(10, 0))

        # buttons
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=6)
        row.columnconfigure((0, 1), weight=1, uniform="a")
        self.btn_rec = ctk.CTkButton(row, text="RECORD", height=54, corner_radius=16, font=mono(13, True),
                                     fg_color=ACCENT, hover_color="#E03E14", text_color="white",
                                     command=self.toggle_record)
        self.btn_rec.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.btn_act = ctk.CTkButton(row, text="ACTIVATE", height=54, corner_radius=16, font=mono(13, True),
                                     fg_color="transparent", border_width=2, border_color=ACCENT,
                                     text_color=ACCENT, hover_color="#2A1913", command=self.toggle_play)
        self.btn_act.grid(row=0, column=1, sticky="ew", padx=(5, 0))

        # 02 settings
        c2 = self._card("02", "SETTINGS")
        brow = ctk.CTkFrame(c2, fg_color="transparent")
        brow.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(brow, text="BRAIN", font=mono(10), text_color=MUTED).pack(side="left")
        self.brain_menu = ctk.CTkOptionMenu(brow, values=list(BRAINS), command=self.on_brain, font=mono(11),
                                            fg_color=FIELD, button_color=EDGE, button_hover_color=DIM,
                                            text_color=TEXT, dropdown_fg_color=CARD, dropdown_text_color=TEXT,
                                            dropdown_font=mono(11))
        self.brain_menu.set("Smart local")
        self.brain_menu.pack(side="left", fill="x", expand=True, padx=(10, 0))
        opts = ctk.CTkFrame(c2, fg_color="transparent")
        opts.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkLabel(opts, text="REPEAT", font=mono(10), text_color=MUTED).pack(side="left")
        self.repeat = ctk.CTkEntry(opts, width=48, justify="center", font=mono(12), fg_color=FIELD,
                                   border_color=EDGE, text_color=TEXT)
        self.repeat.insert(0, "1")
        self.repeat.pack(side="left", padx=(8, 14))
        self.speed = ctk.CTkSegmentedButton(opts, values=["0.5x", "1x", "2x", "3x"], font=mono(11),
                                            selected_color=ACCENT, selected_hover_color="#E03E14",
                                            unselected_color=FIELD, unselected_hover_color=EDGE,
                                            fg_color=FIELD, text_color=TEXT)
        self.speed.set("1x")
        self.speed.pack(side="left")

        # 03 library
        c3 = self._card("03", "LIBRARY")
        self.menu = ctk.CTkOptionMenu(c3, values=["No saved macros"], command=self.load_named, font=mono(11),
                                      fg_color=FIELD, button_color=EDGE, button_hover_color=DIM,
                                      text_color=TEXT, dropdown_fg_color=CARD, dropdown_text_color=TEXT,
                                      dropdown_font=mono(11))
        self.menu.pack(fill="x", padx=16)
        sb = ctk.CTkFrame(c3, fg_color="transparent")
        sb.pack(fill="x", padx=16, pady=(8, 14))
        ctk.CTkButton(sb, text="SAVE CURRENT", font=mono(11), fg_color=EDGE, hover_color=DIM,
                      text_color=TEXT, command=self.save).pack(side="left", expand=True, fill="x", padx=(0, 4))
        ctk.CTkButton(sb, text="DELETE", font=mono(11), fg_color="transparent", border_width=1,
                      border_color=EDGE, text_color=MUTED, hover_color=FIELD,
                      command=self.delete).pack(side="left", expand=True, fill="x", padx=(4, 0))

        ctk.CTkLabel(self, text="F8 STOP REC   F9 STOP PLAY   F10 RUN", font=mono(9),
                     text_color=MUTED).pack(pady=(10, 0))
        ctk.CTkLabel(self, text="BUILD ANYTHING WITH INTELLIGENCE _", font=mono(9),
                     text_color=DIM).pack(pady=(2, 0))

    # ---------- thread bridge + animation ----------
    def ui(self, fn, *a):
        self.q.put(lambda: fn(*a))

    def _pump(self):
        try:
            while True:
                self.q.get_nowait()()
        except queue.Empty:
            pass
        self.after(50, self._pump)

    def _tick(self):
        self.anim += 1
        for i, d in enumerate(self.dots):
            if self.recording:
                dist = (self.anim - i) % DOTS
                col = TAIL[dist] if dist < len(TAIL) else DIM
            elif self.playing:
                lit = int(self.prog * DOTS)
                col = ACCENT if i < lit else (TEXT if i == lit else DIM)
            else:
                col = "#C9C9CE" if i < min(self.nsteps, DOTS) else DIM
            if col != self.cols[i]:
                self.cols[i] = col
                self.ring.itemconfigure(d, fill=col)
        self.after(90, self._tick)

    def set_status(self, color, text):
        self.dot.configure(text_color=color)
        self.status.configure(text=text.upper())

    def refresh_buttons(self):
        self.btn_rec.configure(text="STOP  F8" if self.recording else "RECORD",
                               state="disabled" if self.playing else "normal")
        self.btn_act.configure(text="STOP  F9" if self.playing else "ACTIVATE",
                               state="disabled" if self.recording else "normal")

    def update_count(self):
        self.nsteps = sum(1 for e in self.events if e["type"] in ("click", "key") and e["pressed"])
        self.ring.itemconfigure(self.num_id, text=str(self.nsteps))

    # ---------- settings ----------
    def ask_key(self):
        key = ctk.CTkInputDialog(text="Paste your Anthropic API key (console.anthropic.com):",
                                 title="API key").get_input()
        if key:
            self.api_key = key.strip()
            self.cfg["api_key"] = self.api_key
            save_cfg(self.cfg)
            self.set_status(GREY, "API key saved")
        return bool(self.api_key)

    def ask_model(self):
        name = ctk.CTkInputDialog(text="Ollama vision model name (e.g. qwen2.5vl:3b):",
                                  title="Ollama model").get_input()
        if name and name.strip():
            self.cfg["ollama_model"] = name.strip()
            save_cfg(self.cfg)
            self.set_status(GREY, f"Model {name.strip()}")
        return bool(self.cfg.get("ollama_model"))

    def on_brain(self, choice):
        key = BRAINS[choice]
        if key == "claude" and not self.api_key and not self.ask_key():
            self.brain_menu.set("Smart local")
        elif key == "ollama" and not self.cfg.get("ollama_model") and not self.ask_model():
            self.brain_menu.set("Smart local")
        elif key == "plugin":
            if not PLUGIN.exists():
                PLUGIN.write_text(PLUGIN_TEMPLATE)
            self.set_status(GREY, "Edit my_model.py (FOLDER button)")

    # ---------- recording ----------
    def toggle_record(self):
        self.stop_record() if self.recording else self.start_record()

    def start_record(self):
        if self.recording or self.playing:
            return
        self.recording, self.events = True, []
        self.update_count()
        self.set_status(RED, f"Recording in {COUNTDOWN}s")
        self.refresh_buttons()
        self.after(800, self.iconify)
        self.after(COUNTDOWN * 1000, self._begin_record)

    def _begin_record(self):
        if self.recording:
            self.t0, self.capturing = time.time(), True
            self.ui(self.set_status, RED, "Recording")
            self.mouse_listener = mouse.Listener(on_click=self.on_click, on_scroll=self.on_scroll)
            self.mouse_listener.start()

    def stop_record(self):
        if not self.recording:
            return
        self.recording = self.capturing = False
        if self.mouse_listener:
            self.mouse_listener.stop()
        self.deiconify()
        self.lift()
        self.update_count()
        self.set_status(GREY, "Recorded. Press Activate")
        self.refresh_buttons()

    def grab_crop(self, x, y):
        """Native-resolution picture around the click, used later to find the target again."""
        try:
            shot = ImageGrab.grab().convert("RGB")
            s = shot.width / self.sw
            half = int(CROP_PT * s / 2)
            cx, cy = int(x * s), int(y * s)
            left, top = max(cx - half, 0), max(cy - half, 0)
            c = shot.crop((left, top, cx + half, cy + half))
            return {"crop": b64(c), "ox": cx - left, "oy": cy - top, "s": s}
        except Exception:
            return {}  # no Screen Recording permission

    def on_click(self, x, y, button, pressed):
        if not self.capturing:
            return
        t = round(time.time() - self.t0, 3)
        ev = {"type": "click", "x": x, "y": y, "button": button.name, "pressed": pressed, "t": t}
        if pressed:
            ev.update(self.grab_crop(x, y))
        self.events.append(ev)
        self.ui(self.update_count)

    def on_scroll(self, x, y, dx, dy):
        if self.capturing:
            self.events.append({"type": "scroll", "x": x, "y": y, "dx": dx, "dy": dy,
                                "t": round(time.time() - self.t0, 3)})

    def on_press(self, key):
        if key == K_STOP_PLAY:
            self.abort.set()
        elif key == K_STOP_REC and self.recording:
            self.ui(self.stop_record)
        elif key == K_PLAY and not self.recording:
            self.ui(self.toggle_play)
        elif self.capturing:
            self.events.append({"type": "key", "pressed": True, "key": key_to_data(key),
                                "t": round(time.time() - self.t0, 3)})
            self.ui(self.update_count)

    def on_release(self, key):
        if self.capturing and key not in (K_STOP_REC, K_STOP_PLAY, K_PLAY):
            self.events.append({"type": "key", "pressed": False, "key": key_to_data(key),
                                "t": round(time.time() - self.t0, 3)})

    # ---------- finding targets ----------
    def match_local(self, ev, shot):
        """Free, fast OpenCV template match. Returns (x, y) in screen points or None."""
        tpl = cv2.imdecode(np.frombuffer(base64.b64decode(ev["crop"]), np.uint8), cv2.IMREAD_GRAYSCALE)
        if "s" not in ev:  # macro from an older version: crop was stored downscaled
            k = shot.width / self.sent_w
            tpl = cv2.resize(tpl, None, fx=k, fy=k)
        scr = cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2GRAY)
        _, score, _, loc = cv2.minMaxLoc(cv2.matchTemplate(scr, tpl, cv2.TM_CCOEFF_NORMED))
        if score < MATCH_MIN:
            return None
        s = shot.width / self.sw
        ox, oy = ev.get("ox", tpl.shape[1] / 2), ev.get("oy", tpl.shape[0] / 2)
        return (loc[0] + ox) / s, (loc[1] + oy) / s

    def model_find(self, ev, shot, s):
        """Second opinion from the chosen model (Claude / Ollama / your plugin)."""
        if self.brain == "plugin":
            crop = Image.open(io.BytesIO(base64.b64decode(ev["crop"]))).convert("RGB")
            r = self.plugin.find(crop, shot, (ev["x"] * s, ev["y"] * s))
            return (r[0] / s, r[1] / s) if r else None
        w, h = self.sent_w, round(shot.height * self.sent_w / shot.width)
        crop = Image.open(io.BytesIO(base64.b64decode(ev["crop"]))).convert("RGB")
        if "s" in ev:
            k = w / shot.width
            crop = crop.resize((max(1, int(crop.width * k)), max(1, int(crop.height * k))))
        px, py = round(ev["x"] * w / self.sw), round(ev["y"] * h / self.sh)
        prompt = (f"Image 1 is a crop around a UI element I clicked earlier. Image 2 is my current screen ({w}x{h} px). "
                  f"Find the same element in image 2. It used to be near ({px}, {py}). "
                  'Reply with JSON only: {"found": true, "x": <int>, "y": <int>} for its center, or {"found": false}.')
        c_b64, s_b64 = b64(crop), b64(shot.resize((w, h)), "JPEG", quality=70)
        if self.brain == "claude":
            r = ask_claude(self.api_key, c_b64, s_b64, prompt)
        else:
            r = ask_ollama(self.cfg["ollama_model"], c_b64, s_b64, prompt)
        return (r["x"] * self.sw / w, r["y"] * self.sh / h) if r.get("found") else None

    def find(self, ev):
        """Local match first; chosen model as backup; keeps trying while the page loads."""
        end, tries = time.time() + WAIT_S, 0
        while time.time() < end and not self.abort.is_set():
            try:
                shot = ImageGrab.grab().convert("RGB")
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
            if not self._sleep(0.7):
                return None
        return None

    # ---------- playback ----------
    def toggle_play(self):
        self.abort.set() if self.playing else self.start_play()

    def start_play(self):
        if self.recording or self.playing:
            return
        if not self.events:
            self.set_status(GREY, "Record or load a macro first")
            return
        self.brain = BRAINS[self.brain_menu.get()]
        if self.brain == "plugin":
            try:
                self.plugin = load_plugin()
            except Exception as exc:
                self.set_status(GREY, "my_model.py error")
                print("Plugin error:", exc)
                return
        try:
            repeat = max(1, int(self.repeat.get()))
        except ValueError:
            repeat = 1
        speed = float(self.speed.get().rstrip("x"))
        self.playing, self.prog, self.fail = True, 0.0, ""
        self.abort.clear()
        self.set_status(GREEN, f"Starting in {COUNTDOWN}s")
        self.refresh_buttons()
        self.after(800, self.iconify)
        threading.Thread(target=self._play, args=(repeat, speed), daemon=True).start()

    def _sleep(self, sec):
        end = time.time() + sec
        while time.time() < end:
            if self.abort.is_set():
                return False
            time.sleep(0.02)
        return True

    def _stopped(self):
        self.ui(self._end, self.fail or "Stopped")

    def _play(self, repeat, speed):
        if not self._sleep(COUNTDOWN):
            return self._stopped()
        total = len(self.events)
        for n in range(repeat):
            self.ui(self.set_status, GREEN, f"Playing {n + 1} of {repeat}")
            prev = 0.0
            for i, ev in enumerate(self.events):
                if not self._sleep((ev["t"] - prev) / speed):
                    return self._stopped()
                prev = ev["t"]
                self.prog = (n + i / total) / repeat
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
                        if hit is None:  # never click blindly
                            if not self.abort.is_set():
                                self.fail = "Target not found. Stopped"
                            self.abort.set()
                            return
                        self.cur = hit
                mouse_ctl.position = self.cur
                (mouse_ctl.press if ev["pressed"] else mouse_ctl.release)(getattr(mouse.Button, ev["button"]))
            elif ev["type"] == "scroll":
                mouse_ctl.position = (ev["x"], ev["y"])
                mouse_ctl.scroll(ev["dx"], ev["dy"])
            elif ev["type"] == "key":
                (kb_ctl.press if ev["pressed"] else kb_ctl.release)(data_to_key(ev["key"]))
        except Exception as exc:
            print("Action failed:", exc)

    def _end(self, msg):
        self.playing, self.prog = False, 0.0
        self.deiconify()
        self.lift()
        self.set_status(GREY, msg)
        self.refresh_buttons()

    # ---------- library ----------
    def refresh_library(self, select=None):
        names = sorted(p.stem for p in MACRO_DIR.glob("*.json"))
        self.menu.configure(values=names or ["No saved macros"])
        self.menu.set(select or (names[0] if names else "No saved macros"))

    def save(self):
        if not self.events:
            return self.set_status(GREY, "Nothing to save yet")
        raw = ctk.CTkInputDialog(text="Name this macro:", title="Save").get_input()
        if raw is None:
            return
        name = re.sub(r"[^\w\- ]", "", raw).strip() or time.strftime("macro-%H%M%S")
        (MACRO_DIR / f"{name}.json").write_text(json.dumps(self.events))
        self.refresh_library(select=name)
        self.set_status(GREY, f"Saved {name}")

    def load_named(self, name):
        path = MACRO_DIR / f"{name}.json"
        if path.exists():
            self.events = json.loads(path.read_text())
            self.update_count()
            self.set_status(GREY, f"Loaded {name}")

    def delete(self):
        path = MACRO_DIR / f"{self.menu.get()}.json"
        if path.exists():
            path.unlink()
            self.refresh_library()
            self.set_status(GREY, "Deleted")


if __name__ == "__main__":
    App().mainloop()