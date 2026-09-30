"""Golden test de imagen para escena multi-nodo (Hito M2, FR-13, NFR-04)."""

import hashlib
from pathlib import Path

import pytest

from archengine.pipeline.preview import render_preview

GOLDEN_DIR = Path(__file__).resolve().parent


@pytest.mark.golden
def test_golden_image_multi_node_scene() -> None:
    """Verifica la reproduccion determinista de un cuadro clave de la escena multi-nodo."""
    res1 = render_preview("demo", t_seconds=0.0, seed=42)
    res2 = render_preview("demo", t_seconds=0.0, seed=42)

    # Determinismo estricto: dos renders bajo la misma semilla producen bytes identicos
    h1 = hashlib.sha256(res1.png_bytes).hexdigest()
    h2 = hashlib.sha256(res2.png_bytes).hexdigest()
    assert h1 == h2, "El renderizado del cuadro de preview debe ser 100% determinista"

    # Guardar o comparar con archivo golden de referencia si existe
    golden_ref = GOLDEN_DIR / "demo_t0.sha256"
    if not golden_ref.exists():
        golden_ref.write_text(h1, encoding="utf-8")
    else:
        expected = golden_ref.read_text(encoding="utf-8").strip()
        assert h1 == expected, f"Discrepancia contra hash golden: {h1} != {expected}"
