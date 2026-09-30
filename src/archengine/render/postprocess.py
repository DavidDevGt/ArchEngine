"""Filtros de lente de post-proceso: viñeta y grano determinista (FR-15, docs/03 §9).

Aplica atenuacion radial en espacio matricial y grano filmico analitico determinista
basado en substreams de PCG64 sobre el buffer de pixeles RGB24.
"""

from __future__ import annotations

import numpy as np

from archengine.core.rng import deterministic_rng


class PostProcessor:
    """Procesador de imagen post-raster con garantia de determinismo frame a frame."""

    def __init__(
        self,
        width: int = 1080,
        height: int = 1920,
        seed: int = 42,
        vignette_strength: float = 0.35,
        grain_intensity: float = 5.0,
        num_grain_tiles: int = 8,
    ) -> None:
        self.width = width
        self.height = height
        self.vignette_strength = vignette_strength
        self.grain_intensity = grain_intensity
        self.num_grain_tiles = max(1, num_grain_tiles)

        # 1. Mascara precomputada de viñeta matricial (docs/03 §9)
        y, x = np.ogrid[:height, :width]
        cx, cy = width * 0.5, height * 0.5
        r2 = ((x - cx) / cx) ** 2 + ((y - cy) / cy) ** 2
        # Normalizado para decaer suavemente hacia las esquinas
        mask_float = np.clip(1.0 - vignette_strength * (r2 / 2.0), 0.0, 1.0)
        self._vignette_mask_u8 = (mask_float * 255.0).astype(np.uint8)[:, :, np.newaxis]

        # 2. Pool de tiles de grano analitico determinista (ADR-0004)
        rng = deterministic_rng(seed=seed, name="grain")
        self._grain_tiles: list[np.ndarray] = []
        bound = max(1, round(grain_intensity))

        for _ in range(self.num_grain_tiles):
            # Ruido simetrico entero centrado en 0
            tile = rng.integers(-bound, bound + 1, size=(height, width, 1), dtype=np.int8)
            self._grain_tiles.append(tile)

        # Buffer temporal de calculo
        self._tmp_u16: np.ndarray | None = None
        self._temp_i16 = np.empty((height, width, 3), dtype=np.int16)

    def apply(self, buffer: np.ndarray, k: int = 0) -> np.ndarray:
        """Aplica la viñeta y el grano filmico correspondiente al cuadro k.

        Args:
            buffer: Array uint8 con forma (height, width, 3).
            k: Indice entero de cuadro de video.

        Returns:
            Buffer procesado con viñeta y grano en formato uint8.
        """
        # 1. Viñeta multiplicativa en uint16 (255*255 < 65536: sin desbordamiento, sin int32)
        if self._tmp_u16 is None:
            self._tmp_u16 = np.empty((self.height, self.width, 3), dtype=np.uint16)
        np.multiply(buffer, self._vignette_mask_u8, out=self._tmp_u16, dtype=np.uint16)
        np.right_shift(self._tmp_u16, 8, out=self._tmp_u16)
        self._temp_i16 = self._tmp_u16.view(np.int16)

        # 2. Seleccion determinista de grano por cuadro k (Knuth multiplicative hash)
        tile_idx = (k * 2654435761) % self.num_grain_tiles
        grain_tile = self._grain_tiles[tile_idx]

        np.add(self._temp_i16, grain_tile, out=self._temp_i16)
        np.clip(self._temp_i16, 0, 255, out=self._temp_i16)

        return self._temp_i16.astype(np.uint8)
