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


def test_dashboard_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "MIZAN" in r.text
