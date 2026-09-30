"""Sonificacion: duracion exacta, alineacion de eventos, determinismo y espectro (docs/04 §7)."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from archengine.audio import sonification as so
from archengine.core.timebase import time_us_to_sample

S = 1_000_000


def _events(**kinds: tuple[list[int], list[int], list[int]]) -> so.SoundEvents:
    by = {
        k.replace("_", "."): (
            np.asarray(v[0], dtype=np.int64),
            np.asarray(v[1], dtype=np.int64),
            np.asarray(v[2], dtype=np.int64),
        )
        for k, v in kinds.items()
    }
    return so.SoundEvents(by)


def test_duration_is_exact_and_output_is_stereo() -> None:
    pcm = so.render_pcm(so.SoundEvents({}), 60 * S, 1)
    assert pcm.shape == (2_880_000, 2)
    assert pcm.dtype == np.float32


def test_render_is_deterministic() -> None:
    ev = _events(power_loss=([S], [0], [0]), bench_tick=([100_000, 300_000], [1, 2], [0, 0]))
    a = so.render_pcm(ev, 3 * S, 9)
    b = so.render_pcm(ev, 3 * S, 9)
    assert np.array_equal(a, b)


def test_click_energy_aligned_to_event_sample() -> None:
    t_us = 500_000
    pcm = so.render_pcm(_events(bench_tick=([t_us], [1], [0])), S, 1)[:, 0]
    start = time_us_to_sample(t_us)
    assert np.abs(pcm[: start - 1]).max() == 0.0  # silencio antes del evento
    peak = int(np.argmax(np.abs(pcm)))
    assert start <= peak <= start + int(0.004 * so.FS)


def test_output_respects_peak_limit_and_has_no_aliasing() -> None:
    ev = _events(bench_tick=([S // 2, S], [1, 2], [0, 0]), scene_end=([0], [0], [0]))
    pcm = so.render_pcm(ev, 4 * S, 3)[:, 0]
    assert np.abs(pcm).max() <= so.PEAK + 1e-6
    spec = np.abs(np.fft.rfft(pcm)) ** 2
    freqs = np.fft.rfftfreq(pcm.size, 1 / so.FS)
    assert spec[freqs > 20_000].sum() < 1e-3 * spec.sum()


def test_node_down_silences_the_drone() -> None:
    ev = _events(node_up=([0], [0], [0]), node_down=([S], [0], [0]))
    pcm = so.render_pcm(ev, 2 * S, 1)[:, 0]
    assert np.sqrt((pcm[: so.FS // 2] ** 2).mean()) > 0.01
    assert np.abs(pcm[int(1.2 * so.FS) :]).max() < 1e-6


def test_wav_roundtrip(tmp_path: Path) -> None:
    pcm = so.render_pcm(_events(bench_tick=([1000], [1], [0])), S // 2, 1)
    so.write_wav(tmp_path / "a.wav", pcm)
    with wave.open(str(tmp_path / "a.wav")) as w:
        assert (w.getnchannels(), w.getframerate(), w.getnframes()) == (2, 48000, pcm.shape[0])
