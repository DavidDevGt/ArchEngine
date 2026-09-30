"""Canvas Skia, camara orbital, proyeccion, culling por capas y decals (FR-09, FR-11, FR-12).

Provee el motor de renderizado vectorial CPU puro sobre Google Skia, calculo
analitico de proyeccion ortografica/isometrica, back-face culling analitico,
ordenamiento determinista por capas LAYER (Painter's algorithm) y decals proyectivos.
"""

from __future__ import annotations

import math
import struct
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import skia  # type: ignore[import-not-found]

from archengine.geometry.primitives import (
    Face,
)
from archengine.render.theme import (
    apply_lambert_lighting,
    get_token_color,
)

# -----------------------------------------------------------------------------
# Gestion de Tipografia JetBrains Mono empaquetada (OQ-14, R-02)
# -----------------------------------------------------------------------------

_FONT_CACHE: dict[float, skia.Font] = {}
_CACHED_TYPEFACE: skia.Typeface | None = None


def get_typeface() -> skia.Typeface:
    """Obtiene el Typeface de JetBrains Mono empaquetado o fallback determinista."""
    global _CACHED_TYPEFACE
    if _CACHED_TYPEFACE is not None:
        return _CACHED_TYPEFACE

    possible_paths = [
        Path(__file__).resolve().parent.parent / "assets" / "fonts" / "JetBrainsMono-Regular.ttf",
        Path(__file__).resolve().parent.parent.parent.parent
        / "assets"
        / "fonts"
        / "JetBrainsMono-Regular.ttf",
    ]

    for p in possible_paths:
        if p.is_file():
            tf = skia.Typeface.MakeFromFile(str(p))
            if tf is not None:
                _CACHED_TYPEFACE = tf
                return _CACHED_TYPEFACE

    # Fallback si no se encuentra archivo
    tf_fb = skia.Typeface.MakeFromName("monospace", skia.FontStyle())
    _CACHED_TYPEFACE = tf_fb
    return _CACHED_TYPEFACE


def get_font(size: float = 14.0) -> skia.Font:
    """Obtiene una fuente Skia cacheada por tamaño."""
    if size not in _FONT_CACHE:
        font = skia.Font(get_typeface(), float(size))
        font.setSubpixel(True)
        _FONT_CACHE[size] = font
    return _FONT_CACHE[size]


# -----------------------------------------------------------------------------
# Camara Orbital Parametrica (FR-09, docs/03 §3)
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Camera:
    """Estado de la camara y matrices analiticas de proyeccion."""

    target: tuple[float, float, float]
    azimuth: float
    elevation: float
    scale: float
    width: int
    height: int
    eye: np.ndarray  # (3,)
    forward: np.ndarray  # d_view (3,)
    right: np.ndarray  # (3,)
    up: np.ndarray  # (3,)

    @property
    def d_view(self) -> np.ndarray:
        """Direccion de vista que va del ojo hacia el objetivo."""
        return self.forward

    def project_points(self, points: np.ndarray) -> np.ndarray:
        """Proyecta un array (N, 3) de coordenadas de mundo a (N, 2) de pantalla."""
        t_arr = np.array(self.target, dtype=np.float64)
        rel = points - t_arr  # (N, 3)

        x_cam = np.dot(rel, self.right)  # (N,)
        y_cam = np.dot(rel, self.up)  # (N,)

        cx = float(self.width) * 0.5
        cy = float(self.height) * 0.5

        u = cx + x_cam * self.scale
        v = cy - y_cam * self.scale  # Eje Y hacia abajo en canvas

        return np.column_stack((u, v))

    def compute_depth(self, point: np.ndarray | tuple[float, float, float]) -> float:
        """Calcula la profundidad proyectada a lo largo del eje de vista para ordenamiento."""
        t_arr = np.array(self.target, dtype=np.float64)
        p_arr = np.asarray(point, dtype=np.float64)
        return float(np.dot(p_arr - t_arr, self.forward))


