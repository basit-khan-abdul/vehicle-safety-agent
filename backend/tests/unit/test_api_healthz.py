"""API smoke test: the app builds and the liveness probe responds.

Exercises the FastAPI wiring (routes, slowapi registration) without touching the
agent or the network.
"""

from fastapi.testclient import TestClient

from app.api.app import create_app


def test_healthz_ok():
    client = TestClient(create_app())
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ask_rejects_empty_question():
    client = TestClient(create_app())
    resp = client.post("/ask", json={"question": ""})
    assert resp.status_code == 422  # min_length=1 validation, no agent call
