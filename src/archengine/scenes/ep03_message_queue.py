"""Episodio 03 — «Cola de mensajes: backpressure vs. perder mensajes» (docs/13).

Un productor, una cola circular de 16 huecos y un consumidor. El guion solo programa los cambios de
escenario (rafaga, politica de desborde, consumidor lento); perdidas, bloqueos y retardos de cola
emergen de la simulacion. Video y simulacion van en tiempo real (1 s = 1 s).
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
    CircularQueue,
    Face,
    NetworkPipes,
    ServerRack,
    _make_box_faces,
)
from archengine.pipeline.preview import Scene
from archengine.render.core import CameraKeyframe, CameraTrack
from archengine.scenes import hud
from archengine.scenes.hud import S
from archengine.simulation.engine import Simulation
from archengine.simulation.messaging import BoundedQueue, Consumer, Producer, QueueParams
from archengine.simulation.trace import Trace

# --- parametros del episodio ----------------------------------------------------------------------
PARAMS = QueueParams(capacity=16, service_us=100_000, policy="drop")  # consumidor ~10 msg/s
RATE_SCHEDULE = [(0, 6.0), (8 * S, 16.0), (50 * S, 6.0)]  # msgs/s ofrecidos por el productor
BLOCK_AT_US = 22 * S  # la politica pasa de drop a block
SLOW_AT_US = 38 * S  # el consumidor se vuelve 4x mas lento
RECOVER_AT_US = 50 * S
SLOW_FACTOR = 4.0
DURATION_S = 60.0

SEGMENTS: tuple[hud.Segment, ...] = (
    (0, 8, "PRODUCTOR 6/s · CONSUMIDOR 10/s · TODO FLUYE", "mem"),
    (8, 22, "RÁFAGA 16/s · COLA LLENA · SE DESCARTA", "alert"),
    (22, 38, "BACKPRESSURE · EL PRODUCTOR ESPERA", "bus"),
    (38, 50, "CONSUMIDOR LENTO ×4 · LA ESPERA CRECE", "warn"),
    (50, 60, "BALANCE DE INGENIERÍA", "text_primary"),
)
PHASES = {"drop": (8 * S, 22 * S), "block": (22 * S, 38 * S), "slow": (38 * S, 50 * S)}


# =============================================================================
# Simulacion
# =============================================================================


@dataclass
class EpisodeSim:
    trace: Trace
    tmap: TimeMap
    trace_hash: str
    sent_v: np.ndarray  # instantes de video de cada evento relevante
    start_v: np.ndarray
    drop_v: np.ndarray
    spark_x: np.ndarray
    spark_y: np.ndarray


def _simulate(seed: int) -> Trace:
    sim = Simulation(seed)
    q = BoundedQueue(PARAMS)
    sim.add(q)
    sim.add(Consumer(PARAMS, q))
    sim.add(Producer(RATE_SCHEDULE))
    sim.schedule_at(1_000, "producer", "ack")  # arranca el lazo productor
    sim.schedule_at(BLOCK_AT_US, "queue", "set_policy", policy="block")
    sim.schedule_at(SLOW_AT_US, "consumer", "set_factor", factor=SLOW_FACTOR)
    sim.schedule_at(RECOVER_AT_US, "consumer", "set_factor", factor=1.0)
    sim.run_until(int(DURATION_S * S))
    return sim.trace


_SIM_CACHE: dict[int, EpisodeSim] = {}


def get_episode_sim(seed: int = 42) -> EpisodeSim:
    if seed in _SIM_CACHE:
        return _SIM_CACHE[seed]
    tr = _simulate(seed)
    tmap = TimeMap([(0, 0), (int(DURATION_S * S), int(DURATION_S * S))])

    def v(kind: str) -> np.ndarray:
        return hud.video_times(tmap, tr.events([kind]).t_us)

    xs = np.arange(0.0, DURATION_S + 0.1, 0.1)
    ys = np.asarray([tr.value_at("q.depth", int(x * S)) for x in xs], dtype=np.float64)
    th = hashlib.sha256((__version__ + tr.trace_hash()).encode()).hexdigest()
    sim = EpisodeSim(
        tr, tmap, f"sha256:{th}", v("msg.sent"), v("msg.start"), v("queue.drop"), xs, ys
    )
    _SIM_CACHE[seed] = sim
    return sim


@dataclass(frozen=True)
class PhaseStats:
    lost: int
    max_wait_s: float
    offered_per_s: float  # mensajes que el productor logro emitir por segundo
    served_per_s: float


def phase_stats(tr: Trace, lo: int, hi: int) -> PhaseStats:
    span = (hi - lo) / S
    starts = tr.events(["msg.start"])
    m = (starts.t_us >= lo) & (starts.t_us < hi)
    drops = tr.events(["queue.drop"])
    return PhaseStats(
        lost=int(((drops.t_us >= lo) & (drops.t_us < hi)).sum()),
        max_wait_s=float(starts.a[m].max()) / S if m.any() else 0.0,
        offered_per_s=(tr.value_at("producer.sent", hi) - tr.value_at("producer.sent", lo)) / span,
        served_per_s=(tr.value_at("consumer.done", hi) - tr.value_at("consumer.done", lo)) / span,
    )


# =============================================================================
# Geometria
# =============================================================================

PROD = (-190.0, -10.0)
QUEUE_C = (0.0, 25.0)
CONS = (130.0, -10.0)
PIPE_IN = [(-130.0, 12.0, 18.0), (-66.0, 12.0, 18.0)]
PIPE_OUT = [(66.0, 12.0, 18.0), (130.0, 12.0, 18.0)]


def _floor(pid: str, cx: float, cy: float, w: float, d: float) -> list[Face]:
    return _make_box_faces(pid, cx - w / 2, cy - d / 2, -6.0, w, d, 6.0, "grid_line", LAYER_FLOOR)


def compose_faces(sim: EpisodeSim, t_us: int) -> list[Face]:
    tr = sim.trace
    st = tr.state_at(sim.tmap.sim_at(t_us))
    win = 500_000
    depth = st.get("q.depth", 0)
    blocked = st.get("q.policy", 0) == 1 and depth >= PARAMS.capacity
    busy = st.get("consumer.busy", 0) == 1
    slow = st.get("consumer.factor_pct", 100) > 100
    faces: list[Face] = _floor("floor", 0, 20, 440, 170)
    faces += ServerRack(
        id="producer",
        pos=(PROD[0], PROD[1], 0.0),
        width=60,
        depth=45,
        height=110,
        num_blades=4,
        blade_states=["idle"] * 4 if blocked else ["active", "active", "active", "idle"],
    ).faces()
    faces += CircularQueue(
        id="queue",
        center=(QUEUE_C[0], QUEUE_C[1], 0.0),
        capacity=PARAMS.capacity,
        head=st.get("q.deq", 0) % PARAMS.capacity,
        tail=st.get("q.enq", 0) % PARAMS.capacity,
        overflow=depth >= PARAMS.capacity,
    ).faces()
    cons_blades = (
        (["active", "idle", "idle", "idle"] if slow else ["active"] * 3 + ["idle"])
        if busy
        else ["idle"] * 4
    )
    faces += ServerRack(
        id="consumer",
        pos=(CONS[0], CONS[1], 0.0),
        width=60,
        depth=45,
        height=110,
        num_blades=4,
        blade_states=cons_blades,
    ).faces()
    faces += NetworkPipes(
        id="pipe_in",
        points=PIPE_IN,
        width=5,
        packets=hud.recent_progress(sim.sent_v, t_us, win, 4),
        packet_color="mem",
    ).faces()
    faces += NetworkPipes(
        id="pipe_out",
        points=PIPE_OUT,
        width=5,
        packets=hud.recent_progress(sim.start_v, t_us, win, 4),
        packet_color="mem",
    ).faces()
    return faces


def camera_track() -> CameraTrack:
    kf = CameraKeyframe
    tgt = (0.0, 20.0, 10.0)
    return CameraTrack(
        [
            kf(0, 45.0, 35.264, 2.3, tgt),
            kf(22 * S, 45.0, 36.0, 2.4, tgt),
            kf(38 * S, 42.0, 35.264, 2.4, tgt),
            kf(50 * S, 45.0, 35.264, 2.3, tgt),
            kf(60 * S, 45.0, 35.264, 2.3, tgt),
        ]
    )


# =============================================================================
# HUD
# =============================================================================


def _rate_at(t_us: int) -> float:
    return Producer(RATE_SCHEDULE).rate_at(t_us)


def make_overlay(sim: EpisodeSim, track: CameraTrack):  # type: ignore[no-untyped-def]
    stats = {k: phase_stats(sim.trace, *v) for k, v in PHASES.items()}

    def overlay(c: skia.Canvas, w: int, h: int, t_us: int) -> None:
        k = w / 1080.0
        c.save()
        c.scale(k, k)
        ts = t_us / S
        st = sim.trace.state_at(sim.tmap.sim_at(t_us))
        cam = track.camera_at(t_us, 1080, 1920)
        depth = st.get("q.depth", 0)
        policy_block = st.get("q.policy", 0) == 1
        # con BLOCK y la cola llena el productor esta parado (q.blocked parpadea en cada pop)
        blocked = policy_block and depth >= PARAMS.capacity
        factor = (st.get("consumer.factor_pct", 0) or 100) / 100.0  # 0 = aun sin cambios

        hud.header(c, "COLA DE MENSAJES", "productor → cola acotada → consumidor", SEGMENTS, ts)
        hud.label3d(c, cam, (PROD[0] + 30, PROD[1] + 22, 128.0), "PRODUCTOR", 24)
        hud.label3d(c, cam, (QUEUE_C[0], QUEUE_C[1], 40.0), "COLA · 16 HUECOS", 24, "mem")
        hud.label3d(c, cam, (CONS[0] + 30, CONS[1] + 22, 128.0), "CONSUMIDOR", 24)

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
            float(PARAMS.capacity),
            "alert" if depth >= PARAMS.capacity else "mem",
            f"mensajes en la cola (capacidad {PARAMS.capacity})",
            f"{depth} / {PARAMS.capacity}",
        )

        dropped = st.get("q.dropped", 0)
        hud.card(
            c,
            40,
            1530,
            500,
            330,
            "Productor",
            "bus",
            [
                ("ofrece", f"{hud.fmt(_rate_at(t_us), 0)} msg/s"),
                ("política de desborde", "BLOCK" if policy_block else "DROP"),
                ("enviados", hud.fmt(st.get("producer.sent", 0))),
                ("mensajes perdidos", hud.fmt(dropped)),
            ],
            state_txt="BLOQUEADO" if blocked else "ACTIVO",
            state_token="warn" if blocked else "led_active",
        )
        wait_s = st.get("q.wait_us", 0) / S
        hud.card(
            c,
            540,
            1530,
            500,
            330,
            "Consumidor",
            "mem",
            [
                ("capacidad", f"{hud.fmt(10.0 / factor, 1)} msg/s"),
                ("procesados", hud.fmt(st.get("consumer.done", 0))),
                ("espera en cola", f"{hud.fmt(wait_s, 2)} s"),
                ("cola", f"{depth} / {PARAMS.capacity}"),
            ],
            state_txt="LENTO ×4" if factor > 1 else ("LLENA" if depth >= PARAMS.capacity else "OK"),
            state_token="warn"
            if factor > 1
            else ("alert" if depth >= PARAMS.capacity else "led_active"),
        )

        recent_drop = sim.drop_v[(sim.drop_v <= t_us) & (sim.drop_v > t_us - 450_000)]
        if recent_drop.size:
            hud.rect(c, 210, 1290, 660, 110, "alert", 0.9)
            hud.text(c, "MENSAJE DESCARTADO", 540, 1363, 44, "text_primary", "center")
        elif blocked and 22 <= ts < 50:
            hud.rect(c, 210, 1290, 660, 110, "warn", 0.9)
            hud.text(c, "PRODUCTOR EN ESPERA", 540, 1363, 44, "bg", "center")
        if ts >= 50:
            _balance(c, stats, min(1.0, (ts - 50) / 1.2))
        c.restore()

    return overlay


def _balance(c: skia.Canvas, stats: dict[str, PhaseStats], a: float) -> None:
    drop, block, slow = stats["drop"], stats["block"], stats["slow"]
    hud.rect(c, 0, 300, 1080, 1180, "bg", 1.0, 0)
    hud.text(c, "Mensajes perdidos", 100, 390, 36, "text_primary", alpha=a)
    hud.text(
        c,
        "ráfaga de 16 msg/s contra un consumidor de 10 msg/s",
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
            ("DROP", float(drop.lost), "alert", f"{hud.fmt(drop.lost)} en 14 s"),
            ("BLOCK", float(block.lost), "mem", f"{hud.fmt(block.lost)} en 16 s"),
        ],
        a,
        bar_w=420,
        v_max=float(max(1, drop.lost)),
    )
    hud.text(c, "Espera máxima en la cola", 100, 760, 36, "text_primary", alpha=a)
    hud.text(
        c,
        "BLOCK no acorta la espera: evita perder mensajes",
        100,
        802,
        24,
        "text_secondary",
        alpha=a,
    )
    top = max(drop.max_wait_s, block.max_wait_s, slow.max_wait_s)
    hud.bars(
        c,
        100,
        840,
        [
            ("DROP", drop.max_wait_s, "alert", f"{hud.fmt(drop.max_wait_s, 1)} s"),
            ("BLOCK", block.max_wait_s, "mem", f"{hud.fmt(block.max_wait_s, 1)} s"),
            ("LENTO ×4", slow.max_wait_s, "warn", f"{hud.fmt(slow.max_wait_s, 1)} s"),
        ],
        a,
        bar_w=420,
        row_h=90,
        v_max=top,
    )
    hud.text(
        c,
        f"BLOCK: el productor baja de 16 a {hud.fmt(block.offered_per_s, 0)} msg/s, sin pérdidas.",
        540,
        1190,
        24,
        "text_primary",
        "center",
        a,
    )
    hud.text(
        c,
        f"Consumidor ×4 más lento: {hud.fmt(slow.offered_per_s, 1)} msg/s y "
        f"{hud.fmt(slow.max_wait_s, 1)} s de espera.",
        540,
        1236,
        24,
        "text_secondary",
        "center",
        a,
    )
    hud.text(
        c,
        "Una cola acotada siempre elige: perder, esperar o escalar.",
        540,
        1330,
        28,
        "mem",
        "center",
        a,
    )


# =============================================================================
# Audio
# =============================================================================


def sound_events(sim: EpisodeSim) -> SoundEvents:
    z = np.zeros(1, dtype=np.int64)
    by: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for kind in ("queue.put", "msg.done", "queue.drop", "queue.block"):
        ev = sim.trace.events([kind])
        v = sim.tmap.video_at(ev.t_us)
        m = (v >= 0) & (v < 55 * S)
        by[kind] = (v[m], ev.a[m], ev.b[m])
    by["arch.end"] = (np.asarray([50 * S], dtype=np.int64), z.copy(), z.copy())
    return SoundEvents(by)


# =============================================================================
# Punto de entrada
# =============================================================================


def build(seed: int = 42) -> Scene:
    sim = get_episode_sim(seed)
    track = camera_track()
    return Scene(
        id="ep03_message_queue",
        video_width=1080,
        video_height=1920,
        fps=30,
        duration_s=DURATION_S,
        seed=seed,
        camera_track=track,
        compose_fn=lambda t_us: compose_faces(sim, t_us),
        overlay_fn=make_overlay(sim, track),
        audio_fn=lambda: sound_events(sim),
        traces_fn=lambda: {"queue": sim.trace},
        input_files=[Path(__file__)],
    )
