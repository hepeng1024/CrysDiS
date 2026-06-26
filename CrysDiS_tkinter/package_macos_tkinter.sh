#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

APP_NAME="CrysDiS-Tkinter"
ENTRY_SCRIPT="CrysDiS_tkinter.py"
ICON_PNG="assets/CrysDiS_tkinter.png"
ICON_ICNS="assets/CrysDiS_tkinter.icns"
SEED_JSON="packaging/custom_crystals_local.json"

[ -f "$ENTRY_SCRIPT" ] || { echo "Missing $ENTRY_SCRIPT"; exit 1; }
[ -f "$ICON_PNG" ] || { echo "Missing $ICON_PNG"; exit 1; }
[ -f "$SEED_JSON" ] || { echo "Missing $SEED_JSON"; exit 1; }

rm -rf build dist "${APP_NAME}.spec"

if [ ! -f "$ICON_ICNS" ]; then
  mkdir -p assets/icon.iconset
  sips -z 16 16     "$ICON_PNG" --out assets/icon.iconset/icon_16x16.png
  sips -z 32 32     "$ICON_PNG" --out assets/icon.iconset/icon_16x16@2x.png
  sips -z 32 32     "$ICON_PNG" --out assets/icon.iconset/icon_32x32.png
  sips -z 64 64     "$ICON_PNG" --out assets/icon.iconset/icon_32x32@2x.png
  sips -z 128 128   "$ICON_PNG" --out assets/icon.iconset/icon_128x128.png
  sips -z 256 256   "$ICON_PNG" --out assets/icon.iconset/icon_128x128@2x.png
  sips -z 256 256   "$ICON_PNG" --out assets/icon.iconset/icon_256x256.png
  sips -z 512 512   "$ICON_PNG" --out assets/icon.iconset/icon_256x256@2x.png
  sips -z 512 512   "$ICON_PNG" --out assets/icon.iconset/icon_512x512.png
  sips -z 1024 1024 "$ICON_PNG" --out assets/icon.iconset/icon_512x512@2x.png
  iconutil -c icns assets/icon.iconset -o "$ICON_ICNS"
  rm -rf assets/icon.iconset
fi

python -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --windowed \
  --name "$APP_NAME" \
  --icon "$ICON_ICNS" \
  --osx-bundle-identifier "edu.umich.hepeng.CrysDiS.Tkinter" \
  --collect-data "pymatgen" \
  --add-data "assets:assets" \
  --add-data "${SEED_JSON}:." \
  "$ENTRY_SCRIPT"

cd dist
ditto -c -k --keepParent "${APP_NAME}.app" "${APP_NAME}-macOS.zip"