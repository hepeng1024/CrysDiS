# CrysDiS

CrysDiS stands for **Crystal Diffraction Simulator**. It is a NiceGUI crystal-structure and electron-diffraction simulator that can run as a hosted web app, a local browser app, or an operating-system-specific desktop-style package.

The easiest way to share CrysDiS across Linux, Windows, macOS, and iPad is still a hosted web deployment. Desktop packages are useful when users need a double-click local app.

## Launch

Hosted app URL:

```text
https://crysdis.onrender.com
```

## What It Does

- Visualizes real-space unit cells, atom sites, crystallographic planes, real-space vectors, and reciprocal vectors.
- Simulates electron diffraction patterns with the built-in Ewald sphere kinematic method or pymatgen TEMCalculator.
- Supports custom structures, symmetry expansion, CIF upload, atom colors, occupancies, and lattice parameters.
- Supports multiple ordinary panels plus combo panels for overlapped multiphase diffraction patterns.
- Exports crystal and diffraction images with DPI and transparent-background options.

## Quick Use

1. Choose a crystal and enter a zone axis such as `100`, `110`, or `0001`.
2. Press `Apply`.
3. Add planes such as `100 123` or vectors such as `110 -1-1-2`.
4. Rotate the 3D crystal with the mouse. Press `Sync` to update the diffraction pattern to the current view.
5. Use `Download` to export images.
6. Use `Add combo panel` to overlay diffraction patterns from multiple panels.

## Run From Source

First install Git and Anaconda/Miniconda. Then clone the repository:

```bash
git clone https://github.com/hepeng1024/CrysDiS.git
cd CrysDiS
```

Create and activate the conda environment:

```bash
conda env create -f environment.yml
conda activate crysdis
```

Start CrysDiS:

```bash
python CrysDiS.py
```

Then open:

```text
http://127.0.0.1:8080
```

Choose another port when needed:

```bash
NICEGUI_PORT=8094 python CrysDiS.py
```

On Windows PowerShell:

```powershell
$env:NICEGUI_PORT = "8094"
python CrysDiS.py
Remove-Item Env:\NICEGUI_PORT
```

## Update A Clone

```bash
cd CrysDiS
git pull
conda env update -f environment.yml --prune
conda activate crysdis
python CrysDiS.py
```

## Run With Pip

From this folder:

```bash
python -m pip install -e .
python CrysDiS.py
```

Then open:

```text
http://127.0.0.1:8080
```

## Desktop Packaging

Desktop packages are operating-system specific. Build on Windows for Windows users, on Linux for Linux users, and on macOS for macOS users. Do not commit `dist/` or `build/`; upload generated release archives as GitHub Release assets or share them through cloud storage or a lab server.

### Windows Desktop Package

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

### Linux Desktop Package

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

### Package Data

Packaged apps include a clean bundled `custom_crystals_local.json` seed library. User-created structures and uploaded CIF structures are saved in the user's app-data folder, not inside the bundled app folder.

Common user-data locations:

```text
Windows: %LOCALAPPDATA%\CrysDiS\custom_crystals.json
Linux:   ${XDG_DATA_HOME:-~/.local/share}/CrysDiS/custom_crystals.json
```

## Run With Docker

Build:

```bash
docker build -t crysdis .
```

Run:

```bash
docker run --rm -p 8080:8080 crysdis
```

Open:

```text
http://localhost:8080
```

## Deploy With Docker

This project is ready for Docker-based hosting.

Typical hosted deployment flow:

1. Create a GitHub repository.
2. Push this folder to GitHub.
3. Create a Docker-based web service on Render, a lab server, a department server, or a university-managed VM.
4. Point the service at this repository.
5. Make sure the service exposes port `8080` or provides a `PORT` environment variable.
6. Share the deployed URL with labmates.

The app reads these environment variables:

```text
PORT=8080
HOST=0.0.0.0
```

For local-only use, override the host:

```bash
HOST=127.0.0.1 NICEGUI_PORT=8094 python CrysDiS.py
```

## Privacy And Persistence

- CIF files are uploaded through the browser and parsed by the server.
- Bundled structures are read from `custom_crystals_local.json`.
- User edits and CIF imports are saved through `platformdirs` to the operating system's CrysDiS app-data folder.
- On a shared hosted deployment, saved custom structures are visible to other users of that same deployment account.
- For sensitive unpublished data, prefer a private lab server, university VM, VPN-protected service, or a private cloud app with authentication.
- Render-style filesystems may be ephemeral. If the server restarts, custom structures saved after deployment may disappear unless persistent storage is configured.

## GitHub Pages

GitHub Pages can host a landing/documentation page with screenshots and a link to the deployed app. It cannot host the NiceGUI app itself because GitHub Pages does not run Python server code.

## Files

- `CrysDiS.py`: main app
- `pyproject.toml`: Python dependencies and optional console script
- `environment.yml`: conda environment for running from source
- `requirements.txt`: pip dependency list used by `environment.yml`
- `package_windows.ps1`: PyInstaller build script for the Windows desktop package
- `assets/`: app icons and bundled runtime assets
- `Dockerfile`: reproducible container build
- `.dockerignore`: keeps the Docker build context small
- `custom_crystals_local.json`: bundled custom crystal seed/library data

Linux packaging helper files from the Ubuntu build may include `requirements-build.txt`, `pack_onedir.py`, `packaging/custom_crystals_local.json`, and `scripts/verify_linux_bundle.sh`.
