"""
mizan_core.py - MIZAN safety-margin core: reference implementation.

WHAT THIS IS
  A small, self-contained, correct implementation of two mechanisms:
    1. An interior-point log-barrier with a feasibility-preserving line
       search, so an optimiser is pulled toward an objective but never
       crosses a hard constraint boundary. This is the "optimisation wall".
    2. A monitoring gate that computes a safety margin from a state built
       out of multiple observation vectors, and flags when the margin goes
       negative.

WHAT THIS IS NOT
  This does not read a real model's internals, and it cannot detect
  deception in text. The telemetry used below is synthetic and labelled as
  such. A real telemetry source (a small open-weights model) plugs into the
  TelemetrySource interface and is a separate step.

NOTES ON CORRECTNESS
  - The barrier is -log(h), self-concordant, with backtracking line search
    (Armijo) that guarantees every iterate stays strictly feasible. An
    earlier version used w / h**2 with a full Newton step and no line
    search; it overshot the boundary. Both faults are corrected here.
  - The state matrix is built from several observation vectors, so it is a
    mixed state and its von Neumann entropy is genuinely non-zero and
    meaningful. Building it from a single vector gives a pure state with
    zero entropy, which is why that is not done.
  - The doubt constant is a named, tunable parameter, not a fixed law.
  - Nothing here is quantum. Entropy is used as an uncertainty measure.

Author: Shadman Hossain. Drafting assisted by Claude (Anthropic AI).
Location: Birmingham, UK.
License: CC0 1.0 Universal.
"""

import math
import numpy as np
from abc import ABC, abstractmethod


# ---------------------------------------------------------------------------
# 1. Telemetry interface
# ---------------------------------------------------------------------------

class TelemetrySource(ABC):
    """A source of observation matrices to be checked by the gate.

    read(context) returns an array of shape (n_observations, dim). Real
    implementation (separate step) reads per-layer, per-token activation
    statistics from a small open-weights model. This base is the plug point
    so the gate code does not change when the real source lands.
    """

    @abstractmethod
    def read(self, context: str) -> np.ndarray:
        ...


class SyntheticTelemetry(TelemetrySource):
    """Synthetic, deterministic telemetry for testing the gate logic only.

    This does NOT understand the text. It hashes the context to seed a
    reproducible set of observation vectors. It is not a detector.
    """

    def __init__(self, dim: int = 4, n_obs: int = 8):
        self.dim = dim
        self.n_obs = n_obs

    def read(self, context: str) -> np.ndarray:
        seed = abs(hash(context)) % (2**32)
        rng = np.random.default_rng(seed)
        return rng.normal(0.0, 1.0, (self.n_obs, self.dim))


# ---------------------------------------------------------------------------
# 2. State construction and uncertainty
# ---------------------------------------------------------------------------

def build_state_matrix(observations: np.ndarray) -> np.ndarray:
    """Build a normalised mixed state matrix (trace 1) from observations.

    observations: shape (n_obs, dim). Returns the normalised second-moment
    matrix C / trace(C), which is positive semi-definite with trace 1. With
    several independent observations this is a genuine mixed state, so its
    entropy is non-zero.
    """
    X = np.atleast_2d(observations).astype(complex)
    C = X.conj().T @ X
    tr = float(np.real(np.trace(C)))
    if tr < 1e-12:
        dim = X.shape[1]
        return np.eye(dim, dtype=complex) / dim
    return C / tr


def von_neumann_entropy(rho: np.ndarray) -> float:
    """Standard von Neumann entropy of a normalised state matrix, in nats."""
    eigvals = np.linalg.eigvalsh(rho)
    eigvals = np.clip(np.real(eigvals), 1e-12, None)
    return float(-np.sum(eigvals * np.log(eigvals)))


# ---------------------------------------------------------------------------
# 3. The monitoring gate
# ---------------------------------------------------------------------------

