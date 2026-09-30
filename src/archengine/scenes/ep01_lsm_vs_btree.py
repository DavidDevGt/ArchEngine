"""Episodio 01 — «LSM-Trees vs B-Trees: ¿Por qué Cassandra escribe tan rápido?» (PDR §5, docs/07).

Cada motor se simula en su propio mundo (reloj virtual independiente) contra la *misma* carga
(llegadas Poisson sembradas). El guion solo fija **cuando se mira** cada tramo de simulacion
(``TimeMap`` por motor); el estado visual y el audio emergen de las trazas. Se cambia la velocidad
de reproduccion, nunca los costos del modelo.
"""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import skia  # type: ignore[import-not-found]

from archengine import __version__
from archengine.audio.sonification import SoundEvents
from archengine.core.schema import load_protocols, load_topology
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
from archengine.render.core import CameraKeyframe, CameraTrack, get_font
from archengine.render.theme import get_token_color
from archengine.simulation.engine import Simulation
from archengine.simulation.storage import (
    BTree,
    BTreeParams,
    DiskModel,
    DiskParams,
    LsmParams,
    LsmTree,
)
from archengine.simulation.trace import Trace
from archengine.simulation.workload import Workload

S = 1_000_000  # µs por segundo

# --- parametros del episodio (workload y fallo; los motores vienen de protocols/topologia) -------
RECORD_BYTES = 512
BENCH_WRITES = 100_000
LSM_TOTAL_WRITES = 560_000  # 100k de benchmark + carga sostenida (4 flushes => compaction L0->L1)
ARRIVAL_RATE = 50_000.0  # escrituras/s (Poisson) — OQ-18
POWER_LOSS_AT_US = 15 * S  # tras la compaction (se verifica en tests)
DURATION_S = 60.0

_DATA = Path(__file__).resolve().parent.parent / "data"
_PROTOCOLS = _DATA / "protocols.yaml"
_TOPOLOGY = _DATA / "topologies" / "lsm_vs_btree.yaml"

SEGMENTS = (
    (0, 5, "BENCHMARK · 100.000 ESCRITURAS ALEATORIAS", "text_primary"),
    (5, 15, "B-TREE · cada escritura es un seek", "disk"),
    (15, 30, "LSM-TREE · escritura a RAM, O(1)", "mem"),
    (30, 45, "FLUSH A SSTABLE · COMPACTACIÓN", "bus"),
    (45, 55, "CORTE DE ENERGÍA · RECUPERACIÓN DESDE WAL", "alert"),
    (55, 60, "BALANCE DE INGENIERÍA", "text_primary"),
)


# =============================================================================
# Simulacion (dos mundos) con cache de trace (OQ-21)
# =============================================================================


@dataclass
class EpisodeSim:
    lsm: Trace
    btree: Trace
    lsm_map: TimeMap
    btree_map: TimeMap
    inputs_hash: str
    trace_hash: str

    @property
    def metrics(self) -> Metrics:
        return _metrics(self)


@dataclass(frozen=True)
class Metrics:
    lsm_writes_per_s: float
    btree_writes_per_s: float
    lsm_service_us: float
    btree_service_us: float
    lsm_write_amp: float
    btree_write_amp: float
    lsm_read_amp_peak: int
    btree_read_pages_per_op: float
    replay_us: int
    replay_records: int


def inputs_hash() -> str:
    h = hashlib.sha256()
    h.update(__version__.encode())
    for p in (_PROTOCOLS, _TOPOLOGY):
        h.update(p.read_bytes())
    h.update(
        f"{RECORD_BYTES}|{BENCH_WRITES}|{LSM_TOTAL_WRITES}|{ARRIVAL_RATE}|{POWER_LOSS_AT_US}".encode()
    )
    return h.hexdigest()


