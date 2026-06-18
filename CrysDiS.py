from __future__ import annotations

import io
import importlib.util
import json
import math
import os
import re
import socket
import sys
import tempfile
import warnings
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
from nicegui import native, ui


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


def find_open_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


APP_DIR = resource_dir()
BUNDLED_LIBRARY_PATH = APP_DIR / "custom_crystals_local.json"
USER_DATA_DIR = app_data_dir()
USER_LIBRARY_PATH = USER_DATA_DIR / "custom_crystals.json"
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
DEFAULT_THICKNESS_NM = 10.0
DEFAULT_MAX_HKL = 7
DEFAULT_CAMERA_LENGTH_MM = 200.0
DIFFRACTION_BASE_LIMIT_NM_INV = 16.0
DEFAULT_SPOT_INTENSITY_THRESHOLD = 0.001
MIN_SPOT_INTENSITY_THRESHOLD = 1e-4
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

ELEMENTS = [
    "Ag",
    "Al",
    "As",
    "Au",
    "Bi",
    "C",
    "Cd",
    "Co",
    "Cr",
    "Cu",
    "Fe",
    "Ga",
    "Ge",
    "Hf",
    "Hg",
    "In",
    "Ir",
    "Mg",
    "Mn",
    "Mo",
    "N",
    "Nb",
    "Ni",
    "O",
    "Os",
    "Pb",
    "Pd",
    "Pt",
    "Re",
    "Rh",
    "Ru",
    "Sb",
    "Sc",
    "Si",
    "Sn",
    "Ta",
    "Te",
    "Ti",
    "V",
    "W",
    "Y",
    "Zn",
    "Zr",
]

FALLBACK_ATOMIC_NUMBERS = {
    "H": 1,
    "Ag": 47,
    "C": 6,
    "N": 7,
    "O": 8,
    "Al": 13,
    "As": 33,
    "Au": 79,
    "Bi": 83,
    "Cd": 48,
    "Co": 27,
    "Cr": 24,
    "Cu": 29,
    "Fe": 26,
    "Ga": 31,
    "Ge": 32,
    "Hf": 72,
    "Hg": 80,
    "In": 49,
    "Ir": 77,
    "Mg": 12,
    "Mn": 25,
    "Mo": 42,
    "Nb": 41,
    "Ni": 28,
    "Os": 76,
    "Pb": 82,
    "Pd": 46,
    "Pt": 78,
    "Re": 75,
    "Rh": 45,
    "Ru": 44,
    "Sb": 51,
    "Sc": 21,
    "Si": 14,
    "Sn": 50,
    "Ta": 73,
    "Te": 52,
    "Ti": 22,
    "V": 23,
    "W": 74,
    "Y": 39,
    "Zn": 30,
    "Zr": 40,
}


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
    "Al": "#AEB6BF",
    "C": "#30323D",
    "Co": "#4D79D8",
    "Cr": "#4ECDC4",
    "Cu": "#D9822B",
    "Fe": "#9B5DE5",
    "Mg": "#F4B942",
    "Mn": "#C77DFF",
    "Mo": "#7D8597",
    "N": "#5C7CFA",
    "Ni": "#10B7A5",
    "O": "#EF476F",
    "Si": "#F77F00",
    "Ti": "#8E9AAF",
    "V": "#63A375",
    "W": "#5E6472",
    "Zn": "#8AB6D6",
}

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
VECTOR_COLORS = ["#E63946", "#F4A261", "#2A9D8F", "#577590", "#B5179E", "#80ED99"]
PLANE_FILL_TEXTURE = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4////fwAJ+wP9KobjigAAAABJRU5ErkJggg=="
)
DEFAULT_DIFFRACTION_COLORS = {
    "FCC": "#31F7F1",
    "BCC": "#F77F00",
    "HCP": "#B985FF",
}


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
    scale_nm: float
    limit: float


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
    zone_text: str = "100"
    plane_text: str = ""
    vector_text: str = ""
    rotation_text: str = ""
    diffraction_color: str = DEFAULT_DIFFRACTION_COLORS["FCC"]
    view_vector: np.ndarray = field(default_factory=lambda: np.array([1.0, 0.0, 0.0]))
    roll: float = 0.0
    applied_zone_text: str = ""


@dataclass
class ComboPanelState:
    combo_id: int
    source_panel_ids: list[int] = field(default_factory=list)
    selected_panel_id: int | None = None
    bind_motion: bool = False


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


def space_group_symbol(value: str | None) -> str:
    text = str(value or "P1").strip()
    if ":" in text:
        text = text.split(":", 1)[1].strip()
    text = text.strip("'\"")
    compact = text.replace(" ", "") or "P1"
    aliases = {
        "P63/mmc": "P6_3/mmc",
        "P63/m": "P6_3/m",
        "P63mc": "P6_3mc",
        "P63cm": "P6_3cm",
        "C12/m1": "C2/m",
        "C1m1": "Cm",
    }
    return aliases.get(compact, compact)


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
    return None


def declared_space_group_from_cif_block(block: dict[str, Any]) -> str:
    number = cif_block_value(block, "_symmetry_Int_Tables_number", "_space_group_IT_number")
    try:
        if number is not None and int(str(number).strip("'\"")) > 0:
            return space_group_symbol_from_number(int(str(number).strip("'\"")))
    except ValueError:
        pass
    symbol = cif_block_value(block, "_symmetry_space_group_name_H-M", "_space_group_name_H-M_alt")
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
    wrapped[np.isclose(wrapped, 1.0, atol=tolerance) | np.isclose(wrapped, 0.0, atol=tolerance)] = 0.0
    return wrapped


def expanded_sites(definition: CrystalDefinition) -> list[AtomicSite]:
    symbol = space_group_symbol(definition.space_group)
    if symbol in {"", "P1", "1"}:
        return [AtomicSite(**asdict(site)) for site in definition.sites]

    try:
        from pymatgen.symmetry.groups import SpaceGroup

        space_group = SpaceGroup.from_int_number(int(symbol)) if symbol.isdigit() else SpaceGroup(symbol)
        operations = space_group.symmetry_ops
    except Exception:
        return [AtomicSite(**asdict(site)) for site in definition.sites]

    expanded: list[AtomicSite] = []
    seen: set[tuple[str, int, int, int]] = set()
    for site in definition.sites:
        base_frac = snap_fractional(site.fractional)
        for operation in operations:
            frac = snap_fractional(np.mod(operation.operate(base_frac), 1.0))
            frac[np.isclose(frac, 1.0, atol=1e-7)] = 0.0
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
    for char in cleaned:
        if char == "+":
            sign = 1
        elif char == "-":
            sign = -1
        elif char.isdigit():
            values.append(sign * int(char))
            sign = 1
    return values


def parse_index_values(text: str) -> tuple[int, ...]:
    text = normalize_text(text).strip("[](){}<>")
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


def mixed_occupancy_display_sites(sites: list[AtomicSite], tolerance: float = 1e-6) -> list[AtomicSite]:
    grouped: dict[tuple[int, int, int], list[AtomicSite]] = {}
    for site in sites:
        frac = wrap_fractional(site.fractional, tolerance=tolerance)
        key = tuple(int(round(float(value) / tolerance)) for value in frac)
        grouped.setdefault(key, []).append(site)

    mixed_sites: list[AtomicSite] = []
    for group in grouped.values():
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
                rgb += weight * np.array(color_to_rgb(color_for_site(site)), dtype=float)
                elements.append(site.element.strip().capitalize())
                if site.label:
                    labels.append(site.label)
            rgb = np.clip(np.round(255.0 * rgb / total_occupancy), 0, 255).astype(int)
            mixed_color = f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
            element = "+".join(dict.fromkeys(elements)) or representative.element
            label = "/".join(dict.fromkeys(labels))
        else:
            mixed_color = color_for_site(representative)
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
                    )
                )

    all_points = [point for edge in display_edges for point in edge]
    all_points.extend(atom.position for atom in display_atoms)
    limit = max(1.25, float(np.max(np.abs(np.array(all_points)))) * 1.35 if all_points else 1.25)
    return CrystalModel(
        definition=definition,
        expanded_sites=model_sites,
        lattice=lattice,
        reciprocal=reciprocal,
        display_lattice=display_lattice,
        display_origin=display_origin,
        display_edges=display_edges,
        display_atoms=display_atoms,
        scale_nm=scale_nm,
        limit=limit,
    )


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
    scale = max(float(np.max(np.abs(components))), 1.0)
    delta_fractional = components / scale
    start_fractional = np.where(delta_fractional < 0.0, -delta_fractional, 0.0)
    end_fractional = start_fractional + delta_fractional
    start = model.display_origin + start_fractional @ model.display_lattice
    end = model.display_origin + end_fractional @ model.display_lattice
    return start, end


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


