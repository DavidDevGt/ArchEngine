# 00 — Análisis del PDR

> Fuente: [`PDR.md`](../PDR.md) (Versión Consolidada, octubre 2026). Este documento extrae requisitos, asigna IDs estables, documenta la resolución de contradicciones y mitiga riesgos. Las decisiones de diseño se detallan en [`adr/`](adr/) y el estado de preguntas en [11-open-questions.md](11-open-questions.md).

Convenciones de todo `docs/`:

| Marca | Significado |
| :--- | :--- |
| `FR-xx` / `NFR-xx` | Requisito funcional / no funcional **explícito en el PDR** (con sección de origen). |
| `[DERIVED]` | Decisión técnica adoptada para hacer implementable un requisito; formalizada en la arquitectura y PDR. |
| `[OPEN QUESTION] OQ-xx` | Pregunta de diseño del sistema. Las que bloqueaban Fase 1 (OQ-01, 04, 08, 09, 11) están resueltas. |
| `ADR-xxxx` | Decisión arquitectónica en [`adr/`](adr/). |

---

## 1. Producto en una frase

ArchEngine es un motor **headless, determinista, en CPU** que convierte una descripción declarativa de arquitectura (topología + protocolos + guion) en un video explicativo, donde **el estado visual y el audio son consecuencia directa de una simulación** (PDR §1, §4.3).

## 2. Requisitos funcionales

| ID | Requisito | PDR § |
| :--- | :--- | :---: |
| FR-01 | Topologías declarativas en YAML: nodos, redes y capacidades de buffer (`data/topologies/`). Definición "YAML/Python". | 2, 3 |
| FR-02 | Parámetros operativos (timeouts, TTL, tamaños de frame) y motores (LSM, B-Tree, disco) en `data/protocols.yaml`. | 3, 4.3 |
| FR-03 | Simulación por eventos discretos con reloj virtual en microsegundos enteros ($\Delta t = 1\ \mu\text{s}$). | 4.3 |
| FR-04 | Canales de red simulados con latencia, jitter, pérdida y particiones (`networking/channel.py`). | 2, 3 |
| FR-05 | Motores de almacenamiento simulados: LSM-Tree, WAL, B-Tree y modelo de disco mecánico (`DiskModel`). | 3, 4.3 |
| FR-06 | Máquinas de estado de consenso: Raft, Paxos (Raft detallado: timeout de elección estocástico 150–300 ms, `Heartbeat`, `Candidate`, `RequestVote`). | 3, 4.3 |
| FR-07 | Inyección de fallos: caídas parciales de nodos, particiones, corte de energía (`PowerLoss`). | 2, 4.3, 5 |
| FR-08 | El estado visual se lee de `node.state` (transiciones reales); **sin interpolaciones ficticias** del comportamiento. | 4.3 |
| FR-09 | Render vectorial CPU con Skia (`skia-python`), cámara orbital paramétrica (isométrica y cenital), cadena `World→View→Projection`. | 1, 4.1 |
| FR-10 | Paleta semántica `THEME` (`bg`, `node_idle`, `bus`, `mem`, `disk`, `alert`) e iluminación sintética. | 3, 4.1 |
| FR-11 | Back-face culling analítico y orden por capas `LAYER` (sin Z-buffer). | 4.1 |
| FR-12 | Decals proyectivos de telemetría (`% CPU`, `IOPS`, `QPS`, logs) vía `Skia.Matrix.setPolyToPoly`, fuente JetBrains Mono. | 4.1 |
| FR-13 | Primitivas: `ServerRack`, `CircularQueue`, `StorageCylinder`, `NetworkPipes`, `MemoryBlock`; zócalos RAM. | 3, 4.2 |
| FR-14 | Enrutamiento ortogonal tipo Manhattan para buses (`topology_layout.py`). | 3, 4.2 |
| FR-15 | Post-proceso: viñeta matricial y grano analógico determinista. | 3, 4.1 |
| FR-16 | Sonificación procedural con NumPy a 48 kHz: drone de clúster, pulsos de transporte, pitch sweep por latencia, impacto percusivo en fallo/failover. | 4.4 |
| FR-17 | Audio acoplado frame a frame a los eventos de red y cómputo (sincronía exacta con la trace). | 1, 4.4 |
| FR-18 | Modo `preview <scene> <t_segundos>`: un cuadro clave a PNG desde memoria. | 4.5 |
| FR-19 | Modo `film`: video `rgb24` crudo por pipe a `stdin` de FFmpeg + audio WAV temporal, sin archivos intermedios de video. | 1, 4.5 |
| FR-20 | Escenas/episodios como scripts narrativos declarativos ejecutables (`scenes/`). | 3, 4 |
| FR-21 | MVP Episodio 01 «LSM-Trees vs B-Trees», 9:16, 1080×1920, 60 s, 30 FPS, 6 segmentos, 1.800 cuadros. | 5 |
| FR-22 | Ejecución headless en scripts locales, CI (GitHub Actions) y Docker mínimo. | 2, 6 |
| FR-23 | Empaquetado y publicación en PyPI (Fase 4); Python ≥ 3.11. | 7, cabecera |
| FR-24 | Proyecto open-core. | 1 |

