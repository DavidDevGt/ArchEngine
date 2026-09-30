# 08 — Requisitos no funcionales: rendimiento, determinismo, seguridad, observabilidad y escalabilidad

Cubre NFR-01…NFR-08. El PDR no contiene requisitos explícitos de seguridad ni observabilidad; lo que sigue es `[DERIVED]` del perfil del producto (CLI que lee archivos, ejecuta FFmpeg y puede cargar código de escenas).

## 1. Matriz NFR → mecanismo

| NFR | Mecanismo | Verificación |
| :--- | :--- | :--- |
| NFR-01 ≤ 0,40 s/cuadro | Presupuesto por etapa ([03](03-rendering-and-geometry.md) §10), capa estática, NumPy vectorizado, buffers preasignados | Benchmark de 120 cuadros representativos; p95 ≤ 0,40 s en hardware de referencia |
| NFR-02 preview | Trace cacheada, `state_at` por snapshot, render directo a PNG en memoria | Benchmark de preview con caché caliente; p90 ≤ 200 ms, p95 ≤ 250 ms |
| NFR-03 ≤ 1,5 GB | Trace columnar, frame buffer único (6,2 MB), PCM 23 MB, sin lista de frames | Contenedor con `--memory=1.5g`; `tracemalloc` + RSS pico |
| NFR-04 hash idéntico | ADR-0002/0004/0007; manifest; imagen congelada | 2 ejecuciones en mismo contenedor → mismo SHA-256 |
| NFR-05 sin GPU | Raster Skia CPU | CI sin GPU |
| NFR-06 sin intermedios | Pipe rawvideo rgb24 a stdin; audio WAV temporal en tempfile | Test: sin archivos de video en disco; WAV temp eliminado en finally |
| NFR-07 ligero | 3 dependencias de runtime + FFmpeg externo | Revisión de `pyproject` en CI |
| NFR-08 iteración rápida | `validate` + `simulate` + `preview` | Medición de ciclo interactivo con caché (< 3 s) |

## 2. Rendimiento y Hardware de Referencia (OQ-01 resuelta)

- **Hardware de referencia**: Runner `ubuntu-latest` de GitHub Actions (4 vCPU x86_64, tipo AMD EPYC 7763 o Intel Xeon Platinum 8370C @ 2.8+ GHz, 16 GB RAM) o estación de trabajo local moderna ($\ge 4$ núcleos físicos @ $\ge 3.0\text{ GHz}$).
- **Gates de CI**: (1) benchmark corto (PR): 60 cuadros, p95 ≤ 0,40 s × factor de tolerancia 1,25 por ruido de CI; (2) nocturno: film completo, tiempo total ≤ 720 s + tiempo de simulación/audio (`[DERIVED]` ≤ 10 s + 5 s).
- **Medición**: `time.perf_counter_ns()` por etapa (sólo métrica, nunca entra en la lógica determinista).
- **Desglose del SLA**: 0,40 s/cuadro incluye raster + post + escritura al pipe; no incluye codificación x264 si corre en paralelo en otros núcleos (supuesto — OQ-20).

## 3. Determinismo (NFR-04)

Cadena de garantías:

| Capa | Fuente de no determinismo | Control |
| :--- | :--- | :--- |
| Simulación | reloj, RNG, orden de hash/sets, hilos | [ADR-0002](adr/0002-time-model.md), [ADR-0004](adr/0004-deterministic-rng.md), [02](02-simulation-engine.md) §8 |
| Render | fuentes del sistema, AA/hinting, versión de Skia, orden de dibujo | fuente empaquetada, versión fijada, orden `(layer, depth, id)` |
| Post-proceso | ruido | semilla por `k` |
| Audio | FFT/NumPy por plataforma, RNG | `float32` fijo, RNG `core.rng`, alcance de entorno |
| Codificación | hilos x264, metadatos, versión | [ADR-0007](adr/0007-reproducible-encoding.md) |

**Alcance** (OQ-07): garantía de SHA-256 **idéntico del MP4** dentro de un entorno congelado (misma imagen Docker / lockfile / FFmpeg). Entre plataformas sólo se garantiza la igualdad de `trace_hash` (y de frames crudos en la misma arquitectura de CPU). El PDR dice "100 % reproducible … mismo entorno y semilla"; esto lo concreta sin ampliarlo.

