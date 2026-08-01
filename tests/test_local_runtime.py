from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from biofield.admission import ActionToolPolicy, AdmissionPolicy
from biofield.communication import (
    CommunicationEdgePermission,
    CommunicationGovernanceError,
    CommunicationPolicy,
)
from biofield.contracts import (
    ActionStatus,
    AgentBid,
    AgentIntent,
    CommitmentStatus,
    CommunicationOffer,
    FeedbackDisposition,
    GovernanceIssuer,
    LocalFieldObservation,
    LocalStateSnapshot,
    LocalStateUpdateProposal,
    LocalStateUpdateIssuer,
    RequirementSpec,
    RequirementStatus,
    ResourceAmount,
    ResourceLimit,
    TaskSpec,
    UpdateSurfaceManifest,
    UpdateSurfaceRule,
)
from biofield.local_runtime import (
    HarnessCycleError,
    RuntimeIssuer,
    ScriptedActionPlan,
    ScriptedCommunicationPlan,
    ScriptedExecutionResult,
    ScriptedVerifierDecision,
    project_organization_snapshot_from_events,
    replay_scripted_cycle,
    run_scripted_cycle,
)
from biofield.local_state import LocalStateGovernanceError
from biofield.multi_admission import (
    BidCandidate,
    MultiAdmissionPolicy,
    resolve_multi_admission,
)


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="task-1",
        requirement_schema_version=1,
        goal="Collect one verified source",
        requirements=(RequirementSpec("sources", "Collect sources"),),
        acceptance_rules=("sources must have accepted evidence",),
        resource_limits=(ResourceLimit("tokens", 100),),
    )


def _candidate() -> BidCandidate:
    observation = LocalFieldObservation(
        schema_version=1,
        observation_id="observation-agent-1",
        agent_id="agent-1",
        task_id="task-1",
        requirement_schema_version=1,
        public_state_revision=0,
        visible_requirement_signals=("sources",),
        congestion_signals=(),
        resource_terms=(ResourceAmount("tokens", 100),),
        risk_flags=(),
        source_event_ids=("task-started",),
        field_policy_version="field-v1",
        created_at="2026-07-30T09:00:00+08:00",
        expires_at="2026-07-30T09:05:00+08:00",
    )
    intent = AgentIntent(
        schema_version=1,
        intent_id="intent-agent-1",
        agent_id="agent-1",
        observation_id=observation.observation_id,
        local_state_version=0,
        target_requirement_id="sources",
        proposed_action_family="fixture_lookup",
        expected_evidence_type="source-record",
        expected_marginal_progress=0.5,
        confidence=0.6,
        uncertainty=0.4,
        requested_resource_bounds=(ResourceAmount("tokens", 80),),
        dependency_refs=(),
        expires_at="2026-07-30T09:04:00+08:00",
    )
    bid = AgentBid(
        schema_version=1,
        bid_id="bid-agent-1",
        agent_id="agent-1",
        intent_id=intent.intent_id,
        observation_id=observation.observation_id,
        target_requirement_id="sources",
        capacity_commitment=1,
        estimated_cost_vector=(ResourceAmount("tokens", 60),),
        requested_budget_vector=(ResourceAmount("tokens", 80),),
        expected_completion_window=(
            "2026-07-30T09:01:00+08:00",
            "2026-07-30T09:03:00+08:00",
        ),
        duplication_tolerance=0,
        communication_needs=(),
    )
    return BidCandidate(
        bid=bid,
        intent=intent,
        observation=observation,
        exploration_eligible=False,
    )


def _admission_policy() -> AdmissionPolicy:
    return AdmissionPolicy(
        schema_version=1,
        policy_version="admission-v1",
        action_tool_policies=(
            ActionToolPolicy("fixture_lookup", ("fixture.read",)),
        ),
    )


