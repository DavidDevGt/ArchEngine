# 13 — Episodios 02–04: arquitecturas simples

> Tres episodios de 60,0 s (9:16, 1080×1920, 30 FPS = 1.800 cuadros) construidos con las mismas primitivas del MVP y el mismo pipeline que el Ep. 01. Cada uno añade **un modelo de simulación** en `simulation/`, **una escena** en `scenes/` y reutiliza el HUD común de `scenes/hud.py`. Selección y orden: cache-aside → cola de mensajes → load balancer (los que no piden geometría nueva).

| Ep. | Escena (`archengine film …`) | Modelo | Primitivas |
| :-: | :--- | :--- | :--- |
| 02 | `ep02` · `scenes/ep02_cache_aside.py` | `simulation/cache/cache_aside.py` | `ServerRack`, `MemoryBlock`, `StorageCylinder`, `NetworkPipes` |
| 03 | `ep03` · `scenes/ep03_message_queue.py` | `simulation/messaging/queue.py` | `ServerRack`, `CircularQueue`, `NetworkPipes` |
| 04 | `ep04` · `scenes/ep04_load_balancer.py` | `simulation/balancing/lb.py` | `ServerRack`, `NetworkPipes` |

Principio común (ADR-0001/0002): el guion solo decide **cuándo se mira** cada tramo (`TimeMap`) y programa eventos de escenario (flush, cambio de política, caída de nodo); el estado visual y el audio emergen de la trace. `Workload` ganó un parámetro `kind` (evento que emite) y `zipf_keys` genera claves con popularidad Zipf; el Ep. 01 no cambia.

## Ep. 02 — Cache-aside (Redis + base de datos)

`CacheAsideApp`: LRU con TTL delante de un `DiskModel` HDD. Un *miss* lee del disco (seek + rotación + transferencia, serializado por el cabezal) y puebla la caché. Carga: 100 lecturas/s Poisson, 50.000 claves Zipf(1,2), caché de 1.200 entradas, TTL 45 s. Se simula un **segundo mundo sin caché** (`capacity=0`) con la misma carga.

| Seg. | Video | Eventos de simulación | Visual |
| :--- | :---: | :--- | :--- |
| Caché fría | 0–10 s | `cache.miss`, `disk.seek`, `cache.fill` | hits/misses en tuberías distintas; la tasa de aciertos sube desde 0 |
| Caché caliente | 10–24 s | `cache.hit` dominan | `MemoryBlock` llenándose |
| Caché llena | 24–36 s | `cache.evict` (LRU), `cache.expire` (TTL) | contadores de desalojos |
| Flush | 36–50 s | `cache.flush` (sim 80 s) → miss storm | aro de alerta, latencia sube |
| Balance | 50–60 s | — | latencia con/sin caché, hit vs miss |

Medido (semilla 42): tasa de aciertos en régimen 79 %; hit 0,4 ms vs miss 15,9 ms; latencia media con caché 4,1 ms; **sin caché el disco se satura** (100 req/s × ~14 ms de seek > 1 → la cola crece sin límite; 24 s de latencia media en la ventana final).

## Ep. 03 — Cola de mensajes (backpressure)

`Producer` (lazo cerrado con *ack*, Poisson con tasa por tramos) → `BoundedQueue` (16 huecos, políticas `drop`/`block`) → `Consumer` (servicio lognormal, 100 ms medio, factor de lentitud). Con `block` la cola retiene el *ack* y el productor se detiene: el backpressure es emergente, no un contador. El anillo `CircularQueue` usa `head = deq mod 16` y `tail = enq mod 16` reales. Video = simulación en tiempo real.

| Seg. | Video | Escenario programado | Emergente |
| :--- | :---: | :--- | :--- |
| Fluye | 0–8 s | productor 6/s, consumidor 10/s | cola casi vacía |
| Ráfaga + DROP | 8–22 s | productor 16/s | cola llena, 66 mensajes perdidos |
| BLOCK | 22–38 s | `set_policy block` | 0 pérdidas; productor baja a 10 msg/s |
| Consumidor lento | 38–50 s | consumidor ×4 más lento | productor a 2,5 msg/s; espera de cola 6,8 s |
| Balance | 50–60 s | — | pérdidas y espera máxima por política |

Nota de honestidad del modelo: `block` **no acorta** la espera máxima (1,7 s con ambas políticas, cola llena); solo evita perder mensajes.

## Ep. 04 — Load balancer (round robin vs least connections)

`LoadBalancer` + 3 `Backend` FIFO (A y B 40 ms, C 120 ms de servicio medio exponencial), 28 req/s. El balanceador solo conoce la salud por **health checks** (cada 500 ms; 3 fallos → `down`, 2 éxitos → `up`). Entre la caída real y la marca `down`, las peticiones enviadas al nodo muerto vencen por *timeout* de 1 s.

| Seg. | Video | Escenario programado | Emergente |
| :--- | :---: | :--- | :--- |
| Round robin | 0–10 s | reparto igual | C (3× más lento) acumula cola y timeouts |
| Least connections | 10–26 s | `set_algo lc` | reparto ∝ capacidad; latencia baja |
| Caída de B | 26–40 s | `crash b1` a los 26 s | detección en 1,5 s; 15 peticiones fallidas; failover a A y C |
| B vuelve | 40–52 s | `recover b1` a los 40 s | reingreso tras 2 chequeos (1,0 s) |
| Balance | 52–60 s | — | p95 RR 806 ms vs LC 253 ms (3,2×) |

## Audio

`SOUND_MAP` v2 añade los bloques de estos episodios (`_render_architecture_events`, con su propio substream de RNG: el audio del Ep. 01 no cambia): `cache.hit` destellos agudos / `cache.miss` golpe grave (ventanas 100–120 ms); `queue.put`, `msg.done`, `queue.drop`, `queue.block`; `lb.route` una nota pentatónica por backend; `req.error` ráfaga de ruido; `sys.alert` (caída de nodo, `cache.flush`) y `sys.recover` (reingreso).

## Verificación

`tests/unit/test_architecture_episodes.py`: conservación y capacidad de la cola, 0 pérdidas bajo `block`, tasa del productor ≈ capacidad del consumidor, hit ≪ miss, sin caché el disco se satura, detección por health check acotada, ningún tráfico al nodo fuera del pool, determinismo de trace por episodio, render de cuadros clave y audio finito no silencioso.
