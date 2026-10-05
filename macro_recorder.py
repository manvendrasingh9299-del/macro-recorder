"""
Macro Recorder v6 - retro handheld UI. Record clicks + keys, replay them.
Hotkeys (hold Fn on a MacBook):  F8 stop recording   F9 stop playback   F10 run
Brains: Exact positions | LOCAL (OpenCV, free) | + CLAUDE | + OLLAMA (small local model) | + MY MODEL
"""
import base64, importlib.util, io, json, math, os, queue, re, subprocess, threading, time
import tkinter as tk, urllib.request
from pathlib import Path

import cv2
import customtkinter as ctk
import numpy as np
from PIL import Image, ImageDraw, ImageGrab
from pynput import keyboard, mouse
from Quartz import (CGEventCreateMouseEvent, CGEventPost, CGEventSetIntegerValueField,
                    kCGHIDEventTap, kCGMouseEventClickState, kCGEventMouseMoved,
                    kCGEventLeftMouseDown, kCGEventLeftMouseUp,
                    kCGEventRightMouseDown, kCGEventRightMouseUp,
                    kCGEventOtherMouseDown, kCGEventOtherMouseUp,
                    kCGMouseButtonLeft, kCGMouseButtonRight, kCGMouseButtonCenter)

APP_DIR = Path.home() / "Library" / "Application Support" / "MacroRecorder"
MACRO_DIR = APP_DIR / "macros"
MACRO_DIR.mkdir(parents=True, exist_ok=True)
CONFIG, PLUGIN = APP_DIR / "config.json", APP_DIR / "my_model.py"

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
OLLAMA_DEFAULT = "qwen2.5vl:3b"
SMART = ["local", "claude", "ollama", "plugin"]
BRAIN_NAME = {"local": "LOCAL", "claude": "CLAUDE", "ollama": "OLLAMA", "plugin": "MY MODEL"}
K_STOP_REC, K_STOP_PLAY, K_PLAY = keyboard.Key.f8, keyboard.Key.f9, keyboard.Key.f10

BODY, BODY_DK, LCD, LCD_EDGE, INK = "#B8CC74", "#A7BC63", "#C9D4B3", "#98A584", "#3C4A33"
MAG, MAG_HI, MAG_DK, MAG_DIM, REC_RED, RUN_GREEN, PILL = (
    "#B5246F", "#D8579A", "#7C1048", "#8C5F76", "#E8452C", "#2E9E6B", "#3A3A3C")
ACCENT = RED = GREEN = MAG
GREY = INK
COUNTDOWN, CROP_PT, SENT_W = 3, 140, 1024
MATCH_MIN, WAIT_S = 0.80, 8.0   # local match confidence, seconds to wait for a target
REPEATS, SPEEDS = [1, 2, 3, 5, 10, 25, 100], [0.5, 1, 2, 3]
SCENE_W, SCENE_H, PX = 100, 72, 4   # scene is painted at 100x72 and zoomed x4

PLUGIN_TEMPLATE = '''"""Your own model. Called when local matching fails (brain: MY MODEL).

crop   : PIL RGB image of what was clicked (screen pixels)
screen : PIL RGB image of the current screen (screen pixels)
hint   : (x, y) where it was when recorded (screen pixels)
Return (x, y) of the target in screen pixels, or None if not found.
"""
def find(crop, screen, hint):
    # Load your ONNX / PyTorch / CoreML model here and run it.
    return None
'''

mouse_ctl, kb_ctl = mouse.Controller(), keyboard.Controller()

BTN = {"left": (kCGEventLeftMouseDown, kCGEventLeftMouseUp, kCGMouseButtonLeft),
       "right": (kCGEventRightMouseDown, kCGEventRightMouseUp, kCGMouseButtonRight),
       "middle": (kCGEventOtherMouseDown, kCGEventOtherMouseUp, kCGMouseButtonCenter)}


def post_mouse(kind, x, y, button=kCGMouseButtonLeft, count=1):
    ev = CGEventCreateMouseEvent(None, kind, (x, y), button)
    CGEventSetIntegerValueField(ev, kCGMouseEventClickState, count)
    CGEventPost(kCGHIDEventTap, ev)


def move_to(x, y):
    post_mouse(kCGEventMouseMoved, x, y)
    time.sleep(0.12)  # let the app under the pointer notice it


# ---------- small helpers ----------
def mono(size, bold=False):
    return ("Menlo", size, "bold" if bold else "normal")


