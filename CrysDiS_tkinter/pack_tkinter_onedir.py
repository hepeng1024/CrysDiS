from __future__ import annotations

import datetime as _dt
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


APP_NAME = "CrysDiS_tkinter"
ROOT = Path(__file__).resolve().parent
ENTRY_POINT = ROOT / "CrysDiS_tkinter.py"
CLEAN_LIBRARY = ROOT / "packaging" / "custom_crystals_local.json"
ICON_SOURCE = ROOT / "assets" / "CrysDiS_tkinter.png"
DIST_ROOT = ROOT / "dist"
DIST_DIR = DIST_ROOT / APP_NAME
INTERNAL_DIR = DIST_DIR / "_internal"
VERIFY_SCRIPT = ROOT / "scripts" / "verify_tkinter_linux_bundle.sh"


def data_arg(source: Path, target: str = ".") -> str:
    separator = ";" if os.name == "nt" else ":"
    return f"{source}{separator}{target}"


def check_clean_library() -> None:
    if not CLEAN_LIBRARY.exists():
        raise FileNotFoundError(f"Missing clean crystal seed library: {CLEAN_LIBRARY}")
    try:
        payload = json.loads(CLEAN_LIBRARY.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid clean crystal seed JSON: {CLEAN_LIBRARY}") from exc
    if not isinstance(payload, dict):
        raise ValueError("The clean crystal seed library must be a JSON object.")


def check_icon_source() -> None:
    if not ICON_SOURCE.exists():
        raise FileNotFoundError(f"Missing tkinter icon: {ICON_SOURCE}")


def conda_lib_dir() -> Path:
    env_root = Path(sys.executable).resolve().parent.parent
    return env_root / "lib"


def conda_runtime_libraries() -> list[Path]:
    if sys.platform != "linux":
        return []
    lib_dir = conda_lib_dir()
    names = [
        "libstdc++.so",
        "libstdc++.so.6",
        "libgcc_s.so",
        "libgcc_s.so.1",
        "libbz2.so",
        "libbz2.so.1.0",
    ]
    libraries = [lib_dir / name for name in names]
    libraries.extend(sorted(lib_dir.glob("libstdc++.so.6.*")))
    libraries.extend(sorted(lib_dir.glob("libbz2.so.1.0.*")))
    unique: dict[str, Path] = {}
    for library in libraries:
        if library.exists():
            unique[library.name] = library
    return list(unique.values())


def conda_runtime_binary_args() -> list[str]:
    args: list[str] = []
    for library in conda_runtime_libraries():
        args.extend(["--add-binary", data_arg(library, ".")])
    return args


def collect_package_args() -> list[str]:
    args: list[str] = []
    if importlib.util.find_spec("matplotlib") is not None:
        args.extend(["--collect-data", "matplotlib"])
    for package in ("pymatgen", "spglib"):
        if importlib.util.find_spec(package) is not None:
            args.extend(["--collect-all", package])
    return args


def hidden_import_args() -> list[str]:
    hidden_imports = [
        "PIL._tkinter_finder",
        "pymatgen.analysis.diffraction.tem",
        "pymatgen.io.cif",
        "pymatgen.symmetry.analyzer",
        "pymatgen.symmetry.groups",
    ]
    args: list[str] = []
    for module in hidden_imports:
        args.extend(["--hidden-import", module])
    return args


def force_symlink(alias_name: str, pattern: str) -> None:
    matches = sorted(INTERNAL_DIR.glob(pattern))
    real_matches = [path for path in matches if path.name != alias_name]
    if not real_matches:
        return
    target = real_matches[-1]
    alias = INTERNAL_DIR / alias_name
    if alias.exists() or alias.is_symlink():
        alias.unlink()
    alias.symlink_to(target.name)


def copy_runtime_assets() -> None:
    check_clean_library()
    check_icon_source()
    shutil.copy2(CLEAN_LIBRARY, DIST_DIR / "custom_crystals_local.json")
    target_assets = DIST_DIR / "assets"
    target_assets.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ICON_SOURCE, target_assets / "CrysDiS_tkinter.png")


def write_linux_launcher() -> None:
    launcher = DIST_DIR / "run_CrysDiS_tkinter.sh"
    launcher.write_text(
        """#!/usr/bin/env bash
set -euo pipefail

APPDIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

stdcpp_real="$(find "$APPDIR/_internal" -maxdepth 1 -name 'libstdc++.so.6.*' | sort | tail -n 1 || true)"
if [ -n "$stdcpp_real" ]; then
    ln -sf "$(basename "$stdcpp_real")" "$APPDIR/_internal/libstdc++.so.6"
fi

bz2_real="$(find "$APPDIR/_internal" -maxdepth 1 -name 'libbz2.so.1.0.*' | sort | tail -n 1 || true)"
if [ -n "$bz2_real" ]; then
    ln -sf "$(basename "$bz2_real")" "$APPDIR/_internal/libbz2.so.1.0"
fi

export LD_LIBRARY_PATH="$APPDIR/_internal:$APPDIR/_internal/lib:${LD_LIBRARY_PATH:-}"

exec "$APPDIR/CrysDiS_tkinter" "$@"
""",
        encoding="utf-8",
    )
    launcher.chmod(0o755)


