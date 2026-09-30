"""Pruebas unitarias de generacion de preview (FR-18)."""

from pathlib import Path

from archengine.pipeline.preview import render_preview


def test_render_preview_png_bytes(tmp_path: Path) -> None:
    out_file = tmp_path / "test_preview.png"
    res = render_preview("demo", t_seconds=0.0, output_path=out_file)

    assert res.width == 1080
    assert res.height == 1920
    assert res.frame_k == 0
    assert len(res.png_bytes) > 0

    # Cabecera magica de archivo PNG
    assert res.png_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    # Archivo en disco creado y coincide byte a byte
    assert out_file.is_file()
    assert out_file.read_bytes() == res.png_bytes


def test_render_preview_scale() -> None:
    res = render_preview("demo", t_seconds=1.0, scale=0.5)
    assert res.width == 540
    assert res.height == 960
    assert res.frame_k == 30  # t=1.0s @ 30 FPS = k=30
