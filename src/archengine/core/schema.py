"""Validacion estricta de esquemas YAML (schema_version: 1).

Proporciona modelos fuertemente tipados basados en dataclasses y validacion
exhaustiva con rutas legibles para topologias, protocolos operativos y escenas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_ID_PATTERN = re.compile(r"^[a-z0-9_]+$")


class ValidationError(Exception):
    """Error de validacion de esquema con ruta JSON-path legible."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"[{path}] {message}")


# -----------------------------------------------------------------------------
# Modelos de Topologia (FR-01)
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class NodeSpec:
    """Especificacion de un nodo de la topologia."""

    id: str
    kind: str
    pos: tuple[float, float, float]
    engine: str = "none"
    capacities: dict[str, int] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EdgeSpec:
    """Especificacion de un enlace de red entre dos nodos."""

    from_node: str
    to_node: str
    latency_us: int = 0
    jitter_us: int = 0
    loss: float = 0.0


@dataclass(frozen=True)
class NetworkSpec:
    """Especificacion de una red de comunicacion."""

    id: str
    edges: list[EdgeSpec] = field(default_factory=list)


@dataclass(frozen=True)
class Topology:
    """Topologia completa declarativa."""

    schema_version: int
    name: str
    nodes: list[NodeSpec]
    networks: list[NetworkSpec] = field(default_factory=list)

    def get_node(self, node_id: str) -> NodeSpec | None:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None


# -----------------------------------------------------------------------------
# Modelos de Protocolos y Motores (FR-02)
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class DiskHDDConfig:
    rpm: int = 7200
    avg_seek_us: int = 8500
    avg_rotation_us: int = 4166
    seq_throughput_mb_s: int = 150
    tracks: int = 2000
    seek_track_to_track_us: int = 800
    seek_max_us: int = 16000
    transfer_us_per_page: int = 27
    source: str = ""


@dataclass(frozen=True)
class LSMConfig:
    memtable_bytes: int = 67_108_864
    sstable_bytes: int = 67_108_864
    l0_compaction_trigger: int = 4
    wal_sync: str = "batch"
    source: str = ""


@dataclass(frozen=True)
class BTreeConfig:
    page_bytes: int = 4096
    fanout: int = 256
    buffer_pool_pages: int = 1024
    source: str = ""


@dataclass(frozen=True)
class RaftConfig:
    election_timeout_ms: tuple[int, int] = (150, 300)
    heartbeat_interval_ms: int = 50


@dataclass(frozen=True)
class TransportConfig:
    ttl_hops: int = 16
    frame_bytes: int = 1500
    timeout_ms: int = 1000


@dataclass(frozen=True)
class ProtocolsConfig:
    schema_version: int
    disk_hdd: DiskHDDConfig = field(default_factory=DiskHDDConfig)
    lsm: LSMConfig = field(default_factory=LSMConfig)
    btree: BTreeConfig = field(default_factory=BTreeConfig)
    raft: RaftConfig = field(default_factory=RaftConfig)
    transport: TransportConfig = field(default_factory=TransportConfig)


# -----------------------------------------------------------------------------
# Modelos de Escena Declarativa (FR-20)
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class VideoConfig:
    width: int = 1080
    height: int = 1920
    fps: int = 30
    duration_s: float = 60.0


@dataclass(frozen=True)
class CameraKeyframeConfig:
    t: float
    azimuth: float = 45.0
    elevation: float = 35.264
    scale: float = 1.0
    target: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class SegmentConfig:
    id: str
    t: tuple[float, float]
    title: str = ""
    time_scale: float = 1.0


@dataclass(frozen=True)
class ActionConfig:
    t: float
    do: str
    target: str | list[str] = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OverlayConfig:
    t: tuple[float, float]
    text: str
    pos: tuple[float, float] = (0.0, 0.0)
    style: str = "default"


@dataclass(frozen=True)
class SceneConfig:
    schema_version: int
    id: str
    video: VideoConfig
    seed: int = 42
    topology: str = ""
    camera: list[CameraKeyframeConfig] = field(default_factory=list)
    segments: list[SegmentConfig] = field(default_factory=list)
    actions: list[ActionConfig] = field(default_factory=list)
    overlays: list[OverlayConfig] = field(default_factory=list)


