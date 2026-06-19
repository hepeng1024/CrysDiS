# CrysDiS Packaging Notes

This document is for developers who want to build CrysDiS desktop packages.

Desktop packages are operating-system specific:

```text
Build on Windows → Windows package
Build on Linux   → Linux package
Build on macOS   → macOS package
```

Do **not** commit generated package folders such as `build/`, `dist/`, or `*.spec`. Upload final release archives as GitHub Release assets.

Suggested release asset names:

```text
CrysDiS-Windows-v0.1.0.zip
CrysDiS-Linux-v0.1.0.tar.gz
CrysDiS-macOS-arm64-v0.1.0.zip
```

## Package Data Behavior

Packaged apps include a clean bundled `custom_crystals_local.json` seed library. User-created structures and uploaded CIF structures are saved in the user's app-data folder, not inside the bundled app folder.

Common user-data locations:

```text
Windows: %LOCALAPPDATA%\CrysDiS\custom_crystals.json
Linux:   ${XDG_DATA_HOME:-~/.local/share}/CrysDiS/custom_crystals.json
macOS:   ~/Library/Application Support/CrysDiS/custom_crystals.json
```

## Windows Desktop Package

From Windows PowerShell in this folder, create and activate an environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If you already have the `crysdis` conda environment, activate it instead:

```powershell
conda activate crysdis
```

Run normally during development:

```powershell
python CrysDiS.py
```

Test the desktop/native branch:

```powershell
$env:CRYSDIS_DESKTOP = "1"
python CrysDiS.py
Remove-Item Env:\CRYSDIS_DESKTOP
```

Build the Windows package:

```powershell
.\package_windows.ps1
```

If PowerShell has not activated the desired environment, point the script at a specific interpreter:

```powershell
$env:PYTHON = "C:\Users\MaxPeng\miniconda3\envs\crysdis\python.exe"
.\package_windows.ps1
Remove-Item Env:\PYTHON
```

The output appears at:

```text
dist\CrysDiS\CrysDiS.exe
```

The build uses `assets\CrysDiS.ico` as the executable icon and bundles the full `assets\` folder, including `CrysDiS.ico` and `CrysDiS.png`.

For distribution, zip the whole folder:

```text
dist\CrysDiS\
```

Do not share only `CrysDiS.exe`, because the `--onedir` executable needs the bundled support files next to it.

## Linux Desktop Package

These commands apply to the Linux packaging checkout that contains the Ubuntu packaging helpers such as `pack_onedir.py`, `requirements-build.txt`, and `scripts/verify_linux_bundle.sh`.

Install the normal environment first:

```bash
conda env create -f environment.yml
conda activate crysdis
```

Install the packaging helper dependencies:

```bash
python -m pip install -r requirements-build.txt
```

Build the Linux app folder:

```bash
python pack_onedir.py
```

The Linux output appears at:

```text
dist/CrysDiS/
```

The Linux helper also verifies the bundle, writes launcher files, and creates a release archive like:

```text
dist/CrysDiS-Linux-YYYYMMDD.tar.gz
```

Share the `.tar.gz` archive for Linux users. This preserves executable permissions and library symlinks more reliably than a Windows-created `.zip`.

Linux users can run:

```bash
tar -xzf CrysDiS-Linux-YYYYMMDD.tar.gz
cd CrysDiS
./run_CrysDiS.sh
```

Optional Linux application-menu launcher:

```bash
./install_launcher.sh
```

After running `install_launcher.sh`, users can search for **CrysDiS** in their Linux application menu. This installs a user-local launcher in `~/.local/share/applications` and does not require `sudo`.

Users can also try double-clicking `CrysDiS.desktop` inside the extracted `CrysDiS` folder. Some Linux desktops may ask the user to right-click and choose **Allow Launching**, **Trust and Launch**, or a similar trust option the first time.

For Linux packaged releases, use `run_CrysDiS.sh`, `CrysDiS.desktop`, or the installed app-menu launcher. The raw `CrysDiS` executable is not the recommended double-click target because the launcher prepares bundled runtime libraries before starting the app.

To verify an existing Linux bundle manually:

```bash
scripts/verify_linux_bundle.sh
```

For faster repeated local test builds after the first successful Linux build:

```bash
python pack_onedir.py --no-clean
```

## macOS Desktop Package

The macOS package can be built with GitHub Actions on a macOS runner or manually on a Mac.

The expected output is a zipped macOS app bundle:

```text
dist/CrysDiS-macOS.zip
```

When unzipped on a Mac, it should contain:

```text
CrysDiS.app
```

### Required Repo Files

For GitHub Actions macOS packaging, keep these files in the repo:

```text
package_macos.sh
.github/workflows/build-macos.yml
assets/CrysDiS.png
assets/CrysDiS.ico
custom_crystals_local.json
CrysDiS.py
pyproject.toml
requirements.txt
```

The script can generate `assets/CrysDiS.icns` from `assets/CrysDiS.png` during the macOS build if `CrysDiS.icns` is not already present.

### Run The GitHub Actions Build

On GitHub:

```text
Repository → Actions → Build macOS CrysDiS → Run workflow
```

After the workflow finishes:

```text
Open the workflow run → Artifacts → download CrysDiS-macOS-arm64
```

The downloaded artifact should contain `CrysDiS-macOS.zip`.

### Manual macOS Build

On a Mac:

```bash
git clone https://github.com/hepeng1024/CrysDiS.git
cd CrysDiS
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[package]"
bash package_macos.sh
```

### macOS Signing Note

The current package is intended for testing or lab sharing. If the app is unsigned, macOS may warn users the first time they open it. Users can usually right-click `CrysDiS.app`, choose **Open**, and confirm. For polished public distribution, macOS apps should eventually be Developer ID signed and notarized.

## Release Checklist

Before creating a release:

1. Update the version/tag name, for example `v0.1.0`.
2. Build and test the Windows package on Windows.
3. Build and test the Linux package on Linux.
4. Build the macOS package with GitHub Actions or on a Mac.
5. Upload the generated archives to GitHub Releases.
6. Do not commit `dist/`, `build/`, generated archives, or `*.spec` files to the normal source tree.

Useful local checks:

```bash
git status
git ls-files assets
```

Expected important icon assets:

```text
assets/CrysDiS.png
assets/CrysDiS.ico
```
