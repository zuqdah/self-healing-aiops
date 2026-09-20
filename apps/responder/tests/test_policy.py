import policy

MANAGED = frozenset({"ca-demo"})


def decide(action="restart_container_app", target="ca-demo", today=0, limit=3):
    return policy.decide(
        action, target, allowed_targets=MANAGED, remediations_today=today, daily_limit=limit
    )


def test_known_action_within_limits_runs_unattended():
    assert decide().outcome == "auto"


def test_no_proposal_is_refused():
    for action in ("none", ""):
        assert decide(action=action).outcome == "refuse"


def test_unknown_action_is_refused_not_escalated():
    # A human approving something the responder cannot perform would be
    # meaningless, so this is refused outright.
    assert decide(action="delete_resource_group").outcome == "refuse"
    assert decide(action="scale_to_zero").outcome == "refuse"


def test_resource_outside_scope_is_refused():
    assert decide(target="ca-production").outcome == "refuse"


def test_repeated_failures_escalate_to_a_human():
    assert decide(today=2, limit=3).outcome == "auto"
    at_limit = decide(today=3, limit=3)
    assert at_limit.outcome == "escalate"
    assert "already been remediated" in at_limit.reason
    assert decide(today=9, limit=3).outcome == "escalate"


def test_a_zero_limit_means_nothing_runs_unattended():
    assert decide(today=0, limit=0).outcome == "escalate"


def test_decisions_explain_themselves():
    assert decide().reason
    assert decide(action="nonsense").reason
    assert decide(today=5).reason
