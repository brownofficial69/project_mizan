"""Telemetry sources. Only a synthetic source exists; it is not a detector."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod

import numpy as np


class TelemetrySource(ABC):
    """Plug point for real activation statistics from an open-weights model."""

    @abstractmethod
    def read(self, context: str) -> np.ndarray:
        """Return an array of shape (n_observations, dim)."""


class SyntheticTelemetry(TelemetrySource):
    """Deterministic pseudo-random observations seeded from the context.

    Uses SHA-256 (not Python's per-process randomised hash) so results are
    reproducible across runs and across workers.
    """

    def __init__(self, dim: int = 4, n_obs: int = 8):
        self.dim = dim
        self.n_obs = n_obs

    def read(self, context: str) -> np.ndarray:
        seed = int.from_bytes(hashlib.sha256(context.encode("utf-8")).digest()[:8], "big")
        return np.random.default_rng(seed).normal(0.0, 1.0, (self.n_obs, self.dim))
