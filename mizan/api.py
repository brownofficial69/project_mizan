"""HTTP service for the MIZAN gate and barrier.

Configuration (environment variables):
  MIZAN_API_KEY      if set, /v1/* requires header `X-API-Key: <value>`
  MIZAN_MAX_OBS      max observation rows per request        (default 256)
  MIZAN_MAX_DIM      max observation dimension               (default 16)
  MIZAN_MAX_BATCH    max items in a batch request            (default 32)
  MIZAN_INDEX_HTML   path to the dashboard served at `/`
"""

from __future__ import annotations

import hmac
import logging
import os
import time
from pathlib import Path
from typing import List, Optional

import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import __version__
from .core import GateConfig, SafetyGate, wall_demo
from .telemetry import SyntheticTelemetry

log = logging.getLogger("mizan")

DISCLAIMER = (
    "Concept demonstration. The gate computes statistics on the vectors it is "
    "given; it is uncalibrated and does not understand text or detect deception."
)


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


MAX_OBS = _int_env("MIZAN_MAX_OBS", 256)
MAX_DIM = _int_env("MIZAN_MAX_DIM", 16)
MAX_BATCH = _int_env("MIZAN_MAX_BATCH", 32)


class GateParams(BaseModel):
    beta: float = Field(0.85, ge=0, le=10)
    tau: float = Field(0.40, ge=-1, le=1)
    doubt_weight: float = Field(0.60, ge=0, le=10)
    risk_threshold: float = Field(0.15, ge=0, le=1)
    trials: int = Field(2000, ge=10, le=2000)
    seed: int = Field(0, ge=0, le=2**32 - 1)


class EvaluateRequest(BaseModel):
    observations: List[List[float]] = Field(..., description="matrix (n_obs x dim)")
    params: GateParams = GateParams()


class SyntheticRequest(BaseModel):
    context: str = Field(..., min_length=1, max_length=512)
    dim: int = Field(4, ge=2, le=MAX_DIM)
    n_obs: int = Field(8, ge=2, le=MAX_OBS)
    params: GateParams = GateParams()


class BatchRequest(BaseModel):
    items: List[EvaluateRequest] = Field(..., min_length=1)


def require_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    expected = os.environ.get("MIZAN_API_KEY")
    if expected and not hmac.compare_digest(x_api_key or "", expected):
        raise HTTPException(status_code=401, detail="invalid or missing API key")


def _evaluate(observations, params: GateParams) -> dict:
    try:
        obs = np.array(observations, dtype=float)
    except ValueError:
        raise HTTPException(status_code=422, detail="observations must be a rectangular matrix")
    if obs.ndim != 2 or obs.shape[0] < 1:
        raise HTTPException(status_code=422, detail="observations must be a 2-D matrix")
    if obs.shape[0] > MAX_OBS or not 2 <= obs.shape[1] <= MAX_DIM:
        raise HTTPException(status_code=422, detail=f"need 1..{MAX_OBS} rows and 2..{MAX_DIM} columns")
    if not np.all(np.isfinite(obs)):
        raise HTTPException(status_code=422, detail="observations must be finite")
    gate = SafetyGate(GateConfig(dim=obs.shape[1], **params.model_dump()))
    result = gate.evaluate(obs)
    result["disclaimer"] = DISCLAIMER
    return result


def create_app() -> FastAPI:
    app = FastAPI(title="MIZAN", version=__version__, description=DISCLAIMER)

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        log.info("%s %s -> %s (%.1f ms)", request.method, request.url.path,
                 response.status_code, (time.perf_counter() - start) * 1000)
        return response

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse({"detail": "internal error"}, status_code=500)

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok", "version": __version__}

    @app.get("/readyz", include_in_schema=False)
    def readyz():
        _evaluate([[1, 0, 0, 0], [0, 1, 0, 0]], GateParams(trials=10))
        return {"status": "ready"}

    @app.post("/v1/evaluate", dependencies=[Depends(require_key)])
    def evaluate(req: EvaluateRequest):
        return _evaluate(req.observations, req.params)

    @app.post("/v1/evaluate/batch", dependencies=[Depends(require_key)])
    def evaluate_batch(req: BatchRequest):
        if len(req.items) > MAX_BATCH:
            raise HTTPException(status_code=422, detail=f"batch limited to {MAX_BATCH} items")
        return {"results": [_evaluate(i.observations, i.params) for i in req.items]}

    @app.post("/v1/evaluate/synthetic", dependencies=[Depends(require_key)])
    def evaluate_synthetic(req: SyntheticRequest):
        obs = SyntheticTelemetry(req.dim, req.n_obs).read(req.context)
        out = _evaluate(obs.tolist(), req.params)
        out["telemetry"] = "synthetic"
        return out

    @app.get("/v1/barrier", dependencies=[Depends(require_key)])
    def barrier():
        traj = wall_demo()
        return {
            "wall": 3.0,
            "target": 5.0,
            "trajectory": [{"t": t, "theta": th, "h": hv} for t, th, hv in traj],
            "boundary_crossed": any(hv < 0 for _, _, hv in traj),
        }

    index = Path(os.environ.get("MIZAN_INDEX_HTML", Path(__file__).resolve().parent.parent / "index.html"))
    if index.is_file():
        @app.get("/", include_in_schema=False)
        def dashboard():
            return FileResponse(index, media_type="text/html")

    report = Path(os.environ.get("MIZAN_REPORT_HTML", Path(__file__).resolve().parent.parent / "results" / "report.html"))
    if report.is_file():
        @app.get("/report", include_in_schema=False)
        def results_report():
            return FileResponse(report, media_type="text/html")

    return app


app = create_app()
