import os

# Ensure TESTING mode is enabled before importing the app so that
# expensive startup checks (external key validation, schedulers, etc.)
# are skipped during tests.
os.environ.setdefault("TESTING", "true")

from fastapi.testclient import TestClient
from gap.main import app


client = TestClient(app)


def test_healthz_basic_ok():
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body.get("status") == "ok"
    assert "timestamp" in body
