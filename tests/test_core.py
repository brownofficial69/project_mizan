import numpy as np
import pytest

from mizan import GateConfig, SafetyGate, barrier_minimise, SyntheticTelemetry, build_state_matrix, von_neumann_entropy, wall_demo


def test_barrier_never_crosses_and_approaches_wall():
    traj = wall_demo()
    assert all(h > 0 for _, _, h in traj)
    hs = [h for _, _, h in traj]
    assert hs == sorted(hs, reverse=True) and hs[-1] < 1e-3


def test_barrier_rejects_infeasible_start():
    with pytest.raises(ValueError):
        barrier_minimise(lambda x: x, lambda x: 1.0, lambda x: 1.0, lambda x: -x, lambda x: -1.0, theta0=1.0)


def test_state_matrix_is_trace_one_psd():
    rho = build_state_matrix(np.random.default_rng(1).normal(size=(8, 4)))
    assert np.isclose(np.trace(rho), 1.0)
    assert np.all(np.linalg.eigvalsh(rho) > -1e-12)


def test_single_vector_is_pure_zero_entropy():
    rho = build_state_matrix(np.array([[1.0, 2.0, 3.0, 4.0]]))
    assert von_neumann_entropy(rho) == pytest.approx(0.0, abs=1e-6)


def test_zero_observations_give_maximally_mixed_state():
    rho = build_state_matrix(np.zeros((3, 4)))
    assert von_neumann_entropy(rho) == pytest.approx(np.log(4))


def test_synthetic_telemetry_is_deterministic():
    a = SyntheticTelemetry().read("x")
    assert np.array_equal(a, SyntheticTelemetry().read("x"))
    assert not np.array_equal(a, SyntheticTelemetry().read("y"))


def test_gate_is_deterministic_and_matches_formula():
    obs = SyntheticTelemetry().read("sample-input-A")
    g = SafetyGate()
    r1, r2 = g.evaluate(obs), g.evaluate(obs)
    assert r1 == r2
    c = g.config
    assert r1["margin"] == pytest.approx(
        r1["alignment_mu"] - c.beta * r1["variance_sigma"] * r1["doubt"] - c.tau)
    assert r1["doubt"] == pytest.approx(r1["entropy"] + c.doubt_weight * r1["robustness_risk"])


def test_gate_passes_when_aligned_and_trips_when_not():
    # all mass on aligned coordinates, low spread -> pass with a lenient floor
    aligned = np.array([[1.0, 1.0, 1.0, 0.0]] * 8)
    lenient = SafetyGate(GateConfig(tau=0.0))
    assert not lenient.evaluate(aligned)["gate_tripped"]
    # all mass on the unaligned coordinate -> trip
    bad = np.array([[0.0, 0.0, 0.0, 1.0]] * 8)
    assert lenient.evaluate(bad)["gate_tripped"]


def test_gate_rejects_wrong_dim_and_nonfinite():
    g = SafetyGate()
    with pytest.raises(ValueError):
        g.evaluate(np.ones((3, 5)))
    with pytest.raises(ValueError):
        g.evaluate(np.array([[np.nan, 0, 0, 0]]))
