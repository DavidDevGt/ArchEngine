"""Pruebas unitarias del sistema de diseño THEME e iluminacion Lambert (FR-10)."""

import re
from pathlib import Path

import numpy as np

from archengine.render.theme import (
    Color,
    apply_lambert_lighting,
    get_token_color,
    hex_to_color,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_canonical_theme_tokens_pdr() -> None:
    """Verifica los tokens y valores hexadecimales explicitos del PDR §4.1."""
    # bg: #080a0f
    assert get_token_color("bg") == hex_to_color("#080a0f")
    # node_idle: #1c2333
    assert get_token_color("node_idle") == hex_to_color("#1c2333")
    # bus: #3b82f6
    assert get_token_color("bus") == hex_to_color("#3b82f6")
    # mem: #10b981
    assert get_token_color("mem") == hex_to_color("#10b981")
    # disk: #6366f1
    assert get_token_color("disk") == hex_to_color("#6366f1")
    # alert: #ef4444
    assert get_token_color("alert") == hex_to_color("#ef4444")


def test_color_conversions() -> None:
    col = Color(1.0, 0.5, 0.0, 1.0)
    rgba = col.to_rgba_bytes()
    assert rgba == (255, 128, 0, 255)

    argb = col.to_argb_int()
    assert ((argb >> 24) & 0xFF) == 255
    assert ((argb >> 16) & 0xFF) == 255
    assert ((argb >> 8) & 0xFF) == 128
    assert (argb & 0xFF) == 0


def test_lambert_lighting_calculation() -> None:
    base = Color(1.0, 1.0, 1.0, 1.0)
    light_dir = np.array([0.0, 0.0, 1.0], dtype=np.float64)

    # Cara orientada directamente hacia la luz (normal [0, 0, 1])
    n_facing = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    lit_facing = apply_lambert_lighting(base, n_facing, light_dir=light_dir, ambient=0.35)
    # factor = 0.35 + (1 - 0.35) * 1.0 = 1.0
    assert abs(lit_facing.r - 1.0) < 1e-4

    # Cara perpendicular a la luz (normal [1, 0, 0])
    n_perp = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    lit_perp = apply_lambert_lighting(base, n_perp, light_dir=light_dir, ambient=0.35)
    # factor = 0.35 + 0 = 0.35
    assert abs(lit_perp.r - 0.35) < 1e-4


def test_no_color_hex_literals_outside_theme() -> None:
    """Verifica que no existan cadenas de color hexadecimal fuera de theme.py (docs/03 §6)."""
    src_dir = REPO_ROOT / "src" / "archengine"
    hex_pattern = re.compile(r"#[0-9a-fA-F]{6}\b")

    violations: list[str] = []
    for py_file in src_dir.rglob("*.py"):
        if py_file.name == "theme.py":
            continue
        content = py_file.read_text(encoding="utf-8")
        matches = hex_pattern.findall(content)
        if matches:
            violations.append(f"{py_file.name}: {matches}")

    assert not violations, f"Se encontraron literales de color fuera de theme.py: {violations}"
