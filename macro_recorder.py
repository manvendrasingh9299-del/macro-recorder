"""
Macro Recorder v3 - record your clicks and keys, replay them. Optional AI "Smart replay"
uses Claude vision to find each button on screen, so macros survive moved windows
and slow page loads.

Hotkeys (work from any app):  F8 stop recording   F9 stop playback   F10 activate
"""
import base64, io, json, os, queue, re, threading, time, urllib.request
from pathlib import Path

import customtkinter as ctk
from PIL import ImageGrab
from pynput import keyboard, mouse

APP_DIR = Path.home() / "Library" / "Application Support" / "MacroRecorder"
MACRO_DIR = APP_DIR / "macros"
MACRO_DIR.mkdir(parents=True, exist_ok=True)
CONFIG = APP_DIR / "config.json"

MODEL = "claude-haiku-4-5-20251001"  # fast + cheap. For harder screens use "claude-sonnet-4-6"
K_STOP_REC, K_STOP_PLAY, K_PLAY = keyboard.Key.f8, keyboard.Key.f9, keyboard.Key.f10
RED, GREEN, GREY, BLUE = "#D64545", "#2E9E6B", "#8A8F98", "#3B5BDB"
COUNTDOWN, CROP_PT, SENT_W = 3, 140, 1280

mouse_ctl, kb_ctl = mouse.Controller(), keyboard.Controller()


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


def load_key():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    try:
        return json.loads(CONFIG.read_text()).get("api_key", "")
    except Exception:
        return ""


