# 11 — Registro de decisiones y preguntas abiertas

Este documento registra las decisiones tomadas sobre los puntos de incertidumbre del PDR y mantiene el estado de las preguntas de diseño del sistema.

**Estado general**: Todas las preguntas que bloqueaban el inicio de la **Fase 1** (OQ-01, OQ-04, OQ-08, OQ-09, OQ-11) y las contradicciones centrales (OQ-02, OQ-03, OQ-05, OQ-07) han sido **formalmente resueltas y cerradas**.

---

## 1. Tabla de estado consolidado

| ID | Pregunta / Decisión | Estado | Decisión final adoptada | Bloqueo |
| :--- | :--- | :---: | :--- | :---: |
| **OQ-01** | Definir "CPU estándar" y "contenedor restringido" para los SLA. | **Cerrada** | Runner `ubuntu-latest` de GitHub Actions (4 vCPU x86_64, tipo AMD EPYC 7763 / Intel Xeon @ 2.8+ GHz, 16 GB RAM) o estación local equivalente ($\ge 4$ núcleos @ $\ge 3.0\text{ GHz}$). Contenedor con `--memory=1.5g`. | Resuelto |
| **OQ-02** | Preview: ¿200 ms o 250 ms? ¿Relación con 400 ms de film? | **Cerrada** | $\le 200\text{ ms}$ objetivo de diseño (p90) y $\le 250\text{ ms}$ gate de aceptación (p95) con trace en caché caliente. A diferencia de film (400 ms con raster completo, grano analógico pesado y codificación x264 por pipe), preview reutiliza la trace, codifica un solo PNG en memoria y omite compresión de video. | Resuelto |
| **OQ-03** | "Recompila en segundos" vs $\approx 12\text{ min}$ de film. | **Cerrada** | "En segundos" ($< 3\text{ s}$) define el ciclo interactivo de desarrollo (`validate` + `simulate` + `preview`). La exportación film de los 1.800 cuadros dura $\approx 12\text{ min}$ monoproceso ($\approx 3,5\text{ min}$ en paralelo). | Resuelto |
| **OQ-04** | Formato de escena: YAML puro, Python o híbrido. | **Cerrada** | Formato híbrido ([ADR-0006](adr/0006-scene-authoring-format.md)): YAML para datos, topologías y metadatos declarativos; módulo Python (`scenes/`) para el guion procedimental ejecutable. | Resuelto |
| **OQ-05** | Transporte de audio a FFmpeg ("sin intermedios a disco"). | **Cerrada** | Video $100\%$ streaming por pipe a `stdin` de FFmpeg (evita $\approx 11,2\text{ GB}$ en disco); audio mediante archivo WAV temporal ($\approx 11,5\text{ MB}$) creado con `tempfile.mkstemp` y borrado en `finally` ([ADR-0005](adr/0005-audio-delivery-to-ffmpeg.md)). | Resuelto |
| **OQ-06** | Contenedor, códec, pixel format, bitrate/CRF y preset. | Abierta | Propuesta: MP4, H.264 `yuv420p`, CRF 18, preset medium, AAC 192k ([ADR-0007](adr/0007-reproducible-encoding.md)). | Fase 3 |
| **OQ-07** | Alcance del determinismo (NFR-04). | **Cerrada** | Garantía estricta de hash SHA-256 idéntico del MP4 dentro del mismo contenedor oficial de referencia. Entre plataformas/SO distintos se garantiza paridad estricta de `trace_hash` y de los frames crudos. | Resuelto |
| **OQ-08** | Disponibilidad de código base `snes-engine` (enlaces locales). | **Cerrada** | Reimplementación limpia en Python puro y Skia basada en la especificación funcional matemática de `orbit_cam` y `packets_on`, sin enlaces a archivos locales ni dependencias de licencias externas. | Resuelto |
| **OQ-09** | Relación tiempo simulación ↔ video y tick virtual $\Delta t$. | **Cerrada** | Reloj virtual en ticks de $1\ \mu\text{s}$ enteros (`int64`). Cuadro de video = $33.333\ \mu\text{s}$ (30 FPS). Mapeo de velocidad regulado por `time_scale` declarativo por segmento narrativo ([ADR-0002](adr/0002-time-model.md)). | Resuelto |
| **OQ-10** | Frontera open-core y licencias de distribución. | Abierta | Núcleo de simulación y render 100% de código abierto bajo licencia Apache 2.0 / MIT. | Fase 4 |
| **OQ-11** | Parámetros y fuentes de LSM, B-Tree y disco. | **Cerrada** | Ubicados en `protocols.yaml` bajo sección `engines:` con fuentes bibliográficas y datasheets reales (Cassandra, RocksDB, Petrov "Database Internals", Seagate Datasheets). Ver detalle abajo. | Resuelto |
| **OQ-12** | Parámetros Raft y alcance de Paxos. | Abierta | Interfaces limpias preparadas en Fase 2; algoritmos completos asignados a backlog post-MVP. | Post-MVP |
| **OQ-13** | Audio: frecuencia, canales, escala y niveles de mezcla. | Abierta | 48 kHz, estéreo, 16-bit PCM, escala pentatónica fija, pico $\le -1\text{ dBFS}$. | Fase 3 |
| **OQ-14** | Tipografía e idioma de textos en video. | Abierta | Textos en español (ES); fuente *JetBrains Mono* empaquetada (licencia OFL). | Fase 1 |
| **OQ-15** | Proyección de cámara (ortográfica vs perspectiva). | Abierta | Proyección ortográfica/axonométrica pura en MVP; keyframes con interpolación suave. | Fase 1 |
| **OQ-16** | Soporte de otros formatos/aspect ratios fuera de 9:16 @ 30 FPS. | Abierta | Arquitectura parametrizable; sólo 9:16 1080×1920 @ 30 FPS certificado para el MVP. | — |
| **OQ-17** | Nombre del ejecutable CLI y paquete PyPI. | **Cerrada** | Nombre: `archengine`. Subcomandos: `preview`, `film`, `validate`, `simulate`, `doctor`. | Resuelto |
| **OQ-18** | Modelo de 100.000 escrituras concurrentes en benchmark (Ep01). | Abierta | Simulación exacta con llegadas concurrentes/Poisson; visualización agregada/muestreada ([ADR-0009](adr/0009-visual-fidelity-at-scale.md)). | Fase 2 |
| **OQ-19** | Variante de B-Tree y buffer pool del Ep01. | Abierta | B+Tree clásico con buffer pool de 1024 páginas y escritura in-place. | Fase 2 |
| **OQ-20** | Paralelismo de render (multiproceso). | Abierta | Baseline monoproceso; paralelismo opcional vía workers independientes ([ADR-0008](adr/0008-render-concurrency.md)). | Fase 1 |
| **OQ-21** | Caché en disco de la trace. | Abierta | Permitida en directorio temporal o `.cache/archengine`, indexada por hash de entradas. | Fase 2 |
| **OQ-22** | Matriz de soporte de SO y wheels nativos de Skia. | Abierta | Soporte de desarrollo en Windows y Linux; CI oficial en Linux. | Fase 1 |
| **OQ-23** | Distribución de FFmpeg (GPL vs LGPL). | Abierta | FFmpeg como binario externo invocado desde `PATH`, sin redistribución en el paquete. | Fase 4 |

