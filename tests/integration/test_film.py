"""Pipeline film con FFmpeg real: formato, limpieza atomica y determinismo (NFR-04)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

from archengine.cli import main
from archengine.pipeline.film import film

pytestmark = pytest.mark.integration

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="requiere FFmpeg")


def _probe(path: Path) -> dict[str, dict[str, Any]]:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-show_entries",
            "stream=codec_type,width,height,nb_read_frames,duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return {s["codec_type"]: s for s in json.loads(out)["streams"]}


@needs_ffmpeg
def test_film_produces_valid_mp4_and_cleans_up(tmp_path: Path) -> None:
    before = set(Path(tempfile.gettempdir()).glob("archengine-*.wav"))
    out = tmp_path / "ep.mp4"
    res = film("ep01", out, max_frames=30)
    assert out.is_file() and not out.with_name("ep.mp4.partial").exists()
    assert set(Path(tempfile.gettempdir()).glob("archengine-*.wav")) == before  # WAV eliminado
    streams = _probe(out)
    assert (streams["video"]["width"], streams["video"]["height"]) == (1080, 1920)
    assert streams["video"]["nb_read_frames"] == "30"
    assert abs(float(streams["audio"]["duration"]) - 1.0) < 0.05
    man = json.loads(res.manifest_path.read_text(encoding="utf-8"))
    assert man["frames"] == 30 and man["video_sha256"].startswith("sha256:")
    assert man["trace_hash"] != "sha256:none" and man["audio_pcm_sha256"] != "sha256:none"


@needs_ffmpeg
def test_film_is_reproducible(tmp_path: Path) -> None:
    a = film("ep01", tmp_path / "a.mp4", max_frames=12)
    b = film("ep01", tmp_path / "b.mp4", max_frames=12)
    assert a.manifest.trace_hash == b.manifest.trace_hash
    assert a.manifest.audio_pcm_sha256 == b.manifest.audio_pcm_sha256
    assert a.manifest.video_sha256 == b.manifest.video_sha256


@needs_ffmpeg
def test_cli_film_reports_and_writes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["film", "ep01", "-o", str(tmp_path / "c.mp4"), "--max-frames", "6"])
    assert rc == 0
    assert "Video generado" in capsys.readouterr().out


def test_film_aborts_and_cleans_partial_when_ffmpeg_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    assert main(["film", "ep01", "-o", str(tmp_path / "x.mp4"), "--max-frames", "3"]) == 3
    assert not list(tmp_path.glob("x.mp4*"))
