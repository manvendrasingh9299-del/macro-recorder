# Macro Recorder

Record your mouse clicks and keystrokes on a Mac, then replay them with one click.
It finds buttons by looking at the screen, so macros still work when a window moves.
Optional AI helps when the free matching fails, and the app can learn from your daily
work so you can train your own model later.

> Status: personal project, tested on macOS (Apple Silicon). Expect rough edges.

## Features

- **Record and replay** clicks, double-clicks, scrolls, and keys.
- **Smart replay**: finds each button on screen using free OpenCV matching.
- **Brains** (tap the brain pill to switch):
  - **LOCAL**: free and fast, no AI.
  - **CLAUDE**: asks Claude if local matching fails (needs an API key).
  - **OLLAMA**: asks a small local vision model (starts `ollama serve` for you).
  - **MY MODEL**: your own model, loaded from `my_model.py`.
- **Learn once, then run fast**: after a run, answer "Was it right?". On Yes, the macro is
  saved as a FAST version that searches near the last known spot and skips long pauses.
- **Learn from my day** (optional): saves screenshots and click positions while you work,
  as training data for your own model.
- **Retro handheld UI** with an animated pixel cat.
- **Library**: save, load, and delete macros by name.

## Install

Requires macOS and Python 3.12 or newer with Tk.

```bash
git clone https://github.com/YOUR-USERNAME/macro-recorder.git
cd macro-recorder
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

If you see `No module named '_tkinter'` on Homebrew Python:

```bash
brew install python-tk@3.14   # use the same version as your python
```

Always start the app with `python run.py`. It loads `macro_recorder.py` and applies the
latest fixes on top.

## macOS permissions

Give permission to the app you launch from (Terminal or Visual Studio Code) in
System Settings, then press Cmd+Q to quit that app and reopen it:

| Permission | Where in System Settings |
|---|---|
| Accessibility | Privacy & Security, **Device Control and Data Access** (called Accessibility on older macOS) |
| Input Monitoring | Privacy & Security, Input Monitoring |
| Screen & System Audio Recording | Privacy & Security |

Quick links (run in Terminal):

```bash
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
open "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"
open "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
```

Check that all three work:

```bash
python -c "from Quartz import CGPreflightListenEventAccess as L, CGPreflightScreenCaptureAccess as S; from ApplicationServices import AXIsProcessTrusted as A; print(A(), L(), S())"
```

## How to use

1. Press **REC**, wait for the countdown, do your task, then press **Fn+F8**.
2. The number on screen shows the recorded steps.
3. Press **RUN** (or **Fn+F10**) and don't touch the mouse.
4. When it finishes, answer **Was it right?**. Yes saves a FAST version.
5. Tap the macro name on the screen to save it. Open **Macros** to load or delete.

### Hotkeys

On a MacBook, hold **Fn** for the F keys, or turn on
"Use F1, F2, etc. keys as standard function keys" in Keyboard settings.

| Key | Action |
|---|---|
| F8 | Stop recording |
| F9 | Stop playback |
| F10 | Run the loaded macro |
| F7 | Pause or resume "Learn from my day" |

## Brains

### Ollama (local model)

```bash
brew install ollama
ollama pull qwen2.5vl:3b
```

Pick the **OLLAMA** brain. The app starts `ollama serve` and loads the model by itself.
Text-only models (such as llama or mistral) cannot read screenshots and will not work.

### Claude

Click the gear icon, choose **Anthropic API key**, and paste a key from
console.anthropic.com. The key is stored in `config.json` in the app folder.
Smart replay with Claude makes API calls that cost money.

### Your own model (`my_model.py`)

Pick **MY MODEL**. The app creates `my_model.py` in its folder with one function:



Warning: this file runs as normal Python code. Only use code you trust.

## Learn from my day (optional)

Turn on in the gear menu: **Learn from my day**.

- Saves, for each real click: a screenshot from just before, a small picture of what you
  clicked, the position, the front app, and a screenshot from just after.
- Does **not** save typed characters. Skips password managers and the app itself.
- Pause with **Fn+F7**. The window title shows **LEARNING** while it is on.
- Capped at 3 GB; the oldest day is deleted first.
- Screenshots can show private content. Everything stays on your Mac. Use
  **Delete learned data** in the gear menu to remove it.

## Where files live

`~/Library/Application Support/MacroRecorder/`

| Path | Contents |
|---|---|
| `macros/` | Your saved macros (JSON). They can contain what you typed. |
| `config.json` | Settings and API key |
| `my_model.py` | Your plugin model |
| `training/` | Data collected during replays |
| `learn/` | Data from "Learn from my day" |

Never commit these files or share them. They may contain private information.

## Build a standalone app

Before building, edit `build_app.sh` so the last line uses `run.py` and
`--collect-all cv2`:

```bash
pyinstaller --noconfirm --windowed --name "Macro Recorder" \
  --osx-bundle-identifier com.macrorecorder.app \
  --collect-all customtkinter --collect-all cv2 run.py
```

Then run `./build_app.sh`. The app appears in `dist/`. Add it to the three permission
lists above. If you rebuild, macOS may ask for permissions again.

## Troubleshooting

| Problem | Try |
|---|---|
| "This process is not trusted" | Permissions are missing. Enable them for your launching app and restart it. |
| "could not create image from display" | Enable Screen & System Audio Recording and restart the app. |
| Cursor moves but nothing clicks | Re-record, run with `python run.py`, and check the `[click]` lines in the terminal. |
| Clicks missed after a long pause | Re-record. Old macros may be missing data. |
| Double-click does not open a folder | Re-record, and double-click quickly (under 0.5 s apart). |
| F8 does nothing | Hold Fn, or enable standard function keys. |
| Ollama gives wrong positions | Use LOCAL or CLAUDE, or try a larger vision model. |

## Limitations

- Main display only.
- Dragging and modifier-clicks (Cmd-click, Shift-click) are not supported yet.
- Automating websites can break their terms of service. Use it responsibly.
- Ollama and "learn" features are lightly tested.

## Roadmap

Step editor, wait-until-it-appears and type-text steps, scheduled runs, API key in the
macOS Keychain, a first-run permission wizard, and training a small button-finding model
from collected data.

## Project structure

```
macro_recorder.py   core app and UI
run.py              latest fixes and features, applied on top of macro_recorder.py
build_app.sh        builds the Mac app
requirements.txt    dependencies
```

## License

Add a license before sharing, for example MIT.
