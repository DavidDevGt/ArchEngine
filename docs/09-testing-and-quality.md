# 09 — Estrategia de pruebas y calidad

Objetivo: demostrar FR/NFR con evidencia automatizada, especialmente determinismo y SLA. Complementa [08](08-nfr-security-observability-scalability.md).

## 1. Pirámide

| Nivel | Qué prueba | Herramienta | Requisitos |
| :--- | :--- | :--- | :--- |
| Unit | timebase, RNG, cola de eventos, LSM/WAL/B-Tree, canales, proyección, culling, layout Manhattan, sintetizadores | `pytest`, `hypothesis` | FR-03…FR-14, FR-16 |
| Propiedades | invariantes (ver §2) | `hypothesis` | FR-05, FR-07 |
| Golden (datos) | hash de trace y de PCM del Ep. 01 | `pytest` + archivos `*.sha256` | NFR-04 |
| Golden (imagen) | cuadros clave (`k` = 0, 150, 450, 900, 1350, 1650, 1799) frente a PNG de referencia con tolerancia cero en mismo entorno | `pytest` + diff | FR-08…FR-15 |
| Integración | `preview` y `film` cortos (p. ej. 2 s) con FFmpeg real; `ffprobe` | `pytest` | FR-18, FR-19 |
| Sistema | film completo Ep. 01 (nocturno) | CI | FR-21, NFR-01/03/04 |
| Rendimiento | benchmark por etapa; RSS pico | `pytest-benchmark`, contenedor 1,5 GB | NFR-01…03 |
| Arquitectura | reglas de import ([01](01-architecture-overview.md) §3) | `import-linter` | NFR-07, determinismo |
| Estático | tipos, lint, sin literales de color fuera de `theme.py` | `mypy --strict`, `ruff` | mantenibilidad |
| Seguridad | `pip-audit`, `bandit` (`yaml.load`, `shell=True`) | CI | §4 de 08 |

## 2. Invariantes y propiedades clave

1. **Causalidad**: todo evento emitido tiene `t_us ≥ now_us`.
2. **Orden total**: la trace es no decreciente en `(t_us, seq)`.
3. **Reproducibilidad**: dos simulaciones con mismo input y semilla ⇒ trace idéntica; semilla distinta ⇒ difiere donde hay estocasticidad.
4. **LSM**: tras `PowerLoss` + `replay`, claves confirmadas por WAL ⊆ claves recuperadas; ninguna SSTable se modifica tras crearse (inmutabilidad); `write_amp = bytes_out_total / bytes_logical ≥ 1`.
5. **B-Tree**: tras N inserciones, todas las claves recuperables; invariantes de ocupación/orden.
6. **Raft (post-MVP)**: a lo sumo un líder por término; `election_timeout ∈ [150, 300] ms`.
7. **Canales**: pérdida empírica ≈ `loss` (test estadístico con semilla fija); ningún paquete llega antes de `latency − jitter`.
8. **Timebase**: `frame_time_us(k)` es monótono y `k ↔ t` round-trip para todo `k ∈ [0,1800)`.
9. **Audio**: longitud exacta `n = duration × fs`; sin NaN/Inf; pico ≤ límite; evento en `t` ⇒ energía en muestra esperada ±1.
10. **Render**: dimensiones y bytes por cuadro = 6.220.800; mismo `(trace, k)` ⇒ mismo buffer.
11. **Culling/orden**: caras con `n·d ≥ 0` nunca se dibujan; orden estable con empates.

## 3. Pruebas de determinismo de extremo a extremo (NFR-04)

```text
run1: film --seed 42 → SHA-256 A
run2: film --seed 42 → SHA-256 B            assert A == B
run3: film --seed 43 → SHA-256 C            assert C != A
run4: film --seed 42 en otro proceso/cwd    assert igual A
```

Con el encoder bajo las banderas de [ADR-0007](adr/0007-reproducible-encoding.md). Variantes: distinto nº de hilos de FFmpeg (debe dar el mismo hash si se usa modo reproducible) y distinto directorio temporal.

## 4. Pruebas de rendimiento y memoria

- Benchmark: 120 cuadros repartidos por todos los segmentos (no sólo los simples). Reportar p50/p95/máx por etapa.
- Memoria: ejecutar `film` en contenedor con límite 1,5 GB; fallar si OOM. Adicional: `tracemalloc` para detectar fugas por cuadro (la memoria debe estabilizarse tras los primeros 100 cuadros).
- Preview: 30 llamadas consecutivas con caché; p95 ≤ 250 ms (gate provisional).

## 5. Datos de prueba

- Topologías mínimas (2 nodos) y la del Ep. 01.
- `protocols.yaml` de test con valores pequeños (MemTable de 1 MB) para simulaciones rápidas.
- Escenas de 2 s para integración.

## 6. Criterios de calidad de entrega (Definition of Done por tarea)

Tests y tipos en verde; cobertura ≥ 85 % en `simulation/` y `core/` `[DERIVED]`; sin violaciones de import; doc del módulo actualizada; si cambia salida de referencia, *goldens* regenerados con justificación en el PR.

## 7. Verificación humana (no automatizable)

Checklist de corrección técnica del Ep. 01 (R-05): revisión por alguien con experiencia en LSM/B-Tree; cada parámetro de motor con `source`; la narrativa no afirma más de lo que el modelo demuestra.
