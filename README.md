# Macro Recorder

**Record a task once. Replay it any time, even after a window moves.**

Macro Recorder records your mouse clicks and keystrokes on a Mac and replays them with one click. Most macro tools click fixed screen positions, so they break when a window moves. This one finds each button by looking at the screen.

**[Watch the 90-second demo](YOUR-VIDEO-LINK)**

<p align="center">
  <img src="assets/main.jpg" alt="Main window" width="300">
  &nbsp;&nbsp;&nbsp;
  <img src="assets/macros.jpg" alt="Saved macros" width="300">
</p>
<p align="center"><sub>The main window and your saved macros</sub></p>

## How it works

1. **Record.** For every click, it saves the click position and a small picture of what you clicked.
2. **Replay.** For every click, it looks for that picture on the current screen (image matching with OpenCV) and clicks where it finds it.
3. **Back up.** If matching fails, an optional vision model can try. Otherwise it clicks the saved position.

Everything runs on your Mac. No account and no internet are needed for the default mode.

## Features

- Records clicks (single, double, right), scrolling and keys
- Repeat from 1 to 100 times, at 0.5x to 3x speed
- **Smart replay** finds buttons on screen, so moved windows are fine
- **Fast replay.** After a run, answer "Was it right?". Yes saves a faster version of the macro
- Save, open and delete macros
- Optional backups for Smart replay: Ollama (local vision model), Claude (API key), or your own model
- Optional **Learn from my day**: saves screenshots and click positions on your Mac, so you can train your own model later (off by default)

## Quick start (macOS)

You need macOS and Python 3.12 or newer with Tk.

```bash
git clone https://github.com/manvendrasingh9299-del/macro-recorder.git
cd macro-recorder
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

### Allow the permissions

Open **System Settings > Privacy & Security** and turn these on for the app you start from (Terminal or VS Code):

- **Accessibility** (called **Device Control and Data Access** on some versions)
- **Input Monitoring**
- **Screen & System Audio Recording**

Then quit that app completely (Cmd+Q) and open it again.

## Use it

1. Press **REC**, wait 3 seconds, do your task, then press **F8**.
2. Press **RUN** (or **F10**) and keep your hands off the mouse.
3. When it finishes, answer **Was it right?**. Yes makes later runs faster.
4. Tap the macro name to save it. **Macros** opens your saved ones.

Tap **REPEAT** and **SPEED** on the screen to change them. Turn **Smart replay** off to replay exact positions instead.

| Key | Action |
|---|---|
| F8 | Stop recording |
| F9 | Stop playback |
| F10 | Run the loaded macro |
| F7 | Pause or resume Learn from my day |

On a MacBook, hold **Fn** with these keys unless you turned on standard function keys.

<<<<<<< HEAD
## Brains for Smart replay

| Brain | What it is |
|---|---|
| Local | Default. Image matching on your Mac. Free, offline |
| Ollama | A small local vision model. Run `ollama pull qwen2.5vl:3b`. The app starts the server for you |
| Claude | Needs an API key (Settings). Sends screenshots to Anthropic, so it needs internet |
| My model | Your own model. Put a `find(crop, screen, hint)` function in `my_model.py` |

If a button is not found within 5 seconds, the macro clicks its saved position. Turn on **Stop if target not found** in Settings to stop instead.

## Privacy

- A macro records everything you type, **including passwords**. Do not record passwords.
- Everything stays on your Mac, except when you choose the Claude brain.
- Your data is in `~/Library/Application Support/MacroRecorder/`: `macros/`, `config.json` (settings and API key), `my_model.py`, and `learn/`.

## Project files

| File | Purpose |
|---|---|
| `macro_recorder.py` | The app and its interface |
| `run.py` | Start here. Click sending, button matching, fast replay, Learn from my day |
| `ui_game.py` | Removes clutter from the screen |
| `requirements.txt` | Python packages |

## Limits

- macOS only. Main display only.
- No dragging, and no Cmd or Shift clicks yet.
- Ollama and Learn from my day have had light testing.

## Build the app (experimental)

```bash
pip install pyinstaller
pyinstaller --noconfirm --windowed --name "Macro Recorder" --collect-all customtkinter --collect-all cv2 run.py
```

The app appears in `dist/`. Give `Macro Recorder.app` the three permissions above.
=======
</details>
ghcyugvbv bbhjgv vb
>>>>>>> e7465da (update)