# -----------------------------------------------------------------------------
# Validadores Funcionales
# -----------------------------------------------------------------------------


def _check_schema_version(data: dict[str, Any], path: str = "") -> int:
    if "schema_version" not in data:
        raise ValidationError(path or "schema_version", "Falta campo obligatorio 'schema_version'")
    v = data["schema_version"]
    if not isinstance(v, int) or v != 1:
        raise ValidationError(
            f"{path}.schema_version" if path else "schema_version",
            f"Solo se soporta schema_version: 1, recibido: {v!r}",
        )
    return v


def validate_topology_dict(raw: dict[str, Any]) -> Topology:
    """Valida un diccionario contra el esquema de Topologia (FR-01)."""
    if not isinstance(raw, dict):
        raise ValidationError("root", "El documento debe ser un mapeo/diccionario")

    v = _check_schema_version(raw)
    name = raw.get("name")
    if not name or not isinstance(name, str):
        raise ValidationError("name", "Debe incluir un campo 'name' no vacio")

    nodes_raw = raw.get("nodes")
    if not isinstance(nodes_raw, list) or not nodes_raw:
        raise ValidationError("nodes", "'nodes' debe ser una lista no vacia")

    seen_node_ids: set[str] = set()
    node_specs: list[NodeSpec] = []

    for i, n in enumerate(nodes_raw):
        prefix = f"nodes[{i}]"
        if not isinstance(n, dict):
            raise ValidationError(prefix, "Cada nodo debe ser un diccionario")

        node_id = n.get("id")
        if not isinstance(node_id, str) or not _ID_PATTERN.match(node_id):
            raise ValidationError(
                f"{prefix}.id",
                f"El ID de nodo debe cumplir regex ^[a-z0-9_]+$, recibido: {node_id!r}",
            )
        if node_id in seen_node_ids:
            raise ValidationError(f"{prefix}.id", f"ID de nodo duplicado: {node_id}")
        seen_node_ids.add(node_id)

        kind = n.get("kind", "server_rack")
        if not isinstance(kind, str) or not kind:
            raise ValidationError(f"{prefix}.kind", "El campo 'kind' no puede ser vacio")

        pos_raw = n.get("pos", [0.0, 0.0, 0.0])
        if not isinstance(pos_raw, (list, tuple)) or len(pos_raw) not in (2, 3):
            raise ValidationError(
                f"{prefix}.pos",
                f"pos debe ser lista/tupla de 2 o 3 coordenadas numericas, recibido: {pos_raw}",
            )
        try:
            pos_x = float(pos_raw[0])
            pos_y = float(pos_raw[1])
            pos_z = float(pos_raw[2]) if len(pos_raw) == 3 else 0.0
        except (TypeError, ValueError) as err:
            raise ValidationError(
                f"{prefix}.pos", f"Coordenadas pos deben ser numeros: {err}"
            ) from err

        engine = str(n.get("engine", "none"))

        capacities_raw = n.get("capacities", {})
        capacities: dict[str, int] = {}
        if capacities_raw:
            if not isinstance(capacities_raw, dict):
                raise ValidationError(f"{prefix}.capacities", "capacities debe ser un diccionario")
            for cap_k, cap_v in capacities_raw.items():
                if not isinstance(cap_v, int) or cap_v <= 0:
                    raise ValidationError(
                        f"{prefix}.capacities.{cap_k}",
                        f"La capacidad debe ser un entero > 0, recibido: {cap_v!r}",
                    )
                capacities[str(cap_k)] = cap_v

        labels_raw = n.get("labels", {})
        labels = (
            {str(k): str(val) for k, val in labels_raw.items()}
            if isinstance(labels_raw, dict)
            else {}
        )

        node_specs.append(
            NodeSpec(
                id=node_id,
                kind=kind,
                pos=(pos_x, pos_y, pos_z),
                engine=engine,
                capacities=capacities,
                labels=labels,
            )
        )

    networks_raw = raw.get("networks", [])
    networks: list[NetworkSpec] = []
    if networks_raw is not None:
        if not isinstance(networks_raw, list):
            raise ValidationError("networks", "'networks' debe ser una lista")

        seen_net_ids: set[str] = set()
        for i, net in enumerate(networks_raw):
            net_prefix = f"networks[{i}]"
            if not isinstance(net, dict):
                raise ValidationError(net_prefix, "Cada red debe ser un diccionario")
            net_id = net.get("id")
            if not isinstance(net_id, str) or not net_id:
                raise ValidationError(f"{net_prefix}.id", "ID de red invalido o vacio")
            if net_id in seen_net_ids:
                raise ValidationError(f"{net_prefix}.id", f"ID de red duplicado: {net_id}")
            seen_net_ids.add(net_id)

            edges_raw = net.get("edges", [])
            edges: list[EdgeSpec] = []
            if edges_raw is not None:
                if not isinstance(edges_raw, list):
                    raise ValidationError(f"{net_prefix}.edges", "edges debe ser una lista")
                for j, e in enumerate(edges_raw):
                    edge_prefix = f"{net_prefix}.edges[{j}]"
                    if not isinstance(e, dict):
                        raise ValidationError(edge_prefix, "Cada arista debe ser un diccionario")
                    from_node = e.get("from") or e.get("from_node")
                    to_node = e.get("to") or e.get("to_node")
                    if not isinstance(from_node, str) or from_node not in seen_node_ids:
                        raise ValidationError(
                            f"{edge_prefix}.from",
                            f"from_node '{from_node}' no existe en la topologia",
                        )
                    if not isinstance(to_node, str) or to_node not in seen_node_ids:
                        raise ValidationError(
                            f"{edge_prefix}.to",
                            f"to_node '{to_node}' no existe en la topologia",
                        )

                    latency_us = int(e.get("latency_us", 0))
                    jitter_us = int(e.get("jitter_us", 0))
                    loss = float(e.get("loss", 0.0))

                    if latency_us < 0:
                        raise ValidationError(
                            f"{edge_prefix}.latency_us", "latency_us no puede ser negativo"
                        )
                    if jitter_us < 0:
                        raise ValidationError(
                            f"{edge_prefix}.jitter_us", "jitter_us no puede ser negativo"
                        )
                    if not (0.0 <= loss <= 1.0):
                        raise ValidationError(
                            f"{edge_prefix}.loss",
                            f"loss debe estar en [0.0, 1.0], recibido: {loss}",
                        )

                    edges.append(
                        EdgeSpec(
                            from_node=from_node,
                            to_node=to_node,
                            latency_us=latency_us,
                            jitter_us=jitter_us,
                            loss=loss,
                        )
                    )
            networks.append(NetworkSpec(id=net_id, edges=edges))

    return Topology(schema_version=v, name=name, nodes=node_specs, networks=networks)


