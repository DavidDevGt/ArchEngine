"""Pruebas unitarias de timebase (Invariante 8, ADR-0002)."""

import pytest

from archengine.core.timebase import (
    DEFAULT_AUDIO_SAMPLE_RATE,
    DEFAULT_FPS,
    frame_to_time_us,
    sample_to_time_us,
    seconds_to_time_us,
    sim_to_video,
    time_us_to_frame,
    time_us_to_sample,
    time_us_to_seconds,
    video_to_sim,
)


def test_frame_to_time_us_canonical_values() -> None:
    assert frame_to_time_us(0) == 0
    assert frame_to_time_us(30) == 1_000_000
    assert frame_to_time_us(150) == 5_000_000
    assert frame_to_time_us(1800) == 60_000_000


def test_time_us_to_frame_roundtrip() -> None:
    fps = DEFAULT_FPS
    for k in range(0, 1800, 15):
        t_us = frame_to_time_us(k, fps=fps)
        k_back = time_us_to_frame(t_us, fps=fps)
        assert k == k_back


def test_timebase_monotonicity() -> None:
    prev_t = -1
    for k in range(100):
        t_us = frame_to_time_us(k)
        assert t_us > prev_t
        prev_t = t_us


def test_seconds_conversions() -> None:
    assert seconds_to_time_us(0.0) == 0
    assert seconds_to_time_us(1.5) == 1_500_000
    assert seconds_to_time_us(60.0) == 60_000_000

    assert time_us_to_seconds(0) == 0.0
    assert time_us_to_seconds(1_500_000) == 1.5
    assert time_us_to_seconds(60_000_000) == 60.0


def test_audio_sample_alignment() -> None:
    sr = DEFAULT_AUDIO_SAMPLE_RATE
    # 1 segundo exacto = 48000 muestras
    assert time_us_to_sample(1_000_000, sr) == 48000
    assert sample_to_time_us(48000, sr) == 1_000_000

    # 0 segundos = muestra 0
    assert time_us_to_sample(0, sr) == 0
    assert sample_to_time_us(0, sr) == 0


def test_rational_sim_to_video_scaling() -> None:
    # 2x slow motion (scale_num=2, scale_den=1)
    t_vid = 1_000_000
    t_sim = video_to_sim(t_vid, scale_num=2, scale_den=1)
    assert t_sim == 2_000_000
    assert sim_to_video(t_sim, scale_num=2, scale_den=1) == t_vid


def test_invalid_parameters_raise_value_error() -> None:
    with pytest.raises(ValueError):
        frame_to_time_us(-1)
    with pytest.raises(ValueError):
        frame_to_time_us(0, fps=0)
    with pytest.raises(ValueError):
        time_us_to_frame(-10)
    with pytest.raises(ValueError):
        time_us_to_sample(-5)
    with pytest.raises(ValueError):
        time_us_to_sample(10, sample_rate=0)
    with pytest.raises(ValueError):
        seconds_to_time_us(-0.1)
