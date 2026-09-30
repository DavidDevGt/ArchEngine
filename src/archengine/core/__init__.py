"""Modulo core de ArchEngine.

Infraestructura base sin dependencias internas.
"""

from archengine.core.manifest import Manifest, compute_inputs_hash, sha256_bytes, sha256_file
from archengine.core.rng import RNGManager, deterministic_rng
from archengine.core.schema import (
    NodeSpec,
    ProtocolsConfig,
    SceneConfig,
    Topology,
    ValidationError,
    load_protocols,
    load_topology,
    load_yaml_file,
    validate_file,
    validate_protocols_dict,
    validate_scene_dict,
    validate_topology_dict,
)
from archengine.core.timebase import (
    DEFAULT_AUDIO_SAMPLE_RATE,
    DEFAULT_FPS,
    MICROSECONDS_PER_SECOND,
    frame_to_time_us,
    sample_to_time_us,
    seconds_to_time_us,
    sim_to_video,
    time_us_to_frame,
    time_us_to_sample,
    time_us_to_seconds,
    video_to_sim,
)

__all__ = [
    "DEFAULT_AUDIO_SAMPLE_RATE",
    "DEFAULT_FPS",
    "MICROSECONDS_PER_SECOND",
    "Manifest",
    "NodeSpec",
    "ProtocolsConfig",
    "RNGManager",
    "SceneConfig",
    "Topology",
    "ValidationError",
    "compute_inputs_hash",
    "deterministic_rng",
    "frame_to_time_us",
    "load_protocols",
    "load_topology",
    "load_yaml_file",
    "sample_to_time_us",
    "seconds_to_time_us",
    "sha256_bytes",
    "sha256_file",
    "sim_to_video",
    "time_us_to_frame",
    "time_us_to_sample",
    "time_us_to_seconds",
    "validate_file",
    "validate_protocols_dict",
    "validate_scene_dict",
    "validate_topology_dict",
    "video_to_sim",
]
