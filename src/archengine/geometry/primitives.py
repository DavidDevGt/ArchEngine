"""Primitivas geometricas procedurales volumetricas (FR-13, PDR §4.2).

Implementa ServerRack, CircularQueue, StorageCylinder, NetworkPipes y MemoryBlock
con generacion analitica de poligonos 3D, normales de cara y ordenamiento por capas.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

# Constantes de capas (ADR-0003, docs/03 §4)
LAYER_BACKGROUND: int = 0
LAYER_FLOOR: int = 10
LAYER_BUS: int = 20
LAYER_BODY: int = 30
LAYER_LED: int = 40
LAYER_DECAL: int = 50
LAYER_HUD: int = 60


@dataclass(frozen=True)
class DecalSpec:
    """Especificacion de decal proyectivo 2D para mapear sobre una cara 3D."""

    src_width: float
    src_height: float
    draw_fn: Callable[[Any, float, float], None]


@dataclass(frozen=True)
class Face:
    """Poligono planar 3D con normal analitica, token semantico y atributos de render."""

    vertices: np.ndarray  # Shape: (N, 3), float64
    normal: np.ndarray  # Shape: (3,), unit vector float64
    color_token: str  # Referencia en render.theme.THEME
    layer: int = LAYER_BODY
    id: str = ""
    decal_spec: DecalSpec | None = None
    wireframe: bool = False

    @property
    def centroid(self) -> np.ndarray:
        return np.asarray(np.mean(self.vertices, axis=0), dtype=np.float64)


class Primitive(Protocol):
    """Protocolo comun para todas las primitivas geometricas."""

    id: str
    layer: int

    def faces(self, view_state: Any = None) -> list[Face]: ...


def _make_box_faces(
    base_id: str,
    x: float,
    y: float,
    z: float,
    w: float,
    d: float,
    h: float,
    color_token: str,
    layer: int = LAYER_BODY,
    decal_front: DecalSpec | None = None,
) -> list[Face]:
    """Genera las 6 caras de un paralelepipedo alineado a los ejes con normales exteriores."""
    p000 = np.array([x, y, z], dtype=np.float64)
    p100 = np.array([x + w, y, z], dtype=np.float64)
    p110 = np.array([x + w, y + d, z], dtype=np.float64)
    p010 = np.array([x, y + d, z], dtype=np.float64)
    p001 = np.array([x, y, z + h], dtype=np.float64)
    p101 = np.array([x + w, y, z + h], dtype=np.float64)
    p111 = np.array([x + w, y + d, z + h], dtype=np.float64)
    p011 = np.array([x, y + d, z + h], dtype=np.float64)

    return [
        # Front (-Y)
        Face(
            vertices=np.array([p000, p100, p101, p001], dtype=np.float64),
            normal=np.array([0.0, -1.0, 0.0], dtype=np.float64),
            color_token=color_token,
            layer=layer,
            id=f"{base_id}:front",
            decal_spec=decal_front,
        ),
        # Back (+Y)
        Face(
            vertices=np.array([p110, p010, p011, p111], dtype=np.float64),
            normal=np.array([0.0, 1.0, 0.0], dtype=np.float64),
            color_token=color_token,
            layer=layer,
            id=f"{base_id}:back",
        ),
        # Left (-X)
        Face(
            vertices=np.array([p010, p000, p001, p011], dtype=np.float64),
            normal=np.array([-1.0, 0.0, 0.0], dtype=np.float64),
            color_token=color_token,
            layer=layer,
            id=f"{base_id}:left",
        ),
        # Right (+X)
        Face(
            vertices=np.array([p100, p110, p111, p101], dtype=np.float64),
            normal=np.array([1.0, 0.0, 0.0], dtype=np.float64),
            color_token=color_token,
            layer=layer,
            id=f"{base_id}:right",
        ),
        # Top (+Z)
        Face(
            vertices=np.array([p001, p101, p111, p011], dtype=np.float64),
            normal=np.array([0.0, 0.0, 1.0], dtype=np.float64),
            color_token=color_token,
            layer=layer,
            id=f"{base_id}:top",
        ),
        # Bottom (-Z)
        Face(
            vertices=np.array([p010, p110, p100, p000], dtype=np.float64),
            normal=np.array([0.0, 0.0, -1.0], dtype=np.float64),
            color_token=color_token,
            layer=layer,
            id=f"{base_id}:bottom",
        ),
    ]


# -----------------------------------------------------------------------------
# 1. ServerRack (FR-13)
# -----------------------------------------------------------------------------


@dataclass
class ServerRack:
    """Rack de servidores modulares blade con LEDs de estado y ranuras de bus."""

    id: str
    pos: tuple[float, float, float] = (0.0, 0.0, 0.0)
    width: float = 80.0
    depth: float = 60.0
    height: float = 120.0
    num_blades: int = 4
    blade_states: list[str] = field(default_factory=lambda: ["idle", "idle", "idle", "idle"])
    is_crashed: bool = False
    layer: int = LAYER_BODY
    decal: DecalSpec | None = None

    def faces(self, view_state: Any = None) -> list[Face]:
        x, y, z = self.pos
        body_color = "alert" if self.is_crashed else "node_idle"
        result: list[Face] = []

        # Chasis principal
        result.extend(
            _make_box_faces(
                base_id=self.id,
                x=x,
                y=y,
                z=z,
                w=self.width,
                d=self.depth,
                h=self.height,
                color_token=body_color,
                layer=self.layer,
                decal_front=self.decal,
            )
        )

        # Modulos blade y LEDs frontales
        margin_x = self.width * 0.08
        blade_w = self.width - 2.0 * margin_x
        margin_z = self.height * 0.05
        available_h = self.height - 2.0 * margin_z
        blade_h = available_h / max(1, self.num_blades)

        for i in range(self.num_blades):
            bz = z + margin_z + i * blade_h
            state = (
                "alert"
                if self.is_crashed
                else (self.blade_states[i] if i < len(self.blade_states) else "idle")
            )

            # Ranura blade
            slot_p0 = np.array([x + margin_x, y - 0.5, bz + blade_h * 0.1], dtype=np.float64)
            slot_p1 = np.array(
                [x + margin_x + blade_w, y - 0.5, bz + blade_h * 0.1], dtype=np.float64
            )
            slot_p2 = np.array(
                [x + margin_x + blade_w, y - 0.5, bz + blade_h * 0.9], dtype=np.float64
            )
            slot_p3 = np.array([x + margin_x, y - 0.5, bz + blade_h * 0.9], dtype=np.float64)
            result.append(
                Face(
                    vertices=np.array([slot_p0, slot_p1, slot_p2, slot_p3], dtype=np.float64),
                    normal=np.array([0.0, -1.0, 0.0], dtype=np.float64),
                    color_token="wireframe",
                    layer=self.layer + 1,
                    id=f"{self.id}:blade_slot:{i}",
                )
            )

            # LED de actividad
            led_color = (
                "led_alert"
                if state == "alert"
                else ("led_active" if state == "active" else "led_idle")
            )
            led_size = min(blade_h * 0.4, 6.0)
            led_x = x + margin_x + 4.0
            led_z = bz + blade_h * 0.5 - led_size * 0.5
            led_p0 = np.array([led_x, y - 1.0, led_z], dtype=np.float64)
            led_p1 = np.array([led_x + led_size, y - 1.0, led_z], dtype=np.float64)
            led_p2 = np.array([led_x + led_size, y - 1.0, led_z + led_size], dtype=np.float64)
            led_p3 = np.array([led_x, y - 1.0, led_z + led_size], dtype=np.float64)
            result.append(
                Face(
                    vertices=np.array([led_p0, led_p1, led_p2, led_p3], dtype=np.float64),
                    normal=np.array([0.0, -1.0, 0.0], dtype=np.float64),
                    color_token=led_color,
                    layer=LAYER_LED,
                    id=f"{self.id}:led:{i}",
                )
            )

        return result


# -----------------------------------------------------------------------------
# 2. CircularQueue (FR-13)
# -----------------------------------------------------------------------------


@dataclass
class CircularQueue:
    """Buffer anular para colas de mensajeria con sectores extruidos y punteros head/tail."""

    id: str
    center: tuple[float, float, float] = (0.0, 0.0, 0.0)
    inner_radius: float = 35.0
    outer_radius: float = 65.0
    height: float = 18.0
    capacity: int = 8
    head: int = 0
    tail: int = 0
    overflow: bool = False
    layer: int = LAYER_BODY

    def faces(self, view_state: Any = None) -> list[Face]:
        cx, cy, cz = self.center
        result: list[Face] = []
        n_sectors = max(3, self.capacity)
        angle_step = 2.0 * math.pi / n_sectors

        # Determinar si el sector i esta ocupado
        def is_occupied(idx: int) -> bool:
            if self.head == self.tail:
                return False
            if self.tail > self.head:
                return self.head <= idx < self.tail
            return idx >= self.head or idx < self.tail

        for i in range(n_sectors):
            th0 = i * angle_step
            th1 = (i + 1) * angle_step
            c0, s0 = math.cos(th0), math.sin(th0)
            c1, s1 = math.cos(th1), math.sin(th1)

            # 4 vertices de la cara superior
            p_in0_top = np.array(
                [cx + self.inner_radius * c0, cy + self.inner_radius * s0, cz + self.height],
                dtype=np.float64,
            )
            p_out0_top = np.array(
                [cx + self.outer_radius * c0, cy + self.outer_radius * s0, cz + self.height],
                dtype=np.float64,
            )
            p_out1_top = np.array(
                [cx + self.outer_radius * c1, cy + self.outer_radius * s1, cz + self.height],
                dtype=np.float64,
            )
            p_in1_top = np.array(
                [cx + self.inner_radius * c1, cy + self.inner_radius * s1, cz + self.height],
                dtype=np.float64,
            )

            # 4 vertices inferiores
            p_out0_bot = np.array(
                [cx + self.outer_radius * c0, cy + self.outer_radius * s0, cz], dtype=np.float64
            )
            p_out1_bot = np.array(
                [cx + self.outer_radius * c1, cy + self.outer_radius * s1, cz], dtype=np.float64
            )

            occupied = is_occupied(i)
            if self.overflow:
                color = "alert"
            elif occupied:
                color = "mem"
            elif i == self.head:
                color = "bus"
            else:
                color = "node_idle"

            # Cara superior del sector
            result.append(
                Face(
                    vertices=np.array(
                        [p_in0_top, p_out0_top, p_out1_top, p_in1_top], dtype=np.float64
                    ),
                    normal=np.array([0.0, 0.0, 1.0], dtype=np.float64),
                    color_token=color,
                    layer=self.layer,
                    id=f"{self.id}:sector_top:{i}",
                )
            )

            # Cara exterior radial
            mid_th = 0.5 * (th0 + th1)
            radial_normal = np.array([math.cos(mid_th), math.sin(mid_th), 0.0], dtype=np.float64)
            result.append(
                Face(
                    vertices=np.array(
                        [p_out0_bot, p_out1_bot, p_out1_top, p_out0_top], dtype=np.float64
                    ),
                    normal=radial_normal,
                    color_token=color,
                    layer=self.layer,
                    id=f"{self.id}:sector_wall:{i}",
                )
            )

        return result


# -----------------------------------------------------------------------------
# 3. StorageCylinder (FR-13)
# -----------------------------------------------------------------------------


@dataclass
class StorageCylinder:
    """Cilindro facetado (>= 32 segmentos) con sectores y cabezal de disco movil."""

    id: str
    center: tuple[float, float, float] = (0.0, 0.0, 0.0)
    radius: float = 60.0
    height: float = 35.0
    num_segments: int = 32
    head_track_normalized: float = 0.5  # 0.0 (interior) a 1.0 (exterior)
    head_angle_rad: float = 0.0
    written_ratio: float = 0.0  # 0.0 a 1.0
    layer: int = LAYER_BODY

    def faces(self, view_state: Any = None) -> list[Face]:
        cx, cy, cz = self.center
        result: list[Face] = []
        n_segs = max(16, self.num_segments)
        step = 2.0 * math.pi / n_segs

        # 1. Tapa superior facetada
        top_center = np.array([cx, cy, cz + self.height], dtype=np.float64)
        for i in range(n_segs):
            th0 = i * step
            th1 = (i + 1) * step
            p0 = np.array(
                [
                    cx + self.radius * math.cos(th0),
                    cy + self.radius * math.sin(th0),
                    cz + self.height,
                ],
                dtype=np.float64,
            )
            p1 = np.array(
                [
                    cx + self.radius * math.cos(th1),
                    cy + self.radius * math.sin(th1),
                    cz + self.height,
                ],
                dtype=np.float64,
            )

            # Sectores escritos tienen color disk
            frac = (i + 1) / n_segs
            color = "disk" if frac <= self.written_ratio else "node_idle"

            result.append(
                Face(
                    vertices=np.array([top_center, p0, p1], dtype=np.float64),
                    normal=np.array([0.0, 0.0, 1.0], dtype=np.float64),
                    color_token=color,
                    layer=self.layer,
                    id=f"{self.id}:disk_top:{i}",
                )
            )

        # 2. Paredes laterales cilindricas
        for i in range(n_segs):
            th0 = i * step
            th1 = (i + 1) * step
            p0_top = np.array(
                [
                    cx + self.radius * math.cos(th0),
                    cy + self.radius * math.sin(th0),
                    cz + self.height,
                ],
                dtype=np.float64,
            )
            p1_top = np.array(
                [
                    cx + self.radius * math.cos(th1),
                    cy + self.radius * math.sin(th1),
                    cz + self.height,
                ],
                dtype=np.float64,
            )
            p0_bot = np.array(
                [cx + self.radius * math.cos(th0), cy + self.radius * math.sin(th0), cz],
                dtype=np.float64,
            )
            p1_bot = np.array(
                [cx + self.radius * math.cos(th1), cy + self.radius * math.sin(th1), cz],
                dtype=np.float64,
            )

            mid_th = 0.5 * (th0 + th1)
            norm = np.array([math.cos(mid_th), math.sin(mid_th), 0.0], dtype=np.float64)

            result.append(
                Face(
                    vertices=np.array([p0_bot, p1_bot, p1_top, p0_top], dtype=np.float64),
                    normal=norm,
                    color_token="node_idle",
                    layer=self.layer,
                    id=f"{self.id}:disk_side:{i}",
                )
            )

        # 3. Brazo y cabezal mecánico móvil (sobre la tapa superior)
        r_head = self.radius * (0.2 + 0.7 * float(np.clip(self.head_track_normalized, 0.0, 1.0)))
        hx = cx + r_head * math.cos(self.head_angle_rad)
        hy = cy + r_head * math.sin(self.head_angle_rad)
        hz = cz + self.height + 2.0

        arm_p0 = np.array(
            [
                cx + (self.radius + 15.0) * math.cos(self.head_angle_rad),
                cy + (self.radius + 15.0) * math.sin(self.head_angle_rad),
                hz,
            ],
            dtype=np.float64,
        )
        arm_p1 = np.array([hx, hy, hz], dtype=np.float64)
        head_box = _make_box_faces(
            base_id=f"{self.id}:head",
            x=hx - 3.0,
            y=hy - 3.0,
            z=hz,
            w=6.0,
            d=6.0,
            h=4.0,
            color_token="alert",
            layer=self.layer + 5,
        )
        result.extend(head_box)

        # Linea/brazo del cabezal
        norm_arm = np.array(
            [-math.sin(self.head_angle_rad), math.cos(self.head_angle_rad), 0.0], dtype=np.float64
        )
        result.append(
            Face(
                vertices=np.array(
                    [arm_p0, arm_p1, arm_p1 + np.array([0, 0, 2]), arm_p0 + np.array([0, 0, 2])],
                    dtype=np.float64,
                ),
                normal=norm_arm,
                color_token="text_secondary",
                layer=self.layer + 4,
                id=f"{self.id}:arm",
            )
        )

        return result


# -----------------------------------------------------------------------------
# 4. NetworkPipes (FR-13, FR-14)
# -----------------------------------------------------------------------------


@dataclass
class NetworkPipes:
    """Tuberias ortogonales de red que canalizan paquetes fisicos a lo largo de buses."""

    id: str
    points: list[tuple[float, float, float]]  # Polilinea 3D de ruta Manhattan
    width: float = 6.0
    color_token: str = "bus"
    packets: list[float] = field(default_factory=list)  # Posicion normalizada s in [0.0, 1.0]
    packet_color: str = "mem"
    layer: int = LAYER_BUS

    def faces(self, view_state: Any = None) -> list[Face]:
        if len(self.points) < 2:
            return []

        result: list[Face] = []
        half_w = self.width * 0.5

        # Tramos ortogonales planos
        for i in range(len(self.points) - 1):
            p0 = np.array(self.points[i], dtype=np.float64)
            p1 = np.array(self.points[i + 1], dtype=np.float64)
            diff = p1 - p0
            length = float(np.linalg.norm(diff))
            if length < 1e-4:
                continue
            dir_vec = diff / length

            # Perpendicular horizontal
            perp = np.array([-dir_vec[1], dir_vec[0], 0.0], dtype=np.float64)
            if np.linalg.norm(perp) < 1e-6:
                perp = np.array([1.0, 0.0, 0.0], dtype=np.float64)
            else:
                perp = perp / np.linalg.norm(perp)

            v0 = p0 - perp * half_w
            v1 = p0 + perp * half_w
            v2 = p1 + perp * half_w
            v3 = p1 - perp * half_w

            result.append(
                Face(
                    vertices=np.array([v0, v1, v2, v3], dtype=np.float64),
                    normal=np.array([0.0, 0.0, 1.0], dtype=np.float64),
                    color_token=self.color_token,
                    layer=self.layer,
                    id=f"{self.id}:seg:{i}",
                )
            )

        # Paquetes en transito
        total_len = 0.0
        segment_lens: list[float] = []
        for i in range(len(self.points) - 1):
            d = float(np.linalg.norm(np.array(self.points[i + 1]) - np.array(self.points[i])))
            segment_lens.append(d)
            total_len += d

        if total_len > 0.0:
            for p_idx, s in enumerate(self.packets):
                target_dist = float(np.clip(s, 0.0, 1.0)) * total_len
                curr = 0.0
                pkt_pos = np.array(self.points[-1], dtype=np.float64)
                for seg_i, seg_l in enumerate(segment_lens):
                    if curr + seg_l >= target_dist:
                        local_frac = (target_dist - curr) / max(1e-6, seg_l)
                        sp0 = np.array(self.points[seg_i], dtype=np.float64)
                        sp1 = np.array(self.points[seg_i + 1], dtype=np.float64)
                        pkt_pos = sp0 + local_frac * (sp1 - sp0)
                        break
                    curr += seg_l

                # Caja del paquete
                sz = self.width * 1.2
                result.extend(
                    _make_box_faces(
                        base_id=f"{self.id}:pkt:{p_idx}",
                        x=pkt_pos[0] - sz * 0.5,
                        y=pkt_pos[1] - sz * 0.5,
                        z=pkt_pos[2] + 1.0,
                        w=sz,
                        d=sz,
                        h=sz,
                        color_token=self.packet_color,
                        layer=self.layer + 5,
                    )
                )

        return result


# -----------------------------------------------------------------------------
# 5. MemoryBlock (FR-13, C-05 resuelta)
# -----------------------------------------------------------------------------


@dataclass
class MemoryBlock:
    """Bloque de memoria volátil (MemTable / RAM) con llenado secuencial verde esmeralda."""

    id: str
    pos: tuple[float, float, float] = (0.0, 0.0, 0.0)
    width: float = 70.0
    depth: float = 50.0
    height: float = 90.0
    fill_level: float = 0.0  # 0.0 a 1.0 (memtable_bytes / capacity)
    grid_cols: int = 4
    grid_rows: int = 6
    layer: int = LAYER_BODY
    decal: DecalSpec | None = None

    def faces(self, view_state: Any = None) -> list[Face]:
        x, y, z = self.pos
        result: list[Face] = []

        # Chasis base / zócalo
        result.extend(
            _make_box_faces(
                base_id=self.id,
                x=x,
                y=y,
                z=z,
                w=self.width,
                d=self.depth,
                h=self.height,
                color_token="node_idle",
                layer=self.layer,
                decal_front=self.decal,
            )
        )

        # Celdas de memoria en la cara frontal
        n_cells = self.grid_cols * self.grid_rows
        active_cells = round(float(np.clip(self.fill_level, 0.0, 1.0)) * n_cells)

        cell_margin = 3.0
        avail_w = self.width - 2.0 * 6.0
        avail_h = self.height - 2.0 * 8.0
        cell_w = (avail_w - (self.grid_cols - 1) * cell_margin) / self.grid_cols
        cell_h = (avail_h - (self.grid_rows - 1) * cell_margin) / self.grid_rows

        cell_idx = 0
        for r in range(self.grid_rows):
            for c in range(self.grid_cols):
                cx = x + 6.0 + c * (cell_w + cell_margin)
                cz = z + 8.0 + r * (cell_h + cell_margin)
                is_lit = cell_idx < active_cells
                color = "mem" if is_lit else "wireframe"

                # Cara planar frontal de celda
                cp0 = np.array([cx, y - 0.5, cz], dtype=np.float64)
                cp1 = np.array([cx + cell_w, y - 0.5, cz], dtype=np.float64)
                cp2 = np.array([cx + cell_w, y - 0.5, cz + cell_h], dtype=np.float64)
                cp3 = np.array([cx, y - 0.5, cz + cell_h], dtype=np.float64)

                result.append(
                    Face(
                        vertices=np.array([cp0, cp1, cp2, cp3], dtype=np.float64),
                        normal=np.array([0.0, -1.0, 0.0], dtype=np.float64),
                        color_token=color,
                        layer=self.layer + 2,
                        id=f"{self.id}:cell:{cell_idx}",
                    )
                )
                cell_idx += 1

        return result