def _simulate(seed: int) -> tuple[Trace, Trace]:
    proto = load_protocols(_PROTOCOLS)
    topo = load_topology(_TOPOLOGY)
    caps = {n.id: n.capacities for n in topo.nodes}
    dp = DiskParams.from_config(proto.disk_hdd)

    lsm_params = LsmParams(
        memtable_bytes=caps["db_lsm"].get("memtable_bytes", proto.lsm.memtable_bytes),
        l0_compaction_trigger=proto.lsm.l0_compaction_trigger,
        record_bytes=RECORD_BYTES,
    )
    sim_l = Simulation(seed)
    sim_l.add(LsmTree(lsm_params, DiskModel(dp), DiskModel(dp)))
    w_l = Workload.random_writes("lsm", LSM_TOTAL_WRITES, ARRIVAL_RATE, seed)
    sim_l.add(w_l)
    sim_l.schedule_at(w_l.first_us, w_l.id, "next")
    sim_l.schedule_at(POWER_LOSS_AT_US, "lsm", "power.loss")
    sim_l.run_until()

    bt_params = BTreeParams(
        fanout=proto.btree.fanout,
        buffer_pool_pages=caps["db_btree"].get("buffer_pool_pages", proto.btree.buffer_pool_pages),
        record_bytes=RECORD_BYTES,
    )
    sim_b = Simulation(seed)
    sim_b.add(BTree(bt_params, DiskModel(dp)))
    w_b = Workload.random_writes("btree", BENCH_WRITES, ARRIVAL_RATE, seed)
    sim_b.add(w_b)
    sim_b.schedule_at(w_b.first_us, w_b.id, "next")
    sim_b.run_until()
    return sim_l.trace, sim_b.trace


def _time_maps(lsm: Trace, btree: Trace) -> tuple[TimeMap, TimeMap]:
    def need(tr: Trace, kind: str) -> int:
        t = tr.first(kind)
        if t is None:
            raise RuntimeError(f"La simulacion no produjo el evento requerido: {kind}")
        return t

    t_flush0 = need(lsm, "lsm.flush.start")
    t_comp_end = need(lsm, "lsm.compaction.end")
    t_crash = need(lsm, "power.loss")
    t_rec = need(lsm, "wal.replay.start")
    t_rep_end = need(lsm, "wal.replay.end")
    lead = 50_000
    lsm_knots = [
        (0, 0),
        (int(2.5 * S), 250_000),
        (4 * S, 800_000),
        (5 * S, 1_600_000),  # benchmark acelera: ~80k escrituras emitidas al cierre del tramo
        (15 * S, 1_600_000),  # tramo B-Tree: el LSM queda pausado
        (30 * S, t_flush0 - lead),  # MemTable llenandose en camara lenta
        (45 * S, t_comp_end),
        (48 * S, t_crash),
        (50 * S, t_rec),
        (53 * S, t_rep_end),
        (60 * S, t_rep_end),
    ]
    t_b_end = btree.end_us
    btree_knots = [(0, 0), (5 * S, 3 * S), (15 * S, t_b_end), (60 * S, t_b_end)]
    return TimeMap(lsm_knots), TimeMap(btree_knots)


def _cache_dir() -> Path:
    return Path(tempfile.gettempdir()) / "archengine-cache"


_SIM_CACHE: dict[int, EpisodeSim] = {}


def get_episode_sim(seed: int = 42, use_disk_cache: bool = True) -> EpisodeSim:
    """Simulacion del episodio con cache caliente en memoria y en disco."""
    if seed in _SIM_CACHE:
        return _SIM_CACHE[seed]
    ih = inputs_hash()
    key = hashlib.sha256(f"{ih}|{seed}".encode()).hexdigest()[:24]
    f_l = _cache_dir() / f"{key}.lsm.npz"
    f_b = _cache_dir() / f"{key}.btree.npz"
    if use_disk_cache and f_l.is_file() and f_b.is_file():
        lsm, btree = Trace.load(f_l), Trace.load(f_b)
    else:
        lsm, btree = _simulate(seed)
        if use_disk_cache:
            lsm.save(f_l)
            btree.save(f_b)
    lm, bm = _time_maps(lsm, btree)
    th = hashlib.sha256((lsm.trace_hash() + btree.trace_hash()).encode()).hexdigest()
    sim = EpisodeSim(lsm, btree, lm, bm, f"sha256:{ih}", f"sha256:{th}")
    _SIM_CACHE[seed] = sim
    return sim


