"""Substreams pseudoaleatorios deterministas PCG64 (ADR-0004).

Garantiza aislamiento e independencia estadistica entre subsistemas (simulacion,
red, grano de post-proceso, audio), evitando que cambios en un componente alteren
la secuencia de numeros aleatorios de los demas.
"""

from __future__ import annotations

import hashlib
import struct
from typing import Final

import numpy as np

# Constante de 32 bits para operaciones de desbordamiento seguro
_UINT32_MASK: Final[int] = 0xFFFFFFFF


def _name_to_entropy_words(name: str) -> list[int]:
    """Genera 4 palabras enteras de 32 bits a partir de un nombre de substream.

    Utiliza BLAKE2b con salida fija de 16 bytes para garantizar independencia
    de la semilla global y determinismo estricto entre plataformas y ejecuciones
    (a diferencia de hash(str) de Python que incluye aleatorizacion de proceso).
    """
    digest = hashlib.blake2b(name.encode("utf-8"), digest_size=16).digest()
    words = struct.unpack(">4I", digest)
    return list(words)


def deterministic_rng(seed: int, name: str) -> np.random.Generator:
    """Crea un generador NumPy determinista aislado basado en PCG64 y SeedSequence.

    Args:
        seed: Semilla global entera.
        name: Identificador del componente o substream (e.g. 'grain', 'network.db1').

    Returns:
        np.random.Generator configurado con PCG64.
    """
    name_words = _name_to_entropy_words(name)
    entropy: list[int] = [seed & _UINT32_MASK, *name_words]
    seed_seq = np.random.SeedSequence(entropy=entropy)
    bit_gen = np.random.PCG64(seed_seq)
    return np.random.Generator(bit_gen)


class RNGManager:
    """Administrador de flujos pseudoaleatorios con semilla central."""

    def __init__(self, seed: int) -> None:
        self._seed = seed

    @property
    def seed(self) -> int:
        return self._seed

    def stream(self, name: str) -> np.random.Generator:
        """Obtiene un generador determinista para el nombre especificado."""
        return deterministic_rng(self._seed, name)

    def spawn(self, name: str, index: int = 0) -> np.random.Generator:
        """Obtiene un generador determinista para una instancia indexada."""
        return deterministic_rng(self._seed, f"{name}[{index}]")
