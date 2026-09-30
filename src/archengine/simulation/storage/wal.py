"""Write-Ahead Log con group commit periodico (docs/02 §5.2; Cassandra commitlog periodic).

Los registros se acumulan en memoria (volatil) y se hacen durables en el disco del WAL cada
``sync_interval_us`` como una escritura secuencial. ``power_loss`` descarta la cola volatil;
``replay`` relee lo durable y su costo proviene del modelo de disco, no se asume.
"""

from __future__ import annotations

from archengine.simulation.storage.disk import PAGE_BYTES, PAGES_PER_TRACK, DiskModel, IoResult


class Wal:
    def __init__(self, disk: DiskModel, sync_interval_us: int = 10_000) -> None:
        self.disk = disk
        self.sync_interval_us = sync_interval_us
        self.durable: list[int] = []  # claves durables desde el ultimo truncate
        self.durable_bytes = 0
        self._pending: list[int] = []
        self._pending_bytes = 0
        self.total_bytes_written = 0
        self._next_track = 0

    @property
    def pending_records(self) -> int:
        return len(self._pending)

    def append(self, key: int, record_bytes: int) -> None:
        self._pending.append(key)
        self._pending_bytes += record_bytes

    def sync(self, now_us: int) -> IoResult | None:
        """Group commit: una escritura secuencial con todo lo pendiente."""
        if not self._pending:
            return None
        pages = -(-self._pending_bytes // PAGE_BYTES)
        io = self.disk.access(now_us, self._next_track, pages, write=True, sequential=True)
        self._next_track = io.track
        self.durable.extend(self._pending)
        self.durable_bytes += self._pending_bytes
        self.total_bytes_written += pages * PAGE_BYTES
        self._pending = []
        self._pending_bytes = 0
        return io

    def truncate(self, n_records: int, record_bytes: int) -> None:
        """Descarta los primeros ``n_records`` durables (ya persistidos en SSTable)."""
        del self.durable[:n_records]
        self.durable_bytes = max(0, self.durable_bytes - n_records * record_bytes)

    def power_loss(self) -> int:
        """Pierde los registros aun no sincronizados; devuelve cuantos."""
        lost = len(self._pending)
        self._pending = []
        self._pending_bytes = 0
        return lost

    def replay_chunk(self, now_us: int, offset_pages: int, n_pages: int) -> IoResult:
        """Lee ``n_pages`` del WAL a partir de ``offset_pages`` (lectura secuencial)."""
        track = offset_pages // PAGES_PER_TRACK
        return self.disk.access(now_us, track, n_pages, sequential=offset_pages > 0)