def _metrics(sim: EpisodeSim) -> Metrics:
    lsm, bt = sim.lsm, sim.btree
    end_l = lsm.end_us
    # LSM: el 100.000-esimo put se confirma cuando llega (sin cola): throughput sostenido = tasa.
    puts_t = lsm.events(["memtable.put"]).t_us
    t100k = int(puts_t[BENCH_WRITES - 1])
    bt_put = bt.events(["btree.put"])
    ra = lsm.events(["lsm.read_amp"]).a
    rep = lsm.events(["wal.replay.end"])
    return Metrics(
        lsm_writes_per_s=BENCH_WRITES / (t100k / S),
        btree_writes_per_s=BENCH_WRITES / (bt.end_us / S),
        lsm_service_us=2.0,
        btree_service_us=float(bt_put.b.mean()),
        lsm_write_amp=lsm.value_at("lsm.bytes_physical", end_l)
        / max(1, lsm.value_at("lsm.bytes_logical", end_l)),
        btree_write_amp=bt.value_at("btree.pages_written", bt.end_us)
        * 4096
        / max(1, bt.value_at("btree.bytes_logical", bt.end_us)),
        lsm_read_amp_peak=int(ra.max()) if ra.size else 1,
        btree_read_pages_per_op=bt.value_at("btree.pages_read", bt.end_us) / BENCH_WRITES,
        replay_us=int(rep.b[0]),
        replay_records=int(rep.a[0]),
    )


# =============================================================================
# Geometria dependiente del estado
# =============================================================================

L0 = (-150.0, 150.0)  # origen de la zona LSM
B0 = (150.0, -150.0)  # origen de la zona B-Tree
MEMTABLE_BYTES_FALLBACK = 67_108_864


def _slab(
    pid: str, x: float, y: float, z: float, w: float, d: float, h: float, token: str
) -> list[Face]:
    return _make_box_faces(pid, x, y, z, w, d, h, token)


def _floor(pid: str, cx: float, cy: float, w: float, d: float) -> list[Face]:
    return _make_box_faces(pid, cx - w / 2, cy - d / 2, -6.0, w, d, 6.0, "grid_line", LAYER_FLOOR)


def _lerp(a: float, b: float, s: float) -> float:
    return a + (b - a) * max(0.0, min(1.0, s))


