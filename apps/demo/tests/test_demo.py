import json

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture(autouse=True)
def reset():
    main.state.update(broken=False, broken_since=None)


@pytest.fixture
def client():
    return TestClient(main.app)


def test_work_succeeds_while_healthy(client):
    assert client.get("/api/work").status_code == 200


def test_work_fails_once_broken(client):
    client.post("/break")
    response = client.get("/api/work")
    assert response.status_code == 500
    assert response.json()["error"] == "dependency_unavailable"


def test_health_stays_ok_while_broken(client):
    # If this failed, the platform probe would restart the app before any
    # alert fired and the lab would prove nothing.
    client.post("/break")
    assert client.get("/healthz").json() == {"status": "ok"}


def test_fix_clears_the_fault(client):
    client.post("/break")
    client.post("/fix")
    assert client.get("/api/work").status_code == 200


def test_fresh_state_is_healthy():
    # A restart resets in-memory state, which is what makes a restart a real
    # remediation.
    assert main.state["broken"] is False


def test_failures_are_logged_as_json(client, caplog):
    with caplog.at_level("INFO"):
        client.post("/break")
        client.get("/api/work")

    events = [json.loads(r.message) for r in caplog.records if r.message.startswith("{")]
    assert any(e["event"] == "fault_injected" for e in events)
    assert any(e["event"] == "request_failed" and e["status"] == 500 for e in events)
