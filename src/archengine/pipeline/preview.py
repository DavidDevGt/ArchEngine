"""Modo preview a PNG en memoria (FR-18, NFR-02, PDR §4.5, docs/05 §2).

Renderiza cuadros clave aislados directamente en memoria a formato PNG con
post-proceso y telemetria en tiempo inferior al SLA de latencia (p90 <= 200 ms).
"""

from __future__ import annotations

import importlib
import importlib.util
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import skia  # type: ignore[import-not-found]

from archengine.core.schema import (
    Topology,
    load_topology,
    load_yaml_file,
    validate_topology_dict,
)
from archengine.core.timebase import (
    frame_to_time_us,
    seconds_to_time_us,
    time_us_to_frame,
)
from archengine.geometry.primitives import (
    CircularQueue,
    Face,
    MemoryBlock,
    NetworkPipes,
    Primitive,
    ServerRack,
    StorageCylinder,
)
from archengine.geometry.topology_layout import compute_topology_layout
from archengine.render.core import (
    Camera,
    CameraKeyframe,
    CameraTrack,
    Renderer,
    encode_png_rgb24,
    orbit_cam,
)
from archengine.render.postprocess import PostProcessor


@dataclass
class Scene:
    """Escena declarativa consumida por el pipeline."""

    id: str
    video_width: int = 1080
    video_height: int = 1920
    fps: int = 30
    duration_s: float = 60.0
    seed: int = 42
    primitives: list[Primitive] = field(default_factory=list)
    camera_track: CameraTrack | None = None
    compose_fn: Callable[[int], list[Face]] | None = None
    # HUD en espacio de pantalla: (canvas, ancho, alto, t_us) tras rasterizar las caras.
    overlay_fn: Callable[[skia.Canvas, int, int, int], None] | None = None
    # Eventos de sonido en tiempo de video (audio derivado de la trace, docs/04).
    audio_fn: Callable[[], Any] | None = None
    # Trazas de simulacion por nombre (para `simulate`, manifest y cache).
    traces_fn: Callable[[], dict[str, Any]] | None = None
    input_files: list[Path] = field(default_factory=list)

    def get_faces(self, t_us: int) -> list[Face]:
        if self.compose_fn is not None:
            return self.compose_fn(t_us)
        faces: list[Face] = []
        for p in self.primitives:
            faces.extend(p.faces())
        return faces

    def get_camera(self, t_us: int) -> Camera:
        if self.camera_track is not None:
            return self.camera_track.camera_at(
                t_us, width=self.video_width, height=self.video_height
            )
        return orbit_cam(
            azimuth=45.0,
            elevation=35.264,
            scale=1.0,
            width=self.video_width,
            height=self.video_height,
        )


def build_default_camera_track(duration_s: float = 60.0) -> CameraTrack:
    dur_us = round(duration_s * 1_000_000)
    keyframes = [
        CameraKeyframe(t_us=0, azimuth=45.0, elevation=35.264, scale=1.0, target=(0.0, 0.0, 0.0)),
        CameraKeyframe(
            t_us=dur_us // 2, azimuth=50.0, elevation=38.0, scale=1.05, target=(0.0, 0.0, 10.0)
        ),
        CameraKeyframe(
            t_us=dur_us, azimuth=45.0, elevation=35.264, scale=1.0, target=(0.0, 0.0, 0.0)
        ),
    ]
    return CameraTrack(keyframes)


@dataclass(frozen=True)
class PreviewResult:
    """Resultado de la generacion de un cuadro preview."""

    png_bytes: bytes
    frame_k: int
    t_us: int
    render_time_ms: float
    width: int
    height: int


