"""Vector barrier and L-BFGS tests across 2, 8 and 32 dimensions.

Merged from two sources: the original ball-constraint tests, and the scenario
suite from the argon-assisted bundle (half-space, trust region, rising
pressure, tightening with t, soft-penalty contrast), ported to this API.
"""

import numpy as np
import pytest

from mizan import barrier_minimise_nd, lbfgs_minimise

DIMS = [2, 8, 32]


def _scaled(f, grad_f, w):
    """Optimisation pressure w multiplies the task objective."""
    return (lambda x: w * f(x)), (lambda x: w * grad_f(x))


def _ball_problem(n, seed=0, target_norm=3.0):
    """min ||x - target||^2 s.t. ||x||^2 <= 1, with the target outside the ball."""
    rng = np.random.default_rng(seed)
    target = rng.normal(size=n)
    target *= target_norm / np.linalg.norm(target)
    f = lambda x: float(np.sum((x - target) ** 2))
    grad_f = lambda x: 2.0 * (x - target)
    h = lambda x: 1.0 - float(x @ x)
    grad_h = lambda x: -2.0 * x
    return target, f, grad_f, h, grad_h


# --- L-BFGS -----------------------------------------------------------------

@pytest.mark.parametrize("n", DIMS)
def test_lbfgs_solves_unconstrained_quadratic(n):
    target = np.arange(1, n + 1, dtype=float) * 0.25
    scales = np.linspace(1.0, 5.0, n)
    x, _ = lbfgs_minimise(lambda x: 0.5 * float(np.sum(scales * (x - target) ** 2)),
                          lambda x: scales * (x - target), np.zeros(n), max_iter=150)
    assert np.allclose(x, target, atol=1e-6)


def test_lbfgs_solves_ill_conditioned_quadratic():
    A = np.diag([1.0, 10.0, 100.0])
    b = np.array([1.0, 2.0, 3.0])
    x, _ = lbfgs_minimise(lambda x: 0.5 * x @ A @ x - b @ x, lambda x: A @ x - b, np.zeros(3))
    assert np.allclose(x, np.linalg.solve(A, b), atol=1e-6)


def test_lbfgs_feasibility_guard_rejects_steps_outside_region():
    # unconstrained minimum at 5; with the region x < 2 the iterate may never leave it
    x, _ = lbfgs_minimise(lambda x: float(np.sum((x - 5.0) ** 2)), lambda x: 2.0 * (x - 5.0),
                          np.array([0.0]), feasible=lambda x: bool(x[0] < 2.0))
    assert x[0] < 2.0


# --- Barrier: feasibility and approach to the optimum ------------------------

@pytest.mark.parametrize("n", DIMS)
def test_nd_barrier_never_leaves_feasible_set_and_nears_optimum(n):
    target, f, grad_f, h, grad_h = _ball_problem(n)
    res = barrier_minimise_nd(f, grad_f, h, grad_h, np.zeros(n))
    assert res["min_h"] > 0
    assert all(row["h"] > 0 for row in res["trajectory"])
    optimum = target / np.linalg.norm(target)
    assert np.linalg.norm(res["theta"] - optimum) < 1e-2
    hs = [row["h"] for row in res["trajectory"]]
    assert hs == sorted(hs, reverse=True)


@pytest.mark.parametrize("n", DIMS)
def test_barrier_halfspace_constraint(n):
    # target at 3 in every coordinate, constraint sum(x) <= 1
    target = np.full(n, 3.0)
    ones = np.ones(n)
    f, grad_f = _scaled(lambda x: 0.5 * float((x - target) @ (x - target)), lambda x: x - target, 10.0)
    res = barrier_minimise_nd(f, grad_f, lambda x: 1.0 - float(ones @ x), lambda x: -ones, np.zeros(n),
                              t_schedule=(20.0,))
    total = float(np.sum(res["theta"]))
    assert res["min_h"] > 0 and 0.90 < total < 1.0


