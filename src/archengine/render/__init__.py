"""Modulo de renderizado y proyeccion.

Motor Skia vectorial en CPU, camara orbital ortografica, culling analitico,
ordenamiento por capas (Painter's algorithm), paleta semantica e iluminacion Lambert.
"""

from archengine.render.core import (
    Camera,
    CameraKeyframe,
    CameraTrack,
    Renderer,
    get_font,
    get_typeface,
    orbit_cam,
)
from archengine.render.postprocess import PostProcessor
from archengine.render.theme import (
    DEFAULT_AMBIENT,
    DEFAULT_LIGHT_DIR,
    THEME,
    Color,
    apply_lambert_lighting,
    get_token_color,
    hex_to_color,
)

__all__ = [
    "DEFAULT_AMBIENT",
    "DEFAULT_LIGHT_DIR",
    "THEME",
    "Camera",
    "CameraKeyframe",
    "CameraTrack",
    "Color",
    "PostProcessor",
    "Renderer",
    "apply_lambert_lighting",
    "get_font",
    "get_token_color",
    "get_typeface",
    "hex_to_color",
    "orbit_cam",
]
