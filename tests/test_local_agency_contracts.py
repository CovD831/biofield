from __future__ import annotations

import json

import pytest

from biofield.contracts import (
    AgentBid,
    AgentIntent,
    AgentRefusal,
    LocalFieldObservation,
    RefusalReason,
    ResourceAmount,
)


def _observation(**overrides: object) -> LocalFieldObservation:
    values: dict[str, object] = {
        "schema_version": 1,
        "observation_id": "observation-1",
        "agent_id": "agent-1",
        "task_id": "task-1",
        "requirement_schema_version": 2,
        "public_state_revision": 3,
        "visible_requirement_signals": ("sources", "answer"),
        "congestion_signals": ("tool:web:busy",),
        "resource_terms": (ResourceAmount("tokens", 500),),
        "risk_flags": ("external-content",),
        "source_event_ids": ("feedback-1", "resource-1"),
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
        "local_state_version": 4,
        "target_requirement_id": "sources",
        "proposed_action_family": "fixture_lookup",
        "expected_evidence_type": "source-record",
        "expected_marginal_progress": 0.6,
        "confidence": 0.75,
        "uncertainty": 0.25,
        "requested_resource_bounds": (ResourceAmount("tokens", 300),),
        "dependency_refs": ("artifact:task-input",),
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
        "capacity_commitment": 0.8,
        "estimated_cost_vector": (ResourceAmount("tokens", 240),),
        "requested_budget_vector": (ResourceAmount("tokens", 260),),
        "expected_completion_window": (
            "2026-07-30T09:01:00+08:00",
            "2026-07-30T09:03:00+08:00",
        ),
        "duplication_tolerance": 0.1,
        "communication_needs": ("agent:any/source-review",),
    }
    values.update(overrides)
    return AgentBid(**values)


def _refusal(**overrides: object) -> AgentRefusal:
    values: dict[str, object] = {
        "schema_version": 1,
        "refusal_id": "refusal-1",
        "agent_id": "agent-1",
        "observation_id": "observation-1",
        "local_state_version": 4,
        "target_requirement_id": "sources",
        "reason_code": RefusalReason.INSUFFICIENT_EVIDENCE,
        "bounded_explanation": "The visible sources cannot support the claim.",
        "retry_conditions": ("new-source-evidence",),
    }
    values.update(overrides)
    return AgentRefusal(**values)


@pytest.mark.parametrize(
    "factory",
    (_observation, _intent, _bid, _refusal),
)
def test_local_agency_contracts_reject_unknown_schema_versions(factory) -> None:
    with pytest.raises(ValueError, match="schema_version must be 1"):
        factory(schema_version=2)


def test_local_field_observation_validates_versions_identity_and_lifetime() -> None:
    with pytest.raises(ValueError, match="agent_id"):
        _observation(agent_id=" ")
    with pytest.raises(ValueError, match="requirement_schema_version"):
        _observation(requirement_schema_version=0)
    with pytest.raises(ValueError, match="public_state_revision"):
        _observation(public_state_revision=-1)
    with pytest.raises(ValueError, match="expires_at must be after created_at"):
        _observation(expires_at="2026-07-30T08:59:00+08:00")


def test_intent_validates_observation_parent_audience_and_expiry() -> None:
    observation = _observation()

    _intent().validate_against(
        observation,
        at="2026-07-30T09:02:00+08:00",
    )

    with pytest.raises(ValueError, match="observation_id"):
        _intent(observation_id="observation-other").validate_against(observation)
    with pytest.raises(ValueError, match="agent_id"):
        _intent(agent_id="agent-2").validate_against(observation)
    with pytest.raises(ValueError, match="target_requirement_id"):
        _intent(target_requirement_id="hidden").validate_against(observation)
    with pytest.raises(ValueError, match="observation has expired"):
        _intent().validate_against(
            observation,
            at="2026-07-30T09:05:00+08:00",
        )
    with pytest.raises(ValueError, match="cannot outlive"):
        _intent(expires_at="2026-07-30T09:06:00+08:00").validate_against(
            observation
        )


def test_bid_requires_cost_bounds_and_enforces_parent_and_budget_limits() -> None:
    observation = _observation()
    intent = _intent()

    with pytest.raises(ValueError, match="estimated_cost_vector cannot be empty"):
        _bid(estimated_cost_vector=())
    with pytest.raises(ValueError, match="requested_budget_vector cannot be empty"):
        _bid(requested_budget_vector=())
    with pytest.raises(ValueError, match="target_requirement_id"):
        _bid(target_requirement_id="")

    _bid().validate_against(
        intent,
        observation,
        run_budget=(ResourceAmount("tokens", 500),),
    )

    with pytest.raises(ValueError, match="intent_id"):
        _bid(intent_id="intent-other").validate_against(intent, observation)
    with pytest.raises(ValueError, match="agent_id"):
        _bid(agent_id="agent-2").validate_against(intent, observation)
    with pytest.raises(ValueError, match="target_requirement_id"):
        _bid(target_requirement_id="answer").validate_against(intent, observation)
    with pytest.raises(ValueError, match="intent resource bound"):
        _bid(
            requested_budget_vector=(ResourceAmount("tokens", 301),)
        ).validate_against(intent, observation)
    with pytest.raises(ValueError, match="run budget"):
        _bid(
            requested_budget_vector=(ResourceAmount("tokens", 260),)
        ).validate_against(
            intent,
            observation,
            run_budget=(ResourceAmount("tokens", 250),),
        )


def test_refusal_is_first_class_and_validates_parent_audience() -> None:
    observation = _observation()
    _refusal().validate_against(observation)

    with pytest.raises(ValueError, match="reason_code"):
        _refusal(reason_code="not-a-reason")
    with pytest.raises(ValueError, match="retry_conditions cannot be empty"):
        _refusal(retry_conditions=())
    with pytest.raises(ValueError, match="agent_id"):
        _refusal(agent_id="agent-2").validate_against(observation)
    with pytest.raises(ValueError, match="observation_id"):
        _refusal(observation_id="observation-other").validate_against(observation)


def test_local_agency_contracts_have_deterministic_round_trip_serialization() -> None:
    contracts = (_observation(), _intent(), _bid(), _refusal())

    for contract in contracts:
        encoded = contract.to_json()
        assert encoded == contract.to_json()
        assert encoded == json.dumps(
            contract.to_dict(),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        restored = type(contract).from_dict(json.loads(encoded))
        assert restored == contract
        assert restored.to_json() == encoded
