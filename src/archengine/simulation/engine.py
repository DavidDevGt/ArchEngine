"""Ciclo de eventos discreto con reloj virtual en microsegundos enteros (docs/02 §2, ADR-0002).

Cola de prioridad con clave ``(t_us, seq)``: ``seq`` monotono global desempata de forma
determinista. Los componentes solo interactuan via eventos; no acceden al reloj de pared.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from archengine.core.rng import deterministic_rng
from archengine.simulation.trace import Trace


@dataclass(order=True)
class Event:
    """Evento discreto. Solo ``(t_us, seq)`` participa del orden."""

    t_us: int
    seq: int
    target: str = field(compare=False)
    kind: str = field(compare=False)
    payload: dict[str, Any] = field(compare=False, default_factory=dict)


class Ctx:
    """Contexto entregado a los componentes durante ``handle``."""

    def __init__(self, sim: Simulation) -> None:
        self._sim = sim

    @property
    def now_us(self) -> int:
        return self._sim.now_us

    @property
    def trace(self) -> Trace:
        return self._sim.trace

    def rng(self, name: str) -> np.random.Generator:
        return self._sim.rng(name)

    def at(self, t_us: int, target: str, kind: str, **payload: Any) -> Event:
        """Crea un evento en tiempo absoluto (>= now, validado al encolar)."""
        return self._sim.make_event(t_us, target, kind, payload)

    def after(self, delay_us: int, target: str, kind: str, **payload: Any) -> Event:
        """Crea un evento ``delay_us`` despues del instante actual."""
        return self._sim.make_event(self._sim.now_us + delay_us, target, kind, payload)

    def emit(self, comp: str, kind: str, a: int = 0, b: int = 0) -> None:
        """Registra un evento observable en la trace al instante actual."""
        self._sim.trace.record(self._sim.now_us, comp, kind, a, b)

    def set_field(self, key: str, value: int) -> None:
        """Registra una transicion de estado al instante actual."""
        self._sim.trace.set_field(self._sim.now_us, key, value)


class Component(Protocol):
    """Contrato de componente simulable (docs/02 §9)."""

    id: str

    def handle(self, ev: Event, ctx: Ctx) -> Iterable[Event]: ...

    def snapshot(self) -> dict[str, Any]: ...

    def restore(self, snap: dict[str, Any]) -> None: ...


class Simulation:
    """Orquesta componentes, cola de eventos, RNG por substream y trace."""

    def __init__(self, seed: int = 42, trace: Trace | None = None) -> None:
        self.seed = seed
        self.now_us = 0
        self.trace = trace if trace is not None else Trace()
        self.components: dict[str, Component] = {}
        self._queue: list[Event] = []
        self._seq = 0
        self._rngs: dict[str, np.random.Generator] = {}
        self._ctx = Ctx(self)
        self.processed = 0

    def add(self, component: Component) -> None:
        if component.id in self.components:
            raise ValueError(f"Componente duplicado: {component.id}")
        self.components[component.id] = component

    def rng(self, name: str) -> np.random.Generator:
        if name not in self._rngs:
            self._rngs[name] = deterministic_rng(self.seed, name)
        return self._rngs[name]

    def make_event(self, t_us: int, target: str, kind: str, payload: dict[str, Any]) -> Event:
        if t_us < self.now_us:
            raise ValueError(f"Evento en el pasado: {t_us} < {self.now_us} ({target}/{kind})")
        self._seq += 1
        return Event(t_us=int(t_us), seq=self._seq, target=target, kind=kind, payload=payload)

    def schedule(self, ev: Event) -> None:
        heapq.heappush(self._queue, ev)

    def schedule_at(self, t_us: int, target: str, kind: str, **payload: Any) -> None:
        self.schedule(self.make_event(t_us, target, kind, payload))

    @property
    def pending(self) -> int:
        return len(self._queue)

    def run_until(self, t_end_us: int | None = None) -> Trace:
        """Procesa eventos hasta ``t_end_us`` (inclusive) o hasta vaciar la cola."""
        q = self._queue
        ctx = self._ctx
        while q and (t_end_us is None or q[0].t_us <= t_end_us):
            ev = heapq.heappop(q)
            self.now_us = ev.t_us
            comp = self.components[ev.target]
            for new_ev in comp.handle(ev, ctx):
                heapq.heappush(q, new_ev)
            self.processed += 1
        if t_end_us is not None:
            self.now_us = max(self.now_us, t_end_us)
        return self.trace
