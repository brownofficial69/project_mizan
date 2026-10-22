# Phase 1: barrier vs soft penalty on a real model

Question: on Pythia-160M, does a log-barrier hold a constraint at rising optimisation pressure where a soft penalty does not, and at what cost to the task?

## Setup

- Trainable: final LayerNorm weight and bias only (1,536 parameters). Its input activations are cached once, so every objective evaluation is exact but cheap.
- Task: lower the mean next-token NLL on 8 fixed sentences in an unusual, consistent style.
- Constraint: `h(theta) = eps - KL(pi_ref || pi_theta) >= 0`, KL measured on 12 fixed neutral sentences. A trust region. It is **not** an ethical principle and says nothing about harmful content.
- Methods: soft penalty `w*L + lam*max(0, KL-eps)^2` vs barrier `w*L - (1/t) log h`, same L-BFGS optimiser, same starting point (the original weights, where `h = eps`).
- Pressure: `w` in {1, 10, 100, 1000}.
- `eps` rule, fixed before constrained runs: 25% of the KL the unconstrained solution reaches.

## Pass / fail, written in advance

- **Supports the hypothesis:** barrier violation is 0 at every pressure, the penalty violates at high pressure, and the barrier's task NLL is within a reasonable margin of what the penalty reaches while violating.
- **Does not support it:** the barrier diverges, stalls far from the boundary, or pays a large task-loss cost for zero violation. Report that as the finding.
- **Inconclusive:** the penalty also holds the constraint at all pressures (eps too loose, or the 1,536-parameter slice cannot reach it).

## Integrity checks built in

- The cached LayerNorm path is compared against a full model forward at the start (aborts if they disagree) and again on the final solutions.
- Computation is float64 by default so `h` near zero is not float32 rounding noise.

## Limits

One model, one small parameter slice, one synthetic constraint, 8+12 sentences. This tests the mechanism at a real model's scale, not whether it protects anything.

## Run

```
pip install -e ".[model]"
python experiments/phase1/run.py --quick   # smoke test
python experiments/phase1/run.py           # full run, writes results/phase1.json
```
