import json
import math
import re
import sys
import tkinter as tk
import warnings
from dataclasses import asdict, dataclass, field
from itertools import product
from pathlib import Path
from typing import Any
from tkinter import filedialog, font as tkfont, messagebox, ttk

import matplotlib
import numpy as np

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.colors import LinearSegmentedColormap, to_rgb
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

try:
    from PIL import Image, ImageDraw, ImageFont, ImageTk

    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

try:
    from platformdirs import user_data_dir
except Exception:
    user_data_dir = None


SOURCE_DIR = Path(__file__).resolve().parent


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    if is_frozen_app():
        return Path(sys.executable).resolve().parent
    return SOURCE_DIR


def resource_path(*parts: str) -> Path:
    candidates: list[Path] = []
    if is_frozen_app():
        candidates.append(app_dir().joinpath(*parts))
        candidates.append(Path(getattr(sys, "_MEIPASS", app_dir())).joinpath(*parts))
    else:
        candidates.append(SOURCE_DIR.joinpath(*parts))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def bundled_library_path() -> Path:
    candidates: list[Path] = []
    if is_frozen_app():
        candidates.append(app_dir() / "custom_crystals_local.json")
        candidates.append(Path(getattr(sys, "_MEIPASS", app_dir())) / "custom_crystals_local.json")
    candidates.append(SOURCE_DIR / "packaging" / "custom_crystals_local.json")
    candidates.append(SOURCE_DIR / "custom_crystals_local.json")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def app_data_dir() -> Path:
    if user_data_dir is not None:
        return Path(user_data_dir("CrysDiS_tkinter", appauthor=False))
    return Path.home() / ".crysdis_tkinter"


APP_DIR = app_dir()
APP_ICON_PATH = resource_path("assets", "CrysDiS_tkinter.png")
BUNDLED_LIBRARY_PATH = bundled_library_path()
USER_DATA_DIR = app_data_dir()
USER_LIBRARY_PATH = USER_DATA_DIR / "custom_crystals.json"
LOCAL_LIBRARY_PATH = USER_LIBRARY_PATH
GLOBAL_LIBRARY_PATH = USER_LIBRARY_PATH
CUSTOM_SENTINEL = "Create / edit customized crystal..."

THEMES = {
    "Dark": {
        "window_bg": "#000000",
        "axis_bg": "#000000",
        "diff_bg": "#000000",
        "title": "#E8EDF2",
        "label": "#E8EDF2",
        "status": "#B8C0CC",
        "atom_edge": "#EAFBFF",
        "origin": "#FFFFFF",
    },
    "Light": {
        "window_bg": "#d9d9d9",
        "axis_bg": "#d9d9d9",
        "diff_bg": "#d9d9d9",
        "title": "#333333",
        "label": "#222222",
        "status": "#333333",
        "atom_edge": "#252525",
        "origin": "#111111",
    },
}

SIMULATION_METHOD_EWALD = "Ewald Sphere Kinematic"
SIMULATION_METHOD_PYMATGEN = "Pymatgen TEMCalculator"
try:
    import pymatgen  # type: ignore  # noqa: F401

    PYMATGEN_AVAILABLE = True
except Exception:
    PYMATGEN_AVAILABLE = False
SIMULATION_METHODS = (
    SIMULATION_METHOD_EWALD,
    *((SIMULATION_METHOD_PYMATGEN,) if PYMATGEN_AVAILABLE else ()),
)
DEFAULT_VOLTAGE_KV = 500.0
DEFAULT_THICKNESS_NM = 10.0
DEFAULT_MAX_HKL = 7
DEFAULT_ZONE_AXIS_SEARCH_MAX = 18
DEFAULT_CAMERA_LENGTH_MM = 200.0
DIFFRACTION_BASE_LIMIT_NM_INV = 16.0
DEFAULT_SPOT_INTENSITY_THRESHOLD = 0.001
MIN_SPOT_INTENSITY_THRESHOLD = 1e-4
DEFAULT_SPOT_SIZE_SCALING = 0.35
DEFAULT_INTENSITY_COMPRESSION_FACTOR = 80.0
BASE_DIFFRACTION_MARKER_SIZE = 5.0
EXTRA_DIFFRACTION_MARKER_SIZE = 28.0
ZONE_AXIS_EXACT_TOL_DEGREES = 0.5
CAMERA_LENGTH_OPTIONS = ("80 mm", "100 mm", "150 mm", "200 mm", "300 mm", "500 mm", "800 mm", "1000 mm", "1500 mm")
DEFAULT_REAL_MAGNIFICATION = 1.0
REAL_MAGNIFICATION_OPTIONS = ("0.5x", "0.75x", "1x", "1.5x", "2x", "3x", "4x", "6x", "8x")
MAX_ORDINARY_PANELS = 16
MAX_COMBO_PANELS = 8
FIGURE_DPI = 100
WINDOW_WIDTH_RESERVE_PX = 24
WINDOW_HEIGHT_RESERVE_PX = 110
MAIN_UI_CHROME_PX = 62
PANEL_ROW_CHROME_PX = 78
SINGLE_PANEL_CHROME_PX = 86
MIN_REGULAR_CANVAS_HEIGHT_PX = 210
MAX_REGULAR_CANVAS_HEIGHT_PX = 420
MIN_SINGLE_CANVAS_HEIGHT_PX = 340
MAX_SINGLE_CANVAS_HEIGHT_PX = 850
MIN_REGULAR_CANVAS_WIDTH_PX = 260
MIN_SINGLE_CANVAS_WIDTH_PX = 360
MIN_COMBO_CANVAS_WIDTH_PX = 270
MIN_COMBO_SOURCE_WIDTH_PX = 160
MIN_COMBO_LEGEND_WIDTH_PX = 118
SCROLLBAR_VISIBILITY_SLACK_PX = 18
DEFAULT_LATTICE_NM = {
    "FCC": 0.3524,
    "BCC": 0.2855,
    "HCP": 0.32094,
}
IDEAL_HCP_CA = math.sqrt(8.0 / 3.0)
SYMMETRY_SITE_TOL = 5e-3

CRYSTAL_STYLES = {
    "FCC": {
        "atom": "#0ABAB5",
        "edge": "#B9F4F0",
        "light_edge": "#087E7B",
        "diff": "#31F7F1",
        "title": "Face-centered cubic",
    },
    "BCC": {
        "atom": "#F2A93B",
        "edge": "#FFE0A5",
        "light_edge": "#9A6414",
        "diff": "#FFC857",
        "title": "Body-centered cubic",
    },
    "HCP": {
        "atom": "#A26CFF",
        "edge": "#DAC7FF",
        "light_edge": "#6740B2",
        "diff": "#B985FF",
        "title": "Hexagonal close-packed",
    },
}

DEFAULT_DIFFRACTION_COLORS_BY_THEME = {
    "Dark": {
        "FCC": "bright cyan",
        "BCC": "amber",
        "HCP": "soft violet",
    },
    "Light": {
        "FCC": "dark cyan",
        "BCC": "dark orange",
        "HCP": "dark purple",
    },
}

ELEMENTS = [
    "Al",
    "C",
    "Co",
    "Cr",
    "Cu",
    "Fe",
    "Mg",
    "Mn",
    "Mo",
    "N",
    "Ni",
    "O",
    "Si",
    "Ti",
    "V",
    "W",
    "Zn",
]

LATTICE_SYSTEMS = [
    "cubic",
    "tetragonal",
    "orthorhombic",
    "hexagonal",
    "monoclinic",
    "triclinic",
]

ATOMIC_NUMBERS = {
    "H": 1,
    "C": 6,
    "N": 7,
    "O": 8,
    "Mg": 12,
    "Al": 13,
    "Si": 14,
    "Ti": 22,
    "V": 23,
    "Cr": 24,
    "Mn": 25,
    "Fe": 26,
    "Co": 27,
    "Ni": 28,
    "Cu": 29,
    "Zn": 30,
    "Mo": 42,
    "W": 74,
}

ELEMENT_COLORS = {
    "Al": "#AEB6BF",
    "C": "#30323D",
    "Co": "#4D79D8",
    "Cr": "#4ECDC4",
    "Cu": "#D9822B",
    "Fe": CRYSTAL_STYLES["BCC"]["atom"],
    "Mg": CRYSTAL_STYLES["HCP"]["atom"],
    "Mn": "#C77DFF",
    "Mo": "#7D8597",
    "N": "#5C7CFA",
    "Ni": CRYSTAL_STYLES["FCC"]["atom"],
    "O": "#EF476F",
    "Si": "#F77F00",
    "Ti": "#8E9AAF",
    "V": "#63A375",
    "W": "#5E6472",
    "Zn": "#8AB6D6",
}

NAMED_COLORS = {
    "bright cyan": "#31F7F1",
    "amber": "#FFC857",
    "soft violet": "#B985FF",
    "blue": "#3B82F6",
    "sky": "#38BDF8",
    "cyan": "#06B6D4",
    "teal": "#14B8A6",
    "green": "#22C55E",
    "lime": "#84CC16",
    "yellow": "#FACC15",
    "gold": "#F59E0B",
    "orange": "#F97316",
    "red": "#EF4444",
    "rose": "#F43F5E",
    "pink": "#EC4899",
    "purple": "#A855F7",
    "violet": "#8B5CF6",
    "indigo": "#6366F1",
    "gray": "#94A3B8",
    "light blue": "#93C5FD",
    "light cyan": "#67E8F9",
    "light teal": "#5EEAD4",
    "light green": "#86EFAC",
    "light yellow": "#FEF08A",
    "light orange": "#FDBA74",
    "light pink": "#F9A8D4",
    "light purple": "#D8B4FE",
    "light gray": "#CBD5E1",
    "dark blue": "#1D4ED8",
    "dark cyan": "#0E7490",
    "dark teal": "#0F766E",
    "dark green": "#15803D",
    "dark yellow": "#A16207",
    "dark orange": "#C2410C",
    "dark red": "#B91C1C",
    "dark pink": "#BE185D",
    "dark purple": "#7E22CE",
    "dark gray": "#475569",
    "black": "#111827",
    "white": "#F8FAFC",
}
DIFFRACTION_COLOR_OPTIONS = tuple(NAMED_COLORS)

CROMER_MANN = {
    "Al": ([6.4202, 1.9002, 1.5936, 1.9646], [3.0387, 0.7426, 31.5472, 85.0886], 1.1151),
    "Co": ([12.2841, 7.3409, 4.0034, 2.3488], [4.2791, 0.2784, 13.5359, 71.1692], 1.0118),
    "Cr": ([10.6406, 7.3537, 3.3240, 1.4922], [6.1038, 0.3920, 20.2626, 98.7399], 1.1832),
    "Cu": ([13.3380, 7.1676, 5.6158, 1.6735], [3.5828, 0.2470, 11.3966, 64.8126], 1.1910),
    "Fe": ([11.7695, 7.3573, 3.5222, 2.3045], [4.7611, 0.3072, 15.3535, 76.8805], 1.0369),
    "Mg": ([5.4204, 2.1735, 1.2269, 2.3073], [2.8275, 79.2611, 0.3808, 7.1937], 0.8584),
    "Mn": ([11.2819, 7.3573, 3.0193, 2.2441], [5.3409, 0.3432, 17.8674, 83.7543], 1.0896),
    "Ni": ([12.8376, 7.2920, 4.4438, 2.3800], [3.8785, 0.2565, 12.1763, 66.3421], 1.0341),
}

PLANE_COLORS = ["#FF6B6B", "#FFD166", "#06D6A0", "#4DABF7", "#C77DFF", "#F783AC"]
VECTOR_COLORS = ["#E63946", "#F4A261", "#2A9D8F", "#577590", "#B5179E", "#80ED99"]


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
    sites: list[AtomicSite] | None = None

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
            sites=sites,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParsedIndex:
    values: tuple[int, ...]
    label: str
    vector: np.ndarray
    is_reciprocal: bool = False


@dataclass
class CrystalModel:
    name: str
    lattice: np.ndarray
    basis: np.ndarray
    display_lattice: np.ndarray
    crystal_origin: np.ndarray
    display_atoms: np.ndarray
    diffraction_atoms: np.ndarray
    cell_edges: list[tuple[np.ndarray, np.ndarray]]
    limit: float
    definition: CrystalDefinition
    expanded_sites: list[AtomicSite]
    reciprocal: np.ndarray
    atom_colors: list[str]
    atom_occupancies: list[float]
    scale_nm: float = 1.0


@dataclass
class RotationCommand:
    axis: np.ndarray | None
    axis_label: str
    angle_degrees: float


@dataclass
class PanelState:
    panel_id: int
    crystal: str
    zone_text: str
    plane_text: str
    vector_text: str
    rotation_text: str = ""
    diffraction_color: str = ""
    diffraction_color_user_set: bool = False
    real_magnification: float = DEFAULT_REAL_MAGNIFICATION
    elev: float = 0.0
    azim: float = 0.0
    roll: float = 0.0
    applied_zone_text: str = ""


@dataclass
class ComboPanelState:
    combo_id: int
    source_panel_ids: list[int] = field(default_factory=list)
    selected_panel_id: int | None = None
    bind_motion: bool = False


ColumnState = PanelState


@dataclass
class LayoutMetrics:
    ordinary_canvas_width: int = 500
    ordinary_canvas_height: int = 375
    combo_canvas_width: int = 500
    combo_canvas_height: int = 375
    combo_source_width: int = 180
    combo_legend_width: int = 135


def figure_size_from_pixels(width: int, height: int) -> tuple[float, float]:
    return (max(int(width), 1) / FIGURE_DPI, max(int(height), 1) / FIGURE_DPI)


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


def default_crystals() -> dict[str, CrystalDefinition]:
    fcc_a = DEFAULT_LATTICE_NM["FCC"]
    bcc_a = DEFAULT_LATTICE_NM["BCC"]
    hcp_a = DEFAULT_LATTICE_NM["HCP"]
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
                AtomicSite("Ni", 0.0, 0.0, 0.0, 1.0, "4a", CRYSTAL_STYLES["FCC"]["atom"]),
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
                AtomicSite("Fe", 0.0, 0.0, 0.0, 1.0, "2a", CRYSTAL_STYLES["BCC"]["atom"]),
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
            space_group="P6_3/mmc",
            sites=[
                AtomicSite("Mg", 1.0 / 3.0, 2.0 / 3.0, 0.25, 1.0, "2c", CRYSTAL_STYLES["HCP"]["atom"]),
            ],
        ),
    }


DEFAULT_CRYSTALS = default_crystals()
DEFAULT_NAMES = set(DEFAULT_CRYSTALS)


def space_group_symbol(value: str | None) -> str:
    text = str(value or "P1").strip()
    if ":" in text:
        text = text.split(":", 1)[1].strip()
    compact = text.replace(" ", "") or "P1"
    aliases = {
        "P63/mmc": "P6_3/mmc",
        "P63/m": "P6_3/m",
        "P63mc": "P6_3mc",
        "P63cm": "P6_3cm",
    }
    return aliases.get(compact, compact)


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


