"""Panel-local drawing markers, independent of crystallographic sites."""

import copy
import math
import re
from dataclasses import dataclass, field, replace
from fractions import Fraction
from functools import lru_cache
from itertools import product

import numpy as np
from PIL import ImageColor
from scipy.spatial import ConvexHull, QhullError
from matplotlib.path import Path as MplPath


COORDINATE_MODES = {"fractional": "Fractional (a, b, c)", "cartesian": "Cartesian (nm)"}
MARKER_KINDS = {"point": "Point", "line": "Line segment", "plane": "Plane patch", "polyhedron": "Polyhedron"}
LINE_STYLES = {"line": "Line", "arrow": "Single-headed arrow", "double_arrow": "Double-headed arrow"}
EDGE_STYLES = {"solid": "Solid", "dashed": "Dashed", "dotted": "Dotted", "dash_dot": "Dash-dotted"}
LABEL_POSITIONS = {"center": (0, 0), "upper_left": (-1, 1), "up": (0, 1), "upper_right": (1, 1),
                   "left": (-1, 0), "right": (1, 0), "bottom_left": (-1, -1),
                   "bottom": (0, -1), "bottom_right": (1, -1)}
MAX_MARKERS = 300
MAX_VERTICES = 64
COORDINATE_ZERO_TOLERANCE = 1e-14


@dataclass
class CrystalMarker:
    kind: str = "point"
    name: str = ""
    coordinates: str = "fractional"
    points: list[tuple[float, float, float]] = field(default_factory=lambda: [(0.0, 0.0, 0.0)])
    color: str = "#FFE066"
    width: float | None = None
    opacity: float = 1.0
    fill_opacity: float = 0.25
    dashed: bool = False
    edge_style: str = "solid"
    point_style: str = "ring"
    line_style: str = "line"
    visible: bool = True
    show_label: bool = False
    atom_scale: float | None = None
    hide_atom: bool = False
    label_size: float = 13.0
    label_color: str = ""
    label_opacity: float = 1.0
    label_position: str = "up"
    label_gap: float = 4.0

    def __post_init__(self):
        if self.width is None:
            self.width = 0.005 if self.kind == "point" else 0.003


def clean_coordinate(value: float) -> float:
    return 0.0 if abs(value) < COORDINATE_ZERO_TOLERANCE else float(value)


def parse_point(text: str) -> tuple[float, float, float]:
    parts = str(text).strip().strip("[]()").replace(",", " ").split()
    if len(parts) != 3:
        raise ValueError("Each position needs three coordinates, separated by commas or spaces.")
    try:
        values = tuple(float(Fraction(part)) for part in parts)
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ValueError("Coordinates must be finite numbers or fractions.") from exc
    if not all(math.isfinite(value) and abs(value) <= 1000 for value in values):
        raise ValueError("Coordinates must be finite and between -1000 and 1000.")
    return tuple(clean_coordinate(value) for value in values)


def coordinate_entry_complete(text: str) -> bool:
    """Allow unfinished triples, signs, fractions and exponents without live warnings."""
    text = str(text or "").strip().strip("[]()")
    parts = text.replace(",", " ").split()
    if len(parts) != 3:
        return len(parts) > 3
    if "," in text and any(not part.strip() for part in text.split(",")):
        return False
    for part in parts:
        token = part.strip()
        if token in {"", "+", "-", ".", "+.", "-."}:
            return False
        if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?|/[+-]?)", token):
            return False
    return True


def point_text(point) -> str:
    return ", ".join(f"{clean_coordinate(value):.12g}" for value in point)


def box_corners(points) -> np.ndarray:
    low, high = np.minimum(*points), np.maximum(*points)
    return np.array(list(product(*zip(low, high))))


def normalize_marker(marker: CrystalMarker) -> CrystalMarker:
    """Keep older session boxes as unfilled polyhedra, without a separate box editor."""
    if marker.kind != "box":
        return marker
    if len(marker.points) != 2 or np.any(np.abs(np.subtract(*marker.points)) < 1e-10):
        raise ValueError("A legacy box needs two corners with a nonzero span along each axis.")
    return replace(marker, kind="polyhedron", points=box_corners(marker.points).tolist(), fill_opacity=0)


