from __future__ import annotations

import json

import pytest

from biofield.admission import ActionToolPolicy, AdmissionPolicy, resolve_admission
from biofield.commitment import (
    CommitmentGovernanceError,
    authorize_action,
    initial_commitment_lifecycle,
    replay_commitment_transitions,
    transition_commitment,
)
from biofield.contracts import (
    ActionAuthorization,
    ActionProposal,
    AgentBid,
    AgentIntent,
    CommitmentStatus,
    GovernanceIssuer,
    LocalFieldObservation,
    ResourceAmount,
    ResourceEvent,
    ResourceOperation,
)
from biofield.ledger import SHARED_POOL, agent_escrow_account


def _observation() -> LocalFieldObservation:
    return LocalFieldObservation(
        schema_version=1,
        observation_id="observation-1",
        agent_id="agent-1",
        task_id="task-1",
        requirement_schema_version=2,
        public_state_revision=3,
        visible_requirement_signals=("sources",),
        congestion_signals=(),
        resource_terms=(ResourceAmount("tokens", 500),),
        risk_flags=(),
        source_event_ids=("event-1",),
        field_policy_version="field-v1",
        created_at="2026-07-30T09:00:00+08:00",
        expires_at="2026-07-30T09:05:00+08:00",
    )


def _intent() -> AgentIntent:
    return AgentIntent(
        schema_version=1,
        intent_id="intent-1",
        agent_id="agent-1",
        observation_id="observation-1",
        local_state_version=1,
        target_requirement_id="sources",
        proposed_action_family="fixture_lookup",
        expected_evidence_type="source-record",
        expected_marginal_progress=0.5,
        confidence=0.8,
        uncertainty=0.2,
        requested_resource_bounds=(ResourceAmount("tokens", 300),),
        dependency_refs=("task-input",),
        expires_at="2026-07-30T09:04:00+08:00",
    )


def _bid() -> AgentBid:
    return AgentBid(
        schema_version=1,
        bid_id="bid-1",
        agent_id="agent-1",
        intent_id="intent-1",
        observation_id="observation-1",
        target_requirement_id="sources",
        capacity_commitment=1.0,
        estimated_cost_vector=(ResourceAmount("tokens", 200),),
        requested_budget_vector=(ResourceAmount("tokens", 250),),
        expected_completion_window=(
            "2026-07-30T09:01:00+08:00",
            "2026-07-30T09:03:00+08:00",
        ),
        duplication_tolerance=0.0,
        communication_needs=(),
    )


def _grant() -> ResourceEvent:
    return ResourceEvent(
        event_id="grant-1",
        operation=ResourceOperation.GRANT,
        resource_type="tokens",
        amount=250,
        source_account=SHARED_POOL,
        target_account=agent_escrow_account("agent-1"),
        idempotency_key="grant-bid-1-tokens",
    )


def _commitment():
    decision = resolve_admission(
        bid=_bid(),
        intent=_intent(),
        observation=_observation(),
        resource_grants=(_grant(),),
        run_budget=(ResourceAmount("tokens", 500),),
        policy=AdmissionPolicy(
            schema_version=1,
            policy_version="admission-v1",
            action_tool_policies=(
                ActionToolPolicy("fixture_lookup", ("fixture.read",)),
            ),
        ),
        at="2026-07-30T09:00:30+08:00",
        run_finalized=False,
    )
    assert decision.commitment is not None
    return decision.commitment


def _proposal(**overrides: object) -> ActionProposal:
    values: dict[str, object] = {
        "schema_version": 1,
        "action_proposal_id": "action-proposal-1",
        "agent_id": "agent-1",
        "task_id": "task-1",
        "requirement_schema_version": 2,
        "commitment_id": _commitment().commitment_id,
        "requirement_ids": ("sources",),
        "tool": "fixture.read",
        "requested_resources": (ResourceAmount("tokens", 100),),
        "input_refs": ("task-input",),
        "causal_parent_ids": (_commitment().commitment_id,),
        "created_at": "2026-07-30T09:01:00+08:00",
        "expires_at": "2026-07-30T09:02:00+08:00",
        "issuer": GovernanceIssuer.AGENT_PROPOSAL,
    }
    values.update(overrides)
    return ActionProposal(**values)


def _authorize(**overrides: object):
    commitment = _commitment()
    values: dict[str, object] = {
        "proposal": _proposal(commitment_id=commitment.commitment_id,
                              causal_parent_ids=(commitment.commitment_id,)),
        "commitment": commitment,
        "lifecycle": initial_commitment_lifecycle(commitment),
        "resource_grants": (_grant(),),
        "at": "2026-07-30T09:01:10+08:00",
        "run_finalized": False,
    }
    values.update(overrides)
    return authorize_action(**values)


