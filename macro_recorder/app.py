"""The Macro Recorder window: recording, replaying and saving macros."""
import queue
import re
import subprocess
import threading
import time
import tkinter as tk
from collections import deque
from tkinter import messagebox

import customtkinter as ctk
from pynput import keyboard, mouse

from . import macos, matching, settings
from .interface import Screen
from .learn import LearnMode

STOP_RECORD, STOP_PLAY, RUN = keyboard.Key.f8, keyboard.Key.f9, keyboard.Key.f10
COUNTDOWN = 3                                   # seconds before recording or playing starts
WAIT = 5.0                                      # seconds to look for a button before giving up
REPEATS, SPEEDS = [1, 2, 3, 5, 10, 25, 100], [0.5, 1, 2, 3]
BRAINS = ["local", "claude", "ollama", "plugin"]
BRAIN_LABELS = {"local": "LOCAL", "claude": "CLAUDE", "ollama": "OLLAMA", "plugin": "MY MODEL"}


def fast_delay(ev, gap):
    """How long the fast version waits before a step."""
    if ev["type"] == "click":
        return 0.12 if ev["pressed"] and ev.get("n", 1) == 1 else min(gap, 0.06)
    if ev["type"] == "key":
        return min(gap, 0.04) if gap < 0.3 else min(gap, 1.0)
    return min(gap, 0.1)


