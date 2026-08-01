from __future__ import annotations

import json

import pytest

from biofield.admission import (
    ActionToolPolicy,
    AdmissionDecision,
    AdmissionPolicy,
    AdmissionRejectionReason,
    AdmissionStatus,
    resolve_admission,
)
from biofield.contracts import (
    AgentBid,
    AgentCommitment,
    AgentIntent,
    CommitmentIssuer,
    CommitmentStatus,
    LocalFieldObservation,
    ResourceAmount,
    ResourceEvent,
    ResourceOperation,
)
from biofield.ledger import SHARED_POOL, agent_escrow_account


def _observation(**overrides: object) -> LocalFieldObservation:
    values: dict[str, object] = {
        "schema_version": 1,
        "observation_id": "observation-1",
        "agent_id": "agent-1",
        "task_id": "task-1",
        "requirement_schema_version": 2,
        "public_state_revision": 3,
        "visible_requirement_signals": ("sources",),
        "congestion_signals": (),
        "resource_terms": (ResourceAmount("tokens", 500),),
        "risk_flags": (),
        "source_event_ids": ("event-1",),
        "field_policy_version": "field-v1",
        "created_at": "2026-07-30T09:00:00+08:00",
        "expires_at": "2026-07-30T09:05:00+08:00",
    }
    values.update(overrides)
    return LocalFieldObservation(**values)


def _intent(**overrides: object) -> AgentIntent:
    values: dict[str, object] = {
        "schema_version": 1,
        "intent_id": "intent-1",
        "agent_id": "agent-1",
        "observation_id": "observation-1",
        "local_state_version": 1,
        "target_requirement_id": "sources",
        "proposed_action_family": "fixture_lookup",
        "expected_evidence_type": "source-record",
        "expected_marginal_progress": 0.5,
        "confidence": 0.8,
        "uncertainty": 0.2,
        "requested_resource_bounds": (ResourceAmount("tokens", 300),),
        "dependency_refs": ("task-input",),
        "expires_at": "2026-07-30T09:04:00+08:00",
    }
    values.update(overrides)
    return AgentIntent(**values)


def _bid(**overrides: object) -> AgentBid:
    values: dict[str, object] = {
        "schema_version": 1,
        "bid_id": "bid-1",
        "agent_id": "agent-1",
        "intent_id": "intent-1",
        "observation_id": "observation-1",
        "target_requirement_id": "sources",
        "capacity_commitment": 1.0,
        "estimated_cost_vector": (ResourceAmount("tokens", 200),),
        "requested_budget_vector": (ResourceAmount("tokens", 250),),
        "expected_completion_window": (
            "2026-07-30T09:01:00+08:00",
            "2026-07-30T09:03:00+08:00",
        ),
        "duplication_tolerance": 0.0,
        "communication_needs": (),
    }
    values.update(overrides)
    return AgentBid(**values)


def _grant(**overrides: object) -> ResourceEvent:
    values: dict[str, object] = {
        "event_id": "grant-1",
        "operation": ResourceOperation.GRANT,
        "resource_type": "tokens",
        "amount": 250,
        "source_account": SHARED_POOL,
        "target_account": agent_escrow_account("agent-1"),
        "idempotency_key": "grant-bid-1-tokens",
    }
    values.update(overrides)
    return ResourceEvent(**values)


def _policy() -> AdmissionPolicy:
    return AdmissionPolicy(
        schema_version=1,
        policy_version="admission-v1",
        action_tool_policies=(
            ActionToolPolicy(
                action_family="fixture_lookup",
                allowed_tools=("fixture.read",),
            ),
        ),
        blocked_risk_flags=("hard-stop",),
    )


def _resolve(**overrides: object):
    values: dict[str, object] = {
        "bid": _bid(),
        "intent": _intent(),
        "observation": _observation(),
        "resource_grants": (_grant(),),
        "run_budget": (ResourceAmount("tokens", 500),),
        "policy": _policy(),
        "at": "2026-07-30T09:00:30+08:00",
        "run_finalized": False,
    }
    values.update(overrides)
    return resolve_admission(**values)