@lru_cache(maxsize=256)
def surface_faces(kind: str, vertices: tuple) -> tuple[tuple[int, ...], ...]:
    """Validate a boundary polygon or build merged faces of a convex hull."""
    points = np.asarray(vertices, dtype=float)
    centered = points - points.mean(axis=0)
    scale = float(np.max(np.linalg.norm(centered, axis=1)))
    if scale < 1e-10:
        raise ValueError("Surface vertices must span a nonzero area or volume.")
    points = centered / scale
    distances = np.linalg.norm(points[:, None] - points[None, :], axis=2)
    if np.any(distances[np.triu_indices(len(points), 1)] < 1e-10):
        raise ValueError("Surface vertices must be distinct; do not repeat the first vertex at the end.")
    _, singular, basis = np.linalg.svd(points, full_matrices=False)
    if singular[1] < 1e-10:
        raise ValueError("Surface vertices must not all lie on one line.")
    if kind == "plane":
        if np.max(np.abs(points @ basis[2])) > 1e-8:
            raise ValueError("All plane-patch vertices must lie on the same plane.")
        projected = points @ basis[:2].T
        count = len(points)
        for i in range(count):
            edge = MplPath(projected[[i, (i + 1) % count]])
            for j in range(i + 1, count):
                if j == i + 1 or (i == 0 and j == count - 1):
                    continue
                if edge.intersects_path(MplPath(projected[[j, (j + 1) % count]]), filled=False):
                    raise ValueError("Polygon edges cross or touch. Arrange vertices around the boundary.")
        area = np.sum(projected[:, 0] * np.roll(projected[:, 1], -1) - projected[:, 1] * np.roll(projected[:, 0], -1))
        if abs(area) < 1e-10:
            raise ValueError("A plane patch must have nonzero area.")
        return (tuple(range(count)),)
    if singular[2] < 1e-9:
        raise ValueError("A polyhedron needs at least four non-coplanar vertices.")
    try:
        hull = ConvexHull(points)
        groups = []
        for triangle, equation in zip(hull.simplices, hull.equations):
            for normal, indices in groups:
                if np.allclose(equation, normal, atol=1e-8, rtol=0):
                    indices.update(triangle.tolist())
                    break
            else:
                groups.append((equation, set(triangle.tolist())))
        faces = []
        # Coplanar Qhull triangles become one polygon, without diagonal frame lines.
        for _, indices in groups:
            indices = sorted(indices)
            face = points[indices] - points[indices].mean(axis=0)
            _, _, axes = np.linalg.svd(face, full_matrices=False)
            order = ConvexHull(face @ axes[:2].T).vertices
            faces.append(tuple(indices[i] for i in order))
        return tuple(faces)
    except QhullError as exc:
        raise ValueError("The polyhedron vertices do not define a stable three-dimensional solid.") from exc


def validate_markers(markers: list[CrystalMarker]) -> None:
    if len(markers) > MAX_MARKERS:
        raise ValueError(f"Use at most {MAX_MARKERS} markers per panel.")
    for original in markers:
        marker = normalize_marker(original)
        limits = {"point": (1, 1), "line": (2, 2), "plane": (3, MAX_VERTICES), "polyhedron": (4, MAX_VERTICES)}.get(marker.kind)
        if limits is None or not limits[0] <= len(marker.points) <= limits[1] or marker.coordinates not in COORDINATE_MODES:
            raise ValueError("Invalid marker type or coordinates.")
        for point in marker.points:
            parse_point(point_text(point))
        ImageColor.getcolor(marker.color, "RGB")
        if marker.label_color:
            ImageColor.getcolor(marker.label_color, "RGB")
        for value, low, high in ((marker.width, 0.00001, 1),
                                 (marker.opacity, 0, 1), (marker.fill_opacity, 0, 1),
                                 (marker.atom_scale if marker.atom_scale is not None else 1.0, 0.01, 9.0),
                                 (marker.label_size, 6, 72), (marker.label_opacity, 0, 1), (marker.label_gap, 0, 200)):
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError("Marker sizes or opacity are out of range.")
        if (marker.point_style not in {"ring", "sphere"} or marker.line_style not in LINE_STYLES
                or marker.edge_style not in EDGE_STYLES or marker.label_position not in LABEL_POSITIONS
                or len(marker.name) > 80):
            raise ValueError("Invalid marker style or name (maximum 80 characters).")
        if marker.hide_atom and marker.kind != "point":
            raise ValueError("Only point markers can hide atoms.")
        points = np.asarray(marker.points)
        if len(points) > 1 and np.linalg.norm(points[1] - points[0]) < 1e-10:
            raise ValueError("Marker endpoints must be different.")
        if marker.kind in {"plane", "polyhedron"}:
            surface_faces(marker.kind, tuple(tuple(point) for point in marker.points))


def marker_hidden_atom_indices(markers: list[CrystalMarker], model) -> frozenset[int]:
    """Mask exact displayed sites, without wrapping coordinates or changing structure data."""
    targets = [marker for marker in markers if marker.kind == "point" and marker.visible and marker.hide_atom]
    if not targets or not model.display_atoms:
        return frozenset()
    positions = np.array([atom.position for atom in model.display_atoms])
    hidden = set()
    for marker in targets:
        point = np.asarray(marker.points[0])
        cartesian = point @ model.lattice if marker.coordinates == "fractional" else point
        target = model.display_origin + cartesian / model.scale_nm
        hidden.update(np.flatnonzero(np.all(np.isclose(positions, target, atol=1e-7, rtol=0), axis=1)).tolist())
    return frozenset(hidden)


def point_marker_size(marker: CrystalMarker, model, atom_positions=None) -> tuple[float, float]:
    """Return radius and size factor, using only an atom at the exact marker position."""
    if atom_positions is None:
        atom_positions = np.array([atom.position for atom in model.display_atoms]).reshape(-1, 3)
    point = np.asarray(marker.points[0], dtype=float)
    cartesian = point @ model.lattice if marker.coordinates == "fractional" else point
    target = model.display_origin + cartesian / model.scale_nm
    indices = np.flatnonzero(np.all(np.isclose(atom_positions, target, atol=1e-7, rtol=0), axis=1))
    atom = model.display_atoms[int(indices[0])] if len(indices) else None
    default_scale = atom.radius_multiplier if atom is not None else model.display_atom_scale
    scale = marker.atom_scale if marker.atom_scale is not None else default_scale
    base_radius = model.atom_radius(atom) / atom.radius_multiplier if atom is not None else model.atom_radius()
    return base_radius * scale, scale


