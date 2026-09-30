"""Pruebas unitarias de primitivas geometricas procedurales (FR-13)."""

import numpy as np

from archengine.geometry.primitives import (
    CircularQueue,
    MemoryBlock,
    NetworkPipes,
    ServerRack,
    StorageCylinder,
)


def test_server_rack_faces() -> None:
    rack = ServerRack(
        id="rack_1",
        pos=(0.0, 0.0, 0.0),
        num_blades=4,
        blade_states=["active", "idle", "alert", "idle"],
    )
    faces = rack.faces()
    assert len(faces) > 6  # Chasis + blades + leds

    # Verificar normales unitarias
    for f in faces:
        norm = np.linalg.norm(f.normal)
        assert abs(norm - 1.0) < 1e-4


def test_circular_queue_faces() -> None:
    cq = CircularQueue(
        id="queue_1",
        center=(0.0, 0.0, 0.0),
        capacity=8,
        head=2,
        tail=5,
    )
    faces = cq.faces()
    assert len(faces) >= 16  # Sectores superiores y laterales


def test_storage_cylinder_faces_and_head() -> None:
    disk = StorageCylinder(
        id="disk_1",
        center=(0.0, 0.0, 0.0),
        radius=50.0,
        num_segments=32,
        head_track_normalized=0.8,
        written_ratio=0.5,
    )
    faces = disk.faces()
    assert len(faces) >= 32 + 32  # Tapa + paredes + brazo
    # Verificar presencia de caras disk y alert (cabezal)
    tokens = {f.color_token for f in faces}
    assert "disk" in tokens
    assert "alert" in tokens


def test_network_pipes_and_packets() -> None:
    points = [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (100.0, 100.0, 0.0)]
    pipe = NetworkPipes(id="pipe_1", points=points, packets=[0.25, 0.75])
    faces = pipe.faces()
    assert len(faces) >= 2  # 2 tramos de tuberia + cajas de paquetes


def test_memory_block_sequential_fill() -> None:
    # Bloque con 24 celdas (4x6)
    mem_empty = MemoryBlock(id="mem_0", fill_level=0.0, grid_cols=4, grid_rows=6)
    mem_half = MemoryBlock(id="mem_1", fill_level=0.5, grid_cols=4, grid_rows=6)
    mem_full = MemoryBlock(id="mem_2", fill_level=1.0, grid_cols=4, grid_rows=6)

    def count_mem_cells(faces: list) -> int:
        return sum(1 for f in faces if f.color_token == "mem")

    assert count_mem_cells(mem_empty.faces()) == 0
    assert count_mem_cells(mem_half.faces()) == 12  # 50% de 24
    assert count_mem_cells(mem_full.faces()) == 24  # 100% de 24
