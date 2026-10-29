"""Where things are saved: settings, macros and learned data."""
import json
from pathlib import Path

APP_DIR = Path.home() / "Library" / "Application Support" / "MacroRecorder"
MACRO_DIR = APP_DIR / "macros"
LEARN_DIR = APP_DIR / "learn"
CONFIG = APP_DIR / "config.json"
PLUGIN = APP_DIR / "my_model.py"
MACRO_DIR.mkdir(parents=True, exist_ok=True)

PLUGIN_TEMPLATE = '''"""Your own model. Used when image matching fails (brain: MY MODEL).

crop   : PIL RGB picture of what was clicked (screen pixels)
screen : PIL RGB picture of the current screen (screen pixels)
hint   : (x, y) where the button was when recorded (screen pixels)
Return (x, y) of the button in screen pixels, or None if not found.
"""


def find(crop, screen, hint):
    return None
'''


def load():
    try:
        return json.loads(CONFIG.read_text())
    except Exception:
        return {}


def save(cfg):
    CONFIG.write_text(json.dumps(cfg))
    CONFIG.chmod(0o600)


def macro_names():
    return sorted(p.stem for p in MACRO_DIR.glob("*.json"))


def read_macro(name):
    return json.loads((MACRO_DIR / f"{name}.json").read_text())


def write_macro(name, events):
    (MACRO_DIR / f"{name}.json").write_text(json.dumps(events))


def macro_exists(name):
    return (MACRO_DIR / f"{name}.json").exists()


def delete_macro(name):
    (MACRO_DIR / f"{name}.json").unlink(missing_ok=True)
