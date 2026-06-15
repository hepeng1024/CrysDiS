# CrysDiS

CrysDiS stands for **Crystal Diffraction Simulator**. It is a browser-based crystal structure and electron diffraction simulator built with NiceGUI.

The recommended way to share this app with labmates on Linux, Windows, macOS, and iPad is to deploy it as a hosted web app. Users only need a browser.

## Launch

Hosted app URL:

```text
TODO: paste your deployed Render, lab-server, or university-server URL here
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

## Run Locally With Python

From this folder:

```bash
python -m pip install -e .
python CrysDiS.py
```

Then open:

```text
http://127.0.0.1:8080
```

You can choose another port:

```bash
NICEGUI_PORT=8094 python CrysDiS.py
```

## Run Locally With Docker

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

For local-only use, you can override the host:

```bash
HOST=127.0.0.1 NICEGUI_PORT=8094 python CrysDiS.py
```

## Privacy And Persistence Notes

- CIF files are uploaded through the browser and parsed by the server.
- Custom structures saved to the project-local library are stored in `custom_crystals_local.json`.
- On a shared hosted deployment, project-local custom structures are visible to other users of that same deployment.
- For sensitive unpublished data, prefer a private lab server, university VM, VPN-protected service, or a private cloud app with authentication.
- Render-style filesystems may be ephemeral. If the server restarts, custom structures saved after deployment may disappear unless persistent storage is configured.

## GitHub Pages

GitHub Pages can host a landing/documentation page with screenshots and a link to the deployed app. It cannot host the NiceGUI app itself because GitHub Pages does not run Python server code.

## Files

- `CrysDiS.py`: main app
- `pyproject.toml`: Python dependencies and optional console script
- `Dockerfile`: reproducible container build
- `.dockerignore`: keeps the Docker build context small
- `custom_crystals_local.json`: shared project-local custom structures