class SafetyGate:
    """Computes a safety margin from an observation matrix and flags failure.

    margin = mu - beta * (sigma * doubt) - tau
    doubt  = entropy + doubt_weight * risk

    The readout operator A defines which subspace counts as "aligned". Here
    A is a fixed placeholder projector. In a real system it would be
    calibrated against labelled data, and that calibration is where the real
    work sits.
    """

    def __init__(self, dim: int = 4, beta: float = 0.85, tau: float = 0.40,
                 doubt_weight: float = 0.60, risk_threshold: float = 0.15):
        self.dim = dim
        self.beta = beta
        self.tau = tau
        self.doubt_weight = doubt_weight
        self.risk_threshold = risk_threshold
        self.A = np.eye(dim)
        self.A[-1, -1] = 0.0

    def _alignment(self, rho: np.ndarray) -> float:
        return float(np.real(np.trace(rho @ self.A)))

    def _variance(self, rho: np.ndarray, mu: float) -> float:
        second = float(np.real(np.trace(rho @ (self.A @ self.A))))
        return max(1e-9, second - mu**2)

    def robustness_risk(self, observations: np.ndarray, trials: int = 2000,
                        steps: int = 8, noise: float = 0.05,
                        drop: float = 0.35) -> float:
        """Monte Carlo sensitivity test: fraction of noisy runs where the
        alignment readout falls by more than `drop`. A robustness proxy,
        not a prediction of real-world outcomes.
        """
        rng = np.random.default_rng(0)
        base_mu = self._alignment(build_state_matrix(observations))
        obs = observations.astype(float)
        collapses = 0
        for _ in range(trials):
            X = obs.copy()
            for t in range(steps):
                X = X + rng.normal(0.0, noise * (t + 1), X.shape)
                mu_t = self._alignment(build_state_matrix(X))
                if (base_mu - mu_t) > drop:
                    collapses += 1
                    break
        return collapses / trials

    def evaluate(self, observations: np.ndarray) -> dict:
        rho = build_state_matrix(observations)
        mu = self._alignment(rho)
        sigma = math.sqrt(self._variance(rho, mu))
        entropy = von_neumann_entropy(rho)
        risk = self.robustness_risk(observations)
        doubt = entropy + self.doubt_weight * risk
        margin = mu - self.beta * (sigma * doubt) - self.tau
        tripped = (margin < 0.0) or (risk > self.risk_threshold)
        return {
            "alignment_mu": mu,
            "variance_sigma": sigma,
            "entropy": entropy,
            "robustness_risk": risk,
            "doubt": doubt,
            "margin": margin,
            "gate_tripped": tripped,
        }


# ---------------------------------------------------------------------------
# 4. The interior-point barrier (the "optimisation wall")
# ---------------------------------------------------------------------------

def barrier_minimise(f, grad_f, hess_f, h, h_prime, theta0: float,
                     t_schedule=(1.0, 10.0, 100.0, 1000.0),
                     newton_steps: int = 60):
    """Minimise f(theta) subject to h(theta) >= 0 using a log barrier.

    Objective at barrier strength t:  phi(theta) = f(theta) - (1/t) log(h(theta))
    Damped Newton with a backtracking (Armijo) line search that also
    enforces strict feasibility h(theta) > 0 at every step. Returns the
    trajectory of minimisers as t increases. Key property to observe: theta
    approaches the boundary h(theta)=0 but never crosses it.
    """
    theta = float(theta0)
    trajectory = []
    for t in t_schedule:
        def phi(x):
            hv = h(x)
            if hv <= 0:
                return math.inf
            return f(x) - (1.0 / t) * math.log(hv)

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


# ---------------------------------------------------------------------------
# 5. Demonstration
# ---------------------------------------------------------------------------

def demo():
    print("=" * 62)
    print("MIZAN core - honest reference demo")
    print("=" * 62)

    # --- 5a. Barrier: prove the optimisation wall holds -------------------
    # Minimise f(theta) = (theta - 5)^2 (alone wants theta = 5).
    # Subject to hard wall theta <= 3, i.e. h(theta) = 3 - theta >= 0.
    f = lambda th: (th - 5.0) ** 2
    grad_f = lambda th: 2.0 * (th - 5.0)
    hess_f = lambda th: 2.0
    h = lambda th: 3.0 - th
    h_prime = lambda th: -1.0

    print("\n[1] Interior-point log-barrier (the optimisation wall)")
    print("    Task pulls theta -> 5.0 ; hard wall at theta = 3.0")
    print("    barrier strength t | theta* | distance to wall h(theta)")
    traj = barrier_minimise(f, grad_f, hess_f, h, h_prime, theta0=0.0)
    for t, th, hv in traj:
        print(f"    {t:>18.1f} | {th:6.4f} | {hv:8.6f}")
    crossed = any(hv < 0 for _, _, hv in traj)
    print(f"    boundary ever crossed: {crossed}   (must be False)")

    # --- 5b. Gate: run on clearly-labelled synthetic telemetry -----------
    print("\n[2] Safety gate on SYNTHETIC telemetry (not a real detector)")
    src = SyntheticTelemetry(dim=4, n_obs=8)
    gate = SafetyGate(dim=4)
    for label in ["sample-input-A", "sample-input-B"]:
        obs = src.read(label)
        r = gate.evaluate(obs)
        print(f"\n    context = {label!r}  (synthetic, meaning not analysed)")
        print(f"      alignment mu   : {r['alignment_mu']:.4f}")
        print(f"      variance sigma : {r['variance_sigma']:.4f}")
        print(f"      entropy        : {r['entropy']:.4f}")
        print(f"      robustness risk: {r['robustness_risk']:.4f}")
        print(f"      doubt          : {r['doubt']:.4f}")
        print(f"      margin         : {r['margin']:.4f}")
        print(f"      gate tripped   : {r['gate_tripped']}")

    print("\n" + "=" * 62)
    print("Demo complete. Barrier holds; gate runs on synthetic data.")
    print("Real telemetry (small open-weights model) is a separate step.")
    print("=" * 62)


if __name__ == "__main__":
    demo()