def compose_faces(sim: EpisodeSim, t_us: int) -> list[Face]:
    ls = sim.lsm.state_at(sim.lsm_map.sim_at(t_us))
    bs = sim.btree.state_at(sim.btree_map.sim_at(t_us))
    mem_cap = MEMTABLE_BYTES_FALLBACK
    state = ls.get("lsm.state", 0)
    faces: list[Face] = []

    # ---- zona LSM ----
    lx, ly = L0
    faces += _floor("floor_lsm", lx + 35, ly + 70, 240, 260)
    crashed = state == 1
    blades = ["idle"] * 4 if crashed else ["active", "active", "active", "idle"]
    faces += ServerRack(
        id="lsm_node",
        pos=(lx - 40, ly - 10, 0.0),
        width=60,
        depth=45,
        height=110,
        num_blades=4,
        blade_states=blades,
        is_crashed=crashed,
    ).faces()
    fill = ls.get("lsm.mem_bytes", 0) / mem_cap
    faces += MemoryBlock(
        id="lsm_mem",
        pos=(lx + 50, ly - 10, 0.0),
        width=70,
        depth=50,
        height=90,
        fill_level=min(1.0, fill),
    ).faces()
    # MemTable inmutable congelada viajando hacia el disco durante el flush
    imm = ls.get("lsm.imm_bytes", 0)
    if imm:
        s = ls.get("lsm.flush_pm", 0) / 1000.0
        faces += _slab(
            "lsm_imm",
            _lerp(lx + 50, lx + 50, s),
            _lerp(ly - 10, ly + 110, s),
            _lerp(95, 0, s),
            70,
            50,
            18,
            "node_active",
        )
    # WAL: tira secuencial cuyo largo es el log durable
    wal = min(1.0, ls.get("lsm.wal_bytes", 0) / mem_cap)
    faces += _slab("lsm_wal", lx - 40, ly - 70, 0, 4 + 66 * wal, 12, 6, "disk")
    # SSTables: L0 apiladas; en compaction se funden hacia L1
    l0 = ls.get("lsm.l0", 0)
    pm = ls.get("lsm.compact_pm", 0) / 1000.0
    base_y = ly + 110
    for i in range(l0):
        faces += _slab(f"lsm_l0_{i}", lx + 50, base_y, _lerp(i * 14, 0, pm) + 2, 70, 50, 10, "disk")
    if ls.get("lsm.l1", 0) or pm > 0:
        grow = pm if pm > 0 else 1.0
        faces += _slab("lsm_l1", lx + 50, base_y + 70, 0, 70, 50, 6 + 8 * grow, "bus")
    # tuberia de escrituras: paquetes avanzan con cada put
    puts = ls.get("lsm.puts", 0)
    faces += NetworkPipes(
        id="lsm_pipe",
        points=[(lx - 10, ly + 12, 20.0), (lx + 50, ly + 12, 20.0)],
        width=5,
        packets=[((puts // 64 + i * 3) % 10) / 10.0 for i in range(3)] if not crashed else [],
    ).faces()

    # ---- zona B-Tree ----
    bx, by = B0
    faces += _floor("floor_btree", bx + 45, by + 10, 240, 160)
    faces += ServerRack(
        id="bt_node",
        pos=(bx - 40, by - 10, 0.0),
        width=60,
        depth=45,
        height=110,
        num_blades=4,
        blade_states=["active", "idle", "active", "active"],
    ).faces()
    head = bs.get("btree.head_track", 0) / 2000.0
    faces += StorageCylinder(
        id="bt_disk",
        center=(bx + 80, by + 15, 0.0),
        radius=58,
        height=30,
        head_track_normalized=head,
        head_angle_rad=(bs.get("btree.head_track", 0) * 0.37) % 6.283,
        written_ratio=min(1.0, bs.get("btree.pages_written", 0) / 60_000),
    ).faces()
    faces += NetworkPipes(
        id="bt_pipe",
        points=[(bx - 10, by + 12, 20.0), (bx + 30, by + 12, 20.0)],
        width=5,
        packets=[((bs.get("btree.puts", 0) // 64 + i * 3) % 10) / 10.0 for i in range(3)],
    ).faces()
    return faces


def camera_track() -> CameraTrack:
    kf = CameraKeyframe
    mid = (0.0, 0.0, 30.0)
    lsm = (L0[0] + 50, L0[1] + 40, 30.0)
    bt = (B0[0] + 40, B0[1] + 10, 20.0)
    return CameraTrack(
        [
            kf(0, 45.0, 35.264, 1.45, mid),
            kf(5 * S, 45.0, 35.264, 1.45, mid),
            kf(7 * S, 52.0, 32.0, 2.7, bt),
            kf(15 * S, 38.0, 34.0, 2.7, bt),
            kf(17 * S, 40.0, 34.0, 3.0, lsm),
            kf(30 * S, 48.0, 36.0, 3.0, lsm),
            kf(32 * S, 45.0, 38.0, 2.7, (lsm[0], lsm[1] + 40, 20.0)),
            kf(45 * S, 42.0, 36.0, 2.7, (lsm[0], lsm[1] + 40, 20.0)),
            kf(48 * S, 45.0, 36.0, 3.0, lsm),
            kf(55 * S, 45.0, 36.0, 3.0, lsm),
            kf(58 * S, 45.0, 35.264, 1.45, mid),
            kf(60 * S, 45.0, 35.264, 1.45, mid),
        ]
    )


# =============================================================================
# HUD en espacio de pantalla
# =============================================================================


def _fmt(n: float, dec: int = 0) -> str:
    s = f"{n:,.{dec}f}"
    return s.replace(",", "\0").replace(".", ",").replace("\0", ".")


def _text(
    c: skia.Canvas,
    s: str,
    x: float,
    y: float,
    size: float,
    token: str,
    align: str = "left",
    alpha: float = 1.0,
) -> None:
    font = get_font(size)
    paint = skia.Paint(AntiAlias=True, Color=get_token_color(token).with_alpha(alpha).to_argb_int())
    if align != "left":
        w = font.measureText(s)
        x -= w if align == "right" else w / 2
    c.drawString(s, x, y, font, paint)


def _rect(
    c: skia.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    token: str,
    alpha: float = 1.0,
    r: float = 10.0,
) -> None:
    paint = skia.Paint(AntiAlias=True, Color=get_token_color(token).with_alpha(alpha).to_argb_int())
    c.drawRoundRect(skia.Rect.MakeXYWH(x, y, w, h), r, r, paint)


def _card(
    c: skia.Canvas,
    x: float,
    w: float,
    title: str,
    token: str,
    rows: list[tuple[str, str]],
    progress: float,
    state_txt: str,
    state_token: str,
) -> None:
    y0, h = 1530.0, 330.0
    _rect(c, x, y0, w, h, "node_idle", 1.0)
    _rect(c, x, y0, 8, h, token, 1.0, 4)
    _text(c, title, x + 30, y0 + 52, 32, "text_primary")
    _text(c, state_txt, x + w - 30, y0 + 120, 22, state_token, "right")
    _rect(c, x + 30, y0 + 74, w - 60, 14, "grid_line", 1.0, 7)
    _rect(c, x + 30, y0 + 74, max(2.0, (w - 60) * progress), 14, token, 1.0, 7)
    for i, (k, v) in enumerate(rows):
        yy = y0 + 160 + i * 44
        _text(c, k, x + 30, yy, 24, "text_secondary")
        _text(c, v, x + w - 28, yy, 28, "text_primary", "right")


def make_overlay(sim: EpisodeSim):  # type: ignore[no-untyped-def]
    m = sim.metrics

    def overlay(c: skia.Canvas, w: int, h: int, t_us: int) -> None:
        k = w / 1080.0
        c.save()
        c.scale(k, k)
        ts = t_us / S
        ls = sim.lsm.state_at(sim.lsm_map.sim_at(t_us))
        bs = sim.btree.state_at(sim.btree_map.sim_at(t_us))

        _text(c, "LSM-TREES  vs  B-TREES", 540, 110, 54, "text_primary", "center")
        _text(c, "¿Por qué Cassandra escribe tan rápido?", 540, 162, 30, "text_secondary", "center")
        for a, b, label, tok in SEGMENTS:
            if a <= ts < b or (ts >= 60 and b == 60):
                _rect(c, 60, 214, 960, 62, "node_idle", 1.0)
                _text(c, label, 540, 255, 30, tok, "center")
        _text(c, f"{int(ts) // 60:02d}:{int(ts) % 60:02d}", 1020, 60, 24, "text_muted", "right")

        lw = ls.get("lsm.puts", 0)
        lsm_amp = ls.get("lsm.bytes_physical", 0) / max(1, ls.get("lsm.bytes_logical", 1))
        state = ls.get("lsm.state", 0)
        state_txt, state_tok = [
            ("OK", "led_active"),
            ("SIN ENERGÍA", "alert"),
            ("REPRODUCIENDO WAL", "warn"),
        ][state]
        lsm_rows = [
            ("escrituras", f"{_fmt(min(lw, BENCH_WRITES))} / {_fmt(BENCH_WRITES)}"),
            ("MemTable", f"{ls.get('lsm.mem_bytes', 0) / MEMTABLE_BYTES_FALLBACK * 100:5.1f} %"),
            ("SSTables L0 / L1", f"{ls.get('lsm.l0', 0)} / {ls.get('lsm.l1', 0)}"),
            (
                "amplif. escritura",
                f"{_fmt(lsm_amp, 2)}x",
            ),
        ]
        _card(
            c,
            40,
            500,
            "LSM-Tree · Cassandra",
            "mem",
            lsm_rows,
            min(1.0, lw / BENCH_WRITES),
            state_txt,
            state_tok,
        )
        bp = bs.get("btree.puts", 0)
        bamp = bs.get("btree.pages_written", 0) * 4096 / max(1, bs.get("btree.bytes_logical", 1))
        bt_rows = [
            ("escrituras", f"{_fmt(bp)} / {_fmt(BENCH_WRITES)}"),
            ("cabezal (pista)", f"{bs.get('btree.head_track', 0):4d} / 2000"),
            ("págs. escritas", _fmt(bs.get("btree.pages_written", 0))),
            ("amplif. escritura", f"{_fmt(bamp, 2)}x"),
        ]
        _card(
            c,
            540,
            500,
            "B-Tree · PostgreSQL",
            "disk",
            bt_rows,
            min(1.0, bp / BENCH_WRITES),
            "OK",
            "led_active",
        )

        if 45 <= ts < 55:
            if state == 1:
                _rect(c, 240, 880, 600, 120, "alert", 0.85)
                _text(c, "POWER LOSS", 540, 958, 56, "text_primary", "center")
            elif state == 2:
                _text(
                    c,
                    f"WAL replay: {_fmt(ls.get('lsm.mem_bytes', 0) / 1_048_576, 1)} MiB",
                    540,
                    1450,
                    34,
                    "warn",
                    "center",
                )
        if ts >= 53:
            _text(
                c,
                f"recuperado en {_fmt(m.replay_us / 1000, 0)} ms "
                f"({_fmt(m.replay_records)} registros)",
                540,
                1480,
                30,
                "led_active",
                "center",
            )
        if ts >= 55:
            _comparison(c, m, min(1.0, (ts - 55) / 1.2))
        c.restore()

    return overlay


def _comparison(c: skia.Canvas, m: Metrics, a: float) -> None:
    _rect(c, 60, 330, 960, 1120, "bg", 1.0, 24)
    _text(c, "Velocidad de escritura", 100, 420, 36, "text_primary", alpha=a)
    _text(c, "escrituras / segundo (mayor es mejor)", 100, 462, 24, "text_secondary", alpha=a)
    top = max(m.lsm_writes_per_s, m.btree_writes_per_s)
    for i, (name, val, tok) in enumerate(
        (("LSM-Tree", m.lsm_writes_per_s, "mem"), ("B-Tree", m.btree_writes_per_s, "disk"))
    ):
        y = 500 + i * 110
        _text(c, name, 100, y + 34, 28, "text_primary", alpha=a)
        _rect(c, 300, y, 560, 50, "grid_line", a, 6)
        _rect(c, 300, y, max(4.0, 560 * val / top * a), 50, tok, a, 6)
        _text(c, _fmt(val, 0 if val >= 100 else 1), 1000, y + 36, 30, "text_primary", "right", a)
    _text(
        c,
        f"{_fmt(m.lsm_writes_per_s / m.btree_writes_per_s, 0)}x más rápido",
        540,
        780,
        44,
        "mem",
        "center",
        a,
    )
    _text(c, "Amplificación de lectura", 100, 900, 36, "text_primary", alpha=a)
    _text(
        c,
        "SSTables consultadas (LSM pico) vs páginas leídas por op (B-Tree)",
        100,
        942,
        24,
        "text_secondary",
        alpha=a,
    )
    top2 = max(m.lsm_read_amp_peak, m.btree_read_pages_per_op)
    for i, (name, val, tok) in enumerate(
        (
            ("LSM-Tree", float(m.lsm_read_amp_peak), "mem"),
            ("B-Tree", m.btree_read_pages_per_op, "disk"),
        )
    ):
        y = 980 + i * 110
        _text(c, name, 100, y + 34, 28, "text_primary", alpha=a)
        _rect(c, 300, y, 560, 50, "grid_line", a, 6)
        _rect(c, 300, y, max(4.0, 560 * val / top2 * a), 50, tok, a, 6)
        _text(c, _fmt(val, 1), 1000, y + 36, 30, "text_primary", "right", a)
    _text(
        c,
        "Escribir rápido se paga al leer: por eso existe la compactación.",
        540,
        1300,
        24,
        "text_secondary",
        "center",
        a,
    )
    _text(
        c,
        f"Amplificación de escritura: LSM {_fmt(m.lsm_write_amp, 1)}x · B-Tree "
        f"{_fmt(m.btree_write_amp, 1)}x",
        540,
        1350,
        26,
        "text_secondary",
        "center",
        a,
    )


# =============================================================================
# Audio: eventos de trace -> tiempo de video
# =============================================================================


def sound_events(sim: EpisodeSim) -> SoundEvents:
    by: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}

    def take(
        tr: Trace, tmap: TimeMap, kind: str, lo_s: float, hi_s: float, out: str | None = None
    ) -> None:
        ev = tr.events([kind])
        v = tmap.video_at(ev.t_us)
        m = (v >= int(lo_s * S)) & (v < int(hi_s * S))
        by[out or kind] = (v[m], ev.a[m], ev.b[m])

    take(sim.lsm, sim.lsm_map, "bench.tick", 0, 5)
    take(sim.btree, sim.btree_map, "disk.seek", 5, 15)
    take(sim.lsm, sim.lsm_map, "memtable.put", 15, 45)
    take(sim.lsm, sim.lsm_map, "lsm.flush.start", 30, 55)
    take(sim.lsm, sim.lsm_map, "lsm.compaction.start", 30, 55)
    take(sim.lsm, sim.lsm_map, "lsm.compaction.end", 30, 60)
    take(sim.lsm, sim.lsm_map, "power.loss", 45, 55)
    take(sim.lsm, sim.lsm_map, "wal.replay.end", 45, 60)
    z = np.zeros(1, dtype=np.int64)
    t_loss = int(by["power.loss"][0][0])
    t_up = int(by["wal.replay.end"][0][0])
    by["node.up"] = (
        np.asarray([0, 0, t_up], dtype=np.int64),
        np.asarray([0, 1, 0], dtype=np.int64),
        np.zeros(3, dtype=np.int64),
    )
    by["node.down"] = (np.asarray([t_loss], dtype=np.int64), z.copy(), z.copy())
    by["scene.end"] = (np.asarray([55 * S], dtype=np.int64), z.copy(), z.copy())
    return SoundEvents(by)


# =============================================================================
# Punto de entrada de escena
# =============================================================================


def build(seed: int = 42) -> Scene:
    sim = get_episode_sim(seed)
    return Scene(
        id="ep01_lsm_vs_btree",
        video_width=1080,
        video_height=1920,
        fps=30,
        duration_s=DURATION_S,
        seed=seed,
        camera_track=camera_track(),
        compose_fn=lambda t_us: compose_faces(sim, t_us),
        overlay_fn=make_overlay(sim),
        audio_fn=lambda: sound_events(sim),
        traces_fn=lambda: {"lsm": sim.lsm, "btree": sim.btree},
        input_files=[_PROTOCOLS, _TOPOLOGY],
    )
