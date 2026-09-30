"""Aceptacion del Episodio 01 (docs/07 §3-§4): eventos por segmento, fronteras y metricas."""

from __future__ import annotations

import numpy as np
import pytest

from archengine.scenes import ep01_lsm_vs_btree as ep

S = 1_000_000


@pytest.fixture(scope="module")
def sim() -> ep.EpisodeSim:
    return ep.get_episode_sim(42)


def _video_times(sim: ep.EpisodeSim, world: str, kind: str) -> np.ndarray:
    tr, tmap = (sim.lsm, sim.lsm_map) if world == "lsm" else (sim.btree, sim.btree_map)
    return tmap.video_at(tr.events([kind]).t_us)


def test_segment_boundaries_are_exact_frame_multiples() -> None:
    for start_s, end_s, _, _ in ep.SEGMENTS:
        assert (start_s * 30) == round(start_s * 30)
        assert end_s > start_s
    assert [s * 30 for s in (5, 15, 30, 45, 55)] == [150, 450, 900, 1350, 1650]


def test_first_flush_starts_within_segment_4(sim: ep.EpisodeSim) -> None:
    t = _video_times(sim, "lsm", "lsm.flush.start")
    assert 30 * S <= t[0] < 45 * S


def test_each_segment_has_its_trace_events(sim: ep.EpisodeSim) -> None:
    def any_in(world: str, kind: str, lo: int, hi: int) -> bool:
        t = _video_times(sim, world, kind)
        return bool(((t >= lo * S) & (t < hi * S)).any())

    assert any_in("lsm", "bench.tick", 0, 5)  # 1 benchmark
    assert any_in("btree", "disk.seek", 5, 15)  # 2 B-Tree: seeks
    assert any_in("lsm", "memtable.put", 15, 30)  # 3 LSM: MemTable
    assert any_in("lsm", "lsm.flush.start", 30, 45)  # 4 flush
    assert any_in("lsm", "lsm.compaction.start", 30, 45)  # 4 compaction
    assert any_in("lsm", "power.loss", 45, 55)  # 5 crash
    assert any_in("lsm", "wal.replay.end", 45, 55)  # 5 replay
    t_all = np.concatenate([_video_times(sim, "lsm", "memtable.put")])
    assert not ((t_all >= 55 * S) & (t_all < 60 * S)).any()  # 6: sin eventos nuevos


def test_compaction_finishes_before_power_loss(sim: ep.EpisodeSim) -> None:
    assert sim.lsm.first("lsm.compaction.end") < sim.lsm.first("power.loss")  # type: ignore[operator]


def test_recovery_is_fast_relative_to_the_segment(sim: ep.EpisodeSim) -> None:
    m = sim.metrics
    assert m.replay_records > 0
    assert m.replay_us < 1_000_000  # << segmento de 10 s; medido, no asumido


def test_benchmark_writes_and_engine_trade_offs(sim: ep.EpisodeSim) -> None:
    m = sim.metrics
    assert sim.btree.value_at("btree.puts", sim.btree.end_us) == ep.BENCH_WRITES
    assert m.lsm_writes_per_s > 100 * m.btree_writes_per_s  # emergente del modelo de disco
    assert m.btree_write_amp > m.lsm_write_amp  # pagina de 4 KiB por registro de 512 B
    assert m.lsm_read_amp_peak > m.btree_read_pages_per_op  # costo de leer en un LSM sin compactar


def test_time_maps_are_monotone_and_cover_60_seconds(sim: ep.EpisodeSim) -> None:
    for tmap in (sim.lsm_map, sim.btree_map):
        assert tmap.knots[0][0] == 0 and tmap.knots[-1][0] == 60 * S
        vals = [tmap.sim_at(v * S // 4) for v in range(0, 241)]
        assert vals == sorted(vals)


def test_state_reflects_simulation_not_tweens(sim: ep.EpisodeSim) -> None:
    # MemTable llena cerca del flush y vacia tras el PowerLoss: el render lee la trace
    t_flush = sim.lsm.first("lsm.flush.start")
    assert t_flush is not None
    assert sim.lsm.value_at("lsm.mem_bytes", t_flush - 1) >= 0.99 * 67_108_864
    t_loss = sim.lsm.first("power.loss")
    assert t_loss is not None
    assert sim.lsm.value_at("lsm.mem_bytes", t_loss) == 0
    assert sim.lsm.value_at("lsm.state", t_loss) == 1


def test_scene_builds_and_renders_every_segment() -> None:
    from archengine.pipeline.preview import render_preview

    for t in (0.0, 10.0, 22.0, 36.0, 48.5, 51.0, 58.0):
        res = render_preview("ep01", t)
        assert res.width == 1080 and res.height == 1920
        assert res.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
