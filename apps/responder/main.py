"""The AIOps responder: alert in, verified recovery out.

An incident runs through five steps, each timed and recorded:

    detect -> diagnose (agent) -> decide (policy) -> remediate -> verify

The agent only diagnoses. The decision is policy in code, the remediation is
an Azure REST call made with this app's own identity, and the verification is
an HTTP check against the workload. Every incident is emitted as one JSON
line, which is what the MTTR and cost dashboard reads.
"""

import hmac
import json
import logging
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date

import httpx
from azure.identity import DefaultAzureCredential
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

import policy
from diagnose import investigate

ARM = "https://management.azure.com"
ARM_SCOPE = "https://management.azure.com/.default"
CONTAINER_APPS_API = "2026-01-01"

SERVICE = "aiops-responder"
VERIFY_ATTEMPTS = 20
VERIFY_INTERVAL_SECONDS = 3

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
log = logging.getLogger(SERVICE)

_credential = DefaultAzureCredential()
_token_cache: dict = {}


def config(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default or "")
    if not value:
        raise RuntimeError(f"{name} is not configured")
    return value


def token(scope: str = ARM_SCOPE) -> str:
    cached = _token_cache.get(scope)
    if cached is None or cached.expires_on - 300 < time.time():
        cached = _credential.get_token(scope)
        _token_cache[scope] = cached
    return cached.token


# ---------------------------------------------------------------------------
# Incident record
# ---------------------------------------------------------------------------


@dataclass
class Incident:
    id: str
    alert: str
    target: str
    detected_at: float
    status: str = "detected"
    diagnosis: str = ""
    proposed_action: str = "none"
    proposed_target: str = ""
    confidence: str = ""
    decision: str = ""
    decision_reason: str = ""
    tools_used: list[str] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    diagnosed_at: float | None = None
    remediated_at: float | None = None
    verified_at: float | None = None
    mttr_seconds: float | None = None
    healed: bool | None = None

    def emit(self) -> None:
        """One JSON line per state change; Log Analytics parses these."""
        log.info(json.dumps({"service": SERVICE, "event": "incident", **asdict(self)}))


INCIDENTS: dict[str, Incident] = {}
REMEDIATIONS: dict[tuple[str, str], int] = {}  # (date, target) -> count


def remediations_today(target: str) -> int:
    return REMEDIATIONS.get((date.today().isoformat(), target), 0)


def record_remediation(target: str) -> None:
    key = (date.today().isoformat(), target)
    REMEDIATIONS[key] = REMEDIATIONS.get(key, 0) + 1


def token_cost(prompt_tokens: int, completion_tokens: int) -> float:
    input_rate = float(os.environ.get("INPUT_USD_PER_MTOK", "0.825"))
    output_rate = float(os.environ.get("OUTPUT_USD_PER_MTOK", "4.95"))
    return round(prompt_tokens / 1e6 * input_rate + completion_tokens / 1e6 * output_rate, 6)


# ---------------------------------------------------------------------------
# Remediation and verification
# ---------------------------------------------------------------------------


def restart_container_app(name: str) -> str:
    """Restart the app's active revision. The identity running this holds a
    custom role whose only action is exactly this."""
    base = (
        f"{ARM}/subscriptions/{config('AZURE_SUBSCRIPTION_ID')}"
        f"/resourceGroups/{config('LAB_RESOURCE_GROUP')}"
        f"/providers/Microsoft.App/containerApps/{name}"
    )
    headers = {"Authorization": f"Bearer {token()}"}
    params = {"api-version": CONTAINER_APPS_API}

    current = httpx.get(base, params=params, headers=headers, timeout=30.0)
    current.raise_for_status()
    revision = current.json().get("properties", {}).get("latestReadyRevisionName")
    if not revision:
        raise RuntimeError("no ready revision to restart")

    restarted = httpx.post(
        f"{base}/revisions/{revision}/restart", params=params, headers=headers, timeout=60.0
    )
    restarted.raise_for_status()
    return revision


def verify_recovery(url: str) -> bool:
    """Poll the workload until it serves traffic again."""
    for _ in range(VERIFY_ATTEMPTS):
        try:
            if httpx.get(f"{url}/api/work", timeout=10.0).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(VERIFY_INTERVAL_SECONDS)
    return False