class App(Screen, ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("Macro Recorder")
        self.geometry("400x700")
        self.resizable(False, False)
        self.update_idletasks()
        self.sw, self.sh = self.winfo_screenwidth(), self.winfo_screenheight()

        self.cfg = settings.load()
        self.api_key = settings.api_key(self.cfg)
        self.tasks = queue.Queue()                       # lets other threads update the window
        self.events, self.t0, self.cur = [], 0.0, (0, 0)
        self.recording = self.capturing = self.playing = False
        self.abort = threading.Event()
        self.mouse_listener = None
        self.frames = deque(maxlen=4)                    # recent screenshots, for "just before the click"
        self.brain = self.smart_brain = "local"
        self.plugin, self.fail, self.learned, self.idx = None, "", {}, 0
        self.nsteps, self.anim = 0, 0
        self.repeat_n, self.speed_v, self.macro_name = 1, 1, "UNTITLED"
        self.last_click, self.click_n = (0.0, (0, 0), 0), 1
        self.strict = tk.BooleanVar(value=self.cfg.get("strict", False))
        self.learn_var = tk.BooleanVar(value=False)
        self.learner = LearnMode(self)

        self._build()
        self.refresh_lcd()
        self.after(50, self._pump)
        self.after(120, self._tick)
        keyboard.Listener(on_press=self.on_press, on_release=self.on_release).start()
        if self.cfg.get("learn") and self.cfg.get("learn_ok"):
            self.learn_var.set(True)
            self.after(1000, self.learner.start)

    # ---------- threads ----------
    def ui(self, fn, *args):
        self.tasks.put(lambda: fn(*args))

    def _pump(self):
        try:
            while True:
                self.tasks.get_nowait()()
        except queue.Empty:
            pass
        self.after(50, self._pump)

    # ---------- keys ----------
    def on_press(self, key):
        if key == STOP_PLAY:
            self.abort.set()
        elif key == STOP_RECORD and self.recording:
            self.ui(self.stop_record)
        elif key == RUN and not self.recording:
            self.ui(self.toggle_play)
        elif self.capturing:
            self.events.append({"type": "key", "pressed": True, "key": macos.key_to_data(key),
                                "t": round(time.time() - self.t0, 3)})
            self.ui(self.update_count)

    def on_release(self, key):
        if self.capturing and key not in (STOP_RECORD, STOP_PLAY, RUN):
            self.events.append({"type": "key", "pressed": False, "key": macos.key_to_data(key),
                                "t": round(time.time() - self.t0, 3)})

    # ---------- recording ----------
    def toggle_record(self):
        self.stop_record() if self.recording else self.start_record()

    def start_record(self):
        if self.recording or self.playing:
            return
        self.recording, self.events = True, []
        self.update_count()
        self.set_status(f"Recording in {COUNTDOWN}s")
        self.refresh_buttons()
        self.after(800, self.iconify)
        self.after(COUNTDOWN * 1000, self._begin_record)

    def _begin_record(self):
        if not self.recording:
            return
        self.frames.clear()
        self.last_click, self.click_n = (0.0, (0, 0), 0), 1
        self.t0, self.capturing = time.time(), True
        threading.Thread(target=self._watch, daemon=True).start()
        self.ui(self.set_status, "Recording")
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
        self.set_status("Recorded. Press RUN")
        self.refresh_buttons()

    def _watch(self):
        """While recording, keep a few recent screenshots."""
        while self.capturing:
            self.frames.append((time.time(), macos.grab_screen()))
            time.sleep(0.15)

    def grab_crop(self, x, y, when):
        """A picture of what was clicked, cut from the screen just BEFORE the click."""
        try:
            frames = list(self.frames)
            old = [f for f in frames if f[0] <= when - 0.1]
            shot = (old[-1] if old else frames[0] if frames else (0, macos.grab_screen()))[1]
            s = shot.width / self.sw
            half = int(matching.CROP_POINTS * s / 2)
            cx, cy = int(x * s), int(y * s)
            left, top = max(cx - half, 0), max(cy - half, 0)
            crop = shot.crop((left, top, cx + half, cy + half))
            return {"crop": matching.b64(crop), "ox": cx - left, "oy": cy - top}
        except Exception:
            return {}   # no Screen Recording permission

    def on_click(self, x, y, button, pressed):
        if not self.capturing:
            return
        try:
            now = time.time()
            ev = {"type": "click", "x": x, "y": y, "button": button.name, "pressed": pressed,
                  "t": round(now - self.t0, 3)}
            if pressed:
                last_t, last_pos, last_n = self.last_click
                near = abs(x - last_pos[0]) < 8 and abs(y - last_pos[1]) < 8
                self.click_n = last_n + 1 if now - last_t < 0.5 and near else 1
                self.last_click = (now, (x, y), self.click_n)
                if self.click_n == 1:                    # a double-click reuses the first click's picture
                    ev.update(self.grab_crop(x, y, now))
            ev["n"] = self.click_n
            self.events.append(ev)
            self.ui(self.update_count)
        except Exception as exc:
            print("Record error:", exc)

    def on_scroll(self, x, y, dx, dy):
        if self.capturing:
            self.events.append({"type": "scroll", "x": x, "y": y, "dx": dx, "dy": dy,
                                "t": round(time.time() - self.t0, 3)})

    # ---------- playing ----------
    def toggle_play(self):
        self.abort.set() if self.playing else self.start_play()

    def start_play(self):
        if self.recording or self.playing:
            return
        if not self.events:
            self.set_status("Record or load a macro first")
            return
        self.brain = self.smart_brain if self.smart.get() else "exact"
        if self.brain == "plugin":
            try:
                self.plugin = matching.load_plugin(settings.PLUGIN)
            except Exception as exc:
                self.set_status("my_model.py error")
                print("Plugin error:", exc)
                return
        self.playing, self.fail = True, ""
        self.abort.clear()
        self.set_status(f"Starting in {COUNTDOWN}s")
        self.refresh_buttons()
        self.after(800, self.iconify)
        threading.Thread(target=self._play, args=(self.repeat_n, self.speed_v), daemon=True).start()

    def _sleep(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            if self.abort.is_set():
                return False
            time.sleep(0.02)
        return True

    def _stopped(self):
        self.ui(self._end, self.fail or "Stopped")

    def _end(self, message):
        self.playing = False
        self.deiconify()
        self.lift()
        self.set_status(message)
        self.refresh_buttons()

    def _play(self, repeat, speed):
        fast = bool(self.events) and "fd" in self.events[0]
        self.learned = {}
        if self.brain == "ollama":
            self.ui(self.set_status, "Starting Ollama")
            problem = matching.ensure_ollama(self.cfg.get("ollama_model", matching.OLLAMA_DEFAULT))
            if problem:
                self.ui(self.set_status, problem)
        if not self._sleep(1 if fast else COUNTDOWN):
            return self._stopped()
        for n in range(repeat):
            self.ui(self.set_status, f"Playing {n + 1} of {repeat}")
            prev = 0.0
            for i, ev in enumerate(self.events):
                if not self._sleep((ev["fd"] if "fd" in ev else ev["t"] - prev) / speed):
                    return self._stopped()
                prev = ev["t"]
                self.idx = i
                self._do(ev)
            if n < repeat - 1 and not self._sleep(0.3 if fast else 1):
                return self._stopped()
        self.ui(self._end, "Finished")
        if not fast and self.learned and self.brain != "exact":
            self.ui(self.ask_fast)

    def _do(self, ev):
        try:
            if ev["type"] == "click":
                n = ev.get("n", 1)
                if ev["pressed"] and n == 1:
                    self.cur = (ev.get("fx", ev["x"]), ev.get("fy", ev["y"]))
                    if self.brain != "exact" and ev.get("crop") and "ox" in ev:
                        self.ui(self.set_status, "Finding target")
                        hit = self.find_target(ev)
                        if hit:
                            self.cur = hit
                            self.learned[self.idx] = hit
                        elif self.abort.is_set():
                            return
                        elif self.strict.get():
                            self.fail = "Target not found. Stopped"
                            self.abort.set()
                            return
                        else:
                            self.ui(self.set_status, "Not found, using saved spot")
                    macos.glide_to(*self.cur, fast="fd" in ev)
                macos.mouse_button(ev["button"], ev["pressed"], *self.cur, n)
            elif ev["type"] == "scroll":
                macos.scroll(ev["x"], ev["y"], ev["dx"], ev["dy"])
            elif ev["type"] == "key":
                macos.key_event(ev["key"], ev["pressed"])
        except Exception as exc:
            print("Action failed:", exc)

    def find_target(self, ev):
        """Image matching first (near the last known spot when this is a fast macro), then the chosen model."""
        near = (ev.get("fx", ev["x"]), ev.get("fy", ev["y"])) if "fd" in ev else None
        end, tries = time.time() + WAIT, 0
        while time.time() < end and not self.abort.is_set():
            try:
                shot = macos.grab_screen()
                hit = (near and matching.locate(ev, shot, self.sw, near)) or matching.locate(ev, shot, self.sw)
                if hit:
                    return hit
                if self.brain in ("claude", "ollama", "plugin") and tries < 2:
                    tries += 1
                    hit = matching.ask_model(self.brain, ev, shot, self.sw, self.sh,
                                             self.cfg, self.api_key, self.plugin)
                    if hit:
                        return hit
            except Exception as exc:
                print("Find error:", exc)
            if not self._sleep(0.15 if "fd" in ev else 0.5):
                return None
        return None

    def ask_fast(self):
        if messagebox.askyesno("Was it right?", "Did the macro do the task correctly?\n\n"
                               "YES  = save a FAST version (next runs skip the waiting)\n"
                               "NO   = keep the macro as it is", parent=self):
            self.make_fast()

    def make_fast(self):
        prev = 0.0
        for i, ev in enumerate(self.events):
            gap = max(0.0, ev["t"] - prev)
            prev = ev["t"]
            if i in self.learned:
                ev["fx"], ev["fy"] = self.learned[i]
            ev["fd"] = fast_delay(ev, gap)
        if settings.macro_exists(self.macro_name):
            settings.write_macro(self.macro_name, self.events)
            self.set_status("Saved as FAST macro")
        else:
            self.set_status("Name it to keep the FAST macro")
            self.save()

    # ---------- saved macros ----------
    def save(self):
        if not self.events:
            return self.set_status("Nothing to save yet")
        raw = ctk.CTkInputDialog(text="Name this macro:", title="Save").get_input()
        if raw is None:
            return
        name = re.sub(r"[^\w\- ]", "", raw).strip() or time.strftime("macro-%H%M%S")
        settings.write_macro(name, self.events)
        self.macro_name = name
        self.refresh_lcd()
        self.set_status(f"Saved {name}")

    def load_named(self, name):
        self.events = settings.read_macro(name)
        self.macro_name = name
        self.update_count()
        self.refresh_lcd()
        self.set_status(f"Loaded {name}")

    def delete_named(self, name):
        settings.delete_macro(name)
        self.set_status(f"Deleted {name}")

    # ---------- settings ----------
    def cycle_repeat(self):
        self.repeat_n = REPEATS[(REPEATS.index(self.repeat_n) + 1) % len(REPEATS)]
        self.refresh_lcd()

    def cycle_speed(self):
        self.speed_v = SPEEDS[(SPEEDS.index(self.speed_v) + 1) % len(SPEEDS)]
        self.refresh_lcd()

    def cycle_brain(self):
        nxt = BRAINS[(BRAINS.index(self.smart_brain) + 1) % len(BRAINS)]
        if nxt == "claude" and not self.api_key and not self.ask_key():
            return
        if nxt == "ollama" and not self.cfg.get("ollama_model"):
            self.cfg["ollama_model"] = matching.OLLAMA_DEFAULT
            settings.save(self.cfg)
        if nxt == "plugin" and not settings.PLUGIN.exists():
            settings.PLUGIN.write_text(settings.PLUGIN_TEMPLATE)
        self.smart_brain = nxt
        self.brain_label.configure(text=BRAIN_LABELS[nxt])
        self.set_status("Edit my_model.py in the folder" if nxt == "plugin" else f"Brain: {BRAIN_LABELS[nxt]}")

    def ask_key(self):
        key = ctk.CTkInputDialog(text="Paste your Anthropic API key (console.anthropic.com):",
                                 title="API key").get_input()
        if key:
            self.api_key = key.strip()
            self.cfg["api_key"] = self.api_key
            settings.save(self.cfg)
            self.set_status("API key saved")
        return bool(self.api_key)

    def ask_model(self):
        name = ctk.CTkInputDialog(text=f"Ollama vision model (default {matching.OLLAMA_DEFAULT}):",
                                  title="Ollama model").get_input()
        if name is not None:
            self.cfg["ollama_model"] = name.strip() or matching.OLLAMA_DEFAULT
            settings.save(self.cfg)
            self.set_status(f"Model {self.cfg['ollama_model']}")

    def save_strict(self):
        self.cfg["strict"] = self.strict.get()
        settings.save(self.cfg)

    def toggle_learn(self):
        if self.learn_var.get():
            if not self.cfg.get("learn_ok"):
                agreed = messagebox.askokcancel(
                    "Learn from my day",
                    "While this is on, the app saves a screenshot, a small picture of what you click, "
                    "and the click position, on THIS Mac only.\n\n"
                    "It does NOT save what you type, and it skips password managers.\n"
                    "Screenshots can still show private content. Press Fn+F7 to pause any time.\n\n"
                    "Turn it on?", parent=self)
                if not agreed:
                    self.learn_var.set(False)
                    return
                self.cfg["learn_ok"] = True
            self.learner.start()
        else:
            self.learner.stop()
        self.cfg["learn"] = bool(self.learn_var.get())
        settings.save(self.cfg)

    def delete_learned(self):
        if messagebox.askyesno("Delete learned data", "Delete ALL saved screenshots and click data?", parent=self):
            self.learner.delete_all()
            self.set_status("Learned data deleted")

    def open_path(self, path):
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(path)])

    def settings_menu(self):
        count, gb = self.learner.stats()
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Anthropic API key...", command=self.ask_key)
        menu.add_command(label="Ollama model...", command=self.ask_model)
        menu.add_checkbutton(label="Stop if target not found", variable=self.strict, command=self.save_strict)
        menu.add_separator()
        menu.add_checkbutton(label="Learn from my day", variable=self.learn_var, command=self.toggle_learn)
        menu.add_command(label=f"{count} examples, {gb:.2f} GB saved", state="disabled")
        menu.add_command(label="Open learned data", command=lambda: self.open_path(settings.LEARN_DIR))
        menu.add_command(label="Delete learned data...", command=self.delete_learned)
        menu.add_separator()
        menu.add_command(label="Open app folder", command=lambda: self.open_path(settings.APP_DIR))
        menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
