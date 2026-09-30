# ADR-0006 — Formato de autoría de escenas

- **Estado**: Propuesta — OQ-04
- **Requisitos**: FR-01, FR-20, NFR-08

## Contexto
PDR §2: "definición declarativa en YAML/Python". §3: `scenes/` = "scripts narrativos declarativos (episodios ejecutables)". No hay especificación de formato.

## Alternativas
| # | Opción | Pros | Contras |
| :-: | :--- | :--- | :--- |
| A | YAML puro | Seguro, validable, diffable | Poco expresivo para guiones (bucles, overlays calculados, `packets_on`) |
| B | Python puro (DSL en código) | Máxima expresividad | Ejecuta código arbitrario; validación estática limitada |
| C | **Híbrido**: topología/protocolos/líneas de tiempo base en YAML; "escena" = módulo Python que *construye* un objeto `Scene` declarativo (sin efectos laterales) | Seguro donde importa; expresivo donde hace falta | Dos superficies que documentar |

## Decisión
**C.** El módulo de escena expone `build() -> Scene` (datos puros: segmentos, cámara, acciones, overlays). El motor sólo consume `Scene`. `archengine validate` valida YAML sin importar Python; importar una escena Python es ejecución de código y se documenta como tal (ver [08](../08-nfr-security-observability-scalability.md) §4). El Ep. 01 se escribe como `ep01.yaml` (datos) + `scenes/ep01_lsm_vs_btree.py` (overlays/decals que requieren código).

## Consecuencias
- (+) Autores sin Python pueden variar topología, tiempos y parámetros.
- (−) Dos caminos de prueba; el esquema de `Scene` es contrato público desde v1.
- Si se decide A o B puros, los docs [06](../06-data-and-schemas.md) §4 y [08](../08-nfr-security-observability-scalability.md) §4 se simplifican.
