#!/usr/bin/env bash
# Builds "Macro Recorder.app" -> dist/Macro Recorder.app   (run on your Mac)
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt pyinstaller
pyinstaller --noconfirm --windowed --name "Macro Recorder" \
  --osx-bundle-identifier com.macrorecorder.app \
  --collect-all customtkinter macro_recorder.py
codesign --force --deep --sign - "dist/Macro Recorder.app"
echo "Done. Drag dist/Macro Recorder.app into /Applications"
open dist
