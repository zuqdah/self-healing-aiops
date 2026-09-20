"""A small workload that can be broken on demand.

The injected fault is an in-process one: the app leaks its worker pool and
cannot recover by itself. That matters for the lab. The evidence in the logs
has to point at a fault a restart actually fixes, otherwise a competent
diagnosis will correctly refuse to restart it.

The failure is deliberately in-memory, so restarting the app really does fix
it. That makes "restart the revision" a genuine remediation rather than a
simulated one.

/healthz keeps reporting healthy while the app is broken. If it failed, the
Container Apps probe would restart the app within seconds and the incident
would heal before any alert fired, which would make the lab prove nothing.
Failures surface in the request path and in the logs instead, which is where
the alert rule looks.
"""

import json
import logging
import os
import sys
import time

from fastapi import FastAPI
from fastapi.responses import JSONResponse

SERVICE = os.environ.get("SERVICE_NAME", "demo-workload")

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
log = logging.getLogger(SERVICE)

app = FastAPI(title="Demo workload", version="1.0.0")

# Reset by any restart: the whole point of the lab.
state = {"broken": False, "broken_since": None, "started_at": time.time()}


def emit(event: str, **fields) -> None:
    """One JSON object per line, so Log Analytics can parse it."""
    log.info(json.dumps({"service": SERVICE, "event": event, **fields}))


@app.get("/healthz")
def healthz() -> dict:
    # Always healthy on purpose; see the module docstring.
    return {"status": "ok"}


@app.get("/")
def info() -> dict:
    return {
        "service": SERVICE,
        "broken": state["broken"],
        "uptime_seconds": round(time.time() - state["started_at"], 1),
        "try": "GET /api/work, POST /break, POST /fix",
    }


@app.get("/api/work")
def work():
    """The business endpoint the alert rule watches."""
    if state["broken"]:
        emit(
            "request_failed",
            status=500,
            reason="worker_pool_exhausted",
            detail="in-process worker pool is exhausted and will not recover on its own",
        )
        return JSONResponse(
            {
                "error": "worker_pool_exhausted",
                "detail": "this process has leaked all of its workers; it must be restarted",
            },
            status_code=500,
        )
    emit("request_ok", status=200)
    return {"result": "ok"}


@app.post("/break")
def break_it() -> dict:
    """Start failing. Used to stage an incident."""
    state["broken"] = True
    state["broken_since"] = time.time()
    emit("fault_injected", reason="worker_pool_exhausted", scope="in_process_state")
    return {"broken": True}


@app.post("/fix")
def fix() -> dict:
    """Recover without a restart, so tests can reset the app."""
    state["broken"] = False
    emit("fault_cleared", method="manual")
    return {"broken": False}
