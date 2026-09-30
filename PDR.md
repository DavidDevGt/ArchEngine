# Product Definition & Design Review (PDR)

| Metadato | Detalle |
| :--- | :--- |
| **Proyecto** | **ArchEngine** (*Architecture-as-Code Explainer*) |
| **Tipo de Documento** | Definición de Producto y Revisión de Diseño Preliminar |
| **Ecosistema Base** | Python 3.11+, Google Skia (`skia-python`), NumPy, FFmpeg |
| **Estado** | `Versión Consolidada / Revisión de Ingeniería Aprobada` |
| **Última Actualización** | Octubre 2026 |

---

## 1. Resumen Ejecutivo y Visión

**ArchEngine** es un motor de renderizado y simulación de código abierto (*open-core*), determinista y ultraligero, diseñado para **generar explicaciones visuales cinemáticas de arquitectura de software y sistemas distribuidos**.

A diferencia de las herramientas convencionales de animación de video o diagramación estática, ArchEngine trata la arquitectura de software como un modelo matemático ejecutable: **el estado visual es un subproducto directo de la simulación del protocolo**.

### Principios Arquitectónicos Consolidados
- **Renderizado vectorial y 2.5D/3D sin dependencia de GPU**: Empleo de Google Skia (`skia-python`) con cálculos analíticos de proyección axonométrica/ortogonal y ordenamiento por capas (`LAYER`).
- **Simulación algorítmica real**: Modelado formal de máquinas de estado finito (FSM), colas de prioridad con reloj virtual en microsegundos enteros ($\mu\text{s}$), buffers circulares y eventos asíncronos.
- **Sonificación procedural de datos**: Generación de audio determinista mediante síntesis de arrays con NumPy a 48 kHz estéreo, acoplada frame a frame a los eventos de red y persistencia.
- **Pipeline de streaming híbrido hacia FFmpeg**: Tiempo de cuadro objetivo $\le 0.40\text{ s}$ en CPU estándar de referencia. El video se transmite $100\%$ sin comprimir (`rgb24`) vía pipe a `stdin` de FFmpeg (ahorrando $\approx 11.2\text{ GB}$ de disco); el audio se entrega mediante un archivo WAV temporal mínimo ($\approx 11.5\text{ MB}$) en el directorio temporal del sistema que se elimina de forma atómica en `finally`.

---

## 2. El Problema y la Oportunidad

| Solución Actual | Limitaciones Críticas | Enfoque ArchEngine |
| :--- | :--- | :--- |
| **Diagramas Estáticos**<br>*(Draw.io, Excalidraw, PlantUML)* | Inertes. No reflejan concurrencia, saturación de buffers, latencia variable, caídas parciales ni particiones de red. | **Simulaciones Vivas**: Los paquetes fluyen con jitter, las colas muestran desbordes físicos y los nodos fallan en tiempo de ejecución. |
| **Animación Manual**<br>*(After Effects, Manim, Premiere)* | Tiempos de producción elevados (semanas por video), mantenimiento costoso y propensión a imprecisiones técnicas. | **Architecture-as-Code**: Definición declarativa en YAML/Python. Cualquier ajuste en la topología valida y previsualiza cuadros en segundos ($< 3\text{ s}$); la exportación completa de video toma $\approx 12\text{ min}$ en CPU monoproceso ($\approx 3.5\text{ min}$ en paralelo). |
| **Motores 3D Pesados**<br>*(Blender, Unreal, Unity)* | Requieren hardware GPU dedicado, gigabytes de dependencias y flujos de trabajo desacoplados del código fuente. | **Motor Headless de CPU**: Ejecución limpia en scripts locales, pipelines de CI/CD (GitHub Actions) y contenedores Docker mínimos. |

---

## 3. Arquitectura del Sistema

La estructura modular del proyecto organiza la separación estricta entre simulación determinista, geometría abstracta, proyección visual y sonificación:

