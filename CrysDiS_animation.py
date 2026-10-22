"""Panel-local animation trajectories, offline rendering, and export dialog."""
from __future__ import annotations

import asyncio
import copy
import io
import json
import math
import re
import shutil
import tempfile
import threading
import uuid
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from nicegui import ui
from PIL import GifImagePlugin, Image, ImageColor, ImageDraw, ImageFont
from scipy.spatial.transform import Rotation

RENDER_LOCK = threading.Lock()
PREVIEW_MAX_FPS = 10
PREVIEW_MAX_HEIGHT = 360

@dataclass
class AnimationStep:
    kind: str = "rotate"
    axis: str = "001"
    frame: str = "crystal"
    angle: float = 360.0
    seconds: float = 4.0
    easing: str = "linear"
    snap_back: bool = False
    with_previous: bool = False
    reference_panel_id: int | None = None


@dataclass
class MotionSegment:
    start: np.ndarray
    rotvec: np.ndarray
    seconds: float
    easing: str
    local: bool = False

    def delta_at(self, fraction: float) -> np.ndarray:
        t = float(np.clip(fraction, 0, 1))
        if self.easing == "smooth":
            t = t * t * (3 - 2 * t)
        return Rotation.from_rotvec(self.rotvec * t).as_matrix()

    def at(self, fraction: float) -> np.ndarray:
        delta = self.delta_at(fraction)
        return self.start @ delta if self.local else delta @ self.start


@dataclass
class MotionGroup:
    start: np.ndarray
    motions: list[MotionSegment]

    @property
    def seconds(self) -> float:
        return max(motion.seconds for motion in self.motions)

    def at(self, fraction: float) -> np.ndarray:
        elapsed = float(np.clip(fraction, 0, 1)) * self.seconds
        frame = self.start.copy()
        # Align the zone first, then compose rotations in list order at the same time.
        for motion in self.motions:
            delta = motion.delta_at(elapsed / motion.seconds)
            frame = frame @ delta if motion.local else delta @ frame
        return frame


def read_axis(api: Any, model: Any, text: str, *, reciprocal: bool = False) -> np.ndarray:
    pattern = r"[^0-9+\-\s,;()\[\]{}<>*rR]" if reciprocal else r"[^0-9+\-\s,;()\[\]{}<>]"
    if re.search(pattern, api.normalize_text(text)):
        raise ValueError("Invalid axis.")
    parsed, errors = api.parse_indices(text, model, "direction", False, allow_reciprocal=reciprocal)
    if errors or len(parsed) != 1:
        raise ValueError("Enter one nonzero axis, such as 001 or [1,1,0].")
    return parsed[0].vector


def compile_step(api: Any, model: Any, frame: np.ndarray, step: AnimationStep) -> MotionSegment:
    seconds = float(step.seconds)
    if not math.isfinite(seconds) or not 0.05 <= seconds <= 600:
        raise ValueError("Duration must be between 0.05 and 600 seconds.")
    if step.easing not in {"linear", "smooth"}:
        raise ValueError("Unknown speed profile.")
    rotvec = np.zeros(3)
    local = False
    if step.kind == "zone":
        axis = read_axis(api, model, step.axis)
        if step.snap_back:
            target = api.orientation_frame(axis, 0.0)
            rotvec = Rotation.from_matrix(target @ frame.T).as_rotvec()
        else:
            old_view = frame[:, 2]
            cross = np.cross(old_view, axis)
            sine = float(np.linalg.norm(cross))
            cosine = float(np.clip(np.dot(old_view, axis), -1, 1))
            if sine > 1e-10:
                rotvec = cross / sine * math.atan2(sine, cosine)
            elif cosine < 0:
                # Opposite directions have infinitely many minimal paths; use screen up.
                rotvec = frame[:, 1] * math.pi
    elif step.kind == "rotate":
        angle = float(step.angle)
        if not math.isfinite(angle) or abs(angle) > 360000:
            raise ValueError("Rotation must be finite and at most 1000 turns.")
        if step.frame == "lab":
            values = re.split(r"[\s,]+", step.axis.strip().strip("[]()"))
            if len(values) != 3:
                raise ValueError("Lab axes need three components: X=1,0,0; Y=0,1,0; Z=0,0,1.")
            axis = np.array([float(value) for value in values])
            if not np.isfinite(axis).all() or np.linalg.norm(axis) < 1e-12:
                raise ValueError("Lab axis must be finite and nonzero.")
            axis = axis / np.linalg.norm(axis)
            local = True
        elif step.frame == "crystal":
            axis = read_axis(api, model, step.axis, reciprocal=True)
        else:
            raise ValueError("Unknown reference frame.")
        # Keep the original signed angle, including complete revolutions.
        rotvec = -axis * math.radians(angle)
    elif step.kind != "hold":
        raise ValueError("Unknown animation step.")
    return MotionSegment(frame.copy(), rotvec, seconds, step.easing, local)


def compile_motion(api: Any, model: Any, start: np.ndarray, steps: list[AnimationStep], *,
                   references: dict[int, tuple[Any, np.ndarray]] | None = None) -> list[MotionSegment | MotionGroup]:
    if not steps:
        raise ValueError("Add at least one animation step.")
    frame = np.array(start, dtype=float, copy=True)
    if (frame.shape != (3, 3) or not np.isfinite(frame).all()
            or not np.allclose(frame.T @ frame, np.eye(3), atol=1e-6) or not np.isclose(np.linalg.det(frame), 1)):
        raise ValueError("Invalid starting orientation.")
    groups: list[list[tuple[int, AnimationStep]]] = []
    for index, step in enumerate(steps, 1):
        if step.with_previous:
            if not groups:
                raise ValueError("Step 1 cannot start with a previous step.")
            group = groups[-1]
            if step.kind == "hold" or any(item.kind == "hold" for _, item in group):
                raise ValueError(f"Step {index}: pauses must run separately.")
            if step.kind == "zone" and any(item.kind == "zone" for _, item in group):
                raise ValueError(f"Step {index}: simultaneous steps can contain only one zone-axis target.")
            group.append((index, step))
        else:
            groups.append([(index, step)])
    segments = []
    for group in groups:
        group_start = frame.copy()
        motions = []
        for index, step in sorted(group, key=lambda item: item[1].kind != "zone"):
            try:
                if references is None or step.kind == "hold":
                    motion = compile_step(api, model, frame, step)
                else:
                    if step.reference_panel_id not in references:
                        raise ValueError("Choose a participating reference panel.")
                    reference_model, relation = references[step.reference_panel_id]
                    motion = compile_step(api, reference_model, relation @ frame, step)
                    # Express each crystal's motion in the anchor crystal's coordinates.
                    # Screen-frame rotations already share coordinates across every panel.
                    motion = MotionSegment(frame.copy(), motion.rotvec if motion.local else relation.T @ motion.rotvec,
                                           motion.seconds, motion.easing, motion.local)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Step {index}: {exc}") from exc
            motions.append(motion)
            frame = motion.at(1)
        segments.append(motions[0] if len(motions) == 1 else MotionGroup(group_start, motions))
    return segments


def compile_bound_motion(api: Any, models: dict[int, Any], starts: dict[int, np.ndarray],
                         steps: list[AnimationStep]) -> list[MotionSegment | MotionGroup]:
    if not starts or set(models) != set(starts):
        raise ValueError("Choose available panels for the animation.")
    for frame in starts.values():
        if (frame.shape != (3, 3) or not np.isfinite(frame).all()
                or not np.allclose(frame.T @ frame, np.eye(3), atol=1e-6) or not np.isclose(np.linalg.det(frame), 1)):
            raise ValueError("Invalid starting orientation.")
    anchor_id = next(iter(starts))
    anchor = starts[anchor_id]
    references = {panel_id: (models[panel_id], frame @ anchor.T) for panel_id, frame in starts.items()}
    return compile_motion(api, models[anchor_id], anchor, steps, references=references)


def bound_frames_at(starts: dict[int, np.ndarray], segments: list[MotionSegment | MotionGroup],
                    time_seconds: float) -> dict[int, np.ndarray]:
    anchor = next(iter(starts.values()))
    delta = anchor.T @ motion_at(segments, time_seconds)
    return {panel_id: frame @ delta for panel_id, frame in starts.items()}


def motion_at(segments: list[MotionSegment | MotionGroup], time_seconds: float) -> np.ndarray:
    elapsed = 0.0
    for segment in segments:
        if time_seconds <= elapsed + segment.seconds:
            return segment.at((time_seconds - elapsed) / segment.seconds)
        elapsed += segment.seconds
    return segments[-1].at(1)


def frame_schedule(segments: list[MotionSegment | MotionGroup], fps: float) -> tuple[np.ndarray, np.ndarray]:
    if not math.isfinite(fps) or not 1 <= fps <= 60:
        raise ValueError("Frame rate must be between 1 and 60 fps.")
    duration = sum(segment.seconds for segment in segments)
    count = max(2, int(round(duration * fps)))
    if count > 5000:
        raise ValueError("This export exceeds 5000 frames. Reduce the duration or frame rate.")
    # Include both endpoints, while keeping playback duration equal to the requested duration.
    times = np.linspace(0, duration, count)
    boundaries = np.rint(np.linspace(0, duration * 100, count + 1)).astype(int)
    return times, np.diff(boundaries) * 10


def animation_extent(api: Any, model: Any, state: Any) -> float:
    points = [point for edge in (model.bounds_edges if model.bounds_edges is not None else model.display_edges) for point in edge]
    points.extend(atom.position for atom in model.display_atoms)
    vectors, _ = api.parse_indices(state.vector_text, model, "direction", True, True)
    for vector in vectors:
        fn = api.reciprocal_segment_for_display if vector.is_reciprocal else api.direction_segment_for_display
        points.extend(fn(vector.values, model))
    return max(1.0, 2.7 * max((np.linalg.norm(point) for point in points), default=1.0))


