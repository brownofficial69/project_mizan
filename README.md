# Project MIZAN

A reference implementation of a safety-margin gate and an interior-point optimisation wall for constraining model behaviour. This is a personal research project and a concept demonstration. It is not a working AGI safety system, and it is not peer-reviewed.

Author: Shadman Hossain
Location: Birmingham, United Kingdom
Date: 11 July 2026
License: Creative Commons Zero (CC0 1.0 Universal), public domain

AI Disclosure: AI tools were used to assist with drafting, structure, and code review. The concept and direction are the author's own. The claims below are presented for critique and have not been externally validated.

---

## 1. What This Is and What It Is Not

Read this section before anything else.

**What this is.** A small, self-contained, tested demonstration of two mechanisms. First, an interior-point log-barrier that pulls an optimiser toward an objective while keeping it strictly on the safe side of a hard constraint. Second, a monitoring gate that computes a safety margin from a state vector and flags when the margin goes negative.

**What this is not.** This does not read the internals of a real model, and it cannot detect deception in text. The telemetry in the current code is synthetic and is labelled as such. It is not a detector. It is a test fixture for the gate logic.

**Verdict:** the value here is a correct, honest core that real components can plug into. The headline problems in AGI alignment are not solved by this repository, and it does not claim to solve them.

---

## 2. The Idea

The project explores one hypothesis: that alignment is better enforced as a hard constraint on the optimisation itself than as a preference learned after the fact.

Preference fine-tuning teaches a model what humans rate highly. It is useful, but it is a soft signal, and a strong enough optimisation pressure can find its way around a soft signal. That is the specification-gaming problem.

A hard constraint is different. An interior-point barrier makes the boundary impossible to cross during optimisation, not merely expensive. The optimiser can approach the limit but cannot pass it. Section 4 shows this working.

This is a hypothesis to test, not a settled result. It is presented for critique by people who work on alignment.

---

## 3. Repository Contents

| File | What it actually does |
| :--- | :--- |
| `mizan_core.py` | The tested core. An interior-point log-barrier with a feasibility-preserving line search, and a monitoring gate that computes the safety margin on synthetic telemetry. Runs standalone. |
| `README.md` | This file. |
| `PROPOSAL.md` | A draft research note intended for feedback. It is a draft, not a reviewed paper. |
| `index.html` | A front-end dashboard for adjusting the gate parameters and viewing output. Currently displays demo values. |

---

## 4. The Mathematics

Three pieces, stated plainly.

**The optimisation wall.** To minimise an objective f(theta) subject to a hard constraint h(theta) >= 0, the barrier method minimises:

    phi(theta) = f(theta) - (1/t) * log(h(theta))

The `-log(h)` barrier is self-concordant, which is what lets Newton's method converge cleanly. As the strength t increases, the solution approaches the boundary but never crosses it. The implementation uses a backtracking line search that enforces h(theta) > 0 at every step. An earlier draft used a `1 / h**2` barrier with a full Newton step and no line search. That version overshot the boundary and is not used.

**The safety margin.** The gate computes:

    margin = mu - beta * (sigma * doubt) - tau
    doubt  = entropy + doubt_weight * risk

mu is an alignment read-out from the state. sigma is its spread. entropy is the von Neumann entropy of the state matrix, used as an uncertainty measure. risk is a Monte Carlo robustness estimate. If the margin goes negative, or the risk crosses a threshold, the gate trips.

**Honest notes on the margin.** The state matrix is built from several observation vectors, so it is a mixed state and its entropy is meaningful. A single-vector state is pure and always has zero entropy, so that is not used. beta, tau, and doubt_weight are tunable parameters, not fixed constants. The alignment read-out is a placeholder. Calibrating it against real labelled data is the actual work and has not been done. Nothing here is quantum.

---

## 5. Running It

Prerequisites:

    pip install numpy

Run the core demonstration:

    python mizan_core.py

Expected output. The barrier section prints a parameter approaching the constraint boundary (h stays positive at every step, and "boundary ever crossed" reports False). The gate section prints the margin and its components for two synthetic inputs, and whether the gate tripped.

The current gate trips on both synthetic inputs under the placeholder parameters. That is expected. The parameters and the alignment read-out are placeholders, and the demo is not tuned to produce a pass/fail split, because a split on random synthetic data would not mean anything.

---

## 6. Roadmap and Limitations

What is done: the barrier wall is correct and tested, the gate runs, the state and entropy are built correctly, and there is a `TelemetrySource` interface for a real data source to plug into.

What is not done, stated plainly:

The telemetry is synthetic. A real source that reads per-layer activation statistics from a small open-weights model has not been built yet. That is the next step.

The gate is not calibrated. The alignment read-out and the thresholds are placeholders. Without calibration against labelled data, the gate's output is not a meaningful judgement about any real input.

The gate does not understand text. It computes statistics from a state vector. It has no semantic understanding of an input.

Nothing here has been evaluated against benchmarks or reviewed by other researchers. Treat it as a concept demonstration.

---

## 7. License

This work is dedicated to the public domain under CC0 1.0 Universal. The name, the code, and the equations are free for anyone to use, modify, and build on, including for commercial purposes, without asking permission.

---

## 8. Contact and Contribution

This is an open project. Corrections and critique are welcome, particularly from people working in alignment, optimisation, and information theory. Issues and pull requests are open.
