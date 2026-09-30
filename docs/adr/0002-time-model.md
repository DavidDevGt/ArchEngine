# ADR-0002 — Modelo de tiempo: µs enteros y mapeo simulación ↔ video

- **Estado**: Propuesta (depende de OQ-09)
- **Requisitos**: FR-03, FR-17, NFR-04

## Contexto
PDR §4.3: "ticks discretos regulados Δt" y "paridad exacta de cuadros". Raft usa 150–300 ms; el video corre a 30 FPS (33,33 ms/cuadro, no entero en µs); el audio requiere resolución de muestra (20,8 µs a 48 kHz). El PDR no fija Δt ni la relación con el tiempo de video.

## Alternativas
| # | Opción | Contras |
| :-: | :--- | :--- |
| A | `float` en segundos | Acumula error; no determinista entre operaciones reordenadas |
| B | Tick = 1 ms entero | Insuficiente para latencias de disco/red sub-ms y sincronía de audio |
| C | **Tick = 1 µs entero (int64)** | Rango 9×10¹² s: holgado. Requiere disciplina de tipos |

## Decisión
**C.** `t_us: int`. Conversión de cuadro: `t_us(k) = (k × 1_000_000) // fps`. Conversión a muestra de audio: `(t_us × fs + 500_000) // 1_000_000`. Mapeo opcional tiempo-video→simulación por segmento: `t_sim = t_sim0 + (t_vid − t_vid0) × time_scale`, con `time_scale` **racional** (`fractions.Fraction` o par entero) para evitar `float`.
Δt de telemetría es un parámetro (defecto 1 ms) independiente del tick.

## Consecuencias
- (+) Determinismo total del tiempo; igualdad exacta entre frontera de segmento y cuadro (5 s = cuadro 150).
- (+) Cámara lenta narrativa sin alterar costos del modelo (sólo velocidad de reproducción).
- (−) `time_scale ≠ 1` complica la alineación de audio: el audio usa **tiempo de video** tras aplicar el mapeo a cada evento; se define una sola función `sim_to_video(t_sim)`.
- Pendiente OQ-09: confirmar que un video donde 1 s de video ≠ 1 s simulado es aceptable para el PDR ("paridad exacta de cuadros" se interpreta como un cuadro ⇔ un instante del reloj virtual).