def _selection(candidate: BidCandidate):
    return resolve_multi_admission(
        candidates=(candidate,),
        run_budget=(ResourceAmount("tokens", 100),),
        reserved_resources=(),
        existing_requirement_loads=(),
        ready_requirement_ids=("sources",),
        current_concurrency=0,
        admission_policy=_admission_policy(),
        policy=MultiAdmissionPolicy(
            schema_version=1,
            policy_version="multi-v1",
            max_concurrent_commitments=1,
            max_commitments_per_requirement=1,
            exploration_min_slots=0,
            tie_break_rule="bid_id_lexicographic",
        ),
        at="2026-07-30T09:00:30+08:00",
        run_finalized=False,
    )


def _plan(**overrides: object) -> ScriptedActionPlan:
    values: dict[str, object] = {
        "plan_id": "plan-1",
        "tool": "fixture.read",
        "requested_resources": (ResourceAmount("tokens", 60),),
        "issuer": RuntimeIssuer.AGENT_PROPOSAL,
    }
    values.update(overrides)
    return ScriptedActionPlan(**values)


def _execution(**overrides: object) -> ScriptedExecutionResult:
    values: dict[str, object] = {
        "execution_id": "execution-1",
        "actual_cost": (ResourceAmount("tokens", 40),),
        "artifact_refs": ("artifact://source-1",),
        "evidence_id": "evidence-1",
        "evidence_bytes": b"verified source record",
        "action_status": ActionStatus.SUCCEEDED,
        "issuer": RuntimeIssuer.HARNESS_EXECUTOR,
    }
    values.update(overrides)
    return ScriptedExecutionResult(**values)


def _verifier(**overrides: object) -> ScriptedVerifierDecision:
    values: dict[str, object] = {
        "decision_id": "verifier-decision-1",
        "evidence_id": "evidence-1",
        "feedback_disposition": FeedbackDisposition.ACCEPTED,
        "confidence": 1.0,
        "evaluator_version": "scripted-verifier-v1",
        "issuer": RuntimeIssuer.HARNESS_VERIFIER,
    }
    values.update(overrides)
    return ScriptedVerifierDecision(**values)


def _manifest() -> UpdateSurfaceManifest:
    return UpdateSurfaceManifest(
        schema_version=1,
        manifest_id="manifest-1",
        run_id="run-1",
        manifest_version=1,
        mutable_surface_rules=(
            UpdateSurfaceRule(
                surface="local.capability",
                surface_schema_version=1,
                max_serialized_bytes=512,
                max_updates_per_run=4,
            ),
        ),
        frozen_surfaces=(
            "permissions",
            "residual",
            "goal_graph",
            "requirement_graph",
            "measurement_graph",
            "measurement_spec",
            "evaluator",
            "ledger",
            "event_schema",
            "experiment_score",
        ),
        promotion_rules=("feedback-event-only",),
        invalidation_rules=("feedback-invalidated",),
        rollback_policy="checkpoint-v1",
    )


def _state_snapshot() -> LocalStateSnapshot:
    return LocalStateSnapshot(
        schema_version=1,
        agent_id="agent-1",
        state_version=0,
        values={"local.capability.feedback_seen": False},
        source_update_ids=(),
    )


def _state_proposal() -> LocalStateUpdateProposal:
    return LocalStateUpdateProposal(
        schema_version=1,
        proposal_id="state-proposal-1",
        agent_id="agent-1",
        manifest_id="manifest-1",
        manifest_version=1,
        previous_state_version=0,
        destination_surface="local.capability",
        update_kind="feedback_assimilation",
        source_event_window=("feedback-plan-1",),
        changed_fields=("local.capability.feedback_seen",),
        proposed_values={"local.capability.feedback_seen": True},
        reversible=True,
        rollback_ref="checkpoint://run-1/agent-1/v0",
        issuer=LocalStateUpdateIssuer.AGENT_PROPOSAL,
    )


