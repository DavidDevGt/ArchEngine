"""Subproceso FFmpeg: video rgb24 por pipe a stdin + audio WAV temporal (ADR-0005, ADR-0007).

FFmpeg escribe a ``<out>.partial`` y se renombra atomicamente solo si ``rc == 0``; en cualquier
fallo se borra el parcial y el WAV temporal (``finally``). Sin ``shell=True``.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import threading
from pathlib import Path
from types import TracebackType


class FFmpegMissingError(RuntimeError):
    """FFmpeg no esta en el PATH (codigo de salida 3)."""


class FFmpegFailedError(RuntimeError):
    """FFmpeg termino con error o cerro el pipe (codigo de salida 4)."""


def find_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise FFmpegMissingError(
            "FFmpeg no encontrado en el PATH. Instale FFmpeg >= 5 (https://ffmpeg.org/download.html)."
        )
    return exe


def ffmpeg_version(exe: str | None = None) -> str:
    """Primera linea de ``ffmpeg -version`` (registrada en el manifest)."""
    exe = exe or find_ffmpeg()
    out = subprocess.run([exe, "-version"], capture_output=True, text=True, check=False).stdout
    return out.splitlines()[0].strip() if out else "unknown"


def build_command(
    exe: str, width: int, height: int, fps: int, wav: str | Path, out: str | Path, threads: int = 4
) -> list[str]:
    """Comando FFmpeg del docs/05 §3.1 (H.264 yuv420p crf 18 + AAC 192k, bitexact)."""
    return [
        exe, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(fps),
        "-i", "pipe:0",
        "-i", str(wav),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium",
        "-g", str(fps * 2), "-threads", str(threads),
        "-c:a", "aac", "-b:a", "192k",
        "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
        "-map_metadata", "-1", "-movflags", "+faststart", "-shortest",
        "-f", "mp4", str(out),
    ]  # fmt: skip


class FFmpegSink:
    """Context manager que recibe cuadros rgb24 y produce el MP4 final atomicamente."""

    def __init__(
        self,
        output: str | Path,
        wav_path: str | Path,
        width: int,
        height: int,
        fps: int,
        threads: int = 4,
    ) -> None:
        self.output = Path(output).resolve()
        self.partial = self.output.with_name(self.output.name + ".partial")
        self._wav = Path(wav_path)
        self._cmd = build_command(
            find_ffmpeg(), width, height, fps, wav_path, self.partial, threads
        )
        self._proc: subprocess.Popen[bytes] | None = None
        self._stderr: list[bytes] = []
        self._drain: threading.Thread | None = None
        self.ok = False

    def __enter__(self) -> FFmpegSink:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self._proc = subprocess.Popen(  # lista de argumentos, sin shell
            self._cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, shell=False
        )
        assert self._proc.stderr is not None
        stream = self._proc.stderr

        def drain() -> None:  # evita deadlock por pipe de stderr lleno
            for chunk in iter(lambda: stream.read(4096), b""):
                self._stderr.append(chunk)

        self._drain = threading.Thread(target=drain, daemon=True)
        self._drain.start()
        return self

    def write_frame(self, buf: memoryview | bytes) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        try:
            self._proc.stdin.write(buf)
        except (BrokenPipeError, OSError) as err:
            raise FFmpegFailedError(f"FFmpeg cerro el pipe: {self.stderr_text()}") from err

    def stderr_text(self) -> str:
        if self._drain is not None:
            self._drain.join(timeout=2)
        return b"".join(self._stderr).decode("utf-8", "replace").strip()

    def finish(self) -> None:
        """Cierra stdin, espera a FFmpeg y promueve el parcial al archivo final."""
        assert self._proc is not None and self._proc.stdin is not None
        with contextlib.suppress(BrokenPipeError, OSError):
            self._proc.stdin.close()
        rc = self._proc.wait()
        if rc != 0:
            raise FFmpegFailedError(f"FFmpeg termino con codigo {rc}: {self.stderr_text()}")
        os.replace(self.partial, self.output)
        self.ok = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:  # error o Ctrl-C: terminar FFmpeg
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if not self.ok:
            with contextlib.suppress(OSError):
                self.partial.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            self._wav.unlink(missing_ok=True)  # el WAV temporal se elimina siempre
