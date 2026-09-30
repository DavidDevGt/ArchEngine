# ADR-0003 — Orden por capas (painter's algorithm) y culling analítico en lugar de Z-buffer

- **Estado**: Aceptada (decisión tomada en PDR §4.1; este ADR documenta consecuencias)
- **Requisitos**: FR-11, NFR-01, NFR-05

## Contexto
El PDR especifica back-face culling analítico y orden por `LAYER`, "suprimiendo el costo de sincronización de un Z-buffer". Skia es un rasterizador 2D; no ofrece Z-buffer.

## Alternativas
| # | Opción | Pros | Contras |
| :-: | :--- | :--- | :--- |
| A | **Capas + orden por profundidad del centroide** (PDR) | Barato, compatible con Skia, determinista | No resuelve intersecciones cíclicas |
| B | Z-buffer por software en NumPy | Correcto por píxel | 2M píxeles × geometría → fuera del presupuesto 0,40 s |
| C | BSP/ordenamiento por polígono | Correcto | Costoso; complejidad alta |

## Decisión
**A**, con reglas de composición: primitivas convexas y sin interpenetración dentro de una capa; `LAYER` explícito por primitiva; clave de orden `(layer, depth, id)`.

## Consecuencias
- (+) Coste O(n log n) en nº de caras, determinista.
- (−) Escenas con solapes entre cuerpos de una misma capa pueden mostrar artefactos; se mitiga con tests de imagen y usando capas distintas (p. ej. cabezal sobre disco).
- (−) Geometrías cóncavas (anillos) se descomponen en caras convexas.
- Revisitar si aparecen artefactos no solucionables con capas (p. ej. cámara orbital completa).
