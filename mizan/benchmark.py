"""Reproducible experiments behind the results report.

Run:  python -m mizan.benchmark [--quick]   -> results/results.json, results/report.html

What these experiments can show, and what they cannot, is stated in the report
itself. Every number in the report is computed here, from fixed seeds.
"""

from __future__ import annotations

import argparse
import html
import json
import platform
import time
from pathlib import Path

import numpy as np

from . import __version__
from .core import GateConfig, SafetyGate

PRESSURES = [1, 10, 100, 1_000, 10_000, 100_000]
PENALTY_LAMBDA = 100.0


# ---------------------------------------------------------------------------
# Experiment 1: hard barrier vs soft penalty under rising optimisation pressure
# ---------------------------------------------------------------------------
# Problem: minimise w * ||x - c||^2 inside the unit ball ||x|| <= 1, with the
# task target c outside the ball. The constrained optimum is c / ||c||.
# w is the optimisation pressure (how strongly the task pulls).

def _barrier_solve(c: np.ndarray, w: float, t_schedule=(1e1, 1e2, 1e3, 1e4, 1e5, 1e6)):
    """Generic damped-Newton log-barrier in R^d, strict feasibility enforced."""
    d = c.size
    x = np.zeros(d)
    h = lambda x: 1.0 - x @ x
    phi = lambda x, t: np.inf if h(x) <= 0 else w * np.sum((x - c) ** 2) - np.log(h(x)) / t
    min_h = 1.0
    for t in t_schedule:
        for _ in range(200):
            hv = h(x)
            g = 2 * w * (x - c) + (2.0 / t) * x / hv
            H = 2 * w * np.eye(d) + (1.0 / t) * (2.0 * np.eye(d) / hv + 4.0 * np.outer(x, x) / hv**2)
            step = np.linalg.solve(H, g)
            dec = g @ step
            if dec < 1e-14:
                break
            s, p0 = 1.0, phi(x, t)
            while s > 1e-16:
                xn = x - s * step
                if h(xn) > 0 and phi(xn, t) <= p0 - 1e-4 * s * dec:
                    break
                s *= 0.5
            x = x - s * step
            min_h = min(min_h, h(x))
    return x, min_h


def _penalty_solve(R: float, w: float, lam: float = PENALTY_LAMBDA) -> float:
    """Radius of the minimiser of w(r-R)^2 + lam*max(0, r^2-1)^2 (bisection)."""
    g = lambda r: 2 * w * (r - R) + 4 * lam * r * (r * r - 1)
    lo, hi = 1.0, R
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if g(mid) < 0 else (lo, mid)
    return 0.5 * (lo + hi)


def experiment_wall(quick: bool) -> dict:
    rng = np.random.default_rng(2026)
    dims = [2, 8, 32]
    seeds = 4 if quick else 10
    problems = []
    for d in dims:
        for _ in range(seeds):
            u = rng.normal(size=d)
            problems.append(u / np.linalg.norm(u) * rng.uniform(1.5, 4.0))
    rows = []
    for w in PRESSURES:
        pen_v, bar_v, bar_gap, min_h = [], [], [], 1.0
        for c in problems:
            R = float(np.linalg.norm(c))
            pen_v.append(max(0.0, _penalty_solve(R, w) - 1.0))
            x, mh = _barrier_solve(c, w)
            bar_v.append(max(0.0, float(np.linalg.norm(x)) - 1.0))
            bar_gap.append(float(np.linalg.norm(x - c / R)))
            min_h = min(min_h, mh)
        rows.append({
            "pressure_w": w,
            "penalty_violation_median": float(np.median(pen_v)),
            "penalty_violation_max": float(np.max(pen_v)),
            "barrier_violation_max": float(np.max(bar_v)),
            "barrier_min_h": float(min_h),
            "barrier_gap_to_optimum_median": float(np.median(bar_gap)),
        })
    return {"n_problems": len(problems), "dims": dims, "penalty_lambda": PENALTY_LAMBDA, "rows": rows}


# ---------------------------------------------------------------------------
# Experiment 2: gate response to a controlled shift in the state
# ---------------------------------------------------------------------------
# Observations ~ N(0, diag(1,1,1,m)). m scales the variance carried by the
# coordinate the placeholder readout treats as "unaligned". The labels are
# true by construction, so this checks monotone sensitivity of the gate
# arithmetic. It does not measure detection of anything real.

