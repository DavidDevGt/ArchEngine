"""`archengine simulate` y determinismo de la simulacion completa del episodio."""

from __future__ import annotations

from pathlib import Path

import pytest

from archengine.cli import main
from archengine.scenes import ep01_lsm_vs_btree as ep
from archengine.simulation.trace import Trace

pytestmark = pytest.mark.integration


def test_simulate_dump_roundtrip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["simulate", "ep01", "--dump", str(tmp_path / "trace.npz")])
    assert rc == 0
    assert "eventos" in capsys.readouterr().out
    lsm = Trace.load(tmp_path / "trace.lsm.npz")
    assert lsm.first("lsm.flush.start") is not None


def test_full_episode_simulation_is_deterministic() -> None:
    a = ep._simulate(42)
    b = ep._simulate(42)
    assert a[0].trace_hash() == b[0].trace_hash()
    assert a[1].trace_hash() == b[1].trace_hash()
    c = ep._simulate(43)
    assert c[0].trace_hash() != a[0].trace_hash()
