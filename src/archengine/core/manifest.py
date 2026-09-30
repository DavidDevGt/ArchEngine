"""Manifests con hashes SHA-256, semilla y telemetria.

Genera el artefacto de auditoria reproducible out.mp4.manifest.json y provee
calculo estricto de hashes criptograficos para insumos, trazas y salidas (NFR-04).
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from archengine import __version__


def sha256_bytes(data: bytes) -> str:
    """Calcula el hash SHA-256 con prefijo canónico sha256:."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def sha256_file(path: str | Path, chunk_size: int = 65536) -> str:
    """Calcula el hash SHA-256 de un archivo en disco de forma incremental."""
    p = Path(path).resolve()
    h = hashlib.sha256()
    with p.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def compute_inputs_hash(files: Sequence[str | Path]) -> str:
    """Calcula un hash combinado y ordenado para un conjunto de archivos de entrada."""
    h = hashlib.sha256()
    for item in sorted(str(Path(f).resolve()) for f in files):
        p = Path(item)
        if p.is_file():
            h.update(p.name.encode("utf-8"))
            h.update(p.read_bytes())
    return f"sha256:{h.hexdigest()}"


@dataclass
class Manifest:
    """Estructura de metadatos y trazabilidad de ejecucion."""

    engine_version: str = __version__
    python: str = field(default_factory=lambda: sys.version.split()[0])
    skia_python: str = "unknown"
    numpy: str = "unknown"
    ffmpeg: str = "none"
    platform: str = field(default_factory=platform.platform)
    seed: int = 42
    inputs_hash: str = "sha256:none"
    trace_hash: str = "sha256:none"
    audio_pcm_sha256: str = "sha256:none"
    video_sha256: str = "sha256:none"
    frames: int = 0
    fps: int = 30
    resolution: list[int] = field(default_factory=lambda: [1080, 1920])
    timings_ms: dict[str, float] = field(
        default_factory=lambda: {
            "simulate": 0.0,
            "audio": 0.0,
            "render_p50": 0.0,
            "render_p95": 0.0,
            "total": 0.0,
        }
    )

    @classmethod
    def create(
        cls,
        seed: int = 42,
        inputs_hash: str = "sha256:none",
        trace_hash: str = "sha256:none",
        audio_pcm_sha256: str = "sha256:none",
        video_sha256: str = "sha256:none",
        frames: int = 1800,
        fps: int = 30,
        resolution: tuple[int, int] = (1080, 1920),
        timings_ms: dict[str, float] | None = None,
        ffmpeg_version: str = "none",
    ) -> Manifest:
        """Crea una instancia con detección automática de versiones de dependencias instaladas."""
        skia_v = "unknown"
        try:
            import skia  # type: ignore[import-not-found]

            skia_v = str(getattr(skia, "__version__", "unknown"))
        except ImportError:
            pass

        np_v = "unknown"
        try:
            import numpy as np

            np_v = getattr(np, "__version__", "unknown")
        except ImportError:
            pass

        t_ms = {
            "simulate": 0.0,
            "audio": 0.0,
            "render_p50": 0.0,
            "render_p95": 0.0,
            "total": 0.0,
        }
        if timings_ms:
            t_ms.update(timings_ms)

        return cls(
            engine_version=__version__,
            python=sys.version.split()[0],
            skia_python=skia_v,
            numpy=np_v,
            ffmpeg=ffmpeg_version,
            platform=platform.platform(),
            seed=seed,
            inputs_hash=inputs_hash,
            trace_hash=trace_hash,
            audio_pcm_sha256=audio_pcm_sha256,
            video_sha256=video_sha256,
            frames=frames,
            fps=fps,
            resolution=list(resolution),
            timings_ms=t_ms,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def write(self, path: str | Path) -> None:
        p = Path(path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json(), encoding="utf-8")
