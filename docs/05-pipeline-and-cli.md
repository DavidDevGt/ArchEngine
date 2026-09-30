# 05 — Pipeline de producción y CLI

Cubre FR-18, FR-19, FR-22, FR-23 y NFR-01/02/04/06. Decisiones: [ADR-0005](adr/0005-audio-delivery-to-ffmpeg.md), [ADR-0007](adr/0007-reproducible-encoding.md), [ADR-0008](adr/0008-render-concurrency.md).

## 1. CLI `[DERIVED]` (OQ-17)

El PDR sólo nombra los comandos `preview <t_segundos>` y `film`. Se propone el ejecutable `archengine`:

| Comando | Origen | Descripción |
| :--- | :--- | :--- |
| `archengine preview <scene> <t_segundos> [-o out.png] [--scale S] [--seed N]` | PDR §4.5 | Un cuadro en `t` → PNG. |
| `archengine film <scene> [-o out.mp4] [--seed N]` | PDR §4.5 | Video completo por pipe a FFmpeg. |
| `archengine validate <path>` | derivado | Valida YAML y escena; sin simular. |
| `archengine simulate <scene> [--dump trace.npz]` | derivado | Sólo simulación; útil para depurar y para tests. |
| `archengine doctor` | derivado | Verifica FFmpeg, `skia-python`, fuentes y versiones. |

Códigos de salida: `0` ok; `2` uso/validación; `3` dependencia ausente (FFmpeg); `4` fallo de FFmpeg; `5` violación de invariante/SLA con `--strict`; `1` error inesperado.

`<scene>`: ruta a módulo/archivo de escena o nombre registrado (p. ej. `ep01`).

## 2. Preview (FR-18)

1. Cargar/validar entradas → `manifest.inputs_hash`.
2. Trace desde caché o simular (OQ-21).
3. `t_us = round(t_segundos × 10⁶)`; cuadro `k = floor(t_us × fps / 10⁶)` para alinear con el film (el cuadro del preview es **idéntico byte a byte** al del film en ese `k`, salvo `--scale`).
4. Render (mismo código que film) → PNG en memoria (`skia.Image.encodeToData(kPNG)`) → archivo o `stdout`.

Presupuesto (OQ-02 resuelta): $\le 200\text{ ms}$ objetivo de diseño (p90) y $\le 250\text{ ms}$ gate de aceptación (p95) con trace en caché caliente. Desglose `[DERIVED]`: `state_at` 15 ms + render 120 ms + PNG 50 ms + I/O 15 ms. La diferencia frente a los 400 ms de film radica en que preview reutiliza la simulación en memoria/caché, omite el pipeline de codificación x264 y genera un único PNG directo en memoria (admitiendo además `--scale 0.5` para latencias interactivas sub-100 ms).

## 3. Film (FR-19)

### 3.1 Comando FFmpeg `[DERIVED]`

```text
ffmpeg -hide_banner -loglevel error -y
  -f rawvideo -pix_fmt rgb24 -s 1080x1920 -r 30 -i pipe:0
  -i <audio.wav>
  -map 0:v -map 1:a
  -c:v libx264 -pix_fmt yuv420p -crf 18 -preset medium -threads <N>
  -c:a aac -b:a 192k
  -fflags +bitexact -flags:v +bitexact -flags:a +bitexact -map_metadata -1
  -movflags +faststart
  out.mp4
```

Valores de códec/CRF/preset en [ADR-0007](adr/0007-reproducible-encoding.md). La entrega de audio mediante archivo temporal WAV ($\approx 11,5\text{ MB}$) es la decisión aceptada en [ADR-0005](adr/0005-audio-delivery-to-ffmpeg.md) (resolviendo formalmente C-03 y OQ-05).

### 3.2 Bucle

```python
proc = subprocess.Popen(cmd, stdin=PIPE, stderr=PIPE, shell=False)  # sin shell
try:
    for k in range(n_frames):
        render_into(buf, k)  # buffer rgb24 preasignado
        proc.stdin.write(buf)  # bloqueante: backpressure natural
    proc.stdin.close()
except BrokenPipeError:
    ...  # FFmpeg murió
rc = proc.wait()
```

- Un hilo drena `stderr` (evita *deadlock* por pipe lleno).
- `stdin.write` bloquea si FFmpeg va más lento: el render se autorregula. Con codificación más lenta que el render, el tiempo total lo domina FFmpeg; `-threads` y `-preset` se ajustan (R-11).
- Se escribe el archivo de salida **directamente** con extensión final tras éxito: FFmpeg escribe a `out.mp4.partial` y se renombra atómicamente en `rc == 0`; en fallo se borra el parcial.
- Sin PNG/frames intermedios (NFR-06). Excepción documentada: WAV temporal (ADR-0005) y caché de trace (OQ-21).

## 4. Paralelismo

Baseline monoproceso; ver [ADR-0008](adr/0008-render-concurrency.md).

## 5. Manifest (soporte a NFR-04)

`out.mp4.manifest.json` `[DERIVED]`:

```json
{
  "engine_version": "0.1.0", "python": "3.11.x", "skia_python": "x.y", "numpy": "x.y",
  "ffmpeg": "ffmpeg version ...", "platform": "...",
  "seed": 42, "inputs_hash": "sha256:...", "trace_hash": "sha256:...",
  "audio_pcm_sha256": "...", "video_sha256": "...",
  "frames": 1800, "fps": 30, "resolution": [1080, 1920],
  "timings_ms": {"simulate": 0, "audio": 0, "render_p50": 0, "render_p95": 0, "total": 0}
}
```

`video_sha256` se calcula sobre el archivo final (NFR-04). El manifest **no** se incluye dentro del video.

## 6. Manejo de errores

| Situación | Comportamiento |
| :--- | :--- |
| FFmpeg no encontrado | Salir con 3; mensaje con versión mínima y cómo instalar. |
| FFmpeg cierra el pipe / rc ≠ 0 | Abortar, volcar `stderr`, borrar `.partial`, salir con 4. |
| Excepción en render del cuadro `k` | Abortar con `k`, `t_us` y el ID de escena; no continuar con cuadros parciales. |
| YAML inválido | Salir con 2; error con ruta JSON-path y línea. |
| Cuadro excede SLA | Sólo advertencia; con `--strict`, código 5 al final. |
| Ctrl-C | Terminar FFmpeg (`terminate`, luego `kill`), borrar `.partial`. |

## 7. Ejecución en CI/Docker (FR-22)

- Imagen mínima: `python:3.11-slim` + `ffmpeg` del gestor de paquetes + wheel de `skia-python` + fuente empaquetada. Sin X11/GPU (raster puro). `[OPEN QUESTION]` dependencias de sistema de `skia-python` en slim (libfontconfig, libGL) → verificar en Fase 1 (R-07, OQ-22).
- Límite de memoria del contenedor de pruebas: 1,5 GB para validar NFR-03.
- GitHub Actions: job `film` no se ejecuta en cada PR (12 min); PR ejecuta preview + tests + benchmark corto (ver [09](09-testing-and-quality.md)).
