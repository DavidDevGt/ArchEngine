"""Pruebas unitarias de validacion estricta de esquemas YAML (FR-01, FR-02)."""

from pathlib import Path

import pytest

from archengine.core.schema import (
    ValidationError,
    load_protocols,
    load_topology,
    validate_scene_dict,
    validate_topology_dict,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_load_canonical_protocols_yaml() -> None:
    p = REPO_ROOT / "src" / "archengine" / "data" / "protocols.yaml"
    cfg = load_protocols(p)
    assert cfg.schema_version == 1
    assert cfg.disk_hdd.rpm == 7200
    assert cfg.disk_hdd.avg_seek_us == 8500
    assert cfg.lsm.memtable_bytes == 67_108_864
    assert cfg.lsm.l0_compaction_trigger == 4
    assert cfg.btree.page_bytes == 4096
    assert cfg.btree.fanout == 256
    assert cfg.raft.election_timeout_ms == (150, 300)


def test_load_canonical_topology_yaml() -> None:
    p = REPO_ROOT / "src" / "archengine" / "data" / "topologies" / "lsm_vs_btree.yaml"
    topo = load_topology(p)
    assert topo.schema_version == 1
    assert topo.name == "lsm_vs_btree"
    assert len(topo.nodes) == 2
    assert topo.get_node("db_lsm") is not None
    assert topo.get_node("db_btree") is not None
    assert topo.get_node("db_lsm").capacities["memtable_bytes"] == 67_108_864


def test_topology_validation_rejects_invalid_id() -> None:
    data = {
        "schema_version": 1,
        "name": "test",
        "nodes": [{"id": "DB-Invalid!", "kind": "server_rack", "pos": [0, 0]}],
    }
    with pytest.raises(ValidationError) as exc:
        validate_topology_dict(data)
    assert "nodes[0].id" in exc.value.path


def test_topology_validation_rejects_duplicate_id() -> None:
    data = {
        "schema_version": 1,
        "name": "test",
        "nodes": [
            {"id": "node1", "kind": "server_rack", "pos": [0, 0]},
            {"id": "node1", "kind": "server_rack", "pos": [1, 1]},
        ],
    }
    with pytest.raises(ValidationError) as exc:
        validate_topology_dict(data)
    assert "duplicado" in exc.value.message


def test_topology_validation_rejects_invalid_capacity() -> None:
    data = {
        "schema_version": 1,
        "name": "test",
        "nodes": [
            {"id": "node1", "kind": "server_rack", "pos": [0, 0], "capacities": {"buf": -10}},
        ],
    }
    with pytest.raises(ValidationError) as exc:
        validate_topology_dict(data)
    assert "capacities.buf" in exc.value.path


def test_topology_validation_rejects_nonexistent_edge_node() -> None:
    data = {
        "schema_version": 1,
        "name": "test",
        "nodes": [{"id": "node1", "kind": "server_rack", "pos": [0, 0]}],
        "networks": [
            {"id": "net0", "edges": [{"from": "node1", "to": "node_missing", "latency_us": 100}]}
        ],
    }
    with pytest.raises(ValidationError) as exc:
        validate_topology_dict(data)
    assert "no existe" in exc.value.message


def test_scene_validation() -> None:
    scene_data = {
        "schema_version": 1,
        "id": "ep01_test",
        "video": {"width": 1080, "height": 1920, "fps": 30, "duration_s": 10.0},
        "segments": [
            {"id": "s1", "t": [0.0, 5.0]},
            {"id": "s2", "t": [5.0, 10.0]},
        ],
    }
    scene_cfg = validate_scene_dict(scene_data)
    assert scene_cfg.id == "ep01_test"
    assert len(scene_cfg.segments) == 2


def test_scene_validation_rejects_discontinuous_segments() -> None:
    scene_data = {
        "schema_version": 1,
        "id": "ep01_bad",
        "video": {"width": 1080, "height": 1920, "fps": 30, "duration_s": 10.0},
        "segments": [
            {"id": "s1", "t": [0.0, 4.0]},
            {"id": "s2", "t": [5.0, 10.0]},
        ],
    }
    with pytest.raises(ValidationError) as exc:
        validate_scene_dict(scene_data)
    assert "Discontinuidad" in exc.value.message