def expanded_sites(definition: CrystalDefinition) -> list[AtomicSite]:
    sites = definition.sites or []
    symbol = space_group_symbol(definition.space_group)
    if symbol in {"", "P1", "1"}:
        return [AtomicSite(**asdict(site)) for site in sites]

    try:
        from pymatgen.core import Structure as _PymatgenStructure
        from pymatgen.symmetry.groups import SpaceGroup

        _ = _PymatgenStructure
        space_group = SpaceGroup.from_int_number(int(symbol)) if symbol.isdigit() else SpaceGroup(symbol)
        operations = space_group.symmetry_ops
    except Exception:
        return [AtomicSite(**asdict(site)) for site in sites]

    expanded: list[AtomicSite] = []
    seen: set[tuple[str, int, int, int]] = set()
    for site in sites:
        base_frac = snap_fractional(site.fractional)
        for operation in operations:
            frac = snap_fractional(np.mod(operation.operate(base_frac), 1.0))
            key = (
                site.element.strip().capitalize(),
                int(round(float(frac[0]) / SYMMETRY_SITE_TOL)),
                int(round(float(frac[1]) / SYMMETRY_SITE_TOL)),
                int(round(float(frac[2]) / SYMMETRY_SITE_TOL)),
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


def wrap_fractional(frac: np.ndarray, tolerance: float = 1e-8) -> np.ndarray:
    wrapped = np.mod(np.asarray(frac, dtype=float), 1.0)
    wrapped[np.isclose(wrapped, 1.0, atol=tolerance)] = 0.0
    wrapped[np.isclose(wrapped, 0.0, atol=tolerance)] = 0.0
    return wrapped


def nearly_equal(a: float, b: float, tolerance: float = 1e-4) -> bool:
    return math.isclose(float(a), float(b), rel_tol=tolerance, abs_tol=tolerance)


def infer_lattice_system(definition: CrystalDefinition) -> str:
    symbol = space_group_symbol(definition.space_group)
    if symbol not in {"", "P1", "1"}:
        try:
            from pymatgen.symmetry.groups import SpaceGroup

            group = SpaceGroup.from_int_number(int(symbol)) if symbol.isdigit() else SpaceGroup(symbol)
            crystal_system = str(group.crystal_system).lower()
            if crystal_system in LATTICE_SYSTEMS:
                return crystal_system
        except Exception:
            pass

    a, b, c = definition.a, definition.b, definition.c
    alpha, beta, gamma = definition.alpha, definition.beta, definition.gamma
    right_angles = nearly_equal(alpha, 90.0) and nearly_equal(beta, 90.0) and nearly_equal(gamma, 90.0)
    if right_angles and nearly_equal(a, b) and nearly_equal(b, c):
        return "cubic"
    if right_angles and nearly_equal(a, b):
        return "tetragonal"
    if right_angles:
        return "orthorhombic"
    if nearly_equal(alpha, 90.0) and nearly_equal(beta, 90.0) and nearly_equal(gamma, 120.0) and nearly_equal(a, b):
        return "hexagonal"
    if nearly_equal(alpha, 90.0) and nearly_equal(gamma, 90.0):
        return "monoclinic"
    return definition.lattice_system.lower() if definition.lattice_system.lower() in LATTICE_SYSTEMS else "triclinic"


def symmetry_operations_for_space_group(space_group: str) -> list[Any]:
    symbol = space_group_symbol(space_group)
    if symbol in {"", "P1", "1"}:
        return []
    try:
        from pymatgen.symmetry.groups import SpaceGroup

        group = SpaceGroup.from_int_number(int(symbol)) if symbol.isdigit() else SpaceGroup(symbol)
        return list(group.symmetry_ops)
    except Exception:
        return []


def fractional_points_match(a: np.ndarray, b: np.ndarray, tolerance: float = SYMMETRY_SITE_TOL) -> bool:
    delta = np.abs(wrap_fractional(np.asarray(a, dtype=float) - np.asarray(b, dtype=float)))
    delta = np.minimum(delta, 1.0 - delta)
    return bool(np.all(delta <= tolerance))


def equivalent_under_symmetry(site: AtomicSite, representative: AtomicSite, operations: list[Any]) -> bool:
    if site.element.strip().capitalize() != representative.element.strip().capitalize():
        return False
    if not math.isclose(float(site.occupancy), float(representative.occupancy), abs_tol=1e-5):
        return False
    target = snap_fractional(wrap_fractional(site.fractional))
    base = snap_fractional(wrap_fractional(representative.fractional))
    for operation in operations:
        frac = snap_fractional(wrap_fractional(operation.operate(base)))
        if fractional_points_match(frac, target):
            return True
    return False


def representative_sites_by_symmetry(definition: CrystalDefinition) -> list[AtomicSite]:
    sites = definition.sites or []
    operations = symmetry_operations_for_space_group(definition.space_group)
    if not operations:
        return [AtomicSite(**asdict(site)) for site in sites]
    representatives: list[AtomicSite] = []
    for site in sites:
        if any(equivalent_under_symmetry(site, representative, operations) for representative in representatives):
            continue
        representatives.append(AtomicSite(**asdict(site)))
    return representatives


def normalized_crystal_definition(definition: CrystalDefinition) -> CrystalDefinition:
    normalized = CrystalDefinition.from_dict(definition.to_dict())
    normalized.lattice_system = infer_lattice_system(normalized)
    normalized.sites = representative_sites_by_symmetry(normalized)
    return normalized


def color_for_element(element: str) -> str:
    symbol = element.strip().capitalize()
    if symbol in ELEMENT_COLORS:
        return ELEMENT_COLORS[symbol]
    palette = ["#2EC4B6", "#E71D36", "#FF9F1C", "#4D96FF", "#9D4EDD", "#6A994E"]
    return palette[sum(ord(char) for char in symbol) % len(palette)]


def color_for_site(site: AtomicSite) -> str:
    color = str(site.color or "").strip()
    if re.match(r"^#[0-9a-fA-F]{6}$", color):
        return color
    named = color.lower()
    if named in NAMED_COLORS:
        return NAMED_COLORS[named]
    return color_for_element(site.element)


def hex_color_from_rgb(rgb: tuple[float, float, float]) -> str:
    values = [min(max(int(round(component * 255.0)), 0), 255) for component in rgb]
    return "#{:02X}{:02X}{:02X}".format(*values)


def mix_hex_color(color: str, target: str, amount: float) -> str:
    try:
        source_rgb = np.array(to_rgb(color), dtype=float)
        target_rgb = np.array(to_rgb(target), dtype=float)
    except ValueError:
        return color
    amount = min(max(float(amount), 0.0), 1.0)
    mixed = source_rgb * (1.0 - amount) + target_rgb * amount
    return hex_color_from_rgb((float(mixed[0]), float(mixed[1]), float(mixed[2])))


def theme_adjusted_custom_diffraction_color(color: str, theme_name: str) -> str:
    if theme_name == "Light":
        return mix_hex_color(color, "#000000", 0.42)
    return mix_hex_color(color, "#FFFFFF", 0.32)


def dominant_color(definition: CrystalDefinition) -> str:
    sites = definition.sites or []
    if sites:
        return color_for_site(sites[0])
    return "#35D0BA"


def atomic_form_factor(element: str, g_nm_inv: float) -> float:
    symbol = element.strip().capitalize()
    g_ang_inv = max(float(g_nm_inv), 0.0) / 10.0
    s_value = 0.5 * g_ang_inv
    if symbol in CROMER_MANN:
        a_values, b_values, c_value = CROMER_MANN[symbol]
        return float(sum(a * math.exp(-b * s_value * s_value) for a, b in zip(a_values, b_values)) + c_value)
    z_value = float(ATOMIC_NUMBERS.get(symbol, 18))
    return z_value * math.exp(-2.8 * s_value * s_value)


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


def space_group_symbol_from_number(number: int) -> str:
    try:
        from pymatgen.symmetry.groups import SpaceGroup

        return space_group_symbol(SpaceGroup.from_int_number(int(number)).symbol)
    except Exception:
        return str(number)


def cif_block_value(block: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in block:
            return block[key]
    return None


def declared_space_group_from_cif_block(block: dict[str, Any]) -> str:
    number = cif_block_value(block, "_symmetry_Int_Tables_number", "_space_group_IT_number")
    if number not in (None, "", ".", "?"):
        try:
            return space_group_symbol_from_number(int(str(number).strip("'\"")))
        except ValueError:
            pass
    symbol = cif_block_value(block, "_symmetry_space_group_name_H-M", "_space_group_name_H-M_alt")
    return space_group_symbol(str(symbol).strip("'\"") if symbol not in (None, "", ".", "?") else "P1")


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
    )
    if operation_texts:
        try:
            from pymatgen.core.operations import SymmOp

            operations = []
            for text in operation_texts:
                operation = str(text).strip().strip("'\"")
                if operation:
                    operations.append(SymmOp.from_xyz_str(operation))
            if operations:
                return operations
        except Exception:
            pass

    symbol = space_group_symbol(declared_space_group)
    if symbol in {"", "P1", "1"}:
        return []
    try:
        from pymatgen.symmetry.groups import SpaceGroup

        space_group = SpaceGroup.from_int_number(int(symbol)) if symbol.isdigit() else SpaceGroup(symbol)
        return list(space_group.symmetry_ops)
    except Exception:
        return []


def equivalent_under_operations(site: AtomicSite, representative: AtomicSite, operations: list[Any]) -> bool:
    if site.element.strip().capitalize() != representative.element.strip().capitalize():
        return False
    if not math.isclose(float(site.occupancy), float(representative.occupancy), abs_tol=1e-5):
        return False
    target = snap_fractional(site.fractional)
    base = snap_fractional(representative.fractional)
    for operation in operations:
        frac = snap_fractional(np.mod(operation.operate(base), 1.0))
        if fractional_points_match(frac, target):
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
        frac = snap_fractional(
            wrap_fractional(
                np.array(
                    [
                        parse_cif_float(cif_value_at(xs, index, 0.0)),
                        parse_cif_float(cif_value_at(ys, index, 0.0)),
                        parse_cif_float(cif_value_at(zs, index, 0.0)),
                    ],
                    dtype=float,
                )
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


def atomic_sites_from_structure(structure: Any, representatives_only: bool) -> list[AtomicSite]:
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
        frac = snap_fractional(wrap_fractional(np.asarray(site.frac_coords, dtype=float)))
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
        from pymatgen.io.cif import CifParser
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    except Exception as exc:
        raise ValueError(f"pymatgen is required to load CIF files: {exc}") from exc

    try:
        parser = CifParser(str(path))
        cif_block = next(iter(parser.as_dict().values()), {})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            structure = parser.parse_structures(primitive=False)[0]
    except Exception as exc:
        raise ValueError(f"Could not read CIF file: {exc}") from exc

    lattice = structure.lattice
    declared_space_group = declared_space_group_from_cif_block(cif_block)
    crystal_system = "triclinic"
    try:
        analyzer = SpacegroupAnalyzer(structure, symprec=0.01)
        crystal_system = str(analyzer.get_crystal_system()).lower()
    except Exception:
        pass

    sites = atomic_sites_from_cif_block(cif_block, declared_space_group)
    if not sites:
        representatives_only = space_group_symbol(declared_space_group) not in {"", "P1", "1"}
        sites = atomic_sites_from_structure(structure, representatives_only=representatives_only)

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
        sites=sites,
    )


class CrystalLibrary:
    def __init__(self) -> None:
        self.definitions: dict[str, CrystalDefinition] = {}
        self.reload()

    def reload(self) -> None:
        self.definitions = {
            name: CrystalDefinition.from_dict(definition.to_dict())
            for name, definition in DEFAULT_CRYSTALS.items()
        }
        for path in (BUNDLED_LIBRARY_PATH, USER_LIBRARY_PATH):
            self.definitions.update(self._load_path(path))
        self.definitions = {
            name: normalized_crystal_definition(definition)
            for name, definition in self.definitions.items()
        }

    def options(self) -> list[str]:
        custom_names = sorted(name for name in self.definitions if name not in DEFAULT_NAMES)
        return ["FCC", "BCC", "HCP", *custom_names, CUSTOM_SENTINEL]

    def get(self, name: str) -> CrystalDefinition:
        return self.definitions.get(name, self.definitions["FCC"])

    def exists(self, name: str) -> bool:
        return (name or "").strip() in self.definitions

    def save(self, definition: CrystalDefinition) -> CrystalDefinition:
        definition = CrystalDefinition.from_dict(definition.to_dict())
        definition.name = self._custom_name(definition.name)
        self._save_definition_to_path(LOCAL_LIBRARY_PATH, definition)
        self.reload()
        return definition

    def save_new(self, definition: CrystalDefinition) -> CrystalDefinition:
        definition = CrystalDefinition.from_dict(definition.to_dict())
        definition.name = self._custom_name(definition.name)
        if self.exists(definition.name):
            raise ValueError(f"A structure named {definition.name!r} already exists. Choose another name.")
        self._save_definition_to_path(LOCAL_LIBRARY_PATH, definition)
        self.reload()
        return definition

    def save_edited(self, definition: CrystalDefinition, original_name: str | None = None) -> CrystalDefinition:
        definition = CrystalDefinition.from_dict(definition.to_dict())
        definition.name = self._custom_name(definition.name)
        original_name = (original_name or "").strip()
        if original_name and original_name not in DEFAULT_NAMES and original_name != definition.name:
            if self.exists(definition.name):
                raise ValueError(f"A structure named {definition.name!r} already exists.")
            self.delete(original_name)
        self._save_definition_to_path(LOCAL_LIBRARY_PATH, definition)
        self.reload()
        return definition

    def delete(self, name: str) -> bool:
        if name in DEFAULT_NAMES:
            return False
        removed = False
        saved = self._load_path(USER_LIBRARY_PATH)
        if name in saved:
            saved.pop(name, None)
            USER_LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
            payload = {"structures": [saved[item].to_dict() for item in sorted(saved)]}
            USER_LIBRARY_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            removed = True
        if removed:
            self.reload()
        return removed

    @staticmethod
    def _save_definition_to_path(path: Path, definition: CrystalDefinition) -> None:
        saved = CrystalLibrary._load_path(path)
        saved[definition.name] = definition
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"structures": [saved[name].to_dict() for name in sorted(saved)]}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def _custom_name(name: str) -> str:
        base = (name or "Customized crystal").strip()
        if base in DEFAULT_NAMES:
            base = f"{base} custom"
        return base

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
    return left + "".join(str(value) for value in values) + right


def zone_axis_direction_label(values: tuple[int, ...]) -> str:
    if any(abs(value) >= 10 for value in values):
        return "[" + " ".join(str(value) for value in values) + "]"
    return compact_label(values, "direction")


def miller_index_label(values: tuple[int, ...]) -> str:
    if len(values) == 4 or any(abs(value) >= 10 for value in values):
        return "(" + " ".join(str(value) for value in values) + ")"
    return compact_label(values, "plane")


def reduce_integer_tuple(values: tuple[int, ...] | list[int] | np.ndarray) -> tuple[int, ...]:
    ints = [int(round(float(value))) for value in values]
    if all(value == 0 for value in ints):
        return tuple(ints)
    divisor = 0
    for value in ints:
        divisor = math.gcd(divisor, abs(value))
    if divisor > 1:
        ints = [value // divisor for value in ints]
    first_nonzero = next((value for value in ints if value != 0), 1)
    if first_nonzero < 0:
        ints = [-value for value in ints]
    return tuple(int(value) for value in ints)


def reduce_integer_vector(values: np.ndarray) -> tuple[int, int, int]:
    reduced = reduce_integer_tuple(values[:3])
    if all(value == 0 for value in reduced):
        return (1, 0, 0)
    return tuple(int(value) for value in reduced[:3])


def hcp_three_index_direction_to_four(axis: tuple[int, int, int]) -> tuple[int, int, int, int]:
    u, v, w = axis
    return reduce_integer_tuple((2 * u - v, 2 * v - u, -u - v, 3 * w))


def hcp_three_index_plane_to_four(index: tuple[int, int, int]) -> tuple[int, int, int, int]:
    h, k, l = index
    return (h, k, -h - k, l)


def split_index_groups(text: str, allow_multiple: bool = False) -> list[str]:
    text = normalize_text(text)
    if not text:
        return []

    bracketed = re.findall(r"[\[\(\{<]\s*([^\]\)\}>]+?)\s*[\]\)\}>]", text)
    if bracketed:
        return [group.strip() for group in bracketed if group.strip()]

    if re.search(r"[,;|/]", text):
        return [part.strip() for part in re.split(r"[,;|/]+", text) if part.strip()]

    parts = text.split()
    if allow_multiple and len(parts) > 1:
        compact_groups = [parse_compact_indices(part) for part in parts]
        if all(len(group) in (3, 4) for group in compact_groups):
            return parts

    return [text]


def parse_compact_indices(text: str) -> list[int]:
    cleaned = re.sub(r"[^0-9+\-]", "", normalize_text(text))
    values = []
    sign = 1
    i = 0
    while i < len(cleaned):
        char = cleaned[i]
        if char == "+":
            sign = 1
        elif char == "-":
            sign = -1
        elif char.isdigit():
            values.append(sign * int(char))
            sign = 1
        i += 1
    return values


def parse_index_values(text: str) -> tuple[int, ...]:
    text = normalize_text(text)
    text = text.strip("[](){}<>")
    spaced = re.sub(r"[,;|/]+", " ", text)
    if re.search(r"\s", spaced):
        values = [int(match.group(0)) for match in re.finditer(r"[+-]?\d+", spaced)]
    else:
        values = parse_compact_indices(spaced)
    return tuple(values)


def reciprocal_lattice(lattice: np.ndarray) -> np.ndarray:
    return np.linalg.inv(lattice).T


def normalize_vector(vector: np.ndarray) -> np.ndarray | None:
    length = float(np.linalg.norm(vector))
    if length < 1e-12:
        return None
    return vector / length


def lattice_matrix(definition: CrystalDefinition) -> np.ndarray:
    a_value = max(float(definition.a), 1e-8)
    b_value = max(float(definition.b), 1e-8)
    c_value = max(float(definition.c), 1e-8)
    alpha = math.radians(float(definition.alpha))
    beta = math.radians(float(definition.beta))
    gamma = math.radians(float(definition.gamma))
    sin_gamma = math.sin(gamma)
    if abs(sin_gamma) < 1e-8:
        raise ValueError("gamma angle is too close to 0 or 180 degrees")

    a_vec = np.array([a_value, 0.0, 0.0], dtype=float)
    b_vec = np.array([b_value * math.cos(gamma), b_value * sin_gamma, 0.0], dtype=float)
    c_x = c_value * math.cos(beta)
    c_y = c_value * (math.cos(alpha) - math.cos(beta) * math.cos(gamma)) / sin_gamma
    c_z2 = c_value * c_value - c_x * c_x - c_y * c_y
    if c_z2 < -1e-8:
        raise ValueError("lattice angles produce an invalid unit cell")
    c_vec = np.array([c_x, c_y, math.sqrt(max(c_z2, 1e-12))], dtype=float)
    return np.array([a_vec, b_vec, c_vec], dtype=float)


def fractional_to_display(frac: np.ndarray, lattice: np.ndarray, center: np.ndarray, scale_nm: float) -> np.ndarray:
    return (frac @ lattice - center) / scale_nm


def is_hexagonal(model: CrystalModel) -> bool:
    return model.definition.lattice_system.lower() == "hexagonal" or model.name.upper() == "HCP"


def hcp_direction_to_cart(values: tuple[int, ...], lattice: np.ndarray) -> np.ndarray:
    a1, a2, c_axis = lattice
    if len(values) == 4:
        u, v, t, w = values
        return (u - t) * a1 + (v - t) * a2 + w * c_axis
    u, v, w = values
    return u * a1 + v * a2 + w * c_axis


def direction_to_cart(values: tuple[int, ...], model: CrystalModel) -> np.ndarray:
    if is_hexagonal(model):
        return hcp_direction_to_cart(values, model.lattice)
    return np.array(values[:3], dtype=float) @ model.lattice


def plane_normal_to_cart(values: tuple[int, ...], model: CrystalModel) -> np.ndarray:
    if is_hexagonal(model) and len(values) == 4:
        h, k, _i, l = values
    else:
        h, k, l = values[:3]
    return np.array([h, k, l], dtype=float) @ model.reciprocal


def plane_coefficients(values: tuple[int, ...], model: CrystalModel) -> np.ndarray:
    if is_hexagonal(model) and len(values) == 4:
        h, k, _i, l = values
    else:
        h, k, l = values[:3]
    return np.array([h, k, l], dtype=float)


def direction_components(values: tuple[int, ...], model: CrystalModel) -> np.ndarray:
    if is_hexagonal(model) and len(values) == 4:
        u, v, t, w = values
        return np.array([u - t, v - t, w], dtype=float)
    return np.array(values[:3], dtype=float)


def direction_delta_for_display(values: tuple[int, ...], model: CrystalModel) -> np.ndarray:
    components = direction_components(values, model)
    scale = max(float(np.max(np.abs(components))), 1.0)
    return (components / scale) @ model.display_lattice


def direction_segment_for_display(values: tuple[int, ...], model: CrystalModel) -> tuple[np.ndarray, np.ndarray]:
    components = direction_components(values, model)
    scale = max(float(np.max(np.abs(components))), 1.0)
    delta_fractional = components / scale
    start_fractional = np.where(delta_fractional < 0.0, -delta_fractional, 0.0)
    end_fractional = start_fractional + delta_fractional
    start = model.crystal_origin + start_fractional @ model.display_lattice
    end = model.crystal_origin + end_fractional @ model.display_lattice
    return start, end


def reciprocal_index_components(values: tuple[int, ...], model: CrystalModel) -> tuple[int, int, int]:
    if is_hexagonal(model) and len(values) == 4:
        components = direction_components(values, model)
    else:
        components = np.array(values[:3], dtype=float)
    ints = [int(round(float(value))) for value in components[:3]]
    if all(value == 0 for value in ints):
        return (1, 0, 0)
    divisor = 0
    for value in ints:
        divisor = math.gcd(divisor, abs(value))
    if divisor > 1:
        ints = [value // divisor for value in ints]
    return tuple(int(value) for value in ints[:3])


def reciprocal_index_to_cart(values: tuple[int, ...], model: CrystalModel) -> np.ndarray:
    return np.array(reciprocal_index_components(values, model), dtype=float) @ model.reciprocal


def reciprocal_delta_for_display(values: tuple[int, ...], model: CrystalModel) -> np.ndarray:
    reciprocal_direction = normalize_vector(reciprocal_index_to_cart(values, model))
    if reciprocal_direction is None:
        return np.zeros(3, dtype=float)
    return reciprocal_direction * 0.72


def shifted_segment_for_display_delta(delta: np.ndarray, model: CrystalModel) -> tuple[np.ndarray, np.ndarray]:
    delta = np.asarray(delta, dtype=float)
    if float(np.linalg.norm(delta)) < 1e-10:
        return model.crystal_origin.copy(), model.crystal_origin.copy()
    try:
        delta_fractional = np.linalg.solve(model.display_lattice.T, delta)
    except np.linalg.LinAlgError:
        return model.crystal_origin.copy(), model.crystal_origin + delta

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

    start = model.crystal_origin + start_fractional @ model.display_lattice
    end = start + delta
    return start, end


def reciprocal_segment_for_display(values: tuple[int, ...], model: CrystalModel) -> tuple[np.ndarray, np.ndarray]:
    return shifted_segment_for_display_delta(reciprocal_delta_for_display(values, model), model)


def reciprocal_prefix_group(group: str) -> tuple[bool, str]:
    text = normalize_text(group).strip()
    if text.startswith("*"):
        return True, text[1:].strip()
    if re.match(r"^[rR](?=\s*[\[\(\{<+\-]|\s*\d)", text):
        return True, text[1:].strip()
    return False, text


def unique_points(points: list[np.ndarray], tolerance: float = 1e-6) -> list[np.ndarray]:
    unique = []
    for point in points:
        if not any(np.linalg.norm(point - saved) < tolerance for saved in unique):
            unique.append(point)
    return unique


def cell_vertices_from_edges(edges: list[tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
    points = []
    for start, end in edges:
        points.extend([start, end])
    return np.array(unique_points(points), dtype=float)


def clipped_plane_polygon(model: CrystalModel, plane: ParsedIndex) -> np.ndarray | None:
    coefficients = plane_coefficients(plane.values, model)
    normal = coefficients @ reciprocal_lattice(model.display_lattice)
    normal_unit = normalize_vector(normal)
    if normal_unit is None:
        return None

    constant = float(np.dot(normal, model.crystal_origin) + 1.0)
    vertices = cell_vertices_from_edges(model.cell_edges)
    polygon = intersect_plane_with_edges(model.cell_edges, normal, constant)
    if len(polygon) < 3:
        projected_vertices = vertices @ normal
        constant = float(0.5 * (projected_vertices.min() + projected_vertices.max()))
        polygon = intersect_plane_with_edges(model.cell_edges, normal, constant)
    if len(polygon) < 3:
        return None

    centroid = np.mean(polygon, axis=0)
    u_axis, v_axis = projection_basis(normal_unit)
    angles = [math.atan2(float(np.dot(point - centroid, v_axis)), float(np.dot(point - centroid, u_axis))) for point in polygon]
    order = np.argsort(angles)
    return polygon[order]


def intersect_plane_with_edges(
    edges: list[tuple[np.ndarray, np.ndarray]], normal: np.ndarray, constant: float
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

    parsed = []
    errors = []
    if not allow_multiple:
        groups = groups[:1]

    for group in groups:
        is_reciprocal = False
        parse_group = group
        if allow_reciprocal and kind == "direction":
            is_reciprocal, parse_group = reciprocal_prefix_group(group)
        values = parse_index_values(parse_group)
        if is_hexagonal(model):
            valid_lengths = (3, 4)
        else:
            valid_lengths = (3,)

        if len(values) not in valid_lengths:
            errors.append(f"{group!r} is not a valid {model.name} index")
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


def camera_vector_from_view(elev: float, azim: float) -> np.ndarray:
    elev_rad = math.radians(elev)
    azim_rad = math.radians(azim)
    return np.array(
        [
            math.cos(elev_rad) * math.cos(azim_rad),
            math.cos(elev_rad) * math.sin(azim_rad),
            math.sin(elev_rad),
        ],
        dtype=float,
    )


def view_from_vector(vector: np.ndarray) -> tuple[float, float]:
    unit = normalize_vector(vector)
    if unit is None:
        return 0.0, 0.0
    elev = math.degrees(math.asin(float(np.clip(unit[2], -1.0, 1.0))))
    if math.hypot(float(unit[0]), float(unit[1])) < 1e-10:
        azim = 0.0
    else:
        azim = math.degrees(math.atan2(float(unit[1]), float(unit[0])))
    return elev, azim


def integer_zone_axis_from_view(
    model: CrystalModel,
    view_vector: np.ndarray,
    max_index: int = DEFAULT_ZONE_AXIS_SEARCH_MAX,
) -> tuple[int, int, int]:
    view = normalize_vector(view_vector)
    if view is None:
        return (1, 0, 0)
    best_axis = (1, 0, 0)
    best_score = -1.0
    limit = max(1, int(max_index))
    for u, v, w in product(range(-limit, limit + 1), repeat=3):
        if u == v == w == 0:
            continue
        candidate_axis = reduce_integer_vector(np.array([u, v, w], dtype=float))
        if candidate_axis != (u, v, w):
            continue
        candidate = normalize_vector(direction_to_cart(candidate_axis, model))
        if candidate is None:
            continue
        score = abs(float(np.dot(view, candidate)))
        if score > best_score:
            best_score = score
            best_axis = candidate_axis
    return best_axis


def zone_axis_label_from_view(
    model: CrystalModel,
    view_vector: np.ndarray,
    max_index: int = DEFAULT_ZONE_AXIS_SEARCH_MAX,
    use_hex_four_index: bool = False,
) -> str:
    axis = integer_zone_axis_from_view(model, view_vector, max_index=max_index)
    view = normalize_vector(view_vector)
    axis_vector = normalize_vector(direction_to_cart(axis, model))
    approximate = True
    if view is not None and axis_vector is not None:
        angle = math.degrees(math.acos(min(max(abs(float(np.dot(view, axis_vector))), -1.0), 1.0)))
        approximate = angle > ZONE_AXIS_EXACT_TOL_DEGREES
    label_axis: tuple[int, ...] = hcp_three_index_direction_to_four(axis) if use_hex_four_index and is_hexagonal(model) else axis
    return f"{'~' if approximate else ''}{zone_axis_direction_label(label_axis)} zone"


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


def electron_wavelength_nm(voltage_kv: float) -> float:
    voltage_v = max(float(voltage_kv), 1e-6) * 1000.0
    wavelength_angstrom = 12.3986 / math.sqrt(voltage_v * (1.0 + 0.97845e-6 * voltage_v))
    return wavelength_angstrom * 0.1


def detector_scale_mm_per_nm_inv(camera_length_mm: float, voltage_kv: float) -> float:
    return max(float(camera_length_mm), 1e-9) * electron_wavelength_nm(voltage_kv)


def default_detector_half_width_mm() -> float:
    return DIFFRACTION_BASE_LIMIT_NM_INV * detector_scale_mm_per_nm_inv(
        DEFAULT_CAMERA_LENGTH_MM,
        DEFAULT_VOLTAGE_KV,
    )


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
    passive = rotation_matrix_about_axis(axis_unit, -float(crystal_degrees))
    new_normal = normalize_vector(passive @ normal)
    new_u = normalize_vector(passive @ u_axis)
    if new_normal is None or new_u is None:
        return normal, normalize_roll(roll)

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

    parsed_axes, _errors = parse_indices(
        axis_text,
        model,
        "direction",
        allow_multiple=False,
        allow_reciprocal=True,
    )
    if not parsed_axes:
        return None, []
    return RotationCommand(axis=parsed_axes[0].vector, axis_label=parsed_axes[0].label, angle_degrees=angle), []


def cube_edges(size: float = 1.0) -> list[tuple[np.ndarray, np.ndarray]]:
    half = size / 2.0
    corners = np.array(list(product([-half, half], repeat=3)), dtype=float)
    edges = []
    for i, start in enumerate(corners):
        for j, end in enumerate(corners):
            if i < j and np.count_nonzero(np.abs(start - end) > 1e-9) == 1:
                edges.append((start, end))
    return edges


def hcp_prism_edges(radius: float, height: float) -> list[tuple[np.ndarray, np.ndarray]]:
    bottom = []
    top = []
    for i in range(6):
        angle = math.radians(60 * i + 30)
        xy = np.array([radius * math.cos(angle), radius * math.sin(angle)])
        bottom.append(np.array([xy[0], xy[1], -height / 2.0]))
        top.append(np.array([xy[0], xy[1], height / 2.0]))

    edges = []
    for i in range(6):
        edges.append((bottom[i], bottom[(i + 1) % 6]))
        edges.append((top[i], top[(i + 1) % 6]))
        edges.append((bottom[i], top[i]))
    return edges


def generate_supercell(lattice: np.ndarray, basis: np.ndarray, radius: int) -> np.ndarray:
    atoms = []
    offsets = range(-radius, radius + 1)
    for i, j, k in product(offsets, offsets, offsets):
        shift = np.array([i, j, k], dtype=float)
        for basis_atom in basis:
            atoms.append((shift + basis_atom) @ lattice)
    atoms = np.array(atoms, dtype=float)
    atoms -= atoms.mean(axis=0)
    return atoms


def make_cubic_model(name: str) -> CrystalModel:
    definition = DEFAULT_CRYSTALS[name]
    expanded = expanded_sites(definition)
    lattice_parameter = DEFAULT_LATTICE_NM[name]
    lattice = np.eye(3) * lattice_parameter
    display_lattice = np.eye(3)
    crystal_origin = np.array([-0.5, -0.5, -0.5], dtype=float)
    if name == "FCC":
        basis = np.array(
            [
                [0.0, 0.0, 0.0],
                [0.5, 0.5, 0.0],
                [0.5, 0.0, 0.5],
                [0.0, 0.5, 0.5],
            ]
        )
        corners = np.array(list(product([-0.5, 0.5], repeat=3)), dtype=float)
        faces = np.array(
            [
                [0.0, 0.0, -0.5],
                [0.0, 0.0, 0.5],
                [0.0, -0.5, 0.0],
                [0.0, 0.5, 0.0],
                [-0.5, 0.0, 0.0],
                [0.5, 0.0, 0.0],
            ],
            dtype=float,
        )
        display_atoms = np.vstack((corners, faces))
    else:
        basis = np.array([[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]])
        display_atoms = np.vstack((np.array(list(product([-0.5, 0.5], repeat=3)), dtype=float), [0, 0, 0]))

    diffraction_atoms = generate_supercell(lattice, basis, radius=6)
    atom_colors = [CRYSTAL_STYLES[name]["atom"]] * len(display_atoms)
    atom_occupancies = [1.0] * len(display_atoms)
    return CrystalModel(
        name=name,
        lattice=lattice,
        basis=basis,
        display_lattice=display_lattice,
        crystal_origin=crystal_origin,
        display_atoms=display_atoms,
        diffraction_atoms=diffraction_atoms,
        cell_edges=cube_edges(),
        limit=0.9,
        definition=definition,
        expanded_sites=expanded,
        reciprocal=reciprocal_lattice(lattice),
        atom_colors=atom_colors,
        atom_occupancies=atom_occupancies,
        scale_nm=lattice_parameter,
    )


def make_hcp_model() -> CrystalModel:
    definition = DEFAULT_CRYSTALS["HCP"]
    if len(expanded_sites(definition)) < 2:
        definition = CrystalDefinition.from_dict(definition.to_dict())
        definition.sites = [
            AtomicSite("Mg", 1.0 / 3.0, 2.0 / 3.0, 0.25, 1.0, "2c", CRYSTAL_STYLES["HCP"]["atom"]),
            AtomicSite("Mg", 2.0 / 3.0, 1.0 / 3.0, 0.75, 1.0, "2c", CRYSTAL_STYLES["HCP"]["atom"]),
        ]
    return make_custom_model(definition)


def make_custom_model(definition: CrystalDefinition) -> CrystalModel:
    lattice = lattice_matrix(definition)
    reciprocal = reciprocal_lattice(lattice)
    expanded = expanded_sites(definition)
    if not expanded:
        expanded = [AtomicSite("Ni", 0.0, 0.0, 0.0, 1.0, "", CRYSTAL_STYLES["FCC"]["atom"])]

    corners_frac = np.array(list(product([0.0, 1.0], repeat=3)), dtype=float)
    corners_cart = corners_frac @ lattice
    center = np.array([0.5, 0.5, 0.5], dtype=float) @ lattice
    edge_norm = float(np.max(np.linalg.norm(lattice, axis=1)))
    bbox_span = float(np.max(np.ptp(corners_cart, axis=0)))
    scale_nm = max(edge_norm, bbox_span, 1e-8)
    display_lattice = lattice / scale_nm
    crystal_origin = fractional_to_display(np.zeros(3), lattice, center, scale_nm)

    cell_edges: list[tuple[np.ndarray, np.ndarray]] = []
    for i, start_frac in enumerate(corners_frac):
        for end_frac in corners_frac[i + 1 :]:
            if np.count_nonzero(np.abs(start_frac - end_frac) > 1e-9) == 1:
                cell_edges.append(
                    (
                        fractional_to_display(start_frac, lattice, center, scale_nm),
                        fractional_to_display(end_frac, lattice, center, scale_nm),
                    )
                )

    atom_positions = []
    atom_colors = []
    atom_occupancies = []
    for site in expanded:
        base = np.mod(site.fractional.astype(float), 1.0)
        base[np.isclose(base, 1.0, atol=1e-9)] = 0.0
        translation_choices = [[0.0, 1.0] if abs(coord) < 1e-8 else [0.0] for coord in base]
        for translation in product(*translation_choices):
            frac = base + np.array(translation, dtype=float)
            if np.all(frac <= 1.0 + 1e-8):
                atom_positions.append(fractional_to_display(frac, lattice, center, scale_nm))
                atom_colors.append(color_for_site(site))
                atom_occupancies.append(min(max(float(site.occupancy), 0.0), 1.0))

    display_atoms = np.array(atom_positions if atom_positions else [crystal_origin], dtype=float)
    basis = np.array([site.fractional for site in expanded], dtype=float)
    diffraction_atoms = generate_supercell(lattice, basis, radius=6)
    all_points = [point for edge in cell_edges for point in edge]
    all_points.extend(display_atoms)
    limit = max(1.25, float(np.max(np.abs(np.array(all_points)))) * 1.35 if all_points else 1.25)
    return CrystalModel(
        name=definition.name,
        lattice=lattice,
        basis=basis,
        display_lattice=display_lattice,
        crystal_origin=crystal_origin,
        display_atoms=display_atoms,
        diffraction_atoms=diffraction_atoms,
        cell_edges=cell_edges,
        limit=limit,
        definition=definition,
        expanded_sites=expanded,
        reciprocal=reciprocal,
        atom_colors=atom_colors or [dominant_color(definition)],
        atom_occupancies=atom_occupancies or [1.0],
        scale_nm=scale_nm,
    )


class CrystalBuilderDialog(tk.Toplevel):
    def __init__(
        self,
        app: "CrystalDiffractionSimulator",
        column: int,
        crystal_name: str | None = None,
        mode: str = "new",
    ):
        super().__init__(app)
        self.app = app
        self.column = column
        self.original_name = (crystal_name or "").strip()
        self.mode = "edit" if mode == "edit" else "new"
        self.title("Customized Crystal Builder")
        self.geometry("860x600+120+80")
        self.transient(app)
        self.configure(bg=app.current_theme()["window_bg"])
        self.site_selection: str | None = None
        self._loading_definition = False
        self._updating_editor = False
        self._site_update_job: str | None = None

        selected = crystal_name or (app.states[column].crystal if 0 <= column < len(app.states) else "FCC")
        definition = app.library.get(selected)

        self.name_var = tk.StringVar()
        self.system_var = tk.StringVar()
        self.space_group_var = tk.StringVar()
        self.a_var = tk.StringVar()
        self.b_var = tk.StringVar()
        self.c_var = tk.StringVar()
        self.alpha_var = tk.StringVar()
        self.beta_var = tk.StringVar()
        self.gamma_var = tk.StringVar()

        self.site_element_var = tk.StringVar(value="Ni")
        self.site_x_var = tk.StringVar(value="0")
        self.site_y_var = tk.StringVar(value="0")
        self.site_z_var = tk.StringVar(value="0")
        self.site_occ_var = tk.StringVar(value="1")
        self.site_color_var = tk.StringVar(value=ELEMENT_COLORS["Ni"])
        self.site_label_var = tk.StringVar(value="")

        self._build_ui()
        self.load_definition(definition)
        self._bind_site_editor_traces()
        self.grab_set()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)
        for column in range(4):
            outer.columnconfigure(column, weight=1)

        fields = [
            ("Name", self.name_var),
            ("Lattice", self.system_var),
            ("Space group", self.space_group_var),
            ("a nm", self.a_var),
            ("b nm", self.b_var),
            ("c nm", self.c_var),
            ("alpha deg", self.alpha_var),
            ("beta deg", self.beta_var),
            ("gamma deg", self.gamma_var),
        ]
        for index, (label, variable) in enumerate(fields):
            row = index // 3
            col = (index % 3) * 2
            ttk.Label(outer, text=label).grid(row=row, column=col, sticky="e", padx=(0, 6), pady=3)
            if label == "Lattice":
                widget = ttk.Combobox(outer, textvariable=variable, values=LATTICE_SYSTEMS, state="readonly", width=14)
            else:
                widget = ttk.Entry(outer, textvariable=variable, width=16)
            widget.grid(row=row, column=col + 1, sticky="ew", pady=3)

        ttk.Button(outer, text="Apply lattice constraints", command=self.apply_lattice_constraints).grid(
            row=3, column=1, sticky="w", pady=(6, 10)
        )

        self.site_tree = ttk.Treeview(
            outer,
            columns=("element", "x", "y", "z", "occupancy", "color", "label"),
            show="headings",
            height=8,
        )
        for column, width in [
            ("element", 80),
            ("x", 80),
            ("y", 80),
            ("z", 80),
            ("occupancy", 90),
            ("color", 100),
            ("label", 120),
        ]:
            self.site_tree.heading(column, text=column)
            self.site_tree.column(column, width=width, anchor="center")
        self.site_tree.grid(row=4, column=0, columnspan=6, sticky="nsew", pady=(0, 8))
        self.site_tree.bind("<<TreeviewSelect>>", self.on_site_selected)
        outer.rowconfigure(4, weight=1)

        editor = ttk.LabelFrame(outer, text="Atom site", padding=8)
        editor.grid(row=5, column=0, columnspan=6, sticky="ew")
        for column in range(7):
            editor.columnconfigure(column, weight=1)

        site_fields = [
            ("Atom", self.site_element_var),
            ("x", self.site_x_var),
            ("y", self.site_y_var),
            ("z", self.site_z_var),
            ("Occ.", self.site_occ_var),
            ("Color", self.site_color_var),
            ("Site", self.site_label_var),
        ]
        for column, (label, variable) in enumerate(site_fields):
            ttk.Label(editor, text=label).grid(row=0, column=column, sticky="w")
            if label == "Atom":
                widget = ttk.Combobox(editor, textvariable=variable, values=ELEMENTS, width=8)
            elif label == "Color":
                widget = ttk.Combobox(editor, textvariable=variable, values=tuple(NAMED_COLORS), width=14)
            else:
                widget = ttk.Entry(editor, textvariable=variable, width=10)
            widget.grid(row=1, column=column, sticky="ew", padx=(0, 6))

        button_row = ttk.Frame(outer)
        button_row.grid(row=6, column=0, columnspan=6, sticky="ew", pady=(10, 0))
        ttk.Button(button_row, text="Add site", command=self.add_site).pack(side=tk.LEFT)
        ttk.Button(button_row, text="Delete selected site", command=self.delete_selected_site).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(button_row, text="Save as a new structure", command=self.save_as_new_structure).pack(side=tk.RIGHT)
        if self.mode == "edit":
            ttk.Button(button_row, text="Save edited structure", command=self.save_edited_structure).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(button_row, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=(0, 8))

    def load_definition(self, definition: CrystalDefinition) -> None:
        self._loading_definition = True
        self.name_var.set(definition.name if self.mode == "edit" else (definition.name if definition.name not in DEFAULT_NAMES else f"{definition.name} custom"))
        self.system_var.set(definition.lattice_system)
        self.space_group_var.set(space_group_symbol(definition.space_group))
        self.a_var.set(f"{definition.a:g}")
        self.b_var.set(f"{definition.b:g}")
        self.c_var.set(f"{definition.c:g}")
        self.alpha_var.set(f"{definition.alpha:g}")
        self.beta_var.set(f"{definition.beta:g}")
        self.gamma_var.set(f"{definition.gamma:g}")
        for item in self.site_tree.get_children():
            self.site_tree.delete(item)
        for site in definition.sites or []:
            self.site_tree.insert(
                "",
                "end",
                values=(
                    site.element,
                    f"{site.x:g}",
                    f"{site.y:g}",
                    f"{site.z:g}",
                    f"{site.occupancy:g}",
                    color_for_site(site),
                    site.label,
                ),
            )
        self._loading_definition = False

    def _bind_site_editor_traces(self) -> None:
        for variable in (
            self.site_element_var,
            self.site_x_var,
            self.site_y_var,
            self.site_z_var,
            self.site_occ_var,
            self.site_color_var,
            self.site_label_var,
        ):
            variable.trace_add("write", lambda *_args: self.schedule_selected_site_update())

    def apply_lattice_constraints(self) -> None:
        system = self.system_var.get() or "triclinic"
        a_value = self.a_var.get() or "0.35"
        if system == "cubic":
            self.b_var.set(a_value)
            self.c_var.set(a_value)
            self.alpha_var.set("90")
            self.beta_var.set("90")
            self.gamma_var.set("90")
        elif system == "tetragonal":
            self.b_var.set(a_value)
            self.alpha_var.set("90")
            self.beta_var.set("90")
            self.gamma_var.set("90")
        elif system == "orthorhombic":
            self.alpha_var.set("90")
            self.beta_var.set("90")
            self.gamma_var.set("90")
        elif system == "hexagonal":
            self.b_var.set(a_value)
            self.alpha_var.set("90")
            self.beta_var.set("90")
            self.gamma_var.set("120")
        elif system == "monoclinic":
            self.alpha_var.set("90")
            self.gamma_var.set("90")

    def on_site_selected(self, _event=None) -> None:
        selection = self.site_tree.selection()
        if not selection:
            self.site_selection = None
            return
        self.site_selection = selection[0]
        values = self.site_tree.item(self.site_selection, "values")
        self._updating_editor = True
        self.site_element_var.set(values[0])
        self.site_x_var.set(values[1])
        self.site_y_var.set(values[2])
        self.site_z_var.set(values[3])
        self.site_occ_var.set(values[4])
        self.site_color_var.set(values[5])
        self.site_label_var.set(values[6])
        self._updating_editor = False

    def schedule_selected_site_update(self) -> None:
        if self._loading_definition or self._updating_editor or not self.site_selection:
            return
        if self._site_update_job is not None:
            self.after_cancel(self._site_update_job)
        self._site_update_job = self.after(250, self.update_selected_site_from_editor)

    def update_selected_site_from_editor(self) -> None:
        self._site_update_job = None
        if not self.site_selection or self.site_selection not in self.site_tree.get_children():
            return
        try:
            site = self.read_site_editor()
        except ValueError:
            return
        self.site_tree.item(self.site_selection, values=self.site_values(site))

    def site_values(self, site: AtomicSite) -> tuple[str, str, str, str, str, str, str]:
        return (
            site.element,
            f"{site.x:g}",
            f"{site.y:g}",
            f"{site.z:g}",
            f"{site.occupancy:g}",
            color_for_site(site),
            site.label,
        )

    def add_site(self) -> None:
        try:
            site = self.read_site_editor()
        except ValueError as exc:
            messagebox.showerror("Invalid Site", str(exc), parent=self)
            return
        item = self.site_tree.insert("", "end", values=self.site_values(site))
        self.site_tree.selection_set(item)
        self.site_tree.focus(item)
        self.site_selection = item

    def delete_selected_site(self) -> None:
        selection = self.site_tree.selection()
        for item in selection:
            self.site_tree.delete(item)
        self.site_selection = None

    def read_site_editor(self) -> AtomicSite:
        element = (self.site_element_var.get() or "X").strip().capitalize()
        return AtomicSite(
            element=element,
            x=float(self.site_x_var.get()),
            y=float(self.site_y_var.get()),
            z=float(self.site_z_var.get()),
            occupancy=float(self.site_occ_var.get() or 1.0),
            label=self.site_label_var.get().strip(),
            color=self.site_color_var.get().strip() or color_for_element(element),
        )

    def read_definition(self) -> CrystalDefinition:
        sites = []
        for item in self.site_tree.get_children():
            values = self.site_tree.item(item, "values")
            sites.append(
                AtomicSite(
                    element=str(values[0]).strip().capitalize(),
                    x=float(values[1]),
                    y=float(values[2]),
                    z=float(values[3]),
                    occupancy=float(values[4]),
                    color=str(values[5]),
                    label=str(values[6]),
                )
            )
        if not sites:
            raise ValueError("add at least one atom site")
        definition = CrystalDefinition(
            name=self.name_var.get().strip() or "Customized crystal",
            lattice_system=self.system_var.get().strip().lower() or "triclinic",
            a=float(self.a_var.get()),
            b=float(self.b_var.get()),
            c=float(self.c_var.get()),
            alpha=float(self.alpha_var.get()),
            beta=float(self.beta_var.get()),
            gamma=float(self.gamma_var.get()),
            space_group=space_group_symbol(self.space_group_var.get()),
            sites=sites,
        )
        lattice_matrix(definition)
        return definition

    def save_as_new_structure(self) -> None:
        try:
            definition = self.read_definition()
            saved = self.app.save_custom_definition(definition, self.column, save_as_new=True)
        except ValueError as exc:
            messagebox.showerror("Invalid Crystal", str(exc), parent=self)
            return
        self.app.status_var.set(f"Saved custom crystal: {saved.name}")
        self.destroy()

    def save_edited_structure(self) -> None:
        try:
            definition = self.read_definition()
            saved = self.app.save_custom_definition(definition, self.column, original_name=self.original_name or None)
        except ValueError as exc:
            messagebox.showerror("Invalid Crystal", str(exc), parent=self)
            return
        self.app.status_var.set(f"Saved edited crystal: {saved.name}")
        self.destroy()


class ScrollableFrame(tk.Frame):
    def __init__(self, parent: tk.Misc, app: "CrystalDiffractionSimulator"):
        super().__init__(parent, bg=app.current_theme()["window_bg"])
        self.app = app
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0, bg=app.current_theme()["window_bg"])
        self.scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview)
        self._scrollbar_visible = True
        self.inner = tk.Frame(self.canvas, bg=app.current_theme()["window_bg"])
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def _on_inner_configure(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.after_idle(self._sync_scrollbar_visibility)

    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfigure(self.window_id, width=event.width)
        self.after_idle(self._sync_scrollbar_visibility)

    def _sync_scrollbar_visibility(self) -> None:
        bbox = self.canvas.bbox("all")
        if not bbox:
            return
        content_height = bbox[3] - bbox[1]
        viewport_height = max(self.canvas.winfo_height(), 1)
        needs_scrollbar = content_height > viewport_height + SCROLLBAR_VISIBILITY_SLACK_PX
        if needs_scrollbar and not self._scrollbar_visible:
            self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            self.canvas.configure(yscrollcommand=self.scrollbar.set)
            self._scrollbar_visible = True
        elif not needs_scrollbar and self._scrollbar_visible:
            self.scrollbar.pack_forget()
            self.canvas.configure(yscrollcommand="")
            self._scrollbar_visible = False

    def apply_theme(self) -> None:
        color = self.app.current_theme()["window_bg"]
        self.configure(bg=color)
        self.canvas.configure(bg=color)
        self.inner.configure(bg=color)


class LandingFrame(tk.Frame):
    def __init__(self, app: "CrystalDiffractionSimulator"):
        super().__init__(app, bg=app.current_theme()["window_bg"])
        self.app = app
        self.ordinary_var = tk.IntVar(value=3)
        self.combo_var = tk.IntVar(value=1)
        self._image_refs: list[Any] = []
        family = tkfont.nametofont("TkDefaultFont").cget("family")
        # Negative sizes are pixel sizes in Tk; this avoids platform scaling quirks
        # where large point-size tuples can still render like the default font.
        self.title_font = tkfont.Font(self, family=family, size=-88, weight="bold")
        self.subtitle_font = tkfont.Font(self, family=family, size=-52)
        self.control_font = tkfont.Font(self, family=family, size=-52)
        self.button_font = tkfont.Font(self, family=family, size=-54, weight="bold")
        self._build()

    def _build(self) -> None:
        theme = self.app.current_theme()
        card = tk.Frame(self, bg=theme["window_bg"], padx=120, pady=100)
        card.place(relx=0.5, rely=0.5, anchor="center")
        title = self._large_label(
            card,
            text="CrysDiS tkinter layout",
            color=theme["title"],
            size=88,
            bold=True,
            font=self.title_font,
        )
        title.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 64))
        subtitle = self._large_label(
            card,
            text="Choose the comparison layout to build.",
            color=theme["status"],
            size=48,
            font=self.subtitle_font,
        )
        subtitle.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 64))
        self._row(card, 2, "Ordinary crystal panels", self.ordinary_var, 1, MAX_ORDINARY_PANELS)
        self._row(card, 3, "Combo diffraction panels", self.combo_var, 0, MAX_COMBO_PANELS)
        start = self._large_button(
            card,
            text="Start",
            command=self.start,
            size=54,
            bold=True,
            xpad=110,
            ypad=26,
        )
        start.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(72, 0))

    def _row(self, parent: tk.Frame, row: int, text: str, variable: tk.IntVar, low: int, high: int) -> None:
        theme = self.app.current_theme()
        label = self._large_label(parent, text=text, color=theme["label"], size=48, font=self.control_font)
        label.grid(row=row, column=0, sticky="w", padx=(0, 80), pady=28)
        counter = self._large_counter(parent, variable, low, high)
        counter.grid(row=row, column=1, sticky="e", pady=28)

    def _pil_font(self, size: int, bold: bool = False):
        font_name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        font_path = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / font_name
        try:
            return ImageFont.truetype(str(font_path), size=size)
        except Exception:
            try:
                return ImageFont.load_default(size=size)
            except TypeError:
                return ImageFont.load_default()

    def _text_image(self, text: str, size: int, color: str, bold: bool = False, xpad: int = 2, ypad: int = 2):
        if not PIL_AVAILABLE:
            return None
        font = self._pil_font(size, bold)
        probe = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        draw = ImageDraw.Draw(probe)
        bbox = draw.textbbox((0, 0), text, font=font)
        width = max(1, bbox[2] - bbox[0] + 2 * xpad)
        height = max(1, bbox[3] - bbox[1] + 2 * ypad)
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.text((xpad - bbox[0], ypad - bbox[1]), text, font=font, fill=color)
        photo = ImageTk.PhotoImage(image, master=self)
        self._image_refs.append(photo)
        return photo

    def _large_label(
        self,
        parent: tk.Frame,
        text: str,
        color: str,
        size: int,
        font,
        bold: bool = False,
    ) -> tk.Label:
        theme = self.app.current_theme()
        image = self._text_image(text, size=size, color=color, bold=bold)
        if image is None:
            return tk.Label(parent, text=text, bg=theme["window_bg"], fg=color, font=font)
        label = tk.Label(parent, image=image, bg=theme["window_bg"], borderwidth=0, highlightthickness=0)
        label.image = image  # type: ignore[attr-defined]
        return label

    def _large_button(
        self,
        parent: tk.Frame,
        text: str,
        command,
        size: int,
        bold: bool = False,
        xpad: int = 32,
        ypad: int = 12,
    ) -> tk.Button:
        colors = self.app.button_theme_colors()
        image = self._text_image(text, size=size, color=colors["fg"], bold=bold, xpad=xpad, ypad=ypad)
        if image is None:
            return tk.Button(
                parent,
                text=text,
                command=command,
                font=self.button_font,
                padx=xpad,
                pady=ypad,
                bg=colors["bg"],
                fg=colors["fg"],
                activebackground=colors["active_bg"],
                activeforeground=colors["fg"],
            )
        button = tk.Button(
            parent,
            image=image,
            command=command,
            bg=colors["bg"],
            activebackground=colors["active_bg"],
            borderwidth=1,
            relief=tk.RAISED,
        )
        button.image = image  # type: ignore[attr-defined]
        return button

    def _large_counter(self, parent: tk.Frame, variable: tk.IntVar, low: int, high: int) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.app.current_theme()["window_bg"])
        value_label = tk.Label(frame, bg="#FFFFFF", bd=1, relief=tk.SUNKEN, padx=8, pady=4)
        value_label.pack(side=tk.LEFT, padx=8)

        def refresh_value() -> None:
            image = self._text_image(str(variable.get()), size=52, color="#111111", xpad=34, ypad=10)
            if image is None:
                value_label.configure(text=str(variable.get()), font=self.control_font, fg="#111111")
                return
            value_label.configure(image=image)
            value_label.image = image  # type: ignore[attr-defined]

        def change(delta: int) -> None:
            variable.set(min(max(int(variable.get()) + delta, low), high))
            refresh_value()

        minus = self._large_button(frame, "-", lambda: change(-1), size=44, bold=True, xpad=18, ypad=10)
        plus = self._large_button(frame, "+", lambda: change(1), size=44, bold=True, xpad=18, ypad=10)
        minus.pack(side=tk.LEFT)
        value_label.pack_forget()
        value_label.pack(side=tk.LEFT, padx=8)
        plus.pack(side=tk.LEFT)
        refresh_value()
        return frame

    def start(self) -> None:
        self.app.start_layout(self.ordinary_var.get(), self.combo_var.get())


