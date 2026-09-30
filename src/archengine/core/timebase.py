"""Conversion exacta cuadro <-> microsegundos (aritmetica entera, ADR-0002).

Proporciona la unica fuente de verdad para la conversion entre tiempo continuo,
reloj virtual discreto en microsegundos (µs), cuadros de video (k) y muestras de audio.
"""

from __future__ import annotations

from bisect import bisect_right
from itertools import pairwise

import numpy as np

DEFAULT_FPS: int = 30
DEFAULT_AUDIO_SAMPLE_RATE: int = 48000
MICROSECONDS_PER_SECOND: int = 1_000_000


def frame_to_time_us(k: int, fps: int = DEFAULT_FPS) -> int:
    """Convierte el indice de cuadro k al tiempo de video en microsegundos enteros.

    Formula formal (ADR-0002):
        t_us(k) = (k * 1_000_000) // fps
    """
    if fps <= 0:
        raise ValueError(f"fps debe ser positivo, recibido: {fps}")
    if k < 0:
        raise ValueError(f"El indice de cuadro k no puede ser negativo, recibido: {k}")
    return (k * MICROSECONDS_PER_SECOND) // fps


def time_us_to_frame(t_us: int, fps: int = DEFAULT_FPS) -> int:
    """Convierte un tiempo en microsegundos al indice de cuadro de video correspondiente.

    Formula formal (ADR-0002):
        k = (t_us * fps) // 1_000_000
    """
    if fps <= 0:
        raise ValueError(f"fps debe ser positivo, recibido: {fps}")
    if t_us < 0:
        raise ValueError(f"El tiempo t_us no puede ser negativo, recibido: {t_us}")
    return (t_us * fps) // MICROSECONDS_PER_SECOND


def seconds_to_time_us(t_seconds: float) -> int:
    """Convierte segundos en punto flotante a microsegundos enteros mediante redondeo."""
    if t_seconds < 0:
        raise ValueError(f"El tiempo en segundos no puede ser negativo, recibido: {t_seconds}")
    return round(t_seconds * MICROSECONDS_PER_SECOND)


def time_us_to_seconds(t_us: int) -> float:
    """Convierte microsegundos enteros a segundos en punto flotante."""
    if t_us < 0:
        raise ValueError(f"El tiempo t_us no puede ser negativo, recibido: {t_us}")
    return t_us / float(MICROSECONDS_PER_SECOND)


def time_us_to_sample(t_us: int, sample_rate: int = DEFAULT_AUDIO_SAMPLE_RATE) -> int:
    """Convierte microsegundos a indice de muestra de audio con redondeo al mas cercano.

    Formula formal (ADR-0002):
        sample = (t_us * sample_rate + 500_000) // 1_000_000
    """
    if sample_rate <= 0:
        raise ValueError(f"sample_rate debe ser positivo, recibido: {sample_rate}")
    if t_us < 0:
        raise ValueError(f"El tiempo t_us no puede ser negativo, recibido: {t_us}")
    return (t_us * sample_rate + (MICROSECONDS_PER_SECOND // 2)) // MICROSECONDS_PER_SECOND


def sample_to_time_us(sample: int, sample_rate: int = DEFAULT_AUDIO_SAMPLE_RATE) -> int:
    """Convierte indice de muestra de audio a microsegundos enteros."""
    if sample_rate <= 0:
        raise ValueError(f"sample_rate debe ser positivo, recibido: {sample_rate}")
    if sample < 0:
        raise ValueError(f"El indice de muestra no puede ser negativo, recibido: {sample}")
    return (sample * MICROSECONDS_PER_SECOND + (sample_rate // 2)) // sample_rate


def video_to_sim(
    t_vid_us: int,
    scale_num: int = 1,
    scale_den: int = 1,
    t_vid0_us: int = 0,
    t_sim0_us: int = 0,
) -> int:
    """Mapea tiempo de video a tiempo de simulacion con factor de escala racional.

    t_sim = t_sim0 + (t_vid - t_vid0) * (scale_num / scale_den)
    """
    if scale_num <= 0 or scale_den <= 0:
        raise ValueError("Los factores de escala deben ser enteros positivos")
    delta_vid = t_vid_us - t_vid0_us
    return t_sim0_us + (delta_vid * scale_num) // scale_den


def sim_to_video(
    t_sim_us: int,
    scale_num: int = 1,
    scale_den: int = 1,
    t_vid0_us: int = 0,
    t_sim0_us: int = 0,
) -> int:
    """Mapea tiempo de simulacion a tiempo de video con factor de escala racional.

    t_vid = t_vid0 + (t_sim - t_sim0) * (scale_den / scale_num)
    """
    if scale_num <= 0 or scale_den <= 0:
        raise ValueError("Los factores de escala deben ser enteros positivos")
    delta_sim = t_sim_us - t_sim0_us
    return t_vid0_us + (delta_sim * scale_den) // scale_num


class TimeMap:
    """Mapa lineal por tramos video -> simulacion con aritmetica entera (docs/02, ADR-0002).

    ``knots`` son pares ``(video_us, sim_us)``: ``video_us`` estrictamente creciente y
    ``sim_us`` no decreciente (un tramo plano *pausa* la simulacion). Solo cambia la
    velocidad de reproduccion; nunca los costos del modelo simulado.
    """

    def __init__(self, knots: list[tuple[int, int]]) -> None:
        if len(knots) < 2:
            raise ValueError("TimeMap requiere al menos dos nudos")
        for (v0, s0), (v1, s1) in pairwise(knots):
            if v1 <= v0 or s1 < s0:
                raise ValueError(f"Nudos invalidos: {(v0, s0)} -> {(v1, s1)}")
        self.knots = list(knots)
        self._v = [k[0] for k in knots]

    def sim_at(self, t_vid_us: int) -> int:
        """Tiempo de simulacion correspondiente al tiempo de video (saturado en los extremos)."""
        if t_vid_us <= self._v[0]:
            return self.knots[0][1]
        if t_vid_us >= self._v[-1]:
            return self.knots[-1][1]
        i = bisect_right(self._v, t_vid_us) - 1
        (v0, s0), (v1, s1) = self.knots[i], self.knots[i + 1]
        return s0 + ((t_vid_us - v0) * (s1 - s0)) // (v1 - v0)

    def video_at(self, t_sim_us: np.ndarray) -> np.ndarray:
        """Tiempos de video (int64) de eventos de simulacion; -1 si caen fuera del mapa.

        En tramos planos (simulacion pausada) un instante de simulacion se asigna al
        primer tiempo de video que lo alcanza.
        """
        s_arr = np.asarray(t_sim_us, dtype=np.float64)
        out = np.full(s_arr.shape, -1, dtype=np.int64)
        first = True
        for (v0, s0), (v1, s1) in pairwise(self.knots):
            if s1 == s0:
                continue  # tramo plano: sin eventos de simulacion
            lo = s_arr >= s0 if first else s_arr > s0
            mask = lo & (s_arr <= s1)
            out[mask] = np.rint(v0 + (s_arr[mask] - s0) * (v1 - v0) / (s1 - s0)).astype(np.int64)
            first = False
        return out
