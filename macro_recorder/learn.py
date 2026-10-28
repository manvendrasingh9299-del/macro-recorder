"""Learn from my day: saves screenshots and click positions so you can train your own model later.
Optional and off by default. It never saves what you type and skips password managers."""
import datetime
import json
import shutil
import threading
import time
from collections import deque

from pynput import keyboard, mouse

from . import macos, settings
from .matching import CROP_POINTS

CAP_GB = 3.0
SKIP_APPS = ("1password", "bitwarden", "keychain", "passwords", "lastpass", "dashlane", "python", "macro recorder")


class LearnMode:
    def __init__(self, app):
        self.app = app
        self.active = self.paused = False
        self.last_move, self.saved = 0.0, 0
        self.frames = deque(maxlen=3)
        self.last_click = (0.0, (0, 0), 1)
        self._listeners = []

    def start(self):
        if self.active:
            return
        settings.LEARN_DIR.mkdir(parents=True, exist_ok=True)
        self.active, self.paused = True, False
        threading.Thread(target=self._watch, daemon=True).start()
        self._listeners = [mouse.Listener(on_click=self._on_click, on_move=self._on_move),
                           keyboard.Listener(on_press=self._on_key)]
        for listener in self._listeners:
            listener.start()
        self.app.title("Macro Recorder - learning")
        self.app.set_status("Learning on. Fn+F7 pauses")

    def stop(self):
        self.active = False
        for listener in self._listeners:
            listener.stop()
        self.app.title("Macro Recorder")
        self.app.set_status("Learning off")

    def stats(self):
        """(number of examples, size in GB)"""
        count, size = 0, 0
        if settings.LEARN_DIR.exists():
            for f in settings.LEARN_DIR.rglob("*"):
                if f.is_file():
                    size += f.stat().st_size
                    if f.name == "data.jsonl":
                        count += sum(1 for _ in open(f))
        return count, size / 1e9

    def delete_all(self):
        shutil.rmtree(settings.LEARN_DIR, ignore_errors=True)

    def _on_key(self, key):
        if key == keyboard.Key.f7:
            self.paused = not self.paused
            self.app.ui(self.app.title, "Macro Recorder - learning" + (" (paused)" if self.paused else ""))
            self.app.ui(self.app.set_status, "Learning paused" if self.paused else "Learning resumed")

    def _on_move(self, x, y):
        self.last_move = time.time()

    def _watch(self):
        """Keep the last few screenshots, but only while the mouse is in use."""
        while self.active:
            if not self.paused and not self.app.playing and time.time() - self.last_move < 3:
                try:
                    self.frames.append((time.time(), macos.grab_screen()))
                except Exception:
                    pass
            time.sleep(0.3)

    def _on_click(self, x, y, button, pressed):
        if not pressed or self.paused or self.app.playing:
            return
        now, app_name = time.time(), macos.front_app()
        if any(s in app_name.lower() for s in SKIP_APPS):
            return
        last_t, last_pos, last_n = self.last_click
        near = abs(x - last_pos[0]) < 8 and abs(y - last_pos[1]) < 8
        n = last_n + 1 if now - last_t < 0.5 and near else 1
        self.last_click = (now, (x, y), n)
        old = [f for f in self.frames if f[0] <= now - 0.08]
        before = old[-1][1] if old and now - old[-1][0] < 2 else None
        threading.Thread(target=self._save, args=(now, x, y, button.name, n, app_name, before), daemon=True).start()

    def _save(self, t, x, y, button, n, app_name, before):
        app = self.app
        try:
            day = settings.LEARN_DIR / datetime.date.today().isoformat()
            day.mkdir(parents=True, exist_ok=True)
            sid = str(int(t * 1000))
            shot = before or macos.grab_screen()
            time.sleep(0.8)   # let the screen react, then save what the click did
            after = macos.grab_screen()
            big = shot.resize((1024, round(shot.height * 1024 / shot.width)))
            big.save(day / f"{sid}.jpg", quality=70)
            small = after.resize((512, round(after.height * 512 / after.width)))
            small.save(day / f"{sid}-after.jpg", quality=60)
            s = shot.width / app.sw
            half = int(CROP_POINTS * s / 2)
            cx, cy = int(x * s), int(y * s)
            shot.crop((max(cx - half, 0), max(cy - half, 0), cx + half, cy + half)).save(day / f"{sid}-crop.png")
            row = {"id": sid, "time": datetime.datetime.fromtimestamp(t).isoformat(timespec="seconds"),
                   "app": app_name, "screen": [app.sw, app.sh], "click": [round(x, 1), round(y, 1)],
                   "norm": [round(x / app.sw, 4), round(y / app.sh, 4)], "button": button, "n": n,
                   "image": f"{sid}.jpg", "crop": f"{sid}-crop.png", "after": f"{sid}-after.jpg"}
            with open(day / "data.jsonl", "a") as f:
                f.write(json.dumps(row) + "\n")
            self.saved += 1
            if self.saved % 50 == 0 and self.stats()[1] > CAP_GB:
                days = sorted(p for p in settings.LEARN_DIR.iterdir() if p.is_dir())
                if len(days) > 1:
                    shutil.rmtree(days[0])
        except Exception as exc:
            print("Learn error:", exc)