def _run(**overrides: object):
    candidate = _candidate()
    values: dict[str, object] = {
        "run_id": "run-1",
        "task": _task(),
        "selection": _selection(candidate),
        "candidate": candidate,
        "admission_policy": _admission_policy(),
        "multi_admission_policy": MultiAdmissionPolicy(
            schema_version=1,
            policy_version="multi-v1",
            max_concurrent_commitments=1,
            max_commitments_per_requirement=1,
            exploration_min_slots=0,
            tie_break_rule="bid_id_lexicographic",
        ),
        "plan": _plan(),
        "execution": _execution(),
        "verifier_decision": _verifier(),
        "initial_local_state": _state_snapshot(),
        "state_update_manifest": _manifest(),
        "state_update_proposal": _state_proposal(),
        "state_compiler_policy_version": "state-compiler-v1",
        "run_budget": (ResourceAmount("tokens", 100),),
        "admission_at": "2026-07-30T09:00:30+08:00",
        "action_at": "2026-07-30T09:01:10+08:00",
        "finished_at": "2026-07-30T09:01:20+08:00",
    }
    values.update(overrides)
    return run_scripted_cycle(**values)


def _replace_payload(event, payload: dict[str, object]):
    digest = hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return replace(event, payload=payload, payload_sha256=digest)


def _communication_inputs():
    commitment = _run().commitment
    payload = b"source evidence summary"
    offer = CommunicationOffer(
        schema_version=1,
        offer_id="runtime-offer-1",
        sender_agent_id="agent-1",
        observation_id="observation-agent-1",
        commitment_id=commitment.commitment_id,
        related_requirement_id="sources",
        intended_audience=("agent-2",),
        payload_schema="evidence-summary-v1",
        payload_size_bytes=len(payload),
        evidence_refs=("evidence-1",),
        byte_budget=128,
        created_at="2026-07-30T09:01:21+08:00",
        expires_at="2026-07-30T09:02:00+08:00",
        causal_parent_ids=(
            "observation-agent-1",
            commitment.commitment_id,
            "evidence-1",
        ),
        issuer=GovernanceIssuer.AGENT_PROPOSAL,
    )
    policy = CommunicationPolicy(
        schema_version=1,
        policy_version="communication-v1",
        edge_permissions=(
            CommunicationEdgePermission(
                sender_agent_id="agent-1",
                receiver_agent_id="agent-2",
                allowed_payload_schemas=("evidence-summary-v1",),
                max_payload_bytes=128,
                max_messages=1,
            ),
        ),
    )
    plan = ScriptedCommunicationPlan(
        sender_agent_id="agent-1",
        receiver_agent_id="agent-2",
        payload_schema="evidence-summary-v1",
        payload=payload,
        message_count=1,
        resource_cost=(ResourceAmount("tokens", 3),),
        admitted_at="2026-07-30T09:01:22+08:00",
        delivered_at="2026-07-30T09:01:23+08:00",
        received_at="2026-07-30T09:01:24+08:00",
        consumed_at="2026-07-30T09:01:25+08:00",
        issuer=RuntimeIssuer.AGENT_PROPOSAL,
    )
    return offer, policy, plan


def test_selected_bid_runs_real_single_cycle_and_settles_ledger() -> None:
    result = _run()

    assert result.residual.requirement("sources").status is (
        RequirementStatus.SATISFIED
    )
    assert result.lifecycle.status is CommitmentStatus.COMPLETED
    assert result.action.status is ActionStatus.SUCCEEDED
    assert result.action.input_refs[:2] == (
        result.commitment.commitment_id,
        result.authorization.authorization_id,
    )
    assert result.ledger_totals["tokens"]["spent"] == "40"
    assert result.ledger_totals["tokens"]["shared_pool"] == "60"
    assert result.ledger_totals["tokens"]["escrow"] == "0"
    assert result.ledger_totals["tokens"]["reserved"] == "0"
    assert result.organization_snapshot.requirement_commitments[0].commitment_id == (
        result.commitment.commitment_id
    )
    assert result.organization_snapshot.agent_cost_contributions[
        0
    ].accepted_contribution == 1.0
    assert result.local_state.state_version == 1
    assert result.local_state.values["local.capability.feedback_seen"] is True
    assert result.organization_snapshot.active_agents[0].state_version == 1
    assert result.organization_snapshot.active_agents[0].source_event_ids == (
        result.local_state_update.update_id,
    )
    assert project_organization_snapshot_from_events(
        events=result.events,
        run_id="run-1",
        checkpoint_id="checkpoint-run-1-1",
    ) == result.organization_snapshot


