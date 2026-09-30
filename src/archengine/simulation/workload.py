"""Generador de carga determinista: llegadas Poisson sembradas (OQ-18, docs/02 §5.4).

Las llegadas y claves se pre-calculan vectorizadas con ``core.rng`` y se entregan al motor
destino una a una; cada motor serializa las escrituras segun su propio modelo de costo.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from archengine.core.rng import deterministic_rng
from archengine.simulation.engine import Ctx, Event


def poisson_arrivals(n: int, rate_per_s: float, seed: int, name: str = "workload") -> np.ndarray:
    """Tiempos de llegada enteros (µs), estrictamente crecientes."""
    rng = deterministic_rng(seed, f"{name}.arrivals")
    gaps = np.maximum(1, np.rint(rng.exponential(1e6 / rate_per_s, size=n)).astype(np.int64))
    return np.cumsum(gaps)


def zipf_keys(n: int, n_keys: int, s: float, seed: int, name: str = "workload.zipf") -> np.ndarray:
    """``n`` claves con popularidad Zipf(s) acotada a ``n_keys``; el rango 0 es el mas popular."""
    p = np.arange(1, n_keys + 1, dtype=np.float64) ** -s
    p /= p.sum()
    return deterministic_rng(seed, name).choice(n_keys, size=n, p=p).astype(np.int64)


class Workload:
    """Fuente: emite ``put`` (o ``kind``) hacia ``target`` y ``bench.tick`` cada ``tick_every``."""

    def __init__(
        self,
        target: str,
        arrivals_us: np.ndarray,
        keys: np.ndarray,
        comp_id: str = "workload",
        tick_every: int = 1000,
        kind: str = "put",
    ) -> None:
        self.id = comp_id
        self.kind = kind
        self.target = target
        self.arrivals = arrivals_us
        self.keys = keys
        self.tick_every = tick_every
        self.issued = 0

    @classmethod
    def random_writes(
        cls,
        target: str,
        n: int,
        rate_per_s: float,
        seed: int,
        comp_id: str = "workload",
        key_space: int = 2**31,
    ) -> Workload:
        arr = poisson_arrivals(n, rate_per_s, seed)
        keys = deterministic_rng(seed, "workload.keys").integers(0, key_space, size=n)
        return cls(target, arr, keys, comp_id)

    @property
    def first_us(self) -> int:
        return int(self.arrivals[0])

    def handle(self, ev: Event, ctx: Ctx) -> Iterable[Event]:
        i = self.issued
        self.issued += 1
        out = [ctx.at(int(self.arrivals[i]), self.target, self.kind, key=int(self.keys[i]))]
        if self.issued % self.tick_every == 0:
            ctx.emit(self.id, "bench.tick", self.issued, len(self.arrivals))
            ctx.set_field(f"{self.id}.issued", self.issued)
        if self.issued < len(self.arrivals):
            out.append(ctx.at(int(self.arrivals[self.issued]), self.id, "next"))
        return out

    def snapshot(self) -> dict[str, int]:
        return {"issued": self.issued}

    def restore(self, snap: dict[str, int]) -> None:
        self.issued = int(snap["issued"])