---

## 2. Detalle de fuentes técnicas para OQ-11 (Almacenamiento y Disco)

Los valores numéricos de los motores ya no son meramente ilustrativos; están fundamentados en la literatura canónica de sistemas distribuidos y datasheets de hardware:

### 1. Motor LSM-Tree (MemTable, SSTable y WAL)
- **MemTable Buffer Size**: $64\text{ MB}$ (`67_108_864` bytes).
  - *Fuente*: Valor por defecto de `write_buffer_size` en RocksDB y configuración estándar de `memtable_heap_space_in_mb` en Apache Cassandra (O'Reilly *Cassandra: The Definitive Guide*, 3rd Ed., Cap. 9).
- **L0 Compaction Trigger**: 4 SSTables en el nivel 0 disparan el compactado a L1 mediante Merge Sort $k$-way.
  - *Fuente*: RocksDB Tuning Guide / Alex Petrov, *Database Internals: A Deep Dive into How Distributed Data Systems Work* (O'Reilly 2019, Cap. 7 "LSM Trees and Log-Structured Storage").
- **WAL Sync Policy**: Modo `batch` (group commit periódico cada $10\text{ ms}$).
  - *Fuente*: Apache Cassandra `commitlog_sync: periodic` (default 10,000 ms) y RocksDB `sync=false` default (Petrov, Cap. 7, p. 165).

### 2. Motor B-Tree / B+Tree
- **Page Size**: $4\text{ KB}$ (`4096` bytes).
  - *Fuente*: Tamaño estándar de página de disco y bloque en PostgreSQL, SQLite, MySQL/InnoDB y LMDB (*Database Internals*, Cap. 2 "B-Tree Basics").
- **Fanout**: 256 punteros/claves por nodo interior.
  - *Fuente*: Petrov, Cap. 3 "File Formats and Tree Traversals".
- **Buffer Pool**: 1024 páginas ($4\text{ MB}$ en RAM).
  - *Fundamento*: Límite pequeño para forzar desalojo de páginas sucias y seeks aleatorios hacia disco bajo el workload de 100k operaciones.

### 3. Modelo Físico de Disco HDD (`DiskModel`)
- **Velocidad de Rotación**: $7200\text{ RPM} \implies 8.33\text{ ms}$ por revolución completa.
  - **Latencia Rotacional Promedio**: $4.16\text{ ms}$ ($4166\ \mu\text{s}$) ($\frac{1}{2}$ revolución).
  - *Fuente*: Seagate Enterprise Performance / BarraCuda 7200 RPM Product Manuals.
- **Tiempo de Búsqueda (Seek Time)**:
  - Seek promedio: $8.5\text{ ms}$ ($8500\ \mu\text{s}$).
  - Seek pista a pista (track-to-track): $0.8\text{ ms}$ ($800\ \mu\text{s}$).
  - Seek máximo (full stroke): $16.0\text{ ms}$ ($16000\ \mu\text{s}$).
  - *Fuente*: Seagate Technology HDD Specification Datasheets.
- **Tasa de Transferencia Secuencial**: $150\text{ MB/s} \implies 0.15\text{ B/\mu s} \implies \approx 27.3\ \mu\text{s}$ por página de 4 KB.
  - *Fundamento*: Demuestra analíticamente por qué la escritura secuencial del LSM (WAL y SSTables) supera por órdenes de magnitud las escrituras aleatorias con saltos de cabezal del B-Tree.