def write_desktop_launchers() -> None:
    desktop = DIST_DIR / "CrysDiS_tkinter.desktop"
    desktop.write_text(
        """[Desktop Entry]
Type=Application
Name=CrysDiS Tkinter
Comment=Crystal Diffraction Simulator - Tkinter Version
Exec=sh -c 'APPDIR="$(dirname "$(readlink -f "$1")")"; exec "$APPDIR/run_CrysDiS_tkinter.sh"' dummy %k
Terminal=false
Categories=Utility;Education;Science;
NoDisplay=false
Icon=assets/CrysDiS_tkinter.png
StartupNotify=true
""",
        encoding="utf-8",
    )
    desktop.chmod(0o755)

    installer = DIST_DIR / "install_launcher.sh"
    installer.write_text(
        """#!/usr/bin/env bash
set -euo pipefail

APPDIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_FILE="$HOME/.local/share/applications/CrysDiS_tkinter.desktop"

mkdir -p "$HOME/.local/share/applications"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=CrysDiS Tkinter
Comment=Crystal Diffraction Simulator - Tkinter Version
Exec=$APPDIR/run_CrysDiS_tkinter.sh
Path=$APPDIR
Icon=$APPDIR/assets/CrysDiS_tkinter.png
Terminal=false
Categories=Utility;Education;Science;
NoDisplay=false
StartupNotify=true
EOF

chmod +x "$APPDIR/run_CrysDiS_tkinter.sh"
chmod +x "$DESKTOP_FILE"

echo "CrysDiS Tkinter launcher installed."
echo "You can now search for CrysDiS Tkinter in your Linux application menu."
""",
        encoding="utf-8",
    )
    installer.chmod(0o755)


def post_build_linux() -> Path:
    if not DIST_DIR.exists():
        raise FileNotFoundError(f"Missing PyInstaller output folder: {DIST_DIR}")
    if not INTERNAL_DIR.exists():
        raise FileNotFoundError(f"Missing PyInstaller internal folder: {INTERNAL_DIR}")
    for library in conda_runtime_libraries():
        destination = INTERNAL_DIR / library.name
        if not destination.exists() and not destination.is_symlink():
            shutil.copy2(library, destination, follow_symlinks=True)
    force_symlink("libstdc++.so", "libstdc++.so.6.*")
    force_symlink("libstdc++.so.6", "libstdc++.so.6.*")
    force_symlink("libbz2.so", "libbz2.so.1.0.*")
    force_symlink("libbz2.so.1.0", "libbz2.so.1.0.*")
    copy_runtime_assets()
    write_linux_launcher()
    write_desktop_launchers()
    subprocess.check_call(["bash", str(VERIFY_SCRIPT)], cwd=ROOT)
    archive = DIST_ROOT / f"{APP_NAME}-Linux-{_dt.date.today():%Y%m%d}.tar.gz"
    if archive.exists():
        archive.unlink()
    subprocess.check_call(["tar", "-czf", archive.name, APP_NAME], cwd=DIST_ROOT)
    return archive


def pyinstaller_command(extra_args: list[str], clean: bool) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name",
        APP_NAME,
        "--onedir",
        "--noconfirm",
        "--add-data",
        data_arg(CLEAN_LIBRARY, "."),
        "--add-data",
        data_arg(ICON_SOURCE, "assets"),
        *collect_package_args(),
        *hidden_import_args(),
        *conda_runtime_binary_args(),
        *extra_args,
        str(ENTRY_POINT.name),
    ]
    if clean:
        command.insert(5, "--clean")
    return command


def main() -> int:
    check_clean_library()
    check_icon_source()
    dry_run = "--dry-run" in sys.argv[1:]
    clean = "--no-clean" not in sys.argv[1:]
    extra_args = [arg for arg in sys.argv[1:] if arg not in {"--dry-run", "--no-clean"}]
    command = pyinstaller_command(extra_args, clean)
    env = os.environ.copy()
    env["PATH"] = f"{Path(sys.executable).resolve().parent}{os.pathsep}{env.get('PATH', '')}"
    print("Running:", " ".join(command))
    if dry_run:
        return 0
    exit_code = subprocess.call(command, cwd=ROOT, env=env)
    if exit_code != 0:
        return exit_code
    if sys.platform == "linux":
        archive = post_build_linux()
        print(f"Linux release archive: {archive}")
    else:
        copy_runtime_assets()
        write_desktop_launchers()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
