"""Cola de mensajes acotada: productor, buffer circular y consumidor (docs/13, Ep. 03).

La cola tiene capacidad fija y dos politicas de desborde: ``drop`` (descarta el mensaje nuevo) y
``block`` (*backpressure*: el productor no recibe el ack y deja de producir hasta que haya hueco).
El retardo de cola, las perdidas y el ritmo efectivo del productor emergen del modelo.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from archengine.simulation.engine import Ctx, Event


@dataclass(frozen=True)
class QueueParams:
    capacity: int = 16
    service_us: int = 100_000  # tiempo medio de proceso del consumidor
    policy: str = "drop"  # "drop" | "block"
    jitter_sigma: float = 0.15  # sigma lognormal del servicio


class BoundedQueue:
    """Componente ``queue``: acepta ``put`` y ``set_policy``; el consumidor llama a ``pop``."""

    def __init__(self, params: QueueParams) -> None:
        self.id = "queue"
        self.p = params
        self.policy = params.policy
        self.items: deque[int] = deque()  # instante de encolado de cada mensaje
        self.enq = 0
        self.deq = 0
        self.dropped = 0
        self.blocked_since: int | None = None

    def handle(self, ev: Event, ctx: Ctx) -> Iterable[Event]:
        now = ctx.now_us
        if ev.kind == "set_policy":
            self.policy = str(ev.payload["policy"])
            ctx.emit(self.id, "queue.policy", 1 if self.policy == "block" else 0, 0)
            ctx.set_field("q.policy", 1 if self.policy == "block" else 0)
            return ()
        if ev.kind != "put":
            raise ValueError(f"Evento desconocido para queue: {ev.kind}")
        if len(self.items) < self.p.capacity:
            self._accept(ctx, now)
            return [ctx.at(now, "producer", "ack"), ctx.at(now, "consumer", "kick")]
        if self.policy == "drop":
            self.dropped += 1
            ctx.emit(self.id, "queue.drop", self.dropped, 0)
            ctx.set_field("q.dropped", self.dropped)
            return [ctx.at(now, "producer", "ack")]
        self.blocked_since = now  # backpressure: sin ack, el productor se detiene
        ctx.emit(self.id, "queue.block", 0, 0)
        ctx.set_field("q.blocked", 1)
        return ()

    def _accept(self, ctx: Ctx, t_enq: int) -> None:
        self.items.append(t_enq)
        self.enq += 1
        ctx.emit(self.id, "queue.put", len(self.items), 0)
        ctx.set_field("q.enq", self.enq)
        ctx.set_field("q.depth", len(self.items))

    def pop(self, ctx: Ctx) -> tuple[int, list[Event]]:
        """Saca el mensaje mas antiguo; si habia un productor bloqueado, admite su mensaje."""
        t_enq = self.items.popleft()
        self.deq += 1
        ctx.set_field("q.deq", self.deq)
        ctx.set_field("q.depth", len(self.items))
        out: list[Event] = []
        if self.blocked_since is not None:
            waited = ctx.now_us - self.blocked_since
            self.blocked_since = None
            ctx.emit(self.id, "queue.unblock", waited, 0)
            ctx.set_field("q.blocked", 0)
            self._accept(ctx, ctx.now_us)
            out.append(ctx.at(ctx.now_us, "producer", "ack"))
        return t_enq, out

    def snapshot(self) -> dict[str, Any]:
        return {"items": list(self.items), "enq": self.enq, "deq": self.deq, "drop": self.dropped}

    def restore(self, snap: dict[str, Any]) -> None:
        self.items = deque(int(x) for x in snap["items"])
        self.enq, self.deq, self.dropped = int(snap["enq"]), int(snap["deq"]), int(snap["drop"])


class Consumer:
    """Componente ``consumer``: sirve de a un mensaje; ``set_factor`` lo vuelve lento."""

    def __init__(self, params: QueueParams, queue: BoundedQueue) -> None:
        self.id = "consumer"
        self.p = params
        self.q = queue
        self.factor = 1.0
        self.busy = False
        self.done = 0

    def handle(self, ev: Event, ctx: Ctx) -> Iterable[Event]:
        if ev.kind == "set_factor":
            self.factor = float(ev.payload["factor"])
            ctx.emit(self.id, "consumer.factor", int(self.factor * 100), 0)
            ctx.set_field("consumer.factor_pct", int(self.factor * 100))
            return ()
        if ev.kind == "done":
            self.busy = False
            self.done += 1
            ctx.emit(self.id, "msg.done", self.done, 0)
            ctx.set_field("consumer.done", self.done)
            ctx.set_field("consumer.busy", 0)
        elif ev.kind != "kick":
            raise ValueError(f"Evento desconocido para consumer: {ev.kind}")
        if self.busy or not self.q.items:
            return ()
        t_enq, out = self.q.pop(ctx)
        now = ctx.now_us
        wait = now - t_enq
        jitter = float(ctx.rng("consumer.service").lognormal(0.0, self.p.jitter_sigma))
        svc = max(1, int(self.p.service_us * self.factor * jitter))
        self.busy = True
        ctx.emit(self.id, "msg.start", wait, svc)
        ctx.set_field("consumer.busy", 1)
        ctx.set_field("q.wait_us", wait)
        out.append(ctx.at(now + svc, self.id, "done"))
        return out

    def snapshot(self) -> dict[str, Any]:
        return {"factor": self.factor, "done": self.done}

    def restore(self, snap: dict[str, Any]) -> None:
        self.factor, self.done = float(snap["factor"]), int(snap["done"])


class Producer:
    """Componente ``producer``: lazo cerrado con ack; llegadas Poisson con tasa por tramos."""

    def __init__(self, rate_schedule: Sequence[tuple[int, float]]) -> None:
        self.id = "producer"
        self.schedule = sorted(rate_schedule)  # (desde_us, msgs/s)
        self.sent = 0

    def rate_at(self, t_us: int) -> float:
        rate = self.schedule[0][1]
        for t0, r in self.schedule:
            if t_us >= t0:
                rate = r
        return rate

    def _gap(self, ctx: Ctx) -> int:
        mean = 1e6 / self.rate_at(ctx.now_us)
        return max(1, int(ctx.rng("producer.gaps").exponential(mean)))

    def handle(self, ev: Event, ctx: Ctx) -> Iterable[Event]:
        now = ctx.now_us
        if ev.kind == "next":
            self.sent += 1
            ctx.emit(self.id, "msg.sent", self.sent, 0)
            ctx.set_field("producer.sent", self.sent)
            return [ctx.at(now, "queue", "put")]
        if ev.kind == "ack":
            return [ctx.at(now + self._gap(ctx), self.id, "next")]
        raise ValueError(f"Evento desconocido para producer: {ev.kind}")

    def snapshot(self) -> dict[str, Any]:
        return {"sent": self.sent}

    def restore(self, snap: dict[str, Any]) -> None:
        self.sent = int(snap["sent"])