def build_scene_from_topology(topology: Topology) -> Scene:
    """Construye automaticamente una escena visual declarativa a partir de una topologia YAML."""
    primitives: list[Primitive] = []
    node_positions: dict[str, tuple[float, float, float]] = {}

    for node in topology.nodes:
        x, y, z = node.pos
        # Escalar coordenadas de rejilla si son pequeñas (e.g. [0, 0] y [6, 0])
        if abs(x) < 20.0 and abs(y) < 20.0:
            world_x = x * 100.0 - 150.0
            world_y = y * 100.0
            world_z = z * 100.0
        else:
            world_x, world_y, world_z = x, y, z

        pos_3d = (world_x, world_y, world_z)
        node_positions[node.id] = pos_3d

        if node.engine == "lsm":
            primitives.append(
                MemoryBlock(
                    id=f"{node.id}:mem",
                    pos=(world_x, world_y, world_z),
                    width=75.0,
                    depth=50.0,
                    height=90.0,
                    fill_level=0.45,
                )
            )
        elif node.engine == "btree":
            primitives.append(
                StorageCylinder(
                    id=f"{node.id}:disk",
                    center=(world_x + 35.0, world_y + 25.0, world_z),
                    radius=50.0,
                    height=30.0,
                    head_track_normalized=0.6,
                    written_ratio=0.5,
                )
            )
        elif node.kind == "queue":
            primitives.append(
                CircularQueue(
                    id=f"{node.id}:queue",
                    center=(world_x + 35.0, world_y + 25.0, world_z),
                    inner_radius=30.0,
                    outer_radius=55.0,
                    capacity=8,
                    head=2,
                    tail=6,
                )
            )
        else:
            primitives.append(
                ServerRack(
                    id=node.id,
                    pos=(world_x, world_y, world_z),
                    width=75.0,
                    depth=50.0,
                    height=100.0,
                    num_blades=4,
                    blade_states=["active", "idle", "active", "idle"],
                )
            )

    # Rutas ortogonales de red
    edges_to_route: list[tuple[str, str, str]] = []
    for net in topology.networks:
        for idx, edge in enumerate(net.edges):
            edges_to_route.append((f"{net.id}:{idx}", edge.from_node, edge.to_node))

    if edges_to_route:
        routes = compute_topology_layout(node_positions, edges_to_route, grid_step=20.0)
        for edge_id, route in routes.items():
            if len(route) >= 2:
                primitives.append(
                    NetworkPipes(
                        id=edge_id,
                        points=route,
                        width=8.0,
                        packets=[0.3, 0.7],
                    )
                )

    return Scene(
        id=topology.name,
        primitives=primitives,
        camera_track=build_default_camera_track(60.0),
    )


def build_demo_scene() -> Scene:
    """Escena demostrativa completa para pruebas y validaciones iniciales de Fase 1."""
    primitives: list[Primitive] = [
        # 1. ServerRack
        ServerRack(
            id="rack_app",
            pos=(-180.0, -50.0, 0.0),
            width=70.0,
            depth=50.0,
            height=110.0,
            num_blades=4,
            blade_states=["active", "idle", "active", "idle"],
        ),
        # 2. MemoryBlock (MemTable verde esmeralda)
        MemoryBlock(
            id="mem_lsm",
            pos=(0.0, -50.0, 0.0),
            width=70.0,
            depth=50.0,
            height=90.0,
            fill_level=0.65,
        ),
        # 3. StorageCylinder (B-Tree Disk)
        StorageCylinder(
            id="disk_btree",
            center=(180.0, -25.0, 0.0),
            radius=45.0,
            height=30.0,
            head_track_normalized=0.75,
            head_angle_rad=0.5,
            written_ratio=0.6,
        ),
        # 4. CircularQueue
        CircularQueue(
            id="queue_bus",
            center=(0.0, 120.0, 0.0),
            inner_radius=30.0,
            outer_radius=55.0,
            capacity=8,
            head=1,
            tail=5,
        ),
        # 5. NetworkPipes conectando nodos
        NetworkPipes(
            id="pipe_rack_to_mem",
            points=[(-110.0, -25.0, 20.0), (-40.0, -25.0, 20.0), (0.0, -25.0, 20.0)],
            width=6.0,
            packets=[0.25, 0.75],
        ),
        NetworkPipes(
            id="pipe_mem_to_disk",
            points=[(70.0, -25.0, 20.0), (105.0, -25.0, 20.0), (135.0, -25.0, 20.0)],
            width=6.0,
            packets=[0.5],
        ),
    ]

    return Scene(
        id="demo_phase1",
        primitives=primitives,
        camera_track=build_default_camera_track(60.0),
    )


_REGISTERED_SCENES: dict[str, str] = {
    "ep01": "archengine.scenes.ep01_lsm_vs_btree",
    "ep01_lsm_vs_btree": "archengine.scenes.ep01_lsm_vs_btree",
    "ep02": "archengine.scenes.ep02_cache_aside",
    "ep02_cache_aside": "archengine.scenes.ep02_cache_aside",
    "ep03": "archengine.scenes.ep03_message_queue",
    "ep03_message_queue": "archengine.scenes.ep03_message_queue",
    "ep04": "archengine.scenes.ep04_load_balancer",
    "ep04_load_balancer": "archengine.scenes.ep04_load_balancer",
}


