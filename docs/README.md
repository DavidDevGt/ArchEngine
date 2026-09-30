# Documentación técnica de ArchEngine

Derivada y alineada con [`PDR.md`](../PDR.md) (Versión Consolidada, octubre 2026; contradicciones resueltas). Idioma: español, como el PDR.

**Estado de los docs**: Especificación técnica de ingeniería consolidada. Las contradicciones originales del PDR (C-01…C-03) y las preguntas que bloqueaban la Fase 1 (OQ-01, 04, 08, 09, 11) han sido resueltas formalmente. Las decisiones arquitectónicas están registradas en [`adr/`](adr/) y el estado de preguntas abiertas en [11-open-questions.md](11-open-questions.md).

## Orden de lectura

| # | Documento | Para quién / qué resuelve |
| :-: | :--- | :--- |
| 00 | [Análisis del PDR](00-pdr-analysis.md) | Requisitos (FR/NFR), contradicciones resueltas y riesgos. **Empezar aquí.** |
| 01 | [Arquitectura general](01-architecture-overview.md) | Módulos, dependencias, flujos y presupuestos de render/simulación |
| 02 | [Motor de simulación](02-simulation-engine.md) | Reloj virtual en µs, trace columnar, redes, LSM, B-Tree, WAL y disco |
| 03 | [Render y geometría](03-rendering-and-geometry.md) | Cámara, culling analítico, capas, decals, primitivas y post-proceso |
| 04 | [Audio](04-audio-sonification.md) | Síntesis procedural a 48 kHz y mapeo determinista evento→sonido |
| 05 | [Pipeline y CLI](05-pipeline-and-cli.md) | `preview`, `film`, streaming FFmpeg + WAV temporal, manifest y errores |
| 06 | [Datos y esquemas](06-data-and-schemas.md) | YAML de topología, parámetros de motores con fuentes, escenas y trace |
| 07 | [Episodio 01](07-episode-01-spec.md) | Especificación del MVP («LSM-Trees vs B-Trees») |
| 08 | [NFR, seguridad, observabilidad, escalabilidad](08-nfr-security-observability-scalability.md) | SLA, determinismo, hardware de referencia y modelo de amenazas |
| 09 | [Pruebas y calidad](09-testing-and-quality.md) | Estrategia de pruebas, invariantes algorítmicos y goldens visuales |
| 10 | [Plan de entrega](10-delivery-plan.md) | Hitos, roadmap consolidado y definición de fases |
| 11 | [Preguntas abiertas](11-open-questions.md) | Registro de decisiones tomadas (OQ-01…11 resueltas) |
| 12 | [Trazabilidad](12-traceability.md) | Matriz: Requisito → diseño → verificación |
| 13 | [Episodios 02–04](13-architecture-episodes.md) | Cache-aside, cola de mensajes y load balancer: modelos, guion y resultados |
| — | [ADR](adr/) | Registros de Decisión Arquitectónica (ADR-0001…0009) |

## Convenciones

`FR-xx`/`NFR-xx` requisitos del PDR · `[DERIVED]` propuesta técnica para operativizar el PDR · `[OPEN QUESTION] OQ-xx` decisiones del sistema · `C-xx` contradicciones (resueltas) · `R-xx` riesgos · ADR = decisión con alternativas.

## Resumen de resoluciones clave

| Tema | Decisión acordada y consolidada | Dónde |
| :--- | :--- | :--- |
| **Arquitectura** | Simular → trace columnar → render/audio puros (dos fases) | [ADR-0001](adr/0001-two-phase-simulate-then-render.md) |
| **Modelo de tiempo** | Microsegundos enteros ($\mu\text{s}$) de 64 bits sin floats | [ADR-0002](adr/0002-time-model.md) |
| **2.5D y capas** | Orden por capas `LAYER` + pintor analítico (sin Z-buffer) | [ADR-0003](adr/0003-painters-algorithm-layers.md) |
| **Audio → FFmpeg** | Video 100% por pipe `stdin`; audio por WAV temporal (~11.5 MB) en `/tmp` eliminado en `finally` (C-03) | [ADR-0005](adr/0005-audio-delivery-to-ffmpeg.md) |
| **Preview vs Film** | Preview: $\le 200\text{ ms}$ (p90) / $\le 250\text{ ms}$ (p95) con trace en caché; Film: $\le 0.40\text{ s/cuadro}$ con postproceso completo (C-01) | [PDR](../PDR.md) §4.5, §6; [05](05-pipeline-and-cli.md) |
| **Ciclo de iteración** | "Segundos" = validación + simulación + preview ($< 3\text{ s}$); film completo = $\approx 12\text{ min}$ (C-02) | [PDR](../PDR.md) §2; [05](05-pipeline-and-cli.md) |
| **Hardware de referencia** | Runner `ubuntu-latest` GitHub Actions (4 vCPU x86_64 @ 2.8+ GHz) o estación local equivalente (OQ-01) | [PDR](../PDR.md) §6; [08](08-nfr-security-observability-scalability.md) |
| **Formato de escena** | Híbrido: YAML declarativo para datos/topología + módulo Python para el guion procedimental (OQ-04) | [ADR-0006](adr/0006-scene-authoring-format.md) |
| **Código base ausente** | Reimplementación limpia de `orbit_cam` y `packets_on` según especificación formal (OQ-08) | [PDR](../PDR.md) §4.1–4.2; [03](03-rendering-and-geometry.md) |
| **Tiempo de simulación** | 1 tick = 1 µs; mapeo a tiempo de video regulado por `time_scale` por segmento (OQ-09) | [ADR-0002](adr/0002-time-model.md) |
| **Parámetros LSM / B-Tree** | Definidos en `protocols.yaml` con fuentes bibliográficas reales (Cassandra, RocksDB, Petrov) (OQ-11) | [06](06-data-and-schemas.md) §3 |
| **Fase 1 Desbloqueada** | Todos los bloqueantes (OQ-01, 04, 08, 09, 11) formalmente resueltos | [10](10-delivery-plan.md), [11](11-open-questions.md) |