def marker_geometry(markers: list[CrystalMarker], model) -> list[dict]:
    markers = [normalize_marker(marker) for marker in markers]
    validate_markers(markers)
    result = []
    segment_count = 0
    atom_positions = None
    for marker in markers:
        if not marker.visible or marker.opacity <= 0:
            continue
        points = np.asarray(marker.points, dtype=float)
        faces = ()
        if marker.kind in {"plane", "polyhedron"}:
            faces = surface_faces(marker.kind, tuple(tuple(point) for point in marker.points))
            pairs = sorted({tuple(sorted((a, b))) for face in faces for a, b in zip(face, (*face[1:], face[0]))})
        else:
            pairs = {"point": [], "line": [(0, 1)]}[marker.kind]
        cartesian = points @ model.lattice if marker.coordinates == "fractional" else points
        points = model.display_origin + cartesian / model.scale_nm
        radius = 0.0
        if marker.kind == "point":
            if atom_positions is None:
                atom_positions = np.array([atom.position for atom in model.display_atoms]).reshape(-1, 3)
            radius, _ = point_marker_size(marker, model, atom_positions)
        segments = []
        dots = []
        arrowheads = []
        # Keep markers created with the original checkbox compatible.
        edge_style = "dashed" if marker.dashed and marker.edge_style == "solid" else marker.edge_style
        width = marker.width / model.scale_nm
        for i, j in pairs:
            start, delta = points[i], points[j] - points[i]
            if marker.kind == "line" and marker.line_style != "line":
                length = np.linalg.norm(delta)
                direction = delta / length
                head_length = min(max(6 * marker.width, .025) / model.scale_nm, .4 * length)
                radius = .35 * head_length
                arrowheads.append({"tip": points[j].tolist(), "base": (points[j] - head_length * direction).tolist(), "radius": radius})
                end = points[j] - head_length * direction
                if marker.line_style == "double_arrow":
                    arrowheads.append({"tip": points[i].tolist(), "base": (points[i] + head_length * direction).tolist(), "radius": radius})
                    start = points[i] + head_length * direction
                delta = end - start
            if edge_style == "dashed":
                # Bound mesh count even for markers far outside the unit cell.
                count = min(32, max(2, int(np.linalg.norm(delta) / max(8 * marker.width / model.scale_nm, 0.05))))
                segments.extend([(start + delta * k / count, start + delta * (k + .6) / count) for k in range(count)])
            elif edge_style == "dotted":
                count = min(64, max(2, int(np.linalg.norm(delta) / max(3 * width, .025))))
                dots.extend(start + delta * (k + .5) / count for k in range(count))
            elif edge_style == "dash_dot":
                count = min(32, max(2, int(np.linalg.norm(delta) / max(12 * width, .07))))
                segments.extend((start + delta * k / count, start + delta * (k + .5) / count) for k in range(count))
                dots.extend(start + delta * (k + .78) / count for k in range(count))
            else:
                segments.append((start, start + delta))
        segment_count += len(segments) + len(dots)
        if segment_count > 5000:
            raise ValueError("Markers exceed 5000 edge pieces. Use fewer patterned markers or solid edges.")
        result.append({"kind": marker.kind, "points": points.tolist(), "segments": [[a.tolist(), b.tolist()] for a, b in segments],
            "dots": [point.tolist() for point in dots],
            "faces": faces, "arrowheads": arrowheads,
            "color": "#%02X%02X%02X" % ImageColor.getcolor(marker.color, "RGB"), "opacity": marker.opacity, "fill_opacity": marker.fill_opacity * marker.opacity,
            "radius": radius, "width": marker.width / model.scale_nm,
            "hide_atom": marker.hide_atom,
            "point_style": marker.point_style, "label": (marker.name.strip() or MARKER_KINDS[marker.kind]) if marker.show_label else "",
            "label_size": marker.label_size, "label_color": marker.label_color or marker.color,
            "label_opacity": marker.label_opacity, "label_direction": LABEL_POSITIONS[marker.label_position],
            "label_gap": marker.label_gap})
    return result


def marker_extent_points(geometry: list[dict]) -> list[np.ndarray]:
    points = []
    for marker in geometry:
        if marker["hide_atom"]:
            continue
        margin = marker["width"]
        if marker["kind"] == "point":
            margin = marker["radius"] + (marker["width"] if marker["point_style"] == "ring" else 0)
        margin = max(margin, max((head["radius"] for head in marker["arrowheads"]), default=0))
        for point in marker["points"]:
            points.extend(np.asarray(point) + sign * np.eye(3)[axis] * margin for sign in (-1, 1) for axis in range(3))
    return points


@dataclass(frozen=True)
class CoordinateGridSettings:
    spacing: float | None = None
    volume: bool = False
    extent: str = "display"
    low: tuple[float, float, float] = (-1.0, -1.0, -1.0)
    high: tuple[float, float, float] = (1.0, 1.0, 1.0)

    def __post_init__(self):
        if self.spacing is not None and (not math.isfinite(self.spacing) or self.spacing <= 0):
            raise ValueError("Grid spacing must be positive and finite.")
        if self.extent not in {"display", "symmetric", "custom"}:
            raise ValueError("Unknown grid extent.")
        if self.extent == "custom":
            low, high = np.asarray(self.low), np.asarray(self.high)
            if low.shape != (3,) or high.shape != (3,) or not np.all(np.isfinite([low, high])):
                raise ValueError("Enter all six grid bounds.")
            if np.any(np.abs([low, high]) > 1000):
                raise ValueError("Grid bounds must be between -1000 and 1000.")
            if np.any(low >= high) or np.any(low > 0) or np.any(high < 0):
                raise ValueError("Each minimum must be below its maximum, with the origin inside the bounds.")


