"""Load balancer (round robin / least connections) con health checks y failover (docs/13, Ep. 04).

Cada backend es un servidor de cola FIFO con tiempo de servicio exponencial. El balanceador reparte
segun su algoritmo y solo conoce la salud por *health checks*: entre la caida real de un nodo y su
marca como ``down`` las peticiones enviadas se pierden y vencen por timeout.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from archengine.simulation.engine import Ctx, Event

NET_US = 200  # latencia balanceador <-> backend
PROBE_US = 100


@dataclass(frozen=True)
class LbParams:
    service_us: Sequence[int] = (40_000, 40_000, 120_000)  # medio por backend
    algo: str = "rr"  # "rr" | "lc"
    health_interval_us: int = 500_000
    fail_threshold: int = 3
    rise_threshold: int = 2
    timeout_us: int = 1_000_000
    end_us: int = 60_000_000  # los health checks se detienen aqui


class Backend:
    """Componente ``b<i>``: FIFO de un servidor; ``crash``/``recover`` lo apagan/encienden."""

    def __init__(self, index: int, service_us: int) -> None:
        self.id = f"b{index}"
        self.index = index
        self.service_us = service_us
        self.up = True
        self.queue: deque[int] = deque()
        self.current: int | None = None
        self.epoch = 0  # invalida ``done`` pendientes tras un crash
        self.served = 0

    def conns(self) -> int:
        return len(self.queue) + (1 if self.current is not None else 0)

    def handle(self, ev: Event, ctx: Ctx) -> Iterable[Event]:
        now = ctx.now_us
        if ev.kind == "req":
            if not self.up:
                return ()  # agujero negro hasta que el balanceador lo marque down
            self.queue.append(int(ev.payload["rid"]))
            ctx.set_field(f"{self.id}.conns", self.conns())
            return self._serve(ctx)
        if ev.kind == "done":
            if ev.payload["epoch"] != self.epoch:
                return ()
            rid = self.current
            self.current = None
            self.served += 1
            ctx.set_field(f"{self.id}.conns", self.conns())
            out = [ctx.at(now + NET_US, "lb", "complete", rid=rid, backend=self.index)]
            return out + self._serve(ctx)
        if ev.kind == "probe":
            return [ctx.at(now + PROBE_US, "lb", "probe.ok", backend=self.index)] if self.up else ()
        if ev.kind == "crash":
            self.up = False
            self.epoch += 1
            self.queue.clear()
            self.current = None
            ctx.emit(self.id, "node.crash", self.index, 0)
            ctx.set_field(f"{self.id}.up", 0)
            ctx.set_field(f"{self.id}.conns", 0)
            return ()
        if ev.kind == "recover":
            self.up = True
            ctx.emit(self.id, "node.recover", self.index, 0)
            ctx.set_field(f"{self.id}.up", 1)
            return ()
        raise ValueError(f"Evento desconocido para {self.id}: {ev.kind}")

    def _serve(self, ctx: Ctx) -> list[Event]:
        if self.current is not None or not self.queue:
            return []
        self.current = self.queue.popleft()
        svc = max(1, int(ctx.rng(f"{self.id}.service").exponential(self.service_us)))
        ctx.set_field(f"{self.id}.conns", self.conns())
        return [ctx.at(ctx.now_us + svc, self.id, "done", epoch=self.epoch)]

    def snapshot(self) -> dict[str, Any]:
        return {"served": self.served, "up": self.up}

    def restore(self, snap: dict[str, Any]) -> None:
        self.served, self.up = int(snap["served"]), bool(snap["up"])


class LoadBalancer:
    """Componente ``lb``: ``put`` (peticion), ``complete``, ``timeout`` y health checks."""

    def __init__(self, params: LbParams) -> None:
        self.id = "lb"
        self.p = params
        n = len(params.service_us)
        self.n = n
        self.algo = params.algo
        self.conns = [0] * n
        self.healthy = [True] * n
        self.fails = [0] * n
        self.oks = [0] * n
        self.replied = [True] * n
        self.pending: dict[int, tuple[int, int]] = {}  # rid -> (backend, t0)
        self.rr_next = 0
        self.rid = 0
        self.done = 0
        self.errors = 0
        self.lat_sum_us = 0

    def snapshot(self) -> dict[str, Any]:
        return {"conns": list(self.conns), "healthy": list(self.healthy), "done": self.done}

    def restore(self, snap: dict[str, Any]) -> None:
        self.conns = [int(c) for c in snap["conns"]]
        self.healthy = [bool(h) for h in snap["healthy"]]
        self.done = int(snap["done"])

    def handle(self, ev: Event, ctx: Ctx) -> Iterable[Event]:
        k = ev.kind
        if k == "put":
            return self._route(ctx)
        if k == "complete":
            return self._complete(ev, ctx)
        if k == "timeout":
            return self._timeout(ev, ctx)
        if k == "health":
            return self._health(ctx)
        if k == "probe.ok":
            self.replied[int(ev.payload["backend"])] = True
            return ()
        if k == "set_algo":
            self.algo = str(ev.payload["algo"])
            ctx.emit(self.id, "lb.algo", 1 if self.algo == "lc" else 0, 0)
            ctx.set_field("lb.algo", 1 if self.algo == "lc" else 0)
            return ()
        raise ValueError(f"Evento desconocido para lb: {k}")

    def _pick(self) -> int | None:
        live = [i for i in range(self.n) if self.healthy[i]]
        if not live:
            return None
        if self.algo == "lc":
            best = min(self.conns[i] for i in live)
            cands = [i for i in live if self.conns[i] == best]
            return cands[self.rid % len(cands)]  # desempate rotatorio, determinista
        for _ in range(self.n):
            i = self.rr_next % self.n
            self.rr_next += 1
            if self.healthy[i]:
                return i
        return None

    def _route(self, ctx: Ctx) -> list[Event]:
        now = ctx.now_us
        self.rid += 1
        rid = self.rid
        i = self._pick()
        ctx.set_field("lb.reqs", rid)
        if i is None:
            self.errors += 1
            ctx.emit(self.id, "req.error", -1, 0)
            ctx.set_field("lb.errors", self.errors)
            return []
        self.conns[i] += 1
        self.pending[rid] = (i, now)
        ctx.emit(self.id, "lb.route", i, rid)
        ctx.set_field(f"lb.conns{i}", self.conns[i])
        return [
            ctx.at(now + NET_US, f"b{i}", "req", rid=rid),
            ctx.at(now + self.p.timeout_us, self.id, "timeout", rid=rid),
        ]

    def _complete(self, ev: Event, ctx: Ctx) -> list[Event]:
        rid = int(ev.payload["rid"])
        entry = self.pending.pop(rid, None)
        if entry is None:
            return []  # ya vencio por timeout
        i, t0 = entry
        self.conns[i] -= 1
        lat = ctx.now_us - t0
        self.done += 1
        self.lat_sum_us += lat
        ctx.emit(self.id, "req.done", lat, i)
        ctx.set_field("lb.done", self.done)
        ctx.set_field("lb.lat_sum_us", self.lat_sum_us)
        ctx.set_field(f"lb.conns{i}", self.conns[i])
        return []

    def _timeout(self, ev: Event, ctx: Ctx) -> list[Event]:
        entry = self.pending.pop(int(ev.payload["rid"]), None)
        if entry is None:
            return []
        i, _ = entry
        self.conns[i] -= 1
        self.errors += 1
        ctx.emit(self.id, "req.error", i, 0)
        ctx.set_field("lb.errors", self.errors)
        ctx.set_field(f"lb.conns{i}", self.conns[i])
        return []

    def _health(self, ctx: Ctx) -> list[Event]:
        now = ctx.now_us
        out: list[Event] = []
        for i in range(self.n):
            if self.replied[i]:
                self.oks[i] += 1
                self.fails[i] = 0
            else:
                self.fails[i] += 1
                self.oks[i] = 0
            if self.healthy[i] and self.fails[i] >= self.p.fail_threshold:
                self.healthy[i] = False
                ctx.emit(self.id, "lb.mark_down", i, 0)
                ctx.set_field(f"lb.healthy{i}", 0)
            elif not self.healthy[i] and self.oks[i] >= self.p.rise_threshold:
                self.healthy[i] = True
                ctx.emit(self.id, "lb.mark_up", i, 0)
                ctx.set_field(f"lb.healthy{i}", 1)
            self.replied[i] = False
            out.append(ctx.at(now, f"b{i}", "probe"))
        if now + self.p.health_interval_us <= self.p.end_us:
            out.append(ctx.at(now + self.p.health_interval_us, self.id, "health"))
        return out
