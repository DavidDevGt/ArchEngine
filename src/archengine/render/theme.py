"""Paleta semantica (THEME) e iluminacion Lambert. Unico lugar con literales de color (FR-10).

Define los tokens de color del sistema de diseño y calcula el sombreado analitico
Lambert para caras poligonales sin dependencias de GPU.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np


@dataclass(frozen=True)
class Color:
    """Color RGBA con componentes en punto flotante normalizados en [0.0, 1.0]."""

    r: float
    g: float
    b: float
    a: float = 1.0

    def to_rgba_bytes(self) -> tuple[int, int, int, int]:
        """Retorna tupla de 4 enteros en [0, 255]."""
        return (
            int(np.clip(round(self.r * 255.0), 0, 255)),
            int(np.clip(round(self.g * 255.0), 0, 255)),
            int(np.clip(round(self.b * 255.0), 0, 255)),
            int(np.clip(round(self.a * 255.0), 0, 255)),
        )

    def to_rgb_bytes(self) -> tuple[int, int, int]:
        """Retorna tupla de 3 enteros RGB en [0, 255]."""
        r, g, b, _ = self.to_rgba_bytes()
        return (r, g, b)

    def to_argb_int(self) -> int:
        """Retorna entero de 32 bits en formato ARGB para Skia ColorSetARGB."""
        r, g, b, a = self.to_rgba_bytes()
        return (a << 24) | (r << 16) | (g << 8) | b

    def with_alpha(self, new_alpha: float) -> Color:
        """Copia el color modificando unicamente el canal alfa."""
        return Color(self.r, self.g, self.b, float(np.clip(new_alpha, 0.0, 1.0)))


def hex_to_color(hex_str: str, alpha: float = 1.0) -> Color:
    """Convierte cadena hexadecimal '#RRGGBB' o '#RGB' a Color."""
    s = hex_str.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        raise ValueError(f"Formato hexadecimal invalido: {hex_str!r}")
    r = int(s[0:2], 16) / 255.0
    g = int(s[2:4], 16) / 255.0
    b = int(s[4:6], 16) / 255.0
    return Color(r, g, b, float(alpha))


# Diccionario inmutable con todos los tokens semanticos del PDR §4.1 y docs/03 §6
_RAW_THEME: dict[str, Color] = {
    # Tokens obligatorios del PDR
    "bg": hex_to_color("#080a0f"),
    "node_idle": hex_to_color("#1c2333"),
    "bus": hex_to_color("#3b82f6"),
    "mem": hex_to_color("#10b981"),
    "disk": hex_to_color("#6366f1"),
    "alert": hex_to_color("#ef4444"),
    # Tokens derivados de UI y telemetria
    "text_primary": hex_to_color("#f8fafc"),
    "text_secondary": hex_to_color("#94a3b8"),
    "text_muted": hex_to_color("#64748b"),
    "node_active": hex_to_color("#2563eb"),
    "warn": hex_to_color("#f59e0b"),
    "led_active": hex_to_color("#22c55e"),
    "led_idle": hex_to_color("#334155"),
    "led_alert": hex_to_color("#ef4444"),
    "grid_line": hex_to_color("#1e293b"),
    "wireframe": hex_to_color("#334155"),
    "border": hex_to_color("#2a3449"),
    # Estados de consenso Raft
    "raft_leader": hex_to_color("#22c55e"),
    "raft_candidate": hex_to_color("#eab308"),
    "raft_follower": hex_to_color("#3b82f6"),
}

THEME: Mapping[str, Color] = MappingProxyType(_RAW_THEME)

# Vector de luz direccional fija normalizado: L = [0.4, 0.6, 0.7]
_L_UNNORM = np.array([0.4, 0.6, 0.7], dtype=np.float64)
DEFAULT_LIGHT_DIR: np.ndarray = _L_UNNORM / np.linalg.norm(_L_UNNORM)
DEFAULT_AMBIENT: float = 0.35


def get_token_color(token: str) -> Color:
    """Obtiene el color correspondiente a un token semantico."""
    if token not in THEME:
        raise KeyError(f"Token de color desconocido en THEME: {token!r}")
    return THEME[token]


def apply_lambert_lighting(
    base_color: Color,
    normal: np.ndarray,
    light_dir: np.ndarray = DEFAULT_LIGHT_DIR,
    ambient: float = DEFAULT_AMBIENT,
) -> Color:
    """Aplica sombreado sintético Lambert analítico multiplicando por cara (FR-10).

    Formula (docs/03 §6):
        shade = ambient + (1 - ambient) * max(0, normal · light_dir)
        color_final = base_color * shade (manteniendo canal alfa)
    """
    n_len = float(np.linalg.norm(normal))
    if n_len < 1e-8:
        return base_color
    n_unit = normal / n_len
    cos_theta = float(np.dot(n_unit, light_dir))
    dot_clamped = max(0.0, cos_theta)
    factor = ambient + (1.0 - ambient) * dot_clamped

    r_lit = float(np.clip(base_color.r * factor, 0.0, 1.0))
    g_lit = float(np.clip(base_color.g * factor, 0.0, 1.0))
    b_lit = float(np.clip(base_color.b * factor, 0.0, 1.0))
    return Color(r=r_lit, g=g_lit, b=b_lit, a=base_color.a)