def integer_zone_axis_from_view(model: CrystalModel, view_vector: np.ndarray, max_index: int = 6) -> tuple[int, int, int]:
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
        candidate = normalize_vector(np.array(candidate_axis, dtype=float) @ model.lattice)
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
    max_index: int = 6,
    use_hex_four_index: bool = False,
) -> str:
    axis = integer_zone_axis_from_view(model, view_vector, max_index=max_index)
    view = normalize_vector(view_vector)
    axis_vector = normalize_vector(np.array(axis, dtype=float) @ model.lattice)
    approximate = True
    if view is not None and axis_vector is not None:
        angle = math.degrees(math.acos(min(max(abs(float(np.dot(view, axis_vector))), -1.0), 1.0)))
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
    if not allow_multiple:
        groups = groups[:1]

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
    polygon = intersect_plane_with_edges(model.display_edges, normal, constant)
    if len(polygon) < 3:
        vertices = np.array([point for edge in model.display_edges for point in edge], dtype=float)
        projected = vertices @ normal
        constant = float(0.5 * (projected.min() + projected.max()))
        polygon = intersect_plane_with_edges(model.display_edges, normal, constant)
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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build a scale bar for the diffraction panel.

    In detector/camera display mode, the plot coordinates are detector-plane
    distances in mm, but the label is still reported as reciprocal-space length
    in nm^-1.  reciprocal_units_per_plot_unit converts one plotted unit into
    nm^-1; for detector coordinates it is 1 / (L * lambda).
    """
    reciprocal_units_per_plot_unit = max(float(reciprocal_units_per_plot_unit), 1e-12)
    reciprocal_limit = max(float(limit) * reciprocal_units_per_plot_unit, 1e-9)
    bar_reciprocal = choose_scale_bar(reciprocal_limit)
    bar_plot = bar_reciprocal / reciprocal_units_per_plot_unit
    x0 = -0.94 * limit
    y0 = -0.91 * limit
    tick = 0.022 * limit
    line = {"type": "line", "xref": "x", "yref": "y", "line": {"color": "#F7FAFC", "width": 3}}
    shapes = [
        {**line, "x0": x0, "x1": x0 + bar_plot, "y0": y0, "y1": y0},
        {**line, "x0": x0, "x1": x0, "y0": y0 - tick, "y1": y0 + tick, "line": {"color": "#F7FAFC", "width": 2}},
        {
            **line,
            "x0": x0 + bar_plot,
            "x1": x0 + bar_plot,
            "y0": y0 - tick,
            "y1": y0 + tick,
            "line": {"color": "#F7FAFC", "width": 2},
        },
    ]
    annotations = [
        {
            "x": x0 + bar_plot * 0.5,
            "y": y0 + 0.055 * limit,
            "xref": "x",
            "yref": "y",
            "text": f"{bar_reciprocal:g} nm<sup>-1</sup>",
            "showarrow": False,
            "font": {"color": "#F7FAFC", "size": 11},
            "xanchor": "center",
            "yanchor": "bottom",
        }
    ]
    return shapes, annotations


def diffraction_zone_axis_annotation(limit: float, label: str) -> dict[str, Any]:
    return {
        "x": 0.94 * float(limit),
        "y": -0.91 * float(limit),
        "xref": "x",
        "yref": "y",
        "text": label,
        "showarrow": False,
        "font": {"color": "#F7FAFC", "size": 12},
        "xanchor": "right",
        "yanchor": "bottom",
        "opacity": 0.9,
    }


def empty_diffraction_figure() -> dict[str, Any]:
    return {
        "data": [],
        "layout": {
            "paper_bgcolor": "#050607",
            "plot_bgcolor": "#050607",
            "margin": {"l": 0, "r": 0, "t": 0, "b": 0},
            "xaxis": {"visible": False, "range": [-4, 4], "scaleanchor": "y", "scaleratio": 1, "fixedrange": True},
            "yaxis": {"visible": False, "range": [-4, 4], "fixedrange": True},
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


def fractional_points_match(a: np.ndarray, b: np.ndarray, tolerance: float = SYMMETRY_SITE_TOL) -> bool:
    delta = np.abs(wrap_fractional(np.asarray(a, dtype=float) - np.asarray(b, dtype=float)))
    delta = np.minimum(delta, 1.0 - delta)
    return bool(np.all(delta <= tolerance))


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
    crystal_system = "triclinic"
    declared_space_group = declared_space_group_from_cif_block(cif_block)
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
        repeat_boundary_atoms=True,
        sites=sites,
    )


def color_for_element(element: str) -> str:
    symbol = element.strip().capitalize()
    if symbol in ELEMENT_COLORS:
        return ELEMENT_COLORS[symbol]
    palette = ["#2EC4B6", "#E71D36", "#FF9F1C", "#4D96FF", "#9D4EDD", "#6A994E"]
    return palette[sum(ord(char) for char in symbol) % len(palette)]


def color_for_site(site: AtomicSite | DisplayAtom) -> str:
    color = str(getattr(site, "color", "") or "").strip()
    if re.match(r"^#[0-9a-fA-F]{6}$", color):
        return color
    return color_for_element(site.element)


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
        self.repeat_boundary_atoms = True
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

            with ui.row().classes("items-center gap-2"):
                ui.button("Apply lattice constraints", icon="architecture", on_click=self.apply_lattice_constraints).props(
                    "outline"
                )
                ui.button("Add atom site", icon="add", on_click=self.add_site).props("outline")
                ui.button("Preview symmetry", icon="grain", on_click=self.preview_symmetry).props("outline")

            ui.separator()
            ui.label("Atom sites").classes("text-subtitle2")
            self.site_container = ui.column().classes("full-width gap-2")

            with ui.row().classes("justify-end full-width gap-2"):
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

    def load_definition(self, definition: CrystalDefinition) -> None:
        self.name_input.value = definition.name if definition.name not in DEFAULT_NAMES else f"{definition.name} custom"
        self.system_select.value = definition.lattice_system
        self.symmetry_select.value = space_group_option_for(definition.space_group)
        self.repeat_boundary_atoms = definition.repeat_boundary_atoms
        self.a_input.value = definition.a
        self.b_input.value = definition.b
        self.c_input.value = definition.c
        self.alpha_input.value = definition.alpha
        self.beta_input.value = definition.beta
        self.gamma_input.value = definition.gamma
        self.rebuild_site_rows([AtomicSite(**asdict(site)) for site in definition.sites])

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
        sites = self.read_sites_from_rows()
        sites.append(AtomicSite("Ni", 0.0, 0.0, 0.0, 1.0, ""))
        self.rebuild_site_rows(sites)

    def remove_site(self, index: int) -> None:
        sites = self.read_sites_from_rows()
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

    def rebuild_site_rows(self, sites: list[AtomicSite]) -> None:
        if self.site_container is None:
            return
        self.site_rows = []
        self.site_container.clear()
        with self.site_container:
            for index, site in enumerate(sites or [AtomicSite("Ni", 0.0, 0.0, 0.0, 1.0, "")]):
                with ui.row().classes("site-row"):
                    element = ui.select(ELEMENTS, label="Atom", value=site.element, with_input=True, new_value_mode="add-unique").props(
                        "outlined dense"
                    )
                    x = ui.number("x", value=site.x, step=0.01).props("outlined dense")
                    y = ui.number("y", value=site.y, step=0.01).props("outlined dense")
                    z = ui.number("z", value=site.z, step=0.01).props("outlined dense")
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

    def read_sites_from_rows(self) -> list[AtomicSite]:
        sites = []
        for row in self.site_rows:
            element = str(row["element"].value or "X").strip().capitalize()
            sites.append(
                AtomicSite(
                    element=element,
                    x=float(row["x"].value or 0.0),
                    y=float(row["y"].value or 0.0),
                    z=float(row["z"].value or 0.0),
                    occupancy=float(row["occupancy"].value if row["occupancy"].value is not None else 1.0),
                    label=str(row["label"].value or ""),
                    color=str(row["color"].value or ""),
                )
            )
        return sites

    def read_definition(self) -> CrystalDefinition:
        definition = CrystalDefinition(
            name=str(self.name_input.value or "Customized crystal").strip(),
            lattice_system=str(self.system_select.value or "triclinic").lower(),
            a=float(self.a_input.value or 0.35),
            b=float(self.b_input.value or self.a_input.value or 0.35),
            c=float(self.c_input.value or self.a_input.value or 0.35),
            alpha=float(self.alpha_input.value or 90.0),
            beta=float(self.beta_input.value or 90.0),
            gamma=float(self.gamma_input.value or 90.0),
            space_group=space_group_symbol(self.symmetry_select.value),
            repeat_boundary_atoms=self.repeat_boundary_atoms,
            sites=self.read_sites_from_rows(),
        )
        lattice_matrix(definition)
        if not definition.sites:
            raise ValueError("add at least one atom site")
        return definition

    def save_edited_structure(self) -> None:
        try:
            definition = self.read_definition()
            saved = self.simulator.library.save_edited(
                definition,
                self.scope_select.value or "Project local library",
                self.original_definition_name,
            )
        except ValueError as exc:
            ui.notify(str(exc), type="negative")
            return
        self.simulator.set_status(f"Saved edited structure {saved.name} to {self.scope_select.value}")
        self.simulator.refresh_library(saved.name, target_panel_id=self.target_panel_id)
        self.simulator.refresh_crystal_list()
        self.dialog.close()

    def save_as_new_structure(self) -> None:
        try:
            definition = self.read_definition()
            saved = self.simulator.library.save_new(definition, self.scope_select.value or "Project local library")
        except ValueError as exc:
            ui.notify(str(exc), type="negative")
            return
        self.simulator.set_status(f"Saved new structure {saved.name} to {self.scope_select.value}")
        self.simulator.refresh_library(saved.name, target_panel_id=self.target_panel_id)
        self.simulator.refresh_crystal_list()
        self.dialog.close()


class PanelController:
    def __init__(self, simulator: "SimulatorApp", state: PanelState) -> None:
        self.simulator = simulator
        self.state = state
        self.card = None
        self.scene = None
        self.diffraction = None
        self.crystal_select = None
        self.zone_input = None
        self.plane_input = None
        self.vector_input = None
        self.rotation_input = None
        self.download_dialog = None
        self.scale_bar_line = None
        self.scale_bar_label = None
        self.scale_bar_container = None
        self.scale_timer = None
        self.current_model: CrystalModel | None = None

    def build(self) -> None:
        with ui.card().classes(f"comparison-panel comparison-panel-{self.state.panel_id}") as self.card:
            with ui.element("div").classes("panel-toolbar"):
                ui.label(str(self.state.panel_id)).classes("panel-number")
                self.crystal_select = ui.select(
                    self.simulator.library.options(),
                    label="Crystal",
                    value=self.state.crystal_name,
                    with_input=True,
                    on_change=self.on_crystal_changed,
                ).props("outlined dense").classes("panel-crystal")
                self.zone_input = ui.input("Zone axis", value=self.state.zone_text, on_change=lambda _: self.apply()).props(
                    "outlined dense"
                ).classes("panel-index panel-zone")
                self.zone_input.on("keydown.enter", self.apply_from_browser)
                self.plane_input = ui.input("Plane", value=self.state.plane_text, on_change=lambda _: self.apply()).props(
                    "outlined dense"
                ).classes("panel-index panel-plane")
                self.plane_input.on("keydown.enter", self.apply_from_browser)
                self.vector_input = ui.input(
                    "Vector", value=self.state.vector_text, on_change=lambda _: self.apply()
                ).props("outlined dense").classes("panel-vector")
                self.vector_input.on("keydown.enter", self.apply_from_browser)
                self.rotation_input = ui.input(
                    "Rotation", value=self.state.rotation_text
                ).props("outlined dense").classes("panel-rotation").tooltip(
                    "Use 110/45 or 110 45. Use 45 ccw or 45 cw for in-plane rotation."
                )
                self.rotation_input.on("keydown.enter", self.apply_from_browser)
                ui.button("Apply", on_click=self.apply_from_browser).props("unelevated dense").classes(
                    "panel-apply-button"
                )
                ui.button("Sync", on_click=self.sync_from_scene).props("outline dense").classes(
                    "panel-sync-button"
                ).tooltip("Sync diffraction to the current 3D crystal view")
                ui.button(icon="photo_camera", on_click=self.open_download_dialog).props("flat round dense").classes(
                    "panel-download-button"
                ).tooltip("Download images")
                ui.button(icon="edit", on_click=self.open_builder).props("flat round dense").classes("panel-edit-button").tooltip(
                    "Edit crystal"
                )
                if len(self.simulator.panel_states) > 1:
                    ui.button(icon="close", on_click=lambda: self.simulator.remove_panel(self.state.panel_id)).props(
                        "flat round dense"
                    ).classes("panel-close-button").tooltip("Remove panel")

            with ui.element("div").classes("visual-stack"):
                with ui.element("div").classes("scene-wrap"):
                    self.scene = ui.scene(
                        width=440,
                        height=280,
                        grid=False,
                        background_color="#0B0F14",
                        camera=ui.scene.perspective_camera(fov=REAL_SCENE_FOV_DEGREES, near=0.1, far=5000),
                    ).classes("real-scene")
                    with ui.element("div").classes("real-scale-bar") as self.scale_bar_container:
                        self.scale_bar_line = ui.element("div").classes("real-scale-line")
                        self.scale_bar_label = ui.label("1 nm").classes("real-scale-label")
                self.diffraction = ui.plotly(empty_diffraction_figure()).classes("diffraction-plot")
            self.scale_timer = ui.timer(0.7, self.update_scene_scale_bar)

        self.apply(initial=True)

    def on_crystal_changed(self) -> None:
        if self.crystal_select.value == CUSTOM_SENTINEL:
            self.crystal_select.value = self.state.crystal_name
            self.crystal_select.update()
            self.open_builder()
            return
        self.state.plane_text = ""
        self.state.vector_text = ""
        self.state.applied_zone_text = ""
        if self.plane_input is not None:
            self.plane_input.value = ""
        if self.vector_input is not None:
            self.vector_input.value = ""
        self.apply()

    def open_builder(self) -> None:
        self.simulator.builder.open(
            self.simulator.library.get(self.state.crystal_name),
            target_panel_id=self.state.panel_id,
            mode="edit",
        )

    def render_crystal_png(
        self,
        dpi: float,
        transparent_background: bool = False,
        view_vector: np.ndarray | None = None,
        roll: float | None = None,
    ) -> bytes:
        import matplotlib

        matplotlib.use("Agg", force=True)
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from matplotlib.patches import Polygon

        model = self.current_model or self.simulator.model_for(self.state.crystal_name)
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
        visible_points.extend(point for edge in model.display_edges for point in edge)
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

        dpi = min(max(float(dpi or 300), 72.0), 1200.0)
        background_color = (0.0, 0.0, 0.0, 0.0) if transparent_background else "#0B0F14"
        fig = Figure(figsize=(4.6, 3.6), dpi=dpi, facecolor=background_color)
        FigureCanvasAgg(fig)
        ax = fig.add_axes([0, 0, 1, 1], facecolor=background_color)
        ax.set_aspect("equal", adjustable="box")
        ax.set_axis_off()
        ax.set_xlim(center_x - width / 2.0, center_x + width / 2.0)
        ax.set_ylim(center_y - height / 2.0, center_y + height / 2.0)

        plane_palette = self.simulator.plane_palette()
        vector_palette = self.simulator.vector_palette()
        for index, (_plane, polygon) in enumerate(plane_polygons):
            color = plane_palette[index % len(plane_palette)]
            projected = project_many(polygon)
            ax.add_patch(
                Polygon(
                    projected,
                    closed=True,
                    facecolor=color,
                    edgecolor=color,
                    linewidth=1.1,
                    alpha=0.35,
                    zorder=1,
                )
            )

        for start, end in model.display_edges:
            x0, y0 = project(start)
            x1, y1 = project(end)
            ax.plot([x0, x1], [y0, y1], color="#7A8796", linewidth=1.25, alpha=0.82, zorder=2)

        atoms = sorted(model.display_atoms, key=lambda atom: float(np.dot(atom.position, view)))
        atom_edge_color = (0.0, 0.0, 0.0, 0.28) if transparent_background else "#0B0F14"
        for atom in atoms:
            x, y = project(atom.position)
            radius_factor = 0.45 + 0.55 * max(atom.occupancy, 0.12) ** (1.0 / 3.0)
            size = 160.0 * radius_factor * radius_factor
            ax.scatter(
                [x],
                [y],
                s=size,
                c=[color_for_site(atom)],
                alpha=0.58 + 0.42 * atom.occupancy,
                edgecolors=atom_edge_color,
                linewidths=0.4,
                zorder=4,
            )

        for index, (vector, start, end) in enumerate(vector_segments):
            color = vector_palette[index % len(vector_palette)]
            x0, y0 = project(start)
            x1, y1 = project(end)
            linestyle = "--" if vector.is_reciprocal else "-"
            ax.annotate(
                "",
                xy=(x1, y1),
                xytext=(x0, y0),
                arrowprops={
                    "arrowstyle": "-|>",
                    "color": color,
                    "linewidth": 2.4,
                    "linestyle": linestyle,
                    "mutation_scale": 18,
                    "shrinkA": 0,
                    "shrinkB": 0,
                    "alpha": 0.95,
                },
                zorder=5,
            )
            if self.simulator.show_crystal_annotations():
                ax.text(
                    x1 + 0.025 * width,
                    y1 + 0.025 * height,
                    vector.label,
                    color=color,
                    fontsize=9,
                    weight="bold",
                    ha="left",
                    va="center",
                    zorder=6,
                )

        if self.simulator.show_crystal_annotations():
            for index, (plane, polygon) in enumerate(plane_polygons):
                color = plane_palette[index % len(plane_palette)]
                x, y = project(np.mean(polygon, axis=0))
                ax.text(x, y, plane.label, color=color, fontsize=9, weight="bold", ha="center", va="center", zorder=6)

        if self.simulator.show_scale_bars():
            visible_nm = max(width * model.scale_nm, 1e-9)
            bar_nm = choose_scale_bar(visible_nm)
            bar_display = bar_nm / max(model.scale_nm, 1e-9)
            x0 = center_x - width / 2.0 + 0.07 * width
            y0 = center_y - height / 2.0 + 0.10 * height
            ax.plot([x0, x0 + bar_display], [y0, y0], color="#F7FAFC", linewidth=2.4, zorder=10)
            ax.text(
                x0,
                y0 - 0.035 * height,
                f"{bar_nm:g} nm",
                color="#F7FAFC",
                fontsize=9,
                weight="bold",
                ha="left",
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
        self.download_dialog = ui.dialog()
        with self.download_dialog, ui.card().classes("download-card"):
            with ui.row().classes("items-center justify-between full-width"):
                ui.label(f"Download panel {self.state.panel_id}").classes("text-h6")
                ui.button(icon="close", on_click=self.download_dialog.close).props("flat round dense").tooltip("Close")
            crystal_checkbox = ui.checkbox("Real-space crystal", value=True).props("dense")
            diffraction_checkbox = ui.checkbox("Diffraction pattern", value=True).props("dense")
            transparent_checkbox = ui.checkbox("Transparent background", value=False).props("dense")
            dpi_input = ui.number("Quality", value=300, min=72, max=1200, step=50, suffix="dpi").props("outlined dense")
            with ui.row().classes("justify-end full-width"):
                ui.button("Cancel", on_click=self.download_dialog.close).props("flat dense")
                ui.button(
                    "Download",
                    icon="download",
                    on_click=lambda: self.download_images(
                        bool(crystal_checkbox.value),
                        bool(diffraction_checkbox.value),
                        float(dpi_input.value or 300),
                        bool(transparent_checkbox.value),
                    ),
                ).props("unelevated dense")
        self.download_dialog.open()

    async def download_images(
        self,
        include_crystal: bool,
        include_diffraction: bool,
        dpi: float,
        transparent_background: bool = False,
    ) -> None:
        if not include_crystal and not include_diffraction:
            ui.notify("Choose at least one image to download", type="warning")
            return
        dpi = min(max(float(dpi or 300), 72.0), 1200.0)
        crystal_downloaded = False
        if include_crystal:
            try:
                live_view, live_roll = await self.live_scene_orientation()
                transparent_suffix = "transparent_" if transparent_background else ""
                ui.download(
                    self.render_crystal_png(
                        dpi,
                        transparent_background=transparent_background,
                        view_vector=live_view,
                        roll=live_roll,
                    ),
                    f"panel_{self.state.panel_id}_crystal_{transparent_suffix}{round(dpi)}dpi.png",
                    media_type="image/png",
                )
                crystal_downloaded = True
            except Exception as exc:
                ui.notify(f"Crystal export failed: {exc}", type="negative")
                if not include_diffraction:
                    return
        if not include_diffraction:
            if self.download_dialog is not None:
                self.download_dialog.close()
            self.simulator.set_status(f"Panel {self.state.panel_id}: downloaded image export")
            return

        selector = f".comparison-panel-{self.state.panel_id}"
        script = f"""
        const root = document.querySelector({json.dumps(selector)});
        const panelName = {json.dumps(f"panel_{self.state.panel_id}")};
        const dpi = {float(dpi):.6f};
        const scale = Math.max(1, dpi / 150);
        const transparentBackground = {json.dumps(bool(transparent_background))};

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
                    width: Math.max(1, Math.round(rect.width)),
                    height: Math.max(1, Math.round(rect.height)),
                    scale,
                }});
            }} finally {{
                if (transparentBackground) {{
                    await window.Plotly.relayout(plot, {{
                        paper_bgcolor: originalPaper || '#050607',
                        plot_bgcolor: originalPlot || '#050607',
                    }});
                }}
            }}
            const transparentSuffix = transparentBackground ? 'transparent_' : '';
            saveDataUrl(dataUrl, `${{panelName}}_diffraction_${{transparentSuffix}}${{Math.round(dpi)}}dpi.png`);
            return true;
        }}

        return await downloadDiffraction();
        """
        try:
            ok = await ui.run_javascript(script, timeout=20.0)
        except Exception as exc:
            ui.notify(f"Download failed: {exc}", type="negative")
            return
        if ok or crystal_downloaded:
            if self.download_dialog is not None:
                self.download_dialog.close()
            self.simulator.set_status(f"Panel {self.state.panel_id}: downloaded image export")
        else:
            ui.notify("Could not capture the selected image", type="warning")

    async def apply_from_browser(self) -> None:
        rotation_text = self.state.rotation_text
        values: dict[str, Any] = {}
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
            values = {}
        if isinstance(values, dict):
            if self.zone_input is not None:
                self.zone_input.value = str(values.get("zone", self.zone_input.value or ""))
            if self.plane_input is not None:
                self.plane_input.value = str(values.get("plane", self.plane_input.value or ""))
            if self.vector_input is not None:
                self.vector_input.value = str(values.get("vector", self.vector_input.value or ""))
            rotation_text = str(values.get("rotation", rotation_text or ""))
        elif self.rotation_input is not None:
            try:
                rotation_text = str(self.rotation_input.value or self.state.rotation_text)
            except Exception:
                rotation_text = self.rotation_input.value or self.state.rotation_text
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

    def apply(self, initial: bool = False, rotation_text_override: str | None = None) -> None:
        old_view = self.state.view_vector.copy()
        old_roll = float(self.state.roll)
        if self.crystal_select is not None and self.crystal_select.value != CUSTOM_SENTINEL:
            self.state.crystal_name = self.crystal_select.value or self.state.crystal_name
        self.state.zone_text = self.zone_input.value if self.zone_input is not None else self.state.zone_text
        self.state.plane_text = self.plane_input.value if self.plane_input is not None else self.state.plane_text
        self.state.vector_text = self.vector_input.value if self.vector_input is not None else self.state.vector_text
        if rotation_text_override is not None:
            self.state.rotation_text = rotation_text_override
        else:
            self.state.rotation_text = self.rotation_input.value if self.rotation_input is not None else self.state.rotation_text

        model = self.simulator.model_for(self.state.crystal_name)
        errors: list[str] = []
        zone_text_changed = initial or self.state.zone_text != self.state.applied_zone_text
        zone: list[ParsedIndex] = []
        if self.state.zone_text.strip():
            zone, zone_errors = parse_indices(self.state.zone_text, model, "direction", allow_multiple=False)
        elif zone_text_changed:
            zone_errors = []
        else:
            zone_errors = []

        if zone_text_changed:
            errors.extend(zone_errors)
            if zone:
                self.state.view_vector = zone[0].vector
                self.state.applied_zone_text = self.state.zone_text
            elif self.state.zone_text.strip():
                errors.append(f"Panel {self.state.panel_id}: keeping previous zone direction")

        rotation_message = ""
        snap_message = ""
        rotation_command, rotation_errors = parse_rotation_command(self.state.rotation_text, model)
        errors.extend(rotation_errors)
        if rotation_command is not None:
            axis = rotation_command.axis
            if axis is None:
                axis = normalize_vector(self.state.view_vector)
            if axis is None:
                errors.append(f"Panel {self.state.panel_id}: rotation axis has zero length")
            else:
                self.state.view_vector, self.state.roll = rotate_orientation(
                    self.state.view_vector,
                    self.state.roll,
                    axis,
                    rotation_command.angle_degrees,
                )
                rotation_message = (
                    f"Panel {self.state.panel_id}: rotated {rotation_command.angle_degrees:g} deg about "
                    f"{rotation_command.axis_label}"
                )
                self.state.rotation_text = ""
                if self.rotation_input is not None:
                    self.rotation_input.value = ""
        elif self.simulator.always_snap_back_view() and zone:
            self.state.view_vector = zone[0].vector
            self.state.roll = 0.0
            self.state.applied_zone_text = self.state.zone_text
            snap_message = f"Panel {self.state.panel_id}: snapped back to {zone[0].label}"
        self.redraw_scene(model)
        self.redraw_diffraction(model)
        if initial:
            self.simulator.refresh_combo_panels()
        else:
            self.simulator.propagate_bound_motion(
                self.state.panel_id,
                old_view,
                old_roll,
                self.state.view_vector,
                self.state.roll,
            )
        if not initial:
            self.simulator.set_status(
                "; ".join(errors[:3]) if errors else (rotation_message or snap_message or f"Panel {self.state.panel_id} updated")
            )

    def redraw_scene(self, model: CrystalModel | None = None) -> None:
        if self.scene is None:
            return
        model = model or self.simulator.model_for(self.state.crystal_name)
        self.current_model = model
        self.scene.clear()
        with self.scene:
            for start, end in model.display_edges:
                self.scene.line(start.tolist(), end.tolist()).material(color="#7A8796", opacity=0.72)

            for atom in model.display_atoms:
                radius = 0.072 * (0.45 + 0.55 * max(atom.occupancy, 0.12) ** (1.0 / 3.0))
                self.scene.sphere(radius=radius, width_segments=32, height_segments=16).move(*atom.position.tolist()).material(
                    color=color_for_site(atom), opacity=0.58 + 0.42 * atom.occupancy
                )

            planes, plane_errors = parse_indices(self.state.plane_text, model, "plane", allow_multiple=True)
            vectors, vector_errors = parse_indices(
                self.state.vector_text,
                model,
                "direction",
                allow_multiple=True,
                allow_reciprocal=True,
            )
            self.draw_planes(model, planes)
            self.draw_vectors(model, vectors)
            if plane_errors or vector_errors:
                self.simulator.set_status("; ".join((plane_errors + vector_errors)[:3]))

        view = normalize_vector(self.state.view_vector)
        if view is None:
            view = np.array([1.0, 0.0, 0.0])
        _u_axis, up_axis = projection_basis(view, self.state.roll)
        distance = calculate_camera_distance(model.limit * 1.08, REAL_SCENE_FOV_DEGREES)
        camera = view * distance
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
        selector = f".comparison-panel-{self.state.panel_id} .scene-wrap"
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

    def set_scale_bar_from_distance(
        self,
        distance: float,
        model: CrystalModel,
        scene_size: tuple[float, float] | None = None,
    ) -> None:
        if self.scale_bar_line is None or self.scale_bar_label is None:
            return
        self.apply_scale_bar_visibility()
        if not self.simulator.show_scale_bars():
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
            self.scale_bar_line.style(replace=f"width: {bar_px:.1f}px")
        else:
            fraction = bar_nm / visible_nm
            self.scale_bar_line.style(replace=f"width: {fraction * 100:.2f}%")
        self.scale_bar_label.set_text(f"{bar_nm:g} nm")

    def apply_scale_bar_visibility(self) -> None:
        if self.scale_bar_container is None:
            return
        self.scale_bar_container.visible = self.simulator.show_scale_bars()
        self.scale_bar_container.update()

    def draw_planes(self, model: CrystalModel, planes: list[ParsedIndex]) -> None:
        if self.scene is None:
            return
        palette = self.simulator.plane_palette()
        for index, plane in enumerate(planes):
            vertices = clipped_plane_polygon(model, plane)
            if vertices is None:
                continue
            color = palette[index % len(palette)]
            centroid = np.mean(vertices, axis=0)
            for start, end in zip(vertices, np.roll(vertices, -1, axis=0)):
                coords = [[start.tolist(), end.tolist()], [centroid.tolist(), centroid.tolist()]]
                self.scene.texture(PLANE_FILL_TEXTURE, coords).material(color=color, opacity=0.36, side="both")
            for start, end in zip(vertices, np.roll(vertices, -1, axis=0)):
                self.scene.line(start.tolist(), end.tolist()).material(color=color, opacity=0.9)
            if self.simulator.show_crystal_annotations():
                label_position = np.mean(vertices, axis=0)
                self.scene.text(plane.label, style=f"color: {color}; font-size: 13px; font-weight: 700;").move(
                    *label_position.tolist()
                )

    def draw_vectors(self, model: CrystalModel, vectors: list[ParsedIndex]) -> None:
        if self.scene is None:
            return
        palette = self.simulator.vector_palette()
        for index, vector in enumerate(vectors):
            color = palette[index % len(palette)]
            if vector.is_reciprocal:
                start, end = reciprocal_segment_for_display(vector.values, model)
                self.draw_arrow(start, end, color, shaft_radius=0.011, head_radius=0.044, opacity=0.78)
                self.draw_reciprocal_markers(start, end, color)
            else:
                start, end = direction_segment_for_display(vector.values, model)
                self.draw_arrow(start, end, color)
            if self.simulator.show_crystal_annotations():
                self.scene.text(vector.label, style=f"color: {color}; font-size: 13px; font-weight: 700;").move(
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
                opacity=0.88,
            )

    def draw_arrow(
        self,
        start: np.ndarray,
        end: np.ndarray,
        color: str,
        shaft_radius: float = 0.018,
        head_radius: float = 0.055,
        opacity: float = 0.95,
    ) -> None:
        if self.scene is None:
            return
        delta = end - start
        length = float(np.linalg.norm(delta))
        if length < 1e-8:
            return
        direction = delta / length
        head_length = min(0.18, length * 0.28)
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
        if self.simulator.current_simulation_method() == SIMULATION_METHOD_PYMATGEN:
            spots = self.simulator.compute_pymatgen_tem_spots(model, self.state.view_vector, self.state.roll)
        else:
            spots = self.simulator.compute_ewald_spots(model, self.state.view_vector, self.state.roll)
        spot_color = dominant_color(model.definition)
        limit = self.simulator.current_diffraction_limit()
        zone_label = (
            zone_axis_label_from_view(
                model,
                self.state.view_vector,
                use_hex_four_index=self.simulator.use_hex_four_index_basis(),
            )
            if self.simulator.show_zone_axis_on_diffraction()
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
        shapes, annotations = (
            diffraction_scale_bar_items(limit, self.simulator.current_reciprocal_units_per_plot_unit())
            if self.simulator.show_scale_bars()
            else ([], [])
        )
        if zone_label:
            annotations.append(diffraction_zone_axis_annotation(limit, zone_label))
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
                    f"Index: {label}<br>Relative intensity: {float(spot[2]):.4f}<br>d-spacing: {d_text}"
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
                        "color": [rgba_css(spot_color, 0.18 + 0.82 * float(value)) for value in intensity],
                        "line": {"width": 0},
                    },
                }
            )
            if self.simulator.show_indices():
                annotations.extend(self.diffraction_index_annotations(spots, limit, labels))
        else:
            annotations.append(
                {
                    "x": 0,
                    "y": 0,
                    "xref": "x",
                    "yref": "y",
                    "text": "No reflections in Ewald condition",
                    "showarrow": False,
                    "font": {"color": "#B8C0CC", "size": 12},
                }
            )
        return {
            "data": data,
            "layout": {
                "paper_bgcolor": "#050607",
                "plot_bgcolor": "#050607",
                "margin": {"l": 0, "r": 0, "t": 0, "b": 0},
                "xaxis": {
                    "visible": False,
                    "range": [-limit, limit],
                    "scaleanchor": "y",
                    "scaleratio": 1,
                    "fixedrange": True,
                    "zeroline": False,
                },
                "yaxis": {
                    "visible": False,
                    "range": [-limit, limit],
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
    def diffraction_index_annotations(spots: np.ndarray, limit: float, labels: list[str]) -> list[dict[str, Any]]:
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
                    "font": {"color": "#F7FAFC", "size": 9},
                    "xanchor": "center",
                    "yanchor": "bottom",
                    "opacity": 0.88,
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
        self.diffraction = None
        self.download_dialog = None
        self.bind_checkbox = None

    def build(self) -> None:
        self.simulator.repair_combo_sources(self.state)
        with ui.card().classes(f"comparison-panel combo-panel combo-panel-{self.state.combo_id}") as self.card:
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
                ).props("dense").classes("combo-bind-checkbox")
                ui.button(icon="photo_camera", on_click=self.open_download_dialog).props("flat round dense").classes(
                    "combo-download-button"
                ).tooltip("Download combo diffraction")
                ui.button(icon="close", on_click=lambda: self.simulator.remove_combo_panel(self.state.combo_id)).props(
                    "flat round dense"
                ).classes("panel-close-button").tooltip("Remove combo panel")

            with ui.element("div").classes("combo-stack"):
                self.source_list_container = ui.element("div").classes("combo-source-list")
                self.diffraction = ui.plotly(empty_diffraction_figure()).classes("diffraction-plot combo-diffraction-plot")

        self.refresh()

    def open_download_dialog(self) -> None:
        self.download_dialog = ui.dialog()
        with self.download_dialog, ui.card().classes("download-card"):
            with ui.row().classes("items-center justify-between full-width"):
                ui.label(f"Download combo C{self.state.combo_id}").classes("text-h6")
                ui.button(icon="close", on_click=self.download_dialog.close).props("flat round dense").tooltip("Close")
            transparent_checkbox = ui.checkbox("Transparent background", value=False).props("dense")
            dpi_input = ui.number("Quality", value=300, min=72, max=1200, step=50, suffix="dpi").props("outlined dense")
            with ui.row().classes("justify-end full-width"):
                ui.button("Cancel", on_click=self.download_dialog.close).props("flat dense")
                ui.button(
                    "Download",
                    icon="download",
                    on_click=lambda: self.download_diffraction_image(
                        float(dpi_input.value or 300),
                        bool(transparent_checkbox.value),
                    ),
                ).props("unelevated dense")
        self.download_dialog.open()

    async def download_diffraction_image(self, dpi: float, transparent_background: bool = False) -> None:
        dpi = min(max(float(dpi or 300), 72.0), 1200.0)
        selector = f".combo-panel-{self.state.combo_id}"
        script = f"""
        const root = document.querySelector({json.dumps(selector)});
        const panelName = {json.dumps(f"combo_C{self.state.combo_id}")};
        const dpi = {float(dpi):.6f};
        const scale = Math.max(1, dpi / 150);
        const transparentBackground = {json.dumps(bool(transparent_background))};

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
                    width: Math.max(1, Math.round(rect.width)),
                    height: Math.max(1, Math.round(rect.height)),
                    scale,
                }});
            }} finally {{
                if (transparentBackground) {{
                    await window.Plotly.relayout(plot, {{
                        paper_bgcolor: originalPaper || '#050607',
                        plot_bgcolor: originalPlot || '#050607',
                    }});
                }}
            }}
            const transparentSuffix = transparentBackground ? 'transparent_' : '';
            saveDataUrl(dataUrl, `${{panelName}}_diffraction_${{transparentSuffix}}${{Math.round(dpi)}}dpi.png`);
            return true;
        }}

        return await downloadDiffraction();
        """
        try:
            ok = await ui.run_javascript(script, timeout=20.0)
        except Exception as exc:
            ui.notify(f"Download failed: {exc}", type="negative")
            return
        if ok:
            if self.download_dialog is not None:
                self.download_dialog.close()
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
        try:
            index = self.state.source_panel_ids.index(panel_id)
        except ValueError:
            return
        new_index = min(max(index + direction, 0), len(self.state.source_panel_ids) - 1)
        if new_index == index:
            return
        self.state.source_panel_ids[index], self.state.source_panel_ids[new_index] = (
            self.state.source_panel_ids[new_index],
            self.state.source_panel_ids[index],
        )
        self.refresh()

    def refresh(self) -> None:
        self.simulator.repair_combo_sources(self.state)
        options = self.source_options()
        if self.source_select is not None:
            self.source_select.options = options
            if self.state.selected_panel_id not in options:
                self.state.selected_panel_id = next(iter(options), None)
            self.source_select.value = self.state.selected_panel_id
            self.source_select.update()
        if self.bind_checkbox is not None:
            self.bind_checkbox.value = self.state.bind_motion
            self.bind_checkbox.update()
        self.refresh_source_list()
        self.redraw_diffraction()

    def refresh_source_list(self) -> None:
        if self.source_list_container is None:
            return
        sources = self.selected_sources()
        self.source_list_container.clear()
        with self.source_list_container:
            with ui.element("div").classes("combo-source-header"):
                ui.label("Panel")
                ui.label("Crystal")
                ui.label("Zone")
                ui.label("")
            for index, source in enumerate(sources):
                model = self.simulator.model_for(source.crystal_name)
                zone = zone_axis_label_from_view(
                    model,
                    source.view_vector,
                    use_hex_four_index=self.simulator.use_hex_four_index_basis(),
                ).replace(" zone", "")
                with ui.element("div").classes("combo-source-row"):
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
        shapes, annotations = (
            diffraction_scale_bar_items(limit, self.simulator.current_reciprocal_units_per_plot_unit())
            if self.simulator.show_scale_bars()
            else ([], [])
        )
        if zone_label:
            annotations.append(diffraction_zone_axis_annotation(limit, zone_label))
        data: list[dict[str, Any]] = []
        for source in reversed(sources):
            model = self.simulator.model_for(source.crystal_name)
            if self.simulator.current_simulation_method() == SIMULATION_METHOD_PYMATGEN:
                spots = self.simulator.compute_pymatgen_tem_spots(model, source.view_vector, source.roll)
            else:
                spots = self.simulator.compute_ewald_spots(model, source.view_vector, source.roll)
            if not len(spots):
                continue
            intensity = spots[:, 2]
            spot_color = dominant_color(model.definition)
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
                    f"<br>Index: {label}<br>Relative intensity: {float(spot[2]):.4f}<br>d-spacing: {d_text}"
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
                        "color": [rgba_css(spot_color, 0.14 + 0.70 * float(value)) for value in intensity],
                        "line": {"width": 0},
                    },
                }
            )
            if self.simulator.show_indices():
                annotations.extend(PanelController.diffraction_index_annotations(spots, limit, labels))
        if not data:
            annotations.append(
                {
                    "x": 0,
                    "y": 0,
                    "xref": "x",
                    "yref": "y",
                    "text": "No source reflections to overlay",
                    "showarrow": False,
                    "font": {"color": "#B8C0CC", "size": 12},
                }
            )
        return {
            "data": data,
            "layout": {
                "paper_bgcolor": "#050607",
                "plot_bgcolor": "#050607",
                "margin": {"l": 0, "r": 0, "t": 0, "b": 0},
                "xaxis": {
                    "visible": False,
                    "range": [-limit, limit],
                    "scaleanchor": "y",
                    "scaleratio": 1,
                    "fixedrange": True,
                    "zeroline": False,
                },
                "yaxis": {"visible": False, "range": [-limit, limit], "fixedrange": True, "zeroline": False},
                "showlegend": False,
                "hovermode": "closest",
                "dragmode": False,
                "shapes": shapes,
                "annotations": annotations,
            },
            "config": {"displayModeBar": False, "responsive": True, "scrollZoom": False},
        }


class SimulatorApp:
    def __init__(self) -> None:
        self.library = CrystalLibrary()
        self.model_cache: dict[tuple[str, str], CrystalModel] = {}
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
        self.show_crystal_annotations_input = None
        self.add_combo_button = None
        self.advanced_dialog = None
        self.intro_dialog = None
        self.palette_dialog = None
        self.palette_vector_container = None
        self.palette_plane_container = None
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
        self.camera_length_input = None
        self.snap_back_input = None
        self.hex_four_index_input = None
        self.auto_sync_input = None
        self.show_zone_axis_input = None
        self.vector_colors = VECTOR_COLORS.copy()
        self.plane_colors = PLANE_COLORS.copy()
        self.builder: CrystalBuilder | None = None

    def build(self) -> None:
        ui.page_title("CrysDiS")
        self.dark_mode = ui.dark_mode(value=True)
        self.add_styles()
        with ui.header().classes("app-header items-center"):
            ui.label("CrysDiS").classes("app-title")
            ui.button("Intro", icon="help_outline", on_click=self.open_intro_dialog).props("flat dense").classes("intro-button")
            ui.space()
            self.show_zone_axis_input = ui.checkbox(
                "Show current zone",
                value=False,
                on_change=lambda _: self.refresh_diffractions(),
            ).classes("top-checkbox")
            self.show_indices_input = ui.checkbox(
                "Show spot indices",
                value=False,
                on_change=lambda _: self.refresh_diffractions(),
            ).classes("top-checkbox")
            self.show_crystal_annotations_input = ui.checkbox(
                "Show crystal annotations",
                value=True,
                on_change=lambda _: self.refresh_crystal_scenes(),
            ).classes("top-checkbox")
            self.show_scale_bar_input = ui.checkbox(
                "Show scale bar",
                value=True,
                on_change=lambda _: self.on_scale_bar_changed(),
            ).classes("top-checkbox")
            ui.button("Advanced", icon="tune", on_click=lambda: self.advanced_dialog.open()).props("flat dense")
            ui.button("Crystal list", icon="format_list_bulleted", on_click=self.open_crystal_list).props("flat dense")
            ui.button("Load CIF", icon="upload_file", on_click=lambda: self.cif_dialog.open()).props("flat dense")
            ui.button("Crystal builder", icon="add_box", on_click=lambda: self.builder.open(mode="new")).props("flat dense")
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
1. Choose a crystal, enter a zone axis such as `100`, `110`, or `0001`, then press `Apply`.
2. Add planes like `100 123` and vectors like `110 -1-1-2` in the panel inputs.
3. Use the mouse to rotate the 3D crystal. Press `Sync` to update the diffraction pattern to the current crystal view.
4. Use `Download` to export the crystal view, diffraction pattern, or both.

### Crystals
- Built-in examples include FCC Ni, BCC Fe, and HCP Mg.
- `Load CIF` imports structures from `.cif` files.
- `Crystal builder` lets you create or edit custom structures, set symmetry, lattice parameters, atom sites, occupancies, and atom colors.
- `Crystal list` lets you review, edit, or delete available structures.

### Indices and vectors
- Plane indices use entries like `100`, `1-10`, or `0001`.
- Real-space vectors use entries like `110` or `2-1-10`.
- Reciprocal vectors can be entered as `*100`, `r100`, or `R100`.
- Negative real-space vectors are shifted back into the unit cell for cleaner visualization.

### Diffraction settings
- `Show spot indices` labels diffraction spots.
- `Show current zone` prints the current or nearest zone axis on the diffraction panel.
- Diffraction spot colors are matched to the dominant atom color of the crystal in that panel. Combo panels keep each source pattern in its own panel color so overlapping phases can be distinguished.
- `Advanced` contains simulation method, voltage, thickness, max hkl, camera length, intensity threshold, spot scaling, intensity compression, auto sync, snap-back view, and hexagonal four-index labeling.

### Combo panels
Use `Add combo panel` to overlay diffraction patterns from multiple ordinary panels. This is useful for multiphase comparisons.
Enable `Bind crystal motion` inside a combo panel after manually setting an orientation relationship; later Apply, Sync, or auto-sync motion from any listed panel is applied as the same view-frame motion to the other listed panels.

### Display controls
- `Show scale bar` toggles scale bars in both crystal and diffraction panels.
- `Show crystal annotations` toggles vector and plane labels in the 3D crystal view.
- `Palette for vectors/planes` lets you customize, reorder, add, remove, or reset vector and plane colors.
                """
            ).classes("intro-text")

    def build_advanced_dialog(self) -> None:
        self.advanced_dialog = ui.dialog()
        with self.advanced_dialog, ui.card().classes("advanced-card"):
            with ui.row().classes("items-center justify-between full-width"):
                ui.label("Advanced settings").classes("text-h6")
                ui.button(icon="close", on_click=self.advanced_dialog.close).props("flat round dense").tooltip("Close")
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
                    ).props("outlined dense").tooltip("Accepts decimals or scientific notation, e.g. 1e-4 or 5e-3.")
                    with ui.element("div").classes("advanced-slider-field"):
                        ui.label("Compression factor").classes("advanced-slider-label")
                        self.intensity_compression_input = ui.slider(
                            min=10.0,
                            max=150.0,
                            step=1.0,
                            value=DEFAULT_INTENSITY_COMPRESSION_FACTOR,
                            on_change=lambda _: self.refresh_diffractions(),
                        ).props("label-always").classes("advanced-slider")
                    with ui.element("div").classes("advanced-slider-field"):
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
                    ui.button(
                        "Palette for vectors/planes",
                        icon="palette",
                        on_click=self.open_palette_dialog,
                    ).props("outline dense").classes("advanced-palette-button")
                self.log_box = ui.textarea("Log", value="\n".join(self.status_history)).props(
                    "outlined dense readonly rows=5"
                ).classes("advanced-log")

    def open_palette_dialog(self) -> None:
        self.palette_dialog = None
        self.palette_vector_container = None
        self.palette_plane_container = None
        self.build_palette_dialog()
        self.refresh_palette_dialog()
        self.palette_dialog.open()

    def build_palette_dialog(self) -> None:
        self.palette_dialog = ui.dialog()
        with self.palette_dialog, ui.card().classes("palette-card"):
            with ui.row().classes("items-center justify-between full-width"):
                ui.label("Palette for vectors/planes").classes("text-h6")
                ui.button(icon="close", on_click=self.palette_dialog.close).props("flat round dense").tooltip("Close")
            with ui.row().classes("palette-columns"):
                with ui.column().classes("palette-column"):
                    with ui.row().classes("items-center justify-between full-width"):
                        ui.label("Vectors").classes("palette-title")
                        with ui.row().classes("palette-actions"):
                            ui.button("Set to default", on_click=lambda: self.reset_palette("vector")).props("flat dense")
                            ui.button("Add", icon="add", on_click=lambda: self.add_palette_color("vector")).props("outline dense")
                    self.palette_vector_container = ui.element("div").classes("palette-list")
                with ui.column().classes("palette-column"):
                    with ui.row().classes("items-center justify-between full-width"):
                        ui.label("Planes").classes("palette-title")
                        with ui.row().classes("palette-actions"):
                            ui.button("Set to default", on_click=lambda: self.reset_palette("plane")).props("flat dense")
                            ui.button("Add", icon="add", on_click=lambda: self.add_palette_color("plane")).props("outline dense")
                    self.palette_plane_container = ui.element("div").classes("palette-list")

    def palette_values(self, kind: str) -> list[str]:
        return self.vector_colors if kind == "vector" else self.plane_colors

    def palette_default_values(self, kind: str) -> list[str]:
        return VECTOR_COLORS if kind == "vector" else PLANE_COLORS

    def normalize_palette_color(self, value: str | None, fallback: str) -> str:
        text = str(value or "").strip()
        if re.fullmatch(r"#?[0-9a-fA-F]{6}", text):
            return ("#" + text.lstrip("#")).upper()
        return fallback

    def refresh_palette_dialog(self) -> None:
        self.refresh_palette_list("vector", self.palette_vector_container)
        self.refresh_palette_list("plane", self.palette_plane_container)

    def refresh_palette_list(self, kind: str, container: Any) -> None:
        if container is None:
            return
        palette = self.palette_values(kind)
        container.clear()
        with container:
            for index, color in enumerate(palette):
                with ui.element("div").classes("palette-row"):
                    ui.label(str(index + 1)).classes("palette-index")
                    ui.color_input(
                        value=color,
                        preview=True,
                        on_change=lambda event, k=kind, i=index: self.set_palette_color(k, i, event.value),
                    ).props("outlined dense").classes("palette-color-input")
                    up = ui.button(icon="arrow_upward", on_click=lambda _=None, k=kind, i=index: self.move_palette_color(k, i, -1)).props(
                        "flat round dense"
                    ).tooltip("Move up")
                    down = ui.button(
                        icon="arrow_downward",
                        on_click=lambda _=None, k=kind, i=index: self.move_palette_color(k, i, 1),
                    ).props("flat round dense").tooltip("Move down")
                    delete = ui.button(icon="delete", on_click=lambda _=None, k=kind, i=index: self.remove_palette_color(k, i)).props(
                        "flat round dense color=negative"
                    ).tooltip("Remove color")
                    if index == 0:
                        up.disable()
                    if index == len(palette) - 1:
                        down.disable()
                    if len(palette) <= 1:
                        delete.disable()

    def set_palette_color(self, kind: str, index: int, value: str | None) -> None:
        palette = self.palette_values(kind)
        if not (0 <= index < len(palette)):
            return
        palette[index] = self.normalize_palette_color(value, palette[index])
        self.refresh_crystal_scenes()

    def add_palette_color(self, kind: str) -> None:
        palette = self.palette_values(kind)
        defaults = self.palette_default_values(kind)
        palette.append(defaults[len(palette) % len(defaults)])
        self.refresh_palette_dialog()
        self.refresh_crystal_scenes()

    def reset_palette(self, kind: str) -> None:
        if kind == "vector":
            self.vector_colors = VECTOR_COLORS.copy()
        else:
            self.plane_colors = PLANE_COLORS.copy()
        self.refresh_palette_dialog()
        self.refresh_crystal_scenes()

    def remove_palette_color(self, kind: str, index: int) -> None:
        palette = self.palette_values(kind)
        if len(palette) <= 1 or not (0 <= index < len(palette)):
            return
        palette.pop(index)
        self.refresh_palette_dialog()
        self.refresh_crystal_scenes()

    def move_palette_color(self, kind: str, index: int, direction: int) -> None:
        palette = self.palette_values(kind)
        new_index = min(max(index + direction, 0), len(palette) - 1)
        if new_index == index:
            return
        palette[index], palette[new_index] = palette[new_index], palette[index]
        self.refresh_palette_dialog()
        self.refresh_crystal_scenes()

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
                with ui.row().classes("crystal-list-row"):
                    swatch = ui.element("div").classes("crystal-list-swatch")
                    swatch.style(f"background: {dominant_color(definition)}")
                    with ui.column().classes("crystal-list-info"):
                        ui.label(name).classes("crystal-list-name")
                        ui.label(f"{status} · {summary}").classes("crystal-list-meta")
                    ui.button(icon="edit", on_click=lambda _=None, n=name: self.edit_crystal_from_list(n)).props(
                        "flat round dense"
                    ).tooltip("Edit crystal")
                    delete = ui.button(icon="delete", on_click=lambda _=None, n=name: self.delete_crystal_from_list(n)).props(
                        "flat round dense color=negative"
                    )
                    delete.tooltip("Delete crystal")
                    if name in DEFAULT_NAMES:
                        delete.disable()

    def edit_crystal_from_list(self, name: str) -> None:
        if self.crystal_list_dialog is not None:
            self.crystal_list_dialog.close()
        self.builder.open(self.library.get(name), mode="edit")

    def delete_crystal_from_list(self, name: str) -> None:
        if not self.library.delete(name):
            ui.notify(f"Could not delete {name}", type="warning")
            return
        self.model_cache.clear()
        for state in self.panel_states:
            if state.crystal_name == name:
                state.crystal_name = "FCC"
                state.zone_text = "100"
                state.applied_zone_text = ""
                state.view_vector = np.array([1.0, 0.0, 0.0])
                state.roll = 0.0
        self.build_panels()
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
            definition.name = Path(upload_name).stem or definition.name
            saved = self.library.save(definition, USER_LIBRARY_SCOPE)
        except ValueError as exc:
            message = str(exc)
            self.set_status(f"CIF import failed: {message}")
            ui.notify(message, type="negative")
            return
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

        self.refresh_library(saved.name)
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
                width: calc(100vw - 20px);
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
                gap: 8px;
                align-items: start;
            }
            .comparison-panel {
                width: 100%;
                min-width: 0;
                padding: 6px;
                container-type: inline-size;
                container-name: comparison-panel;
            }
            .combo-panel {
                background: #151f2d;
                border-color: rgba(130, 178, 245, 0.28);
            }
            .panel-toolbar {
                width: 100%;
                display: grid;
                grid-template-columns: 22px minmax(104px, 1.3fr) minmax(58px, 0.7fr) minmax(58px, 0.7fr) minmax(74px, 0.8fr) minmax(74px, 0.8fr) minmax(52px, auto) minmax(48px, auto) 26px 26px 22px;
                grid-template-areas: "number crystal zone plane vector rotation apply sync download edit close";
                gap: 3px;
                align-items: center;
                margin-bottom: 6px;
            }
            .panel-number {
                grid-area: number;
                width: 22px;
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
                width: 22px;
                height: 34px;
                min-height: 34px;
            }
            .panel-edit-button {
                grid-area: edit;
                width: 26px;
                height: 34px;
                min-height: 34px;
            }
            .panel-download-button {
                grid-area: download;
                width: 26px;
                height: 34px;
                min-height: 34px;
            }
            .panel-apply-button {
                grid-area: apply;
                min-width: 52px;
            }
            .panel-sync-button {
                grid-area: sync;
                min-width: 48px;
            }
            .combo-toolbar {
                width: 100%;
                display: grid;
                grid-template-columns: 34px minmax(132px, 1fr) auto auto minmax(112px, auto) 30px 26px;
                grid-template-areas: "combo-number combo-select combo-add combo-remove combo-bind combo-download combo-close";
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
            .visual-stack {
                display: grid;
                grid-template-columns: minmax(0, 0.95fr) minmax(0, 1.05fr);
                gap: 8px;
                width: 100%;
                height: var(--panel-visual-height);
                min-height: var(--panel-visual-height);
                max-height: var(--panel-visual-height);
                align-items: stretch;
                overflow: hidden;
            }
            .combo-stack {
                display: grid;
                grid-template-columns: minmax(0, 0.95fr) minmax(0, 1.05fr);
                gap: 8px;
                width: 100%;
                height: var(--panel-visual-height);
                min-height: var(--panel-visual-height);
                max-height: var(--panel-visual-height);
                align-items: stretch;
                overflow: hidden;
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
                grid-template-columns: 34px minmax(0, 1fr) minmax(64px, 0.58fr) 86px;
                gap: 5px;
                align-items: center;
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
                width: 100% !important;
                height: 100% !important;
                min-height: 0 !important;
                max-height: 100% !important;
                border-radius: 8px;
                overflow: hidden;
                border: 1px solid rgba(255, 255, 255, 0.08);
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
                width: 100%;
                height: var(--panel-visual-height) !important;
                min-height: var(--panel-visual-height) !important;
                max-height: var(--panel-visual-height) !important;
                border-radius: 8px;
                overflow: hidden;
                background: #050607;
                border: 1px solid rgba(255, 255, 255, 0.08);
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
            .intro-card {
                width: min(860px, calc(100vw - 40px));
                max-height: min(820px, calc(100vh - 40px));
                border-radius: 8px;
                overflow-y: auto;
            }
            .intro-text {
                color: #e5edf7;
                font-size: 13px;
                line-height: 1.42;
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
                border-radius: 8px;
                gap: 10px;
            }
            .palette-columns {
                width: 100%;
                align-items: stretch;
                gap: 14px;
            }
            .palette-column {
                flex: 1 1 0;
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
                display: grid;
                grid-template-columns: 20px minmax(0, 1fr) 34px 34px;
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
            .crystal-list-info {
                gap: 0;
                min-width: 0;
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
                color: #eef2f6;
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
                margin-top: 0;
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
            .site-row {
                display: grid;
                grid-template-columns: minmax(128px, 1.1fr) repeat(4, minmax(86px, 0.72fr)) minmax(130px, 0.9fr) minmax(112px, 0.8fr) 38px;
                gap: 8px;
                width: 100%;
                align-items: start;
            }
            @container comparison-panel (max-width: 590px) {
                .panel-toolbar {
                    grid-template-columns: 24px minmax(112px, 1.45fr) minmax(72px, 0.8fr) minmax(72px, 0.8fr) minmax(86px, 0.95fr) minmax(76px, 0.85fr);
                    grid-template-areas:
                        "number crystal zone plane vector rotation"
                        "number apply sync download edit close";
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
                .panel-edit-button,
                .panel-toolbar .panel-close-button {
                    justify-self: start;
                }
                .combo-toolbar {
                    grid-template-columns: 42px minmax(150px, 1fr) auto auto minmax(112px, auto) 30px 28px;
                }
            }
            @container comparison-panel (max-width: 500px) {
                .panel-toolbar {
                    grid-template-columns: 22px minmax(0, 1fr) minmax(0, 1fr);
                    grid-template-areas:
                        "number crystal crystal"
                        "number zone plane"
                        "number vector rotation"
                        "number apply sync"
                        "number download edit"
                        "number close close";
                }
                .panel-apply-button,
                .panel-sync-button {
                    width: 100%;
                    min-width: 0;
                    justify-self: stretch;
                }
                .panel-download-button,
                .panel-edit-button,
                .panel-toolbar .panel-close-button {
                    justify-self: start;
                }
                .combo-toolbar {
                    grid-template-columns: 34px minmax(0, 1fr) 30px 28px;
                    grid-template-areas:
                        "combo-number combo-select combo-download combo-close"
                        "combo-number combo-add combo-remove ."
                        "combo-number combo-bind combo-bind .";
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
                        "number apply sync download edit close";
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
                .app-shell {
                    --panel-visual-height: 300px;
                }
                .panel-toolbar {
                    grid-template-columns: 24px minmax(112px, 1.45fr) minmax(72px, 0.8fr) minmax(72px, 0.8fr) minmax(86px, 0.95fr) minmax(76px, 0.85fr);
                    grid-template-areas:
                        "number crystal zone plane vector rotation"
                        "number apply sync download edit close";
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
                .panel-edit-button,
                .panel-toolbar .panel-close-button {
                    justify-self: start;
                }
                .combo-toolbar {
                    grid-template-columns: 42px minmax(150px, 1fr) auto auto minmax(112px, auto) 30px 28px;
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
                .advanced-grid,
                .builder-grid {
                    grid-template-columns: 1fr !important;
                }
                .panel-toolbar {
                    grid-template-columns: 22px minmax(0, 1fr) minmax(0, 1fr);
                    grid-template-areas:
                        "number crystal crystal"
                        "number zone plane"
                        "number vector rotation"
                        "number apply sync"
                        "number download edit"
                        "number close close";
                }
                .panel-apply-button,
                .panel-sync-button {
                    width: 100%;
                    min-width: 0;
                    justify-self: stretch;
                }
                .panel-download-button,
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
                .combo-stack {
                    grid-template-columns: 1fr;
                    height: auto;
                    min-height: 0;
                    max-height: none;
                    overflow: visible;
                }
                .combo-toolbar {
                    grid-template-columns: 34px minmax(0, 1fr) 30px 28px;
                    grid-template-areas:
                        "combo-number combo-select combo-download combo-close"
                        "combo-number combo-add combo-remove ."
                        "combo-number combo-bind combo-bind .";
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

    def show_indices(self) -> bool:
        return bool(getattr(getattr(self, "show_indices_input", None), "value", False))

    def show_crystal_annotations(self) -> bool:
        return bool(getattr(getattr(self, "show_crystal_annotations_input", None), "value", True))

    def plane_palette(self) -> list[str]:
        return self.plane_colors or PLANE_COLORS

    def vector_palette(self) -> list[str]:
        return self.vector_colors or VECTOR_COLORS

    def refresh_crystal_scenes(self) -> None:
        for controller in self.controllers:
            controller.redraw_scene()

    def show_scale_bars(self) -> bool:
        return bool(getattr(getattr(self, "show_scale_bar_input", None), "value", True))

    def on_scale_bar_changed(self) -> None:
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
        return min(max(compression, 10.0), 150.0)

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

    def model_for(self, name: str) -> CrystalModel:
        definition = self.library.get(name)
        cache_key = (definition.name, json.dumps(definition.to_dict(), sort_keys=True))
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

    def add_panel(self) -> None:
        defaults = [
            ("FCC", "100", "", ""),
            ("BCC", "110", "", ""),
            ("HCP", "0001", "", ""),
        ]
        crystal, zone, plane, vector = defaults[(self.next_panel_id - 1) % len(defaults)]
        self.panel_states.append(
            PanelState(
                panel_id=self.next_panel_id,
                crystal_name=crystal,
                zone_text=zone,
                plane_text=plane,
                vector_text=vector,
                diffraction_color=DEFAULT_DIFFRACTION_COLORS.get(crystal, "#31F7F1"),
            )
        )
        self.layout_items.append(("panel", self.next_panel_id))
        self.next_panel_id += 1
        self.build_panels()
        self.set_status("Added a comparison panel")

    def add_combo_panel(self) -> None:
        if len(self.panel_states) < 2:
            ui.notify("Add at least two panels before creating a combo panel", type="warning")
            return
        self.combo_panel_states.append(
            ComboPanelState(
                combo_id=self.next_combo_id,
                source_panel_ids=[state.panel_id for state in self.panel_states],
                selected_panel_id=self.panel_states[0].panel_id,
            )
        )
        self.layout_items.append(("combo", self.next_combo_id))
        self.next_combo_id += 1
        self.build_panels()
        self.set_status("Added a combo panel")

    def remove_panel(self, panel_id: int) -> None:
        if len(self.panel_states) <= 1:
            return
        self.panel_states = [state for state in self.panel_states if state.panel_id != panel_id]
        self.layout_items = [item for item in self.layout_items if item != ("panel", panel_id)]
        self.repair_all_combo_sources()
        self.build_panels()
        self.set_status(f"Removed panel {panel_id}")

    def remove_combo_panel(self, combo_id: int) -> None:
        self.combo_panel_states = [state for state in self.combo_panel_states if state.combo_id != combo_id]
        self.layout_items = [item for item in self.layout_items if item != ("combo", combo_id)]
        self.build_panels()
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

    def refresh_library(self, selected_name: str, target_panel_id: int | None = None) -> None:
        self.model_cache.clear()
        for state in self.panel_states:
            if state.crystal_name == CUSTOM_SENTINEL or state.crystal_name not in self.library.definitions:
                state.crystal_name = selected_name
        target = self.panel_state_by_id(target_panel_id)
        if target is not None:
            target.crystal_name = selected_name
        self.build_panels()

    def refresh_diffractions(self, clear_cache: bool = False) -> None:
        if clear_cache:
            self.model_cache.clear()
        for controller in self.controllers:
            controller.redraw_diffraction()
        self.refresh_combo_panels()

    def refresh_combo_panels(self) -> None:
        self.repair_all_combo_sources()
        for controller in self.combo_controllers:
            controller.refresh()

    def controller_by_panel_id(self, panel_id: int) -> PanelController | None:
        return next((controller for controller in self.controllers if controller.state.panel_id == panel_id), None)

    def propagate_bound_motion(
        self,
        source_panel_id: int,
        old_view: np.ndarray,
        old_roll: float,
        new_view: np.ndarray,
        new_roll: float,
    ) -> None:
        bound_ids: set[int] = set()
        for combo_state in self.combo_panel_states:
            if combo_state.bind_motion and source_panel_id in combo_state.source_panel_ids:
                bound_ids.update(combo_state.source_panel_ids)
        bound_ids.discard(source_panel_id)
        if not bound_ids:
            self.refresh_combo_panels()
            return

        # Propagate the motion in the driver's view frame, not in the driver's
        # crystal coordinates. This preserves orientation relationships such as
        # panel 1 [100] parallel to panel 2 [110]: an in-plane spin in panel 1
        # becomes an in-plane spin around panel 2's current beam direction.
        delta = local_orientation_delta(old_view, old_roll, new_view, new_roll)
        if np.allclose(delta, np.eye(3), atol=1e-6):
            self.refresh_combo_panels()
            return

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
        self.refresh_combo_panels()

    def compute_pymatgen_tem_spots(self, model: CrystalModel, view_vector: np.ndarray, roll: float) -> np.ndarray:
        try:
            from pymatgen.analysis.diffraction.tem import TEMCalculator

            structure = pymatgen_structure_from_model(model)
            zone_axis = integer_zone_axis_from_view(model, view_vector)
            calculator_class = occupancy_aware_tem_calculator_class(TEMCalculator)
            calculator = calculator_class(
                symprec=None,
                voltage=self.current_voltage_kv(),
                beam_direction=zone_axis,
                camera_length=max(int(round(self.current_camera_length_mm() / 10.0)), 1),
            )
            max_order = self.current_max_hkl()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                dots = calculator.tem_dots(structure, TEMCalculator.generate_points(-max_order, max_order))
        except Exception as exc:
            self.set_status(f"Pymatgen TEM calculation failed: {exc}")
            return np.empty((0, 6), dtype=float)

        threshold = self.current_spot_intensity_threshold()
        rows = [[0.0, 0.0, 1.0, 0, 0, 0]]
        normal = normalize_vector(view_vector)
        if normal is None:
            normal = normalize_vector(direction_to_cart(zone_axis, model))
        if normal is None:
            normal = np.array([1.0, 0.0, 0.0])
        u_axis, v_axis = projection_basis(normal, roll)
        detector_scale = self.current_detector_scale_mm_per_nm_inv()
        compression = self.current_intensity_compression_factor()
        for dot in dots:
            h, k, l = (int(value) for value in dot.hkl)
            if h == k == l == 0:
                continue
            raw_intensity = max(float(dot.intensity), 0.0)
            display_intensity = math.log1p(compression * raw_intensity) / math.log1p(compression)
            if display_intensity <= threshold:
                continue
            g_vector = np.array([h, k, l], dtype=float) @ model.reciprocal
            x_coord = detector_scale * float(np.dot(g_vector, u_axis))
            y_coord = detector_scale * float(np.dot(g_vector, v_axis))
            rows.append(
                [
                    x_coord,
                    y_coord,
                    display_intensity,
                    h,
                    k,
                    l,
                ]
            )
        return np.array(rows, dtype=float)

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
        compression = self.current_intensity_compression_factor()
        display_intensity = np.log1p(compression * raw_intensity) / math.log1p(compression)
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
        return (
            np.array(hkl_values, dtype=int),
            np.array(reciprocal_points, dtype=float),
            np.array(intensities, dtype=float),
        )


@ui.page("/")
def index() -> None:
    SimulatorApp().build()


def main() -> None:
    is_hosted = os.environ.get("RENDER") == "true" or os.environ.get("PORT") is not None
    is_desktop = bool(getattr(sys, "frozen", False)) or os.environ.get("CRYSDIS_DESKTOP") == "1"
    if is_hosted:
        ui.run(
            title="CrysDiS",
            host="0.0.0.0",
            port=int(os.environ.get("PORT", "8080")),
            reload=False,
            show=False,
        )
        return

    if is_desktop:
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

    port = int(os.environ.get("NICEGUI_PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")
    ui.run(title="CrysDiS", host=host, port=port, reload=False, show=False)


if __name__ in {"__main__", "__mp_main__"}:
    main()
