# Research Note: Hard Constraint Enforcement via Interior-Point Barriers

A request for comments on one idea in alignment, backed by a small tested reference implementation.

Author: Shadman Hossain
Location: Birmingham, United Kingdom
Date: 11 July 2026
License: Creative Commons Zero (CC0 1.0 Universal), public domain
Status: Early-stage concept with a working core. Not peer-reviewed. Not a finished system.

AI Disclosure: AI tools were used to assist with drafting, structure, and code review. The concept and direction are the author's own. Everything below is presented for critique. Claims of what the code does are limited to what has actually been tested, and the open problems are stated plainly.

---

## 1. What This Note Is

This is a research note, not a pitch. It sets out one question, explains the mechanism behind it, describes a small reference implementation that has been built and tested, and lists honestly what is not solved. The aim is feedback from people who work on alignment, optimisation, and information theory.

It does not propose that any lab commit resources. It asks whether the idea is worth pursuing, and where it is wrong.

---

## 2. The Question

Most current alignment methods, including RLHF and DPO, teach a model what humans rate highly. That is a soft signal added after or alongside the main objective. A strong enough optimisation pressure can route around a soft signal, which is the specification-gaming problem.

The question this note raises is narrow and testable:

Can a hard constraint, enforced inside the optimisation itself through an interior-point barrier, keep a model on the safe side of a defined boundary more reliably than a soft penalty does, and does that property hold as the model scales.

This is a hypothesis. It is not claimed as a result.

---

## 3. Mechanism

The proposal is to add an interior-point log-barrier to the training objective for each protected constraint:

    L_MIZAN(theta) = L_task(theta) - (1/t) * sum over i of log(h_i(theta))

Here h_i(theta) >= 0 is the satisfaction margin of constraint i, and t sets the barrier strength. As a margin approaches zero, its term grows without bound, which repels the parameter update away from the boundary.

The barrier is `-log(h)`. It is self-concordant, which is the property that lets Newton's method converge cleanly, and it requires a line search that keeps every step strictly feasible. An earlier draft of this project used an inverse-square form, `w / h**2`. That form is not self-concordant and, without a line search, overshoots the boundary. The reference implementation uses the corrected barrier with a feasibility-preserving line search, and it demonstrates a parameter approaching a hard wall without crossing it.

Two supporting pieces are included. An uncertainty measure, the von Neumann entropy S(rho) = -Tr(rho log rho) of a state matrix built from observations, used to decide when the system should stop and defer rather than act under high uncertainty. And a monitoring margin that combines the alignment read-out, its spread, and that uncertainty into a single value that flags when it goes negative.

Nothing in this mechanism is quantum, and none of it involves hardware.

---

## 4. What Is Actually Built and Tested

The repository contains a small reference implementation, `mizan_core.py`, that runs standalone with only numpy.

It demonstrates two things. The barrier wall: a parameter is pulled toward an objective that lies outside the feasible region, approaches the constraint boundary as the barrier strength increases, and never crosses it. This is verified in the output. The gate: the safety margin and its components are computed on telemetry and reported, with a flag when the margin is negative.

The telemetry in the current code is synthetic and is labelled as such. It does not read a model and it does not understand text. It is a fixture for exercising the gate logic.

---

## 5. What Is Not Solved

Stated plainly, because this is where the useful discussion is.

There is no zero-breach guarantee. A hard barrier is stronger than a soft penalty, but a guarantee of zero breach depends on the constraint being correctly specified and correctly measured, and both of those are unsolved. The claim is that this is a better enforcement mechanism, not that it is perfect.

The constraints are the hard part. Encoding a real ethical principle, such as protecting the vulnerable, as a measurable margin h(theta) is an open problem. This note does not claim to have done it. Treating such principles as barrier functions today is aspiration, not mechanism.

The telemetry is synthetic. A real source that reads per-layer activation statistics from a small open-weights model has not been built yet.

The gate is not calibrated. The alignment read-out and the thresholds are placeholders. Without calibration against labelled data, the gate output is not a meaningful judgement about any real input.

Nothing here scales to a large model yet, and nothing has been evaluated against published benchmarks or reviewed by other researchers.

---

## 6. A Phased Way to Evaluate the Idea

If the idea is worth testing, a low-risk sequence would answer the open questions in order.

| Phase | Scope | Question it answers |
| :--- | :--- | :--- |
| 1 | Toy model. Apply the corrected log-barrier in PyTorch or JAX to a small open-weights model such as Pythia-160M or Gemma-2B. | Does the barrier shape parameter gradients near a defined boundary as intended, at a real model's scale. |
| 2 | Telemetry and calibration. Feed real per-layer activation statistics into the gate and calibrate the read-out and thresholds against labelled data. | Can the margin be made to mean something, and what is its false-positive rate on benign inputs. |
| 3 | Behaviour under shift. Measure how the calibrated gate behaves as inputs move away from the calibration distribution. | Does the property hold under distribution shift, defensively measured, without building attack tooling. |

This sequence is deliberately modest. Each phase is a question, not a promised deliverable.

---

## 7. Openness

The idea, the mathematics, and the code are dedicated to the public domain under CC0 1.0 Universal. Anyone may use, fork, or build on them, including commercially, without permission. The intent is simply that the work stays open. There is no trademark and no licensing gate.

---

## 8. Repository and Contact

Repository: https://github.com/brownofficial69/project_mizan

Critique is welcome, particularly on the barrier formulation, the calibration problem, and whether the central hypothesis holds under scale. Issues and pull requests are open.
