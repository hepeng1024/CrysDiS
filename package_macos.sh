#!/usr/bin/env bash
set -euo pipefail

APP_NAME="CrysDiS"

rm -rf build dist "${APP_NAME}.spec"

# Create a macOS .icns icon from assets/CrysDiS.png if assets/CrysDiS.icns does not exist.
if [ ! -f "assets/CrysDiS.icns" ] && [ -f "assets/CrysDiS.png" ]; then
  mkdir -p assets/icon.iconset
  sips -z 16 16     assets/CrysDiS.png --out assets/icon.iconset/icon_16x16.png
  sips -z 32 32     assets/CrysDiS.png --out assets/icon.iconset/icon_16x16@2x.png
  sips -z 32 32     assets/CrysDiS.png --out assets/icon.iconset/icon_32x32.png
  sips -z 64 64     assets/CrysDiS.png --out assets/icon.iconset/icon_32x32@2x.png
  sips -z 128 128   assets/CrysDiS.png --out assets/icon.iconset/icon_128x128.png
  sips -z 256 256   assets/CrysDiS.png --out assets/icon.iconset/icon_128x128@2x.png
  sips -z 256 256   assets/CrysDiS.png --out assets/icon.iconset/icon_256x256.png
  sips -z 512 512   assets/CrysDiS.png --out assets/icon.iconset/icon_256x256@2x.png
  sips -z 512 512   assets/CrysDiS.png --out assets/icon.iconset/icon_512x512.png
  sips -z 1024 1024 assets/CrysDiS.png --out assets/icon.iconset/icon_512x512@2x.png
  iconutil -c icns assets/icon.iconset -o assets/CrysDiS.icns
  rm -rf assets/icon.iconset
fi

python -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --windowed \
  --name "$APP_NAME" \
  --icon "assets/CrysDiS.icns" \
  --osx-bundle-identifier "edu.umich.hepeng.CrysDiS" \
  --add-data "assets:assets" \
  --add-data "custom_crystals_local.json:." \
  CrysDiS.py

cd dist
ditto -c -k --keepParent "${APP_NAME}.app" "${APP_NAME}-macOS.zip"