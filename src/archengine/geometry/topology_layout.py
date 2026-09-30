"""Enrutamiento ortogonal estilo Manhattan para buses de topologia (FR-14, docs/03 §8).

Conecta nodos en la escena utilizando exclusivamente segmentos axiales ortogonales,
minimizando giros y cruces mediante una busqueda A* sobre rejilla con penalizaciones
de giro y desempate determinista por ID.
"""

from __future__ import annotations

import heapq
from collections.abc import Sequence
from dataclasses import dataclass

# Penalizaciones del algoritmo A* Manhattan
_LENGTH_COST: float = 1.0
_TURN_PENALTY: float = 15.0
_CROSSING_PENALTY: float = 40.0


@dataclass(frozen=True)
class RouteSegment:
    start: tuple[float, float, float]
    end: tuple[float, float, float]


def is_segment_axial(
    p0: tuple[float, float, float], p1: tuple[float, float, float], tol: float = 1e-4
) -> bool:
    """Verifica si un segmento es estrictamente axial (al menos dos ejes son identicos)."""
    dx = abs(p1[0] - p0[0]) > tol
    dy = abs(p1[1] - p0[1]) > tol
    dz = abs(p1[2] - p0[2]) > tol
    # Es axial si como maximo una dimension varia significativamente
    return (int(dx) + int(dy) + int(dz)) <= 1


def route_manhattan(
    start: tuple[float, float, float],
    goal: tuple[float, float, float],
    grid_step: float = 10.0,
    obstacles: set[tuple[int, int]] | None = None,
    occupied_segments: set[tuple[tuple[int, int], tuple[int, int]]] | None = None,
) -> list[tuple[float, float, float]]:
    """Encuentra una polilinea ortogonal axial A* entre start y goal en plano XY.

    Mantiene z constante o interpola linealmente en el eje Z si difieren.
    """
    sx, sy, sz = start
    gx, gy, gz = goal

    # Discretizar a celdas de rejilla
    start_cell = (round(sx / grid_step), round(sy / grid_step))
    goal_cell = (round(gx / grid_step), round(gy / grid_step))

    if start_cell == goal_cell:
        return [start, goal]

    obs = obstacles or set()
    occ_segs = occupied_segments or set()

    # Priority queue: (f_score, counter, current_cell, current_direction)
    # Direction: 0=(1,0), 1=(0,1), 2=(-1,0), 3=(0,-1), -1=none
    directions: list[tuple[int, int]] = [(1, 0), (0, 1), (-1, 0), (0, -1)]

    counter = 0
    # (cost, counter, cell, dir_idx)
    open_set: list[tuple[float, int, tuple[int, int], int]] = []
    h_start = (abs(start_cell[0] - goal_cell[0]) + abs(start_cell[1] - goal_cell[1])) * _LENGTH_COST
    heapq.heappush(open_set, (h_start, counter, start_cell, -1))

    came_from: dict[tuple[tuple[int, int], int], tuple[tuple[int, int], int]] = {}
    g_score: dict[tuple[tuple[int, int], int], float] = {(start_cell, -1): 0.0}

    best_end_state: tuple[tuple[int, int], int] | None = None
    min_dist_to_goal = float("inf")
    fallback_state: tuple[tuple[int, int], int] = (start_cell, -1)

    max_steps = 4000
    steps = 0

    while open_set and steps < max_steps:
        steps += 1
        _, _, current, cur_dir = heapq.heappop(open_set)

        if current == goal_cell:
            best_end_state = (current, cur_dir)
            break

        dist_g = abs(current[0] - goal_cell[0]) + abs(current[1] - goal_cell[1])
        if dist_g < min_dist_to_goal:
            min_dist_to_goal = dist_g
            fallback_state = (current, cur_dir)

        cur_g = g_score.get((current, cur_dir), float("inf"))

        for d_idx, (dx, dy) in enumerate(directions):
            nxt = (current[0] + dx, current[1] + dy)
            # Evitar obstaculos salvo si es el destino final
            if nxt in obs and nxt != goal_cell:
                continue

            # Calcular coste de transicion
            step_cost = _LENGTH_COST
            if cur_dir != -1 and cur_dir != d_idx:
                step_cost += _TURN_PENALTY

            seg = (min(current, nxt), max(current, nxt))
            if seg in occ_segs:
                step_cost += _CROSSING_PENALTY

            new_g = cur_g + step_cost
            state = (nxt, d_idx)

            if new_g < g_score.get(state, float("inf")):
                g_score[state] = new_g
                h = (abs(nxt[0] - goal_cell[0]) + abs(nxt[1] - goal_cell[1])) * _LENGTH_COST
                counter += 1
                came_from[state] = (current, cur_dir)
                heapq.heappush(open_set, (new_g + h, counter, nxt, d_idx))

    if best_end_state is None:
        best_end_state = fallback_state

    # Reconstruir camino de celdas
    path_cells: list[tuple[int, int]] = []
    curr = best_end_state
    while curr in came_from:
        path_cells.append(curr[0])
        curr = came_from[curr]
    path_cells.append(start_cell)
    path_cells.reverse()

    # Si fallback no llego exacto, agregar goal_cell
    if path_cells[-1] != goal_cell:
        path_cells.append(goal_cell)

    # Simplificar segmentos colineales (eliminar puntos intermedios en lineas rectas)
    points_2d: list[tuple[float, float]] = [(sx, sy)]
    if len(path_cells) > 1:
        # Convertir a coordenadas reales
        raw_pts = [(c[0] * grid_step, c[1] * grid_step) for c in path_cells]
        raw_pts[0] = (sx, sy)
        raw_pts[-1] = (gx, gy)

        simplified: list[tuple[float, float]] = [raw_pts[0]]
        for i in range(1, len(raw_pts) - 1):
            p_prev = simplified[-1]
            p_curr = raw_pts[i]
            p_next = raw_pts[i + 1]

            # Verificar si p_curr es colineal con prev y next
            dx1 = p_curr[0] - p_prev[0]
            dy1 = p_curr[1] - p_prev[1]
            dx2 = p_next[0] - p_curr[0]
            dy2 = p_next[1] - p_curr[1]

            if (abs(dx1) > 1e-4 and abs(dx2) > 1e-4 and abs(dy1) < 1e-4 and abs(dy2) < 1e-4) or (
                abs(dy1) > 1e-4 and abs(dy2) > 1e-4 and abs(dx1) < 1e-4 and abs(dx2) < 1e-4
            ):
                continue
            simplified.append(p_curr)
        simplified.append(raw_pts[-1])
        points_2d = simplified

    # Interpolar Z
    n_pts = len(points_2d)
    result_3d: list[tuple[float, float, float]] = []
    for i, (px, py) in enumerate(points_2d):
        frac = i / max(1, n_pts - 1)
        pz = sz + frac * (gz - sz)
        result_3d.append((px, py, pz))

    return result_3d


