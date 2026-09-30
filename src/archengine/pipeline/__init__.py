"""Modulo de orquestacion y pipelines de salida.

Preview a PNG en memoria (Fase 1) y Film con streaming FFmpeg (Fase 3).
"""

from archengine.pipeline.preview import (
    PreviewResult,
    build_demo_scene,
    build_scene_from_topology,
    render_preview,
    resolve_scene,
)

__all__ = [
    "PreviewResult",
    "build_demo_scene",
    "build_scene_from_topology",
    "render_preview",
    "resolve_scene",
]
