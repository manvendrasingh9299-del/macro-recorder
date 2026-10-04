"""
Macro Recorder v2 - record mouse + keyboard actions, replay them with one click.

    pip install -r requirements.txt
    python macro_recorder.py

Hotkeys (work from any app):  F8 stop recording   F9 stop playback   F10 activate
"""
import json
import queue
import re
import threading
import time
from pathlib import Path

import customtkinter as ctk
from pynput import keyboard, mouse

MACRO_DIR = Path(__file__).parent / "macros"
MACRO_DIR.mkdir(exist_ok=True)

K_STOP_REC, K_STOP_PLAY, K_PLAY = keyboard.Key.f8, keyboard.Key.f9, keyboard.Key.f10
RED, GREEN, GREY, INK = "#D64545", "#2E9E6B", "#8A8F98", "#3B5BDB"
COUNTDOWN = 3

mouse_ctl, kb_ctl = mouse.Controller(), keyboard.Controller()


def key_to_data(key):
    if isinstance(key, keyboard.KeyCode):
        return {"char": key.char} if key.char else {"vk": key.vk}
    return {"name": key.name}


def data_to_key(d):
    if "char" in d:
        return d["char"]
    if "vk" in d:
        return keyboard.KeyCode.from_vk(d["vk"])
    return getattr(keyboard.Key, d["name"])