def coordinate_grid_geometry(model, low, high, markers=(), settings=None) -> dict:
    """Bounded guides in lattice coordinates, not an orthogonal Cartesian grid."""
    settings = settings or CoordinateGridSettings()
    low, high = np.minimum(np.asarray(low, dtype=float), 0), np.maximum(np.asarray(high, dtype=float), 1)
    inverse = np.linalg.inv(model.lattice)
    for marker in markers:
        if not marker.visible:
            continue
        points = np.asarray(marker.points, dtype=float)
        fractional = points if marker.coordinates == "fractional" else points @ inverse
        low = np.minimum(low, np.min(fractional, axis=0))
        high = np.maximum(high, np.max(fractional, axis=0))
    if settings.extent == "symmetric":
        high = np.maximum(np.abs(low), np.abs(high))
        low = -high
    elif settings.extent == "custom":
        low, high = np.asarray(settings.low), np.asarray(settings.high)
    span = float(np.max(high - low))
    if settings.spacing is None:
        required = max(.25, span / 16)
        step = .25 * 2 ** max(0, math.ceil(math.log2(required / .25)))
    else:
        # Bound geometry for large 3D extents, retaining multiples of the chosen spacing.
        intervals = 24 if settings.volume else 64
        step = settings.spacing * max(1, math.ceil(span / (intervals * settings.spacing)))
    if settings.extent != "custom":
        low, high = np.floor(low / step + 1e-10) * step, np.ceil(high / step - 1e-10) * step

    def display(point):
        return (model.display_origin + np.asarray(point) @ model.display_lattice).tolist()

    segments = []
    ticks = [np.arange(math.ceil(lo / step - 1e-10), math.floor(hi / step + 1e-10) + 1) * step
             for lo, hi in zip(low, high)]
    for moving in range(3):
        a, b = [axis for axis in range(3) if axis != moving]
        for va, vb in product(ticks[a], ticks[b]):
            at_a, at_b = abs(va) < 1e-10, abs(vb) < 1e-10
            if (at_a and at_b) or (not settings.volume and not (at_a or at_b)):
                continue  # The three arrows already mark the origin axes.
            start, end = np.zeros(3), np.zeros(3)
            start[a] = end[a] = va
            start[b] = end[b] = vb
            start[moving], end[moving] = low[moving], high[moving]
            segments.append([display(start), display(end)])
    axes = []
    head_length = .22
    atom_radius = max(model.atom_radius(), max((model.atom_radius(atom) for atom in model.display_atoms), default=0))
    for i, (label, color) in enumerate(zip("abc", ("#F28C8C", "#81D4A1", "#81BAEF"))):
        start, end = np.zeros(3), np.zeros(3)
        # Keep the whole arrowhead beyond boundary atoms, also on short/skew axes.
        clearance = (atom_radius + head_length + .03) / np.linalg.norm(model.display_lattice[i])
        start[i], end[i] = low[i], high[i] + max(step * .6, clearance)
        axes.append({"start": display(start), "end": display(end), "label": label, "color": color,
                     "head_length": head_length})
    corners = [display(point) for point in product(*zip(low, high))]
    extent = corners + [axis["end"] for axis in axes]
    limit = max(model.limit, float(np.max(np.linalg.norm(extent, axis=1))) * 1.12)
    return {"segments": segments, "axes": axes, "step": step, "low": low.tolist(), "high": high.tolist(), "limit": limit}


THREE_MARKERS_SCRIPT = r"""
function addCrystalMarkers(THREE, root, markers, sphereMaterial) {
    const V = p => new THREE.Vector3(...p);
    const material = (color, opacity) => new THREE.MeshBasicMaterial({color, opacity,
        transparent: opacity < 1, depthWrite: opacity >= 1, side: THREE.DoubleSide});
    for (const marker of markers) {
        for (const [a, b] of marker.segments) {
            const delta = V(b).sub(V(a));
            const mesh = new THREE.Mesh(new THREE.CylinderGeometry(marker.width/2, marker.width/2, delta.length(), 12),
                material(marker.color, marker.opacity));
            mesh.position.copy(V(a)).addScaledVector(delta, .5);
            mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0), delta.normalize()); root.add(mesh);
        }
        for (const head of marker.arrowheads) {
            const delta = V(head.tip).sub(V(head.base));
            const mesh = new THREE.Mesh(new THREE.ConeGeometry(head.radius, delta.length(), 32), material(marker.color, marker.opacity));
            mesh.position.copy(V(head.base)).addScaledVector(delta, .5);
            mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0), delta.normalize()); root.add(mesh);
        }
        for (const point of marker.dots) {
            const mesh = new THREE.Mesh(new THREE.SphereGeometry(marker.width/2, 12, 8), material(marker.color, marker.opacity));
            mesh.position.copy(V(point)); root.add(mesh);
        }
        if (marker.fill_opacity > 0) for (const face of marker.faces) {
            const points = face.map(i => V(marker.points[i]));
            const origin = points[0], x = points[1].clone().sub(origin).normalize();
            let normal = new THREE.Vector3();
            for (let i=2; i<points.length; i++) {
                const n = new THREE.Vector3().crossVectors(x, points[i].clone().sub(origin));
                if (n.lengthSq() > normal.lengthSq()) normal.copy(n);
            }
            const y = new THREE.Vector3().crossVectors(normal.normalize(), x).normalize();
            const contour = points.map(p => {const d=p.clone().sub(origin); return new THREE.Vector2(d.dot(x), d.dot(y));});
            const triangles = THREE.ShapeUtils.triangulateShape(contour, []);
            const geometry = new THREE.BufferGeometry();
            geometry.setAttribute('position', new THREE.Float32BufferAttribute(points.flatMap(p => p.toArray()), 3));
            geometry.setIndex(triangles.flat());
            const mesh = new THREE.Mesh(geometry, material(marker.color, marker.fill_opacity));
            mesh.material.forceSinglePass = true; root.add(mesh);
        }
        if (marker.kind === 'point' && !marker.hide_atom) {
            let mesh;
            if (marker.point_style === 'ring') {
                const canvas = document.createElement('canvas'); canvas.width = canvas.height = 256;
                const ctx = canvas.getContext('2d');
                const outer = marker.radius + marker.width / 2;
                ctx.strokeStyle = 'white'; ctx.lineWidth = Math.min(240, 240 * marker.width / (2 * outer));
                ctx.beginPath(); ctx.arc(128,128,120 * marker.radius/outer,0,2*Math.PI); ctx.stroke();
                const texture = new THREE.CanvasTexture(canvas);
                mesh = new THREE.Sprite(new THREE.SpriteMaterial({map:texture, color:marker.color,
                    opacity:marker.opacity, transparent:true, depthWrite:false}));
                mesh.scale.setScalar(2 * outer * 256/240);
            } else {
                mesh = new THREE.Mesh(new THREE.SphereGeometry(marker.radius,32,16), sphereMaterial(marker.color,marker.opacity));
            }
            mesh.position.copy(V(marker.points[0])); root.add(mesh);
        }
    }
}
"""