def validate_protocols_dict(raw: dict[str, Any]) -> ProtocolsConfig:
    """Valida un diccionario contra el esquema de protocolos operativos (FR-02)."""
    if not isinstance(raw, dict):
        raise ValidationError("root", "El documento debe ser un mapeo/diccionario")

    v = _check_schema_version(raw)

    # Permitir anidamiento bajo 'protocols' o 'engines' o directamente en raiz
    container = raw.get("protocols", raw)
    engines = raw.get("engines", raw)

    # Disco HDD
    disk_raw = engines.get("disk_hdd") or engines.get("disk", {})
    disk_cfg = DiskHDDConfig(
        rpm=int(disk_raw.get("rpm", 7200)),
        avg_seek_us=int(disk_raw.get("avg_seek_us", disk_raw.get("seek_avg_us", 8500))),
        avg_rotation_us=int(disk_raw.get("avg_rotation_us", disk_raw.get("rotational_us", 4166))),
        seq_throughput_mb_s=int(disk_raw.get("seq_throughput_mb_s", 150)),
        tracks=int(disk_raw.get("tracks", 2000)),
        seek_track_to_track_us=int(disk_raw.get("seek_track_to_track_us", 800)),
        seek_max_us=int(disk_raw.get("seek_max_us", 16000)),
        transfer_us_per_page=int(disk_raw.get("transfer_us_per_page", 27)),
        source=str(disk_raw.get("source", "")),
    )

    # LSM
    lsm_raw = engines.get("lsm", {})
    lsm_cfg = LSMConfig(
        memtable_bytes=int(lsm_raw.get("memtable_bytes", 67_108_864)),
        sstable_bytes=int(lsm_raw.get("sstable_bytes", 67_108_864)),
        l0_compaction_trigger=int(lsm_raw.get("l0_compaction_trigger", 4)),
        wal_sync=str(lsm_raw.get("wal_sync", "batch")),
        source=str(lsm_raw.get("source", "")),
    )

    # B-Tree
    btree_raw = engines.get("btree", {})
    btree_cfg = BTreeConfig(
        page_bytes=int(btree_raw.get("page_bytes", 4096)),
        fanout=int(btree_raw.get("fanout", 256)),
        buffer_pool_pages=int(btree_raw.get("buffer_pool_pages", 1024)),
        source=str(btree_raw.get("source", "")),
    )

    # Raft
    raft_raw = container.get("raft", {})
    raft_timeout = raft_raw.get("election_timeout_ms", [150, 300])
    if isinstance(raft_timeout, (list, tuple)) and len(raft_timeout) == 2:
        t_range = (int(raft_timeout[0]), int(raft_timeout[1]))
    else:
        t_range = (150, 300)
    raft_cfg = RaftConfig(
        election_timeout_ms=t_range,
        heartbeat_interval_ms=int(raft_raw.get("heartbeat_interval_ms", 50)),
    )

    # Transport
    trans_raw = container.get("transport", {})
    trans_cfg = TransportConfig(
        ttl_hops=int(trans_raw.get("ttl_hops", 16)),
        frame_bytes=int(trans_raw.get("frame_bytes", 1500)),
        timeout_ms=int(trans_raw.get("timeout_ms", 1000)),
    )

    return ProtocolsConfig(
        schema_version=v,
        disk_hdd=disk_cfg,
        lsm=lsm_cfg,
        btree=btree_cfg,
        raft=raft_cfg,
        transport=trans_cfg,
    )