def describe(ev):
    """Readable text for an event, or None for events not worth listing (releases)."""
    if ev["type"] == "click" and ev["pressed"]:
        return f"Click {ev['button']} at ({int(ev['x'])}, {int(ev['y'])})"
    if ev["type"] == "scroll":
        return "Scroll " + ("down" if ev["dy"] < 0 else "up")
    if ev["type"] == "key" and ev["pressed"]:
        k = ev["key"]
        return "Press " + str(k.get("char") or k.get("name") or f"key {k.get('vk')}")
    return None


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("system")
        self.title("Macro Recorder")
        self.geometry("440x680")
        self.minsize(420, 640)

        self.q = queue.Queue()
        self.events, self.t0 = [], 0.0
        self.recording = self.capturing = self.playing = False
        self.abort = threading.Event()
        self.mouse_listener = None

        self._build()
        self.refresh_library()
        self.after(50, self._pump)
        keyboard.Listener(on_press=self.on_press, on_release=self.on_release).start()

    # ---------- UI ----------
    def _build(self):
        pad = {"padx": 24}
        ctk.CTkLabel(self, text="Macro Recorder", font=("Helvetica Neue", 28, "bold")).pack(anchor="w", pady=(22, 0), **pad)
        ctk.CTkLabel(self, text="Do it once. Replay it any time.", text_color=GREY).pack(anchor="w", **pad)

        self.pill = ctk.CTkLabel(self, text="Ready", fg_color=GREY, text_color="white",
                                 corner_radius=14, height=28, width=200)
        self.pill.pack(anchor="w", pady=14, **pad)

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", **pad)
        row.columnconfigure((0, 1), weight=1, uniform="a")
        self.btn_rec = ctk.CTkButton(row, text="Record", height=56, corner_radius=12, fg_color=RED,
                                     hover_color="#B93636", font=("Helvetica Neue", 16, "bold"),
                                     command=self.toggle_record)
        self.btn_rec.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.btn_act = ctk.CTkButton(row, text="Activate", height=56, corner_radius=12, fg_color=GREEN,
                                     hover_color="#237A53", font=("Helvetica Neue", 16, "bold"),
                                     command=self.toggle_play)
        self.btn_act.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        ctk.CTkLabel(self, text="Steps", font=("Helvetica Neue", 14, "bold")).pack(anchor="w", pady=(18, 4), **pad)
        self.steps = ctk.CTkTextbox(self, height=190, corner_radius=10, font=("Menlo", 12), state="disabled")
        self.steps.pack(fill="x", **pad)
        self.log_empty()

        opts = ctk.CTkFrame(self, fg_color="transparent")
        opts.pack(fill="x", pady=(14, 0), **pad)
        ctk.CTkLabel(opts, text="Repeat").pack(side="left")
        self.repeat = ctk.CTkEntry(opts, width=56, justify="center")
        self.repeat.insert(0, "1")
        self.repeat.pack(side="left", padx=(8, 18))
        ctk.CTkLabel(opts, text="Speed").pack(side="left")
        self.speed = ctk.CTkSegmentedButton(opts, values=["0.5x", "1x", "2x", "3x"], selected_color=INK)
        self.speed.set("1x")
        self.speed.pack(side="left", padx=8)

        ctk.CTkLabel(self, text="Library", font=("Helvetica Neue", 14, "bold")).pack(anchor="w", pady=(18, 4), **pad)
        save = ctk.CTkFrame(self, fg_color="transparent")
        save.pack(fill="x", **pad)
        self.name = ctk.CTkEntry(save, placeholder_text="Name this macro")
        self.name.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(save, text="Save", width=70, fg_color=INK, command=self.save).pack(side="left", padx=(8, 0))

        lib = ctk.CTkFrame(self, fg_color="transparent")
        lib.pack(fill="x", pady=(8, 0), **pad)
        self.menu = ctk.CTkOptionMenu(lib, values=["No saved macros"], command=self.load_named)
        self.menu.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(lib, text="Delete", width=70, fg_color="transparent", border_width=1,
                      text_color=("gray20", "gray80"), command=self.delete).pack(side="left", padx=(8, 0))

        ctk.CTkLabel(self, text="F8 stops recording   F9 stops playback   F10 activates",
                     text_color=GREY, font=("Helvetica Neue", 12)).pack(side="bottom", pady=14)

    def ui(self, fn, *args):
        self.q.put(lambda: fn(*args))

    def _pump(self):
        try:
            while True:
                self.q.get_nowait()()
        except queue.Empty:
            pass
        self.after(50, self._pump)

    def set_state(self, color, text):
        self.pill.configure(fg_color=color, text=text)

    def refresh_buttons(self):
        self.btn_rec.configure(text="Stop (F8)" if self.recording else "Record",
                               state="disabled" if self.playing else "normal")
        self.btn_act.configure(text="Stop (F9)" if self.playing else "Activate",
                               state="disabled" if self.recording else "normal")

    def log(self, text):
        self.steps.configure(state="normal")
        self.steps.insert("end", text + "\n")
        self.steps.see("end")
        self.steps.configure(state="disabled")

    def log_clear(self):
        self.steps.configure(state="normal")
        self.steps.delete("1.0", "end")
        self.steps.configure(state="disabled")

    def log_empty(self):
        self.log("Nothing recorded yet. Press Record, then do the steps you want to repeat.")

    def show_events(self):
        self.log_clear()
        lines = [f"{e['t']:5.1f}s  {d}" for e in self.events if (d := describe(e))]
        if lines:
            for line in lines:
                self.log(line)
        else:
            self.log_empty()

    # ---------- recording ----------
    def toggle_record(self):
        self.stop_record() if self.recording else self.start_record()

    def start_record(self):
        if self.recording or self.playing:
            return
        self.recording, self.events = True, []
        self.log_clear()
        self.set_state(RED, f"Recording starts in {COUNTDOWN}s")
        self.refresh_buttons()
        self.after(800, self.iconify)
        self.after(COUNTDOWN * 1000, self._begin_record)

    def _begin_record(self):
        if not self.recording:
            return
        self.t0 = time.time()
        self.capturing = True
        self.set_state(RED, "Recording")
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
        self.show_events()
        self.set_state(GREY, f"Recorded {sum(1 for e in self.events if describe(e))} steps")
        self.refresh_buttons()

    def add(self, **ev):
        ev["t"] = round(time.time() - self.t0, 3)
        self.events.append(ev)
        if d := describe(ev):
            self.ui(self.log, f"{ev['t']:5.1f}s  {d}")

    def on_click(self, x, y, button, pressed):
        if self.capturing:
            self.add(type="click", x=x, y=y, button=button.name, pressed=pressed)

    def on_scroll(self, x, y, dx, dy):
        if self.capturing:
            self.add(type="scroll", x=x, y=y, dx=dx, dy=dy)

    def on_press(self, key):
        if key == K_STOP_PLAY:
            self.abort.set()
        elif key == K_STOP_REC and self.recording:
            self.ui(self.stop_record)
        elif key == K_PLAY and not self.recording:
            self.ui(self.toggle_play)
        elif self.capturing:
            self.add(type="key", pressed=True, key=key_to_data(key))

    def on_release(self, key):
        if self.capturing and key not in (K_STOP_REC, K_STOP_PLAY, K_PLAY):
            self.add(type="key", pressed=False, key=key_to_data(key))

    # ---------- playback ----------
    def toggle_play(self):
        self.abort.set() if self.playing else self.start_play()

    def start_play(self):
        if self.recording or self.playing:
            return
        if not self.events:
            self.set_state(GREY, "Record or load a macro first")
            return
        try:
            repeat = max(1, int(self.repeat.get()))
        except ValueError:
            repeat = 1
        speed = float(self.speed.get().rstrip("x"))
        self.playing = True
        self.abort.clear()
        self.set_state(GREEN, f"Starting in {COUNTDOWN}s")
        self.refresh_buttons()
        self.after(800, self.iconify)
        threading.Thread(target=self._play, args=(repeat, speed), daemon=True).start()

    def _sleep(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            if self.abort.is_set():
                return False
            time.sleep(0.02)
        return True

    def _play(self, repeat, speed):
        if not self._sleep(COUNTDOWN):
            return self.ui(self._end_play, "Stopped")
        for n in range(repeat):
            self.ui(self.set_state, GREEN, f"Playing  run {n + 1} of {repeat}")
            prev = 0.0
            for ev in self.events:
                if not self._sleep((ev["t"] - prev) / speed):
                    return self.ui(self._end_play, "Stopped")
                prev = ev["t"]
                self._do(ev)
            if n < repeat - 1 and not self._sleep(1):
                return self.ui(self._end_play, "Stopped")
        self.ui(self._end_play, "Finished")

    @staticmethod
    def _do(ev):
        try:
            if ev["type"] == "click":
                mouse_ctl.position = (ev["x"], ev["y"])
                btn = getattr(mouse.Button, ev["button"])
                (mouse_ctl.press if ev["pressed"] else mouse_ctl.release)(btn)
            elif ev["type"] == "scroll":
                mouse_ctl.position = (ev["x"], ev["y"])
                mouse_ctl.scroll(ev["dx"], ev["dy"])
            elif ev["type"] == "key":
                k = data_to_key(ev["key"])
                (kb_ctl.press if ev["pressed"] else kb_ctl.release)(k)
        except Exception as exc:  # one failed action shouldn't end the run
            print("Action failed:", exc)

    def _end_play(self, msg):
        self.playing = False
        self.deiconify()
        self.lift()
        self.set_state(GREY, msg)
        self.refresh_buttons()

    # ---------- library ----------
    def names(self):
        return sorted(p.stem for p in MACRO_DIR.glob("*.json"))

    def refresh_library(self, select=None):
        names = self.names()
        self.menu.configure(values=names or ["No saved macros"])
        self.menu.set(select or (names[0] if names else "No saved macros"))

    def save(self):
        if not self.events:
            self.set_state(GREY, "Nothing to save yet")
            return
        name = re.sub(r"[^\w\- ]", "", self.name.get()).strip() or time.strftime("macro-%H%M%S")
        (MACRO_DIR / f"{name}.json").write_text(json.dumps(self.events))
        self.refresh_library(select=name)
        self.name.delete(0, "end")
        self.set_state(GREY, f"Saved {name}")

    def load_named(self, name):
        path = MACRO_DIR / f"{name}.json"
        if path.exists():
            self.events = json.loads(path.read_text())
            self.show_events()
            self.set_state(GREY, f"Loaded {name}")

    def delete(self):
        path = MACRO_DIR / f"{self.menu.get()}.json"
        if path.exists():
            path.unlink()
            self.refresh_library()
            self.set_state(GREY, "Deleted")


if __name__ == "__main__":
    App().mainloop()