def test_cycle_and_replay_are_deterministic_with_versioned_parented_events() -> None:
    first = _run()
    second = _run()

    assert first.events == second.events
    assert first.terminal_projection_sha256 == second.terminal_projection_sha256
    assert first.events[0].causal_parent_ids == ()
    assert all(event.event_schema_version == 1 for event in first.events)
    assert all(
        event.public_state_revision == index
        for index, event in enumerate(first.events)
    )
    assert all(event.causal_parent_ids for event in first.events[1:])

    replayed = replay_scripted_cycle(
        task=_task(),
        run_budget=(ResourceAmount("tokens", 100),),
        events=first.events,
    )
    assert replayed.terminal_projection_sha256 == (
        first.terminal_projection_sha256
    )
    assert replayed.residual == first.residual
    assert replayed.ledger_totals == first.ledger_totals
    assert replayed.local_state.agent_id == first.local_state.agent_id
    assert replayed.local_state.state_version == first.local_state.state_version
    assert replayed.local_state.state_hash == first.local_state.state_hash()


def test_agent_plan_cannot_choose_feedback_or_impersonate_verifier() -> None:
    with pytest.raises(TypeError, match="feedback_disposition"):
        _plan(feedback_disposition=FeedbackDisposition.ACCEPTED)

    with pytest.raises(ValueError, match="Harness verifier"):
        _verifier(issuer=RuntimeIssuer.AGENT_PROPOSAL)


