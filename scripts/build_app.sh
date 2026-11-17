#!/usr/bin/env bash
# Builds "Macro Recorder.app" into dist/. Run it from the project folder:  ./scripts/build_app.sh
#
# One-time step, before the first build: turn scripts/icon_1024.png into the .icns
# file macOS actually needs for an app icon. This uses iconutil, which ships with
# every Mac, so nothing extra to install:
#
#   mkdir scripts/icon.iconset
#   for s in 16 32 128 256 512; do
#     sips -z $s $s scripts/icon_1024.png --out scripts/icon.iconset/icon_${s}x${s}.png
#     sips -z $((s*2)) $((s*2)) scripts/icon_1024.png --out scripts/icon.iconset/icon_${s}x${s}@2x.png
#   done
#   iconutil -c icns scripts/icon.iconset -o scripts/icon.icns
#
set -e
cd "$(dirname "$0")/.."
python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt pyinstaller

ICON_ARGS=()
if [ -f scripts/icon.icns ]; then
  ICON_ARGS=(--icon scripts/icon.icns)
else
  echo "No scripts/icon.icns yet -- building with the default icon. See the comment"
  echo "at the top of this script for the one-time command to make one."
fi

# Newer Python installs (Homebrew included) now ship Tcl/Tk 9, whose library names
# PyInstaller's bundler does not always find on its own -- add them explicitly so the
# built app doesn't fail on "libtcl9.0 ... not found" the moment it's opened. This was
# tested and genuinely needed: a build without this line crashed immediately on launch.
TCL_LIB=$(python3 -c "import tkinter, pathlib; print(pathlib.Path(tkinter.__file__).parent.parent.parent)")
TCL_ARGS=()
for lib in "$TCL_LIB"/libtcl9*.dylib "$TCL_LIB"/libtcl9*.so; do
  [ -f "$lib" ] && TCL_ARGS+=(--add-binary "$lib:.")
done
if [ ${#TCL_ARGS[@]} -eq 0 ]; then
  echo "Note: could not find Tcl/Tk 9 libraries near $TCL_LIB -- if the built app"
  echo "fails to open with a 'libtcl9... not found' error, that's why. Tell me the"
  echo "exact error and I'll adjust this path."
fi

pyinstaller --noconfirm --windowed --name "Macro Recorder" \
  --osx-bundle-identifier com.macrorecorder.app \
  "${ICON_ARGS[@]}" "${TCL_ARGS[@]}" \
  --paths . --collect-all customtkinter --collect-all cv2 scripts/launch.py
codesign --force --deep --sign - "dist/Macro Recorder.app"
echo "Done. Move dist/Macro Recorder.app to Applications, then give it the three permissions."
