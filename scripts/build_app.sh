#!/usr/bin/env bash
# Builds "Macro Recorder.app" into dist/. Run it from the project folder:  ./scripts/build_app.sh
set -e
cd "$(dirname "$0")/.."
python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt pyinstaller
pyinstaller --noconfirm --windowed --name "Macro Recorder" \
  --osx-bundle-identifier com.macrorecorder.app \
  --paths . --collect-all customtkinter --collect-all cv2 scripts/launch.py
codesign --force --deep --sign - "dist/Macro Recorder.app"
echo "Done. Move dist/Macro Recorder.app to Applications, then give it the three permissions."
