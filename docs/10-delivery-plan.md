# 10 — Plan de entrega

Fuente: Roadmap consolidado en [`PDR.md`](../PDR.md) §7 (octubre 2026). Integra todos los componentes del MVP: B-Tree, modelo de disco rotacional, WAL/crash recovery, CLI unificado, pipeline de CI y benchmarks de rendimiento.

## 1. Cronograma consolidado de fases

```mermaid
gantt
    title Roadmap Consolidado de Entrega - ArchEngine
    dateFormat  YYYY-MM-DD
    axisFormat  %b %d

    section Fase 1 - Core, Render y CLI Básico
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

Duración total estimada: **54 días** (≈ 1 de octubre a 23 de noviembre de 2026).

---

## 2. Integración de brechas previamente identificadas

Todas las brechas del roadmap preliminar han sido incorporadas y asignadas a fases concretas:

| Componente / Brecha | Requisitos | Fase asignada | Estado |
| :--- | :--- | :---: | :--- |
| **B-Tree y Buffer Pool** | FR-05, FR-21 | Fase 2 (`f2_4`) | **Integrado**: páginas de 4 KB, fanout 256, desalojo aleatorio. |
| **Modelo de disco físico (`DiskModel`)** | FR-05, FR-21 | Fase 2 (`f2_2`) | **Integrado**: simulación analítica de seek, rotación 7200 RPM y transfer. |
| **WAL y recuperación de Crash (`PowerLoss`)** | FR-05, FR-07 | Fase 2 (`f2_5`) | **Integrado**: append secuencial, pérdida volátil y replay de WAL. |
| **CLI básico (`preview`, `validate`, `doctor`)** | FR-18, FR-22 | Fase 1 (`f1_3`) | **Integrado**: render de cuadro clave en $\le 200\text{ ms}$ (p90) / $\le 250\text{ ms}$ (p95). |
| **Pipeline `film` y entrega FFmpeg** | FR-19, NFR-06 | Fase 3 (`f3_2`) | **Integrado**: streaming `rgb24` por pipe + audio WAV temporal en `/tmp`. |
| **CI (GitHub Actions) y linters** | FR-22, NFR-07 | Fase 1 (`f1_1`) | **Integrado**: runner `ubuntu-latest` como hardware de referencia. |
| **Gates de SLA y benchmarks** | NFR-01…04 | Fases 1, 2 y 3 | **Integrado**: benchmark continuo de p95 frame time y RSS de memoria. |
| **Layout Manhattan y `MemoryBlock`** | FR-13, FR-14 | Fase 1 (`f1_3`) | **Integrado**: ruteo ortogonal y bloque verde de MemTable. |

---

## 3. Hitos y criterios de salida verificables

| Hito | Alcance | Criterio de salida verificable |
| :--- | :--- | :--- |
| **M0 — Fundaciones** (Día 4) | Estructura de repo, `pyproject.toml`, CI en GitHub Actions, `core/` (`timebase`, `rng`, `schema`, `manifest`), import-linter. | CI en verde; `archengine doctor` verifica entorno y dependencias. |
| **M1 — Render Core** (Día 9) | `render/core`, `theme`, cámara `orbit_cam`, back-face culling analítico, ordenamiento por capas `LAYER`, decals proyectivos, fuente JetBrains Mono. | Cuadro estático de prueba reproducible; p95 de render en hardware de referencia $\le 0,35\text{ s}$. |
| **M2 — Primitivas y Preview** (Día 14) | Primitivas (`ServerRack`, `CircularQueue`, `StorageCylinder`, `NetworkPipes`, `MemoryBlock`), layout Manhattan, postproceso, comando `preview`. | Golden test de imagen de escena multi-nodo; latencia de preview con trace en caché $\le 200\text{ ms}$ (p90) / $\le 250\text{ ms}$ (p95). |
| **M3 — Motor de eventos y Trace** (Día 19) | `simulation/engine`, `simulation/trace`, reloj virtual en µs, colas de eventos, snapshotting y función `state_at(t)`. | Trace determinista columnar con tests de invariantes 1, 2, 3 de [09](09-testing-and-quality.md); `state_at(t)` en $< 20\text{ ms}$. |
| **M4 — Motores de almacenamiento** (Día 33) | `DiskModel`, `LSMTree` (MemTable, flush, SSTables, compactación), `BTree` (páginas, buffer pool), `WAL` y replay de crash. | Invariantes de persistencia (test de crash/recovery sin pérdida); amplificación de escritura comprobada numéricamente. |
| **M5 — Audio determinista** (Día 38) | `audio/sonification`, `SoundMap`, síntesis aditiva/sustractiva a 48 kHz estéreo. | PCM idéntico byte a byte; sincronización frame a evento con desviación $\le \pm 1$ muestra. |
| **M6 — Episodio 01 y Film** (Día 47) | Pipeline `film` con subproceso FFmpeg, streaming `rgb24` y audio WAV temporal, guion completo de los 6 segmentos. | Generación de video de 60 s (1.800 cuadros) en $\le 720\text{ s}$ en runner de referencia; hash SHA-256 verificado en manifest. |
| **M7 — Release** (Día 54) | Wheel y sdist, publicación PyPI (Trusted Publishing), contenedor Dockerfile oficial, suite completa de pruebas. | Instalación limpia `pip install archengine` en contenedor aislado y ejecución exitosa de `archengine film ep01`. |

---

## 4. Definición de "Listo para Empezar" (Definition of Ready)

### Fase 1: **LISTA PARA EJECUCIÓN (DESBLOQUEADA)**
Todos los bloqueantes previos han sido formalmente resueltos:
- **OQ-01 (Hardware de referencia)**: Resuelto (GitHub Actions 4 vCPU x86_64 @ 2.8+ GHz).
- **OQ-04 (Formato de escena)**: Resuelto (Híbrido YAML + Python según ADR-0006).
- **OQ-08 (Código base heredado)**: Resuelto (Reimplementación matemática limpia de `orbit_cam` y `packets_on`).
- **OQ-09 (Tiempo de simulación y tick virtual)**: Resuelto (Tick = 1 µs entero; `time_scale` narrativo).
- **OQ-11 (Parámetros y fuentes de almacenamiento)**: Resuelto (Documentados con fuentes canónicas en `protocols.yaml`).
- **OQ-14 / OQ-15 / OQ-20 / OQ-22**: Resueltos provisionalmente según arquitectura base (español, proyección ortográfica, baseline monoproceso, soporte Linux/Windows).

---

## 5. Estado de entrega

| Hito | Estado | Evidencia |
| :--- | :---: | :--- |
| M0–M2 (Fase 1) | Completo | `tests/unit`, `tests/golden`, `tests/benchmarks` |
| M3 Motor de eventos y trace | Completo | `simulation/engine.py`, `simulation/trace.py` (`state_at`, hash, `.npz`) |
| M4 Motores de almacenamiento | Completo | `simulation/storage/*`; invariante de recovery en `tests/unit/test_simulation.py` |
| M5 Audio determinista | Completo | `audio/sonification.py`; `tests/unit/test_audio.py` (duración exacta, alineación ±1 muestra, sin aliasing) |
| M6 Episodio 01 y film | Completo | `pipeline/film.py`, `scenes/ep01_lsm_vs_btree.py`; `tests/unit/test_episode.py`, `tests/integration/test_film.py` |
| M7 Release | Preparado | `release.yml` (Trusted Publishing), `Dockerfile`, wheel verificado con fuentes y YAML incluidos |

Pendiente fuera del repo (requiere acciones del propietario): dar de alta el *trusted publisher* en PyPI,
crear el tag `v0.1.0` y validar el build de Docker en un host con Docker. Post-MVP: Raft/Paxos y particiones
de red (`simulation/consensus`, `simulation/networking`), render concurrente `--jobs N` (ADR-0008).
