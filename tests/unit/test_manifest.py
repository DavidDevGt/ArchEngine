"""Pruebas unitarias de generacion de manifests y hashes de telemetria (NFR-04)."""

import json
from pathlib import Path

from archengine.core.manifest import Manifest, sha256_bytes


def test_sha256_bytes() -> None:
    data = b"ArchEngine deterministic byte test"
    h = sha256_bytes(data)
    assert h.startswith("sha256:")
    assert len(h) == 7 + 64


def test_manifest_creation_and_json(tmp_path: Path) -> None:
    manifest = Manifest.create(
        seed=42,
        inputs_hash="sha256:abc12345",
        frames=1800,
        fps=30,
        resolution=(1080, 1920),
    )
    assert manifest.engine_version == "0.1.0"
    assert manifest.seed == 42
    assert manifest.frames == 1800
    assert manifest.resolution == [1080, 1920]

    out_file = tmp_path / "test.manifest.json"
    manifest.write(out_file)

    loaded = json.loads(out_file.read_text(encoding="utf-8"))
    assert loaded["seed"] == 42
    assert loaded["frames"] == 1800
    assert loaded["inputs_hash"] == "sha256:abc12345"
