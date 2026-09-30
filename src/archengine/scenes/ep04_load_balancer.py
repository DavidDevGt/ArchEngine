"""Episodio 04 — «Load balancer: round robin vs least connections y failover» (docs/13).

Tres backends heterogeneos (A y B rapidos, C 3x mas lento) detras de un balanceador. El guion solo
programa el cambio de algoritmo y la caida/recuperacion de B; el reparto, las colas, los timeouts
y el tiempo de deteccion emergen de la simulacion. Video y simulacion van en tiempo real.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import skia  # type: ignore[import-not-found]

from archengine import __version__
from archengine.audio.sonification import SoundEvents
from archengine.core.timebase import TimeMap
from archengine.geometry.primitives import (
    LAYER_FLOOR,
    Face,
    NetworkPipes,
    ServerRack,
    _make_box_faces,
)
from archengine.pipeline.preview import Scene
from archengine.render.core import CameraKeyframe, CameraTrack
from archengine.scenes import hud
from archengine.scenes.hud import S
from archengine.simulation.balancing import Backend, LbParams, LoadBalancer
from archengine.simulation.engine import Simulation
from archengine.simulation.trace import Trace
from archengine.simulation.workload import Workload, poisson_arrivals

# --- parametros del episodio ----------------------------------------------------------------------
RATE = 28.0  # peticiones/s (Poisson)
DURATION_S = 60.0
PARAMS = LbParams(
    service_us=(40_000, 40_000, 120_000),
    algo="rr",
    health_interval_us=500_000,
    fail_threshold=3,
    rise_threshold=2,
    timeout_us=1_000_000,
    end_us=int(DURATION_S * S),
)
NAMES = ("A", "B", "C")
LC_AT_US = 10 * S  # round robin -> least connections
CRASH_AT_US = 26 * S  # cae el backend B (indice 1)
RECOVER_AT_US = 40 * S
CRASHED = 1

SEGMENTS: tuple[hud.Segment, ...] = (
    (0, 10, "ROUND ROBIN · REPARTO IGUAL, NODO C LENTO", "warn"),
    (10, 26, "LEAST CONNECTIONS · REPARTO SEGÚN CARGA", "mem"),
    (26, 40, "NODO B CAE · HEALTH CHECKS Y FAILOVER", "alert"),
    (40, 52, "B VUELVE · REINGRESA TRAS 2 CHEQUEOS", "bus"),
    (52, 60, "BALANCE DE INGENIERÍA", "text_primary"),
)


# =============================================================================
# Simulacion
# =============================================================================


@dataclass
class EpisodeSim:
    trace: Trace
    tmap: TimeMap
    trace_hash: str
    route_v: tuple[np.ndarray, ...]  # instantes de video de cada peticion, por backend
    spark_x: np.ndarray
    spark_y: np.ndarray
    crash_us: int
    mark_down_us: int
    mark_up_us: int


def _simulate(seed: int) -> Trace:
    n = int(RATE * DURATION_S * 1.2)
    sim = Simulation(seed)
    sim.add(LoadBalancer(PARAMS))
    for i, svc in enumerate(PARAMS.service_us):
        sim.add(Backend(i, svc))
    arrivals = poisson_arrivals(n, RATE, seed, "lb.arrivals")
    w = Workload("lb", arrivals, np.zeros(n, dtype=np.int64), comp_id="client", tick_every=10**9)
    sim.add(w)
    sim.schedule_at(w.first_us, w.id, "next")
    sim.schedule_at(0, "lb", "health")
    sim.schedule_at(LC_AT_US, "lb", "set_algo", algo="lc")
    sim.schedule_at(CRASH_AT_US, f"b{CRASHED}", "crash")
    sim.schedule_at(RECOVER_AT_US, f"b{CRASHED}", "recover")
    sim.run_until(int(DURATION_S * S))
    return sim.trace


def val(tr: Trace, key: str, t_us: int, default: int = 0) -> int:
    """``value_at`` con valor por defecto explicito (``state_at`` daria 0 antes del 1er cambio)."""
    return tr.value_at(key, t_us, default)


def window_latency_ms(tr: Trace, t_us: int, win_us: int) -> float:
    a = max(0, t_us - win_us)
    d = val(tr, "lb.done", t_us) - val(tr, "lb.done", a)
    lat = val(tr, "lb.lat_sum_us", t_us) - val(tr, "lb.lat_sum_us", a)
    return lat / d / 1000.0 if d else 0.0


_SIM_CACHE: dict[int, EpisodeSim] = {}


def get_episode_sim(seed: int = 42) -> EpisodeSim:
    if seed in _SIM_CACHE:
        return _SIM_CACHE[seed]
    tr = _simulate(seed)
    tmap = TimeMap([(0, 0), (int(DURATION_S * S), int(DURATION_S * S))])
    routes = tr.events(["lb.route"])
    route_v = tuple(
        hud.video_times(tmap, routes.t_us[routes.a == i]) for i in range(len(PARAMS.service_us))
    )
    xs = np.arange(0.0, DURATION_S + 0.25, 0.25)
    ys = np.asarray([window_latency_ms(tr, int(x * S), 2 * S) for x in xs])
    down = tr.events(["lb.mark_down"])
    up = tr.events(["lb.mark_up"])
    crash = tr.first("node.crash")
    if crash is None or not len(down) or not len(up):
        raise RuntimeError("La simulacion no produjo caida/deteccion/reingreso del nodo")
    th = hashlib.sha256((__version__ + tr.trace_hash()).encode()).hexdigest()
    sim = EpisodeSim(
        tr, tmap, f"sha256:{th}", route_v, xs, ys, crash, int(down.t_us[0]), int(up.t_us[0])
    )
    _SIM_CACHE[seed] = sim
    return sim


@dataclass(frozen=True)
class Metrics:
    p95_rr_ms: float
    p95_lc_ms: float
    errors_rr: int
    errors_lc: int
    errors_failover: int
    detect_s: float
    rejoin_s: float


def _p95_ms(tr: Trace, lo: int, hi: int) -> float:
    ev = tr.events(["req.done"])
    m = (ev.t_us >= lo) & (ev.t_us < hi)
    return float(np.percentile(ev.a[m], 95)) / 1000.0 if m.any() else 0.0


def _errors(tr: Trace, lo: int, hi: int) -> int:
    ev = tr.events(["req.error"])
    return int(((ev.t_us >= lo) & (ev.t_us < hi)).sum())


def metrics(sim: EpisodeSim) -> Metrics:
    tr = sim.trace
    return Metrics(
        p95_rr_ms=_p95_ms(tr, 2 * S, LC_AT_US),
        p95_lc_ms=_p95_ms(tr, LC_AT_US + 4 * S, CRASH_AT_US),
        errors_rr=_errors(tr, 0, LC_AT_US + 2 * S),  # incluye el vaciado del backlog de C
        errors_lc=_errors(tr, LC_AT_US + 4 * S, CRASH_AT_US),
        errors_failover=_errors(tr, CRASH_AT_US, RECOVER_AT_US),
        detect_s=(sim.mark_down_us - sim.crash_us) / S,
        rejoin_s=(sim.mark_up_us - RECOVER_AT_US) / S,
    )


# =============================================================================
# Geometria
# =============================================================================

# Backends en linea a lo largo de la diagonal de pantalla (mismo x - y) y el balanceador detras,
# de modo que los buses corran por el suelo sin quedar tapados por ningun cuerpo.
LB = (-105.0, 115.0)
BACKS = ((-110.0, -70.0), (-30.0, 10.0), (50.0, 90.0))  # esquina (x, y) de los racks A, B, C


def _floor(pid: str, cx: float, cy: float, w: float, d: float) -> list[Face]:
    return _make_box_faces(pid, cx - w / 2, cy - d / 2, -6.0, w, d, 6.0, "grid_line", LAYER_FLOOR)


PIPES = (
    [(-80.0, 114.0, 18.0), (-80.0, -25.0, 18.0)],
    [(-60.0, 114.0, 18.0), (-60.0, 32.0, 18.0), (-30.0, 32.0, 18.0)],
    [(-45.0, 125.0, 18.0), (50.0, 125.0, 18.0)],
)


def compose_faces(sim: EpisodeSim, t_us: int) -> list[Face]:
    tr = sim.trace
    t_sim = sim.tmap.sim_at(t_us)
    win = 450_000
    faces: list[Face] = _floor("floor", -30, 40, 300, 280)
    faces += ServerRack(
        id="lb",
        pos=(LB[0], LB[1], 0.0),
        width=60,
        depth=45,
        height=110,
        num_blades=4,
        blade_states=["active", "active", "active", "active"],
    ).faces()
    for i, (bx, by) in enumerate(BACKS):
        up = val(tr, f"b{i}.up", t_sim, 1) == 1
        healthy = val(tr, f"lb.healthy{i}", t_sim, 1) == 1
        conns = val(tr, f"b{i}.conns", t_sim)
        faces += ServerRack(
            id=f"b{i}",
            pos=(bx, by, 0.0),
            width=60,
            depth=45,
            height=70,
            num_blades=3,
            blade_states=["idle"] * 3 if not up else (["active"] * 3 if conns else ["idle"] * 3),
            is_crashed=not up,
        ).faces()
        # barra de conexiones en curso delante del backend (largo proporcional, tope 14)
        n = min(14, val(tr, f"lb.conns{i}", t_sim))
        if n:
            tok = "alert" if n >= 9 else ("warn" if n >= 5 else "mem")
            faces += _make_box_faces(
                f"conns{i}", bx - 10.0, by - 26.0, 0.0, 6.0 * n, 10.0, 8.0, tok
            )
        faces += NetworkPipes(
            id=f"pipe{i}",
            points=PIPES[i],
            width=5,
            color_token="bus" if healthy else "wireframe",
            packets=hud.recent_progress(sim.route_v[i], t_us, win, 3),
            packet_color="mem" if up else "alert",
        ).faces()
    return faces


def camera_track() -> CameraTrack:
    kf = CameraKeyframe
    tgt = (-30.0, 40.0, 10.0)
    return CameraTrack(
        [
            kf(0, 45.0, 35.264, 2.3, tgt),
            kf(26 * S, 45.0, 36.0, 2.4, tgt),
            kf(40 * S, 42.0, 35.264, 2.4, tgt),
            kf(52 * S, 45.0, 35.264, 2.3, tgt),
            kf(60 * S, 45.0, 35.264, 2.3, tgt),
        ]
    )


# =============================================================================
# HUD
# =============================================================================


def make_overlay(sim: EpisodeSim, track: CameraTrack):  # type: ignore[no-untyped-def]
    m = metrics(sim)
    tr = sim.trace

    def overlay(c: skia.Canvas, w: int, h: int, t_us: int) -> None:
        k = w / 1080.0
        c.save()
        c.scale(k, k)
        ts = t_us / S
        t_sim = sim.tmap.sim_at(t_us)
        cam = track.camera_at(t_us, 1080, 1920)
        algo_lc = val(tr, "lb.algo", t_sim) == 1

        hud.header(c, "LOAD BALANCER", "reparto, health checks y failover", SEGMENTS, ts)
        hud.label3d(c, cam, (LB[0] + 30, LB[1] + 22, 128.0), "BALANCEADOR", 24, "bus")
        for i, (bx, by) in enumerate(BACKS):
            up = val(tr, f"b{i}.up", t_sim, 1) == 1
            hud.label3d(
                c,
                cam,
                (bx + 30, by + 22, 88.0),
                f"BACKEND {NAMES[i]}",
                22,
                "text_primary" if up else "alert",
            )

        lat = window_latency_ms(tr, t_sim, 2 * S)
        hud.sparkline(
            c,
            60,
            300,
            960,
            230,
            sim.spark_x,
            sim.spark_y,
            ts,
            DURATION_S,
            500.0,
            "alert" if lat > 250 else ("warn" if lat > 120 else "mem"),
            "latencia media (ventana 2 s)",
            f"{hud.fmt(lat, 0)} ms",
        )

        errors = val(tr, "lb.errors", t_sim)
        healthy_n = sum(val(tr, f"lb.healthy{i}", t_sim, 1) for i in range(3))
        hud.card(
            c,
            40,
            1530,
            500,
            330,
            "Balanceador",
            "bus",
            [
                ("algoritmo", "LEAST CONN" if algo_lc else "ROUND ROBIN"),
                ("tráfico", f"{hud.fmt(RATE, 0)} req/s"),
                ("peticiones fallidas", hud.fmt(errors)),
                ("nodos en el pool", f"{healthy_n} / 3"),
            ],
            state_txt="DEGRADADO" if healthy_n < 3 else "OK",
            state_token="warn" if healthy_n < 3 else "led_active",
        )
        rows = []
        for i, nm in enumerate(NAMES):
            up = val(tr, f"b{i}.up", t_sim, 1) == 1
            healthy = val(tr, f"lb.healthy{i}", t_sim, 1) == 1
            state = {(True, True): "OK", (True, False): "REINGRESA", (False, True): "MUERTO ?"}.get(
                (up, healthy), "FUERA"
            )
            rows.append(
                (
                    f"{nm} · {PARAMS.service_us[i] // 1000} ms",
                    f"{val(tr, f'lb.conns{i}', t_sim)} · {state}",
                )
            )
        rows.append(("conn = peticiones en curso", ""))
        hud.card(c, 540, 1530, 500, 330, "Backends", "disk", rows)

        if 0 <= t_us - sim.crash_us < 2 * S and t_us >= sim.crash_us:
            hud.rect(c, 210, 1290, 660, 110, "alert", 0.9)
            hud.text(c, "BACKEND B CAÍDO", 540, 1363, 44, "text_primary", "center")
        elif sim.crash_us <= t_us < sim.mark_down_us:
            hud.rect(c, 210, 1290, 660, 110, "warn", 0.9)
            hud.text(c, "AÚN EN ROTACIÓN · PIERDE PETICIONES", 540, 1357, 28, "bg", "center")
        elif sim.mark_down_us <= t_us < sim.mark_down_us + 2 * S:
            hud.rect(c, 210, 1290, 660, 110, "bus", 0.9)
            hud.text(c, "FAILOVER · B FUERA DEL POOL", 540, 1357, 32, "text_primary", "center")
        elif sim.mark_up_us <= t_us < sim.mark_up_us + 2 * S:
            hud.rect(c, 210, 1290, 660, 110, "mem", 0.9)
            hud.text(c, "B REINGRESA AL POOL", 540, 1357, 36, "bg", "center")
        if ts >= 52:
            _balance(c, m, min(1.0, (ts - 52) / 1.2))
        c.restore()

    return overlay


def _balance(c: skia.Canvas, m: Metrics, a: float) -> None:
    hud.rect(c, 0, 300, 1080, 1180, "bg", 1.0, 0)
    hud.text(c, "Latencia p95 por algoritmo", 100, 390, 36, "text_primary", alpha=a)
    hud.text(
        c,
        "backends A y B rápidos, C 3x más lento · 28 req/s",
        100,
        432,
        24,
        "text_secondary",
        alpha=a,
    )
    hud.bars(
        c,
        100,
        470,
        [
            ("ROUND ROBIN", m.p95_rr_ms, "warn", f"{hud.fmt(m.p95_rr_ms, 0)} ms"),
            ("LEAST CONN", m.p95_lc_ms, "mem", f"{hud.fmt(m.p95_lc_ms, 0)} ms"),
        ],
        a,
        bar_w=400,
        v_max=max(m.p95_rr_ms, m.p95_lc_ms),
    )
    hud.text(
        c,
        f"{hud.fmt(m.p95_rr_ms / max(1e-9, m.p95_lc_ms), 1)}x menos latencia p95 "
        "con least connections",
        540,
        740,
        30,
        "mem",
        "center",
        a,
    )
    hud.text(c, "Peticiones fallidas", 100, 830, 36, "text_primary", alpha=a)
    hud.text(
        c, "timeouts de 1 s · RR incluye el backlog de C", 100, 872, 24, "text_secondary", alpha=a
    )
    hud.bars(
        c,
        100,
        910,
        [
            ("RR", float(m.errors_rr), "warn", f"{hud.fmt(m.errors_rr)}"),
            ("LC", float(m.errors_lc), "mem", f"{hud.fmt(m.errors_lc)}"),
            ("Caída B", float(m.errors_failover), "alert", f"{hud.fmt(m.errors_failover)}"),
        ],
        a,
        bar_w=400,
        row_h=90,
        v_max=float(max(1, m.errors_rr, m.errors_failover)),
    )
    hud.text(
        c,
        f"El health check tardó {hud.fmt(m.detect_s, 1)} s en sacar a B; "
        f"reingresó en {hud.fmt(m.rejoin_s, 1)} s.",
        540,
        1240,
        24,
        "text_primary",
        "center",
        a,
    )
    hud.text(
        c,
        "Sin health checks el balanceador seguiría enviando tráfico a un nodo muerto.",
        540,
        1290,
        22,
        "text_secondary",
        "center",
        a,
    )
    hud.text(
        c,
        "Menos nodos = más carga por nodo: el failover cuesta capacidad.",
        540,
        1336,
        22,
        "text_secondary",
        "center",
        a,
    )


# =============================================================================
# Audio
# =============================================================================


def sound_events(sim: EpisodeSim) -> SoundEvents:
    z = np.zeros(1, dtype=np.int64)
    by: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}

    def take(kind: str, out: str, lo_s: float, hi_s: float) -> None:
        ev = sim.trace.events([kind])
        v = sim.tmap.video_at(ev.t_us)
        m = (v >= int(lo_s * S)) & (v < int(hi_s * S))
        by[out] = (v[m], ev.a[m], ev.b[m])

    take("lb.route", "lb.route", 0, 52)
    take("req.error", "req.error", 0, 52)
    take("node.crash", "sys.alert", 0, 52)
    take("lb.mark_up", "sys.recover", 0, 52)
    by["arch.end"] = (np.asarray([52 * S], dtype=np.int64), z.copy(), z.copy())
    return SoundEvents(by)


# =============================================================================
# Punto de entrada
# =============================================================================


def build(seed: int = 42) -> Scene:
    sim = get_episode_sim(seed)
    track = camera_track()
    return Scene(
        id="ep04_load_balancer",
        video_width=1080,
        video_height=1920,
        fps=30,
        duration_s=DURATION_S,
        seed=seed,
        camera_track=track,
        compose_fn=lambda t_us: compose_faces(sim, t_us),
        overlay_fn=make_overlay(sim, track),
        audio_fn=lambda: sound_events(sim),
        traces_fn=lambda: {"lb": sim.trace},
        input_files=[Path(__file__)],
    )
