# ADR-0007 — Codificación reproducible (códec, contenedor y banderas)

- **Estado**: Propuesta — OQ-06, OQ-07, OQ-23
- **Requisitos**: NFR-04, FR-19

## Contexto
NFR-04 pide SHA-256 idéntico "de los archivos finales". El PDR no fija códec/contenedor. x264 multihilo, timestamps/metadatos y versión de FFmpeg pueden alterar bytes.

## Alternativas
| # | Opción | Pros | Contras |
| :-: | :--- | :--- | :--- |
| A | MP4 + H.264 (libx264) `yuv420p` | Compatible con redes sociales (formato 9:16) | x264 es GPL; determinismo exige control |
| B | MKV/FFV1 (sin pérdida) | Determinista y simple | Archivos enormes; no publicable tal cual |
| C | Dos salidas: master determinista (B) + derivado (A) | Verificable | Más trabajo/tiempo |

## Decisión (provisional)
**A**, con: `-fflags +bitexact -flags:v +bitexact -flags:a +bitexact -map_metadata -1`, `-threads` fijo (se documenta en el manifest; x264 con hilos fijos es determinista en la misma build), GOP/keyint y `-preset` explícitos, sin `-movflags +use_metadata_tags`, sin marca de tiempo de creación. Audio AAC (o PCM si AAC resulta no determinista entre builds; se verifica en Fase 3). La build de FFmpeg se registra en el manifest y el determinismo **sólo se garantiza para la misma build** (OQ-07).

## Consecuencias
- (+) Cumple NFR-04 en el alcance definido.
- (−) Cambiar de versión de FFmpeg cambia el hash esperado → los *goldens* de hash de video se etiquetan con la versión.
- Mitigación adicional: además del hash del MP4 se verifican `trace_hash`, `audio_pcm_sha256` y hash de frames crudos (independientes del códec), de modo que una regresión se localice.
- Si A no logra bits idénticos entre ejecuciones en la misma build, recurrir a C.