class OrdinaryPanelFrame(tk.LabelFrame):
    def __init__(self, app: "CrystalDiffractionSimulator", state: PanelState, column_index: int):
        theme = app.current_theme()
        super().__init__(
            app.panels_parent,
            text=f"Panel {state.panel_id}",
            bg=theme["window_bg"],
            fg=theme["title"],
            padx=1,
            pady=1,
        )
        self.app = app
        self.state = state
        self.column_index = column_index
        self.status_var = tk.StringVar(value="")
        self.crystal_var = tk.StringVar(value=state.crystal)
        self.zone_var = tk.StringVar(value=state.zone_text)
        self.plane_var = tk.StringVar(value=state.plane_text)
        self.vector_var = tk.StringVar(value=state.vector_text)
        self.rotation_var = tk.StringVar(value=state.rotation_text)
        default_color = state.diffraction_color or app.default_diffraction_color_for_model(app.model_for(state.crystal))
        self.diff_color_var = tk.StringVar(value=app.display_color_name(default_color))
        self.crystal_combo: ttk.Combobox | None = None
        self._build()

    def _build(self) -> None:
        self.app.register_frame(self)
        controls = tk.Frame(self, bg=self.app.current_theme()["window_bg"])
        controls.pack(side=tk.TOP, fill=tk.X)
        self.app.register_frame(controls)
        for column in range(12):
            controls.grid_columnconfigure(column, weight=1)
        self.crystal_combo = self._combo(controls, "Crystal", self.crystal_var, self.app.crystal_options(), 0, 0, width=18)
        self._entry(controls, "Zone", self.zone_var, 0, 2, width=9)
        self._entry(controls, "Plane", self.plane_var, 0, 4, width=9)
        self._entry(controls, "Vector", self.vector_var, 0, 6, width=9)
        self._entry(controls, "Rotation", self.rotation_var, 0, 8, width=9)
        self._combo(
            controls,
            "Color",
            self.diff_color_var,
            DIFFRACTION_COLOR_OPTIONS,
            0,
            10,
            width=14,
            readonly=False,
        )

        buttons = tk.Frame(self, bg=self.app.current_theme()["window_bg"])
        buttons.pack(side=tk.TOP, fill=tk.X, pady=(1, 1))
        self.app.register_frame(buttons)
        ttk.Button(buttons, text="Apply", command=lambda: self.app.apply_panel_settings(self.state.panel_id)).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(buttons, text="Sync view", command=lambda: self.app.sync_panel_from_axis(self.state.panel_id)).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(buttons, text="Reset view", command=lambda: self.app.reset_panel_view(self.state.panel_id)).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(buttons, text="Crystal PNG", command=lambda: self.app.save_panel_image(self.state.panel_id, "crystal")).pack(
            side=tk.LEFT, padx=(8, 4)
        )
        ttk.Button(
            buttons,
            text="Diffraction PNG",
            command=lambda: self.app.save_panel_image(self.state.panel_id, "diffraction"),
        ).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(
            buttons,
            text="Edit crystal",
            command=lambda: self.app.open_crystal_builder(
                self.column_index,
                crystal_name=self.state.crystal,
                mode="edit",
            ),
        ).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(buttons, text="Load CIF", command=lambda: self.app.load_cif_file(self.column_index)).pack(side=tk.RIGHT)

        self.visual_frame = tk.Frame(self, bg=self.app.current_theme()["window_bg"])
        self.visual_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.app.register_frame(self.visual_frame)
        self.visual_frame.grid_columnconfigure(0, weight=1)
        self.visual_frame.grid_columnconfigure(1, weight=1)
        self.visual_frame.grid_rowconfigure(0, weight=1)

        face = self.app.current_theme()["window_bg"]
        metrics = self.app.layout_metrics
        ordinary_figsize = figure_size_from_pixels(metrics.ordinary_canvas_width, metrics.ordinary_canvas_height)
        self.crystal_fig = Figure(figsize=ordinary_figsize, dpi=FIGURE_DPI, facecolor=face)
        self.crystal_ax = self.crystal_fig.add_subplot(111, projection="3d")
        self.crystal_ax.set_proj_type("ortho")
        self.crystal_canvas = FigureCanvasTkAgg(self.crystal_fig, master=self.visual_frame)
        self.crystal_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew", padx=0)
        self.crystal_canvas.mpl_connect("button_press_event", lambda event: self.app.on_mouse_press(self.state.panel_id, event))
        self.crystal_canvas.mpl_connect("motion_notify_event", lambda event: self.app.on_mouse_motion(self.state.panel_id, event))
        self.crystal_canvas.mpl_connect("button_release_event", lambda event: self.app.on_mouse_release(self.state.panel_id, event))
        self.crystal_canvas.mpl_connect("scroll_event", lambda event: self.app.on_mouse_scroll(self.state.panel_id, event))

        self.diffraction_fig = Figure(figsize=ordinary_figsize, dpi=FIGURE_DPI, facecolor=face)
        self.diffraction_ax = self.diffraction_fig.add_subplot(111)
        self.diffraction_canvas = FigureCanvasTkAgg(self.diffraction_fig, master=self.visual_frame)
        self.diffraction_canvas.get_tk_widget().grid(row=0, column=1, sticky="nsew", padx=0)
        self.apply_layout_metrics(redraw=False)

        if self.crystal_combo is not None:
            self.crystal_combo.bind("<<ComboboxSelected>>", lambda _event: self.app.on_crystal_selected(self.column_index))
        for variable in (self.zone_var, self.plane_var, self.vector_var, self.rotation_var):
            variable.trace_add("write", lambda *_args, panel_id=self.state.panel_id: self.app.schedule_panel_apply(panel_id))
        self.diff_color_var.trace_add(
            "write",
            lambda *_args, panel_id=self.state.panel_id: self.app.on_panel_color_changed(panel_id),
        )
        self.bind_all("<Return>", self.app.apply_all_panels)

    def _label(self, parent: tk.Frame, text: str, row: int, column: int) -> None:
        label = tk.Label(parent, text=text, bg=self.app.current_theme()["window_bg"], fg=self.app.current_theme()["label"])
        label.grid(row=row, column=column, sticky="e", padx=(0, 3), pady=1)
        self.app.register_label(label)

    def _entry(self, parent: tk.Frame, text: str, variable: tk.StringVar, row: int, column: int, width: int) -> ttk.Entry:
        self._label(parent, text, row, column)
        entry = ttk.Entry(parent, textvariable=variable, width=width, style="CrysDis.TEntry")
        entry.grid(row=row, column=column + 1, sticky="ew", padx=(0, 5), pady=1)
        return entry

    def _combo(
        self,
        parent: tk.Frame,
        text: str,
        variable: tk.StringVar,
        values: tuple[str, ...] | list[str],
        row: int,
        column: int,
        width: int,
        readonly: bool = True,
    ) -> ttk.Combobox:
        self._label(parent, text, row, column)
        combo = ttk.Combobox(
            parent,
            textvariable=variable,
            values=values,
            state="readonly" if readonly else "normal",
            width=width,
            style="CrysDis.TCombobox",
        )
        combo.grid(row=row, column=column + 1, sticky="ew", padx=(0, 5), pady=1)
        return combo

    def refresh_options(self) -> None:
        if self.crystal_combo is not None:
            self.crystal_combo.configure(values=self.app.crystal_options())

    def apply_layout_metrics(self, redraw: bool = True) -> None:
        metrics = self.app.layout_metrics
        face = self.app.current_theme()["window_bg"]
        for figure, canvas in (
            (self.crystal_fig, self.crystal_canvas),
            (self.diffraction_fig, self.diffraction_canvas),
        ):
            figure.set_size_inches(
                *figure_size_from_pixels(metrics.ordinary_canvas_width, metrics.ordinary_canvas_height),
                forward=True,
            )
            widget = canvas.get_tk_widget()
            widget.configure(
                width=metrics.ordinary_canvas_width,
                height=metrics.ordinary_canvas_height,
                bg=face,
                highlightbackground=face,
                highlightthickness=0,
                borderwidth=0,
            )
            if redraw:
                canvas.draw_idle()

    def sync_state_from_controls(self) -> None:
        self.state.crystal = self.crystal_var.get()
        self.state.zone_text = self.zone_var.get()
        self.state.plane_text = self.plane_var.get()
        self.state.vector_text = self.vector_var.get()
        self.state.rotation_text = self.rotation_var.get()
        self.state.diffraction_color = self.diff_color_var.get().strip()

    def set_controls_from_state(self) -> None:
        self.crystal_var.set(self.state.crystal)
        self.zone_var.set(self.state.zone_text)
        self.plane_var.set(self.state.plane_text)
        self.vector_var.set(self.state.vector_text)
        self.rotation_var.set(self.state.rotation_text)
        if self.state.diffraction_color:
            self.diff_color_var.set(self.app.display_color_name(self.state.diffraction_color))

    def apply_theme(self) -> None:
        theme = self.app.current_theme()
        self.configure(bg=theme["window_bg"], fg=theme["title"])
        for fig in (self.crystal_fig, self.diffraction_fig):
            fig.set_facecolor(theme["window_bg"])
        for canvas in (self.crystal_canvas, self.diffraction_canvas):
            canvas.get_tk_widget().configure(bg=theme["window_bg"], highlightbackground=theme["window_bg"])


