"""Lab UI backend: read-only views of the whole MIZAN process.

Routes (all under /v1/lab, same API-key rule as the rest of /v1):
  GET  /wall        live barrier vs soft-penalty geometry for one random problem
  GET  /benchmark   results/results.json (run `python -m mizan.benchmark`)
  GET  /phase1      real-model experiment: finished, quick-only, in progress, or absent
  GET  /capabilities
  POST /tests       run the pytest suite (only when MIZAN_LAB_ALLOW_RUN=1)

The page itself is web/lab.html, served at /lab.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query

from .benchmark import _barrier_solve, _penalty_solve

ROOT = Path(__file__).resolve().parent.parent
PRESSURES = [10.0 ** (k / 2) for k in range(0, 13)]  # 1 .. 1e6


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def make_router(require_key) -> APIRouter:
    r = APIRouter(prefix="/v1/lab", dependencies=[Depends(require_key)])

    @r.get("/capabilities")
    def capabilities():
        return {"run_tests": os.environ.get("MIZAN_LAB_ALLOW_RUN") == "1"}

    @r.get("/wall")
    def wall(dim: int = Query(2, ge=2, le=64), seed: int = Query(1, ge=0, le=10**6),
             target_norm: float = Query(3.0, ge=1.2, le=6.0),
             penalty_lambda: float = Query(100.0, ge=0.1, le=1e5)):
        rng = np.random.default_rng(seed)
        u = rng.normal(size=dim)
        c = u / np.linalg.norm(u) * target_norm
        angle = float(rng.uniform(0, 2 * np.pi))  # only used to orient the 2-D drawing
        points = []
        for w in PRESSURES:
            pr = _penalty_solve(target_norm, w, penalty_lambda)
            x, min_h = _barrier_solve(c, w)
            br = float(np.linalg.norm(x))
            points.append({"w": w, "penalty_radius": pr, "barrier_radius": br,
                           "barrier_min_h": min_h, "penalty_violation": max(0.0, pr - 1.0),
                           "barrier_violation": max(0.0, br - 1.0)})
        return {"dim": dim, "seed": seed, "target_radius": target_norm, "angle": angle,
                "penalty_lambda": penalty_lambda, "points": points,
                "note": "Both solutions lie on the ray toward the target, so the 2-D drawing is exact."}

    @r.get("/benchmark")
    def benchmark():
        data = _read_json(ROOT / "results" / "results.json")
        if data is None:
            raise HTTPException(404, "no results yet: run `python -m mizan.benchmark`")
        return data

    @r.get("/phase1")
    def phase1():
        d = Path(os.environ.get("MIZAN_PHASE1_DIR", ROOT / "experiments" / "phase1" / "results"))
        full, quick, log = d / "phase1.json", d / "phase1_quick.json", d / "full_run.log"
        out = {"status": "absent", "data": None, "log_tail": None, "log_age_s": None}
        if log.is_file():
            text = log.read_text(encoding="utf-8", errors="replace").replace("\r", "\n")
            lines = [ln for ln in text.splitlines() if ln.strip() and "Loading weights" not in ln]
            out["log_tail"] = "\n".join(lines[-8:])
            out["log_age_s"] = round(time.time() - log.stat().st_mtime)
        if full.is_file():
            out.update(status="done", data=_read_json(full))
        elif quick.is_file():
            out.update(status="in_progress" if log.is_file() else "quick_only", data=_read_json(quick))
        elif log.is_file():
            out["status"] = "in_progress"
        return out

    @r.post("/tests")
    def run_tests():
        if os.environ.get("MIZAN_LAB_ALLOW_RUN") != "1":
            raise HTTPException(403, "running tests from the UI is disabled (set MIZAN_LAB_ALLOW_RUN=1)")
        t0 = time.time()
        p = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"],
                           cwd=ROOT, capture_output=True, text=True, timeout=300)
        lines = (p.stdout + p.stderr).strip().splitlines()
        return {"ok": p.returncode == 0, "summary": lines[-1] if lines else "", "tail": "\n".join(lines[-25:]),
                "seconds": round(time.time() - t0, 1)}

    return r
