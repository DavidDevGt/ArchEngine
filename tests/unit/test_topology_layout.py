"""Pruebas unitarias de enrutamiento Manhattan para buses de topologia (FR-14)."""

from archengine.geometry.topology_layout import (
    compute_topology_layout,
    is_segment_axial,
    route_manhattan,
)


def test_route_manhattan_is_strictly_axial() -> None:
    start = (0.0, 0.0, 10.0)
    goal = (150.0, 80.0, 10.0)
    route = route_manhattan(start, goal, grid_step=10.0)

    assert len(route) >= 2
    assert route[0] == start
    assert route[-1] == goal

    # Todos los segmentos deben ser estrictamente axiales
    for i in range(len(route) - 1):
        assert is_segment_axial(route[i], route[i + 1]), (
            f"Segmento no axial: {route[i]} -> {route[i + 1]}"
        )


def test_topology_layout_determinism() -> None:
    nodes = {
        "client": (0.0, 0.0, 0.0),
        "db_lsm": (200.0, 0.0, 0.0),
        "db_btree": (200.0, 100.0, 0.0),
    }
    edges = [
        ("edge_1", "client", "db_lsm"),
        ("edge_2", "client", "db_btree"),
    ]

    routes1 = compute_topology_layout(nodes, edges)
    routes2 = compute_topology_layout(nodes, edges)

    assert routes1.keys() == routes2.keys()
    for k in routes1:
        assert routes1[k] == routes2[k]