class ComboPanelFrame(tk.LabelFrame):
    def __init__(self, app: "CrystalDiffractionSimulator", state: ComboPanelState):
        theme = app.current_theme()
        super().__init__(
            app.panels_parent,
            text=f"Combo C{state.combo_id}",
            bg=theme["window_bg"],
            fg=theme["title"],
            padx=1,
            pady=1,
        )
        self.app = app
        self.state = state
        self.source_var = tk.StringVar()
        self.bind_var = tk.BooleanVar(value=state.bind_motion)
        self._source_labels: dict[str, int] = {}
        self.body: tk.Frame | None = None
        self.legend_frame: tk.Frame | None = None
        self._last_legend_entries: list[tuple[str, str]] = []
        self._build()

    def _build(self) -> None:
        self.app.register_frame(self)
        toolbar = tk.Frame(self, bg=self.app.current_theme()["window_bg"])
        toolbar.pack(side=tk.TOP, fill=tk.X, pady=(0, 2))
        self.app.register_frame(toolbar)
        self.source_combo = ttk.Combobox(
            toolbar,
            textvariable=self.source_var,
            state="readonly",
            width=22,
            style="CrysDis.TCombobox",
        )
        self.source_combo.pack(side=tk.LEFT, padx=(0, 4))
        self.source_combo.bind("<<ComboboxSelected>>", lambda _event: self.on_source_selected())
        ttk.Button(toolbar, text="Add", command=self.add_selected_source).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(toolbar, text="Remove", command=self.remove_selected_source).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(toolbar, text="Move up", command=lambda: self.move_selected_source(-1)).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(toolbar, text="Move down", command=lambda: self.move_selected_source(1)).pack(side=tk.LEFT, padx=(0, 6))
        bind = tk.Checkbutton(
            toolbar,
            text="Bind crystal motion",
            variable=self.bind_var,
            command=self.on_bind_changed,
            bg=self.app.current_theme()["window_bg"],
            fg=self.app.current_theme()["label"],
            selectcolor=self.app.current_theme()["axis_bg"],
            activebackground=self.app.current_theme()["window_bg"],
            activeforeground=self.app.current_theme()["label"],
        )
        bind.pack(side=tk.LEFT, padx=(0, 6))
        self.app.register_checkbutton(bind)
        ttk.Button(toolbar, text="Combo PNG", command=lambda: self.app.save_combo_image(self.state.combo_id)).pack(side=tk.RIGHT)

        metrics = self.app.layout_metrics
        self.body = tk.Frame(self, bg=self.app.current_theme()["window_bg"])
        self.body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.app.register_frame(self.body)
        self.body.grid_columnconfigure(0, minsize=metrics.combo_source_width)
        self.body.grid_columnconfigure(1, minsize=metrics.combo_canvas_width, weight=1)
        self.body.grid_columnconfigure(2, minsize=metrics.combo_legend_width)
        self.body.grid_rowconfigure(0, minsize=metrics.combo_canvas_height, weight=1)
        self.source_list = tk.Listbox(self.body, height=8, exportselection=False)
        self.app.configure_listbox_theme(self.source_list)
        self.source_list.grid(row=0, column=0, sticky="nsew", padx=(0, 2))
        self.source_list.bind("<<ListboxSelect>>", lambda _event: self.on_list_source_selected())
        visual = tk.Frame(self.body, bg=self.app.current_theme()["window_bg"])
        visual.grid(row=0, column=1, sticky="nsew")
        self.app.register_frame(visual)
        visual.grid_columnconfigure(0, weight=1)
        visual.grid_rowconfigure(0, weight=1)
        self.diffraction_fig = Figure(
            figsize=figure_size_from_pixels(metrics.combo_canvas_width, metrics.combo_canvas_height),
            dpi=FIGURE_DPI,
            facecolor=self.app.current_theme()["window_bg"],
        )
        self.diffraction_ax = self.diffraction_fig.add_subplot(111)
        self.diffraction_canvas = FigureCanvasTkAgg(self.diffraction_fig, master=visual)
        self.diffraction_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        self.legend_frame = tk.Frame(self.body, bg=self.app.current_theme()["window_bg"])
        self.legend_frame.grid(row=0, column=2, sticky="nsew", padx=(4, 0))
        self.legend_frame.grid_propagate(False)
        self.apply_layout_metrics(redraw=False)
        self.refresh()

    def source_options(self) -> dict[str, int]:
        options = {}
        for state in self.app.states:
            label = f"Panel {state.panel_id}: {state.crystal}"
            options[label] = state.panel_id
        return options

    def refresh(self) -> None:
        self.app.repair_combo_sources(self.state)
        self._source_labels = self.source_options()
        labels = list(self._source_labels)
        self.source_combo.configure(values=labels)
        selected_id = self.state.selected_panel_id
        selected_label = next((label for label, panel_id in self._source_labels.items() if panel_id == selected_id), labels[0] if labels else "")
        self.source_var.set(selected_label)
        self.source_list.delete(0, tk.END)
        for panel_id in self.state.source_panel_ids:
            source = self.app.panel_state_by_id(panel_id)
            if source is None:
                continue
            self.source_list.insert(tk.END, f"Panel {source.panel_id}  {source.crystal}  zone {source.zone_text or 'free'}")
        self.bind_var.set(self.state.bind_motion)
        self.app.draw_combo_diffraction(self.state.combo_id)

    def on_source_selected(self) -> None:
        self.state.selected_panel_id = self._source_labels.get(self.source_var.get())

    def on_list_source_selected(self) -> None:
        panel_id = self.selected_list_panel_id()
        if panel_id is not None:
            self.state.selected_panel_id = panel_id

    def selected_list_panel_id(self) -> int | None:
        selection = self.source_list.curselection()
        if not selection:
            return None
        index = int(selection[0])
        if 0 <= index < len(self.state.source_panel_ids):
            return self.state.source_panel_ids[index]
        return None

    def add_selected_source(self) -> None:
        self.on_source_selected()
        if self.state.selected_panel_id is None:
            return
        if self.state.selected_panel_id not in self.state.source_panel_ids:
            self.state.source_panel_ids.append(self.state.selected_panel_id)
        self.refresh()
        self.app.status_var.set(f"Combo C{self.state.combo_id}: updated sources")

    def remove_selected_source(self) -> None:
        selected = self.selected_list_panel_id()
        if selected is None:
            self.on_source_selected()
            selected = self.state.selected_panel_id
        if selected in self.state.source_panel_ids:
            self.state.source_panel_ids = [panel_id for panel_id in self.state.source_panel_ids if panel_id != selected]
        self.refresh()
        self.app.status_var.set(f"Combo C{self.state.combo_id}: updated sources")

    def move_selected_source(self, direction: int) -> None:
        selected = self.selected_list_panel_id()
        if selected is None:
            self.on_source_selected()
            selected = self.state.selected_panel_id
        if selected is None:
            return
        try:
            index = self.state.source_panel_ids.index(selected)
        except ValueError:
            return
        new_index = min(max(index + int(direction), 0), len(self.state.source_panel_ids) - 1)
        if new_index == index:
            return
        self.state.source_panel_ids[index], self.state.source_panel_ids[new_index] = (
            self.state.source_panel_ids[new_index],
            self.state.source_panel_ids[index],
        )
        self.refresh()
        self.source_list.selection_set(new_index)
        self.source_list.activate(new_index)
        self.app.status_var.set(f"Combo C{self.state.combo_id}: reordered sources")

    def on_bind_changed(self) -> None:
        self.state.bind_motion = bool(self.bind_var.get())
        state = "enabled" if self.state.bind_motion else "disabled"
        self.app.status_var.set(f"Combo C{self.state.combo_id}: bind crystal motion {state}")

    def draw_legend(self, entries: list[tuple[str, str]]) -> None:
        if self.legend_frame is None:
            return
        self._last_legend_entries = list(entries)
        theme = self.app.current_theme()
        for child in self.legend_frame.winfo_children():
            child.destroy()
        wraplength = max(self.app.layout_metrics.combo_legend_width - 30, 80)
        if not entries:
            label = tk.Label(
                self.legend_frame,
                text="No source\nreflections",
                bg=theme["window_bg"],
                fg=theme["status"],
                anchor="nw",
                justify=tk.LEFT,
                wraplength=wraplength,
            )
            label.pack(side=tk.TOP, fill=tk.X, anchor="nw", pady=(3, 0))
        else:
            for index, (label, color) in enumerate(entries[:8]):
                row = tk.Frame(self.legend_frame, bg=theme["window_bg"])
                row.pack(side=tk.TOP, fill=tk.X, anchor="nw", pady=(3 if index == 0 else 2, 0))
                marker = tk.Canvas(
                    row,
                    width=16,
                    height=16,
                    bg=theme["window_bg"],
                    highlightthickness=0,
                    borderwidth=0,
                )
                marker.create_oval(4, 4, 12, 12, fill=color, outline=color)
                marker.pack(side=tk.LEFT, padx=(0, 5), pady=(1, 0))
                text = tk.Label(
                    row,
                    text=label,
                    bg=theme["window_bg"],
                    fg=theme["title"],
                    anchor="w",
                    justify=tk.LEFT,
                    wraplength=wraplength,
                )
                text.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def apply_layout_metrics(self, redraw: bool = True) -> None:
        metrics = self.app.layout_metrics
        theme = self.app.current_theme()
        if self.body is not None:
            self.body.grid_columnconfigure(0, minsize=metrics.combo_source_width)
            self.body.grid_columnconfigure(1, minsize=metrics.combo_canvas_width, weight=1)
            self.body.grid_columnconfigure(2, minsize=metrics.combo_legend_width)
            self.body.grid_rowconfigure(0, minsize=metrics.combo_canvas_height, weight=1)
        self.diffraction_fig.set_size_inches(
            *figure_size_from_pixels(metrics.combo_canvas_width, metrics.combo_canvas_height),
            forward=True,
        )
        widget = self.diffraction_canvas.get_tk_widget()
        widget.configure(
            width=metrics.combo_canvas_width,
            height=metrics.combo_canvas_height,
            bg=theme["window_bg"],
            highlightbackground=theme["window_bg"],
            highlightthickness=0,
            borderwidth=0,
        )
        if self.legend_frame is not None:
            self.legend_frame.configure(
                width=metrics.combo_legend_width,
                height=metrics.combo_canvas_height,
                bg=theme["window_bg"],
            )
            self.draw_legend(self._last_legend_entries)
        if redraw:
            self.diffraction_canvas.draw_idle()

    def apply_theme(self) -> None:
        theme = self.app.current_theme()
        self.configure(bg=theme["window_bg"], fg=theme["title"])
        self.app.configure_listbox_theme(self.source_list)
        if self.legend_frame is not None:
            self.legend_frame.configure(bg=theme["window_bg"])
            self.draw_legend(self._last_legend_entries)
        self.diffraction_fig.set_facecolor(theme["window_bg"])
        self.diffraction_canvas.get_tk_widget().configure(bg=theme["window_bg"], highlightbackground=theme["window_bg"])


