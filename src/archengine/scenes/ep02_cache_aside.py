"""Episodio 02 — «Cache-aside: ¿por qué Redis delante de la base de datos?» (docs/13).

Dos mundos con la *misma* carga Zipf sembrada: con caché (LRU + TTL) y sin caché (todas las
lecturas al disco). El guion solo decide cuando se mira cada tramo (``TimeMap``); aciertos, fallos,
latencias y el *stampede* tras el flush emergen de la simulacion.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import skia  # type: ignore[import-not-found]

from archengine import __version__
from archengine.audio.sonification import SoundEvents
from archengine.core.rng import deterministic_rng
from archengine.core.schema import load_protocols
from archengine.core.timebase import TimeMap
from archengine.geometry.primitives import (
    LAYER_FLOOR,
    Face,
    MemoryBlock,
    NetworkPipes,
    ServerRack,
    StorageCylinder,
    _make_box_faces,
)
from archengine.pipeline.preview import Scene
from archengine.render.core import CameraKeyframe, CameraTrack
from archengine.scenes import hud
from archengine.scenes.hud import S
from archengine.simulation.cache import CacheAsideApp, CacheAsideParams
from archengine.simulation.engine import Simulation
from archengine.simulation.storage import DiskModel, DiskParams
from archengine.simulation.trace import Trace
from archengine.simulation.workload import Workload, poisson_arrivals, zipf_keys

# --- parametros del episodio ----------------------------------------------------------------------
RATE = 100.0  # lecturas/s (Poisson)
SIM_S = 130  # segundos de simulacion generados
FLUSH_AT_US = 80 * S
ZIPF_S = 1.2
PARAMS = CacheAsideParams(capacity=1200, ttl_us=45 * S, cache_rtt_us=400, n_keys=50_000)
HIT_WINDOW_S = 4  # ventana de la tasa de aciertos (segundos de simulacion)
DURATION_S = 60.0

_PROTOCOLS = Path(__file__).resolve().parent.parent / "data" / "protocols.yaml"

SEGMENTS: tuple[hud.Segment, ...] = (
    (0, 10, "CACHÉ FRÍA · CADA MISS CUESTA UN SEEK", "disk"),
    (10, 24, "CACHÉ CALIENTE · HITS EN MICROSEGUNDOS", "mem"),
    (24, 36, "CACHÉ LLENA · DESALOJO LRU Y TTL", "bus"),
    (36, 50, "FLUSH · STAMPEDE HACIA EL DISCO", "alert"),
    (50, 60, "BALANCE DE INGENIERÍA", "text_primary"),
)
# nudos (video_us, sim_us): 0-10 s de video casi en tiempo real (se ve calentar la cache);
# el flush (sim 80 s) cae en el video a ~36,9 s
KNOTS = [(0, 0), (10 * S, 8 * S), (24 * S, 50 * S), (36 * S, 78 * S), (50 * S, 110 * S)]
END_SIM_US = 110 * S


# =============================================================================
# Simulacion
# =============================================================================


@dataclass
class EpisodeSim:
    cached: Trace
    bare: Trace
    tmap: TimeMap
    trace_hash: str
    hit_v: np.ndarray  # instantes de video de cada hit / miss / flush
    miss_v: np.ndarray
    flush_v: np.ndarray
    spark_x: np.ndarray  # serie precalculada de la tasa de aciertos (s de video)
    spark_y: np.ndarray
    evict_t: np.ndarray  # instantes de simulacion de desalojos LRU y vencimientos TTL
    expire_t: np.ndarray


def _run(seed: int, capacity: int, with_flush: bool) -> Trace:
    proto = load_protocols(_PROTOCOLS)
    dp = DiskParams.from_config(proto.disk_hdd)
    n = int(RATE * SIM_S * 1.15)
    params = CacheAsideParams(
        capacity=capacity,
        ttl_us=PARAMS.ttl_us,
        cache_rtt_us=PARAMS.cache_rtt_us,
        n_keys=PARAMS.n_keys,
    )
    arrivals = poisson_arrivals(n, RATE, seed, "cache.arrivals")
    keys = zipf_keys(n, params.n_keys, ZIPF_S, seed)
    # permutacion fija clave -> pista: las claves calientes no comparten zona del disco
    perm = deterministic_rng(seed, "cache.layout").permutation(params.n_keys)
    track_of = perm * dp.tracks // params.n_keys
    sim = Simulation(seed)
    sim.add(CacheAsideApp(params, DiskModel(dp), track_of))
    w = Workload(
        target="app",
        arrivals_us=arrivals,
        keys=keys,
        comp_id="client",
        tick_every=10**9,
        kind="get",
    )
    sim.add(w)
    sim.schedule_at(w.first_us, w.id, "next")
    if with_flush:
        sim.schedule_at(FLUSH_AT_US, "app", "flush")
    sim.run_until(SIM_S * S)
    return sim.trace


def window_hit_ratio(tr: Trace, t_us: int, win_us: int) -> float:
    a = max(0, t_us - win_us)
    reqs = tr.value_at("app.reqs", t_us) - tr.value_at("app.reqs", a)
    hits = tr.value_at("app.hits", t_us) - tr.value_at("app.hits", a)
    return hits / reqs if reqs else 0.0


def window_latency_ms(tr: Trace, t_us: int, win_us: int) -> float:
    a = max(0, t_us - win_us)
    done = tr.value_at("app.done", t_us) - tr.value_at("app.done", a)
    lat = tr.value_at("app.lat_sum_us", t_us) - tr.value_at("app.lat_sum_us", a)
    return lat / done / 1000.0 if done else 0.0


_SIM_CACHE: dict[int, EpisodeSim] = {}


def get_episode_sim(seed: int = 42) -> EpisodeSim:
    if seed in _SIM_CACHE:
        return _SIM_CACHE[seed]
    cached = _run(seed, PARAMS.capacity, with_flush=True)
    bare = _run(seed, 0, with_flush=False)
    tmap = TimeMap(KNOTS)

    def v(kind: str) -> np.ndarray:
        return hud.video_times(tmap, cached.events([kind]).t_us)

    xs = np.arange(0.0, DURATION_S + 0.25, 0.25)
    ys = np.asarray(
        [window_hit_ratio(cached, tmap.sim_at(int(x * S)), HIT_WINDOW_S * S) * 100.0 for x in xs]
    )
    th = hashlib.sha256((__version__ + cached.trace_hash() + bare.trace_hash()).encode())
    sim = EpisodeSim(
        cached,
        bare,
        tmap,
        f"sha256:{th.hexdigest()}",
        v("cache.hit"),
        v("cache.miss"),
        v("cache.flush"),
        xs,
        ys,
        cached.events(["cache.evict"]).t_us,
        cached.events(["cache.expire"]).t_us,
    )
    _SIM_CACHE[seed] = sim
    return sim


@dataclass(frozen=True)
class Metrics:
    hit_ratio: float
    lat_cached_ms: float
    lat_bare_ms: float
    hit_ms: float
    miss_ms: float


def metrics(sim: EpisodeSim) -> Metrics:
    lo, hi = END_SIM_US - 20 * S, END_SIM_US
    ev = sim.cached.events(["req.done"])
    m = (ev.t_us >= 60 * S) & (ev.t_us < FLUSH_AT_US)  # regimen estable previo al flush
    miss = ev.b[m] == 1
    return Metrics(
        hit_ratio=window_hit_ratio(sim.cached, FLUSH_AT_US, 20 * S),
        lat_cached_ms=window_latency_ms(sim.cached, hi, hi - lo),
        lat_bare_ms=window_latency_ms(sim.bare, hi, hi - lo),
        hit_ms=float(ev.a[m][~miss].mean()) / 1000.0,
        miss_ms=float(ev.a[m][miss].mean()) / 1000.0,
    )


# =============================================================================
# Geometria
# =============================================================================

# Fila a lo largo de x; los buses corren por delante (y < 0) para que ningun cuerpo los tape.
APP = (-130.0, -10.0)
REDIS = (-20.0, 0.0)
DB = (110.0, 25.0)
PIPE_CACHE = [(-105.0, -10.0, 20.0), (-105.0, -35.0, 20.0), (15.0, -35.0, 20.0), (15.0, 0.0, 20.0)]
PIPE_DB = [(-75.0, -10.0, 20.0), (-75.0, -58.0, 20.0), (110.0, -58.0, 20.0), (110.0, -20.0, 20.0)]


def _floor(pid: str, cx: float, cy: float, w: float, d: float) -> list[Face]:
    return _make_box_faces(pid, cx - w / 2, cy - d / 2, -6.0, w, d, 6.0, "grid_line", LAYER_FLOOR)


def compose_faces(sim: EpisodeSim, t_us: int) -> list[Face]:
    st = sim.cached.state_at(sim.tmap.sim_at(t_us))
    win = 450_000
    fill = st.get("cache.size", 0) / PARAMS.capacity
    flushing = bool(sim.flush_v.size) and 0 <= t_us - int(sim.flush_v[0]) < 2 * S
    faces: list[Face] = _floor("floor", -5, 15, 350, 150)
    faces += ServerRack(
        id="app",
        pos=(APP[0], APP[1], 0.0),
        width=60,
        depth=45,
        height=110,
        num_blades=4,
        blade_states=["active", "active", "active", "idle"],
    ).faces()
    faces += MemoryBlock(
        id="redis",
        pos=(REDIS[0], REDIS[1], 0.0),
        width=70,
        depth=50,
        height=90,
        fill_level=min(1.0, fill),
    ).faces()
    if flushing:  # el flush vacia la RAM: aro de alerta bajo el bloque
        faces += _make_box_faces(
            "redis_alert", REDIS[0] - 6, REDIS[1] - 6, 0.0, 82, 62, 3.0, "alert"
        )
    head = st.get("db.head_track", 0) / 2000.0
    faces += StorageCylinder(
        id="db",
        center=(DB[0], DB[1], 0.0),
        radius=46,
        height=30,
        head_track_normalized=head,
        head_angle_rad=(st.get("db.head_track", 0) * 0.37) % 6.283,
        written_ratio=0.35,
    ).faces()
    faces += NetworkPipes(
        id="pipe_cache",
        points=PIPE_CACHE,
        width=5,
        packets=hud.recent_progress(sim.hit_v, t_us, win),
        packet_color="mem",
    ).faces()
    faces += NetworkPipes(
        id="pipe_db",
        points=PIPE_DB,
        width=5,
        packets=hud.recent_progress(sim.miss_v, t_us, win),
        packet_color="alert",
    ).faces()
    return faces


def camera_track() -> CameraTrack:
    kf = CameraKeyframe
    tgt = (-5.0, 10.0, 10.0)
    return CameraTrack(
        [
            kf(0, 45.0, 35.264, 2.75, tgt),
            kf(24 * S, 40.0, 34.0, 2.9, tgt),
            kf(36 * S, 45.0, 36.0, 2.9, tgt),
            kf(50 * S, 50.0, 35.264, 2.75, tgt),
            kf(60 * S, 45.0, 35.264, 2.75, tgt),
        ]
    )


# =============================================================================
# HUD
# =============================================================================


def make_overlay(sim: EpisodeSim, track: CameraTrack):  # type: ignore[no-untyped-def]
    m = metrics(sim)

    def overlay(c: skia.Canvas, w: int, h: int, t_us: int) -> None:
        k = w / 1080.0
        c.save()
        c.scale(k, k)
        ts = t_us / S
        ts_sim = sim.tmap.sim_at(t_us)
        win = HIT_WINDOW_S * S
        cs = sim.cached.state_at(ts_sim)
        bs = sim.bare.state_at(ts_sim)
        cam = track.camera_at(t_us, 1080, 1920)

        hud.header(c, "CACHE-ASIDE", "1º la caché, 2º la base de datos", SEGMENTS, ts)
        hud.label3d(c, cam, (APP[0] + 30, APP[1] + 22, 128.0), "APP", 26)
        hud.label3d(c, cam, (REDIS[0] + 35, REDIS[1] + 25, 108.0), "REDIS", 24, "mem")
        hud.label3d(c, cam, (DB[0], DB[1], 52.0), "DISCO HDD", 24, "disk")

        hit = window_hit_ratio(sim.cached, ts_sim, win)
        hud.sparkline(
            c,
            60,
            300,
            960,
            230,
            sim.spark_x,
            sim.spark_y,
            ts,
            DURATION_S - 10.0 if ts < 50 else DURATION_S,
            100.0,
            "mem",
            f"tasa de aciertos (ventana {HIT_WINDOW_S} s sim)",
            f"{hud.fmt(hit * 100, 0)} %",
        )

        flush_on = bool(sim.flush_v.size) and 0 <= t_us - int(sim.flush_v[0]) < 2 * S
        reqs = cs.get("app.reqs", 0)
        hud.card(
            c,
            40,
            1530,
            500,
            330,
            "Con caché",
            "mem",
            [
                ("lecturas servidas", hud.fmt(reqs)),
                ("latencia media", _ms(window_latency_ms(sim.cached, ts_sim, win))),
                ("entradas", f"{hud.fmt(cs.get('cache.size', 0))} / {hud.fmt(PARAMS.capacity)}"),
                (
                    "desalojos LRU / TTL",
                    f"{hud.fmt(int(np.searchsorted(sim.evict_t, ts_sim, 'right')))} / "
                    f"{hud.fmt(int(np.searchsorted(sim.expire_t, ts_sim, 'right')))}",
                ),
            ],
            progress=cs.get("cache.size", 0) / PARAMS.capacity,
            state_txt="FLUSH" if flush_on else "OK",
            state_token="alert" if flush_on else "led_active",
        )
        bare_lat = window_latency_ms(sim.bare, ts_sim, win)
        hud.card(
            c,
            540,
            1530,
            500,
            330,
            "Sin caché",
            "disk",
            [
                ("lecturas servidas", hud.fmt(bs.get("app.done", 0))),
                ("latencia media", _ms(bare_lat)),
                ("cola en el disco", hud.fmt(bs.get("db.inflight", 0))),
                ("cabezal (pista)", f"{bs.get('db.head_track', 0):4d} / 2000"),
            ],
            progress=min(1.0, bs.get("db.inflight", 0) / 50.0),
            state_txt="SATURADO" if bs.get("db.inflight", 0) > 20 else "OK",
            state_token="alert" if bs.get("db.inflight", 0) > 20 else "led_active",
        )

        if flush_on:
            hud.rect(c, 240, 1290, 600, 110, "alert", 0.85)
            hud.text(c, "FLUSHALL", 540, 1365, 52, "text_primary", "center")
        if ts >= 50:
            _balance(c, m, min(1.0, (ts - 50) / 1.2))
        c.restore()

    return overlay


def _ms(v: float) -> str:
    return f"{hud.fmt(v / 1000, 1)} s" if v >= 1000 else f"{hud.fmt(v, 1)} ms"


def _balance(c: skia.Canvas, m: Metrics, a: float) -> None:
    hud.rect(c, 0, 300, 1080, 1180, "bg", 1.0, 0)
    hud.text(c, "Latencia media por lectura", 100, 420, 36, "text_primary", alpha=a)
    hud.text(
        c,
        "milisegundos, mismos 100 req/s (menor es mejor)",
        100,
        462,
        24,
        "text_secondary",
        alpha=a,
    )
    top = max(m.lat_cached_ms, m.lat_bare_ms)
    hud.bars(
        c,
        100,
        500,
        [
            ("Con caché", m.lat_cached_ms, "mem", _ms(m.lat_cached_ms)),
            ("Sin caché", m.lat_bare_ms, "disk", _ms(m.lat_bare_ms)),
        ],
        a,
        bar_w=460,
        v_max=top,
    )
    factor = m.lat_bare_ms / max(1e-9, m.lat_cached_ms)
    hud.text(c, f"{hud.fmt(factor, 0)}x menos latencia", 540, 780, 44, "mem", "center", a)
    hud.text(c, "Un hit vs. un miss", 100, 900, 36, "text_primary", alpha=a)
    hud.text(c, "costo de una lectura en régimen estable", 100, 942, 24, "text_secondary", alpha=a)
    hud.bars(
        c,
        100,
        980,
        [
            ("Hit", m.hit_ms, "mem", f"{hud.fmt(m.hit_ms, 1)} ms"),
            ("Miss", m.miss_ms, "alert", f"{hud.fmt(m.miss_ms, 1)} ms"),
        ],
        a,
        bar_w=460,
        v_max=m.miss_ms,
    )
    hud.text(
        c,
        f"Tasa de aciertos en régimen: {hud.fmt(m.hit_ratio * 100, 0)} %",
        540,
        1290,
        30,
        "text_secondary",
        "center",
        a,
    )
    hud.text(
        c,
        "Sin caché el disco no da abasto: la cola crece sin límite.",
        540,
        1350,
        24,
        "text_secondary",
        "center",
        a,
    )
    hud.text(
        c,
        "Con caché, un flush solo cuesta un bache temporal.",
        540,
        1394,
        24,
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

    def take(kind: str, lo_s: float, hi_s: float) -> None:
        ev = sim.cached.events([kind])
        v = sim.tmap.video_at(ev.t_us)
        m = (v >= int(lo_s * S)) & (v < int(hi_s * S))
        by[kind] = (v[m], ev.a[m], ev.b[m])

    take("cache.hit", 0, 55)
    take("cache.miss", 0, 55)
    take("cache.flush", 0, 55)
    by["arch.end"] = (np.asarray([50 * S], dtype=np.int64), z.copy(), z.copy())
    return SoundEvents(by)


# =============================================================================
# Punto de entrada
# =============================================================================


def build(seed: int = 42) -> Scene:
    sim = get_episode_sim(seed)
    track = camera_track()
    return Scene(
        id="ep02_cache_aside",
        video_width=1080,
        video_height=1920,
        fps=30,
        duration_s=DURATION_S,
        seed=seed,
        camera_track=track,
        compose_fn=lambda t_us: compose_faces(sim, t_us),
        overlay_fn=make_overlay(sim, track),
        audio_fn=lambda: sound_events(sim),
        traces_fn=lambda: {"cached": sim.cached, "bare": sim.bare},
        input_files=[_PROTOCOLS],
    )
