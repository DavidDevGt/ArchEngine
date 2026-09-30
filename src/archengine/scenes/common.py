"""Helpers de escena (packets_on, animadores de camara) (PDR §3, C-04).

Provee la interfaz declarativa para composicion de escenas, interpolacion de
posiciones de paquetes de red sobre buses y animadores parametricos de camara.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from archengine.pipeline.preview import (
    Scene,
    build_default_camera_track,
)


def interpolate_arc_position(
    polyline: Sequence[tuple[float, float, float]],
    progress: float,
) -> tuple[float, float, float]:
    """Calcula la coordenada 3D exacta a lo largo de una polilinea segun el progreso [0.0, 1.0]."""
    if not polyline:
        return (0.0, 0.0, 0.0)
    if len(polyline) == 1:
        return polyline[0]

    s = float(np.clip(progress, 0.0, 1.0))
    dists: list[float] = []
    total_len = 0.0

    for i in range(len(polyline) - 1):
        p0 = np.array(polyline[i], dtype=np.float64)
        p1 = np.array(polyline[i + 1], dtype=np.float64)
        d = float(np.linalg.norm(p1 - p0))
        dists.append(d)
        total_len += d

    if total_len <= 1e-6:
        return polyline[0]

    target = s * total_len
    curr = 0.0

    for i, d in enumerate(dists):
        if curr + d >= target:
            seg_s = (target - curr) / max(1e-6, d)
            p0 = np.array(polyline[i], dtype=np.float64)
            p1 = np.array(polyline[i + 1], dtype=np.float64)
            res = p0 + seg_s * (p1 - p0)
            return (float(res[0]), float(res[1]), float(res[2]))
        curr += d

    return polyline[-1]


def packets_on(
    channel_path: Sequence[tuple[float, float, float]],
    packet_progresses: Sequence[float],
) -> list[tuple[float, float, float]]:
    """Helper de escena (C-04): interpola las posiciones espaciales de los paquetes en vuelo."""
    return [interpolate_arc_position(channel_path, s) for s in packet_progresses]


__all__ = [
    "Scene",
    "build_default_camera_track",
    "interpolate_arc_position",
    "packets_on",
]
