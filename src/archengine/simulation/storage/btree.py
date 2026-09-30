"""B+Tree con buffer pool LRU y escritura in-place sobre un disco mecanico (docs/02 §5.3).

Modelo de *upsert* aleatorio sobre una tabla ya cargada (arbol de 3 niveles: raiz, nivel 1
y hojas de 4 KiB). La amplificacion de escritura y los seeks largos son **emergentes**:
cada put lee paginas que faltan del pool y, al desalojar una hoja sucia, la reescribe entera.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from archengine.simulation.engine import Ctx, Event
from archengine.simulation.storage.disk import PAGE_BYTES, PAGES_PER_TRACK, DiskModel


@dataclass(frozen=True)
class BTreeParams:
    fanout: int = 256
    buffer_pool_pages: int = 1024
    n_leaves: int = 1_000_000
    record_bytes: int = 512


class BTree:
    """Componente B+Tree. ``id`` fijo: ``btree``."""

    def __init__(self, params: BTreeParams, disk: DiskModel) -> None:
        self.id = "btree"
        self.p = params
        self.disk = disk
        self.n_l1 = -(-params.n_leaves // params.fanout)
        self.pool: OrderedDict[int, bool] = OrderedDict()  # page_id -> sucia
        self._queue: deque[int] = deque()
        self._busy = False
        self.puts = 0
        self.pages_written = 0
        self.pages_read = 0
        self.busy_us_total = 0

    # --- geometria de paginas -----------------------------------------------------------------

    def _leaf_page(self, key: int) -> int:
        return 1 + self.n_l1 + key % self.p.n_leaves

    def _l1_page(self, leaf_index: int) -> int:
        return 1 + leaf_index // self.p.fanout

    def page_track(self, page: int) -> int:
        """Pista fisica: arbol cargado por bulk-load, hojas contiguas en orden de clave."""
        if page == 0:
            return 0
        if page <= self.n_l1:
            return ((page - 1) * self.p.fanout) // PAGES_PER_TRACK
        return (page - 1 - self.n_l1) // PAGES_PER_TRACK

    @property
    def bytes_logical(self) -> int:
        return self.puts * self.p.record_bytes

    @property
    def write_amp(self) -> float:
        return self.pages_written * PAGE_BYTES / max(1, self.bytes_logical)

    # --- protocolo ------------------------------------------------------------------------------

    def handle(self, ev: Event, ctx: Ctx) -> Iterable[Event]:
        if ev.kind == "put":
            self._queue.append(int(ev.payload["key"]))
            if not self._busy:
                return self._serve(ctx)
            return ()
        if ev.kind == "svc.done":
            self._busy = False
            return self._serve(ctx) if self._queue else ()
        raise ValueError(f"Evento desconocido para btree: {ev.kind}")

    def snapshot(self) -> dict[str, Any]:
        return {
            "pool": list(self.pool.items()),
            "puts": self.puts,
            "pages_written": self.pages_written,
            "pages_read": self.pages_read,
        }

    def restore(self, snap: dict[str, Any]) -> None:
        self.pool = OrderedDict((int(k), bool(v)) for k, v in snap["pool"])
        self.puts = int(snap["puts"])
        self.pages_written = int(snap["pages_written"])
        self.pages_read = int(snap["pages_read"])

    # --- servicio de un put (serializado: un solo escritor) -------------------------------------

    def _io(self, ctx: Ctx, t: int, page: int, *, write: bool) -> int:
        trace = ctx.trace
        io = self.disk.access(t, self.page_track(page), 1, write=write)
        trace.record(
            io.start_us, self.id, "disk.seek", abs(io.delta_track), io.done_us - io.start_us
        )
        trace.set_field(io.done_us, "btree.head_track", io.track)
        if write:
            self.pages_written += 1
        else:
            self.pages_read += 1
        return io.done_us

    def _serve(self, ctx: Ctx) -> list[Event]:
        key = self._queue.popleft()
        self._busy = True
        start = ctx.now_us
        t = start
        leaf = self._leaf_page(key)
        for page in (0, self._l1_page(leaf - 1 - self.n_l1), leaf):
            if page in self.pool:
                self.pool.move_to_end(page)
                continue
            if len(self.pool) >= self.p.buffer_pool_pages:
                victim, dirty = self.pool.popitem(last=False)
                if dirty:
                    t = self._io(ctx, t, victim, write=True)
            t = self._io(ctx, t, page, write=False)
            self.pool[page] = False
        self.pool[leaf] = True
        self.puts += 1
        self.busy_us_total += t - start
        tr = ctx.trace
        tr.record(t, self.id, "btree.put", self.page_track(leaf), t - start)
        tr.set_field(t, "btree.puts", self.puts)
        tr.set_field(t, "btree.pages_written", self.pages_written)
        tr.set_field(t, "btree.pages_read", self.pages_read)
        tr.set_field(t, "btree.bytes_logical", self.bytes_logical)
        return [ctx.at(t, self.id, "svc.done")]