def compute_topology_layout(
    nodes: dict[str, tuple[float, float, float]],
    edges: Sequence[tuple[str, str, str]],  # (edge_id, from_id, to_id)
    grid_step: float = 10.0,
    lane_offset: float = 4.0,
) -> dict[str, list[tuple[float, float, float]]]:
    """Calcula rutas ortogonales estilo Manhattan para todas las aristas de la red.

    Garantiza determinismo estricto ordenando por edge_id y asignando carriles
    paralelos si varias aristas comparten nodos.
    """
    sorted_edges = sorted(edges, key=lambda e: e[0])
    occupied_segments: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    routes: dict[str, list[tuple[float, float, float]]] = {}

    # Obstaculos en celdas de nodos
    node_cells: set[tuple[int, int]] = {
        (round(pos[0] / grid_step), round(pos[1] / grid_step)) for pos in nodes.values()
    }

    # Registro de uso entre pares de nodos para offset de carril
    pair_counts: dict[tuple[str, str], int] = {}

    for edge_id, from_id, to_id in sorted_edges:
        if from_id not in nodes or to_id not in nodes:
            continue
        p_from = nodes[from_id]
        p_to = nodes[to_id]

        pair_key = (min(from_id, to_id), max(from_id, to_id))
        lane_idx = pair_counts.get(pair_key, 0)
        pair_counts[pair_key] = lane_idx + 1

        offset = (lane_idx * lane_offset) if lane_idx > 0 else 0.0

        # Obstaculos excluyendo origen y destino
        target_obstacles = set(node_cells)
        target_obstacles.discard((round(p_from[0] / grid_step), round(p_from[1] / grid_step)))
        target_obstacles.discard((round(p_to[0] / grid_step), round(p_to[1] / grid_step)))

        route = route_manhattan(
            start=p_from,
            goal=p_to,
            grid_step=grid_step,
            obstacles=target_obstacles,
            occupied_segments=occupied_segments,
        )

        # Aplicar lane_offset si corresponde
        if offset > 0.0 and len(route) >= 2:
            offset_route: list[tuple[float, float, float]] = []
            for rx, ry, rz in route:
                offset_route.append((rx + offset, ry + offset, rz))
            route = offset_route

        # Registrar segmentos ocupados
        for i in range(len(route) - 1):
            c0 = (round(route[i][0] / grid_step), round(route[i][1] / grid_step))
            c1 = (round(route[i + 1][0] / grid_step), round(route[i + 1][1] / grid_step))
            occupied_segments.add((min(c0, c1), max(c0, c1)))

        routes[edge_id] = route

    return routes
