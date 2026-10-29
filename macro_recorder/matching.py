"""Finding a recorded button on the current screen.
Local image matching runs first and needs no internet. If you add your own model
(see settings.PLUGIN_TEMPLATE), it is asked only when local matching is not sure."""
import base64
import importlib.util
import io

import cv2
import numpy as np

CROP_POINTS = 140          # size of the picture saved around every click
MATCH_MIN = 0.72           # how sure local matching must be (0 to 1)
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
    s = shot.width / screen_w                        # pixels per point
    ox, oy = ev["ox"], ev["oy"]                      # where the click was inside the picture
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


def load_plugin(path):
    """Load your own model from my_model.py. It must define find(crop, screen, hint)."""
    spec = importlib.util.spec_from_file_location("my_model", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ask_plugin(plugin, ev, shot, screen_w, screen_h):
    """Ask your own model. Returns (x, y) in screen points, or None."""
    import io as _io
    from PIL import Image
    crop = Image.open(_io.BytesIO(base64.b64decode(ev["crop"]))).convert("RGB")
    s = shot.width / screen_w
    found = plugin.find(crop, shot, (ev["x"] * s, ev["y"] * s))
    return (found[0] / s, found[1] / s) if found else None
