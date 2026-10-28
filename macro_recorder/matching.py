"""Finding a recorded button on the current screen: image matching first, optional models second."""
import base64
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request

import cv2
import numpy as np
from PIL import Image

CROP_POINTS = 140          # size of the picture saved around every click
MATCH_MIN = 0.72           # how sure image matching must be (0 to 1)
SEND_WIDTH = 1024          # screenshots are shrunk to this width before a model sees them
OLLAMA_DEFAULT = "qwen2.5vl:3b"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
_templates = {}


def b64(img, fmt="PNG", **kw):
    buf = io.BytesIO()
    img.save(buf, fmt, **kw)
    return base64.b64encode(buf.getvalue()).decode()


def locate(ev, shot, screen_w, around=None):
    """Find the recorded picture on the screen. Returns (x, y) in screen points, or None.
    around=(x, y) searches only near that point, which is much faster."""
    key = hash(ev["crop"])
    if key not in _templates:
        _templates[key] = cv2.imdecode(np.frombuffer(base64.b64decode(ev["crop"]), np.uint8), cv2.IMREAD_GRAYSCALE)
    tpl = _templates[key]
    if tpl.std() < 3:                                # a flat picture would "match" anywhere
        return None
    th, tw = tpl.shape[:2]
    s = shot.width / screen_w                       # pixels per point
    ox, oy = ev["ox"], ev["oy"]                     # where the click was inside the picture
    x0, y0, x1, y1 = 0, 0, shot.width, shot.height
    if around:
        pad = int(260 * s)
        left, top = int(around[0] * s - ox), int(around[1] * s - oy)
        x0, y0 = max(left - pad, 0), max(top - pad, 0)
        x1, y1 = min(left + tw + pad, shot.width), min(top + th + pad, shot.height)
        if x1 - x0 < tw or y1 - y0 < th:
            return None
    gray = cv2.cvtColor(np.array(shot.crop((x0, y0, x1, y1))), cv2.COLOR_RGB2GRAY)
    _, score, _, best = cv2.minMaxLoc(cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED))
    if not score >= MATCH_MIN:                       # also false when the score is not a number
        return None
    return (x0 + best[0] + ox) / s, (y0 + best[1] + oy) / s


# ---------- optional models ----------
def _json_reply(text):
    return json.loads(re.search(r"\{.*\}", text, re.S).group())


def _ask_claude(key, crop, shot, prompt):
    image = lambda media, data: {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}
    body = {"model": CLAUDE_MODEL, "max_tokens": 60, "messages": [{"role": "user", "content": [
        image("image/png", crop), image("image/jpeg", shot), {"type": "text", "text": prompt}]}]}
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", json.dumps(body).encode(),
        {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as reply:
        return _json_reply(json.load(reply)["content"][0]["text"])


def _ask_ollama(model, crop, shot, prompt):
    body = {"model": model, "stream": False, "keep_alive": "30m", "options": {"temperature": 0},
            "messages": [{"role": "user", "content": prompt, "images": [crop, shot]}]}
    request = urllib.request.Request("http://localhost:11434/api/chat", json.dumps(body).encode(),
                                     {"content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as reply:
        return _json_reply(json.load(reply)["message"]["content"])


def ollama_running():
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1).read()
        return True
    except Exception:
        return False


def ensure_ollama(model):
    """Start the Ollama server if needed and load the model. Returns '' or a short problem message."""
    if not ollama_running():
        exe = shutil.which("ollama") or next(
            (p for p in ("/opt/homebrew/bin/ollama", "/usr/local/bin/ollama") if os.path.exists(p)), None)
        if exe:
            subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        else:
            subprocess.run(["open", "-a", "Ollama"])
        for _ in range(30):
            if ollama_running():
                break
            time.sleep(0.5)
        else:
            return "Ollama not found. Using LOCAL"
    try:
        body = json.dumps({"model": model, "keep_alive": "30m"}).encode()
        urllib.request.urlopen(urllib.request.Request(
            "http://localhost:11434/api/generate", body, {"content-type": "application/json"}), timeout=90).read()
    except Exception:
        return f"Run: ollama pull {model}"
    return ""


def load_plugin(path):
    spec = importlib.util.spec_from_file_location("my_model", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ask_model(brain, ev, shot, screen_w, screen_h, cfg, api_key, plugin):
    """A second opinion from Claude, Ollama or your own model. Returns (x, y) in screen points, or None."""
    crop = Image.open(io.BytesIO(base64.b64decode(ev["crop"]))).convert("RGB")
    s = shot.width / screen_w
    if brain == "plugin":
        found = plugin.find(crop, shot, (ev["x"] * s, ev["y"] * s))
        return (found[0] / s, found[1] / s) if found else None
    w, h = SEND_WIDTH, round(shot.height * SEND_WIDTH / shot.width)
    k = w / shot.width
    crop = crop.resize((max(1, int(crop.width * k)), max(1, int(crop.height * k))))
    px, py = round(ev["x"] * w / screen_w), round(ev["y"] * h / screen_h)
    prompt = (f"Image 1 is a crop around a UI element I clicked earlier. Image 2 is my current screen ({w}x{h} px). "
              f"Find the same element in image 2. It used to be near ({px}, {py}). "
              'Reply with JSON only: {"found": true, "x": <int>, "y": <int>} for its center, or {"found": false}.')
    crop_b64, shot_b64 = b64(crop), b64(shot.resize((w, h)), "JPEG", quality=70)
    if brain == "claude":
        reply = _ask_claude(api_key, crop_b64, shot_b64, prompt)
    else:
        reply = _ask_ollama(cfg.get("ollama_model", OLLAMA_DEFAULT), crop_b64, shot_b64, prompt)
    return (reply["x"] * screen_w / w, reply["y"] * screen_h / h) if reply.get("found") else None
