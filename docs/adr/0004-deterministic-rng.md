# ADR-0004 — RNG determinista por substreams

- **Estado**: Propuesta
- **Requisitos**: FR-04 (jitter/pérdida), FR-06 (timeouts Raft), FR-15 (grano), FR-16 (ruido), NFR-04

## Contexto
Hay cuatro consumidores de aleatoriedad (simulación, red, grano, audio). Un único generador compartido haría que añadir un evento cambie todo lo demás; `random`/`hash()` de Python no son reproducibles entre procesos (hash de `str` aleatorizado).

## Alternativas
| # | Opción | Contras |
| :-: | :--- | :--- |
| A | `random.seed(seed)` global | Orden-dependiente, frágil, global |
| B | Un `Generator` compartido | Acoplamiento entre subsistemas |
| C | **`numpy.random.SeedSequence` + `PCG64`, un substream por nombre estable** | Requiere mapear nombre→entropía |

## Decisión
**C.** `core.rng.stream(name: str) -> Generator` crea `SeedSequence(entropy=[seed, *blake2b_32bit_words(name)])` → `Generator(PCG64(...))`. `name` = ID de componente o `"grain"`, `"audio.noise"`. Nunca se usa `hash()` de Python. Pruebas fijan las primeras N salidas de cada stream (*golden*) para detectar cambios de versión de NumPy.

## Consecuencias
- (+) Añadir un nodo no altera la aleatoriedad de los demás.
- (+) Mismo código para simulación y post-proceso.
- (−) Una actualización mayor de NumPy puede cambiar el algoritmo de muestreo (`integers`, `uniform`); se fija la versión y el golden detecta el cambio.
