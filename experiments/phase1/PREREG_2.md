# Phase 1, follow-up runs (declared 2026-10-28, before these runs)

## Why

The first full run (`results/phase1.json`, eps-frac 0.25) was **inconclusive**: the unconstrained solution drifted to KL = 1870 nats over 150 iterations, so eps = 467 nats was an enormous trust region. The task reached its loss floor inside it, and the soft penalty never violated the constraint.

## Runs

Both use the same code, model, sentences, optimiser, penalty weight (100), pressures (1, 10, 100, 1000) and t schedule as the first run. Only eps changes.

| Run | eps-frac | eps (approx, nats) | Status |
| --- | --- | --- | --- |
| A | 0.05 | 93.5 | Planned in the original design as the tighter fallback |
| B | 0.002 | 3.7 | **New. Chosen after seeing run 1's results**, because 93 nats is still very loose. Report it as a post-hoc follow-up, not as the original pre-registered test |

Outputs: `results/eps005/phase1.json` and `results/eps0002/phase1.json`. The first run's file is not touched.

## Criteria (same as the original README)

- **Supports the hypothesis:** barrier violation is 0 at every pressure, the penalty violates at high pressure, and the barrier's task NLL is within a reasonable margin of the penalty's.
- **Does not support it:** the barrier diverges, stalls far from the boundary while paying a large task-loss cost, or violates.
- **Inconclusive:** the penalty also holds the constraint everywhere.

"Reasonable margin" is fixed now as: barrier task NLL no more than 0.1 nats above the penalty's at the same pressure.

## Reporting rule

Every run is reported, including inconclusive and negative ones. Run B is labelled post-hoc.