def lerp(a, b, t):
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(pa, pb))


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
    body = {"model": model, "stream": False, "keep_alive": "30m", "options": {"temperature": 0},
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


# ---------- pixel art ----------
def make_scene():
    im = Image.new("RGB", (SCENE_W, SCENE_H))
    d = ImageDraw.Draw(im)
    for y in range(SCENE_H):  # banded sky
        d.line([(0, y), (SCENE_W, y)], fill=lerp("#6EC1EE", "#CFEAFB", min(y // 6, 9) / 9))
    for cx, cy, w in ((14, 10, 12), (62, 7, 16), (86, 20, 10), (34, 24, 9)):  # clouds
        d.rounded_rectangle([cx - w, cy - 3, cx + w, cy + 3], 3, fill="#FFFFFF")
        d.rounded_rectangle([cx - w // 2, cy - 5, cx + w // 2, cy], 2, fill="#FFFFFF")
    d.polygon([(0, 56), (22, 30), (38, 40), (56, 18), (78, 38), (100, 28), (100, 58), (0, 58)], fill="#A9BDEB")
    d.polygon([(40, 58), (56, 18), (70, 40), (78, 58)], fill="#C9D6F4")
    d.polygon([(50, 30), (56, 18), (62, 30), (56, 27)], fill="#FFFFFF")      # snow cap
    d.polygon([(54, 22), (56, 6), (58, 22)], fill="#F4B6D2")                  # castle spires
    d.polygon([(60, 24), (62, 10), (64, 24)], fill="#F4B6D2")
    d.ellipse([-10, 44, 40, 70], fill="#6DB36B")
    d.ellipse([70, 36, 112, 70], fill="#4E9A5B")
    d.ellipse([80, 40, 100, 62], fill="#5FAF66")
    d.rectangle([0, 52, SCENE_W, SCENE_H], fill="#BBD958")                    # grass
    d.rectangle([0, 60, SCENE_W, SCENE_H], fill="#A9CB4B")
    d.rectangle([14, 40, 36, 54], fill="#9A6B45")                             # house
    d.polygon([(11, 41), (25, 30), (39, 41)], fill="#C95A3B")
    d.rectangle([17, 44, 21, 48], fill="#F2C94C")
    d.rectangle([28, 44, 32, 48], fill="#F2C94C")
    d.rectangle([23, 47, 26, 54], fill="#5B3A29")
    for x, y, c in ((6, 64, "#F06FA8"), (20, 67, "#FFE066"), (46, 66, "#F06FA8"),
                    (70, 68, "#FFE066"), (90, 65, "#F06FA8"), (34, 69, "#FFFFFF")):
        d.rectangle([x, y, x + 1, y + 1], fill=c)
    return im


def to_photo(im):
    return tk.PhotoImage(data=b"P6 %d %d 255\n" % im.size + im.convert("RGB").tobytes(), format="PPM")


CAT = [".o.....o.", "ooo...ooo", "ooooooooo", "oKooooKoo", "ooooPoooo",
       "owwwwwwwo", ".owwwwwo.", ".owwwwwo.", ".oo...oo."]
CAT_COL = {"o": "#F29A4A", "w": "#FFF3E0", "K": "#2F2323", "P": "#E86A8A"}
ICON_COL = {"o": "#8E948A", "w": "#B8BDB2", "K": "#5B6155", "P": "#5B6155"}


def draw_sprite(cv, rows, x, y, px, colors, tag, blink=False, tail=False):
    cv.delete(tag)
    for r, line in enumerate(rows):
        for c, ch in enumerate(line):
            col = colors.get(ch)
            if blink and ch == "K":
                col = colors["o"]
            if col:
                cv.create_rectangle(x + c * px, y + r * px, x + (c + 1) * px, y + (r + 1) * px,
                                    fill=col, outline="", tags=tag)
    tx, ty = x + 9 * px, y + 6 * px
    for dx, dy in ((0, 0), (1, -1 if tail else 1)):
        cv.create_rectangle(tx + dx * px, ty + dy * px, tx + (dx + 1) * px, ty + (dy + 1) * px,
                            fill=colors["o"], outline="", tags=tag)


def round_rect(cv, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
           x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


def clickable(cv, tag, cmd):
    cv.tag_bind(tag, "<Button-1>", lambda e: cmd())
    cv.tag_bind(tag, "<Enter>", lambda e: cv.config(cursor="hand2"))
    cv.tag_bind(tag, "<Leave>", lambda e: cv.config(cursor=""))


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("Macro Recorder")
        self.configure(fg_color=BODY)
        self.geometry("400x700")
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
        self.brain, self.smart_brain, self.plugin, self.fail = "local", "local", None, ""
        self.nsteps, self.anim = 0, 0
        self.repeat_n, self.speed_v = 1, 1
        self.macro_name = "UNTITLED"
        self.click_n, self.last_click = 1, (0.0, (0, 0))

        self._build()
        self.refresh_lcd()
        self.after(50, self._pump)
        self.after(120, self._tick)
        keyboard.Listener(on_press=self.on_press, on_release=self.on_release).start()

    # ---------- UI ----------
    def _icon_btn(self, parent, text, cmd, x, y, color=INK):
        ctk.CTkButton(parent, text=text, width=38, height=38, corner_radius=8, font=mono(16, True),
                      fg_color="#F4EFD8", hover_color="#E3DCB8", text_color=color, border_width=2,
                      border_color="#CFC8A6", command=cmd).place(x=x, y=y)

    def _pill(self, parent, label, cmd):
        f = ctk.CTkFrame(parent, fg_color=BODY_DK, corner_radius=16)
        f.pack(side="left", padx=(0, 8))
        ctk.CTkButton(f, text="", width=62, height=20, corner_radius=10, fg_color=PILL,
                      hover_color="#55555A", command=cmd).pack(padx=8, pady=(9, 3))
        lbl = ctk.CTkLabel(f, text=label, font=mono(10, True), text_color=INK)
        lbl.pack(pady=(0, 8))
        return lbl

    def _round_btn(self, cv, cx, cy, tag, text, cmd):
        cv.create_oval(cx - 35, cy - 31, cx + 35, cy + 39, fill=MAG_DK, outline="", tags=tag)
        cv.create_oval(cx - 34, cy - 34, cx + 34, cy + 34, fill=MAG, outline=MAG_DK, width=2, tags=(tag, tag + "_f"))
        cv.create_oval(cx - 23, cy - 27, cx - 7, cy - 15, fill=MAG_HI, outline="", tags=tag)
        cv.create_text(cx, cy + 2, text=text, fill="#FFFFFF", font=mono(12, True), tags=(tag, tag + "_t"))
        clickable(cv, tag, cmd)

    def _build(self):
        # pixel scene + top bar
        holder = ctk.CTkFrame(self, fg_color="transparent", width=400, height=SCENE_H * PX, corner_radius=0)
        holder.pack()
        holder.pack_propagate(False)
        self.scene = tk.Canvas(holder, width=400, height=SCENE_H * PX, highlightthickness=0, bg=BODY)
        self.scene.place(x=0, y=0)
        self.bg = to_photo(make_scene()).zoom(PX)
        self.scene.create_image(0, 0, anchor="nw", image=self.bg)
        for dx, dy, col in ((2, 2, "#2B2B2B"), (0, 0, "#FFFFFF")):
            self.scene.create_text(202 + dx, 70 + dy, text="", tags="badge", fill=col, font=mono(16, True))
        for dx, dy, col in ((2, 2, "#3A2A2A"), (0, 0, "#FF4D6D")):
            self.scene.create_text(66 + dx, 29 + dy, text="♥ 0", tags="hearts", anchor="w", fill=col, font=mono(18, True))
        self._icon_btn(holder, "◆", self.open_folder, 14, 10, "#D99A00")
        self._icon_btn(holder, "i", lambda: self.set_status(GREY, "Fn+F8 stop rec, Fn+F9 stop, Fn+F10 run"), 304, 10)
        self._icon_btn(holder, "⚙", self.settings_menu, 348, 10)

        ctk.CTkLabel(self, text="BUILD ANYTHING WITH INTELLIGENCE _", font=mono(9),
                     text_color=INK).pack(side="bottom", pady=10)

        # LCD
        self.lcd = cv = tk.Canvas(self, width=364, height=140, bg=BODY, highlightthickness=0)
        cv.pack(pady=(14, 0))
        round_rect(cv, 3, 3, 361, 137, 24, fill=LCD, outline=LCD_EDGE, width=3)
        draw_sprite(cv, CAT, 34, 16, 5, ICON_COL, "icon", tail=True)
        cv.create_text(20, 84, text="", tags="name", anchor="w", fill=INK, font=mono(12, True))
        cv.create_text(20, 114, text="READY", tags="status", anchor="w", fill=INK, font=mono(10), width=164)
        cv.create_line(188, 22, 188, 118, fill=LCD_EDGE, width=2)
        for y, label, tag in ((34, "STEPS", "steps"), (70, "REPEAT", "rep"), (106, "SPEED", "spd")):
            cv.create_text(204, y, text=label, anchor="w", fill=INK, font=mono(11))
            cv.create_text(346, y, text="", anchor="e", tags=tag, fill=INK, font=mono(13, True))
        for tag, cmd in (("name", self.save), ("rep", self.cycle_repeat), ("spd", self.cycle_speed)):
            clickable(cv, tag, cmd)

        # controls
        ctrl = ctk.CTkFrame(self, fg_color="transparent")
        ctrl.pack(fill="x", padx=18, pady=(8, 0))
        left = ctk.CTkFrame(ctrl, fg_color="transparent")
        left.pack(side="left", anchor="n")
        self.smart = ctk.CTkSwitch(left, text="Smart replay", font=mono(12, True), text_color=INK,
                                   progress_color=MAG, button_color="#F1E6EE", fg_color="#7A8A55")
        self.smart.select()
        self.smart.pack(anchor="w", pady=(14, 14))
        pills = ctk.CTkFrame(left, fg_color="transparent")
        pills.pack(anchor="w")
        self._pill(pills, "Macros", self.open_library)
        self.lbl_brain = self._pill(pills, BRAIN_NAME["local"], self.cycle_brain)

        self.pad = pad = tk.Canvas(ctrl, width=180, height=190, bg=BODY, highlightthickness=0)
        pad.pack(side="right")
        pad.create_line(50, 138, 126, 72, width=104, capstyle="round", fill=BODY_DK)
        self._round_btn(pad, 50, 138, "rec", "REC", self.toggle_record)
        self._round_btn(pad, 126, 72, "act", "RUN", self.toggle_play)

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
        a = self.anim
        x, y = 250, 200
        if self.recording:
            x = 70 + int(130 * (1 + math.sin(a / 6)))
        elif self.playing:
            x, y = 40 + (a * 4) % 300, 200 - int(abs(math.sin(a / 2)) * 16)
        badge = "● REC" if self.recording and a % 8 < 5 else ("▶ PLAY" if self.playing else "")
        self.scene.itemconfigure("badge", text=badge)
        draw_sprite(self.scene, CAT, x, y, 4, CAT_COL, "cat", blink=a % 26 < 2, tail=a % 6 < 3)
        self.after(120, self._tick)

    def set_status(self, color, text):
        self.lcd.itemconfigure("status", text=text.upper())

    def refresh_lcd(self):
        self.lcd.itemconfigure("name", text=f"{self.macro_name.upper()[:12]} ✎")
        self.lcd.itemconfigure("rep", text=f"x{self.repeat_n} ▸")
        self.lcd.itemconfigure("spd", text=f"{self.speed_v:g}x ▸")
        self.lcd.itemconfigure("steps", text=str(self.nsteps))

    def refresh_buttons(self):
        p = self.pad
        p.itemconfigure("rec_f", fill=REC_RED if self.recording else (MAG_DIM if self.playing else MAG))
        p.itemconfigure("rec_t", text="STOP" if self.recording else "REC")
        p.itemconfigure("act_f", fill=RUN_GREEN if self.playing else (MAG_DIM if self.recording else MAG))
        p.itemconfigure("act_t", text="STOP" if self.playing else "RUN")

    def update_count(self):
        self.nsteps = sum(1 for e in self.events if e["type"] in ("click", "key") and e["pressed"])
        self.lcd.itemconfigure("steps", text=str(self.nsteps))
        self.scene.itemconfigure("hearts", text=f"♥ {self.nsteps}")

    # ---------- settings ----------
    def open_folder(self):
        subprocess.run(["open", str(APP_DIR)])

    def settings_menu(self):
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="Anthropic API key…", command=self.ask_key)
        m.add_command(label="Ollama model…", command=self.ask_model)
        m.add_command(label="Open app folder", command=self.open_folder)
        m.add_separator()
        m.add_command(label="Fn+F8 stop rec   Fn+F9 stop play   Fn+F10 run", state="disabled")
        m.tk_popup(self.winfo_pointerx(), self.winfo_pointery())

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
        name = ctk.CTkInputDialog(text=f"Ollama vision model (default {OLLAMA_DEFAULT}):",
                                  title="Ollama model").get_input()
        if name is not None:
            self.cfg["ollama_model"] = name.strip() or OLLAMA_DEFAULT
            save_cfg(self.cfg)
            self.set_status(GREY, f"Model {self.cfg['ollama_model']}")

    def cycle_repeat(self):
        i = REPEATS.index(self.repeat_n) if self.repeat_n in REPEATS else 0
        self.repeat_n = REPEATS[(i + 1) % len(REPEATS)]
        self.refresh_lcd()

    def cycle_speed(self):
        i = SPEEDS.index(self.speed_v) if self.speed_v in SPEEDS else 1
        self.speed_v = SPEEDS[(i + 1) % len(SPEEDS)]
        self.refresh_lcd()

    def cycle_brain(self):
        nxt = SMART[(SMART.index(self.smart_brain) + 1) % len(SMART)]
        if nxt == "claude" and not self.api_key and not self.ask_key():
            return
        if nxt == "ollama" and not self.cfg.get("ollama_model"):
            self.cfg["ollama_model"] = OLLAMA_DEFAULT
            save_cfg(self.cfg)
        if nxt == "plugin" and not PLUGIN.exists():
            PLUGIN.write_text(PLUGIN_TEMPLATE)
        self.smart_brain = nxt
        self.lbl_brain.configure(text=BRAIN_NAME[nxt])
        self.set_status(GREY, "Edit my_model.py in the folder" if nxt == "plugin" else f"Brain: {BRAIN_NAME[nxt]}")

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
        self.macro_name = "UNTITLED"
        self.refresh_lcd()
        self.set_status(GREY, "Recorded. Press RUN")
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
        crop = Image.open(io.BytesIO(base64.b64decode(ev["crop"]))).convert("RGB")
        if self.brain == "plugin":
            r = self.plugin.find(crop, shot, (ev["x"] * s, ev["y"] * s))
            return (r[0] / s, r[1] / s) if r else None
        w, h = self.sent_w, round(shot.height * self.sent_w / shot.width)
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
            r = ask_ollama(self.cfg.get("ollama_model", OLLAMA_DEFAULT), c_b64, s_b64, prompt)
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
        self.brain = self.smart_brain if self.smart.get() else "exact"
        if self.brain == "plugin":
            try:
                self.plugin = load_plugin()
            except Exception as exc:
                self.set_status(GREY, "my_model.py error")
                print("Plugin error:", exc)
                return
        self.playing, self.fail = True, ""
        self.abort.clear()
        self.set_status(GREEN, f"Starting in {COUNTDOWN}s")
        self.refresh_buttons()
        self.after(800, self.iconify)
        threading.Thread(target=self._play, args=(self.repeat_n, self.speed_v), daemon=True).start()

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
                        if hit is None:  # never click blindly
                            if not self.abort.is_set():
                                self.fail = "Target not found. Stopped"
                            self.abort.set()
                            return
                        self.cur = hit
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

    def _end(self, msg):
        self.playing = False
        self.deiconify()
        self.lift()
        self.set_status(GREY, msg)
        self.refresh_buttons()

    # ---------- library ----------
    def save(self):
        if not self.events:
            return self.set_status(GREY, "Nothing to save yet")
        raw = ctk.CTkInputDialog(text="Name this macro:", title="Save").get_input()
        if raw is None:
            return
        name = re.sub(r"[^\w\- ]", "", raw).strip() or time.strftime("macro-%H%M%S")
        (MACRO_DIR / f"{name}.json").write_text(json.dumps(self.events))
        self.macro_name = name
        self.refresh_lcd()
        self.set_status(GREY, f"Saved {name}")

    def load_named(self, name):
        path = MACRO_DIR / f"{name}.json"
        if path.exists():
            self.events = json.loads(path.read_text())
            self.macro_name = name
            self.update_count()
            self.refresh_lcd()
            self.set_status(GREY, f"Loaded {name}")

    def delete_named(self, name):
        path = MACRO_DIR / f"{name}.json"
        if path.exists():
            path.unlink()
            self.set_status(GREY, f"Deleted {name}")

    def open_library(self):
        names = sorted(p.stem for p in MACRO_DIR.glob("*.json"))
        win = ctk.CTkToplevel(self)
        win.title("Macros")
        win.geometry("320x380")
        win.configure(fg_color=BODY)
        win.after(100, win.lift)
        ctk.CTkLabel(win, text="SAVED MACROS", font=mono(12, True), text_color=INK).pack(pady=(14, 8))
        box = ctk.CTkScrollableFrame(win, fg_color=LCD, corner_radius=14)
        box.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        if not names:
            ctk.CTkLabel(box, text="Nothing saved yet.\nTap the name on the screen to save.",
                         font=mono(10), text_color=INK).pack(pady=20)
        for n in names:
            row = ctk.CTkFrame(box, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkButton(row, text=n.upper(), anchor="w", font=mono(11), fg_color=BODY_DK, hover_color=BODY,
                          text_color=INK, command=lambda n=n: (self.load_named(n), win.destroy())
                          ).pack(side="left", fill="x", expand=True)
            ctk.CTkButton(row, text="✕", width=32, font=mono(12, True), fg_color="transparent",
                          hover_color=BODY, text_color=INK,
                          command=lambda n=n: (self.delete_named(n), win.destroy())).pack(side="left", padx=(6, 0))


if __name__ == "__main__":
    App().mainloop()