# MIZAN Phase 1 handover (for another AI tool or collaborator)

Written 2026-10-21. Paste this file, or point the tool at the repo folder, to give it full context.

## Goal
Phase 1 of `PROPOSAL.md` section 6: test whether an interior-point log-barrier holds a constraint on a real small model (Pythia-160M) under rising optimisation pressure, where a soft penalty does not. Phase 2 (real activation telemetry plus gate calibration) follows and is not started.

## What exists
- `mizan/core.py`: `SafetyGate`, scalar `barrier_minimise`, and new `lbfgs_minimise` and `barrier_minimise_nd` (L-BFGS whose line search rejects any step with h <= 0).
- `tests/test_barrier_nd.py`: tests for the vector barrier (2, 8, 32 dims). Full suite: 23 passed.
- `pyproject.toml`: new optional extra `[model]` (torch, transformers).
- `experiments/phase1/run.py`: the experiment. `experiments/phase1/README.md`: design and pass/fail criteria written before results.

## Experiment design
- Trainable: final LayerNorm weight and bias only (1,536 params); its input activations are cached once.
- Task: lower mean next-token NLL on 8 fixed sentences ending in "Banana protocol engaged."
- Constraint: h = eps - KL(pi_ref || pi_theta) >= 0 on 12 fixed neutral sentences. A trust region, not an ethical principle.
- eps rule (fixed in advance): 0.25 x the KL of the unconstrained solution.
- Methods, same optimiser and start: penalty `w*L + 100*max(0, KL-eps)^2` vs barrier `w*L - (1/t)log h`, t in (1, 10, 100). Pressures w in 1, 10, 100, 1000.
- Float64 by default. Integrity check: cached path vs full model forward at start and on final solutions.

## Results so far
- `--quick` smoke test passed. Reference NLL 5.8785, matches the full model. Unconstrained solution: NLL 0.89, KL 25.4, so eps = 6.36 nats (loose). Quick-mode penalty was unconverged (20 iterations), so its comparison with the barrier is meaningless.
- The full run was started in the background; check `experiments/phase1/results/phase1.json`. If that file is absent, the run did not finish.
- Pass/fail criteria are in `experiments/phase1/README.md`. If the penalty never violates eps, the result is "inconclusive", and the next step is a tighter `--eps-frac` run reported separately.

## Reproduce
```
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e ".[model]"
pytest -q
python experiments/phase1/run.py --quick
python experiments/phase1/run.py
```
Windows, Python 3.10.6, torch 2.14.1+cpu, transformers 5.20.2. Set `HF_HUB_DISABLE_SYMLINKS_WARNING=1` to quiet cache warnings.

## Gotchas
- In current transformers use `model.get_output_embeddings()` (no `embed_out`) and `dtype=` not `torch_dtype=`.
- Do not describe results as safety evidence. One model, one slice, one synthetic constraint.
- Honesty rule from the README: state what is not shown, including negative or inconclusive outcomes.

## Next (Phase 2, not started)
`HFActivationTelemetry(TelemetrySource)`, a learned readout argument on `SafetyGate`, a labelled dataset split by source, calibration sweep, and baselines (plain probe, toxicity classifier). Details are in the plan in `PROPOSAL.md` section 6.
