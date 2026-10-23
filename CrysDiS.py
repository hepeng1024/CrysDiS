from __future__ import annotations

import asyncio
import base64
import colorsys
import copy
import hashlib
import io
import importlib.util
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import uuid
import warnings
from dataclasses import asdict, dataclass, field, replace
from fractions import Fraction
from functools import lru_cache
from html import escape
from itertools import product
from pathlib import Path
from typing import Any, Callable

import numpy as np
from nicegui import app, core, native, ui
# Register event/marker dragging before NiceGUI builds the initial page's import map.
from nicegui.elements import sortable as _sortable
from CrysDiS_views import DisplayPresetStore
from CrysDiS_markers import (CrystalMarker, MarkerEditor, THREE_MARKERS_SCRIPT,
                            marker_geometry, marker_extent_points, marker_hidden_atom_indices,
                            validate_markers, clean_coordinate, point_text, coordinate_grid_geometry,
                            CoordinateGridSettings)


try:
    from platformdirs import user_data_dir
except Exception:
    user_data_dir = None


def resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def app_data_dir() -> Path:
    if user_data_dir is not None:
        return Path(user_data_dir("CrysDiS", appauthor=False))
    return Path.home() / ".crysdis"


def default_export_dir() -> Path:
    return Path.home() / "Downloads"


def normalize_export_path(path_text: str) -> Path:
    cleaned = str(path_text or "").strip().strip('"').strip("'")
    return Path(os.path.expandvars(os.path.expanduser(cleaned)))


def system_export_folder_dialog(start_dir: Path) -> tuple[Path | None, bool]:
    start_dir = Path(start_dir).expanduser()
    if sys.platform.startswith("linux"):
        linux_dialogs = [
            ("zenity", ["zenity", "--file-selection", "--directory", "--filename", f"{start_dir}{os.sep}"]),
            ("kdialog", ["kdialog", "--getexistingdirectory", str(start_dir)]),
            ("yad", ["yad", "--file-selection", "--directory", "--filename", f"{start_dir}{os.sep}"]),
        ]
        for executable, command in linux_dialogs:
            if shutil.which(executable) is None:
                continue
            try:
                result = subprocess.run(command, capture_output=True, text=True)
            except OSError:
                continue
            folder_text = result.stdout.strip()
            if result.returncode == 0 and folder_text:
                return normalize_export_path(folder_text), True
            if result.returncode != 0 and result.stderr.strip():
                continue
            return None, True

    if sys.platform.startswith(("linux", "darwin", "win")):
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            try:
                root.attributes("-topmost", True)
            except tk.TclError:
                pass
            folder_text = filedialog.askdirectory(
                initialdir=str(start_dir),
                title="Choose CrysDiS export folder",
                mustexist=False,
            )
            root.destroy()
            return (normalize_export_path(folder_text), True) if folder_text else (None, True)
        except Exception:
            return None, False

    return None, False


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def system_save_file_dialog(suggested: Path, extension: str) -> tuple[Path | None, bool]:
    """Return (selection, picker_available), distinguishing Cancel from failure."""
    if sys.platform.startswith("linux"):
        commands = (
            ("zenity", ["zenity", "--file-selection", "--save", "--confirm-overwrite", f"--filename={suggested}"]),
            ("kdialog", ["kdialog", "--getsavefilename", str(suggested), f"*{extension}"]),
            ("yad", ["yad", "--file-selection", "--save", "--confirm-overwrite", f"--filename={suggested}"]),
        )
        for executable, command in commands:
            if shutil.which(executable):
                try:
                    result = subprocess.run(command, capture_output=True, text=True)
                    if result.returncode == 0:
                        value = result.stdout.strip()
                        return (normalize_export_path(value) if value else None), True
                    if not result.stderr.strip():
                        return None, True
                except OSError:
                    pass
    root = None
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        value = filedialog.asksaveasfilename(title="Save CrysDiS file as", initialdir=str(suggested.parent),
            initialfile=suggested.name, defaultextension=extension,
            filetypes=[(extension[1:].upper() + " files", "*" + extension)], confirmoverwrite=True)
        return (normalize_export_path(value) if value else None), True
    except Exception:
        return None, False
    finally:
        if root is not None:
            root.destroy()


def is_desktop_mode() -> bool:
    return is_frozen_app() or os.environ.get("CRYSDIS_DESKTOP") == "1"


def is_hosted_mode() -> bool:
    port_env = os.environ.get("PORT")
    return not is_desktop_mode() and (os.environ.get("RENDER") == "true" or (port_env is not None and os.name != "nt"))


def direct_file_exports_enabled() -> bool:
    return is_desktop_mode() and not is_hosted_mode()


def decode_png_data_url(data_url: str) -> bytes:
    prefix = "data:image/png;base64,"
    if not isinstance(data_url, str) or not data_url.startswith(prefix):
        raise ValueError("Plotly did not return a PNG data URL")
    return base64.b64decode(data_url[len(prefix) :], validate=True)


def sanitize_export_filename_stem(value: Any, fallback: str = "crysdis_export") -> str:
    text = str(value or "").strip()
    if text.lower().endswith(".png"):
        text = text[:-4]
    text = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", text)
    text = re.sub(r"\s+", "_", text)
    text = text.strip(" ._")
    fallback_text = re.sub(r"[\\/:*?\"<>|\x00-\x1f\s]+", "_", str(fallback or "crysdis_export")).strip(" ._")
    return text or fallback_text or "crysdis_export"


def sanitize_export_filename(value: Any, fallback_stem: str = "crysdis_export", extension: str = ".png") -> str:
    suffix = "." + str(extension or ".png").lstrip(".")
    text = str(value or "").strip()
    if text.lower().endswith(suffix.lower()):
        text = text[: -len(suffix)]
    return f"{sanitize_export_filename_stem(text, fallback_stem)}{suffix}"


def export_image_filename(
    filename_base: Any,
    fallback_base: str,
    dpi: float,
    transparent_background: bool = False,
    include_suffixes: bool = True,
) -> str:
    stem = sanitize_export_filename_stem(filename_base, fallback_base)
    if not include_suffixes:
        return sanitize_export_filename(stem, fallback_base)
    transparent_suffix = "_transparent" if transparent_background else ""
    return sanitize_export_filename(f"{stem}{transparent_suffix}_{round(float(dpi))}dpi", fallback_base)


def find_open_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


APP_DIR = resource_dir()
BUNDLED_LIBRARY_PATH = APP_DIR / "custom_crystals_local.json"
USER_DATA_DIR = app_data_dir()
USER_LIBRARY_PATH = USER_DATA_DIR / "custom_crystals.json"
ELEMENT_COLORS_PATH = USER_DATA_DIR / "element_colors.json"
DISPLAY_PRESETS_PATH = USER_DATA_DIR / "display_presets.json"
THEME_PATH = USER_DATA_DIR / "theme.json"
SAVED_THEMES_PATH = USER_DATA_DIR / "saved_themes.json"
LEGACY_LIBRARY_PATH = Path.home() / ".crystal_diffraction_simulator" / "custom_crystals.json"
LOCAL_LIBRARY_PATH = BUNDLED_LIBRARY_PATH
GLOBAL_LIBRARY_PATH = USER_LIBRARY_PATH
USER_LIBRARY_SCOPE = "User app-data library"

CUSTOM_SENTINEL = "Create / edit customized crystal..."
SIMULATION_METHOD_EWALD = "Ewald Sphere Kinematic"
SIMULATION_METHOD_PYMATGEN = "Pymatgen TEMCalculator"
SIMULATION_METHODS = (SIMULATION_METHOD_EWALD, SIMULATION_METHOD_PYMATGEN)
SIMULATION_METHOD = SIMULATION_METHOD_PYMATGEN
DEFAULT_VOLTAGE_KV = 500.0
DEFAULT_THICKNESS_NM = 30.0
DEFAULT_MAX_HKL = 7
DEFAULT_ZONE_AXIS_SEARCH_MAX = 18
_ZONE_AXIS_CANDIDATE_CACHE: dict[tuple[tuple[float, ...], int], tuple[np.ndarray, np.ndarray]] = {}
DEFAULT_CAMERA_LENGTH_MM = 200.0
DIFFRACTION_BASE_LIMIT_NM_INV = 16.0
DEFAULT_SPOT_INTENSITY_THRESHOLD = 1e-4
MIN_SPOT_INTENSITY_THRESHOLD = 1e-10
DEFAULT_SPOT_SIZE_SCALING = 0.3
DEFAULT_INTENSITY_COMPRESSION_FACTOR = 100.0
BASE_DIFFRACTION_MARKER_SIZE = 5.0
EXTRA_DIFFRACTION_MARKER_SIZE = 22.0
MOTT_BETHE_CONVERSION_ANGSTROM_INV = 0.023934
MOTT_BETHE_S_TOL = 1e-8
FALLBACK_XRAY_GAUSSIAN_B = 2.8
ZONE_AXIS_EXACT_TOL_DEGREES = 0.5
CAMERA_LENGTH_OPTIONS = ("80 mm", "100 mm", "150 mm", "200 mm", "300 mm", "500 mm", "800 mm", "1000 mm", "1500 mm")
REAL_SCENE_FOV_DEGREES = 1.0
REAL_SCENE_FIT_FRACTION = 0.9
REAL_SCENE_ASPECT = 440.0 / 280.0
REAL_SCENE_ATOM_RADIUS = 0.072
REAL_SCENE_ATOM_MIN_RADIUS_SCALE = 0.38
REAL_SCENE_ATOM_SPACING_FRACTION = 0.35
CRYSTAL_EXPORT_ATOM_MARKER_SIZE = 160.0
MAX_FRAME_THICKNESS = 20.0
IDEAL_HCP_CA = math.sqrt(8.0 / 3.0)
SYMMETRY_SITE_TOL = 5e-3

LATTICE_SYSTEMS = [
    "cubic",
    "tetragonal",
    "orthorhombic",
    "hexagonal",
    "monoclinic",
    "triclinic",
]

FALLBACK_ELEMENTS = [
    "H",
    "He",
    "Li",
    "Be",
    "B",
    "C",
    "N",
    "O",
    "F",
    "Ne",
    "Na",
    "Mg",
    "Al",
    "Si",
    "P",
    "S",
    "Cl",
    "Ar",
    "K",
    "Ca",
    "Sc",
    "Ti",
    "V",
    "Cr",
    "Mn",
    "Fe",
    "Co",
    "Ni",
    "Cu",
    "Zn",
    "Ga",
    "Ge",
    "As",
    "Se",
    "Br",
    "Kr",
    "Rb",
    "Sr",
    "Y",
    "Zr",
    "Nb",
    "Mo",
    "Tc",
    "Ru",
    "Rh",
    "Pd",
    "Ag",
    "Cd",
    "In",
    "Sn",
    "Sb",
    "Te",
    "I",
    "Xe",
    "Cs",
    "Ba",
    "La",
    "Ce",
    "Pr",
    "Nd",
    "Pm",
    "Sm",
    "Eu",
    "Gd",
    "Tb",
    "Dy",
    "Ho",
    "Er",
    "Tm",
    "Yb",
    "Lu",
    "Hf",
    "Ta",
    "W",
    "Re",
    "Os",
    "Ir",
    "Pt",
    "Au",
    "Hg",
    "Tl",
    "Pb",
    "Bi",
    "Po",
    "At",
    "Rn",
    "Fr",
    "Ra",
    "Ac",
    "Th",
    "Pa",
    "U",
    "Np",
    "Pu",
    "Am",
    "Cm",
    "Bk",
    "Cf",
    "Es",
    "Fm",
    "Md",
    "No",
    "Lr",
    "Rf",
    "Db",
    "Sg",
    "Bh",
    "Hs",
    "Mt",
    "Ds",
    "Rg",
    "Cn",
    "Nh",
    "Fl",
    "Mc",
    "Lv",
    "Ts",
    "Og",
]


def elements_from_periodictable() -> list[str]:
    try:
        import periodictable
    except Exception:
        return FALLBACK_ELEMENTS.copy()
    symbols: list[str] = []
    for element in periodictable.elements:
        number = getattr(element, "number", None)
        symbol = str(getattr(element, "symbol", "") or "")
        if number and 1 <= int(number) <= 118 and re.fullmatch(r"[A-Z][a-z]?", symbol):
            symbols.append(symbol)
    return symbols or FALLBACK_ELEMENTS.copy()


ELEMENTS = elements_from_periodictable()

FALLBACK_ATOMIC_NUMBERS = {symbol: number for number, symbol in enumerate(FALLBACK_ELEMENTS, start=1)}


def atomic_numbers_from_periodictable(symbols: list[str]) -> dict[str, int]:
    numbers = dict(FALLBACK_ATOMIC_NUMBERS)
    try:
        import periodictable
    except Exception:
        return numbers
    for symbol in symbols:
        element = getattr(periodictable, symbol, None)
        number = getattr(element, "number", None)
        if number:
            numbers[symbol] = int(number)
    return numbers


ATOMIC_NUMBERS = atomic_numbers_from_periodictable(sorted({*ELEMENTS, *FALLBACK_ATOMIC_NUMBERS}))

ELEMENT_COLORS = {
    "Al": "#FFFB00",
    "C": "#30323D",
    "Co": "#0351FA",
    "Cr": "#FF9100",
    "Cu": "#ADEC1A",
    "Fe": "#e81010",
    "Mg": "#F4B942",
    "Mn": "#d9be0f",
    "Mo": "#88AC07",
    "N": "#5CAEFA",
    "Ni": "#ed02e9",
    "O": "#EF476F",
    "Si": "#D38A3C",
    "Ti": "#03fc07",
    "Zr": "#8F5D12",
    "Hf": "#F5A9F2",
    "V": "#6BB891",
    "Nb": "#5D29EC",
    "Ta": "#04C02D",
    "W": "#5E6472",
    "Zn": "#8AB6D6",
}


def normalized_hex_color(color: str) -> str | None:
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(color or "").strip())
    return f"#{match.group(1).upper()}" if match else None


def generated_element_color(atomic_number: int, offset: int = 0) -> str:
    hue = (0.071 + (atomic_number + offset * 17) * 0.618033988749895) % 1.0
    saturation = 0.58 + 0.22 * (((atomic_number + offset * 3) % 5) / 4.0)
    value = 0.70 + 0.24 * (((atomic_number * 3 + offset * 5) % 7) / 6.0)
    red, green, blue = colorsys.hsv_to_rgb(hue, saturation, value)
    return f"#{int(round(red * 255)):02X}{int(round(green * 255)):02X}{int(round(blue * 255)):02X}"


def build_generated_element_colors() -> dict[str, str]:
    used = {color for color in (normalized_hex_color(color) for color in ELEMENT_COLORS.values()) if color is not None}
    generated: dict[str, str] = {}
    for symbol in ELEMENTS:
        if symbol in ELEMENT_COLORS:
            continue
        atomic_number = ATOMIC_NUMBERS.get(symbol, FALLBACK_ATOMIC_NUMBERS.get(symbol, len(generated) + 1))
        for offset in range(256):
            color = generated_element_color(int(atomic_number), offset)
            if color not in used:
                generated[symbol] = color
                used.add(color)
                break
        else:
            raise RuntimeError(f"Could not assign a unique color for element {symbol}")
    return generated


GENERATED_ELEMENT_COLORS = build_generated_element_colors()

# Cromer-Mann neutral-atom X-ray form-factor coefficients. They are used here
# as a practical element-specific kinematic scattering envelope. The active
# table is filled from periodictable.cromermann when available; this legacy
# table only keeps the simulator usable if that optional data source is absent.
LEGACY_CROMER_MANN = {
    "Al": ([6.4202, 1.9002, 1.5936, 1.9646], [3.0387, 0.7426, 31.5472, 85.0886], 1.1151),
    "Co": ([12.2841, 7.3409, 4.0034, 2.3488], [4.2791, 0.2784, 13.5359, 71.1692], 1.0118),
    "Cr": ([10.6406, 7.3537, 3.3240, 1.4922], [6.1038, 0.3920, 20.2626, 98.7399], 1.1832),
    "Cu": ([13.3380, 7.1676, 5.6158, 1.6735], [3.5828, 0.2470, 11.3966, 64.8126], 1.1910),
    "Fe": ([11.7695, 7.3573, 3.5222, 2.3045], [4.7611, 0.3072, 15.3535, 76.8805], 1.0369),
    "Mg": ([5.4204, 2.1735, 1.2269, 2.3073], [2.8275, 79.2611, 0.3808, 7.1937], 0.8584),
    "Mn": ([11.2819, 7.3573, 3.0193, 2.2441], [5.3409, 0.3432, 17.8674, 83.7543], 1.0896),
    "Ni": ([12.8376, 7.2920, 4.4438, 2.3800], [3.8785, 0.2565, 12.1763, 66.3421], 1.0341),
}


def cromer_mann_from_periodictable(symbol: str) -> tuple[list[float], list[float], float] | None:
    try:
        from periodictable import cromermann

        formula = cromermann.getCMformula(symbol)
        return (
            [float(value) for value in formula.a],
            [float(value) for value in formula.b],
            float(formula.c),
        )
    except Exception:
        return None


def build_cromer_mann_table() -> dict[str, tuple[list[float], list[float], float]]:
    table = dict(LEGACY_CROMER_MANN)
    for symbol in sorted({*ELEMENTS, *LEGACY_CROMER_MANN}):
        coefficients = cromer_mann_from_periodictable(symbol)
        if coefficients is not None:
            table[symbol] = coefficients
    return table


CROMER_MANN = build_cromer_mann_table()

PLANE_COLORS = ["#FF6B6B", "#FFD166", "#06D6A0", "#4DABF7", "#C77DFF", "#F783AC"]
VECTOR_COLORS = ["#E63946", "#F4A261", "#2A9D8F", "#577590", "#B5179E", "#ED80E4"]
PLANE_FILL_TEXTURE = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4////fwAJ+wP9KobjigAAAABJRU5ErkJggg=="
)
DEFAULT_DIFFRACTION_COLORS = {
    "FCC": "#31F7F1",
    "BCC": "#F77F00",
    "HCP": "#B985FF",
}
LIGHT_BACKGROUND_DEMO_COLORS = {"FCC": "#087F83", "BCC": "#B45309", "HCP": "#7E45B8"}


@dataclass
class AtomicSite:
    element: str
    x: float
    y: float
    z: float
    occupancy: float = 1.0
    label: str = ""
    color: str = ""

    @property
    def fractional(self) -> np.ndarray:
        return np.array([self.x, self.y, self.z], dtype=float)


@dataclass
class CrystalDefinition:
    name: str
    lattice_system: str
    a: float
    b: float
    c: float
    alpha: float
    beta: float
    gamma: float
    space_group: str = "P1"
    repeat_boundary_atoms: bool = True
    sites: list[AtomicSite] = field(default_factory=list)
    symmetry_operations: list[str] = field(default_factory=list)
    structure_id: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CrystalDefinition":
        sites = [atomic_site_from_dict(site) for site in data.get("sites", [])]
        return cls(
            name=str(data.get("name", "Untitled crystal")).strip() or "Untitled crystal",
            lattice_system=str(data.get("lattice_system", "triclinic")).lower(),
            a=float(data.get("a", 0.3)),
            b=float(data.get("b", data.get("a", 0.3))),
            c=float(data.get("c", data.get("a", 0.3))),
            alpha=float(data.get("alpha", 90.0)),
            beta=float(data.get("beta", 90.0)),
            gamma=float(data.get("gamma", 90.0)),
            space_group=str(data.get("space_group", data.get("symmetry", "P1")) or "P1"),
            repeat_boundary_atoms=bool(data.get("repeat_boundary_atoms", True)),
            sites=sites,
            symmetry_operations=list(data.get("symmetry_operations", [])),
            structure_id=str(data.get("structure_id", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DisplayAtom:
    element: str
    position: np.ndarray
    occupancy: float
    label: str = ""
    color: str = ""
    radius_multiplier: float = 1.0
    components: tuple[tuple[str, float, str], ...] = ()


@dataclass
class AnnotationStyle:
    font_size: float = 12.0
    color: str = "#F7FAFC"
    position: str = "bottom_left"
    opacity: float = 1.0


@dataclass
class PanelAnnotations:
    real_scale_visible: bool = True
    reciprocal_scale_visible: bool = True
    real_scale: AnnotationStyle = field(default_factory=AnnotationStyle)
    reciprocal_scale: AnnotationStyle = field(default_factory=lambda: AnnotationStyle(font_size=11))
    zone: AnnotationStyle = field(default_factory=lambda: AnnotationStyle(position="bottom_right", opacity=.9))
    indices: AnnotationStyle = field(default_factory=lambda: AnnotationStyle(font_size=9, position="up", opacity=.88))
    index_offset: float = 4.0


ANNOTATION_CORNERS = {"top_left": "Top left", "top_right": "Top right",
                      "bottom_left": "Bottom left", "bottom_right": "Bottom right"}
SPOT_LABEL_DIRECTIONS = {"upper_left": (-1, 1), "up": (0, 1), "upper_right": (1, 1),
                         "left": (-1, 0), "right": (1, 0),
                         "bottom_left": (-1, -1), "bottom": (0, -1), "bottom_right": (1, -1)}
ANNOTATION_STYLE_NAMES = ("real_scale", "reciprocal_scale", "zone", "indices")


@dataclass
class PanelBackgrounds:
    crystal: str = "#000000"
    diffraction: str = "#000000"
    automatic_text: bool = False


@dataclass
class InterfaceTheme:
    dark: bool = True
    primary: str = "#6E97CD"
    secondary: str = "#88E0E5"
    page: str = "#11161D"
    surface: str = "#1E1E1E"
    panel: str = "#18202A"
    header: str = "#161C24"
    text: str = "#EEF2F6"
    muted: str = "#B8C0CC"
    backgrounds: PanelBackgrounds = field(default_factory=PanelBackgrounds)


THEME_PRESETS = {
    "Classic dark": InterfaceTheme(),
    "Graphite": InterfaceTheme(primary="#71C5B1", secondary="#F2BF77", page="#151515",
                                surface="#222222", panel="#202020", header="#191919",
                                backgrounds=PanelBackgrounds("#101414", "#0E1113", True)),
    "Light": InterfaceTheme(dark=False, primary="#245DA8", secondary="#087E75", page="#F4F5F7",
                             surface="#FFFFFF", panel="#FFFFFF", header="#E9EDF2", text="#20242B", muted="#58616F",
                             backgrounds=PanelBackgrounds("#FFFFFF", "#FFFFFF", True)),
    "Forest": InterfaceTheme(dark=False, primary="#286B50", secondary="#A3446B", page="#F2F5F3",
                              surface="#FFFFFF", panel="#FAFCFB", header="#E5EDE8", text="#20382C", muted="#52665A",
                              backgrounds=PanelBackgrounds("#F4FAF6", "#F9FBFA", True)),
    "Carbon": InterfaceTheme(primary="#E3B75A", secondary="#72C9D1", page="#101010",
                              surface="#202020", panel="#191919", header="#151515", text="#F3F3F3", muted="#BABABA",
                              backgrounds=PanelBackgrounds("#000000", "#000000", True)),
    "Rose": InterfaceTheme(primary="#E99AB7", secondary="#95CDB8", page="#181619",
                            surface="#262227", panel="#211E22", header="#1D191E", text="#F5EFF3", muted="#C8BAC3",
                            backgrounds=PanelBackgrounds("#171217", "#141116", True)),
    "Lagoon": InterfaceTheme(dark=False, primary="#066F76", secondary="#B64B36", page="#F2F7F7",
                              surface="#FFFFFF", panel="#FBFDFD", header="#E3EEEE", text="#203638", muted="#53696B",
                              backgrounds=PanelBackgrounds("#F1FAFB", "#F8FCFD", True)),
    "Ruby": InterfaceTheme(dark=False, primary="#A3324D", secondary="#326CA0", page="#F8F4F5",
                            surface="#FFFFFF", panel="#FDFBFC", header="#F0E6E9", text="#38262D", muted="#715D66",
                            backgrounds=PanelBackgrounds("#FDF5F7", "#FFFAFB", True)),
    "Jade": InterfaceTheme(primary="#82D6AD", secondary="#E7AD8F", page="#141B18",
                            surface="#222B26", panel="#1B241F", header="#18201C", text="#EEF5F0", muted="#B7C8BD",
                            backgrounds=PanelBackgrounds("#101B16", "#0D1511", True)),
    "Ember": InterfaceTheme(primary="#F3A08A", secondary="#8BCED8", page="#1B1919",
                             surface="#2A2525", panel="#231F1F", header="#201B1B", text="#F7F0ED", muted="#CBBDB7",
                             backgrounds=PanelBackgrounds("#1A1414", "#151212", True)),
    "Orchid": InterfaceTheme(dark=False, primary="#78468C", secondary="#21796F", page="#F7F4F9",
                              surface="#FFFFFF", panel="#FDFBFE", header="#EEE7F2", text="#33293C", muted="#6B5C73",
                              backgrounds=PanelBackgrounds("#FAF5FD", "#FDFBFE", True)),
    "Sky": InterfaceTheme(dark=False, primary="#245F91", secondary="#A44262", page="#F2F6FA",
                           surface="#FFFFFF", panel="#FAFCFE", header="#E4EDF5", text="#233747", muted="#536A7C",
                           backgrounds=PanelBackgrounds("#F2F8FD", "#FAFCFF", True)),
}
THEME_COLOR_LABELS = {"primary": "Accent", "secondary": "Secondary accent", "page": "Page background",
                      "surface": "Dialogs and menus", "panel": "Panel surround", "header": "Toolbar background",
                      "text": "Interface text", "muted": "Secondary text"}


@dataclass
class PanelDisplaySettings:
    frame_mode: str = "original"
    frame_color: str = "#7A8796"
    frame_width: float = 1.0
    atom_scale: float = 1.0
    element_scales: dict[str, float] = field(default_factory=dict)
    occupancy_colors: str = "sectors"
    cells: tuple[int, int, int] = (1, 1, 1)
    extend_annotations: bool = False
    frame_opacity: float = 0.72
    vector_opacity: float = 0.95
    reciprocal_opacity: float = 0.78
    plane_opacity: float = 0.36
    plane_edge_opacity: float = 0.9
    vector_label_scale: float = 1.0
    vector_label_opacity: float = 0.95
    plane_label_scale: float = 1.0
    plane_label_opacity: float = 0.9
    backgrounds: PanelBackgrounds = field(default_factory=PanelBackgrounds)
    annotations: PanelAnnotations = field(default_factory=PanelAnnotations)
    markers: list[CrystalMarker] = field(default_factory=list)


DISPLAY_SETTING_FIELDS = {
    "frame": ("frame_mode", "frame_color", "frame_width", "frame_opacity"),
    "atoms": ("atom_scale", "element_scales", "occupancy_colors"),
    "cells": ("cells", "extend_annotations"),
    "colors": ("vector_opacity", "reciprocal_opacity", "plane_opacity", "plane_edge_opacity",
               "vector_label_scale", "vector_label_opacity", "plane_label_scale", "plane_label_opacity"),
    "annotations": ("annotations",),
    "backgrounds": ("backgrounds",),
}
DISPLAY_SETTING_SECTIONS = frozenset(DISPLAY_SETTING_FIELDS)


def crystal_display_settings(settings: PanelDisplaySettings) -> PanelDisplaySettings:
    """Exclude 2D overlays from crystal geometry/cache invalidation."""
    return replace(settings, annotations=PanelAnnotations(), backgrounds=PanelBackgrounds())


def contrast_text_color(background: str) -> str:
    channels = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
                for value in color_to_rgb(background)]
    luminance = sum(weight * value for weight, value in zip((.2126, .7152, .0722), channels))
    return "#000000" if luminance > .179 else "#FFFFFF"


def crystal_text_color(settings: PanelDisplaySettings, color: str) -> str:
    return contrast_text_color(settings.backgrounds.crystal) if settings.backgrounds.automatic_text else color


def display_annotations(settings: PanelDisplaySettings, backgrounds: PanelBackgrounds | None = None) -> PanelAnnotations:
    backgrounds = backgrounds or settings.backgrounds
    if not backgrounds.automatic_text:
        return settings.annotations
    annotations = copy.deepcopy(settings.annotations)
    for name in ANNOTATION_STYLE_NAMES:
        getattr(annotations, name).color = contrast_text_color(
            backgrounds.crystal if name == "real_scale" else backgrounds.diffraction)
    return annotations


@dataclass
class DisplaySettingsDraft:
    display: PanelDisplaySettings = field(default_factory=PanelDisplaySettings)
    inherited: set[str] = field(default_factory=set)
    vector_colors: list[str] = field(default_factory=lambda: VECTOR_COLORS.copy())
    plane_colors: list[str] = field(default_factory=lambda: PLANE_COLORS.copy())
    diffraction_color: str | None = None
    element_colors: dict[str, str] = field(default_factory=dict)
    panel_element_colors: dict[str, str] | None = None
    annotation_visibility: dict[str, bool] = field(default_factory=dict)


def inherited_display_settings(local: PanelDisplaySettings, defaults: PanelDisplaySettings,
                               sections: set[str]) -> PanelDisplaySettings:
    values = {name: getattr(defaults, name) for section, names in DISPLAY_SETTING_FIELDS.items()
              if section in sections for name in names}
    return copy.deepcopy(replace(local, **values))


@dataclass
class CrystalModel:
    definition: CrystalDefinition
    expanded_sites: list[AtomicSite]
    lattice: np.ndarray
    reciprocal: np.ndarray
    display_lattice: np.ndarray
    display_origin: np.ndarray
    display_edges: list[tuple[np.ndarray, np.ndarray]]
    display_atoms: list[DisplayAtom]
    atom_radius_scale: float
    scale_nm: float
    limit: float
    display_source: CrystalModel | None = None
    bounds_edges: list[tuple[np.ndarray, np.ndarray]] | None = None
    clip_edges: list[tuple[np.ndarray, np.ndarray]] | None = None
    annotation_min: np.ndarray = field(default_factory=lambda: np.zeros(3))
    annotation_max: np.ndarray = field(default_factory=lambda: np.ones(3))
    display_extent_scale: float = 1.0
    display_atom_scale: float = 1.0
    hidden_atom_indices: frozenset[int] = field(default_factory=frozenset)

    def atom_radius(self, atom: DisplayAtom | None = None) -> float:
        factor = occupancy_radius_factor(atom.occupancy) * atom.radius_multiplier if atom is not None else 1.0
        return REAL_SCENE_ATOM_RADIUS * self.atom_radius_scale * factor

    def visible_display_atoms(self):
        return (atom for index, atom in enumerate(self.display_atoms) if index not in self.hidden_atom_indices)


@dataclass
class ParsedIndex:
    values: tuple[int, ...]
    label: str
    vector: np.ndarray
    is_reciprocal: bool = False


@dataclass
class RotationCommand:
    axis: np.ndarray | None
    axis_label: str
    angle_degrees: float


@dataclass
class PanelState:
    panel_id: int
    crystal_name: str = "FCC"
    zone_text: str = ""
    plane_text: str = ""
    vector_text: str = ""
    rotation_text: str = ""
    diffraction_color: str = DEFAULT_DIFFRACTION_COLORS["FCC"]
    view_vector: np.ndarray = field(default_factory=lambda: np.array([1.0, 0.0, 0.0]))
    roll: float = 0.0
    applied_zone_text: str = "100"
    magnified: bool = False
    crystal_view_percent: float = 50.0
    vector_colors: list[str] | None = None
    plane_colors: list[str] | None = None
    display_settings: PanelDisplaySettings = field(default_factory=PanelDisplaySettings)
    global_display_sections: set[str] = field(default_factory=lambda: set(DISPLAY_SETTING_SECTIONS))
    diffraction_color_custom: bool = False
    element_colors: dict[str, str] | None = None
    annotation_visibility: dict[str, bool] = field(default_factory=dict)
    saved_view_id: str | None = None
    initial_camera: dict[str, Any] | None = None


@dataclass
class ComboPanelState:
    combo_id: int
    source_panel_ids: list[int] = field(default_factory=list)
    selected_panel_id: int | None = None
    bind_motion: bool = False
    magnified: bool = False
    source_view_percent: float = 50.0


def atomic_site_from_dict(data: dict[str, Any]) -> AtomicSite:
    return AtomicSite(
        element=str(data.get("element", "Ni") or "Ni").strip().capitalize(),
        x=float(data.get("x", 0.0)),
        y=float(data.get("y", 0.0)),
        z=float(data.get("z", 0.0)),
        occupancy=float(data.get("occupancy", 1.0)),
        label=str(data.get("label", "") or ""),
        color=str(data.get("color", "") or ""),
    )


def crystal_definition_key(definition: CrystalDefinition) -> str:
    data = definition.to_dict()
    data.pop("structure_id", None)
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def crystal_identity(definition: CrystalDefinition) -> str:
    if definition.name in DEFAULT_NAMES:
        return f"builtin:{definition.name}"
    return definition.structure_id or str(uuid.uuid5(uuid.NAMESPACE_URL, f"CrysDiS:legacy:{definition.name}"))


def crystal_version(definition: CrystalDefinition) -> str:
    data = definition.to_dict()
    for key in ("name", "structure_id"):
        data.pop(key, None)
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


SAVED_VISIBILITY_METHODS = {"indices": "show_indices", "crystal": "show_crystal_annotations",
                            "scale": "show_scale_bars", "zone": "show_zone_axis_on_diffraction"}


def display_settings_from_dict(data: dict) -> PanelDisplaySettings:
    data = copy.deepcopy(data)
    annotations = data.pop("annotations", {})
    for name in ANNOTATION_STYLE_NAMES:
        if name in annotations:
            annotations[name] = AnnotationStyle(**annotations[name])
    settings = PanelDisplaySettings(
        annotations=PanelAnnotations(**annotations), backgrounds=PanelBackgrounds(**data.pop("backgrounds", {})),
        markers=[CrystalMarker(**marker) for marker in data.pop("markers", [])], **data)
    settings.cells = tuple(settings.cells)
    validate_display_settings(settings)
    return settings


def validated_saved_camera(camera: dict | None) -> dict | None:
    if camera is None:
        return None
    result = {}
    for name in ("position", "target", "up"):
        values = np.asarray(camera[name], dtype=float)
        if values.shape != (3,) or not np.isfinite(values).all() or np.max(np.abs(values)) > 1e7:
            raise ValueError("Invalid saved camera coordinates.")
        result[name] = values.tolist()
    view = np.array(result["position"]) - result["target"]
    if np.linalg.norm(view) < 1e-6 or np.linalg.norm(np.cross(view, result["up"])) < 1e-6:
        raise ValueError("Invalid saved camera orientation.")
    zoom = float(camera["zoom"])
    if not math.isfinite(zoom) or not .01 <= zoom <= 100:
        raise ValueError("Saved zoom must be between 0.01 and 100.")
    result["zoom"] = zoom
    return result


def crystal_model_key(model: CrystalModel) -> str:
    return crystal_definition_key(model.definition)


def default_crystals() -> dict[str, CrystalDefinition]:
    fcc_a = 0.3524
    bcc_a = 0.2855
    hcp_a = 0.32094
    return {
        "FCC": CrystalDefinition(
            name="FCC",
            lattice_system="cubic",
            a=fcc_a,
            b=fcc_a,
            c=fcc_a,
            alpha=90.0,
            beta=90.0,
            gamma=90.0,
            space_group="Fm-3m",
            sites=[
                AtomicSite("Ni", 0.0, 0.0, 0.0, 1.0, "4a", "#10B7A5"),
            ],
        ),
        "BCC": CrystalDefinition(
            name="BCC",
            lattice_system="cubic",
            a=bcc_a,
            b=bcc_a,
            c=bcc_a,
            alpha=90.0,
            beta=90.0,
            gamma=90.0,
            space_group="Im-3m",
            sites=[
                AtomicSite("Fe", 0.0, 0.0, 0.0, 1.0, "2a", "#F77F00"),
            ],
        ),
        "HCP": CrystalDefinition(
            name="HCP",
            lattice_system="hexagonal",
            a=hcp_a,
            b=hcp_a,
            c=hcp_a * IDEAL_HCP_CA,
            alpha=90.0,
            beta=90.0,
            gamma=120.0,
            space_group="P1",
            sites=[
                AtomicSite("Mg", 0.0, 0.0, 0.0, 1.0, "A", "#B985FF"),
                AtomicSite("Mg", 2.0 / 3.0, 1.0 / 3.0, 0.5, 1.0, "B", "#B985FF"),
            ],
        ),
    }


DEFAULT_CRYSTALS = default_crystals()
DEFAULT_NAMES = set(DEFAULT_CRYSTALS)


@lru_cache(maxsize=1)
def space_group_options() -> tuple[str, ...]:
    try:
        from pymatgen.symmetry.groups import SpaceGroup

        return tuple(f"{number}: {SpaceGroup.from_int_number(number).symbol}" for number in range(1, 231))
    except Exception:
        return (
            "1: P1",
            "2: P-1",
            "12: C2/m",
            "14: P2_1/c",
            "62: Pnma",
            "139: I4/mmm",
            "194: P6_3/mmc",
            "221: Pm-3m",
            "225: Fm-3m",
            "229: Im-3m",
        )


@lru_cache(maxsize=512)
def space_group_symbol(value: str | None) -> str:
    text = str(value or "P1").strip()
    text = re.sub(r"^\d+\s*:\s*", "", text)
    text = text.strip("'\"")
    if text in {"", ".", "?"}:
        return "P1"
    compact = re.sub(r"\s+", "", text).replace("{", "").replace("}", "") or "P1"
    aliases = {
        "P63/mmc": "P6_3/mmc",
        "P63/m": "P6_3/m",
        "P63mc": "P6_3mc",
        "P63cm": "P6_3cm",
        "C12/m1": "C2/m",
        "C1m1": "Cm",
    }
    compact = aliases.get(compact, compact)
    try:
        from pymatgen.symmetry.groups import SpaceGroup

        space_group = SpaceGroup.from_int_number(int(compact)) if compact.isdigit() else SpaceGroup(compact)
        symbol = str(space_group.symbol)
        if ":" in compact and ":" not in symbol:
            symbol += ":" + compact.rsplit(":", 1)[1]
        return symbol
    except Exception:
        return compact


def space_group_symbol_from_number(number: int) -> str:
    try:
        from pymatgen.symmetry.groups import SpaceGroup

        return SpaceGroup.from_int_number(int(number)).symbol
    except Exception:
        return str(number)


def cif_block_value(block: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = block.get(key)
        if value is not None:
            return value
    lower_values = {str(key).lower(): value for key, value in block.items()}
    for key in keys:
        value = lower_values.get(key.lower())
        if value is not None:
            return value
    return None


def declared_space_group_from_cif_block(block: dict[str, Any]) -> str:
    setting = cif_block_value(block, "_space_group_IT_coordinate_system_code", "_space_group.IT_coordinate_system_code")
    setting_suffix = f":{setting}" if setting and str(setting).strip() not in {".", "?"} else ""
    symbol = cif_block_value(
        block, "_symmetry_space_group_name_H-M", "_space_group_name_H-M_alt", "_space_group.name_H-M_alt"
    )
    if symbol and str(symbol).strip() not in {".", "?"}:
        symbol = space_group_symbol(symbol)
        if setting_suffix and ":" not in symbol:
            symbol = space_group_symbol(symbol + setting_suffix)
        try:
            from pymatgen.symmetry.groups import SpaceGroup

            SpaceGroup(symbol)
            return symbol
        except ValueError:
            pass
    number = cif_block_value(
        block,
        "_symmetry_Int_Tables_number",
        "_space_group_IT_number",
        "_space_group.it_number",
    )
    number_match = re.match(r"\s*([1-9]\d*)", str(number if number is not None else "").strip("'\""))
    if number_match:
        return space_group_symbol(space_group_symbol_from_number(int(number_match.group(1))) + setting_suffix)
    return space_group_symbol(symbol)


def space_group_option_for(value: str | None) -> str:
    symbol = space_group_symbol(value)
    for option in space_group_options():
        if space_group_symbol(option) == symbol:
            return option
    return symbol


def snap_fractional_value(value: float) -> float:
    wrapped = float(value) % 1.0
    if math.isclose(wrapped, 1.0, abs_tol=SYMMETRY_SITE_TOL) or math.isclose(wrapped, 0.0, abs_tol=SYMMETRY_SITE_TOL):
        return 0.0
    for denominator in (2, 3, 4, 6, 8, 12):
        for numerator in range(1, denominator):
            candidate = numerator / denominator
            if abs(wrapped - candidate) <= SYMMETRY_SITE_TOL:
                return candidate
    return wrapped


def snap_fractional(frac: np.ndarray) -> np.ndarray:
    return np.array([snap_fractional_value(float(value)) for value in frac], dtype=float)


def wrap_fractional(frac: np.ndarray, tolerance: float = 1e-8) -> np.ndarray:
    wrapped = np.mod(np.asarray(frac, dtype=float), 1.0)
    wrapped[np.isclose(wrapped, 1.0, atol=tolerance, rtol=0) | np.isclose(wrapped, 0.0, atol=tolerance, rtol=0)] = 0.0
    return wrapped


@lru_cache(maxsize=256)
def parsed_symmetry_operations(operation_texts: tuple[str, ...]) -> tuple[Any, ...]:
    from pymatgen.core.operations import SymmOp

    operations = []
    for text in operation_texts:
        operation = SymmOp.from_xyz_str(text)
        if len(text.split(",")) != 3 or not np.isclose(abs(np.linalg.det(operation.rotation_matrix)), 1.0):
            raise ValueError(f"Invalid CIF symmetry operation: {text}")
        operations.append(operation)
    return tuple(operations)


def expanded_sites(definition: CrystalDefinition) -> list[AtomicSite]:
    symbol = space_group_symbol(definition.space_group)
    if definition.symmetry_operations:
        operations = parsed_symmetry_operations(tuple(definition.symmetry_operations))
    elif symbol in {"", "P1", "1"}:
        return [AtomicSite(**asdict(site)) for site in definition.sites]
    else:
        try:
            from pymatgen.symmetry.groups import SpaceGroup

            space_group = SpaceGroup.from_int_number(int(symbol)) if symbol.isdigit() else SpaceGroup(symbol)
            operations = space_group.symmetry_ops
        except Exception:
            return [AtomicSite(**asdict(site)) for site in definition.sites]

    expanded: list[AtomicSite] = []
    seen: set[tuple[str, int, int, int]] = set()
    # Imported coordinates and operations share a setting; do not snap them to ideal sites.
    normalize_fractional = wrap_fractional if definition.symmetry_operations else snap_fractional
    site_tolerance = 1e-6 if definition.symmetry_operations else SYMMETRY_SITE_TOL
    for site in definition.sites:
        base_frac = normalize_fractional(site.fractional)
        for operation in operations:
            frac = normalize_fractional(operation.operate(base_frac))
            key = (
                site.element.strip().capitalize(),
                int(round(float(frac[0]) / site_tolerance)),
                int(round(float(frac[1]) / site_tolerance)),
                int(round(float(frac[2]) / site_tolerance)),
            )
            if key in seen:
                continue
            seen.add(key)
            expanded.append(
                AtomicSite(
                    element=site.element,
                    x=float(frac[0]),
                    y=float(frac[1]),
                    z=float(frac[2]),
                    occupancy=site.occupancy,
                    label=site.label,
                    color=site.color,
                )
            )
    return expanded


def normalize_text(text: str) -> str:
    replacements = {
        "\u2212": "-",
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u3008": "<",
        "\u3009": ">",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.strip()


def compact_label(values: tuple[int, ...], bracket: str) -> str:
    left, right = ("[", "]") if bracket == "direction" else ("(", ")")
    separator = " " if any(abs(value) >= 10 for value in values) else ""
    return left + separator.join(str(value) for value in values) + right


def zone_axis_direction_label(values: tuple[int, ...]) -> str:
    if any(abs(value) >= 10 for value in values):
        return "[" + " ".join(str(value) for value in values) + "]"
    return compact_label(values, "direction")


def split_index_groups(text: str, allow_multiple: bool = False) -> list[str]:
    text = normalize_text(text)
    if not text:
        return []
    text = re.sub(r"\s*,\s*", ",", text)
    _reciprocal, coordinates = reciprocal_prefix_group(text)
    parts = coordinates.split()
    if len(parts) in (3, 4) and all(re.fullmatch(r"[+-]?[0-9]+", part) for part in parts):
        # Retain standalone spaced coordinates, but never reinterpret complete
        # compact entries plus an unfinished entry (e.g. "100 114 1") as one vector.
        if not allow_multiple or all(len(parse_compact_indices(part)) not in (3, 4) for part in parts):
            return [text]

    # Keep wrappers and reciprocal prefixes attached, and consume bare entries
    # as well. The final alternative preserves malformed brackets for validation.
    token_pattern = (
        r"(?:[*rR]\s*)?(?:\[[^\[\]]*\]|\([^()]*\)|\{[^{}]*\}|<[^<>]*>|[^\s;|/\[\](){}<>]+)"
        r"|[^\s;|/]"
    )
    return [match.group(0).strip() for match in re.finditer(token_pattern, text)]


def parse_compact_indices(text: str) -> list[int]:
    text = normalize_text(text)
    if not re.fullmatch(r"(?:[+-]?[0-9])+", text):
        return []
    return [int(value) for value in re.findall(r"[+-]?[0-9]", text)]


def parse_index_values(text: str) -> tuple[int, ...]:
    text = normalize_text(text)
    pairs = {"[": "]", "(": ")", "{": "}", "<": ">"}
    if text[:1] in pairs:
        if not text.endswith(pairs[text[0]]):
            return ()
        text = text[1:-1].strip()
    if re.search(r"[\s,;|/]", text):
        if not re.fullmatch(r"[+-]?[0-9]+(?:(?:\s*[,;|/]\s*|\s+)[+-]?[0-9]+)+", text):
            return ()
        return tuple(int(value) for value in re.split(r"[\s,;|/]+", text))
    return tuple(parse_compact_indices(text))


def reciprocal_lattice(lattice: np.ndarray) -> np.ndarray:
    return np.linalg.inv(lattice).T


def normalize_vector(vector: np.ndarray) -> np.ndarray | None:
    length = float(np.linalg.norm(vector))
    if length < 1e-12:
        return None
    return vector / length


def lattice_matrix(definition: CrystalDefinition) -> np.ndarray:
    a = max(float(definition.a), 1e-8)
    b = max(float(definition.b), 1e-8)
    c = max(float(definition.c), 1e-8)
    alpha = math.radians(float(definition.alpha))
    beta = math.radians(float(definition.beta))
    gamma = math.radians(float(definition.gamma))
    sin_gamma = math.sin(gamma)
    if abs(sin_gamma) < 1e-8:
        raise ValueError("gamma angle is too close to 0 or 180 degrees")

    a_vec = np.array([a, 0.0, 0.0], dtype=float)
    b_vec = np.array([b * math.cos(gamma), b * sin_gamma, 0.0], dtype=float)
    c_x = c * math.cos(beta)
    c_y = c * (math.cos(alpha) - math.cos(beta) * math.cos(gamma)) / sin_gamma
    c_z2 = c * c - c_x * c_x - c_y * c_y
    if c_z2 < -1e-8:
        raise ValueError("lattice angles produce an invalid unit cell")
    c_vec = np.array([c_x, c_y, math.sqrt(max(c_z2, 1e-12))], dtype=float)
    return np.array([a_vec, b_vec, c_vec], dtype=float)


def fractional_to_display(frac: np.ndarray, lattice: np.ndarray, center: np.ndarray, scale_nm: float) -> np.ndarray:
    return (frac @ lattice - center) / scale_nm


def occupancy_radius_factor(occupancy: float) -> float:
    return 0.45 + 0.55 * max(float(occupancy), 0.12) ** (1.0 / 3.0)


def atom_radius_scale_for_display(atoms: list[DisplayAtom]) -> float:
    if len(atoms) < 2:
        return 1.0
    positions = np.array([atom.position for atom in atoms], dtype=float)
    nearest_spacing = math.inf
    for index, position in enumerate(positions[:-1]):
        distances = np.linalg.norm(positions[index + 1 :] - position, axis=1)
        distances = distances[distances > 1e-6]
        if len(distances):
            nearest_spacing = min(nearest_spacing, float(np.min(distances)))
    if not math.isfinite(nearest_spacing):
        return 1.0
    spacing_scale = nearest_spacing * REAL_SCENE_ATOM_SPACING_FRACTION / REAL_SCENE_ATOM_RADIUS
    return min(1.0, max(REAL_SCENE_ATOM_MIN_RADIUS_SCALE, spacing_scale))


def occupancy_site_key(fractional: np.ndarray, tolerance: float = 1e-6) -> tuple[int, int, int]:
    return tuple(int(round(float(value) / tolerance)) for value in wrap_fractional(fractional, tolerance=tolerance))


def grouped_occupancy_sites(sites: list[AtomicSite], tolerance: float = 1e-6) -> dict:
    grouped: dict[tuple[int, int, int], list[AtomicSite]] = {}
    for site in sites:
        grouped.setdefault(occupancy_site_key(site.fractional, tolerance), []).append(site)
    return grouped


def occupancy_components(sites: list[AtomicSite], element_colors: dict[str, str] | None = None) -> dict:
    return {
        key: tuple((site.element, max(float(site.occupancy), 0.0), color_for_site(site, element_colors))
                   for site in group if site.occupancy > 0)
        for key, group in grouped_occupancy_sites(sites).items()
    }


def mixed_occupancy_display_sites(sites: list[AtomicSite], tolerance: float = 1e-6,
                                  element_colors: dict[str, str] | None = None) -> list[AtomicSite]:
    mixed_sites: list[AtomicSite] = []
    for group in grouped_occupancy_sites(sites, tolerance).values():
        representative = group[0]
        total_occupancy = sum(max(float(site.occupancy), 0.0) for site in group)
        if total_occupancy > 1e-12:
            rgb = np.zeros(3, dtype=float)
            labels = []
            elements = []
            for site in group:
                weight = max(float(site.occupancy), 0.0)
                if weight <= 0.0:
                    continue
                rgb += weight * np.array(color_to_rgb(color_for_site(site, element_colors)), dtype=float)
                elements.append(site.element.strip().capitalize())
                if site.label:
                    labels.append(site.label)
            rgb = np.clip(np.round(255.0 * rgb / total_occupancy), 0, 255).astype(int)
            mixed_color = f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
            element = "+".join(dict.fromkeys(elements)) or representative.element
            label = "/".join(dict.fromkeys(labels))
        else:
            mixed_color = color_for_site(representative, element_colors)
            element = representative.element
            label = representative.label
        mixed_sites.append(
            AtomicSite(
                element=element,
                x=representative.x,
                y=representative.y,
                z=representative.z,
                occupancy=min(max(total_occupancy, 0.0), 1.0),
                label=label,
                color=mixed_color,
            )
        )
    return mixed_sites


def make_model(definition: CrystalDefinition) -> CrystalModel:
    lattice = lattice_matrix(definition)
    reciprocal = reciprocal_lattice(lattice)
    model_sites = expanded_sites(definition)
    display_sites = mixed_occupancy_display_sites(model_sites)
    components = occupancy_components(model_sites)
    corners_frac = np.array(list(product([0.0, 1.0], repeat=3)), dtype=float)
    corners_cart = corners_frac @ lattice
    center = np.array([0.5, 0.5, 0.5], dtype=float) @ lattice
    edge_norm = float(np.max(np.linalg.norm(lattice, axis=1)))
    bbox_span = float(np.max(np.ptp(corners_cart, axis=0)))
    scale_nm = max(edge_norm, bbox_span, 1e-8)
    display_lattice = lattice / scale_nm
    display_origin = fractional_to_display(np.zeros(3), lattice, center, scale_nm)

    display_edges: list[tuple[np.ndarray, np.ndarray]] = []
    for i, start_frac in enumerate(corners_frac):
        for end_frac in corners_frac[i + 1 :]:
            if np.count_nonzero(np.abs(start_frac - end_frac) > 1e-9) == 1:
                display_edges.append(
                    (
                        fractional_to_display(start_frac, lattice, center, scale_nm),
                        fractional_to_display(end_frac, lattice, center, scale_nm),
                    )
                )

    display_atoms: list[DisplayAtom] = []
    for site in display_sites:
        base = np.mod(site.fractional.astype(float), 1.0)
        base[np.isclose(base, 1.0, atol=1e-9)] = 0.0
        if definition.repeat_boundary_atoms:
            translation_choices = [[0.0, 1.0] if abs(coord) < 1e-8 else [0.0] for coord in base]
        else:
            translation_choices = [[0.0] for _coord in base]
        for translation in product(*translation_choices):
            frac = base + np.array(translation, dtype=float)
            if np.all(frac <= 1.0 + 1e-8):
                display_atoms.append(
                    DisplayAtom(
                        element=site.element,
                        position=fractional_to_display(frac, lattice, center, scale_nm),
                        occupancy=min(max(float(site.occupancy), 0.0), 1.0),
                        label=site.label,
                        color=site.color,
                        components=components.get(occupancy_site_key(site.fractional), ()),
                    )
                )

    all_points = [point for edge in display_edges for point in edge]
    all_points.extend(atom.position for atom in display_atoms)
    limit = max(1.25, float(np.max(np.abs(np.array(all_points)))) * 1.35 if all_points else 1.25)
    atom_radius_scale = atom_radius_scale_for_display(display_atoms)
    return CrystalModel(
        definition=definition,
        expanded_sites=model_sites,
        lattice=lattice,
        reciprocal=reciprocal,
        display_lattice=display_lattice,
        display_origin=display_origin,
        display_edges=display_edges,
        display_atoms=display_atoms,
        atom_radius_scale=atom_radius_scale,
        scale_nm=scale_nm,
        limit=limit,
    )


def validate_display_settings(settings: PanelDisplaySettings) -> None:
    validate_markers(settings.markers)
    for value in (settings.backgrounds.crystal, settings.backgrounds.diffraction):
        if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError("Panel backgrounds must be six-digit hex colors.")
    annotations = settings.annotations
    for name in ANNOTATION_STYLE_NAMES:
        style = getattr(annotations, name)
        positions = SPOT_LABEL_DIRECTIONS if name == "indices" else ANNOTATION_CORNERS
        if style.position not in positions:
            raise ValueError(f"Invalid {name.replace('_', ' ')} annotation position.")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", style.color):
            raise ValueError("Annotation colors must be six-digit hex colors.")
        if not math.isfinite(style.font_size) or not 6 <= style.font_size <= 40:
            raise ValueError("Annotation font sizes must be between 6 and 40 px.")
        if not math.isfinite(style.opacity) or not 0 <= style.opacity <= 1:
            raise ValueError("Annotation opacity must be between 0 and 100%.")
    if not math.isfinite(annotations.index_offset) or not -20 <= annotations.index_offset <= 40:
        raise ValueError("Spot label gap must be between -20 and 40 px.")
    if settings.frame_mode not in {"original", "all", "hidden"}:
        raise ValueError("Choose original-cell, every-cell, or hidden frames.")
    if settings.occupancy_colors not in OCCUPANCY_COLOR_OPTIONS:
        raise ValueError("Choose blended colors or occupancy sectors.")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", settings.frame_color):
        raise ValueError("Frame color must be a six-digit hex color.")
    for value, name, low, high in (
        (settings.frame_width, "Frame thickness", 0.25, MAX_FRAME_THICKNESS),
        (settings.atom_scale, "Atom size", 0.1, 3.0),
        (settings.vector_label_scale, "Vector text size", 0.25, 3.0),
        (settings.plane_label_scale, "Plane text size", 0.25, 3.0),
        *((getattr(settings, name), name.replace("_", " ").capitalize(), 0.0, 1.0) for name in (
            "frame_opacity", "vector_opacity", "reciprocal_opacity", "plane_opacity", "plane_edge_opacity",
            "vector_label_opacity", "plane_label_opacity")),
        *((value, f"{element} atom size", 0.1, 3.0) for element, value in settings.element_scales.items()),
    ):
        if not math.isfinite(float(value)) or not low <= float(value) <= high:
            raise ValueError(f"{name} must be between {low:g} and {high:g}.")
    if len(settings.cells) != 3 or any(not math.isfinite(float(n)) or int(n) != n or not 1 <= abs(n) <= 8 for n in settings.cells):
        raise ValueError("Cell counts must be nonzero integers from -8 to 8.")
    if math.prod(abs(n) for n in settings.cells) > 216:
        raise ValueError("Display at most 216 unit cells at a time.")


def display_cell_bounds(cells: tuple[int, int, int]) -> tuple[np.ndarray, np.ndarray]:
    counts = np.array(cells, dtype=int)
    return np.minimum(counts + 1, 0).astype(float), np.maximum(counts, 1).astype(float)


def fractional_box_edges(low: np.ndarray, high: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    corners = np.array(list(product(*zip(low, high))), dtype=float)
    return [(start, end) for index, start in enumerate(corners) for end in corners[index + 1:]
            if np.count_nonzero(np.abs(start - end) > 1e-9) == 1]


def make_panel_display_model(source: CrystalModel, settings: PanelDisplaySettings,
                             element_colors: dict[str, str] | None = None) -> CrystalModel:
    """Replicate drawing geometry only; keep the crystallographic unit cell intact."""
    validate_display_settings(settings)
    source = source.display_source or source
    element_colors = display_element_colors(source, settings, element_colors or {})
    if settings == PanelDisplaySettings() and not element_colors:
        return source
    low, high = display_cell_bounds(settings.cells)
    translations = list(product(*(range(int(a), int(b)) for a, b in zip(low, high))))
    if len(translations) > 1 and len(source.display_atoms) * len(translations) > 30000:
        raise ValueError("This display would exceed 30,000 atoms. Reduce the cell counts.")
    origin = -0.5 * (low + high) @ source.display_lattice

    def to_display(edges):
        return [(origin + start @ source.display_lattice, origin + end @ source.display_lattice) for start, end in edges]

    original = fractional_box_edges(np.zeros(3), np.ones(3))
    outer = to_display(fractional_box_edges(low, high))
    edges = []
    if settings.frame_mode == "original":
        edges = to_display(original)
    elif settings.frame_mode == "all":
        seen_edges = set()
        for translation in translations:
            for start, end in original:
                start, end = start + translation, end + translation
                key = tuple(sorted((tuple(start), tuple(end))))
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append((origin + start @ source.display_lattice, origin + end @ source.display_lattice))

    # A mixed-occupancy sphere retains one geometry and uses an occupancy-weighted size.
    size_weights: dict[tuple, list[float]] = {}
    for site in source.expanded_sites:
        key = tuple(np.round(wrap_fractional(site.fractional), 6))
        weight = max(float(site.occupancy), 0.0)
        values = size_weights.setdefault(key, [0.0, 0.0])
        values[0] += weight * settings.element_scales.get(site.element, 1.0)
        values[1] += weight
    atoms = []
    seen_atoms = set()
    colors_by_site = {
        tuple(np.round(wrap_fractional(site.fractional), 6)): site.color
        for site in mixed_occupancy_display_sites(source.expanded_sites, element_colors=element_colors)
    } if element_colors else {}
    components_by_site = occupancy_components(source.expanded_sites, element_colors) if element_colors else {}
    inverse = np.linalg.inv(source.display_lattice)
    for atom in source.display_atoms:
        fractional = (atom.position - source.display_origin) @ inverse
        weight, total = size_weights.get(tuple(np.round(wrap_fractional(fractional), 6)), (1.0, 1.0))
        multiplier = settings.atom_scale * (weight / total if total > 1e-12 else 1.0)
        color = colors_by_site.get(tuple(np.round(wrap_fractional(fractional), 6)), atom.color)
        components = components_by_site.get(occupancy_site_key(fractional), atom.components)
        for translation in translations:
            position = fractional + translation
            key = (tuple(np.round(position, 7)), atom.element, atom.color, atom.occupancy)
            if key in seen_atoms:
                continue
            seen_atoms.add(key)
            atoms.append(replace(atom, position=origin + position @ source.display_lattice,
                                 radius_multiplier=multiplier, color=color, components=components))
    points = np.array([point for edge in outer for point in edge])
    limit = max(1.25, float(np.max(np.abs(points))) * 1.35)
    base_extent = max(np.linalg.norm(point) for edge in source.display_edges for point in edge)
    extent_scale = max(1.0, float(np.max(np.linalg.norm(points, axis=1))) / max(base_extent, 1e-9))
    result = replace(source, display_source=source, display_origin=origin, display_edges=edges, display_atoms=atoms,
                   bounds_edges=outer, clip_edges=outer if settings.extend_annotations else to_display(original),
                   annotation_min=low if settings.extend_annotations else np.zeros(3),
                   annotation_max=high if settings.extend_annotations else np.ones(3),
                   limit=limit, display_extent_scale=extent_scale, display_atom_scale=settings.atom_scale)
    result.hidden_atom_indices = marker_hidden_atom_indices(settings.markers, result)
    marker_points = marker_extent_points(marker_geometry(settings.markers, result))
    if marker_points:
        result.bounds_edges = [*outer, *((point, point) for point in marker_points)]
        result.limit = max(result.limit, max(np.linalg.norm(point) for point in marker_points) * 1.15)
    return result


def is_hexagonal(definition: CrystalDefinition) -> bool:
    return definition.lattice_system.lower() == "hexagonal" or definition.name.upper() == "HCP"


def hcp_direction_to_cart(values: tuple[int, ...], lattice: np.ndarray) -> np.ndarray:
    a1, a2, c_axis = lattice
    if len(values) == 4:
        u, v, t, w = values
        return (u - t) * a1 + (v - t) * a2 + w * c_axis
    u, v, w = values
    return u * a1 + v * a2 + w * c_axis


def direction_to_cart(values: tuple[int, ...], model: CrystalModel) -> np.ndarray:
    if is_hexagonal(model.definition):
        return hcp_direction_to_cart(values, model.lattice)
    return np.array(values[:3], dtype=float) @ model.lattice


def direction_components(values: tuple[int, ...], model: CrystalModel) -> np.ndarray:
    if is_hexagonal(model.definition) and len(values) == 4:
        u, v, t, w = values
        return np.array([u - t, v - t, w], dtype=float)
    return np.array(values[:3], dtype=float)


def direction_delta_for_display(values: tuple[int, ...], model: CrystalModel) -> np.ndarray:
    components = direction_components(values, model)
    scale = max(float(np.max(np.abs(components))), 1.0)
    return (components / scale) @ model.display_lattice


def direction_segment_for_display(values: tuple[int, ...], model: CrystalModel) -> tuple[np.ndarray, np.ndarray]:
    components = direction_components(values, model)
    nonzero = np.abs(components) > 1e-12
    spans = model.annotation_max - model.annotation_min
    scale = float(np.min(spans[nonzero] / np.abs(components[nonzero]))) if np.any(nonzero) else 0.0
    delta_fractional = components * scale
    start_fractional = model.annotation_min + np.where(delta_fractional < 0.0, -delta_fractional, 0.0)
    end_fractional = start_fractional + delta_fractional
    start = model.display_origin + start_fractional @ model.display_lattice
    end = model.display_origin + end_fractional @ model.display_lattice
    return start, end


def reduce_integer_tuple(
    values: tuple[int, ...] | list[int] | np.ndarray, *, preserve_sign: bool = False,
) -> tuple[int, ...]:
    ints = [int(round(float(value))) for value in values]
    if all(value == 0 for value in ints):
        return tuple(ints)
    divisor = 0
    for value in ints:
        divisor = math.gcd(divisor, abs(value))
    if divisor > 1:
        ints = [value // divisor for value in ints]
    first_nonzero = next((value for value in ints if value != 0), 1)
    if first_nonzero < 0 and not preserve_sign:
        ints = [-value for value in ints]
    return tuple(int(value) for value in ints)


def reduce_integer_vector(values: np.ndarray) -> tuple[int, int, int]:
    reduced = reduce_integer_tuple(values[:3])
    if all(value == 0 for value in reduced):
        return (1, 0, 0)
    return tuple(int(value) for value in reduced[:3])


def zone_axis_candidate_table(model: CrystalModel, max_index: int) -> tuple[np.ndarray, np.ndarray]:
    limit = max(1, int(max_index))
    lattice_key = tuple(float(value) for value in np.round(np.asarray(model.lattice, dtype=float).ravel(), 10))
    key = (lattice_key, limit)
    cached = _ZONE_AXIS_CANDIDATE_CACHE.get(key)
    if cached is not None:
        return cached

    axes: list[tuple[int, int, int]] = []
    vectors: list[np.ndarray] = []
    for u, v, w in product(range(-limit, limit + 1), repeat=3):
        if u == v == w == 0:
            continue
        candidate_axis = reduce_integer_vector(np.array([u, v, w], dtype=float))
        if candidate_axis != (u, v, w):
            continue
        candidate = normalize_vector(direction_to_cart(candidate_axis, model))
        if candidate is None:
            continue
        axes.append(candidate_axis)
        vectors.append(candidate)

    if not axes:
        axes = [(1, 0, 0)]
        vectors = [np.array([1.0, 0.0, 0.0], dtype=float)]
    table = (np.array(axes, dtype=int), np.array(vectors, dtype=float))
    _ZONE_AXIS_CANDIDATE_CACHE[key] = table
    return table


def hcp_three_index_direction_to_four(axis: tuple[int, int, int]) -> tuple[int, int, int, int]:
    u, v, w = axis
    return reduce_integer_tuple((2 * u - v, 2 * v - u, -u - v, 3 * w), preserve_sign=True)


def integer_zone_axis_from_view(
    model: CrystalModel,
    view_vector: np.ndarray,
    max_index: int = DEFAULT_ZONE_AXIS_SEARCH_MAX,
) -> tuple[int, int, int]:
    view = normalize_vector(view_vector)
    if view is None:
        return (1, 0, 0)

    axes, candidates = zone_axis_candidate_table(model, max_index)
    scores = np.abs(candidates @ view)
    best = int(np.argmax(scores))
    return tuple(int(value) for value in axes[best])


def zone_axis_label_from_view(
    model: CrystalModel,
    view_vector: np.ndarray,
    max_index: int = DEFAULT_ZONE_AXIS_SEARCH_MAX,
    use_hex_four_index: bool = False,
) -> str:
    axis = integer_zone_axis_from_view(model, view_vector, max_index=max_index)
    view = normalize_vector(view_vector)
    axis_vector = normalize_vector(np.array(axis, dtype=float) @ model.lattice)
    approximate = True
    if view is not None and axis_vector is not None:
        # The candidate cache identifies an axis up to sign; the label identifies a viewing direction.
        alignment = float(np.dot(view, axis_vector))
        if alignment < 0.0:
            axis = tuple(-value for value in axis)
        angle = math.degrees(math.acos(min(max(abs(alignment), -1.0), 1.0)))
        approximate = angle > ZONE_AXIS_EXACT_TOL_DEGREES
    prefix = "~" if approximate else ""
    label_axis: tuple[int, ...] = (
        hcp_three_index_direction_to_four(axis) if use_hex_four_index and is_hexagonal(model.definition) else axis
    )
    return f"{prefix}{zone_axis_direction_label(label_axis)} zone"


def pymatgen_structure_from_model(model: CrystalModel) -> Any:
    from pymatgen.core import Lattice, Structure

    species = []
    coords = []
    for site in model.expanded_sites:
        occupancy = min(max(float(site.occupancy), 0.0), 1.0)
        if occupancy <= 0.0:
            continue
        element = site.element.strip().capitalize()
        species.append(element if math.isclose(occupancy, 1.0) else {element: occupancy})
        coords.append(wrap_fractional(site.fractional))
    if not species:
        raise ValueError("No occupied atom sites are available for pymatgen TEM calculation.")
    return Structure(Lattice(model.lattice * 10.0), species, coords, coords_are_cartesian=False, to_unit_cell=True)


def cif_quote(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        return "''"
    return "'" + text.replace("'", "''") + "'"


def cif_number(value: float) -> str:
    return f"{float(value):.8f}"


def unit_cell_composition(definition: CrystalDefinition, *, expanded: list[AtomicSite] | None = None) -> dict[str, Fraction]:
    totals: dict[str, Fraction] = {}
    for site in expanded_sites(definition) if expanded is None else expanded:
        occupancy = min(max(float(site.occupancy), 0.0), 1.0)
        if occupancy <= 0.0:
            continue
        element = site.element.strip().capitalize()
        # Decimal occupancies stay exact when summed and reduced to integer ratios.
        totals[element] = totals.get(element, Fraction(0)) + Fraction(str(occupancy))
    return totals


FORMULA_MODES = {"cell": "Unit cell", "reduced": "Reduced", "fraction": "Atomic fraction", "sites": "Site occupancies"}


def rounded_formula_units(amounts: list[Fraction]) -> list[int]:
    scaled = [amount * 1000 for amount in amounts]
    units = [amount.numerator // amount.denominator for amount in scaled]
    # Balance rounding to the original total, without normalizing partially vacant sites.
    order = sorted(range(len(units)), key=lambda index: scaled[index] - units[index], reverse=True)
    for index in order[:round(sum(scaled)) - sum(units)]:
        units[index] += 1
    return units


@dataclass(frozen=True)
class SiteOccupancyGroup:
    components: tuple[tuple[str, Fraction], ...]
    multiplicity: int


def site_occupancy_groups(sites: list[AtomicSite]) -> list[SiteOccupancyGroup]:
    positions: dict[tuple[int, ...], dict[str, Fraction]] = {}
    tolerance = 1e-6
    for site in sites:
        frac = wrap_fractional(site.fractional, tolerance=tolerance)
        key = tuple(int(round(float(value) / tolerance)) for value in frac)
        components = positions.setdefault(key, {})
        element = site.element.strip().capitalize()
        occupancy = Fraction(str(float(site.occupancy)))
        components[element] = components.get(element, Fraction(0)) + occupancy

    counts: dict[tuple[tuple[str, Fraction], ...], int] = {}
    for components in positions.values():
        occupied = {element: amount for element, amount in components.items() if amount != 0}
        pattern = tuple(sorted((occupied or components).items()))
        counts[pattern] = counts.get(pattern, 0) + 1
    groups = [SiteOccupancyGroup(pattern, count) for pattern, count in counts.items()]
    # Mixed/partial groups precede fully occupied elements; keep distinct patterns separate.
    return sorted(groups, key=lambda group: len(group.components) == 1 and group.components[0][1] == 1)


def unbalanced_site_occupancies(definition: CrystalDefinition) -> list[SiteOccupancyGroup]:
    groups = site_occupancy_groups(expanded_sites(definition))
    # Ignore decimal rounding noise without hiding an underfilled or overfilled site.
    tolerance = Fraction(1, 1_000_000)
    return [group for group in groups if abs(sum(amount for _, amount in group.components) - 1) > tolerance]


def site_occupancy_formula(groups: list[SiteOccupancyGroup]) -> str:
    if not groups:
        return ""
    divisor = math.gcd(*(group.multiplicity for group in groups))
    parts = []
    for group in groups:
        if len(group.components) == 1 and group.components[0][1] == 1:
            content = escape(group.components[0][0])
        else:
            units = rounded_formula_units([amount for _, amount in group.components])
            content = "(" + "<wbr>".join(
                escape(element) + "<sub>" + f"{amount / 1000:.3f}".rstrip("0").rstrip(".") + "</sub>"
                for (element, _), amount in zip(group.components, units)
            ) + ")"
        multiplier = group.multiplicity // divisor
        parts.append(content + (f"<sub>{multiplier}</sub>" if multiplier != 1 else ""))
    return "<wbr>".join(parts)


def formula_terms(totals: dict[str, Fraction], mode: str) -> list[tuple[str, str]]:
    if not totals:
        return []
    elements = list(totals)
    amounts = list(totals.values())
    if mode == "reduced":
        denominator = math.lcm(*(amount.denominator for amount in amounts))
        integers = [int(amount * denominator) for amount in amounts]
        divisor = math.gcd(*integers)
        return [(element, str(amount // divisor) if amount != divisor else "")
                for element, amount in zip(elements, integers)]
    if mode == "fraction":
        total = sum(amounts)
        units = rounded_formula_units([amount / total for amount in amounts])
        return [(element, f"{amount / 1000:.3f}") for element, amount in zip(elements, units)]
    if mode != "cell":
        raise ValueError(f"Unknown formula mode: {mode}")
    return [(element, "" if amount == 1 else str(amount.numerator) if amount.denominator == 1 else f"{float(amount):.12g}")
            for element, amount in zip(elements, amounts)]


def cif_formula_sum(definition: CrystalDefinition) -> str:
    totals = unit_cell_composition(definition)
    parts = []
    for element in sorted(totals):
        amount = float(totals[element])
        if math.isclose(amount, 1.0, abs_tol=1e-8):
            amount_text = ""
        elif math.isclose(amount, round(amount), abs_tol=1e-8):
            amount_text = str(int(round(amount)))
        else:
            amount_text = f"{amount:.6g}"
        parts.append(f"{element}{amount_text}")
    return " ".join(parts) or "?"


def space_group_export_metadata(value: str | None) -> tuple[str, int | None, list[str]]:
    symbol = space_group_symbol(value)
    if symbol in {"", "1"}:
        symbol = "P1"
    try:
        from pymatgen.symmetry.groups import SpaceGroup

        space_group = SpaceGroup.from_int_number(int(symbol)) if symbol.isdigit() else SpaceGroup(symbol)
        operations = sorted({operation.as_xyz_str() for operation in space_group.symmetry_ops})
        if "x, y, z" in operations:
            operations = ["x, y, z", *[operation for operation in operations if operation != "x, y, z"]]
        return symbol, int(space_group.int_number), operations or ["x, y, z"]
    except Exception:
        return symbol or "P1", None, ["x, y, z"]


def cif_site_label(site: AtomicSite, element: str, index: int, used_labels: set[str]) -> str:
    base = str(site.label or "").strip().strip("'\"")
    base = re.sub(r"[^A-Za-z0-9_.+-]+", "_", base).strip("._")
    if not base:
        base = f"{element}{index + 1}"
    if base[0].isdigit():
        base = f"{element}{base}"
    label = base
    counter = 2
    while label in used_labels:
        label = f"{base}_{counter}"
        counter += 1
    used_labels.add(label)
    return label


def symmetry_preserving_cif_text_for_definition(definition: CrystalDefinition) -> str:
    symbol, number, operations = space_group_export_metadata(definition.space_group)
    if definition.symmetry_operations:
        operations = [operation.as_xyz_str() for operation in parsed_symmetry_operations(tuple(definition.symmetry_operations))]
    block_name = sanitize_export_filename_stem(definition.name, "crystal")
    lines = [
        "# generated using CrysDiS",
        f"data_{block_name}",
        f"_symmetry_space_group_name_H-M   {cif_quote(symbol)}",
        f"_space_group_name_H-M_alt   {cif_quote(symbol)}",
        f"_symmetry_Int_Tables_number   {number if number is not None else '?'}",
        f"_space_group_IT_number   {number if number is not None else '?'}",
        f"_cell_length_a   {cif_number(definition.a * 10.0)}",
        f"_cell_length_b   {cif_number(definition.b * 10.0)}",
        f"_cell_length_c   {cif_number(definition.c * 10.0)}",
        f"_cell_angle_alpha   {cif_number(definition.alpha)}",
        f"_cell_angle_beta   {cif_number(definition.beta)}",
        f"_cell_angle_gamma   {cif_number(definition.gamma)}",
        f"_chemical_formula_sum   {cif_quote(cif_formula_sum(definition))}",
        "loop_",
        "_space_group_symop_id",
        "_space_group_symop_operation_xyz",
    ]
    for index, operation in enumerate(operations, start=1):
        lines.append(f"{index} {cif_quote(operation)}")
    lines.extend(
        [
            "loop_",
            "_atom_site_label",
            "_atom_site_type_symbol",
            "_atom_site_fract_x",
            "_atom_site_fract_y",
            "_atom_site_fract_z",
            "_atom_site_occupancy",
        ]
    )
    used_labels: set[str] = set()
    row_count = 0
    for index, site in enumerate(definition.sites):
        occupancy = min(max(float(site.occupancy), 0.0), 1.0)
        if occupancy <= 0.0:
            continue
        element = site.element.strip().capitalize()
        label = cif_site_label(site, element, index, used_labels)
        frac = wrap_fractional(site.fractional)
        lines.append(
            " ".join(
                [
                    cif_quote(label),
                    cif_quote(element),
                    cif_number(float(frac[0])),
                    cif_number(float(frac[1])),
                    cif_number(float(frac[2])),
                    cif_number(occupancy),
                ]
            )
        )
        row_count += 1
    if row_count == 0:
        raise ValueError("No occupied atom sites are available for CIF export.")
    return "\n".join(lines) + "\n"


def cif_text_for_definition(definition: CrystalDefinition, preserve_symmetry: bool = False) -> str:
    if preserve_symmetry:
        return symmetry_preserving_cif_text_for_definition(definition)

    from pymatgen.io.cif import CifWriter

    model = make_model(definition)
    structure = pymatgen_structure_from_model(model)
    writer = CifWriter(structure, symprec=None, significant_figures=8, refine_struct=False)
    return str(writer)


def occupancy_aware_tem_calculator_class(base_calculator_class: type[Any]) -> type[Any]:
    """Return a TEMCalculator subclass that respects partial site occupancies.

    Pymatgen's TEMCalculator already provides the reciprocal-space geometry,
    electron wavelength, electron scattering factors, and spot projection.  This
    subclass keeps that workflow but corrects the structure-factor sum for
    disordered/mixed-occupancy sites:

        F_hkl = sum_sites sum_species occ * f_species * exp(2*pi*i*g.r)

    The average-site Bragg intensity is still calculated kinematically as
    |F_hkl|^2 by the parent class.  Occupational diffuse scattering and
    dynamical TEM effects are intentionally outside this Level-1 correction.
    """

    class OccupancyAwareTEMCalculator(base_calculator_class):  # type: ignore[misc, valid-type]
        def cell_scattering_factors(self, structure: Any, bragg_angles: dict[Any, Any]) -> dict[Any, complex]:
            electron_scattering_factors = self.electron_scattering_factors(structure, bragg_angles)
            cell_scattering_factors: dict[Any, complex] = {}

            for plane in bragg_angles:
                hkl = np.asarray(plane, dtype=float)
                structure_factor_sum = 0.0 + 0.0j

                for site in structure:
                    phase = np.exp(2j * np.pi * float(np.dot(hkl, site.frac_coords)))
                    for specie, occupancy in site.species.items():
                        symbol = getattr(specie, "symbol", str(specie)).strip().capitalize()
                        scattering_by_plane = electron_scattering_factors.get(symbol)
                        if scattering_by_plane is None:
                            continue
                        try:
                            scattering_factor = scattering_by_plane[plane]
                        except KeyError:
                            continue
                        structure_factor_sum += float(occupancy) * scattering_factor * phase

                cell_scattering_factors[plane] = structure_factor_sum

            return cell_scattering_factors

    OccupancyAwareTEMCalculator.__name__ = "OccupancyAwareTEMCalculator"
    return OccupancyAwareTEMCalculator

def reciprocal_delta_for_display(values: tuple[int, ...], model: CrystalModel) -> np.ndarray:
    reciprocal_direction = normalize_vector(reciprocal_index_to_cart(values, model))
    if reciprocal_direction is None:
        return np.zeros(3, dtype=float)
    return reciprocal_direction * 0.72


def shifted_segment_for_display_delta(delta: np.ndarray, model: CrystalModel) -> tuple[np.ndarray, np.ndarray]:
    delta = np.asarray(delta, dtype=float)
    if float(np.linalg.norm(delta)) < 1e-10:
        return model.display_origin.copy(), model.display_origin.copy()
    try:
        delta_fractional = np.linalg.solve(model.display_lattice.T, delta)
    except np.linalg.LinAlgError:
        return model.display_origin.copy(), model.display_origin + delta

    start_fractional = np.zeros(3, dtype=float)
    for axis, component in enumerate(delta_fractional):
        if component < 0.0:
            start_fractional[axis] = min(max(-float(component), 0.0), 1.0)

    end_fractional = start_fractional + delta_fractional
    for axis in range(3):
        if end_fractional[axis] > 1.0:
            shift = min(float(end_fractional[axis] - 1.0), float(start_fractional[axis]))
            start_fractional[axis] -= shift
            end_fractional[axis] -= shift
        elif end_fractional[axis] < 0.0:
            shift = min(float(-end_fractional[axis]), float(1.0 - start_fractional[axis]))
            start_fractional[axis] += shift
            end_fractional[axis] += shift

    start = model.display_origin + start_fractional @ model.display_lattice
    end = start + delta
    return start, end


def reciprocal_segment_for_display(values: tuple[int, ...], model: CrystalModel) -> tuple[np.ndarray, np.ndarray]:
    if model.display_source is not None:
        delta = reciprocal_delta_for_display(values, model)
        fractional = np.linalg.solve(model.display_lattice.T, delta)
        nonzero = np.abs(fractional) > 1e-12
        spans = model.annotation_max - model.annotation_min
        fit = float(np.min(spans[nonzero] / np.abs(fractional[nonzero]))) if np.any(nonzero) else 0.0
        extended = not (np.array_equal(model.annotation_min, np.zeros(3)) and np.array_equal(model.annotation_max, np.ones(3)))
        fractional *= fit if extended else min(1.0, fit)
        start = model.annotation_min + np.where(fractional < 0.0, -fractional, 0.0)
        return model.display_origin + start @ model.display_lattice, model.display_origin + (start + fractional) @ model.display_lattice
    return shifted_segment_for_display_delta(reciprocal_delta_for_display(values, model), model)


def reciprocal_index_components(values: tuple[int, ...], model: CrystalModel) -> tuple[int, int, int]:
    if is_hexagonal(model.definition) and len(values) == 4:
        return reduce_integer_vector(direction_components(values, model))
    return reduce_integer_vector(np.array(values[:3], dtype=float))


def reciprocal_index_to_cart(values: tuple[int, ...], model: CrystalModel) -> np.ndarray:
    return np.array(reciprocal_index_components(values, model), dtype=float) @ model.reciprocal


def plane_coefficients(values: tuple[int, ...], model: CrystalModel) -> np.ndarray:
    if is_hexagonal(model.definition) and len(values) == 4:
        h, k, _i, l = values
    else:
        h, k, l = values[:3]
    return np.array([h, k, l], dtype=float)


def plane_normal_to_cart(values: tuple[int, ...], model: CrystalModel) -> np.ndarray:
    return plane_coefficients(values, model) @ model.reciprocal


def diffraction_intensity_text(intensity: float) -> str:
    if intensity == 0:
        return "0"
    if 0 < intensity < 0.01:
        mantissa, exponent = f"{intensity:.3e}".split("e")
        return f"{mantissa.rstrip('0').rstrip('.')}e{int(exponent)}"
    return f"{intensity:.4f}"


def diffraction_label_for_hkl(
    h: int,
    k: int,
    l: int,
    model: CrystalModel,
    use_hex_four_index: bool,
) -> str:
    if use_hex_four_index and is_hexagonal(model.definition):
        return compact_label((h, k, -h - k, l), "plane")
    return compact_label((h, k, l), "plane")


def plane_spacing_nm_for_hkl(h: int, k: int, l: int, model: CrystalModel) -> float:
    if h == k == l == 0:
        return math.inf
    g_vector = np.array([h, k, l], dtype=float) @ model.reciprocal
    g_norm = float(np.linalg.norm(g_vector))
    if g_norm < 1e-12:
        return math.inf
    return 1.0 / g_norm


def reciprocal_prefix_group(group: str) -> tuple[bool, str]:
    text = normalize_text(group).strip()
    if text.startswith("*"):
        return True, text[1:].strip()
    if re.match(r"^[rR](?=\s*[\[\(\{<+\-]|\s*\d)", text):
        return True, text[1:].strip()
    return False, text


def parse_indices(
    text: str,
    model: CrystalModel,
    kind: str,
    allow_multiple: bool,
    allow_reciprocal: bool = False,
) -> tuple[list[ParsedIndex], list[str]]:
    groups = split_index_groups(text, allow_multiple=allow_multiple)
    if not groups:
        return [], []
    if not allow_multiple and len(groups) != 1:
        return [], ["Enter a single index"]

    valid_lengths = (3, 4) if is_hexagonal(model.definition) else (3,)
    parsed = []
    errors = []
    for group in groups:
        is_reciprocal = False
        parse_group = group
        if allow_reciprocal and kind == "direction":
            is_reciprocal, parse_group = reciprocal_prefix_group(group)
        values = parse_index_values(parse_group)
        if len(values) not in valid_lengths:
            errors.append(f"{group!r} is not a valid index for {model.definition.name}")
            continue
        if kind == "plane":
            vector = plane_normal_to_cart(values, model)
            label = compact_label(values, "plane")
        elif is_reciprocal:
            vector = reciprocal_index_to_cart(values, model)
            label = "*" + compact_label(values, "direction")
        else:
            vector = direction_to_cart(values, model)
            label = compact_label(values, "direction")
        unit = normalize_vector(vector)
        if unit is None:
            errors.append(f"{group!r} has zero length")
            continue
        parsed.append(ParsedIndex(values=values, label=label, vector=unit, is_reciprocal=is_reciprocal))
    return parsed, errors


def projection_basis(view_vector: np.ndarray, roll: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    normal = normalize_vector(view_vector)
    if normal is None:
        normal = np.array([1.0, 0.0, 0.0])
    reference = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(normal, reference))) > 0.94:
        reference = np.array([0.0, 1.0, 0.0])
    u_axis = normalize_vector(np.cross(reference, normal))
    if u_axis is None:
        u_axis = np.array([1.0, 0.0, 0.0])
    v_axis = normalize_vector(np.cross(normal, u_axis))
    if v_axis is None:
        v_axis = np.array([0.0, 1.0, 0.0])
    roll_rad = math.radians(roll)
    rolled_u = math.cos(roll_rad) * u_axis + math.sin(roll_rad) * v_axis
    rolled_v = -math.sin(roll_rad) * u_axis + math.cos(roll_rad) * v_axis
    return rolled_u, rolled_v


@dataclass
class CrystalExportLayer:
    path: Any
    depth_at: Callable[[np.ndarray, np.ndarray], np.ndarray]
    face_color: tuple[float, ...] | None = None
    edge_color: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0)
    linewidth: float = 0.0
    dashed: bool = False
    color_at: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None


ATOM_SHADING_OPTIONS = {"none": "None", "mild": "Mild", "strong": "Strong", "very_strong": "Very strong"}
ATOM_SHADING_STRENGTH = {"none": 0.0, "mild": 0.3, "strong": 0.68, "very_strong": 0.9}
OCCUPANCY_COLOR_OPTIONS = {"blend": "Blended colors", "sectors": "Occupancy sectors"}
EXPORT_OCCUPANCY_COLOR_OPTIONS = {"panel": "Panel settings", **OCCUPANCY_COLOR_OPTIONS}


def occupancy_sectors(components: tuple) -> list[tuple[float, str]]:
    """Cumulative sector fractions, including vacancies; never change site data."""
    parts = [(float(weight), color) for _element, weight, color in components if weight > 0]
    total = sum(weight for weight, _color in parts)
    if parts and total < 1.0 - 1e-8:
        parts.append((1.0 - total, "#B8B8B8"))
        total = 1.0
    end = 0.0
    result = []
    for weight, color in parts:
        end += weight / total
        result.append((min(end, 1.0), color))
    return result


THREE_OCCUPANCY_SCRIPT = r"""
function applyOccupancySectors(mesh, sectors) {
    if (sectors.length < 2 || mesh.userData.crysdisSectors) return;
    const material = mesh.material;
    const count = sectors.length;
    const colors = sectors.map(part => new THREE.Color(part[1]));
    const ends = sectors.map(part => part[0] * 2 * Math.PI);
    // Recolor before lighting, leaving geometry, depth, opacity and highlights intact.
    material.onBeforeCompile = shader => {
        shader.uniforms.crysdisSectorColors = {value: colors};
        shader.uniforms.crysdisSectorEnds = {value: ends};
        shader.vertexShader = 'varying vec2 crysdisSectorPosition;\n' + shader.vertexShader;
        shader.vertexShader = shader.vertexShader.replace('#include <project_vertex>', `
            #include <project_vertex>
            vec4 sectorCenter = projectionMatrix * modelViewMatrix * vec4(0.0, 0.0, 0.0, 1.0);
            crysdisSectorPosition = (gl_Position.xy - sectorCenter.xy * gl_Position.w / sectorCenter.w)
                / vec2(projectionMatrix[0][0], projectionMatrix[1][1]);
        `);
        shader.fragmentShader = `
            varying vec2 crysdisSectorPosition;
            uniform vec3 crysdisSectorColors[${count}];
            uniform float crysdisSectorEnds[${count}];
            vec3 crysdisSectorColor(vec2 point) {
                float angle = mod(atan(point.x, point.y) + 6.28318530718, 6.28318530718);
                for (int i = 0; i < ${count}; i++) {
                    if (angle < crysdisSectorEnds[i]) return crysdisSectorColors[i];
                }
                return crysdisSectorColors[${count - 1}];
            }
        ` + shader.fragmentShader;
        shader.fragmentShader = shader.fragmentShader.replace('#include <color_fragment>', `
            #include <color_fragment>
            vec2 sectorDx = 0.25 * dFdx(crysdisSectorPosition);
            vec2 sectorDy = 0.25 * dFdy(crysdisSectorPosition);
            diffuseColor.rgb = 0.25 * (
                crysdisSectorColor(crysdisSectorPosition - sectorDx - sectorDy) +
                crysdisSectorColor(crysdisSectorPosition + sectorDx - sectorDy) +
                crysdisSectorColor(crysdisSectorPosition - sectorDx + sectorDy) +
                crysdisSectorColor(crysdisSectorPosition + sectorDx + sectorDy));
        `);
    };
    material.customProgramCacheKey = () => 'crysdis-sectors-v1-' + count;
    material.needsUpdate = true;
    mesh.userData.crysdisSectors = sectors;
}
"""


class CrystalScene(ui.scene):
    """Keep live atom materials consistent across redraws and browser remounts."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.atom_sectors: dict[str, list] = {}
        self.marker_groups: dict[str, list] = {}
        super().__init__(*args, **kwargs)
        # Orbit drags can end with a browser click; do not interpret those as atom picks.
        self.on("init", js_handler=f"""() => {{
            const scene = getElement({self.id});
            const canvas = scene?.renderer?.domElement;
            if (!canvas || canvas.dataset.atomClickGuard) return;
            canvas.dataset.atomClickGuard = 'true';
            let start = null, dragged = false;
            canvas.addEventListener('pointerdown', e => {{start = [e.clientX, e.clientY]; dragged = false;}});
            canvas.addEventListener('pointermove', e => {{
                if (start && Math.hypot(e.clientX-start[0], e.clientY-start[1]) > 5) dragged = true;
            }});
            canvas.addEventListener('pointercancel', () => {{start = null; dragged = true;}});
            canvas.addEventListener('click', e => {{
                start = null;
                if (dragged) e.stopImmediatePropagation();
            }}, true);
            // Split panes resize without a window resize event.
            let frame = null;
            const resizeObserver = new ResizeObserver(() => {{
                cancelAnimationFrame(frame);
                frame = requestAnimationFrame(() => {{
                    if (scene.$el.clientWidth && scene.$el.clientHeight) scene.resize();
                }});
            }});
            resizeObserver.observe(scene.$el);
            const removalObserver = new MutationObserver(() => {{
                if (scene.$el.isConnected) return;
                resizeObserver.disconnect(); removalObserver.disconnect(); cancelAnimationFrame(frame);
            }});
            removalObserver.observe(document.body, {{childList:true, subtree:true}});
        }}""")

    def _handle_init(self) -> None:
        super()._handle_init()
        self.apply_atom_sectors()
        self.apply_markers()

    def apply_markers(self) -> None:
        if not self.marker_groups:
            return
        self.client.run_javascript(
            "const {default: SceneLib} = await import('nicegui-scene'); const {THREE} = SceneLib;\n"
            + THREE_MARKERS_SCRIPT + f"\nconst component = getElement({self.id});\n"
            + "const sphereMaterial = (color, opacity) => new THREE.MeshPhongMaterial({color, opacity, transparent:true});\n"
            + f"for (const [id, markers] of Object.entries({json.dumps(self.marker_groups)})) {{\n"
              " const group = component?.objects?.get(id);\n"
              " if (group && !group.userData.crysdisMarkers) {addCrystalMarkers(THREE, group, markers, sphereMaterial); group.userData.crysdisMarkers = true;}\n"
              "}\n")

    def clear(self):
        if self.marker_groups:
            self.client.run_javascript(f"""
                const component = getElement({self.id});
                for (const id of {json.dumps(list(self.marker_groups))}) {{
                    component?.objects?.get(id)?.traverse(o => {{
                        o.geometry?.dispose(); o.material?.map?.dispose(); o.material?.dispose();
                    }});
                }}
            """)
            self.marker_groups = {}
        return super().clear()

    def apply_atom_sectors(self) -> None:
        if not self.atom_sectors:
            return
        self.client.run_javascript(
            "const {default: SceneLib} = await import('nicegui-scene'); const {THREE} = SceneLib;\n"
            + THREE_OCCUPANCY_SCRIPT + f"\nconst component = getElement({self.id});\n"
            + f"for (const [id, sectors] of Object.entries({json.dumps(self.atom_sectors)})) {{\n"
              "    const mesh = component?.objects?.get(id);\n"
              "    if (mesh) applyOccupancySectors(mesh, sectors);\n"
              "}\n")


def crystal_atom_shader(center: np.ndarray, radius: float, color: tuple[float, ...],
                        shading: str = "strong", components: tuple = ()) -> Callable:
    """Screen-fixed lighting on the same spherical surface used for atom depth."""
    strength = ATOM_SHADING_STRENGTH[shading]
    light = normalize_vector(np.array([-0.45, 0.55, 1.0]))
    halfway = normalize_vector(light + np.array([0.0, 0.0, 1.0]))
    rgb = np.asarray(color[:3])
    sectors = occupancy_sectors(components)
    boundaries = np.array([end for end, _color in sectors])
    colors = [color_to_rgb(color) for _end, color in sectors]
    sector_colors = np.asarray(colors)

    def color_at(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        base = rgb
        if sectors:
            # Subpixel samples smooth sector boundaries without gaps or overlapping wedges.
            base = np.zeros((*x.shape, 3))
            for dx, dy in ((-.25, -.25), (.25, -.25), (-.25, .25), (.25, .25)):
                turn = np.mod(np.arctan2(x + dx - center[0], y + dy - center[1]), 2 * math.pi) / (2 * math.pi)
                indices = np.minimum(np.searchsorted(boundaries, turn, side="right"), len(colors) - 1)
                base += sector_colors[indices] * .25
        if strength == 0:
            return np.broadcast_to(base, (*x.shape, 3))
        nx, ny = (x - center[0]) / radius, (y - center[1]) / radius
        nz = np.sqrt(np.maximum(1.0 - nx * nx - ny * ny, 0.0))
        diffuse = np.maximum(nx * light[0] + ny * light[1] + nz * light[2], 0.0)
        highlight = np.maximum(nx * halfway[0] + ny * halfway[1] + nz * halfway[2], 0.0) ** 80
        return np.clip(base * (1 - strength + strength * diffuse[..., None])
                       + (0.65 * strength / .68) * highlight[..., None], 0.0, 1.0)

    return color_at


def composite_crystal_export(
    layers: list[CrystalExportLayer], width: int, height: int, dpi: float, tile_size: int = 256,
) -> np.ndarray:
    """Rasterize with Agg, then alpha-composite each pixel from far to near.

    Paths use display pixels; depth increases toward the camera. Small tiles
    bound temporary memory even at 1200 dpi with several translucent planes.
    """
    from matplotlib.backends.backend_agg import RendererAgg
    from matplotlib.path import Path as MplPath
    from matplotlib.transforms import Affine2D

    paths = []
    for layer in layers:
        path = layer.path
        if layer.dashed:
            # Dashed layers are straight vector shafts. Construct the dashes before
            # viewport clipping, which would otherwise restart their phase in each tile.
            start, end = path.vertices[0], path.vertices[-1]
            delta = end - start
            length = float(np.linalg.norm(delta))
            dash_unit = layer.linewidth * dpi / 72.0
            if length > 1e-12 and dash_unit > 0.0:
                starts = np.arange(0.0, length, 5.3 * dash_unit)
                ends = np.minimum(starts + 3.7 * dash_unit, length)
                distances = np.column_stack((starts, ends)).ravel()
                vertices = start + distances[:, None] * delta / length
                path = MplPath(vertices, np.tile([MplPath.MOVETO, MplPath.LINETO], len(starts)))
        paths.append(path)

    bounds = [path.get_extents().padded(layer.linewidth * dpi / 144.0 + 2.0) for layer, path in zip(layers, paths)]
    # Agg clips paths at its viewport before stroking them. Keep those clipped
    # caps and antialiasing outside the tile that will actually be composited.
    padding = math.ceil(max((layer.linewidth for layer in layers), default=0.0) * dpi / 72.0) + 2
    image = np.zeros((height, width, 4), dtype=np.uint8)
    for bottom in range(0, height, tile_size):
        top = min(bottom + tile_size, height)
        for left in range(0, width, tile_size):
            right = min(left + tile_size, width)
            visible = [(layer, path) for layer, path, bound in zip(layers, paths, bounds)
                       if bound.x1 >= left and bound.x0 <= right and bound.y1 >= bottom and bound.y0 <= top]
            if not visible:
                continue
            renderer = RendererAgg(right - left + 2 * padding, top - bottom + 2 * padding, dpi)
            transform = Affine2D().translate(-left + padding, -bottom + padding)
            x, y = np.meshgrid(np.arange(left, right) + 0.5, np.arange(top - 1, bottom - 1, -1) + 0.5)
            colors, depths = [], []
            for layer, path in visible:
                renderer.clear()
                gc = renderer.new_gc()
                gc.set_foreground(layer.edge_color, isRGBA=True)
                gc.set_linewidth(layer.linewidth)
                gc.set_capstyle("round")
                renderer.draw_path(gc, path, transform, layer.face_color)
                gc.restore()
                rgba = np.asarray(renderer.buffer_rgba())[padding:padding + top - bottom, padding:padding + right - left].copy()
                if not np.any(rgba[:, :, 3]):
                    continue
                if layer.color_at is not None:
                    rgba[:, :, :3] = np.round(255.0 * layer.color_at(x, y)).astype(np.uint8)
                depth = np.broadcast_to(layer.depth_at(x, y), x.shape).astype(np.float32).copy()
                depth[rgba[:, :, 3] == 0] = -np.inf
                colors.append(rgba)
                depths.append(depth)
            if not colors:
                continue
            order = np.argsort(np.stack(depths), axis=0, kind="stable")
            sorted_colors = np.take_along_axis(np.stack(colors), order[:, :, :, None], axis=0)
            blended = np.zeros((*x.shape, 4), dtype=np.float32)
            for rgba in sorted_colors:
                color = rgba.astype(np.float32) / 255.0
                alpha = color[:, :, 3:4]
                blended[:, :, :3] = color[:, :, :3] * alpha + blended[:, :, :3] * (1.0 - alpha)
                blended[:, :, 3:4] = alpha + blended[:, :, 3:4] * (1.0 - alpha)
            # PNG stores straight alpha, not premultiplied colors.
            np.divide(blended[:, :, :3], blended[:, :, 3:4], out=blended[:, :, :3], where=blended[:, :, 3:4] > 0)
            image[height - top:height - bottom, left:right] = np.clip(np.round(255.0 * blended), 0, 255).astype(np.uint8)
    return image


def crystal_segment_depth(
    start: np.ndarray, end: np.ndarray, front_offset: float = 0.0,
) -> Callable[[np.ndarray, np.ndarray], np.ndarray]:
    """Depth along a projected segment, whose x/y coordinates are display pixels."""
    delta = end - start
    length_squared = float(np.dot(delta[:2], delta[:2]))
    if length_squared < 1e-20:
        return lambda x, y: np.full_like(x, max(start[2], end[2]) + front_offset, dtype=float)

    def depth_at(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        fraction = np.clip(((x - start[0]) * delta[0] + (y - start[1]) * delta[1]) / length_squared, 0.0, 1.0)
        return start[2] + fraction * delta[2] + front_offset

    return depth_at


def rotation_matrix_about_axis(axis: np.ndarray, degrees: float) -> np.ndarray:
    unit = normalize_vector(axis)
    if unit is None:
        return np.eye(3)
    x, y, z = unit
    theta = math.radians(float(degrees))
    c = math.cos(theta)
    s = math.sin(theta)
    one_minus_c = 1.0 - c
    return np.array(
        [
            [c + x * x * one_minus_c, x * y * one_minus_c - z * s, x * z * one_minus_c + y * s],
            [y * x * one_minus_c + z * s, c + y * y * one_minus_c, y * z * one_minus_c - x * s],
            [z * x * one_minus_c - y * s, z * y * one_minus_c + x * s, c + z * z * one_minus_c],
        ],
        dtype=float,
    )


def normalize_roll(degrees: float) -> float:
    return ((float(degrees) + 180.0) % 360.0) - 180.0


def roll_from_view_and_up(view_vector: np.ndarray, up_vector: np.ndarray, fallback_roll: float = 0.0) -> float:
    view = normalize_vector(view_vector)
    up = normalize_vector(up_vector)
    if view is None or up is None:
        return normalize_roll(fallback_roll)
    projected_up = normalize_vector(up - float(np.dot(up, view)) * view)
    if projected_up is None:
        return normalize_roll(fallback_roll)
    base_u, base_v = projection_basis(view, 0.0)
    angle = math.degrees(math.atan2(-float(np.dot(projected_up, base_u)), float(np.dot(projected_up, base_v))))
    return normalize_roll(angle)


def rotate_orientation(
    view_vector: np.ndarray,
    roll: float,
    axis: np.ndarray,
    crystal_degrees: float,
) -> tuple[np.ndarray, float]:
    normal = normalize_vector(view_vector)
    axis_unit = normalize_vector(axis)
    if normal is None or axis_unit is None:
        return view_vector, roll

    u_axis, _v_axis = projection_basis(normal, roll)
    # A +theta crystal rotation is represented as a -theta rotation of the
    # beam/projection basis in crystal coordinates.
    passive = rotation_matrix_about_axis(axis_unit, -float(crystal_degrees))
    new_normal = normalize_vector(passive @ normal)
    new_u = normalize_vector(passive @ u_axis)
    if new_normal is None or new_u is None:
        return normal, roll

    base_u, base_v = projection_basis(new_normal, 0.0)
    new_roll = math.degrees(math.atan2(float(np.dot(new_u, base_v)), float(np.dot(new_u, base_u))))
    return new_normal, normalize_roll(new_roll)


def orientation_frame(view_vector: np.ndarray, roll: float) -> np.ndarray:
    normal = normalize_vector(view_vector)
    if normal is None:
        normal = np.array([1.0, 0.0, 0.0])
    u_axis, v_axis = projection_basis(normal, roll)
    return np.column_stack([u_axis, v_axis, normal])


def orientation_from_frame(frame: np.ndarray, fallback_roll: float = 0.0) -> tuple[np.ndarray, float]:
    normal = normalize_vector(frame[:, 2])
    if normal is None:
        normal = np.array([1.0, 0.0, 0.0])
    u_axis = normalize_vector(frame[:, 0] - float(np.dot(frame[:, 0], normal)) * normal)
    if u_axis is None:
        return normal, normalize_roll(fallback_roll)
    base_u, base_v = projection_basis(normal, 0.0)
    roll = math.degrees(math.atan2(float(np.dot(u_axis, base_v)), float(np.dot(u_axis, base_u))))
    return normal, normalize_roll(roll)


def local_orientation_delta(
    old_view: np.ndarray,
    old_roll: float,
    new_view: np.ndarray,
    new_roll: float,
) -> np.ndarray:
    old_frame = orientation_frame(old_view, old_roll)
    new_frame = orientation_frame(new_view, new_roll)
    return old_frame.T @ new_frame


def apply_local_orientation_delta(view_vector: np.ndarray, roll: float, delta: np.ndarray) -> tuple[np.ndarray, float]:
    frame = orientation_frame(view_vector, roll)
    return orientation_from_frame(frame @ delta, fallback_roll=roll)


def parse_rotation_command(text: str, model: CrystalModel) -> tuple[RotationCommand | None, list[str]]:
    text = normalize_text(str(text or ""))
    if not text:
        return None, []

    angle_pattern = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
    in_plane = re.fullmatch(rf"\s*({angle_pattern})\s*(ccw|cw)\s*", text, flags=re.IGNORECASE)
    if in_plane:
        angle = float(in_plane.group(1))
        direction = in_plane.group(2).lower()
        if direction == "cw":
            angle = -angle
        return RotationCommand(axis=None, axis_label=f"view axis {direction}", angle_degrees=angle), []

    bare_in_plane = re.fullmatch(rf"\s*({angle_pattern})\s*", text)
    if bare_in_plane:
        return RotationCommand(axis=None, axis_label="view axis ccw", angle_degrees=float(bare_in_plane.group(1))), []

    axis_text = ""
    angle_text = ""
    if "/" in text:
        axis_text, angle_text = (part.strip() for part in text.rsplit("/", 1))
    else:
        matches = list(re.finditer(angle_pattern, text))
        if len(matches) >= 2:
            angle_match = matches[-1]
            axis_text = text[: angle_match.start()].strip()
            angle_text = angle_match.group(0)

    if not axis_text or not angle_text:
        return None, []
    try:
        angle = float(angle_text)
    except ValueError:
        return None, []

    parsed_axes, errors = parse_indices(
        axis_text,
        model,
        "direction",
        allow_multiple=False,
        allow_reciprocal=True,
    )
    if not parsed_axes:
        return None, []
    return RotationCommand(axis=parsed_axes[0].vector, axis_label=parsed_axes[0].label, angle_degrees=angle), []


def unique_points(points: list[np.ndarray], tolerance: float = 1e-6) -> list[np.ndarray]:
    unique = []
    for point in points:
        if not any(np.linalg.norm(point - saved) < tolerance for saved in unique):
            unique.append(point)
    return unique


def intersect_plane_with_edges(
    edges: list[tuple[np.ndarray, np.ndarray]],
    normal: np.ndarray,
    constant: float,
) -> np.ndarray:
    points = []
    tolerance = 1e-8
    for start, end in edges:
        start_value = float(np.dot(normal, start) - constant)
        end_value = float(np.dot(normal, end) - constant)
        if abs(start_value) < tolerance:
            points.append(start)
        if abs(end_value) < tolerance:
            points.append(end)
        if start_value * end_value < -tolerance:
            fraction = start_value / (start_value - end_value)
            points.append(start + fraction * (end - start))
    return np.array(unique_points(points), dtype=float)


def clipped_plane_polygon(model: CrystalModel, plane: ParsedIndex) -> np.ndarray | None:
    coefficients = plane_coefficients(plane.values, model)
    normal = coefficients @ reciprocal_lattice(model.display_lattice)
    normal_unit = normalize_vector(normal)
    if normal_unit is None:
        return None
    constant = float(np.dot(normal, model.display_origin) + 1.0)
    edges = model.clip_edges if model.clip_edges is not None else model.display_edges
    polygon = intersect_plane_with_edges(edges, normal, constant)
    if len(polygon) < 3:
        vertices = np.array([point for edge in edges for point in edge], dtype=float)
        projected = vertices @ normal
        constant = float(0.5 * (projected.min() + projected.max()))
        polygon = intersect_plane_with_edges(edges, normal, constant)
    if len(polygon) < 3:
        return None

    centroid = np.mean(polygon, axis=0)
    u_axis, v_axis = projection_basis(normal_unit)
    angles = [math.atan2(float(np.dot(point - centroid, v_axis)), float(np.dot(point - centroid, u_axis))) for point in polygon]
    return polygon[np.argsort(angles)]


def rotation_matrix_from_y(direction: np.ndarray) -> list[list[float]]:
    target = normalize_vector(direction)
    if target is None:
        return np.eye(3).tolist()
    source = np.array([0.0, 1.0, 0.0])
    dot = float(np.clip(np.dot(source, target), -1.0, 1.0))
    if dot > 0.999999:
        return np.eye(3).tolist()
    if dot < -0.999999:
        return np.array([[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]]).tolist()
    axis = normalize_vector(np.cross(source, target))
    if axis is None:
        return np.eye(3).tolist()
    x, y, z = axis
    angle = math.acos(dot)
    c = math.cos(angle)
    s = math.sin(angle)
    one_c = 1.0 - c
    matrix = np.array(
        [
            [c + x * x * one_c, x * y * one_c - z * s, x * z * one_c + y * s],
            [y * x * one_c + z * s, c + y * y * one_c, y * z * one_c - x * s],
            [z * x * one_c - y * s, z * y * one_c + x * s, c + z * z * one_c],
        ],
        dtype=float,
    )
    return matrix.tolist()


def xray_form_factor_from_coefficients(
    a_values: list[float],
    b_values: list[float],
    c_value: float,
    s_angstrom_inv: float,
) -> float:
    s2 = s_angstrom_inv * s_angstrom_inv
    return float(sum(a * math.exp(-b * s2) for a, b in zip(a_values, b_values)) + c_value)


def xray_zero_from_coefficients(a_values: list[float], c_value: float) -> float:
    return float(sum(a_values) + c_value)


def electron_form_factor_zero_limit(element: str) -> float:
    symbol = element.strip().capitalize()
    z = float(ATOMIC_NUMBERS.get(symbol, 18))
    if symbol in CROMER_MANN:
        a_values, b_values, _c_value = CROMER_MANN[symbol]
        return MOTT_BETHE_CONVERSION_ANGSTROM_INV * float(sum(a * b for a, b in zip(a_values, b_values)))
    return MOTT_BETHE_CONVERSION_ANGSTROM_INV * FALLBACK_XRAY_GAUSSIAN_B * z


def atomic_form_factor(element: str, g_nm_inv: float) -> float:
    symbol = element.strip().capitalize()
    return cached_atomic_form_factor(symbol, round(max(float(g_nm_inv), 0.0), 10))


@lru_cache(maxsize=100_000)
def cached_atomic_form_factor(symbol: str, g_nm_inv: float) -> float:
    g_ang_inv = max(float(g_nm_inv), 0.0) / 10.0
    s = 0.5 * g_ang_inv
    if s <= MOTT_BETHE_S_TOL:
        return electron_form_factor_zero_limit(symbol)
    z = float(ATOMIC_NUMBERS.get(symbol, 18))
    if symbol in CROMER_MANN:
        a_values, b_values, c_value = CROMER_MANN[symbol]
        xray_factor = xray_form_factor_from_coefficients(a_values, b_values, c_value, s)
        neutral_xray_factor = xray_zero_from_coefficients(a_values, c_value)
    else:
        xray_factor = z * math.exp(-FALLBACK_XRAY_GAUSSIAN_B * s * s)
        neutral_xray_factor = z
    return max(MOTT_BETHE_CONVERSION_ANGSTROM_INV * (neutral_xray_factor - xray_factor) / (s * s), 0.0)


def structure_factor(
    definition: CrystalDefinition,
    hkl: np.ndarray,
    g_nm_inv: float,
    sites: list[AtomicSite] | None = None,
) -> complex:
    factor = 0.0j
    active_sites = sites if sites is not None else expanded_sites(definition)
    for site in active_sites:
        occupancy = min(max(float(site.occupancy), 0.0), 1.0)
        if occupancy <= 0.0:
            continue
        phase = 2.0 * math.pi * float(np.dot(hkl, site.fractional))
        factor += occupancy * atomic_form_factor(site.element, g_nm_inv) * complex(math.cos(phase), math.sin(phase))
    return factor


def electron_wavelength_nm(voltage_kv: float) -> float:
    voltage_v = max(float(voltage_kv), 1e-6) * 1000.0
    wavelength_angstrom = 12.3986 / math.sqrt(voltage_v * (1.0 + 0.97845e-6 * voltage_v))
    return wavelength_angstrom * 0.1


def detector_scale_mm_per_nm_inv(camera_length_mm: float, voltage_kv: float) -> float:
    """Return detector-plane distance in mm for 1 nm^-1 reciprocal spacing.

    For small-angle electron diffraction, R ~= L * lambda * g, where
    L is camera length in mm, lambda is electron wavelength in nm, and
    g is reciprocal spacing in nm^-1.
    """
    return max(float(camera_length_mm), 1e-9) * electron_wavelength_nm(voltage_kv)


def default_detector_half_width_mm() -> float:
    """Detector half-width used for the diffraction plot in camera mode.

    It is chosen so the default 500 kV / 200 mm view shows the same
    reciprocal-space window that the previous implementation used.
    """
    return DIFFRACTION_BASE_LIMIT_NM_INV * detector_scale_mm_per_nm_inv(
        DEFAULT_CAMERA_LENGTH_MM,
        DEFAULT_VOLTAGE_KV,
    )


def choose_scale_bar(limit: float) -> float:
    target = max(limit * 0.32, 1e-9)
    exponent = math.floor(math.log10(target))
    base = target / 10**exponent
    if base < 2.0:
        nice = 1.0
    elif base < 5.0:
        nice = 2.0
    else:
        nice = 5.0
    return nice * 10**exponent


def diffraction_scale_bar_items(
    limit: float,
    reciprocal_units_per_plot_unit: float = 1.0,
    settings: PanelAnnotations | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build a scale bar for the diffraction panel.

    In detector/camera display mode, the plot coordinates are detector-plane
    distances in mm, but the label is still reported as reciprocal-space length
    in nm^-1.  reciprocal_units_per_plot_unit converts one plotted unit into
    nm^-1; for detector coordinates it is 1 / (L * lambda).
    """
    settings = settings or PanelAnnotations()
    style = settings.reciprocal_scale
    if not settings.reciprocal_scale_visible:
        return [], []
    right, top = "right" in style.position, "top" in style.position
    reciprocal_units_per_plot_unit = max(float(reciprocal_units_per_plot_unit), 1e-12)
    reciprocal_limit = max(float(limit) * reciprocal_units_per_plot_unit, 1e-9)
    bar_reciprocal = choose_scale_bar(reciprocal_limit)
    bar_plot = bar_reciprocal / reciprocal_units_per_plot_unit
    x0 = 0.94 * limit - bar_plot if right else -0.94 * limit
    y0 = (0.91 if top else -0.91) * limit
    tick = 0.022 * limit
    line = {"type": "line", "xref": "x", "yref": "y", "opacity": style.opacity,
            "line": {"color": style.color, "width": 3}}
    shapes = [
        {**line, "x0": x0, "x1": x0 + bar_plot, "y0": y0, "y1": y0},
        {**line, "x0": x0, "x1": x0, "y0": y0 - tick, "y1": y0 + tick, "line": {"color": style.color, "width": 2}},
        {
            **line,
            "x0": x0 + bar_plot,
            "x1": x0 + bar_plot,
            "y0": y0 - tick,
            "y1": y0 + tick,
            "line": {"color": style.color, "width": 2},
        },
    ]
    annotations = [
        {
            "x": x0 + bar_plot * 0.5,
            "y": y0,
            "yshift": -7 if top else 7,
            "xref": "x",
            "yref": "y",
            "text": f"{bar_reciprocal:g} nm<sup>-1</sup>",
            "showarrow": False,
            "font": {"color": style.color, "size": style.font_size},
            "xanchor": "center",
            "yanchor": "top" if top else "bottom",
            "opacity": style.opacity,
        }
    ]
    return shapes, annotations


def diffraction_zone_axis_annotation(limit: float, label: str, settings: PanelAnnotations | None = None,
                                    scale_visible: bool = True) -> dict[str, Any]:
    settings = settings or PanelAnnotations()
    style = settings.zone
    right, top = "right" in style.position, "top" in style.position
    shift = 0
    if scale_visible and settings.reciprocal_scale_visible and settings.reciprocal_scale.opacity > 0 and style.position == settings.reciprocal_scale.position:
        shift = (settings.reciprocal_scale.font_size + 20) * (-1 if top else 1)
    return {
        "x": (0.94 if right else -0.94) * float(limit),
        "y": (0.91 if top else -0.91) * float(limit),
        "yshift": shift,
        "xref": "x",
        "yref": "y",
        "text": label,
        "showarrow": False,
        "font": {"color": style.color, "size": style.font_size},
        "xanchor": "right" if right else "left",
        "yanchor": "top" if top else "bottom",
        "opacity": style.opacity,
    }


def empty_diffraction_figure() -> dict[str, Any]:
    return {
        "data": [],
        "layout": {
            "paper_bgcolor": "#000000",
            "plot_bgcolor": "#000000",
            "margin": {"l": 0, "r": 0, "t": 0, "b": 0},
            "xaxis": {"visible": False, "range": [-4, 4], "scaleanchor": "y", "scaleratio": 1, "fixedrange": True, "constrain": "domain"},
            "yaxis": {"visible": False, "range": [-4, 4], "fixedrange": True, "constrain": "domain"},
            "showlegend": False,
            "hovermode": "closest",
            "dragmode": False,
        },
        "config": {"displayModeBar": False, "responsive": True, "scrollZoom": False},
    }


def calculate_camera_distance(crystal_radius: float, fov_degrees: float, fit_fraction: float = REAL_SCENE_FIT_FRACTION) -> float:
    theta_radians = math.radians(max(float(fov_degrees), 0.01) / 2.0)
    return max(float(crystal_radius), 1e-6) / (max(float(fit_fraction), 0.1) * math.tan(theta_radians))


def canonical_symmetry_site(group: list[Any]) -> Any:
    def site_key(site: Any) -> tuple[float, float, float, float]:
        frac = snap_fractional(wrap_fractional(np.asarray(site.frac_coords, dtype=float)))
        return (round(float(frac[2]), 8), -round(float(np.sum(frac)), 8), round(float(frac[1]), 8), round(float(frac[0]), 8))

    return sorted(group, key=site_key)[0]


def cif_values(block: dict[str, Any], *keys: str) -> list[Any]:
    value = cif_block_value(block, *keys)
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def cif_value_at(values: list[Any], index: int, default: Any = "") -> Any:
    if not values:
        return default
    if index < len(values):
        return values[index]
    return values[-1]


def parse_cif_float(value: Any, default: float = 0.0) -> float:
    text = str(value if value is not None else "").strip().strip("'\"")
    if text in {"", ".", "?"}:
        return float(default)
    if "/" in text and re.fullmatch(r"[-+]?\d+\s*/\s*[-+]?\d+", text):
        numerator, denominator = text.split("/", 1)
        try:
            return float(numerator) / float(denominator)
        except ZeroDivisionError:
            return float(default)
    text = re.sub(r"\([^)]*\)$", "", text)
    try:
        return float(text)
    except ValueError:
        return float(default)


def element_from_cif_atom(type_symbol: Any, label: Any) -> str:
    for value in (type_symbol, label):
        text = str(value if value is not None else "").strip().strip("'\"")
        match = re.match(r"([A-Za-z]{1,2})", text)
        if match:
            return match.group(1).capitalize()
    return ""


def declared_cif_symmetry_operations(block: dict[str, Any], declared_space_group: str) -> list[Any]:
    operation_texts = cif_values(
        block,
        "_space_group_symop_operation_xyz",
        "_symmetry_equiv_pos_as_xyz",
        "_space_group_symop.operation_xyz",
        "_symmetry_equiv.pos_as_xyz",
    )
    operation_texts = [str(text).strip().strip("'\"") for text in operation_texts if str(text).strip() not in {"", ".", "?"}]
    if operation_texts:
        try:
            return list(parsed_symmetry_operations(tuple(operation_texts)))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Could not read the CIF symmetry operations: {exc}") from exc

    from pymatgen.symmetry.groups import SpaceGroup

    hall_symbol = cif_block_value(block, "_space_group_name_Hall", "_symmetry_space_group_name_Hall", "_space_group.name_Hall")
    if hall_symbol and str(hall_symbol).strip() not in {".", "?"}:
        hall_key = re.sub(r"\s+", "", str(hall_symbol))
        for setting in SpaceGroup.SYMM_OPS:
            if re.sub(r"\s+", "", setting["hall"]) == hall_key:
                return list(parsed_symmetry_operations(tuple(setting["symops"])))

    symbol = space_group_symbol(declared_space_group)
    if symbol in {"", "P1", "1"}:
        return []
    try:
        space_group = SpaceGroup.from_int_number(int(symbol)) if symbol.isdigit() else SpaceGroup(symbol)
        return list(space_group.symmetry_ops)
    except ValueError as exc:
        raise ValueError(f"Could not determine CIF symmetry from space group {symbol!r}") from exc


@lru_cache(maxsize=256)
def space_group_for_operations(symbol: str, operation_texts: tuple[str, ...]) -> str:
    from pymatgen.symmetry.groups import SpaceGroup

    def operation_keys(operations: Any) -> set[tuple[float, ...]]:
        return {
            tuple(np.round(operation.rotation_matrix.ravel(), 7))
            + tuple(np.round(wrap_fractional(operation.translation_vector), 7))
            for operation in operations
        }

    operations = parsed_symmetry_operations(operation_texts)
    if not operations:
        return symbol
    try:
        import spglib

        group_type = spglib.get_spacegroup_type_from_symmetry(
            [operation.rotation_matrix for operation in operations],
            [operation.translation_vector for operation in operations],
        )
        if group_type is not None:
            symbol = space_group_symbol_from_number(group_type.number)
    except (ImportError, ValueError):
        pass
    expected = operation_keys(operations)
    try:
        candidates = [symbol, *sorted(SpaceGroup.get_settings(symbol))]
        for candidate in candidates:
            if operation_keys(SpaceGroup(candidate).symmetry_ops) == expected:
                return space_group_symbol(candidate)
    except ValueError:
        pass
    # A nonstandard origin/basis may have no matching named setting; keep its operations.
    return symbol


def fractional_points_match(a: np.ndarray, b: np.ndarray, tolerance: float = SYMMETRY_SITE_TOL) -> bool:
    delta = np.abs(wrap_fractional(np.asarray(a, dtype=float) - np.asarray(b, dtype=float)))
    delta = np.minimum(delta, 1.0 - delta)
    return bool(np.all(delta <= tolerance))


def equivalent_under_operations(site: AtomicSite, representative: AtomicSite, operations: list[Any]) -> bool:
    if site.element.strip().capitalize() != representative.element.strip().capitalize():
        return False
    if not math.isclose(float(site.occupancy), float(representative.occupancy), abs_tol=1e-5):
        return False
    target = wrap_fractional(site.fractional)
    base = wrap_fractional(representative.fractional)
    for operation in operations:
        frac = wrap_fractional(operation.operate(base))
        if fractional_points_match(frac, target, tolerance=1e-6):
            return True
    return False


def reduce_cif_sites_by_declared_symmetry(
    sites: list[AtomicSite], block: dict[str, Any], declared_space_group: str
) -> list[AtomicSite]:
    operations = declared_cif_symmetry_operations(block, declared_space_group)
    if not operations:
        return [AtomicSite(**asdict(site)) for site in sites]

    representatives: list[AtomicSite] = []
    for site in sites:
        if any(equivalent_under_operations(site, representative, operations) for representative in representatives):
            continue
        representatives.append(AtomicSite(**asdict(site)))
    return representatives


def atomic_sites_from_cif_block(block: dict[str, Any], declared_space_group: str) -> list[AtomicSite]:
    xs = cif_values(block, "_atom_site_fract_x")
    ys = cif_values(block, "_atom_site_fract_y")
    zs = cif_values(block, "_atom_site_fract_z")
    if not xs or not ys or not zs:
        return []

    labels = cif_values(block, "_atom_site_label")
    symbols = cif_values(block, "_atom_site_type_symbol")
    occupancies = cif_values(block, "_atom_site_occupancy")
    row_count = max(len(xs), len(ys), len(zs), len(labels), len(symbols), len(occupancies), 0)
    sites: list[AtomicSite] = []
    for index in range(row_count):
        label = str(cif_value_at(labels, index, "")).strip().strip("'\"")
        element = element_from_cif_atom(cif_value_at(symbols, index, ""), label)
        if not element:
            continue
        frac = wrap_fractional(
            np.array(
                [
                    parse_cif_float(cif_value_at(xs, index, 0.0)),
                    parse_cif_float(cif_value_at(ys, index, 0.0)),
                    parse_cif_float(cif_value_at(zs, index, 0.0)),
                ],
                dtype=float,
            )
        )
        sites.append(
            AtomicSite(
                element=element,
                x=float(frac[0]),
                y=float(frac[1]),
                z=float(frac[2]),
                occupancy=parse_cif_float(cif_value_at(occupancies, index, 1.0), 1.0),
                label=label or element,
                color=color_for_element(element),
            )
        )
    return reduce_cif_sites_by_declared_symmetry(sites, block, declared_space_group)


def atomic_sites_from_structure(structure: Any, *, representatives_only: bool) -> list[AtomicSite]:
    source_sites: list[Any]
    if representatives_only:
        try:
            from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

            symmetrized = SpacegroupAnalyzer(structure, symprec=0.01).get_symmetrized_structure()
            source_sites = [canonical_symmetry_site(list(group)) for group in symmetrized.equivalent_sites]
        except Exception:
            source_sites = list(structure)
    else:
        source_sites = list(structure)

    sites: list[AtomicSite] = []
    for site in source_sites:
        frac = wrap_fractional(np.asarray(site.frac_coords, dtype=float))
        for specie, occupancy in site.species.items():
            element = getattr(specie, "symbol", str(specie)).strip().capitalize()
            sites.append(
                AtomicSite(
                    element=element,
                    x=float(frac[0]),
                    y=float(frac[1]),
                    z=float(frac[2]),
                    occupancy=float(occupancy),
                    label=str(site.label or element),
                    color=color_for_element(element),
                )
            )
    return sites


def definition_from_cif(path: Path) -> CrystalDefinition:
    try:
        from pymatgen.io.cif import CifBlock, CifFile, CifParser
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    except Exception as exc:
        raise ValueError(f"pymatgen is required to load CIF files: {exc}") from exc

    try:
        blocks = CifFile.from_file(str(path)).data
        source_block = next(
            (block for block in blocks.values() if cif_block_value(block.data, "_atom_site_fract_x", "_atom_site.fract_x") is not None),
            next(iter(blocks.values())),
        )
        # Normalize CIF tag spelling, then give pymatgen the same operations used by the model.
        normalize_tag = lambda key: str(key).lower().replace(".", "_").rstrip("_")
        cif_block = {normalize_tag(key): value for key, value in source_block.data.items()}
        declared_space_group = declared_space_group_from_cif_block(cif_block)
        operations = declared_cif_symmetry_operations(cif_block, declared_space_group)
        operation_texts = [operation.as_xyz_str() for operation in operations] or ["x, y, z"]
        operation_tag = "_symmetry_equiv_pos_as_xyz"
        cif_block[operation_tag] = operation_texts
        loops = [[normalize_tag(key) for key in loop if normalize_tag(key) != operation_tag] for loop in source_block.loops]
        sites = atomic_sites_from_cif_block(cif_block, declared_space_group)
        parser_data = dict(cif_block)
        if sites:
            # Some exporters include equivalent sites as well as symmetry; expand each orbit only once.
            parser_data = {key: value for key, value in parser_data.items() if not key.startswith("_atom_site_")}
            loops = [[key for key in loop if key in parser_data] for loop in loops]
            atom_columns = {
                "_atom_site_label": [site.label for site in sites],
                "_atom_site_type_symbol": [site.element for site in sites],
                "_atom_site_fract_x": [str(site.x) for site in sites],
                "_atom_site_fract_y": [str(site.y) for site in sites],
                "_atom_site_fract_z": [str(site.z) for site in sites],
                "_atom_site_occupancy": [str(site.occupancy) for site in sites],
            }
            parser_data.update(atom_columns)
            loops.append(list(atom_columns))
        parser_block = CifBlock(parser_data, [loop for loop in loops if loop] + [[operation_tag]], source_block.header)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            parser = CifParser.from_str(str(parser_block), frac_tolerance=0)
            structure = parser.parse_structures(primitive=False)[0]
    except Exception as exc:
        raise ValueError(f"Could not read CIF file: {exc}") from exc

    lattice = structure.lattice
    crystal_system = "triclinic"
    declared_space_group = space_group_for_operations(declared_space_group, tuple(operation_texts))
    try:
        analyzer = SpacegroupAnalyzer(structure, symprec=0.01)
        crystal_system = str(analyzer.get_crystal_system()).lower()
    except Exception:
        pass

    if not sites:
        sites = atomic_sites_from_structure(structure, representatives_only=False)
        sites = reduce_cif_sites_by_declared_symmetry(sites, cif_block, declared_space_group)

    if not sites:
        raise ValueError("The CIF file did not contain any atom sites.")

    return CrystalDefinition(
        name=path.stem,
        lattice_system=crystal_system if crystal_system in LATTICE_SYSTEMS else "triclinic",
        a=float(lattice.a) * 0.1,
        b=float(lattice.b) * 0.1,
        c=float(lattice.c) * 0.1,
        alpha=float(lattice.alpha),
        beta=float(lattice.beta),
        gamma=float(lattice.gamma),
        space_group=declared_space_group,
        repeat_boundary_atoms=True,
        sites=sites,
        symmetry_operations=operation_texts,
    )


def color_for_element(element: str) -> str:
    symbol = element.strip().capitalize()
    if symbol in ELEMENT_COLORS:
        return ELEMENT_COLORS[symbol]
    if symbol in GENERATED_ELEMENT_COLORS:
        return GENERATED_ELEMENT_COLORS[symbol]
    used = {
        color
        for color in (normalized_hex_color(color) for color in [*ELEMENT_COLORS.values(), *GENERATED_ELEMENT_COLORS.values()])
        if color is not None
    }
    seed = sum((index + 1) * ord(char) for index, char in enumerate(symbol)) or 119
    for offset in range(256):
        color = generated_element_color(seed + offset, offset)
        if color not in used:
            return color
    return "#35D0BA"


def color_for_site(site: AtomicSite | DisplayAtom, element_colors: dict[str, str] | None = None) -> str:
    if element_colors and site.element.strip().capitalize() in element_colors:
        return element_colors[site.element.strip().capitalize()]
    color = str(getattr(site, "color", "") or "").strip()
    if re.match(r"^#[0-9a-fA-F]{6}$", color):
        return color
    return color_for_element(site.element)


def relevant_element_colors(model: CrystalModel, colors: dict[str, str]) -> dict[str, str]:
    elements = {site.element.strip().capitalize() for site in model.expanded_sites}
    return {symbol: color for symbol, color in colors.items() if symbol in elements}


def display_element_colors(model: CrystalModel, settings: PanelDisplaySettings, colors: dict[str, str]) -> dict[str, str]:
    """Adapt only built-in demo colors; never overwrite user color preferences."""
    result = relevant_element_colors(model, colors)
    default = DEFAULT_CRYSTALS.get(model.definition.name)
    if default is None or contrast_text_color(settings.backgrounds.crystal) != "#000000":
        return result
    site = default.sites[0]
    if model.definition.sites and all(atom.element == site.element and str(atom.color or "").upper() == site.color.upper()
                                      for atom in model.definition.sites):
        result.setdefault(site.element, LIGHT_BACKGROUND_DEMO_COLORS[default.name])
    return result


def validate_element_colors(colors: Any) -> dict[str, str]:
    if not isinstance(colors, dict):
        raise ValueError("Element colors must be a dictionary.")
    result = {}
    for element, value in colors.items():
        if element not in ELEMENTS:
            raise ValueError(f"Unknown element: {element}")
        color = normalized_hex_color(value)
        if color is None:
            raise ValueError(f"{element} color must be a six-digit hex color.")
        result[element] = color
    return result


def load_element_colors(path: Path | None = None) -> dict[str, str]:
    path = path or ELEMENT_COLORS_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError("Unsupported element-color preferences format.")
        return validate_element_colors(payload.get("element_colors"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError) as exc:
        warnings.warn(f"Could not load element colors from {path}: {exc}. Using structure/default colors.")
        return {}


def save_element_colors(colors: dict[str, str], path: Path | None = None) -> None:
    path = path or ELEMENT_COLORS_PATH
    payload = {"version": 1, "element_colors": validate_element_colors(colors)}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def validate_theme(theme: InterfaceTheme) -> InterfaceTheme:
    if not isinstance(theme, InterfaceTheme) or not isinstance(theme.dark, bool):
        raise ValueError("Invalid interface theme.")
    values = {}
    for name in THEME_COLOR_LABELS:
        value = normalized_hex_color(getattr(theme, name))
        if value is None:
            raise ValueError(f"{THEME_COLOR_LABELS[name]} must be a six-digit hex color.")
        values[name] = value
    backgrounds = theme.backgrounds
    if not isinstance(backgrounds, PanelBackgrounds) or type(backgrounds.automatic_text) is not bool:
        raise ValueError("Invalid theme panel backgrounds.")
    colors = [normalized_hex_color(value) for value in (backgrounds.crystal, backgrounds.diffraction)]
    if any(value is None for value in colors):
        raise ValueError("Panel backgrounds must be six-digit hex colors.")
    return replace(theme, backgrounds=PanelBackgrounds(*colors, backgrounds.automatic_text), **values)


def load_theme(path: Path | None = None) -> InterfaceTheme:
    path = path or THEME_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") not in (1, 2) or not isinstance(payload.get("theme"), dict):
            raise ValueError("Unsupported theme preferences format.")
        values = payload["theme"].copy()
        values["backgrounds"] = PanelBackgrounds(**values.get("backgrounds", {}))
        return validate_theme(InterfaceTheme(**values))
    except FileNotFoundError:
        return InterfaceTheme()
    except (OSError, ValueError, TypeError) as exc:
        warnings.warn(f"Could not load theme from {path}: {exc}. Using the default theme.")
        return InterfaceTheme()


def save_theme(theme: InterfaceTheme, path: Path | None = None) -> None:
    path = path or THEME_PATH
    payload = {"version": 2, "theme": asdict(validate_theme(theme))}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class SavedThemeStore:
    _lock = threading.RLock()

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @staticmethod
    def name(value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("Enter a theme name.")
        value = value.strip()
        if not value or len(value) > 80 or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Use a theme name between 1 and 80 characters, without control characters.")
        if value.casefold() in {name.casefold() for name in (*THEME_PRESETS, "Custom")}:
            raise ValueError("This name is reserved. Choose a name different from the built-in themes and Custom.")
        return value

    def read(self) -> dict[str, InterfaceTheme]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise ValueError(f"Cannot read saved themes: {exc}. The file has not been changed.") from exc
        try:
            if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("themes"), dict):
                raise ValueError("Unsupported saved-theme format.")
            themes, names = {}, set()
            for name, values in payload["themes"].items():
                if self.name(name) != name or name.casefold() in names or not isinstance(values, dict):
                    raise ValueError("Invalid or duplicate saved-theme name.")
                values = values.copy()
                values["backgrounds"] = PanelBackgrounds(**values.get("backgrounds", {}))
                themes[name] = validate_theme(InterfaceTheme(**values))
                names.add(name.casefold())
            return themes
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Cannot read saved themes: {exc}. The file has not been changed.") from exc

    def _write(self, themes: dict[str, InterfaceTheme]) -> None:
        payload = {"version": 1, "themes": {name: asdict(validate_theme(theme)) for name, theme in themes.items()}}
        text = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def save(self, name: str, theme: InterfaceTheme) -> dict[str, InterfaceTheme]:
        name, theme = self.name(name), validate_theme(theme)
        with self._lock:
            themes = self.read()
            if any(saved.casefold() == name.casefold() for saved in themes):
                raise ValueError("A saved theme with this name already exists. Choose another name or update that theme.")
            themes[name] = theme
            self._write(themes)
            return themes

    def change(self, name: str, action: str, value=None, *, expected: InterfaceTheme) -> dict[str, InterfaceTheme]:
        with self._lock:
            themes = self.read()
            if name not in themes or themes[name] != expected:
                raise ValueError("This saved theme changed or was removed. Reopen Theme before trying again.")
            if action == "update":
                themes[name] = validate_theme(value)
            elif action == "rename":
                renamed = self.name(value)
                if any(saved != name and saved.casefold() == renamed.casefold() for saved in themes):
                    raise ValueError("A saved theme with this name already exists.")
                theme = themes.pop(name)
                themes[renamed] = theme
            elif action == "delete":
                del themes[name]
            else:
                raise ValueError("Unknown saved-theme action.")
            self._write(themes)
            return themes


def theme_css(theme: InterfaceTheme) -> str:
    theme = validate_theme(theme)
    variables = ";".join(f"--crys-{name}:{getattr(theme, name)}" for name in THEME_COLOR_LABELS)
    return f"""
        :root {{{variables}; --q-primary:{theme.primary}; --q-secondary:{theme.secondary};
                 --q-dark:{theme.surface}; --q-dark-page:{theme.page};
                 --crys-accent-text:{contrast_text_color(theme.primary)};
                 --crys-border:{rgba_css(theme.text, .18)};}}
        body.body--dark, body.body--light {{background:var(--crys-page);color:var(--crys-text);}}
        .app-header {{background:var(--crys-header);color:var(--crys-text);border-color:var(--crys-border);}}
        .comparison-panel, .combo-panel {{background:var(--crys-panel);border-color:var(--crys-border);}}
        .q-dialog__inner > .q-card, .q-menu {{background:var(--crys-surface);color:var(--crys-text);}}
        .q-field__native, .q-field__input, .q-field__prefix, .q-field__suffix,
        .q-field__marginal, .q-checkbox__label, .q-item {{color:var(--crys-text);}}
        .q-field__label {{color:var(--crys-muted);}}
        /* Layered important rules take precedence over unlayered ones in Quasar. */
        @layer overrides {{
            .q-btn.bg-primary {{color:var(--crys-accent-text)!important;}}
            .q-btn:is(.animation-drag, .marker-vertex-drag, .combo-source-drag):is(:hover, :active, :focus-visible):not([disabled]),
            :is(.animation-drag-active, .animation-drag-preview) .animation-drag,
            :is(.marker-vertex-chosen, .marker-vertex-ghost) .marker-vertex-drag,
            :is(.combo-source-chosen, .combo-source-ghost) .combo-source-drag {{color:var(--q-secondary)!important;}}
        }}
        .top-checkbox, .panel-number, .combo-number, .combo-bind-checkbox,
        .combo-source-header, .combo-source-row, .intro-text, .intro-text h3,
        .crystal-list-name, .palette-title, .advanced-checkbox {{color:var(--crys-text);}}
        .combo-source-list, .combo-source-ghost, .marker-vertex-ghost,
        .animation-drag-preview {{background:var(--crys-surface);}}
        .export-folder-label, .crystal-list-meta, .advanced-slider-label,
        .palette-index {{color:var(--crys-muted);}}
        .atom-inspector {{background:var(--crys-surface);color:var(--crys-text);border-color:var(--crys-border);}}
        .atom-coordinate-caption {{color:var(--crys-muted);}}
        .combo-bind-checkbox[aria-checked="true"] .q-checkbox__label {{color:var(--q-secondary);}}
        .panel-split-handle::after {{background:var(--crys-muted);}}
        .panel-splitter > .q-splitter__separator:hover .panel-split-handle::after,
        .panel-splitter.q-splitter--active > .q-splitter__separator .panel-split-handle::after {{background:var(--q-secondary);}}
    """


def color_to_rgb(color: str) -> tuple[float, float, float]:
    match = re.match(r"^#?([0-9a-fA-F]{6})$", str(color or "").strip())
    if not match:
        return (0.20, 0.82, 0.73)
    value = match.group(1)
    return tuple(int(value[index : index + 2], 16) / 255.0 for index in (0, 2, 4))


def rgba_css(color: str, alpha: float) -> str:
    red, green, blue = (int(round(component * 255.0)) for component in color_to_rgb(color))
    return f"rgba({red}, {green}, {blue}, {min(max(float(alpha), 0.0), 1.0):.3f})"


def dominant_color(definition: CrystalDefinition) -> str:
    weighted_rgb = np.zeros(3, dtype=float)
    total_weight = 0.0
    for site in definition.sites:
        weight = max(float(site.occupancy), 0.0) * max(float(ATOMIC_NUMBERS.get(site.element.strip().capitalize(), 18)), 1.0)
        if weight <= 0.0:
            continue
        weighted_rgb += weight * np.array(color_to_rgb(color_for_site(site)), dtype=float)
        total_weight += weight
    if total_weight <= 0.0:
        return "#35D0BA"
    rgb = np.clip(np.round(255.0 * weighted_rgb / total_weight), 0, 255).astype(int)
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"

class CrystalLibrary:
    def __init__(self) -> None:
        self.definitions: dict[str, CrystalDefinition] = {}
        self.reload()

    def reload(self) -> None:
        self.definitions = {name: CrystalDefinition.from_dict(definition.to_dict()) for name, definition in DEFAULT_CRYSTALS.items()}
        for path in (BUNDLED_LIBRARY_PATH, LEGACY_LIBRARY_PATH, USER_LIBRARY_PATH):
            self.definitions.update(self._load_path(path))
        self._refresh_legacy_cif_imports()

    def options(self) -> list[str]:
        custom_names = sorted(name for name in self.definitions if name not in DEFAULT_NAMES)
        return ["FCC", "BCC", "HCP", *custom_names, CUSTOM_SENTINEL]

    def get(self, name: str) -> CrystalDefinition:
        return self.definitions.get(name, self.definitions["FCC"])

    def exists(self, name: str) -> bool:
        return (name or "").strip() in self.definitions

    def path_for_scope(self, scope: str) -> Path:
        return USER_LIBRARY_PATH

    def save(self, definition: CrystalDefinition, scope: str) -> CrystalDefinition:
        definition = CrystalDefinition.from_dict(definition.to_dict())
        definition.name = self._custom_name(definition.name)
        definition.structure_id = (crystal_identity(self.get(definition.name)) if self.exists(definition.name)
                                   else str(uuid.uuid4()))
        path = self.path_for_scope(scope)
        saved = self._load_path(path)
        saved[definition.name] = definition
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"structures": [saved[name].to_dict() for name in sorted(saved)]}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.reload()
        return definition

    def save_new(self, definition: CrystalDefinition, scope: str) -> CrystalDefinition:
        definition = CrystalDefinition.from_dict(definition.to_dict())
        definition.name = (definition.name or "Customized crystal").strip() or "Customized crystal"
        if self.exists(definition.name):
            raise ValueError(
                f"A structure named {definition.name!r} already exists. Change the name or use SAVE EDITED STRUCTURE."
            )
        definition.structure_id = str(uuid.uuid4())
        path = self.path_for_scope(scope)
        saved = self._load_path(path)
        saved[definition.name] = definition
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"structures": [saved[name].to_dict() for name in sorted(saved)]}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.reload()
        return definition

    def save_edited(self, definition: CrystalDefinition, scope: str, original_name: str | None) -> CrystalDefinition:
        definition = CrystalDefinition.from_dict(definition.to_dict())
        definition.name = self._custom_name(definition.name)
        original_name = (original_name or "").strip()
        if original_name and original_name not in DEFAULT_NAMES and definition.name != original_name and self.exists(definition.name):
            raise ValueError(f"A structure named {definition.name!r} already exists. Choose another name or save as a new structure.")

        definition.structure_id = (crystal_identity(self.get(original_name))
                                   if original_name not in DEFAULT_NAMES and self.exists(original_name)
                                   else str(uuid.uuid4()))

        target_path = self.path_for_scope(scope)
        target_saved = self._load_path(target_path)
        if original_name and original_name not in DEFAULT_NAMES and definition.name != original_name:
            for path in (USER_LIBRARY_PATH, LEGACY_LIBRARY_PATH):
                saved = target_saved if path == target_path else self._load_path(path)
                if original_name not in saved:
                    continue
                saved.pop(original_name, None)
                path.parent.mkdir(parents=True, exist_ok=True)
                payload = {"structures": [saved[name].to_dict() for name in sorted(saved)]}
                path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                if path == target_path:
                    target_saved = saved

        target_saved[definition.name] = definition
        target_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"structures": [target_saved[name].to_dict() for name in sorted(target_saved)]}
        target_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.reload()
        return definition

    def delete(self, name: str) -> bool:
        if name in DEFAULT_NAMES:
            return False
        removed = False
        for path in (USER_LIBRARY_PATH, LEGACY_LIBRARY_PATH):
            saved = self._load_path(path)
            if name not in saved:
                continue
            saved.pop(name, None)
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"structures": [saved[item].to_dict() for item in sorted(saved)]}
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            removed = True
        if removed:
            self.reload()
        return removed

    def _custom_name(self, name: str) -> str:
        base = (name or "Customized crystal").strip()
        if base in DEFAULT_NAMES:
            base = f"{base} custom"
        candidate = base
        counter = 2
        while candidate in DEFAULT_NAMES:
            candidate = f"{base} {counter}"
            counter += 1
        return candidate

    def _refresh_legacy_cif_imports(self) -> None:
        for path in APP_DIR.glob("*.cif"):
            if path.stem not in self.definitions:
                continue
            existing = self.definitions[path.stem]
            try:
                imported = definition_from_cif(path)
            except ValueError:
                continue
            existing_group = space_group_symbol(existing.space_group)
            imported_group = space_group_symbol(imported.space_group)
            needs_refresh = not existing.repeat_boundary_atoms or (
                existing_group in {"", "P1", "1"} and imported_group not in {"", "P1", "1"}
            )
            if needs_refresh:
                imported.name = path.stem
                imported.structure_id = crystal_identity(existing)
                self.definitions[path.stem] = imported

    @staticmethod
    def _load_path(path: Path) -> dict[str, CrystalDefinition]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        structures = payload.get("structures", payload if isinstance(payload, list) else [])
        loaded: dict[str, CrystalDefinition] = {}
        for item in structures:
            try:
                definition = CrystalDefinition.from_dict(item)
                if definition.sites:
                    loaded[definition.name] = definition
            except (TypeError, ValueError):
                continue
        return loaded


class CrystalBuilder:
    def __init__(self, simulator: "SimulatorApp") -> None:
        self.simulator = simulator
        self.dialog = ui.dialog()
        self.site_rows: list[dict[str, Any]] = []
        self.site_container = None
        self.target_panel_id: int | None = None
        self.mode = "new"
        self.original_definition_name: str | None = None
        self.save_edit_button = None
        self.save_new_button = None
        self.export_cif_button = None
        self.occupancy_warning_dialog = None
        self.repeat_boundary_atoms = True
        self.imported_space_group = "P1"
        self.imported_symmetry_operations: list[str] = []
        self.formula_mode = "cell"
        self.formula_totals: dict[str, Fraction] = {}
        self.formula_groups: list[SiteOccupancyGroup] = []
        self.formula_error = ""
        self.formula_label = None
        self.formula_mode_label = None
        self.formula_timer = None
        self._loading_definition = False
        self.coordinate_mode = "fractional"
        self._build()

    def _build(self) -> None:
        with self.dialog, ui.card().classes("builder-card"):
            with ui.row().classes("items-center justify-between full-width"):
                ui.label("Customized crystal builder").classes("text-h6")
                ui.button(icon="close", on_click=self.dialog.close).props("flat round dense").tooltip("Close")

            with ui.grid(columns=3).classes("builder-grid"):
                self.name_input = ui.input("Name").props("outlined dense")
                self.system_select = ui.select(LATTICE_SYSTEMS, label="Lattice", value="cubic").props("outlined dense")
                self.symmetry_select = ui.select(
                    list(space_group_options()),
                    label="Symmetry",
                    value=space_group_option_for("P1"),
                    with_input=True,
                    new_value_mode="add-unique",
                ).props("outlined dense")
                self.scope_select = ui.select(
                    [USER_LIBRARY_SCOPE],
                    label="Save target",
                    value=USER_LIBRARY_SCOPE,
                ).props("outlined dense")
                self.a_input = ui.number("a", value=0.35, min=0.0001, step=0.001, suffix="nm").props("outlined dense")
                self.b_input = ui.number("b", value=0.35, min=0.0001, step=0.001, suffix="nm").props("outlined dense")
                self.c_input = ui.number("c", value=0.35, min=0.0001, step=0.001, suffix="nm").props("outlined dense")
                self.alpha_input = ui.number("alpha", value=90.0, min=1.0, max=179.0, step=0.5, suffix="deg").props(
                    "outlined dense"
                )
                self.beta_input = ui.number("beta", value=90.0, min=1.0, max=179.0, step=0.5, suffix="deg").props(
                    "outlined dense"
                )
                self.gamma_input = ui.number("gamma", value=90.0, min=1.0, max=179.0, step=0.5, suffix="deg").props(
                    "outlined dense"
                )

            with ui.row().classes("items-center gap-2 flex-wrap"):
                ui.button("Apply lattice constraints", icon="architecture", on_click=self.apply_lattice_constraints).props(
                    "outline"
                )
                ui.button("Add atom site", icon="add", on_click=self.add_site).props("outline")
                ui.button("Preview symmetry", icon="grain", on_click=self.preview_symmetry).props("outline")
                ui.button(
                    "Apply same color to same element",
                    icon="format_color_fill",
                    on_click=self.apply_same_color_to_same_element,
                ).props("outline")
                ui.button(
                    "Set element color to default",
                    icon="restart_alt",
                    on_click=self.set_element_colors_to_default,
                ).props("outline")

            ui.separator()
            with ui.row().classes("items-center justify-between full-width"):
                ui.label("Atom sites").classes("text-subtitle2")
                self.coordinate_select = ui.toggle({"fractional": "Fractional", "cartesian": "Cartesian (nm)"},
                    value="fractional", on_change=self.change_coordinate_mode).props("no-caps")
                self.coordinate_select.tooltip("Convert existing positions. Cartesian axes: a along x, b in the xy plane; distances in nm.")
            self.site_container = ui.column().classes("full-width gap-2")

            with ui.row().classes("builder-footer"):
                with ui.row().classes("builder-formula"):
                    self.formula_cycle_button = ui.button(icon="swap_horiz", on_click=self.cycle_formula_mode).props(
                        'flat round dense aria-label="Cycle formula representation"'
                    ).classes("formula-cycle")
                    self.formula_cycle_button.tooltip("Cycle formula representation")
                    with ui.column().classes("formula-content"):
                        self.formula_mode_label = ui.label(FORMULA_MODES[self.formula_mode]).classes("formula-mode")
                        self.formula_label = ui.html("No occupied sites").classes("formula-value")
                with ui.row().classes("builder-save-actions"):
                    self.save_edit_button = ui.button(
                        "Save edited structure",
                        icon="save",
                        on_click=self.save_edited_structure,
                    ).props("outline color=primary")
                    self.save_new_button = ui.button(
                        "Save as a new structure",
                        icon="save_as",
                        on_click=self.save_as_new_structure,
                    ).props("unelevated color=primary")
                    self.export_cif_button = ui.button(
                        "EXPORT AS CIF",
                        icon="download",
                        on_click=self.open_cif_export_dialog,
                    ).props("outline color=primary")
        for field in (self.symmetry_select, self.system_select, self.a_input, self.b_input, self.c_input,
                      self.alpha_input, self.beta_input, self.gamma_input):
            field.on_value_change(self.schedule_formula_update)

    def schedule_formula_update(self) -> None:
        if self._loading_definition:
            return
        if self.formula_timer is not None:
            self.formula_timer.deactivate()
        if core.is_loop_running():
            self.formula_timer = ui.timer(0.25, self.update_formula, once=True, immediate=False)
        else:
            self.update_formula()

    def update_formula(self) -> None:
        if self._loading_definition:
            return
        if self.formula_timer is not None:
            self.formula_timer.deactivate()
            self.formula_timer = None
        try:
            for row in self.site_rows:
                if not str(row["element"].value or "").strip():
                    raise ValueError("Incomplete atom site")
                for key in ("x", "y", "z", "occupancy"):
                    value = row[key].value
                    if value is None or not math.isfinite(float(value)):
                        raise ValueError("Incomplete atom site")
                if not 0 <= float(row["occupancy"].value) <= 1:
                    raise ValueError("Invalid occupancy")
            definition = self.read_definition()
            if not definition.symmetry_operations and space_group_export_metadata(definition.space_group)[1] is None:
                raise ValueError("Unknown symmetry")
            sites = expanded_sites(definition)
            self.formula_totals = unit_cell_composition(definition, expanded=sites)
            self.formula_groups = (site_occupancy_groups(sites)
                                   if any(site.occupancy != 1 for site in definition.sites) else [])
            self.formula_error = ""
        except (ValueError, TypeError, OverflowError):
            self.formula_totals = {}
            self.formula_groups = []
            self.formula_error = "Formula unavailable"
        self.render_formula()

    def render_formula(self) -> None:
        if self.formula_mode == "sites" and not self.formula_groups:
            self.formula_mode = "cell"
        self.formula_mode_label.set_text(FORMULA_MODES[self.formula_mode])
        if self.formula_mode == "sites":
            content = site_occupancy_formula(self.formula_groups)
        else:
            terms = formula_terms(self.formula_totals, self.formula_mode)
            content = "<wbr>".join(escape(element) + (f"<sub>{escape(amount)}</sub>" if amount else "")
                                  for element, amount in terms)
        self.formula_label.set_content(content or self.formula_error or "No occupied sites")

    def cycle_formula_mode(self) -> None:
        modes = [mode for mode in FORMULA_MODES if mode != "sites" or self.formula_groups]
        self.formula_mode = modes[(modes.index(self.formula_mode) + 1) % len(modes)]
        self.render_formula()

    def open(
        self,
        definition: CrystalDefinition | None = None,
        target_panel_id: int | None = None,
        mode: str | None = None,
    ) -> None:
        self.mode = mode or ("edit" if definition is not None else "new")
        self.target_panel_id = target_panel_id
        self.original_definition_name = definition.name if definition is not None else None
        self.load_definition(definition or self.new_definition_template())
        self.update_save_buttons()
        self.dialog.open()

    def new_definition_template(self) -> CrystalDefinition:
        return CrystalDefinition(
            name="Customized crystal",
            lattice_system="cubic",
            a=0.35,
            b=0.35,
            c=0.35,
            alpha=90.0,
            beta=90.0,
            gamma=90.0,
            space_group="P1",
            repeat_boundary_atoms=True,
            sites=[AtomicSite("Ni", 0.0, 0.0, 0.0, 1.0, "Ni", color_for_element("Ni"))],
        )

    def update_save_buttons(self) -> None:
        if self.save_edit_button is not None:
            self.save_edit_button.visible = self.mode == "edit"
            self.save_edit_button.update()
        if self.save_new_button is not None:
            self.save_new_button.visible = True
            self.save_new_button.update()
        if self.export_cif_button is not None:
            self.export_cif_button.visible = True
            self.export_cif_button.update()

    def load_definition(self, definition: CrystalDefinition) -> None:
        self._loading_definition = True
        try:
            self.name_input.value = definition.name if definition.name not in DEFAULT_NAMES else f"{definition.name} custom"
            self.system_select.value = definition.lattice_system
            symmetry_option = space_group_option_for(definition.space_group)
            self.symmetry_select.set_options(list(dict.fromkeys([*space_group_options(), symmetry_option])), value=symmetry_option)
            self.imported_space_group = space_group_symbol(definition.space_group)
            self.imported_symmetry_operations = list(definition.symmetry_operations)
            self.repeat_boundary_atoms = definition.repeat_boundary_atoms
            self.a_input.value = definition.a
            self.b_input.value = definition.b
            self.c_input.value = definition.c
            self.alpha_input.value = definition.alpha
            self.beta_input.value = definition.beta
            self.gamma_input.value = definition.gamma
            self.rebuild_site_rows([AtomicSite(**asdict(site)) for site in definition.sites])
        finally:
            self._loading_definition = False
        self.update_formula()

    def builder_lattice(self) -> np.ndarray:
        try:
            values = [float(control.value) for control in (self.a_input, self.b_input, self.c_input,
                      self.alpha_input, self.beta_input, self.gamma_input)]
        except (ValueError, TypeError) as exc:
            raise ValueError("Complete all lattice parameters before converting coordinates.") from exc
        if not all(math.isfinite(value) for value in values) or min(values[:3]) <= 0:
            raise ValueError("Lattice lengths must be positive and finite.")
        if not all(0 < value < 180 for value in values[3:]):
            raise ValueError("Lattice angles must lie between 0 and 180 degrees.")
        ca, cb, cg = np.cos(np.radians(values[3:]))
        if 1 + 2 * ca * cb * cg - ca**2 - cb**2 - cg**2 <= 1e-12:
            raise ValueError("The lattice angles must define a cell with positive volume.")
        matrix = lattice_matrix(replace(self.new_definition_template(), **dict(zip(
            ("a", "b", "c", "alpha", "beta", "gamma"), values))))
        if abs(np.linalg.det(matrix)) < 1e-12 * np.prod(values[:3]):
            raise ValueError("The unit cell must have nonzero volume.")
        return matrix

    def change_coordinate_mode(self, event: Any) -> None:
        mode = event.value
        if mode == self.coordinate_mode or self._loading_definition:
            return
        try:
            lattice = self.builder_lattice()
            positions = np.array([[float(row[key].value) for key in ("x", "y", "z")] for row in self.site_rows])
            if not np.all(np.isfinite(positions)):
                raise ValueError("Complete all atom coordinates before switching.")
            converted = positions @ lattice if mode == "cartesian" else np.linalg.solve(lattice.T, positions.T).T
        except (ValueError, TypeError, np.linalg.LinAlgError) as exc:
            self.coordinate_select.value = self.coordinate_mode
            ui.notify(f"Cannot convert coordinates: {exc}", type="warning")
            return
        self._loading_definition = True
        try:
            self.coordinate_mode = mode
            for row, point in zip(self.site_rows, converted):
                for key, value in zip(("x", "y", "z"), point):
                    row[key].value = clean_coordinate(value)
                    if mode == "cartesian":
                        row[key].props("suffix=nm")
                    else:
                        row[key].props(remove="suffix")
        finally:
            self._loading_definition = False
        self.update_formula()

    def apply_lattice_constraints(self) -> None:
        system = self.system_select.value or "triclinic"
        a = float(self.a_input.value or 0.35)
        b = float(self.b_input.value or a)
        c = float(self.c_input.value or a)
        if system == "cubic":
            self.b_input.value = a
            self.c_input.value = a
            self.alpha_input.value = self.beta_input.value = self.gamma_input.value = 90.0
        elif system == "tetragonal":
            self.b_input.value = a
            self.c_input.value = c
            self.alpha_input.value = self.beta_input.value = self.gamma_input.value = 90.0
        elif system == "orthorhombic":
            self.b_input.value = b
            self.c_input.value = c
            self.alpha_input.value = self.beta_input.value = self.gamma_input.value = 90.0
        elif system == "hexagonal":
            self.b_input.value = a
            self.alpha_input.value = 90.0
            self.beta_input.value = 90.0
            self.gamma_input.value = 120.0
        elif system == "monoclinic":
            self.alpha_input.value = 90.0
            self.gamma_input.value = 90.0

    def add_site(self) -> None:
        try:
            sites = self.read_sites_from_rows()
        except ValueError as exc:
            ui.notify(str(exc), type="warning")
            return
        sites.append(AtomicSite("Ni", 0.0, 0.0, 0.0, 1.0, ""))
        self.rebuild_site_rows(sites)

    def remove_site(self, index: int) -> None:
        try:
            sites = self.read_sites_from_rows()
        except ValueError as exc:
            ui.notify(str(exc), type="warning")
            return
        if len(sites) > 1:
            sites.pop(index)
        self.rebuild_site_rows(sites)

    def preview_symmetry(self) -> None:
        try:
            definition = self.read_definition()
            count = len(expanded_sites(definition))
        except ValueError as exc:
            ui.notify(str(exc), type="negative")
            return
        ui.notify(f"{space_group_symbol(definition.space_group)} expands to {count} atom site(s)", type="info")

    def apply_same_color_to_same_element(self) -> None:
        first_colors: dict[str, str] = {}
        repeated_elements: set[str] = set()
        updated_count = 0
        for row in self.site_rows:
            element = str(row["element"].value or "").strip().capitalize()
            if not element:
                continue
            color = str(row["color"].value or "").strip() or color_for_element(element)
            if element not in first_colors:
                first_colors[element] = color
                continue
            repeated_elements.add(element)
            if str(row["color"].value or "").strip() != first_colors[element]:
                row["color"].value = first_colors[element]
                row["color"].update()
                updated_count += 1

        if not repeated_elements:
            ui.notify("No repeated elements found", type="info")
            return
        element_list = ", ".join(sorted(repeated_elements))
        ui.notify(f"Applied first-row colors to repeated element(s): {element_list}", type="positive")
        if updated_count:
            self.simulator.set_status(f"Updated {updated_count} atom-site color(s) for: {element_list}")

    def set_element_colors_to_default(self) -> None:
        updated_count = 0
        for row in self.site_rows:
            element = str(row["element"].value or "").strip().capitalize()
            if not element:
                continue
            default_color = color_for_element(element)
            if str(row["color"].value or "").strip() != default_color:
                row["color"].value = default_color
                row["color"].update()
                updated_count += 1
        if updated_count:
            ui.notify(f"Reset {updated_count} atom-site color(s) to default", type="positive")
            self.simulator.set_status(f"Reset {updated_count} atom-site color(s) to default element colors")
        else:
            ui.notify("Element colors already match defaults", type="info")

    def rebuild_site_rows(self, sites: list[AtomicSite]) -> None:
        if self.site_container is None:
            return
        self.site_rows = []
        self.site_container.clear()
        with self.site_container:
            for index, site in enumerate(sites or [AtomicSite("Ni", 0.0, 0.0, 0.0, 1.0, "")]):
                position = site.fractional @ self.builder_lattice() if self.coordinate_mode == "cartesian" else site.fractional
                with ui.row().classes("site-row"):
                    element_options = ELEMENTS if site.element in ELEMENTS else [*ELEMENTS, site.element]
                    element = ui.select(
                        element_options,
                        label="Atom",
                        value=site.element,
                        with_input=True,
                        new_value_mode="add-unique",
                    ).props("outlined dense")
                    suffix = "nm" if self.coordinate_mode == "cartesian" else None
                    x = ui.number("x", value=clean_coordinate(position[0]), step=0.01, suffix=suffix).props("outlined dense")
                    y = ui.number("y", value=clean_coordinate(position[1]), step=0.01, suffix=suffix).props("outlined dense")
                    z = ui.number("z", value=clean_coordinate(position[2]), step=0.01, suffix=suffix).props("outlined dense")
                    occ = ui.number("Occ.", value=site.occupancy, min=0.0, max=1.0, step=0.05).props("outlined dense")
                    color = ui.color_input("Color", value=color_for_site(site), preview=True).props("outlined dense")
                    label = ui.input("Site").props("outlined dense")
                    label.value = site.label
                    remove = ui.button(icon="delete", on_click=lambda _=None, i=index: self.remove_site(i)).props(
                        "flat round dense color=negative"
                    )
                    remove.tooltip("Remove site")
                    self.site_rows.append(
                        {
                            "element": element,
                            "x": x,
                            "y": y,
                            "z": z,
                            "occupancy": occ,
                            "color": color,
                            "label": label,
                        }
                    )
                    for field in (element, x, y, z, occ):
                        field.on_value_change(self.schedule_formula_update)
        self.update_formula()

    def read_sites_from_rows(self) -> list[AtomicSite]:
        sites = []
        for row in self.site_rows:
            try:
                point = np.array([float(row[key].value) for key in ("x", "y", "z")])
            except (ValueError, TypeError) as exc:
                raise ValueError("Complete all atom coordinates before continuing.") from exc
            if not np.all(np.isfinite(point)):
                raise ValueError("Atom coordinates must be finite.")
            if self.coordinate_mode == "cartesian":
                point = np.linalg.solve(self.builder_lattice().T, point)
            element = str(row["element"].value or "X").strip().capitalize()
            sites.append(
                AtomicSite(
                    element=element,
                    x=clean_coordinate(point[0]),
                    y=clean_coordinate(point[1]),
                    z=clean_coordinate(point[2]),
                    occupancy=float(row["occupancy"].value if row["occupancy"].value is not None else 1.0),
                    label=str(row["label"].value or ""),
                    color=str(row["color"].value or ""),
                )
            )
        return sites

    def read_definition(self) -> CrystalDefinition:
        selected_group = space_group_symbol(self.symmetry_select.value)
        definition = CrystalDefinition(
            name=str(self.name_input.value or "Customized crystal").strip(),
            lattice_system=str(self.system_select.value or "triclinic").lower(),
            a=float(self.a_input.value or 0.35),
            b=float(self.b_input.value or self.a_input.value or 0.35),
            c=float(self.c_input.value or self.a_input.value or 0.35),
            alpha=float(self.alpha_input.value or 90.0),
            beta=float(self.beta_input.value or 90.0),
            gamma=float(self.gamma_input.value or 90.0),
            space_group=selected_group,
            repeat_boundary_atoms=self.repeat_boundary_atoms,
            sites=self.read_sites_from_rows(),
            symmetry_operations=(
                list(self.imported_symmetry_operations) if selected_group == self.imported_space_group else []
            ),
        )
        lattice_matrix(definition)
        if not definition.sites:
            raise ValueError("add at least one atom site")
        return definition

    def open_cif_export_dialog(self) -> None:
        self.request_structure_action(
            lambda definition: self.simulator.open_crystal_cif_export_dialog(definition=definition),
            exporting=True,
        )

    def save_edited_structure(self) -> None:
        self.request_structure_action(self._save_edited_structure)

    def save_as_new_structure(self) -> None:
        self.request_structure_action(self._save_as_new_structure)

    def request_structure_action(self, action: Callable[[CrystalDefinition], None], *, exporting: bool = False) -> None:
        if self.occupancy_warning_dialog is not None:
            return
        try:
            definition = self.read_definition()
            warnings = unbalanced_site_occupancies(definition)
        except (ValueError, TypeError, OverflowError) as exc:
            ui.notify(str(exc), type="negative")
            return
        if not warnings:
            action(definition)
            return

        dialog = self.occupancy_warning_dialog = ui.dialog().props("persistent")
        decided = False

        def finish(confirmed: bool) -> None:
            nonlocal decided
            if decided:
                return
            decided = True
            self.occupancy_warning_dialog = None
            dialog.close()
            if confirmed:
                # A follow-up export dialog must not be a child of this disappearing warning.
                with self.dialog.client:
                    action(definition)

        dialog.on("hide", dialog.delete)
        action_name = "exporting" if exporting else "saving"
        with dialog, ui.card().classes("occupancy-warning-card"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("warning", color="warning")
                ui.label("Check site occupancies").classes("text-h6")
            ui.label(f"Crystal: {definition.name}").classes("full-width break-words text-caption")
            ui.label(f"Some atomic positions have total occupancy below or above 1. Continue {action_name} with these values?")
            with ui.column().classes("occupancy-warning-list"):
                for group in warnings:
                    components = ", ".join(f"{element}: {float(amount):.12g}" for element, amount in group.components)
                    total = float(sum(amount for _, amount in group.components))
                    count = group.multiplicity
                    with ui.column().classes("full-width gap-1"):
                        ui.label(components).classes("full-width break-words")
                        ui.label(f"Total: {total:.12g} | {count} unit-cell position{'s' if count != 1 else ''}").classes(
                            "text-caption"
                        )
            with ui.row().classes("justify-end full-width gap-2"):
                ui.button("Cancel", on_click=lambda: finish(False)).props("flat")
                ui.button(f"Continue {action_name}", icon="download" if exporting else "save", on_click=lambda: finish(True)).props("unelevated")
        dialog.open()

    def _save_edited_structure(self, definition: CrystalDefinition) -> None:
        try:
            saved = self.simulator.library.save_edited(
                definition,
                self.scope_select.value or "Project local library",
                self.original_definition_name,
            )
        except ValueError as exc:
            ui.notify(str(exc), type="negative")
            return
        self.simulator.set_status(f"Saved edited structure {saved.name} to {self.scope_select.value}")
        affected_names = {saved.name}
        original_name = str(self.original_definition_name or "").strip()
        if original_name and original_name not in DEFAULT_NAMES:
            affected_names.add(original_name)
        self.simulator.refresh_library(
            saved.name,
            target_panel_id=self.target_panel_id,
            force_default_color=True,
            affected_crystal_names=affected_names,
        )
        self.simulator.refresh_crystal_list()
        self.dialog.close()

    def _save_as_new_structure(self, definition: CrystalDefinition) -> None:
        try:
            saved = self.simulator.library.save_new(definition, self.scope_select.value or "Project local library")
        except ValueError as exc:
            ui.notify(str(exc), type="negative")
            return
        self.simulator.set_status(f"Saved new structure {saved.name} to {self.scope_select.value}")
        self.simulator.refresh_panel_crystal_select_options()
        # Saves from Crystal List remain library-only; creation from the toolbar
        # or a panel opens a separate view without replacing the source panel.
        if self.mode == "new" or self.target_panel_id is not None:
            self.simulator.add_panel(crystal_name=saved.name)
        self.simulator.refresh_crystal_list()
        self.dialog.close()


class PanelViewSplitter(ui.splitter):
    """Shared, ten-percent view divider with client-side snapping while dragging."""

    def __init__(self, value, on_change, label, *, responsive=True):
        self.handle = None
        super().__init__(value=value, limits=(0, 100), on_change=on_change)
        self.classes("panel-splitter").props("emit-immediately")
        if responsive:
            self.props(':horizontal="Quasar.Screen.lt.sm"')
        with self.separator:
            self.handle = ui.element("div").classes("panel-split-handle").props(
                f'role=separator aria-label="{label}" aria-valuemin=0 aria-valuemax=100 '
                f'aria-valuenow={self.value:g} aria-orientation=vertical')
            if responsive:
                self.handle.props(':aria-orientation="Quasar.Screen.lt.sm ? \'horizontal\' : \'vertical\'"')
            self.handle.on("dblclick", lambda: self.set_value(50))
        # Quasar writes a continuous size directly during a drag. Snap that size
        # locally too, so rendering does not wait for a server round trip.
        self.on("update:model-value", js_handler=f'''value => {{
            const percent = Math.max(0, Math.min(100, Math.round(value / 10) * 10));
            const root = getElement({self.id}).$el;
            const before = root.querySelector(':scope > .q-splitter__before');
            before.style[root.classList.contains('q-splitter--horizontal') ? 'height' : 'width'] = percent + '%';
            root.classList.toggle('split-at-start', percent === 0);
            root.classList.toggle('split-at-end', percent === 100);
            root.querySelector('.panel-split-handle').setAttribute('aria-valuenow', percent);
        }}''')

    def set_value(self, value):
        if value is None or not math.isfinite(float(value)):
            return self
        return super().set_value(min(100.0, max(0.0, 10.0 * math.floor(float(value) / 10 + .5))))

    def _handle_value_change(self, value):
        super()._handle_value_change(value)
        self.classes(add="split-at-start" if value == 0 else "", remove="split-at-start" if value != 0 else "")
        self.classes(add="split-at-end" if value == 100 else "", remove="split-at-end" if value != 100 else "")
        if self.handle is not None:
            self.handle.props(f"aria-valuenow={value:g}")


class PanelController:
    def __init__(self, simulator: "SimulatorApp", state: PanelState) -> None:
        self.simulator = simulator
        self.state = state
        self.card = None
        self.scene = None
        self.atom_objects: dict[str, DisplayAtom] = {}
        self.atom_inspector = None
        self.diffraction = None
        self.crystal_select = None
        self.zone_input = None
        self.plane_input = None
        self.vector_input = None
        self.rotation_input = None
        self.download_dialog = None
        self.animation_dialog = None
        self.close_button = None
        self.magnify_button = None
        self.view_splitter = None
        self.split_handle = None
        self.coordinate_grid_enabled = False
        self.coordinate_grid_settings = CoordinateGridSettings()
        self.coordinate_grid_step = None
        self.coordinate_grid_limit = None
        self.scale_bar_line = None
        self.scale_bar_label = None
        self.scale_bar_container = None
        self.scale_timer = None
        self.current_model: CrystalModel | None = None
        self._display_model_key: tuple | None = None
        self._display_model: CrystalModel | None = None
        self.scene_signature: tuple[Any, ...] | None = None
        self._updating_inputs = False
        self._applying = False

    def build(self) -> None:
        card_classes = f"comparison-panel comparison-panel-{self.state.panel_id}"
        if self.state.magnified:
            card_classes += " panel-magnified"
        with ui.card().classes(card_classes) as self.card:
            with ui.element("div").classes("panel-toolbar"):
                ui.label(str(self.state.panel_id)).classes("panel-number")
                self.crystal_select = ui.select(
                    self.simulator.library.options(),
                    label="Crystal",
                    value=self.state.crystal_name,
                    with_input=True,
                    on_change=self.on_crystal_changed,
                ).props("outlined dense").classes("panel-crystal")
                self.zone_input = ui.input(
                    "Zone axis", value=self.state.zone_text,
                    on_change=lambda event: setattr(self.state, "zone_text", event.value),
                ).props(
                    "outlined dense"
                ).classes("panel-index panel-zone")
                self.zone_input.on("keydown.enter", self.apply_from_browser)
                self.plane_input = ui.input("Plane", value=self.state.plane_text, on_change=lambda _: self.update_annotations()).props(
                    "outlined dense"
                ).classes("panel-index panel-plane")
                self.plane_input.on("keydown.enter", self.apply_from_browser)
                self.vector_input = ui.input(
                    "Vector", value=self.state.vector_text, on_change=lambda _: self.update_annotations()
                ).props("outlined dense").classes("panel-vector")
                self.vector_input.on("keydown.enter", self.apply_from_browser)
                self.rotation_input = ui.input(
                    "Rotation", value=self.state.rotation_text,
                    on_change=lambda event: setattr(self.state, "rotation_text", event.value),
                ).props("outlined dense").classes("panel-rotation").tooltip(
                    "Use 110/45 or 110 45. Use 45, 45 ccw, or 45 cw for in-plane rotation."
                )
                self.rotation_input.on("keydown.enter", self.apply_from_browser)
                ui.button("Apply", on_click=self.apply_from_browser).props("unelevated dense").classes(
                    "panel-apply-button"
                )
                ui.button("Sync", on_click=self.sync_from_scene).props("outline dense").classes(
                    "panel-sync-button"
                ).tooltip("Sync diffraction to the current 3D crystal view")
                ui.button(
                    icon="settings", on_click=lambda: self.simulator.open_palette_dialog(self.state.panel_id),
                ).props("flat round dense").classes("panel-colors-button").tooltip("Panel settings")
                ui.button(icon="photo_camera", on_click=self.open_download_dialog).props("flat round dense").classes(
                    "panel-download-button"
                ).tooltip("Download images")
                ui.button(icon="edit", on_click=self.open_builder).props("flat round dense").classes("panel-edit-button").tooltip(
                    "Edit crystal"
                )
                self.magnify_button = ui.button(
                    icon=self.magnify_icon(),
                    on_click=self.toggle_magnified,
                ).props("flat round dense").classes("panel-magnify-button").tooltip("Magnify/shrink panel")
                self.close_button = ui.button(
                    icon="close",
                    on_click=lambda: self.simulator.remove_panel(self.state.panel_id),
                ).props("flat round dense").classes("panel-close-button").tooltip("Remove panel")

            with PanelViewSplitter(self.state.crystal_view_percent,
                                   lambda event: setattr(self.state, "crystal_view_percent", event.value),
                                   "Resize crystal and diffraction views") as self.view_splitter:
                self.split_handle = self.view_splitter.handle
                with self.view_splitter.before:
                    with ui.element("div").classes("scene-wrap"):
                        self.scene = CrystalScene(
                            width=440,
                            height=280,
                            grid=False,
                            background_color=self.state.display_settings.backgrounds.crystal,
                            camera=ui.scene.perspective_camera(fov=REAL_SCENE_FOV_DEGREES, near=0.1, far=5000),
                            on_click=self.inspect_atom, click_events=["click"],
                        ).classes("real-scene")
                        self.build_atom_inspector()
                        with ui.element("div").classes("real-scale-bar") as self.scale_bar_container:
                            self.scale_bar_line = ui.element("div").classes("real-scale-line")
                            self.scale_bar_label = ui.label("1 nm").classes("real-scale-label")
                with self.view_splitter.after:
                    self.diffraction = ui.plotly(empty_diffraction_figure()).classes("diffraction-plot")
            self.scale_timer = ui.timer(0.7, self.update_scene_scale_bar)

        self.apply(initial=True)
        self.update_close_button()
        self.update_magnify_button()

    def build_atom_inspector(self) -> None:
        with ui.column().classes("atom-inspector") as self.atom_inspector:
            with ui.row().classes("items-start no-wrap full-width gap-1"):
                self.atom_title = ui.label("").classes("text-weight-bold flex-1 min-w-0 break-words")
                ui.button(icon="close", on_click=self.hide_atom_inspector).props("flat round dense size=sm aria-label='Close atom position'").tooltip("Close atom position")
            ui.label("Fractional (a, b, c)").classes("atom-coordinate-caption")
            self.atom_fractional = ui.label("").classes("atom-coordinate-value")
            ui.label("Cartesian (nm)").classes("atom-coordinate-caption")
            self.atom_cartesian = ui.label("").classes("atom-coordinate-value")
        self.atom_inspector.set_visibility(False)

    def set_view_split(self, value: float) -> None:
        if self.view_splitter is not None:
            self.view_splitter.set_value(value)

    def hide_atom_inspector(self) -> None:
        if self.atom_inspector is not None:
            self.atom_inspector.set_visibility(False)

    def inspect_atom(self, event) -> None:
        if event.button != 0 or self.atom_inspector is None or self.current_model is None:
            return
        atom = self.atom_at_click(event)
        if atom is None:
            self.hide_atom_inspector()
            return
        model = self.current_model
        offset = atom.position - model.display_origin
        fractional = np.linalg.solve(model.display_lattice.T, offset)
        cartesian = offset * model.scale_nm
        title = atom.element + (f" ({atom.label})" if atom.label else "")
        self.atom_title.set_text(title)
        self.atom_fractional.set_text(point_text(fractional))
        self.atom_cartesian.set_text(point_text(cartesian))
        self.atom_inspector.set_visibility(True)

    def atom_at_click(self, event) -> DisplayAtom | None:
        if event.button != 0:
            return None
        # Hits are nearest-first. Ignore frame lines and translucent annotation surfaces.
        return next((self.atom_objects[hit.object_id] for hit in event.hits if hit.object_id in self.atom_objects), None)

    def magnify_icon(self) -> str:
        return "close_fullscreen" if self.state.magnified else "open_in_full"

    def update_magnify_button(self) -> None:
        if self.magnify_button is None:
            return
        self.magnify_button.props(f"icon={self.magnify_icon()}")
        self.magnify_button.update()

    def toggle_magnified(self) -> None:
        self.state.magnified = not self.state.magnified
        if self.card is not None:
            if self.state.magnified:
                self.card.classes(add="panel-magnified")
            else:
                self.card.classes(remove="panel-magnified")
        self.update_magnify_button()
        self.resize_scene_after_layout()

    def resize_scene_after_layout(self) -> None:
        if self.scene is None or not core.is_loop_running():
            return
        ui.run_javascript(
            f"""
            const resizeCrystalScene = () => getElement({self.scene.id})?.resize?.();
            requestAnimationFrame(() => {{
                resizeCrystalScene();
                setTimeout(resizeCrystalScene, 120);
            }});
            """
        )

    def update_close_button(self) -> None:
        if self.close_button is None:
            return
        self.close_button.visible = len(self.simulator.panel_states) > 1
        self.close_button.update()

    def on_crystal_changed(self) -> None:
        if self.crystal_select.value == CUSTOM_SENTINEL:
            self.crystal_select.value = self.state.crystal_name
            self.crystal_select.update()
            self.open_builder()
            return
        if self.crystal_select.value == self.state.crystal_name:
            return
        self.simulator.set_panel_crystal(self.state, self.crystal_select.value)
        self.state.plane_text = ""
        self.state.vector_text = ""
        self.state.zone_text = ""
        self.state.rotation_text = ""
        zone_text = "100" if self.state.crystal_name in DEFAULT_NAMES else self.state.applied_zone_text or "001"
        model = self.simulator.model_for(self.state.crystal_name)
        zone, _ = parse_indices(zone_text, model, "direction", allow_multiple=False)
        if zone:
            self.state.view_vector = zone[0].vector
            self.state.roll = 0.0
            self.state.applied_zone_text = zone_text
        self.simulator.apply_default_saved_view(self.state)
        self._updating_inputs = True
        if self.plane_input is not None:
            self.plane_input.value = self.state.plane_text
        if self.vector_input is not None:
            self.vector_input.value = self.state.vector_text
        self.zone_input.value = ""
        self.rotation_input.value = ""
        self._updating_inputs = False
        self.set_view_split(self.state.crystal_view_percent)
        self.redraw_scene(model)
        self.redraw_diffraction(model)
        self.simulator.refresh_combo_panels_for_sources({self.state.panel_id})

    def open_builder(self) -> None:
        self.simulator.builder.open(
            self.simulator.library.get(self.state.crystal_name),
            target_panel_id=self.state.panel_id,
            mode="edit",
        )

    def display_model(self, source: CrystalModel | None = None, *, settings: PanelDisplaySettings | None = None,
                      element_colors: dict[str, str] | None = None) -> CrystalModel:
        source = source or self.simulator.model_for(self.state.crystal_name)
        source = source.display_source or source
        if settings is None:
            settings = self.state.display_settings
            count = math.prod(abs(n) for n in settings.cells)
            if count > 1 and len(source.display_atoms) * count > 30000:
                settings = replace(settings, cells=(1, 1, 1))
                self.state.display_settings = settings
                self.state.global_display_sections.discard("cells")
                self.simulator.set_status(f"Panel {self.state.panel_id}: displayed cells reset to one; replication would exceed 30,000 atoms")
        colors = display_element_colors(source, settings, self.effective_element_colors() if element_colors is None else element_colors)
        key = (id(source), crystal_model_key(source), json.dumps(asdict(crystal_display_settings(settings)), sort_keys=True), tuple(sorted(colors.items())))
        if key != self._display_model_key:
            self._display_model = make_panel_display_model(source, settings, colors)
            self._display_model_key = key
        return self._display_model

    def effective_element_colors(self) -> dict[str, str]:
        return (getattr(self.simulator, "element_colors", {}) if self.state.element_colors is None
                else self.state.element_colors)

    def annotation_visible(self, kind: str) -> bool:
        if kind in self.state.annotation_visibility:
            return self.state.annotation_visibility[kind]
        return getattr(self.simulator, SAVED_VISIBILITY_METHODS[kind])()

    async def capture_camera_pose(self) -> dict | None:
        if self.scene is None:
            return None
        try:
            pose = await ui.run_javascript(f"""
                const scene = getElement({self.scene.id});
                if (!scene?.camera || !scene.controls) return null;
                return {{position:scene.camera.position.toArray(), target:scene.controls.target.toArray(),
                         up:scene.camera.up.toArray(), zoom:scene.camera.zoom}};
            """, timeout=3)
            return validated_saved_camera(pose)
        except (TimeoutError, RuntimeError):
            return None

    def restore_camera_pose(self, pose: dict, model: CrystalModel) -> None:
        position, up, target = (pose[key] for key in ("position", "up", "target"))
        self.scene.move_camera(x=position[0], y=position[1], z=position[2],
            look_at_x=target[0], look_at_y=target[1], look_at_z=target[2],
            up_x=up[0], up_y=up[1], up_z=up[2], duration=0)
        script = f"""
            const scene = getElement({self.scene.id});
            if (scene?.camera && scene.controls) {{
                scene.camera_tween?.stop();
                scene.camera.position.fromArray({json.dumps(position)});
                scene.camera.up.fromArray({json.dumps(up)});
                scene.controls.target.fromArray({json.dumps(target)});
                scene.camera.zoom = {pose['zoom']};
                scene.camera.far = {max(5000, float(np.linalg.norm(position)) + model.limit * 3)};
                scene.controls.update(); scene.camera.updateProjectionMatrix(); scene.resize();
            }}
        """
        self.scene.on("init", js_handler=f"() => {{{script}}}")
        self.scene.client.run_javascript(script)

    def render_crystal_png(
        self,
        dpi: float,
        transparent_background: bool = False,
        view_vector: np.ndarray | None = None,
        roll: float | None = None,
        frame_size: tuple[int, int] | None = None,
        fixed_extent: float | None = None,
        shaded_atoms: bool = False,
        atom_shading: str | None = None,
        occupancy_colors: str = "panel",
    ) -> bytes:
        atom_shading = atom_shading if atom_shading is not None else ("strong" if shaded_atoms else "none")
        if occupancy_colors == "panel":
            occupancy_colors = self.state.display_settings.occupancy_colors
        if atom_shading not in ATOM_SHADING_OPTIONS or occupancy_colors not in OCCUPANCY_COLOR_OPTIONS:
            raise ValueError("Unknown atom shading or occupancy color style.")
        import matplotlib

        matplotlib.use("Agg", force=True)
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from matplotlib.patches import ArrowStyle
        from matplotlib.path import Path as MplPath
        from matplotlib.transforms import Affine2D

        model = self.display_model(self.current_model or self.simulator.model_for(self.state.crystal_name))
        view = normalize_vector(view_vector if view_vector is not None else self.state.view_vector)
        if view is None:
            view = np.array([1.0, 0.0, 0.0])
        u_axis, v_axis = projection_basis(view, self.state.roll if roll is None else float(roll))

        def project(point: np.ndarray) -> tuple[float, float]:
            return float(np.dot(point, u_axis)), float(np.dot(point, v_axis))

        def project_many(points: np.ndarray) -> np.ndarray:
            return np.array([[float(np.dot(point, u_axis)), float(np.dot(point, v_axis))] for point in points], dtype=float)

        planes, _plane_errors = parse_indices(self.state.plane_text, model, "plane", allow_multiple=True)
        vectors, _vector_errors = parse_indices(
            self.state.vector_text,
            model,
            "direction",
            allow_multiple=True,
            allow_reciprocal=True,
        )

        visible_points: list[np.ndarray] = []
        visible_points.extend(point for edge in (model.bounds_edges if model.bounds_edges is not None else model.display_edges) for point in edge)
        visible_points.extend(atom.position for atom in model.display_atoms)
        plane_polygons: list[tuple[ParsedIndex, np.ndarray]] = []
        for plane in planes:
            polygon = clipped_plane_polygon(model, plane)
            if polygon is not None:
                plane_polygons.append((plane, polygon))
                visible_points.extend(polygon)

        vector_segments: list[tuple[ParsedIndex, np.ndarray, np.ndarray]] = []
        for vector in vectors:
            if vector.is_reciprocal:
                start, end = reciprocal_segment_for_display(vector.values, model)
            else:
                start, end = direction_segment_for_display(vector.values, model)
            vector_segments.append((vector, start, end))
            visible_points.extend([start, end])

        projected_points = project_many(np.array(visible_points, dtype=float)) if visible_points else np.zeros((1, 2))
        min_x, min_y = np.min(projected_points, axis=0)
        max_x, max_y = np.max(projected_points, axis=0)
        center_x = 0.5 * (min_x + max_x)
        center_y = 0.5 * (min_y + max_y)
        width = max(max_x - min_x, 1e-6)
        height = max(max_y - min_y, 1e-6)
        figure_aspect = 1.28
        if width / height < figure_aspect:
            width = height * figure_aspect
        else:
            height = width / figure_aspect
        width *= 1.34
        height *= 1.34
        if fixed_extent is not None:
            center_x = center_y = 0.0
            height = float(fixed_extent)
            width = height * (frame_size[0] / frame_size[1] if frame_size else figure_aspect)

        dpi = min(max(float(dpi or 300), 72.0), 1200.0)
        background_color = (0.0, 0.0, 0.0, 0.0) if transparent_background else self.state.display_settings.backgrounds.crystal
        figsize = (frame_size[0] / dpi, frame_size[1] / dpi) if frame_size else (4.6, 3.6)
        fig = Figure(figsize=figsize, dpi=dpi, facecolor=background_color)
        FigureCanvasAgg(fig)
        ax = fig.add_axes([0, 0, 1, 1], facecolor="none")
        ax.set_aspect("equal", adjustable="box")
        ax.set_axis_off()
        ax.set_xlim(center_x - width / 2.0, center_x + width / 2.0)
        ax.set_ylim(center_y - height / 2.0, center_y + height / 2.0)
        fig.canvas.draw()
        pixel_width, pixel_height = fig.canvas.get_width_height()
        units_per_pixel = 1.0 / float(ax.transData.transform((1, 0))[0] - ax.transData.transform((0, 0))[0])
        camera_basis = np.column_stack((u_axis, v_axis, view))

        def screen_points(points: np.ndarray) -> np.ndarray:
            camera_points = np.asarray(points) @ camera_basis
            return np.column_stack((ax.transData.transform(camera_points[:, :2]), camera_points[:, 2]))

        layers: list[CrystalExportLayer] = []

        def add_line(start: np.ndarray, end: np.ndarray, color: tuple[float, ...], linewidth: float) -> None:
            layers.append(CrystalExportLayer(
                MplPath([start[:2], end[:2]]), crystal_segment_depth(start, end),
                edge_color=color, linewidth=linewidth,
            ))

        plane_palette = self.simulator.plane_palette(self.state.panel_id)
        vector_palette = self.simulator.vector_palette(self.state.panel_id)
        settings = self.state.display_settings
        for index, (_plane, polygon) in enumerate(plane_polygons):
            rgb = color_to_rgb(plane_palette[index % len(plane_palette)])
            points = screen_points(polygon)
            normal = np.cross(points[1] - points[0], points[2] - points[0])
            if abs(float(normal[2])) > 1e-8:
                equation = np.array([-normal[0], -normal[1], np.dot(normal, points[0])]) / normal[2]
                layers.append(CrystalExportLayer(
                    MplPath(np.vstack((points[:, :2], points[0, :2])), closed=True),
                    lambda x, y, eq=equation: eq[0] * x + eq[1] * y + eq[2],
                    face_color=(*rgb, settings.plane_opacity),
                ))
            for start, end in zip(points, np.roll(points, -1, axis=0)):
                add_line(start, end, (*rgb, settings.plane_edge_opacity), 1.1)

        for start, end in model.display_edges:
            points = screen_points(np.array([start, end]))
            add_line(points[0], points[1], (*color_to_rgb(settings.frame_color), settings.frame_opacity), 1.25 * settings.frame_width)

        atom_edge_rgb = (0.0, 0.0, 0.0) if transparent_background else color_to_rgb(self.state.display_settings.backgrounds.crystal)
        for atom in model.visible_display_atoms():
            center = screen_points(np.array([atom.position]))[0]
            radius_factor = model.atom_radius_scale * occupancy_radius_factor(atom.occupancy) * atom.radius_multiplier / model.display_extent_scale
            radius = 0.5 * math.sqrt(CRYSTAL_EXPORT_ATOM_MARKER_SIZE) * radius_factor * dpi / 72.0
            opacity = 0.58 + 0.42 * atom.occupancy

            def atom_depth(x: np.ndarray, y: np.ndarray, center=center, radius=radius) -> np.ndarray:
                distance_squared = (x - center[0]) ** 2 + (y - center[1]) ** 2
                return center[2] + np.sqrt(np.maximum(radius ** 2 - distance_squared, 0.0)) * units_per_pixel

            path = MplPath.unit_circle().transformed(Affine2D().scale(radius).translate(*center[:2]))
            components = atom.components if occupancy_colors == "sectors" else ()
            use_shader = atom_shading != "none" or bool(components)
            layers.append(CrystalExportLayer(
                path,
                atom_depth, face_color=(*color_to_rgb(color_for_site(atom)), opacity),
                edge_color=(*atom_edge_rgb, opacity), linewidth=0.0 if use_shader else 0.4,
                color_at=crystal_atom_shader(center, radius, color_to_rgb(color_for_site(atom)),
                                             atom_shading, components) if use_shader else None,
            ))
            if use_shader:
                layers.append(CrystalExportLayer(path, atom_depth, edge_color=(*atom_edge_rgb, opacity), linewidth=0.4))

        for index, (vector, start, end) in enumerate(vector_segments):
            color = vector_palette[index % len(vector_palette)]
            x0, y0 = project(start)
            x1, y1 = project(end)
            points = screen_points(np.array([start, end]))
            paths, filled = ArrowStyle("-|>")(MplPath(points[:, :2]), 18.0 * dpi / 72.0, 2.4 * dpi / 72.0)
            # The shaft has thickness, so a vector lying in a plane is just in front of its surface.
            depth_at = crystal_segment_depth(points[0], points[1], 1.2 * dpi / 72.0 * units_per_pixel)
            opacity = settings.reciprocal_opacity if vector.is_reciprocal else settings.vector_opacity
            rgba = (*color_to_rgb(color), opacity)
            for path, fill in zip(paths, filled):
                layers.append(CrystalExportLayer(
                    path, depth_at, face_color=rgba if fill else None,
                    edge_color=rgba, linewidth=2.4, dashed=vector.is_reciprocal and not fill,
                ))
            if self.annotation_visible("crystal") and settings.vector_label_opacity > 0:
                ax.text(
                    x1 + 0.025 * width,
                    y1 + 0.025 * height,
                    vector.label,
                    color=crystal_text_color(settings, color),
                    alpha=settings.vector_label_opacity,
                    fontsize=9 * settings.vector_label_scale,
                    weight="bold",
                    ha="left",
                    va="center",
                    zorder=6,
                )

        for marker in marker_geometry(settings.markers, model):
            rgb = color_to_rgb(marker["color"])
            rgba = (*rgb, marker["opacity"])
            linewidth = marker["width"] / units_per_pixel * 72 / dpi
            for start, end in marker["segments"]:
                points = screen_points(np.array([start, end]))
                add_line(points[0], points[1], rgba, linewidth)
            for dot in marker["dots"]:
                center = screen_points(np.array([dot]))[0]
                radius = marker["width"] / (2 * units_per_pixel)
                path = MplPath.unit_circle().transformed(Affine2D().scale(radius).translate(*center[:2]))

                def dot_depth(x, y, center=center, radius=radius):
                    return center[2] + np.sqrt(np.maximum(radius ** 2 - (x-center[0])**2 - (y-center[1])**2, 0)) * units_per_pixel

                layers.append(CrystalExportLayer(path, dot_depth, face_color=rgba))
            points = screen_points(np.array(marker["points"]))
            if marker["fill_opacity"] > 0:
                for face in marker["faces"]:
                    corners = points[list(face)]
                    _, _, axes = np.linalg.svd(corners - corners.mean(axis=0), full_matrices=False)
                    normal = axes[-1]
                    if abs(float(normal[2])) > 1e-8:
                        equation = np.array([-normal[0], -normal[1], np.dot(normal, corners[0])]) / normal[2]
                        layers.append(CrystalExportLayer(
                            MplPath(np.vstack((corners[:, :2], corners[0, :2])), closed=True),
                            lambda x, y, eq=equation: eq[0] * x + eq[1] * y + eq[2],
                            face_color=(*rgb, marker["fill_opacity"])))
            for head in marker["arrowheads"]:
                base, tip = screen_points(np.array([head["base"], head["tip"]]))
                delta = tip[:2] - base[:2]
                radius = head["radius"] / units_per_pixel
                length = np.linalg.norm(delta)
                if length > 1e-8:
                    side = np.array([-delta[1], delta[0]]) * radius / length
                    path = MplPath(np.array([tip[:2], base[:2] + side, base[:2] - side, tip[:2]]), closed=True)
                else:
                    path = MplPath.unit_circle().transformed(Affine2D().scale(radius).translate(*base[:2]))
                layers.append(CrystalExportLayer(path, crystal_segment_depth(base, tip), face_color=rgba))
            if marker["kind"] == "point" and not marker["hide_atom"]:
                center = points[0]
                radius = (0.5 * math.sqrt(CRYSTAL_EXPORT_ATOM_MARKER_SIZE) * marker["radius"]
                          / REAL_SCENE_ATOM_RADIUS / model.display_extent_scale * dpi / 72.0)
                path = MplPath.unit_circle().transformed(Affine2D().scale(radius).translate(*center[:2]))
                if marker["point_style"] == "ring":
                    layers.append(CrystalExportLayer(path, lambda x, y, z=center[2]: z,
                                                    edge_color=rgba, linewidth=linewidth))
                else:
                    def marker_depth(x, y, center=center, radius=radius):
                        return center[2] + np.sqrt(np.maximum(radius ** 2 - (x-center[0])**2 - (y-center[1])**2, 0)) * units_per_pixel
                    use_shader = atom_shading != "none"
                    edge = (*atom_edge_rgb, marker["opacity"])
                    layers.append(CrystalExportLayer(path, marker_depth, face_color=rgba,
                        edge_color=edge, linewidth=0 if use_shader else .4,
                        color_at=crystal_atom_shader(center, radius, rgb, atom_shading) if use_shader else None))
                    if use_shader:
                        layers.append(CrystalExportLayer(path, marker_depth, edge_color=edge, linewidth=.4))
            if marker["label"] and self.annotation_visible("crystal"):
                x, y = project(np.mean(marker["points"], axis=0))
                dx, dy = marker["label_direction"]
                gap = marker["label_gap"] * 9 / 13
                ax.annotate(marker["label"], (x, y), xytext=(dx * gap, dy * gap), textcoords="offset points",
                    color=crystal_text_color(settings, marker["label_color"]), alpha=marker["label_opacity"], fontsize=9 * marker["label_size"] / 13,
                    ha="left" if dx > 0 else "right" if dx < 0 else "center",
                    va="bottom" if dy > 0 else "top" if dy < 0 else "center", zorder=6, parse_math=False)

        pixels = composite_crystal_export(layers, pixel_width, pixel_height, dpi)
        fig.figimage(pixels, origin="upper", zorder=-1)

        if self.annotation_visible("crystal") and settings.plane_label_opacity > 0:
            for index, (plane, polygon) in enumerate(plane_polygons):
                color = plane_palette[index % len(plane_palette)]
                x, y = project(np.mean(polygon, axis=0))
                ax.text(x, y, plane.label, color=crystal_text_color(settings, color), alpha=settings.plane_label_opacity,
                        fontsize=9 * settings.plane_label_scale, weight="bold", ha="center", va="center", zorder=6)

        if self.annotation_visible("scale") and settings.annotations.real_scale_visible:
            style = display_annotations(settings).real_scale
            right, top = "right" in style.position, "top" in style.position
            visible_nm = max(width * model.scale_nm, 1e-9)
            bar_nm = choose_scale_bar(visible_nm)
            bar_display = bar_nm / max(model.scale_nm, 1e-9)
            x0 = center_x + (0.43 * width - bar_display if right else -0.43 * width)
            y0 = center_y + (0.40 if top else -0.40) * height
            if not top:
                text_height = style.font_size * .75 * dpi / 72 * units_per_pixel * 1.3
                y0 = max(y0, center_y - height / 2 + .065 * height + text_height)
            ax.plot([x0, x0 + bar_display], [y0, y0], color=style.color, alpha=style.opacity, linewidth=2.4, zorder=10)
            ax.text(
                x0 + bar_display if right else x0,
                y0 - 0.035 * height,
                f"{bar_nm:g} nm",
                color=style.color,
                alpha=style.opacity,
                fontsize=style.font_size * .75,
                weight="bold",
                ha="right" if right else "left",
                va="top",
                zorder=10,
            )

        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", dpi=dpi, facecolor=background_color, transparent=transparent_background)
        return buffer.getvalue()

    async def live_scene_orientation(self) -> tuple[np.ndarray | None, float | None]:
        if self.scene is None:
            return None, None
        try:
            camera = await self.scene.get_camera()
        except Exception:
            return None, None
        position = camera.get("position", {})
        up = camera.get("up", {})
        view = normalize_vector(
            np.array(
                [
                    float(position.get("x", 1.0)),
                    float(position.get("y", 0.0)),
                    float(position.get("z", 0.0)),
                ],
                dtype=float,
            )
        )
        up_vector = normalize_vector(
            np.array(
                [
                    float(up.get("x", 0.0)),
                    float(up.get("y", 0.0)),
                    float(up.get("z", 1.0)),
                ],
                dtype=float,
            )
        )
        if view is None:
            return None, None
        roll = roll_from_view_and_up(view, up_vector if up_vector is not None else np.array([0.0, 0.0, 1.0]), self.state.roll)
        return view, roll

    def open_download_dialog(self) -> None:
        self.download_editor = StaticDownloadDialog(self)
        self.download_dialog = self.download_editor.dialog
        self.download_editor.open()

    async def render_crystal_image(
        self, dpi: float, transparent: bool = False, renderer: str = "three",
        atom_shading: str = "mild", occupancy_colors: str = "panel", shaded_atoms: bool = False,
    ) -> bytes:
        from CrysDiS_animation import RENDER_LOCK, render_static_three_png

        view, roll = await self.live_scene_orientation()
        if renderer == "three":
            return await render_static_three_png(
                sys.modules[__name__], self, dpi, transparent, view, roll,
                atom_shading=atom_shading, occupancy_colors=occupancy_colors)

        def render() -> bytes:
            with RENDER_LOCK:
                return self.render_crystal_png(
                    dpi, transparent_background=transparent, view_vector=view, roll=roll,
                    shaded_atoms=shaded_atoms, atom_shading=atom_shading, occupancy_colors=occupancy_colors)

        return await asyncio.to_thread(render)

    async def open_animation_dialog(self) -> None:
        from CrysDiS_animation import AnimationDialog

        if self.download_dialog is not None:
            self.download_dialog.close()
        if self.animation_dialog is None:
            self.animation_dialog = AnimationDialog(self, sys.modules[__name__])
        await self.animation_dialog.open()

    async def download_images(
        self,
        include_crystal: bool,
        include_diffraction: bool,
        dpi: float,
        transparent_background: bool = False,
        crystal_filename_base: str | None = None,
        diffraction_filename_base: str | None = None,
        include_suffixes: bool = True,
        crystal_renderer: str = "three",
        shaded_atoms: bool = False,
        atom_shading: str | None = None,
        occupancy_colors: str = "panel",
    ) -> None:
        if not include_crystal and not include_diffraction:
            ui.notify("Choose at least one image to download", type="warning")
            return
        dpi = min(max(float(dpi or 300), 72.0), 1200.0)
        direct_export = self.simulator.direct_file_exports_enabled()
        saved_paths: list[Path] = []
        crystal_downloaded = False
        crystal_filename = export_image_filename(
            crystal_filename_base,
            f"panel_{self.state.panel_id}_crystal",
            dpi,
            transparent_background,
            include_suffixes=include_suffixes,
        )
        diffraction_filename = export_image_filename(
            diffraction_filename_base,
            f"panel_{self.state.panel_id}_diffraction",
            dpi,
            transparent_background,
            include_suffixes=include_suffixes,
        )
        if include_crystal:
            try:
                shading = atom_shading or ("strong" if shaded_atoms else "mild")
                image_bytes = await self.render_crystal_image(
                    dpi, transparent_background, crystal_renderer, shading, occupancy_colors, shaded_atoms)
                if direct_export:
                    saved_paths.append(self.simulator.save_exported_image(image_bytes, crystal_filename))
                else:
                    ui.download(image_bytes, crystal_filename, media_type="image/png")
                crystal_downloaded = True
            except Exception as exc:
                ui.notify(f"Crystal export failed: {exc}", type="negative")
                if not include_diffraction:
                    return
        if not include_diffraction:
            if self.download_dialog is not None:
                self.download_dialog.close()
            if direct_export:
                self.simulator.announce_saved_exports(saved_paths)
            else:
                self.simulator.set_status(f"Panel {self.state.panel_id}: downloaded image export")
            return

        selector = f".comparison-panel-{self.state.panel_id}"
        script = f"""
        const root = document.querySelector({json.dumps(selector)});
        const dpi = {float(dpi):.6f};
        const scale = Math.max(1, dpi / 150);
        const transparentBackground = {json.dumps(bool(transparent_background))};
        const directExport = {json.dumps(bool(direct_export))};
        const filename = {json.dumps(diffraction_filename)};

        function saveDataUrl(dataUrl, filename) {{
            const link = document.createElement('a');
            link.href = dataUrl;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            link.remove();
        }}

        async function downloadDiffraction() {{
            const plot = root?.querySelector('.diffraction-plot.js-plotly-plot') || root?.querySelector('.diffraction-plot .js-plotly-plot');
            if (!plot || !window.Plotly) return false;
            const rect = plot.getBoundingClientRect();
            const originalPaper = plot.layout?.paper_bgcolor;
            const originalPlot = plot.layout?.plot_bgcolor;
            if (transparentBackground) {{
                await window.Plotly.relayout(plot, {{
                    paper_bgcolor: 'rgba(0,0,0,0)',
                    plot_bgcolor: 'rgba(0,0,0,0)',
                }});
            }}
            let dataUrl;
            try {{
                dataUrl = await window.Plotly.toImage(plot, {{
                    format: 'png',
                    width: Math.round(rect.width > 1 ? rect.width : (plot._fullLayout?.width || 440)),
                    height: Math.round(rect.height > 1 ? rect.height : (plot._fullLayout?.height || 280)),
                    scale,
                }});
            }} finally {{
                if (transparentBackground) {{
                    await window.Plotly.relayout(plot, {{
                        paper_bgcolor: originalPaper || '#000000',
                        plot_bgcolor: originalPlot || '#000000',
                    }});
                }}
            }}
            if (directExport) {{
                return {{filename, dataUrl}};
            }}
            saveDataUrl(dataUrl, filename);
            return {{downloaded: true}};
        }}

        return await downloadDiffraction();
        """
        try:
            result = await ui.run_javascript(script, timeout=20.0)
        except Exception as exc:
            ui.notify(f"Download failed: {exc}", type="negative")
            return
        diffraction_downloaded = False
        if direct_export:
            if isinstance(result, dict) and result.get("dataUrl") and result.get("filename"):
                try:
                    image_bytes = decode_png_data_url(str(result["dataUrl"]))
                    saved_paths.append(self.simulator.save_exported_image(image_bytes, str(result["filename"])))
                except Exception as exc:
                    ui.notify(f"Diffraction export failed: {exc}", type="negative")
                    if not saved_paths:
                        return
            elif not saved_paths:
                ui.notify("Could not capture the selected image", type="warning")
                return
            else:
                ui.notify("Could not capture the selected image", type="warning")
        else:
            diffraction_downloaded = bool(result and (result is True or (isinstance(result, dict) and result.get("downloaded"))))

        if saved_paths or diffraction_downloaded or crystal_downloaded:
            if self.download_dialog is not None:
                self.download_dialog.close()
            if direct_export:
                self.simulator.announce_saved_exports(saved_paths)
            else:
                self.simulator.set_status(f"Panel {self.state.panel_id}: downloaded image export")
        else:
            ui.notify("Could not capture the selected image", type="warning")

    async def apply_from_browser(self) -> None:
        if self._applying:
            return
        self._applying = True
        try:
            await self.read_browser_inputs_and_apply()
        finally:
            self._applying = False

    async def read_browser_inputs_and_apply(self) -> None:
        rotation_text = self.rotation_input.value if self.rotation_input is not None else self.state.rotation_text
        selector = f".comparison-panel-{self.state.panel_id}"
        try:
            values = await ui.run_javascript(
                f"""
                const root = document.querySelector({json.dumps(selector)});
                const fields = root ? [...root.querySelectorAll('.panel-index input')] : [];
                return {{
                    zone: fields[0]?.value ?? '',
                    plane: fields[1]?.value ?? '',
                    vector: root?.querySelector('.panel-vector input')?.value ?? '',
                    rotation: root?.querySelector('.panel-rotation input')?.value ?? '',
                }};
                """
            )
        except Exception:
            values = None
        if isinstance(values, dict):
            self._updating_inputs = True
            try:
                for name, field in (("zone", self.zone_input), ("plane", self.plane_input), ("vector", self.vector_input)):
                    if field is not None:
                        field.value = str(values.get(name, field.value or ""))
                rotation_text = str(values.get("rotation", rotation_text or ""))
            finally:
                self._updating_inputs = False
        self.apply(rotation_text_override=rotation_text)

    async def sync_from_scene(self) -> None:
        if self.scene is None:
            return
        old_view = self.state.view_vector.copy()
        old_roll = float(self.state.roll)
        unit, roll = await self.live_scene_orientation()
        if unit is None:
            ui.notify("Could not read the 3D camera direction", type="warning")
            return
        self.state.view_vector = unit
        if roll is not None:
            self.state.roll = roll
        self.redraw_diffraction()
        self.simulator.propagate_bound_motion(self.state.panel_id, old_view, old_roll, self.state.view_vector, self.state.roll)
        self.simulator.set_status(f"Panel {self.state.panel_id}: diffraction synced to current 3D view")

    def update_annotations(self, *, redraw: bool = True) -> list[str]:
        if self._updating_inputs:
            return []
        model = self.simulator.model_for(self.state.crystal_name)
        errors: list[str] = []
        changed = False
        for field, attribute, kind in (
            (self.plane_input, "plane_text", "plane"),
            (self.vector_input, "vector_text", "direction"),
        ):
            text = str(field.value or "") if field is not None else getattr(self.state, attribute)
            _, field_errors = parse_indices(text, model, kind, allow_multiple=True, allow_reciprocal=kind == "direction")
            errors.extend(field_errors)
            if not field_errors and text != getattr(self.state, attribute):
                setattr(self.state, attribute, text)
                changed = True
        if changed and redraw:
            self.redraw_scene(model, update_camera=False)
        return errors

    def apply(self, initial: bool = False, rotation_text_override: str | None = None) -> None:
        model = self.simulator.model_for(self.state.crystal_name)
        if initial:
            self.redraw_scene(model)
            self.redraw_diffraction(model)
            return

        zone_text = str(self.zone_input.value if self.zone_input is not None else self.state.zone_text).strip()
        rotation_text = str(
            rotation_text_override if rotation_text_override is not None else
            self.rotation_input.value if self.rotation_input is not None else self.state.rotation_text
        ).strip()
        zone, zone_errors = parse_indices(zone_text, model, "direction", allow_multiple=False)
        rotation_command, rotation_errors = parse_rotation_command(rotation_text, model)
        # Validate both commands before changing orientation or consuming either input.
        if zone_text and (
            zone_errors or len(zone) != 1 or len(split_index_groups(zone_text, allow_multiple=True)) != 1
            or re.search(r"[^0-9+\-\s,;()\[\]{}<>]", normalize_text(zone_text))
        ):
            return
        if rotation_text and (rotation_errors or rotation_command is None):
            return

        old_view = self.state.view_vector.copy()
        old_roll = float(self.state.roll)
        new_view, new_roll = old_view.copy(), old_roll
        if zone:
            new_view = zone[0].vector
            if self.simulator.always_snap_back_view():
                new_roll = 0.0
        message = f"Panel {self.state.panel_id} updated"
        if rotation_command is not None:
            axis = rotation_command.axis
            if axis is None:
                axis = normalize_vector(new_view)
            if axis is None:
                return
            new_view, new_roll = rotate_orientation(new_view, new_roll, axis, rotation_command.angle_degrees)
            message = f"Panel {self.state.panel_id}: rotated {rotation_command.angle_degrees:g} deg about {rotation_command.axis_label}"
        elif not zone and self.simulator.always_snap_back_view() and self.state.applied_zone_text:
            previous_zone, _ = parse_indices(self.state.applied_zone_text, model, "direction", allow_multiple=False)
            if previous_zone:
                new_view, new_roll = previous_zone[0].vector, 0.0
                message = f"Panel {self.state.panel_id}: snapped back to {previous_zone[0].label}"
        if not np.all(np.isfinite(new_view)) or not math.isfinite(new_roll):
            return
        self.state.view_vector, self.state.roll = new_view, new_roll
        if zone:
            self.state.applied_zone_text = zone_text
        self.state.zone_text = self.state.rotation_text = ""
        if self.zone_input is not None:
            self.zone_input.value = ""
        if self.rotation_input is not None:
            self.rotation_input.value = ""
        errors = self.update_annotations(redraw=False)
        self.redraw_scene(model)
        self.redraw_diffraction(model)
        self.simulator.propagate_bound_motion(self.state.panel_id, old_view, old_roll, new_view, new_roll)
        self.simulator.set_status("; ".join(errors[:3]) if errors else message)

    def redraw_scene(self, model: CrystalModel | None = None, *, update_camera: bool = True) -> None:
        if self.scene is None:
            return
        background = self.state.display_settings.backgrounds.crystal
        if self.scene._props.get("background-color") != background:
            self.scene.props(f"background-color={background}")
            if core.is_loop_running():
                ui.run_javascript(f"const scene=getElement({self.scene.id}); scene?.renderer?.setClearColor({json.dumps(background)});")
        model = self.display_model(model)
        self.current_model = model
        signature = self.scene_content_signature(model)
        if signature != self.scene_signature:
            self.atom_objects.clear()
            self.hide_atom_inspector()
            self.scene.clear()
            self.scene.atom_sectors = {}
            self.scene.marker_groups = {}
            with self.scene:
                if self.coordinate_grid_enabled:
                    self.draw_coordinate_grid(model)
                for start, end in model.display_edges:
                    settings = self.state.display_settings
                    if settings.frame_opacity == 0:
                        continue
                    if settings.frame_width == 1.0:
                        self.scene.line(start.tolist(), end.tolist()).material(color=settings.frame_color, opacity=settings.frame_opacity)
                    else:
                        delta = end - start
                        radius = 0.0025 * settings.frame_width
                        self.scene.cylinder(radius, radius, float(np.linalg.norm(delta)), radial_segments=12).move(
                            *((start + end) * 0.5).tolist()
                        ).rotate_R(rotation_matrix_from_y(delta)).material(color=settings.frame_color, opacity=settings.frame_opacity)

                for atom in model.visible_display_atoms():
                    radius = model.atom_radius(atom)
                    sphere = self.scene.sphere(radius=radius, width_segments=32, height_segments=16).move(*atom.position.tolist()).material(
                        color=color_for_site(atom), opacity=0.58 + 0.42 * atom.occupancy
                    )
                    self.atom_objects[sphere.id] = atom
                    if self.state.display_settings.occupancy_colors == "sectors":
                        sectors = occupancy_sectors(atom.components)
                        if len(sectors) > 1:
                            self.scene.atom_sectors[sphere.id] = sectors

                planes, _ = parse_indices(self.state.plane_text, model, "plane", allow_multiple=True)
                vectors, _ = parse_indices(
                    self.state.vector_text,
                    model,
                    "direction",
                    allow_multiple=True,
                    allow_reciprocal=True,
                )
                self.draw_planes(model, planes)
                self.draw_vectors(model, vectors)
                geometry = marker_geometry(self.state.display_settings.markers, model)
                if geometry:
                    group = self.scene.group()
                    self.scene.marker_groups[group.id] = geometry
                    if self.annotation_visible("crystal"):
                        for marker in geometry:
                            if marker["label"]:
                                dx, dy = marker["label_direction"]
                                gap = marker["label_gap"]
                                style = (f"color:{crystal_text_color(self.state.display_settings, marker['label_color'])};opacity:{marker['label_opacity']};"
                                         f"font-size:{marker['label_size']}px;white-space:nowrap;pointer-events:none;"
                                         f"translate:calc({dx * 50}% + {dx * gap}px) calc({-dy * 50}% + {-dy * gap}px);")
                                self.scene.text(marker["label"], style=style).move(
                                    *np.mean(marker["points"], axis=0).tolist())
            self.scene.apply_atom_sectors()
            self.scene.apply_markers()
            self.scene_signature = signature

        if not update_camera:
            return
        self.position_scene_camera(model, self.state.view_vector, self.state.roll)

    def position_scene_camera(self, model: CrystalModel, view_vector: np.ndarray, roll: float) -> None:
        if self.state.initial_camera is not None:
            pose, self.state.initial_camera = self.state.initial_camera, None
            self.restore_camera_pose(pose, model)
            return
        view = normalize_vector(view_vector)
        if view is None:
            view = np.array([1.0, 0.0, 0.0])
        _u_axis, up_axis = projection_basis(view, roll)
        distance = calculate_camera_distance(model.limit * 1.08, REAL_SCENE_FOV_DEGREES)
        camera = view * distance
        self.scene.client.run_javascript(f"""
            const scene = getElement({self.scene.id});
            if (scene?.camera) {{scene.camera.far = {max(5000, distance + 3 * model.limit)}; scene.camera.updateProjectionMatrix();}}
        """)
        self.scene.move_camera(
            x=float(camera[0]),
            y=float(camera[1]),
            z=float(camera[2]),
            look_at_x=0.0,
            look_at_y=0.0,
            look_at_z=0.0,
            up_x=float(up_axis[0]),
            up_y=float(up_axis[1]),
            up_z=float(up_axis[2]),
            duration=0.3,
        )
        self.set_scale_bar_from_distance(distance, model)

    async def scene_client_size(self) -> tuple[float, float] | None:
        """Return the actual browser size of this 3D scene in CSS pixels.

        The real-space scale bar must use the actual rendered aspect ratio,
        not the original nominal ui.scene(width=440, height=280) aspect ratio.
        Otherwise the scale bar changes when the responsive layout changes.
        """
        if self.scene is None:
            return None
        selector = f"#c{self.scene.id}"
        try:
            size = await ui.run_javascript(
                f"""
                const element = document.querySelector({json.dumps(selector)});
                if (!element) return null;
                const rect = element.getBoundingClientRect();
                return {{width: rect.width, height: rect.height}};
                """,
                timeout=1.0,
            )
        except Exception:
            return None
        if not isinstance(size, dict):
            return None
        try:
            width = float(size.get("width", 0.0))
            height = float(size.get("height", 0.0))
        except (TypeError, ValueError):
            return None
        if width <= 1.0 or height <= 1.0:
            return None
        return width, height

    async def update_scene_scale_bar(self) -> None:
        if self.scene is None or self.current_model is None:
            return
        try:
            camera = await self.scene.get_camera()
        except Exception:
            return
        if not isinstance(camera, dict):
            return
        position = camera.get("position", {})
        distance = float(
            np.linalg.norm(
                np.array(
                    [
                        float(position.get("x", 0.0)),
                        float(position.get("y", 0.0)),
                        float(position.get("z", 0.0)),
                    ],
                    dtype=float,
                )
            )
        )
        if distance > 1e-9:
            self.set_scale_bar_from_distance(
                distance,
                self.current_model,
                scene_size=await self.scene_client_size(),
            )
        if self.simulator.auto_sync_view():
            unit = normalize_vector(
                np.array(
                    [
                        float(position.get("x", 1.0)),
                        float(position.get("y", 0.0)),
                        float(position.get("z", 0.0)),
                    ],
                    dtype=float,
                )
            )
            up = camera.get("up", {})
            up_vector = normalize_vector(
                np.array(
                    [
                        float(up.get("x", 0.0)),
                        float(up.get("y", 0.0)),
                        float(up.get("z", 1.0)),
                    ],
                    dtype=float,
                )
            )
            previous = normalize_vector(self.state.view_vector)
            if unit is not None and previous is not None:
                angle_change = math.degrees(math.acos(min(max(float(np.dot(unit, previous)), -1.0), 1.0)))
                if angle_change > 1.0:
                    old_view = self.state.view_vector.copy()
                    old_roll = float(self.state.roll)
                    self.state.view_vector = unit
                    self.state.roll = roll_from_view_and_up(
                        unit,
                        up_vector if up_vector is not None else np.array([0.0, 0.0, 1.0]),
                        self.state.roll,
                    )
                    self.redraw_diffraction(self.current_model)
                    self.simulator.propagate_bound_motion(
                        self.state.panel_id,
                        old_view,
                        old_roll,
                        self.state.view_vector,
                        self.state.roll,
                    )

    def scene_content_signature(self, model: CrystalModel) -> tuple[Any, ...]:
        return (
            crystal_model_key(model),
            json.dumps(asdict(crystal_display_settings(self.state.display_settings)), sort_keys=True),
            crystal_text_color(self.state.display_settings, ""),
            self.state.plane_text,
            self.state.vector_text,
            self.annotation_visible("crystal"),
            self.coordinate_grid_enabled,
            self.coordinate_grid_settings if self.coordinate_grid_enabled else None,
            tuple(self.simulator.plane_palette(self.state.panel_id)),
            tuple(self.simulator.vector_palette(self.state.panel_id)),
            tuple(sorted(display_element_colors(model, self.state.display_settings, self.effective_element_colors()).items())),
        )

    def set_scale_bar_from_distance(
        self,
        distance: float,
        model: CrystalModel,
        scene_size: tuple[float, float] | None = None,
    ) -> None:
        if self.scale_bar_line is None or self.scale_bar_label is None:
            return
        self.apply_scale_bar_visibility()
        if not self.annotation_visible("scale") or not self.state.display_settings.annotations.real_scale_visible:
            return

        viewport_height_world = max(
            2.0 * max(float(distance), 1e-9) * math.tan(math.radians(REAL_SCENE_FOV_DEGREES / 2.0)),
            1e-9,
        )
        width_px: float | None = None
        height_px: float | None = None
        if scene_size is not None:
            width_px, height_px = scene_size
            actual_aspect = max(width_px / max(height_px, 1e-9), 1e-9)
        else:
            # Fallback for the first draw before the browser reports the actual size.
            actual_aspect = REAL_SCENE_ASPECT

        visible_nm = max(viewport_height_world * actual_aspect * model.scale_nm, 1e-9)
        bar_nm = choose_scale_bar(visible_nm)

        if height_px is not None:
            # Convert nm -> world units -> pixels using the vertical FOV. This makes
            # the overlay independent of screen size and responsive layout aspect ratio.
            pixels_per_nm = height_px / max(viewport_height_world * model.scale_nm, 1e-9)
            bar_px = max(bar_nm * pixels_per_nm, 1.0)
            self.scale_bar_line.style(f"width: {bar_px:.1f}px")
        else:
            fraction = bar_nm / visible_nm
            self.scale_bar_line.style(f"width: {fraction * 100:.2f}%")
        self.scale_bar_label.set_text(f"{bar_nm:g} nm")

    def apply_scale_bar_visibility(self) -> None:
        if self.scale_bar_container is None:
            return
        settings = display_annotations(self.state.display_settings)
        style = settings.real_scale
        right, top = "right" in style.position, "top" in style.position
        self.scale_bar_container.visible = self.annotation_visible("scale") and settings.real_scale_visible
        self.scale_bar_container.style(
            f"top: {'14px' if top else 'auto'}; bottom: {'auto' if top else '14px'}; "
            f"display: flex; flex-direction: column; align-items: {'flex-end' if right else 'flex-start'}; opacity: {style.opacity};"
            f"text-shadow: {'none' if self.state.display_settings.backgrounds.automatic_text else '0 1px 3px rgba(0,0,0,.85)'}")
        self.scale_bar_line.style(f"margin-left: 16px; margin-right: 16px; background: {style.color}; border-color: {style.color};"
                                 f"box-shadow: {'none' if self.state.display_settings.backgrounds.automatic_text else '0 1px 4px rgba(0,0,0,.7)'}")
        self.scale_bar_label.style(f"margin-left: 16px; margin-right: 16px; color: {style.color}; font-size: {style.font_size:g}px")
        self.scale_bar_container.update()

    def draw_coordinate_grid(self, model: CrystalModel) -> None:
        low, high = display_cell_bounds(self.state.display_settings.cells)
        grid = coordinate_grid_geometry(model, low, high, self.state.display_settings.markers,
                                        self.coordinate_grid_settings)
        self.coordinate_grid_step = grid["step"]
        self.coordinate_grid_limit = grid["limit"]
        with self.scene.group().with_name("coordinate-grid"):
            for start, end in grid["segments"]:
                self.scene.line(start, end).material(color="#A1ABB6", opacity=.22)
            for axis in grid["axes"]:
                self.draw_arrow(np.array(axis["start"]), np.array(axis["end"]), axis["color"],
                                shaft_radius=.006, head_radius=.028, opacity=.9, head_length=axis["head_length"])
                self.scene.text(axis["label"], style=f"color:{axis['color']};font-size:14px;font-weight:700;"
                                "pointer-events:none;translate:8px -10px;text-shadow:0 1px 3px #000;").move(*axis["end"])

    def draw_planes(self, model: CrystalModel, planes: list[ParsedIndex]) -> None:
        if self.scene is None:
            return
        palette = self.simulator.plane_palette(self.state.panel_id)
        settings = self.state.display_settings
        for index, plane in enumerate(planes):
            vertices = clipped_plane_polygon(model, plane)
            if vertices is None:
                continue
            color = palette[index % len(palette)]
            centroid = np.mean(vertices, axis=0)
            if settings.plane_opacity > 0:
                for start, end in zip(vertices, np.roll(vertices, -1, axis=0)):
                    coords = [[start.tolist(), end.tolist()], [centroid.tolist(), centroid.tolist()]]
                    self.scene.texture(PLANE_FILL_TEXTURE, coords).material(color=color, opacity=settings.plane_opacity, side="both")
            if settings.plane_edge_opacity > 0:
                for start, end in zip(vertices, np.roll(vertices, -1, axis=0)):
                    self.scene.line(start.tolist(), end.tolist()).material(color=color, opacity=settings.plane_edge_opacity)
            if self.annotation_visible("crystal") and settings.plane_label_opacity > 0:
                label_position = np.mean(vertices, axis=0)
                self.scene.text(plane.label, style=f"color: {crystal_text_color(settings, color)}; opacity: {settings.plane_label_opacity}; font-size: {13 * settings.plane_label_scale:g}px; font-weight: 700;").move(
                    *label_position.tolist()
                )

    def draw_vectors(self, model: CrystalModel, vectors: list[ParsedIndex]) -> None:
        if self.scene is None:
            return
        palette = self.simulator.vector_palette(self.state.panel_id)
        settings = self.state.display_settings
        for index, vector in enumerate(vectors):
            color = palette[index % len(palette)]
            opacity = settings.reciprocal_opacity if vector.is_reciprocal else settings.vector_opacity
            if vector.is_reciprocal:
                start, end = reciprocal_segment_for_display(vector.values, model)
                if opacity > 0:
                    self.draw_arrow(start, end, color, shaft_radius=0.011, head_radius=0.044, opacity=opacity)
                    self.draw_reciprocal_markers(start, end, color)
            else:
                start, end = direction_segment_for_display(vector.values, model)
                if opacity > 0:
                    self.draw_arrow(start, end, color, opacity=opacity)
            if self.annotation_visible("crystal") and settings.vector_label_opacity > 0:
                self.scene.text(vector.label, style=f"color: {crystal_text_color(settings, color)}; opacity: {settings.vector_label_opacity}; font-size: {13 * settings.vector_label_scale:g}px; font-weight: 700;").move(
                    *end.tolist()
                )

    def draw_reciprocal_markers(self, start: np.ndarray, end: np.ndarray, color: str) -> None:
        if self.scene is None:
            return
        delta = end - start
        if float(np.linalg.norm(delta)) < 1e-8:
            return
        for fraction in np.linspace(0.22, 0.78, 4):
            point = start + delta * float(fraction)
            self.scene.sphere(radius=0.018, width_segments=16, height_segments=8).move(*point.tolist()).material(
                color=color,
                opacity=min(1.0, self.state.display_settings.reciprocal_opacity * 0.88 / 0.78),
            )

    def draw_arrow(
        self,
        start: np.ndarray,
        end: np.ndarray,
        color: str,
        shaft_radius: float = 0.018,
        head_radius: float = 0.055,
        opacity: float = 0.95,
        head_length: float = 0.18,
    ) -> None:
        if self.scene is None:
            return
        delta = end - start
        length = float(np.linalg.norm(delta))
        if length < 1e-8:
            return
        direction = delta / length
        head_length = min(head_length, length * 0.28)
        shaft_length = max(length - head_length, length * 0.5)
        rotation = rotation_matrix_from_y(direction)
        shaft_center = start + direction * (shaft_length * 0.5)
        self.scene.cylinder(shaft_radius, shaft_radius, shaft_length, radial_segments=16).move(*shaft_center.tolist()).rotate_R(
            rotation
        ).material(color=color, opacity=opacity)
        head_center = start + direction * (shaft_length + head_length * 0.5)
        self.scene.cylinder(0.0, head_radius, head_length, radial_segments=24).move(*head_center.tolist()).rotate_R(
            rotation
        ).material(color=color, opacity=opacity)

    def redraw_diffraction(self, model: CrystalModel | None = None) -> None:
        if self.diffraction is None:
            return
        model = model or self.simulator.model_for(self.state.crystal_name)
        spots = self.simulator.diffraction_spots_for_state(self.state, model)
        spot_color = self.simulator.display_diffraction_color(self.state)
        limit = self.simulator.current_diffraction_limit()
        zone_label = (
            zone_axis_label_from_view(
                model,
                self.state.view_vector,
                use_hex_four_index=self.simulator.use_hex_four_index_basis(),
            )
            if self.annotation_visible("zone")
            else ""
        )
        self.diffraction.update_figure(
            self.build_diffraction_figure(
                model=model,
                spots=spots,
                limit=limit,
                spot_color=spot_color,
                zone_label=zone_label,
            )
        )

    def build_diffraction_figure(
        self,
        model: CrystalModel,
        spots: np.ndarray,
        limit: float,
        spot_color: str,
        zone_label: str = "",
    ) -> dict[str, Any]:
        settings = display_annotations(self.state.display_settings)
        background = self.state.display_settings.backgrounds.diffraction
        shapes, annotations = (
            diffraction_scale_bar_items(limit, self.simulator.current_reciprocal_units_per_plot_unit(), settings)
            if self.annotation_visible("scale")
            else ([], [])
        )
        if zone_label:
            annotations.append(diffraction_zone_axis_annotation(limit, zone_label, settings, self.annotation_visible("scale")))
        data: list[dict[str, Any]] = []
        if len(spots):
            intensity = spots[:, 2]
            size_scaling = self.simulator.current_spot_size_scaling_effect()
            marker_size = BASE_DIFFRACTION_MARKER_SIZE + EXTRA_DIFFRACTION_MARKER_SIZE * size_scaling * intensity**1.18
            labels = []
            hover_text = []
            for spot in spots:
                h, k, l = (int(round(value)) for value in spot[3:6])
                label = diffraction_label_for_hkl(h, k, l, model, self.simulator.use_hex_four_index_basis())
                labels.append(label)
                d_nm = plane_spacing_nm_for_hkl(h, k, l, model)
                d_text = "infinite" if math.isinf(d_nm) else f"{d_nm:.4g} nm"
                hover_text.append(
                    f"Index: {label}<br>Relative intensity: {diffraction_intensity_text(float(spot[2]))}<br>d-spacing: {d_text}"
                )
            data.append(
                {
                    "type": "scatter",
                    "mode": "markers",
                    "x": spots[:, 0].tolist(),
                    "y": spots[:, 1].tolist(),
                    "text": hover_text,
                    "hovertemplate": "%{text}<extra></extra>",
                    "marker": {
                        "size": marker_size.tolist(),
                        "color": [rgba_css(spot_color, alpha) for alpha in self.simulator.diffraction_spot_opacities(intensity)],
                        "line": {"width": 0},
                    },
                }
            )
            if self.annotation_visible("indices"):
                annotations.extend(self.diffraction_index_annotations(spots, limit, labels, settings, marker_size))
        else:
            annotations.append(
                {
                    "x": 0,
                    "y": 0,
                    "xref": "x",
                    "yref": "y",
                    "text": "No reflections in Ewald condition",
                    "showarrow": False,
                    "font": {"color": contrast_text_color(background), "size": 12},
                }
            )
        return {
            "data": data,
            "layout": {
                "paper_bgcolor": background,
                "plot_bgcolor": background,
                "margin": {"l": 0, "r": 0, "t": 0, "b": 0},
                "xaxis": {
                    "visible": False,
                    "range": [-limit, limit],
                    "scaleanchor": "y",
                    "scaleratio": 1,
                    "constrain": "domain",
                    "fixedrange": True,
                    "zeroline": False,
                },
                "yaxis": {
                    "visible": False,
                    "range": [-limit, limit],
                    "constrain": "domain",
                    "fixedrange": True,
                    "zeroline": False,
                },
                "showlegend": False,
                "hovermode": "closest",
                "dragmode": False,
                "shapes": shapes,
                "annotations": annotations,
            },
            "config": {"displayModeBar": False, "responsive": True, "scrollZoom": False},
        }

    @staticmethod
    def diffraction_index_annotations(spots: np.ndarray, limit: float, labels: list[str],
                                     settings: PanelAnnotations | None = None,
                                     marker_sizes: np.ndarray | None = None) -> list[dict[str, Any]]:
        settings = settings or PanelAnnotations()
        style = settings.indices
        dx, dy = SPOT_LABEL_DIRECTIONS[style.position]
        order = np.argsort(spots[:, 2])[::-1]
        labeled = 0
        margin = 0.94 * float(limit)
        annotations = []
        for spot_index in order:
            h, k, l = (int(round(value)) for value in spots[spot_index, 3:6])
            if h == k == l == 0:
                continue
            x_coord = float(spots[spot_index, 0])
            y_coord = float(spots[spot_index, 1])
            radius = float(marker_sizes[spot_index]) / 2 if marker_sizes is not None else 0
            offset = max(0.0, radius + settings.index_offset) / math.hypot(dx, dy)
            if abs(x_coord) > margin or abs(y_coord) > margin:
                continue
            annotations.append(
                {
                    "x": x_coord,
                    "y": y_coord,
                    "xref": "x",
                    "yref": "y",
                    "text": labels[spot_index],
                    "showarrow": False,
                    "font": {"color": style.color, "size": style.font_size},
                    "borderpad": 0,
                    "borderwidth": 0,
                    "xanchor": "left" if dx > 0 else "right" if dx < 0 else "center",
                    "yanchor": "bottom" if dy > 0 else "top" if dy < 0 else "middle",
                    "xshift": dx * offset,
                    "yshift": dy * offset,
                    "opacity": style.opacity,
                }
            )
            labeled += 1
            if labeled >= 80:
                break
        return annotations


class ComboPanelController:
    def __init__(self, simulator: "SimulatorApp", state: ComboPanelState) -> None:
        self.simulator = simulator
        self.state = state
        self.card = None
        self.source_select = None
        self.source_list_container = None
        self.source_rows = self.source_sortable = None
        self.source_row_panel_ids = {}
        self.view_splitter = None
        self.diffraction = None
        self.download_dialog = None
        self.animation_dialog = None
        self.bind_checkbox = None
        self.magnify_button = None

    def build(self) -> None:
        self.simulator.repair_combo_sources(self.state)
        card_classes = f"comparison-panel combo-panel combo-panel-{self.state.combo_id}"
        if self.state.magnified:
            card_classes += " panel-magnified"
        with ui.card().classes(card_classes) as self.card:
            with ui.element("div").classes("combo-toolbar"):
                ui.label(f"C{self.state.combo_id}").classes("combo-number")
                options = self.source_options()
                self.state.selected_panel_id = self.state.selected_panel_id or next(iter(options), None)
                self.source_select = ui.select(
                    options,
                    label="Current crystals",
                    value=self.state.selected_panel_id,
                    on_change=self.on_source_selected,
                ).props("outlined dense").classes("combo-source-select")
                ui.button("Add", on_click=self.add_selected_source).props("outline dense").classes(
                    "combo-action-button combo-add-button"
                )
                ui.button("Remove", on_click=self.remove_selected_source).props("outline dense").classes(
                    "combo-action-button combo-remove-button"
                )
                self.bind_checkbox = ui.checkbox(
                    "Bind crystal motion",
                    value=self.state.bind_motion,
                    on_change=self.on_bind_motion_changed,
                ).props("dense color=secondary").classes("combo-bind-checkbox")
                ui.button(icon="photo_camera", on_click=self.open_download_dialog).props("flat round dense").classes(
                    "combo-download-button"
                ).tooltip("Download combo diffraction")
                self.magnify_button = ui.button(
                    icon=self.magnify_icon(),
                    on_click=self.toggle_magnified,
                ).props("flat round dense").classes("combo-magnify-button").tooltip("Magnify/shrink panel")
                ui.button(icon="close", on_click=lambda: self.simulator.remove_combo_panel(self.state.combo_id)).props(
                    "flat round dense"
                ).classes("panel-close-button").tooltip("Remove combo panel")

            with PanelViewSplitter(self.state.source_view_percent,
                                   lambda event: setattr(self.state, "source_view_percent", event.value),
                                   "Resize source list and diffraction views") as self.view_splitter:
                with self.view_splitter.before:
                    with ui.element("div").classes("combo-source-list") as self.source_list_container:
                        with ui.element("div").classes("combo-source-header"):
                            ui.element("div")
                            ui.label("Panel")
                            ui.label("Crystal")
                            ui.label("Zone")
                            ui.label("")
                        self.source_rows = ui.column().classes("combo-source-rows full-width gap-0")
                        self.source_sortable = self.source_rows.make_sortable(
                            options={"forceFallback": True, "fallbackTolerance": 4,
                                     "chosenClass": "combo-source-chosen", "fallbackClass": "combo-source-ghost"},
                            handle=".combo-source-drag", on_end=self.on_sources_sorted)
                        self.source_sortable.move(self.source_list_container)
                with self.view_splitter.after:
                    self.diffraction = ui.plotly(empty_diffraction_figure()).classes("diffraction-plot combo-diffraction-plot")

        self.refresh()
        self.update_magnify_button()

    def magnify_icon(self) -> str:
        return "close_fullscreen" if self.state.magnified else "open_in_full"

    def update_magnify_button(self) -> None:
        if self.magnify_button is None:
            return
        self.magnify_button.props(f"icon={self.magnify_icon()}")
        self.magnify_button.update()

    def toggle_magnified(self) -> None:
        self.state.magnified = not self.state.magnified
        if self.card is not None:
            if self.state.magnified:
                self.card.classes(add="panel-magnified")
            else:
                self.card.classes(remove="panel-magnified")
        self.update_magnify_button()

    def open_download_dialog(self) -> None:
        self.download_editor = StaticDownloadDialog(self)
        self.download_dialog = self.download_editor.dialog
        self.download_editor.open()

    async def open_animation_dialog(self) -> None:
        from CrysDiS_animation import ComboAnimationDialog

        if self.download_dialog is not None:
            self.download_dialog.close()
        available = ComboAnimationDialog.available_panel_ids(self)
        sources = [state.panel_id for state in self.selected_sources()]
        if not sources:
            ui.notify("Choose source panels before creating an animation", type="warning")
            return
        if (self.animation_dialog is None or self.animation_dialog.available_ids != available
                or self.animation_dialog.source_ids != sources):
            if self.animation_dialog is not None:
                self.animation_dialog.dialog.delete()
            with ui.context.client.content:
                self.animation_dialog = ComboAnimationDialog(self, sys.modules[__name__])
        await self.animation_dialog.open()

    async def download_diffraction_image(
        self,
        dpi: float,
        transparent_background: bool = False,
        filename_base: str | None = None,
        include_suffixes: bool = True,
    ) -> None:
        dpi = min(max(float(dpi or 300), 72.0), 1200.0)
        direct_export = self.simulator.direct_file_exports_enabled()
        selector = f".combo-panel-{self.state.combo_id}"
        filename = export_image_filename(
            filename_base,
            f"combo_C{self.state.combo_id}_diffraction",
            dpi,
            transparent_background,
            include_suffixes=include_suffixes,
        )
        script = f"""
        const root = document.querySelector({json.dumps(selector)});
        const dpi = {float(dpi):.6f};
        const scale = Math.max(1, dpi / 150);
        const transparentBackground = {json.dumps(bool(transparent_background))};
        const directExport = {json.dumps(bool(direct_export))};
        const filename = {json.dumps(filename)};

        function saveDataUrl(dataUrl, filename) {{
            const link = document.createElement('a');
            link.href = dataUrl;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            link.remove();
        }}

        async function downloadDiffraction() {{
            const plot = root?.querySelector('.diffraction-plot.js-plotly-plot') || root?.querySelector('.diffraction-plot .js-plotly-plot');
            if (!plot || !window.Plotly) return false;
            const rect = plot.getBoundingClientRect();
            const originalPaper = plot.layout?.paper_bgcolor;
            const originalPlot = plot.layout?.plot_bgcolor;
            if (transparentBackground) {{
                await window.Plotly.relayout(plot, {{
                    paper_bgcolor: 'rgba(0,0,0,0)',
                    plot_bgcolor: 'rgba(0,0,0,0)',
                }});
            }}
            let dataUrl;
            try {{
                dataUrl = await window.Plotly.toImage(plot, {{
                    format: 'png',
                    width: Math.round(rect.width > 1 ? rect.width : (plot._fullLayout?.width || 440)),
                    height: Math.round(rect.height > 1 ? rect.height : (plot._fullLayout?.height || 280)),
                    scale,
                }});
            }} finally {{
                if (transparentBackground) {{
                    await window.Plotly.relayout(plot, {{
                        paper_bgcolor: originalPaper || '#000000',
                        plot_bgcolor: originalPlot || '#000000',
                    }});
                }}
            }}
            if (directExport) {{
                return {{filename, dataUrl}};
            }}
            saveDataUrl(dataUrl, filename);
            return {{downloaded: true}};
        }}

        return await downloadDiffraction();
        """
        try:
            result = await ui.run_javascript(script, timeout=20.0)
        except Exception as exc:
            ui.notify(f"Download failed: {exc}", type="negative")
            return
        saved_paths: list[Path] = []
        if direct_export:
            if not (isinstance(result, dict) and result.get("dataUrl") and result.get("filename")):
                ui.notify("Could not capture the combo diffraction pattern", type="warning")
                return
            try:
                image_bytes = decode_png_data_url(str(result["dataUrl"]))
                saved_paths.append(self.simulator.save_exported_image(image_bytes, str(result["filename"])))
            except Exception as exc:
                ui.notify(f"Combo diffraction export failed: {exc}", type="negative")
                return
        downloaded = bool(result and (result is True or (isinstance(result, dict) and result.get("downloaded"))))
        if saved_paths or downloaded:
            if self.download_dialog is not None:
                self.download_dialog.close()
            if direct_export:
                self.simulator.announce_saved_exports(saved_paths)
            else:
                self.simulator.set_status(f"Combo C{self.state.combo_id}: downloaded diffraction export")
        else:
            ui.notify("Could not capture the combo diffraction pattern", type="warning")

    def source_options(self) -> dict[int, str]:
        return {state.panel_id: f"{state.panel_id}. {state.crystal_name}" for state in self.simulator.panel_states}

    def selected_sources(self) -> list[PanelState]:
        panel_map = {state.panel_id: state for state in self.simulator.panel_states}
        return [panel_map[panel_id] for panel_id in self.state.source_panel_ids if panel_id in panel_map]

    def on_source_selected(self) -> None:
        try:
            self.state.selected_panel_id = int(self.source_select.value)
        except (TypeError, ValueError):
            self.state.selected_panel_id = None

    def on_bind_motion_changed(self) -> None:
        self.state.bind_motion = bool(self.bind_checkbox.value) if self.bind_checkbox is not None else False
        state_text = "enabled" if self.state.bind_motion else "disabled"
        self.simulator.set_status(f"Combo C{self.state.combo_id}: bind all crystal motion {state_text}")

    def add_selected_source(self) -> None:
        self.on_source_selected()
        panel_id = self.state.selected_panel_id
        if panel_id is None:
            return
        if panel_id in self.state.source_panel_ids:
            ui.notify("That panel is already in this combo panel", type="info")
            return
        self.state.source_panel_ids.append(panel_id)
        self.refresh()
        self.simulator.set_status(f"Combo C{self.state.combo_id}: added panel {panel_id}")

    def remove_selected_source(self) -> None:
        self.on_source_selected()
        panel_id = self.state.selected_panel_id
        if panel_id is None or panel_id not in self.state.source_panel_ids:
            return
        self.remove_source(panel_id)

    def remove_source(self, panel_id: int) -> None:
        if len(self.state.source_panel_ids) <= 2:
            ui.notify("A combo panel needs at least two source panels", type="warning")
            return
        self.state.source_panel_ids = [value for value in self.state.source_panel_ids if value != panel_id]
        self.refresh()
        self.simulator.set_status(f"Combo C{self.state.combo_id}: removed panel {panel_id}")

    def move_source(self, panel_id: int, direction: int) -> None:
        if panel_id in self.state.source_panel_ids:
            self.move_source_to(panel_id, self.state.source_panel_ids.index(panel_id) + direction)

    def move_source_to(self, panel_id: int, new_index: int) -> None:
        try:
            index = self.state.source_panel_ids.index(panel_id)
        except ValueError:
            return
        new_index = min(max(new_index, 0), len(self.state.source_panel_ids) - 1)
        if new_index == index:
            return
        self.state.source_panel_ids.insert(new_index, self.state.source_panel_ids.pop(index))
        self.refresh()

    def on_sources_sorted(self, event) -> None:
        panel_id = self.source_row_panel_ids.get(event.item.id)
        if panel_id is not None:
            self.move_source_to(panel_id, event.new_index)

    def refresh(self) -> None:
        self.simulator.repair_combo_sources(self.state)
        self.refresh_source_options()
        if self.bind_checkbox is not None:
            self.bind_checkbox.value = self.state.bind_motion
            self.bind_checkbox.update()
        self.refresh_source_list()
        self.redraw_diffraction()

    def refresh_source_options(self) -> None:
        options = self.source_options()
        if self.source_select is None:
            return
        self.source_select.options = options
        if self.state.selected_panel_id not in options:
            self.state.selected_panel_id = next(iter(options), None)
        self.source_select.value = self.state.selected_panel_id
        self.source_select.update()

    def refresh_source_list(self) -> None:
        if self.source_rows is None:
            return
        sources = self.selected_sources()
        self.source_rows.clear()
        self.source_row_panel_ids.clear()
        with self.source_rows:
            for index, source in enumerate(sources):
                model = self.simulator.model_for(source.crystal_name)
                zone = zone_axis_label_from_view(
                    model,
                    source.view_vector,
                    use_hex_four_index=self.simulator.use_hex_four_index_basis(),
                ).replace(" zone", "")
                with ui.element("div").classes("combo-source-row") as row:
                    self.source_row_panel_ids[row.id] = source.panel_id
                    ui.button(icon="drag_indicator").props("flat round dense size=sm aria-label='Reorder crystal'").classes(
                        "combo-source-drag").tooltip("Hold and drag to reorder crystal")
                    ui.label(str(source.panel_id)).classes("combo-source-panel-id")
                    ui.label(source.crystal_name).classes("combo-source-name")
                    ui.label(zone).classes("combo-source-zone")
                    with ui.row().classes("combo-source-actions"):
                        up = ui.button(icon="arrow_upward", on_click=lambda _=None, p=source.panel_id: self.move_source(p, -1)).props(
                            "flat round dense"
                        ).tooltip("Move up")
                        down = ui.button(
                            icon="arrow_downward",
                            on_click=lambda _=None, p=source.panel_id: self.move_source(p, 1),
                        ).props("flat round dense").tooltip("Move down")
                        remove = ui.button(icon="close", on_click=lambda _=None, p=source.panel_id: self.remove_source(p)).props(
                            "flat round dense color=negative"
                        ).tooltip("Remove from combo")
                        if index == 0:
                            up.disable()
                        if index == len(sources) - 1:
                            down.disable()
                        if len(sources) <= 2:
                            remove.disable()

    def redraw_diffraction(self) -> None:
        if self.diffraction is None:
            return
        sources = self.selected_sources()
        limit = self.simulator.current_diffraction_limit()
        zone_label = ""
        if self.simulator.show_zone_axis_on_diffraction() and sources:
            model = self.simulator.model_for(sources[0].crystal_name)
            zone_label = zone_axis_label_from_view(
                model,
                sources[0].view_vector,
                use_hex_four_index=self.simulator.use_hex_four_index_basis(),
            )
        self.diffraction.update_figure(self.build_combo_figure(sources, limit, zone_label))

    def build_combo_figure(self, sources: list[PanelState], limit: float, zone_label: str = "") -> dict[str, Any]:
        display = self.simulator.global_display_settings
        settings = display_annotations(display)
        shapes, annotations = (
            diffraction_scale_bar_items(limit, self.simulator.current_reciprocal_units_per_plot_unit(), settings)
            if self.simulator.show_scale_bars()
            else ([], [])
        )
        if zone_label:
            annotations.append(diffraction_zone_axis_annotation(limit, zone_label, settings, self.simulator.show_scale_bars()))
        data: list[dict[str, Any]] = []
        for source in reversed(sources):
            model = self.simulator.model_for(source.crystal_name)
            spots = self.simulator.diffraction_spots_for_state(source, model)
            if not len(spots):
                continue
            intensity = spots[:, 2]
            spot_color = self.simulator.display_diffraction_color(source, display.backgrounds.diffraction)
            size_scaling = self.simulator.current_spot_size_scaling_effect()
            marker_size = BASE_DIFFRACTION_MARKER_SIZE + EXTRA_DIFFRACTION_MARKER_SIZE * size_scaling * intensity**1.18
            labels = []
            hover_text = []
            for spot in spots:
                h, k, l = (int(round(value)) for value in spot[3:6])
                label = diffraction_label_for_hkl(h, k, l, model, self.simulator.use_hex_four_index_basis())
                labels.append(label)
                d_nm = plane_spacing_nm_for_hkl(h, k, l, model)
                d_text = "infinite" if math.isinf(d_nm) else f"{d_nm:.4g} nm"
                hover_text.append(
                    f"Source: panel {source.panel_id} - {source.crystal_name}"
                    f"<br>Index: {label}<br>Relative intensity: {diffraction_intensity_text(float(spot[2]))}<br>d-spacing: {d_text}"
                )
            data.append(
                {
                    "type": "scatter",
                    "mode": "markers",
                    "x": spots[:, 0].tolist(),
                    "y": spots[:, 1].tolist(),
                    "text": hover_text,
                    "hovertemplate": "%{text}<extra></extra>",
                    "marker": {
                        "size": marker_size.tolist(),
                        "color": [rgba_css(spot_color, alpha) for alpha in self.simulator.diffraction_spot_opacities(intensity, combo=True)],
                        "line": {"width": 0},
                    },
                }
            )
            if self.simulator.show_indices():
                annotations.extend(PanelController.diffraction_index_annotations(
                    spots, limit, labels, display_annotations(source.display_settings, display.backgrounds), marker_size))
        if not data:
            annotations.append(
                {
                    "x": 0,
                    "y": 0,
                    "xref": "x",
                    "yref": "y",
                    "text": "No source reflections to overlay",
                    "showarrow": False,
                    "font": {"color": contrast_text_color(display.backgrounds.diffraction), "size": 12},
                }
            )
        return {
            "data": data,
            "layout": {
                "paper_bgcolor": display.backgrounds.diffraction,
                "plot_bgcolor": display.backgrounds.diffraction,
                "margin": {"l": 0, "r": 0, "t": 0, "b": 0},
                "xaxis": {
                    "visible": False,
                    "range": [-limit, limit],
                    "scaleanchor": "y",
                    "scaleratio": 1,
                    "constrain": "domain",
                    "fixedrange": True,
                    "zeroline": False,
                },
                "yaxis": {"visible": False, "range": [-limit, limit], "fixedrange": True, "zeroline": False, "constrain": "domain"},
                "showlegend": False,
                "hovermode": "closest",
                "dragmode": False,
                "shapes": shapes,
                "annotations": annotations,
            },
            "config": {"displayModeBar": False, "responsive": True, "scrollZoom": False},
        }


class StaticDownloadDialog:
    """Low-resolution export previews without changing the live panel."""

    def __init__(self, controller: PanelController | ComboPanelController) -> None:
        self.controller = controller
        self.combo = isinstance(controller, ComboPanelController)
        self.closed = False
        self.busy = False
        self.revision = 0
        self.timer = None
        self.preview_lock = asyncio.Lock()
        self.cache: dict[str, tuple[tuple, bytes]] = {}
        self.controls: list[Any] = []
        self.shading_by_renderer = {"png": "mild", "three": "mild"}
        self.last_renderer = "three"
        self.crystal = self.renderer = self.shading = self.occupancy = self.crystal_filename = None
        self.tiles: dict[str, Any] = {}
        self.images: dict[str, Any] = {}
        self.errors: dict[str, Any] = {}
        name = f"combo C{controller.state.combo_id}" if self.combo else f"panel {controller.state.panel_id}"
        base = f"combo_C{controller.state.combo_id}" if self.combo else f"panel_{controller.state.panel_id}"
        self.dialog = ui.dialog()
        with self.dialog, ui.card().classes("download-card static-download-card"):
            with ui.row().classes("items-center justify-between full-width"):
                ui.label(f"Download {name}").classes("text-h6")
                self.control(ui.button(icon="close", on_click=self.dialog.close).props("flat round dense").tooltip("Close"))
            with ui.row().classes("full-width items-center"):
                if not self.combo:
                    self.crystal = self.control(ui.checkbox("Real-space crystal", value=True).props("dense"))
                self.diffraction = self.control(ui.checkbox("Diffraction pattern", value=True).props("dense"))
                if self.combo:
                    self.diffraction.set_visibility(False)
                self.transparent = self.control(ui.checkbox("Transparent background", value=False).props("dense"))
            with ui.element("div").classes("static-download-options"):
                if not self.combo:
                    self.renderer = self.control(ui.select({"png": "Current PNG exporter", "three": "Three.js"},
                        value="three", label="Crystal renderer").props("outlined dense"))
                    self.renderer.tooltip("Both renderers save PNG files. Three.js uses a lit 3D scene.")
                    self.shading = self.control(ui.select(ATOM_SHADING_OPTIONS, value="mild", label="Shading").props("outlined dense"))
                    self.occupancy = self.control(ui.select(EXPORT_OCCUPANCY_COLOR_OPTIONS, value="panel",
                        label="Site occupancy colors").props("outlined dense"))
                    self.occupancy.tooltip("Viewer-facing sectors represent site occupancy; gray is unoccupied.")
                    self.crystal_filename = self.control(ui.input("Crystal file name base", value=base + "_crystal").props("outlined dense"))
                self.diffraction_filename = self.control(ui.input("Diffraction file name base", value=base + "_diffraction").props("outlined dense"))
                self.dpi = self.control(ui.number("Quality", value=300, min=72, max=1200, step=50, suffix="dpi").props("outlined dense"))
            self.suffix = self.control(ui.checkbox("Add transparency and DPI suffixes", value=True).props("dense"))
            if controller.simulator.direct_file_exports_enabled():
                folder = ui.label(f"Export folder: {controller.simulator.export_dir_text()}").classes("export-folder-label")

                async def choose_folder() -> None:
                    await controller.simulator.choose_export_folder(folder)

                self.control(ui.button("Choose export folder", icon="folder_open", on_click=choose_folder).props("outline dense"))
            with ui.row().classes("full-width items-center gap-2"):
                ui.label("Preview").classes("text-subtitle2").tooltip("Preview resolution is limited for speed. Downloads use the selected DPI.")
                self.spinner = ui.spinner(size="sm")
                self.status = ui.label("Updating preview...").classes("text-caption")
                self.control(ui.button(icon="refresh", on_click=self.refresh).props("flat round dense").tooltip("Refresh preview"))
            with ui.element("div").classes("static-download-previews") as self.previews:
                for kind, label in (("crystal", "Real-space crystal"), ("diffraction", "Diffraction pattern")):
                    if self.combo and kind == "crystal":
                        continue
                    with ui.column().classes("static-download-tile gap-1") as self.tiles[kind]:
                        ui.label(label).classes("text-caption")
                        self.images[kind] = ui.image().props("fit=contain no-spinner no-transition").classes("static-download-image")
                        self.errors[kind] = ui.label().classes("text-negative text-caption full-width")
                        self.errors[kind].set_visibility(False)
            with ui.row().classes("full-width items-center justify-between static-download-actions"):
                self.control(ui.button("Create animation", icon="movie", on_click=self.open_animation).props("outline dense"))
                with ui.row().classes("items-center gap-2"):
                    self.control(ui.button("Cancel", on_click=self.dialog.close).props("flat dense"))
                    self.download_button = self.control(ui.button("Download", icon="download", on_click=self.download).props("unelevated dense"))
        for control in (self.crystal, self.diffraction, self.transparent, self.renderer, self.shading, self.occupancy, self.dpi):
            if control is not None:
                control.on_value_change(self.schedule_preview)
        self.dialog.on("show", self.schedule_preview)
        self.dialog.on("hide", self.stop)
        self.dialog.client.on_disconnect(self.stop)
        self.update_controls()

    def control(self, element: Any) -> Any:
        self.controls.append(element)
        return element

    def selected(self) -> list[str]:
        return (["crystal"] if self.crystal is not None and self.crystal.value else []) + (["diffraction"] if self.diffraction.value else [])

    def update_controls(self) -> None:
        if self.renderer is not None:
            if self.renderer.value != self.last_renderer:
                self.shading_by_renderer[self.last_renderer] = self.shading.value
                self.last_renderer = self.renderer.value
                self.shading.set_value(self.shading_by_renderer[self.last_renderer])
            for control in (self.renderer, self.shading, self.occupancy, self.crystal_filename):
                control.set_enabled(not self.busy and bool(self.crystal.value))
        self.diffraction_filename.set_enabled(not self.busy and bool(self.diffraction.value))
        selected = self.selected()
        self.download_button.set_enabled(not self.busy and bool(selected))
        for kind, tile in self.tiles.items():
            tile.set_visibility(kind in selected)
            self.images[kind].classes(add="static-download-transparent" if self.transparent.value else "",
                                      remove="static-download-transparent" if not self.transparent.value else "")
        self.previews.classes(add="static-download-single" if len(selected) == 1 else "",
                              remove="static-download-single" if len(selected) != 1 else "")

    def open(self) -> None:
        self.dialog.open()
        self.schedule_preview()

    def stop(self) -> None:
        self.closed = True
        self.revision += 1
        if self.timer is not None:
            self.timer.cancel()
        self.cache.clear()
        for image in self.images.values():
            image.set_source("")

    def refresh(self) -> None:
        self.cache.clear()
        self.schedule_preview()

    def schedule_preview(self) -> None:
        if self.closed or self.busy:
            return
        self.revision += 1
        if self.timer is not None:
            self.timer.cancel()
        self.update_controls()
        selected = self.selected()
        self.spinner.set_visibility(bool(selected))
        self.status.set_text("Updating preview..." if selected else "Choose at least one image")
        for kind in selected:
            self.images[kind].style("opacity:0.4")
        if selected:
            with self.dialog:
                self.timer = ui.timer(0.25, self.update_preview, once=True, immediate=False)

    async def diffraction_preview(self, dpi: float, transparent: bool) -> bytes:
        state = self.controller.state
        selector = f".combo-panel-{state.combo_id}" if self.combo else f".comparison-panel-{state.panel_id}"
        # Plotly.toImage accepts a figure copy, so transparency never relayouts the live plot.
        data_url = await ui.run_javascript(f"""
            const root = document.querySelector({json.dumps(selector)});
            const plot = root?.querySelector('.diffraction-plot.js-plotly-plot') || root?.querySelector('.diffraction-plot .js-plotly-plot');
            if (!plot || !window.Plotly) throw new Error('Diffraction view is not ready');
            const rect = plot.getBoundingClientRect();
            const width = Math.round(rect.width > 1 ? rect.width : (plot._fullLayout?.width || 440));
            const height = Math.round(rect.height > 1 ? rect.height : (plot._fullLayout?.height || 280));
            const figure = JSON.parse(JSON.stringify({{data: plot.data, layout: plot.layout}}));
            if ({json.dumps(transparent)}) {{
                figure.layout.paper_bgcolor = 'rgba(0,0,0,0)';
                figure.layout.plot_bgcolor = 'rgba(0,0,0,0)';
            }}
            return await window.Plotly.toImage(figure, {{format: 'png',
                width, height,
                scale: Math.min(1, 690 / Math.max(width, height)) * Math.min(1, {dpi} / 150)}});
        """, timeout=30)
        return decode_png_data_url(data_url)

    async def update_preview(self) -> None:
        revision = self.revision
        async with self.preview_lock:
            if self.closed or self.busy or revision != self.revision:
                return
            dpi = min(max(float(self.dpi.value or 300), 72), 150)
            transparent = bool(self.transparent.value)
            selected = self.selected()
            failed = False
            for kind in selected:
                key = (dpi, transparent)
                if kind == "crystal":
                    key += (self.renderer.value, self.shading.value, self.occupancy.value)
                try:
                    cached = self.cache.get(kind)
                    if cached is not None and cached[0] == key:
                        png = cached[1]
                    elif kind == "crystal":
                        png = await self.controller.render_crystal_image(*key)
                    else:
                        png = await self.diffraction_preview(*key)
                    if self.closed or self.busy or revision != self.revision:
                        return
                    self.cache[kind] = (key, png)
                    self.images[kind].set_source("data:image/png;base64," + base64.b64encode(png).decode("ascii"))
                    self.images[kind].style("opacity:1")
                    self.errors[kind].set_visibility(False)
                except Exception as exc:
                    if self.closed or self.busy or revision != self.revision:
                        return
                    failed = True
                    self.images[kind].set_source("")
                    self.errors[kind].set_text(f"Preview unavailable: {exc}")
                    self.errors[kind].set_visibility(True)
            self.spinner.set_visibility(False)
            self.status.set_text("Preview incomplete" if failed else "Ready")

    async def open_animation(self) -> None:
        self.stop()
        async with self.preview_lock:
            await self.controller.open_animation_dialog()

    async def download(self) -> None:
        if self.busy or not self.selected():
            return
        self.busy = True
        self.revision += 1
        if self.timer is not None:
            self.timer.cancel()
        for control in self.controls:
            control.disable()
        self.dialog.props("persistent")
        self.status.set_text("Exporting...")
        self.spinner.set_visibility(True)
        try:
            # Let an in-flight preview release its WebGL context before exporting at full DPI.
            async with self.preview_lock:
                options = dict(dpi=float(self.dpi.value or 300), transparent_background=bool(self.transparent.value),
                               include_suffixes=bool(self.suffix.value))
                if self.combo:
                    await self.controller.download_diffraction_image(filename_base=self.diffraction_filename.value, **options)
                else:
                    await self.controller.download_images(
                        bool(self.crystal.value), bool(self.diffraction.value),
                        crystal_filename_base=self.crystal_filename.value, diffraction_filename_base=self.diffraction_filename.value,
                        crystal_renderer=self.renderer.value, atom_shading=self.shading.value,
                        occupancy_colors=self.occupancy.value, **options)
        finally:
            self.busy = False
            self.dialog.props(remove="persistent")
            for control in self.controls:
                control.enable()
            self.update_controls()
            if self.dialog.value:
                self.schedule_preview()


class ThemeDialog:
    def __init__(self, simulator: "SimulatorApp") -> None:
        self.simulator = simulator
        self.loading = True
        self.busy = False
        self.theme_inputs: dict[str, Any] = {}
        self.theme_store = SavedThemeStore(SAVED_THEMES_PATH)
        self.saved_theme_name: str | None = None
        self.action_dialog = None
        storage_error = ""
        try:
            self.saved_themes = self.theme_store.read()
        except ValueError as exc:
            self.saved_themes = {}
            storage_error = str(exc)
        self.dialog = ui.dialog()
        with self.dialog, ui.card().classes("theme-card"):
            with ui.row().classes("items-center justify-between full-width"):
                ui.label("Theme").classes("text-h6")
                ui.button(icon="close", on_click=self.dialog.close).props("flat round dense").tooltip("Close")
            with ui.column().classes("theme-dialog-body full-width"):
                self.theme_preset = ui.select(self.preset_options(), label="Theme", value="Custom",
                                             on_change=self.choose_theme).props("outlined dense").classes("full-width")
                with ui.row().classes("items-center gap-1 theme-preset-actions"):
                    self.save_button = ui.button("Save theme", icon="bookmark_add", on_click=self.open_save_theme).props(
                        "outline dense").tooltip("Save a new named copy of these colors")
                    self.update_button = ui.button(icon="save", on_click=lambda: self.confirm_saved_theme_action("update")).props(
                        'flat round dense aria-label="Update saved theme"').tooltip("Update saved theme")
                    self.rename_button = ui.button(icon="edit", on_click=lambda: self.open_save_theme(rename=True)).props(
                        'flat round dense aria-label="Rename saved theme"').tooltip("Rename saved theme")
                    self.delete_button = ui.button(icon="delete", on_click=lambda: self.confirm_saved_theme_action("delete")).props(
                        'flat round dense color=negative aria-label="Delete saved theme"').tooltip("Delete saved theme")
                self.theme_dark = ui.checkbox("Dark controls", on_change=self.customize_theme)
                self.theme_dark.tooltip("Use dark styling for inputs, menus, and checkboxes; panel backgrounds are set separately.")
                with ui.grid(columns=2).classes("full-width gap-3 theme-color-grid"):
                    for name, label in THEME_COLOR_LABELS.items():
                        self.theme_inputs[name] = ui.color_input(label, preview=True, on_change=self.customize_theme).props("outlined dense")
                    self.crystal_background = ui.color_input("Crystal background", preview=True,
                        on_change=self.customize_theme).props("outlined dense")
                    self.diffraction_background = ui.color_input("Diffraction background", preview=True,
                        on_change=self.customize_theme).props("outlined dense")
                self.background_auto_text = ui.checkbox("Automatic text contrast", on_change=self.customize_theme)
                self.background_auto_text.tooltip("Use black or white annotations against each panel background. Panel-specific background overrides are kept.")
                with ui.row().classes("items-center gap-2"):
                    ui.button("White background", icon="light_mode", on_click=lambda:
                              self.set_backgrounds(PanelBackgrounds("#FFFFFF", "#FFFFFF", True))).props("outline dense")
                    ui.button("Black background", icon="dark_mode", on_click=lambda:
                              self.set_backgrounds(PanelBackgrounds("#000000", "#000000", True))).props("outline dense")
                with ui.element("div").classes("theme-sample full-width") as self.theme_sample:
                    with ui.row().classes("items-center justify-between full-width"):
                        ui.label("CrysDiS").classes("text-subtitle1")
                        ui.icon("palette").classes("theme-sample-accent").tooltip("Accent color preview")
                    with ui.row().classes("full-width no-wrap gap-2"):
                        self.crystal_sample = ui.label("Crystal").classes("theme-panel-sample")
                        self.diffraction_sample = ui.label("Diffraction").classes("theme-panel-sample")
            with ui.row().classes("full-width justify-end gap-2"):
                self.reset_button = ui.button("Reset theme", icon="restart_alt",
                    on_click=lambda: self.set_theme_draft(InterfaceTheme(), preset_name="Classic dark")).props("outline dense")
                self.apply_button = ui.button("Apply/Close", icon="check", on_click=self.apply).props("unelevated dense")
        self.set_theme_draft(simulator.theme)
        self.loading = False
        if storage_error:
            ui.notify(storage_error, type="warning")

    def preset_options(self) -> dict[str, str]:
        return {**{name: name for name in THEME_PRESETS},
                **{name: f"{name} (saved)" for name in sorted(self.saved_themes, key=str.casefold)}, "Custom": "Custom"}

    def refresh_saved_theme_controls(self) -> None:
        saved = self.saved_theme_name in self.saved_themes
        self.save_button.set_enabled(not self.busy)
        self.rename_button.set_enabled(saved and not self.busy)
        self.delete_button.set_enabled(saved and not self.busy)
        try:
            modified = saved and self.read_theme() != self.saved_themes[self.saved_theme_name]
        except (ValueError, TypeError):
            modified = False
        self.update_button.set_enabled(bool(modified) and not self.busy)

    def refresh_preset_options(self) -> None:
        loading, self.loading = self.loading, True
        value = self.theme_preset.value
        options = self.preset_options()
        self.theme_preset.set_options(options, value=value if value in options else "Custom")
        self.loading = loading

    def clear_action_dialog(self, dialog) -> None:
        if self.action_dialog is dialog:
            self.action_dialog = None

    def open_save_theme(self, *, rename: bool = False) -> None:
        if self.busy or self.action_dialog is not None:
            return
        original = self.saved_theme_name if rename else None
        if rename and original not in self.saved_themes:
            return
        try:
            theme = self.read_theme()
        except (ValueError, TypeError) as exc:
            ui.notify(f"Cannot save theme: {exc}", type="negative")
            return
        previous = copy.deepcopy(self.saved_themes.get(original))
        with self.dialog:
            dialog = self.action_dialog = ui.dialog()
        dialog.on("hide", lambda: self.clear_action_dialog(dialog))
        with dialog, ui.card().classes("theme-name-card"):
            ui.label("Rename saved theme" if rename else "Save theme").classes("text-h6")
            name = ui.input("Theme name", value=original or "").props("outlined dense autofocus maxlength=80").classes("full-width")
            error = ui.label().classes("text-negative full-width break-words")
            error.visible = False

            def save() -> None:
                try:
                    saved_name = self.theme_store.name(name.value)
                    themes = (self.theme_store.change(original, "rename", saved_name, expected=previous) if rename
                              else self.theme_store.save(saved_name, theme))
                except (OSError, ValueError, TypeError) as exc:
                    error.set_text(str(exc))
                    error.visible = True
                    return
                selected = self.theme_preset.value
                self.saved_themes = themes
                self.refresh_preset_options()
                if rename:
                    self.saved_theme_name = saved_name
                    if selected == original:
                        loading, self.loading = self.loading, True
                        self.theme_preset.value = saved_name
                        self.loading = loading
                    self.refresh_saved_theme_controls()
                else:
                    self.set_theme_draft(theme, preset_name=saved_name)
                dialog.close()
                self.clear_action_dialog(dialog)
                ui.notify("Theme renamed" if rename else "Theme saved", type="positive")

            name.on("keydown.enter", save)
            with ui.row().classes("full-width justify-end gap-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat dense")
                ui.button("Rename" if rename else "Save", icon="save", on_click=save).props("unelevated dense")
        dialog.open()

    def confirm_saved_theme_action(self, action: str) -> None:
        name = self.saved_theme_name
        if self.busy or self.action_dialog is not None or name not in self.saved_themes:
            return
        try:
            theme = self.read_theme() if action == "update" else None
        except (ValueError, TypeError) as exc:
            ui.notify(f"Cannot update theme: {exc}", type="negative")
            return
        previous = copy.deepcopy(self.saved_themes[name])
        with self.dialog:
            dialog = self.action_dialog = ui.dialog()
        dialog.on("hide", lambda: self.clear_action_dialog(dialog))
        with dialog, ui.card().classes("theme-name-card"):
            ui.label("Update saved theme?" if action == "update" else "Delete saved theme?").classes("text-h6")
            ui.label(f'Replace the saved colors in "{name}"?' if action == "update" else
                     f'Delete "{name}" from saved themes? Your current appearance will stay unchanged.').classes("full-width break-words")
            error = ui.label().classes("text-negative full-width break-words")
            error.visible = False

            def confirm() -> None:
                try:
                    themes = self.theme_store.change(name, action, theme, expected=previous)
                except (OSError, ValueError, TypeError) as exc:
                    error.set_text(str(exc))
                    error.visible = True
                    return
                self.saved_themes = themes
                self.refresh_preset_options()
                if action == "update":
                    self.set_theme_draft(theme, preset_name=name)
                else:
                    self.saved_theme_name = None
                    self.customize_theme()
                dialog.close()
                self.clear_action_dialog(dialog)
                ui.notify("Saved theme updated" if action == "update" else "Saved theme deleted", type="positive")

            with ui.row().classes("full-width justify-end gap-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat dense")
                ui.button("Update" if action == "update" else "Delete", icon="save" if action == "update" else "delete",
                          on_click=confirm).props("unelevated dense" + (" color=negative" if action == "delete" else ""))
        dialog.open()

    def read_theme(self) -> InterfaceTheme:
        return validate_theme(InterfaceTheme(dark=bool(self.theme_dark.value),
            backgrounds=PanelBackgrounds(str(self.crystal_background.value), str(self.diffraction_background.value),
                                         bool(self.background_auto_text.value)),
            **{name: control.value for name, control in self.theme_inputs.items()}))

    def set_theme_draft(self, theme: InterfaceTheme, *, preset_name: str | None = None) -> None:
        loading, self.loading = self.loading, True
        self.theme_dark.value = theme.dark
        for name, control in self.theme_inputs.items():
            control.value = getattr(theme, name)
        self.crystal_background.value = theme.backgrounds.crystal
        self.diffraction_background.value = theme.backgrounds.diffraction
        self.background_auto_text.value = theme.backgrounds.automatic_text
        presets = {**self.saved_themes, **THEME_PRESETS}
        preferred = preset_name or self.saved_theme_name
        selected = (preferred if preferred in presets and presets[preferred] == theme else
                    next((name for name, preset in presets.items() if preset == theme), "Custom"))
        self.saved_theme_name = selected if selected in self.saved_themes else None
        self.theme_preset.value = selected
        self.loading = loading
        self.update_theme_sample()
        self.refresh_saved_theme_controls()

    def set_backgrounds(self, backgrounds: PanelBackgrounds) -> None:
        loading, self.loading = self.loading, True
        self.crystal_background.value = backgrounds.crystal
        self.diffraction_background.value = backgrounds.diffraction
        self.background_auto_text.value = backgrounds.automatic_text
        self.loading = loading
        self.customize_theme()

    def choose_theme(self) -> None:
        if not self.loading:
            name = self.theme_preset.value
            presets = {**THEME_PRESETS, **self.saved_themes}
            if name in presets:
                self.set_theme_draft(presets[name], preset_name=name)

    def customize_theme(self) -> None:
        if not self.loading:
            self.theme_preset.value = "Custom"
            self.update_theme_sample()
            self.refresh_saved_theme_controls()

    def update_theme_sample(self) -> None:
        try:
            theme = self.read_theme()
        except (ValueError, TypeError):
            return
        self.theme_sample.style(f"background:{theme.surface};color:{theme.text};border-color:{theme.primary};"
                               f"--sample-accent:{theme.primary};--sample-ink:{contrast_text_color(theme.primary)}")
        for sample, background in ((self.crystal_sample, theme.backgrounds.crystal),
                                   (self.diffraction_sample, theme.backgrounds.diffraction)):
            sample.style(f"background:{background};color:{contrast_text_color(background)}")

    async def apply(self) -> None:
        if self.busy:
            return
        self.busy = True
        self.apply_button.disable()
        self.reset_button.disable()
        self.refresh_saved_theme_controls()
        try:
            if await self.simulator.apply_theme_settings(self.read_theme()):
                self.dialog.close()
        except (ValueError, TypeError, OSError) as exc:
            ui.notify(f"Cannot apply theme: {exc}", type="negative")
        finally:
            self.busy = False
            self.apply_button.enable()
            self.reset_button.enable()
            self.refresh_saved_theme_controls()


class DisplaySettingsDialog:
    """Preview private panel edits; commit them only on confirmation."""

    def __init__(self, simulator: SimulatorApp, panel_id: int | None) -> None:
        self.simulator, self.panel_id = simulator, panel_id
        self.draft = simulator.display_settings_draft(panel_id)
        if panel_id is not None:
            # Start with local edits; opening the dialog does not change live inheritance.
            self.draft.inherited.clear()
        self.loading = True
        self.busy = False
        self.preview: PanelController | None = None
        self.preview_timer = None
        self.preview_ready = False
        self.preview_closed = False
        self.preview_camera = None
        self.preview_view_limit = None
        self.settings_splitter = None
        self.preview_magnified = None
        self.preview_panes: dict[str, Any] = {}
        self.preview_magnify_buttons: dict[str, Any] = {}
        self.inherit_controls: dict[str, Any] = {}
        self.section_controls: dict[str, list[Any]] = {section: [] for section in DISPLAY_SETTING_SECTIONS}
        self.palette_containers: dict[str, Any] = {}
        self.palette_widgets: dict[str, list[tuple[Any, bool]]] = {"vector": [], "plane": []}
        self.palette_inputs: dict[str, list[Any]] = {"vector": [], "plane": []}
        self.action_buttons = []
        self.crystal_default = None
        self.element_color_inputs: dict[str, Any] = {}
        self.element_color_rows: dict[str, Any] = {}
        self.element_reset_dialog = None
        self.action_confirm_dialog = None
        self.overlay_inputs: dict[str, dict[str, Any]] = {}
        self.marker_editor = None
        self.coordinate_grid = None
        self.grid_spacing = self.grid_volume = self.grid_extent = self.grid_notice = None
        self.grid_bounds = []
        self.scale_visibility_inputs: dict[str, Any] = {}
        state = simulator.panel_state_by_id(panel_id) if panel_id is not None else None
        self.dialog = ui.dialog()
        with self.dialog, ui.card().classes("palette-card" + (" panel-settings-card" if state else "")):
            with ui.row().classes("items-center justify-between full-width"):
                title = f"Panel {panel_id} settings - {state.crystal_name}" if state else "Global display settings"
                ui.label(title).classes("text-h6 flex-1 min-w-0 break-words")
                ui.button(icon="close", on_click=self.dialog.close).props("flat round dense").tooltip("Close")
            with ui.element("div").classes("display-settings-body"):
                if state is not None:
                    with PanelViewSplitter(50, None, "Resize settings previews and controls", responsive=False).classes(
                            "panel-settings-body") as self.settings_splitter:
                        with self.settings_splitter.before:
                            self.build_preview()
                        with self.settings_splitter.after:
                            with ui.column().classes("display-settings-controls"):
                                self.build_controls(state)
                else:
                    with ui.column().classes("display-settings-controls"):
                        self.build_controls(state)
            with ui.row().classes("full-width justify-end display-settings-actions"):
                if state is not None:
                    self.action_buttons.append(ui.button("Save view", icon="bookmark_add", on_click=self.open_save_view).props("outline dense"))
                    self.action_buttons.append(ui.button("Follow global settings", icon="public", on_click=lambda: self.request_action("global")).props("outline dense"))
                self.action_buttons.append(ui.button("Reset display", icon="restart_alt", on_click=lambda: self.request_action("reset")).props("outline dense").tooltip("Restore built-in display settings; keep element colors"))
                self.action_buttons.append(ui.button("Apply/Close", icon="check", on_click=lambda: self.run_action("apply")).props("unelevated dense"))
        self.load(self.draft)
        for controls in self.section_controls.values():
            for control in controls:
                if hasattr(control, "on_value_change"):
                    control.on_value_change(self.schedule_preview)
        self.dialog.on("show", self.initialize_preview)
        self.dialog.on("hide", self.dispose_preview)

    async def open_save_view(self) -> None:
        if self.preview is None or not self.preview_ready or self.preview_closed:
            ui.notify("Wait for the settings preview before saving a view.", type="warning")
            return
        try:
            draft = self.simulator.validated_display_settings_draft(self.panel_id, self.read())
            await self.update_preview()
            camera = await self.preview.capture_camera_pose()
            if camera is None:
                raise ValueError("The preview camera is not ready. Please try again.")
            definition, payload = self.simulator.saved_view_payload(self.panel_id, draft, camera)
            views = self.simulator.view_store.for_crystal(crystal_identity(definition))
        except (ValueError, TypeError, OSError) as exc:
            ui.notify(str(exc), type="negative")
            return
        dialog = ui.dialog()
        dialog.on("hide", dialog.delete)
        with dialog, ui.card().classes("saved-view-dialog"):
            ui.label(f"Save view - {definition.name}").classes("text-h6 break-words")
            target = ui.select({"new": "New saved view", **{v["id"]: v["name"] for v in views}},
                               label="Save target", value="new").props("outlined dense").classes("full-width")
            names = {view["name"].casefold() for view in views}
            number = 1
            while f"View {number}".casefold() in names:
                number += 1
            name = ui.input("View name", value=f"View {number}").props("outlined dense maxlength=120").classes("full-width")
            default = ui.checkbox("Use as default for this crystal", value=False)
            error = ui.label("").classes("text-negative text-caption break-words")

            def change_target():
                view = next((v for v in views if v["id"] == target.value), None)
                name.value = view["name"] if view else f"View {number}"
                default.value = view["default"] if view else False
                save.text = "Update view" if view else "Save view"
                error.text = ""

            def save_view():
                try:
                    record = self.simulator.view_store.save(
                        crystal_identity(definition), crystal_version(definition), name.value, payload,
                        view_id=None if target.value == "new" else target.value, default=default.value)
                except (ValueError, OSError) as exc:
                    error.text = str(exc)
                    return
                self.simulator.refresh_crystal_list()
                self.simulator.set_status(f"Saved view: {definition.name} / {record['name']}")
                ui.notify(f"Saved view: {record['name']}", type="positive")
                dialog.close()

            with ui.row().classes("full-width justify-end gap-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat dense")
                save = ui.button("Save view", icon="save", on_click=save_view).props("unelevated dense")
            target.on_value_change(change_target)
        dialog.open()

    def build_controls(self, state: PanelState | None) -> None:
        simulator = self.simulator
        with ui.expansion("Crystal frame", icon="crop_square").classes("full-width"):
            self.inheritance_control("frame", "Use global frame settings")
            self.frame_visible = ui.checkbox("Crystal frame", on_change=lambda _: self.refresh_enabled())
            with ui.grid(columns=2).classes("full-width gap-3 panel-frame-settings"):
                self.frame_mode = ui.select({"original": "Original cell", "all": "Every cell"}, label="Frame boundaries", value="original").props("outlined dense")
                self.frame_width = ui.number("Frame thickness", value=1, min=0.25, max=MAX_FRAME_THICKNESS, step=0.25, suffix="x").props("outlined dense")
                self.frame_color = ui.color_input("Frame color", preview=True).props("outlined dense")
                self.frame_opacity = self.opacity_control("Frame opacity", self.draft.display.frame_opacity)
            self.section_controls["frame"] = [self.frame_visible, self.frame_mode, self.frame_width, self.frame_color, self.frame_opacity]
        with ui.expansion("Atom sizes", icon="bubble_chart").classes("full-width"):
            self.inheritance_control("atoms", "Use global atom settings")
            self.occupancy_colors = ui.select(OCCUPANCY_COLOR_OPTIONS, value=self.draft.display.occupancy_colors, label="Site occupancy colors").props("outlined dense").classes("full-width")
            self.occupancy_colors.tooltip("Viewer-facing sectors represent site occupancy; gray is unoccupied.")
            self.atom_scale = ui.number("All atom sizes", value=100, min=10, max=300, step=10, suffix="%").props("outlined dense").style("width: 240px; max-width: 100%; margin-bottom: 12px")
            self.atom_scale.tooltip("Radius relative to the automatic atom size; element-specific factors multiply this value.")
            elements = ({site.element for site in simulator.model_for(state.crystal_name).expanded_sites}
                        if state else set(ELEMENTS) | set(self.draft.display.element_scales))
            self.element_inputs = {}
            with ui.grid(columns=3).classes("full-width gap-3 panel-element-sizes").style("max-height: 260px; overflow-y: auto"):
                for element in sorted(elements):
                    self.element_inputs[element] = ui.number(element, value=100, min=10, max=300, step=10, suffix="%").props("outlined dense")
            self.section_controls["atoms"] = [self.atom_scale, self.occupancy_colors, *self.element_inputs.values()]
        with ui.expansion("Displayed cells", icon="grid_view").classes("full-width"):
            self.inheritance_control("cells", "Use global displayed cells")
            with ui.grid(columns=3).classes("full-width gap-3 panel-cell-counts"):
                self.cells = [ui.number(f"Cells along {axis}", value=1, min=-8, max=8, step=1).props("outlined dense")
                              for axis in ("a (x)", "b (y)", "c (z)")]
                for control in self.cells:
                    control.tooltip("Signed total cell count, including the original: 2 spans 0 to 2; -2 spans -1 to 1. Zero is invalid.")
            self.extend = ui.checkbox("Extend planes and vectors")
            self.extend.tooltip("Clip planes and extend vectors to the displayed block. Otherwise annotations stay inside the original cell.")
            self.section_controls["cells"] = [*self.cells, self.extend]
        with ui.expansion("Vector/Plane colors", icon="palette").classes("full-width"):
            self.inheritance_control("colors", "Use global colors")
            if state is None:
                self.crystal_default = ui.checkbox("Crystal default diffraction color", on_change=lambda _: self.refresh_enabled())
                self.section_controls["colors"].append(self.crystal_default)
            with ui.row().classes("items-center full-width gap-2"):
                self.diffraction_color = ui.color_input("Diffraction pattern", preview=True).props("outlined dense").classes("panel-diffraction-color")
                self.section_controls["colors"].append(self.diffraction_color)
                if state is not None:
                    reset_color = ui.button(icon="restart_alt", on_click=self.reset_diffraction_color).props("flat round dense").classes("panel-diffraction-reset").tooltip("Reset diffraction color")
                    self.section_controls["colors"].append(reset_color)
            with ui.row().classes("palette-columns"):
                self.annotation_inputs = {}
                for kind, label in (("vector", "Vectors"), ("plane", "Planes")):
                    with ui.column().classes(f"palette-column palette-{kind}-column"):
                        with ui.row().classes("items-center justify-between full-width"):
                            ui.label(label).classes("palette-title")
                            with ui.row().classes("palette-actions"):
                                reset = ui.button(icon="restart_alt", on_click=lambda k=kind: self.edit_palette(k, "reset")).props("flat round dense").tooltip(f"Reset {kind} defaults")
                                add = ui.button("Add", icon="add", on_click=lambda k=kind: self.edit_palette(k, "add")).props("outline dense")
                                self.section_controls["colors"].extend([reset, add])
                        for attribute, title in (
                            (("vector_opacity", "Vector opacity"), ("reciprocal_opacity", "Reciprocal vector opacity"))
                            if kind == "vector" else
                            (("plane_opacity", "Plane fill opacity"), ("plane_edge_opacity", "Plane edge opacity"))
                        ):
                            control = self.opacity_control(title, getattr(self.draft.display, attribute)).classes("full-width")
                            self.annotation_inputs[attribute] = control
                            self.section_controls["colors"].append(control)
                        text_size = ui.number(f"{kind.capitalize()} text size", value=100,
                            min=25, max=300, step=10, suffix="%").props("outlined dense").classes("full-width")
                        text_size.tooltip("Size relative to the original annotation text.")
                        text_opacity = self.opacity_control(f"{kind.capitalize()} text opacity",
                            getattr(self.draft.display, f"{kind}_label_opacity")).classes("full-width")
                        self.annotation_inputs[f"{kind}_label_scale"] = text_size
                        self.annotation_inputs[f"{kind}_label_opacity"] = text_opacity
                        self.section_controls["colors"].extend([text_size, text_opacity])
                        self.palette_containers[kind] = ui.element("div").classes("palette-list")
        with ui.expansion("Panel background colors", icon="format_color_fill").classes("full-width"):
            self.inheritance_control("backgrounds", "Use global background settings")
            with ui.grid(columns=2).classes("full-width gap-3 panel-background-settings"):
                self.crystal_background = ui.color_input("Crystal background", preview=True).props("outlined dense")
                self.diffraction_background = ui.color_input("Diffraction background", preview=True).props("outlined dense")
            self.background_auto_text = ui.checkbox("Automatic text contrast")
            self.background_auto_text.tooltip("Use black or white annotations against each panel background. Uncheck to restore your annotation colors.")
            with ui.row().classes("items-center gap-2"):
                white = ui.button("White background", icon="light_mode", on_click=self.white_background).props("outline dense")
                black = ui.button("Black background", icon="dark_mode", on_click=self.black_background).props("outline dense")
            self.section_controls["backgrounds"] = [self.crystal_background, self.diffraction_background,
                                                   self.background_auto_text, white, black]
        with ui.expansion("Annotations", icon="text_fields").classes("full-width"):
            self.inheritance_control("annotations", "Use global annotation settings")
            with ui.row().classes("items-center full-width gap-2"):
                for name, title in (("real_scale_visible", "Real-space scale bar"),
                                    ("reciprocal_scale_visible", "Reciprocal-space scale bar")):
                    self.scale_visibility_inputs[name] = ui.checkbox(title)
            for name, title in (("real_scale", "Real-space scale bar"), ("reciprocal_scale", "Reciprocal-space scale bar"),
                                ("zone", "Current zone"), ("indices", "Spot indices")):
                ui.label(title).classes("text-subtitle2 mt-3")
                with ui.grid(columns=2).classes("full-width gap-3 annotation-style-grid"):
                    positions = ({key: key.replace("_", " ").capitalize() for key in SPOT_LABEL_DIRECTIONS}
                                 if name == "indices" else ANNOTATION_CORNERS)
                    self.overlay_inputs[name] = {
                        "font_size": ui.number(f"{title} font size", min=6, max=40, step=1, suffix="px").props("outlined dense"),
                        "color": ui.color_input(f"{title} color", preview=True).props("outlined dense"),
                        "position": ui.select(positions, label=f"{title} position").props("outlined dense"),
                        "opacity": self.opacity_control(f"{title} opacity", 1),
                    }
            self.index_offset = ui.number("Spot label gap", min=-20, max=40, step=1, suffix="px").props("outlined dense").classes("full-width mt-3")
            self.index_offset.tooltip("Negative values move text closer and may overlap the spot; positions stop at the spot center.")
            reset = ui.button("Reset annotations", icon="restart_alt", on_click=self.reset_annotations).props("outline dense")
            self.section_controls["annotations"] = [*self.scale_visibility_inputs.values(), self.index_offset, reset,
                *(control for controls in self.overlay_inputs.values() for control in controls.values())]
        if state is None:
            with ui.expansion("Element colors", icon="science").classes("full-width"):
                with ui.row().classes("items-center full-width gap-2 element-color-tools"):
                    self.element_search = ui.input("Find element", on_change=self.filter_element_colors).props("outlined dense clearable").classes("flex-1 min-w-0")
                    ui.button("Reset element colors", icon="restart_alt", on_click=self.request_reset_element_colors).props("outline dense")
                with ui.grid(columns=3).classes("full-width gap-3 element-color-grid").style("max-height: 300px; overflow-y: auto"):
                    for element in ELEMENTS:
                        with ui.row().classes("items-center no-wrap gap-1 min-w-0") as row:
                            control = ui.color_input(element, preview=True,
                                on_change=lambda event, element=element: self.edit_element_color(element, event.value)
                            ).props("outlined dense").classes("flex-1 min-w-0")
                            ui.button(icon="restart_alt", on_click=lambda element=element: self.reset_element_colors(element)).props("flat round dense").tooltip(f"Reset {element} color")
                        self.element_color_inputs[element] = control
                        self.element_color_rows[element] = row
        if state is not None:
            with ui.expansion("Crystal markers", icon="edit_location_alt").classes("full-width"):
                self.coordinate_grid = ui.checkbox("Coordinate grid", value=False,
                                                  on_change=self.schedule_preview).props("dense")
                self.coordinate_grid.tooltip("Preview only: not included in export")
                with ui.column().classes("full-width gap-3 coordinate-grid-options").bind_visibility_from(self.coordinate_grid, "value"):
                    with ui.grid().classes("full-width gap-3 coordinate-grid-fields"):
                        self.grid_spacing = ui.select(
                            {.1: "0.1", .2: "0.2", .25: "0.25", 1/3: "1/3", .5: "0.5", 1.0: "1"},
                            label="Spacing (cell fractions)", value=.25, on_change=self.schedule_preview).props("outlined dense")
                        self.grid_extent = ui.select(
                            {"display": "Displayed cells + markers", "symmetric": "Both sides of origin", "custom": "Custom bounds"},
                            label="Grid extent", value="display", on_change=self.schedule_preview).props("outlined dense")
                    self.grid_volume = ui.checkbox("Full 3D grid", value=False, on_change=self.schedule_preview).props("dense")
                    with ui.grid(columns=2).classes("full-width gap-3 coordinate-grid-bounds").bind_visibility_from(
                            self.grid_extent, "value", backward=lambda value: value == "custom"):
                        for axis in "abc":
                            self.grid_bounds.append(tuple(ui.number(
                                f"{axis} {label}", value=value, min=-1000, max=1000, step=.25,
                                on_change=self.schedule_preview).props("outlined dense")
                                for label, value in (("min", -1), ("max", 1))))
                    self.grid_notice = ui.label("").classes("text-caption full-width break-words")
                    self.grid_notice.set_visibility(False)
                model = make_panel_display_model(simulator.model_for(state.crystal_name), state.display_settings,
                                                 simulator.element_colors_for_state(state))
                self.marker_editor = MarkerEditor(model, self.schedule_preview,
                                                  lambda: self.preview.annotation_visible("crystal") if self.preview else simulator.show_crystal_annotations(),
                                                  self.marker_pick_changed)

    @staticmethod
    def opacity_control(label: str, value: float) -> Any:
        return ui.number(label, value=100 * value, min=0, max=100, step=5, suffix="%").props("outlined dense").tooltip("0% is invisible; 100% is opaque.")

    def white_background(self) -> None:
        self.crystal_background.value = self.diffraction_background.value = "#FFFFFF"
        self.background_auto_text.value = True
        self.schedule_preview()

    def black_background(self) -> None:
        self.crystal_background.value = self.diffraction_background.value = "#000000"
        self.background_auto_text.value = True
        self.schedule_preview()

    def read_coordinate_grid(self) -> CoordinateGridSettings:
        bounds = {}
        if self.grid_extent.value == "custom":
            try:
                bounds = {"low": tuple(float(pair[0].value) for pair in self.grid_bounds),
                          "high": tuple(float(pair[1].value) for pair in self.grid_bounds)}
            except (TypeError, ValueError) as exc:
                raise ValueError("Enter all six grid bounds.") from exc
        return CoordinateGridSettings(spacing=float(self.grid_spacing.value), volume=bool(self.grid_volume.value),
                                      extent=self.grid_extent.value, **bounds)

    def load_annotations(self, settings: PanelAnnotations) -> None:
        for name, control in self.scale_visibility_inputs.items():
            control.value = getattr(settings, name)
        for name, controls in self.overlay_inputs.items():
            for field, control in controls.items():
                value = getattr(getattr(settings, name), field)
                control.value = value * 100 if field == "opacity" else value
        if self.overlay_inputs:
            self.index_offset.value = settings.index_offset

    def read_annotations(self) -> PanelAnnotations:
        settings = copy.deepcopy(self.draft.display.annotations)
        for name, control in self.scale_visibility_inputs.items():
            setattr(settings, name, bool(control.value))
        for name, controls in self.overlay_inputs.items():
            for field, control in controls.items():
                value = float(control.value) if field in {"opacity", "font_size"} else str(control.value)
                setattr(getattr(settings, name), field, value / 100 if field == "opacity" else value)
        if self.overlay_inputs:
            settings.index_offset = float(self.index_offset.value)
        return settings

    def reset_annotations(self) -> None:
        if "annotations" in self.draft.inherited:
            return
        self.load_annotations(PanelAnnotations())
        self.schedule_preview()

    def filter_element_colors(self) -> None:
        query = str(self.element_search.value or "").strip().lower()
        for element, row in self.element_color_rows.items():
            row.visible = query in element.lower()

    def edit_element_color(self, element: str, value: str) -> None:
        if not self.loading:
            self.draft.element_colors[element] = value

    def reset_element_colors(self, element: str | None = None) -> None:
        self.loading = True
        if element is None:
            self.draft.element_colors.clear()
        else:
            self.draft.element_colors.pop(element, None)
        for symbol in ([element] if element is not None else self.element_color_inputs):
            self.element_color_inputs[symbol].value = color_for_element(symbol)
        self.loading = False

    def request_reset_element_colors(self) -> None:
        if self.element_reset_dialog is not None:
            return
        customized = any(normalized_hex_color(value) != normalized_hex_color(color_for_element(element))
                         for element, value in self.draft.element_colors.items())
        if not customized:
            self.reset_element_colors()
            return
        dialog = self.element_reset_dialog = ui.dialog().props("persistent")

        def finish(confirmed: bool) -> None:
            if self.element_reset_dialog is not dialog:
                return
            self.element_reset_dialog = None
            if confirmed:
                self.reset_element_colors()
            dialog.close()

        dialog.on("hide", dialog.delete)
        with dialog, ui.card().classes("element-color-reset-card").style("width: 440px; max-width: calc(100vw - 40px)"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("warning", color="warning")
                ui.label("Reset element colors?").classes("text-h6")
            ui.label("You have customized element colors. Reset all of them? These edits will be discarded when you apply the settings.")
            with ui.row().classes("justify-end full-width gap-2"):
                ui.button("Cancel", on_click=lambda: finish(False)).props("flat")
                ui.button("Reset element colors", icon="restart_alt", on_click=lambda: finish(True)).props("unelevated")
        dialog.open()

    def build_preview(self) -> None:
        from CrysDiS_animation import export_snapshot

        source = self.simulator.controller_by_panel_id(self.panel_id)
        if source is None:
            return
        self.preview = export_snapshot(sys.modules[__name__], source, self.simulator.current_simulation_method())
        preview = self.preview
        # Reuse the frozen renderer, never a controller registered with the live app.
        preview.simulator.auto_sync_view = lambda: False
        preview.simulator.diffraction_color_for_state = lambda state: state.diffraction_color
        preview.simulator.global_diffraction_color = None
        preview.simulator.diffraction_spot_cache = self.simulator.diffraction_spot_cache.copy()
        self.preview_initial_cells = preview.state.display_settings.cells
        self.preview_initial_limit = preview.current_model.limit
        self.preview_color = None
        with ui.element("div").classes("display-settings-preview full-width") as self.preview_container:
            with ui.element("div").classes("visual-stack") as self.preview_stack:
                with ui.element("div").classes("scene-wrap settings-preview-pane settings-crystal-pane") as crystal_pane:
                    self.preview_panes["crystal"] = crystal_pane
                    preview.scene = CrystalScene(
                        width=350, height=260, grid=False, background_color=preview.state.display_settings.backgrounds.crystal,
                        camera=ui.scene.perspective_camera(fov=REAL_SCENE_FOV_DEGREES, near=0.1, far=5000),
                        on_click=self.inspect_preview_atom, click_events=["click"],
                    ).classes("real-scene settings-preview-scene")
                    preview.build_atom_inspector()
                    self.build_preview_magnify_button("crystal")
                    # The dialog unmounts its canvas before its server-side hide callback.
                    preview.scene.on("init", js_handler=f"""() => {{
                        const scene = getElement({preview.scene.id});
                        if (!scene?.renderer) return;
                        const observer = new MutationObserver(() => {{
                            if (scene.$el.isConnected) return;
                            observer.disconnect();
                            scene.camera_tween?.stop();
                            scene.controls.dispose();
                            scene.drag_controls.dispose();
                            scene.scene.traverse(o => {{
                                o.geometry?.dispose();
                                for (const m of (Array.isArray(o.material) ? o.material : [o.material])) {{
                                    m?.map?.dispose(); m?.dispose();
                                }}
                            }});
                            scene.renderer.render = scene.controls.update = () => {{}};
                            scene.text_renderer.render = scene.text3d_renderer.render = () => {{}};
                            scene.renderer.dispose();
                            scene.renderer.forceContextLoss();
                            scene.scene.clear();
                            scene.objects.clear();
                            delete window['scene_c{preview.scene.id}'];
                        }});
                        observer.observe(document.body, {{childList: true, subtree: true}});
                    }}""")
                    with ui.element("div").classes("real-scale-bar") as preview.scale_bar_container:
                        preview.scale_bar_line = ui.element("div").classes("real-scale-line")
                        preview.scale_bar_label = ui.label("").classes("real-scale-label")
                with ui.element("div").classes("settings-preview-pane settings-diffraction-pane") as diffraction_pane:
                    self.preview_panes["diffraction"] = diffraction_pane
                    preview.diffraction = ui.plotly(empty_diffraction_figure()).classes("diffraction-plot settings-preview-diffraction")
                    self.build_preview_magnify_button("diffraction")
            self.preview_error = ui.label("Loading preview...").classes("text-caption text-grey-5 full-width break-words")

    def marker_pick_changed(self, active: bool) -> None:
        if self.preview is None or self.preview_closed:
            return
        self.preview.scene.classes(add="marker-picking" if active else "", remove="" if active else "marker-picking")
        if active:
            self.preview.hide_atom_inspector()
            if self.preview_magnified == "diffraction":
                self.toggle_preview_magnified("crystal")

    def inspect_preview_atom(self, event) -> None:
        if self.preview is None or self.preview_closed:
            return
        atom = self.preview.atom_at_click(event)
        if atom is not None and self.marker_editor is not None and self.marker_editor.pick_from_scene(atom, self.preview.current_model):
            self.preview.hide_atom_inspector()
            return
        self.preview.inspect_atom(event)

    def build_preview_magnify_button(self, kind: str) -> None:
        self.preview_magnify_buttons[kind] = ui.button(icon="open_in_full",
            on_click=lambda: self.toggle_preview_magnified(kind)).props(
                f"flat round dense aria-label='Magnify {kind} preview'"
            ).classes(f"preview-magnify preview-magnify-{kind}").tooltip(f"Magnify/shrink {kind} preview")

    def toggle_preview_magnified(self, kind: str) -> None:
        if self.preview_closed or kind not in self.preview_panes:
            return
        self.preview_magnified = None if self.preview_magnified == kind else kind
        if self.preview_magnified is None:
            self.preview_stack.classes(remove="preview-expanded")
        else:
            self.preview_stack.classes(add="preview-expanded")
        for name, pane in self.preview_panes.items():
            pane.set_visibility(self.preview_magnified in (None, name))
            expanded = self.preview_magnified == name
            self.preview_magnify_buttons[name].props(
                f"icon={'close_fullscreen' if expanded else 'open_in_full'} "
                f"aria-label='{'Restore split previews' if expanded else f'Magnify {name} preview'}'")
        if self.preview is not None and core.is_loop_running():
            ui.run_javascript(f"""
                const resize = () => {{
                    const scene = getElement({self.preview.scene.id});
                    if (scene?.$el.clientHeight && scene.$el.clientWidth) scene.resize();
                    const plot = getElement({self.preview.diffraction.id});
                    if (plot?.$el.clientHeight && plot.$el.clientWidth) plot.Plotly?.Plots.resize(plot.$el);
                }};
                requestAnimationFrame(() => {{resize(); setTimeout(resize, 120);}});
            """)

    async def initialize_preview(self) -> None:
        if self.preview is None or self.preview_closed:
            return
        preview = self.preview
        source = self.simulator.controller_by_panel_id(self.panel_id)
        try:
            await asyncio.wait_for(preview.scene.initialized(), timeout=5)
            if self.preview_closed:
                return
            if source is not None and source.scene is not None:
                self.preview_camera = await ui.run_javascript(f"""
                    const source = getElement({source.scene.id});
                    if (!source?.camera) return null;
                    return {{position: source.camera.position.toArray(), up: source.camera.up.toArray(),
                             target: source.controls.target.toArray(), zoom: source.camera.zoom}};
                """, timeout=3)
            if self.preview_closed:
                return
            self.preview_ready = True
            await self.update_preview()
            with self.dialog:
                preview.scale_timer = ui.timer(0.7, preview.update_scene_scale_bar)
        except (TimeoutError, RuntimeError) as exc:
            if not self.preview_closed:
                self.preview_error.set_text(f"Preview unavailable: {exc}")

    def schedule_preview(self) -> None:
        if self.loading or not self.preview_ready or self.preview_closed:
            return
        if self.preview_timer is not None:
            self.preview_timer.cancel()
        with self.dialog:
            self.preview_timer = ui.timer(0.15, self.update_preview, once=True)

    async def update_preview(self) -> None:
        if self.preview is None or not self.preview_ready or self.preview_closed:
            return
        preview = self.preview
        markers, marker_errors = self.marker_editor.read_preview() if self.marker_editor is not None else (None, [])
        hidden_markers = self.marker_editor is not None and len(markers) < len(self.marker_editor.rows)
        notice = ""
        try:
            draft = self.simulator.validated_display_settings_draft(self.panel_id, self.read(preview_markers=markers))
        except (ValueError, TypeError, OverflowError) as exc:
            if not hidden_markers:
                self.preview_error.set_text(f"Preview unchanged: {exc}")
                self.preview_error.visible = True
                return
            # Even when another field is unfinished, do not leave an invalid marker on screen.
            draft = DisplaySettingsDraft(
                display=replace(preview.state.display_settings, markers=markers),
                vector_colors=preview.simulator.vector_palette(), plane_colors=preview.simulator.plane_palette(),
                diffraction_color=preview.state.diffraction_color,
                panel_element_colors=copy.deepcopy(preview.state.element_colors),
                annotation_visibility=preview.state.annotation_visibility.copy())
            notice = f"Other preview settings unchanged: {exc} "
        try:
            colors = self.simulator.element_colors if draft.panel_element_colors is None else draft.panel_element_colors
            model = preview.display_model(settings=draft.display, element_colors=colors)
        except (ValueError, TypeError, OverflowError) as exc:
            self.preview_error.set_text(f"Preview unchanged: {exc}")
            self.preview_error.visible = True
            return
        initial_view = preview.scene_signature is None
        previous_limit = self.preview_view_limit or preview.current_model.limit
        annotations_changed = (draft.display.annotations != preview.state.display_settings.annotations or
                               draft.display.backgrounds != preview.state.display_settings.backgrounds or
                               draft.annotation_visibility != preview.state.annotation_visibility)
        preview.state.display_settings = draft.display
        preview.state.element_colors = colors.copy()
        preview.state.annotation_visibility = draft.annotation_visibility.copy()
        preview.state.diffraction_color = draft.diffraction_color or self.simulator.default_diffraction_color_for_crystal(preview.state.crystal_name)
        preview.state.diffraction_color_custom = draft.diffraction_color is not None
        for kind in ("vector", "plane"):
            colors = getattr(draft, f"{kind}_colors").copy()
            setattr(preview.simulator, f"{kind}_palette", lambda _id=None, colors=colors: colors)
        preview.coordinate_grid_enabled = bool(self.coordinate_grid and self.coordinate_grid.value)
        grid_notice = ""
        if preview.coordinate_grid_enabled:
            try:
                preview.coordinate_grid_settings = self.read_coordinate_grid()
            except (TypeError, ValueError) as exc:
                grid_notice = f"Grid unchanged: {exc}"
        preview.redraw_scene(model, update_camera=False)
        if preview.coordinate_grid_enabled and not grid_notice:
            requested = preview.coordinate_grid_settings.spacing
            if requested is not None and preview.coordinate_grid_step > requested * (1 + 1e-10):
                grid_notice = f"Effective grid spacing: {preview.coordinate_grid_step:g} (density limit)"
        if self.grid_notice is not None:
            self.grid_notice.set_text(grid_notice)
            self.grid_notice.set_visibility(bool(grid_notice))
        self.preview_view_limit = max(model.limit, preview.coordinate_grid_limit or 0) if preview.coordinate_grid_enabled else model.limit
        if self.marker_editor is not None:
            self.marker_editor.update_model(model)
        preview.apply_scale_bar_visibility()
        if self.preview_color != preview.state.diffraction_color or annotations_changed:
            preview.redraw_diffraction()
            self.preview_color = preview.state.diffraction_color
        if initial_view or not math.isclose(previous_limit, self.preview_view_limit):
            if initial_view:
                self.position_preview_camera()
                if self.preview_view_limit > model.limit:
                    self.resize_preview_camera(model.limit, self.preview_view_limit)
            else:
                self.resize_preview_camera(previous_limit, self.preview_view_limit)
        if marker_errors:
            notice += f"{len(marker_errors)} invalid marker{'s' if len(marker_errors) != 1 else ''} hidden."
        self.preview_error.set_text(notice)
        self.preview_error.visible = bool(notice)

    def resize_preview_camera(self, previous_limit: float, limit: float) -> None:
        # Keep the user's orbit, pan and zoom when a larger marker/cell block needs more room.
        ratio = float(limit / max(previous_limit, 1e-9))
        ui.run_javascript(f"""
            const scene = getElement({self.preview.scene.id});
            if (scene?.camera && scene.controls) {{
                const target = scene.controls.target;
                scene.camera.position.sub(target).multiplyScalar({ratio}).add(target);
                scene.camera.far = Math.max(5000, scene.camera.position.length() + {3 * limit});
                scene.camera.updateProjectionMatrix();
                scene.controls.update();
            }}
        """)

    def position_preview_camera(self) -> None:
        preview = self.preview
        pose = self.preview_camera
        if pose is None:
            preview.position_scene_camera(preview.current_model, preview.state.view_vector, preview.state.roll)
            return
        position, up, target = (np.array(pose[key], dtype=float) for key in ("position", "up", "target"))
        zoom = pose["zoom"]
        if (preview.state.display_settings.cells != self.preview_initial_cells
                or preview.current_model.limit != self.preview_initial_limit):
            view = normalize_vector(position)
            if view is None:
                view = normalize_vector(preview.state.view_vector)
            roll = roll_from_view_and_up(view, up, preview.state.roll)
            _, up = projection_basis(view, roll)
            position = view * calculate_camera_distance(preview.current_model.limit * 1.08, REAL_SCENE_FOV_DEGREES)
            target, zoom = np.zeros(3), 1.0
        preview.scene.move_camera(
            x=float(position[0]), y=float(position[1]), z=float(position[2]),
            look_at_x=float(target[0]), look_at_y=float(target[1]), look_at_z=float(target[2]),
            up_x=float(up[0]), up_y=float(up[1]), up_z=float(up[2]), duration=0,
        )
        ui.run_javascript(f"""
            const scene = getElement({preview.scene.id});
            if (scene?.camera) {{scene.camera.zoom = {float(zoom)}; scene.camera.far = {max(5000, float(np.linalg.norm(position)) + preview.current_model.limit * 3)}; scene.resize();}}
        """)
        preview.set_scale_bar_from_distance(float(np.linalg.norm(position)), preview.current_model)

    def dispose_preview(self) -> None:
        self.preview_closed = True
        self.preview_ready = False
        if self.marker_editor is not None:
            self.marker_editor.cancel_pick()
        if self.action_confirm_dialog is not None:
            dialog, self.action_confirm_dialog = self.action_confirm_dialog, None
            dialog.close()
        if self.preview_timer is not None:
            self.preview_timer.cancel()
        if self.preview is not None:
            if self.preview.scale_timer is not None:
                self.preview.scale_timer.cancel(with_current_invocation=True)
            self.preview_container.clear()
            self.preview = None

    def inheritance_control(self, section: str, label: str) -> None:
        if self.panel_id is not None:
            self.inherit_controls[section] = ui.checkbox(label, on_change=lambda event: self.change_inheritance(section, event.value))

    def change_inheritance(self, section: str, follow: bool) -> None:
        if self.loading:
            return
        if follow:
            self.draft.inherited.add(section)
            defaults = self.simulator.display_settings_draft()
            self.draft.display = inherited_display_settings(self.draft.display, defaults.display, {section})
            if section == "colors":
                self.draft.vector_colors, self.draft.plane_colors = defaults.vector_colors, defaults.plane_colors
                self.draft.diffraction_color = defaults.diffraction_color
            self.load_section(section)
        else:
            self.draft.inherited.discard(section)
        self.refresh_enabled()
        self.schedule_preview()

    def load(self, draft: DisplaySettingsDraft) -> None:
        self.loading = True
        self.draft = copy.deepcopy(draft)
        for section, control in self.inherit_controls.items():
            control.value = section in draft.inherited
        for section in DISPLAY_SETTING_SECTIONS:
            self.load_section(section)
        for element, control in self.element_color_inputs.items():
            control.value = self.draft.element_colors.get(element, color_for_element(element))
        if self.marker_editor is not None:
            self.marker_editor.load(self.draft.display.markers)
        self.loading = False
        self.refresh_enabled()
        self.schedule_preview()

    def load_section(self, section: str) -> None:
        settings = self.draft.display
        if section == "frame":
            self.frame_visible.value = settings.frame_mode != "hidden"
            self.frame_mode.value = "original" if settings.frame_mode == "hidden" else settings.frame_mode
            self.frame_width.value, self.frame_color.value = settings.frame_width, settings.frame_color
            self.frame_opacity.value = 100 * settings.frame_opacity
        elif section == "atoms":
            self.atom_scale.value = 100 * settings.atom_scale
            self.occupancy_colors.value = settings.occupancy_colors
            for element, control in self.element_inputs.items():
                control.value = 100 * settings.element_scales.get(element, 1.0)
        elif section == "cells":
            for value, control in zip(settings.cells, self.cells):
                control.value = value
            self.extend.value = settings.extend_annotations
        elif section == "annotations":
            self.load_annotations(settings.annotations)
        elif section == "backgrounds":
            self.crystal_background.value = settings.backgrounds.crystal
            self.diffraction_background.value = settings.backgrounds.diffraction
            self.background_auto_text.value = settings.backgrounds.automatic_text
        else:
            for attribute, control in self.annotation_inputs.items():
                control.value = 100 * getattr(settings, attribute)
            if self.crystal_default is not None:
                self.crystal_default.value = self.draft.diffraction_color is None
            state = self.simulator.panel_state_by_id(self.panel_id) if self.panel_id is not None else None
            fallback = self.simulator.default_diffraction_color_for_crystal(state.crystal_name if state else "FCC")
            self.diffraction_color.value = self.draft.diffraction_color or fallback
            self.refresh_palette("vector")
            self.refresh_palette("plane")

    def refresh_enabled(self) -> None:
        if self.loading:
            return
        for section, controls in self.section_controls.items():
            for control in controls:
                control.set_enabled(section not in self.draft.inherited)
        self.frame_mode.set_enabled("frame" not in self.draft.inherited and self.frame_visible.value)
        use_default = self.crystal_default is not None and self.crystal_default.value
        self.diffraction_color.set_enabled("colors" not in self.draft.inherited and not use_default)
        for widgets in self.palette_widgets.values():
            for widget, allowed in widgets:
                widget.set_enabled(allowed and "colors" not in self.draft.inherited)

    def reset_diffraction_color(self) -> None:
        state = self.simulator.panel_state_by_id(self.panel_id)
        if state is None or "colors" in self.draft.inherited:
            return
        self.draft.diffraction_color = None
        self.diffraction_color.value = self.simulator.default_diffraction_color_for_crystal(state.crystal_name)

    def refresh_palette(self, kind: str) -> None:
        colors = getattr(self.draft, f"{kind}_colors")
        container = self.palette_containers[kind]
        container.clear()
        self.palette_inputs[kind], self.palette_widgets[kind] = [], []
        with container:
            for index, color in enumerate(colors):
                with ui.element("div").classes("palette-row"):
                    ui.label(str(index + 1)).classes("palette-index")
                    control = ui.color_input(value=color, preview=True).props("outlined dense").classes("palette-color-input")
                    control.on_value_change(self.schedule_preview)
                    self.palette_inputs[kind].append(control)
                    self.palette_widgets[kind].append((control, True))
                    for action, icon, tooltip, allowed in (
                        ("up", "arrow_upward", "Move up", index > 0),
                        ("down", "arrow_downward", "Move down", index < len(colors) - 1),
                        ("delete", "delete", "Remove color", len(colors) > 1),
                    ):
                        button = ui.button(icon=icon, on_click=lambda k=kind, a=action, i=index: self.edit_palette(k, a, i)).props("flat round dense" + (" color=negative" if action == "delete" else "")).tooltip(tooltip)
                        self.palette_widgets[kind].append((button, allowed))
        self.refresh_enabled()

    def edit_palette(self, kind: str, action: str, index: int = 0) -> None:
        if "colors" in self.draft.inherited:
            return
        colors = [str(control.value) for control in self.palette_inputs[kind]]
        defaults = self.simulator.palette_default_values(kind)
        if action == "reset":
            colors = defaults.copy()
            display_defaults = PanelDisplaySettings()
            attributes = (("vector_opacity", "reciprocal_opacity") if kind == "vector"
                          else ("plane_opacity", "plane_edge_opacity"))
            attributes += (f"{kind}_label_scale", f"{kind}_label_opacity")
            for attribute in attributes:
                value = getattr(display_defaults, attribute)
                setattr(self.draft.display, attribute, value)
                self.annotation_inputs[attribute].value = 100 * value
        elif action == "add":
            colors.append(defaults[len(colors) % len(defaults)])
        elif action == "delete" and len(colors) > 1:
            colors.pop(index)
        elif action in {"up", "down"}:
            other = min(max(index + (-1 if action == "up" else 1), 0), len(colors) - 1)
            colors[index], colors[other] = colors[other], colors[index]
        setattr(self.draft, f"{kind}_colors", colors)
        self.refresh_palette(kind)
        self.schedule_preview()

    def read(self, *, preview_markers: list[CrystalMarker] | None = None) -> DisplaySettingsDraft:
        draft = copy.deepcopy(self.draft)
        draft.inherited = {section for section, control in self.inherit_controls.items() if control.value}
        settings = draft.display
        if "backgrounds" not in draft.inherited:
            settings.backgrounds = PanelBackgrounds(str(self.crystal_background.value),
                str(self.diffraction_background.value), bool(self.background_auto_text.value))
        if self.marker_editor is not None:
            settings.markers = self.marker_editor.read() if preview_markers is None else preview_markers
        if "annotations" not in draft.inherited:
            settings.annotations = self.read_annotations()
        if "frame" not in draft.inherited:
            settings.frame_mode = self.frame_mode.value if self.frame_visible.value else "hidden"
            settings.frame_color, settings.frame_width = str(self.frame_color.value), float(self.frame_width.value)
            settings.frame_opacity = float(self.frame_opacity.value) / 100
        if "atoms" not in draft.inherited:
            settings.atom_scale = float(self.atom_scale.value) / 100
            settings.occupancy_colors = self.occupancy_colors.value
            for element, control in self.element_inputs.items():
                factor = float(control.value) / 100
                if factor == 1:
                    settings.element_scales.pop(element, None)
                else:
                    settings.element_scales[element] = factor
        if "cells" not in draft.inherited:
            settings.cells = tuple(control.value for control in self.cells)
            settings.extend_annotations = bool(self.extend.value)
        if "colors" not in draft.inherited:
            for attribute, control in self.annotation_inputs.items():
                setattr(settings, attribute, float(control.value) / 100)
            use_default = self.crystal_default is not None and self.crystal_default.value
            if self.crystal_default is None and self.draft.diffraction_color is None:
                state = self.simulator.panel_state_by_id(self.panel_id)
                fallback = self.simulator.default_diffraction_color_for_crystal(state.crystal_name)
                use_default = str(self.diffraction_color.value).upper() == fallback.upper()
            draft.diffraction_color = None if use_default else str(self.diffraction_color.value)
            for kind, controls in self.palette_inputs.items():
                setattr(draft, f"{kind}_colors", [str(control.value) for control in controls])
        return draft

    def request_action(self, action: str) -> None:
        if self.busy or self.action_confirm_dialog is not None:
            return
        follow = action == "global"
        title = "Follow global settings?" if follow else "Reset display?"
        message = ("Replace this panel's display settings with the global defaults and follow future global changes?"
                   if follow else "Restore the built-in display settings?")
        message += (" Crystal markers will be kept. Saved-view color and visibility overrides will follow global settings." if follow
                    else " Crystal markers will be removed. Element colors will be kept.")
        if self.panel_id is not None:
            message += " The real panel will not change until you click Apply/Close."
        dialog = self.action_confirm_dialog = ui.dialog().props("persistent")

        async def finish(confirmed: bool) -> None:
            if self.action_confirm_dialog is not dialog:
                return
            self.action_confirm_dialog = None
            dialog.close()
            if confirmed and not self.preview_closed:
                await self.run_action(action)

        dialog.on("hide", dialog.delete)
        with dialog, ui.card().classes("display-action-confirm").style("width: 460px; max-width: calc(100vw - 40px)"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("warning", color="warning")
                ui.label(title).classes("text-h6")
            ui.label(message)
            with ui.row().classes("justify-end full-width gap-2"):
                ui.button("Cancel", on_click=lambda: finish(False)).props("flat")
                ui.button("Follow global settings" if follow else "Reset display",
                    icon="public" if follow else "restart_alt", on_click=lambda: finish(True)).props("unelevated")
        dialog.open()

    async def run_action(self, action: str) -> None:
        if self.busy:
            return
        self.busy = True
        for button in self.action_buttons:
            button.disable()
        try:
            if action == "reset":
                # Reset live display defaults without committing or discarding pending element edits.
                colors = self.simulator.element_colors if self.panel_id is None else self.draft.element_colors
                draft = DisplaySettingsDraft(element_colors=colors.copy())
                draft.panel_element_colors = copy.deepcopy(self.draft.panel_element_colors)
            elif action == "global":
                draft = self.simulator.display_settings_draft()
                draft.inherited = set(DISPLAY_SETTING_SECTIONS)
            else:
                draft = self.read()
            if action == "global" and self.marker_editor is not None:
                draft.display.markers = self.marker_editor.read()
            if self.panel_id is not None and action != "apply":
                self.load(draft)
            elif await self.simulator.apply_display_settings_draft(self.panel_id, draft):
                if action == "apply":
                    self.dialog.close()
                    return
                refreshed = self.simulator.display_settings_draft(self.panel_id)
                refreshed.element_colors = self.draft.element_colors.copy()
                self.load(refreshed)
        except (ValueError, TypeError, OSError) as exc:
            ui.notify(f"Cannot apply display settings: {exc}", type="negative")
        finally:
            self.busy = False
            for button in self.action_buttons:
                button.enable()


class SimulatorApp:
    def __init__(self) -> None:
        self.element_colors = load_element_colors()
        self.theme = load_theme()
        self.theme_style = None
        self.theme_colors = None
        self.theme_editor: ThemeDialog | None = None
        self.library = CrystalLibrary()
        self.view_store = DisplayPresetStore(DISPLAY_PRESETS_PATH)
        self.expanded_crystal_views: set[str] = set()
        self.saved_view_warnings: set[str] = set()
        self.model_cache: dict[tuple[str, str], CrystalModel] = {}
        self.reciprocal_table_cache: dict[tuple[str, int], tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        self.diffraction_spot_cache: dict[tuple[Any, ...], np.ndarray] = {}
        self.pymatgen_tem_cache: dict[tuple[Any, ...], np.ndarray] = {}
        self.panel_states = [PanelState(panel_id=1)]
        self.combo_panel_states: list[ComboPanelState] = []
        self.layout_items: list[tuple[str, int]] = [("panel", 1)]
        self.next_panel_id = 2
        self.next_combo_id = 1
        self.controllers: list[PanelController] = []
        self.combo_controllers: list[ComboPanelController] = []
        self.panels_container = None
        self.log_box = None
        self.status_history = ["Ready"]
        self.dark_mode = None
        self.show_indices_input = None
        self.show_scale_bar_input = None
        self.scale_bars_enabled = True
        self.show_crystal_annotations_input = None
        self.add_combo_button = None
        self.advanced_dialog = None
        self.intro_dialog = None
        self.palette_dialog = None
        self.display_settings_editor: DisplaySettingsDialog | None = None
        self.cif_dialog = None
        self.crystal_list_dialog = None
        self.crystal_list_container = None
        self.simulation_method_input = None
        self.voltage_input = None
        self.thickness_input = None
        self.max_hkl_input = None
        self.spot_threshold_input = None
        self.spot_size_scaling_input = None
        self.intensity_compression_input = None
        self.uniform_spot_brightness_input = None
        self.camera_length_input = None
        self.snap_back_input = None
        self.hex_four_index_input = None
        self.auto_sync_input = None
        self.show_zone_axis_input = None
        self.vector_colors = VECTOR_COLORS.copy()
        self.plane_colors = PLANE_COLORS.copy()
        self.global_display_settings = PanelDisplaySettings(backgrounds=copy.deepcopy(self.theme.backgrounds))
        self.panel_states[0].display_settings = copy.deepcopy(self.global_display_settings)
        self.global_diffraction_color: str | None = None
        self.selected_export_dir: Path | None = None
        self.builder: CrystalBuilder | None = None
        self.apply_default_saved_view(self.panel_states[0])

    def build(self) -> None:
        ui.page_title("CrysDiS")
        self.dark_mode = ui.dark_mode(value=self.theme.dark)
        self.add_styles()
        self.theme_style = ui.html("", sanitize=False).style("display:none")
        self.apply_interface_theme()
        with ui.header().classes("app-header items-center"):
            ui.label("CrysDiS").classes("app-title")
            ui.button("Intro", icon="help_outline", on_click=self.open_intro_dialog).props("flat dense").classes("intro-button")
            ui.space()
            self.show_zone_axis_input = ui.checkbox(
                "Current zone",
                value=False,
                on_change=lambda _: self.on_annotation_visibility_changed("zone"),
            ).classes("top-checkbox")
            self.show_indices_input = ui.checkbox(
                "Spot indices",
                value=False,
                on_change=lambda _: self.on_annotation_visibility_changed("indices"),
            ).classes("top-checkbox")
            self.show_crystal_annotations_input = ui.checkbox(
                "Crystal annotations",
                value=True,
                on_change=lambda _: self.on_annotation_visibility_changed("crystal"),
            ).classes("top-checkbox")
            self.show_scale_bar_input = ui.checkbox(
                "Scale bar",
                value=True,
                on_change=lambda _: self.on_scale_bar_changed(),
            ).classes("top-checkbox")
            ui.button("Advanced", icon="tune", on_click=lambda: self.advanced_dialog.open()).props("flat dense")
            ui.button("Crystal list", icon="format_list_bulleted", on_click=self.open_crystal_list).props("flat dense")
            ui.button("Load CIF", icon="upload_file", on_click=lambda: self.cif_dialog.open()).props("flat dense")
            ui.button(
                "New crystal",
                icon="add_box",
                on_click=lambda: self.builder.open(mode="new"),
            ).props("flat dense")
            self.add_combo_button = ui.button(
                "Add combo panel",
                icon="join_inner",
                on_click=self.add_combo_panel,
            ).props("flat dense")
            ui.button("Add panel", icon="splitscreen", on_click=self.add_panel).props("unelevated dense")

        with ui.element("main").classes("app-shell"):
            self.panels_container = ui.element("div").classes("panel-grid")

        self.builder = CrystalBuilder(self)
        self.build_advanced_dialog()
        self.build_intro_dialog()
        self.build_cif_dialog()
        self.build_crystal_list_dialog()
        self.update_add_combo_button()
        self.build_panels()
        ui.timer(0.5, self.prewarm_builtin_zone_axis_cache, once=True, immediate=False)

    def apply_interface_theme(self) -> None:
        if self.dark_mode is not None:
            self.dark_mode.value = self.theme.dark
        if self.theme_style is not None:
            if self.theme_colors is not None:
                self.theme_colors.delete()
            with self.theme_style.parent_slot:
                self.theme_colors = ui.colors(primary=self.theme.primary, secondary=self.theme.secondary,
                                             dark=self.theme.surface, dark_page=self.theme.page)
            self.theme_style.set_content(f"<style>{theme_css(self.theme)}</style>")

    async def prewarm_builtin_zone_axis_cache(self) -> None:
        await asyncio.to_thread(self._prewarm_builtin_zone_axis_cache)

    def _prewarm_builtin_zone_axis_cache(self) -> None:
        for definition in DEFAULT_CRYSTALS.values():
            try:
                model = make_model(definition)
                zone_axis_candidate_table(model, DEFAULT_ZONE_AXIS_SEARCH_MAX)
            except Exception:
                continue

    def open_intro_dialog(self) -> None:
        if self.intro_dialog is not None:
            self.intro_dialog.open()

    def build_intro_dialog(self) -> None:
        self.intro_dialog = ui.dialog()
        with self.intro_dialog, ui.card().classes("intro-card"):
            with ui.row().classes("items-center justify-between full-width"):
                ui.label("Introduction").classes("text-h6")
                ui.button(icon="close", on_click=self.intro_dialog.close).props("flat round dense").tooltip("Close")
            ui.markdown(
                """
### What this simulator does
CrysDiS represents **Crystal Diffraction Simulator**.

Compare a real-space crystal view with its electron diffraction pattern. Each ordinary panel has the crystal on the left and the diffraction pattern on the right.

### Basic workflow
1. Choose a crystal, enter a zone axis such as `100`, `110`, or `0001`, then press `Apply` or Enter. Zone axis and Rotation clear after execution; when both are entered, the zone axis is applied first.
2. Add planes like `100 123` and vectors like `110 -1-1-2` in the panel inputs.
3. Use the mouse to rotate the 3D crystal. Press `Sync` to update the diffraction pattern to the current crystal view.
4. Use `Download` to export the crystal view, diffraction pattern, or both.

### Crystals
- Built-in examples include FCC Ni, BCC Fe, and HCP Mg.
- `Load CIF` imports structures from `.cif` files.
- `New Crystal` lets you create or edit custom structures, set symmetry, lattice parameters, atom sites, occupancies, and atom colors.
- `Crystal list` lets you review, edit, export, or delete available structures.

### Chemical formulas
The formula at the bottom left of the crystal builder is calculated after symmetry expansion, with each element weighted by its site occupancy. The cycle button switches between:

- **Unit cell:** total elemental amounts in one unit cell, such as `Fe14Cr16`.
- **Reduced:** the simplest whole-number elemental ratio, such as `Fe7Cr8`.
- **Atomic fraction:** elemental amounts normalized to 1, such as `Fe0.467Cr0.533`. Subscripts are rounded to three decimal places and balanced to sum to 1.000.
- **Site occupancies:** available when any occupancy differs from 1. Elements sharing a position are grouped, identical occupation patterns are combined, and outer coefficients give reduced integer site counts. For example, `(Fe0.2Mn0.2Ni0.6)3Ti`; different occupation patterns remain separate. Inner occupancies are rounded to three decimal places without normalization.

Extra drawings on opposite cell boundaries are not counted again in the formula. Boundary atoms themselves are included: an FCC cell shows eight corners and six face centers, contributing `8 x 1/8 + 6 x 1/2 = 4` atoms per unit cell. This geometric sharing is separate from chemical occupancy; a fully occupied corner site still has occupancy 1.

Both builder Save buttons and **Export as CIF** check the sum of occupancies at each position after symmetry expansion. Totals differing from 1 by more than 0.000001 trigger a warning. **Cancel** returns to editing without saving or exporting; **Continue saving** or **Continue exporting** keeps the entered values unchanged, including intentional vacancies. Continuing an export opens the filename and symmetry options. Neither action normalizes occupancies automatically.

### Indices and vectors
- Plane indices use entries like `100`, `1-10`, or `0001`.
- Real-space vectors use entries like `110` or `2-1-10`.
- Reciprocal vectors can be entered as `*100`, `r100`, or `R100`.
- Negative real-space vectors are shifted back into the unit cell for cleaner visualization.

### Diffraction settings
- `Spot indices` labels diffraction spots.
- `Current zone` prints the current or nearest zone axis on the diffraction panel.
- Diffraction spot colors default to the panel crystal color and can be reassigned per panel. Combo panels keep each source pattern in its own panel color so overlapping phases can be distinguished.
- `Advanced` contains simulation method, voltage, thickness, max hkl, camera length, intensity threshold, spot scaling, intensity compression, auto sync, snap-back view, and hexagonal four-index labeling.
- `Uniform spot brightness` in Advanced gives every surviving reflection the same brightness. The threshold still uses compressed relative intensities, and the `Compression factor` remains adjustable from 10 to 200 in either brightness mode. Switching brightness modes does not change which spots pass the threshold. Spot sizes remain independently intensity-scaled; set `Spot size scaling effect` to zero for equal-sized spots. This setting also applies to combo patterns, image previews, and exports.
- `Spot intensity threshold` accepts scientific notation down to `1e-10`; its default is `1e-4`. This is a visibility cutoff after compression, not a test of whether a reflection is symmetry-forbidden. The Ewald method's separate raw-intensity cutoff is unchanged. Hover over the Advanced controls for help.
- Diffraction hover labels show relative intensities below `0.01` in scientific notation, such as `1e-5` or `1.235e-5`. Larger values retain four decimal places; exact zero is shown as `0`. This formatting does not change the calculated intensity.

### Combo panels
Use `Add combo panel` to overlay diffraction patterns from multiple ordinary panels. This is useful for multiphase comparisons.
Enable `Bind crystal motion` inside a combo panel after manually setting an orientation relationship; later Apply, Sync, or auto-sync motion from any listed panel is applied as the same view-frame motion to the other listed panels.

### Display controls
- `Scale bar` toggles scale bars in both crystal and diffraction panels.
- `Crystal annotations` toggles vector and plane labels in the 3D crystal view.
- `Panel colors` sets the panel's diffraction color and vector/plane palettes. `Palette for vectors/planes` in Advanced sets global defaults; local palettes can return to these with `Use global default`.
                """
            ).classes("intro-text")

    def build_advanced_dialog(self) -> None:
        self.advanced_dialog = ui.dialog()
        with self.advanced_dialog, ui.card().classes("advanced-card"):
            with ui.row().classes("items-center justify-between full-width"):
                ui.label("Advanced settings").classes("text-h6")
                close_button = ui.button(icon="close", on_click=self.advanced_dialog.close).props("flat round dense")
            with ui.column().classes("advanced-body"):
                with ui.grid(columns=2).classes("advanced-grid"):
                    self.simulation_method_input = ui.select(
                        list(SIMULATION_METHODS),
                        label="Simulation method",
                        value=SIMULATION_METHOD,
                        on_change=lambda _: self.refresh_diffractions(clear_cache=True),
                    ).props("outlined dense")
                    self.camera_length_input = ui.select(
                        list(CAMERA_LENGTH_OPTIONS),
                        label="Camera length",
                        value=f"{DEFAULT_CAMERA_LENGTH_MM:g} mm",
                        on_change=lambda _: self.refresh_diffractions(),
                    ).props("outlined dense")
                    self.voltage_input = ui.number(
                        "Voltage",
                        value=DEFAULT_VOLTAGE_KV,
                        min=1.0,
                        step=10.0,
                        suffix="kV",
                        on_change=lambda _: self.refresh_diffractions(),
                    ).props("outlined dense")
                    self.thickness_input = ui.number(
                        "Thickness",
                        value=DEFAULT_THICKNESS_NM,
                        min=0.05,
                        step=1.0,
                        suffix="nm",
                        on_change=lambda _: self.refresh_diffractions(),
                    ).props("outlined dense")
                    self.max_hkl_input = ui.number(
                        "Max hkl",
                        value=DEFAULT_MAX_HKL,
                        min=1,
                        max=30,
                        step=1,
                        on_change=lambda _: self.refresh_diffractions(clear_cache=True),
                    ).props("outlined dense")
                    self.spot_threshold_input = ui.input(
                        "Spot intensity threshold",
                        value=f"{DEFAULT_SPOT_INTENSITY_THRESHOLD:g}",
                        on_change=lambda _: self.refresh_diffractions(),
                    ).props("outlined dense")
                    self.uniform_spot_brightness_input = ui.checkbox(
                        "Uniform spot brightness", value=False, on_change=lambda _: self.refresh_diffractions(),
                    ).props("dense").classes("advanced-checkbox").style("grid-column: 1 / -1")
                    with ui.element("div").classes("advanced-slider-field") as compression_field:
                        ui.label("Compression factor").classes("advanced-slider-label")
                        self.intensity_compression_input = ui.slider(
                            min=10.0,
                            max=200.0,
                            step=1.0,
                            value=DEFAULT_INTENSITY_COMPRESSION_FACTOR,
                            on_change=lambda _: self.refresh_diffractions(),
                        ).props("label-always").classes("advanced-slider")
                    with ui.element("div").classes("advanced-slider-field") as size_scaling_field:
                        ui.label("Spot size scaling effect").classes("advanced-slider-label")
                        self.spot_size_scaling_input = ui.slider(
                            min=0.0,
                            max=1.0,
                            step=0.01,
                            value=DEFAULT_SPOT_SIZE_SCALING,
                            on_change=lambda _: self.refresh_diffractions(),
                        ).props("label-always").classes("advanced-slider")
                    self.snap_back_input = ui.checkbox(
                        "Always snap back view",
                        value=True,
                    ).props("dense").classes("advanced-checkbox")
                    self.hex_four_index_input = ui.checkbox(
                        "Use four-index basis for hexagonal systems",
                        value=True,
                        on_change=lambda _: self.refresh_diffractions(),
                    ).props("dense").classes("advanced-checkbox")
                    self.auto_sync_input = ui.checkbox(
                        "Auto sync crystal/diffraction",
                        value=False,
                    ).props("dense").classes("advanced-checkbox")
                    with ui.column().classes("full-width gap-2"):
                        global_settings_button = ui.button(
                            "Global display settings",
                            icon="settings",
                            on_click=lambda: self.open_palette_dialog(),
                        ).props("outline dense").classes("advanced-palette-button full-width")
                        theme_button = ui.button("Theme", icon="palette", on_click=self.open_theme_dialog).props(
                            "outline dense").classes("full-width")
                self.log_box = ui.textarea("Log", value="\n".join(self.status_history)).props(
                    "outlined dense readonly rows=5"
                ).classes("advanced-log")
            for control, help_text in (
                (close_button, "Close Advanced settings. Changes take effect immediately."),
                (self.simulation_method_input,
                 "Pymatgen calculates the nearest integer zone axis. Ewald sphere uses the continuous viewing direction and specimen thickness."),
                (self.camera_length_input,
                 "Camera length in millimeters. A longer camera length spreads diffraction spots farther from the central beam."),
                (self.voltage_input,
                 "Electron accelerating voltage in kV. Sets the electron wavelength and diffraction geometry."),
                (self.thickness_input,
                 "Specimen thickness in nm. Controls the intensity of off-zone reflections in the Ewald-sphere method; not used by Pymatgen."),
                (self.max_hkl_input,
                 "Limits the Miller indices searched for reflections. Higher values include higher-order spots but take longer to calculate."),
                (self.spot_threshold_input,
                 "Show spots with compressed relative intensity above this value. Range: 1e-10 to 1; default: 1e-4. Scientific notation is accepted. Applies in both brightness modes."),
                (self.uniform_spot_brightness_input,
                 "Draw all spots above the threshold at equal brightness. Compression still affects the cutoff, and spot size scaling remains independent."),
                (compression_field,
                 "Enhances weak relative intensities before applying the threshold. Higher values can reveal weaker spots. Range: 10 to 200; also active with uniform brightness."),
                (size_scaling_field,
                 "Controls how strongly spot size varies with compressed intensity. Zero gives equal-sized spots; one gives the full size variation. Does not change which spots pass the threshold."),
                (self.snap_back_input,
                 "When applying a zone axis, reset its in-plane roll to the standard view. Uncheck to retain the current roll. Any entered rotation is applied after the zone change."),
                (self.hex_four_index_input,
                 "Use four-index Miller-Bravais notation for hexagonal zone labels and diffraction indices. Uncheck for three-index labels. The crystal geometry does not change."),
                (self.auto_sync_input,
                 "Automatically update diffraction after rotating the crystal with the mouse. When unchecked, click the panel's SYNC button to update it."),
                (global_settings_button,
                 "Edit default display settings for new panels and panels following global settings, including frames, atom sizes, colors, and annotations."),
                (theme_button,
                 "Choose or customize interface colors and global panel backgrounds. Apply/Close saves them for future sessions; local panel overrides stay unchanged."),
                (self.log_box, "Recent status messages, input errors, and calculation messages. Read-only."),
            ):
                with control:
                    ui.tooltip(help_text).props('anchor="bottom left" self="top left" :offset="[0, 8]" delay=300').classes("advanced-tooltip")

    def open_theme_dialog(self) -> None:
        if self.theme_editor is not None:
            self.theme_editor.dialog.close()
            self.theme_editor.dialog.delete()
        with ui.context.client.content:
            self.theme_editor = ThemeDialog(self)
        self.theme_editor.dialog.open()

    async def apply_theme_settings(self, theme: InterfaceTheme) -> bool:
        theme = validate_theme(theme)
        draft = self.display_settings_draft()
        draft.display.backgrounds = copy.deepcopy(theme.backgrounds)
        return await self.apply_display_settings_draft(None, draft, theme=theme)

    def open_palette_dialog(self, panel_id: int | None = None) -> None:
        if panel_id is not None and self.panel_state_by_id(panel_id) is None:
            return
        if self.palette_dialog is not None:
            if self.display_settings_editor is not None:
                self.display_settings_editor.dispose_preview()
            self.palette_dialog.close()
            self.palette_dialog.delete()
        # Event callbacks can run inside the old dialog's slot. Always attach to the page.
        with ui.context.client.content:
            self.display_settings_editor = DisplaySettingsDialog(self, panel_id)
        self.palette_dialog = self.display_settings_editor.dialog
        self.palette_dialog.open()

    def display_settings_draft(self, panel_id: int | None = None) -> DisplaySettingsDraft:
        if panel_id is None:
            return DisplaySettingsDraft(copy.deepcopy(self.global_display_settings), set(),
                                        self.vector_colors.copy(), self.plane_colors.copy(), self.global_diffraction_color,
                                        self.element_colors.copy())
        state = self.panel_state_by_id(panel_id)
        if state is None:
            raise ValueError("Panel no longer exists.")
        color = self.diffraction_color_for_state(state)
        if not state.diffraction_color_custom and color == self.default_diffraction_color_for_crystal(state.crystal_name):
            color = None
        if "colors" in state.global_display_sections:
            color = self.global_diffraction_color
        return DisplaySettingsDraft(copy.deepcopy(state.display_settings), state.global_display_sections.copy(),
                                    self.vector_palette(panel_id).copy(), self.plane_palette(panel_id).copy(), color,
                                    panel_element_colors=copy.deepcopy(state.element_colors),
                                    annotation_visibility=state.annotation_visibility.copy())

    def validated_display_settings_draft(self, panel_id: int | None, draft: DisplaySettingsDraft) -> DisplaySettingsDraft:
        draft = copy.deepcopy(draft)
        if not draft.inherited <= DISPLAY_SETTING_SECTIONS:
            raise ValueError("Unknown global settings section.")

        def color(value: str) -> str:
            if not re.fullmatch(r"#?[0-9a-fA-F]{6}", str(value)):
                raise ValueError("Colors must be six-digit hex colors.")
            return "#" + str(value).lstrip("#").upper()

        if panel_id is not None:
            draft.display = inherited_display_settings(draft.display, self.global_display_settings, draft.inherited)
            if "colors" in draft.inherited:
                draft.vector_colors, draft.plane_colors = self.vector_colors.copy(), self.plane_colors.copy()
                draft.diffraction_color = self.global_diffraction_color
        draft.display.frame_color = color(draft.display.frame_color)
        draft.display.backgrounds.crystal = color(draft.display.backgrounds.crystal)
        draft.display.backgrounds.diffraction = color(draft.display.backgrounds.diffraction)
        for name in ANNOTATION_STYLE_NAMES:
            style = getattr(draft.display.annotations, name)
            style.color = color(style.color)
        validate_display_settings(draft.display)
        draft.display.cells = tuple(int(n) for n in draft.display.cells)
        for kind in ("vector", "plane"):
            values = getattr(draft, f"{kind}_colors")
            if not values:
                raise ValueError("Each palette needs at least one color.")
            setattr(draft, f"{kind}_colors", [color(value) for value in values])
        if draft.diffraction_color is not None:
            draft.diffraction_color = color(draft.diffraction_color)
        if panel_id is None:
            draft.element_colors = validate_element_colors(draft.element_colors)
        elif draft.panel_element_colors is not None:
            draft.panel_element_colors = validate_element_colors(draft.panel_element_colors)
        if (not set(draft.annotation_visibility) <= set(SAVED_VISIBILITY_METHODS)
                or any(type(value) is not bool for value in draft.annotation_visibility.values())):
            raise ValueError("Invalid annotation visibility.")
        return draft

    async def apply_display_settings_draft(self, panel_id: int | None, draft: DisplaySettingsDraft,
                                          *, theme: InterfaceTheme | None = None) -> bool:
        if getattr(self, "_applying_display_settings", False):
            return False
        if panel_id is not None and self.panel_state_by_id(panel_id) is None:
            return False
        self._applying_display_settings = True
        try:
            draft = self.validated_display_settings_draft(panel_id, draft)
            next_theme = (validate_theme(replace(theme or self.theme, backgrounds=copy.deepcopy(draft.display.backgrounds)))
                          if panel_id is None else self.theme)
            global_display = draft.display if panel_id is None else self.global_display_settings
            global_vectors = draft.vector_colors if panel_id is None else self.vector_colors
            global_planes = draft.plane_colors if panel_id is None else self.plane_colors
            global_diffraction = draft.diffraction_color if panel_id is None else self.global_diffraction_color
            global_annotations_changed = panel_id is None and (
                draft.display.annotations != self.global_display_settings.annotations or
                draft.display.backgrounds != self.global_display_settings.backgrounds)
            scale_bars_enabled = (draft.display.annotations.real_scale_visible or draft.display.annotations.reciprocal_scale_visible
                                  if panel_id is None and theme is None else self.show_scale_bars())
            master_visibility_changed = scale_bars_enabled != self.show_scale_bars()
            element_colors = draft.element_colors if panel_id is None else self.element_colors
            changed_elements = {element for element in self.element_colors.keys() | element_colors.keys()
                                if self.element_colors.get(element) != element_colors.get(element)}
            changes = []
            # Validate every affected geometry before committing any shared defaults or panel state.
            for state in self.panel_states:
                if panel_id is not None and state.panel_id != panel_id:
                    continue
                inherited = draft.inherited.copy() if panel_id is not None else state.global_display_sections.copy()
                settings = (copy.deepcopy(draft.display) if panel_id is not None else
                            inherited_display_settings(state.display_settings, global_display,
                                                       inherited & {"backgrounds"} if theme is not None else inherited))
                panel_colors = draft.panel_element_colors if panel_id is not None else state.element_colors
                visibility = draft.annotation_visibility.copy() if panel_id is not None else state.annotation_visibility.copy()
                if panel_id is None and master_visibility_changed:
                    visibility.pop("scale", None)
                vectors, planes, diffraction = state.vector_colors, state.plane_colors, state.diffraction_color
                diffraction_custom = state.diffraction_color_custom
                if "colors" in inherited and theme is None:
                    vectors = planes = None
                    diffraction = global_diffraction or self.default_diffraction_color_for_crystal(state.crystal_name)
                    diffraction_custom = False
                elif panel_id is not None:
                    vectors, planes = draft.vector_colors.copy(), draft.plane_colors.copy()
                    diffraction = draft.diffraction_color or self.default_diffraction_color_for_crystal(state.crystal_name)
                    diffraction_custom = draft.diffraction_color is not None
                geometry_changed = crystal_display_settings(settings) != crystal_display_settings(state.display_settings)
                backgrounds_changed = settings.backgrounds != state.display_settings.backgrounds
                visibility_changed = visibility != state.annotation_visibility
                annotations_changed = settings.annotations != state.display_settings.annotations or backgrounds_changed or visibility_changed
                palette_changed = (self.vector_palette(state.panel_id) != (vectors or global_vectors) or
                                   self.plane_palette(state.panel_id) != (planes or global_planes))
                diffraction_changed = self.diffraction_color_for_state(state) != diffraction
                controller = self.controller_by_panel_id(state.panel_id)
                element_colors_changed = panel_colors != state.element_colors or (panel_colors is None and bool(changed_elements) and any(
                    site.element.strip().capitalize() in changed_elements
                    for site in self.model_for(state.crystal_name).expanded_sites))
                model = None
                if geometry_changed or element_colors_changed:
                    try:
                        source = self.model_for(state.crystal_name)
                        effective_colors = panel_colors if panel_colors is not None else element_colors
                        model = (controller.display_model(source, settings=settings, element_colors=effective_colors)
                                 if controller else make_panel_display_model(source, settings, effective_colors))
                    except (ValueError, TypeError) as exc:
                        raise ValueError(f"Panel {state.panel_id} ({state.crystal_name}): {exc}") from exc
                changes.append(dict(state=state, settings=settings, inherited=inherited, vectors=vectors, planes=planes,
                                    panel_colors=copy.deepcopy(panel_colors), visibility=visibility,
                                    diffraction=diffraction, controller=controller, model=model,
                                    diffraction_custom=diffraction_custom,
                                    redraw_scene=geometry_changed or palette_changed or element_colors_changed or backgrounds_changed or visibility_changed,
                                    redraw_diffraction=diffraction_changed or annotations_changed or master_visibility_changed,
                                    annotations_changed=annotations_changed or master_visibility_changed,
                                    refit=(settings.cells != state.display_settings.cells or
                                           model is not None and controller is not None and controller.current_model is not None
                                           and model.limit != controller.current_model.limit), view=None, roll=None))
            for change in changes:
                if change["refit"] and change["controller"] is not None:
                    change["view"], change["roll"] = await change["controller"].live_scene_orientation()
            if panel_id is None:
                theme_changed = next_theme != self.theme
                if theme_changed:
                    save_theme(next_theme)
                try:
                    if changed_elements:
                        save_element_colors(element_colors)
                except OSError:
                    if theme_changed:
                        save_theme(self.theme)
                    raise
                self.theme = copy.deepcopy(next_theme)
                if theme_changed:
                    self.apply_interface_theme()
                self.element_colors = element_colors.copy()
                self.global_display_settings = copy.deepcopy(draft.display)
                self.vector_colors, self.plane_colors = draft.vector_colors.copy(), draft.plane_colors.copy()
                self.global_diffraction_color = draft.diffraction_color
                self.scale_bars_enabled = scale_bars_enabled
                if self.show_scale_bar_input is not None:
                    # Commit all panel state below before refreshing the master switch's followers.
                    self._updating_scale_bar_checkbox = True
                    try:
                        self.show_scale_bar_input.value = scale_bars_enabled
                    finally:
                        self._updating_scale_bar_checkbox = False
            diffraction_ids = set()
            for change in changes:
                state, controller = change["state"], change["controller"]
                state.display_settings, state.global_display_sections = change["settings"], change["inherited"]
                state.element_colors, state.annotation_visibility = change["panel_colors"], change["visibility"]
                state.vector_colors = copy.deepcopy(change["vectors"])
                state.plane_colors = copy.deepcopy(change["planes"])
                state.diffraction_color = change["diffraction"]
                state.diffraction_color_custom = change["diffraction_custom"]
                if controller is not None and change["annotations_changed"]:
                    controller.apply_scale_bar_visibility()
                if controller is not None and change["redraw_scene"]:
                    controller.redraw_scene(change["model"], update_camera=False)
                    if change["refit"] and controller.scene is not None:
                        controller.position_scene_camera(change["model"],
                            change["view"] if change["view"] is not None else state.view_vector,
                            change["roll"] if change["roll"] is not None else state.roll)
                if change["redraw_diffraction"]:
                    diffraction_ids.add(state.panel_id)
            if diffraction_ids:
                self.redraw_panel_diffractions(diffraction_ids)
            combo_ids = {state.panel_id for state in self.panel_states} if global_annotations_changed or master_visibility_changed else diffraction_ids
            if combo_ids:
                self.refresh_combo_panels_for_sources(combo_ids)
            if panel_id is None:
                editor = self.display_settings_editor
                if editor is not None and editor.panel_id is None:
                    loading, editor.loading = editor.loading, True
                    editor.draft.display.backgrounds = copy.deepcopy(self.global_display_settings.backgrounds)
                    editor.load_section("backgrounds")
                    editor.loading = loading
                if self.theme_editor is not None:
                    if theme is not None:
                        self.theme_editor.set_theme_draft(self.theme)
                    else:
                        self.theme_editor.set_backgrounds(self.theme.backgrounds)
            self.set_status("Theme updated" if theme is not None else
                            "Global display settings updated" if panel_id is None else f"Panel {panel_id} display settings updated")
            return True
        finally:
            self._applying_display_settings = False

    async def apply_panel_display_settings(self, panel_id: int, settings: PanelDisplaySettings) -> bool:
        draft = self.display_settings_draft(panel_id)
        draft.display = settings
        draft.inherited.difference_update(DISPLAY_SETTING_FIELDS)
        return await self.apply_display_settings_draft(panel_id, draft)

    def palette_values(self, kind: str, panel_id: int | None = None) -> list[str]:
        if panel_id is not None:
            state = self.panel_state_by_id(panel_id)
            if state is not None:
                colors = state.vector_colors if kind == "vector" else state.plane_colors
                if colors is not None:
                    return colors
        return self.vector_colors if kind == "vector" else self.plane_colors

    def palette_default_values(self, kind: str) -> list[str]:
        return VECTOR_COLORS if kind == "vector" else PLANE_COLORS

    def normalize_palette_color(self, value: str | None, fallback: str) -> str:
        text = str(value or "").strip()
        if re.fullmatch(r"#?[0-9a-fA-F]{6}", text):
            return ("#" + text.lstrip("#")).upper()
        return fallback

    def default_diffraction_color_for_crystal(self, crystal_name: str, *, background: str | None = None) -> str:
        if crystal_name in LIGHT_BACKGROUND_DEMO_COLORS and background is not None and contrast_text_color(background) == "#000000":
            return LIGHT_BACKGROUND_DEMO_COLORS[crystal_name]
        fallback = DEFAULT_DIFFRACTION_COLORS.get(str(crystal_name or ""), "#31F7F1")
        try:
            definition = self.library.get(str(crystal_name or ""))
        except Exception:
            return fallback
        return DEFAULT_DIFFRACTION_COLORS.get(definition.name, dominant_color(definition))

    def diffraction_color_for_state(self, state: PanelState) -> str:
        fallback = self.default_diffraction_color_for_crystal(state.crystal_name)
        global_color = getattr(self, "global_diffraction_color", None)
        value = global_color if "colors" in state.global_display_sections and global_color is not None else state.diffraction_color
        color = self.normalize_palette_color(value, fallback)
        state.diffraction_color = color
        return color

    def display_diffraction_color(self, state: PanelState, background: str | None = None) -> str:
        color = self.diffraction_color_for_state(state)
        custom = state.diffraction_color_custom or (
            "colors" in state.global_display_sections and getattr(self, "global_diffraction_color", None) is not None)
        if not custom and color == DEFAULT_DIFFRACTION_COLORS.get(state.crystal_name):
            return self.default_diffraction_color_for_crystal(state.crystal_name,
                background=background if background is not None else state.display_settings.backgrounds.diffraction)
        return color

    def set_panel_crystal(self, state: PanelState, crystal_name: str, force_default_color: bool = False,
                          *, preserve_saved_view: bool = False) -> None:
        """Refresh automatic colors without discarding an explicit panel color."""
        selected_name = str(crystal_name or state.crystal_name)
        if selected_name == CUSTOM_SENTINEL:
            return
        if selected_name != state.crystal_name and not preserve_saved_view:
            state.element_colors = None
            state.annotation_visibility.clear()
            state.saved_view_id = None
            state.initial_camera = None
        old_default = self.default_diffraction_color_for_crystal(state.crystal_name)
        current_color = self.normalize_palette_color(state.diffraction_color, old_default)
        if "colors" in state.global_display_sections:
            state.diffraction_color = self.global_diffraction_color or self.default_diffraction_color_for_crystal(selected_name)
            state.diffraction_color_custom = False
        elif not state.diffraction_color_custom and (force_default_color or selected_name != state.crystal_name):
            state.diffraction_color = self.default_diffraction_color_for_crystal(selected_name)
        else:
            state.diffraction_color = current_color
        state.crystal_name = selected_name

    def set_panel_diffraction_color(self, panel_id: int, value: str | None) -> None:
        state = self.panel_state_by_id(panel_id)
        if state is None:
            return
        color = self.normalize_palette_color(value, self.diffraction_color_for_state(state))
        state.global_display_sections.discard("colors")
        state.diffraction_color_custom = True
        if color == state.diffraction_color:
            return
        state.diffraction_color = color
        self.redraw_panel_diffractions({panel_id})
        self.refresh_combo_panels_for_sources({panel_id})

    def reset_panel_diffraction_color(self, panel_id: int) -> None:
        state = self.panel_state_by_id(panel_id)
        if state is None:
            return
        state.global_display_sections.discard("colors")
        state.diffraction_color = self.default_diffraction_color_for_crystal(state.crystal_name)
        state.diffraction_color_custom = False
        self.redraw_panel_diffractions({panel_id})
        self.refresh_combo_panels_for_sources({panel_id})


    def replace_palette(self, kind: str, colors: list[str] | None, panel_id: int | None) -> None:
        attribute = "vector_colors" if kind == "vector" else "plane_colors"
        if panel_id is None:
            setattr(self, attribute, colors if colors is not None else self.palette_default_values(kind).copy())
            affected = {state.panel_id for state in self.panel_states if getattr(state, attribute) is None}
        else:
            state = self.panel_state_by_id(panel_id)
            if state is None:
                return
            setattr(state, attribute, colors)
            state.global_display_sections.discard("colors")
            affected = {panel_id}
        for controller in self.controllers:
            if controller.state.panel_id in affected:
                controller.redraw_scene(update_camera=False)

    def set_palette_color(self, kind: str, index: int, value: str | None, panel_id: int | None = None) -> None:
        palette = self.palette_values(kind, panel_id).copy()
        if not (0 <= index < len(palette)):
            return
        color = self.normalize_palette_color(value, palette[index])
        if color != palette[index]:
            palette[index] = color
            self.replace_palette(kind, palette, panel_id)

    def add_palette_color(self, kind: str, panel_id: int | None = None) -> None:
        palette = self.palette_values(kind, panel_id).copy()
        defaults = self.palette_values(kind) if panel_id is not None else self.palette_default_values(kind)
        palette.append(defaults[len(palette) % len(defaults)])
        self.replace_palette(kind, palette, panel_id)

    def reset_palette(self, kind: str, panel_id: int | None = None) -> None:
        self.replace_palette(kind, None, panel_id)

    def remove_palette_color(self, kind: str, index: int, panel_id: int | None = None) -> None:
        palette = self.palette_values(kind, panel_id).copy()
        if len(palette) <= 1 or not (0 <= index < len(palette)):
            return
        palette.pop(index)
        self.replace_palette(kind, palette, panel_id)

    def move_palette_color(self, kind: str, index: int, direction: int, panel_id: int | None = None) -> None:
        palette = self.palette_values(kind, panel_id).copy()
        if not 0 <= index < len(palette):
            return
        new_index = min(max(index + direction, 0), len(palette) - 1)
        if new_index == index:
            return
        palette[index], palette[new_index] = palette[new_index], palette[index]
        self.replace_palette(kind, palette, panel_id)

    def build_cif_dialog(self) -> None:
        self.cif_dialog = ui.dialog()
        with self.cif_dialog, ui.card().classes("cif-card"):
            with ui.row().classes("items-center justify-between full-width"):
                ui.label("Load CIF").classes("text-h6")
                ui.button(icon="close", on_click=self.cif_dialog.close).props("flat round dense").tooltip("Close")
            ui.upload(
                label="Choose a .cif file",
                auto_upload=True,
                max_file_size=25_000_000,
                on_upload=self.load_cif_upload,
            ).props("accept=.cif").classes("full-width")

    def element_colors_for_state(self, state: PanelState) -> dict[str, str]:
        return self.element_colors if state.element_colors is None else state.element_colors

    def saved_view_payload(self, panel_id: int, draft: DisplaySettingsDraft, camera: dict | None) -> tuple[CrystalDefinition, dict]:
        state = self.panel_state_by_id(panel_id)
        if state is None:
            raise ValueError("Panel no longer exists.")
        definition = copy.deepcopy(self.library.get(state.crystal_name))
        camera = validated_saved_camera(camera)
        view, roll = state.view_vector.copy(), state.roll
        if camera is not None:
            view = normalize_vector(np.array(camera["position"]) - camera["target"])
            roll = roll_from_view_and_up(view, np.array(camera["up"]), roll)
        colors = self.element_colors if draft.panel_element_colors is None else draft.panel_element_colors
        payload = dict(display=asdict(draft.display), element_colors=colors.copy(),
                       vector_colors=draft.vector_colors.copy(), plane_colors=draft.plane_colors.copy(),
                       diffraction_color=draft.diffraction_color or self.default_diffraction_color_for_crystal(
                           state.crystal_name, background=draft.display.backgrounds.diffraction),
                       view_vector=np.asarray(view).tolist(), roll=float(roll), camera=camera,
                       plane_text=state.plane_text, vector_text=state.vector_text, applied_zone_text=state.applied_zone_text,
                       crystal_view_percent=state.crystal_view_percent,
                       visibility={key: draft.annotation_visibility.get(key, getattr(self, method)())
                                   for key, method in SAVED_VISIBILITY_METHODS.items()})
        # Validate the complete snapshot, including marker geometry, before offering to save it.
        probe = PanelState(panel_id=panel_id, crystal_name=state.crystal_name)
        self.restore_saved_view(probe, dict(id="validation", crystal_id=crystal_identity(definition), payload=payload))
        return definition, payload

    def restore_saved_view(self, state: PanelState, view: dict) -> None:
        definition = self.library.get(state.crystal_name)
        if view["crystal_id"] != crystal_identity(definition):
            raise ValueError("This saved view belongs to another crystal.")
        data = view["payload"]
        try:
            settings = display_settings_from_dict(data["display"])
            colors = validate_element_colors(data["element_colors"])
            direction = np.asarray(data["view_vector"], dtype=float)
            roll, split = float(data["roll"]), float(data["crystal_view_percent"])
            if (direction.shape != (3,) or not np.isfinite(direction).all() or np.linalg.norm(direction) < 1e-10
                    or not math.isfinite(roll) or not math.isfinite(split) or not 0 <= split <= 100):
                raise ValueError("Invalid orientation or panel divider position.")
            camera = validated_saved_camera(data.get("camera"))
            visibility = data["visibility"]
            if (not isinstance(visibility, dict) or set(visibility) != set(SAVED_VISIBILITY_METHODS)
                    or any(type(value) is not bool for value in visibility.values())):
                raise ValueError("Invalid annotation visibility.")
            palettes = {}
            for kind in ("vector", "plane"):
                palette = data[f"{kind}_colors"]
                if not isinstance(palette, list) or not palette or any(normalized_hex_color(v) is None for v in palette):
                    raise ValueError("Invalid saved palette.")
                palettes[kind] = [normalized_hex_color(v) for v in palette]
            diffraction_color = normalized_hex_color(data["diffraction_color"])
            if diffraction_color is None:
                raise ValueError("Invalid diffraction color.")
            source = self.model_for(state.crystal_name)
            for key, kind in (("plane_text", "plane"), ("vector_text", "direction")):
                if not isinstance(data[key], str) or len(data[key]) > 10000:
                    raise ValueError("Invalid saved indices.")
                _, errors = parse_indices(data[key], source, kind, True, kind == "direction")
                if errors:
                    raise ValueError("; ".join(errors[:3]))
            if not isinstance(data["applied_zone_text"], str):
                raise ValueError("Invalid saved zone.")
            make_panel_display_model(source, settings, colors)
        except (TypeError, KeyError, AttributeError, OverflowError) as exc:
            raise ValueError(f"Invalid saved-view settings: {exc}") from exc
        state.display_settings = settings
        state.global_display_sections.clear()
        state.element_colors = colors
        state.annotation_visibility = visibility.copy()
        state.vector_colors, state.plane_colors = palettes["vector"], palettes["plane"]
        state.diffraction_color, state.diffraction_color_custom = diffraction_color, True
        state.view_vector, state.roll = normalize_vector(direction), roll
        state.initial_camera = camera
        state.plane_text, state.vector_text = data["plane_text"], data["vector_text"]
        state.applied_zone_text = data["applied_zone_text"]
        state.zone_text = state.rotation_text = ""
        state.crystal_view_percent = round(split / 10) * 10
        state.saved_view_id = view["id"]

    def saved_view_problem(self, message: str) -> None:
        if message in self.saved_view_warnings:
            return
        self.saved_view_warnings.add(message)
        self.set_status(message)
        if core.is_loop_running():
            ui.notify(message, type="warning", timeout=8000)

    def apply_default_saved_view(self, state: PanelState) -> bool:
        definition = self.library.get(state.crystal_name)
        try:
            view = next((v for v in self.view_store.for_crystal(crystal_identity(definition)) if v["default"]), None)
            if view is None:
                return False
            if view["structure_version"] != crystal_version(definition):
                self.saved_view_problem(f"{state.crystal_name}: default view '{view['name']}' was skipped because the crystal changed. Review it in Crystal list.")
                return False
            self.restore_saved_view(state, view)
            return True
        except (ValueError, OSError) as exc:
            self.saved_view_problem(f"Could not load the saved default for {state.crystal_name}: {exc}")
            return False

    def open_saved_view(self, name: str, view_id: str) -> None:
        try:
            definition = self.library.get(name)
            view = next((v for v in self.view_store.for_crystal(crystal_identity(definition)) if v["id"] == view_id), None)
            if view is None:
                raise ValueError("This saved view no longer exists.")
        except (ValueError, OSError) as exc:
            ui.notify(str(exc), type="negative")
            return

        def open_view():
            try:
                self.add_panel(crystal_name=name, saved_view=view)
            except (ValueError, OSError) as exc:
                ui.notify(str(exc), type="negative")
                return
            self.crystal_list_dialog.close()
            self.set_status(f"Opened saved view: {name} / {view['name']}")

        if view["structure_version"] == crystal_version(definition):
            open_view()
            return
        with ui.context.client.content:
            dialog = ui.dialog()
        dialog.on("hide", dialog.delete)
        with dialog, ui.card().classes("saved-view-dialog"):
            ui.label("Crystal changed").classes("text-h6")
            ui.label(f"{name} has changed since '{view['name']}' was saved. Markers and viewing directions may no longer match. Open it with the current structure?").classes("break-words")
            with ui.row().classes("full-width justify-end gap-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat dense")
                ui.button("Open anyway", on_click=lambda: (dialog.close(), open_view())).props("unelevated dense")
        dialog.open()

    def change_saved_view(self, view_id: str, action: str, value=None) -> bool:
        try:
            self.view_store.change(view_id, action, value)
        except (ValueError, OSError) as exc:
            ui.notify(str(exc), type="negative")
            return False
        self.refresh_crystal_list()
        return True

    def edit_saved_view_entry(self, view: dict, *, delete: bool = False) -> None:
        # List refreshes replace their rows; keep dialogs outside those temporary slots.
        with ui.context.client.content:
            dialog = ui.dialog()
        dialog.on("hide", dialog.delete)
        with dialog, ui.card().classes("saved-view-dialog"):
            ui.label("Delete saved view?" if delete else "Rename saved view").classes("text-h6")
            if delete:
                ui.label(f"Delete '{view['name']}'? The crystal and open panels will not be changed.").classes("break-words")
                name = None
            else:
                name = ui.input("View name", value=view["name"]).props("outlined dense maxlength=120").classes("full-width")

            def confirm():
                if self.change_saved_view(view["id"], "delete" if delete else "rename", name.value if name else None):
                    dialog.close()

            with ui.row().classes("full-width justify-end gap-2"):
                ui.button("Cancel", on_click=dialog.close).props("flat dense")
                ui.button("Delete" if delete else "Rename", icon="delete" if delete else "edit", on_click=confirm,
                          color="negative" if delete else "primary").props("unelevated dense")
        dialog.open()

    def build_crystal_list_dialog(self) -> None:
        self.crystal_list_dialog = ui.dialog()
        with self.crystal_list_dialog, ui.card().classes("crystal-list-card"):
            with ui.row().classes("items-center justify-between full-width"):
                ui.label("Crystal list").classes("text-h6")
                ui.button(icon="close", on_click=self.crystal_list_dialog.close).props("flat round dense").tooltip("Close")
            self.crystal_list_container = ui.column().classes("crystal-list")

    def open_crystal_list(self) -> None:
        self.refresh_crystal_list()
        if self.crystal_list_dialog is not None:
            self.crystal_list_dialog.open()

    def refresh_crystal_list(self) -> None:
        if self.crystal_list_container is None:
            return
        try:
            saved_views = self.view_store.read()
        except (ValueError, OSError) as exc:
            saved_views = []
            self.saved_view_problem(str(exc))
        self.crystal_list_container.clear()
        with self.crystal_list_container:
            for name in self.library.options():
                if name == CUSTOM_SENTINEL:
                    continue
                definition = self.library.get(name)
                status = "Built-in" if name in DEFAULT_NAMES else "Custom"
                summary = (
                    f"{definition.lattice_system}, {space_group_symbol(definition.space_group)}, "
                    f"{len(definition.sites)} site(s)"
                )
                identity = crystal_identity(definition)
                views = [view for view in saved_views if view["crystal_id"] == identity]
                with ui.column().classes("full-width gap-0 crystal-list-entry"):
                    with ui.row().classes("crystal-list-row" + (" crystal-list-has-views" if views else "")):
                        if views:
                            expanded = identity in self.expanded_crystal_views
                            toggle = ui.button(icon="expand_more" if expanded else "chevron_right").props(
                                f"flat round dense aria-expanded={'true' if expanded else 'false'}"
                            ).classes("saved-view-toggle").tooltip(f"{len(views)} saved view(s)")
                            toggle._props["aria-label"] = f"Saved views for {name}"
                        swatch = ui.element("div").classes("crystal-list-swatch")
                        swatch.style(f"background: {dominant_color(definition)}")
                        with ui.column().classes("crystal-list-info"):
                            ui.label(name).classes("crystal-list-name")
                            ui.label(f"{status} · {summary}").classes("crystal-list-meta")
                        open_button = ui.button(icon="open_in_new", on_click=lambda _=None, n=name:
                                                self.open_crystal_in_new_panel(n)).props("flat round dense").classes(
                                                    "crystal-list-open").tooltip("Open in new panel")
                        open_button._props["aria-label"] = f"Open {name} in new panel"
                        ui.button(
                            icon="download",
                            on_click=lambda _=None, n=name: self.open_crystal_cif_export_dialog(n),
                        ).props("flat round dense").tooltip("Export CIF")
                        ui.button(icon="edit", on_click=lambda _=None, n=name: self.edit_crystal_from_list(n)).props(
                            "flat round dense"
                        ).tooltip("Edit crystal")
                        delete = ui.button(icon="delete", on_click=lambda _=None, n=name: self.delete_crystal_from_list(n)).props(
                            "flat round dense color=negative"
                        )
                        delete.tooltip("Delete crystal")
                        if name in DEFAULT_NAMES:
                            delete.disable()
                    if views:
                        with ui.column().classes("saved-view-list") as children:
                            for view in views:
                                with ui.row().classes("saved-view-row"):
                                    ui.button(view["name"], icon="open_in_new", on_click=lambda _=None, n=name, v=view:
                                              self.open_saved_view(n, v["id"])).props("flat dense no-caps align=left").classes(
                                                  "saved-view-open").tooltip(f"Open {view['name']} in a new panel")
                                    if view["structure_version"] != crystal_version(definition):
                                        ui.icon("warning", color="warning").tooltip("Crystal changed since this view was saved")
                                    else:
                                        ui.element("span")
                                    ui.button(icon="star" if view["default"] else "star_border",
                                        on_click=lambda _=None, v=view: self.change_saved_view(v["id"], "default", not v["default"])
                                    ).props("flat round dense").tooltip("Remove default view" if view["default"] else "Use as default view")
                                    ui.button(icon="edit", on_click=lambda _=None, v=view: self.edit_saved_view_entry(v)).props(
                                        "flat round dense").tooltip("Rename saved view")
                                    ui.button(icon="delete", on_click=lambda _=None, v=view: self.edit_saved_view_entry(v, delete=True)).props(
                                        "flat round dense color=negative").tooltip("Delete saved view")
                        children.set_visibility(expanded)

                        def toggle_views(_=None, key=identity, group=children, button=toggle):
                            visible = key not in self.expanded_crystal_views
                            if visible:
                                self.expanded_crystal_views.add(key)
                            else:
                                self.expanded_crystal_views.discard(key)
                            group.set_visibility(visible)
                            button.props(f"icon={'expand_more' if visible else 'chevron_right'} aria-expanded={'true' if visible else 'false'}")

                        toggle.on_click(toggle_views)

    def open_crystal_in_new_panel(self, name: str) -> None:
        self.add_panel(crystal_name=name)
        if self.crystal_list_dialog is not None:
            self.crystal_list_dialog.close()
        self.set_status(f"Opened {name} in a new panel")

    def edit_crystal_from_list(self, name: str) -> None:
        if self.crystal_list_dialog is not None:
            self.crystal_list_dialog.close()
        self.builder.open(self.library.get(name), mode="edit")

    def open_crystal_cif_export_dialog(
        self,
        name: str | None = None,
        definition: CrystalDefinition | None = None,
    ) -> None:
        definition = definition or self.library.get(str(name or "FCC"))
        display_name = str(name or definition.name or "Crystal")
        dialog = ui.dialog()
        preserve_label = "Preserve symmetry"
        p1_label = "Remove symmetry (P1)"
        default_label = preserve_label if space_group_symbol(definition.space_group) not in {"", "P1", "1"} else p1_label
        with dialog, ui.card().classes("download-card"):
            with ui.row().classes("items-center justify-between full-width"):
                ui.label(f"Export CIF: {display_name}").classes("text-h6")
                ui.button(icon="close", on_click=dialog.close).props("flat round dense").tooltip("Close")
            ui.label(f"Crystal: {display_name}").classes("text-caption text-grey-4")
            filename_input = (
                ui.input("File name base", value=sanitize_export_filename_stem(definition.name, "crystal"))
                .props("outlined dense")
                .classes("full-width")
            )
            symmetry_input = ui.select(
                [preserve_label, p1_label],
                label="Symmetry",
                value=default_label,
            ).props("outlined dense").classes("full-width")
            if self.direct_file_exports_enabled():
                export_folder_label = ui.label(f"Export folder: {self.export_dir_text()}").classes("export-folder-label")

                async def choose_folder() -> None:
                    await self.choose_export_folder(export_folder_label)

                ui.button("Choose export folder", icon="folder_open", on_click=choose_folder).props("outline dense")
            with ui.row().classes("justify-end full-width"):
                ui.button("Cancel", on_click=dialog.close).props("flat dense")
                ui.button(
                    "Export",
                    icon="download",
                    on_click=lambda: self.export_crystal_cif(
                        definition,
                        str(filename_input.value or ""),
                        symmetry_input.value == preserve_label,
                        dialog,
                    ),
                ).props("unelevated dense")
        dialog.open()

    def export_crystal_cif(
        self,
        definition: CrystalDefinition,
        filename_base: str | None = None,
        preserve_symmetry: bool = False,
        dialog: Any | None = None,
    ) -> None:
        filename = sanitize_export_filename(filename_base or definition.name, "crystal", ".cif")
        try:
            cif_text = cif_text_for_definition(definition, preserve_symmetry=preserve_symmetry)
        except Exception as exc:
            message = f"Could not export {definition.name} as CIF: {exc}"
            self.set_status(message)
            ui.notify(message, type="negative")
            return

        if self.direct_file_exports_enabled():
            try:
                path = self.save_exported_text(cif_text, filename, ".cif")
            except Exception as exc:
                message = f"Could not save CIF: {exc}"
                self.set_status(message)
                ui.notify(message, type="negative")
                return
            self.announce_saved_exports([path])
            if dialog is not None:
                dialog.close()
            return

        ui.download(cif_text.encode("utf-8"), filename, media_type="chemical/x-cif")
        message = f"Downloaded CIF: {filename}"
        self.set_status(message)
        ui.notify(message, type="positive")
        if dialog is not None:
            dialog.close()

    def delete_crystal_from_list(self, name: str, confirmed: bool = False) -> None:
        identity = crystal_identity(self.library.get(name))
        try:
            views = self.view_store.for_crystal(identity)
        except (ValueError, OSError) as exc:
            ui.notify(str(exc), type="negative")
            return
        if views and not confirmed and name not in DEFAULT_NAMES:
            with ui.context.client.content:
                dialog = ui.dialog()
            dialog.on("hide", dialog.delete)
            with dialog, ui.card().classes("saved-view-dialog"):
                ui.label("Delete crystal and saved views?").classes("text-h6")
                ui.label(f"Delete {name} and its {len(views)} saved view(s)?").classes("break-words")
                with ui.row().classes("full-width justify-end gap-2"):
                    ui.button("Cancel", on_click=dialog.close).props("flat dense")
                    ui.button("Delete", color="negative", on_click=lambda: (
                        dialog.close(), self.delete_crystal_from_list(name, confirmed=True))).props("unelevated dense")
            dialog.open()
            return
        if not self.library.delete(name):
            ui.notify(f"Could not delete {name}", type="warning")
            return
        try:
            self.view_store.delete_crystal(identity)
        except (ValueError, OSError) as exc:
            ui.notify(f"Crystal deleted, but saved-view cleanup failed: {exc}", type="warning")
        self.model_cache.clear()
        self.clear_scientific_caches()
        affected_panel_ids: set[int] = set()
        for state in self.panel_states:
            if state.crystal_name == name:
                self.set_panel_crystal(state, "FCC", force_default_color=True)
                state.zone_text = ""
                state.applied_zone_text = "100"
                state.view_vector = np.array([1.0, 0.0, 0.0])
                state.roll = 0.0
                affected_panel_ids.add(state.panel_id)
        self.refresh_panel_crystal_select_options()
        self.redraw_panel_controllers(affected_panel_ids)
        if affected_panel_ids:
            self.refresh_combo_panels_for_sources(affected_panel_ids)
        self.refresh_crystal_list()
        self.set_status(f"Deleted crystal: {name}")
        ui.notify(f"Deleted crystal: {name}", type="positive")

    async def load_cif_upload(self, event: Any) -> None:
        upload_name = Path(str(getattr(event.file, "name", "uploaded.cif"))).name
        suffix = Path(upload_name).suffix or ".cif"
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
                temp_path = Path(handle.name)
            await event.file.save(temp_path)
            definition = definition_from_cif(temp_path)
            base_name = Path(upload_name).stem or definition.name
            definition.name = base_name
            counter = 2
            while self.library.exists(definition.name):
                definition.name = f"{base_name} {counter}"
                counter += 1
            saved = self.library.save_new(definition, USER_LIBRARY_SCOPE)
        except ValueError as exc:
            message = str(exc)
            self.set_status(f"CIF import failed: {message}")
            ui.notify(message, type="negative")
            return
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

        self.refresh_panel_crystal_select_options()
        self.add_panel(crystal_name=saved.name)
        self.refresh_crystal_list()
        self.set_status(f"Loaded CIF: {saved.name}")
        ui.notify(f"Loaded CIF: {saved.name}", type="positive")
        if self.cif_dialog is not None:
            self.cif_dialog.close()
        sender = getattr(event, "sender", None)
        if sender is not None and hasattr(sender, "reset"):
            sender.reset()

    def add_styles(self) -> None:
        ui.add_css(
            """
            body {
                background: #11161d;
            }
            .q-page-container .nicegui-content {
                padding-top: 0 !important;
            }
            .app-header {
                background: #161c24;
                border-bottom: 1px solid rgba(255, 255, 255, 0.08);
                height: auto !important;
                min-height: 38px !important;
                padding: 3px 8px;
                display: flex;
                flex-wrap: wrap !important;
                align-items: center;
                align-content: center;
                gap: 4px 6px;
                overflow: visible;
            }
            .app-header.wrap {
                flex-wrap: wrap !important;
            }
            .app-header > * {
                flex-shrink: 0;
            }
            .app-header .q-space {
                flex: 1 1 auto;
                min-width: 0;
            }
            .app-title {
                font-size: 14px;
                font-weight: 650;
                letter-spacing: 0;
            }
            .intro-button {
                margin-left: 8px;
            }
            .app-header .q-btn {
                min-height: 28px;
                padding: 2px 7px;
                font-size: 12px;
            }
            .app-shell {
                width: calc(100vw - 32px);
                max-width: 1920px;
                margin: 2px auto 16px auto;
                --panel-visual-height: clamp(285px, calc((100vh - 240px) / 2), 360px);
            }
            .comparison-panel {
                border-radius: 8px;
                background: #18202a;
                border: 1px solid rgba(255, 255, 255, 0.08);
                box-shadow: none;
            }
            .top-checkbox {
                min-height: 28px;
                align-items: center;
                color: #eef2f6;
                flex: 0 1 auto;
            }
            .top-checkbox .q-checkbox__label {
                font-size: 12px;
            }
            .top-checkbox .q-checkbox__inner {
                font-size: 28px;
            }
            .panel-grid {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 6px;
                align-items: start;
            }
            .comparison-panel {
                width: 100%;
                min-width: 0;
                padding: 5px;
                container-type: inline-size;
                container-name: comparison-panel;
            }
            .comparison-panel.panel-magnified {
                grid-column: span 2;
                --panel-visual-height: clamp(570px, calc(100vh - 240px), 720px);
            }
            .combo-panel {
                background: #151f2d;
                border-color: rgba(130, 178, 245, 0.28);
            }
            .panel-toolbar {
                width: 100%;
                display: grid;
                grid-template-columns: 20px minmax(70px, 1fr) minmax(50px, 0.64fr) minmax(50px, 0.64fr) minmax(62px, 0.76fr) minmax(54px, 0.66fr) minmax(48px, auto) minmax(44px, auto) 24px 24px 24px 24px 24px;
                grid-template-areas: "number crystal zone plane vector rotation apply sync colors download edit magnify close";
                gap: 2px;
                align-items: center;
                margin-bottom: 6px;
            }
            .panel-number {
                grid-area: number;
                width: 20px;
                height: 38px;
                display: flex;
                align-items: center;
                justify-content: center;
                color: #d7dee8;
                font-size: 13px;
                font-weight: 700;
            }
            .panel-crystal,
            .panel-index,
            .panel-vector,
            .panel-rotation {
                min-width: 0;
            }
            .panel-crystal {
                grid-area: crystal;
            }
            .panel-zone {
                grid-area: zone;
            }
            .panel-plane {
                grid-area: plane;
            }
            .panel-vector {
                grid-area: vector;
            }
            .panel-rotation {
                grid-area: rotation;
            }
            .panel-close-button {
                grid-area: close;
                width: 24px;
                height: 34px;
                min-height: 34px;
            }
            .panel-edit-button {
                grid-area: edit;
                width: 24px;
                height: 34px;
                min-height: 34px;
            }
            .panel-download-button {
                grid-area: download;
                width: 24px;
                height: 34px;
                min-height: 34px;
            }
            .panel-colors-button {
                grid-area: colors;
                width: 24px;
                height: 34px;
                min-height: 34px;
                justify-self: start;
            }
            .panel-magnify-button {
                grid-area: magnify;
                width: 24px;
                height: 34px;
                min-height: 34px;
            }
            .panel-apply-button {
                grid-area: apply;
                min-width: 48px;
            }
            .panel-sync-button {
                grid-area: sync;
                min-width: 44px;
            }
            .combo-toolbar {
                width: 100%;
                display: grid;
                grid-template-columns: 34px minmax(116px, 1fr) auto auto minmax(104px, auto) 30px 30px 26px;
                grid-template-areas: "combo-number combo-select combo-add combo-remove combo-bind combo-download combo-magnify combo-close";
                gap: 4px;
                align-items: center;
                margin-bottom: 6px;
            }
            .combo-number {
                grid-area: combo-number;
                color: #dce9fb;
                font-size: 18px;
                font-weight: 750;
                line-height: 1;
                text-align: center;
            }
            .combo-source-select {
                grid-area: combo-select;
                min-width: 0;
            }
            .combo-action-button {
                min-width: 58px;
            }
            .combo-add-button {
                grid-area: combo-add;
            }
            .combo-remove-button {
                grid-area: combo-remove;
            }
            .combo-bind-checkbox {
                grid-area: combo-bind;
                min-height: 34px;
                align-items: center;
                color: #dce9fb;
            }
            .combo-bind-checkbox .q-checkbox__label {
                font-size: 11px;
                white-space: nowrap;
            }
            .combo-bind-checkbox .q-checkbox__inner {
                font-size: 24px;
            }
            .combo-download-button {
                grid-area: combo-download;
            }
            .combo-magnify-button {
                grid-area: combo-magnify;
            }
            .combo-toolbar .panel-close-button {
                grid-area: combo-close;
            }
            .comparison-panel .q-field--dense .q-field__control,
            .comparison-panel .q-field--dense .q-field__marginal {
                min-height: 38px;
                height: 38px;
            }
            .comparison-panel .q-field__label {
                font-size: 10px;
                top: 4px;
            }
            .comparison-panel .q-field--float .q-field__label {
                transform: translateY(-24%) scale(0.72);
            }
            .comparison-panel .q-field__native,
            .comparison-panel .q-field__input {
                font-size: 11.5px;
                line-height: 16px;
                min-height: 38px;
                padding-top: 10px;
                padding-bottom: 2px;
            }
            .comparison-panel .q-select .q-field__native {
                min-height: 20px;
                height: 20px;
                padding: 0;
                overflow: hidden;
                align-items: center;
                font-size: 11.5px;
                line-height: 16px;
            }
            .comparison-panel .q-select .q-field__input {
                min-height: 20px;
                height: 20px;
                padding: 0;
                line-height: 16px;
                font-size: 11.5px;
                align-self: center;
            }
            .comparison-panel .q-select .q-field__control-container {
                padding-top: 15px;
                min-height: 38px;
            }
            .comparison-panel .q-btn {
                min-height: 34px;
                padding: 2px 5px;
                font-size: 11.5px;
            }
            .panel-toolbar .q-btn--round {
                min-width: 24px;
                padding: 0;
            }
            .visual-stack {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 8px;
                width: 100%;
                height: var(--panel-visual-height);
                min-height: var(--panel-visual-height);
                max-height: var(--panel-visual-height);
                align-items: stretch;
                overflow: hidden;
            }
            .panel-splitter {
                width: 100%;
                height: var(--panel-visual-height);
                min-height: var(--panel-visual-height);
                max-height: var(--panel-visual-height);
                overflow: hidden;
            }
            .panel-splitter > .q-splitter__panel {
                min-width: 0;
                min-height: 0;
                overflow: hidden;
            }
            .panel-splitter .scene-wrap,
            .panel-splitter .real-scene,
            .panel-splitter .combo-source-list,
            .panel-splitter .diffraction-plot {
                height: 100% !important;
                min-height: 0 !important;
                max-height: 100% !important;
            }
            .panel-splitter > .q-splitter__separator {
                background: transparent;
                flex-shrink: 0;
            }
            .panel-splitter.q-splitter--vertical > .q-splitter__separator {
                width: 0;
            }
            .panel-splitter.q-splitter--horizontal > .q-splitter__separator {
                height: 0;
            }
            .panel-splitter.q-splitter--vertical > .q-splitter__before {
                padding-right: 5px;
            }
            .panel-splitter.q-splitter--vertical > .q-splitter__after {
                padding-left: 5px;
            }
            .panel-splitter.q-splitter--horizontal > .q-splitter__before {
                padding-bottom: 5px;
            }
            .panel-splitter.q-splitter--horizontal > .q-splitter__after {
                padding-top: 5px;
            }
            .panel-splitter.split-at-start > .q-splitter__panel,
            .panel-splitter.split-at-end > .q-splitter__panel {
                padding: 0;
            }
            .panel-splitter.split-at-start > .q-splitter__before,
            .panel-splitter.split-at-end > .q-splitter__after {
                visibility: hidden;
                pointer-events: none;
            }
            .panel-splitter.q-splitter--vertical.split-at-start .q-splitter__separator-area {
                left: 0;
                right: -12px;
            }
            .panel-splitter.q-splitter--vertical.split-at-end .q-splitter__separator-area {
                left: -12px;
                right: 0;
            }
            .panel-splitter.q-splitter--horizontal.split-at-start .q-splitter__separator-area {
                top: 0;
                bottom: -12px;
            }
            .panel-splitter.q-splitter--horizontal.split-at-end .q-splitter__separator-area {
                top: -12px;
                bottom: 0;
            }
            .panel-splitter .panel-split-handle {
                position: absolute;
                inset: 0;
                width: 100%;
                height: 100%;
                transform: none;
                touch-action: none;
                outline: none;
            }
            .panel-split-handle::after {
                content: '';
                position: absolute;
                width: 3px;
                height: 40px;
                left: 50%;
                top: 50%;
                transform: translate(-50%, -50%);
                border-radius: 2px;
                background: #59697B;
            }
            .q-splitter--horizontal .panel-split-handle::after {
                width: 40px;
                height: 3px;
            }
            .panel-split-handle:hover::after {
                background: #8BBFFF;
            }
            @media (max-width: 599px) {
                .panel-splitter {
                    height: calc(2 * var(--panel-visual-height) + 10px);
                    min-height: calc(2 * var(--panel-visual-height) + 10px);
                    max-height: calc(2 * var(--panel-visual-height) + 10px);
                }
            }
            .combo-source-list {
                width: 100%;
                height: 100%;
                min-height: 0;
                overflow: auto;
                border-radius: 8px;
                background: #0b1017;
                border: 1px solid rgba(255, 255, 255, 0.10);
                padding: 8px;
            }
            .combo-source-header,
            .combo-source-row {
                display: grid;
                grid-template-columns: 24px 34px minmax(48px, 1fr) minmax(54px, 0.58fr) 86px;
                gap: 5px;
                align-items: center;
            }
            .combo-source-header,
            .combo-source-rows {
                min-width: 266px;
            }
            .combo-source-drag {
                width: 24px;
                min-width: 24px;
                height: 32px;
                cursor: grab;
                touch-action: none;
                user-select: none;
            }
            .combo-source-chosen { background: rgba(120, 170, 220, 0.12); }
            .combo-source-ghost { background: #1b222b; opacity: 0.85; }
            .coordinate-grid-fields > .q-field,
            .coordinate-grid-bounds > .q-field { min-width: 0; }
            .coordinate-grid-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            @media (max-width: 599px) {
                .coordinate-grid-fields { grid-template-columns: minmax(0, 1fr); }
            }
            .combo-source-header {
                color: #eff6ff;
                font-size: 11px;
                font-weight: 700;
                padding: 0 0 8px 0;
                border-bottom: 1px dashed rgba(255, 255, 255, 0.50);
                margin-bottom: 8px;
            }
            .combo-source-row {
                min-height: 36px;
                width: 100%;
                color: #edf2f7;
                font-size: 11.5px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.06);
            }
            .combo-source-name,
            .combo-source-zone {
                min-width: 0;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            .combo-source-panel-id {
                font-weight: 700;
            }
            .combo-source-actions {
                gap: 0;
                justify-content: end;
            }
            .combo-source-actions .q-btn {
                min-width: 24px;
                width: 24px;
                min-height: 24px;
                height: 24px;
                padding: 0;
            }
            .scene-wrap {
                position: relative;
                width: 100%;
                height: var(--panel-visual-height);
                min-height: var(--panel-visual-height);
                max-height: var(--panel-visual-height);
                min-width: 0;
                overflow: hidden;
            }
            .real-scene {
                box-sizing: border-box;
                width: 100% !important;
                height: 100% !important;
                min-height: 0 !important;
                max-height: 100% !important;
                border-radius: 8px;
                overflow: hidden;
                border: 1px solid rgba(255, 255, 255, 0.08);
            }
            .atom-inspector {
                position: absolute;
                top: 0;
                left: 0;
                width: min(320px, calc(100% - 44px));
                max-height: 100%;
                overflow: auto;
                z-index: 3;
                padding: 8px 10px;
                gap: 2px;
                border: 1px solid #626970;
                border-radius: 4px;
                background: rgba(20, 23, 27, 0.95);
                color: #f5f6f7;
                font-size: 12px;
                user-select: text;
            }
            .atom-coordinate-caption {
                color: #b6bdc5;
                font-size: 11px;
                margin-top: 3px;
            }
            .atom-coordinate-value {
                width: 100%;
                overflow-wrap: anywhere;
                font-variant-numeric: tabular-nums;
            }
            .marker-picking canvas {
                cursor: crosshair;
            }
            .real-scale-bar {
                position: absolute;
                left: 0;
                bottom: 14px;
                width: 100%;
                min-width: 0;
                pointer-events: none;
                color: #f7fafc;
                text-shadow: 0 1px 3px rgba(0, 0, 0, 0.85);
            }
            .real-scale-line {
                height: 3px;
                width: 80px;
                min-width: 0;
                max-width: none;
                margin-left: 16px;
                background: #f7fafc;
                border-left: 2px solid #f7fafc;
                border-right: 2px solid #f7fafc;
                box-shadow: 0 1px 4px rgba(0, 0, 0, 0.7);
            }
            .real-scale-label {
                margin-left: 16px;
                margin-top: 3px;
                color: #f7fafc;
                font-size: 12px;
                line-height: 1;
                font-weight: 600;
            }
            .diffraction-plot {
                box-sizing: border-box;
                width: 100%;
                min-width: 0;
                height: var(--panel-visual-height) !important;
                min-height: var(--panel-visual-height) !important;
                max-height: var(--panel-visual-height) !important;
                border-radius: 8px;
                overflow: hidden;
                background: transparent;
                border: 0;
            }
            .diffraction-plot,
            .diffraction-plot > div,
            .diffraction-plot .plot-container,
            .diffraction-plot .svg-container,
            .diffraction-plot .main-svg {
                width: 100%;
                height: 100% !important;
                min-height: 0 !important;
                max-height: 100% !important;
                display: block;
            }
            .q-dialog .advanced-card.q-card {
                width: min(1120px, calc(100vw - 40px)) !important;
                max-width: calc(100vw - 40px) !important;
                border-radius: 8px;
            }
            .cif-card {
                width: min(620px, calc(100vw - 40px));
                border-radius: 8px;
            }
            .download-card {
                width: min(420px, calc(100vw - 40px));
                border-radius: 8px;
                gap: 8px;
            }
            .static-download-card {
                width: 1040px;
                max-width: calc(100vw - 32px) !important;
                padding: 18px;
                gap: 12px;
            }
            .static-download-options {
                display: grid;
                grid-template-columns: repeat(3, minmax(0, 1fr));
                gap: 12px;
                width: 100%;
            }
            .static-download-options .q-field { min-width: 0; }
            .static-download-previews {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 12px;
                width: 100%;
            }
            .static-download-single { grid-template-columns: minmax(0, 1fr); }
            .static-download-tile { width: 100%; min-width: 0; }
            .static-download-tile .text-negative { overflow-wrap: anywhere; }
            .static-download-image {
                width: 100%;
                height: 300px;
                background-color: #252525;
                border: 1px solid #555;
                border-radius: 4px;
            }
            .static-download-transparent {
                background-image: conic-gradient(#383838 25%, #252525 0 50%, #383838 0 75%, #252525 0);
                background-size: 20px 20px;
            }
            @media(max-width:700px) {
                .static-download-options { grid-template-columns: repeat(2, minmax(0, 1fr)); }
                .static-download-previews { grid-template-columns: minmax(0, 1fr); }
                .static-download-image { height: 250px; }
            }
            @media(max-width:440px) {
                .static-download-card { padding: 12px; }
                .static-download-options { grid-template-columns: minmax(0, 1fr); }
                .static-download-actions { justify-content: flex-end; }
            }
            .occupancy-warning-card {
                width: min(560px, calc(100vw - 40px));
                max-width: calc(100vw - 40px) !important;
                border-radius: 8px;
                gap: 12px;
                overflow-wrap: anywhere;
            }
            .occupancy-warning-list {
                width: 100%;
                max-height: 35vh;
                overflow-y: auto;
                gap: 12px;
            }
            .export-folder-label {
                max-width: 100%;
                color: #B8C0CC;
                font-size: 12px;
                line-height: 1.35;
                overflow-wrap: anywhere;
            }
            .intro-card {
                width: min(1180px, calc(100vw - 32px));
                max-width: calc(100vw - 32px);
                max-height: min(820px, calc(100vh - 40px));
                border-radius: 8px;
                overflow-y: auto;
                overflow-x: hidden;
            }
            .intro-text {
                color: #e5edf7;
                font-size: 13px;
                line-height: 1.42;
                white-space: normal;
                overflow-wrap: anywhere;
            }
            .intro-text h3 {
                margin: 10px 0 5px 0;
                color: #f8fafc;
                font-size: 15px;
                font-weight: 700;
            }
            .intro-text p,
            .intro-text ol,
            .intro-text ul {
                margin-top: 4px;
                margin-bottom: 8px;
            }
            .palette-card {
                width: min(760px, calc(100vw - 40px));
                max-width: calc(100vw - 40px) !important;
                max-height: calc(100vh - 40px);
                border-radius: 8px;
                gap: 10px;
                overflow: hidden;
                flex-wrap: nowrap;
            }
            .panel-settings-card {
                width: min(1500px, calc(100vw - 40px));
                height: calc(100vh - 40px);
                height: calc(100dvh - 40px);
            }
            .palette-card > .row {
                flex-shrink: 0;
            }
            .display-settings-body {
                display: grid;
                grid-template-columns: minmax(0, 1fr);
                width: 100%;
                flex: 1 1 auto;
                min-height: 0;
                overflow: hidden;
            }
            .panel-splitter.panel-settings-body {
                height: 100%;
                min-height: 0;
                max-height: 100%;
            }
            .panel-settings-body .display-settings-preview,
            .panel-settings-body .display-settings-controls {
                height: 100%;
            }
            .panel-settings-body > .q-splitter__after {
                overflow-x: auto;
            }
            .panel-settings-body .display-settings-controls {
                min-width: 280px;
                width: 100%;
            }
            .display-settings-controls {
                container-type: inline-size;
                min-width: 0;
                min-height: 0;
                overflow-y: auto;
                overflow-x: hidden;
                overscroll-behavior: contain;
                scrollbar-gutter: stable;
                padding-right: 4px;
                gap: 10px;
            }
            .panel-frame-settings, .panel-element-sizes, .panel-cell-counts,
            .panel-background-settings, .annotation-style-grid, .theme-color-grid {
                max-width: 640px;
            }
            @container (max-width: 340px) {
                .panel-frame-settings,
                .panel-element-sizes,
                .panel-cell-counts,
                .panel-background-settings,
                .theme-color-grid,
                .annotation-style-grid {
                    grid-template-columns: minmax(0, 1fr) !important;
                }
            }
            .palette-card .q-field {
                min-width: 0;
            }
            .theme-sample {
                padding: 12px;
                border: 1px solid;
                border-radius: 4px;
                display: flex;
                align-items: center;
                flex-wrap: wrap;
                gap: 12px;
            }
            .theme-card {
                width: 680px;
                max-width: calc(100vw - 40px);
                max-height: calc(100dvh - 48px);
                flex-wrap: nowrap;
            }
            .theme-dialog-body { min-height: 0; overflow-y: auto; }
            .theme-name-card { width: 420px; max-width: calc(100vw - 40px); }
            .theme-card > :first-child, .theme-card > :last-child { flex-shrink: 0; }
            .theme-panel-sample {
                flex: 1;
                min-width: 0;
                padding: 20px 8px;
                text-align: center;
                border-radius: 4px;
            }
            @media (max-width: 480px) {
                .theme-card .theme-color-grid { grid-template-columns: minmax(0, 1fr) !important; }
            }
            .theme-sample-accent {
                padding: 8px;
                border-radius: 4px;
                background: var(--sample-accent);
                color: var(--sample-ink);
            }
            .display-settings-preview {
                display: flex;
                flex-direction: column;
                min-width: 0;
                min-height: 0;
                gap: 4px;
            }
            .display-settings-preview .visual-stack {
                flex: 1 1 0;
                grid-template-columns: minmax(0, 1fr);
                grid-template-rows: repeat(2, minmax(0, 1fr));
                height: 100%;
                min-height: 0;
                max-height: none;
            }
            .display-settings-preview .scene-wrap,
            .display-settings-preview .diffraction-plot {
                height: 100% !important;
                min-height: 0;
                max-height: 100% !important;
            }
            .settings-preview-pane {
                position: relative;
                min-height: 0;
                min-width: 0;
                overflow: hidden;
            }
            .preview-magnify {
                position: absolute;
                top: 8px;
                right: 8px;
                z-index: 4;
                background: rgba(20, 23, 27, 0.9);
            }
            .display-settings-preview .visual-stack.preview-expanded {
                grid-template-columns: minmax(0, 1fr);
                grid-template-rows: minmax(0, 1fr);
            }
            .display-settings-actions {
                flex-wrap: wrap;
                gap: 8px;
            }
            @media (max-width: 600px) {
                .element-color-tools {
                    flex-direction: column;
                    align-items: stretch;
                }
                .element-color-grid {
                    grid-template-columns: minmax(0, 1fr) !important;
                }
                .palette-card .text-h6 {
                    font-size: 16px;
                    overflow-wrap: anywhere;
                }
            }
            .palette-columns {
                width: 100%;
                align-items: stretch;
                gap: 14px;
            }
            .palette-column {
                flex: 1 1 300px;
                min-width: 0;
                gap: 8px;
            }
            .palette-title {
                color: #eff6ff;
                font-weight: 700;
                font-size: 13px;
            }
            .palette-actions {
                gap: 5px;
            }
            .palette-actions .q-btn {
                min-height: 26px;
                padding: 1px 6px;
                font-size: 11px;
            }
            .palette-list {
                width: 100%;
                max-height: min(460px, calc(100vh - 220px));
                overflow-y: auto;
                display: flex;
                flex-direction: column;
                gap: 6px;
            }
            .palette-row {
                display: grid;
                grid-template-columns: 22px minmax(0, 1fr) 28px 28px 28px;
                gap: 5px;
                align-items: center;
                width: 100%;
            }
            .palette-index {
                color: #dbeafe;
                font-weight: 700;
                font-size: 12px;
            }
            .palette-color-input {
                min-width: 0;
            }
            .palette-row .q-btn {
                min-width: 26px;
                width: 26px;
                min-height: 26px;
                height: 26px;
                padding: 0;
            }
            .crystal-list-card {
                width: min(760px, calc(100vw - 40px));
                border-radius: 8px;
            }
            .crystal-list {
                width: 100%;
                max-height: min(650px, calc(100vh - 160px));
                overflow-y: auto;
                gap: 6px;
            }
            .crystal-list-row {
                width: 100%;
                position: relative;
                display: grid;
                grid-template-columns: 20px minmax(0, 1fr) repeat(4, 34px);
                align-items: center;
                gap: 8px;
                padding: 6px 4px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            }
            .crystal-list-swatch {
                width: 14px;
                height: 14px;
                border-radius: 50%;
                border: 1px solid rgba(255, 255, 255, 0.36);
            }
            .crystal-list-entry { padding-left: 24px; }
            .crystal-list-row > .q-btn:not(.saved-view-toggle) {
                min-width: 0;
                width: 100%;
                padding: 0;
            }
            .saved-view-toggle.q-btn {
                position: absolute;
                left: -24px;
                min-width: 24px;
                width: 24px;
            }
            .saved-view-list {
                width: 100%;
                padding: 4px 0 8px 30px;
                gap: 4px;
            }
            .saved-view-row {
                width: 100%;
                display: grid;
                grid-template-columns: minmax(0, 1fr) 18px 28px 28px 28px;
                align-items: center;
                gap: 3px;
            }
            .saved-view-row .q-btn { min-width: 0; }
            .saved-view-open .q-btn__content { flex-wrap: nowrap; min-width: 0; }
            .saved-view-open .block { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
            .saved-view-dialog { width: 440px; max-width: calc(100vw - 40px); }
            .crystal-list-info {
                gap: 0;
                min-width: 0;
                overflow-wrap: anywhere;
            }
            .crystal-list-name {
                font-size: 13px;
                font-weight: 650;
                line-height: 1.2;
            }
            .crystal-list-meta {
                color: #9aa7b5;
                font-size: 11px;
                line-height: 1.2;
            }
            @media (max-width: 480px) {
                .crystal-list-row {
                    grid-template-columns: 14px minmax(0, 1fr) repeat(4, 26px);
                    gap: 2px;
                    padding: 6px 0;
                }
            }
            .advanced-body {
                width: 100%;
                display: flex;
                flex-direction: column;
                gap: 12px;
                align-items: stretch;
            }
            .advanced-grid {
                width: 100%;
                grid-template-columns: repeat(3, minmax(190px, 1fr)) !important;
                gap: 10px;
            }
            .advanced-checkbox {
                min-height: 40px;
                align-items: center;
                align-self: center;
                justify-self: start;
                max-width: 100%;
                color: #eef2f6;
            }
            .advanced-tooltip {
                max-width: min(320px, calc(100vw - 24px));
                white-space: normal;
                overflow-wrap: anywhere;
                font-size: 12px;
                line-height: 1.4;
                text-align: left;
            }
            .advanced-checkbox .q-checkbox__label {
                font-size: 12px;
            }
            .advanced-slider-field {
                min-height: 54px;
                padding: 2px 4px 0 4px;
            }
            .advanced-slider-label {
                color: #cfd7e3;
                font-size: 12px;
                line-height: 1.1;
                margin-bottom: 2px;
            }
            .advanced-slider {
                margin: 28px 12px 0;
                width: calc(100% - 24px);
            }
            .advanced-log {
                width: 100%;
                min-height: 128px;
            }
            .advanced-log textarea {
                font-size: 12px;
                line-height: 1.35;
            }
            .builder-card {
                width: min(1500px, calc(100vw - 32px)) !important;
                max-width: calc(100vw - 32px) !important;
                border-radius: 8px;
            }
            .builder-grid {
                width: 100%;
                grid-template-columns: repeat(5, minmax(130px, 1fr)) !important;
                gap: 10px;
            }
            .builder-footer {
                width: 100%;
                display: flex;
                flex-wrap: wrap;
                align-items: center;
                justify-content: space-between;
                gap: 12px;
            }
            .builder-formula {
                flex: 1 1 240px;
                min-width: 0;
                max-width: 100%;
                align-items: center;
                flex-wrap: nowrap;
                gap: 8px;
            }
            .formula-content {
                min-width: 0;
                gap: 2px;
            }
            .formula-mode {
                font-size: 12px;
                opacity: 0.7;
            }
            .formula-value {
                max-width: 100%;
                min-height: 32px;
                font-size: 20px;
                line-height: 1.6;
                overflow-wrap: anywhere;
            }
            .formula-value sub {
                font-size: 0.75em;
                line-height: 0;
            }
            .formula-cycle {
                flex: 0 0 32px;
                width: 32px;
                height: 32px;
            }
            .builder-save-actions {
                max-width: 100%;
                flex-wrap: wrap;
                justify-content: flex-end;
                gap: 8px;
            }
            .site-row {
                display: grid;
                grid-template-columns: minmax(128px, 1.1fr) repeat(4, minmax(86px, 0.72fr)) minmax(130px, 0.9fr) minmax(112px, 0.8fr) 38px;
                gap: 8px;
                width: 100%;
                align-items: start;
            }
            @container comparison-panel (max-width: 650px) {
                .panel-toolbar {
                    grid-template-columns: 24px minmax(112px, 1.45fr) minmax(72px, 0.8fr) minmax(72px, 0.8fr) minmax(86px, 0.95fr) minmax(76px, 0.85fr);
                    grid-template-areas:
                        "number crystal zone plane vector rotation"
                        "number apply sync colors download edit"
                        "number magnify close . . .";
                }
                .panel-number {
                    height: 100%;
                    min-height: 38px;
                    align-items: flex-start;
                    padding-top: 8px;
                }
                .panel-apply-button,
                .panel-sync-button,
                .panel-download-button,
                .panel-magnify-button,
                .panel-edit-button,
                .panel-toolbar .panel-close-button {
                    justify-self: start;
                }
                .combo-toolbar {
                    grid-template-columns: 42px minmax(150px, 1fr) auto auto minmax(112px, auto) 30px 30px 28px;
                }
            }
            @container comparison-panel (max-width: 500px) {
                .panel-toolbar {
                    grid-template-columns: 22px repeat(4, minmax(0, 1fr));
                    grid-template-areas:
                        "number crystal crystal crystal crystal"
                        "number zone zone plane plane"
                        "number vector vector rotation rotation"
                        "number apply apply sync colors"
                        "number download edit magnify close";
                }
                .panel-apply-button,
                .panel-sync-button {
                    width: 100%;
                    min-width: 0;
                    justify-self: stretch;
                }
                .panel-download-button,
                .panel-magnify-button,
                .panel-edit-button,
                .panel-toolbar .panel-close-button {
                    justify-self: start;
                }
                .combo-toolbar {
                    grid-template-columns: 34px minmax(0, 1fr) 30px 30px 28px;
                    grid-template-areas:
                        "combo-number combo-select combo-download combo-magnify combo-close"
                        "combo-number combo-add combo-add combo-remove combo-remove"
                        "combo-number combo-bind combo-bind combo-bind .";
                }
                .combo-action-button {
                    width: 100%;
                    min-width: 0;
                }
            }
            @media (max-width: 1180px) and (min-width: 761px) {
                .panel-toolbar {
                    grid-template-columns: 24px minmax(112px, 1.45fr) minmax(72px, 0.8fr) minmax(72px, 0.8fr) minmax(86px, 0.95fr) minmax(76px, 0.85fr);
                    grid-template-areas:
                        "number crystal zone plane vector rotation"
                        "number apply sync colors download edit"
                        "number magnify close . . .";
                }
                .panel-number {
                    height: 100%;
                    min-height: 38px;
                    align-items: flex-start;
                    padding-top: 8px;
                }
                .panel-apply-button,
                .panel-sync-button,
                .panel-download-button,
                .panel-magnify-button,
                .panel-edit-button,
                .panel-toolbar .panel-close-button {
                    justify-self: start;
                }
            }
            @media (max-width: 1280px) {
                .app-header {
                    padding: 3px 6px;
                    gap: 3px 5px;
                }
                .app-header .q-space {
                    display: none;
                }
                .app-title {
                    font-size: 13px;
                }
                .intro-button {
                    margin-left: 2px;
                }
                .app-header .q-btn {
                    min-height: 26px;
                    padding: 1px 5px;
                    font-size: 11px;
                }
                .top-checkbox {
                    min-height: 26px;
                }
                .top-checkbox .q-checkbox__label {
                    font-size: 11px;
                }
                .top-checkbox .q-checkbox__inner {
                    font-size: 24px;
                }
            }
            @media (max-width: 1100px) {
                .panel-grid {
                    grid-template-columns: 1fr;
                }
                .comparison-panel.panel-magnified {
                    grid-column: span 1;
                    --panel-visual-height: 600px;
                }
                .app-shell {
                    --panel-visual-height: 300px;
                }
                .panel-toolbar {
                    grid-template-columns: 24px minmax(112px, 1.45fr) minmax(72px, 0.8fr) minmax(72px, 0.8fr) minmax(86px, 0.95fr) minmax(76px, 0.85fr);
                    grid-template-areas:
                        "number crystal zone plane vector rotation"
                        "number apply sync colors download edit"
                        "number magnify close . . .";
                }
                .panel-number {
                    height: 100%;
                    min-height: 38px;
                    align-items: flex-start;
                    padding-top: 8px;
                }
                .panel-apply-button,
                .panel-sync-button,
                .panel-download-button,
                .panel-magnify-button,
                .panel-edit-button,
                .panel-toolbar .panel-close-button {
                    justify-self: start;
                }
                .combo-toolbar {
                    grid-template-columns: 42px minmax(150px, 1fr) auto auto minmax(112px, auto) 30px 30px 28px;
                }
                .combo-toolbar .q-space {
                    display: none;
                }
            }
            @media (max-width: 760px) {
                .app-shell {
                    width: calc(100vw - 16px);
                    margin-top: 5px;
                    --panel-visual-height: 230px;
                }
                .comparison-panel.panel-magnified {
                    grid-column: span 1;
                    --panel-visual-height: 460px;
                }
                .advanced-grid,
                .builder-grid {
                    grid-template-columns: 1fr !important;
                }
                .panel-toolbar {
                    grid-template-columns: 22px repeat(4, minmax(0, 1fr));
                    grid-template-areas:
                        "number crystal crystal crystal crystal"
                        "number zone zone plane plane"
                        "number vector vector rotation rotation"
                        "number apply apply sync colors"
                        "number download edit magnify close";
                }
                .panel-apply-button,
                .panel-sync-button {
                    width: 100%;
                    min-width: 0;
                    justify-self: stretch;
                }
                .panel-download-button,
                .panel-magnify-button,
                .panel-edit-button,
                .panel-toolbar .panel-close-button {
                    justify-self: start;
                }
                .advanced-body {
                    grid-template-columns: 1fr;
                }
                .panel-grid {
                    grid-template-columns: 1fr;
                }
                .visual-stack {
                    grid-template-columns: 1fr;
                    height: auto;
                    min-height: 0;
                    max-height: none;
                    overflow: visible;
                }
                .combo-toolbar {
                    grid-template-columns: 34px minmax(0, 1fr) 30px 30px 28px;
                    grid-template-areas:
                        "combo-number combo-select combo-download combo-magnify combo-close"
                        "combo-number combo-add combo-add combo-remove combo-remove"
                        "combo-number combo-bind combo-bind combo-bind .";
                }
                .combo-action-button {
                    width: 100%;
                    min-width: 0;
                }
                .combo-source-list {
                    height: var(--panel-visual-height);
                }
                .site-row {
                    grid-template-columns: 1fr 1fr;
                }
                .real-scene {
                    height: var(--panel-visual-height) !important;
                }
                .diffraction-plot {
                    height: var(--panel-visual-height);
                }
            }
            """
        )

    def set_status(self, text: str) -> None:
        message = str(text or "").strip() or "Ready"
        self.status_history.append(message)
        self.status_history = self.status_history[-10:]
        if self.log_box is not None:
            self.log_box.value = "\n".join(self.status_history)
            self.log_box.update()

    def direct_file_exports_enabled(self) -> bool:
        return direct_file_exports_enabled()

    def ensure_export_dir(self) -> Path:
        folder = self.selected_export_dir or default_export_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            folder = USER_DATA_DIR / "exports"
            folder.mkdir(parents=True, exist_ok=True)
        self.selected_export_dir = folder
        return folder

    def export_dir_text(self) -> str:
        return str(self.ensure_export_dir())

    def set_export_folder(self, folder: Path, label: Any | None = None) -> bool:
        try:
            folder = Path(folder).expanduser()
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            ui.notify(f"Could not use export folder: {exc}", type="negative")
            return False
        self.selected_export_dir = folder
        if label is not None:
            label.text = f"Export folder: {folder}"
            label.update()
        self.set_status(f"Export folder: {folder}")
        ui.notify(f"Export folder: {folder}", type="positive")
        return True

    def open_export_folder_path_dialog(self, label: Any | None = None) -> None:
        dialog = ui.dialog()
        with dialog, ui.card().classes("download-card"):
            with ui.row().classes("items-center justify-between full-width"):
                ui.label("Choose export folder").classes("text-h6")
                ui.button(icon="close", on_click=dialog.close).props("flat round dense").tooltip("Close")
            ui.label(
                "Enter a folder path for Linux browser mode. The folder will be created if it does not exist."
            ).classes("text-caption text-grey-4")
            path_input = ui.input("Folder path", value=self.export_dir_text()).props("outlined dense").classes("full-width")

            def apply_path() -> None:
                path_text = str(path_input.value or "").strip()
                if not path_text:
                    ui.notify("Enter a folder path", type="warning")
                    return
                if self.set_export_folder(normalize_export_path(path_text), label):
                    dialog.close()

            path_input.on("keydown.enter", lambda _: apply_path())
            with ui.row().classes("justify-end full-width"):
                ui.button("Cancel", on_click=dialog.close).props("flat dense")
                ui.button("Use folder", icon="folder_open", on_click=apply_path).props("unelevated dense")
        dialog.open()

    async def choose_export_folder(self, label: Any | None = None) -> None:
        window = app.native.main_window
        if window is not None:
            try:
                import webview

                dialog_type = webview.FileDialog.FOLDER if hasattr(webview, "FileDialog") else webview.FOLDER_DIALOG
                result = await window.create_file_dialog(dialog_type=dialog_type, directory=str(self.ensure_export_dir()))
            except Exception as exc:
                ui.notify(f"Could not open folder picker: {exc}", type="warning")
            else:
                if not result:
                    ui.notify("Export cancelled", type="info")
                    self.set_status("Export cancelled")
                    return
                folder = Path(result[0] if isinstance(result, (list, tuple)) else result)
                self.set_export_folder(folder, label)
                return

        folder, picker_was_shown = await asyncio.to_thread(system_export_folder_dialog, self.ensure_export_dir())
        if folder is not None:
            self.set_export_folder(folder, label)
            return
        if picker_was_shown:
            ui.notify("Export cancelled", type="info")
            self.set_status("Export cancelled")
            return
        self.open_export_folder_path_dialog(label)

    async def choose_save_file(self, filename: str, extension: str) -> Path | None:
        suggested = self.ensure_export_dir() / sanitize_export_filename(filename, "crysdis_export", extension)
        selection, available = None, False
        window = app.native.main_window
        if window is not None:
            try:
                import webview
                dialog_type = webview.FileDialog.SAVE if hasattr(webview, "FileDialog") else webview.SAVE_DIALOG
                result = await window.create_file_dialog(dialog_type=dialog_type, directory=str(suggested.parent),
                    save_filename=suggested.name, file_types=(f"{extension[1:].upper()} files (*{extension})",))
                selection = Path(result[0] if isinstance(result, (list, tuple)) else result) if result else None
                available = True
            except Exception:
                pass
        if not available:
            selection, available = await asyncio.to_thread(system_save_file_dialog, suggested, extension)
        if not available:
            ui.notify("A native Save As dialog is unavailable. No file was saved. Install a system file picker or enable the native desktop window.", type="negative")
            return None
        if selection is None:
            return None
        # Some OS pickers do not append the selected format's extension.
        if selection.suffix.lower() != extension.lower():
            selection = selection.with_name(selection.name + extension)
            if selection.exists():
                with ui.dialog() as confirm, ui.card():
                    ui.label(f"Replace {selection.name}?")
                    with ui.row():
                        ui.button("Cancel", on_click=lambda: confirm.submit(False)).props("flat")
                        ui.button("Replace", on_click=lambda: confirm.submit(True))
                replace_file = await confirm
                confirm.delete()
                if not replace_file:
                    return None
        if not selection.parent.is_dir():
            raise ValueError("The selected save folder does not exist.")
        self.selected_export_dir = selection.parent
        return selection

    def save_exported_image(self, image_bytes: bytes, filename: str) -> Path:
        path = self.ensure_export_dir() / sanitize_export_filename(filename)
        path.write_bytes(image_bytes)
        return path

    def save_exported_text(self, text: str, filename: str, extension: str = ".txt") -> Path:
        path = self.ensure_export_dir() / sanitize_export_filename(filename, "crysdis_export", extension)
        path.write_text(text, encoding="utf-8")
        return path

    def announce_saved_exports(self, paths: list[Path]) -> None:
        if not paths:
            return
        if len(paths) == 1:
            message = f"Saved file to: {paths[0]}"
        else:
            message = f"Saved {len(paths)} files to: {paths[0].parent}"
        ui.notify(message, type="positive")
        self.set_status(message)

    def show_indices(self) -> bool:
        return bool(getattr(getattr(self, "show_indices_input", None), "value", False))

    def on_annotation_visibility_changed(self, kind: str) -> None:
        for state in self.panel_states:
            state.annotation_visibility.pop(kind, None)
        if kind == "crystal":
            self.refresh_crystal_scenes()
        else:
            self.refresh_diffractions()

    def show_crystal_annotations(self) -> bool:
        return bool(getattr(getattr(self, "show_crystal_annotations_input", None), "value", True))

    def plane_palette(self, panel_id: int | None = None) -> list[str]:
        return self.palette_values("plane", panel_id) or PLANE_COLORS

    def vector_palette(self, panel_id: int | None = None) -> list[str]:
        return self.palette_values("vector", panel_id) or VECTOR_COLORS

    def refresh_crystal_scenes(self) -> None:
        for controller in self.controllers:
            controller.redraw_scene(update_camera=False)

    def show_scale_bars(self) -> bool:
        return bool(getattr(getattr(self, "show_scale_bar_input", None), "value", getattr(self, "scale_bars_enabled", True)))

    def global_annotation_settings(self) -> PanelAnnotations:
        settings = getattr(self, "global_display_settings", None)
        return settings.annotations if settings is not None else PanelAnnotations()

    def on_scale_bar_changed(self) -> None:
        if getattr(self, "_updating_scale_bar_checkbox", False):
            return
        for state in self.panel_states:
            state.annotation_visibility.pop("scale", None)
        self.scale_bars_enabled = self.show_scale_bars()
        settings = self.global_annotation_settings()
        # A matched pair follows the toolbar; a mixed pair is a remembered filter.
        if settings.real_scale_visible == settings.reciprocal_scale_visible:
            settings.real_scale_visible = settings.reciprocal_scale_visible = self.scale_bars_enabled
            for state in self.panel_states:
                if "annotations" in state.global_display_sections:
                    annotations = state.display_settings.annotations
                    annotations.real_scale_visible = annotations.reciprocal_scale_visible = self.scale_bars_enabled
        for controller in self.controllers:
            controller.apply_scale_bar_visibility()
        self.refresh_diffractions()

    def current_simulation_method(self) -> str:
        value = str(getattr(getattr(self, "simulation_method_input", None), "value", SIMULATION_METHOD) or SIMULATION_METHOD)
        return value if value in SIMULATION_METHODS else SIMULATION_METHOD

    def always_snap_back_view(self) -> bool:
        return bool(getattr(getattr(self, "snap_back_input", None), "value", True))

    def use_hex_four_index_basis(self) -> bool:
        return bool(getattr(getattr(self, "hex_four_index_input", None), "value", True))

    def auto_sync_view(self) -> bool:
        return bool(getattr(getattr(self, "auto_sync_input", None), "value", False))

    def show_zone_axis_on_diffraction(self) -> bool:
        return bool(getattr(getattr(self, "show_zone_axis_input", None), "value", False))

    def current_voltage_kv(self) -> float:
        value = getattr(getattr(self, "voltage_input", None), "value", DEFAULT_VOLTAGE_KV)
        return max(float(value or DEFAULT_VOLTAGE_KV), 1e-6)

    def current_thickness_nm(self) -> float:
        value = getattr(getattr(self, "thickness_input", None), "value", DEFAULT_THICKNESS_NM)
        return max(float(value or DEFAULT_THICKNESS_NM), 0.05)

    def current_max_hkl(self) -> int:
        value = getattr(getattr(self, "max_hkl_input", None), "value", DEFAULT_MAX_HKL)
        return int(min(max(int(float(value or DEFAULT_MAX_HKL)), 1), 30))

    def current_spot_intensity_threshold(self) -> float:
        value = getattr(getattr(self, "spot_threshold_input", None), "value", DEFAULT_SPOT_INTENSITY_THRESHOLD)
        try:
            threshold = float(str(value if value is not None else DEFAULT_SPOT_INTENSITY_THRESHOLD).strip())
        except (TypeError, ValueError):
            threshold = DEFAULT_SPOT_INTENSITY_THRESHOLD
        return min(max(threshold, MIN_SPOT_INTENSITY_THRESHOLD), 1.0)

    def current_spot_size_scaling_effect(self) -> float:
        value = getattr(getattr(self, "spot_size_scaling_input", None), "value", DEFAULT_SPOT_SIZE_SCALING)
        try:
            scaling = float(value if value is not None else DEFAULT_SPOT_SIZE_SCALING)
        except (TypeError, ValueError):
            scaling = DEFAULT_SPOT_SIZE_SCALING
        return min(max(scaling, 0.0), 1.0)

    def current_intensity_compression_factor(self) -> float:
        value = getattr(
            getattr(self, "intensity_compression_input", None),
            "value",
            DEFAULT_INTENSITY_COMPRESSION_FACTOR,
        )
        try:
            compression = float(value if value is not None else DEFAULT_INTENSITY_COMPRESSION_FACTOR)
        except (TypeError, ValueError):
            compression = DEFAULT_INTENSITY_COMPRESSION_FACTOR
        return min(max(compression, 10.0), 200.0)

    def uniform_spot_brightness(self) -> bool:
        return bool(getattr(getattr(self, "uniform_spot_brightness_input", None), "value", False))

    def diffraction_display_intensities(self, raw_intensity: np.ndarray) -> np.ndarray:
        intensity = np.maximum(raw_intensity, 0.0)
        compression = self.current_intensity_compression_factor()
        return np.log1p(compression * intensity) / math.log1p(compression)

    def diffraction_spot_opacities(self, intensity: np.ndarray, combo: bool = False) -> np.ndarray:
        base, scale = (0.14, 0.70) if combo else (0.18, 0.82)
        if self.uniform_spot_brightness():
            # Preserve relative intensities for filtering, size scaling, labels, and hover text.
            return np.full_like(intensity, base + scale, dtype=float)
        return base + scale * intensity

    def current_camera_length_mm(self) -> float:
        value = getattr(getattr(self, "camera_length_input", None), "value", f"{DEFAULT_CAMERA_LENGTH_MM:g} mm")
        match = re.match(r"\s*([0-9]*\.?[0-9]+)", str(value or ""))
        if not match:
            return DEFAULT_CAMERA_LENGTH_MM
        return max(float(match.group(1)), 1.0)

    def current_detector_scale_mm_per_nm_inv(self) -> float:
        return detector_scale_mm_per_nm_inv(self.current_camera_length_mm(), self.current_voltage_kv())

    def current_reciprocal_units_per_plot_unit(self) -> float:
        # Plot coordinates are detector-plane millimeters in camera mode.
        # This converts plotted mm back to reciprocal-space nm^-1 for the scale bar.
        return 1.0 / max(self.current_detector_scale_mm_per_nm_inv(), 1e-12)

    def current_diffraction_limit(self) -> float:
        # Camera-mode plot coordinates use detector-plane millimeters.
        # Keep a fixed detector half-width so changing voltage/camera length
        # physically shrinks or expands the diffraction pattern.
        return max(0.05, default_detector_half_width_mm())

    def clear_scientific_caches(self) -> None:
        self.reciprocal_table_cache.clear()
        self.diffraction_spot_cache.clear()
        self.pymatgen_tem_cache.clear()

    @staticmethod
    def trim_cache(cache: dict[Any, Any], max_entries: int) -> None:
        if len(cache) > max_entries:
            cache.clear()

    def model_for(self, name: str) -> CrystalModel:
        definition = self.library.get(name)
        cache_key = (definition.name, crystal_definition_key(definition))
        if cache_key not in self.model_cache:
            self.model_cache[cache_key] = make_model(definition)
        return self.model_cache[cache_key]

    def build_panels(self) -> None:
        if self.panels_container is None:
            return
        self.repair_all_combo_sources()
        self.repair_layout_items()
        self.panels_container.clear()
        self.controllers = []
        self.combo_controllers = []
        panel_map = {state.panel_id: state for state in self.panel_states}
        combo_map = {state.combo_id: state for state in self.combo_panel_states}
        with self.panels_container:
            for item_type, item_id in self.layout_items:
                if item_type == "panel" and item_id in panel_map:
                    controller = PanelController(self, panel_map[item_id])
                    self.controllers.append(controller)
                    controller.build()
                elif item_type == "combo" and item_id in combo_map:
                    controller = ComboPanelController(self, combo_map[item_id])
                    self.combo_controllers.append(controller)
                    controller.build()
        self.update_add_combo_button()
        self.update_panel_close_buttons()

    def append_panel_controller(self, state: PanelState) -> None:
        if self.panels_container is None:
            return
        with self.panels_container:
            controller = PanelController(self, state)
            self.controllers.append(controller)
            controller.build()

    def append_combo_controller(self, state: ComboPanelState) -> None:
        if self.panels_container is None:
            return
        with self.panels_container:
            controller = ComboPanelController(self, state)
            self.combo_controllers.append(controller)
            controller.build()

    def delete_panel_controller(self, panel_id: int) -> None:
        controller = self.controller_by_panel_id(panel_id)
        if controller is None:
            return
        if controller.scale_timer is not None:
            controller.scale_timer.active = False
        if controller.card is not None:
            controller.card.delete()
        self.controllers = [item for item in self.controllers if item.state.panel_id != panel_id]

    def delete_combo_controller(self, combo_id: int) -> None:
        controller = self.combo_controller_by_id(combo_id)
        if controller is None:
            return
        if controller.card is not None:
            controller.card.delete()
        self.combo_controllers = [item for item in self.combo_controllers if item.state.combo_id != combo_id]

    def delete_invalid_combo_controllers(self) -> None:
        valid_ids = {state.combo_id for state in self.combo_panel_states}
        for controller in list(self.combo_controllers):
            if controller.state.combo_id not in valid_ids:
                if controller.card is not None:
                    controller.card.delete()
                self.combo_controllers.remove(controller)

    def update_panel_close_buttons(self) -> None:
        for controller in self.controllers:
            controller.update_close_button()

    def refresh_combo_source_options(self) -> None:
        for controller in self.combo_controllers:
            controller.refresh_source_options()

    def add_panel(self, *, crystal_name: str | None = None, saved_view: dict | None = None) -> None:
        crystal = crystal_name
        if crystal is None:
            crystals = [name for name in self.library.options() if name != CUSTOM_SENTINEL]
            crystal = crystals[(self.next_panel_id - 1) % len(crystals)]
        state = PanelState(
            panel_id=self.next_panel_id,
            crystal_name=crystal,
            applied_zone_text="100",
            plane_text="",
            vector_text="",
            diffraction_color=self.global_diffraction_color or self.default_diffraction_color_for_crystal(crystal),
            display_settings=copy.deepcopy(self.global_display_settings),
        )
        if saved_view is not None:
            self.restore_saved_view(state, saved_view)
        else:
            self.apply_default_saved_view(state)
        self.panel_states.append(state)
        self.layout_items.append(("panel", self.next_panel_id))
        self.next_panel_id += 1
        self.append_panel_controller(state)
        self.update_panel_close_buttons()
        self.update_add_combo_button()
        self.refresh_combo_source_options()
        self.set_status("Added a comparison panel")

    def add_combo_panel(self) -> None:
        if len(self.panel_states) < 2:
            ui.notify("Add at least two panels before creating a combo panel", type="warning")
            return
        state = ComboPanelState(
            combo_id=self.next_combo_id,
            source_panel_ids=[state.panel_id for state in self.panel_states],
            selected_panel_id=self.panel_states[0].panel_id,
        )
        self.combo_panel_states.append(state)
        self.layout_items.append(("combo", self.next_combo_id))
        self.next_combo_id += 1
        self.append_combo_controller(state)
        self.update_add_combo_button()
        self.set_status("Added a combo panel")

    def remove_panel(self, panel_id: int) -> None:
        if len(self.panel_states) <= 1:
            return
        affected_combo_ids = {
            state.combo_id
            for state in self.combo_panel_states
            if panel_id in state.source_panel_ids or state.selected_panel_id == panel_id
        }
        self.panel_states = [state for state in self.panel_states if state.panel_id != panel_id]
        self.layout_items = [item for item in self.layout_items if item != ("panel", panel_id)]
        self.delete_panel_controller(panel_id)
        self.repair_all_combo_sources()
        self.repair_layout_items()
        self.delete_invalid_combo_controllers()
        for controller in self.combo_controllers:
            if controller.state.combo_id in affected_combo_ids:
                controller.refresh()
            else:
                controller.refresh_source_options()
        self.update_panel_close_buttons()
        self.update_add_combo_button()
        self.set_status(f"Removed panel {panel_id}")

    def remove_combo_panel(self, combo_id: int) -> None:
        self.combo_panel_states = [state for state in self.combo_panel_states if state.combo_id != combo_id]
        self.layout_items = [item for item in self.layout_items if item != ("combo", combo_id)]
        self.delete_combo_controller(combo_id)
        self.repair_layout_items()
        self.update_add_combo_button()
        self.set_status(f"Removed combo panel C{combo_id}")

    def repair_layout_items(self) -> None:
        valid_panels = {state.panel_id for state in self.panel_states}
        valid_combos = {state.combo_id for state in self.combo_panel_states}
        seen: set[tuple[str, int]] = set()
        repaired: list[tuple[str, int]] = []
        for item in self.layout_items:
            item_type, item_id = item
            if item in seen:
                continue
            if item_type == "panel" and item_id in valid_panels:
                repaired.append(item)
                seen.add(item)
            elif item_type == "combo" and item_id in valid_combos:
                repaired.append(item)
                seen.add(item)
        for state in self.panel_states:
            item = ("panel", state.panel_id)
            if item not in seen:
                repaired.append(item)
                seen.add(item)
        for state in self.combo_panel_states:
            item = ("combo", state.combo_id)
            if item not in seen:
                repaired.append(item)
                seen.add(item)
        self.layout_items = repaired

    def update_add_combo_button(self) -> None:
        if self.add_combo_button is None:
            return
        if len(self.panel_states) >= 2:
            self.add_combo_button.enable()
        else:
            self.add_combo_button.disable()

    def repair_combo_sources(self, combo_state: ComboPanelState) -> None:
        available = [state.panel_id for state in self.panel_states]
        available_set = set(available)
        combo_state.source_panel_ids = [panel_id for panel_id in combo_state.source_panel_ids if panel_id in available_set]
        for panel_id in available:
            if len(combo_state.source_panel_ids) >= min(2, len(available)):
                break
            if panel_id not in combo_state.source_panel_ids:
                combo_state.source_panel_ids.append(panel_id)
        if combo_state.selected_panel_id not in available_set:
            combo_state.selected_panel_id = available[0] if available else None

    def repair_all_combo_sources(self) -> None:
        if len(self.panel_states) < 2:
            self.combo_panel_states = []
            return
        for state in self.combo_panel_states:
            self.repair_combo_sources(state)

    def panel_state_by_id(self, panel_id: int | None) -> PanelState | None:
        if panel_id is None:
            return self.panel_states[0] if self.panel_states else None
        return next((state for state in self.panel_states if state.panel_id == panel_id), None)

    def refresh_panel_crystal_select_options(self) -> None:
        options = self.library.options()
        for controller in self.controllers:
            if controller.crystal_select is None:
                continue
            controller.crystal_select.options = options
            if controller.state.crystal_name in options:
                controller.crystal_select.value = controller.state.crystal_name
            controller.crystal_select.update()

    def sync_panel_inputs_from_state(self, controller: PanelController) -> None:
        state = controller.state
        if controller.crystal_select is not None:
            controller.crystal_select.value = state.crystal_name
            controller.crystal_select.update()
        if controller.zone_input is not None:
            controller.zone_input.value = state.zone_text
            controller.zone_input.update()
        if controller.plane_input is not None:
            controller.plane_input.value = state.plane_text
            controller.plane_input.update()
        if controller.vector_input is not None:
            controller.vector_input.value = state.vector_text
            controller.vector_input.update()
        if controller.rotation_input is not None:
            controller.rotation_input.value = state.rotation_text
            controller.rotation_input.update()

    def redraw_panel_controllers(self, panel_ids: set[int]) -> None:
        for panel_id in sorted(panel_ids):
            controller = self.controller_by_panel_id(panel_id)
            state = self.panel_state_by_id(panel_id)
            if controller is None or state is None:
                continue
            self.sync_panel_inputs_from_state(controller)
            model = self.model_for(state.crystal_name)
            controller.redraw_scene(model)
            controller.redraw_diffraction(model)

    def redraw_panel_diffractions(self, panel_ids: set[int]) -> None:
        for panel_id in sorted(panel_ids):
            controller = self.controller_by_panel_id(panel_id)
            state = self.panel_state_by_id(panel_id)
            if controller is None or state is None:
                continue
            controller.redraw_diffraction(self.model_for(state.crystal_name))

    def refresh_combo_panels_for_sources(self, panel_ids: set[int]) -> None:
        self.repair_all_combo_sources()
        for controller in self.combo_controllers:
            if set(controller.state.source_panel_ids) & panel_ids:
                controller.refresh()
            else:
                controller.refresh_source_options()

    def refresh_library(
        self,
        selected_name: str,
        target_panel_id: int | None = None,
        force_default_color: bool = False,
        affected_crystal_names: set[str] | tuple[str, ...] | list[str] | None = None,
    ) -> None:
        self.model_cache.clear()
        self.clear_scientific_caches()
        affected_names = (
            {str(name) for name in affected_crystal_names if str(name).strip()}
            if affected_crystal_names is not None
            else {selected_name}
        )
        affected_panel_ids: set[int] = set()
        for state in self.panel_states:
            if state.crystal_name == CUSTOM_SENTINEL or state.crystal_name not in self.library.definitions:
                self.set_panel_crystal(state, selected_name, force_default_color=True,
                                       preserve_saved_view=state.crystal_name in affected_names)
                affected_panel_ids.add(state.panel_id)
        if target_panel_id is not None:
            target = self.panel_state_by_id(target_panel_id)
            if target is not None:
                self.set_panel_crystal(target, selected_name, force_default_color=force_default_color,
                                       preserve_saved_view=target.crystal_name in affected_names)
                affected_panel_ids.add(target.panel_id)
        for state in self.panel_states:
            if state.crystal_name in affected_names:
                if force_default_color:
                    self.set_panel_crystal(state, state.crystal_name, force_default_color=True)
                affected_panel_ids.add(state.panel_id)
        self.refresh_panel_crystal_select_options()
        self.redraw_panel_controllers(affected_panel_ids)
        if affected_panel_ids:
            self.refresh_combo_panels_for_sources(affected_panel_ids)

    def refresh_diffractions(self, clear_cache: bool = False) -> None:
        if clear_cache:
            self.model_cache.clear()
            self.clear_scientific_caches()
        for controller in self.controllers:
            controller.redraw_diffraction()
        self.refresh_combo_panels()

    def refresh_combo_panels(self) -> None:
        self.repair_all_combo_sources()
        for controller in self.combo_controllers:
            controller.refresh()

    def controller_by_panel_id(self, panel_id: int) -> PanelController | None:
        return next((controller for controller in self.controllers if controller.state.panel_id == panel_id), None)

    def combo_controller_by_id(self, combo_id: int) -> ComboPanelController | None:
        return next((controller for controller in self.combo_controllers if controller.state.combo_id == combo_id), None)

    def diffraction_spot_cache_key(self, state: PanelState, model: CrystalModel) -> tuple[Any, ...]:
        method = self.current_simulation_method()
        view = normalize_vector(state.view_vector)
        if view is None:
            view = np.array(state.view_vector, dtype=float)
        return (
            method,
            crystal_model_key(model),
            self.current_max_hkl(),
            round(self.current_voltage_kv(), 5),
            round(self.current_thickness_nm(), 5),
            round(self.current_camera_length_mm(), 5),
            self.current_spot_intensity_threshold(),
            round(self.current_intensity_compression_factor(), 5),
            tuple(float(value) for value in np.round(view, 6)),
            round(float(state.roll), 5),
        )

    def diffraction_spots_for_state(self, state: PanelState, model: CrystalModel | None = None) -> np.ndarray:
        model = model or self.model_for(state.crystal_name)
        key = self.diffraction_spot_cache_key(state, model)
        cached = self.diffraction_spot_cache.get(key)
        if cached is not None:
            return cached
        if self.current_simulation_method() == SIMULATION_METHOD_PYMATGEN:
            spots = self.compute_pymatgen_tem_spots(model, state.view_vector, state.roll)
        else:
            spots = self.compute_ewald_spots(model, state.view_vector, state.roll)
        self.diffraction_spot_cache[key] = spots
        self.trim_cache(self.diffraction_spot_cache, 512)
        return spots

    def bound_motion_panel_ids(self, source_panel_id: int) -> set[int]:
        connected = {source_panel_id}
        pending = [source_panel_id]
        while pending:
            panel_id = pending.pop()
            for combo_state in self.combo_panel_states:
                if not combo_state.bind_motion or panel_id not in combo_state.source_panel_ids:
                    continue
                for candidate_id in combo_state.source_panel_ids:
                    if candidate_id in connected or self.panel_state_by_id(candidate_id) is None:
                        continue
                    connected.add(candidate_id)
                    pending.append(candidate_id)
        return connected

    def propagate_bound_motion(
        self,
        source_panel_id: int,
        old_view: np.ndarray,
        old_roll: float,
        new_view: np.ndarray,
        new_roll: float,
    ) -> None:
        bound_ids = self.bound_motion_panel_ids(source_panel_id)
        bound_ids.discard(source_panel_id)
        if not bound_ids:
            self.refresh_combo_panels_for_sources({source_panel_id})
            return

        # Propagate the motion in the driver's view frame, not in the driver's
        # crystal coordinates. This preserves orientation relationships such as
        # panel 1 [100] parallel to panel 2 [110]: an in-plane spin in panel 1
        # becomes an in-plane spin around panel 2's current beam direction.
        delta = local_orientation_delta(old_view, old_roll, new_view, new_roll)
        if np.allclose(delta, np.eye(3), atol=1e-6):
            self.refresh_combo_panels_for_sources({source_panel_id})
            return

        affected_panel_ids = {source_panel_id, *bound_ids}
        for panel_id in sorted(bound_ids):
            state = self.panel_state_by_id(panel_id)
            if state is None:
                continue
            state.view_vector, state.roll = apply_local_orientation_delta(state.view_vector, state.roll, delta)
            controller = self.controller_by_panel_id(panel_id)
            if controller is not None:
                model = self.model_for(state.crystal_name)
                controller.redraw_scene(model)
                controller.redraw_diffraction(model)
        self.refresh_combo_panels_for_sources(affected_panel_ids)

    def pymatgen_tem_reflections(self, model: CrystalModel, zone_axis: tuple[int, int, int]) -> np.ndarray | None:
        max_order = self.current_max_hkl()
        camera_length = max(int(round(self.current_camera_length_mm() / 10.0)), 1)
        cache_key = (
            crystal_model_key(model),
            zone_axis,
            max_order,
            round(self.current_voltage_kv(), 5),
            camera_length,
        )
        cached = self.pymatgen_tem_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            from pymatgen.analysis.diffraction.tem import TEMCalculator

            structure = pymatgen_structure_from_model(model)
            calculator_class = occupancy_aware_tem_calculator_class(TEMCalculator)
            calculator = calculator_class(
                symprec=None,
                voltage=self.current_voltage_kv(),
                beam_direction=zone_axis,
                camera_length=camera_length,
            )
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                dots = calculator.tem_dots(structure, TEMCalculator.generate_points(-max_order, max_order))
        except Exception as exc:
            self.set_status(f"Pymatgen TEM calculation failed: {exc}")
            return None

        rows = [[int(dot.hkl[0]), int(dot.hkl[1]), int(dot.hkl[2]), max(float(dot.intensity), 0.0)] for dot in dots]
        reflections = np.array(rows, dtype=float) if rows else np.empty((0, 4), dtype=float)
        self.pymatgen_tem_cache[cache_key] = reflections
        self.trim_cache(self.pymatgen_tem_cache, 128)
        return reflections

    def compute_pymatgen_tem_spots(self, model: CrystalModel, view_vector: np.ndarray, roll: float) -> np.ndarray:
        zone_axis = integer_zone_axis_from_view(model, view_vector)
        reflections = self.pymatgen_tem_reflections(model, zone_axis)
        if reflections is None:
            return np.empty((0, 6), dtype=float)
        if not len(reflections):
            return np.array([[0.0, 0.0, 1.0, 0, 0, 0]], dtype=float)

        try:
            hkl = reflections[:, :3].astype(int)
            raw_intensity = reflections[:, 3].astype(float)
            threshold = self.current_spot_intensity_threshold()
            normal = normalize_vector(view_vector)
            if normal is None:
                normal = normalize_vector(direction_to_cart(zone_axis, model))
            if normal is None:
                normal = np.array([1.0, 0.0, 0.0])
            u_axis, v_axis = projection_basis(normal, roll)
            detector_scale = self.current_detector_scale_mm_per_nm_inv()
            display_intensity = self.diffraction_display_intensities(raw_intensity)
            nonzero = ~np.all(hkl == 0, axis=1)
            visible = (display_intensity > threshold) & nonzero
            g_vectors = hkl[visible].astype(float) @ model.reciprocal
            rows = [[0.0, 0.0, 1.0, 0, 0, 0]]
            if len(g_vectors):
                x_coord = detector_scale * (g_vectors @ u_axis)
                y_coord = detector_scale * (g_vectors @ v_axis)
                rows.extend(
                    np.column_stack(
                        (
                            x_coord,
                            y_coord,
                            display_intensity[visible],
                            hkl[visible, 0],
                            hkl[visible, 1],
                            hkl[visible, 2],
                        )
                    ).tolist()
                )
            return np.array(rows, dtype=float)
        except Exception as exc:
            self.set_status(f"Pymatgen TEM projection failed: {exc}")
            return np.empty((0, 6), dtype=float)

    def compute_ewald_spots(self, model: CrystalModel, view_vector: np.ndarray, roll: float) -> np.ndarray:
        hkl, reciprocal_points, structure_intensity = self.reciprocal_points_for_model(model)
        if len(hkl) == 0:
            return np.empty((0, 6), dtype=float)
        normal = normalize_vector(view_vector)
        if normal is None:
            normal = np.array([1.0, 0.0, 0.0])
        u_axis, v_axis = projection_basis(normal, roll)
        x_screen = reciprocal_points @ u_axis
        y_screen = reciprocal_points @ v_axis
        depth = reciprocal_points @ normal
        detector_scale = self.current_detector_scale_mm_per_nm_inv()
        x_plot = detector_scale * x_screen
        y_plot = detector_scale * y_screen

        wavelength_nm = electron_wavelength_nm(self.current_voltage_kv())
        ewald_radius = 1.0 / wavelength_nm
        g_perp2 = x_screen * x_screen + y_screen * y_screen
        valid_curvature = g_perp2 < ewald_radius * ewald_radius
        curvature = np.full_like(g_perp2, np.inf, dtype=float)
        curvature[valid_curvature] = ewald_radius - np.sqrt(ewald_radius * ewald_radius - g_perp2[valid_curvature])
        excitation_error = depth + curvature

        thickness = self.current_thickness_nm()
        thickness_shape = np.sinc(excitation_error * thickness) ** 2
        # high_angle_envelope = np.exp(-0.0008 * g_perp2)
        # raw_intensity = structure_intensity * thickness_shape * high_angle_envelope
        raw_intensity = structure_intensity * thickness_shape
        zero_beam = np.all(hkl == 0, axis=1)
        raw_intensity[zero_beam] = max(float(raw_intensity.max(initial=1.0)), 1.0)
        if raw_intensity.max(initial=0.0) > 0:
            raw_intensity = raw_intensity / raw_intensity.max()
        display_intensity = self.diffraction_display_intensities(raw_intensity)
        visible = (display_intensity > self.current_spot_intensity_threshold()) & valid_curvature
        return np.column_stack(
            (
                x_plot[visible],
                y_plot[visible],
                display_intensity[visible],
                hkl[visible, 0],
                hkl[visible, 1],
                hkl[visible, 2],
            )
        )

    def reciprocal_points_for_model(self, model: CrystalModel) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        max_order = self.current_max_hkl()
        cache_key = (crystal_model_key(model), max_order)
        cached = self.reciprocal_table_cache.get(cache_key)
        if cached is not None:
            return cached
        hkl_values = []
        reciprocal_points = []
        intensities = []
        for h, k, l in product(range(-max_order, max_order + 1), repeat=3):
            if h * h + k * k + l * l > max_order * max_order:
                continue
            hkl = np.array([h, k, l], dtype=float)
            g_vector = hkl @ model.reciprocal
            g_norm = float(np.linalg.norm(g_vector))
            factor = structure_factor(model.definition, hkl, g_norm, model.expanded_sites)
            intensity = float(abs(factor) ** 2)
            if intensity < 1e-10 and not (h == 0 and k == 0 and l == 0):
                continue
            hkl_values.append([h, k, l])
            reciprocal_points.append(g_vector)
            intensities.append(intensity)
        table = (
            np.array(hkl_values, dtype=int),
            np.array(reciprocal_points, dtype=float),
            np.array(intensities, dtype=float),
        )
        self.reciprocal_table_cache[cache_key] = table
        self.trim_cache(self.reciprocal_table_cache, 64)
        return table


@ui.page("/")
def index() -> None:
    SimulatorApp().build()


def main() -> None:
    if is_desktop_mode():
        use_native_window = os.environ.get("CRYSDIS_NATIVE", "auto").lower() not in {"0", "false", "no"}
        native_available = importlib.util.find_spec("webview") is not None
        ui.run(
            title="CrysDiS",
            host="127.0.0.1",
            port=find_open_port(),
            reload=False,
            show=not (use_native_window and native_available),
            native=use_native_window and native_available,
        )
        return

    port_env = os.environ.get("PORT")
    if is_hosted_mode():
        ui.run(
            title="CrysDiS",
            host="0.0.0.0",
            port=int(port_env or "8080"),
            reload=False,
            show=False,
        )
        return

    port = int(os.environ.get("NICEGUI_PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")
    ui.run(title="CrysDiS", host=host, port=port, reload=False, show=False)


if __name__ in {"__main__", "__mp_main__"}:
    main()
