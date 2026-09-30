# ADR-0005 — Entrega del audio a FFmpeg

- **Estado**: **Aceptada** (Resolución formal de C-03 y OQ-05 en PDR y arquitectura)
- **Requisitos**: FR-16, FR-17, FR-19, NFR-06

## Contexto
El PDR envía el video por `stdin` de FFmpeg y prohíbe escrituras intermedias. FFmpeg tiene un solo `stdin`; el audio necesita un segundo *input*. Además, el audio se sintetiza completo desde la trace (≈ 23 MB de PCM f32, 11,5 MB en s16).

## Alternativas
| # | Opción | Pros | Contras |
| :-: | :--- | :--- | :--- |
| A | **WAV temporal** en directorio temporal (`-i audio.wav`) | Portable (Windows/Linux), simple, robusto | Un archivo intermedio (11,5 MB) — matiza NFR-06 |
| B | **Segundo pipe** (POSIX: `pass_fds` + `-i pipe:3`; Windows: *named pipe*) | Sin archivos | Gestión de dos pipes con riesgo de deadlock (hilo por pipe); Windows complejo (el equipo desarrolla en Windows) |
| C | Video sólo por pipe → MP4 sin audio → `ffmpeg -i v -i a -c copy` | Sencillo | Dos pasos, archivo intermedio **grande**; peor que A |
| D | Audio por `stdin` y video por archivo | — | Invierte el problema (video = 11 GB) |
| E | Un solo stream multiplexado (NUT) por `stdin` escrito por ArchEngine | Sin archivos, un pipe | Requiere escribir un muxer NUT propio/librería |

## Decisión Aceptada
**Opción A**: Escribir el PCM sintetizado como archivo WAV (`s16le`, 48 kHz, estéreo, $\approx 11,5\text{ MB}$ para 60 s) utilizando `tempfile.mkstemp` (permisos 0600) en el directorio temporal del sistema operativo, y eliminarlo de forma garantizada en el bloque `finally` de `ffmpeg_sink.py`. El flujo de video masivo ($\approx 11,2\text{ GB}$) viaja $100\%$ por pipe a `stdin`, satisfaciendo el objetivo fundamental de rendimiento de NFR-06.

## Consecuencias
- (+) Cross-platform; fácil de depurar.
- (−) Excepción documentada a "sin escrituras intermedias" (sólo audio, ≈ 11,5 MB).
- Si el producto exige estricto cero archivos: migrar a **B** en POSIX y mantener A como *fallback* en Windows.
- El hash del audio (`audio_pcm_sha256`) se registra antes de escribir, por lo que el determinismo no depende del sistema de archivos.