def resolve_scene(scene_target: str | Scene, seed: int = 42) -> Scene:
    """Resuelve un identificador, ruta de archivo o instancia a una Scene ejecutable."""
    if isinstance(scene_target, Scene):
        return scene_target

    # Nombres registrados
    if scene_target in ("demo", "demo_phase1", "ep01_stub"):
        return build_demo_scene()
    if scene_target in _REGISTERED_SCENES:
        # Import dinamico: pipeline no depende estaticamente de scenes (import-linter).
        mod = importlib.import_module(_REGISTERED_SCENES[scene_target])
        built = mod.build(seed)
        if not isinstance(built, Scene):
            raise ValueError(f"{scene_target}: build() no devolvio una Scene")
        return built

    p = Path(scene_target).resolve()
    if p.is_file():
        if p.suffix in (".yaml", ".yml"):
            data = load_yaml_file(p)
            if "nodes" in data:
                topo = validate_topology_dict(data)
                return build_scene_from_topology(topo)
            # Archivo de escena YAML generico
            topo_name = str(data.get("topology", ""))
            if topo_name:
                # Buscar topologia vecina
                topo_p = p.parent / "topologies" / f"{topo_name}.yaml"
                if topo_p.is_file():
                    return build_scene_from_topology(load_topology(topo_p))
            return build_demo_scene()

        if p.suffix == ".py":
            spec = importlib.util.spec_from_file_location("scene_module", str(p))
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, "build"):
                    res = mod.build()
                    if isinstance(res, Scene):
                        return res
            raise ValueError(f"El archivo {p} no exporta una funcion build() -> Scene valida")

    # Intentar buscar en data/topologies/<target>.yaml
    possible_topo = (
        Path(__file__).resolve().parent.parent / "data" / "topologies" / f"{scene_target}.yaml"
    )
    if possible_topo.is_file():
        return build_scene_from_topology(load_topology(possible_topo))

    raise FileNotFoundError(f"No se pudo resolver la escena o topologia: {scene_target!r}")


_RENDERER_CACHE: dict[tuple[int, int], Renderer] = {}
_POSTPROCESSOR_CACHE: dict[tuple[int, int, int], PostProcessor] = {}


def get_cached_renderer(width: int, height: int) -> Renderer:
    key = (width, height)
    if key not in _RENDERER_CACHE:
        _RENDERER_CACHE[key] = Renderer(width=width, height=height)
    return _RENDERER_CACHE[key]


def get_cached_postprocessor(width: int, height: int, seed: int) -> PostProcessor:
    key = (width, height, seed)
    if key not in _POSTPROCESSOR_CACHE:
        _POSTPROCESSOR_CACHE[key] = PostProcessor(width=width, height=height, seed=seed)
    return _POSTPROCESSOR_CACHE[key]


def draw_scene_frame(renderer: Renderer, scene: Scene, t_us: int, scale: float = 1.0) -> None:
    """Rasteriza un cuadro completo (caras 3D + HUD). Codigo unico de preview y film."""
    w, h = renderer.width, renderer.height
    base_cam = scene.get_camera(t_us)
    cam = orbit_cam(
        target=base_cam.target,
        azimuth=base_cam.azimuth,
        elevation=base_cam.elevation,
        scale=base_cam.scale * scale,
        width=w,
        height=h,
    )
    renderer.render_frame(scene.get_faces(t_us), cam, clear_color_token="bg")
    if scene.overlay_fn is not None:
        scene.overlay_fn(renderer.surface.getCanvas(), w, h, t_us)


def render_preview(
    scene_target: str | Scene,
    t_seconds: float,
    scale: float = 1.0,
    seed: int = 42,
    apply_postprocessing: bool = False,
    output_path: str | Path | None = None,
) -> PreviewResult:
    """Renderiza un cuadro clave a PNG en memoria cumpliendo el SLA NFR-02 (<= 200 ms p90).

    Args:
        scene_target: Instancia de Scene, nombre registrado o ruta de archivo.
        t_seconds: Tiempo en segundos en el que se captura el cuadro.
        scale: Factor de escala adicional para calibracion interactiva.
        seed: Semilla para el grano determinista.
        apply_postprocessing: Si aplica viñeta y grano analógico (False por defecto en preview).
        output_path: Ruta opcional de destino para escribir el archivo .png.

    Returns:
        PreviewResult con los bytes PNG, metadatos y tiempo de renderizado medido.
    """
    t_start = time.perf_counter()

    scene = resolve_scene(scene_target, seed)
    t_us = seconds_to_time_us(t_seconds)
    k = time_us_to_frame(t_us, scene.fps)

    w = round(scene.video_width * scale)
    h = round(scene.video_height * scale)

    renderer = get_cached_renderer(width=w, height=h)
    draw_scene_frame(renderer, scene, frame_to_time_us(k, scene.fps), scale)

    if apply_postprocessing:
        # Extraer buffer, aplicar postproceso y generar PNG
        rgb = renderer.to_rgb24_buffer()
        post = get_cached_postprocessor(width=w, height=h, seed=seed)
        processed_rgb = post.apply(rgb, k=k)

        png_bytes = encode_png_rgb24(processed_rgb)
    else:
        png_bytes = renderer.to_png_bytes()

    t_end = time.perf_counter()
    elapsed_ms = (t_end - t_start) * 1000.0

    if output_path is not None:
        p = Path(output_path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(png_bytes)

    return PreviewResult(
        png_bytes=png_bytes,
        frame_k=k,
        t_us=t_us,
        render_time_ms=elapsed_ms,
        width=w,
        height=h,
    )
