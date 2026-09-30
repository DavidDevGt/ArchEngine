"""Benchmark de rendimiento de renderizado y preview (NFR-01, NFR-02, Hitos M1-M2)."""

from typing import Any

from archengine.pipeline.preview import render_preview, resolve_scene
from archengine.render.core import Renderer, orbit_cam
from archengine.scenes.common import Scene


def test_benchmark_render_frame(benchmark: Any) -> None:
    """Benchmark del rasterizado puro Skia CPU."""
    scene: Scene = resolve_scene("demo")
    faces = scene.get_faces(0)
    cam = orbit_cam(width=1080, height=1920)
    renderer = Renderer(width=1080, height=1920)

    def run_render() -> None:
        renderer.render_frame(faces, cam)

    benchmark(run_render)


def test_benchmark_preview_pipeline(benchmark: Any) -> None:
    """Benchmark del pipeline completo de preview a PNG en memoria (NFR-02)."""
    # Ejecucion previa para calentar caches
    render_preview("demo", t_seconds=0.0)

    def run_preview() -> None:
        render_preview("demo", t_seconds=0.0)

    benchmark(run_preview)
