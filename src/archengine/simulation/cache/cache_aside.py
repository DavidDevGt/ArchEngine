"""Cache-aside (Redis + DB): LRU con TTL delante de un disco mecanico (docs/13, Ep. 02).

La app consulta primero la cache; en *miss* lee del disco (seek + rotacion segun ``DiskModel``) y
luego puebla la cache. Nada del resultado esta escrito a mano: la tasa de aciertos y la latencia
emergen de la popularidad Zipf de las claves, la capacidad LRU, el TTL y la cola del cabezal.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np

from archengine.simulation.engine import Ctx, Event
from archengine.simulation.storage.disk import DiskModel


@dataclass(frozen=True)
class CacheAsideParams:
    capacity: int = 1000  # entradas LRU
    ttl_us: int = 20_000_000
    cache_rtt_us: int = 400  # red + Redis (lectura o escritura)
    n_keys: int = 20_000


class CacheAsideApp:
    """Componente ``app``: atiende ``get`` (clave), ``db.done`` y ``flush``."""

    def __init__(self, params: CacheAsideParams, disk: DiskModel, track_of: np.ndarray) -> None:
        self.id = "app"
        self.p = params
        self.disk = disk
        self.track_of = track_of  # clave -> pista (permutacion fija: sin localidad espacial)
        self.cache: OrderedDict[int, int] = OrderedDict()  # clave -> expiracion (µs)
        self.reqs = 0
        self.hits = 0
        self.misses = 0
        self.done = 0
        self.lat_sum_us = 0
        self.inflight = 0

    # --- protocolo ------------------------------------------------------------------------------

    def handle(self, ev: Event, ctx: Ctx) -> Iterable[Event]:
        if ev.kind == "get":
            return self._get(ev, ctx)
        if ev.kind == "db.done":
            return self._db_done(ev, ctx)
        if ev.kind == "flush":
            self.cache.clear()
            ctx.emit(self.id, "cache.flush", 0, 0)
            ctx.set_field("cache.size", 0)
            return ()
        raise ValueError(f"Evento desconocido para app: {ev.kind}")

    def snapshot(self) -> dict[str, Any]:
        return {
            "cache": list(self.cache.items()),
            "reqs": self.reqs,
            "hits": self.hits,
            "misses": self.misses,
        }

    def restore(self, snap: dict[str, Any]) -> None:
        self.cache = OrderedDict((int(k), int(v)) for k, v in snap["cache"])
        self.reqs = int(snap["reqs"])
        self.hits = int(snap["hits"])
        self.misses = int(snap["misses"])

    # --- logica ---------------------------------------------------------------------------------

    def _finish(self, ctx: Ctx, latency_us: int, miss: bool) -> None:
        self.done += 1
        self.lat_sum_us += latency_us
        ctx.emit(self.id, "req.done", latency_us, int(miss))
        ctx.set_field("app.done", self.done)
        ctx.set_field("app.lat_sum_us", self.lat_sum_us)

    def _get(self, ev: Event, ctx: Ctx) -> list[Event]:
        key = int(ev.payload["key"])
        now = ctx.now_us
        self.reqs += 1
        ctx.set_field("app.reqs", self.reqs)
        exp = self.cache.get(key)
        if exp is not None and exp > now:
            self.cache.move_to_end(key)
            self.hits += 1
            ctx.emit(self.id, "cache.hit", key, self.p.cache_rtt_us)
            ctx.set_field("app.hits", self.hits)
            self._finish(ctx, self.p.cache_rtt_us, miss=False)
            return []
        if exp is not None:  # entrada vencida por TTL
            del self.cache[key]
            ctx.emit(self.id, "cache.expire", key, 0)
            ctx.set_field("cache.size", len(self.cache))
        self.misses += 1
        ctx.emit(self.id, "cache.miss", key, 0)
        ctx.set_field("app.misses", self.misses)
        io = self.disk.access(now + self.p.cache_rtt_us, int(self.track_of[key]), 1)
        self.inflight += 1
        ctx.set_field("db.inflight", self.inflight)
        return [ctx.at(io.done_us, self.id, "db.done", key=key, t0=now, io=io)]

    def _db_done(self, ev: Event, ctx: Ctx) -> list[Event]:
        key = int(ev.payload["key"])
        io = ev.payload["io"]
        now = ctx.now_us
        self.inflight -= 1
        ctx.emit(self.id, "disk.seek", abs(io.delta_track), io.done_us - io.start_us)
        ctx.set_field("db.head_track", io.track)
        ctx.set_field("db.inflight", self.inflight)
        if self.p.capacity > 0:  # capacity=0 modela "sin cache": toda lectura va al disco
            if key not in self.cache and len(self.cache) >= self.p.capacity:
                victim, _ = self.cache.popitem(last=False)
                ctx.emit(self.id, "cache.evict", victim, 0)
            self.cache[key] = now + self.p.ttl_us
            self.cache.move_to_end(key)
            ctx.emit(self.id, "cache.fill", key, 0)
            ctx.set_field("cache.size", len(self.cache))
        self._finish(ctx, now - int(ev.payload["t0"]) + self.p.cache_rtt_us, miss=True)
        return []