def ask_claude(key, crop_b64, shot_b64, prompt):
    img = lambda m, d: {"type": "image", "source": {"type": "base64", "media_type": m, "data": d}}
    body = {"model": MODEL, "max_tokens": 60, "messages": [{"role": "user", "content": [
        img("image/png", crop_b64), img("image/jpeg", shot_b64), {"type": "text", "text": prompt}]}]}
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", json.dumps(body).encode(),
        {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        text = json.load(r)["content"][0]["text"]
    return json.loads(re.search(r"\{.*\}", text, re.S).group())


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("system")
        self.title("Macro Recorder")
        self.geometry("360x440")
        self.resizable(False, False)
        self.update_idletasks()
        self.sw, self.sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.sent_w = min(self.sw, SENT_W)

        self.q = queue.Queue()
        self.events, self.t0, self.cur = [], 0.0, (0, 0)
        self.recording = self.capturing = self.playing = False
        self.abort = threading.Event()
        self.mouse_listener = None
        self.api_key = load_key()

        self._build()
        self.refresh_library()
        self.after(50, self._pump)
        keyboard.Listener(on_press=self.on_press, on_release=self.on_release).start()

    # ---------- UI ----------
    def _build(self):
        p = {"padx": 22}
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", pady=(18, 10), **p)
        ctk.CTkLabel(top, text="Macro Recorder", font=("Helvetica Neue", 22, "bold")).pack(side="left")
        ctk.CTkButton(top, text="API key", width=64, height=24, fg_color="transparent", border_width=1,
                      text_color=("gray20", "gray80"), command=self.ask_key).pack(side="right")

        self.pill = ctk.CTkLabel(self, text="Ready", fg_color=GREY, text_color="white", corner_radius=14, height=28)
        self.pill.pack(fill="x", **p)

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", pady=12, **p)
        row.columnconfigure((0, 1), weight=1, uniform="a")
        font = ("Helvetica Neue", 16, "bold")
        self.btn_rec = ctk.CTkButton(row, text="Record", height=60, corner_radius=12, fg_color=RED,
                                     hover_color="#B93636", font=font, command=self.toggle_record)
        self.btn_rec.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.btn_act = ctk.CTkButton(row, text="Activate", height=60, corner_radius=12, fg_color=GREEN,
                                     hover_color="#237A53", font=font, command=self.toggle_play)
        self.btn_act.grid(row=0, column=1, sticky="ew", padx=(5, 0))

        self.count = ctk.CTkLabel(self, text="No steps yet", text_color=GREY)
        self.count.pack(**p)

        self.smart = ctk.CTkSwitch(self, text="Smart replay (AI finds buttons)", progress_color=BLUE,
                                   command=self.on_smart)
        self.smart.pack(anchor="w", pady=(16, 6), **p)

        opts = ctk.CTkFrame(self, fg_color="transparent")
        opts.pack(fill="x", **p)
        ctk.CTkLabel(opts, text="Repeat").pack(side="left")
        self.repeat = ctk.CTkEntry(opts, width=50, justify="center")
        self.repeat.insert(0, "1")
        self.repeat.pack(side="left", padx=(8, 14))
        self.speed = ctk.CTkSegmentedButton(opts, values=["0.5x", "1x", "2x", "3x"], selected_color=BLUE)
        self.speed.set("1x")
        self.speed.pack(side="left")

        lib = ctk.CTkFrame(self, fg_color="transparent")
        lib.pack(fill="x", pady=(18, 0), **p)
        self.menu = ctk.CTkOptionMenu(lib, values=["No saved macros"], command=self.load_named)
        self.menu.pack(fill="x")
        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", pady=8, **p)
        ctk.CTkButton(btns, text="Save current", fg_color=BLUE, command=self.save).pack(side="left", expand=True, fill="x", padx=(0, 4))
        ctk.CTkButton(btns, text="Delete", fg_color="transparent", border_width=1,
                      text_color=("gray20", "gray80"), command=self.delete).pack(side="left", expand=True, fill="x", padx=(4, 0))

        ctk.CTkLabel(self, text="F8 stop recording   F9 stop playback   F10 activate",
                     text_color=GREY, font=("Helvetica Neue", 11)).pack(side="bottom", pady=10)

    def ui(self, fn, *a):
        self.q.put(lambda: fn(*a))

    def _pump(self):
        try:
            while True:
                self.q.get_nowait()()
        except queue.Empty:
            pass
        self.after(50, self._pump)

    def state(self, color, text):
        self.pill.configure(fg_color=color, text=text)

    def refresh_buttons(self):
        self.btn_rec.configure(text="Stop (F8)" if self.recording else "Record", state="disabled" if self.playing else "normal")
        self.btn_act.configure(text="Stop (F9)" if self.playing else "Activate", state="disabled" if self.recording else "normal")

    def update_count(self):
        n = sum(1 for e in self.events if e["type"] == "click" and e["pressed"] or e["type"] == "key" and e["pressed"])
        self.count.configure(text=f"{n} steps" if n else "No steps yet")

    def ask_key(self):
        key = ctk.CTkInputDialog(text="Paste your Anthropic API key (console.anthropic.com):", title="API key").get_input()
        if key:
            self.api_key = key.strip()
            CONFIG.write_text(json.dumps({"api_key": self.api_key}))
            CONFIG.chmod(0o600)
            self.state(GREY, "API key saved")
        return bool(self.api_key)

    def on_smart(self):
        if self.smart.get() and not self.api_key and not self.ask_key():
            self.smart.deselect()

    # ---------- recording ----------
    def toggle_record(self):
        self.stop_record() if self.recording else self.start_record()

    def start_record(self):
        if self.recording or self.playing:
            return
        self.recording, self.events = True, []
        self.update_count()
        self.state(RED, f"Recording starts in {COUNTDOWN}s")
        self.refresh_buttons()
        self.after(800, self.iconify)
        self.after(COUNTDOWN * 1000, self._begin_record)

    def _begin_record(self):
        if self.recording:
            self.t0, self.capturing = time.time(), True
            self.ui(self.state, RED, "Recording")
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
        self.state(GREY, "Recorded. Press Activate to replay")
        self.refresh_buttons()

    def grab_crop(self, x, y):
        """Small picture of what was clicked, used later by Smart replay."""
        try:
            shot = ImageGrab.grab().convert("RGB")
            s, half = shot.width / self.sw, int(CROP_PT * shot.width / self.sw / 2)
            cx, cy = int(x * s), int(y * s)
            c = shot.crop((max(cx - half, 0), max(cy - half, 0), cx + half, cy + half))
            f = self.sent_w / shot.width
            return b64(c.resize((max(1, int(c.width * f)), max(1, int(c.height * f)))))
        except Exception:
            return None  # no Screen Recording permission

    def on_click(self, x, y, button, pressed):
        if not self.capturing:
            return
        t = round(time.time() - self.t0, 3)
        ev = {"type": "click", "x": x, "y": y, "button": button.name, "pressed": pressed, "t": t}
        if pressed:
            ev["crop"] = self.grab_crop(x, y)
        self.events.append(ev)
        self.ui(self.update_count)

    def on_scroll(self, x, y, dx, dy):
        if self.capturing:
            self.events.append({"type": "scroll", "x": x, "y": y, "dx": dx, "dy": dy, "t": round(time.time() - self.t0, 3)})

    def on_press(self, key):
        if key == K_STOP_PLAY:
            self.abort.set()
        elif key == K_STOP_REC and self.recording:
            self.ui(self.stop_record)
        elif key == K_PLAY and not self.recording:
            self.ui(self.toggle_play)
        elif self.capturing:
            self.events.append({"type": "key", "pressed": True, "key": key_to_data(key), "t": round(time.time() - self.t0, 3)})
            self.ui(self.update_count)

    def on_release(self, key):
        if self.capturing and key not in (K_STOP_REC, K_STOP_PLAY, K_PLAY):
            self.events.append({"type": "key", "pressed": False, "key": key_to_data(key), "t": round(time.time() - self.t0, 3)})

    # ---------- playback ----------
    def toggle_play(self):
        self.abort.set() if self.playing else self.start_play()

    def start_play(self):
        if self.recording or self.playing:
            return
        if not self.events:
            self.state(GREY, "Record or load a macro first")
            return
        try:
            repeat = max(1, int(self.repeat.get()))
        except ValueError:
            repeat = 1
        speed, smart = float(self.speed.get().rstrip("x")), bool(self.smart.get())
        self.playing = True
        self.abort.clear()
        self.state(GREEN, f"Starting in {COUNTDOWN}s")
        self.refresh_buttons()
        self.after(800, self.iconify)
        threading.Thread(target=self._play, args=(repeat, speed, smart), daemon=True).start()

    def _sleep(self, sec):
        end = time.time() + sec
        while time.time() < end:
            if self.abort.is_set():
                return False
            time.sleep(0.02)
        return True

    def _play(self, repeat, speed, smart):
        if not self._sleep(COUNTDOWN):
            return self.ui(self._end, "Stopped")
        for n in range(repeat):
            self.ui(self.state, GREEN, f"Playing  run {n + 1} of {repeat}")
            prev = 0.0
            for ev in self.events:
                if not self._sleep((ev["t"] - prev) / speed):
                    return self.ui(self._end, "Stopped")
                prev = ev["t"]
                self._do(ev, smart)
            if n < repeat - 1 and not self._sleep(1):
                return self.ui(self._end, "Stopped")
        self.ui(self._end, "Finished")

    def find(self, ev):
        """Ask Claude where the recorded button is on the current screen (retries while the page loads)."""
        for _ in range(4):
            if self.abort.is_set():
                return None
            try:
                shot = ImageGrab.grab().convert("RGB")
                w, h = self.sent_w, round(shot.height * self.sent_w / shot.width)
                px, py = round(ev["x"] * w / self.sw), round(ev["y"] * h / self.sh)
                prompt = (f"Image 1 is a crop around a UI element I clicked earlier. Image 2 is my current screen ({w}x{h} px). "
                          f"Find the same element in image 2. It used to be near ({px}, {py}). "
                          'Reply with JSON only: {"found": true, "x": <int>, "y": <int>} for its center, or {"found": false}.')
                r = ask_claude(self.api_key, ev["crop"], b64(shot.resize((w, h)), "JPEG", quality=70), prompt)
                if r.get("found"):
                    return r["x"] * self.sw / w, r["y"] * self.sh / h
            except Exception as exc:
                print("Smart replay error:", exc)
            if not self._sleep(1.2):
                return None
        return None

    def _do(self, ev, smart):
        try:
            if ev["type"] == "click":
                if ev["pressed"]:
                    self.cur = (ev["x"], ev["y"])
                    if smart and self.api_key and ev.get("crop"):
                        self.ui(self.state, GREEN, "Looking for button…")
                        self.cur = self.find(ev) or self.cur
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
        self.playing = False
        self.deiconify()
        self.lift()
        self.state(GREY, msg)
        self.refresh_buttons()

    # ---------- library ----------
    def refresh_library(self, select=None):
        names = sorted(p.stem for p in MACRO_DIR.glob("*.json"))
        self.menu.configure(values=names or ["No saved macros"])
        self.menu.set(select or (names[0] if names else "No saved macros"))

    def save(self):
        if not self.events:
            return self.state(GREY, "Nothing to save yet")
        raw = ctk.CTkInputDialog(text="Name this macro:", title="Save").get_input()
        if raw is None:
            return
        name = re.sub(r"[^\w\- ]", "", raw).strip() or time.strftime("macro-%H%M%S")
        (MACRO_DIR / f"{name}.json").write_text(json.dumps(self.events))
        self.refresh_library(select=name)
        self.state(GREY, f"Saved {name}")

    def load_named(self, name):
        path = MACRO_DIR / f"{name}.json"
        if path.exists():
            self.events = json.loads(path.read_text())
            self.update_count()
            self.state(GREY, f"Loaded {name}")

    def delete(self):
        path = MACRO_DIR / f"{self.menu.get()}.json"
        if path.exists():
            path.unlink()
            self.refresh_library()
            self.state(GREY, "Deleted")


if __name__ == "__main__":
    App().mainloop()
