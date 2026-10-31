import pytest
from fastapi.testclient import TestClient

from mizan.api import create_app

OBS = [[1, 1, 1, 0]] * 4


@pytest.fixture()
def client():
    return TestClient(create_app())


def test_health(client):
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/readyz").json()["status"] == "ready"


def test_evaluate(client):
    r = client.post("/v1/evaluate", json={"observations": OBS})
    assert r.status_code == 200
    body = r.json()
    assert {"margin", "gate_tripped", "disclaimer"} <= body.keys()


def test_evaluate_validation(client):
    assert client.post("/v1/evaluate", json={"observations": [[1, 2], [3]]}).status_code == 422
    assert client.post("/v1/evaluate", json={"observations": [[1] * 100]}).status_code == 422
    assert client.post("/v1/evaluate", json={"observations": OBS, "params": {"trials": 10**9}}).status_code == 422
    nan = client.post("/v1/evaluate", content='{"observations": [[NaN, 0, 0, 0]]}',
                      headers={"Content-Type": "application/json"})
    assert nan.status_code == 422


def test_synthetic_is_reproducible(client):
    body = {"context": "hello"}
    a = client.post("/v1/evaluate/synthetic", json=body).json()
    b = client.post("/v1/evaluate/synthetic", json=body).json()
    assert a == b and a["telemetry"] == "synthetic"


def test_batch_and_limit(client):
    item = {"observations": OBS, "params": {"trials": 10}}
    assert len(client.post("/v1/evaluate/batch", json={"items": [item] * 3}).json()["results"]) == 3
    assert client.post("/v1/evaluate/batch", json={"items": [item] * 1000}).status_code == 422


def test_barrier_endpoint(client):
    body = client.get("/v1/barrier").json()
    assert body["boundary_crossed"] is False


def test_api_key_enforced(client, monkeypatch):
    monkeypatch.setenv("MIZAN_API_KEY", "s3cret")
    payload = {"observations": OBS, "params": {"trials": 10}}
    assert client.post("/v1/evaluate", json=payload).status_code == 401
    assert client.post("/v1/evaluate", json=payload, headers={"X-API-Key": "nope"}).status_code == 401
    assert client.post("/v1/evaluate", json=payload, headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/healthz").status_code == 200  # probes stay open


def test_benchmark_quick_and_report(tmp_path, client):
    from mizan.benchmark import main
    res = main(["--quick", "--out", str(tmp_path)])
    assert all(r["barrier_violation_max"] == 0.0 and r["barrier_min_h"] > 0 for r in res["wall"]["rows"])
    # soft penalty overshoots more as pressure rises
    pv = [r["penalty_violation_median"] for r in res["wall"]["rows"]]
    assert pv == sorted(pv) and pv[-1] > 1.0
    # gate trip rate rises with unaligned variance
    tr = [r["trip_rate"] for r in res["gate"]["rows"]]
    assert tr[0] < 0.1 and tr[-1] > 0.9
    assert "What this does not show" in (tmp_path / "report.html").read_text(encoding="utf-8")


def test_lab_page_and_endpoints(client, monkeypatch):
    assert "MIZAN Lab" in client.get("/lab").text
    w = client.get("/v1/lab/wall?dim=3&seed=2").json()
    assert all(p["barrier_violation"] == 0.0 and p["barrier_min_h"] > 0 for p in w["points"])
    assert w["points"][-1]["penalty_violation"] > w["points"][0]["penalty_violation"]
    assert client.get("/v1/lab/wall?dim=1").status_code == 422
    assert client.get("/v1/lab/phase1").json()["status"] in {"absent", "quick_only", "in_progress", "done"}
    monkeypatch.delenv("MIZAN_LAB_ALLOW_RUN", raising=False)
    assert client.get("/v1/lab/capabilities").json() == {"run_tests": False}
    assert client.post("/v1/lab/tests").status_code == 403


def test_phase1_verdict_follows_preregistered_criteria():
    from mizan.lab import phase1_verdict
    def row(m, v, w=1.0, nll=0.1):
        return {"method": m, "violation": v, "pressure_w": w, "task_nll": nll}
    meta = {"meta": {"eps": 100.0}}  # materiality line = 1.0 nat
    assert phase1_verdict({"rows": [row("barrier", 0.0), row("penalty", 0.0)], **meta})["verdict"] == "INCONCLUSIVE"
    assert phase1_verdict({"rows": [row("barrier", 0.0), row("penalty", 0.0005)], **meta})["verdict"] == "INCONCLUSIVE"
    assert phase1_verdict({"rows": [row("barrier", 0.0), row("penalty", 2.0)], **meta})["verdict"] == "PASS"
    assert phase1_verdict({"rows": [row("barrier", 0.1), row("penalty", 2.0)], **meta})["verdict"] == "FAIL"
    costly = {"rows": [row("barrier", 0.0, nll=1.5), row("penalty", 2.0, nll=0.1)], **meta}
    assert phase1_verdict(costly)["verdict"] == "FAIL" and "task loss" in phase1_verdict(costly)["reason"]


def test_dashboard_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "MIZAN" in r.text
