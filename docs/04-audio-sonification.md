# 04 — Audio y sonificación

Cubre FR-16, FR-17. Decisión relacionada: [ADR-0005](adr/0005-audio-delivery-to-ffmpeg.md).

## 1. Principios

1. **El audio se deriva de la trace**, no del render. Se calcula completo, antes o independientemente de los cuadros.
2. **Precisión de muestra**: un evento en `t_us` se ubica en la muestra `n = round(t_us × fs / 10⁶)` (aritmética entera: `(t_us*fs + 500_000)//1_000_000`). Esto cumple FR-17 (el pulso suena en el instante exacto en que el paquete cruza la arista) con mayor resolución que un cuadro (33,3 ms).
3. Sólo NumPy (NFR-07; sin SciPy). Determinista: mismo orden de operaciones, `float32`/`float64` fijo, RNG de `core.rng`.

## 2. Parámetros `[DERIVED]` (OQ-13)

| Parámetro | Valor provisional |
| :--- | :--- |
| Frecuencia de muestreo `fs` | 48.000 Hz |
| Canales | 2 (mismo contenido en MVP; panning por nodo opcional) |
| Precisión interna | Fase y acumuladores (`cumsum`) en `float64`; buffer maestro y mezcla en `float32` (ver [§8.2](#82-determinismo-y-precisión)); salida `s16le` con dither **desactivado** (determinismo) |
| Pico máximo | −1 dBFS (limitador duro `np.clip` tras normalización global fija, no dependiente de datos) |
| Duración | `frames / fps` s exactos (60,000 s → 2.880.000 muestras/canal) |

## 3. Bloques de síntesis (FR-16)

| Bloque | Estímulo | Síntesis |
| :--- | :--- | :--- |
| **Cluster Drone** | nodos activos en cada intervalo | Suma de senoidales: `Σ a_i·sin(2π f_i t)`; `f_i` fijada por índice de nodo sobre una escala (pentatónica, `[DERIVED]`). Amplitud `a_i` con envolvente suave al activarse/caer un nodo (rampa 20–50 ms para evitar clics). Se construye por tramos entre eventos `NodeUp/NodeDown` con fase continua. |
| **Pulso de transporte** | `PacketArrive` / cruce de arista | Onda cuadrada corta (~5–15 ms) × decaimiento `exp(−t/τ)`; frecuencia por tipo de canal. Acumulación por suma en un buffer maestro con *overlap-add*. |
| **Pitch sweep por latencia** | `LatencySpike` / incremento de latencia medida | Barrido ascendente de frecuencia: fase `φ(t)=2π∫f(t)dt`, con `f(t)=f0·(1+k·lat_ratio)` y `np.cumsum` para integrar (nunca `sin(2π f(t) t)`). |
| **Impacto de fallo/failover** | `NodeCrash`, `Failover` | Transitorio percusivo: ataque ≈ 1–2 ms, caída exponencial, pasa-bajos. |
| **Ruido blanco súbito** (Ep. 01 crash) | `PowerLoss` | Ruido gaussiano/uniforme de `core.rng` + corte duro del drone + pulso de reinicio limpio al inicio de `Recovery`. |

### Filtro paso bajo sin SciPy

Implementar como **convolución FFT** con respuesta impulsiva de un polo (`h[n]=(1−a)·aⁿ`, truncada a ≥ 10 constantes de tiempo) usando `np.fft.rfft`/`irfft`; para *resonant filter sweep* (Ep. 01 seg. 4), usar un biquad por bloques con coeficientes variables por bloque (bloques de 256 muestras) — bucle Python sobre bloques, no sobre muestras. Riesgo: rendimiento/variabilidad de FFT entre plataformas → cubierto por el alcance de determinismo (OQ-07).

## 4. Mapeo evento → sonido (tabla de datos)

Sin lógica ad hoc en las escenas: `audio/sonification.py` lee una tabla `SoundMap` (YAML/dict versionado):

| `kind` de la trace | Bloque | Parámetros |
| :--- | :--- | :--- |
| `bench.tick` (ráfaga de clicks) | Pulso | densidad ∝ tasa de escrituras (Ep. 01 seg. 1) |
| `disk.seek` | Tono grave saturado | duración = tiempo de seek → "silencios forzados por I/O wait" cuando `disk.busy` y sin avance |
| `memtable.put` | Arpegio | nota por secuencia de inserciones (estable, limpio) |
| `lsm.flush.start/end` | Tono descendente + sweep resonante | |
| `compaction.*` | Sweep de filtro | |
| `power.loss` | Ruido blanco + corte | |
| `wal.replay.end` | Pulso de reinicio | |
| `scene.end` | Acorde sostenido + fade | fade out lineal en los últimos segundos |

Densidad: eventos de alta frecuencia (10⁵ escrituras) se **agrupan** por ventana (p. ej. 1 ms) en un pulso con amplitud/tasa acorde; no se sintetiza un pulso por escritura.

## 5. Algoritmo de render de audio

```python
def render_pcm(trace, scene_len_us, fs) -> np.ndarray:  # (n, 2) float32
    n = (scene_len_us * fs) // 1_000_000
    buf = np.zeros(n, np.float32)
    add_drone(buf, trace.events(["node.up", "node.down"]))
    add_pulses(buf, trace.events(SoundMap.pulse_kinds))
    add_sweeps(buf, ...)
    add_impacts(buf, ...)
    add_noise(buf, rng("audio.noise"))
    buf *= GLOBAL_GAIN  # constante, no normalización dependiente de datos
    return np.stack([buf, buf], 1)
```

Memoria: 2.880.000 × 2 × 4 B ≈ 23 MB. Tiempo objetivo ≤ 5 s `[DERIVED]`.

## 6. Entrega a FFmpeg

Ver [ADR-0005](adr/0005-audio-delivery-to-ffmpeg.md) y [05](05-pipeline-and-cli.md) §3.

## 7. Verificación

- Test de alineación: un evento a `t` produce energía máxima en la muestra esperada (±1).
- Test de energía por segmento contra el guion del Ep. 01.
- Hash SHA-256 del PCM fijo en tests dorados ([09](09-testing-and-quality.md)).
- Tests de medición de [§8.7](#87-verificación-por-medición).

## 8. Técnicas de calidad de síntesis `[DERIVED]`

Resultado de la investigación sobre síntesis en NumPy. Son **propuestas** que refinan §3; ninguna está implementada y las decisiones abiertas se marcan como tales. Respetan el principio 3 (sólo NumPy, sin SciPy, determinista).

Fuentes: [Seeing Sound: Generative Techno and DSP in Pure NumPy](https://msuiche.com/posts/seeing-sound-generative-techno-and-dsp-in-pure-numpy/) (osciladores, PolyBLEP, envolventes, ducking, medición); [pyfar `signals.deterministic`](https://pyfar.readthedocs.io/en/stable/_modules/pyfar/signals/deterministic.html) (acumulación de fase y precisión). Lo no atribuido a ellas es criterio de diseño propio.

### 8.1 Osciladores sin aliasing

Una onda cuadrada o de sierra "ingenua" (`phase % 1`) tiene discontinuidades con armónicos infinitos; los que superan Nyquist (24 kHz a 48 kHz) rebotan al rango audible como ruido metálico. Afecta al **Pulso de transporte** (§3, onda cuadrada).

| Opción | Uso | Costo |
| :--- | :--- | :--- |
| **PolyBLEP** | Cuadrada/sierra: se resta una corrección polinómica de ~2 muestras alrededor de cada discontinuidad. Vectorizable con máscaras (`np.where`) sobre la fase. | ~10 líneas; elimina la mayor parte del aliasing. |
| **Aditiva con parciales limitados** | Drones: sumar sólo parciales con `f_k < fs/2`. Cero aliasing por construcción. | Más operaciones por nodo; aceptable (pocos nodos). |

Decisión propuesta: senoidales puras para el Cluster Drone; PolyBLEP para cuadrada/sierra.

### 8.2 Determinismo y precisión

- La fase se integra con `np.cumsum` en **`float64`**; en `float32` la suma acumulada pierde precisión y produce artefactos audibles. Se convierte a `float32` sólo al sintetizar la muestra.
- Toda aleatoriedad (ruido, fases iniciales, dispersión de *detune*) sale de substreams de `core.rng` ([ADR-0004](adr/0004-deterministic-rng.md)); nunca del RNG global.
- **Riesgo abierto** (enlaza con OQ-07): operaciones que dependan de BLAS/SIMD o de FFT pueden diferir entre plataformas. Hay que fijar el hash del PCM por plataforma y medir la diferencia antes de declararlo golden multiplataforma (NFR-04 sólo garantiza `trace_hash` y frames entre plataformas distintas).

### 8.3 Envolventes sin clics

- Decaimientos **exponenciales** (`exp(-t/τ)`), no rampas lineales, para pulsos e impactos.
- Todo evento lleva un ataque mínimo de 1–5 ms para evitar discontinuidades al inicio; las rampas del drone (20–50 ms, §3) se mantienen.
- Las envolventes son **moduladores**, no parte de la ruta de audio: generan una señal de control que multiplica amplitud o frecuencia de corte. Las envolventes se disparan una vez por evento; los LFO corren continuamente y se suman si modulan el mismo parámetro.

### 8.4 Filtros sin SciPy

Los IIR (biquad, tipo Moog) son **secuenciales**: cada muestra depende del estado previo, por lo que no se vectorizan. Un bucle Python por muestra equivale a ~2,9 M iteraciones por canal en 60 s, incompatible con el objetivo de ≤ 5 s (§5). Por eso se mantiene lo ya definido en §3:

1. Paso bajo fijo: convolución FFT con respuesta de un polo.
2. Filtro con barrido (*resonant sweep*): biquad **por bloques** de 256 muestras con coeficientes por bloque; bucle Python sobre bloques, no sobre muestras.
3. Las fórmulas del *RBJ Audio EQ Cookbook* son la referencia de coeficientes; para saturación suave se usa `np.tanh`.

`scipy.signal.lfilter` resolvería el bucle en C pero añade una dependencia y contradice NFR-07; queda **descartada** salvo que OQ-07/NFR-07 se reabran.

### 8.5 Mapeo de timbres adicionales

| Evento (§4) | Técnica sugerida |
| :--- | :--- |
| `disk.seek` / I/O wait | Ruido filtrado + silencios rítmicos; *Karplus-Strong* (buffer de ruido de un periodo, promediado entre muestras vecinas) para *clicks* con carácter mecánico. Nota: KS es un bucle recursivo; usar por bloques o acotar a pocos eventos. |
| Pitch sweep | `f(t)` integrada con `cumsum` (ya en §3). |
| Impacto de fallo | Ruido + transitorio exponencial + paso bajo (ya en §3). |
| Timbres metálicos | FM simple (portadora + moduladora) con índice de modulación ∝ métrica; barata y vectorizable. |

### 8.6 Mezcla

- **Sidechain / ducking** de eventos críticos sobre el drone: ataque 1–5 ms, *release* 200–350 ms exponencial (`1 − (1 − floor)·exp(−t/τ)`), para dar prioridad a `NodeCrash` / `PowerLoss`.
- Capas con *detune* pequeño o fases iniciales distintas dan sensación de ancho sin panning (útil si se activa el panning por nodo de §2).
- Cadena de salida fija y no dependiente de datos: `tanh` suave → `np.clip` a −1 dBFS (§2). Sin normalización adaptativa.
- Las colas de reverb/decay se suman por solapamiento (*overlap-add*) entre segmentos, sin cortes duros.

### 8.7 Verificación por medición

Validar con métricas automatizadas en lugar de escucha manual:

- Espectro por segmento: sin energía anómala sobre ~20 kHz (detecta aliasing).
- RMS por segmento del Ep. 01 frente al guion ([07](07-episode-01-spec.md)).
- Ancho estéreo (correlación L/R) si se activa panning.
- Alineación de eventos (±1 muestra) y hash del PCM (ver §7).

### 8.8 Decisiones abiertas

| Tema | Pregunta | Afecta |
| :--- | :--- | :--- |
| PolyBLEP vs. aditiva limitada | ¿Un solo método para toda onda no senoidal? | `audio/sonification.py` |
| Hash de PCM entre plataformas | ¿Se exige paridad o sólo por plataforma? | NFR-04, OQ-07 |
| Karplus-Strong / FM | ¿Entran en el MVP o post-MVP? | alcance Fase 3 |
