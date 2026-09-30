# ADR-0001 — Simulación completa previa (trace) y render como función pura

- **Estado**: Propuesta
- **Requisitos**: FR-08, FR-17, FR-18, NFR-01, NFR-02, NFR-04

## Contexto
El PDR exige que el visual sea reflejo de la simulación (§4.3), preview de un `t` arbitrario (§4.5), audio sincronizado a eventos (§4.4) y hashes reproducibles (§6).

## Alternativas
| # | Opción | Pros | Contras |
| :-: | :--- | :--- | :--- |
| A | **Lockstep**: simular y renderizar cuadro a cuadro | Memoria mínima, simple | Preview en `t` exige simular desde 0; audio requiere pasada extra de todos modos; difícil cachear |
| B | **Dos fases**: simular todo → trace + snapshots → render/audio como proyecciones | Preview con `state_at`; audio independiente; render paralelizable; tests de simulación sin gráficos | Memoria de trace; complejidad de snapshots |
| C | Precalcular estados por cuadro (1.800 snapshots completos) | `state_at` O(1) | Memoria/time altos; no sirve para audio a resolución de µs |

## Decisión
**B.** La simulación corre hasta `t_end` produciendo trace columnar + snapshots periódicos; render y audio consumen la trace.

## Consecuencias
- (+) `frame(k)` es función pura de `(trace, k)`; determinismo verificable por partes.
- (+) Preview rápido con caché (OQ-21).
- (−) Hay que mantener `snapshot/restore` en cada componente (coste de implementación).
- (−) Simulación interactiva/en vivo no es objetivo del PDR; queda fuera.
- Revisitar si la trace supera 1,5 GB en algún episodio (R-04).
