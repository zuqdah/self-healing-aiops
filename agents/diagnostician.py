"""The diagnosing agent, defined as code.

This agent investigates and reports. It has read-only tools, and the
responder refuses any tool call that isn't on that list, so the agent
cannot act on its own conclusions. Deciding and remediating happen in the
responder, under policy.
"""

import os

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential

AGENT_NAME = os.environ.get("AGENT_NAME", "aiops-diagnostician")

INSTRUCTIONS = """
You diagnose incidents in one Azure resource group and propose at most one
remediation. You never take action yourself.

How to investigate:
- Confirm the resource exists and check its current state before judging it.
- Read the workload's recent logs. Its failures are JSON lines containing
  "request_failed"; faults it was given are "fault_injected".
- Distinguish a failing app from a healthy app with no traffic. Absence of
  errors is not evidence of failure.

What to propose:
- "restart_container_app" when the evidence suggests the app's own state is
  at fault and a restart would plausibly clear it.
- "none" when the evidence points elsewhere, or is too thin to act on. An
  honest "none" is more useful than a guess.

Always reply with the JSON object you were asked for, and nothing else. Keep
the diagnosis to two sentences that cite what you actually observed.
""".strip()


def main() -> None:
    project = AIProjectClient(
        endpoint=os.environ["PROJECT_ENDPOINT"],
        credential=DefaultAzureCredential(),
    )

    agent = project.agents.create_version(
        agent_name=AGENT_NAME,
        definition=PromptAgentDefinition(
            model=os.environ["MODEL_DEPLOYMENT"],
            instructions=INSTRUCTIONS,
            tools=[
                MCPTool(
                    server_label="azure-ops",
                    server_url=os.environ["MCP_ENDPOINT"],
                    # Every call returns for approval; the responder approves
                    # read-only tools and refuses everything else.
                    require_approval="always",
                    project_connection_id=os.environ["MCP_CONNECTION_NAME"],
                )
            ],
        ),
    )
    print(f"agent={agent.name} version={agent.version} id={agent.id}")


if __name__ == "__main__":
    main()
