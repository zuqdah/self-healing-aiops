"""Ask the Foundry agent what is wrong and what it would do about it.

The agent investigates with read-only tools only. Every tool call still
comes back for approval, and this client approves reads and refuses
everything else, so the agent can look but cannot act. Remediation is
carried out by the responder under policy, never by the model.
"""

import json
import os
import re
from dataclasses import dataclass

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

READ_ONLY_TOOLS = ("list_resources", "container_app_status", "query_logs")
MAX_ROUNDS = 6

PROMPT = """
An alert fired for the container app "{target}": {alert}

Investigate with your tools and reply with JSON only, no prose:
{{"diagnosis": "<two sentences on what the evidence shows>",
  "proposed_action": "restart_container_app" | "none",
  "target": "{target}",
  "confidence": "low" | "medium" | "high"}}

Propose restart_container_app only when the evidence suggests the app's own
state is at fault and a restart would plausibly clear it. Propose "none" when
the evidence points elsewhere or is insufficient.
""".strip()


@dataclass
class Diagnosis:
    diagnosis: str
    proposed_action: str
    target: str
    confidence: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tools_used: tuple[str, ...] = ()
    raw: str = ""


def _parse(text: str, target: str) -> tuple[str, str, str]:
    """Pull the JSON object out of the reply, tolerating stray prose."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return ("the agent did not return a usable diagnosis", "none", "low")
    try:
        body = json.loads(match.group(0))
    except json.JSONDecodeError:
        return ("the agent returned malformed JSON", "none", "low")

    action = str(body.get("proposed_action", "none"))
    # A proposal for a different resource is not actionable here; policy would
    # refuse it anyway, but this keeps the record honest.
    if str(body.get("target", target)) != target:
        action = "none"
    return (str(body.get("diagnosis", "")), action, str(body.get("confidence", "low")))


def investigate(target: str, alert: str, *, agent_name: str | None = None) -> Diagnosis:
    project = AIProjectClient(
        endpoint=os.environ["PROJECT_ENDPOINT"],
        credential=DefaultAzureCredential(),
    )
    openai = project.get_openai_client()
    reference = {
        "agent_reference": {
            "name": agent_name or os.environ.get("AGENT_NAME", "azure-ops-copilot"),
            "type": "agent_reference",
        }
    }

    response = openai.responses.create(
        input=PROMPT.format(target=target, alert=alert), extra_body=reference
    )

    tools_used: list[str] = []
    prompt_tokens = completion_tokens = 0

    for _ in range(MAX_ROUNDS):
        usage = getattr(response, "usage", None)
        if usage:
            prompt_tokens += getattr(usage, "input_tokens", 0) or 0
            completion_tokens += getattr(usage, "output_tokens", 0) or 0

        decisions = []
        for item in response.output:
            if item.type != "mcp_approval_request" or not item.id:
                continue
            tool = getattr(item, "name", "<unknown>")
            approve = tool in READ_ONLY_TOOLS
            if approve:
                tools_used.append(tool)
            decisions.append(
                {
                    "type": "mcp_approval_response",
                    "approve": approve,
                    "approval_request_id": item.id,
                }
            )

        if not decisions:
            break

        response = openai.responses.create(
            input=decisions, previous_response_id=response.id, extra_body=reference
        )

    text = response.output_text or ""
    diagnosis, action, confidence = _parse(text, target)
    return Diagnosis(
        diagnosis=diagnosis,
        proposed_action=action,
        target=target,
        confidence=confidence,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        tools_used=tuple(tools_used),
        raw=text,
    )
