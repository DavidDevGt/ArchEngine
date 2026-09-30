"""Episodios 02-04 (docs/13): propiedades de los modelos, determinismo y escenas."""

from __future__ import annotations

import numpy as np
import pytest

from archengine.pipeline.film import synthesize_audio
from archengine.pipeline.preview import render_preview, resolve_scene
from archengine.scenes import ep02_cache_aside as ep02
from archengine.scenes import ep03_message_queue as ep03
from archengine.scenes import ep04_load_balancer as ep04

S = 1_000_000


# --- Ep. 02: cache-aside -----------------------------------------------------------------------


@pytest.fixture(scope="module")
def cache_sim() -> ep02.EpisodeSim:
    return ep02.get_episode_sim(42)


def test_cache_warms_up_and_flush_dips_the_hit_ratio(cache_sim: ep02.EpisodeSim) -> None:
    tr = cache_sim.cached
    cold = ep02.window_hit_ratio(tr, 2 * S, 2 * S)
    warm = ep02.window_hit_ratio(tr, 78 * S, 10 * S)
    after_flush = ep02.window_hit_ratio(tr, 82 * S, 2 * S)
    assert warm > cold + 0.15
    assert after_flush < warm - 0.10


def test_hit_is_orders_of_magnitude_cheaper_than_miss(cache_sim: ep02.EpisodeSim) -> None:
    m = ep02.metrics(cache_sim)
    assert m.hit_ms < 1.0  # RAM + red
    assert m.miss_ms > 10 * m.hit_ms  # seek + rotacion del disco mecanico


def test_cache_never_exceeds_capacity_and_evicts(cache_sim: ep02.EpisodeSim) -> None:
    sizes = cache_sim.cached._series_v["cache.size"]
    assert max(sizes) == ep02.PARAMS.capacity
    assert cache_sim.evict_t.size > 0 and cache_sim.expire_t.size > 0
    assert cache_sim.flush_v.size == 1


def test_without_cache_the_disk_saturates(cache_sim: ep02.EpisodeSim) -> None:
    m = ep02.metrics(cache_sim)
    assert m.lat_bare_ms > 50 * m.lat_cached_ms
    assert cache_sim.bare.value_at("db.inflight", 100 * S) > 100


def test_cache_episode_is_deterministic(cache_sim: ep02.EpisodeSim) -> None:
    assert ep02._run(42, ep02.PARAMS.capacity, True).trace_hash() == cache_sim.cached.trace_hash()


# --- Ep. 03: cola de mensajes ------------------------------------------------------------------


@pytest.fixture(scope="module")
def queue_sim() -> ep03.EpisodeSim:
    return ep03.get_episode_sim(42)


def test_queue_conservation_and_capacity(queue_sim: ep03.EpisodeSim) -> None:
    tr = queue_sim.trace
    assert max(tr._series_v["q.depth"]) == ep03.PARAMS.capacity
    for t in range(0, 60, 3):
        at = t * S
        assert tr.value_at("q.enq", at) - tr.value_at("q.deq", at) == tr.value_at("q.depth", at)


def test_drop_policy_loses_messages_but_block_does_not(queue_sim: ep03.EpisodeSim) -> None:
    tr = queue_sim.trace
    assert tr.value_at("q.dropped", ep03.BLOCK_AT_US) > 0
    assert tr.value_at("q.dropped", 60 * S) == tr.value_at("q.dropped", ep03.BLOCK_AT_US)
    assert tr.value_at("q.policy", 30 * S) == 1


def test_backpressure_throttles_the_producer_to_the_consumer_rate(
    queue_sim: ep03.EpisodeSim,
) -> None:
    st = ep03.phase_stats(queue_sim.trace, *ep03.PHASES["block"])
    assert 8.0 <= st.offered_per_s <= 11.5  # ~ capacidad del consumidor (10 msg/s), no 16
    slow = ep03.phase_stats(queue_sim.trace, *ep03.PHASES["slow"])
    assert slow.offered_per_s < 4.0 and slow.max_wait_s > 3 * st.max_wait_s


def test_queue_episode_is_deterministic(queue_sim: ep03.EpisodeSim) -> None:
    assert ep03._simulate(42).trace_hash() == queue_sim.trace.trace_hash()


# --- Ep. 04: load balancer ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def lb_sim() -> ep04.EpisodeSim:
    return ep04.get_episode_sim(42)


def test_least_connections_beats_round_robin_with_a_slow_node(lb_sim: ep04.EpisodeSim) -> None:
    m = ep04.metrics(lb_sim)
    assert m.p95_rr_ms > 2 * m.p95_lc_ms
    assert m.errors_lc == 0


def test_failover_is_detected_by_health_checks_only(lb_sim: ep04.EpisodeSim) -> None:
    m = ep04.metrics(lb_sim)
    p = ep04.PARAMS
    assert lb_sim.crash_us == ep04.CRASH_AT_US
    assert 0 < m.detect_s <= (p.fail_threshold + 1) * p.health_interval_us / S
    assert lb_sim.mark_up_us > ep04.RECOVER_AT_US
    assert m.errors_failover > 0  # peticiones perdidas mientras el nodo muerto seguia en rotacion


def test_no_traffic_reaches_the_node_while_it_is_out_of_the_pool(lb_sim: ep04.EpisodeSim) -> None:
    routes = lb_sim.trace.events(["lb.route"])
    b = routes.t_us[routes.a == ep04.CRASHED]
    assert not ((b > lb_sim.mark_down_us) & (b < lb_sim.mark_up_us)).any()


def test_lb_episode_is_deterministic(lb_sim: ep04.EpisodeSim) -> None:
    assert ep04._simulate(42).trace_hash() == lb_sim.trace.trace_hash()


# --- escenas -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("scene_id", "times"),
    [("ep02", (3.0, 38.0, 55.0)), ("ep03", (5.0, 16.0, 55.0)), ("ep04", (5.0, 28.0, 56.0))],
)
def test_scene_renders_frames(scene_id: str, times: tuple[float, ...]) -> None:
    for t in times:
        res = render_preview(scene_id, t)
        assert (res.width, res.height) == (1080, 1920)


@pytest.mark.parametrize("scene_id", ["ep02", "ep03", "ep04"])
def test_scene_audio_is_finite_and_not_silent(scene_id: str) -> None:
    scene = resolve_scene(scene_id)
    assert scene.duration_s == 60.0 and scene.fps == 30
    pcm = synthesize_audio(scene, 900)  # 30 s
    assert pcm.shape == (1_440_000, 2)
    assert np.isfinite(pcm).all() and float(np.abs(pcm).max()) > 0.05