def export_snapshot(api: Any, controller: Any, method: str) -> Any:
    """Reuse the scientific methods with private caches and frozen settings, without UI references."""
    source = controller.simulator
    simulator = object.__new__(api.SimulatorApp)
    simulator.element_colors = copy.deepcopy(getattr(source, "element_colors", {}))
    simulator.global_display_settings = copy.deepcopy(getattr(source, "global_display_settings", api.PanelDisplaySettings()))
    for name in ("model_cache", "reciprocal_table_cache", "diffraction_spot_cache", "pymatgen_tem_cache"):
        setattr(simulator, name, {})
    for name in ("current_voltage_kv", "current_thickness_nm", "current_max_hkl",
                 "current_spot_intensity_threshold", "current_spot_size_scaling_effect",
                 "current_intensity_compression_factor", "uniform_spot_brightness", "current_camera_length_mm",
                 "current_diffraction_limit", "show_indices", "show_crystal_annotations",
                 "show_scale_bars", "show_zone_axis_on_diffraction", "use_hex_four_index_basis"):
        value = getattr(source, name)()
        setattr(simulator, name, lambda value=value: value)
    simulator.current_simulation_method = lambda: method
    model = copy.deepcopy(source.model_for(controller.state.crystal_name))
    simulator.model_for = lambda _name: model
    for name in ("plane_palette", "vector_palette"):
        palette = list(getattr(source, name)(controller.state.panel_id))
        setattr(simulator, name, lambda _id=None, palette=palette: palette)

    def fail(message: str) -> None:
        raise RuntimeError(message)

    simulator.set_status = fail
    snapshot = api.PanelController(simulator, copy.deepcopy(controller.state))
    snapshot.current_model = snapshot.display_model(model)
    return snapshot


def render_diffraction(api: Any, controller: Any, size: int, transparent: bool,
                       sources: list[Any] | None = None) -> Image.Image:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    sim, state, model = controller.simulator, controller.state, controller.current_model
    limit = sim.current_diffraction_limit()
    dpi = size / 3.6
    fig = Figure(figsize=(3.6, 3.6), dpi=dpi, facecolor="none" if transparent else "#050607")
    FigureCanvasAgg(fig)
    ax = fig.add_axes([0, 0, 1, 1], facecolor="none")
    ax.set(xlim=(-limit, limit), ylim=(-limit, limit), aspect="equal")
    ax.set_axis_off()

    def draw_annotation(annotation):
        font = annotation["font"]
        ax.annotate(annotation["text"].replace("<sup>-1</sup>", "$^{-1}$"),
                    xy=(annotation["x"], annotation["y"]),
                    xytext=(annotation.get("xshift", 0) * .65, annotation.get("yshift", 0) * .65),
                    textcoords="offset points", color=font["color"], fontsize=font["size"] * .65,
                    alpha=annotation.get("opacity", 1),
                    ha=annotation.get("xanchor", "center"),
                    va={"middle": "center"}.get(annotation.get("yanchor"), annotation.get("yanchor", "center")))

    for source in reversed(sources or [controller]):
        source_sim, source_state, source_model = source.simulator, source.state, source.current_model
        spots = source_sim.diffraction_spots_for_state(source_state, source_model)
        if not len(spots):
            continue
        intensity = spots[:, 2]
        marker = api.BASE_DIFFRACTION_MARKER_SIZE + api.EXTRA_DIFFRACTION_MARKER_SIZE * sim.current_spot_size_scaling_effect() * intensity ** 1.18
        colors = [(*api.color_to_rgb(source_state.diffraction_color), float(alpha))
                  for alpha in source_sim.diffraction_spot_opacities(intensity, combo=bool(sources))]
        ax.scatter(spots[:, 0], spots[:, 1], s=(marker * 0.65) ** 2, c=colors, linewidths=0)
        if sim.show_indices():
            labels = [api.diffraction_label_for_hkl(*map(int, spot[3:6]), source_model, sim.use_hex_four_index_basis()) for spot in spots]
            for label in controller.diffraction_index_annotations(spots, limit, labels, source_state.display_settings.annotations, marker):
                draw_annotation(label)
    settings = sim.global_annotation_settings() if sources else state.display_settings.annotations
    if sim.show_scale_bars():
        shapes, labels = api.diffraction_scale_bar_items(limit, sim.current_reciprocal_units_per_plot_unit(), settings)
        for shape in shapes:
            ax.plot([shape["x0"], shape["x1"]], [shape["y0"], shape["y1"]],
                    color=shape["line"]["color"], linewidth=shape["line"]["width"] * .65, alpha=shape["opacity"])
        for label in labels:
            draw_annotation(label)
    if sim.show_zone_axis_on_diffraction():
        label = api.zone_axis_label_from_view(model, state.view_vector, use_hex_four_index=sim.use_hex_four_index_basis())
        draw_annotation(api.diffraction_zone_axis_annotation(limit, label, settings, sim.show_scale_bars()))
    fig.canvas.draw()
    return Image.fromarray(np.asarray(fig.canvas.buffer_rgba()).copy())


def render_frame(api: Any, controller: Any, frame: np.ndarray, height: int, content: str,
                 transparent: bool, extent: float, crystal_png: bytes | None = None,
                 show_crystal_name: bool = False, shaded_atoms: bool = False,
                 atom_shading: str | None = None, occupancy_colors: str = "panel") -> bytes:
    controller.state.view_vector, controller.state.roll = api.orientation_from_frame(frame)
    images = []
    if content != "diffraction":
        png = crystal_png or controller.render_crystal_png(
            max(72, height / 3.6), transparent, frame_size=(height, height), fixed_extent=extent,
            shaded_atoms=shaded_atoms, atom_shading=atom_shading, occupancy_colors=occupancy_colors)
        with Image.open(io.BytesIO(png)) as image:
            images.append(image.convert("RGBA"))
    if content != "crystal":
        images.append(render_diffraction(api, controller, height, transparent))
    result = Image.new("RGBA", (height * len(images), height), (0, 0, 0, 0))
    for index, image in enumerate(images):
        result.paste(image, (index * height, 0))
        image.close()
    if show_crystal_name:
        titled = compose_animation_tiles([(controller.state.crystal_name, result)], transparent)
        result.close()
        result = titled
    buffer = io.BytesIO()
    result.save(buffer, format="PNG")
    result.close()
    return buffer.getvalue()


CONTENT_OPTIONS = {"both": "Crystal + diffraction", "crystal": "Crystal only", "diffraction": "Diffraction only"}
COMBO_LAYOUTS = {
    "crystals_combo": "Crystals + combined diffraction",
    "grid": "Individual panels in one image",
    "separate": "Separate files for each panel",
    "combo": "Combined diffraction only",
}


