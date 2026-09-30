"""Motor de eventos, trace, disco, WAL, LSM y B-Tree (docs/02, docs/09)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from archengine.core.schema import load_protocols
from archengine.simulation.engine import Ctx, Event, Simulation
from archengine.simulation.storage import (
    BTree,
    BTreeParams,
    DiskModel,
    DiskParams,
    LsmParams,
    LsmTree,
)
from archengine.simulation.trace import Trace
from archengine.simulation.workload import Workload, poisson_arrivals

PROTOCOLS = Path(__file__).resolve().parents[2] / "src" / "archengine" / "data" / "protocols.yaml"


def _disk() -> DiskModel:
    return DiskModel(DiskParams.from_config(load_protocols(PROTOCOLS).disk_hdd))


class _Echo:
    def __init__(self, cid: str) -> None:
        self.id = cid
        self.seen: list[tuple[int, str]] = []

    def handle(self, ev: Event, ctx: Ctx) -> list[Event]:
        self.seen.append((ctx.now_us, ev.kind))
        return []

    def snapshot(self) -> dict[str, int]:
        return {}

    def restore(self, snap: dict[str, int]) -> None:
        return None


def test_event_queue_orders_by_time_then_insertion() -> None:
    sim = Simulation(1)
    c = _Echo("c")
    sim.add(c)
    sim.schedule_at(20, "c", "b")
    sim.schedule_at(10, "c", "a1")
    sim.schedule_at(10, "c", "a2")
    sim.run_until()
    assert c.seen == [(10, "a1"), (10, "a2"), (20, "b")]


def test_event_in_the_past_is_rejected() -> None:
    sim = Simulation(1)
    sim.add(_Echo("c"))
    sim.now_us = 100
    with pytest.raises(ValueError):
        sim.schedule_at(50, "c", "x")


def test_trace_state_at_and_hash_roundtrip(tmp_path: Path) -> None:
    tr = Trace()
    tr.record(5, "a", "k1", 1, 2)
    tr.set_field(0, "x", 0)
    tr.set_field(10, "x", 7)
    tr.set_field(10, "x", 8)  # mismo instante: reemplaza
    tr.set_field(20, "x", 8)  # mismo valor: sin transicion
    assert tr.value_at("x", 9) == 0
    assert tr.state_at(10) == {"x": 8}
    assert tr.first("k1") == 5
    tr.save(tmp_path / "t.npz")
    tr2 = Trace.load(tmp_path / "t.npz")
    assert tr2.trace_hash() == tr.trace_hash()
    assert tr2.state_at(15) == {"x": 8}


def test_disk_seek_curve_and_sequential_is_cheap() -> None:
    d = _disk()
    assert d.seek_us(0) == 0
    assert d.seek_us(1) == 800
    assert d.seek_us(d.p.tracks - 1) == d.p.seek_max_us
    assert d.seek_us(10) < d.seek_us(500) < d.seek_us(1999)
    rand = d.access(0, 1500, 1, write=True)
    seq = d.access(rand.done_us, 1500, 1, write=True, sequential=True)
    assert seq.done_us - seq.start_us == 27  # solo transferencia: sin seek ni rotacion
    assert rand.done_us - rand.start_us > 10_000


def test_poisson_arrivals_are_deterministic_and_increasing() -> None:
    a = poisson_arrivals(1000, 50_000, 7)
    b = poisson_arrivals(1000, 50_000, 7)
    assert np.array_equal(a, b)
    assert (np.diff(a) >= 1).all()


def _run_lsm(n: int, crash_at: int | None = None) -> tuple[LsmTree, Simulation]:
    # memtable pequena para forzar varios flushes y una compaction con pocos eventos
    lsm = LsmTree(LsmParams(memtable_bytes=512 * 2000, record_bytes=512), _disk(), _disk())
    sim = Simulation(3)
    sim.add(lsm)
    w = Workload.random_writes("lsm", n, 50_000, 3)
    sim.add(w)
    sim.schedule_at(w.first_us, "workload", "next")
    if crash_at is not None:
        sim.schedule_at(crash_at, "lsm", "power.loss")
    sim.run_until()
    return lsm, sim


def test_lsm_flush_and_compaction_happen_in_order() -> None:
    lsm, sim = _run_lsm(9000)
    tr = sim.trace
    assert lsm.flushes == 4 and lsm.compactions >= 1
    f_start = tr.first("lsm.flush.start")
    f_end = tr.first("lsm.flush.end")
    c_start = tr.first("lsm.compaction.start")
    assert f_start is not None and f_end is not None and c_start is not None
    assert f_start < f_end < c_start
    assert lsm.level_count(0) == 0 and lsm.level_count(1) == 1
    assert lsm.bytes_physical > lsm.bytes_logical  # amplificacion de escritura real


def test_lsm_recovery_replays_exactly_the_durable_wal() -> None:
    """Invariante: tras recovery, las claves confirmadas por el WAL son las previas al crash."""
    lsm, sim = _run_lsm(9000, crash_at=300_000)
    assert lsm.durable_before_crash, "el crash debe ocurrir con WAL durable"
    assert sorted(lsm.recovered_keys) == sorted(lsm.durable_before_crash)
    assert lsm.state == 0 and lsm.recovery_us > 0
    ev = sim.trace.events(["power.loss"])
    assert ev.b[0] >= 0  # escrituras no sincronizadas perdidas (politica batch)


def test_lsm_ignores_stale_events_after_power_loss() -> None:
    # crash durante un flush: el flush en vuelo no debe completarse
    lsm, sim = _run_lsm(9000, crash_at=120_000)
    assert lsm.state == 0
    assert sim.trace.events(["wal.replay.end"]).t_us.size == 1


def test_btree_random_writes_are_seek_bound_and_amplified() -> None:
    bt = BTree(BTreeParams(record_bytes=512), _disk())
    sim = Simulation(5)
    sim.add(bt)
    w = Workload.random_writes("btree", 2000, 50_000, 5)
    sim.add(w)
    sim.schedule_at(w.first_us, "workload", "next")
    sim.run_until()
    assert bt.puts == 2000
    per_put_ms = bt.busy_us_total / bt.puts / 1000
    assert per_put_ms > 8  # un seek aleatorio medio ya cuesta ~8.5 ms
    assert bt.write_amp > 3  # pagina de 4 KiB por registro de 512 B


def test_simulation_is_deterministic() -> None:
    _, s1 = _run_lsm(3000)
    _, s2 = _run_lsm(3000)
    assert s1.trace.trace_hash() == s2.trace.trace_hash()
