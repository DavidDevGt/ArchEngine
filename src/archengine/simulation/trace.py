"""Trace columnar NumPy + series de estado + state_at(t) (docs/02 §3, R-03/R-04).

Almacena eventos como arrays enteros (t_us, comp, kind, a, b) y el estado observable como
series escalonadas (campo -> (t_us, valor)). El render solo lee vistas de estado via
``state_at``; nunca toca objetos vivos de la simulacion.
"""

from __future__ import annotations

import hashlib
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class EventArrays:
    """Vista columnar inmutable de eventos filtrados."""

    t_us: np.ndarray
    comp: np.ndarray
    kind: np.ndarray
    a: np.ndarray
    b: np.ndarray
    kind_names: tuple[str, ...]
    comp_names: tuple[str, ...]

    def __len__(self) -> int:
        return int(self.t_us.shape[0])


class Trace:
    """Registro de eventos y series de estado de una simulacion."""

    def __init__(self) -> None:
        self._t: list[int] = []
        self._comp: list[int] = []
        self._kind: list[int] = []
        self._a: list[int] = []
        self._b: list[int] = []
        self._kinds: dict[str, int] = {}
        self._comps: dict[str, int] = {}
        self._series_t: dict[str, list[int]] = {}
        self._series_v: dict[str, list[int]] = {}
        self._frozen: dict[str, tuple[np.ndarray, np.ndarray]] | None = None
        self._arrays: tuple[np.ndarray, ...] | None = None

    # --- escritura -------------------------------------------------------------------------

    def record(self, t_us: int, comp: str, kind: str, a: int = 0, b: int = 0) -> None:
        """Registra un evento observable."""
        self._t.append(t_us)
        self._comp.append(self._comps.setdefault(comp, len(self._comps)))
        self._kind.append(self._kinds.setdefault(kind, len(self._kinds)))
        self._a.append(int(a))
        self._b.append(int(b))
        self._arrays = None

    def set_field(self, t_us: int, key: str, value: int) -> None:
        """Registra una transicion de estado ``key`` (solo si el valor cambia)."""
        ts = self._series_t.setdefault(key, [])
        vs = self._series_v.setdefault(key, [])
        if vs and vs[-1] == value:
            return
        if ts and ts[-1] == t_us:
            vs[-1] = int(value)
        else:
            ts.append(t_us)
            vs.append(int(value))
        self._frozen = None

    # --- lectura ---------------------------------------------------------------------------

    @property
    def kind_names(self) -> tuple[str, ...]:
        return tuple(self._kinds)

    @property
    def comp_names(self) -> tuple[str, ...]:
        return tuple(self._comps)

    @property
    def n_events(self) -> int:
        return len(self._t)

    @property
    def end_us(self) -> int:
        return self._t[-1] if self._t else 0

    def _event_arrays(self) -> tuple[np.ndarray, ...]:
        if self._arrays is None:
            self._arrays = (
                np.asarray(self._t, dtype=np.int64),
                np.asarray(self._comp, dtype=np.int32),
                np.asarray(self._kind, dtype=np.int16),
                np.asarray(self._a, dtype=np.int64),
                np.asarray(self._b, dtype=np.int64),
            )
        return self._arrays

    def events(self, kinds: Sequence[str] | None = None) -> EventArrays:
        """Eventos (ordenados por tiempo de registro), opcionalmente filtrados por ``kind``."""
        t, comp, kind, a, b = self._event_arrays()
        if kinds is not None:
            ids = [self._kinds[k] for k in kinds if k in self._kinds]
            mask = np.isin(kind, np.asarray(ids, dtype=np.int16))
            t, comp, kind, a, b = t[mask], comp[mask], kind[mask], a[mask], b[mask]
        return EventArrays(t, comp, kind, a, b, self.kind_names, self.comp_names)

    def first(self, kind: str) -> int | None:
        """Tiempo (µs) del primer evento de ese ``kind`` o None."""
        ev = self.events([kind])
        return int(ev.t_us[0]) if len(ev) else None

    def _series(self) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        if self._frozen is None:
            self._frozen = {
                k: (
                    np.asarray(self._series_t[k], dtype=np.int64),
                    np.asarray(self._series_v[k], dtype=np.int64),
                )
                for k in self._series_t
            }
        return self._frozen

    def value_at(self, key: str, t_us: int, default: int = 0) -> int:
        """Valor de la serie ``key`` en ``t_us`` (ultima transicion con t <= t_us)."""
        ts = self._series_t.get(key)
        if not ts:
            return default
        i = bisect_right(ts, t_us) - 1
        return default if i < 0 else self._series_v[key][i]

    def state_at(self, t_us: int) -> dict[str, int]:
        """Vista inmutable del estado de todos los campos en ``t_us``."""
        return {k: self.value_at(k, t_us) for k in self._series_t}

    def series_keys(self) -> list[str]:
        return list(self._series_t)

    # --- integridad y persistencia ----------------------------------------------------------

    def trace_hash(self) -> str:
        """SHA-256 canonico (little-endian) de eventos, nombres y series (NFR-04)."""
        h = hashlib.sha256()
        for arr in self._event_arrays():
            h.update(arr.astype(arr.dtype.newbyteorder("<")).tobytes())
        h.update("|".join(self.kind_names).encode())
        h.update("|".join(self.comp_names).encode())
        for k in sorted(self._series_t):
            h.update(k.encode())
            h.update(np.asarray(self._series_t[k], dtype="<i8").tobytes())
            h.update(np.asarray(self._series_v[k], dtype="<i8").tobytes())
        return f"sha256:{h.hexdigest()}"

    def save(self, path: str | Path) -> None:
        """Vuelca la trace a .npz (``archengine simulate --dump``)."""
        t, comp, kind, a, b = self._event_arrays()
        keys = sorted(self._series_t)
        payload: dict[str, np.ndarray] = {
            "t_us": t,
            "comp": comp,
            "kind": kind,
            "a": a,
            "b": b,
            "kind_names": np.asarray(self.kind_names, dtype=str),
            "comp_names": np.asarray(self.comp_names, dtype=str),
            "series_keys": np.asarray(keys, dtype=str),
        }
        for i, k in enumerate(keys):
            payload[f"st_{i}"] = np.asarray(self._series_t[k], dtype=np.int64)
            payload[f"sv_{i}"] = np.asarray(self._series_v[k], dtype=np.int64)
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(p, **payload)  # type: ignore[arg-type]

    @classmethod
    def load(cls, path: str | Path) -> Trace:
        """Carga una trace desde .npz."""
        tr = cls()
        with np.load(Path(path), allow_pickle=False) as z:
            tr._t = z["t_us"].tolist()
            tr._comp = z["comp"].tolist()
            tr._kind = z["kind"].tolist()
            tr._a = z["a"].tolist()
            tr._b = z["b"].tolist()
            tr._kinds = {str(n): i for i, n in enumerate(z["kind_names"])}
            tr._comps = {str(n): i for i, n in enumerate(z["comp_names"])}
            for i, k in enumerate(z["series_keys"]):
                tr._series_t[str(k)] = z[f"st_{i}"].tolist()
                tr._series_v[str(k)] = z[f"sv_{i}"].tolist()
        return tr