class MarkerEditor:
    def __init__(self, model, on_change, annotations_enabled=lambda: True, on_pick_change=lambda active: None):
        from nicegui import ui
        self.model, self.on_change = model, on_change
        self.annotations_enabled = annotations_enabled
        self.on_pick_change = on_pick_change
        self.pick_target = None
        self.rows = []
        self.loading = False
        with ui.row().classes("full-width items-center gap-2"):
            for kind, icon in (("point", "radio_button_checked"), ("line", "show_chart"), ("plane", "change_history"), ("polyhedron", "view_in_ar")):
                button = ui.button(MARKER_KINDS[kind], icon=icon, on_click=lambda k=kind: self.add(k)).props("outline dense")
                if kind == "polyhedron":
                    button.tooltip("Convex hull of at least four non-coplanar vertices. Interior vertices do not change its surface.")
                elif kind == "plane":
                    button.tooltip("Coplanar polygon vertices in boundary order; concave polygons are supported.")
        self.container = ui.column().classes("full-width gap-1 marker-editor")
        ui.add_css(".marker-editor{container-type:inline-size}"
                   ".marker-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;width:100%;max-width:640px}"
                   ".marker-fields .q-field{min-width:0}"
                   ".marker-position{grid-column:1 / -1;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,.85fr);gap:8px}"
                   ".marker-position .q-field{width:100%!important}"
                   ".marker-pick-position{display:flex;align-items:center;gap:4px;min-width:0}"
                   ".marker-position-picking .q-field__control:before{border-color:var(--q-secondary);border-width:2px}"
                   ".marker-positions{grid-column:1 / -1;width:100%;gap:10px}"
                   ".marker-vertex-row{display:grid;grid-template-columns:28px minmax(0,1fr);gap:4px;width:100%;align-items:center}"
                   ".marker-vertex-fields{min-width:0;width:100%;gap:4px}"
                   ".marker-vertex-drag{cursor:grab;touch-action:none;user-select:none;width:28px;min-width:28px;height:32px}"
                   ".marker-vertex-drag:active{cursor:grabbing}"
                   ".marker-vertex-chosen{outline:1px solid var(--q-primary);outline-offset:-1px}"
                   ".marker-vertex-ghost{background:#252525;opacity:.95!important}"
                   "@container(max-width:300px){.marker-fields,.marker-position{grid-template-columns:minmax(0,1fr)}}")
        inverse = np.linalg.inv(model.display_lattice)
        self.atom_points = [(atom, (atom.position - model.display_origin) @ inverse) for atom in model.display_atoms[:500]]

    def read(self, *, validate=True) -> list[CrystalMarker]:
        markers = [self.read_row(row) for row in self.rows]
        if validate:
            validate_markers(markers)
        return markers

    def read_row(self, row) -> CrystalMarker:
        marker = copy.deepcopy(row["marker"])
        for key in ("name", "color", "coordinates", "visible", "edge_style", "point_style", "line_style", "show_label",
                    "hide_atom", "label_position"):
            setattr(marker, key, row[key].value)
        marker.dashed = False
        marker.name = str(marker.name or "").strip()
        marker.color = str(marker.color or "")
        marker.label_color = "" if row["label_same_color"].value else str(row["label_color"].value or "")
        for key in ("width", "opacity", "fill_opacity", "label_size", "label_opacity", "label_gap"):
            setattr(marker, key, float(row[key].value) / (100 if "opacity" in key else 1))
        marker.atom_scale = float(row["atom_scale"].value) / 100 if row["size_edited"] else None
        marker.points = [parse_point(control.value) for control in row["points"]]
        return marker

    def read_preview(self) -> tuple[list[CrystalMarker], list[str]]:
        markers, errors = [], []
        for row in self.rows:
            if not all(coordinate_entry_complete(control.value) for control in row["points"]):
                row["error"].set_visibility(False)
                if row["preview_marker"] is not None:
                    markers.append(copy.deepcopy(row["preview_marker"]))
                continue
            try:
                marker = self.read_row(row)
                validate_markers([marker])
            except (ValueError, TypeError, OverflowError) as exc:
                row["preview_marker"] = None
                message = f"Hidden in preview: {exc}"
                row["error"].set_text(message)
                row["error"].set_visibility(True)
                errors.append(message)
            else:
                row["error"].set_visibility(False)
                row["preview_marker"] = copy.deepcopy(marker)
                self.update_size_control(row, marker)
                markers.append(marker)
        return markers, errors

    def update_size_control(self, row, marker):
        if marker is None or marker.kind != "point" or row["size_edited"]:
            return
        _, scale = point_marker_size(marker, self.model)
        row["updating_size"] = True
        try:
            row["atom_scale"].value = round(100 * scale, 8)
        finally:
            row["updating_size"] = False

    def update_model(self, model):
        self.model = model
        for row in self.rows:
            self.update_size_control(row, row["preview_marker"])

    def size_changed(self, row):
        if self.loading or row["updating_size"]:
            return
        row["size_edited"] = True
        self.changed()

    def load(self, markers: list[CrystalMarker], opened: int | None = None) -> None:
        from nicegui import ui
        self.cancel_pick()
        self.loading = True
        self.container.clear()
        self.rows = []
        with self.container:
            for index, original in enumerate(markers):
                marker = normalize_marker(original)
                with ui.expansion(f"{index + 1}. {marker.name or MARKER_KINDS[marker.kind]}", value=index == opened).classes("full-width"):
                    row = {"marker": copy.deepcopy(marker), "points": [], "pick_buttons": [], "preview_marker": None,
                           "size_edited": marker.atom_scale is not None, "updating_size": False}
                    try:
                        validate_markers([marker])
                        row["preview_marker"] = copy.deepcopy(marker)
                    except (ValueError, TypeError, OverflowError):
                        pass
                    with ui.row().classes("items-center full-width gap-1"):
                        row["visible"] = ui.checkbox("Visible", value=marker.visible).props("dense")
                        row["show_label"] = ui.checkbox("Label", value=marker.show_label).props("dense")
                        row["show_label"].tooltip("Show the marker name. Also enable Crystal annotations on the main toolbar.")
                        row["show_label"].on_value_change(self.label_changed)
                        ui.space()
                        ui.button(icon="content_copy", on_click=lambda i=index: self.edit(i, "duplicate")).props("flat round dense").tooltip("Duplicate marker")
                        ui.button(icon="delete", on_click=lambda i=index: self.edit(i, "delete")).props("flat round dense color=negative").tooltip("Delete marker")
                    with ui.element("div").classes("marker-fields"):
                        row["name"] = ui.input("Marker name", value=marker.name).props("outlined dense maxlength=80")
                        row["coordinates"] = ui.select(COORDINATE_MODES, value=marker.coordinates, label="Coordinates").props("outlined dense")
                        row["coordinates"].on_value_change(lambda event, r=row: self.convert(r, event.value))
                        row["positions"] = ui.column().classes("marker-positions")
                        if marker.kind != "point":
                            row["sortable"] = row["positions"].make_sortable(
                                options={"forceFallback": True, "fallbackTolerance": 4,
                                         "chosenClass": "marker-vertex-chosen", "fallbackClass": "marker-vertex-ghost"},
                                handle=".marker-vertex-drag",
                                on_end=lambda event, r=row: self.move_vertex(r, event.old_index, event.new_index))
                            row["sortable"].move(row["positions"].parent_slot.parent)
                        self.build_positions(row, [point_text(point) for point in marker.points])
                        if marker.kind in {"plane", "polyhedron"}:
                            row["add_vertex"] = ui.button("Add vertex", icon="add", on_click=lambda i=index: self.edit_vertex(i, None, "add")).props("outline dense").set_enabled(len(marker.points) < MAX_VERTICES)
                        row["color"] = ui.color_input("Marker color", value=marker.color, preview=True).props("outlined dense")
                        row["hide_atom"] = ui.checkbox("Transparent (hide atom)", value=marker.hide_atom).props("dense")
                        row["hide_atom"].set_visibility(marker.kind == "point")
                        row["hide_atom"].tooltip("Hide only the atom at this exact 3D position. Frame lines, other atoms, and diffraction are unchanged. Uncheck or delete this marker to restore it.")
                        row["point_style"] = ui.select({"ring": "Circle (faces viewer)", "sphere": "Colored sphere"}, label="Point style", value=marker.point_style).props("outlined dense")
                        row["point_style"].set_visibility(marker.kind == "point")
                        row["line_style"] = ui.select(LINE_STYLES, label="Line style", value=marker.line_style).props("outlined dense")
                        row["line_style"].tooltip("A single-headed arrow points from Position A to Position B.")
                        row["line_style"].set_visibility(marker.kind == "line")
                        scale = point_marker_size(marker, self.model)[1] if marker.kind == "point" else 1.0
                        row["atom_scale"] = ui.number("Marker size", value=round(100 * scale, 8), min=1, max=900, step=10, suffix="%").props("outlined dense")
                        row["atom_scale"].tooltip("Defaults to the atom's size at this exact position, or All atom sizes at an empty position. Enter a percentage to override; element-specific and All atom sizes factors multiply for a matched atom.")
                        row["atom_scale"].on_value_change(lambda r=row: self.size_changed(r))
                        row["width"] = ui.number("Line thickness", value=marker.width, min=.00001, max=1, step=.001, suffix="nm").props("outlined dense")
                        row["opacity"] = ui.number("Marker opacity", value=100 * marker.opacity, min=0, max=100, suffix="%").props("outlined dense")
                        row["fill_opacity"] = ui.number("Fill opacity", value=100 * marker.fill_opacity, min=0, max=100, suffix="%").props("outlined dense")
                        row["fill_opacity"].set_visibility(marker.kind in {"plane", "polyhedron"})
                        row["edge_style"] = ui.select(EDGE_STYLES, label="Edge style",
                            value="dashed" if marker.dashed and marker.edge_style == "solid" else marker.edge_style).props("outlined dense")
                        row["edge_style"].set_visibility(marker.kind != "point")
                        def update_point_controls(r=row):
                            point = r["marker"].kind == "point"
                            r["atom_scale"].set_visibility(point)
                            for key in ("atom_scale", "point_style", "color", "opacity"):
                                r[key].set_enabled(not r["hide_atom"].value)
                            r["width"].set_enabled(not r["hide_atom"].value and not (point and r["point_style"].value == "sphere"))
                        update_point_controls()
                        row["point_style"].on_value_change(update_point_controls)
                        row["hide_atom"].on_value_change(update_point_controls)
                    with ui.element("div").classes("marker-fields").bind_visibility_from(row["show_label"], "value"):
                        row["label_size"] = ui.number("Label size", value=marker.label_size, min=6, max=72, suffix="px").props("outlined dense")
                        row["label_opacity"] = ui.number("Label opacity", value=100 * marker.label_opacity, min=0, max=100, suffix="%").props("outlined dense")
                        row["label_position"] = ui.select({key: key.replace("_", " ").title() for key in LABEL_POSITIONS},
                            label="Label position", value=marker.label_position).props("outlined dense")
                        row["label_position"].tooltip("Screen-relative position around the marker's center, maintained as the crystal rotates.")
                        row["label_gap"] = ui.number("Label gap", value=marker.label_gap, min=0, max=200, suffix="px").props("outlined dense")
                        row["label_same_color"] = ui.checkbox("Use marker color for label", value=not marker.label_color).props("dense")
                        row["label_color"] = ui.color_input("Label color", value=marker.label_color or marker.color, preview=True).props("outlined dense")
                        row["label_color"].bind_enabled_from(row["label_same_color"], "value", lambda value: not value)
                    row["error"] = ui.label().classes("text-warning text-caption full-width break-words marker-error")
                    row["error"].set_visibility(False)
                    for key in ("name", "color", "visible", "edge_style", "point_style", "line_style", "width", "opacity", "fill_opacity",
                                "hide_atom", "label_size", "label_opacity", "label_position", "label_gap", "label_same_color", "label_color"):
                        row[key].on_value_change(self.changed)
                    self.rows.append(row)
        self.loading = False

    def build_positions(self, row, values):
        from nicegui import ui
        row["positions"].clear()
        row["vertices"], row["points"], row["pick_buttons"] = [], [], []
        surface = row["marker"].kind in {"plane", "polyhedron"}
        movable = row["marker"].kind != "point"
        with row["positions"]:
            for value in values:
                vertex = {}
                with ui.element("div").classes("marker-vertex-row") as vertex["container"]:
                    if movable:
                        vertex["handle"] = ui.button(icon="drag_indicator").props("flat round dense size=sm").classes("marker-vertex-drag").tooltip("Hold and drag to reorder position")
                    else:
                        vertex["container"].style("grid-template-columns:minmax(0,1fr)")
                    with ui.column().classes("marker-vertex-fields"):
                        if movable:
                            with ui.row().classes("full-width items-center gap-1"):
                                vertex["label"] = ui.label().classes("text-caption")
                                ui.space()
                                for action, icon, title in (("up", "arrow_upward", "Move position up"), ("down", "arrow_downward", "Move position down"), ("delete", "close", "Remove vertex")):
                                    if action == "delete" and not surface:
                                        continue
                                    vertex[action] = ui.button(icon=icon, on_click=lambda r=row, v=vertex, a=action: self.vertex_action(r, v, a)).props("flat round dense").tooltip(title)
                        with ui.element("div").classes("full-width marker-position items-center"):
                            with ui.element("div").classes("marker-pick-position"):
                                control = ui.input(value=value).props("outlined dense").classes("flex-1 min-w-0")
                                control.tooltip("Three coordinates; decimals, negatives and fractions such as 1/2 are accepted.")
                                control.on_value_change(self.changed)
                                pick = ui.button(icon="my_location").props("flat round dense aria-pressed=false").classes("marker-pick-button").tooltip("Pick an atom in the crystal preview for this position. Click again to cancel.")
                                pick.on_click(lambda r=row, target=control, button=pick: self.start_pick(r, target, button))
                            row["points"].append(control)
                            row["pick_buttons"].append(pick)
                            options = {i: f"{atom.element}: ({point_text(frac)})" for i, (atom, frac) in enumerate(self.atom_points)}
                            select = ui.select(options, label="Atom position", with_input=True).props("outlined dense clearable stack-label")
                            select.tooltip("Displayed atom positions, in fractional coordinates; first 500 atoms.")
                            select.on_value_change(lambda event, r=row, target=control, s=select: self.pick_atom(r, target, s, event.value))
                row["vertices"].append(vertex)
        self.update_position_labels(row)

    def update_position_labels(self, row):
        surface = row["marker"].kind in {"plane", "polyhedron"}
        count = len(row["points"])
        for index, (vertex, control, pick) in enumerate(zip(row["vertices"], row["points"], row["pick_buttons"])):
            label = f"Vertex {index + 1}" if surface else f"Position {'ABC'[index]}"
            control.set_label(f"{label} (x, y, z)")
            pick.props(f"aria-label='Pick atom for {label}'")
            if "label" in vertex:
                vertex["label"].set_text(label)
                vertex["handle"].props(f"aria-label='Drag {label}'")
                vertex["up"].set_enabled(index > 0)
                vertex["down"].set_enabled(index < count - 1)
                if surface:
                    vertex["delete"].set_enabled(count > (3 if row["marker"].kind == "plane" else 4))
        if "add_vertex" in row:
            row["add_vertex"].set_enabled(count < MAX_VERTICES)

    def vertex_action(self, row, vertex, action):
        index = next(i for i, item in enumerate(self.rows) if item is row)
        self.edit_vertex(index, row["vertices"].index(vertex), action)

    def move_vertex(self, row, index, target):
        if self.loading or not any(item is row for item in self.rows):
            return
        if not (0 <= index < len(row["points"]) and 0 <= target < len(row["points"])) or index == target:
            return
        self.cancel_pick()
        for key in ("vertices", "points", "pick_buttons"):
            row[key].insert(target, row[key].pop(index))
        row["vertices"][target]["container"].move(target_container=row["positions"], target_index=target)
        self.update_position_labels(row)
        self.changed()

    def changed(self):
        if not self.loading:
            self.on_change()

    def label_changed(self, event):
        if self.loading:
            return
        if event.value and not self.annotations_enabled():
            from nicegui import ui
            ui.notify("Marker labels are hidden. Enable Crystal annotations on the main toolbar to show them.", type="info")
        self.changed()

    def add(self, kind):
        from nicegui import ui
        try:
            markers = self.read()
            points = {"point": [(0,0,0)], "line": [(0,0,0),(1,0,0)],
                      "plane": [(0,0,0),(1,0,0),(0,1,0)],
                      "polyhedron": [(0,0,0),(1,0,0),(0,1,0),(0,0,1)]}[kind]
            markers.append(CrystalMarker(kind=kind, name=f"{MARKER_KINDS[kind]} {len(markers) + 1}", points=points))
            validate_markers(markers)
            self.load(markers, len(markers) - 1)
            self.changed()
        except (ValueError, TypeError) as exc:
            ui.notify(str(exc), type="warning")

    def edit(self, index, action):
        from nicegui import ui
        try:
            # Deletion remains possible even if this marker has incomplete edits.
            if action == "delete":
                row = self.rows.pop(index)
                try:
                    markers = self.read()
                finally:
                    self.rows.insert(index, row)
            else:
                markers = self.read()
                markers.insert(index + 1, copy.deepcopy(markers[index]))
            validate_markers(markers)
            self.load(markers, min(index, len(markers) - 1))
            self.changed()
        except (ValueError, TypeError) as exc:
            ui.notify(str(exc), type="warning")

    def edit_vertex(self, index, vertex, action):
        from nicegui import ui
        try:
            row = self.rows[index]
            if action in {"up", "down"}:
                self.move_vertex(row, vertex, vertex + (-1 if action == "up" else 1))
                return
            values = [control.value for control in row["points"]]
            kind = row["marker"].kind
            minimum = 3 if kind == "plane" else 4
            if action == "add" and len(values) < MAX_VERTICES:
                points = [parse_point(value) for value in values]
                if kind == "plane":
                    point = .5 * (np.asarray(points[-1]) + points[0])
                else:
                    center = np.mean(points, axis=0)
                    furthest = np.argmax(np.linalg.norm(np.asarray(points) - center, axis=1))
                    point = center + 1.3 * (np.asarray(points[furthest]) - center)
                values.append(point_text(point))
            elif action == "delete" and len(values) > minimum:
                values.pop(vertex)
            else:
                return
            self.cancel_pick()
            self.build_positions(row, values)
            self.changed()
        except (ValueError, TypeError) as exc:
            ui.notify(str(exc), type="warning")

    def convert(self, row, mode):
        from nicegui import ui
        old = row["marker"].coordinates
        if old == mode:
            return
        try:
            points = np.array([parse_point(control.value) for control in row["points"]])
            points = points @ self.model.lattice if mode == "cartesian" else np.linalg.solve(self.model.lattice.T, points.T).T
            converted = [point_text(point) for point in points]
            for text in converted:
                parse_point(text)
        except (ValueError, TypeError) as exc:
            row["coordinates"].value = old
            ui.notify(str(exc), type="warning")
            return
        self.loading = True
        row["marker"].coordinates = mode
        for control, text in zip(row["points"], converted):
            control.value = text
        self.loading = False
        self.changed()

    def pick_atom(self, row, target, select, index):
        if index is None:
            return
        self.cancel_pick()
        _, point = self.atom_points[index]
        if row["coordinates"].value == "cartesian":
            point = point @ self.model.lattice
        target.value = point_text(point)
        select.value = None

    def start_pick(self, row, target, button):
        same_target = self.pick_target is not None and self.pick_target[1] is target
        self.cancel_pick()
        if same_target:
            return
        self.pick_target = (row, target, button)
        target.classes(add="marker-position-picking")
        button.props("icon=close color=secondary aria-pressed=true")
        self.on_pick_change(True)

    def cancel_pick(self):
        if self.pick_target is None:
            return
        _, target, button = self.pick_target
        self.pick_target = None
        target.classes(remove="marker-position-picking")
        button.props("icon=my_location color=primary aria-pressed=false")
        self.on_pick_change(False)

    def pick_from_scene(self, atom, model) -> bool:
        if self.pick_target is None:
            return False
        row, target, _ = self.pick_target
        # Use the currently displayed origin, including any newly expanded cells.
        offset = atom.position - model.display_origin
        point = (offset * model.scale_nm if row["coordinates"].value == "cartesian"
                 else np.linalg.solve(model.display_lattice.T, offset))
        self.cancel_pick()
        target.value = point_text(point)
        return True
