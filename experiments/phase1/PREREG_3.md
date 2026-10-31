# Phase 1, re-run of one point (declared 2026-10-31, before the run)

## Why

In run B (eps = 1.8049506 nats, GPU, post-hoc) every method used its full iteration cap (150 per barrier strength, 450 in total). At pressure w = 1000 the barrier ended with a task NLL of 1.5652 and a slack of 7e-9, against a penalty NLL of 0.1006. At lower pressures the barrier reached about 0.13 at similar KL. This looks like an optimiser that did not converge, not a real cost of the constraint. This run tests that explanation.

## Change (the only one)

`--max-iter` 150 -> 600 (so up to 1,800 iterations in total per method). Everything else is identical to run B: model, sentences, float64, GPU, penalty weight 100, t schedule (1, 10, 100), pressure 1000.

eps is fixed with the new `--eps` option at **1.8049506279** so it matches run B exactly. (The fraction rule would give a different eps, because the unconstrained solve depends on `--max-iter` and on the device.)

## Criteria

- **Explains the stall (optimiser failure):** barrier task NLL within 0.1 nats of the penalty's at w = 1000, with no violation. Then the pre-declared cost margin is met and the run B shortfall is attributed to non-convergence.
- **Does not:** barrier NLL still more than 0.1 nats above the penalty's, or the barrier violates. Then the cost at high pressure is real for this method and setup, and is reported as a limitation.
- Either way: report it, and keep run B's original numbers beside it.