@pytest.mark.parametrize("n", DIMS)
def test_barrier_norm_ball_trust_region(n):
    rng = np.random.default_rng(42 + n)
    c = rng.normal(size=n)
    c /= np.linalg.norm(c)
    radius_sq = 0.64
    f, grad_f = _scaled(lambda x: -float(c @ x) + 0.05 * float(x @ x), lambda x: -c + 0.10 * x, 50.0)
    res = barrier_minimise_nd(f, grad_f, lambda x: radius_sq - float(x @ x), lambda x: -2.0 * x,
                              np.zeros(n), t_schedule=(10.0,))
    assert res["min_h"] > 0 and float(res["theta"] @ res["theta"]) < radius_sq


@pytest.mark.parametrize("n", DIMS)
@pytest.mark.parametrize("w", [1.0, 100.0, 1000.0, 1e5])
def test_barrier_holds_under_rising_pressure(n, w):
    direction = np.ones(n) / np.sqrt(n)
    far = 10.0 * direction
    eps = 0.5
    f, grad_f = _scaled(lambda x: 0.5 * float((x - far) @ (x - far)), lambda x: x - far, w)
    res = barrier_minimise_nd(f, grad_f, lambda x: eps - 0.5 * float(x @ x), lambda x: -x, np.zeros(n),
                              t_schedule=(10.0,))
    assert res["min_h"] > 0, f"constraint violated at n={n}, w={w}"
    assert all(row["h"] > 0 for row in res["trajectory"])


@pytest.mark.parametrize("n", DIMS)
def test_barrier_tightens_toward_boundary_as_t_grows(n):
    target = np.full(n, 4.0)
    f, grad_f = _scaled(lambda x: 0.5 * float((x - target) @ (x - target)), lambda x: x - target, 10.0)
    h, grad_h = (lambda x: 1.0 - 0.5 * float(x @ x)), (lambda x: -x)
    slacks = [barrier_minimise_nd(f, grad_f, h, grad_h, np.zeros(n), t_schedule=(t,))["trajectory"][-1]["h"]
              for t in (1.0, 10.0, 100.0)]
    assert slacks[0] > slacks[1] > slacks[2] > 0.0


# --- Contrast: soft penalty versus barrier -----------------------------------

@pytest.mark.parametrize("n", DIMS)
def test_soft_penalty_violates_where_barrier_holds(n):
    target = np.full(n, 5.0)
    eps, w, lam = 0.5, 1000.0, 100.0
    task = lambda x: 0.5 * float((x - target) @ (x - target))
    grad_task = lambda x: x - target
    kl = lambda x: 0.5 * float(x @ x)  # divergence proxy
    h, grad_h = (lambda x: eps - kl(x)), (lambda x: -x)

    def penalty(x):
        return w * task(x) + lam * max(0.0, kl(x) - eps) ** 2

    def grad_penalty(x):
        return w * grad_task(x) + 2.0 * lam * max(0.0, kl(x) - eps) * x

    x_pen, _ = lbfgs_minimise(penalty, grad_penalty, np.zeros(n), max_iter=300)
    f, grad_f = _scaled(task, grad_task, w)
    barrier = barrier_minimise_nd(f, grad_f, h, grad_h, np.zeros(n))

    assert h(x_pen) < 0.0, "soft penalty should overshoot at high pressure"
    assert barrier["min_h"] > 0.0, "log-barrier must hold the constraint"


# --- Input validation --------------------------------------------------------

def test_nd_barrier_rejects_infeasible_start():
    _, f, grad_f, h, grad_h = _ball_problem(4)
    with pytest.raises(ValueError, match="strictly feasible"):
        barrier_minimise_nd(f, grad_f, h, grad_h, np.ones(4) * 2.0)


def test_nd_barrier_rejects_start_on_the_boundary():
    _, f, grad_f, h, grad_h = _ball_problem(4)
    with pytest.raises(ValueError):
        barrier_minimise_nd(f, grad_f, h, grad_h, np.array([1.0, 0.0, 0.0, 0.0]))


@pytest.mark.parametrize("bad", [0.0, -1.0])
def test_nd_barrier_rejects_nonpositive_t(bad):
    _, f, grad_f, h, grad_h = _ball_problem(2)
    with pytest.raises(ValueError, match="t must be > 0"):
        barrier_minimise_nd(f, grad_f, h, grad_h, np.zeros(2), t_schedule=(1.0, bad))
