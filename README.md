# Macro Recorder

Records your mouse clicks, scrolls and keystrokes on macOS, then replays them with one click.
Saved macros live in the `macros/` folder (git-ignored). Hotkeys: F8 stop recording, F9 stop playback, F10 activate.

## Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python macro_recorder.py
```

## macOS permissions
System Settings → Privacy & Security → enable **Accessibility** and **Input Monitoring**
for the app you run it from (Terminal or Visual Studio Code). Restart that app afterwards.

## Usage
- **Record** → do your steps → press **F8** to stop
- **Activate** → replays the macro (3 second countdown)
- **F9** → emergency stop
- **Save / Load** → keep macros as JSON files

## Warning
Macros record everything you type, including passwords. Never commit macro files to GitHub.