def test_public_events_redact_private_local_state_values() -> None:
    result = _run()
    encoded_events = json.dumps(
        [event.to_dict() for event in result.events],
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    assert "local.capability.feedback_seen" not in encoded_events
    assert '"committed_values"' not in encoded_events
    assert '"proposed_values"' not in encoded_events
    for event in result.events:
        if event.event_type.startswith("local_state_"):
            assert event.payload["audience"] == "public"
            assert event.payload["redaction"] == "private_values_omitted"


def test_unselected_or_overbudget_plan_fails_without_returning_partial_state() -> None:
    candidate = _candidate()
    rejected_selection = resolve_multi_admission(
        candidates=(candidate,),
        run_budget=(ResourceAmount("tokens", 100),),
        reserved_resources=(),
        existing_requirement_loads=(),
        ready_requirement_ids=("sources",),
        current_concurrency=1,
        admission_policy=_admission_policy(),
        policy=MultiAdmissionPolicy(
            schema_version=1,
            policy_version="multi-v1",
            max_concurrent_commitments=1,
            max_commitments_per_requirement=1,
            exploration_min_slots=0,
            tie_break_rule="bid_id_lexicographic",
        ),
        at="2026-07-30T09:00:30+08:00",
        run_finalized=False,
    )
    with pytest.raises(HarnessCycleError, match="not selected"):
        _run(selection=rejected_selection)

    with pytest.raises(ValueError, match="actual_cost"):
        _run(
            execution=_execution(
                actual_cost=(ResourceAmount("tokens", 61),),
            )
        )

    initial_state = _state_snapshot()
    frozen_surface_proposal = replace(
        _state_proposal(),
        destination_surface="residual",
        changed_fields=("residual.status",),
        proposed_values={"residual.status": "forged"},
    )
    with pytest.raises(LocalStateGovernanceError, match="not mutable"):
        _run(
            initial_local_state=initial_state,
            state_update_proposal=frozen_surface_proposal,
        )
    assert initial_state == _state_snapshot()


def test_rejected_feedback_does_not_claim_accepted_contribution() -> None:
    result = _run(
        verifier_decision=_verifier(
            feedback_disposition=FeedbackDisposition.REJECTED,
        )
    )

    assert result.residual.requirement("sources").status is RequirementStatus.UNMET
    assert result.organization_snapshot.agent_cost_contributions[
        0
    ].accepted_contribution == 0.0
    assert result.lifecycle.status is CommitmentStatus.CANCELLED
    assert result.residual.requirement(
        "sources"
    ).status is RequirementStatus.UNMET
    assert result.local_state_update.source_event_window == (
        result.feedback.feedback_id,
    )


def test_replay_rejects_tampered_payload_without_partial_projection() -> None:
    result = _run()
    action_index = next(
        index
        for index, event in enumerate(result.events)
        if event.event_type == "action"
    )
    tampered_event = replace(
        result.events[action_index],
        payload={"forged": True},
    )
    tampered = (
        *result.events[:action_index],
        tampered_event,
        *result.events[action_index + 1 :],
    )

    with pytest.raises(HarnessCycleError, match="payload_sha256"):
        replay_scripted_cycle(
            task=_task(),
            run_budget=(ResourceAmount("tokens", 100),),
            events=tampered,
        )


def test_replay_validates_redacted_local_state_hash_chain() -> None:
    result = _run()
    update_index = next(
        index
        for index, event in enumerate(result.events)
        if event.event_type == "local_state_update"
    )
    payload = result.events[update_index].to_dict()["payload"]
    payload["local_state_update"]["after_hash"] = "0" * 64
    tampered_event = _replace_payload(result.events[update_index], payload)
    tampered = (
        *result.events[:update_index],
        tampered_event,
        *result.events[update_index + 1 :],
    )

    with pytest.raises(HarnessCycleError, match="does not replay"):
        replay_scripted_cycle(
            task=_task(),
            run_budget=(ResourceAmount("tokens", 100),),
            events=tampered,
        )


def test_permitted_communication_is_delivered_consumed_and_accounted() -> None:
    offer, policy, communication_plan = _communication_inputs()
    result = _run(
        communication_offer=offer,
        communication_policy=policy,
        communication_plan=communication_plan,
    )

    assert result.communication_permit is not None
    assert result.communication_delivery is not None
    assert result.communication_receipt is not None
    assert result.communication_consumption is not None
    assert result.communication_consumption.receipt_id == (
        result.communication_receipt.receipt_id
    )
    assert result.ledger_totals["tokens"]["spent"] == "43"
    assert result.ledger_totals["tokens"]["shared_pool"] == "57"
    edge = result.organization_snapshot.communication_edges[0]
    assert edge.permit_id == result.communication_permit.permit_id
    assert edge.sender_agent_id == "agent-1"
    assert edge.receiver_agent_ids == ("agent-2",)
    assert edge.message_count == 1
    assert edge.payload_bytes == len(communication_plan.payload)
    sender_cost = next(
        contribution
        for contribution in result.organization_snapshot.agent_cost_contributions
        if contribution.agent_id == "agent-1"
    )
    assert sender_cost.actual_cost == (ResourceAmount("tokens", 43),)
    assert result.terminal_projection_sha256 != (
        _run().terminal_projection_sha256
    )
    delivery_event = next(
        event
        for event in result.events
        if event.event_type == "communication_delivery"
    )
    public_delivery = delivery_event.payload["delivery"]
    assert public_delivery["permit_id"] == result.communication_permit.permit_id
    assert public_delivery["sender_agent_id"] == "agent-1"
    assert public_delivery["receiver_agent_id"] == "agent-2"
    assert public_delivery["payload_size_bytes"] == len(
        communication_plan.payload
    )
    assert public_delivery["message_count"] == 1
    assert public_delivery["resource_cost"] == (
        {"resource_type": "tokens", "amount": 3},
    )
    assert any(
        event.event_type == "communication_resource_spend"
        for event in result.events
    )

    replayed = replay_scripted_cycle(
        task=_task(),
        run_budget=(ResourceAmount("tokens", 100),),
        events=result.events,
    )
    assert replayed.terminal_projection_sha256 == (
        result.terminal_projection_sha256
    )


def test_runtime_communication_rejects_over_budget_without_partial_state() -> None:
    offer, policy, communication_plan = _communication_inputs()
    initial_state = _state_snapshot()
    with pytest.raises(HarnessCycleError, match="communication.*authorization"):
        _run(
            initial_local_state=initial_state,
            communication_offer=offer,
            communication_policy=policy,
            communication_plan=replace(
                communication_plan,
                resource_cost=(ResourceAmount("tokens", 21),),
            ),
        )
    assert initial_state == _state_snapshot()

    with pytest.raises(CommunicationGovernanceError, match="message"):
        _run(
            initial_local_state=initial_state,
            communication_offer=offer,
            communication_policy=policy,
            communication_plan=replace(
                communication_plan,
                message_count=2,
            ),
        )
    assert initial_state == _state_snapshot()


def test_replay_rejects_forged_communication_receipt_semantics() -> None:
    offer, policy, communication_plan = _communication_inputs()
    result = _run(
        communication_offer=offer,
        communication_policy=policy,
        communication_plan=communication_plan,
    )
    receipt_index = next(
        index
        for index, event in enumerate(result.events)
        if event.event_type == "communication_receipt"
    )
    payload = result.events[receipt_index].to_dict()["payload"]
    payload["receipt"]["payload_sha256"] = "0" * 64
    tampered_event = _replace_payload(result.events[receipt_index], payload)
    tampered = (
        *result.events[:receipt_index],
        tampered_event,
        *result.events[receipt_index + 1 :],
    )

    with pytest.raises(HarnessCycleError, match="receipt"):
        replay_scripted_cycle(
            task=_task(),
            run_budget=(ResourceAmount("tokens", 100),),
            events=tampered,
        )


def test_replay_rejects_rehashed_communication_content_tamper() -> None:
    offer, policy, communication_plan = _communication_inputs()
    result = _run(
        communication_offer=offer,
        communication_policy=policy,
        communication_plan=communication_plan,
    )
    delivery_index = next(
        index
        for index, event in enumerate(result.events)
        if event.event_type == "communication_delivery"
    )
    payload = result.events[delivery_index].to_dict()["payload"]
    payload["content_hex"] = b"forged public payload".hex()
    tampered_event = _replace_payload(result.events[delivery_index], payload)
    tampered = (
        *result.events[:delivery_index],
        tampered_event,
        *result.events[delivery_index + 1 :],
    )

    with pytest.raises(HarnessCycleError, match="delivery"):
        replay_scripted_cycle(
            task=_task(),
            run_budget=(ResourceAmount("tokens", 100),),
            events=tampered,
        )


def test_replay_rejects_forged_action_authorization_authority() -> None:
    result = _run()
    authorization_index = next(
        index
        for index, event in enumerate(result.events)
        if event.event_type == "action_authorization"
    )
    payload = result.events[authorization_index].to_dict()["payload"]
    payload["authorization"]["issuer"] = GovernanceIssuer.AGENT_PROPOSAL.value
    forged = _replace_payload(
        result.events[authorization_index],
        payload,
    )
    events = (
        *result.events[:authorization_index],
        forged,
        *result.events[authorization_index + 1 :],
    )

    with pytest.raises(HarnessCycleError, match="action authorization"):
        replay_scripted_cycle(
            task=_task(),
            run_budget=(ResourceAmount("tokens", 100),),
            events=events,
        )
