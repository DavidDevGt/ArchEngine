"""Helpers de HUD en espacio de pantalla y de animacion compartidos por los episodios 02-04.

Todo se dibuja en un lienzo logico de 1080 px de ancho (el overlay escala por ``w / 1080``). Los
paquetes en vuelo salen de eventos reales de la trace, vistos en *tiempo de video*, de modo que su
densidad no depende del ``time_scale`` del guion.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import skia  # type: ignore[import-not-found]

from archengine.core.timebase import TimeMap
from archengine.render.core import Camera, get_font
from archengine.render.theme import get_token_color

S = 1_000_000  # µs por segundo

Segment = tuple[float, float, str, str]  # (desde_s, hasta_s, etiqueta, token de color)


def fmt(n: float, dec: int = 0) -> str:
    """Numero con separador de miles ``.`` y decimal ``,`` (ES)."""
    s = f"{n:,.{dec}f}"
    return s.replace(",", "\0").replace(".", ",").replace("\0", ".")


def text(
    c: skia.Canvas,
    s: str,
    x: float,
    y: float,
    size: float,
    token: str,
    align: str = "left",
    alpha: float = 1.0,
) -> None:
    font = get_font(size)
    paint = skia.Paint(AntiAlias=True, Color=get_token_color(token).with_alpha(alpha).to_argb_int())
    if align != "left":
        w = font.measureText(s)
        x -= w if align == "right" else w / 2
    c.drawString(s, x, y, font, paint)


def rect(
    c: skia.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    token: str,
    alpha: float = 1.0,
    r: float = 10.0,
) -> None:
    paint = skia.Paint(AntiAlias=True, Color=get_token_color(token).with_alpha(alpha).to_argb_int())
    c.drawRoundRect(skia.Rect.MakeXYWH(x, y, w, h), r, r, paint)


def header(
    c: skia.Canvas, title: str, subtitle: str, segments: Sequence[Segment], ts: float
) -> None:
    """Titulo, subtitulo, reloj y banner del segmento activo (lo que el guion esta mostrando)."""
    text(c, title, 540, 110, 54, "text_primary", "center")
    text(c, subtitle, 540, 162, 30, "text_secondary", "center")
    end = segments[-1][1]
    for a, b, label, tok in segments:
        if a <= ts < b or (ts >= end and b == end):
            rect(c, 60, 214, 960, 62, "node_idle", 1.0)
            text(c, label, 540, 255, 30, tok, "center")
    text(c, f"{int(ts) // 60:02d}:{int(ts) % 60:02d}", 1020, 60, 24, "text_muted", "right")


def card(
    c: skia.Canvas,
    x: float,
    y0: float,
    w: float,
    h: float,
    title: str,
    token: str,
    rows: Sequence[tuple[str, str]],
    progress: float | None = None,
    state_txt: str = "",
    state_token: str = "led_active",
) -> None:
    """Tarjeta de metricas con barra de progreso opcional y filas clave/valor."""
    rect(c, x, y0, w, h, "node_idle", 1.0)
    rect(c, x, y0, 8, h, token, 1.0, 4)
    text(c, title, x + 30, y0 + 52, 32, "text_primary")
    if state_txt:
        text(c, state_txt, x + w - 30, y0 + 52, 22, state_token, "right")
    top = 82.0
    if progress is not None:
        rect(c, x + 30, y0 + 74, w - 60, 14, "grid_line", 1.0, 7)
        rect(c, x + 30, y0 + 74, max(2.0, (w - 60) * min(1.0, progress)), 14, token, 1.0, 7)
        top = 120.0
    for i, (k, v) in enumerate(rows):
        yy = y0 + top + 40 + i * 44
        text(c, k, x + 30, yy, 24, "text_secondary")
        text(c, v, x + w - 28, yy, 28, "text_primary", "right")


def sparkline(
    c: skia.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    xs: np.ndarray,
    ys: np.ndarray,
    now_x: float,
    x_max: float,
    y_max: float,
    token: str,
    label: str,
    value_txt: str,
) -> None:
    """Serie temporal hasta ``now_x`` (mismas unidades que ``xs``) dentro de un marco."""
    rect(c, x, y, w, h, "node_idle", 1.0)
    text(c, label, x + 24, y + 38, 24, "text_secondary")
    text(c, value_txt, x + w - 24, y + 38, 28, token, "right")
    px, py, pw, ph = x + 24, y + 58, w - 48, h - 82
    c.drawRect(
        skia.Rect.MakeXYWH(px, py + ph, pw, 2),
        skia.Paint(Color=get_token_color("grid_line").to_argb_int()),
    )
    m = xs <= now_x
    if m.sum() < 2:
        return
    sx = px + pw * (xs[m] / x_max)
    sy = py + ph * (1.0 - np.clip(ys[m] / y_max, 0.0, 1.0))
    path = skia.Path()
    path.moveTo(float(sx[0]), float(sy[0]))
    for a, b in zip(sx[1:], sy[1:], strict=True):
        path.lineTo(float(a), float(b))
    paint = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=4,
        Color=get_token_color(token).to_argb_int(),
        StrokeJoin=skia.Paint.kRound_Join,
    )
    c.drawPath(path, paint)
    dot = skia.Paint(AntiAlias=True, Color=get_token_color(token).to_argb_int())
    c.drawCircle(float(sx[-1]), float(sy[-1]), 7, dot)


def bars(
    c: skia.Canvas,
    x: float,
    y: float,
    rows: Sequence[tuple[str, float, str, str]],
    alpha: float,
    bar_w: float = 500.0,
    row_h: float = 100.0,
    v_max: float | None = None,
) -> None:
    """Barras horizontales ``(nombre, valor, token, etiqueta)`` con ancho proporcional."""
    top = v_max if v_max is not None else max(v for _, v, _, _ in rows)
    top = max(top, 1e-9)
    for i, (name, val, tok, label) in enumerate(rows):
        yy = y + i * row_h
        text(c, name, x, yy + 34, 28, "text_primary", alpha=alpha)
        rect(c, x + 200, yy, bar_w, 50, "grid_line", alpha, 6)
        rect(c, x + 200, yy, max(4.0, bar_w * min(1.0, val / top) * alpha), 50, tok, alpha, 6)
        text(c, label, x + 200 + bar_w + 20, yy + 36, 28, "text_primary", alpha=alpha)


def recent_progress(video_us: np.ndarray, t_us: int, window_us: int, max_n: int = 6) -> list[float]:
    """Posiciones normalizadas [0, 1) de los ultimos eventos dentro de ``window_us`` de video.

    ``video_us`` es un arreglo ordenado con los instantes de video de los eventos (>= 0).
    """
    lo = int(np.searchsorted(video_us, t_us - window_us, side="right"))
    hi = int(np.searchsorted(video_us, t_us, side="right"))
    if hi <= lo:
        return []
    # muestreo uniforme de la ventana: los paquetes se reparten a lo largo de la tuberia
    idx = np.unique(np.linspace(lo, hi - 1, min(max_n, hi - lo)).round().astype(int))
    return [float((t_us - int(video_us[i])) / window_us) for i in idx]


def video_times(tmap: TimeMap, t_sim_us: np.ndarray) -> np.ndarray:
    """Instantes de video (ordenados, descartando los fuera de mapa) de eventos de simulacion."""
    v = tmap.video_at(t_sim_us)
    v = v[v >= 0]
    return np.sort(v)


def label3d(
    c: skia.Canvas,
    cam: Camera,
    world: tuple[float, float, float],
    s: str,
    size: float = 26,
    token: str = "text_primary",
    dy: float = 0.0,
) -> None:
    """Etiqueta anclada a un punto del mundo (proyectado con la camara del cuadro)."""
    u, v = cam.project_points(np.asarray([world], dtype=np.float64))[0]
    w = get_font(size).measureText(s)
    rect(c, float(u) - w / 2 - 12, float(v) + dy - size - 2, w + 24, size + 18, "bg", 0.75, 8)
    text(c, s, float(u), float(v) + dy, size, token, "center")