def remediate_and_verify(incident: Incident) -> None:
    target = incident.proposed_target or incident.target
    revision = restart_container_app(target)
    record_remediation(target)
    incident.remediated_at = time.time()
    incident.status = "verifying"
    incident.emit()

    incident.healed = verify_recovery(config("WORKLOAD_URL"))
    incident.verified_at = time.time()
    incident.mttr_seconds = round(incident.verified_at - incident.detected_at, 1)
    incident.status = "resolved" if incident.healed else "unresolved"
    log.info(
        json.dumps(
            {"service": SERVICE, "event": "remediation", "incident": incident.id,
             "action": "restart_container_app", "target": target,
             "revision": revision, "healed": incident.healed}
        )
    )
    incident.emit()


def handle(incident: Incident) -> Incident:
    """Diagnose, decide, and act."""
    finding = investigate(incident.target, incident.alert)
    incident.diagnosis = finding.diagnosis
    incident.proposed_action = finding.proposed_action
    # The agent may name a different resource than the one that alerted; the
    # decision is made about what it actually proposed to touch.
    incident.proposed_target = finding.target or incident.target
    incident.confidence = finding.confidence
    incident.tools_used = list(finding.tools_used)
    incident.prompt_tokens = finding.prompt_tokens
    incident.completion_tokens = finding.completion_tokens
    incident.cost_usd = token_cost(finding.prompt_tokens, finding.completion_tokens)
    incident.diagnosed_at = time.time()
    incident.status = "diagnosed"
    incident.emit()

    decision = policy.decide(
        incident.proposed_action,
        incident.proposed_target,
        allowed_targets=frozenset(config("MANAGED_APPS").split(",")),
        remediations_today=remediations_today(incident.proposed_target),
        daily_limit=int(os.environ.get("DAILY_REMEDIATION_LIMIT", "3")),
    )
    incident.decision = decision.outcome
    incident.decision_reason = decision.reason

    if not decision.is_auto:
        incident.status = "awaiting_approval" if decision.outcome == "escalate" else "refused"
        incident.emit()
        return incident

    remediate_and_verify(incident)
    return incident


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------

app = FastAPI(title="AIOps responder", version="1.0.0")


def check_key(request: Request) -> None:
    presented = request.headers.get("x-lab-key", "")
    if not hmac.compare_digest(presented, config("LAB_KEY")):
        raise HTTPException(status_code=401, detail="unauthorized")


class Alert(BaseModel):
    target: str | None = None
    alert: str | None = None


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/alert/{path_token}")
async def alert(path_token: str, body: Alert, request: Request) -> dict:
    """Azure Monitor webhook target.

    Azure Monitor's plain webhooks cannot send custom headers, so the shared
    secret is in the path. A production deployment would use a secure webhook
    with an Entra identity instead; this keeps the secret out of the payload
    and the query string, and the endpoint does nothing without it.
    """
    if not hmac.compare_digest(path_token, config("ALERT_TOKEN")):
        raise HTTPException(status_code=404, detail="not found")

    payload = await request.json() if not body.target else {}
    target = body.target or _target_from_azure_alert(payload) or config("DEFAULT_TARGET")
    description = body.alert or _name_from_azure_alert(payload) or "alert fired"

    incident = Incident(
        id=uuid.uuid4().hex[:12], alert=description, target=target, detected_at=time.time()
    )
    INCIDENTS[incident.id] = incident
    incident.emit()

    handle(incident)
    # The full record, so callers don't need a second request that could land
    # on a different replica.
    return asdict(incident)


@app.post("/incidents/{incident_id}/approve")
def approve(incident_id: str, request: Request) -> dict:
    """Human approval for an escalated incident."""
    check_key(request)
    incident = INCIDENTS.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="no such incident")
    if incident.status != "awaiting_approval":
        raise HTTPException(status_code=409, detail=f"incident is {incident.status}")

    incident.decision = "approved_by_human"
    incident.decision_reason = "a person approved the escalated action"
    incident.emit()
    remediate_and_verify(incident)
    return asdict(incident)


@app.get("/incidents")
def list_incidents() -> dict:
    return {"incidents": [asdict(i) for i in INCIDENTS.values()]}


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: str) -> dict:
    incident = INCIDENTS.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="no such incident")
    return asdict(incident)


def _target_from_azure_alert(payload: dict) -> str | None:
    """Pull the affected resource name out of a Common Alert Schema payload."""
    try:
        ids = payload["data"]["essentials"]["alertTargetIDs"]
        return ids[0].rsplit("/", 1)[-1] if ids else None
    except (KeyError, TypeError, IndexError):
        return None


def _name_from_azure_alert(payload: dict) -> str | None:
    try:
        return payload["data"]["essentials"]["alertRule"]
    except (KeyError, TypeError):
        return None