```text
archengine/
├── data/                         # Fuentes de verdad: protocolos y topologías
│   ├── topologies/               # Definición YAML: Nodos, redes y capacidades de buffer
│   └── protocols.yaml            # Parámetros operativos y motores: timeouts, TTL, LSM, B-Tree, disco
├── core/                         # Infraestructura fundamental independiente
│   ├── timebase.py               # Conversión exacta cuadro <-> microsegundos (aritmética entera)
│   ├── rng.py                    # Substreams pseudoaleatorios deterministas (PCG64)
│   ├── schema.py                 # Validación estricta de esquemas YAML (schema_version: 1)
│   └── manifest.py               # Generación de manifests con hashes (SHA-256) y telemetría
├── simulation/                   # Simulación determinista de sistemas
│   ├── engine.py                 # Ciclo de eventos discreto (Virtual Clock & Ticks regulados)
│   ├── trace.py                  # Log columnar NumPy + snapshots + cálculo de state_at(t)
│   ├── storage/                  # Motores de persistencia: LSM-Tree, WAL, B-Tree, DiskModel
│   ├── networking/               # Canales de red: latencia, jitter, pérdida y particiones
│   └── consensus/                # Máquinas de estado de consenso (Raft, Paxos - post-MVP)
├── geometry/                     # Primitivas geométricas volumétricas
│   ├── primitives.py             # ServerRack, CircularQueue, StorageCylinder, NetworkPipes, MemoryBlock
│   └── topology_layout.py        # Enrutamiento ortogonal estilo Manhattan para buses
├── render/                       # Pipeline de rasterizado y proyección
│   ├── core.py                   # Canvas Skia, cámara orbital paramétrica, cálculo de proyección y decals
│   ├── theme.py                  # Sistema semántico de colores e iluminación sintética (Lambert)
│   └── postprocess.py            # Filtros de lente: viñeta matricial y grano analógico determinista
├── audio/                        # Motor de síntesis y sonificación
│   └── sonification.py           # Drones armónicos, sintetizador de impulsos, eventos IOPS y SoundMap
├── pipeline/                     # Orquestación de salida
│   ├── preview.py                # Modo preview a PNG en memoria
│   ├── film.py                   # Modo film con streaming a FFmpeg
│   └── ffmpeg_sink.py            # Gestión del subproceso FFmpeg y entrega de audio WAV temporal
├── cli.py                        # CLI unificado (preview, film, validate, simulate, doctor)
└── scenes/                       # Scripts narrativos declarativos (Episodios ejecutables)
    ├── common.py                 # Helpers de escena (packets_on, animadores de cámara)
    └── ep01_lsm_vs_btree.py      # Episodio 01 completo (LSM vs B-Tree)
```

---

## 4. Especificación Técnica de los Componentes

### 4.1. Motor de Renderizado (`render/core.py`)

1. **Paleta Semántica del Sistema (`THEME`)**:
   - `bg`: `#080a0f` — Fondo industrial oscuro de alto contraste.
   - `node_idle`: `#1c2333` — Nodos y servidores en estado nominal/reposo.
   - `bus`: `#3b82f6` — Buses de comunicación y líneas de transporte.
   - `mem`: `#10b981` — Caché volátil y estructuras en memoria (MemTable/RAM).
   - `disk`: `#6366f1` — Bloques de almacenamiento persistente (SSTables/WAL).
   - `alert`: `#ef4444` — Timeouts, errores HTTP 5xx y caídas de nodos.

2. **Proyección y Cámara Paramétrica**:
   - Algoritmo `orbit_cam(azimuth, elevation, scale, target)`: transformaciones matriciales `World -> View -> Projection` para vistas isométricas (azimuth 45°, elevation 35.264°) y cenitales de precisión técnica.
   - **Back-face culling** analítico y ordenamiento por capas (`LAYER`), suprimiendo el costo de sincronización de un Z-buffer tradicional.

3. **Decals Proyectivos de Telemetría**:
   - Uso de `Skia.Matrix.setPolyToPoly` para mapear métricas dinámicas directamente sobre las caras de las carcasas 2.5D:
     - Métricas en tiempo real: `% CPU`, `IOPS`, `QPS`.
     - Logs de eventos y consolas con fuentes monospace (*JetBrains Mono* empaquetada).