def orbit_cam(
    target: tuple[float, float, float] = (0.0, 0.0, 0.0),
    azimuth: float = 45.0,
    elevation: float = 35.264,
    scale: float = 1.0,
    width: int = 1080,
    height: int = 1920,
) -> Camera:
    """Construye una camara orbital ortografica con proyeccion analitica (FR-09).

    Args:
        target: Punto central en coordenadas de mundo hacia donde mira la camara.
        azimuth: Angulo azimutal en grados (0 = mira a lo largo de +Y, 45 = isometrico).
        elevation: Angulo de elevacion en grados (0 = horizontal,
            35.264 = isometrico, 90 = cenital).
        scale: Factor de escala de visualizacion (1 unidad de mundo = scale pixeles).
        width: Ancho del canvas (default 1080).
        height: Alto del canvas (default 1920).
    """
    az_rad = math.radians(azimuth)
    el_rad = math.radians(elevation)

    d = 2000.0  # Distancia analitica de punto de vista
    tx, ty, tz = target

    cos_el = math.cos(el_rad)
    sin_el = math.sin(el_rad)
    cos_az = math.cos(az_rad)
    sin_az = math.sin(az_rad)

    # Posicion del ojo en coordenadas de mundo
    eye_x = tx + d * cos_el * sin_az
    eye_y = ty - d * cos_el * cos_az
    eye_z = tz + d * sin_el
    eye = np.array([eye_x, eye_y, eye_z], dtype=np.float64)

    # Vector forward de ojo a objetivo
    t_arr = np.array([tx, ty, tz], dtype=np.float64)
    forward = t_arr - eye
    norm_f = np.linalg.norm(forward)
    forward = forward / norm_f if norm_f > 1e-8 else np.array([0.0, 0.0, -1.0], dtype=np.float64)

    # Vector Up de referencia para evitar singularidad en vista cenital exacta
    if abs(forward[2]) > 0.9999:
        world_up = np.array([0.0, 1.0, 0.0], dtype=np.float64)
    else:
        world_up = np.array([0.0, 0.0, 1.0], dtype=np.float64)

    right = np.cross(forward, world_up)
    norm_r = np.linalg.norm(right)
    right = right / norm_r if norm_r > 1e-8 else np.array([1.0, 0.0, 0.0], dtype=np.float64)

    up = np.cross(right, forward)
    norm_u = np.linalg.norm(up)
    up = up / norm_u if norm_u > 1e-8 else np.array([0.0, 1.0, 0.0], dtype=np.float64)

    return Camera(
        target=target,
        azimuth=azimuth,
        elevation=elevation,
        scale=scale,
        width=width,
        height=height,
        eye=eye,
        forward=forward,
        right=right,
        up=up,
    )


# -----------------------------------------------------------------------------
# Trayectorias de Camara con Interpolacion Suave
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class CameraKeyframe:
    t_us: int
    azimuth: float = 45.0
    elevation: float = 35.264
    scale: float = 1.0
    target: tuple[float, float, float] = (0.0, 0.0, 0.0)


class CameraTrack:
    """Pista de camara con interpolacion Hermite suave (smoothstep) entre keyframes."""

    def __init__(self, keyframes: Sequence[CameraKeyframe]) -> None:
        if not keyframes:
            raise ValueError("CameraTrack requiere al menos un keyframe")
        self._keyframes = sorted(keyframes, key=lambda k: k.t_us)

    def camera_at(self, t_us: int, width: int = 1080, height: int = 1920) -> Camera:
        """Obtiene la camara interpolada en el instante t_us especificado."""
        if len(self._keyframes) == 1 or t_us <= self._keyframes[0].t_us:
            kf = self._keyframes[0]
            return orbit_cam(
                target=kf.target,
                azimuth=kf.azimuth,
                elevation=kf.elevation,
                scale=kf.scale,
                width=width,
                height=height,
            )

        if t_us >= self._keyframes[-1].t_us:
            kf = self._keyframes[-1]
            return orbit_cam(
                target=kf.target,
                azimuth=kf.azimuth,
                elevation=kf.elevation,
                scale=kf.scale,
                width=width,
                height=height,
            )

        # Buscar segmento
        for i in range(len(self._keyframes) - 1):
            kf0 = self._keyframes[i]
            kf1 = self._keyframes[i + 1]
            if kf0.t_us <= t_us <= kf1.t_us:
                span = kf1.t_us - kf0.t_us
                t_norm = (t_us - kf0.t_us) / max(1, span)
                # Funcion smoothstep: 3*t^2 - 2*t^3
                s = t_norm * t_norm * (3.0 - 2.0 * t_norm)

                az = kf0.azimuth + s * (kf1.azimuth - kf0.azimuth)
                el = kf0.elevation + s * (kf1.elevation - kf0.elevation)
                sc = kf0.scale + s * (kf1.scale - kf0.scale)
                tgt = (
                    kf0.target[0] + s * (kf1.target[0] - kf0.target[0]),
                    kf0.target[1] + s * (kf1.target[1] - kf0.target[1]),
                    kf0.target[2] + s * (kf1.target[2] - kf0.target[2]),
                )
                return orbit_cam(
                    target=tgt,
                    azimuth=az,
                    elevation=el,
                    scale=sc,
                    width=width,
                    height=height,
                )

        kf = self._keyframes[-1]
        return orbit_cam(
            target=kf.target,
            azimuth=kf.azimuth,
            elevation=kf.elevation,
            scale=kf.scale,
            width=width,
            height=height,
        )


