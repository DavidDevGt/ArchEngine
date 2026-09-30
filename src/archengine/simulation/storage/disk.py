"""Modelo fisico de disco HDD 7200 RPM (docs/02 §5.1, protocols.yaml ``disk_hdd``).

El tiempo de cada acceso es ``seek(|Δtrack|) + rotacion + transferencia``; un acceso
secuencial (misma pista contigua) omite seek y rotacion. No se hardcodea quien gana.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isqrt
from typing import Any

PAGE_BYTES = 4096
PAGES_PER_TRACK = 512  # 2 MiB por pista; 2000 pistas ~ 4 GiB


@dataclass(frozen=True)
class DiskParams:
    tracks: int = 2000
    seek_track_to_track_us: int = 800
    seek_max_us: int = 16000
    avg_rotation_us: int = 4166
    transfer_us_per_page: int = 27

    @classmethod
    def from_config(cls, cfg: Any) -> DiskParams:
        """Construye desde ``DiskHDDConfig`` (core.schema)."""
        return cls(
            tracks=int(cfg.tracks),
            seek_track_to_track_us=int(cfg.seek_track_to_track_us),
            seek_max_us=int(cfg.seek_max_us),
            avg_rotation_us=int(cfg.avg_rotation_us),
            transfer_us_per_page=int(cfg.transfer_us_per_page),
        )


@dataclass(frozen=True)
class IoResult:
    """Resultado de un acceso: intervalo ocupado y costes desglosados."""

    start_us: int
    done_us: int
    seek_us: int
    delta_track: int
    track: int


class DiskModel:
    """Disco mecanico con un unico cabezal y cola implicita (``busy_until``)."""

    def __init__(self, params: DiskParams | None = None) -> None:
        self.p = params or DiskParams()
        self.head_track = 0
        self.busy_until_us = 0
        self.bytes_written = 0
        self.bytes_read = 0
        self.io_count = 0

    def seek_us(self, delta_track: int) -> int:
        """Curva de seek entera: t2t + (max - t2t) * sqrt((Δ-1)/(N-2))."""
        d = abs(delta_track)
        if d == 0:
            return 0
        p = self.p
        if d == 1:
            return p.seek_track_to_track_us
        span = p.seek_max_us - p.seek_track_to_track_us
        num = isqrt((d - 1) * 1_000_000)
        den = max(1, isqrt((p.tracks - 2) * 1_000_000))
        return p.seek_track_to_track_us + (span * num) // den

    def access(
        self,
        now_us: int,
        track: int,
        n_pages: int = 1,
        *,
        write: bool = False,
        sequential: bool = False,
    ) -> IoResult:
        """Accede ``n_pages`` paginas desde ``track``; serializa tras ``busy_until``."""
        track = max(0, min(self.p.tracks - 1, track))
        start = max(now_us, self.busy_until_us)
        delta = track - self.head_track
        seek = self.seek_us(delta)
        rot = 0 if (sequential and delta == 0) else self.p.avg_rotation_us
        if sequential and delta == 0:
            seek = 0
        # Cruce de pistas durante transferencias largas (p. ej. flush de 64 MiB).
        crossings = max(0, (n_pages - 1) // PAGES_PER_TRACK)
        cost = seek + rot + n_pages * self.p.transfer_us_per_page
        cost += crossings * self.p.seek_track_to_track_us
        done = start + cost
        self.head_track = min(self.p.tracks - 1, track + crossings)
        self.busy_until_us = done
        self.io_count += 1
        if write:
            self.bytes_written += n_pages * PAGE_BYTES
        else:
            self.bytes_read += n_pages * PAGE_BYTES
        return IoResult(start, done, seek, delta, self.head_track)