## 3. Requisitos no funcionales

| ID | Requisito | Valor Consolidado | PDR § |
| :--- | :--- | :--- | :---: |
| NFR-01 | Tiempo de cuadro en modo film | $\le 0,40\text{ s/cuadro}$ en CPU estándar de referencia (1.800 cuadros $\approx 12\text{ min}$ monoproceso; $\approx 3.5\text{ min}$ con 4 workers) | 1, 6 |
| NFR-02 | Latencia de preview | $\le 200\text{ ms}$ objetivo (p90) / $\le 250\text{ ms}$ límite (p95 en CI), con trace en caché caliente | 4.5, 6 |
| NFR-03 | RAM pico | $\le 1,5\text{ GB}$ (probado con límites cgroup/Docker) | 6 |
| NFR-04 | Determinismo | SHA-256 idéntico en MP4 final bajo el mismo contenedor de referencia; paridad estricta de `trace_hash` y frames crudos entre plataformas | 6 |
| NFR-05 | Sin GPU | Raster Skia CPU puro | 1, 2 |
| NFR-06 | Sin escrituras intermedias pesadas a disco | Pipeline de video $100\%$ por pipes ($\approx 11,2\text{ GB}$ ahorrados); audio por WAV temporal ($\approx 11,5\text{ MB}$) eliminado en `finally` | 1, 4.5 |
| NFR-07 | "Ultraligero" / contenedores mínimos | Pocas dependencias fijadas: Python, `skia-python`, NumPy, FFmpeg externo | cabecera, 1, 2 |
| NFR-08 | Iteración rápida | Ciclo interactivo `validate + simulate + preview` en $< 3\text{ s}$ en desarrollo | 2, 4.5 |

## 4. Arquitectura propuesta por el PDR (resumen)

Separación limpia en paquetes (`core`, `data`, `simulation`, `geometry`, `render`, `audio`, `pipeline`, `scenes`, `cli`). Flujo conceptual de dos fases: *topología + protocolos + guion → simulación → trace columnar inmutable → (render ∥ audio) → FFmpeg*. Detalle técnico en [01-architecture-overview.md](01-architecture-overview.md).

## 5. Contradicciones y ambigüedades resueltas

| ID | Hallazgo Original | Resolución Consolidada |
| :--- | :--- | :--- |
| **C-01** | Preview: **200 ms** (§4.5) vs **250 ms** (§6). Además, un cuadro de film cuesta 400 ms. | **Resuelta**. Se unifica en PDR y docs: $\le 200\text{ ms}$ es el objetivo de diseño (p90) y $\le 250\text{ ms}$ el umbral de aceptación en CI (p95) con trace en caché caliente. A diferencia de film (400 ms de raster completo + grano analógico pesado + encoding x264 bloqueante por pipe), preview reutiliza la trace, omite compresión y codifica un solo PNG en memoria. |
| **C-02** | §2 promete recompilar "en segundos"; §6 fija $\approx 12\text{ min}$ para el video completo. | **Resuelta**. Se formaliza: "en segundos" ($< 3\text{ s}$) describe el bucle de autoría iterativa (`validate` + `simulate` + `preview` de cuadros clave). La exportación del video completo de 60 s (1.800 cuadros) toma $\approx 12\text{ min}$ monoproceso ($\approx 3,5\text{ min}$ con render concurrente). |
| **C-03** | Audio: FFmpeg recibe el video por un único `stdin` y el PDR prohíbe intermedios a disco. | **Resuelta** vía [ADR-0005](adr/0005-audio-delivery-to-ffmpeg.md). El video fluye $100\%$ por pipe a `stdin` (evita $\approx 11,2\text{ GB}$ de disco). El audio sintetizado se pasa mediante un archivo WAV temporal mínimo ($\approx 11,5\text{ MB}$) creado con `tempfile.mkstemp` y borrado de forma atómica en `finally`. |
| **C-04** | `packets_on` en `scenes/common.py` vs primitiva `NetworkPipes` en `geometry/`. | **Resuelta**. `NetworkPipes` reside en `geometry/` y expone la geometría; el helper de escena `packets_on(channel, t)` interpola las posiciones espaciales de los paquetes en vuelo. |
| **C-05** | `primitives.py` lista "zócalos RAM" pero falta primitiva para MemTable verde. | **Resuelta**. Primitiva `MemoryBlock` añadida formalmente en `geometry/primitives.py` y PDR §4.2. |
| **C-06** | `protocols.yaml` carece de parámetros para motores (MemTable, B-Tree, seek disco). | **Resuelta**. Sección `engines:` añadida a `protocols.yaml` con parámetros y fuentes bibliográficas formales (OQ-11). |
| **C-07** | Raft detallado en §4.3 pero fuera del MVP y del roadmap. | **Resuelta**. Interfaces `ConsensusNode` se definen limpias en Fase 2; implementación completa de Raft/Paxos pasa a backlog post-MVP sin bloquear el Episodio 01. |
| **C-08** | "Mismo entorno" y "CPU estándar" sin definición. | **Resuelta** (OQ-01, OQ-07). Hardware de referencia: runner `ubuntu-latest` de GitHub Actions (4 vCPU x86_64 @ 2.8+ GHz) o estación local ($\ge 4$ núcleos @ $\ge 3.0\text{ GHz}$). Entorno: contenedor Docker congelado (`python:3.11-slim`, skia, numpy, ffmpeg bitexact). |
| **C-09** | Enlaces a `snes-engine-src` inaccesibles. | **Resuelta** (OQ-08). Se eliminaron los enlaces rotos en el PDR; el comportamiento de `orbit_cam` y `packets_on` se especifica formalmente por matemática e interfaz. |
| **C-10** | Formato de escena sin definir. | **Resuelta** (OQ-04). Formato híbrido: YAML para datos y configuración estática, módulo Python para el guion procedimental ejecutable ([ADR-0006](adr/0006-scene-authoring-format.md)). |
| **C-11** | Nombre del ejecutable CLI sin definir. | **Resuelta** (OQ-17). Ejecutable `archengine` con subcomandos `preview`, `film`, `validate`, `simulate`, `doctor`. |
| **C-12** | 100.000 escrituras concurrentes en 5 s de video. | **Resuelta** (OQ-18). Simulación exacta evento a evento con arribo Poisson/concurrente; visualización muestreada según [ADR-0009](adr/0009-visual-fidelity-at-scale.md). |

