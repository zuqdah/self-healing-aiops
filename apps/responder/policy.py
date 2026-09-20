"""What the responder is allowed to do without asking a human.

Autonomy here is bounded three ways: by the set of actions that exist at
all, by the resources they may touch, and by how often they may run. A
proposal that clears all three runs on its own; anything else waits for a
person. The model's confidence is deliberately not an input.
"""

from dataclasses import dataclass
from typing import Literal

Outcome = Literal["auto", "escalate", "refuse"]

# Actions the responder knows how to perform. Anything else is refused
# outright rather than escalated: a human approving an action we cannot
# safely execute would be meaningless.
KNOWN_ACTIONS = frozenset({"restart_container_app"})

# Actions safe enough to run unattended when the other limits hold.
AUTONOMOUS_ACTIONS = frozenset({"restart_container_app"})


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    reason: str

    @property
    def is_auto(self) -> bool:
        return self.outcome == "auto"


def decide(
    action: str,
    target: str,
    *,
    allowed_targets: frozenset[str],
    remediations_today: int,
    daily_limit: int,
) -> Decision:
    """Decide how a proposed remediation may proceed."""
    if not action or action == "none":
        return Decision("refuse", "the diagnosis proposed no action")

    if action not in KNOWN_ACTIONS:
        return Decision("refuse", f"{action!r} is not an action this responder can perform")

    if target not in allowed_targets:
        return Decision("refuse", f"{target!r} is outside the resources this responder manages")

    if action not in AUTONOMOUS_ACTIONS:
        return Decision("escalate", f"{action!r} always requires human approval")

    if remediations_today >= daily_limit:
        return Decision(
            "escalate",
            f"{target} has already been remediated {remediations_today} times today "
            f"(limit {daily_limit}); repeated failures need a person to look",
        )

    return Decision("auto", f"{action} on {target} is within policy ({remediations_today}/{daily_limit} today)")
