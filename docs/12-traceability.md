# 12 — Matriz de trazabilidad PDR → diseño → verificación

Cada requisito de [00](00-pdr-analysis.md) tiene al menos un elemento técnico, una prueba y, si aplica, una decisión/pregunta abierta.

| Req. | Diseño (doc § / módulo) | Verificación ([09](09-testing-and-quality.md)) | ADR / OQ |
| :--- | :--- | :--- | :--- |
| FR-01 | [06](06-data-and-schemas.md) §2; `core/schema.py`, `data/topologies` | validación YAML, unit | ADR-0006 · OQ-04 |
| FR-02 | [06](06-data-and-schemas.md) §3; `data/protocols.yaml` | validación, precedencia | OQ-11, OQ-12 |
| FR-03 | [02](02-simulation-engine.md) §2; `simulation/engine.py`, `core/timebase.py` | invariantes 1, 2, 3, 8 | ADR-0001, 0002 · OQ-09 |
| FR-04 | [02](02-simulation-engine.md) §4; `networking/channel.py` | invariante 7 | OQ-18 (carga) |
| FR-05 | [02](02-simulation-engine.md) §5; `storage/*` | invariantes 4, 5 | OQ-11, OQ-19 |
| FR-06 | [02](02-simulation-engine.md) §6; `consensus/*` (post-MVP) | invariante 6 | OQ-12 |
| FR-07 | [02](02-simulation-engine.md) §7 | eventos de fallo en trace; invariante 4 | — |
| FR-08 | [02](02-simulation-engine.md) §1, §3; `Scene.compose` ([03](03-rendering-and-geometry.md) §1) | golden de imagen; revisión de que no hay estado visual sin origen en trace | ADR-0001, 0009 |
| FR-09 | [03](03-rendering-and-geometry.md) §2–3; `render/core.py` | unit de proyección; golden | OQ-15 |
| FR-10 | [03](03-rendering-and-geometry.md) §6; `render/theme.py` | lint sin literales de color; unit de tokens | OQ-14 |
| FR-11 | [03](03-rendering-and-geometry.md) §4 | invariante 11 | ADR-0003 |
| FR-12 | [03](03-rendering-and-geometry.md) §5 | golden de imagen | OQ-14 |
| FR-13 | [03](03-rendering-and-geometry.md) §7; `geometry/primitives.py` | unit + golden | C-05 (MemoryBlock) |
| FR-14 | [03](03-rendering-and-geometry.md) §8; `topology_layout.py` | unit: rutas sólo axiales, sin cruces evitables | — |
| FR-15 | [03](03-rendering-and-geometry.md) §9; `postprocess.py` | determinismo por `k` | OQ-14 |
| FR-16 | [04](04-audio-sonification.md) §3–5; `audio/sonification.py` | invariante 9 | OQ-13 |
| FR-17 | [04](04-audio-sonification.md) §1; ADR-0002 | alineación ±1 muestra | ADR-0002 |
| FR-18 | [05](05-pipeline-and-cli.md) §2; `pipeline/preview.py` | integración + benchmark preview | OQ-02 (resuelta), OQ-21 |
| FR-19 | [05](05-pipeline-and-cli.md) §3; `pipeline/film.py`, `ffmpeg_sink.py` | integración con `ffprobe` | ADR-0005 (aceptada), 0007 · OQ-05 (resuelta), OQ-06 |
| FR-20 | [06](06-data-and-schemas.md) §4; `scenes/` | validación de escena | ADR-0006 · OQ-04 (resuelta) |
| FR-21 | [07](07-episode-01-spec.md) | aceptación §4 de 07 | OQ-18, OQ-19 |
| FR-22 | [05](05-pipeline-and-cli.md) §7; CI ([10](10-delivery-plan.md) M0) | CI sin GPU, contenedor | OQ-22 |
| FR-23 | [10](10-delivery-plan.md) M7 | instalación en entorno limpio | OQ-10, OQ-17 (resuelta), OQ-23 |
| FR-24 | [10](10-delivery-plan.md) (licencia en M7) | — | OQ-10 |
| NFR-01 | [03](03-rendering-and-geometry.md) §10; [08](08-nfr-security-observability-scalability.md) §2 | benchmark p95 | ADR-0008 · OQ-01 (resuelta), OQ-20 |
| NFR-02 | [05](05-pipeline-and-cli.md) §2 | benchmark preview (p90 ≤ 200 ms, p95 ≤ 250 ms) | OQ-02 (resuelta) |
| NFR-03 | [08](08-nfr-security-observability-scalability.md) §1; trace columnar | contenedor 1,5 GB | ADR-0001, 0009 |
| NFR-04 | [08](08-nfr-security-observability-scalability.md) §3; [05](05-pipeline-and-cli.md) §5 | [09](09-testing-and-quality.md) §3 | ADR-0002, 0004, 0007 · OQ-07 (resuelta) |
| NFR-05 | [03](03-rendering-and-geometry.md) §2 | CI sin GPU | — |
| NFR-06 | [05](05-pipeline-and-cli.md) §3 | test sin archivos intermedios de video (audio WAV temp en `/tmp`) | ADR-0005 (aceptada) · OQ-05 (resuelta), OQ-21 |
| NFR-07 | [01](01-architecture-overview.md) §3 | import-linter, revisión de dependencias | — |
| NFR-08 | [05](05-pipeline-and-cli.md) §1–2 | medición ciclo validate+simulate+preview (< 3 s) | OQ-03 (resuelta) |

## Segmentos del Ep. 01 (PDR §5) ↔ diseño

| Segmento PDR | Sección de diseño |
| :--- | :--- |
| Intro & Benchmark | [07](07-episode-01-spec.md) §2 fila 1; [02](02-simulation-engine.md) §5.4; ADR-0009 |
| B-Tree (Aleatorio) | [02](02-simulation-engine.md) §5.1, §5.3; [03](03-rendering-and-geometry.md) §7 `StorageCylinder` |
| LSM-Tree (MemTable) | [02](02-simulation-engine.md) §5.2; `MemoryBlock` |
| Flush & Compaction | [02](02-simulation-engine.md) §5.2 |
| Simulación de Crash | [02](02-simulation-engine.md) §5.2, §7 |
| Conclusión & Balance | [07](07-episode-01-spec.md) §3.1 |

## Fuentes del PDR sin representación completa (declaradas)

- Paxos: sólo nombrado en PDR §3; sin especificación → OQ-12.
- Decisiones de open-core → OQ-10.
- Iluminación sintética: especificada como Lambert (`[DERIVED]`), PDR sólo la nombra.
