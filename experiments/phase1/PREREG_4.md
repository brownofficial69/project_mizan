# Phase 1, replication runs (declared 2026-10-31, before these runs)

## Why

The w = 1000 re-run (`results/rerun_w1000`) showed the earlier barrier stall was non-convergence. It covered one pressure and one limit. These runs check that the result is not a one-point coincidence.

## Runs (same code, model, sentences, float64, GPU, penalty weight 100, t schedule 1 / 10 / 100, `--max-iter 600`)

| Run | eps (fixed with `--eps`) | Pressures | Output |
| --- | --- | --- | --- |
| C | 1.8049506279 (same as run B and the re-run) | 1, 10, 100 | `results/rerun_lowp` |
| D | **4.0** (new; chosen now, before any result at this value) | 1, 10, 100, 1000 | `results/eps4` |

Run D's eps is a round number picked for being between run B's 1.8 and the loose runs, not tuned to any outcome. Runs execute one after the other on the GPU. Estimated 1.5 hours in total.

## Criteria, fixed now

- A **violation counts as material** if it exceeds 1% of eps (0.018 nats for run C, 0.04 for run D). Smaller overshoots are reported but do not count. (This is added now because run A's 0.0005-nat overshoot on a 93-nat limit should not count as the penalty violating.)
- **Supports the hypothesis (per run):** the barrier never violates at any pressure; the penalty has a material violation at the highest pressure; and the barrier's task NLL is within 0.1 nats of the penalty's at every pressure.
- **Does not support:** the barrier violates, or its NLL exceeds the penalty's by more than 0.1 nats at any pressure.
- **Inconclusive:** the penalty never has a material violation.

## Reporting rule

Report both runs whichever way they go, beside the earlier results. Note that iteration caps (1,800 total per method) may still be reached, so convergence is not claimed.