### 4.2. Primitivas Geométricas Procedurales (`geometry/`)

Modelado técnico de hardware e infraestructura mediante primitivas vectoriales:
- **`ServerRack`**: Módulos blade escalables con indicadores LED de actividad y ranuras de bus.
- **`CircularQueue`**: Búfer anular para colas de mensajería (Kafka/RabbitMQ) donde los punteros *head/tail* rotan volumétricamente.
- **`StorageCylinder`**: Bloque cilíndrico de base de datos con sectores y cabezal mecánico de lectura/escritura móvil.
- **`NetworkPipes`**: Segmentos ortogonales de red que canalizan paquetes físicos mediante el helper `packets_on(channel, t)`, interpolando su posición geométrica a lo largo de rutas Manhattan.
- **`MemoryBlock`**: Bloque de celdas de memoria volátil para representación de MemTable y búferes de RAM.

### 4.3. Motor de Simulación Algorítmica (`simulation/`)

> [!IMPORTANT]
> El estado visual no se anima de manera fija: **es el reflejo directo de las transiciones de estado de los algoritmos**.

- **Virtual Clock Engine**: El tiempo avanza mediante ticks discretos en microsegundos enteros ($\Delta t = 1\ \mu\text{s}$), garantizando paridad exacta de cuadros.
- **Parámetros de Motores de Persistencia**:
  - **LSM-Tree / Cassandra / RocksDB**: MemTable de 64 MB (`67_108_864` B), compactación L0 $\to$ L1 con disparador de 4 SSTables (Fuente: O'Reilly *Database Internals* Cap. 7; RocksDB default `write_buffer_size`). Política WAL `batch` con sincronización periódica (Fuente: Cassandra `commitlog_sync: periodic`).
  - **B-Tree / B+Tree**: Páginas de 4 KB (`4096` B), fanout 256, buffer pool limitado a 1024 páginas (Fuente: PostgreSQL / LMDB default leaf page size; *Database Internals* Cap. 2-3).
  - **DiskModel (HDD)**: Disco de 7200 RPM, tiempo de rotación promedio $4.16\text{ ms}$, seek promedio $8.5\text{ ms}$ ($8500\ \mu\text{s}$), tasa de transferencia secuencial $150\text{ MB/s}$ ($\approx 27\ \mu\text{s}$ por página de 4KB) (Fuente: Especificaciones Seagate Enterprise HDD).
- **Consenso Raft (post-MVP)**:
  - Temporizador de elección estocástico determinista: $T_{\text{election}} \in [150, 300]\text{ ms}$.
  - Transiciones reales de estado `Follower -> Candidate -> Leader` registradas en la trace.

### 4.4. Sonificación de Arquitectura (`audio/`)

Arquitectura de síntesis aditiva y sustractiva basada en arrays de NumPy a 48 kHz estéreo:
- **Zumbido de Clúster (*Cluster Drone*)**: Acorde polifónico resultante de la suma de osciladores senoidales de cada nodo activo.
- **Pulsos de Transporte**: Disparos de ondas cuadradas e impulsos con decaimiento exponencial al momento exacto en que un paquete cruza una arista.
- **Resonancia de Eventos Críticos**:
  - **Incremento de latencia**: Modulación de frecuencia ascendente (*pitch sweep*).
  - **Fallo / Failover**: Impacto percusivo con envolvente de ataque rápido y filtro de paso bajo.
  - **I/O Wait**: Silencios rítmicos forzados mientras el cabezal del disco ejecuta un seek mecánico.

### 4.5. Pipeline de Producción y CLI

1. **Modo Preview (`archengine preview <scene> <t_segundos>`)**:
   - Renderiza cuadros clave aislados en búfer de memoria a PNG en $\le 200\text{ ms}$ (objetivo p90) / $\le 250\text{ ms}$ (límite p95 en CI) con caché de trace caliente.
   - A diferencia del modo film (400 ms de raster completo + grano analógico + encoding x264 por pipe), el preview se enfoca en encuadre e interactividad, reutiliza la simulación en caché y permite renderizado directo sin compresión de video.
2. **Modo Film (`archengine film <scene> [-o out.mp4]`)**:
   - Emite el flujo continuo de píxeles sin comprimir (`rgb24`) directamente al descriptor de entrada estándar (`stdin`) de FFmpeg a través de un canal IPC (*pipe*), sin guardar frames en disco ($\approx 11.2\text{ GB}$ ahorrados).
   - Entrega el audio sintetizado como archivo WAV PCM temporal ($\approx 11.5\text{ MB}$) mediante `-i audio.wav`, eliminándolo de forma segura al terminar el proceso.
3. **Comandos Auxiliares**:
   - `archengine validate <path>`: Validación estricta de sintaxis y esquemas YAML.
   - `archengine simulate <scene> [--dump trace.npz]`: Ejecución aislada de la simulación para depuración y benchmarking.
   - `archengine doctor`: Verificación de entorno, dependencias nativas, FFmpeg y fuentes.

---

## 5. Caso de Uso MVP: Episodio 01

### *«LSM-Trees vs B-Trees: ¿Por qué Cassandra escribe tan rápido?»*
*Formato: Vertical 9:16 (1080x1920) | Duración: 60.0 segundos | Framerate: 30 FPS = 1.800 cuadros*

| Intervalo | Segmento | Acción Visual en Canvas | Diseño Sonoro / Sonificación |
| :---: | :--- | :--- | :--- |
| **00.0s – 05.0s** | **Intro & Benchmark** | Consola de carga disparando 100.000 escrituras concurrentes contra ambos sistemas. | Ráfaga de clicks rítmicos acelerando gradualmente. |
| **05.0s – 15.0s** | **B-Tree (Aleatorio)** | El cabezal mecánico del cilindro salta erráticamente buscando bloques en disco. Alta amplificación de escritura. | Tono grave saturado e irregular con silencios forzados por I/O wait. |
| **15.0s – 30.0s** | **LSM-Tree (MemTable)** | La escritura fluye directo a RAM en tiempo $O(1)$. Bloque verde esmeralda (`MemoryBlock`) llenándose en orden secuencial. | Arpegio limpio y constante; zumbido de clúster estable. |
| **30.0s – 45.0s** | **Flush & Compaction** | La MemTable se bloquea y se transfiere a disco como SSTable inmutable. Fusión 3D de capas (*Merge Sort*). | Tono armónico descendente seguido de barrido de filtro resonante. |
| **45.0s – 55.0s** | **Simulación de Crash** | Se simula corte de energía repentino (`PowerLoss`). Demostración de recuperación instantánea reproduciendo el WAL. | Ruido blanco súbito, corte de osciladores y pulso de reinicio limpio. |
| **55.0s – 60.0s** | **Conclusión & Balance** | Cuadro comparativo de balance de ingeniería: velocidad de escritura vs. amplificación de lectura. | Acorde de resolución sostenido en desvanecimiento (*fade out*). |

---

## 6. Métricas Clave de Rendimiento (SLAs) y Hardware de Referencia

### 6.1. Definición del Hardware y Entorno de Referencia
- **CPU estándar de referencia**: Runner `ubuntu-latest` de GitHub Actions (4 vCPU x86_64, tipo AMD EPYC 7763 o Intel Xeon Platinum 8370C @ 2.8+ GHz, 16 GB RAM) o estación de trabajo local moderna ($\ge 4$ núcleos físicos @ $\ge 3.0\text{ GHz}$).
- **Entorno de determinismo**: Contenedor oficial Docker (`python:3.11-slim`) con dependencias congeladas (`skia-python`, `numpy`, `ffmpeg` con flags `+bitexact`, fuente *JetBrains Mono* empaquetada).

### 6.2. Matriz de SLAs

| Dimensión | Métrica Objetivo | Justificación Técnica |
| :--- | :---: | :--- |
| **Velocidad de Renderizado** | $\le 0.40\text{ s / cuadro}$ | Exportación del video completo de 60 s (1.800 cuadros) en $\approx 12$ min en CPU monoproceso ($\approx 3.5$ min con render concurrente) en hardware de referencia. |
| **Latencia de Vista Previa** | $\le 200\text{ ms}$ (p90) / $\le 250\text{ ms}$ (p95) | Permite calibración interactiva ágil en desarrollo con trace en caché caliente. |
| **Huella de Memoria (RAM)** | $\le 1.5\text{ GB}$ pico | Ejecución sin contención en contenedores Docker y runners de GitHub Actions (verificado con `--memory=1.5g`). |
| **Determinismo de Salida** | $100\%$ reproducible | Idéntico hash SHA-256 en archivos finales (`.mp4`) generados bajo el mismo entorno y semilla. Entre plataformas distintas se garantiza paridad estricta de `trace_hash` y de frames crudos. |

---

## 7. Plan de Lanzamiento y Fases de Desarrollo

El plan de trabajo integra todas las dependencias del MVP (B-Tree, DiskModel, WAL/Crash, CLI, CI y Benchmarks):

```mermaid
gantt
    title Roadmap de Desarrollo Consolidado - ArchEngine
    dateFormat  YYYY-MM-DD
    axisFormat  %b %d

    section Fase 1 - Core, Render y CLI
    Fundaciones: timebase, rng, schema, manifest, CI      :f1_1, 2026-10-01, 4d
    Render core: cámara, culling, capas, decals, tema      :f1_2, after f1_1, 5d
    Primitivas, layout Manhattan, MemoryBlock, preview CLI :f1_3, after f1_2, 5d

    section Fase 2 - Simulación y Almacenamiento
    Motor de eventos, reloj virtual y trace columnar       :f2_1, after f1_3, 5d
    Modelo de disco físico (seek, rotación, latencia)      :f2_2, after f2_1, 3d
    Simulador LSM-Tree (MemTable, flush, SSTables, compact):f2_3, after f2_2, 4d
    Simulador B-Tree (páginas 4KB, buffer pool, seek)      :f2_4, after f2_3, 4d
    Persistencia WAL, simulación de crash y replay         :f2_5, after f2_4, 3d

    section Fase 3 - Audio, Pipeline Film y MVP Ep01
    Sonificación procedural con NumPy y SoundMap           :f3_1, after f2_5, 5d
    Pipeline film: streaming FFmpeg + WAV temporal + manifest:f3_2, after f3_1, 4d
    Producción y verificación integral del Episodio 01     :f3_3, after f3_2, 5d

    section Fase 4 - Calidad y Distribución
    Empaquetado pyproject.toml y publicación PyPI          :f4_1, after f3_3, 4d
    Dockerfile oficial, documentación final y release      :f4_2, after f4_1, 3d
```

### Detalle de Fases:
- **Fase 1 (Días 1–14)**: Infraestructura `core/`, render vectorial Skia, primitivas completas incluyendo `MemoryBlock`, CLI inicial (`validate`, `doctor`, `preview`), configuración de CI y benchmarks preliminares.
- **Fase 2 (Días 15–33)**: Simulación completa de almacenamiento para el Episodio 01: `simulation/engine`, `DiskModel`, LSM-Tree, B-Tree, WAL y fallos de energía (`PowerLoss`), generador de workload de 100.000 escrituras y tests de invariantes.
- **Fase 3 (Días 34–47)**: Motor de sonificación, pipeline `film` con streaming `rgb24` y entrega de audio por WAV temporal, orquestación del guion del Episodio 01 y validación de SLAs (≤ 0.40s/frame, ≤ 1.5GB RAM, determinismo de hash).
- **Fase 4 (Días 48–54)**: Publicación en PyPI con Trusted Publishing, contenedor Docker de referencia y cierre de documentación pública.

---

> [!TIP]
> Para ejecutar la suite de pruebas o comprobar escenas en desarrollo, ejecute `archengine doctor` y los comandos de prueba en el entorno de desarrollo una vez completada la **Fase 1**.
