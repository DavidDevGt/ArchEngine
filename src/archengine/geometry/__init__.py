"""Modulo de geometria procedural y diseno de topologia.

Primitivas geometricas volumetricas y enrutamiento ortogonal Manhattan.
"""

from archengine.geometry.primitives import (
    LAYER_BACKGROUND,
    LAYER_BODY,
    LAYER_BUS,
    LAYER_DECAL,
    LAYER_FLOOR,
    LAYER_HUD,
    LAYER_LED,
    CircularQueue,
    DecalSpec,
    Face,
    MemoryBlock,
    NetworkPipes,
    Primitive,
    ServerRack,
    StorageCylinder,
)
from archengine.geometry.topology_layout import (
    compute_topology_layout,
    is_segment_axial,
    route_manhattan,
)

__all__ = [
    "LAYER_BACKGROUND",
    "LAYER_BODY",
    "LAYER_BUS",
    "LAYER_DECAL",
    "LAYER_FLOOR",
    "LAYER_HUD",
    "LAYER_LED",
    "CircularQueue",
    "DecalSpec",
    "Face",
    "MemoryBlock",
    "NetworkPipes",
    "Primitive",
    "ServerRack",
    "StorageCylinder",
    "compute_topology_layout",
    "is_segment_axial",
    "route_manhattan",
]
