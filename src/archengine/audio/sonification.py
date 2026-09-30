"""Sonificacion procedural determinista con NumPy a 48 kHz estereo (docs/04, PDR §4.4).

El audio se deriva de eventos de la trace (ya mapeados al tiempo de video) mediante una tabla
``SOUND_MAP`` ``kind -> bloque``. Un evento en ``t_us`` cae en la muestra
``(t_us * fs + 500_000) // 1_000_000`` (precision de muestra, FR-17). Solo NumPy; fases
acumuladas en float64; todo el azar sale de ``core.rng``.
"""

from __future__ import annotations

import math
import wave
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from archengine.core.rng import deterministic_rng
from archengine.core.timebase import DEFAULT_AUDIO_SAMPLE_RATE, time_us_to_sample

FS = DEFAULT_AUDIO_SAMPLE_RATE
GLOBAL_GAIN = 0.55  # constante: sin normalizacion dependiente de datos
PEAK = 10 ** (-1.0 / 20.0)  # -1 dBFS

# Escala pentatonica menor de La (Hz)
SCALE_HZ = (110.0, 130.81, 146.83, 164.81, 196.0, 220.0, 261.63, 293.66, 329.63, 392.0)
ARP_PATTERN = (0, 2, 4, 5, 7, 9, 7, 5, 4, 2)

# Tabla de mapeo evento -> bloque de sintesis (versionada, docs/04 §4)
SOUND_MAP: Mapping[str, str] = {
    "bench.tick": "click",
    "disk.seek": "seek_tone",
    "memtable.put": "arpeggio",
    "lsm.flush.start": "flush_sweep",
    "lsm.compaction.start": "filter_sweep",
    "power.loss": "power_loss",
    "wal.replay.end": "restart_pulse",
    "node.up": "drone",
    "node.down": "drone",
    "scene.end": "final_chord",
    # Episodios 02-04 (docs/13): arquitecturas simples
    "cache.hit": "hit_blip",
    "cache.miss": "miss_thud",
    "cache.flush": "alert_burst",
    "queue.put": "tick",
    "msg.done": "soft_note",
    "queue.drop": "noise_tick",
    "queue.block": "miss_thud",
    "lb.route": "backend_blip",
    "req.error": "noise_tick",
    "sys.alert": "alert_burst",
    "sys.recover": "restart_pulse",
}
SOUND_MAP_VERSION = 2


