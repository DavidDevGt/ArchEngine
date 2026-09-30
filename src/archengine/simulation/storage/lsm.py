"""LSM-Tree con WAL, MemTable, flush a SSTable inmutable y compaction L0->L1 (docs/02 §5.2).

Toda transicion visible queda en la trace como series de estado (``lsm.*``) y eventos
(``memtable.put``, ``lsm.flush.start/end``, ``lsm.compaction.*``, ``power.loss``,
``wal.replay.*``). Los costos de I/O provienen de ``DiskModel`` (secuencial => barato).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from archengine.simulation.engine import Ctx, Event
from archengine.simulation.storage.disk import PAGE_BYTES, PAGES_PER_TRACK, DiskModel
from archengine.simulation.storage.wal import Wal

STATE_UP = 0
STATE_CRASHED = 1
STATE_RECOVERING = 2


@dataclass(frozen=True)
class LsmParams:
    memtable_bytes: int = 67_108_864
    l0_compaction_trigger: int = 4
    record_bytes: int = 512
    put_cpu_us: int = 2
    sync_interval_us: int = 10_000
    progress_steps: int = 20
    replay_chunk_pages: int = 256
    reboot_delay_us: int = 200_000


@dataclass
class SSTable:
    id: int
    level: int
    nbytes: int
    n_keys: int
    track: int


class LsmTree:
    """Componente LSM. ``id`` fijo: ``lsm``."""

    def __init__(self, params: LsmParams, data_disk: DiskModel, wal_disk: DiskModel) -> None:
        self.id = "lsm"
        self.p = params
        self.data_disk = data_disk
        self.wal = Wal(wal_disk, params.sync_interval_us)
        self.memtable: list[int] = []
        self.mem_bytes = 0
        self.immutable: list[int] | None = None
        self.sstables: list[SSTable] = []
        self.state = STATE_UP
        self.epoch = 0
        self.compacting = False
        self.puts = 0
        self.flushes = 0
        self.compactions = 0
        self.bytes_flushed = 0
        self.bytes_compacted = 0
        self._next_sst = 1
        self._next_track = 0
        self._sync_armed = False
        self.recovery_us = 0
        self.recovery_start_us = 0
        self.recovered_keys: list[int] = []
        self.durable_before_crash: list[int] = []

    # --- metricas --------------------------------------------------------------------------

    @property
    def bytes_logical(self) -> int:
        return self.puts * self.p.record_bytes

    @property
    def bytes_physical(self) -> int:
        return self.wal.total_bytes_written + self.bytes_flushed + self.bytes_compacted

    def level_count(self, level: int) -> int:
        return sum(1 for s in self.sstables if s.level == level)

    # --- protocolo de componente -----------------------------------------------------------

    def handle(self, ev: Event, ctx: Ctx) -> Iterable[Event]:
        kind = ev.kind
        if kind == "put":
            return self._put(ev, ctx)
        if kind == "wal.sync":
            return self._wal_sync(ctx)
        if ev.payload.get("epoch", self.epoch) != self.epoch:
            return ()  # evento de un ciclo anterior a un PowerLoss
        if kind == "flush.progress":
            ctx.set_field("lsm.flush_pm", ev.payload["pm"])
            return ()
        if kind == "flush.done":
            return self._flush_done(ctx)
        if kind == "compaction.progress":
            ctx.set_field("lsm.compact_pm", ev.payload["pm"])
            return ()
        if kind == "compaction.done":
            return self._compaction_done(ev, ctx)
        if kind == "power.loss":
            return self._power_loss(ctx)
        if kind == "recover.start":
            return self._recover_start(ctx)
        if kind == "replay.chunk":
            return self._replay_chunk(ev, ctx)
        if kind == "replay.end":
            return self._replay_end(ctx)
        raise ValueError(f"Evento desconocido para lsm: {kind}")

    def snapshot(self) -> dict[str, Any]:
        return {
            "memtable": list(self.memtable),
            "mem_bytes": self.mem_bytes,
            "sstables": [(s.id, s.level, s.nbytes, s.n_keys, s.track) for s in self.sstables],
            "state": self.state,
            "puts": self.puts,
        }

    def restore(self, snap: dict[str, Any]) -> None:
        self.memtable = list(snap["memtable"])
        self.mem_bytes = int(snap["mem_bytes"])
        self.sstables = [SSTable(*t) for t in snap["sstables"]]
        self.state = int(snap["state"])
        self.puts = int(snap["puts"])

    # --- escritura ---------------------------------------------------------------------------

    def _put(self, ev: Event, ctx: Ctx) -> list[Event]:
        if self.state != STATE_UP:
            return []  # el nodo esta caido: la escritura no se confirma
        key = int(ev.payload["key"])
        out: list[Event] = []
        self.wal.append(key, self.p.record_bytes)
        self.memtable.append(key)
        self.mem_bytes += self.p.record_bytes
        self.puts += 1
        ctx.emit(self.id, "memtable.put", key, self.mem_bytes)
        ctx.set_field("lsm.mem_bytes", self.mem_bytes)
        ctx.set_field("lsm.puts", self.puts)
        ctx.set_field("lsm.bytes_logical", self.bytes_logical)
        if not self._sync_armed:
            self._sync_armed = True
            out.append(ctx.after(self.p.sync_interval_us, self.id, "wal.sync"))
        if self.mem_bytes >= self.p.memtable_bytes and self.immutable is None:
            out.extend(self._freeze_and_flush(ctx))
        return out

    def _wal_sync(self, ctx: Ctx) -> list[Event]:
        self._sync_armed = False
        if self.state != STATE_UP:
            return []
        nbytes = self.wal._pending_bytes
        io = self.wal.sync(ctx.now_us)
        if io is not None:
            ctx.emit(self.id, "wal.sync", nbytes, io.done_us - io.start_us)
            ctx.set_field("lsm.wal_bytes", self.wal.durable_bytes)
            ctx.set_field("lsm.bytes_physical", self.bytes_physical)
        return []

    def _progress(
        self, ctx: Ctx, start_us: int, done_us: int, kind: str, epoch: int
    ) -> list[Event]:
        steps = self.p.progress_steps
        return [
            ctx.at(
                start_us + (done_us - start_us) * i // steps,
                self.id,
                kind,
                pm=i * 1000 // steps,
                epoch=epoch,
            )
            for i in range(1, steps)
        ]

    def _freeze_and_flush(self, ctx: Ctx) -> list[Event]:
        """MemTable llena -> Immutable (bloqueada) -> flush secuencial a SSTable L0."""
        self.immutable = self.memtable
        imm_bytes = self.mem_bytes
        self.memtable = []
        self.mem_bytes = 0
        ctx.set_field("lsm.mem_bytes", 0)
        ctx.set_field("lsm.imm_bytes", imm_bytes)
        ctx.emit(self.id, "lsm.flush.start", len(self.immutable), imm_bytes)
        pages = -(-imm_bytes // PAGE_BYTES)
        io = self.data_disk.access(ctx.now_us, self._next_track, pages, write=True, sequential=True)
        self._next_track = io.track
        out = self._progress(ctx, io.start_us, io.done_us, "flush.progress", self.epoch)
        out.append(ctx.at(io.done_us, self.id, "flush.done", epoch=self.epoch))
        return out

    def _flush_done(self, ctx: Ctx) -> list[Event]:
        assert self.immutable is not None
        n_keys = len(self.immutable)
        nbytes = n_keys * self.p.record_bytes
        track = max(0, self._next_track - (nbytes // (PAGES_PER_TRACK * PAGE_BYTES)))
        self.sstables.append(SSTable(self._next_sst, 0, nbytes, n_keys, track))
        self._next_sst += 1
        self.immutable = None
        self.flushes += 1
        self.bytes_flushed += nbytes
        self.wal.truncate(n_keys, self.p.record_bytes)
        ctx.emit(self.id, "lsm.flush.end", n_keys, nbytes)
        ctx.set_field("lsm.imm_bytes", 0)
        ctx.set_field("lsm.flush_pm", 0)
        ctx.set_field("lsm.wal_bytes", self.wal.durable_bytes)
        ctx.set_field("lsm.l0", self.level_count(0))
        ctx.set_field("lsm.bytes_physical", self.bytes_physical)
        ctx.set_field("lsm.read_amp", 1 + len(self.sstables))
        ctx.emit(self.id, "lsm.read_amp", 1 + len(self.sstables))
        out: list[Event] = []
        if self.memtable and self.mem_bytes >= self.p.memtable_bytes:
            out.extend(self._freeze_and_flush(ctx))
        if not self.compacting and self.level_count(0) >= self.p.l0_compaction_trigger:
            out.extend(self._start_compaction(ctx))
        return out

    # --- compaction ------------------------------------------------------------------------

    def _start_compaction(self, ctx: Ctx) -> list[Event]:
        inputs = [s for s in self.sstables if s.level in (0, 1)]
        self.compacting = True
        bytes_in = sum(s.nbytes for s in inputs)
        ctx.emit(self.id, "lsm.compaction.start", bytes_in, len(inputs))
        t = ctx.now_us
        first_start: int | None = None
        for s in inputs:  # merge k-way: lectura secuencial de cada entrada
            io = self.data_disk.access(t, s.track, -(-s.nbytes // PAGE_BYTES), sequential=True)
            first_start = io.start_us if first_start is None else first_start
            t = io.done_us
        out_pages = -(-bytes_in // PAGE_BYTES)
        io = self.data_disk.access(t, self._next_track, out_pages, write=True, sequential=True)
        self._next_track = io.track
        out = self._progress(
            ctx, first_start or ctx.now_us, io.done_us, "compaction.progress", self.epoch
        )
        out.append(
            ctx.at(
                io.done_us,
                self.id,
                "compaction.done",
                epoch=self.epoch,
                input_ids=[s.id for s in inputs],
                bytes_in=bytes_in,
            )
        )
        return out

    def _compaction_done(self, ev: Event, ctx: Ctx) -> list[Event]:
        ids = set(ev.payload["input_ids"])
        bytes_in = int(ev.payload["bytes_in"])
        merged = [s for s in self.sstables if s.id in ids]
        self.sstables = [s for s in self.sstables if s.id not in ids]
        n_keys = sum(s.n_keys for s in merged)
        track = max(0, self._next_track - (bytes_in // (PAGES_PER_TRACK * PAGE_BYTES)))
        self.sstables.append(SSTable(self._next_sst, 1, bytes_in, n_keys, track))
        self._next_sst += 1
        self.compacting = False
        self.compactions += 1
        self.bytes_compacted += bytes_in  # bytes_out == bytes_in (claves unicas, sin tombstones)
        ctx.emit(self.id, "lsm.compaction.end", bytes_in, len(self.sstables))
        ctx.set_field("lsm.compact_pm", 0)
        ctx.set_field("lsm.l0", self.level_count(0))
        ctx.set_field("lsm.l1", self.level_count(1))
        ctx.set_field("lsm.bytes_physical", self.bytes_physical)
        ctx.set_field("lsm.read_amp", 1 + len(self.sstables))
        ctx.emit(self.id, "lsm.read_amp", 1 + len(self.sstables))
        if self.level_count(0) >= self.p.l0_compaction_trigger:
            return self._start_compaction(ctx)
        return []

    # --- PowerLoss y recuperacion ------------------------------------------------------------

    def _power_loss(self, ctx: Ctx) -> list[Event]:
        """Pierde todo el estado volatil; el WAL durable y las SSTables persisten."""
        self.durable_before_crash = list(self.wal.durable)
        lost_mem = len(self.memtable) + (len(self.immutable) if self.immutable else 0)
        lost_wal = self.wal.power_loss()
        self.epoch += 1  # invalida flush/compaction en vuelo
        self.memtable = []
        self.immutable = None
        self.mem_bytes = 0
        self.compacting = False
        self._sync_armed = False
        self.state = STATE_CRASHED
        self.data_disk.busy_until_us = ctx.now_us
        self.wal.disk.busy_until_us = ctx.now_us
        ctx.emit(self.id, "power.loss", lost_mem, lost_wal)
        for key in ("lsm.mem_bytes", "lsm.imm_bytes", "lsm.flush_pm", "lsm.compact_pm"):
            ctx.set_field(key, 0)
        ctx.set_field("lsm.state", STATE_CRASHED)
        return [ctx.after(self.p.reboot_delay_us, self.id, "recover.start", epoch=self.epoch)]

    def _recover_start(self, ctx: Ctx) -> list[Event]:
        self.state = STATE_RECOVERING
        self.recovery_start_us = ctx.now_us
        n_rec = len(self.wal.durable)
        total_pages = -(-(n_rec * self.p.record_bytes) // PAGE_BYTES)
        ctx.emit(self.id, "wal.replay.start", n_rec, total_pages * PAGE_BYTES)
        ctx.set_field("lsm.state", STATE_RECOVERING)
        out: list[Event] = []
        t = ctx.now_us
        offset = 0
        chunk = self.p.replay_chunk_pages
        while offset < total_pages:
            n = min(chunk, total_pages - offset)
            io = self.wal.replay_chunk(t, offset, n)
            t = io.done_us
            offset += n
            out.append(
                ctx.at(
                    t,
                    self.id,
                    "replay.chunk",
                    epoch=self.epoch,
                    bytes=min(n_rec * self.p.record_bytes, offset * PAGE_BYTES),
                )
            )
        out.append(ctx.at(t, self.id, "replay.end", epoch=self.epoch))
        return out

    def _replay_chunk(self, ev: Event, ctx: Ctx) -> list[Event]:
        nbytes = int(ev.payload["bytes"])
        self.mem_bytes = nbytes
        ctx.set_field("lsm.mem_bytes", nbytes)
        ctx.emit(self.id, "wal.replay.chunk", nbytes)
        return []

    def _replay_end(self, ctx: Ctx) -> list[Event]:
        self.memtable = list(self.wal.durable)
        self.recovered_keys = list(self.memtable)
        self.mem_bytes = len(self.memtable) * self.p.record_bytes
        self.state = STATE_UP
        self.recovery_us = ctx.now_us - self.recovery_start_us
        ctx.emit(self.id, "wal.replay.end", len(self.memtable), self.recovery_us)
        ctx.set_field("lsm.mem_bytes", self.mem_bytes)
        ctx.set_field("lsm.state", STATE_UP)
        return []
