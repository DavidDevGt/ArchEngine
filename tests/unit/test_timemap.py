import numpy as np
import pytest

from archengine.core.timebase import TimeMap


def test_piecewise_mapping_and_pause() -> None:
    m = TimeMap([(0, 0), (10, 100), (20, 100), (30, 400)])
    assert m.sim_at(5) == 50
    assert m.sim_at(15) == 100  # tramo plano: simulacion pausada
    assert m.sim_at(25) == 250
    assert m.sim_at(99) == 400


def test_inverse_maps_events_and_flags_outside() -> None:
    m = TimeMap([(0, 0), (10, 100), (20, 100), (30, 400)])
    v = m.video_at(np.asarray([0, 50, 100, 250, 400, 500]))
    assert v.tolist() == [0, 5, 10, 25, 30, -1]


def test_invalid_knots_are_rejected() -> None:
    with pytest.raises(ValueError):
        TimeMap([(0, 0), (0, 5)])
    with pytest.raises(ValueError):
        TimeMap([(0, 10), (5, 3)])
