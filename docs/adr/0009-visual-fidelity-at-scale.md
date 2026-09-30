# ADR-0009 — Fidelidad visual a escala (100.000 escrituras)

- **Estado**: Propuesta — OQ-18
- **Requisitos**: FR-08, FR-21, NFR-01, NFR-03

## Contexto
El Ep. 01 lanza 100.000 escrituras en los primeros 5 s (PDR §5). No es posible ni legible dibujar 100.000 entidades, pero FR-08 prohíbe "interpolaciones ficticias" del comportamiento.

## Alternativas
| # | Opción | Pros | Contras |
| :-: | :--- | :--- | :--- |
| A | Simular sólo una muestra (p. ej. 1.000 escrituras) y escalar | Barato | Las métricas (write amp, tiempos de flush) dejan de ser reales: viola el espíritu del PDR |
| B | **Simular todas las operaciones exactas; visualizar una muestra determinista y agregados exactos** | Contadores reales; visual legible | Trace más grande (R-03/R-04) |
| C | Simular por lotes (agregando N escrituras en un evento) | Rápido | Se pierde granularidad de I/O (seeks individuales del B-Tree) |

## Decisión
**B.** Las 100.000 operaciones se simulan una a una en cada motor. Visualización: (1) **agregados exactos** (contadores, barras de llenado, tasa) calculados desde el estado; (2) **partículas/paquetes individuales** sólo para una muestra determinista (cada operación con índice `i` donde `i mod stride == 0`, `stride = ceil(rate_visible)`), con tope de entidades visibles por cuadro (`[DERIVED]` ≤ 200); (3) el cabezal del disco y los punteros se dibujan siempre desde el estado real. La muestra se declara en pantalla ("1 de cada N") para no inducir a error.

## Consecuencias
- (+) Las cifras mostradas son verdad de la simulación; el muestreo sólo afecta qué partículas se ven.
- (−) Coste de simulación 10⁶ eventos: presupuesto ≤ 30 s `[DERIVED]`; si no se cumple, recurrir a C para el tramo de benchmark con justificación explícita.
- Aplica por analogía a cualquier carga masiva futura.
