"""CLI unificado de ArchEngine: preview, film, validate, simulate, doctor (FR-18, FR-22).

Punto de entrada unificado para previsualizaciones, validaciones de esquema YAML,
diagnostico de dependencias y pipeline de video.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from archengine import __version__
from archengine.core.schema import ValidationError, validate_file
from archengine.pipeline.preview import render_preview
from archengine.render.core import get_typeface


def _cmd_doctor(_: argparse.Namespace) -> int:
    """Verifica entorno de ejecucion, librerias nativas, FFmpeg y fuentes empaquetadas."""
    all_ok = True
    print(f"archengine {__version__}")
    print(f"python     {sys.version.split()[0]}")

    for mod in ("skia", "numpy", "yaml"):
        try:
            m = __import__(mod)
            v = getattr(m, "__version__", "ok")
            print(f"{mod:<10} {v}")
        except ImportError:
            print(f"{mod:<10} FALTA")
            all_ok = False

    tf = get_typeface()
    tf_family = tf.getFamilyName() if tf else "desconocida"
    print(f"fuente     {tf_family}")

    ffmpeg = shutil.which("ffmpeg")
    print(f"ffmpeg     {ffmpeg or 'FALTA'}")

    if not all_ok:
        return 1
    if not ffmpeg:
        return 3
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    """Valida sintaxis y esquemas estrictos de archivos YAML (FR-01, FR-02, FR-20)."""
    p = Path(args.path)
    if not p.exists():
        print(f"Error de validacion: El archivo no existe: {args.path}", file=sys.stderr)
        return 2

    try:
        result = validate_file(p)
        print(f"Validacion exitosa: {p.name} ({result.__class__.__name__})")
        return 0
    except ValidationError as err:
        print(f"Error de validacion en {err.path}: {err.message}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error de validacion en {p.name}: {exc}", file=sys.stderr)
        return 2


def _cmd_preview(args: argparse.Namespace) -> int:
    """Renderiza un cuadro clave a PNG en memoria (FR-18, NFR-02)."""
    try:
        t_sec = float(args.t_seconds)
        scale = float(args.scale)
        seed = int(args.seed)
    except (ValueError, TypeError) as err:
        print(f"Argumento invalido: {err}", file=sys.stderr)
        return 2

    out_path = args.output
    if not out_path:
        # Destino por defecto basado en nombre de escena
        safe_name = Path(args.scene).stem
        out_path = f"{safe_name}_preview_{t_sec:.2f}s.png"

    try:
        res = render_preview(
            scene_target=args.scene,
            t_seconds=t_sec,
            scale=scale,
            seed=seed,
            apply_postprocessing=bool(args.post),
            output_path=out_path,
        )
        print(
            f"Preview generado: {out_path} ({res.width}x{res.height}, "
            f"cuadro k={res.frame_k}, t={t_sec:.3f}s, {res.render_time_ms:.1f}ms)"
        )
        return 0
    except FileNotFoundError as err:
        print(f"Archivo o escena no encontrada: {err}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error en render preview: {exc}", file=sys.stderr)
        return 1


def _cmd_film(args: argparse.Namespace) -> int:
    """Modo film: video rgb24 por pipe a FFmpeg + audio WAV temporal (FR-19)."""
    from archengine.pipeline.ffmpeg_sink import FFmpegFailedError, FFmpegMissingError
    from archengine.pipeline.film import film

    def progress(done: int, total: int, dt: float) -> None:
        if done % 60 == 0 or done == total:
            print(f"  cuadro {done}/{total} ({dt * 1000:.0f} ms/cuadro)", file=sys.stderr)

    try:
        res = film(
            args.scene,
            output=args.output,
            seed=args.seed,
            threads=args.threads,
            progress=progress,
            max_frames=args.max_frames,
        )
    except FFmpegMissingError as err:
        print(str(err), file=sys.stderr)
        return 3
    except FFmpegFailedError as err:
        print(f"Fallo de FFmpeg: {err}", file=sys.stderr)
        return 4
    except FileNotFoundError as err:
        print(f"Archivo o escena no encontrada: {err}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrumpido; se elimino el archivo parcial.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error en film: {exc}", file=sys.stderr)
        return 1

    print(
        f"Video generado: {res.output} ({res.frames} cuadros, "
        f"p50={res.frame_p50_s * 1000:.0f} ms, p95={res.frame_p95_s * 1000:.0f} ms/cuadro)"
    )
    print(f"Manifest: {res.manifest_path}")
    if not res.sla_ok:
        print("Advertencia: p95 por cuadro excede el SLA de 0.40 s", file=sys.stderr)
        if args.strict:
            return 5
    return 0


def _cmd_simulate(args: argparse.Namespace) -> int:
    """Ejecuta solo la simulacion y opcionalmente vuelca las trazas (.npz)."""
    import time

    from archengine.pipeline.preview import resolve_scene

    try:
        scene = resolve_scene(args.scene, args.seed)
    except FileNotFoundError as err:
        print(f"Archivo o escena no encontrada: {err}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error al preparar la escena: {exc}", file=sys.stderr)
        return 1
    if scene.traces_fn is None:
        print(f"La escena {scene.id!r} no tiene simulacion asociada.", file=sys.stderr)
        return 2

    t0 = time.perf_counter()
    traces = scene.traces_fn()
    dt = time.perf_counter() - t0
    for name, tr in sorted(traces.items()):
        print(f"{name}: {tr.n_events} eventos, fin={tr.end_us / 1e6:.3f}s sim, {tr.trace_hash()}")
    print(f"simulacion: {dt:.2f}s")
    if args.dump:
        dump = Path(args.dump)
        for name, tr in traces.items():
            target = dump.with_name(f"{dump.stem}.{name}{dump.suffix or '.npz'}")
            tr.save(target)
            print(f"trace volcada: {target}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de comandos CLI de ArchEngine."""
    parser = argparse.ArgumentParser(prog="archengine", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    # preview
    p_prev = sub.add_parser("preview", help="Renderiza un cuadro a PNG")
    p_prev.add_argument("scene", help="Identificador, archivo YAML o script Python de escena")
    p_prev.add_argument("t_seconds", type=float, help="Instante temporal en segundos")
    p_prev.add_argument("-o", "--output", help="Ruta del archivo PNG de salida")
    p_prev.add_argument("--scale", type=float, default=1.0, help="Factor de escala interactiva")
    p_prev.add_argument("--seed", type=int, default=42, help="Semilla pseudoaleatoria determinista")
    p_prev.add_argument(
        "--post", action="store_true", help="Aplica vineta y grano (igual que film)"
    )
    p_prev.set_defaults(func=_cmd_preview)

    # film
    p_film = sub.add_parser("film", help="Renderiza video completo via FFmpeg")
    p_film.add_argument("scene", help="Escena a filmar")
    p_film.add_argument("-o", "--output", default="out.mp4", help="Archivo de salida MP4")
    p_film.add_argument("--seed", type=int, default=42, help="Semilla determinista")
    p_film.add_argument(
        "--threads", type=int, default=4, help="Hilos de x264 (fijo => determinista)"
    )
    p_film.add_argument("--max-frames", type=int, default=None, help="Limita cuadros (depuracion)")
    p_film.add_argument("--strict", action="store_true", help="Codigo 5 si p95 > 0.40 s/cuadro")
    p_film.set_defaults(func=_cmd_film)

    # validate
    p_val = sub.add_parser("validate", help="Valida sintaxis y esquemas YAML")
    p_val.add_argument("path", help="Ruta al archivo YAML a validar")
    p_val.set_defaults(func=_cmd_validate)

    # simulate
    p_sim = sub.add_parser("simulate", help="Ejecuta solo la simulacion")
    p_sim.add_argument("scene", help="Escena a simular")
    p_sim.add_argument("--seed", type=int, default=42, help="Semilla determinista")
    p_sim.add_argument("--dump", metavar="TRACE.NPZ", help="Archivo de volcado de trace")
    p_sim.set_defaults(func=_cmd_simulate)

    # doctor
    p_doc = sub.add_parser("doctor", help="Verifica entorno y dependencias")
    p_doc.set_defaults(func=_cmd_doctor)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada principal para ejecucion por script o binario archengine."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
