# 06 — Datos, esquemas y persistencia

Cubre FR-01, FR-02, FR-20. ArchEngine **no tiene base de datos**: la "persistencia" son archivos de entrada, una caché opcional y artefactos de salida.

## 1. Inventario de datos

| Dato | Formato | Dónde | Mutable en runtime | Fuente PDR |
| :--- | :--- | :--- | :---: | :--- |
| Topologías | YAML | `data/topologies/*.yaml` | No | §3 |
| Parámetros de protocolo | YAML | `data/protocols.yaml` | No | §3 |
| Guion de escena | YAML + Python (ADR-0006) | `scenes/` | No | §3 |
| Trace | NumPy columnar en RAM; opcional `.npz` | caché (`~/.cache/archengine` / `--cache-dir`) | Se regenera | `[DERIVED]` |
| Preview | PNG | salida | — | §4.5 |
| Video | MP4 | salida | — | §4.5 |
| Manifest | JSON | junto al video | — | `[DERIVED]` |

Validación: todos los YAML se cargan con `yaml.safe_load` y se validan contra modelos tipados (propuesta: `dataclasses` + validador propio, o `pydantic` si se acepta la dependencia — decisión menor, NFR-07 favorece no añadir dependencias). Cada archivo declara `schema_version: 1`.

## 2. Topología (`data/topologies/<name>.yaml`) — FR-01

Campos exigidos por el PDR: **nodos, redes y capacidades de buffer**. El resto es `[DERIVED]`.

```yaml
schema_version: 1
name: lsm_vs_btree
nodes:
  - id: db_lsm                # único, [a-z0-9_]+
    kind: storage_node        # server_rack | storage_node | queue | client_pool
    pos: [0, 0]               # celda de rejilla (layout manual)
    engine: lsm               # lsm | btree | none
    capacities:               # "capacidades de buffer"
      memtable_bytes: 67108864
      wal_bytes: 268435456
  - id: db_btree
    kind: storage_node
    pos: [6, 0]
    engine: btree
    capacities: { buffer_pool_pages: 1024 }
networks:                      # vacío en Ep. 01
  - id: lan0
    edges:
      - { from: client, to: db_lsm, latency_us: 200, jitter_us: 50, loss: 0.0 }
```

Reglas de validación: IDs únicos; aristas referencian nodos existentes; capacidades > 0; `pos` sin colisiones; `loss ∈ [0,1]`.

## 3. `protocols.yaml` — FR-02

El PDR define su contenido como "timeouts, TTL, tamaños de frame". Esquema:

```yaml
schema_version: 1
protocols:
  raft:
    election_timeout_ms: [150, 300]     # PDR §4.3
    heartbeat_interval_ms: 50           # [DERIVED] OQ-12
  transport:
    ttl_hops: 16                        # TTL
    frame_bytes: 1500                   # tamaño de frame
    timeout_ms: 1000
engines:                                # FR-05, PDR §4.3 (OQ-11 resuelta)
  lsm:
    memtable_bytes: 67108864           # 64 MB
    sstable_bytes: 67108864            # 64 MB
    l0_compaction_trigger: 4           # 4 SSTables en L0 disparan compactación L0->L1
    wal_sync: batch                    # Group commit periódico (10 ms)
    source: "RocksDB write_buffer_size default (64MB); Cassandra commitlog_sync: periodic; Petrov 'Database Internals' Cap. 7"
  btree:
    page_bytes: 4096                   # 4 KB
    fanout: 256                        # 256 claves por nodo interior
    buffer_pool_pages: 1024            # 4 MB en RAM para inducir desalojo y seeks aleatorios
    source: "PostgreSQL/LMDB default leaf page size (4KB); Petrov 'Database Internals' Cap. 2-3"
  disk:
    tracks: 2000
    rpm: 7200                          # 7200 RPM -> revolución = 8.33 ms
    rotational_us: 4166                # Latencia rotacional promedio (1/2 vuelta)
    seek_avg_us: 8500                  # Seek promedio 8.5 ms
    seek_track_to_track_us: 800        # Seek adyacente 0.8 ms
    transfer_us_per_page: 27           # 150 MB/s secuencial (~27.3 µs por página de 4KB)
    source: "Seagate Enterprise HDD 7200 RPM Datasheets & Architecture Specs"
```

Los parámetros están respaldados por las fuentes bibliográficas y especificaciones técnicas arriba citadas (resolviendo C-06 y OQ-11). La precedencia de resolución es: escena > topología > `protocols.yaml` > defaults del código (los defaults viven en `core/schema.py` y se auditan con `archengine validate --show-effective`).

## 4. Escena (FR-20) — modelo lógico

Independiente de si se escribe en YAML o Python ([ADR-0006](adr/0006-scene-authoring-format.md)):

```yaml
schema_version: 1
id: ep01
video: { width: 1080, height: 1920, fps: 30, duration_s: 60.0 }   # PDR §5
seed: 42
topology: lsm_vs_btree
camera:
  - { t: 0.0,  azimuth: 45, elevation: 35.264, scale: 1.0, target: [3, 0, 0] }
segments:
  - { id: intro,      t: [0, 5],   title: "…" }
  - { id: btree,      t: [5, 15] }
  - { id: lsm,        t: [15, 30] }
  - { id: flush,      t: [30, 45] }
  - { id: crash,      t: [45, 55] }
  - { id: conclusion, t: [55, 60] }
actions:                       # entradas a la simulación
  - { t: 0.0,  do: workload, target: [db_lsm, db_btree], writes: 100000, arrival: poisson, clients: 64 }
  - { t: 45.0, do: power_loss, target: db_lsm }
overlays: [ … ]                # textos/HUD
```

`t` en **segundos de video**; se convierte a µs por `core.timebase`. Mapeo a tiempo de simulación: `time_scale` por segmento ([ADR-0002](adr/0002-time-model.md)).

Validaciones: segmentos contiguos, cubren `[0, duration_s]` sin solapes; `duration_s × fps` entero; acciones dentro de rango; `seed` entero.

## 5. Formato de trace (en RAM; `.npz` opcional)

| Columna | Tipo | Significado |
| :--- | :--- | :--- |
| `t_us` | int64 | Instante virtual |
| `seq` | int64 | Desempate |
| `comp` | int32 | Índice en tabla de componentes |
| `kind` | int16 | Índice en tabla de tipos de evento |
| `a`, `b` | int64 | Argumentos numéricos (bytes, track, ID de paquete…) |

Más: tabla `components` (IDs), tabla `kinds`, lista de snapshots `(t_us, payload)`, cabecera con `engine_version` y `inputs_hash`. La caché se invalida si cambia cualquiera.

## 6. Invariantes de datos

- Mismo `inputs_hash` + misma `engine_version` ⇒ misma trace (byte a byte).
- Las entradas son de sólo lectura; el motor nunca escribe en `data/`.
- Sin secretos ni PII en los datos (no aplican al producto).
