#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="CrysDiS_tkinter"
DIST_DIR="$ROOT/dist/$APP_NAME"
EXE="$DIST_DIR/$APP_NAME"
RUNNER="$DIST_DIR/run_CrysDiS_tkinter.sh"
DESKTOP="$DIST_DIR/CrysDiS_tkinter.desktop"
INSTALLER="$DIST_DIR/install_launcher.sh"
ICON="$DIST_DIR/assets/CrysDiS_tkinter.png"
SEED_LIBRARY="$DIST_DIR/custom_crystals_local.json"
INTERNAL="$DIST_DIR/_internal"

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

require_file() {
    local path="$1"
    [ -f "$path" ] || fail "Missing file: $path"
}

require_executable() {
    local path="$1"
    require_file "$path"
    [ -x "$path" ] || fail "File is not executable: $path"
}

[ -d "$DIST_DIR" ] || fail "Missing dist folder: $DIST_DIR"
[ -d "$INTERNAL" ] || fail "Missing PyInstaller _internal folder: $INTERNAL"
require_executable "$EXE"
require_executable "$RUNNER"
require_executable "$DESKTOP"
require_executable "$INSTALLER"
require_file "$ICON"
require_file "$SEED_LIBRARY"

grep -Fq "run_CrysDiS_tkinter.sh" "$DESKTOP" || fail "Desktop launcher does not reference run_CrysDiS_tkinter.sh"
grep -Fq "Icon=" "$DESKTOP" || fail "Desktop launcher has no Icon= line"
grep -Fq 'Icon=$APPDIR/assets/CrysDiS_tkinter.png' "$INSTALLER" || fail "Installer does not write the expected absolute icon path"
grep -Fq 'Exec=$APPDIR/run_CrysDiS_tkinter.sh' "$INSTALLER" || fail "Installer does not write the expected launcher Exec line"

if command -v ldd >/dev/null 2>&1; then
    if LDD_OUTPUT="$(ldd "$EXE" 2>&1)"; then
        if printf '%s\n' "$LDD_OUTPUT" | grep -Fq "not found"; then
            printf '%s\n' "$LDD_OUTPUT" >&2
            fail "ldd reports missing shared libraries for $EXE"
        fi
    elif ! printf '%s\n' "$LDD_OUTPUT" | grep -Fq "not a dynamic executable"; then
        printf '%s\n' "$LDD_OUTPUT" >&2
        fail "ldd failed for $EXE"
    fi
fi

[ -d "$INTERNAL/pymatgen" ] || fail "pymatgen package directory was not found in the PyInstaller bundle"
require_file "$INTERNAL/pymatgen/analysis/diffraction/tem.py"
require_file "$INTERNAL/pymatgen/analysis/diffraction/atomic_scattering_params.json"
require_file "$INTERNAL/pymatgen/io/cif.py"
require_file "$INTERNAL/pymatgen/symmetry/analyzer.py"
require_file "$INTERNAL/pymatgen/symmetry/symm_data.json"

echo "CrysDiS_tkinter Linux bundle verification passed."
