# CrysDiS

**CrysDiS** stands for **Crystal Diffraction Simulator**. It is a NiceGUI-based crystal-structure and electron-diffraction simulator that can run as a hosted web app, a local browser app, or an operating-system-specific desktop-style package.

The easiest way to try CrysDiS is the hosted web app. However, it may be laggy and disconnect occasionally. The most robust way is to run the Python code directly (see Run From Source below). Desktop packages are useful when users want a double-click local app, which is convenient and performs better than the hosted web version.

## Introduction Slides

A short visual introduction to CrysDiS is available here:

- [CrysDiS introduction slides](docs/CrysDiS_intro.pdf)

## Launch Online

Hosted app:

```text
https://crysdis.onrender.com
```

## Download Desktop Packages

Desktop packages are available from the GitHub **Releases** page. For version `v0.1.6`, download the file matching your operating system.

Release assets:

```text
CrysDiS-Windows-v0.1.6.zip
CrysDiS-Linux-v0.1.6.tar.gz
CrysDiS-macOS-arm64-v0.1.6.zip
```

### Windows

1. Download `CrysDiS-Windows-v0.1.6.zip`.
2. Before extracting, right-click the zip file → Properties → General → Unblock → Apply → OK.
3. Extract/unzip the folder.
4. Open the extracted `CrysDiS` folder.
5. Double-click:

```text
CrysDiS.exe
```

### Linux

1. Download `CrysDiS-Linux-v0.1.6.tar.gz`.
2. Extract it:

```bash
tar -xzf CrysDiS-Linux-v0.1.6.tar.gz
cd CrysDiS
```

3. Run:

```bash
./run_CrysDiS.sh
```

Optional application-menu launcher:

```bash
./install_launcher.sh
```

After installing the launcher, search for **CrysDiS** in your Linux application menu.

### macOS

1. Download `CrysDiS-macOS-arm64-v0.1.6.zip`.
2. Unzip it.
3. Double-click:

```text
CrysDiS.app
```

If macOS blocks the app because it is unsigned, right-click `CrysDiS.app`, choose **Open**, then confirm. This is usually only needed the first time.

## What It Does

- Visualizes real-space unit cells, atom sites, crystallographic planes, real-space vectors, and reciprocal vectors.
- Simulates electron diffraction patterns with the built-in Ewald sphere kinematic method or pymatgen TEMCalculator.
- Supports custom structures, symmetry expansion, CIF upload, atom colors, occupancies, and lattice parameters.
- Supports multiple ordinary panels plus combo panels for overlapped multiphase diffraction patterns.
- Exports crystal and diffraction images with DPI and transparent-background options.

## Quick Use

1. Choose a crystal and enter a zone axis such as `100`, `110`, or `0001`.
2. Press `Apply`.
3. Add planes such as `123 (411) 1,1,4` or vectors such as `100 114 [123] *1,2,3` (see Input Formats below).
4. Rotate the 3D crystal with the mouse. Press `Sync` to update the diffraction pattern to the current view.
5. Use `Download` to export images.
6. Use `Add combo panel` to overlay diffraction patterns from multiple panels.

### Input Formats

In the **Plane** and **Vector** fields, use **spaces to separate different entries** and **commas to separate the components of one entry**. Compact and bracketed forms can be mixed in the same field.

| Entry type | Accepted examples |
| --- | --- |
| Real-space vector (`u,v,w`) | `114`, `1,1,4`, `[114]`, `[1,1,4]`, `[1 1 4]` |
| Reciprocal vector (`*u,v,w`) | `*123`, `*1,2,3`, `*[123]`, `*[1,2,3]`, `*[1 2 3]` |
| Plane (`h,k,l`) | `411`, `4,1,1`, `(411)`, `(4,1,1)`, `(4 1 1)` |

The letters above stand for integer indices. Reciprocal vectors also accept `r` or `R` instead of `*`, for example `r123`, `R1,2,3`, `r[123]`, and `R[1,2,3]`.

Examples with multiple entries:

- Vector: `100 114 [123]` displays all three vectors.
- Vector: `1,1,4 *1,2,3` mixes a real-space vector and a reciprocal vector.
- Plane: `123 (411) 1,1,4` displays all three planes.

For negative or multi-digit components, use forms such as `1,-1,10`, `[13 3 0]`, or `(1 2 27)`. Compact notation treats each digit as a separate component, so use commas or spaces inside brackets/parentheses to make multi-digit indices unambiguous. When mixing entries, enclose space-separated components in brackets/parentheses, or use commas without brackets.

Use `100 114`, not `100,114`, for two separate vectors or planes: commas mean components, not separate entries. Hexagonal structures also accept four-index forms such as `10-10`, `1,0,-1,0`, `[1 0 -1 0]`, or `(1 0 -1 0)` in the corresponding field.

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

## User Data And Privacy

- CIF files are uploaded through the browser and parsed by the running CrysDiS app.
- Bundled structures are read from `custom_crystals_local.json`.
- User edits and CIF imports are saved to the operating system's CrysDiS app-data folder.
- Desktop package image exports are saved to the selected export folder, or to `Downloads/CrysDiS` by default when that folder is available.
- Hosted web exports use the browser's normal download behavior instead of saving files on the server.
- On a shared hosted deployment, saved custom structures may be visible to other users of that same deployment account.
- For sensitive unpublished data, prefer the local desktop package, a private lab server, a university VM, a VPN-protected service, or a private cloud app with authentication.

Common user-data locations:

```text
Windows: %LOCALAPPDATA%\CrysDiS\custom_crystals.json
Linux:   ${XDG_DATA_HOME:-~/.local/share}/CrysDiS/custom_crystals.json
macOS:   ~/Library/Application Support/CrysDiS/custom_crystals.json
```

## Developer Documentation

Developer notes have been moved out of the main README:

```text
docs/PACKAGING.md
docs/DEPLOYMENT.md
```

Use `docs/PACKAGING.md` for Windows/Linux/macOS package-building notes. Use `docs/DEPLOYMENT.md` for Docker, Render, and hosted deployment notes.

## Main Files

- `CrysDiS.py`: main app
- `custom_crystals_local.json`: bundled custom crystal seed/library data
- `assets/`: app icons and bundled runtime assets
- `environment.yml`: conda environment for running from source
- `requirements.txt`: pip dependency list used by `environment.yml`
- `pyproject.toml`: Python project metadata and dependencies
- `Dockerfile`: reproducible container build
- `.dockerignore`: keeps the Docker build context small