def test_admission_is_deterministic_for_identical_public_inputs() -> None:
    first = _resolve()
    second = _resolve()

    assert first == second
    assert first.to_json() == second.to_json()
    assert AdmissionDecision.from_dict(json.loads(first.to_json())) == first
    assert first.status is AdmissionStatus.ADMITTED
    assert first.rejection_reason is None
    assert first.commitment is not None
    assert first.commitment.issuer is CommitmentIssuer.HARNESS_ADMISSION
    assert first.commitment.allowed_tools == ("fixture.read",)
    assert first.commitment.accepted_scope == ("sources",)
    assert first.commitment.admitted_resources == (ResourceAmount("tokens", 250),)
    assert first.commitment.causal_parent_ids == (
        "observation-1",
        "intent-1",
        "bid-1",
        "grant-1",
    )
    assert json.loads(first.to_json())["commitment"]["status"] == "active"

    rejected = _resolve(run_finalized=True)
    assert AdmissionDecision.from_dict(json.loads(rejected.to_json())) == rejected

    admitted_payload = json.loads(first.to_json())
    with pytest.raises(ValueError, match="policy version"):
        AdmissionDecision.from_dict(
            {**admitted_payload, "policy_version": "forged-policy"}
        )
    with pytest.raises(ValueError, match="decision ID"):
        AdmissionDecision.from_dict(
            {**admitted_payload, "decision_id": "forged-decision"}
        )


def test_commitment_round_trip_and_parent_chain_validation() -> None:
    decision = _resolve()
    commitment = decision.commitment
    assert commitment is not None

    restored = AgentCommitment.from_dict(json.loads(commitment.to_json()))
    assert restored == commitment
    commitment.validate_against(
        _bid(),
        _intent(),
        _observation(),
        (_grant(),),
    )

    with pytest.raises(ValueError, match="bid_id"):
        commitment.validate_against(
            _bid(bid_id="bid-other"),
            _intent(),
            _observation(),
            (_grant(),),
        )


def test_agent_cannot_self_issue_a_commitment() -> None:
    decision = _resolve()
    commitment = decision.commitment
    assert commitment is not None
    payload = commitment.to_dict()
    payload["issuer"] = CommitmentIssuer.AGENT_PROPOSAL

    with pytest.raises(ValueError, match="Harness Admission"):
        AgentCommitment.from_dict(payload)


def test_invalid_parent_and_over_budget_bid_fail_closed() -> None:
    wrong_parent = _resolve(
        bid=_bid(intent_id="intent-other"),
    )
    assert wrong_parent.status is AdmissionStatus.REJECTED
    assert wrong_parent.rejection_reason is AdmissionRejectionReason.INVALID_BID
    assert wrong_parent.commitment is None

    over_budget = _resolve(
        run_budget=(ResourceAmount("tokens", 200),),
    )
    assert over_budget.status is AdmissionStatus.REJECTED
    assert over_budget.rejection_reason is AdmissionRejectionReason.BUDGET_EXCEEDED
    assert over_budget.commitment is None


def test_expired_bid_and_finalized_run_fail_closed() -> None:
    expired = _resolve(at="2026-07-30T09:03:00+08:00")
    assert expired.status is AdmissionStatus.REJECTED
    assert expired.rejection_reason is AdmissionRejectionReason.EXPIRED

    finalized = _resolve(run_finalized=True)
    assert finalized.status is AdmissionStatus.REJECTED
    assert finalized.rejection_reason is AdmissionRejectionReason.RUN_FINALIZED


@pytest.mark.parametrize(
    "grant",
    (
        _grant(operation=ResourceOperation.RESERVE),
        _grant(target_account=agent_escrow_account("agent-2")),
        _grant(amount=249),
    ),
)
def test_invalid_or_mismatched_grants_fail_closed(grant: ResourceEvent) -> None:
    decision = _resolve(resource_grants=(grant,))

    assert decision.status is AdmissionStatus.REJECTED
    assert decision.rejection_reason is AdmissionRejectionReason.INVALID_GRANT
    assert decision.commitment is None


def test_policy_risk_hard_stop_and_unknown_action_family_fail_closed() -> None:
    hard_stop = _resolve(
        observation=_observation(risk_flags=("hard-stop",)),
    )
    assert hard_stop.rejection_reason is AdmissionRejectionReason.RISK_HARD_STOP

    unknown_family = _resolve(
        intent=_intent(proposed_action_family="unknown"),
    )
    assert (
        unknown_family.rejection_reason is AdmissionRejectionReason.ACTION_NOT_ALLOWED
    )


def test_commitment_rejects_invalid_version_status_and_deadline() -> None:
    decision = _resolve()
    commitment = decision.commitment
    assert commitment is not None
    payload = commitment.to_dict()

    with pytest.raises(ValueError, match="schema_version"):
        AgentCommitment.from_dict({**payload, "schema_version": 2})
    with pytest.raises(ValueError, match="status must be active"):
        AgentCommitment.from_dict({**payload, "status": CommitmentStatus.CANCELLED})
    with pytest.raises(ValueError, match="deadline must be after created_at"):
        AgentCommitment.from_dict({**payload, "deadline": payload["created_at"]})