## 6. Riesgos y mitigaciones

| ID | Riesgo | Prob. | Impacto | Mitigación |
| :--- | :--- | :---: | :---: | :--- |
| R-01 | 0,40 s/cuadro en 1080×1920 con Skia CPU no se alcanza. | M | A | Presupuesto por etapa ([03](03-rendering-and-geometry.md) §10), caches de geometría, gate de CI en hardware de referencia, paralelismo opcional ([ADR-0008](adr/0008-render-concurrency.md)). |
| R-02 | Hash idéntico falla por FFmpeg o fuentes. | M | A | [ADR-0007](adr/0007-reproducible-encoding.md); banderas `+bitexact`; fuente *JetBrains Mono* empaquetada; manifest de auditoría. |
| R-03 | Simulación en Python pura lenta para 10⁵–10⁶ eventos. | M | M | Trace columnar NumPy; agregación controlada ([ADR-0009](adr/0009-visual-fidelity-at-scale.md)); presupuesto de simulación $\le 10\text{ s}$. |
| R-04 | Trace/estado excede 1,5 GB. | B | A | Log columnar compacto ($\approx 38\text{ B/evento}$) + snapshots cada 1 s; validado con límite Docker de 1,5 GB. |
| R-05 | Afirmaciones técnicas incorrectas del video. | M | A | Parámetros de motores respaldados con fuentes (Cassandra, RocksDB, Petrov) y tests de invariantes algorítmicos ([09](09-testing-and-quality.md)). |
| R-06 | Artefactos del painter's algorithm sin Z-buffer. | M | M | [ADR-0003](adr/0003-painters-algorithm-layers.md): jerarquía estricta de capas `LAYER` y tests visuales de regresión. |
| R-07 | Wheels de `skia-python` no disponibles. | B | A | Fijar versión probada; contenedor Docker oficial con dependencias nativas instaladas. |
| R-08 | Scope creep: Raft/Paxos/redes saturan el roadmap. | B | M | Post-MVP explícito; interfaces limpias preparadas en Fase 2. |
| R-09 | Calendario sin holgura o tareas faltantes. | B | M | Roadmap consolidado en 4 fases con B-Tree, disco, WAL, CLI y CI integrados ([10](10-delivery-plan.md)). |
| R-10 | Dependencia de código heredado no disponible. | B | A | Reimplementación limpia basada en especificación matemática e interfaces puras. |
| R-11 | Backpressure del pipe a FFmpeg. | B | M | Escritura síncrona bloqueante en orden; drenaje de `stderr` en hilo secundario; [05](05-pipeline-and-cli.md). |

## 7. Estado de Decisiones y Bloqueos

Las preguntas que **bloqueaban la Fase 1** (OQ-01, OQ-04, OQ-08, OQ-09, OQ-11) han sido **formalmente resueltas**:
- **OQ-01**: Hardware de referencia fijado (runner 4 vCPU x86_64).
- **OQ-04**: Formato de escena híbrido aprobado (YAML + Python).
- **OQ-08**: Reimplementación matemática limpia sin código heredado externo.
- **OQ-09**: Reloj virtual en ticks de 1 µs con `time_scale` por segmento.
- **OQ-11**: Parámetros de motores documentados con fuentes bibliográficas reales.

La **Fase 1 está lista para ejecución**.
