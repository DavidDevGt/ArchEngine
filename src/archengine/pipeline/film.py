"""Modo film: simulacion -> audio -> cuadros rgb24 por pipe a FFmpeg (FR-19, docs/05 §3).

Video 100 % sin comprimir por ``stdin`` (sin PNG intermedios); audio como WAV temporal.
Cada cuadro ``k`` se renderiza con el mismo codigo que ``preview`` (``draw_scene_frame``).
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from archengine.audio.sonification import FS, SoundEvents, pcm_to_s16, render_pcm, write_wav
from archengine.core.manifest import Manifest, compute_inputs_hash, sha256_file
from archengine.core.timebase import frame_to_time_us
from archengine.pipeline.ffmpeg_sink import FFmpegFailedError, FFmpegSink, ffmpeg_version
from archengine.pipeline.preview import (
    Scene,
    draw_scene_frame,
    get_cached_postprocessor,
    get_cached_renderer,
    resolve_scene,
)

FRAME_SLA_S = 0.40  # NFR-01


@dataclass(frozen=True)
class FilmResult:
    output: Path
    manifest_path: Path
    manifest: Manifest
    frames: int
    frame_p50_s: float
    frame_p95_s: float

    @property
    def sla_ok(self) -> bool:
        return self.frame_p95_s <= FRAME_SLA_S


def _traces_hash(scene: Scene) -> str:
    if scene.traces_fn is None:
        return "sha256:none"
    h = hashlib.sha256()
    for name, tr in sorted(scene.traces_fn().items()):
        h.update(name.encode())
        h.update(tr.trace_hash().encode())
    return f"sha256:{h.hexdigest()}"


def synthesize_audio(scene: Scene, n_frames: int) -> np.ndarray:
    """PCM maestro (n, 2) float32 con duracion exacta ``n_frames / fps``."""
    duration_us = (n_frames * 1_000_000) // scene.fps
    events = scene.audio_fn() if scene.audio_fn is not None else SoundEvents({})
    return render_pcm(events, duration_us, scene.seed)


def film(
    scene_target: str | Scene,
    output: str | Path = "out.mp4",
    seed: int = 42,
    threads: int = 4,
    progress: Callable[[int, int, float], None] | None = None,
    max_frames: int | None = None,
) -> FilmResult:
    """Renderiza el episodio completo a ``output`` y escribe ``<output>.manifest.json``."""
    t_total = time.perf_counter()
    scene = resolve_scene(scene_target, seed)
    n_frames = round(scene.duration_s * scene.fps)
    if max_frames is not None:
        n_frames = min(n_frames, max_frames)
    w, h = scene.video_width, scene.video_height

    t0 = time.perf_counter()
    trace_hash = _traces_hash(scene)
    t_sim_ms = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    pcm = synthesize_audio(scene, n_frames)
    audio_hash = f"sha256:{hashlib.sha256(pcm_to_s16(pcm).tobytes()).hexdigest()}"
    t_audio_ms = (time.perf_counter() - t0) * 1000.0
    expected = (((n_frames * 1_000_000) // scene.fps) * FS + 500_000) // 1_000_000
    if pcm.shape[0] != expected:
        raise RuntimeError(f"Duracion de audio inconsistente: {pcm.shape[0]} != {expected}")

    fd, wav_name = tempfile.mkstemp(suffix=".wav", prefix="archengine-")
    os.close(fd)
    write_wav(wav_name, pcm)

    renderer = get_cached_renderer(w, h)
    post = get_cached_postprocessor(w, h, seed)
    buf = np.empty((h, w, 3), dtype=np.uint8)
    frame_times: list[float] = []

    out = Path(output)
    with FFmpegSink(out, wav_name, w, h, scene.fps, threads) as sink:
        for k in range(n_frames):
            t0 = time.perf_counter()
            t_us = frame_to_time_us(k, scene.fps)
            try:
                draw_scene_frame(renderer, scene, t_us)
                renderer.to_rgb24_buffer(out=buf)
                sink.write_frame(np.ascontiguousarray(post.apply(buf, k=k)).tobytes())
            except FFmpegFailedError:
                raise
            except Exception as err:
                raise RuntimeError(
                    f"Fallo al renderizar el cuadro k={k} (t_us={t_us}, escena={scene.id}): {err}"
                ) from err
            dt = time.perf_counter() - t0
            frame_times.append(dt)
            if progress is not None:
                progress(k + 1, n_frames, dt)
        sink.finish()

    ft = np.asarray(frame_times)
    p50, p95 = float(np.percentile(ft, 50)), float(np.percentile(ft, 95))
    manifest = Manifest.create(
        seed=seed,
        inputs_hash=compute_inputs_hash(scene.input_files),
        trace_hash=trace_hash,
        audio_pcm_sha256=audio_hash,
        video_sha256=sha256_file(out),
        frames=n_frames,
        fps=scene.fps,
        resolution=(w, h),
        timings_ms={
            "simulate": t_sim_ms,
            "audio": t_audio_ms,
            "render_p50": p50 * 1000.0,
            "render_p95": p95 * 1000.0,
            "total": (time.perf_counter() - t_total) * 1000.0,
        },
        ffmpeg_version=ffmpeg_version(),
    )
    mpath = out.with_name(out.name + ".manifest.json")
    manifest.write(mpath)
    return FilmResult(out, mpath, manifest, n_frames, p50, p95)
