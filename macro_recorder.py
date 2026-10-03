"""
Macro Recorder - records your mouse + keyboard actions and replays them.

Setup (Terminal):
    pip3 install pynput
    python3 macro_recorder.py

Hotkeys:
    F8 = stop recording
    F9 = emergency stop during playback
"""
import json
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox

from pynput import keyboard, mouse

STOP_RECORD_KEY = keyboard.Key.f8
STOP_PLAY_KEY = keyboard.Key.f9

mouse_ctl = mouse.Controller()
kb_ctl = keyboard.Controller()


# ---------- key (de)serialisation ----------
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


class App:
    def __init__(self, root):
        self.root = root
        root.title("Macro Recorder")
        root.geometry("340x330")
        root.resizable(False, False)

        self.events = []
        self.recording = False
        self.playing = False
        self.abort = threading.Event()
        self.t0 = 0.0
        self.mouse_listener = None

        tk.Label(root, text="Macro Recorder", font=("Helvetica", 18, "bold")).pack(pady=(14, 2))
        self.status = tk.Label(root, text="Ready. Press Record.", fg="#555", wraplength=300)
        self.status.pack(pady=4)

        self.btn_rec = tk.Button(root, text="●  Record", width=22, command=self.start_record)
        self.btn_rec.pack(pady=3)
        self.btn_act = tk.Button(root, text="▶  Activate", width=22, command=self.start_play)
        self.btn_act.pack(pady=3)
        tk.Button(root, text="■  Stop playback (F9)", width=22, command=self.abort.set).pack(pady=3)

        opts = tk.Frame(root)
        opts.pack(pady=8)
        tk.Label(opts, text="Repeat:").grid(row=0, column=0)
        self.repeat = tk.Spinbox(opts, from_=1, to=999, width=5)
        self.repeat.grid(row=0, column=1, padx=6)
        tk.Label(opts, text="Speed:").grid(row=0, column=2)
        self.speed = tk.Spinbox(opts, values=(0.5, 1, 1.5, 2, 3), width=5)
        self.speed.delete(0, "end")
        self.speed.insert(0, "1")
        self.speed.grid(row=0, column=3, padx=6)

        files = tk.Frame(root)
        files.pack(pady=4)
        tk.Button(files, text="Save…", width=10, command=self.save).grid(row=0, column=0, padx=4)
        tk.Button(files, text="Load…", width=10, command=self.load).grid(row=0, column=1, padx=4)

        self.count = tk.Label(root, text="0 actions recorded", fg="#888")
        self.count.pack(pady=6)

        # Global keyboard listener (hotkeys + recording keys)
        self.kb_listener = keyboard.Listener(on_press=self.on_press, on_release=self.on_release)
        self.kb_listener.start()

    # ---------- helpers ----------
    def set_status(self, text):
        self.root.after(0, lambda: self.status.config(text=text))

    def update_count(self):
        self.root.after(0, lambda: self.count.config(text=f"{len(self.events)} actions recorded"))

    def add(self, **ev):
        ev["t"] = time.time() - self.t0
        self.events.append(ev)
        self.update_count()

    # ---------- recording ----------
    def start_record(self):
        if self.recording or self.playing:
            return
        self.events = []
        self.update_count()
        self.status.config(text="Starting in 3 seconds… window will minimise.\nPress F8 to stop.")
        self.root.after(1000, self.root.iconify)
        self.root.after(3000, self._begin_record)

    def _begin_record(self):
        self.t0 = time.time()
        self.recording = True
        self.mouse_listener = mouse.Listener(on_click=self.on_click, on_scroll=self.on_scroll)
        self.mouse_listener.start()

    def stop_record(self):
        self.recording = False
        if self.mouse_listener:
            self.mouse_listener.stop()
        self.root.after(0, self.root.deiconify)
        self.set_status(f"Recorded {len(self.events)} actions. Press Activate to replay.")

    def on_click(self, x, y, button, pressed):
        if self.recording:
            self.add(type="click", x=x, y=y, button=button.name, pressed=pressed)

    def on_scroll(self, x, y, dx, dy):
        if self.recording:
            self.add(type="scroll", x=x, y=y, dx=dx, dy=dy)

    def on_press(self, key):
        if key == STOP_PLAY_KEY:
            self.abort.set()
            return
        if key == STOP_RECORD_KEY and self.recording:
            self.stop_record()
            return
        if self.recording:
            self.add(type="key", pressed=True, key=key_to_data(key))

    def on_release(self, key):
        if self.recording and key not in (STOP_RECORD_KEY, STOP_PLAY_KEY):
            self.add(type="key", pressed=False, key=key_to_data(key))

    # ---------- playback ----------
    def start_play(self):
        if self.recording or self.playing:
            return
        if not self.events:
            messagebox.showinfo("Nothing to play", "Record or load a macro first.")
            return
        try:
            repeat = max(1, int(self.repeat.get()))
            speed = max(0.1, float(self.speed.get()))
        except ValueError:
            repeat, speed = 1, 1.0
        self.abort.clear()
        self.playing = True
        self.status.config(text="Starting in 3 seconds… switch to your starting screen.\nF9 = stop.")
        self.root.after(1000, self.root.iconify)
        threading.Thread(target=self._play, args=(repeat, speed), daemon=True).start()

    def _sleep(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            if self.abort.is_set():
                return False
            time.sleep(min(0.02, max(0, end - time.time())))
        return True

    def _play(self, repeat, speed):
        if not self._sleep(3):
            return self._end_play("Stopped.")
        for n in range(repeat):
            prev = 0.0
            for ev in self.events:
                if not self._sleep((ev["t"] - prev) / speed):
                    return self._end_play("Stopped.")
                prev = ev["t"]
                self._do(ev)
            self.set_status(f"Run {n + 1}/{repeat} done")
            if n < repeat - 1 and not self._sleep(1):
                return self._end_play("Stopped.")
        self._end_play("Finished.")

    def _do(self, ev):
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
        except Exception as e:  # keep going if one action fails
            print("Action failed:", e)

    def _end_play(self, msg):
        self.playing = False
        self.set_status(msg)
        self.root.after(0, self.root.deiconify)

    # ---------- save / load ----------
    def save(self):
        if not self.events:
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("Macro", "*.json")])
        if path:
            with open(path, "w") as f:
                json.dump(self.events, f)
            self.status.config(text="Saved.")

    def load(self):
        path = filedialog.askopenfilename(filetypes=[("Macro", "*.json")])
        if path:
            with open(path) as f:
                self.events = json.load(f)
            self.update_count()
            self.status.config(text="Loaded. Press Activate.")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