PNG_SIGNATURE = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])


def encode_png_rgb24(rgb: np.ndarray) -> bytes:
    """PNG RGB de 8 bits, deterministico y rapido (zlib nivel 1, sin filtros).

    El codificador de Skia cuesta ~210 ms a 1080x1920; este ~50 ms con tamano equivalente,
    lo que permite cumplir el SLA de preview (NFR-02).
    """
    h, w, _ = rgb.shape
    raw = np.zeros((h, 1 + w * 3), dtype=np.uint8)  # byte de filtro 0 por fila
    raw[:, 1:] = rgb.reshape(h, w * 3)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    return (
        PNG_SIGNATURE
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw.tobytes(), 1))
        + chunk(b"IEND", b"")
    )


# -----------------------------------------------------------------------------
# Motor de Rasterizado Skia en CPU (FR-09, FR-11, FR-12)
# -----------------------------------------------------------------------------


class Renderer:
    """Motor de rasterizado 2.5D/3D determinista en CPU."""

    def __init__(self, width: int = 1080, height: int = 1920) -> None:
        self.width = width
        self.height = height

        # Superficie de renderizado preasignada
        self._surface = skia.Surface.MakeRasterN32Premul(width, height)
        if self._surface is None:
            raise RuntimeError(f"No se pudo crear la superficie Skia de {width}x{height}")

        self._native_buffer: np.ndarray | None = None
        # Buffer temporal de extraccion de pixeles
        self._rgba_buffer = np.zeros((height, width, 4), dtype=np.uint8)
        self._image_info = skia.ImageInfo.Make(
            width,
            height,
            skia.ColorType.kRGBA_8888_ColorType,
            skia.AlphaType.kUnpremul_AlphaType,
        )

        # Pinturas cacheadas
        self._fill_paint = skia.Paint()
        self._fill_paint.setAntiAlias(True)
        self._fill_paint.setStyle(skia.Paint.kFill_Style)

        self._stroke_paint = skia.Paint()
        self._stroke_paint.setAntiAlias(True)
        self._stroke_paint.setStyle(skia.Paint.kStroke_Style)
        self._stroke_paint.setStrokeWidth(1.0)

    @property
    def surface(self) -> skia.Surface:
        return self._surface

    def render_frame(
        self,
        faces: Sequence[Face],
        camera: Camera,
        clear_color_token: str = "bg",
    ) -> skia.Surface:
        """Rasteriza una lista de caras 3D aplicando culling analitico y orden por capas."""
        canvas = self._surface.getCanvas()

        # Limpiar canvas con color de fondo
        bg_col = get_token_color(clear_color_token)
        canvas.clear(bg_col.to_argb_int())

        # 1. Back-face culling analitico (FR-11):
        # Descartar cara si normal · d_view >= 0
        visible_faces: list[Face] = []
        d_view = camera.d_view

        for face in faces:
            # Wireframe o capas especiales (HUD/Decal) se dibujan siempre
            if face.wireframe or face.layer >= 50:
                visible_faces.append(face)
                continue

            dot_view = float(np.dot(face.normal, d_view))
            if dot_view < -1e-6:
                visible_faces.append(face)

        # 2. Ordenamiento por capas y profundidad (Painter's algorithm, ADR-0003):
        # Clave: (layer ASC, -depth DESC, id ASC)
        def sort_key(f: Face) -> tuple[int, float, str]:
            depth = camera.compute_depth(f.centroid)
            return (f.layer, -depth, f.id)

        sorted_faces = sorted(visible_faces, key=sort_key)

        # 3. Dibujo de caras ordenadas
        for face in sorted_faces:
            if len(face.vertices) < 3:
                continue

            screen_pts = camera.project_points(face.vertices)  # (N, 2)

            # Construir Skia Path
            path = skia.Path()
            path.moveTo(float(screen_pts[0, 0]), float(screen_pts[0, 1]))
            for i in range(1, len(screen_pts)):
                path.lineTo(float(screen_pts[i, 0]), float(screen_pts[i, 1]))
            path.close()

            # Aplicar iluminacion sintetica Lambert
            base_col = get_token_color(face.color_token)
            lit_col = apply_lambert_lighting(base_col, face.normal)
            self._fill_paint.setColor(lit_col.to_argb_int())

            canvas.drawPath(path, self._fill_paint)

            # Borde sutil para separacion tecnica
            border_col = get_token_color("border").with_alpha(0.35)
            self._stroke_paint.setColor(border_col.to_argb_int())
            canvas.drawPath(path, self._stroke_paint)

            # 4. Decals proyectivos de telemetria (FR-12)
            if face.decal_spec is not None and len(screen_pts) == 4:
                self._draw_decal(canvas, face.decal_spec, screen_pts)

        return self._surface

    def _draw_decal(
        self,
        canvas: skia.Canvas,
        decal: Any,
        screen_pts: np.ndarray,
    ) -> None:
        """Mapea un decal 2D sobre el cuadrilatero proyectado de la cara via setPolyToPoly."""
        w_src = float(decal.src_width)
        h_src = float(decal.src_height)

        # Puntos de origen rectangulares
        src_points = [
            skia.Point(0.0, 0.0),
            skia.Point(w_src, 0.0),
            skia.Point(w_src, h_src),
            skia.Point(0.0, h_src),
        ]

        # Puntos de destino proyectados en pantalla
        dst_points = [
            skia.Point(float(screen_pts[0, 0]), float(screen_pts[0, 1])),
            skia.Point(float(screen_pts[1, 0]), float(screen_pts[1, 1])),
            skia.Point(float(screen_pts[2, 0]), float(screen_pts[2, 1])),
            skia.Point(float(screen_pts[3, 0]), float(screen_pts[3, 1])),
        ]

        matrix = skia.Matrix()
        if matrix.setPolyToPoly(src_points, dst_points, 4):
            canvas.save()
            canvas.concat(matrix)
            try:
                decal.draw_fn(canvas, w_src, h_src)
            finally:
                canvas.restore()

    def to_png_bytes(self) -> bytes:
        """Codifica el estado actual de la superficie en formato PNG en memoria."""
        return encode_png_rgb24(self.to_rgb24_buffer())

    def to_rgb24_buffer(self, out: np.ndarray | None = None) -> np.ndarray:
        """Extrae el buffer de pixeles crudo en formato RGB24 (height, width, 3) uint8.

        Lee la superficie en su formato nativo (sin conversion de color/alfa: el fondo es
        opaco, asi que premul == unpremul) y reordena canales en NumPy.
        """
        if self._native_buffer is None:
            self._native_buffer = np.empty((self.height, self.width, 4), dtype=np.uint8)
        info = self._surface.imageInfo()
        if not self._surface.readPixels(info, self._native_buffer, self.width * 4):
            raise RuntimeError("Fallo readPixels en la superficie Skia")
        bgra = info.colorType() == skia.ColorType.kBGRA_8888_ColorType
        src = self._native_buffer[:, :, 2::-1] if bgra else self._native_buffer[:, :, :3]
        if out is not None:
            np.copyto(out, src)
            return out
        return np.ascontiguousarray(src)