@dataclass(frozen=True)
class SoundEvents:
    """Eventos por ``kind`` en tiempo de video: (t_us, a, b) columnares."""

    by_kind: Mapping[str, tuple[np.ndarray, np.ndarray, np.ndarray]]

    def get(self, kind: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        e = np.empty(0, dtype=np.int64)
        return self.by_kind.get(kind, (e, e, e))


def _add(buf: np.ndarray, start: int, sig: np.ndarray) -> None:
    """Suma ``sig`` en ``buf`` desde ``start`` recortando a los limites (overlap-add)."""
    if start >= buf.shape[0] or start + sig.shape[0] <= 0:
        return
    lo = max(0, -start)
    hi = min(sig.shape[0], buf.shape[0] - start)
    buf[start + lo : start + hi] += sig[lo:hi]


def _expenv(n: int, tau_s: float, attack_s: float = 0.002) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / FS
    return np.exp(-t / tau_s) * np.minimum(1.0, t / max(attack_s, 1e-6))


def _lowpass_fft(x: np.ndarray, cutoff_hz: float) -> np.ndarray:
    """Paso bajo de un polo por convolucion FFT (sin SciPy, docs/04 §3)."""
    a = math.exp(-2.0 * math.pi * cutoff_hz / FS)
    m = max(8, int(10.0 / (1.0 - a)))
    h = (1.0 - a) * a ** np.arange(m, dtype=np.float64)
    nfft = 1 << (x.shape[0] + m - 1).bit_length()
    y = np.fft.irfft(np.fft.rfft(x, nfft) * np.fft.rfft(h, nfft), nfft)
    return np.asarray(y[: x.shape[0]], dtype=np.float64)


def _note(freq: float, dur_s: float, tau_s: float) -> np.ndarray:
    n = int(dur_s * FS)
    t = np.arange(n, dtype=np.float64) / FS
    sig = np.sin(2 * math.pi * freq * t) + 0.3 * np.sin(2 * math.pi * 2 * freq * t)
    return np.asarray(sig * _expenv(n, tau_s, 0.003), dtype=np.float64)


_CLICK_CACHE: dict[float, np.ndarray] = {}


def _click(freq: float) -> np.ndarray:
    """Onda cuadrada aditiva (parciales < Nyquist, sin aliasing) con decaimiento exponencial."""
    if freq not in _CLICK_CACHE:
        n = int(0.012 * FS)
        t = np.arange(n, dtype=np.float64) / FS
        sig = np.zeros(n)
        k = 1
        while freq * k < FS / 2 and k <= 15:
            sig += np.sin(2 * math.pi * freq * k * t) / k
            k += 2
        _CLICK_CACHE[freq] = (4 / math.pi) * sig * _expenv(n, 0.004, 0.001)
    return _CLICK_CACHE[freq]


def _chirp(f0: float, f1: float, dur_s: float, harmonics: int = 3) -> np.ndarray:
    """Barrido exponencial de frecuencia; fase integrada con cumsum en float64."""
    n = max(2, int(dur_s * FS))
    f = f0 * (f1 / f0) ** (np.arange(n, dtype=np.float64) / (n - 1))
    phase = 2 * math.pi * np.cumsum(f) / FS
    sig = sum(np.sin(h * phase) / h for h in range(1, harmonics + 1))
    env = np.minimum(1.0, np.arange(n) / (0.01 * FS)) * np.minimum(
        1.0, (n - np.arange(n)) / (0.05 * FS)
    )
    return np.asarray(sig * env, dtype=np.float64)


def _filter_sweep(n: int, rng: np.random.Generator, f0: float, f1: float) -> np.ndarray:
    """Ruido pasa-banda resonante con frecuencia central barrida (STFT por bloques, Hann 50 %)."""
    blk = 1024
    hop = blk // 2
    noise = rng.standard_normal(n + blk)
    win = np.hanning(blk)
    out = np.zeros(n + blk)
    freqs = np.fft.rfftfreq(blk, 1.0 / FS)
    n_blocks = max(1, n // hop)
    for i in range(n_blocks):
        fc = f0 * (f1 / f0) ** (i / max(1, n_blocks - 1))
        gain = np.exp(-0.5 * ((freqs - fc) / (0.12 * fc + 40.0)) ** 2)
        seg = noise[i * hop : i * hop + blk] * win
        out[i * hop : i * hop + blk] += np.fft.irfft(np.fft.rfft(seg) * gain, blk) * win
    return np.asarray(out[:n] * 6.0, dtype=np.float64)


def _window_groups(t_us: np.ndarray, window_us: int) -> tuple[np.ndarray, np.ndarray]:
    """Agrupa eventos densos por ventana: (indices de ventana, conteo)."""
    if t_us.size == 0:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)
    idx, cnt = np.unique(t_us // window_us, return_counts=True)
    return idx, cnt


def _sample(t_us: int) -> int:
    return time_us_to_sample(max(0, int(t_us)), FS)


def render_pcm(events: SoundEvents, duration_us: int, seed: int = 42) -> np.ndarray:
    """Renderiza el PCM maestro ``(n, 2)`` float32 de ``duration_us`` exactos."""
    n = time_us_to_sample(duration_us, FS)
    rng = deterministic_rng(seed, "audio.noise")
    bus = np.zeros(n, dtype=np.float64)
    drone = np.zeros(n, dtype=np.float64)

    # 1. Benchmark: clicks ritmicos (densidad proporcional a la tasa de escrituras)
    t, _, _ = events.get("bench.tick")
    for ti in t:
        _add(bus, _sample(int(ti)), 0.22 * _click(1800.0))

    # 2. B-Tree: tono grave saturado por seeks; ventanas dominadas por seeks largos => silencio
    t, a, _ = events.get("disk.seek")
    if t.size:
        win_us = 20_000
        widx = t // win_us
        for w in np.unique(widx):
            m = widx == w
            mean_d = float(a[m].mean())
            long_frac = float((a[m] >= 600).mean())
            if long_frac > 0.6 and (int(w) % 3 == 0):
                continue  # I/O wait: silencio forzado
            f = 55.0 + 0.045 * mean_d
            nn = int(win_us * FS / 1e6)
            tt = np.arange(nn, dtype=np.float64) / FS
            tone = np.tanh(3.5 * np.sin(2 * math.pi * f * tt + 0.7 * float(w % 5)))
            env = np.minimum(1.0, np.arange(nn) / (0.002 * FS)) * np.minimum(
                1.0, (nn - np.arange(nn)) / (0.002 * FS)
            )
            _add(bus, _sample(int(w) * win_us), 0.20 * tone * env)

    # 3. LSM: arpegio limpio, una nota por ventana de 62.5 ms con escrituras
    t, _, _ = events.get("memtable.put")
    widx_arr, cnt = _window_groups(t, 62_500)
    for w, c in zip(widx_arr, cnt, strict=True):
        f = SCALE_HZ[ARP_PATTERN[int(w) % len(ARP_PATTERN)]] * 2.0
        amp = 0.16 + 0.04 * min(1.0, math.log10(1 + float(c)) / 3.0)
        _add(bus, _sample(int(w) * 62_500), amp * _note(f, 0.30, 0.10))

    # 4. Flush: tono armonico descendente; Compaction: barrido de filtro resonante
    t, _, _ = events.get("lsm.flush.start")
    for ti in t:
        _add(bus, _sample(int(ti)), 0.25 * _chirp(880.0, 196.0, 0.9))
    t, _, _ = events.get("lsm.compaction.start")
    t_end, _, _ = events.get("lsm.compaction.end")
    for i, ti in enumerate(t):
        stop = int(t_end[i]) if i < t_end.size else int(ti) + 4_000_000
        nn = max(1, _sample(stop) - _sample(int(ti)))
        _add(bus, _sample(int(ti)), 0.30 * _filter_sweep(nn, rng, 300.0, 4200.0))

    # 5. PowerLoss: ruido blanco subito + impacto grave; corte de drone via ducking
    duck = np.ones(n, dtype=np.float64)
    t, _, _ = events.get("power.loss")
    for ti in t:
        s0 = _sample(int(ti))
        nn = int(0.8 * FS)
        noise = _lowpass_fft(rng.standard_normal(nn), 7000.0) * _expenv(nn, 0.25, 0.001)
        _add(bus, s0, 0.55 * noise)
        tt = np.arange(int(0.5 * FS), dtype=np.float64) / FS
        _add(bus, s0, 0.45 * np.sin(2 * math.pi * 55.0 * tt) * _expenv(tt.size, 0.15, 0.001))
        rel = np.arange(n - s0, dtype=np.float64) / FS
        duck[s0:] *= 1.0 - 0.85 * np.exp(-rel / 0.3)

    # 6. Reinicio limpio tras replay del WAL
    t, _, _ = events.get("wal.replay.end")
    for ti in t:
        s0 = _sample(int(ti))
        _add(bus, s0, 0.30 * _note(660.0, 0.6, 0.25))
        _add(bus, s0 + int(0.12 * FS), 0.30 * _note(990.0, 0.6, 0.25))

    # 7. Zumbido de cluster: senoidales por nodo con rampas de 30 ms (fase continua)
    ups = np.zeros((4, n), dtype=np.float64)
    node_up_t, node_up_a, _ = events.get("node.up")
    node_dn_t, node_dn_a, _ = events.get("node.down")
    for node in range(4):
        pts = sorted(
            [
                (_sample(int(ti)), 1.0)
                for ti, ai in zip(node_up_t, node_up_a, strict=True)
                if ai == node
            ]
            + [
                (_sample(int(ti)), 0.0)
                for ti, ai in zip(node_dn_t, node_dn_a, strict=True)
                if ai == node
            ]
        )
        if not pts:
            continue
        xs, ys = [0], [0.0]
        ramp = int(0.03 * FS)
        for s0, v in pts:
            xs.extend([max(xs[-1], s0), max(xs[-1], s0) + ramp])
            ys.extend([ys[-1], v])
        ups[node] = np.interp(np.arange(n), xs, ys)
    tt = np.arange(n, dtype=np.float64) / FS
    for node in range(4):
        if ups[node].any():
            f = SCALE_HZ[node * 2] * 0.5
            drone += ups[node] * 0.07 * np.sin(2 * math.pi * f * tt + 0.9 * node)
    bus += drone * duck

    # 8. Acorde final sostenido con fade out lineal
    t, _, _ = events.get("scene.end")
    for ti in t:
        s0 = _sample(int(ti))
        m = n - s0
        if m <= 0:
            continue
        tc = np.arange(m, dtype=np.float64) / FS
        chord = sum(np.sin(2 * math.pi * f * tc) for f in (110.0, 164.81, 220.0, 277.18, 329.63))
        fade = np.clip(1.0 - tc / (m / FS), 0.0, 1.0)
        _add(bus, s0, 0.10 * chord * np.minimum(1.0, tc / 0.3) * fade)

    _render_architecture_events(events, bus, seed)

    bus *= GLOBAL_GAIN
    out = np.clip(np.tanh(bus), -PEAK, PEAK).astype(np.float32)
    return np.stack([out, out], axis=1)


def _noise_burst(rng: np.random.Generator, dur_s: float, tau_s: float, cutoff: float) -> np.ndarray:
    nn = int(dur_s * FS)
    return np.asarray(
        _lowpass_fft(rng.standard_normal(nn), cutoff) * _expenv(nn, tau_s, 0.001), dtype=np.float64
    )


def _thud(freq: float, dur_s: float = 0.12) -> np.ndarray:
    n = int(dur_s * FS)
    t = np.arange(n, dtype=np.float64) / FS
    return np.asarray(np.tanh(2.0 * np.sin(2 * math.pi * freq * t)) * _expenv(n, 0.05, 0.002))


def _render_architecture_events(events: SoundEvents, bus: np.ndarray, seed: int) -> None:
    """Bloques de los episodios 02-04; usa su propio substream para no alterar el Ep. 01."""
    rng = deterministic_rng(seed, "audio.noise.arch")

    # Cache: aciertos = destellos agudos limpios; fallos = golpes graves (seek)
    t, _, _ = events.get("cache.hit")
    widx, _ = _window_groups(t, 100_000)
    for w in widx:
        f = SCALE_HZ[ARP_PATTERN[int(w) % len(ARP_PATTERN)]] * 4.0
        _add(bus, _sample(int(w) * 100_000), 0.07 * _note(f, 0.12, 0.04))
    t, _, _ = events.get("cache.miss")
    widx, _ = _window_groups(t, 120_000)
    for w in widx:
        _add(bus, _sample(int(w) * 120_000), 0.17 * _thud(70.0))

    # Cola: ticks al encolar, notas suaves al consumir, ruido al perder, golpe al bloquear
    t, _, _ = events.get("queue.put")
    for ti in t:
        _add(bus, _sample(int(ti)), 0.07 * _click(1200.0))
    t, _, _ = events.get("msg.done")
    for ti in t:
        _add(bus, _sample(int(ti)), 0.06 * _note(SCALE_HZ[4] * 2.0, 0.15, 0.06))
    t, _, _ = events.get("queue.drop")
    for ti in t:
        _add(bus, _sample(int(ti)), 0.22 * _noise_burst(rng, 0.08, 0.03, 5000.0))
    t, _, _ = events.get("queue.block")
    widx, _ = _window_groups(t, 250_000)
    for w in widx:
        _add(bus, _sample(int(w) * 250_000), 0.15 * _thud(55.0, 0.2))

    # Balanceador: una nota por backend (pentatonica) agrupada en ventanas de 60 ms
    t, a, _ = events.get("lb.route")
    if t.size:
        widx_all = t // 60_000
        for node in np.unique(a):
            for w in np.unique(widx_all[a == node]):
                f = SCALE_HZ[(int(node) * 2 + 3) % len(SCALE_HZ)] * 2.0
                _add(bus, _sample(int(w) * 60_000), 0.08 * _note(f, 0.16, 0.05))
    t, _, _ = events.get("req.error")
    widx, _ = _window_groups(t, 100_000)
    for w in widx:
        _add(bus, _sample(int(w) * 100_000), 0.2 * _noise_burst(rng, 0.09, 0.035, 4500.0))

    # Fallos de nodo / cache: ruido + impacto grave; recuperacion: pulso de reinicio
    for kind in ("sys.alert", "cache.flush"):
        t, _, _ = events.get(kind)
        for ti in t:
            s0 = _sample(int(ti))
            _add(bus, s0, 0.45 * _noise_burst(rng, 0.6, 0.2, 7000.0))
            _add(bus, s0, 0.35 * _thud(55.0, 0.5))
    t, _, _ = events.get("sys.recover")
    for ti in t:
        s0 = _sample(int(ti))
        _add(bus, s0, 0.30 * _note(660.0, 0.6, 0.25))
        _add(bus, s0 + int(0.12 * FS), 0.30 * _note(990.0, 0.6, 0.25))

    # Acorde final de los episodios que lo piden (Ep. 01 lo trata aparte)
    t, _, _ = events.get("arch.end")
    for ti in t:
        s0 = _sample(int(ti))
        m = bus.shape[0] - s0
        if m <= 0:
            continue
        tc = np.arange(m, dtype=np.float64) / FS
        chord = sum(np.sin(2 * math.pi * f * tc) for f in (110.0, 164.81, 220.0, 277.18, 329.63))
        fade = np.clip(1.0 - tc / (m / FS), 0.0, 1.0)
        _add(bus, s0, 0.10 * chord * np.minimum(1.0, tc / 0.3) * fade)


def pcm_to_s16(pcm: np.ndarray) -> np.ndarray:
    """Cuantiza a s16 little-endian sin dither (determinista)."""
    return np.asarray(np.rint(np.clip(pcm, -1.0, 1.0) * 32767.0), dtype="<i2")


def write_wav(path: str | Path, pcm: np.ndarray) -> None:
    """Escribe PCM estereo s16 en un WAV minimo (ADR-0005)."""
    s16 = pcm_to_s16(pcm)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(FS)
        w.writeframes(s16.tobytes())
