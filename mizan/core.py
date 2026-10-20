"""Core MIZAN mechanisms: the safety gate and the interior-point barrier.

Nothing here reads a real model. The gate computes statistics on whatever
observation matrix it is given; calibration against labelled data has not
been done (see README section 6).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict

import numpy as np


def build_state_matrix(observations: np.ndarray) -> np.ndarray:
    """Normalised second-moment matrix C / trace(C) (PSD, trace 1)."""
    X = np.atleast_2d(observations).astype(float)
    C = X.T @ X
    tr = float(np.trace(C))
    if tr < 1e-12:
        dim = X.shape[1]
        return np.eye(dim) / dim
    return C / tr


def von_neumann_entropy(rho: np.ndarray) -> float:
    """Von Neumann entropy of a normalised state matrix, in nats."""
    eigvals = np.clip(np.linalg.eigvalsh(rho), 1e-12, None)
    return float(-np.sum(eigvals * np.log(eigvals)))


@dataclass(frozen=True)
class GateConfig:
    dim: int = 4
    beta: float = 0.85
    tau: float = 0.40
    doubt_weight: float = 0.60
    risk_threshold: float = 0.15
    trials: int = 2000
    steps: int = 8
    noise: float = 0.05
    drop: float = 0.35
    seed: int = 0


class SafetyGate:
    """margin = mu - beta * (sigma * doubt) - tau;  doubt = entropy + w * risk.

    The readout operator A is a fixed diagonal placeholder projector that
    treats the last coordinate as "unaligned". It is not calibrated.
    """

    def __init__(self, config: GateConfig | None = None):
        self.config = config or GateConfig()
        a = np.ones(self.config.dim)
        a[-1] = 0.0
        self._a = a  # diagonal of A

    def _alignment(self, rho: np.ndarray) -> float:
        return float(np.sum(np.diag(rho) * self._a))

    def robustness_risk(self, observations: np.ndarray) -> float:
        """Fraction of noisy random walks where the readout drops by > `drop`.

        Vectorised across trials. A robustness proxy, not a prediction.
        """
        c = self.config
        rng = np.random.default_rng(c.seed)
        obs = np.asarray(observations, dtype=float)
        base_mu = self._alignment(build_state_matrix(obs))
        X = np.broadcast_to(obs, (c.trials,) + obs.shape).copy()
        collapsed = np.zeros(c.trials, dtype=bool)
        for t in range(c.steps):
            X += rng.normal(0.0, c.noise * (t + 1), X.shape)
            sq = np.sum(X * X, axis=1)  # (trials, dim): diagonal of X^T X
            tot = sq.sum(axis=1)
            mu_t = (sq * self._a).sum(axis=1) / np.maximum(tot, 1e-12)
            collapsed |= (base_mu - mu_t) > c.drop
        return float(collapsed.mean())

    def evaluate(self, observations: np.ndarray) -> dict:
        c = self.config
        obs = np.atleast_2d(np.asarray(observations, dtype=float))
        if obs.shape[1] != c.dim:
            raise ValueError(f"expected observations with dim={c.dim}, got {obs.shape[1]}")
        if not np.all(np.isfinite(obs)):
            raise ValueError("observations must be finite")
        rho = build_state_matrix(obs)
        mu = self._alignment(rho)
        sigma = math.sqrt(max(1e-9, float(np.sum(np.diag(rho) * self._a**2)) - mu**2))
        entropy = von_neumann_entropy(rho)
        risk = self.robustness_risk(obs)
        doubt = entropy + c.doubt_weight * risk
        margin = mu - c.beta * (sigma * doubt) - c.tau
        return {
            "alignment_mu": mu,
            "variance_sigma": sigma,
            "entropy": entropy,
            "robustness_risk": risk,
            "doubt": doubt,
            "margin": margin,
            "gate_tripped": bool(margin < 0.0 or risk > c.risk_threshold),
        }

    def config_dict(self) -> dict:
        return asdict(self.config)


def barrier_minimise(f, grad_f, hess_f, h, h_prime, theta0: float,
                     t_schedule=(1.0, 10.0, 100.0, 1000.0),
                     newton_steps: int = 60):
    """Minimise f(theta) s.t. h(theta) >= 0 with a log barrier.

    Damped Newton with a backtracking (Armijo) line search that also enforces
    strict feasibility at every step. Returns [(t, theta, h(theta)), ...].
    """
    if h(theta0) <= 0:
        raise ValueError("theta0 must be strictly feasible (h(theta0) > 0)")
    theta = float(theta0)
    trajectory = []
    for t in t_schedule:
        def phi(x):
            hv = h(x)
            return math.inf if hv <= 0 else f(x) - (1.0 / t) * math.log(hv)

        for _ in range(newton_steps):
            hv = h(theta)
            g = grad_f(theta) - (1.0 / t) * (h_prime(theta) / hv)
            H = hess_f(theta) + (1.0 / t) * (h_prime(theta) ** 2) / (hv ** 2)
            step = g / H
            gstep = g * step
            s = 1.0
            phi0 = phi(theta)
            while s > 1e-14:
                xn = theta - s * step
                if h(xn) > 1e-12 and phi(xn) <= phi0 - 1e-4 * s * gstep:
                    break
                s *= 0.5
            theta = theta - s * step
            if abs(s * step) < 1e-12:
                break
        trajectory.append((t, theta, h(theta)))
    return trajectory


def wall_demo(t_schedule=(1.0, 10.0, 100.0, 1000.0), target: float = 5.0, wall: float = 3.0):
    """The README demo problem: pull toward `target`, hard wall at `wall`."""
    return barrier_minimise(
        lambda th: (th - target) ** 2,
        lambda th: 2.0 * (th - target),
        lambda th: 2.0,
        lambda th: wall - th,
        lambda th: -1.0,
        theta0=wall - 3.0,
        t_schedule=t_schedule,
    )
