from __future__ import annotations

import json
from dataclasses import replace

import pytest

from biofield.admission import ActionToolPolicy, AdmissionPolicy, resolve_admission
from biofield.commitment import (
    initial_commitment_lifecycle,
    transition_commitment,
)
from biofield.communication import (
    CommunicationEdgePermission,
    CommunicationEdgeUsage,
    CommunicationGovernanceError,
    CommunicationPolicy,
    admit_communication_offer,
    admit_communication_request,
    consume_communication,
    deliver_communication,
    record_communication_receipt,
)
from biofield.contracts import (
    AgentBid,
    AgentIntent,
    CommitmentStatus,
    CommunicationOffer,
    CommunicationPermit,
    CommunicationRequest,
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
        requirement_schema_version=1,
        public_state_revision=1,
        visible_requirement_signals=("sources",),
        congestion_signals=(),
        resource_terms=(ResourceAmount("tokens", 100),),
        risk_flags=(),
        source_event_ids=("event-1",),
        field_policy_version="field-v1",
        created_at="2026-07-30T09:00:00+08:00",
        expires_at="2026-07-30T09:05:00+08:00",
    )


def _commitment():
    observation = _observation()
    intent = AgentIntent(
        schema_version=1,
        intent_id="intent-1",
        agent_id="agent-1",
        observation_id=observation.observation_id,
        local_state_version=0,
        target_requirement_id="sources",
        proposed_action_family="fixture_lookup",
        expected_evidence_type="source-record",
        expected_marginal_progress=0.4,
        confidence=0.7,
        uncertainty=0.3,
        requested_resource_bounds=(ResourceAmount("tokens", 100),),
        dependency_refs=(),
        expires_at="2026-07-30T09:04:00+08:00",
    )
    bid = AgentBid(
        schema_version=1,
        bid_id="bid-1",
        agent_id="agent-1",
        intent_id=intent.intent_id,
        observation_id=observation.observation_id,
        target_requirement_id="sources",
        capacity_commitment=1,
        estimated_cost_vector=(ResourceAmount("tokens", 50),),
        requested_budget_vector=(ResourceAmount("tokens", 100),),
        expected_completion_window=(
            "2026-07-30T09:01:00+08:00",
            "2026-07-30T09:03:00+08:00",
        ),
        duplication_tolerance=0,
        communication_needs=("agent-2",),
    )
    grant = ResourceEvent(
        event_id="grant-1",
        operation=ResourceOperation.GRANT,
        resource_type="tokens",
        amount=100,
        source_account=SHARED_POOL,
        target_account=agent_escrow_account("agent-1"),
        idempotency_key="grant-1",
    )
    decision = resolve_admission(
        bid=bid,
        intent=intent,
        observation=observation,
        resource_grants=(grant,),
        run_budget=(ResourceAmount("tokens", 100),),
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


def _policy() -> CommunicationPolicy:
    return CommunicationPolicy(
        schema_version=1,
        policy_version="communication-v1",
        edge_permissions=(
            CommunicationEdgePermission(
                sender_agent_id="agent-1",
                receiver_agent_id="agent-2",
                allowed_payload_schemas=("evidence-summary-v1",),
                max_payload_bytes=256,
                max_messages=2,
            ),
            CommunicationEdgePermission(
                sender_agent_id="agent-2",
                receiver_agent_id="agent-1",
                allowed_payload_schemas=("evidence-summary-v1",),
                max_payload_bytes=256,
                max_messages=2,
            ),
        ),
    )


def _offer(**overrides: object) -> CommunicationOffer:
    commitment = _commitment()
    values: dict[str, object] = {
        "schema_version": 1,
        "offer_id": "offer-1",
        "sender_agent_id": "agent-1",
        "observation_id": "observation-1",
        "commitment_id": commitment.commitment_id,
        "related_requirement_id": "sources",
        "intended_audience": ("agent-2",),
        "payload_schema": "evidence-summary-v1",
        "payload_size_bytes": 128,
        "evidence_refs": ("evidence-1",),
        "byte_budget": 200,
        "created_at": "2026-07-30T09:01:00+08:00",
        "expires_at": "2026-07-30T09:02:00+08:00",
        "causal_parent_ids": (
            "observation-1",
            commitment.commitment_id,
            "evidence-1",
        ),
        "issuer": GovernanceIssuer.AGENT_PROPOSAL,
    }
    values.update(overrides)
    return CommunicationOffer(**values)


def _request(**overrides: object) -> CommunicationRequest:
    commitment = _commitment()
    values: dict[str, object] = {
        "schema_version": 1,
        "request_id": "request-1",
        "requester_agent_id": "agent-1",
        "intended_sender_agent_id": "agent-2",
        "observation_id": "observation-1",
        "commitment_id": commitment.commitment_id,
        "related_requirement_id": "sources",
        "requested_payload_schema": "evidence-summary-v1",
        "max_payload_bytes": 128,
        "evidence_refs": ("evidence-gap-1",),
        "created_at": "2026-07-30T09:01:00+08:00",
        "expires_at": "2026-07-30T09:02:00+08:00",
        "causal_parent_ids": (
            "observation-1",
            commitment.commitment_id,
            "evidence-gap-1",
        ),
        "issuer": GovernanceIssuer.AGENT_PROPOSAL,
    }
    values.update(overrides)
    return CommunicationRequest(**values)


def test_offer_and_request_are_canonical_agent_proposals() -> None:
    for proposal in (_offer(), _request()):
        encoded = proposal.to_json()
        assert type(proposal).from_dict(json.loads(encoded)) == proposal
        payload = proposal.to_dict()
        payload["issuer"] = GovernanceIssuer.HARNESS_ADMISSION
        with pytest.raises(ValueError, match="Agent proposal"):
            type(proposal).from_dict(payload)


def test_offer_admission_is_deterministic_and_harness_owned() -> None:
    commitment = _commitment()
    kwargs = {
        "offer": _offer(
            commitment_id=commitment.commitment_id,
            causal_parent_ids=(
                "observation-1",
                commitment.commitment_id,
                "evidence-1",
            ),
        ),
        "observation": _observation(),
        "commitment": commitment,
        "lifecycle": initial_commitment_lifecycle(commitment),
        "policy": _policy(),
        "edge_usage": (),
        "at": "2026-07-30T09:01:10+08:00",
        "run_finalized": False,
    }
    first = admit_communication_offer(**kwargs)
    second = admit_communication_offer(**kwargs)

    assert first == second
    assert first.issuer is GovernanceIssuer.HARNESS_ADMISSION
    assert first.sender_agent_id == "agent-1"
    assert first.receiver_agent_ids == ("agent-2",)
    assert CommunicationPermit.from_dict(json.loads(first.to_json())) == first


def test_request_admission_reverses_edge_direction_for_response() -> None:
    commitment = _commitment()
    permit = admit_communication_request(
        request=_request(
            commitment_id=commitment.commitment_id,
            causal_parent_ids=(
                "observation-1",
                commitment.commitment_id,
                "evidence-gap-1",
            ),
        ),
        observation=_observation(),
        commitment=commitment,
        lifecycle=initial_commitment_lifecycle(commitment),
        policy=_policy(),
        edge_usage=(),
        at="2026-07-30T09:01:10+08:00",
        run_finalized=False,
    )

    assert permit.sender_agent_id == "agent-2"
    assert permit.receiver_agent_ids == ("agent-1",)


def test_communication_permit_cannot_outlive_its_observation() -> None:
    commitment = _commitment()
    observation = replace(
        _observation(),
        expires_at="2026-07-30T09:01:30+08:00",
    )
    permit = admit_communication_offer(
        offer=_offer(
            commitment_id=commitment.commitment_id,
            causal_parent_ids=(
                observation.observation_id,
                commitment.commitment_id,
                "evidence-1",
            ),
        ),
        observation=observation,
        commitment=commitment,
        lifecycle=initial_commitment_lifecycle(commitment),
        policy=_policy(),
        edge_usage=(),
        at="2026-07-30T09:01:10+08:00",
        run_finalized=False,
    )

    assert permit.expires_at == observation.expires_at


def test_communication_rejects_bad_audience_schema_budget_quota_and_parent() -> None:
    commitment = _commitment()
    common = {
        "observation": _observation(),
        "commitment": commitment,
        "lifecycle": initial_commitment_lifecycle(commitment),
        "policy": _policy(),
        "edge_usage": (),
        "at": "2026-07-30T09:01:10+08:00",
        "run_finalized": False,
    }
    with pytest.raises(CommunicationGovernanceError, match="permission"):
        admit_communication_offer(
            offer=_offer(
                commitment_id=commitment.commitment_id,
                intended_audience=("agent-3",),
                causal_parent_ids=(
                    "observation-1",
                    commitment.commitment_id,
                    "evidence-1",
                ),
            ),
            **common,
        )
    with pytest.raises(CommunicationGovernanceError, match="schema"):
        admit_communication_offer(
            offer=_offer(
                commitment_id=commitment.commitment_id,
                payload_schema="free-text",
                causal_parent_ids=(
                    "observation-1",
                    commitment.commitment_id,
                    "evidence-1",
                ),
            ),
            **common,
        )
    with pytest.raises(ValueError, match="byte_budget"):
        _offer(payload_size_bytes=201)
    with pytest.raises(CommunicationGovernanceError, match="quota"):
        admit_communication_offer(
            offer=_offer(
                commitment_id=commitment.commitment_id,
                causal_parent_ids=(
                    "observation-1",
                    commitment.commitment_id,
                    "evidence-1",
                ),
            ),
            **{
                **common,
                "edge_usage": (
                    CommunicationEdgeUsage("agent-1", "agent-2", 2),
                ),
            },
        )
    with pytest.raises(CommunicationGovernanceError, match="commitment_id"):
        admit_communication_offer(
            offer=_offer(
                commitment_id="commitment-other",
                causal_parent_ids=(
                    "observation-1",
                    "commitment-other",
                    "evidence-1",
                ),
            ),
            **common,
        )


def test_expired_finalized_or_terminal_communication_is_rejected() -> None:
    commitment = _commitment()
    common = {
        "offer": _offer(
            commitment_id=commitment.commitment_id,
            causal_parent_ids=(
                "observation-1",
                commitment.commitment_id,
                "evidence-1",
            ),
        ),
        "observation": _observation(),
        "commitment": commitment,
        "lifecycle": initial_commitment_lifecycle(commitment),
        "policy": _policy(),
        "edge_usage": (),
    }
    with pytest.raises(CommunicationGovernanceError, match="expired"):
        admit_communication_offer(
            **common,
            at="2026-07-30T09:02:00+08:00",
            run_finalized=False,
        )
    with pytest.raises(CommunicationGovernanceError, match="finalized"):
        admit_communication_offer(
            **common,
            at="2026-07-30T09:01:10+08:00",
            run_finalized=True,
        )

    _, terminal = transition_commitment(
        commitment,
        common["lifecycle"],
        next_status=CommitmentStatus.COMPLETED,
        reason="done",
        at="2026-07-30T09:01:30+08:00",
        run_finalized=False,
    )
    with pytest.raises(CommunicationGovernanceError, match="not active"):
        admit_communication_offer(
            **{**common, "lifecycle": terminal},
            at="2026-07-30T09:01:40+08:00",
            run_finalized=False,
        )


def _permit():
    commitment = _commitment()
    offer = _offer(
        commitment_id=commitment.commitment_id,
        causal_parent_ids=(
            "observation-1",
            commitment.commitment_id,
            "evidence-1",
        ),
    )
    permit = admit_communication_offer(
        offer=offer,
        observation=_observation(),
        commitment=commitment,
        lifecycle=initial_commitment_lifecycle(commitment),
        policy=_policy(),
        edge_usage=(),
        at="2026-07-30T09:01:10+08:00",
        run_finalized=False,
    )
    return permit


def test_permit_drives_delivery_receipt_and_single_consumption() -> None:
    permit = _permit()
    payload = b"bounded evidence summary"
    delivery = deliver_communication(
        permit=permit,
        sender_agent_id="agent-1",
        receiver_agent_id="agent-2",
        payload_schema="evidence-summary-v1",
        payload=payload,
        message_count=1,
        resource_cost=(ResourceAmount("tokens", 3),),
        at="2026-07-30T09:01:20+08:00",
    )
    receipt = record_communication_receipt(
        permit=permit,
        delivery=delivery,
        receiver_agent_id="agent-2",
        at="2026-07-30T09:01:21+08:00",
    )
    consumption = consume_communication(
        permit=permit,
        delivery=delivery,
        receipt=receipt,
        consumer_agent_id="agent-2",
        consumed_receipt_ids=(),
        at="2026-07-30T09:01:22+08:00",
    )

    assert delivery.payload_size_bytes == len(payload)
    assert delivery.message_count == 1
    assert delivery.resource_cost == (ResourceAmount("tokens", 3),)
    assert receipt.delivery_id == delivery.delivery_id
    assert consumption.receipt_id == receipt.receipt_id
    for contract in (delivery, receipt, consumption):
        assert type(contract).from_dict(json.loads(contract.to_json())) == contract

    with pytest.raises(CommunicationGovernanceError, match="already consumed"):
        consume_communication(
            permit=permit,
            delivery=delivery,
            receipt=receipt,
            consumer_agent_id="agent-2",
            consumed_receipt_ids=(receipt.receipt_id,),
            at="2026-07-30T09:01:23+08:00",
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"sender_agent_id": "agent-2"}, "sender"),
        ({"receiver_agent_id": "agent-3"}, "receiver"),
        ({"payload": b"x" * 129}, "byte"),
        ({"message_count": 2}, "message"),
        ({"at": "2026-07-30T09:02:00+08:00"}, "expired"),
    ),
)
def test_delivery_fails_closed_outside_permit(overrides, message) -> None:
    values = {
        "permit": _permit(),
        "sender_agent_id": "agent-1",
        "receiver_agent_id": "agent-2",
        "payload_schema": "evidence-summary-v1",
        "payload": b"bounded evidence summary",
        "message_count": 1,
        "resource_cost": (ResourceAmount("tokens", 3),),
        "at": "2026-07-30T09:01:20+08:00",
    }
    values.update(overrides)
    with pytest.raises(CommunicationGovernanceError, match=message):
        deliver_communication(**values)


def test_forged_receipt_is_rejected_without_consumption() -> None:
    permit = _permit()
    delivery = deliver_communication(
        permit=permit,
        sender_agent_id="agent-1",
        receiver_agent_id="agent-2",
        payload_schema="evidence-summary-v1",
        payload=b"bounded evidence summary",
        message_count=1,
        resource_cost=(ResourceAmount("tokens", 3),),
        at="2026-07-30T09:01:20+08:00",
    )
    receipt = record_communication_receipt(
        permit=permit,
        delivery=delivery,
        receiver_agent_id="agent-2",
        at="2026-07-30T09:01:21+08:00",
    )
    forged = replace(receipt, payload_sha256="0" * 64)

    with pytest.raises(CommunicationGovernanceError, match="receipt"):
        consume_communication(
            permit=permit,
            delivery=delivery,
            receipt=forged,
            consumer_agent_id="agent-2",
            consumed_receipt_ids=(),
            at="2026-07-30T09:01:22+08:00",
        )