def validate_scene_dict(raw: dict[str, Any]) -> SceneConfig:
    """Valida un diccionario contra el esquema logico de Escena (FR-20)."""
    if not isinstance(raw, dict):
        raise ValidationError("root", "El documento de escena debe ser un diccionario")

    v = _check_schema_version(raw)
    scene_id = raw.get("id")
    if not scene_id or not isinstance(scene_id, str):
        raise ValidationError("id", "Falta ID de escena no vacio")

    video_raw = raw.get("video", {})
    if not isinstance(video_raw, dict):
        raise ValidationError("video", "video debe ser un diccionario")
    width = int(video_raw.get("width", 1080))
    height = int(video_raw.get("height", 1920))
    fps = int(video_raw.get("fps", 30))
    duration_s = float(video_raw.get("duration_s", 60.0))
    if width <= 0 or height <= 0:
        raise ValidationError("video.resolution", "Resolucion debe ser positiva")
    if fps <= 0:
        raise ValidationError("video.fps", "FPS debe ser positivo")
    if duration_s <= 0:
        raise ValidationError("video.duration_s", "duration_s debe ser positivo")
    video_cfg = VideoConfig(width=width, height=height, fps=fps, duration_s=duration_s)

    seed = int(raw.get("seed", 42))
    topology_name = str(raw.get("topology", ""))

    # Segmentos
    segments_raw = raw.get("segments", [])
    segments: list[SegmentConfig] = []
    if not isinstance(segments_raw, list):
        raise ValidationError("segments", "segments debe ser una lista")

    last_t_end = 0.0
    for i, s in enumerate(segments_raw):
        s_prefix = f"segments[{i}]"
        if not isinstance(s, dict):
            raise ValidationError(s_prefix, "Cada segmento debe ser un diccionario")
        seg_id = s.get("id")
        if not isinstance(seg_id, str) or not seg_id:
            raise ValidationError(f"{s_prefix}.id", "ID de segmento invalido")
        t_range = s.get("t")
        if not isinstance(t_range, (list, tuple)) or len(t_range) != 2:
            raise ValidationError(
                f"{s_prefix}.t", "t debe ser rango de dos elementos [t_start, t_end]"
            )
        t_start, t_end = float(t_range[0]), float(t_range[1])
        if t_start < 0 or t_end <= t_start:
            raise ValidationError(
                f"{s_prefix}.t", f"Intervalo temporal invalido: [{t_start}, {t_end}]"
            )
        if i > 0 and abs(t_start - last_t_end) > 1e-4:
            raise ValidationError(
                f"{s_prefix}.t",
                f"Discontinuidad entre segmentos: prev={last_t_end}s vs actual={t_start}s",
            )
        last_t_end = t_end
        segments.append(
            SegmentConfig(
                id=seg_id,
                t=(t_start, t_end),
                title=str(s.get("title", "")),
                time_scale=float(s.get("time_scale", 1.0)),
            )
        )

    # Validar que los segmentos cubran hasta duration_s si hay segmentos
    if segments and abs(last_t_end - duration_s) > 1e-4:
        raise ValidationError(
            "segments",
            f"La suma de segmentos ({last_t_end}s) no coincide con duration_s ({duration_s}s)",
        )

    # Camaras
    camera_raw = raw.get("camera", [])
    camera_keyframes: list[CameraKeyframeConfig] = []
    if isinstance(camera_raw, list):
        for i, c in enumerate(camera_raw):
            c_prefix = f"camera[{i}]"
            if not isinstance(c, dict):
                raise ValidationError(c_prefix, "Cada keyframe de camara debe ser un diccionario")
            target_raw = c.get("target", [0.0, 0.0, 0.0])
            target = (
                float(target_raw[0]),
                float(target_raw[1]),
                float(target_raw[2]) if len(target_raw) > 2 else 0.0,
            )
            camera_keyframes.append(
                CameraKeyframeConfig(
                    t=float(c.get("t", 0.0)),
                    azimuth=float(c.get("azimuth", 45.0)),
                    elevation=float(c.get("elevation", 35.264)),
                    scale=float(c.get("scale", 1.0)),
                    target=target,
                )
            )

    return SceneConfig(
        schema_version=v,
        id=scene_id,
        video=video_cfg,
        seed=seed,
        topology=topology_name,
        camera=camera_keyframes,
        segments=segments,
    )