def experiment_gate(quick: bool) -> dict:
    ms = [0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0]
    n = 40 if quick else 200
    gate = SafetyGate(GateConfig(trials=200))
    rows = []
    for m in ms:
        trips, margins = 0, []
        for s in range(n):
            rng = np.random.default_rng(10_000 + s)
            X = rng.normal(size=(8, 4)) * np.sqrt([1, 1, 1, m])
            r = gate.evaluate(X)
            trips += r["gate_tripped"]
            margins.append(r["margin"])
        rows.append({"unaligned_variance_m": m, "trip_rate": trips / n,
                     "margin_median": float(np.median(margins))})
    return {"samples_per_point": n, "rows": rows}


# ---------------------------------------------------------------------------
# Experiment 3: cost
# ---------------------------------------------------------------------------

def experiment_latency(quick: bool) -> dict:
    gate = SafetyGate()
    X = np.random.default_rng(0).normal(size=(8, 4))
    gate.evaluate(X)
    n = 30 if quick else 200
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        gate.evaluate(X)
        ts.append((time.perf_counter() - t0) * 1000)
    ts = np.array(ts)
    return {"runs": n, "default_trials": gate.config.trials,
            "p50_ms": float(np.percentile(ts, 50)), "p99_ms": float(np.percentile(ts, 99)),
            "evals_per_sec_single_core": float(1000 / ts.mean())}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _chart(title, xlabels, series, ylabel, ymax, width=640, height=300):
    """Tiny inline-SVG line chart. series: [(name, colour, [y...])]."""
    L, R, T, B = 56, 32, 16, 44
    pw, ph = width - L - R, height - T - B
    xs = [L + pw * i / (len(xlabels) - 1) for i in range(len(xlabels))]
    y = lambda v: T + ph * (1 - min(v, ymax) / ymax)
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">']
    for k in range(5):
        v = ymax * k / 4
        out.append(f'<line x1="{L}" x2="{width-R}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                   f'<text x="{L-8}" y="{y(v)+4:.1f}" class="tick" text-anchor="end">{v:.2g}</text>')
    for x, lab in zip(xs, xlabels):
        out.append(f'<text x="{x:.1f}" y="{height-24}" class="tick" text-anchor="middle">{html.escape(str(lab))}</text>')
    out.append(f'<text x="{L-44}" y="{T+ph/2}" class="tick" transform="rotate(-90 {L-44} {T+ph/2})" text-anchor="middle">{html.escape(ylabel)}</text>')
    for name, colour, ys in series:
        pts = " ".join(f"{x:.1f},{y(v):.1f}" for x, v in zip(xs, ys))
        out.append(f'<polyline points="{pts}" fill="none" stroke="{colour}" stroke-width="2.5"/>')
        out += [f'<circle cx="{x:.1f}" cy="{y(v):.1f}" r="3.5" fill="{colour}"/>' for x, v in zip(xs, ys)]
    lx = L + 8
    for name, colour, _ in series:
        out.append(f'<rect x="{lx}" y="{T+2}" width="12" height="12" fill="{colour}"/>'
                   f'<text x="{lx+18}" y="{T+12}" class="tick">{html.escape(name)}</text>')
        lx += 18 + 8 * len(name) + 18
    out.append("</svg>")
    return "".join(out)


def render_report(res: dict) -> str:
    w, g, lat = res["wall"], res["gate"], res["latency"]
    rows = w["rows"]
    top = rows[-1]
    c1 = _chart("Constraint violation versus optimisation pressure",
                [f"{r['pressure_w']:g}" for r in rows],
                [("soft penalty (median)", "#ff5d73", [r["penalty_violation_median"] for r in rows]),
                 ("hard barrier (max)", "#12b886", [r["barrier_violation_max"] for r in rows])],
                "violation: ||x|| - 1", max(r["penalty_violation_max"] for r in rows) * 1.1 or 1)
    c2 = _chart("Gate trip rate versus unaligned variance",
                [f"{r['unaligned_variance_m']:g}" for r in g["rows"]],
                [("trip rate", "#56ccf2", [r["trip_rate"] for r in g["rows"]])],
                "fraction of runs tripped", 1.0)
    table = "".join(
        f"<tr><td>{r['pressure_w']:,}</td><td>{r['penalty_violation_median']:.4f}</td>"
        f"<td>{r['penalty_violation_max']:.4f}</td><td>{r['barrier_violation_max']:.1e}</td>"
        f"<td>{r['barrier_min_h']:.1e}</td><td>{r['barrier_gap_to_optimum_median']:.1e}</td></tr>"
        for r in rows)
    m = res["meta"]
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>MIZAN results</title>
<style>
:root{{--bg:#fff;--fg:#14202e;--mut:#5b6b7c;--card:#f4f7fa;--line:#d8e0e8}}
@media(prefers-color-scheme:dark){{:root{{--bg:#0b1a2b;--fg:#dbe4ee;--mut:#8296ab;--card:#11253c;--line:#22456a}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,sans-serif}}
main{{max-width:820px;margin:0 auto;padding:28px 16px 64px}}
h1{{font-size:30px;margin:0 0 6px}} h2{{font-size:20px;margin:34px 0 6px}}
.mut{{color:var(--mut)}} .card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:14px 0}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}}
.kpi b{{display:block;font-size:26px}} svg{{width:100%;height:auto}} .grid{{stroke:var(--line)}}
.tick{{fill:var(--mut);font:11px ui-monospace,monospace}}
table{{border-collapse:collapse;width:100%;font:13px ui-monospace,monospace}}
td,th{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right}} th{{color:var(--mut)}}
.warn{{border-left:4px solid #ffc14d}} .scroll{{overflow-x:auto}}
</style></head><body><main>
<p class="mut">PROJECT MIZAN &middot; v{__version__} &middot; results report</p>
<h1>A hard constraint holds where a soft one gives way</h1>
<p class="mut">Everything below was computed by <code>python -m mizan.benchmark</code> from fixed seeds. It tests one narrow claim about optimisation. It is not a test of AI safety.</p>

<div class="card kpis">
<div class="kpi"><b>{top['barrier_violation_max']:.0f}</b><span class="mut">barrier violations across {w['n_problems']} problems &times; {len(rows)} pressure levels</span></div>
<div class="kpi"><b>{top['penalty_violation_median']:.2f}</b><span class="mut">median overshoot of the soft penalty at pressure {top['pressure_w']:,} (unit: radius of the safe ball)</span></div>
<div class="kpi"><b>{lat['p50_ms']:.0f} ms</b><span class="mut">median gate evaluation, {lat['default_trials']} Monte Carlo trials, one core</span></div>
</div>

<h2>1. Hard barrier versus soft penalty</h2>
<p>A task pulls a parameter vector toward a target that lies outside a safe region (the unit ball). One method adds a fixed-weight penalty for leaving the region, which is the shape of a learned preference. The other uses an interior-point log-barrier that keeps every iterate strictly inside. We raise the optimisation pressure on the task and measure how far each method ends up outside the region.</p>
<div class="card">{c1}</div>
<div class="card scroll"><table><tr><th>pressure</th><th>penalty median</th><th>penalty max</th><th>barrier max</th><th>barrier min h</th><th>barrier gap to optimum</th></tr>{table}</table></div>
<p>The penalty's overshoot grows with pressure and approaches the full distance to the target. The barrier is never outside, and its distance to the true constrained optimum shrinks as the barrier strength rises, so it is not simply staying far from the wall.</p>

<h2>2. Gate response to a controlled shift</h2>
<p>Synthetic observations are generated with a known amount of variance on the coordinate the placeholder readout treats as unaligned. The gate trips more often as that variance grows ({g['samples_per_point']} runs per point).</p>
<div class="card">{c2}</div>

<h2>3. Cost</h2>
<p>Median {lat['p50_ms']:.1f} ms, 99th percentile {lat['p99_ms']:.1f} ms, about {lat['evals_per_sec_single_core']:.0f} evaluations per second per core ({lat['runs']} runs). The service is stateless, so throughput scales with the number of containers.</p>

<h2>What this does not show</h2>
<div class="card warn"><ul>
<li><b>Experiment 1 is a mathematical illustration</b> on a convex toy problem with a known safe region. It supports the narrow claim that a barrier method keeps iterates inside a constraint set that a fixed-weight penalty does not. It does not show that any real model's behaviour can be expressed as such a constraint.</li>
<li><b>Experiment 2 uses data labelled by construction.</b> It shows the gate arithmetic responds in the expected direction. It is not a detection rate on real inputs.</li>
<li>The gate is uncalibrated, reads no real model, and does not understand text. No external review or benchmark has been done.</li>
<li>The soft-penalty baseline uses one weight ({w['penalty_lambda']:g}). A larger weight delays the overshoot but does not remove it, and an exact-penalty method would behave differently.</li>
</ul></div>
<p class="mut">Environment: Python {m['python']}, numpy {m['numpy']}, {m['platform']}. Mode: {m['mode']}. Source: github.com/brownofficial69/project_mizan. CC0.</p>
</main></body></html>"""


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="fewer samples (CI)")
    ap.add_argument("--out", default="results")
    args = ap.parse_args(argv)
    res = {
        "wall": experiment_wall(args.quick),
        "gate": experiment_gate(args.quick),
        "latency": experiment_latency(args.quick),
        "meta": {"python": platform.python_version(), "numpy": np.__version__,
                 "platform": platform.platform(), "mode": "quick" if args.quick else "full",
                 "version": __version__},
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(res, indent=2))
    (out / "report.html").write_text(render_report(res), encoding="utf-8")
    return res


if __name__ == "__main__":
    main()
