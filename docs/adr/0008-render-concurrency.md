# ADR-0008 — Concurrencia del render

- **Estado**: Propuesta — OQ-20
- **Requisitos**: NFR-01, NFR-03, NFR-04

## Contexto
NFR-01 = 0,40 s/cuadro y "≈ 12 min" de video completo (1.800 × 0,40) implican **monoproceso** secuencial: el PDR calcula el total como producto, no como throughput paralelo. Aun así, R-01 (no alcanzar 0,40 s) necesita una válvula.

## Alternativas
| # | Opción | Pros | Contras |
| :-: | :--- | :--- | :--- |
| A | **Monoproceso síncrono** | Simple, determinista, memoria mínima | Sin margen si se excede 0,40 s |
| B | `multiprocessing` por cuadro, buffer de reordenamiento | Reduce tiempo total ≈ /N | Memoria ≈ N × 6,2 MB + copias de trace; orden estricto para el pipe; Skia por proceso |
| C | Hilos con Skia | — | GIL y seguridad de hilos de skia-python no garantizadas |

## Decisión
**A como baseline y criterio de SLA** (el SLA de 0,40 s se mide por cuadro en un proceso). **B como modo opcional** `--jobs N` activable sólo si OQ-20 lo permite, con reglas: `frame(k)` es función pura, los workers reciben la trace por memoria compartida de sólo lectura (`multiprocessing.shared_memory`), el productor escribe al pipe estrictamente en orden `k`, ventana de reordenamiento acotada (≤ 2N cuadros en vuelo) para respetar NFR-03.

## Consecuencias
- (+) El resultado de B es idéntico byte a byte al de A (mismo `frame(k)`), verificado por test.
- (−) El tiempo total deja de ser `1.800 × 0,40` y la métrica de SLA debe reportarse como **p95 por cuadro en modo monoproceso**.
- No se implementa B antes de medir A (Fase 1 end).
