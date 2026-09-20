import json

import pytest
from fastapi.testclient import TestClient

import main
from diagnose import Diagnosis

TOKEN = "alert-token-123"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub-1")
    monkeypatch.setenv("LAB_RESOURCE_GROUP", "rg-aiops-lab")
    monkeypatch.setenv("MANAGED_APPS", "ca-demo")
    monkeypatch.setenv("WORKLOAD_URL", "https://ca-demo.example.com")
    monkeypatch.setenv("LAB_KEY", "correct-key")
    monkeypatch.setenv("ALERT_TOKEN", TOKEN)
    monkeypatch.setenv("DAILY_REMEDIATION_LIMIT", "3")
    main.INCIDENTS.clear()
    main.REMEDIATIONS.clear()


@pytest.fixture
def client():
    return TestClient(main.app)


def stub_agent(monkeypatch, action="restart_container_app", target="ca-demo", tokens=(1000, 200)):
    def _investigate(t, alert, **_):
        return Diagnosis(
            diagnosis="The app returns 500s from /api/work; its dependency state looks stuck.",
            proposed_action=action,
            target=target,
            confidence="high",
            prompt_tokens=tokens[0],
            completion_tokens=tokens[1],
            tools_used=("container_app_status", "query_logs"),
        )

    monkeypatch.setattr(main, "investigate", _investigate)


def stub_azure(monkeypatch, healed=True):
    calls = {"restarts": 0}
    monkeypatch.setattr(main, "restart_container_app", lambda name: calls.update(restarts=calls["restarts"] + 1, last=name) or "ca-demo--rev1")
    monkeypatch.setattr(main, "verify_recovery", lambda url: healed)
    return calls


def fire_alert(client, target="ca-demo"):
    return client.post(f"/alert/{TOKEN}", json={"target": target, "alert": "5xx rate above threshold"})


# --------------------------------------------------------------------------
# The happy path: detect, diagnose, decide, remediate, verify
# --------------------------------------------------------------------------


def test_incident_runs_end_to_end_and_is_measured(client, monkeypatch):
    stub_agent(monkeypatch)
    calls = stub_azure(monkeypatch)

    response = fire_alert(client)
    assert response.status_code == 200
    incident = client.get(f"/incidents/{response.json()['incident']}").json()

    assert incident["status"] == "resolved"
    assert incident["decision"] == "auto"
    assert incident["healed"] is True
    assert calls["restarts"] == 1 and calls["last"] == "ca-demo"
    # Measured: time to recovery and what the diagnosis cost.
    assert incident["mttr_seconds"] >= 0
    assert incident["cost_usd"] == pytest.approx(1000 / 1e6 * 0.825 + 200 / 1e6 * 4.95)
    assert incident["tools_used"] == ["container_app_status", "query_logs"]


def test_unhealed_incident_is_not_reported_as_resolved(client, monkeypatch):
    stub_agent(monkeypatch)
    stub_azure(monkeypatch, healed=False)

    incident = client.get(f"/incidents/{fire_alert(client).json()['incident']}").json()

    assert incident["healed"] is False
    assert incident["status"] == "unresolved"


# --------------------------------------------------------------------------
# Policy boundaries
# --------------------------------------------------------------------------


def test_repeated_incidents_escalate_instead_of_looping(client, monkeypatch):
    stub_agent(monkeypatch)
    calls = stub_azure(monkeypatch)

    for _ in range(3):
        fire_alert(client)
    assert calls["restarts"] == 3

    fourth = client.get(f"/incidents/{fire_alert(client).json()['incident']}").json()
    assert fourth["status"] == "awaiting_approval"
    assert calls["restarts"] == 3, "the fourth restart must wait for a human"


def test_action_outside_policy_is_never_executed(client, monkeypatch):
    stub_agent(monkeypatch, action="delete_resource_group")
    calls = stub_azure(monkeypatch)

    incident = client.get(f"/incidents/{fire_alert(client).json()['incident']}").json()

    assert incident["status"] == "refused"
    assert calls["restarts"] == 0


def test_proposal_for_another_resource_is_not_executed(client, monkeypatch):
    stub_agent(monkeypatch, target="ca-production")
    calls = stub_azure(monkeypatch)

    fire_alert(client)

    assert calls["restarts"] == 0


# --------------------------------------------------------------------------
# Human approval
# --------------------------------------------------------------------------


def test_human_can_approve_an_escalated_incident(client, monkeypatch):
    stub_agent(monkeypatch)
    calls = stub_azure(monkeypatch)
    for _ in range(3):
        fire_alert(client)
    escalated = fire_alert(client).json()["incident"]

    approved = client.post(f"/incidents/{escalated}/approve", headers={"x-lab-key": "correct-key"})

    assert approved.status_code == 200
    assert approved.json()["healed"] is True
    assert calls["restarts"] == 4


@pytest.mark.parametrize("headers", [{}, {"x-lab-key": "wrong"}])
def test_approval_requires_the_key(client, monkeypatch, headers):
    stub_agent(monkeypatch)
    calls = stub_azure(monkeypatch)
    for _ in range(3):
        fire_alert(client)
    escalated = fire_alert(client).json()["incident"]

    assert client.post(f"/incidents/{escalated}/approve", headers=headers).status_code == 401
    assert calls["restarts"] == 3


def test_an_already_resolved_incident_cannot_be_approved_again(client, monkeypatch):
    stub_agent(monkeypatch)
    stub_azure(monkeypatch)
    resolved = fire_alert(client).json()["incident"]

    again = client.post(f"/incidents/{resolved}/approve", headers={"x-lab-key": "correct-key"})

    assert again.status_code == 409


# --------------------------------------------------------------------------
# The webhook itself
# --------------------------------------------------------------------------


def test_wrong_alert_token_reveals_nothing(client, monkeypatch):
    stub_agent(monkeypatch)
    calls = stub_azure(monkeypatch)

    response = client.post("/alert/guessed-token", json={"target": "ca-demo"})

    assert response.status_code == 404
    assert calls["restarts"] == 0
    assert main.INCIDENTS == {}


def test_azure_alert_payload_is_understood(client, monkeypatch):
    stub_agent(monkeypatch)
    stub_azure(monkeypatch)
    payload = {
        "data": {
            "essentials": {
                "alertRule": "demo-5xx-rate",
                "alertTargetIDs": [
                    "/subscriptions/s/resourceGroups/rg/providers/Microsoft.App/containerApps/ca-demo"
                ],
            }
        }
    }

    response = client.post(f"/alert/{TOKEN}", json=payload)

    incident = client.get(f"/incidents/{response.json()['incident']}").json()
    assert incident["target"] == "ca-demo"
    assert incident["alert"] == "demo-5xx-rate"


def test_incidents_are_emitted_as_json_lines(client, monkeypatch, caplog):
    stub_agent(monkeypatch)
    stub_azure(monkeypatch)

    with caplog.at_level("INFO"):
        fire_alert(client)

    events = [
        json.loads(r.message) for r in caplog.records if r.message.startswith("{")
    ]
    incidents = [e for e in events if e.get("event") == "incident"]
    assert incidents, "the dashboard reads these lines"
    assert {"id", "status", "mttr_seconds", "cost_usd"} <= set(incidents[-1])