def compose_animation_tiles(tiles: list[tuple[str, Image.Image]], transparent: bool,
                            show_crystal_name: bool = True) -> Image.Image:
    """Compose tiles without changing their scale; omit the title band when hidden."""
    columns = min(2, len(tiles))
    width = max(tile.width for _, tile in tiles)
    height = max(tile.height for _, tile in tiles)
    heading = max(24, height // 14) if show_crystal_name else 0
    gap = max(4, height // 60)
    size = (columns * width + (columns - 1) * gap,
            math.ceil(len(tiles) / columns) * (height + heading + gap) - gap)
    if size[0] * size[1] > 32_000_000:
        raise ValueError("Combined image exceeds 32 megapixels. Reduce the frame size or use separate files.")
    result = Image.new("RGBA", size, (0, 0, 0, 0) if transparent else (11, 15, 20, 255))
    if show_crystal_name:
        draw = ImageDraw.Draw(result)
        try:
            font = ImageFont.load_default(size=max(12, heading // 2))
        except TypeError:  # Pillow 10.0 does not accept a size for its bundled font.
            font = ImageFont.load_default()
    for index, (title, tile) in enumerate(tiles):
        x = (index % columns) * (width + gap)
        y = (index // columns) * (height + heading + gap)
        if show_crystal_name:
            while title and draw.textlength(title, font=font) > width - 16:
                title = title[:-4] + "..." if len(title) > 4 else ""
            draw.text((x + 8, y + 4), title, font=font, fill="#80909F" if transparent else "#F7FAFC")
        result.paste(tile, (x, y + heading))
    return result


def render_bound_layout(api: Any, snapshots: dict[int, Any], panel_paths: dict[int, Path],
                        layout: str, height: int, transparent: bool,
                        show_crystal_name: bool = True) -> bytes:
    images = []
    tiles = []
    try:
        for panel_id, path in panel_paths.items():
            with Image.open(path) as source:
                image = source.convert("RGBA")
            images.append(image)
            state = snapshots[panel_id].state
            tiles.append((state.crystal_name, image))
        if layout in {"combo", "crystals_combo"}:
            sources = list(snapshots.values())
            image = render_diffraction(api, sources[0], height, transparent, sources=sources)
            images.append(image)
            tiles.append((" + ".join(source.state.crystal_name for source in sources), image))
        result = compose_animation_tiles(tiles, transparent, show_crystal_name)
        images.append(result)
        buffer = io.BytesIO()
        result.save(buffer, format="PNG")
        return buffer.getvalue()
    finally:
        for image in images:
            image.close()


def package_panel_animations(streams: dict[int, list[Path]], output: Path, durations: np.ndarray,
                             metadata: dict, gif: bool, loop: bool, cancelled: threading.Event) -> None:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for panel_id, paths in streams.items():
            if cancelled.is_set():
                raise ExportCancelled()
            name = f"panel_{panel_id}"
            if gif:
                panel_metadata = {**metadata, **metadata["panels"][str(panel_id)]}
                destination = output.parent / f"{name}.gif"
                encode_animation(paths, destination, durations, panel_metadata, loop, cancelled)
                archive.write(destination, destination.name)
            else:
                for path in paths:
                    if cancelled.is_set():
                        raise ExportCancelled()
                    archive.write(path, f"{name}/{path.name}")
        archive.writestr("animation.json", json.dumps(metadata, indent=2))


class ExportCancelled(Exception):
    pass


def gif_transparency_mask(alpha: np.ndarray) -> np.ndarray:
    # Screen-fixed ordered coverage preserves partial alpha without frame-to-frame random noise.
    bayer = np.array([[0, 2], [3, 1]])
    for _ in range(2):
        bayer = np.block([[4 * bayer, 4 * bayer + 2], [4 * bayer + 3, 4 * bayer + 1]])
    thresholds = (bayer + 0.5) * (255.0 / 64)
    return alpha <= thresholds[np.arange(alpha.shape[0])[:, None] % 8, np.arange(alpha.shape[1])[None, :] % 8]


def gif_rgb_image(image: Image.Image, matte: tuple[int, int, int] | None) -> Image.Image:
    if matte is None:
        return image.convert("RGB")
    # Bake partial alpha into RGB for the chosen slide color, not into pixel holes.
    with image.convert("RGBA") as rgba, Image.new("RGBA", image.size, (*matte, 255)) as background:
        with Image.alpha_composite(background, rgba) as composite:
            return composite.convert("RGB")


def encode_animation(paths: list[Path], output: Path, durations: np.ndarray, metadata: dict,
                     loop: bool, cancelled: threading.Event) -> None:
    def check() -> None:
        if cancelled.is_set():
            raise ExportCancelled()

    if output.suffix == ".zip":
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
            for path in paths:
                check()
                archive.write(path, path.name)
            archive.writestr("animation.json", json.dumps(metadata, indent=2))
        return
    transparent = bool(metadata.get("transparent_background", False))
    mode = metadata.get("gif_transparency", "matte") if transparent else None
    if mode not in {None, "matte", "dither"}:
        raise ValueError("Unknown GIF transparency mode.")
    matte = ImageColor.getcolor(metadata.get("gif_matte_color", "#FFFFFF"), "RGB") if mode == "matte" else None
    # A shared palette avoids color flicker. Stream encoded frames rather than retain full rasters.
    samples = []
    for index in np.unique(np.linspace(0, len(paths) - 1, min(24, len(paths))).astype(int)):
        check()
        with Image.open(paths[index]) as image:
            sample = gif_rgb_image(image, matte)
            sample.thumbnail((160, 160))
            samples.append(sample)
    atlas = Image.new("RGB", (160 * len(samples), 160), matte or "#0B0F14")
    for index, sample in enumerate(samples):
        atlas.paste(sample, (160 * index, 0))
        sample.close()
    palette = atlas.quantize(colors=255 if transparent else 256)
    atlas.close()
    if transparent:
        colors = (palette.getpalette() or [])[:765]
        colors += [0] * (765 - len(colors))
        palette.putpalette(colors + colors[:3])
    with output.open("wb") as stream:
        for index, path in enumerate(paths):
            check()
            with Image.open(path) as image:
                with gif_rgb_image(image, matte) as rgb:
                    frame = rgb.quantize(palette=palette, dither=Image.Dither.NONE)
                if transparent:
                    indices = np.array(frame)
                    indices[indices == 255] = 0
                    with image.convert("RGBA") as rgba:
                        alpha = np.array(rgba)[:, :, 3]
                    mask = alpha == 0 if mode == "matte" else gif_transparency_mask(alpha)
                    indices[mask] = 255
                    frame.close()
                    frame = Image.fromarray(indices)
                    frame.putpalette(palette.getpalette())
            if index == 0:
                info = {"duration": int(durations[0])}
                if loop:
                    info["loop"] = 0
                if transparent:
                    info.update(transparency=255, background=255)
                header, _ = GifImagePlugin.getheader(frame, info=info)
                for block in header:
                    stream.write(block)
            options = {"transparency": 255} if transparent else {}
            for block in GifImagePlugin.getdata(frame, duration=int(durations[index]), disposal=2, **options):
                stream.write(block)
            frame.close()
        stream.write(b";")
    palette.close()


def offer_download(api: Any, output: Path, filename: str) -> None:
    from starlette.background import BackgroundTask
    from starlette.responses import FileResponse

    # FileResponse streams large ZIPs; do not copy the entire archive into the websocket message.
    delivery = tempfile.TemporaryDirectory(prefix="crysdis-download-")
    path = Path(delivery.name) / filename
    shutil.move(str(output), path)
    route = "/crysdis-animation/" + uuid.uuid4().hex

    def cleanup() -> None:
        expiry.cancel()
        api.app.remove_route(route)
        delivery.cleanup()

    expiry = asyncio.get_running_loop().call_later(900, cleanup)

    @api.app.get(route, include_in_schema=False)
    async def download():
        expiry.cancel()
        api.app.remove_route(route)
        return FileResponse(path, filename=filename,
                            media_type="image/gif" if path.suffix == ".gif" else "application/zip",
                            headers={"Cache-Control": "no-store"}, background=BackgroundTask(cleanup))

    ui.download.from_url(route)


def three_scene_data(api: Any, controller: Any, occupancy_colors: str = "panel") -> dict:
    model, state, sim = controller.current_model, controller.state, controller.simulator
    if occupancy_colors == "panel":
        occupancy_colors = state.display_settings.occupancy_colors
    if occupancy_colors not in api.OCCUPANCY_COLOR_OPTIONS:
        raise ValueError("Choose blended colors or occupancy sectors.")
    planes, _ = api.parse_indices(state.plane_text, model, "plane", True)
    vectors, _ = api.parse_indices(state.vector_text, model, "direction", True, True)
    data = {"atoms": [], "edges": [], "planes": [], "vectors": [], "labels": [],
            "frame_color": state.display_settings.frame_color, "frame_width": state.display_settings.frame_width,
            "frame_opacity": state.display_settings.frame_opacity}
    for atom in model.visible_display_atoms():
        data["atoms"].append({"point": atom.position.tolist(), "color": api.color_for_site(atom),
                              "radius": model.atom_radius(atom),
                              "opacity": 0.58 + 0.42 * atom.occupancy,
                              "sectors": api.occupancy_sectors(atom.components) if occupancy_colors == "sectors" else []})
    data["edges"] = [[a.tolist(), b.tolist()] for a, b in model.display_edges]
    for index, plane in enumerate(planes):
        polygon = api.clipped_plane_polygon(model, plane)
        if polygon is None:
            continue
        colors = sim.plane_palette(state.panel_id)
        color = colors[index % len(colors)]
        opacity, edge_opacity = state.display_settings.plane_opacity, state.display_settings.plane_edge_opacity
        data["planes"].append({"points": polygon.tolist(), "color": color, "opacity": opacity, "edge_opacity": edge_opacity})
        if state.display_settings.plane_label_opacity > 0:
            data["labels"].append({"text": plane.label, "point": polygon.mean(axis=0).tolist(), "color": color,
                                   "opacity": state.display_settings.plane_label_opacity,
                                   "scale": state.display_settings.plane_label_scale})
    for index, vector in enumerate(vectors):
        fn = api.reciprocal_segment_for_display if vector.is_reciprocal else api.direction_segment_for_display
        start, end = fn(vector.values, model)
        colors = sim.vector_palette(state.panel_id)
        color = colors[index % len(colors)]
        opacity = state.display_settings.reciprocal_opacity if vector.is_reciprocal else state.display_settings.vector_opacity
        data["vectors"].append({"start": start.tolist(), "end": end.tolist(), "color": color, "reciprocal": vector.is_reciprocal, "opacity": opacity})
        if state.display_settings.vector_label_opacity > 0:
            data["labels"].append({"text": vector.label, "point": end.tolist(), "color": color,
                                   "opacity": state.display_settings.vector_label_opacity,
                                   "scale": state.display_settings.vector_label_scale})
    data["markers"] = api.marker_geometry(state.display_settings.markers, model)
    for marker in data["markers"]:
        if marker["label"]:
            data["labels"].append({"text": marker["label"], "point": np.mean(marker["points"], axis=0).tolist(),
                "color": marker["label_color"], "opacity": marker["label_opacity"], "scale": marker["label_size"] / 13,
                "direction": marker["label_direction"], "gap": marker["label_gap"]})
    if not sim.show_crystal_annotations():
        data["labels"] = []
    return data


THREE_RENDERER_SCRIPT = r"""
const {default: SceneLib} = await import('nicegui-scene');
const {THREE} = SceneLib;
__OCCUPANCY_MATERIAL__
__CRYSTAL_MARKERS__
const scene = new THREE.Scene();
scene.add(new THREE.AmbientLight(0xffffff, (1 - shading) * Math.PI));
const light = new THREE.DirectionalLight(0xffffff, shading * Math.PI);
scene.add(light);
const renderer = new THREE.WebGLRenderer({antialias: true, alpha: true});
function dispose() {
    scene.traverse(o => {o.geometry?.dispose(); o.material?.map?.dispose(); o.material?.dispose();});
    renderer.dispose(); renderer.forceContextLoss(); delete window[key];
}
try {
const maxSize = Math.min(renderer.capabilities.maxTextureSize, renderer.getContext().getParameter(renderer.getContext().MAX_RENDERBUFFER_SIZE));
if (width > maxSize || size > maxSize) throw new Error(`Requested image exceeds this browser's ${maxSize}px WebGL limit; lower Quality.`);
renderer.setPixelRatio(1); renderer.setSize(width, size);
renderer.setClearColor('#0B0F14', transparent ? 0 : 1);
const distance = extent / (2 * Math.tan(fov * Math.PI / 360));
const camera = new THREE.PerspectiveCamera(fov, width / size, 0.1, Math.max(5000, distance + 2 * extent));
const V = p => new THREE.Vector3(...p);
function material(color, opacity) {
    const options = {color, opacity, transparent: opacity < 1, depthWrite: opacity >= 1, side: THREE.DoubleSide};
    return shading === 0 ? new THREE.MeshBasicMaterial(options) :
        new THREE.MeshPhongMaterial({...options, shininess: 80, specular: new THREE.Color().setScalar(0.65 * shading / 0.68)});
}
function line(points, color, opacity) {
    scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(points.map(V)),
              new THREE.LineBasicMaterial({color, opacity, transparent: opacity < 1})));
}
for (const atom of data.atoms) {
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(atom.radius, 32, 16), material(atom.color, atom.opacity));
    applyOccupancySectors(mesh, atom.sectors);
    mesh.position.copy(V(atom.point)); scene.add(mesh);
}
for (const edge of data.edges) {
    if (data.frame_width === 1) line(edge, data.frame_color, data.frame_opacity);
    else {
        const delta = V(edge[1]).sub(V(edge[0])), radius = 0.0025 * data.frame_width;
        const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, delta.length(), 12), material(data.frame_color, data.frame_opacity));
        mesh.position.copy(V(edge[0])).addScaledVector(delta, 0.5);
        mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0), delta.normalize()); scene.add(mesh);
    }
}
for (const plane of data.planes) {
    const vertices = [];
    for (let i = 1; i < plane.points.length - 1; i++) vertices.push(...plane.points[0], ...plane.points[i], ...plane.points[i+1]);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
    geometry.computeVertexNormals();
    scene.add(new THREE.Mesh(geometry, material(plane.color, plane.opacity)));
    line([...plane.points, plane.points[0]], plane.color, plane.edge_opacity);
}
for (const vector of data.vectors) {
    const start = V(vector.start), delta = V(vector.end).sub(start), length = delta.length();
    if (length < 1e-8) continue;
    const direction = delta.clone().normalize();
    const head = Math.min(0.18, length * 0.28), shaft = length - head;
    const radius = vector.reciprocal ? 0.011 : 0.018;
    const opacity = vector.opacity;
    for (const [top, bottom, len, offset] of [[radius, radius, shaft, shaft/2], [0, radius*3, head, shaft+head/2]]) {
        const mesh = new THREE.Mesh(new THREE.CylinderGeometry(top, bottom, len, 24), material(vector.color, opacity));
        mesh.position.copy(start).addScaledVector(direction, offset);
        mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0), direction); scene.add(mesh);
    }
    if (vector.reciprocal) for (const fraction of [0.22, 0.4067, 0.5933, 0.78]) {
        const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.018, 16, 8), material(vector.color, Math.min(1, opacity*0.88/0.78)));
        mesh.position.copy(start).addScaledVector(delta, fraction); scene.add(mesh);
    }
}
addCrystalMarkers(THREE, scene, data.markers || [], material);
const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = size;
const context = canvas.getContext('2d');
window[key] = {
    render(frame) {
        camera.position.set(frame[0][2]*distance, frame[1][2]*distance, frame[2][2]*distance);
        camera.up.set(frame[0][1], frame[1][1], frame[2][1]); camera.lookAt(0,0,0);
        light.position.set(...frame.map(row => -0.45 * row[0] + 0.55 * row[1] + row[2]));
        camera.updateMatrixWorld(); renderer.render(scene, camera);
        context.clearRect(0,0,width,size); context.drawImage(renderer.domElement, 0, 0);
        const baseFontSize = Math.max(10, size/45);
        for (const label of data.labels) {
            context.font = `${label.direction ? '' : 'bold '}${baseFontSize * label.scale}px sans-serif`;
            const p = V(label.point).project(camera); context.fillStyle = label.color;
            context.globalAlpha = label.opacity;
            const [dx, dy] = label.direction || [0, 0], gap = (label.gap || 0) * baseFontSize / 13;
            context.textAlign = dx > 0 ? 'left' : dx < 0 ? 'right' : 'center';
            context.textBaseline = label.direction ? (dy > 0 ? 'bottom' : dy < 0 ? 'top' : 'middle') : 'alphabetic';
            context.fillText(label.text, (p.x+1)*width/2 + dx*gap, (1-p.y)*size/2 - dy*gap);
        }
        context.globalAlpha = 1;
        if (bar) {
            const fontSize = baseFontSize * bar.font_size / 12;
            const right = bar.position.includes('right'), top = bar.position.includes('top');
            const x = right ? width*0.93-bar.fraction*width : width*0.07;
            const y = top ? size*0.1 : Math.min(size*0.9, size*0.96-fontSize-size*0.02);
            context.font = `bold ${fontSize}px sans-serif`;
            context.globalAlpha = bar.opacity;
            context.strokeStyle = context.fillStyle = bar.color; context.lineWidth = size/180;
            context.beginPath(); context.moveTo(x, y);
            context.lineTo(x+bar.fraction*width, y); context.stroke();
            context.textAlign = right ? 'right' : 'left'; context.textBaseline = 'top';
            context.fillText(bar.label, right ? x+bar.fraction*width : x, y+size*0.02);
            context.textBaseline = 'alphabetic'; context.globalAlpha = 1;
        }
        return canvas.toDataURL('image/png');
    },
    dispose
};
return true;
} catch (error) { dispose(); throw error; }
"""


async def initialize_three_renderer(api: Any, key: str, snapshot: Any, height: int,
                                    extent: float, transparent: bool, width: int | None = None,
                                    atom_shading: str = "mild", occupancy_colors: str = "panel") -> None:
    width = height if width is None else width
    bar = None
    settings = snapshot.state.display_settings.annotations
    if snapshot.simulator.show_scale_bars() and settings.real_scale_visible:
        width_nm = extent * width / height * snapshot.current_model.scale_nm
        bar_nm = api.choose_scale_bar(width_nm)
        bar = {"fraction": bar_nm / width_nm, "label": f"{bar_nm:g} nm", **asdict(settings.real_scale)}
    await ui.run_javascript(
        f"const key={json.dumps(key)}, data={json.dumps(three_scene_data(api, snapshot, occupancy_colors))}, size={height}, width={width}, "
        f"extent={extent}, fov={float(api.REAL_SCENE_FOV_DEGREES)}, shading={api.ATOM_SHADING_STRENGTH[atom_shading]}, "
        f"transparent={json.dumps(transparent)}, bar={json.dumps(bar)};\n"
        + THREE_RENDERER_SCRIPT.replace("__OCCUPANCY_MATERIAL__", api.THREE_OCCUPANCY_SCRIPT)
                               .replace("__CRYSTAL_MARKERS__", api.THREE_MARKERS_SCRIPT), timeout=30)


async def render_static_three_png(api: Any, controller: Any, dpi: float, transparent: bool,
                                  view: np.ndarray | None = None, roll: float | None = None,
                                  atom_shading: str = "mild", occupancy_colors: str = "panel") -> bytes:
    snapshot = export_snapshot(api, controller, controller.simulator.current_simulation_method())
    state = snapshot.state
    frame = api.orientation_frame(state.view_vector if view is None else view, state.roll if roll is None else roll)
    extent = animation_extent(api, snapshot.current_model, state)
    dpi = min(max(float(dpi or 300), 72.0), 1200.0)
    key = "crysdis_static_" + uuid.uuid4().hex
    try:
        await initialize_three_renderer(api, key, snapshot, round(3.6 * dpi), extent, transparent,
                                        width=round(4.6 * dpi), atom_shading=atom_shading, occupancy_colors=occupancy_colors)
        data_url = await ui.run_javascript(f"return window[{json.dumps(key)}].render({json.dumps(frame.tolist())});", timeout=30)
        png = api.decode_png_data_url(data_url)
        with Image.open(io.BytesIO(png)) as image:
            output = io.BytesIO()
            image.save(output, format="PNG", dpi=(dpi, dpi))
        return output.getvalue()
    finally:
        try:
            await ui.run_javascript(f"window[{json.dumps(key)}]?.dispose();", timeout=5)
        except Exception:
            pass


class AnimationDialog:
    def __init__(self, controller: Any, api: Any) -> None:
        self.controller, self.api = controller, api
        self.steps = [AnimationStep()]
        self.start = api.orientation_frame(controller.state.view_vector, controller.state.roll)
        self.busy = False
        self.cancelled = threading.Event()
        self.preview_bytes: bytes | None = None
        self.controls: list[Any] = []
        self.row_controls: list[Any] = []
        self.shading_by_renderer = {"png": "none", "three": "mild"}
        self.last_renderer = "three"
        self.dialog = ui.dialog().props("persistent")
        self.dialog.client.on_disconnect(self.cancel)
        ui.add_css("""
            .animation-card {width:1100px;max-width:96vw!important;padding:20px;gap:14px;}
            .animation-settings {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;width:100%;}
            .animation-step {display:grid;grid-template-columns:48px 64px minmax(80px,1fr) minmax(120px,1fr) 108px 82px 126px 146px 112px;grid-template-areas:"num kind axis ref angle duration easing timing tools";gap:6px;align-items:center;width:100%;padding:10px 0;border-bottom:1px solid #6665;}
            .animation-drag {cursor:grab;touch-action:none;user-select:none;width:28px;min-width:28px;height:32px;}
            .animation-drag:active {cursor:grabbing;}
            .animation-drag-active {outline:1px solid var(--q-primary);outline-offset:-1px;}
            .animation-drag-preview {background:#252525;opacity:.95!important;}
            .animation-step-tools .q-btn {width:28px;min-width:28px;height:32px;}
            .animation-step .q-field {min-width:0;}
            .animation-snap {grid-column:ref-start / angle-end;grid-row:1;}
            .animation-step .q-field__native,.animation-step .q-field__suffix,.animation-step .q-checkbox__label {font-size:13px;}
            .animation-step .q-field--outlined .q-field__control {padding:0 8px;}
            .animation-step .q-field__append {padding-left:2px;}
            .animation-preview {width:100%;height:320px;object-fit:contain;background:#0b0f14;}
            .animation-preview-transparent {background-color:#252525;background-image:conic-gradient(#383838 25%,#252525 0 50%,#383838 0 75%,#252525 0);background-size:20px 20px;}
            .animation-sequence-upload {width:164px;max-width:100%;box-shadow:none;border:1px solid var(--q-primary);border-radius:4px;}
            .animation-sequence-upload .q-uploader__list,.animation-sequence-upload .q-uploader__subtitle{display:none;}
            .animation-sequence-upload .q-uploader__header{background:transparent;color:var(--q-primary);}
            .animation-sequence-upload .q-uploader__header-content{padding:2px 6px;min-height:30px;}
            @media(max-width:1130px) {.animation-step {grid-template-columns:48px 82px minmax(126px,1fr) minmax(146px,1fr) 112px;grid-template-areas:"num kind axis ref angle" ". duration easing timing tools";}.animation-settings{grid-template-columns:repeat(2,minmax(0,1fr));}}
            @media(max-width:650px) {.animation-card{padding:12px;}.animation-settings{grid-template-columns:minmax(0,1fr);}.animation-step{grid-template-columns:48px minmax(120px,1fr) minmax(126px,1fr);grid-template-areas:"num kind tools" ". axis axis" ". ref angle" ". duration easing" ". timing timing";}.animation-snap{grid-row:3;}.animation-preview{height:220px;}}
            @media(max-width:360px) {.animation-step{grid-template-columns:40px minmax(0,1fr);grid-template-areas:"num kind" ". axis" ". ref" ". angle" ". duration" ". easing" ". timing" ". tools";}.animation-snap{grid-column:ref;}}
        """)
        with self.dialog, ui.card().classes("animation-card") as card:
            with ui.row().classes("items-center justify-between full-width"):
                self.title = ui.label("Create animation").classes("text-h6")
                self.close_button = ui.button(icon="close", on_click=self.close).props("flat round dense").tooltip("Close")
            self.build_context_controls()
            self.start_label = ui.label().classes("text-body2")
            self.rows = ui.column().classes("full-width gap-0")
            self.sortable = self.control(self.rows.make_sortable(
                options={"forceFallback": True, "fallbackTolerance": 4,
                         "chosenClass": "animation-drag-active", "fallbackClass": "animation-drag-preview"},
                handle=".animation-drag", on_end=self.on_steps_sorted))
            # The default layout-level controller outlives the dialog's DOM rows.
            self.sortable.move(card)
            with ui.row().classes("full-width items-center"):
                for kind, label, icon in (("rotate", "Rotation", "rotate_right"), ("zone", "Zone axis", "explore"), ("hold", "Pause", "pause")):
                    self.control(ui.button(label, icon=icon, on_click=lambda kind=kind: self.add_step(kind)).props("outline dense"))
                self.control(ui.button(icon="save", on_click=self.save_sequence).props("flat round dense").tooltip("Save animation sequence"))
                self.control(ui.upload(label="Load sequence", on_upload=self.load_sequence, auto_upload=True).props("accept=.json max-file-size=1000000 flat").classes("animation-sequence-upload"))
            with ui.element("div").classes("animation-settings"):
                self.renderer = self.control(ui.select({"png": "Current PNG exporter", "three": "Three.js"}, value="three", label="Crystal renderer").props("outlined dense"))
                self.shading = self.control(ui.select(api.ATOM_SHADING_OPTIONS, value="mild", label="Shading").props("outlined dense"))
                self.shading.tooltip("Surface shading and highlights. PNG shades atoms; Three.js shades solid 3D geometry.")
                self.occupancy_colors = self.control(ui.select(api.EXPORT_OCCUPANCY_COLOR_OPTIONS, value="panel",
                    label="Site occupancy colors").props("outlined dense"))
                self.occupancy_colors.tooltip("Viewer-facing sectors represent site occupancy; gray is unoccupied. Panel settings preserves each panel's choice.")
                self.method = self.control(ui.select(list(api.SIMULATION_METHODS), value=api.SIMULATION_METHOD_EWALD, label="Diffraction method").props("outlined dense"))
                self.method.tooltip("Ewald uses the continuous viewing direction. Pymatgen uses the nearest integer zone; reflections may change abruptly during tilting.")
                self.content = self.build_content_control()
                self.format = self.control(ui.select({"gif": "GIF", "zip": "PNG sequence (ZIP)"}, value="gif", label="Export format", on_change=self.update_format).props("outlined dense"))
                self.build_layout_controls()
                self.height = self.control(ui.select([360, 540, 720, 1080], value=540, label="Frame height (px)").props("outlined dense"))
                self.fps = self.control(ui.number("Frames per second", value=20, min=1, max=60, step=1).props("outlined dense"))
                self.fps.tooltip("Export frame rate. Preview uses at most 10 fps and 360-pixel views, with the same total duration.")
                self.filename = self.control(ui.input("File name", value=f"panel_{controller.state.panel_id}_animation").props("outlined dense"))
                self.loop = self.control(ui.checkbox("Loop GIF", value=True))
                self.loop.tooltip("Repeat the sequence. Match the final and initial views for a seamless loop.")
                self.show_crystal_name = self.control(ui.checkbox("Show crystal name", value=False))
                self.transparent = self.control(ui.checkbox("Transparent background", value=False, on_change=self.update_format))
                self.transparent.tooltip("PNG preserves full alpha. GIF offers matte-color blending or dithered transparency.")
                self.gif_transparency = self.control(ui.select({"matte": "Clean edges (matte)", "dither": "Dithered alpha"},
                    value="matte", label="GIF transparency", on_change=self.update_format).props("outlined dense"))
                self.gif_transparency.tooltip("Matte blends against a chosen slide color. Dithering approximates partial transparency with pixel coverage.")
                self.gif_matte = self.control(ui.color_input("Matte / slide color", value="#FFFFFF", preview=True).props("outlined dense"))
                self.gif_matte.tooltip("Match your slide background. Empty pixels stay transparent; edge and plane colors are blended with this color. Other backgrounds can reveal halos.")
            if controller.simulator.direct_file_exports_enabled():
                self.folder = ui.label(f"Export folder: {controller.simulator.export_dir_text()}").classes("export-folder-label")
                self.control(ui.button("Choose export folder", icon="folder_open", on_click=self.choose_folder).props("outline dense"))
            self.preview = ui.html("", sanitize=False).classes("full-width")
            self.progress = ui.linear_progress(value=0, show_value=False).classes("full-width")
            self.status = ui.label("Ready").classes("text-body2")
            with ui.row().classes("full-width justify-end"):
                self.cancel_button = ui.button("Cancel export", icon="stop", on_click=self.cancel).props("outline dense")
                self.cancel_button.disable()
                self.control(ui.button("Preview", icon="play_arrow", on_click=self.run_preview).props("outline dense"))
                self.control(ui.button("Export", icon="download", on_click=self.run_export).props("unelevated dense"))
        self.rebuild_rows()
        self.renderer.on_value_change(self.update_render_controls)
        self.content.on_value_change(self.update_render_controls)
        self.update_format()

    def build_context_controls(self) -> None:
        pass

    def build_content_control(self) -> Any:
        return self.control(ui.select(CONTENT_OPTIONS, value="both", label="Content").props("outlined dense"))

    def build_layout_controls(self) -> None:
        pass

    def build_step_reference(self, step: AnimationStep) -> None:
        pass

    def control(self, element: Any) -> Any:
        self.controls.append(element)
        return element

    async def open(self) -> None:
        if self.busy:
            self.dialog.open()
            return
        self.title.set_text(f"Animation: panel {self.controller.state.panel_id} / {self.controller.state.crystal_name}")
        self.dialog.open()
        await self.capture_start()

    async def capture_start(self) -> None:
        if self.busy:
            return
        view, roll = await self.controller.live_scene_orientation()
        state = self.controller.state
        self.start = self.api.orientation_frame(view if view is not None else state.view_vector,
                                                roll if roll is not None else state.roll)
        self.update_start_readout()
        self.preview.set_content("")
        self.preview_bytes = None
        await self.run(preview=True, start_only=True)

    def update_start_readout(self) -> None:
        model = self.controller.simulator.model_for(self.controller.state.crystal_name)
        view, roll = self.api.orientation_from_frame(self.start)
        label = self.api.zone_axis_label_from_view(model, view, use_hex_four_index=self.controller.simulator.use_hex_four_index_basis())
        self.start_label.set_text(f"Starting panel view: {label}, roll {roll:.3f} deg")

    def close(self) -> None:
        if self.busy:
            self.cancel()
        else:
            self.dialog.close()

    def cancel(self) -> None:
        self.cancelled.set()

    def update_format(self) -> None:
        if not hasattr(self, "gif_matte"):
            return
        self.transparent.set_enabled(not self.busy)
        self.loop.set_enabled(not self.busy and self.format.value == "gif")
        gif_alpha = self.format.value == "gif" and self.transparent.value
        self.gif_transparency.set_visibility(gif_alpha)
        self.gif_matte.set_visibility(gif_alpha and self.gif_transparency.value == "matte")
        self.update_render_controls()

    def update_render_controls(self) -> None:
        if self.renderer.value != self.last_renderer:
            self.shading_by_renderer[self.last_renderer] = self.shading.value
            self.last_renderer = self.renderer.value
            self.shading.set_value(self.shading_by_renderer[self.last_renderer])
        enabled = not self.busy and self.content.value not in {"diffraction", "combo"}
        self.shading.set_enabled(enabled)
        self.occupancy_colors.set_enabled(enabled)

    async def choose_folder(self) -> None:
        await self.controller.simulator.choose_export_folder(self.folder)

    def add_step(self, kind: str) -> None:
        if self.busy:
            return
        self.steps.append(AnimationStep(kind=kind, seconds=1 if kind == "hold" else 3, angle=45,
                                        snap_back=kind == "zone" and self.controller.simulator.always_snap_back_view()))
        self.rebuild_rows()

    def move_step(self, index: int, delta: int) -> None:
        self.move_step_to(index, index + delta)

    def move_step_to(self, index: int, target: int) -> None:
        if not self.busy and 0 <= index < len(self.steps) and 0 <= target < len(self.steps) and index != target:
            self.steps.insert(target, self.steps.pop(index))
            self.rebuild_rows()

    def on_steps_sorted(self, event: Any) -> None:
        if self.busy:
            event.item.move(target_container=self.rows, target_index=event.old_index)
            return
        self.move_step_to(event.old_index, event.new_index)

    def duplicate_step(self, index: int) -> None:
        if not self.busy and 0 <= index < len(self.steps):
            self.steps.insert(index + 1, copy.deepcopy(self.steps[index]))
            self.rebuild_rows()

    def delete_step(self, index: int) -> None:
        if self.busy or not 0 <= index < len(self.steps):
            return
        self.steps.pop(index)
        self.rebuild_rows()

    def rebuild_rows(self) -> None:
        self.rows.clear()
        self.row_controls = []
        with self.rows:
            for index, step in enumerate(self.steps):
                with ui.element("div").classes("animation-step"):
                    with ui.row().classes("gap-0 items-center no-wrap").style("grid-area:num"):
                        handle = ui.button(icon="drag_indicator").props("flat round dense size=sm").classes("animation-drag").tooltip("Hold and drag to reorder event")
                        self.row_controls.append(handle)
                        ui.label(str(index + 1)).classes("text-caption")
                    ui.label({"rotate": "Rotation", "zone": "Zone axis", "hold": "Pause"}[step.kind]).style("grid-area:kind")
                    self.build_step_reference(step)
                    if step.kind != "hold":
                        label = "Axis (x,y,z)" if step.kind == "rotate" and step.frame == "lab" else "Axis [uvw]"
                        axis = ui.input(label).bind_value(step, "axis").props("outlined dense").style("grid-area:axis")
                        axis.tooltip("Crystal: indices, including reciprocal *h,k,l. Lab: X right, Y up, Z toward viewer; comma-separated components.")
                        self.row_controls.append(axis)
                    else:
                        ui.element("div").style("grid-area:axis")
                    if step.kind == "rotate":
                        frame = ui.select({"crystal": "Crystal", "lab": "Lab / screen"}, label="Reference").bind_value(step, "frame").props("outlined dense").style("grid-area:ref")
                        def change_frame(event, step=step, axis=axis):
                            if event.value == "lab" and step.axis == "001":
                                axis.set_value("0,0,1")
                            axis.set_label("Axis (x,y,z)" if event.value == "lab" else "Axis [uvw]")
                        frame.on_value_change(change_frame)
                        angle = ui.number("Angle", suffix="deg").bind_value(step, "angle").props("outlined dense").style("grid-area:angle")
                        self.row_controls.extend([frame, angle])
                    elif step.kind == "zone":
                        snap = ui.checkbox("Snap back view").bind_value(step, "snap_back").props("dense").classes("animation-snap")
                        snap.tooltip("Finish at the normal panel's fixed zero-roll zone view. Off uses the minimal-twist tilt.")
                        self.row_controls.append(snap)
                    duration = ui.number("Duration", min=0.05, max=600, step=0.5, suffix="s").bind_value(step, "seconds").props("outlined dense").style("grid-area:duration")
                    self.row_controls.append(duration)
                    if step.kind != "hold":
                        easing = ui.select({"linear": "Constant", "smooth": "Ease in/out"}, label="Speed").bind_value(step, "easing").props("outlined dense").style("grid-area:easing")
                        self.row_controls.append(easing)
                    else:
                        ui.element("div").style("grid-area:easing")
                    with ui.row().classes("animation-step-tools gap-0 no-wrap").style("grid-area:tools"):
                        for icon, tooltip, action in (
                            ("arrow_upward", "Move step up", lambda i=index: self.move_step(i, -1)),
                            ("arrow_downward", "Move step down", lambda i=index: self.move_step(i, 1)),
                            ("content_copy", "Duplicate event", lambda i=index: self.duplicate_step(i)),
                            ("delete", "Delete step", lambda i=index: self.delete_step(i)),
                        ):
                            button = ui.button(icon=icon, on_click=action).props("flat round dense size=sm").tooltip(tooltip)
                            self.row_controls.append(button)
                    timing = ui.select({False: "After previous", True: "With previous"}, label="Start event").bind_value(step, "with_previous").props("outlined dense").style("grid-area:timing")
                    timing.tooltip("With previous shares the previous group's start time. At most one zone target; zone first, then rotations in list order. Each keeps its own duration.")
                    self.row_controls.append(timing)

    def sequence(self) -> dict:
        return {"version": 3, "start_source": "panel", "crystal": self.controller.state.crystal_name,
                "start_frame": self.start.tolist(), "steps": [asdict(step) for step in self.steps]}

    async def save_sequence(self) -> None:
        if self.busy:
            return
        self.busy = True
        try:
            data = json.dumps(self.sequence(), indent=2).encode()
            simulator = self.controller.simulator
            if simulator.direct_file_exports_enabled():
                path = await simulator.choose_save_file("crysdis_animation.json", ".json")
                if path is not None:
                    await asyncio.to_thread(path.write_bytes, data)
                    simulator.announce_saved_exports([path])
            else:
                ui.download(data, "crysdis_animation.json", media_type="application/json")
        except (ValueError, TypeError, OSError) as exc:
            ui.notify(str(exc), type="negative")
        finally:
            self.busy = False

    async def export_destination(self, extension: str) -> tuple[str, Path | None]:
        name = self.api.sanitize_export_filename(self.filename.value, "crysdis_animation", extension)
        simulator = self.controller.simulator
        if not simulator.direct_file_exports_enabled():
            return name, None
        destination = await simulator.choose_save_file(name, extension)
        if destination is None:
            raise ExportCancelled()
        self.cancel_check()
        return destination.name, destination

    async def load_sequence(self, event: Any) -> None:
        try:
            data = json.loads(await event.file.read())
            if data.get("version") not in {1, 2, 3} or not 1 <= len(data["steps"]) <= 200:
                raise ValueError("Unsupported sequence or invalid step count.")
            steps = [AnimationStep(**step) for step in data["steps"]]
            model = self.controller.simulator.model_for(self.controller.state.crystal_name)
            # Recipes reuse events, never replace the orientation captured from this panel.
            compile_motion(self.api, model, self.start, steps)
            self.steps = steps
            self.rebuild_rows()
            self.status.set_text("Sequence loaded; panel starting view retained")
        except Exception as exc:
            ui.notify(f"Cannot load sequence: {exc}", type="negative")

    async def run_preview(self) -> None:
        await self.run(preview=True)

    async def run_export(self) -> None:
        await self.run(preview=False)

    async def run(self, *, preview: bool, start_only: bool = False) -> None:
        if self.busy:
            return
        self.busy = True
        self.cancelled.clear()
        for control in [*self.controls, *self.row_controls, self.close_button]:
            control.disable()
        self.cancel_button.enable()
        self.progress.set_value(0)
        self.status.set_text("Preparing animation")
        key = "crysdis_animation_" + uuid.uuid4().hex
        initialized = False
        try:
            snapshot = export_snapshot(self.api, self.controller, self.method.value)
            segments = [] if start_only else compile_motion(self.api, snapshot.current_model, self.start, copy.deepcopy(self.steps))
            fps = 1.0 if start_only else float(self.fps.value)
            height = int(self.height.value)
            if preview:
                fps, height = min(fps, PREVIEW_MAX_FPS), min(height, PREVIEW_MAX_HEIGHT)
            times, durations = (np.array([0.0]), np.array([1000])) if start_only else frame_schedule(segments, fps)
            transparent = bool(self.transparent.value)
            gif_mode = self.gif_transparency.value
            matte_color = self.gif_matte.value
            if transparent and gif_mode == "matte" and (preview or self.format.value == "gif"):
                # Validate before spending time rendering; normalize before embedding in CSS.
                matte_color = "#%02X%02X%02X" % ImageColor.getcolor(matte_color, "RGB")
            content = self.content.value
            show_crystal_name = bool(self.show_crystal_name.value)
            atom_shading = self.shading.value
            occupancy_colors = self.occupancy_colors.value
            extent = animation_extent(self.api, snapshot.current_model, snapshot.state)
            if not preview:
                name, destination = await self.export_destination("." + self.format.value)
            if self.renderer.value == "three" and content != "diffraction":
                await initialize_three_renderer(self.api, key, snapshot, height, extent, transparent,
                                                atom_shading=atom_shading, occupancy_colors=occupancy_colors)
                initialized = True
            with tempfile.TemporaryDirectory(prefix="crysdis-animation-") as folder:
                paths = []
                for index, time_seconds in enumerate(times):
                    if self.cancelled.is_set():
                        raise ExportCancelled()
                    self.status.set_text(f"{'Preview' if preview else 'Export'} ({fps:g} fps): frame {index + 1} / {len(times)}")
                    frame = self.start.copy() if start_only else motion_at(segments, float(time_seconds))
                    crystal_png = None
                    if initialized:
                        data_url = await ui.run_javascript(f"return window[{json.dumps(key)}].render({json.dumps(frame.tolist())});", timeout=30)
                        crystal_png = self.api.decode_png_data_url(data_url)
                    path = Path(folder) / f"frame_{index:06d}.png"

                    def write_frame() -> None:
                        with RENDER_LOCK:
                            self.cancel_check()
                            path.write_bytes(render_frame(self.api, snapshot, frame, height, content, transparent, extent, crystal_png,
                                                         show_crystal_name, atom_shading=atom_shading, occupancy_colors=occupancy_colors))

                    await asyncio.to_thread(write_frame)
                    paths.append(path)
                    self.progress.set_value(0.9 * (index + 1) / len(times))
                self.cancel_check()
                self.status.set_text("Encoding GIF" if preview or self.format.value == "gif" else "Packaging PNG sequence")
                extension = ".gif" if preview else "." + self.format.value
                output = Path(folder) / ("animation" + extension)
                metadata = {**self.sequence(), "renderer": self.renderer.value, "diffraction_method": self.method.value,
                            "content": content, "frame_height": height, "fps_requested": fps,
                            "sample_times_seconds": times.tolist(), "frame_durations_ms": durations.tolist(),
                            "loop": bool(self.loop.value), "transparent_background": transparent,
                            "gif_transparency": gif_mode, "gif_matte_color": matte_color,
                            "show_crystal_name": show_crystal_name, "atom_shading": atom_shading,
                            "occupancy_colors": occupancy_colors,
                            "display_settings": asdict(snapshot.state.display_settings),
                            "element_colors": snapshot.simulator.element_colors.copy(),
                            "simulation": {name: getattr(snapshot.simulator, name)() for name in (
                                "current_max_hkl", "current_voltage_kv", "current_thickness_nm", "current_camera_length_mm",
                                "current_spot_intensity_threshold", "current_intensity_compression_factor",
                                "uniform_spot_brightness")}}
                if not start_only:
                    await asyncio.to_thread(encode_animation, paths, output, durations, metadata, bool(self.loop.value), self.cancelled)
                self.cancel_check()
                if preview:
                    import base64
                    self.preview_bytes = paths[0].read_bytes() if start_only else output.read_bytes()
                    encoded = base64.b64encode(self.preview_bytes).decode()
                    classes = "animation-preview animation-preview-transparent" if transparent else "animation-preview"
                    mime = "image/png" if start_only else "image/gif"
                    style = f'background:{matte_color};' if transparent and gif_mode == "matte" else ""
                    self.preview.set_content(f'<img class="{classes}" style="{style}" alt="Animation preview" src="data:{mime};base64,{encoded}">')
                else:
                    simulator = self.controller.simulator
                    if destination is not None:
                        await asyncio.to_thread(shutil.copyfile, output, destination)
                        simulator.announce_saved_exports([destination])
                    else:
                        offer_download(self.api, output, name)
                self.progress.set_value(1)
                self.status.set_text("Starting view ready" if start_only else f"{'Preview ready' if preview else 'Export complete'}: {len(times)} frames at {fps:g} fps, {sum(durations) / 1000:g} s")
        except ExportCancelled:
            self.status.set_text("Animation cancelled")
        except Exception as exc:
            self.status.set_text(f"Animation failed: {exc}")
            ui.notify(f"Animation failed: {exc}", type="negative")
        finally:
            if initialized:
                try:
                    await ui.run_javascript(f"window[{json.dumps(key)}]?.dispose();", timeout=5)
                except Exception:
                    pass
            self.busy = False
            for control in [*self.controls, *self.row_controls, self.close_button]:
                control.enable()
            self.cancel_button.disable()
            self.update_format()

    def cancel_check(self) -> None:
        if self.cancelled.is_set():
            raise ExportCancelled()


class ComboAnimationDialog(AnimationDialog):
    @staticmethod
    def available_panel_ids(combo: Any) -> list[int]:
        sources = [state.panel_id for state in combo.selected_sources()]
        connected = set(sources)
        for panel_id in sources:
            connected.update(combo.simulator.bound_motion_panel_ids(panel_id))
        return sources + sorted(connected - set(sources))

    def __init__(self, combo: Any, api: Any) -> None:
        self.combo = combo
        self.source_ids = [state.panel_id for state in combo.selected_sources()]
        self.available_ids = self.available_panel_ids(combo)
        self.source_controllers = {panel_id: combo.simulator.controller_by_panel_id(panel_id)
                                   for panel_id in self.available_ids}
        if not self.source_ids or any(controller is None for controller in self.source_controllers.values()):
            raise ValueError("The combo's source panels are not available.")
        self.starts = {panel_id: api.orientation_frame(controller.state.view_vector, controller.state.roll)
                       for panel_id, controller in self.source_controllers.items()}
        self.captured: dict[int, Any] = {}
        self.panel_contents = {panel_id: "both" for panel_id in self.available_ids}
        self.content_controls: dict[int, Any] = {}
        self.participant_rows: dict[int, Any] = {}
        self.participant_labels: dict[int, Any] = {}
        super().__init__(self.source_controllers[self.source_ids[0]], api)
        self.show_crystal_name.value = True
        self.dialog.classes("combo-animation-dialog")
        self.filename.value = f"combo_C{combo.state.combo_id}_animation"
        self.height.set_label("Tile height (px)")
        self.steps[0].reference_panel_id = self.source_ids[0]
        self.rebuild_rows()
        self.update_layout()
        ui.add_css("""
            .combo-animation-dialog .animation-card {width:1340px;}
            .combo-animation-dialog .animation-step {
                grid-template-columns:48px 64px minmax(112px,160px) minmax(80px,1fr) minmax(120px,1fr) 108px 82px 126px 146px 112px;
                grid-template-areas:"num kind driver axis ref angle duration easing timing tools";
            }
            .combo-animation-participants {grid-column:1 / -1;width:100%;gap:6px;}
            .combo-animation-participant {display:grid;grid-template-columns:minmax(0,1fr) minmax(180px,260px);gap:12px;align-items:center;width:100%;}
            .combo-animation-participant .q-field {min-width:0;}
            @media(max-width:1250px) {
                .combo-animation-dialog .animation-step {grid-template-columns:48px 82px minmax(126px,1fr) minmax(100px,1fr) minmax(120px,1fr) 112px;
                    grid-template-areas:"num kind driver axis ref angle" ". duration easing timing timing tools";}
            }
            @media(max-width:800px) {
                .combo-animation-dialog .animation-step {grid-template-columns:48px minmax(120px,1fr) minmax(126px,1fr);
                    grid-template-areas:"num kind tools" ". driver driver" ". axis axis" ". ref angle" ". duration easing" ". timing timing";}
                .combo-animation-dialog .animation-snap {grid-row:4;}
                .combo-animation-participant {grid-template-columns:minmax(0,1fr);gap:4px;}
            }
            @media(max-width:360px) {
                .combo-animation-dialog .animation-step {grid-template-columns:40px minmax(0,1fr);
                    grid-template-areas:"num kind" ". driver" ". axis" ". ref" ". angle" ". duration" ". easing" ". timing" ". tools";}
            }
        """)

    def active_ids(self) -> list[int]:
        return self.available_ids if self.include_bound.value else self.source_ids

    def build_context_controls(self) -> None:
        self.include_bound = self.control(ui.checkbox("Include other bound panels", value=False, on_change=self.update_participants))
        self.include_bound.set_visibility(len(self.available_ids) > len(self.source_ids))

    def build_layout_controls(self) -> None:
        with ui.column().classes("combo-animation-participants") as self.participants:
            for panel_id, controller in self.source_controllers.items():
                with ui.element("div").classes("combo-animation-participant") as row:
                    self.participant_labels[panel_id] = ui.label(f"Panel {panel_id}: {controller.state.crystal_name}").classes("break-words min-w-0")
                    control = self.control(ui.select(CONTENT_OPTIONS, value="both", label=f"Panel {panel_id} content",
                        on_change=lambda event, p=panel_id: self.panel_contents.__setitem__(p, event.value)).props("outlined dense"))
                    self.participant_rows[panel_id], self.content_controls[panel_id] = row, control
        self.update_layout()

    def build_content_control(self) -> Any:
        return self.control(ui.select(COMBO_LAYOUTS, value="crystals_combo", label="Export layout",
                                      on_change=self.update_layout).props("outlined dense"))

    def update_layout(self) -> None:
        individual = self.content.value in {"grid", "separate"}
        self.participants.set_visibility(individual)
        for panel_id, row in self.participant_rows.items():
            row.set_visibility(panel_id in self.active_ids())
            self.content_controls[panel_id].set_visibility(individual)

    def update_participants(self) -> None:
        if self.busy:
            return
        for step in self.steps:
            if step.reference_panel_id not in self.active_ids():
                step.reference_panel_id = None
        self.rebuild_rows()
        self.update_layout()
        self.update_start_readout()
        self.preview.set_content("")

    def build_step_reference(self, step: AnimationStep) -> None:
        if step.kind == "hold":
            ui.element("div").style("grid-area:driver")
            return
        options = {panel_id: f"{panel_id}: {self.source_controllers[panel_id].state.crystal_name}" for panel_id in self.active_ids()}
        control = ui.select(options, label="Reference crystal", value=step.reference_panel_id).bind_value(step, "reference_panel_id").props("outlined dense").style("grid-area:driver")
        self.row_controls.append(control)

    async def open(self) -> None:
        if self.busy:
            self.dialog.open()
            return
        self.title.set_text(f"Bound animation: combo C{self.combo.state.combo_id}")
        self.dialog.open()
        await self.capture_start()

    async def capture_start(self) -> None:
        self.busy = True
        controls = [*self.controls, *self.row_controls, self.close_button]
        for control in controls:
            control.disable()
        try:
            captured, starts = {}, {}
            for panel_id in self.available_ids:
                controller = self.combo.simulator.controller_by_panel_id(panel_id)
                if controller is None:
                    raise ValueError(f"Panel {panel_id} is no longer available; reopen from the combo panel.")
                self.source_controllers[panel_id] = controller
                view, roll = await controller.live_scene_orientation()
                state = controller.state
                starts[panel_id] = self.api.orientation_frame(view if view is not None else state.view_vector,
                                                            roll if roll is not None else state.roll)
                captured[panel_id] = export_snapshot(self.api, controller, self.method.value)
                self.participant_labels[panel_id].set_text(f"Panel {panel_id}: {state.crystal_name}")
            self.controller = self.source_controllers[self.source_ids[0]]
            self.captured, self.starts = captured, starts
            self.update_start_readout()
            self.preview.set_content("")
        except Exception as exc:
            self.status.set_text(f"Cannot capture starting views: {exc}")
            ui.notify(f"Cannot capture starting views: {exc}", type="negative")
            return
        finally:
            self.busy = False
            for control in controls:
                control.enable()
            self.update_format()
        self.rebuild_rows()
        await self.run(preview=True, start_only=True)

    def update_start_readout(self) -> None:
        labels = []
        for panel_id in self.active_ids():
            controller = self.captured.get(panel_id) or self.source_controllers[panel_id]
            model = controller.simulator.model_for(controller.state.crystal_name)
            view, roll = self.api.orientation_from_frame(self.starts[panel_id])
            zone = self.api.zone_axis_label_from_view(model, view, use_hex_four_index=controller.simulator.use_hex_four_index_basis())
            labels.append(f"Panel {panel_id}: {zone}, roll {roll:.3f} deg")
        self.start_label.set_text("Starting panel views: " + "; ".join(labels))

    def add_step(self, kind: str) -> None:
        if self.busy:
            return
        self.steps.append(AnimationStep(kind=kind, seconds=1 if kind == "hold" else 3, angle=45,
            snap_back=kind == "zone" and self.controller.simulator.always_snap_back_view(), reference_panel_id=self.active_ids()[0]))
        self.rebuild_rows()

    def sequence(self) -> dict:
        return {"version": 4, "kind": "bound", "start_source": "panels", "combo_id": self.combo.state.combo_id,
                "start_frames": {str(p): self.starts[p].tolist() for p in self.active_ids()},
                "steps": [asdict(step) for step in self.steps]}

    async def load_sequence(self, event: Any) -> None:
        try:
            data = json.loads(await event.file.read())
            if data.get("version") not in {1, 2, 3, 4} or not 1 <= len(data["steps"]) <= 200:
                raise ValueError("Unsupported sequence or invalid step count.")
            steps = [AnimationStep(**step) for step in data["steps"]]
            if data.get("kind") != "bound":
                for step in steps:
                    step.reference_panel_id = self.active_ids()[0]
            starts = {p: self.starts[p] for p in self.active_ids()}
            models = {p: self.captured[p].current_model for p in starts}
            compile_bound_motion(self.api, models, starts, steps)
            self.steps = steps
            self.rebuild_rows()
            self.status.set_text("Sequence loaded; captured panel views retained")
        except Exception as exc:
            ui.notify(f"Cannot load sequence: {exc}", type="negative")

    async def run(self, *, preview: bool, start_only: bool = False) -> None:
        if self.busy:
            return
        self.busy = True
        self.cancelled.clear()
        for control in [*self.controls, *self.row_controls, self.close_button]:
            control.disable()
        self.cancel_button.enable()
        self.progress.set_value(0)
        self.status.set_text("Preparing bound animation")
        try:
            ids = self.active_ids()
            snapshots = {p: export_snapshot(self.api, self.captured[p], self.method.value) for p in ids}
            starts = {p: self.starts[p].copy() for p in ids}
            models = {p: snapshots[p].current_model for p in ids}
            segments = [] if start_only else compile_bound_motion(self.api, models, starts, copy.deepcopy(self.steps))
            fps = 1.0 if start_only else float(self.fps.value)
            height = int(self.height.value)
            if preview:
                fps, height = min(fps, PREVIEW_MAX_FPS), min(height, PREVIEW_MAX_HEIGHT)
            times, durations = (np.array([0.0]), np.array([1000])) if start_only else frame_schedule(segments, fps)
            if len(times) * len(ids) > 20000:
                raise ValueError("This export exceeds 20,000 panel frames. Reduce the duration, frame rate, or panel count.")
            frames = [starts if start_only else bound_frames_at(starts, segments, float(t)) for t in times]
            layout, transparent = self.content.value, bool(self.transparent.value)
            gif_mode, matte_color = self.gif_transparency.value, self.gif_matte.value
            if transparent and gif_mode == "matte" and (preview or self.format.value == "gif"):
                matte_color = "#%02X%02X%02X" % ImageColor.getcolor(matte_color, "RGB")
            contents = {p: "crystal" if layout == "crystals_combo" else self.panel_contents[p] for p in ids}
            show_crystal_name = bool(self.show_crystal_name.value)
            atom_shading = self.shading.value
            occupancy_colors = self.occupancy_colors.value
            if not preview:
                extension = ".zip" if layout == "separate" else "." + self.format.value
                name, destination = await self.export_destination(extension)
            metadata = {**self.sequence(), "renderer": self.renderer.value, "diffraction_method": self.method.value,
                "layout": layout, "frame_height": height, "fps_requested": fps, "sample_times_seconds": times.tolist(),
                "frame_durations_ms": durations.tolist(), "loop": bool(self.loop.value), "transparent_background": transparent,
                "gif_transparency": gif_mode, "gif_matte_color": matte_color,
                "show_crystal_name": show_crystal_name, "atom_shading": atom_shading, "occupancy_colors": occupancy_colors,
                "panels": {str(p): {"crystal": snapshots[p].state.crystal_name, "content": contents[p],
                    "display_settings": asdict(snapshots[p].state.display_settings),
                    "element_colors": snapshots[p].simulator.element_colors.copy(),
                    "diffraction_color": snapshots[p].state.diffraction_color,
                    "plane_colors": snapshots[p].simulator.plane_palette(p), "vector_colors": snapshots[p].simulator.vector_palette(p),
                    "plane_text": snapshots[p].state.plane_text, "vector_text": snapshots[p].state.vector_text} for p in ids},
                "simulation": {name: getattr(snapshots[ids[0]].simulator, name)() for name in (
                    "current_max_hkl", "current_voltage_kv", "current_thickness_nm", "current_camera_length_mm",
                    "current_spot_intensity_threshold", "current_intensity_compression_factor",
                    "uniform_spot_brightness")}}
            with tempfile.TemporaryDirectory(prefix="crysdis-combo-animation-") as folder:
                root = Path(folder)
                streams: dict[int, list[Path]] = {}
                # Render one crystal's stream at a time, using at most one extra WebGL context.
                for number, p in enumerate(ids if layout != "combo" else []):
                    snapshot = snapshots[p]
                    extent = animation_extent(self.api, models[p], snapshot.state)
                    key = "crysdis_animation_" + uuid.uuid4().hex
                    initialized = False
                    streams[p] = []
                    (root / f"panel_{p}").mkdir()
                    try:
                        self.cancel_check()
                        if self.renderer.value == "three" and contents[p] != "diffraction":
                            await initialize_three_renderer(self.api, key, snapshot, height, extent, transparent,
                                                            atom_shading=atom_shading, occupancy_colors=occupancy_colors)
                            initialized = True
                        for index, frame_set in enumerate(frames):
                            self.cancel_check()
                            self.status.set_text(f"{'Preview' if preview else 'Export'} ({fps:g} fps), panel {p}: frame {index + 1} / {len(times)}")
                            crystal_png = None
                            if initialized:
                                data_url = await ui.run_javascript(f"return window[{json.dumps(key)}].render({json.dumps(frame_set[p].tolist())});", timeout=30)
                                crystal_png = self.api.decode_png_data_url(data_url)
                            path = root / f"panel_{p}" / f"frame_{index:06d}.png"

                            def write_panel_frame() -> None:
                                with RENDER_LOCK:
                                    self.cancel_check()
                                    path.write_bytes(render_frame(self.api, snapshot, frame_set[p], height, contents[p], transparent, extent, crystal_png,
                                                                  show_crystal_name and layout == "separate" and not preview,
                                                                  atom_shading=atom_shading, occupancy_colors=occupancy_colors))

                            await asyncio.to_thread(write_panel_frame)
                            streams[p].append(path)
                            self.progress.set_value(.7 * (number * len(times) + index + 1) / (len(ids) * len(times)))
                    finally:
                        if initialized:
                            try:
                                await ui.run_javascript(f"window[{json.dumps(key)}]?.dispose();", timeout=5)
                            except Exception:
                                pass
                paths = []
                if layout != "separate" or preview:
                    for index, frame_set in enumerate(frames):
                        self.cancel_check()
                        self.status.set_text(f"{'Preview' if preview else 'Export'} ({fps:g} fps): composing frame {index + 1} / {len(times)}")
                        path = root / f"frame_{index:06d}.png"

                        def write_composite() -> None:
                            with RENDER_LOCK:
                                self.cancel_check()
                                for p, snapshot in snapshots.items():
                                    snapshot.state.view_vector, snapshot.state.roll = self.api.orientation_from_frame(frame_set[p])
                                png = render_bound_layout(self.api, snapshots, {p: stream[index] for p, stream in streams.items()},
                                    layout, height, transparent, show_crystal_name)
                                path.write_bytes(png)

                        await asyncio.to_thread(write_composite)
                        paths.append(path)
                        self.progress.set_value(.7 + .2 * (index + 1) / len(times))
                self.cancel_check()
                self.status.set_text("Encoding animation" if preview or self.format.value == "gif" else "Packaging PNG sequences")
                extension = ".gif" if preview else ".zip" if layout == "separate" else "." + self.format.value
                output = root / ("animation" + extension)
                if not start_only:
                    if layout == "separate" and not preview:
                        await asyncio.to_thread(package_panel_animations, streams, output, durations, metadata,
                                                self.format.value == "gif", bool(self.loop.value), self.cancelled)
                    else:
                        await asyncio.to_thread(encode_animation, paths, output, durations, metadata, bool(self.loop.value), self.cancelled)
                self.cancel_check()
                if preview:
                    import base64
                    self.preview_bytes = paths[0].read_bytes() if start_only else output.read_bytes()
                    encoded = base64.b64encode(self.preview_bytes).decode()
                    classes = "animation-preview animation-preview-transparent" if transparent else "animation-preview"
                    mime = "image/png" if start_only else "image/gif"
                    style = f'background:{matte_color};' if transparent and gif_mode == "matte" else ""
                    self.preview.set_content(f'<img class="{classes}" style="{style}" alt="Bound animation preview" src="data:{mime};base64,{encoded}">')
                else:
                    simulator = self.combo.simulator
                    if destination is not None:
                        await asyncio.to_thread(shutil.copyfile, output, destination)
                        simulator.announce_saved_exports([destination])
                    else:
                        offer_download(self.api, output, name)
                self.progress.set_value(1)
                prefix = "Starting views ready" if start_only else "Preview ready" if preview else "Export complete"
                self.status.set_text(f"{prefix}: {len(ids)} panels, {len(times)} frames at {fps:g} fps, {sum(durations) / 1000:g} s")
        except ExportCancelled:
            self.status.set_text("Animation cancelled")
        except Exception as exc:
            self.status.set_text(f"Animation failed: {exc}")
            ui.notify(f"Animation failed: {exc}", type="negative")
        finally:
            self.busy = False
            for control in [*self.controls, *self.row_controls, self.close_button]:
                control.enable()
            self.cancel_button.disable()
            self.update_format()
