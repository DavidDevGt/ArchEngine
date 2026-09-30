# ArchEngine

Motor determinista y headless (CPU) para generar explicaciones visuales de arquitectura de software: la simulación del protocolo produce el estado visual, que se renderiza con Skia y se envía a FFmpeg.

Definición de producto en [PDR.md](PDR.md); diseño detallado en [docs/](docs/README.md).

## Uso

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"      # Python 3.11+ y FFmpeg en el PATH

archengine doctor                              # verifica entorno, FFmpeg y fuente
archengine validate src/archengine/data/protocols.yaml
archengine simulate ep01 --dump trace.npz      # solo simulación (+ volcado de trazas)
archengine preview ep01 22 -o frame.png        # un cuadro en t = 22 s
archengine film ep01 -o out/ep01.mp4           # video completo 1080x1920, 60 s, 30 FPS
```

`film` escribe `out/ep01.mp4` y `out/ep01.mp4.manifest.json` (hashes SHA-256 de entradas, trace,
audio y video; versiones; tiempos). Códigos de salida: `0` ok · `2` uso/validación · `3` falta FFmpeg ·
`4` fallo de FFmpeg · `5` SLA incumplido con `--strict` · `1` error inesperado.

Con Docker:

```bash
docker build -t archengine .
docker run --rm -v "$PWD/out:/out" archengine film ep01 -o /out/ep01.mp4
```

## Episodio 01 — «LSM-Trees vs B-Trees: ¿por qué Cassandra escribe tan rápido?»

Cada motor se simula con la misma carga (100.000 escrituras aleatorias, llegadas Poisson sembradas)
sobre un modelo físico de HDD 7200 RPM (seek, rotación, transferencia). Nada del resultado está
escrito a mano: el cabezal que salta, la MemTable que se llena, el flush, la compactación y la
recuperación del WAL tras un `PowerLoss` son transiciones de la simulación; el audio se deriva de
los mismos eventos. Resultados medidos con la semilla 42:

| Métrica | LSM-Tree | B-Tree |
| :--- | ---: | ---: |
| Escrituras/s sostenidas | ≈ 50.200 | ≈ 29,7 |
| Amplificación de escritura | 2,9× | 8,0× |
| Amplificación de lectura | 5 SSTables (pico, antes de compactar) | 1,9 páginas/op |
| Recuperación tras `PowerLoss` | 164 ms (35.712 registros del WAL) | — |

El guion solo decide *cuándo se mira* cada tramo de simulación (`TimeMap` por motor, cámara lenta o
pausa); nunca cambia los costos del modelo.

## Episodios 02–04 — arquitecturas simples

Mismo motor, mismas primitivas, un modelo de simulación nuevo por episodio (detalle en [docs/13](docs/13-architecture-episodes.md)):

| Episodio | Comando | Resultado medido (semilla 42) |
| :--- | :--- | :--- |
| 02 · Cache-aside | `archengine film ep02 -o out/ep02_cache_aside.mp4` | 79 % de aciertos; hit 0,4 ms vs miss 15,9 ms; sin caché el HDD se satura |
| 03 · Cola de mensajes | `archengine film ep03 -o out/ep03_message_queue.mp4` | DROP pierde 66 mensajes; BLOCK 0 y frena al productor de 16 a 10 msg/s |
| 04 · Load balancer | `archengine film ep04 -o out/ep04_load_balancer.mp4` | p95 806 ms (round robin) vs 253 ms (least conn); caída detectada en 1,5 s |

## Rendimiento (máquina de desarrollo, Windows 11)

| SLA | Objetivo | Medido |
| :--- | :--- | :--- |
| Tiempo por cuadro (film, con post-proceso) | ≤ 0,40 s | p50 ≈ 0,18 s · p95 ≈ 0,21 s (video completo en ≈ 6 min) |
| Preview con trace en caché (1080x1920) | ≤ 0,20 s (p90) | p50 ≈ 0,14 s · máx. ≈ 0,17 s |
| Determinismo | hash idéntico | `trace_hash`, PCM y MP4 idénticos entre ejecuciones (mismo FFmpeg) |

El MP4 de 60 s pesa ≈ 230 MB (CRF 18 conserva el grano analógico); suba el CRF en
`pipeline/ffmpeg_sink.py` si necesita un archivo más liviano para publicar.

Las trazas de simulación se cachean en `<tmp>/archengine-cache` (clave = hash de entradas + semilla).

## Estructura

| Ruta | Contenido |
| :--- | :--- |
| `src/archengine/core` | timebase (+ `TimeMap`), rng, schema, manifest |
| `src/archengine/simulation` | motor de eventos, trace, workload, storage (disk, WAL, LSM, B-Tree), cache, messaging, balancing |
| `src/archengine/geometry` | primitivas y layout Manhattan |
| `src/archengine/render` | Skia, tema, postproceso |
| `src/archengine/audio` | sonificación procedural (NumPy) y `SOUND_MAP` |
| `src/archengine/pipeline` | preview, film, sink FFmpeg |
| `src/archengine/scenes` | episodios (`ep01`…`ep04`) y helpers de HUD (`hud.py`) |
| `src/archengine/data` | topologías y `protocols.yaml` |
| `tests/` | unit, golden, integration (FFmpeg real), benchmarks |

## Calidad

```powershell
ruff check . ; ruff format --check . ; mypy ; lint-imports ; pytest
```

`lint-imports` verifica las reglas de dependencia entre paquetes (la simulación no conoce el render ni el audio).
Alcance post-MVP (Raft/Paxos, particiones de red) descrito en [docs/](docs/README.md).

## Licencia

Código bajo [Apache-2.0](LICENSE). Las fuentes de ssets/fonts/ (JetBrains Mono, IBM Plex Sans) se distribuyen bajo SIL OFL 1.1; sus textos están junto a los archivos.