class CrystalDiffractionSimulator(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CrysDiS tkinter")
        self._app_icon_image: tk.PhotoImage | None = None
        self.set_window_icon()
        self.minsize(1120, 720)
        self.set_initial_window_geometry()

        self.library = CrystalLibrary()
        self.model_cache: dict[str, CrystalModel] = {}
        self.reciprocal_cache: dict[tuple[str, int], tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        self.spot_cache: dict[tuple[Any, ...], np.ndarray] = {}
        self.diffraction_cmaps: dict[str, LinearSegmentedColormap] = {}
        self.states: list[PanelState] = []
        self.combo_states: list[ComboPanelState] = []
        self.ordinary_panels: dict[int, OrdinaryPanelFrame] = {}
        self.combo_panels: dict[int, ComboPanelFrame] = {}
        self.controls: list[dict[str, tk.StringVar]] = []
        self.crystal_combos: list[ttk.Combobox] = []
        self.themed_frames: list[tk.Widget] = []
        self.themed_labels: list[tk.Label] = []
        self.themed_checkbuttons: list[tk.Checkbutton] = []
        self.plane_colors = PLANE_COLORS.copy()
        self.vector_colors = VECTOR_COLORS.copy()
        self._pending_apply_jobs: dict[int, str] = {}
        self._pending_diffraction_jobs: dict[int, str] = {}
        self._pending_combo_jobs: dict[int, str] = {}
        self._drag_panel_id: int | None = None
        self._drag_old_view: np.ndarray | None = None
        self._drag_old_roll = 0.0
        self._is_propagating_motion = False
        self._updating_color_controls = False

        self.theme_var = tk.StringVar(value="Light")
        self.ttk_style = ttk.Style(self)
        try:
            self.ttk_style.theme_use("clam")
        except tk.TclError:
            pass
        self.configure_ttk_theme()
        self.method_var = tk.StringVar(value=SIMULATION_METHOD_PYMATGEN if PYMATGEN_AVAILABLE else SIMULATION_METHOD_EWALD)
        self.voltage_var = tk.StringVar(value=f"{DEFAULT_VOLTAGE_KV:g}")
        self.thickness_var = tk.StringVar(value=f"{DEFAULT_THICKNESS_NM:g}")
        self.max_hkl_var = tk.StringVar(value=str(DEFAULT_MAX_HKL))
        self.camera_length_var = tk.StringVar(value=f"{DEFAULT_CAMERA_LENGTH_MM:g} mm")
        self.spot_threshold_var = tk.StringVar(value=f"{DEFAULT_SPOT_INTENSITY_THRESHOLD:g}")
        self.spot_size_scaling_var = tk.StringVar(value=f"{DEFAULT_SPOT_SIZE_SCALING:g}")
        self.intensity_compression_var = tk.StringVar(value=f"{DEFAULT_INTENSITY_COMPRESSION_FACTOR:g}")
        self.show_indices_var = tk.BooleanVar(value=False)
        self.show_annotations_var = tk.BooleanVar(value=True)
        self.show_real_scale_bar_var = tk.BooleanVar(value=False)
        self.show_reciprocal_scale_bar_var = tk.BooleanVar(value=True)
        self.show_zone_axis_var = tk.BooleanVar(value=False)
        self.hex_four_index_var = tk.BooleanVar(value=True)
        self.auto_sync_var = tk.BooleanVar(value=False)
        self.performance_mode_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Ready")
        self.status_history: list[str] = ["Ready"]
        self.advanced_log_text: tk.Text | None = None
        self._last_logged_status = "Ready"
        self.status_var.trace_add("write", self.on_status_changed)
        self.status_label: tk.Label | None = None
        self.theme_button: ttk.Button | None = None
        self.intro_dialog: tk.Toplevel | None = None
        self.advanced_dialog: tk.Toplevel | None = None
        self.crystal_list_dialog: tk.Toplevel | None = None
        self.crystal_listbox: tk.Listbox | None = None
        self.scrollable: ScrollableFrame | None = None
        self.panels_parent: tk.Frame | None = None
        self.single_panel_mode = False
        self.layout_metrics = LayoutMetrics()
        self._layout_resize_job: str | None = None

        self.bind("<Configure>", self.on_root_configure, add="+")
        self.rebuild_diffraction_cmaps()
        self.show_landing()

    def set_window_icon(self) -> None:
        if not APP_ICON_PATH.exists():
            return
        try:
            self._app_icon_image = tk.PhotoImage(file=str(APP_ICON_PATH))
            self.iconphoto(True, self._app_icon_image)
        except tk.TclError:
            self._app_icon_image = None

    def set_initial_window_geometry(self) -> None:
        screen_width = max(int(self.winfo_screenwidth()), 1120)
        screen_height = max(int(self.winfo_screenheight()), 720)
        width = min(screen_width, max(1120, screen_width - WINDOW_WIDTH_RESERVE_PX))
        height = min(screen_height, max(720, screen_height - WINDOW_HEIGHT_RESERVE_PX))
        x = max((screen_width - width) // 2, 0)
        y = 0
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.after(80, self.maximize_startup_window)

    def maximize_startup_window(self) -> None:
        # Different desktop/window managers support different Tk maximize APIs.
        for action in (
            lambda: self.state("zoomed"),
            lambda: self.attributes("-zoomed", True),
        ):
            try:
                action()
            except tk.TclError:
                continue
        if getattr(self, "panels_parent", None) is not None:
            self.after(120, self.apply_responsive_layout)

    def on_root_configure(self, event) -> None:
        if event.widget is not self or self.panels_parent is None:
            return
        if not self.ordinary_panels and not self.combo_panels:
            return
        if self._layout_resize_job is not None:
            try:
                self.after_cancel(self._layout_resize_job)
            except tk.TclError:
                pass
        self._layout_resize_job = self.after(180, self.apply_responsive_layout)

    def layout_window_size(self) -> tuple[int, int]:
        self.update_idletasks()
        screen_width = max(int(self.winfo_screenwidth()), 1120)
        screen_height = max(int(self.winfo_screenheight()), 720)
        fallback_width = min(screen_width, max(1120, screen_width - WINDOW_WIDTH_RESERVE_PX))
        fallback_height = min(screen_height, max(720, screen_height - WINDOW_HEIGHT_RESERVE_PX))
        width = int(self.winfo_width() or fallback_width)
        height = int(self.winfo_height() or fallback_height)
        if width < 800:
            width = fallback_width
        if height < 500:
            height = fallback_height
        width = min(width, screen_width)
        height = min(height, screen_height)
        return max(width, 1120), max(height, 640)

    def layout_item_row_count(self, ordinary_count: int, combo_count: int) -> int:
        item_index = 0
        single_panel = ordinary_count == 1
        for _index in range(ordinary_count):
            columnspan = 2 if single_panel and item_index == 0 else 1
            item_index += columnspan
        item_index += max(combo_count, 0)
        return max(1, math.ceil(item_index / 2))

    def compute_layout_metrics(self, ordinary_count: int, combo_count: int) -> LayoutMetrics:
        window_width, window_height = self.layout_window_size()
        row_count = self.layout_item_row_count(ordinary_count, combo_count)
        viewport_height = 0
        if self.scrollable is not None:
            self.update_idletasks()
            viewport_height = int(self.scrollable.canvas.winfo_height() or 0)
        available_height = viewport_height if viewport_height >= 360 else max(360, window_height - MAIN_UI_CHROME_PX)
        row_gap = 2 * max(row_count - 1, 0)
        regular_height = (available_height - row_count * PANEL_ROW_CHROME_PX - row_gap) // row_count
        regular_height = max(MIN_REGULAR_CANVAS_HEIGHT_PX, min(MAX_REGULAR_CANVAS_HEIGHT_PX, regular_height))

        panel_width = max(540, (window_width - 10) // 2)
        regular_width = max(MIN_REGULAR_CANVAS_WIDTH_PX, (panel_width - 8) // 2)
        single_width = max(MIN_SINGLE_CANVAS_WIDTH_PX, (window_width - 12) // 2)
        single_height = regular_height
        if ordinary_count == 1 and combo_count == 0:
            single_height = min(
                MAX_SINGLE_CANVAS_HEIGHT_PX,
                max(
                    MIN_SINGLE_CANVAS_HEIGHT_PX,
                    min(available_height - SINGLE_PANEL_CHROME_PX, int(single_width * 0.82)),
                ),
            )

        combo_source_width = max(MIN_COMBO_SOURCE_WIDTH_PX, min(220, int(panel_width * 0.24)))
        combo_legend_width = max(MIN_COMBO_LEGEND_WIDTH_PX, min(155, int(panel_width * 0.16)))
        combo_width = max(
            MIN_COMBO_CANVAS_WIDTH_PX,
            panel_width - combo_source_width - combo_legend_width - 14,
        )
        return LayoutMetrics(
            ordinary_canvas_width=single_width if ordinary_count == 1 and combo_count == 0 else regular_width,
            ordinary_canvas_height=single_height if ordinary_count == 1 and combo_count == 0 else regular_height,
            combo_canvas_width=combo_width,
            combo_canvas_height=regular_height,
            combo_source_width=combo_source_width,
            combo_legend_width=combo_legend_width,
        )

    def apply_responsive_layout(self) -> None:
        self._layout_resize_job = None
        if self.panels_parent is None:
            return
        metrics = self.compute_layout_metrics(len(self.states), len(self.combo_states))
        if metrics == self.layout_metrics:
            if self.scrollable is not None:
                self.scrollable.after_idle(self.scrollable._sync_scrollbar_visibility)
            return
        self.layout_metrics = metrics
        for panel in self.ordinary_panels.values():
            panel.apply_layout_metrics()
        for combo in self.combo_panels.values():
            combo.apply_layout_metrics()
        if self.scrollable is not None:
            self.scrollable.after_idle(self.scrollable._sync_scrollbar_visibility)

    def on_status_changed(self, *_args) -> None:
        message = str(self.status_var.get() or "").strip() or "Ready"
        if message == self._last_logged_status:
            return
        self._last_logged_status = message
        self.status_history.append(message)
        self.status_history = self.status_history[-80:]
        self.refresh_advanced_log()

    def refresh_advanced_log(self) -> None:
        if self.advanced_log_text is None:
            return
        try:
            if not self.advanced_log_text.winfo_exists():
                return
            self.advanced_log_text.configure(state=tk.NORMAL)
            self.advanced_log_text.delete("1.0", tk.END)
            self.advanced_log_text.insert(tk.END, "\n".join(self.status_history[-20:]))
            self.advanced_log_text.configure(state=tk.DISABLED)
            self.advanced_log_text.see(tk.END)
        except tk.TclError:
            self.advanced_log_text = None

    def clear_window(self) -> None:
        if self._layout_resize_job is not None:
            try:
                self.after_cancel(self._layout_resize_job)
            except tk.TclError:
                pass
            self._layout_resize_job = None
        for child in self.winfo_children():
            child.destroy()
        self.ordinary_panels.clear()
        self.combo_panels.clear()
        self.controls.clear()
        self.crystal_combos.clear()
        self.themed_frames.clear()
        self.themed_labels.clear()
        self.themed_checkbuttons.clear()
        self.scrollable = None
        self.panels_parent = None
        self.config(menu="")

    def show_landing(self) -> None:
        self.clear_window()
        self.configure(bg=self.current_theme()["window_bg"])
        LandingFrame(self).pack(fill=tk.BOTH, expand=True)

    def start_layout(self, ordinary_count: int, combo_count: int) -> None:
        ordinary_count = min(max(int(ordinary_count or 3), 1), MAX_ORDINARY_PANELS)
        combo_count = min(max(int(combo_count or 0), 0), MAX_COMBO_PANELS)
        self.single_panel_mode = ordinary_count == 1
        self.layout_metrics = self.compute_layout_metrics(ordinary_count, combo_count)
        defaults = [("FCC", "100"), ("BCC", "100"), ("HCP", "100")]
        self.states = []
        for index in range(ordinary_count):
            crystal, zone = defaults[index % len(defaults)]
            color = self.default_diffraction_color_for_model(self.model_for(crystal))
            self.states.append(
                PanelState(
                    panel_id=index + 1,
                    crystal=crystal,
                    zone_text=zone,
                    plane_text="",
                    vector_text="",
                    diffraction_color=color,
                )
            )
        self.combo_states = []
        for index in range(combo_count):
            source_ids = [state.panel_id for state in self.states[: min(3, len(self.states))]]
            self.combo_states.append(
                ComboPanelState(
                    combo_id=index + 1,
                    source_panel_ids=source_ids,
                    selected_panel_id=source_ids[0] if source_ids else None,
                )
            )
        self._build_main_ui()
        self.after_idle(self.apply_responsive_layout)
        for state in self.states:
            self.apply_panel_settings(state.panel_id, initial=True)
        self.refresh_combo_panels()
        self.status_var.set(f"Layout ready: {ordinary_count} ordinary panel(s), {combo_count} combo panel(s)")

    def _build_main_ui(self) -> None:
        self.clear_window()
        theme = self.current_theme()
        self.configure(bg=theme["window_bg"])
        self._build_menu()
        self._build_toolbar()
        self.scrollable = ScrollableFrame(self, self)
        self.scrollable.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=2, pady=(1, 1))
        self.panels_parent = self.scrollable.inner
        self.ordinary_panels.clear()
        self.combo_panels.clear()
        self.controls.clear()
        self.crystal_combos.clear()

        item_index = 0
        for index, state in enumerate(self.states):
            panel = OrdinaryPanelFrame(self, state, index)
            row, column = divmod(item_index, 2)
            columnspan = 2 if self.single_panel_mode and item_index == 0 else 1
            panel.grid(row=row, column=column, columnspan=columnspan, sticky="nsew", padx=1, pady=1)
            self.panels_parent.grid_rowconfigure(row, weight=1)
            self.ordinary_panels[state.panel_id] = panel
            self.controls.append(
                {
                    "crystal": panel.crystal_var,
                    "zone": panel.zone_var,
                    "plane": panel.plane_var,
                    "vector": panel.vector_var,
                    "rotation": panel.rotation_var,
                    "color": panel.diff_color_var,
                }
            )
            if panel.crystal_combo is not None:
                self.crystal_combos.append(panel.crystal_combo)
            item_index += columnspan

        for state in self.combo_states:
            combo = ComboPanelFrame(self, state)
            row, column = divmod(item_index, 2)
            combo.grid(row=row, column=column, sticky="nsew", padx=1, pady=1)
            self.panels_parent.grid_rowconfigure(row, weight=1)
            self.combo_panels[state.combo_id] = combo
            item_index += 1
        self.panels_parent.grid_columnconfigure(0, weight=1, uniform="panel_column")
        self.panels_parent.grid_columnconfigure(1, weight=1, uniform="panel_column")

        self.status_label = tk.Label(
            self,
            textvariable=self.status_var,
            anchor="w",
            bg=theme["window_bg"],
            fg=theme["status"],
            padx=6,
            pady=2,
        )
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)
        self.register_label(self.status_label, status=True)

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="New layout", command=self.show_landing)
        file_menu.add_command(label="Load CIF into panel 1", command=lambda: self.load_cif_file(0))
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menu.add_cascade(label="File", menu=file_menu)
        self.config(menu=menu)

    def _build_toolbar(self) -> None:
        theme = self.current_theme()
        toolbar = tk.Frame(self, bg=theme["window_bg"])
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=4, pady=(4, 1))
        self.register_frame(toolbar)
        ttk.Button(toolbar, text="Intro", command=self.open_intro_dialog).pack(side=tk.LEFT, padx=(0, 6))

        for text, variable, command in (
            ("Show current zone", self.show_zone_axis_var, self.refresh_diffractions),
            ("Show indices", self.show_indices_var, self.refresh_diffractions),
            ("Crystal annotations", self.show_annotations_var, self.redraw_all_crystals),
            ("Real space scale bar", self.show_real_scale_bar_var, self.redraw_all_crystals),
            ("Reciprocal space scale bar", self.show_reciprocal_scale_bar_var, self.refresh_diffractions),
        ):
            check = tk.Checkbutton(
                toolbar,
                text=text,
                variable=variable,
                command=command,
                bg=theme["window_bg"],
                fg=theme["label"],
                selectcolor=theme["axis_bg"],
                activebackground=theme["window_bg"],
                activeforeground=theme["label"],
            )
            check.pack(side=tk.LEFT, padx=(2, 5))
            self.register_checkbutton(check)

        self.theme_button = ttk.Button(
            toolbar,
            text="Dark background" if self.theme_var.get() == "Light" else "Light background",
            command=self.toggle_theme,
        )
        self.theme_button.pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(toolbar, text="New layout", command=self.show_landing).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(toolbar, text="Advanced", command=self.open_advanced_settings).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(toolbar, text="Crystal list", command=self.open_crystal_list).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(toolbar, text="Crystal builder", command=lambda: self.open_crystal_builder(0, mode="new")).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(toolbar, text="Load CIF", command=lambda: self.load_cif_file(0)).pack(side=tk.RIGHT, padx=(4, 0))

    def _toolbar_entry(self, parent: tk.Frame, label: str, variable: tk.StringVar, width: int, callback) -> None:
        self._add_toolbar_label(parent, label)
        entry = ttk.Entry(parent, textvariable=variable, width=width)
        entry.pack(side=tk.LEFT, padx=(5, 12))
        entry.bind("<Return>", callback)
        entry.bind("<FocusOut>", callback)

    def open_intro_dialog(self) -> None:
        if self.intro_dialog is not None and self.intro_dialog.winfo_exists():
            self.intro_dialog.lift()
            return
        theme = self.current_theme()
        dialog = tk.Toplevel(self)
        self.intro_dialog = dialog
        dialog.title("CrysDiS Intro")
        dialog.geometry("760x620+140+100")
        dialog.transient(self)
        dialog.configure(bg=theme["window_bg"])

        outer = tk.Frame(dialog, bg=theme["window_bg"], padx=22, pady=18)
        outer.pack(fill=tk.BOTH, expand=True)
        title = tk.Label(
            outer,
            text="Welcome to CrysDiS",
            bg=theme["window_bg"],
            fg=theme["title"],
            font=("TkDefaultFont", 18, "bold"),
            anchor="w",
        )
        title.pack(fill=tk.X, pady=(0, 10))

        text_frame = tk.Frame(outer, bg=theme["axis_bg"])
        text_frame.pack(fill=tk.BOTH, expand=True)
        text = tk.Text(
            text_frame,
            wrap=tk.WORD,
            bg=theme["axis_bg"],
            fg=theme["label"],
            insertbackground=theme["label"],
            relief=tk.FLAT,
            padx=14,
            pady=12,
            font=("TkDefaultFont", 12),
            height=20,
        )
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.insert(
            tk.END,
            "CrysDiS represents Crystal Diffraction Simulator, which is a handy desktop crystal/diffraction comparison tool.\n\n"
            "Basic workflow\n"
            "1. Choose one or more ordinary crystal panels on the startup screen.\n"
            "2. Pick a crystal, type a zone axis such as 001, 110, or 2-1-10, then click Apply.\n"
            "3. Rotate the 3D crystal with the mouse. Use the mouse wheel to zoom the real-space view.\n"
            "4. If Auto sync crystal/diffraction is off, click Sync view when you want the diffraction pattern to follow the current crystal view.\n\n"
            "Panel tools\n"
            "- Plane and Vector fields draw real-space overlays on the crystal view.\n"
            "- Reciprocal vectors can be entered as *100, r100, or R100; they also work as rotation axes.\n"
            "- Show current zone labels the diffraction pattern with the current viewing direction.\n"
            "- Show indices labels diffraction spots. Crystal annotations labels atoms and overlays.\n"
            "- Real space and reciprocal space scale bars can be controlled independently.\n"
            "- Crystal PNG and Diffraction PNG export the current panel with optional DPI and transparency settings.\n\n"
            "Combo panels\n"
            "- Add source panels to overlay their diffraction patterns on one canvas.\n"
            "- Select an entry in the combo list, then use Move up or Move down to control the legend and drawing order.\n"
            "- Bind crystal motion copies the master panel orientation to the selected source panels. The tkinter version uses guarded, throttled updates for stability.\n\n"
            "Crystals and CIF files\n"
            "- Load CIF imports a structure into a panel.\n"
            "- Crystal builder creates a new custom structure.\n"
            "- Crystal list lets you edit or remove saved custom structures.\n"
            "- Edited custom structures can be saved in place or saved as a new structure.\n\n"
            "Advanced settings\n"
            "- Choose the diffraction method, voltage, thickness, max HKL, camera length, spot threshold, spot size scaling, and intensity compression.\n"
            "- Pymatgen TEMCalculator is used when pymatgen is installed; otherwise CrysDiS falls back to the built-in kinematic method.\n"
            "- Delay diffraction during drag avoids expensive diffraction recalculation until mouse release.\n",
        )
        text.configure(state=tk.DISABLED)

        buttons = tk.Frame(outer, bg=theme["window_bg"])
        buttons.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(buttons, text="Close", command=dialog.destroy).pack(side=tk.RIGHT)

    def open_advanced_settings(self) -> None:
        if self.advanced_dialog is not None and self.advanced_dialog.winfo_exists():
            self.advanced_dialog.lift()
            return
        theme = self.current_theme()
        dialog = tk.Toplevel(self)
        self.advanced_dialog = dialog
        dialog.title("Advanced settings")
        dialog.geometry("720x560+160+120")
        dialog.transient(self)
        dialog.configure(bg=theme["window_bg"])
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        outer = tk.Frame(dialog, bg=theme["window_bg"], padx=14, pady=12)
        outer.pack(fill=tk.BOTH, expand=True)
        for column in range(4):
            outer.grid_columnconfigure(column, weight=1)
        outer.grid_rowconfigure(5, weight=1)

        def label(row: int, column: int, text: str) -> None:
            tk.Label(outer, text=text, bg=theme["window_bg"], fg=theme["label"]).grid(
                row=row, column=column, sticky="e", padx=(0, 6), pady=5
            )

        def entry(row: int, column: int, text: str, variable: tk.StringVar, width: int = 10) -> None:
            label(row, column, text)
            ttk.Entry(outer, textvariable=variable, width=width).grid(row=row, column=column + 1, sticky="ew", pady=5)

        label(0, 0, "Simulation method")
        ttk.Combobox(outer, textvariable=self.method_var, values=SIMULATION_METHODS, state="readonly", width=24).grid(
            row=0, column=1, sticky="ew", pady=5
        )
        label(0, 2, "Camera length")
        ttk.Combobox(outer, textvariable=self.camera_length_var, values=CAMERA_LENGTH_OPTIONS, state="readonly", width=12).grid(
            row=0, column=3, sticky="ew", pady=5
        )
        entry(1, 0, "Voltage kV", self.voltage_var)
        entry(1, 2, "Thickness nm", self.thickness_var)
        entry(2, 0, "Max hkl", self.max_hkl_var)
        entry(2, 2, "Spot threshold", self.spot_threshold_var)

        label(3, 0, "Compression")
        compression_scale = tk.Scale(
            outer,
            from_=10,
            to=150,
            orient=tk.HORIZONTAL,
            resolution=1,
            bg=theme["window_bg"],
            fg=theme["label"],
            highlightthickness=0,
            command=lambda value: self.intensity_compression_var.set(f"{float(value):.0f}"),
        )
        compression_scale.set(float(self.current_intensity_compression_factor()))
        compression_scale.grid(row=3, column=1, sticky="ew", pady=5)
        label(3, 2, "Spot size scaling")
        spot_scale = tk.Scale(
            outer,
            from_=0,
            to=1,
            orient=tk.HORIZONTAL,
            resolution=0.01,
            bg=theme["window_bg"],
            fg=theme["label"],
            highlightthickness=0,
            command=lambda value: self.spot_size_scaling_var.set(f"{float(value):.2f}"),
        )
        spot_scale.set(float(self.current_spot_size_scaling_effect()))
        spot_scale.grid(row=3, column=3, sticky="ew", pady=5)

        lower = tk.Frame(outer, bg=theme["window_bg"])
        lower.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(12, 6))
        lower.grid_columnconfigure(0, weight=1)
        lower.grid_columnconfigure(1, weight=1)
        checks = tk.Frame(lower, bg=theme["window_bg"])
        checks.grid(row=0, column=0, sticky="nw")
        for text, variable in (
            ("Use four-index basis for hexagonal systems", self.hex_four_index_var),
            ("Auto sync crystal/diffraction", self.auto_sync_var),
            ("Delay diffraction during drag", self.performance_mode_var),
        ):
            check = tk.Checkbutton(
                checks,
                text=text,
                variable=variable,
                bg=theme["window_bg"],
                fg=theme["label"],
                selectcolor=theme["axis_bg"],
                activebackground=theme["window_bg"],
                activeforeground=theme["label"],
            )
            check.pack(anchor="w", side=tk.TOP, pady=1)
            self.register_checkbutton(check)

        palette_cell = tk.Frame(lower, bg=theme["window_bg"])
        palette_cell.grid(row=0, column=1, sticky="ne")
        ttk.Button(palette_cell, text="Palette for vectors/planes", command=self.open_palette_settings).pack(anchor="ne")

        log_frame = tk.LabelFrame(
            outer,
            text="Log",
            bg=theme["window_bg"],
            fg=theme["title"],
            padx=6,
            pady=5,
        )
        log_frame.grid(row=5, column=0, columnspan=4, sticky="nsew", pady=(8, 8))
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(0, weight=1)
        self.advanced_log_text = tk.Text(
            log_frame,
            height=7,
            wrap=tk.WORD,
            relief=tk.FLAT,
            padx=8,
            pady=6,
        )
        self.advanced_log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.advanced_log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.advanced_log_text.configure(yscrollcommand=log_scroll.set)
        self.configure_textbox_theme(self.advanced_log_text)
        self.refresh_advanced_log()

        actions = tk.Frame(outer, bg=theme["window_bg"])
        actions.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(2, 0))
        ttk.Button(actions, text="Close", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(actions, text="Apply", command=self.apply_advanced_settings).pack(side=tk.RIGHT, padx=(0, 8))

    def apply_advanced_settings(self) -> None:
        self.reciprocal_cache.clear()
        self.spot_cache.clear()
        self.redraw_all()
        self.status_var.set("Advanced settings applied")

    def open_palette_settings(self) -> None:
        theme = self.current_theme()
        dialog = tk.Toplevel(self)
        dialog.title("Palette for vectors/planes")
        dialog.geometry("520x360+190+150")
        dialog.transient(self)
        dialog.configure(bg=theme["window_bg"])
        outer = tk.Frame(dialog, bg=theme["window_bg"], padx=12, pady=10)
        outer.pack(fill=tk.BOTH, expand=True)
        plane_vars = [tk.StringVar(value=self.display_color_name(color)) for color in self.plane_colors]
        vector_vars = [tk.StringVar(value=self.display_color_name(color)) for color in self.vector_colors]

        def build_column(parent: tk.Frame, title: str, variables: list[tk.StringVar]) -> None:
            tk.Label(parent, text=title, bg=theme["window_bg"], fg=theme["title"], font=("TkDefaultFont", 10, "bold")).pack(
                anchor="w", pady=(0, 6)
            )
            for index, variable in enumerate(variables, start=1):
                row = tk.Frame(parent, bg=theme["window_bg"])
                row.pack(fill=tk.X, pady=2)
                tk.Label(row, text=str(index), width=3, bg=theme["window_bg"], fg=theme["label"]).pack(side=tk.LEFT)
                ttk.Combobox(
                    row,
                    textvariable=variable,
                    values=DIFFRACTION_COLOR_OPTIONS,
                    width=14,
                ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        columns = tk.Frame(outer, bg=theme["window_bg"])
        columns.pack(fill=tk.BOTH, expand=True)
        left = tk.Frame(columns, bg=theme["window_bg"])
        right = tk.Frame(columns, bg=theme["window_bg"])
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        build_column(left, "Plane colors", plane_vars)
        build_column(right, "Vector colors", vector_vars)

        def apply_palette() -> None:
            plane_colors = [self.resolve_color(value.get()) for value in plane_vars if value.get().strip()]
            vector_colors = [self.resolve_color(value.get()) for value in vector_vars if value.get().strip()]
            if not plane_colors or not vector_colors:
                messagebox.showerror("Invalid Palette", "Keep at least one plane and vector color.", parent=dialog)
                return
            try:
                for color in plane_colors + vector_colors:
                    to_rgb(color)
            except ValueError as exc:
                messagebox.showerror("Invalid Palette", f"Invalid color: {exc}", parent=dialog)
                return
            self.plane_colors = plane_colors
            self.vector_colors = vector_colors
            self.redraw_all_crystals()
            dialog.destroy()
            self.status_var.set("Palette updated")

        buttons = tk.Frame(outer, bg=theme["window_bg"])
        buttons.pack(fill=tk.X, pady=(10, 0))
        def reset_palette() -> None:
            for variable, color in zip(plane_vars, PLANE_COLORS):
                variable.set(self.display_color_name(color))
            for variable, color in zip(vector_vars, VECTOR_COLORS):
                variable.set(self.display_color_name(color))

        ttk.Button(buttons, text="Reset", command=reset_palette).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Apply", command=apply_palette).pack(side=tk.RIGHT, padx=(0, 8))

    def _add_toolbar_label(self, parent: tk.Frame, text: str) -> None:
        label = tk.Label(parent, text=text, bg=self.current_theme()["window_bg"], fg=self.current_theme()["label"])
        label.pack(side=tk.LEFT)
        self.register_label(label)

    def register_frame(self, frame: tk.Widget) -> None:
        self.themed_frames.append(frame)

    def register_label(self, label: tk.Label, status: bool = False) -> None:
        label._crysdis_status_label = status  # type: ignore[attr-defined]
        self.themed_labels.append(label)

    def register_checkbutton(self, checkbutton: tk.Checkbutton) -> None:
        self.style_checkbutton(checkbutton)
        self.themed_checkbuttons.append(checkbutton)

    def style_checkbutton(self, checkbutton: tk.Checkbutton) -> None:
        theme = self.current_theme()
        checkbutton.configure(
            bg=theme["window_bg"],
            fg=theme["label"],
            selectcolor=theme["window_bg"],
            activebackground=theme["window_bg"],
            activeforeground=theme["label"],
            highlightthickness=0,
            highlightbackground=theme["window_bg"],
            highlightcolor=theme["window_bg"],
            borderwidth=0,
            relief=tk.FLAT,
            offrelief=tk.FLAT,
            overrelief=tk.FLAT,
        )

    def current_theme(self) -> dict[str, str]:
        return THEMES[self.theme_var.get()]

    def input_theme_colors(self) -> dict[str, str]:
        if self.theme_var.get() == "Dark":
            return {
                "field_bg": "#080A0E",
                "field_fg": "#E8EDF2",
                "select_bg": "#374151",
                "select_fg": "#FFFFFF",
                "border": "#6B7280",
            }
        return {
            "field_bg": "#FFFFFF",
            "field_fg": "#111827",
            "select_bg": "#C7D2FE",
            "select_fg": "#111827",
            "border": "#8A8A8A",
            }

    def button_theme_colors(self) -> dict[str, str]:
        if self.theme_var.get() == "Dark":
            return {
                "bg": "#1F2937",
                "active_bg": "#374151",
                "pressed_bg": "#111827",
                "fg": "#F3F4F6",
                "border": "#6B7280",
            }
        return {
            "bg": "#E5E7EB",
            "active_bg": "#F3F4F6",
            "pressed_bg": "#D1D5DB",
            "fg": "#111827",
            "border": "#8A8A8A",
        }

    def configure_ttk_theme(self) -> None:
        colors = self.input_theme_colors()
        button_colors = self.button_theme_colors()
        theme = self.current_theme()
        for style_name in ("TFrame", "CrysDis.TFrame"):
            self.ttk_style.configure(style_name, background=theme["window_bg"])
        for style_name in ("TLabel", "CrysDis.TLabel"):
            self.ttk_style.configure(style_name, background=theme["window_bg"], foreground=theme["label"])
        for style_name in ("TLabelframe", "CrysDis.TLabelframe"):
            self.ttk_style.configure(
                style_name,
                background=theme["window_bg"],
                foreground=theme["title"],
                bordercolor=colors["border"],
                lightcolor=colors["border"],
                darkcolor=colors["border"],
            )
        for style_name in ("TLabelframe.Label", "CrysDis.TLabelframe.Label"):
            self.ttk_style.configure(style_name, background=theme["window_bg"], foreground=theme["title"])
        self.ttk_style.configure(
            "Treeview",
            background=colors["field_bg"],
            fieldbackground=colors["field_bg"],
            foreground=colors["field_fg"],
            bordercolor=colors["border"],
            rowheight=22,
        )
        self.ttk_style.map(
            "Treeview",
            background=[("selected", colors["select_bg"]), ("!selected", colors["field_bg"])],
            foreground=[("selected", colors["select_fg"]), ("!selected", colors["field_fg"])],
        )
        self.ttk_style.configure(
            "Treeview.Heading",
            background=button_colors["bg"],
            foreground=button_colors["fg"],
            bordercolor=button_colors["border"],
            relief=tk.FLAT,
        )
        self.ttk_style.map(
            "Treeview.Heading",
            background=[("active", button_colors["active_bg"]), ("!active", button_colors["bg"])],
            foreground=[("!disabled", button_colors["fg"])],
        )
        for style_name in ("TEntry", "CrysDis.TEntry"):
            self.ttk_style.configure(
                style_name,
                fieldbackground=colors["field_bg"],
                foreground=colors["field_fg"],
                insertcolor=colors["field_fg"],
                bordercolor=colors["border"],
                lightcolor=colors["border"],
                darkcolor=colors["border"],
            )
            self.ttk_style.map(
                style_name,
                fieldbackground=[("disabled", colors["field_bg"]), ("readonly", colors["field_bg"]), ("!disabled", colors["field_bg"])],
                foreground=[("disabled", colors["field_fg"]), ("!disabled", colors["field_fg"])],
                selectbackground=[("!disabled", colors["select_bg"])],
                selectforeground=[("!disabled", colors["select_fg"])],
            )
        for style_name in ("TCombobox", "CrysDis.TCombobox"):
            self.ttk_style.configure(
                style_name,
                fieldbackground=colors["field_bg"],
                background=colors["field_bg"],
                foreground=colors["field_fg"],
                arrowcolor=colors["field_fg"],
                bordercolor=colors["border"],
                lightcolor=colors["border"],
                darkcolor=colors["border"],
            )
            self.ttk_style.map(
                style_name,
                fieldbackground=[("readonly", colors["field_bg"]), ("!disabled", colors["field_bg"])],
                foreground=[("readonly", colors["field_fg"]), ("!disabled", colors["field_fg"])],
                background=[("readonly", colors["field_bg"]), ("!disabled", colors["field_bg"])],
                selectbackground=[("readonly", colors["field_bg"]), ("!disabled", colors["select_bg"])],
                selectforeground=[("readonly", colors["field_fg"]), ("!disabled", colors["select_fg"])],
            )
        self.option_add("*TCombobox*Listbox.background", colors["field_bg"])
        self.option_add("*TCombobox*Listbox.foreground", colors["field_fg"])
        self.option_add("*TCombobox*Listbox.selectBackground", colors["select_bg"])
        self.option_add("*TCombobox*Listbox.selectForeground", colors["select_fg"])

        for style_name in ("TButton", "CrysDis.TButton"):
            self.ttk_style.configure(
                style_name,
                background=button_colors["bg"],
                foreground=button_colors["fg"],
                bordercolor=button_colors["border"],
                lightcolor=button_colors["border"],
                darkcolor=button_colors["border"],
                focuscolor=button_colors["border"],
                padding=(6, 3),
            )
            self.ttk_style.map(
                style_name,
                background=[
                    ("pressed", button_colors["pressed_bg"]),
                    ("active", button_colors["active_bg"]),
                    ("!disabled", button_colors["bg"]),
                ],
                foreground=[("disabled", colors["border"]), ("!disabled", button_colors["fg"])],
            )

    def configure_listbox_theme(self, listbox: tk.Listbox) -> None:
        colors = self.input_theme_colors()
        listbox.configure(
            bg=colors["field_bg"],
            fg=colors["field_fg"],
            selectbackground=colors["select_bg"],
            selectforeground=colors["select_fg"],
            highlightbackground=colors["border"],
            highlightcolor=colors["border"],
            relief=tk.SOLID,
            borderwidth=1,
        )

    def configure_textbox_theme(self, text: tk.Text) -> None:
        colors = self.input_theme_colors()
        text.configure(
            bg=colors["field_bg"],
            fg=colors["field_fg"],
            insertbackground=colors["field_fg"],
            selectbackground=colors["select_bg"],
            selectforeground=colors["select_fg"],
            highlightbackground=colors["border"],
            highlightcolor=colors["border"],
            relief=tk.SOLID,
            borderwidth=1,
        )

    def crystal_options(self) -> list[str]:
        return self.library.options()

    def display_color_name(self, value: str) -> str:
        color = str(value or "").strip()
        if not color:
            return ""
        lower = color.lower()
        if lower in NAMED_COLORS:
            return lower
        if re.match(r"^#[0-9a-fA-F]{6}$", color):
            for name, hex_color in NAMED_COLORS.items():
                if hex_color.lower() == lower:
                    return name
        return color

    def resolve_color(self, value: str, fallback: str = "#FFFFFF") -> str:
        color = str(value or "").strip()
        if not color:
            return fallback
        return NAMED_COLORS.get(color.lower(), color)

    def default_diffraction_color_for_model(self, model: CrystalModel) -> str:
        themed = DEFAULT_DIFFRACTION_COLORS_BY_THEME.get(self.theme_var.get(), {}).get(model.name)
        if themed:
            return themed
        base_color = self.resolve_color(self.style_for_model(model)["diff"], dominant_color(model.definition))
        return self.display_color_name(theme_adjusted_custom_diffraction_color(base_color, self.theme_var.get()))

    def set_panel_diffraction_color_control(self, state: PanelState, color: str, user_set: bool) -> None:
        state.diffraction_color = color
        state.diffraction_color_user_set = user_set
        panel = self.ordinary_panels.get(state.panel_id)
        if panel is None:
            return
        self._updating_color_controls = True
        try:
            panel.diff_color_var.set(self.display_color_name(color))
        finally:
            self._updating_color_controls = False

    def refresh_theme_default_diffraction_colors(self) -> None:
        for state in self.states:
            if state.diffraction_color_user_set:
                continue
            self.set_panel_diffraction_color_control(
                state,
                self.default_diffraction_color_for_model(self.model_for(state.crystal)),
                user_set=False,
            )

    def on_panel_color_changed(self, panel_id: int) -> None:
        state = self.panel_state_by_id(panel_id)
        if state is not None and not self._updating_color_controls:
            state.diffraction_color_user_set = True
        self.schedule_panel_apply(panel_id)

    def current_simulation_method(self) -> str:
        method = self.method_var.get()
        if method in SIMULATION_METHODS:
            return method
        fallback = SIMULATION_METHOD_PYMATGEN if PYMATGEN_AVAILABLE else SIMULATION_METHOD_EWALD
        self.method_var.set(fallback)
        return fallback

    def rebuild_diffraction_cmaps(self) -> None:
        theme = self.current_theme()
        self.diffraction_cmaps = {
            name: LinearSegmentedColormap.from_list(
                f"{name.lower()}_{self.theme_var.get().lower()}_diffraction",
                [theme["diff_bg"], style["diff"], "#FFFFFF"],
            )
            for name, style in CRYSTAL_STYLES.items()
        }

    def toggle_theme(self) -> None:
        self.theme_var.set("Light" if self.theme_var.get() == "Dark" else "Dark")
        theme = self.current_theme()
        self.configure_ttk_theme()
        self.configure(bg=theme["window_bg"])
        for frame in self.themed_frames:
            try:
                frame.configure(bg=theme["window_bg"])
            except tk.TclError:
                pass
        for label in self.themed_labels:
            try:
                is_status = bool(getattr(label, "_crysdis_status_label", False))
                label.configure(bg=theme["window_bg"], fg=theme["status"] if is_status else theme["label"])
            except tk.TclError:
                pass
        for check in self.themed_checkbuttons:
            try:
                self.style_checkbutton(check)
            except tk.TclError:
                pass
        if self.scrollable is not None:
            self.scrollable.apply_theme()
        for panel in self.ordinary_panels.values():
            panel.apply_theme()
        for combo in self.combo_panels.values():
            combo.apply_theme()
        if self.theme_button is not None:
            self.theme_button.configure(text="Dark background" if self.theme_var.get() == "Light" else "Light background")
        if self.crystal_listbox is not None and self.crystal_listbox.winfo_exists():
            self.configure_listbox_theme(self.crystal_listbox)
        if self.advanced_log_text is not None and self.advanced_log_text.winfo_exists():
            self.configure_textbox_theme(self.advanced_log_text)
        self.rebuild_diffraction_cmaps()
        self.refresh_theme_default_diffraction_colors()
        self.redraw_all()

    def model_for(self, name: str) -> CrystalModel:
        definition = self.library.get(name)
        cache_key = json.dumps(definition.to_dict(), sort_keys=True)
        if cache_key in self.model_cache:
            return self.model_cache[cache_key]
        if definition.name == "FCC":
            model = make_cubic_model("FCC")
        elif definition.name == "BCC":
            model = make_cubic_model("BCC")
        elif definition.name == "HCP":
            model = make_hcp_model()
        else:
            model = make_custom_model(definition)
        self.model_cache[cache_key] = model
        return model

    def style_for_model(self, model: CrystalModel) -> dict[str, str]:
        if model.name in CRYSTAL_STYLES:
            return CRYSTAL_STYLES[model.name]
        color = dominant_color(model.definition)
        return {"atom": color, "edge": color, "light_edge": color, "diff": color, "title": model.name}

    def panel_state_by_id(self, panel_id: int | None) -> PanelState | None:
        if panel_id is None:
            return None
        return next((state for state in self.states if state.panel_id == panel_id), None)

    def panel_index_by_id(self, panel_id: int) -> int:
        for index, state in enumerate(self.states):
            if state.panel_id == panel_id:
                return index
        return 0

    def open_crystal_builder(self, column: int = 0, crystal_name: str | None = None, mode: str = "new") -> None:
        if not self.states:
            return
        CrystalBuilderDialog(self, min(max(column, 0), len(self.states) - 1), crystal_name=crystal_name, mode=mode)

    def save_custom_definition(
        self,
        definition: CrystalDefinition,
        column: int = 0,
        original_name: str | None = None,
        save_as_new: bool = False,
    ) -> CrystalDefinition:
        saved = (
            self.library.save_new(definition)
            if save_as_new
            else (self.library.save_edited(definition, original_name) if original_name else self.library.save(definition))
        )
        self.model_cache.clear()
        self.reciprocal_cache.clear()
        self.spot_cache.clear()
        self.refresh_crystal_options(saved.name, column)
        self.refresh_crystal_list_dialog()
        return saved

    def open_crystal_list(self) -> None:
        if self.crystal_list_dialog is not None and self.crystal_list_dialog.winfo_exists():
            self.crystal_list_dialog.lift()
            self.refresh_crystal_list_dialog()
            return
        theme = self.current_theme()
        dialog = tk.Toplevel(self)
        self.crystal_list_dialog = dialog
        dialog.title("Crystal list")
        dialog.geometry("560x430+180+120")
        dialog.transient(self)
        dialog.configure(bg=theme["window_bg"])
        outer = tk.Frame(dialog, bg=theme["window_bg"], padx=12, pady=10)
        outer.pack(fill=tk.BOTH, expand=True)
        self.crystal_listbox = tk.Listbox(outer, height=16, exportselection=False)
        self.configure_listbox_theme(self.crystal_listbox)
        self.crystal_listbox.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        actions = tk.Frame(outer, bg=theme["window_bg"])
        actions.pack(side=tk.TOP, fill=tk.X, pady=(10, 0))
        ttk.Button(actions, text="Edit", command=self.edit_selected_crystal).pack(side=tk.LEFT)
        ttk.Button(actions, text="Remove", command=self.remove_selected_crystal).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(actions, text="Close", command=dialog.destroy).pack(side=tk.RIGHT)
        self.refresh_crystal_list_dialog()

    def refresh_crystal_list_dialog(self) -> None:
        if self.crystal_listbox is None or not self.crystal_listbox.winfo_exists():
            return
        selection = self.selected_crystal_name()
        self.crystal_listbox.delete(0, tk.END)
        for name in self.library.options():
            if name == CUSTOM_SENTINEL:
                continue
            definition = self.library.get(name)
            status = "built-in" if name in DEFAULT_NAMES else "custom"
            site_count = len(definition.sites or [])
            self.crystal_listbox.insert(tk.END, f"{name}    {status}, {definition.lattice_system}, {site_count} site(s)")
        if selection:
            for index, name in enumerate(self.crystal_list_names()):
                if name == selection:
                    self.crystal_listbox.selection_set(index)
                    self.crystal_listbox.activate(index)
                    break

    def crystal_list_names(self) -> list[str]:
        return [name for name in self.library.options() if name != CUSTOM_SENTINEL]

    def selected_crystal_name(self) -> str | None:
        if self.crystal_listbox is None or not self.crystal_listbox.winfo_exists():
            return None
        selection = self.crystal_listbox.curselection()
        if not selection:
            return None
        names = self.crystal_list_names()
        index = int(selection[0])
        return names[index] if 0 <= index < len(names) else None

    def edit_selected_crystal(self) -> None:
        name = self.selected_crystal_name()
        if not name:
            return
        self.open_crystal_builder(0, crystal_name=name, mode="edit")

    def remove_selected_crystal(self) -> None:
        name = self.selected_crystal_name()
        if not name:
            return
        if name in DEFAULT_NAMES:
            messagebox.showinfo("Built-in Crystal", "Built-in FCC, BCC, and HCP crystals cannot be removed.", parent=self)
            return
        if not messagebox.askyesno("Remove Crystal", f"Remove {name} from the custom crystal library?", parent=self):
            return
        if not self.library.delete(name):
            messagebox.showwarning("Remove Crystal", f"Could not remove {name}.", parent=self)
            return
        self.model_cache.clear()
        self.reciprocal_cache.clear()
        self.spot_cache.clear()
        for index, state in enumerate(self.states):
            if state.crystal != name:
                continue
            state.crystal = "FCC"
            if index < len(self.controls):
                self.controls[index]["crystal"].set("FCC")
            self.apply_panel_settings(state.panel_id)
        self.refresh_crystal_options()
        self.refresh_crystal_list_dialog()
        self.status_var.set(f"Removed custom crystal: {name}")

    def load_cif_file(self, column: int = 0) -> None:
        path_text = filedialog.askopenfilename(
            parent=self,
            title="Choose CIF file",
            initialdir=str(APP_DIR),
            filetypes=(("CIF files", "*.cif"), ("All files", "*.*")),
        )
        if not path_text:
            return
        try:
            definition = definition_from_cif(Path(path_text))
            saved = self.save_custom_definition(definition, column)
        except ValueError as exc:
            messagebox.showerror("CIF Import Failed", str(exc), parent=self)
            return
        self.status_var.set(f"Loaded CIF: {saved.name}")

    def refresh_crystal_options(self, selected_name: str | None = None, column: int = 0) -> None:
        for panel in self.ordinary_panels.values():
            panel.refresh_options()
        if selected_name and self.controls:
            target = min(max(column, 0), len(self.states) - 1)
            self.controls[target]["crystal"].set(selected_name)
            self.states[target].crystal = selected_name
            color = self.default_diffraction_color_for_model(self.model_for(selected_name))
            self.set_panel_diffraction_color_control(self.states[target], color, user_set=False)
            self.apply_panel_settings(self.states[target].panel_id)
        self.refresh_combo_panels()

    def current_voltage_kv(self) -> float:
        try:
            value = float(self.voltage_var.get().strip())
        except ValueError:
            value = DEFAULT_VOLTAGE_KV
            self.status_var.set(f"Invalid voltage; using {DEFAULT_VOLTAGE_KV:g} kV")
        return max(value, 1e-6)

    def current_thickness_nm(self) -> float:
        try:
            value = float(self.thickness_var.get().strip())
        except ValueError:
            value = DEFAULT_THICKNESS_NM
            self.status_var.set(f"Invalid thickness; using {DEFAULT_THICKNESS_NM:g} nm")
        return max(value, 0.05)

    def current_max_hkl(self) -> int:
        try:
            value = int(float(self.max_hkl_var.get().strip()))
        except ValueError:
            value = DEFAULT_MAX_HKL
            self.status_var.set(f"Invalid max hkl; using {DEFAULT_MAX_HKL}")
        return min(max(value, 1), 30)

    def current_camera_length_mm(self) -> float:
        match = re.match(r"\s*([0-9]*\.?[0-9]+)", self.camera_length_var.get())
        return max(float(match.group(1)), 1.0) if match else DEFAULT_CAMERA_LENGTH_MM

    def current_real_magnification(self, panel_id: int | None = None) -> float:
        state = self.panel_state_by_id(panel_id)
        if state is not None:
            return min(max(float(state.real_magnification), 0.25), 12.0)
        return DEFAULT_REAL_MAGNIFICATION

    def current_spot_intensity_threshold(self) -> float:
        try:
            value = float(self.spot_threshold_var.get().strip())
        except ValueError:
            value = DEFAULT_SPOT_INTENSITY_THRESHOLD
        return min(max(value, MIN_SPOT_INTENSITY_THRESHOLD), 1.0)

    def current_spot_size_scaling_effect(self) -> float:
        try:
            value = float(self.spot_size_scaling_var.get().strip())
        except ValueError:
            value = DEFAULT_SPOT_SIZE_SCALING
        return min(max(value, 0.0), 1.0)

    def current_intensity_compression_factor(self) -> float:
        try:
            value = float(self.intensity_compression_var.get().strip())
        except ValueError:
            value = DEFAULT_INTENSITY_COMPRESSION_FACTOR
        return min(max(value, 10.0), 150.0)

    def current_detector_scale_mm_per_nm_inv(self) -> float:
        return detector_scale_mm_per_nm_inv(self.current_camera_length_mm(), self.current_voltage_kv())

    def current_reciprocal_units_per_plot_unit(self) -> float:
        return 1.0 / max(self.current_detector_scale_mm_per_nm_inv(), 1e-12)

    def current_diffraction_limit(self) -> float:
        return max(0.05, default_detector_half_width_mm())

    def schedule_panel_apply(self, panel_id: int) -> None:
        if not self.ordinary_panels:
            return
        job = self._pending_apply_jobs.get(panel_id)
        if job is not None:
            self.after_cancel(job)
        self._pending_apply_jobs[panel_id] = self.after(550, lambda p=panel_id: self.apply_panel_settings(p))

    def apply_all_panels(self, _event=None) -> None:
        for state in self.states:
            self.apply_panel_settings(state.panel_id)

    def on_crystal_selected(self, column: int) -> None:
        if not self.controls:
            return
        selected = self.controls[column]["crystal"].get()
        if selected == CUSTOM_SENTINEL:
            self.controls[column]["crystal"].set(self.states[column].crystal)
            self.open_crystal_builder(column, mode="new")
            return
        self.controls[column]["plane"].set("")
        self.controls[column]["vector"].set("")
        color = self.default_diffraction_color_for_model(self.model_for(selected))
        self.set_panel_diffraction_color_control(self.states[column], color, user_set=False)
        self.apply_panel_settings(self.states[column].panel_id)

    def apply_panel_settings(self, panel_id: int, initial: bool = False) -> None:
        pending = self._pending_apply_jobs.pop(panel_id, None)
        if pending is not None:
            self.after_cancel(pending)
        state = self.panel_state_by_id(panel_id)
        panel = self.ordinary_panels.get(panel_id)
        if state is None or panel is None:
            return
        old_view = camera_vector_from_view(state.elev, state.azim)
        old_roll = state.roll
        panel.sync_state_from_controls()
        if state.crystal == CUSTOM_SENTINEL:
            state.crystal = "FCC"
            panel.crystal_var.set("FCC")
        model = self.model_for(state.crystal)
        errors: list[str] = []

        zone_changed = initial or state.zone_text != state.applied_zone_text
        zone: list[ParsedIndex] = []
        if state.zone_text.strip():
            zone, zone_errors = parse_indices(state.zone_text, model, "direction", allow_multiple=False)
            if zone_changed:
                errors.extend(zone_errors)
                if zone:
                    state.elev, state.azim = view_from_vector(zone[0].vector)
                    state.roll = 0.0
                    state.applied_zone_text = state.zone_text
                else:
                    errors.append(f"Panel {panel_id}: keeping previous view")

        rotation_message = ""
        rotation_command, rotation_errors = parse_rotation_command(state.rotation_text, model)
        errors.extend(rotation_errors)
        if rotation_command is not None:
            view = camera_vector_from_view(state.elev, state.azim)
            axis = rotation_command.axis if rotation_command.axis is not None else view
            if normalize_vector(axis) is None:
                errors.append(f"Panel {panel_id}: rotation axis has zero length")
            else:
                view, state.roll = rotate_orientation(view, state.roll, axis, rotation_command.angle_degrees)
                state.elev, state.azim = view_from_vector(view)
                rotation_message = f"Panel {panel_id}: rotated {rotation_command.angle_degrees:g} deg about {rotation_command.axis_label}"
                state.rotation_text = ""
                panel.rotation_var.set("")

        self.draw_panel(panel_id)
        new_view = camera_vector_from_view(state.elev, state.azim)
        if not initial:
            self.propagate_bound_motion(panel_id, old_view, old_roll, new_view, state.roll)
            self.refresh_combo_panels()
            self.status_var.set("; ".join(errors[:3]) if errors else (rotation_message or f"Panel {panel_id}: {state.crystal} updated"))

    def sync_panel_from_axis(self, panel_id: int) -> None:
        state = self.panel_state_by_id(panel_id)
        if state is None:
            return
        old_view = camera_vector_from_view(state.elev, state.azim)
        old_roll = state.roll
        self.update_state_from_axis(panel_id)
        self.draw_diffraction(panel_id)
        panel = self.ordinary_panels.get(panel_id)
        if panel is not None:
            panel.diffraction_canvas.draw_idle()
        new_view = camera_vector_from_view(state.elev, state.azim)
        self.propagate_bound_motion(panel_id, old_view, old_roll, new_view, state.roll)
        self.refresh_combo_panels()
        self.status_var.set(f"Panel {panel_id}: diffraction synced to current view")

    def reset_panel_view(self, panel_id: int) -> None:
        state = self.panel_state_by_id(panel_id)
        if state is None:
            return
        old_view = camera_vector_from_view(state.elev, state.azim)
        old_roll = state.roll
        model = self.model_for(state.crystal)
        zone, errors = parse_indices(state.zone_text, model, "direction", allow_multiple=False)
        if not zone:
            self.status_var.set("; ".join(errors[:2]) if errors else f"Panel {panel_id}: no zone axis to reset to")
            return
        state.elev, state.azim = view_from_vector(zone[0].vector)
        state.roll = 0.0
        state.applied_zone_text = state.zone_text
        self.draw_panel(panel_id)
        self.propagate_bound_motion(panel_id, old_view, old_roll, camera_vector_from_view(state.elev, state.azim), state.roll)
        self.status_var.set(f"Panel {panel_id}: reset to {zone[0].label}")

    def on_mouse_press(self, panel_id: int, event) -> None:
        panel = self.ordinary_panels.get(panel_id)
        state = self.panel_state_by_id(panel_id)
        if panel is None or state is None or event.inaxes is not panel.crystal_ax:
            return
        state = self.panel_state_by_id(panel_id)
        if state is None:
            return
        self._drag_panel_id = panel_id
        self._drag_old_view = camera_vector_from_view(state.elev, state.azim)
        self._drag_old_roll = state.roll

    def on_mouse_motion(self, panel_id: int, _event) -> None:
        if self._drag_panel_id != panel_id:
            return
        if not self.auto_sync_var.get():
            return
        self.update_state_from_axis(panel_id)
        state = self.panel_state_by_id(panel_id)
        panel = self.ordinary_panels.get(panel_id)
        if state is not None and panel is not None:
            panel.status_var.set(self.panel_status_text(state))
        if self.performance_mode_var.get():
            return
        job = self._pending_diffraction_jobs.get(panel_id)
        if job is None:
            self._pending_diffraction_jobs[panel_id] = self.after(
                240,
                lambda p=panel_id: self.refresh_diffraction_after_drag(p),
            )

    def on_mouse_release(self, panel_id: int, _event) -> None:
        if self._drag_panel_id != panel_id:
            return
        self._drag_panel_id = None
        old_view = self._drag_old_view
        old_roll = self._drag_old_roll
        self._drag_old_view = None
        pending = self._pending_diffraction_jobs.pop(panel_id, None)
        if pending is not None:
            self.after_cancel(pending)
        if not self.auto_sync_var.get():
            self.status_var.set(f"Panel {panel_id}: crystal view changed; press Sync view to update diffraction")
            return
        self.update_state_from_axis(panel_id)
        state = self.panel_state_by_id(panel_id)
        self.draw_diffraction(panel_id)
        panel = self.ordinary_panels.get(panel_id)
        if panel is not None:
            panel.diffraction_canvas.draw_idle()
        if state is not None and old_view is not None:
            self.propagate_bound_motion(panel_id, old_view, old_roll, camera_vector_from_view(state.elev, state.azim), state.roll)
        self.refresh_combo_panels()

    def on_mouse_scroll(self, panel_id: int, event) -> None:
        panel = self.ordinary_panels.get(panel_id)
        state = self.panel_state_by_id(panel_id)
        if panel is None or state is None or event.inaxes is not panel.crystal_ax:
            return
        step = float(getattr(event, "step", 0.0) or 0.0)
        if step == 0.0:
            step = 1.0 if getattr(event, "button", "") == "up" else -1.0
        factor = 1.18 if step > 0 else 1.0 / 1.18
        state.real_magnification = min(max(state.real_magnification * factor, 0.25), 12.0)
        self.draw_crystal(panel_id)
        panel.crystal_canvas.draw_idle()
        self.status_var.set(f"Panel {panel_id}: real-space magnification {state.real_magnification:.3g}x")

    def update_state_from_axis(self, panel_id: int) -> None:
        panel = self.ordinary_panels.get(panel_id)
        state = self.panel_state_by_id(panel_id)
        if panel is None or state is None:
            return
        state.elev = float(panel.crystal_ax.elev)
        state.azim = float(panel.crystal_ax.azim)
        state.roll = float(getattr(panel.crystal_ax, "roll", 0.0))

    def refresh_diffraction_after_drag(self, panel_id: int) -> None:
        self._pending_diffraction_jobs.pop(panel_id, None)
        self.update_state_from_axis(panel_id)
        self.draw_diffraction(panel_id)
        panel = self.ordinary_panels.get(panel_id)
        if panel is not None:
            panel.diffraction_canvas.draw_idle()

    def propagate_bound_motion(
        self,
        source_panel_id: int,
        old_view: np.ndarray,
        old_roll: float,
        new_view: np.ndarray,
        new_roll: float,
    ) -> None:
        if self._is_propagating_motion:
            return
        bound_ids: set[int] = set()
        for combo_state in self.combo_states:
            if combo_state.bind_motion and source_panel_id in combo_state.source_panel_ids:
                bound_ids.update(combo_state.source_panel_ids)
        bound_ids.discard(source_panel_id)
        if not bound_ids:
            return
        delta = local_orientation_delta(old_view, old_roll, new_view, new_roll)
        if np.allclose(delta, np.eye(3), atol=1e-6):
            return
        self._is_propagating_motion = True
        try:
            for panel_id in sorted(bound_ids):
                state = self.panel_state_by_id(panel_id)
                if state is None:
                    continue
                view, state.roll = apply_local_orientation_delta(camera_vector_from_view(state.elev, state.azim), state.roll, delta)
                state.elev, state.azim = view_from_vector(view)
                self.draw_panel(panel_id)
        finally:
            self._is_propagating_motion = False

    def repair_combo_sources(self, combo_state: ComboPanelState) -> None:
        available = [state.panel_id for state in self.states]
        available_set = set(available)
        combo_state.source_panel_ids = [panel_id for panel_id in combo_state.source_panel_ids if panel_id in available_set]
        if not combo_state.source_panel_ids and available:
            combo_state.source_panel_ids = available[: min(2, len(available))]
        if combo_state.selected_panel_id not in available_set:
            combo_state.selected_panel_id = available[0] if available else None

    def refresh_combo_panels(self) -> None:
        for combo in self.combo_panels.values():
            combo.refresh()

    def refresh_diffractions(self, _event=None, clear_cache: bool = False) -> None:
        if clear_cache:
            self.reciprocal_cache.clear()
            self.spot_cache.clear()
        for state in self.states:
            self.draw_diffraction(state.panel_id)
            panel = self.ordinary_panels.get(state.panel_id)
            if panel is not None:
                panel.diffraction_canvas.draw_idle()
        self.refresh_combo_panels()

    def redraw_all_crystals(self, _event=None) -> None:
        for state in self.states:
            self.draw_crystal(state.panel_id)
            panel = self.ordinary_panels.get(state.panel_id)
            if panel is not None:
                panel.crystal_canvas.draw_idle()

    def redraw_all(self, _event=None) -> None:
        for state in self.states:
            self.draw_panel(state.panel_id)
        self.refresh_combo_panels()

    def draw_panel(self, panel_id: int) -> None:
        self.draw_crystal(panel_id)
        self.draw_diffraction(panel_id)
        panel = self.ordinary_panels.get(panel_id)
        if panel is not None:
            panel.crystal_canvas.draw_idle()
            panel.diffraction_canvas.draw_idle()

    def draw_crystal(self, panel_id: int) -> None:
        state = self.panel_state_by_id(panel_id)
        panel = self.ordinary_panels.get(panel_id)
        if state is None or panel is None:
            return
        model = self.model_for(state.crystal)
        style = self.style_for_model(model)
        theme = self.current_theme()
        axis = panel.crystal_ax
        axis.clear()
        axis.set_proj_type("ortho")
        axis.set_facecolor(theme["axis_bg"])
        atoms = model.display_atoms
        atom_sizes = np.full(len(atoms), 170.0 if state.crystal != "HCP" else 145.0)
        if state.crystal == "BCC" and len(atom_sizes):
            atom_sizes[-1] = 230.0
        if state.crystal not in CRYSTAL_STYLES:
            atom_sizes = np.array([110.0 * (0.42 + max(occ, 0.12)) for occ in model.atom_occupancies], dtype=float)
        axis.scatter(
            atoms[:, 0],
            atoms[:, 1],
            atoms[:, 2],
            s=atom_sizes,
            c=model.atom_colors if len(model.atom_colors) == len(atoms) else style["atom"],
            edgecolors=theme["atom_edge"],
            linewidths=1.1,
            depthshade=True,
        )
        edge_color = "#9AA3AD" if self.theme_var.get() == "Dark" else "#6B7280"
        for start, end in model.cell_edges:
            axis.plot(
                [start[0], end[0]],
                [start[1], end[1]],
                [start[2], end[2]],
                color=edge_color,
                linewidth=1.1,
                linestyle="-",
                alpha=0.85,
            )
        overlay_points = [model.crystal_origin]
        planes, plane_errors = parse_indices(state.plane_text, model, "plane", allow_multiple=True)
        vectors, vector_errors = parse_indices(
            state.vector_text,
            model,
            "direction",
            allow_multiple=True,
            allow_reciprocal=True,
        )
        overlay_points.extend(self.draw_planes(axis, planes, model))
        overlay_points.extend(self.draw_vectors(axis, vectors, model))
        if plane_errors or vector_errors:
            self.status_var.set("; ".join((plane_errors + vector_errors)[:3]))
        axis.set_box_aspect([1, 1, 1])
        all_points = np.vstack([model.display_atoms, np.array(overlay_points)])
        base_limit = max(model.limit, float(np.max(np.abs(all_points))) * 1.12)
        limit = max(base_limit / self.current_real_magnification(panel_id), 0.08)
        axis.set_xlim(-limit, limit)
        axis.set_ylim(-limit, limit)
        axis.set_zlim(-limit, limit)
        self.set_axis_view(axis, state)
        axis.axis("off")
        if self.show_real_scale_bar_var.get():
            self.draw_real_space_scale_bar(axis, model, limit, state)
        panel.status_var.set(self.panel_status_text(state))

    def panel_status_text(self, state: PanelState) -> str:
        return f"{state.crystal} | zone {state.zone_text or 'free'} | elev {state.elev:.1f}, azim {state.azim:.1f}, roll {state.roll:.1f}"

    def draw_real_space_scale_bar(self, axis, model: CrystalModel, limit: float, state: PanelState) -> None:
        theme = self.current_theme()
        visible_nm = max(2.0 * limit * model.scale_nm, 1e-9)
        bar_nm = choose_scale_bar(visible_nm)
        bar_display = min(bar_nm / max(model.scale_nm, 1e-12), 0.72 * limit)
        view = camera_vector_from_view(state.elev, state.azim)
        normal = normalize_vector(view)
        if normal is None:
            normal = np.array([1.0, 0.0, 0.0])
        u_axis, v_axis = projection_basis(normal, state.roll)
        anchor = (0.70 * normal - 0.76 * u_axis - 0.76 * v_axis) * limit
        start = anchor
        end = anchor + bar_display * u_axis
        tick = 0.035 * limit
        tick_vec = tick * v_axis
        color = theme["title"]
        for a, b, linewidth in (
            (start, end, 2.5),
            (start - tick_vec, start + tick_vec, 1.5),
            (end - tick_vec, end + tick_vec, 1.5),
        ):
            axis.plot(
                [a[0], b[0]],
                [a[1], b[1]],
                [a[2], b[2]],
                color=color,
                linewidth=linewidth,
                solid_capstyle="butt",
                zorder=1000,
            )
        label_position = 0.5 * (start + end) + 1.9 * tick_vec
        axis.text(
            label_position[0],
            label_position[1],
            label_position[2],
            f"{bar_nm:g} nm",
            color=color,
            fontsize=8,
            ha="center",
            va="center",
            zorder=1001,
        )

    def draw_planes(self, axis, planes: list[ParsedIndex], model: CrystalModel) -> list[np.ndarray]:
        overlay_points = []
        for index, plane in enumerate(planes):
            vertices = clipped_plane_polygon(model, plane)
            if vertices is None:
                continue
            color = self.resolve_color(self.plane_colors[index % len(self.plane_colors)], PLANE_COLORS[index % len(PLANE_COLORS)])
            axis.add_collection3d(Poly3DCollection([vertices], facecolor=color, edgecolor=color, linewidth=1.0, alpha=0.24))
            overlay_points.extend(vertices)
            if self.show_annotations_var.get():
                label_position = np.mean(vertices, axis=0)
                axis.text(label_position[0], label_position[1], label_position[2], plane.label, color=color, fontsize=8, ha="center", va="center")
        return overlay_points

    def draw_vectors(self, axis, vectors: list[ParsedIndex], model: CrystalModel) -> list[np.ndarray]:
        overlay_points = []
        for index, vector in enumerate(vectors):
            color = self.resolve_color(self.vector_colors[index % len(self.vector_colors)], VECTOR_COLORS[index % len(VECTOR_COLORS)])
            if vector.is_reciprocal:
                start, end = reciprocal_segment_for_display(vector.values, model)
            else:
                start, end = direction_segment_for_display(vector.values, model)
            overlay_points.extend([start, end])
            axis.quiver(
                start[0],
                start[1],
                start[2],
                end[0] - start[0],
                end[1] - start[1],
                end[2] - start[2],
                color=color,
                linewidth=2.4,
                linestyle="--" if vector.is_reciprocal else "-",
                arrow_length_ratio=0.16,
            )
            if self.show_annotations_var.get():
                axis.text(end[0], end[1], end[2], vector.label, color=color, fontsize=8, ha="center", va="center")
        return overlay_points

    def diffraction_color_for_state(self, state: PanelState, model: CrystalModel) -> str:
        color = state.diffraction_color.strip() if state.diffraction_color else ""
        if re.match(r"^#[0-9a-fA-F]{6}$", color):
            return color
        if color.lower() in NAMED_COLORS:
            return NAMED_COLORS[color.lower()]
        return self.resolve_color(self.default_diffraction_color_for_model(model), self.style_for_model(model)["diff"])

    def draw_diffraction(self, panel_id: int) -> None:
        state = self.panel_state_by_id(panel_id)
        panel = self.ordinary_panels.get(panel_id)
        if state is None or panel is None:
            return
        model = self.model_for(state.crystal)
        theme = self.current_theme()
        axis = panel.diffraction_ax
        axis.clear()
        axis.set_facecolor(theme["diff_bg"])
        view_vector = camera_vector_from_view(state.elev, state.azim)
        color = self.diffraction_color_for_state(state, model)
        method = self.current_simulation_method()
        if method == SIMULATION_METHOD_PYMATGEN:
            self.draw_spot_diffraction(axis, self.compute_pymatgen_tem_spots(model, view_vector, state.roll), color, model=model)
        else:
            self.draw_spot_diffraction(axis, self.compute_ewald_spots(model, view_vector, state.roll), color, model=model)
        if self.show_zone_axis_var.get():
            zone_label = zone_axis_label_from_view(
                model,
                view_vector,
                use_hex_four_index=bool(self.hex_four_index_var.get()),
            )
            self.draw_zone_annotation(axis, axis.get_xlim()[1], zone_label)
        axis.set_aspect("equal")
        axis.set_xticks([])
        axis.set_yticks([])
        for spine in axis.spines.values():
            spine.set_visible(False)

    def draw_spot_diffraction(
        self,
        axis,
        spots: np.ndarray,
        color: str,
        label: str | None = None,
        model: CrystalModel | None = None,
    ) -> None:
        limit = self.current_diffraction_limit()
        if len(spots):
            intensity = spots[:, 2]
            rgb = to_rgb(color)
            colors = [(rgb[0], rgb[1], rgb[2], 0.16 + 0.78 * float(value)) for value in intensity]
            sizes = BASE_DIFFRACTION_MARKER_SIZE + EXTRA_DIFFRACTION_MARKER_SIZE * self.current_spot_size_scaling_effect() * intensity**1.18
            axis.scatter(spots[:, 0], spots[:, 1], s=sizes, c=colors, edgecolors="none", label=label)
            if self.show_indices_var.get():
                self.draw_indices(axis, spots, model)
        else:
            axis.text(0, 0, "No visible reflections", color=self.current_theme()["status"], fontsize=9, ha="center", va="center")
        if self.show_reciprocal_scale_bar_var.get():
            self.draw_scale_bar(axis, limit, self.current_reciprocal_units_per_plot_unit())
        axis.set_xlim(-limit, limit)
        axis.set_ylim(-limit, limit)

    def draw_combo_diffraction(self, combo_id: int) -> None:
        combo = self.combo_panels.get(combo_id)
        state = next((item for item in self.combo_states if item.combo_id == combo_id), None)
        if combo is None or state is None:
            return
        self.repair_combo_sources(state)
        axis = combo.diffraction_ax
        axis.clear()
        axis.set_facecolor(self.current_theme()["diff_bg"])
        limit = self.current_diffraction_limit()
        has_data = False
        legend_entries: list[tuple[str, str]] = []
        method = self.current_simulation_method()
        for panel_id in reversed(state.source_panel_ids):
            source = self.panel_state_by_id(panel_id)
            if source is None:
                continue
            model = self.model_for(source.crystal)
            view = camera_vector_from_view(source.elev, source.azim)
            spots = (
                self.compute_pymatgen_tem_spots(model, view, source.roll)
                if method == SIMULATION_METHOD_PYMATGEN
                else self.compute_ewald_spots(model, view, source.roll)
            )
            if not len(spots):
                continue
            has_data = True
            color = self.diffraction_color_for_state(source, model)
            legend_entries.append((f"P{source.panel_id} {source.crystal}", color))
            intensity = spots[:, 2]
            rgb = to_rgb(color)
            colors = [(rgb[0], rgb[1], rgb[2], 0.14 + 0.72 * float(value)) for value in intensity]
            sizes = (
                BASE_DIFFRACTION_MARKER_SIZE
                + EXTRA_DIFFRACTION_MARKER_SIZE * self.current_spot_size_scaling_effect() * intensity**1.18
            )
            axis.scatter(spots[:, 0], spots[:, 1], s=sizes, c=colors, edgecolors="none", label=f"P{source.panel_id} {source.crystal}")
            if self.show_indices_var.get():
                self.draw_indices(axis, spots, model)
        if not has_data:
            axis.text(0, 0, "No source reflections to overlay", color=self.current_theme()["status"], fontsize=10, ha="center", va="center")
        if self.show_zone_axis_var.get() and state.source_panel_ids:
            first_source = self.panel_state_by_id(state.source_panel_ids[0])
            if first_source is not None:
                first_model = self.model_for(first_source.crystal)
                self.draw_zone_annotation(
                    axis,
                    limit,
                    zone_axis_label_from_view(
                        first_model,
                        camera_vector_from_view(first_source.elev, first_source.azim),
                        use_hex_four_index=bool(self.hex_four_index_var.get()),
                    ),
                )
        if self.show_reciprocal_scale_bar_var.get():
            self.draw_scale_bar(axis, limit, self.current_reciprocal_units_per_plot_unit())
        axis.set_xlim(-limit, limit)
        axis.set_ylim(-limit, limit)
        combo.draw_legend(list(reversed(legend_entries)))
        axis.set_aspect("equal")
        axis.set_xticks([])
        axis.set_yticks([])
        for spine in axis.spines.values():
            spine.set_visible(False)
        combo.diffraction_canvas.draw_idle()

    def compute_ewald_spots(self, model: CrystalModel, view_vector: np.ndarray, roll: float) -> np.ndarray:
        view = normalize_vector(view_vector)
        if view is None:
            view = np.array([1.0, 0.0, 0.0])
        cache_key = (
            "ewald",
            model.name,
            self.current_max_hkl(),
            round(self.current_voltage_kv(), 4),
            round(self.current_thickness_nm(), 4),
            round(self.current_camera_length_mm(), 4),
            round(self.current_spot_intensity_threshold(), 6),
            round(self.current_intensity_compression_factor(), 4),
            tuple(np.round(view, 5)),
            round(float(roll), 3),
        )
        if cache_key in self.spot_cache:
            return self.spot_cache[cache_key]
        hkl, reciprocal_points, structure_intensity = self.reciprocal_points_for_model(model)
        if len(hkl) == 0:
            return np.empty((0, 6), dtype=float)
        u_axis, v_axis = projection_basis(view, roll)
        x_screen = reciprocal_points @ u_axis
        y_screen = reciprocal_points @ v_axis
        depth = reciprocal_points @ view
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
        thickness_shape = np.sinc(excitation_error * self.current_thickness_nm()) ** 2
        raw_intensity = structure_intensity * thickness_shape
        zero_beam = np.all(hkl == 0, axis=1)
        raw_intensity[zero_beam] = max(float(raw_intensity.max(initial=1.0)), 1.0)
        if raw_intensity.max(initial=0.0) > 0:
            raw_intensity = raw_intensity / raw_intensity.max()
        compression = self.current_intensity_compression_factor()
        display_intensity = np.log1p(compression * raw_intensity) / math.log1p(compression)
        visible = (display_intensity > self.current_spot_intensity_threshold()) & valid_curvature
        result = np.column_stack((x_plot[visible], y_plot[visible], display_intensity[visible], hkl[visible, 0], hkl[visible, 1], hkl[visible, 2]))
        if len(self.spot_cache) > 256:
            self.spot_cache.clear()
        self.spot_cache[cache_key] = result
        return result

    def pymatgen_structure_from_model(self, model: CrystalModel) -> Any:
        from pymatgen.core import Lattice, Structure

        lattice = Lattice(np.asarray(model.lattice, dtype=float) * 10.0)
        species = []
        coords = []
        for site in model.expanded_sites:
            occupancy = min(max(float(site.occupancy), 0.0), 1.0)
            if occupancy <= 0.0:
                continue
            species.append({site.element: occupancy})
            coords.append(site.fractional)
        return Structure(lattice, species, coords)

    def integer_zone_axis_from_view(
        self,
        model: CrystalModel,
        view_vector: np.ndarray,
        max_index: int = DEFAULT_ZONE_AXIS_SEARCH_MAX,
    ) -> tuple[int, int, int]:
        return integer_zone_axis_from_view(model, view_vector, max_index=max_index)

    def compute_pymatgen_tem_spots(self, model: CrystalModel, view_vector: np.ndarray, roll: float) -> np.ndarray:
        if not PYMATGEN_AVAILABLE:
            self.status_var.set("Pymatgen is not installed; using Ewald reflections instead")
            return self.compute_ewald_spots(model, view_vector, roll)
        try:
            from pymatgen.analysis.diffraction.tem import TEMCalculator

            structure = self.pymatgen_structure_from_model(model)
            zone_axis = self.integer_zone_axis_from_view(model, view_vector)
            calculator = TEMCalculator(
                symprec=None,
                voltage=self.current_voltage_kv(),
                beam_direction=zone_axis,
                camera_length=max(int(round(self.current_camera_length_mm() / 10.0)), 1),
            )
            max_order = self.current_max_hkl()
            dots = calculator.tem_dots(structure, TEMCalculator.generate_points(-max_order, max_order))
        except Exception as exc:
            self.status_var.set(f"Pymatgen TEM calculation failed: {exc}")
            return np.empty((0, 6), dtype=float)

        normal = normalize_vector(view_vector)
        if normal is None:
            normal = np.array([1.0, 0.0, 0.0])
        u_axis, v_axis = projection_basis(normal, roll)
        detector_scale = self.current_detector_scale_mm_per_nm_inv()
        compression = self.current_intensity_compression_factor()
        rows = [[0.0, 0.0, 1.0, 0, 0, 0]]
        for dot in dots:
            h, k, l = (int(value) for value in dot.hkl)
            if h == k == l == 0:
                continue
            raw_intensity = max(float(dot.intensity), 0.0)
            display_intensity = math.log1p(compression * raw_intensity) / math.log1p(compression)
            if display_intensity <= self.current_spot_intensity_threshold():
                continue
            g_vector = np.array([h, k, l], dtype=float) @ model.reciprocal
            rows.append(
                [
                    detector_scale * float(np.dot(g_vector, u_axis)),
                    detector_scale * float(np.dot(g_vector, v_axis)),
                    display_intensity,
                    h,
                    k,
                    l,
                ]
            )
        return np.array(rows, dtype=float)

    def reciprocal_points_for_model(self, model: CrystalModel) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        max_order = self.current_max_hkl()
        cache_key = (json.dumps(model.definition.to_dict(), sort_keys=True), max_order)
        if cache_key in self.reciprocal_cache:
            return self.reciprocal_cache[cache_key]
        hkl_values = []
        reciprocal_points = []
        structure_intensity = []
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
            structure_intensity.append(intensity)
        result = (
            np.array(hkl_values, dtype=int),
            np.array(reciprocal_points, dtype=float),
            np.array(structure_intensity, dtype=float),
        )
        self.reciprocal_cache[cache_key] = result
        return result

    def draw_indices(self, axis, spots: np.ndarray, model: CrystalModel | None = None) -> None:
        theme = self.current_theme()
        order = np.argsort(spots[:, 2])[::-1]
        labeled = 0
        use_hex_four = bool(model is not None and is_hexagonal(model) and self.hex_four_index_var.get())
        for spot_index in order:
            h, k, l = (int(round(value)) for value in spots[spot_index, 3:6])
            if h == k == l == 0:
                continue
            indices: tuple[int, ...] = hcp_three_index_plane_to_four((h, k, l)) if use_hex_four else (h, k, l)
            axis.text(
                float(spots[spot_index, 0]),
                float(spots[spot_index, 1]),
                miller_index_label(indices),
                color=theme["title"],
                fontsize=6.2,
                ha="center",
                va="bottom",
                alpha=0.86,
                clip_on=True,
            )
            labeled += 1
            if labeled >= 80:
                break

    def draw_scale_bar(self, axis, limit: float, reciprocal_units_per_plot_unit: float = 1.0) -> None:
        theme = self.current_theme()
        reciprocal_units_per_plot_unit = max(float(reciprocal_units_per_plot_unit), 1e-12)
        reciprocal_limit = max(float(limit) * reciprocal_units_per_plot_unit, 1e-9)
        bar_reciprocal = choose_scale_bar(reciprocal_limit)
        bar_plot = bar_reciprocal / reciprocal_units_per_plot_unit
        x0 = -0.88 * limit
        y0 = -0.84 * limit
        tick = 0.025 * limit
        color = theme["title"]
        axis.plot([x0, x0 + bar_plot], [y0, y0], color=color, linewidth=2.2, solid_capstyle="butt")
        axis.plot([x0, x0], [y0 - tick, y0 + tick], color=color, linewidth=1.4)
        axis.plot([x0 + bar_plot, x0 + bar_plot], [y0 - tick, y0 + tick], color=color, linewidth=1.4)
        axis.text(x0 + bar_plot * 0.5, y0 + 0.075 * limit, f"{bar_reciprocal:g} nm$^{{-1}}$", color=color, fontsize=8, ha="center", va="bottom")

    def draw_zone_annotation(self, axis, limit: float, label: str) -> None:
        color = self.current_theme()["title"]
        axis.text(0.92 * limit, -0.90 * limit, str(label), color=color, fontsize=8, ha="right", va="bottom", alpha=0.9)

    def compute_diffraction(self, model: CrystalModel, view_vector: np.ndarray, roll: float) -> np.ndarray:
        grid_size = 256
        real_image = np.zeros((grid_size, grid_size), dtype=float)
        u_axis, v_axis = projection_basis(view_vector, roll)
        projected_x = model.diffraction_atoms @ u_axis
        projected_y = model.diffraction_atoms @ v_axis
        span = max(float(np.ptp(projected_x)), float(np.ptp(projected_y)))
        half_span = max(span * 0.54, 1.0)
        scale = (grid_size - 12) / (2.0 * half_span)
        center = (grid_size - 1) / 2.0
        pixel_x = projected_x * scale + center
        pixel_y = projected_y * scale + center
        kernel_radius = 2
        sigma = 0.85
        offsets = range(-kernel_radius, kernel_radius + 1)
        for x_coord, y_coord in zip(pixel_x, pixel_y):
            ix = int(round(x_coord))
            iy = int(round(y_coord))
            if ix < kernel_radius or ix >= grid_size - kernel_radius or iy < kernel_radius or iy >= grid_size - kernel_radius:
                continue
            for dx in offsets:
                for dy in offsets:
                    real_image[iy + dy, ix + dx] += math.exp(-(dx * dx + dy * dy) / (2.0 * sigma * sigma))
        real_image -= real_image.min()
        if real_image.max() > 0:
            real_image /= real_image.max()
        window_1d = np.hanning(grid_size)
        amplitude = np.fft.fftshift(np.fft.fft2(real_image * np.outer(window_1d, window_1d)))
        intensity = np.abs(amplitude) ** 2
        center_index = grid_size // 2
        crop_radius = 88
        cropped = intensity[center_index - crop_radius : center_index + crop_radius, center_index - crop_radius : center_index + crop_radius]
        cropped = np.log1p(cropped)
        if cropped.max() > 0:
            cropped /= cropped.max()
        cropped = np.clip(cropped, 0.0, 1.0) ** 0.42
        yy, xx = np.ogrid[: cropped.shape[0], : cropped.shape[1]]
        cy = (cropped.shape[0] - 1) / 2.0
        cx = (cropped.shape[1] - 1) / 2.0
        radius = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        cropped *= np.clip(1.15 - radius / (cropped.shape[0] * 0.82), 0.28, 1.0)
        return self.render_spot_image(cropped)

    def render_spot_image(self, fft_image: np.ndarray) -> np.ndarray:
        threshold = max(0.22, float(fft_image.mean() + 1.35 * fft_image.std()))
        local_max = fft_image > threshold
        for dy in [-1, 0, 1]:
            for dx in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue
                local_max &= fft_image >= np.roll(np.roll(fft_image, dy, axis=0), dx, axis=1)
        candidates = np.argwhere(local_max)
        if len(candidates) == 0:
            return fft_image
        values = fft_image[candidates[:, 0], candidates[:, 1]]
        order = np.argsort(values)[::-1]
        selected = []
        min_distance_sq = 6.5**2
        for candidate_index in order:
            y_coord, x_coord = candidates[candidate_index]
            value = float(values[candidate_index])
            if all((x_coord - sx) ** 2 + (y_coord - sy) ** 2 >= min_distance_sq for sy, sx, _ in selected):
                selected.append((int(y_coord), int(x_coord), value))
            if len(selected) >= 115:
                break
        spot_image = np.zeros_like(fft_image)
        yy, xx = np.indices(fft_image.shape)
        for y_coord, x_coord, value in selected:
            sigma = 1.15 + 2.2 * (1.0 - min(value, 1.0))
            radius = max(3, int(3.2 * sigma))
            y_min = max(0, y_coord - radius)
            y_max = min(fft_image.shape[0], y_coord + radius + 1)
            x_min = max(0, x_coord - radius)
            x_max = min(fft_image.shape[1], x_coord + radius + 1)
            y_slice = yy[y_min:y_max, x_min:x_max] - y_coord
            x_slice = xx[y_min:y_max, x_min:x_max] - x_coord
            gaussian = np.exp(-(x_slice * x_slice + y_slice * y_slice) / (2.0 * sigma * sigma))
            spot_image[y_min:y_max, x_min:x_max] += (value**1.35) * gaussian
        spot_image = np.maximum(spot_image, fft_image * 0.055)
        if spot_image.max() > 0:
            spot_image /= spot_image.max()
        return np.clip(spot_image, 0.0, 1.0) ** 0.72

    def set_axis_view(self, axis, state: PanelState) -> None:
        if hasattr(axis, "roll"):
            axis.view_init(elev=state.elev, azim=state.azim, roll=state.roll)
        else:
            axis.view_init(elev=state.elev, azim=state.azim)

    def ask_export_options(self, title: str) -> tuple[float, bool] | None:
        theme = self.current_theme()
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.geometry("300x150+220+170")
        dialog.transient(self)
        dialog.configure(bg=theme["window_bg"])
        dpi_var = tk.StringVar(value="300")
        transparent_var = tk.BooleanVar(value=False)
        result: dict[str, tuple[float, bool] | None] = {"value": None}

        body = tk.Frame(dialog, bg=theme["window_bg"], padx=12, pady=10)
        body.pack(fill=tk.BOTH, expand=True)
        tk.Label(body, text="Quality dpi", bg=theme["window_bg"], fg=theme["label"]).grid(
            row=0, column=0, sticky="e", padx=(0, 8), pady=6
        )
        ttk.Entry(body, textvariable=dpi_var, width=10).grid(row=0, column=1, sticky="w", pady=6)
        transparent_check = tk.Checkbutton(
            body,
            text="Transparent background",
            variable=transparent_var,
            bg=theme["window_bg"],
            fg=theme["label"],
            selectcolor=theme["axis_bg"],
            activebackground=theme["window_bg"],
            activeforeground=theme["label"],
        )
        transparent_check.grid(row=1, column=0, columnspan=2, sticky="w", pady=6)
        self.style_checkbutton(transparent_check)

        def accept() -> None:
            try:
                dpi = min(max(float(dpi_var.get().strip()), 72.0), 1200.0)
            except ValueError:
                messagebox.showerror("Invalid Export", "Enter a numeric dpi value.", parent=dialog)
                return
            result["value"] = (dpi, bool(transparent_var.get()))
            dialog.destroy()

        buttons = tk.Frame(body, bg=theme["window_bg"])
        buttons.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Continue", command=accept).pack(side=tk.RIGHT, padx=(0, 8))
        dialog.grab_set()
        self.wait_window(dialog)
        return result["value"]

    def save_figure_png(self, fig: Figure, path: str, dpi: float, transparent: bool) -> None:
        fig.savefig(
            path,
            dpi=dpi,
            facecolor="none" if transparent else fig.get_facecolor(),
            transparent=transparent,
            bbox_inches="tight",
        )

    def save_panel_image(self, panel_id: int, kind: str) -> None:
        panel = self.ordinary_panels.get(panel_id)
        if panel is None:
            return
        fig = panel.crystal_fig if kind == "crystal" else panel.diffraction_fig
        options = self.ask_export_options(f"Export panel {panel_id} {kind}")
        if options is None:
            return
        dpi, transparent = options
        path = filedialog.asksaveasfilename(
            parent=self,
            title=f"Save panel {panel_id} {kind} PNG",
            defaultextension=".png",
            initialfile=f"panel_{panel_id}_{kind}.png",
            filetypes=(("PNG image", "*.png"), ("All files", "*.*")),
        )
        if not path:
            return
        self.save_figure_png(fig, path, dpi, transparent)
        self.status_var.set(f"Saved {kind} image: {path}")

    def save_combo_image(self, combo_id: int) -> None:
        combo = self.combo_panels.get(combo_id)
        if combo is None:
            return
        options = self.ask_export_options(f"Export combo C{combo_id}")
        if options is None:
            return
        dpi, transparent = options
        path = filedialog.asksaveasfilename(
            parent=self,
            title=f"Save combo C{combo_id} PNG",
            defaultextension=".png",
            initialfile=f"combo_C{combo_id}_diffraction.png",
            filetypes=(("PNG image", "*.png"), ("All files", "*.*")),
        )
        if not path:
            return
        self.save_figure_png(combo.diffraction_fig, path, dpi, transparent)
        self.status_var.set(f"Saved combo image: {path}")


def main() -> int:
    app = CrystalDiffractionSimulator()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
