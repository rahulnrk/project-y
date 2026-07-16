"""HTTP smoke tests against the FastAPI app (no Redis needed for /healthz)."""

from fastapi.testclient import TestClient

from src.api.server import app


def test_healthz():
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "hi-IN" in data["languages"]
    assert "te-IN" in data["languages"]
    assert "en-IN" in data["languages"]
