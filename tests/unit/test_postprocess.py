"""Pruebas unitarias de filtros post-proceso: viñeta y grano (FR-15)."""

import numpy as np

from archengine.render.postprocess import PostProcessor


def test_vignette_attenuates_corners() -> None:
    w, h = 200, 200
    post = PostProcessor(width=w, height=h, vignette_strength=0.5, grain_intensity=0.0)

    # Imagen plana gris uniforme
    buf = np.full((h, w, 3), 200, dtype=np.uint8)
    res = post.apply(buf, k=0)

    # El centro (100, 100) debe estar menos atenuado que las esquinas (0, 0)
    center_val = int(res[100, 100, 0])
    corner_val = int(res[0, 0, 0])
    assert center_val > corner_val


def test_analog_grain_determinism_and_bounds() -> None:
    w, h = 100, 100
    post = PostProcessor(width=w, height=h, grain_intensity=8.0)

    buf = np.full((h, w, 3), 128, dtype=np.uint8)

    # Mismo k debe producir array identico byte a byte
    run1 = post.apply(buf.copy(), k=42)
    run2 = post.apply(buf.copy(), k=42)
    np.testing.assert_array_equal(run1, run2)

    # Diferente k debe variar el patron de grano
    run3 = post.apply(buf.copy(), k=43)
    assert not np.array_equal(run1, run3)

    # Verificacion de limites uint8
    assert np.all(run1 >= 0)
    assert np.all(run1 <= 255)