# -----------------------------------------------------------------------------
# Carga Segura y Deteccion de Archivos
# -----------------------------------------------------------------------------


def load_yaml_file(path: str | Path) -> dict[str, Any]:
    """Carga un archivo YAML usando yaml.safe_load garantizando que no ejecute codigo."""
    p = Path(path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Archivo no encontrado: {p}")
    content = p.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    if not isinstance(data, dict):
        raise ValidationError("root", f"El archivo {p.name} no contiene un objeto YAML valido")
    return data


def load_topology(path: str | Path) -> Topology:
    """Carga y valida estrictamente un archivo de topologia."""
    data = load_yaml_file(path)
    return validate_topology_dict(data)


def load_protocols(path: str | Path) -> ProtocolsConfig:
    """Carga y valida estrictamente un archivo de protocolos operativos."""
    data = load_yaml_file(path)
    return validate_protocols_dict(data)


def validate_file(path: str | Path) -> Topology | ProtocolsConfig | SceneConfig:
    """Detecta automaticamente el tipo de archivo YAML y valida su esquema.

    Returns:
        Instancia de Topology, ProtocolsConfig o SceneConfig segun corresponda.

    Raises:
        ValidationError: Si el esquema es invalido o no reconocido.
    """
    data = load_yaml_file(path)
    if "nodes" in data:
        return validate_topology_dict(data)
    if "video" in data or "segments" in data:
        return validate_scene_dict(data)
    if (
        "disk_hdd" in data
        or "lsm" in data
        or "btree" in data
        or "protocols" in data
        or "engines" in data
    ):
        return validate_protocols_dict(data)
    raise ValidationError(
        "root", "No se pudo inferir el tipo de esquema YAML (falta 'nodes', 'video' o motores)"
    )