def test_action_authorization_is_deterministic_and_round_trips() -> None:
    first = _authorize()
    second = _authorize()
    proposal = _proposal()

    assert first == second
    assert first.to_json() == second.to_json()
    assert first.issuer is GovernanceIssuer.HARNESS_ADMISSION
    assert first.authorized_resources == (ResourceAmount("tokens", 100),)
    assert ActionAuthorization.from_dict(json.loads(first.to_json())) == first
    assert ActionProposal.from_dict(json.loads(proposal.to_json())) == proposal


def test_action_must_match_active_commitment_scope_tool_budget_and_grants() -> None:
    with pytest.raises(CommitmentGovernanceError, match="agent_id"):
        _authorize(proposal=_proposal(agent_id="agent-2"))
    with pytest.raises(CommitmentGovernanceError, match="scope"):
        _authorize(proposal=_proposal(requirement_ids=("answer",)))
    with pytest.raises(CommitmentGovernanceError, match="tool"):
        _authorize(proposal=_proposal(tool="shell.exec"))
    with pytest.raises(CommitmentGovernanceError, match="resource"):
        _authorize(
            proposal=_proposal(
                requested_resources=(ResourceAmount("tokens", 251),)
            )
        )
    with pytest.raises(CommitmentGovernanceError, match="cumulative"):
        _authorize(
            proposal=_proposal(
                requested_resources=(ResourceAmount("tokens", 100),)
            ),
            consumed_resources=(ResourceAmount("tokens", 200),),
        )
    with pytest.raises(CommitmentGovernanceError, match="grant"):
        _authorize(resource_grants=())


def test_expired_or_finalized_action_is_rejected() -> None:
    with pytest.raises(CommitmentGovernanceError, match="expired"):
        _authorize(at="2026-07-30T09:02:00+08:00")
    with pytest.raises(CommitmentGovernanceError, match="finalized"):
        _authorize(run_finalized=True)


def test_agent_cannot_self_authorize_an_action() -> None:
    authorization = _authorize()
    payload = authorization.to_dict()
    payload["issuer"] = GovernanceIssuer.AGENT_PROPOSAL

    with pytest.raises(ValueError, match="Harness Admission"):
        ActionAuthorization.from_dict(payload)


@pytest.mark.parametrize(
    "terminal_status",
    (CommitmentStatus.COMPLETED, CommitmentStatus.CANCELLED),
)
def test_commitment_terminal_transitions_are_replayable_and_final(
    terminal_status: CommitmentStatus,
) -> None:
    commitment = _commitment()
    initial = initial_commitment_lifecycle(commitment)
    transition, terminal = transition_commitment(
        commitment,
        initial,
        next_status=terminal_status,
        reason="task path settled",
        at="2026-07-30T09:02:00+08:00",
        run_finalized=False,
    )

    assert replay_commitment_transitions(commitment, (transition,)) == terminal
    assert terminal.status is terminal_status
    assert type(transition).from_dict(
        json.loads(transition.to_json())
    ) == transition
    assert type(terminal).from_dict(json.loads(terminal.to_json())) == terminal
    with pytest.raises(CommitmentGovernanceError, match="terminal"):
        transition_commitment(
            commitment,
            terminal,
            next_status=CommitmentStatus.CANCELLED,
            reason="second transition",
            at="2026-07-30T09:02:10+08:00",
            run_finalized=False,
        )
    with pytest.raises(CommitmentGovernanceError, match="not active"):
        authorize_action(
            proposal=_proposal(
                commitment_id=commitment.commitment_id,
                causal_parent_ids=(commitment.commitment_id,),
            ),
            commitment=commitment,
            lifecycle=terminal,
            resource_grants=(_grant(),),
            at="2026-07-30T09:01:10+08:00",
            run_finalized=False,
        )


def test_only_harness_can_create_lifecycle_transition() -> None:
    commitment = _commitment()
    transition, _ = transition_commitment(
        commitment,
        initial_commitment_lifecycle(commitment),
        next_status=CommitmentStatus.COMPLETED,
        reason="done",
        at="2026-07-30T09:02:00+08:00",
        run_finalized=False,
    )
    payload = transition.to_dict()
    payload["issuer"] = GovernanceIssuer.AGENT_PROPOSAL

    with pytest.raises(ValueError, match="Harness Admission"):
        type(transition).from_dict(payload)