## 4. Seguridad `[DERIVED]`

Modelo de amenazas: el autor es de confianza, pero YAML/escenas pueden venir de terceros (repos, PRs en CI).

| Amenaza | Control |
| :--- | :--- |
| Ejecución de código vía YAML | `yaml.safe_load`; prohibido `yaml.load`; sin tags personalizados |
| Ejecución de código vía escenas Python | Son **código**: se documenta como no confiable por defecto; en CI sólo ejecutar escenas del propio repo/PRs de confianza; `validate` sobre YAML no importa Python ([ADR-0006](adr/0006-scene-authoring-format.md)) |
| Inyección de comandos a FFmpeg | `subprocess` con lista de argumentos, `shell=False`; rutas de salida validadas; nunca interpolar entrada del YAML en argumentos FFmpeg |
| Path traversal en salidas/caché | Normalizar con `Path.resolve()`; salida sólo en directorio indicado |
| Agotamiento de recursos (YAML hostil: 10¹⁰ escrituras) | Límites de validación: máx. eventos simulados, tamaño de topología, duración, resolución (configurables, `--strict-limits`) |
| Cadena de suministro | Dependencias fijadas con hash (`pip-compile --generate-hashes`); `pip-audit` en CI; wheels oficiales de `skia-python`; SBOM en release |
| Licencias | JetBrains Mono (OFL 1.1), `skia-python` (BSD-3), NumPy (BSD), FFmpeg (LGPL/GPL según build; OQ-23) |
| Archivos temporales (WAL de audio) | `tempfile.mkstemp` con permisos 0600, eliminación en `finally` |
| Secretos | No hay; CI sin credenciales salvo publicación PyPI (Trusted Publishing/OIDC) |

## 5. Observabilidad `[DERIVED]`

No hay servicio que monitorizar; "observabilidad" = **diagnosticar runs y regresiones**.

- **Logging**: `logging` estándar, niveles, formato `key=value`; `--log-json` para CI. Sin `print` en biblioteca.
- **Métricas por ejecución** (en manifest): tiempos por etapa (simulate, audio, frame p50/p95/máx), nº de eventos, RSS pico, bytes escritos a FFmpeg.
- **Progreso**: línea cada 30 cuadros (cuadro, ETA, ms/cuadro) en `stderr`.
- **Trazabilidad**: manifest con versiones, semilla y hashes; se sube como *artifact* en CI.
- **Depuración**: `simulate --dump` exporta la trace; `preview --debug-overlay` dibuja layers/IDs/bounding boxes y `LAYER`.
- **Alertas de regresión**: job que compara `render_p95` con la línea base guardada y falla si > +10 %.

## 6. Escalabilidad

| Eje | Límite/estrategia |
| :--- | :--- |
| Duración del video | Lineal en cuadros; memoria constante (un frame en vuelo). |
| Tamaño de topología | Coste de simulación O(eventos); geometría O(nº primitivas) por cuadro → presupuesto de caras (`[DERIVED]`: ≤ 50.000 caras/cuadro en MVP). |
| Volumen de eventos | Trace columnar; ≈ 2–4 × 10⁶ eventos en Ep. 01 × ≈ 38 B/evento (8+8+4+2+8+8) ≈ 80–160 MB. Si se supera, muestreo/agregación ([ADR-0009](adr/0009-visual-fidelity-at-scale.md)). |
| Multi-episodio/CI | Escala **horizontal** ejecutando un proceso por episodio (matriz de jobs); no hay estado compartido. |
| Un episodio | Escala vertical vía ADR-0008 (paralelismo de cuadros con reensamblado ordenado) — opcional. |
| Resoluciones mayores | Coste ≈ lineal en píxeles: 4K ≈ 4× → fuera del SLA (OQ-16). |

## 7. Fiabilidad

- Fallos atómicos: salida vía `.partial` + rename.
- Reintentos: ninguno automático; el run es determinista, relanzar produce el mismo resultado.
- Compatibilidad: `schema_version` en YAML; cambios incompatibles ⇒ versión mayor del esquema con migrador.
