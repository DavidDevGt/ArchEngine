"""Pruebas unitarias de generacion pseudoaleatoria determinista por substreams (ADR-0004)."""

import numpy as np

from archengine.core.rng import RNGManager, deterministic_rng


def test_deterministic_rng_reproducibility() -> None:
    rng1 = deterministic_rng(seed=42, name="grain")
    rng2 = deterministic_rng(seed=42, name="grain")

    vals1 = rng1.uniform(0.0, 1.0, size=10)
    vals2 = rng2.uniform(0.0, 1.0, size=10)

    np.testing.assert_array_equal(vals1, vals2)


def test_substream_isolation() -> None:
    rng_a1 = deterministic_rng(seed=100, name="stream_a")
    rng_b = deterministic_rng(seed=100, name="stream_b")
    rng_a2 = deterministic_rng(seed=100, name="stream_a")

    # Consumir valores de stream_b
    _ = rng_b.integers(0, 1000, size=50)

    # stream_a debe producir exactamente la misma secuencia
    vals_a1 = rng_a1.integers(0, 1000, size=20)
    vals_a2 = rng_a2.integers(0, 1000, size=20)
    np.testing.assert_array_equal(vals_a1, vals_a2)


def test_seed_difference() -> None:
    rng1 = deterministic_rng(seed=1, name="node")
    rng2 = deterministic_rng(seed=2, name="node")

    vals1 = rng1.integers(0, 100, size=10)
    vals2 = rng2.integers(0, 100, size=10)
    assert not np.array_equal(vals1, vals2)


def test_rng_manager_streams() -> None:
    mgr = RNGManager(seed=123)
    s1 = mgr.stream("component_1")
    s2 = mgr.stream("component_2")
    v1 = s1.integers(0, 50, size=5)
    v2 = s2.integers(0, 50, size=5)
    assert len(v1) == 5
    assert len(v2) == 5
