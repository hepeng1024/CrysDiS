# CrysDiS Deployment Notes

This document is for developers who want to host CrysDiS as a web app or maintain deployment infrastructure.

For ordinary users, the easiest options are:

```text
Hosted web app
GitHub Releases desktop packages
Local source run with conda
```

## Local Docker Run

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

## Docker-Based Hosting

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

## Render Notes

The hosted Render app currently uses:

```text
https://crysdis.onrender.com
```

Render-style deployments may provide a `PORT` environment variable. The app should respect this for hosted deployment.

For the web deployment, keep desktop-only dependencies such as `pywebview` and packaging-only dependencies such as `pyinstaller` out of the normal web/runtime dependency path when possible. They can remain in optional packaging dependencies for desktop builds.

A recommended `pyproject.toml` dependency layout is:

```toml
dependencies = [
    "nicegui>=3.13,<4",
    "numpy>=2.0",
    "plotly>=6.0",
    "matplotlib>=3.8",
    "pymatgen>=2024.0",
    "periodictable>=2.0",
    "platformdirs",
]

[project.optional-dependencies]
desktop = [
    "pywebview",
]

package = [
    "pyinstaller",
    "pywebview",
]
```

If Render uses `requirements.txt`, keep that file web-safe too. In general, `platformdirs` is useful for both web and packaged modes, while `pywebview` and `pyinstaller` are only needed for desktop packaging.

## Privacy And Persistence

- CIF files are uploaded through the browser and parsed by the server.
- Bundled structures are read from `custom_crystals_local.json`.
- User edits and CIF imports are saved through `platformdirs` to the operating system's CrysDiS app-data folder.
- On a shared hosted deployment, saved custom structures are visible to other users of that same deployment account.
- For sensitive unpublished data, prefer a private lab server, university VM, VPN-protected service, or a private cloud app with authentication.
- Render-style filesystems may be ephemeral. If the server restarts, custom structures saved after deployment may disappear unless persistent storage is configured.

Common user-data locations:

```text
Windows: %LOCALAPPDATA%\CrysDiS\custom_crystals.json
Linux:   ${XDG_DATA_HOME:-~/.local/share}/CrysDiS/custom_crystals.json
macOS:   ~/Library/Application Support/CrysDiS/custom_crystals.json
```

## GitHub Pages

GitHub Pages can host a landing/documentation page with screenshots and a link to the deployed app. It cannot host the NiceGUI app itself because GitHub Pages does not run Python server code.

A GitHub Pages landing page can be useful for:

- screenshots
- download buttons
- links to GitHub Releases
- links to the Render-hosted app
- short tutorials or documentation

## Deployment Checklist

Before changing the hosted app:

1. Test `python CrysDiS.py` locally.
2. Test the Docker build locally if the deployment uses Docker.
3. Confirm dependency changes are compatible with Render or the chosen host.
4. Push source changes to GitHub.
5. Watch the deployment logs.
6. Open the deployed URL and test common workflows.
7. Check whether custom crystal persistence is expected to be temporary or persistent.
