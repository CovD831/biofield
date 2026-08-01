from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from .admission import ActionToolPolicy, AdmissionPolicy
from .contracts import (
    ActionStatus,
    AgentBid,
    AgentIntent,
    FeedbackDisposition,
    LocalFieldObservation,
    LocalStateSnapshot,
    LocalStateUpdateIssuer,
    LocalStateUpdateProposal,
    OrganizationSnapshot,
    RequirementSpec,
    ResourceAmount,
    ResourceLimit,
    TaskSpec,
    UpdateSurfaceManifest,
    UpdateSurfaceRule,
)
from .dispute_runtime import (
    IndependentRevalidationDecision,
    RevalidationEvidence,
    RevalidationIssuer,
    replay_disputed_revalidation,
    run_disputed_revalidation,
)
from .local_runtime import (
    HarnessRuntimeEvent,
    RuntimeIssuer,
    ScriptedActionPlan,
    ScriptedExecutionResult,
    ScriptedVerifierDecision,
    replay_scripted_cycle,
    run_scripted_cycle,
)
from .multi_admission import (
    BidCandidate,
    MultiAdmissionPolicy,
    resolve_multi_admission,
)


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _json_ready(value),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="governance-task",
        requirement_schema_version=1,
        goal="Collect one verified source",
        requirements=(RequirementSpec("sources", "Collect sources"),),
        acceptance_rules=("sources must have accepted evidence",),
        resource_limits=(ResourceLimit("tokens", 100),),
    )


def _candidate(
    *,
    action_family: str = "fixture_lookup",
    bid_id: str = "bid-governance",
) -> BidCandidate:
    observation = LocalFieldObservation(
        schema_version=1,
        observation_id=f"observation-{bid_id}",
        agent_id="agent-governance",
        task_id="governance-task",
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
        intent_id=f"intent-{bid_id}",
        agent_id=observation.agent_id,
        observation_id=observation.observation_id,
        local_state_version=0,
        target_requirement_id="sources",
        proposed_action_family=action_family,
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
        bid_id=bid_id,
        agent_id=observation.agent_id,
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
        policy_version="governance-admission-v1",
        action_tool_policies=(ActionToolPolicy("fixture_lookup", ("fixture.read",)),),
    )


def _multi_policy() -> MultiAdmissionPolicy:
    return MultiAdmissionPolicy(
        schema_version=1,
        policy_version="governance-multi-v1",
        max_concurrent_commitments=1,
        max_commitments_per_requirement=1,
        exploration_min_slots=0,
        tie_break_rule="bid_id_lexicographic",
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
        policy=_multi_policy(),
        at="2026-07-30T09:00:30+08:00",
        run_finalized=False,
    )


def _plan() -> ScriptedActionPlan:
    return ScriptedActionPlan(
        plan_id="plan-governance",
        tool="fixture.read",
        requested_resources=(ResourceAmount("tokens", 60),),
        issuer=RuntimeIssuer.AGENT_PROPOSAL,
    )


def _execution() -> ScriptedExecutionResult:
    return ScriptedExecutionResult(
        execution_id="execution-governance",
        actual_cost=(ResourceAmount("tokens", 40),),
        artifact_refs=("artifact://source-governance",),
        evidence_id="evidence-governance",
        evidence_bytes=b"verified source record",
        action_status=ActionStatus.SUCCEEDED,
        issuer=RuntimeIssuer.HARNESS_EXECUTOR,
    )


def _verifier(disposition: FeedbackDisposition) -> ScriptedVerifierDecision:
    return ScriptedVerifierDecision(
        decision_id="verifier-decision-governance",
        evidence_id="evidence-governance",
        feedback_disposition=disposition,
        confidence=0.5 if disposition is FeedbackDisposition.DISPUTED else 1.0,
        evaluator_version="governance-verifier-v1",
        issuer=RuntimeIssuer.HARNESS_VERIFIER,
    )


def _manifest(run_id: str) -> UpdateSurfaceManifest:
    return UpdateSurfaceManifest(
        schema_version=1,
        manifest_id="manifest-governance",
        run_id=run_id,
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


def _state() -> LocalStateSnapshot:
    return LocalStateSnapshot(
        schema_version=1,
        agent_id="agent-governance",
        state_version=0,
        values={"local.capability.feedback_seen": False},
        source_update_ids=(),
    )


def _proposal(
    *,
    proposal_id: str = "state-proposal-governance",
    source_event: str = "feedback-plan-governance",
) -> LocalStateUpdateProposal:
    return LocalStateUpdateProposal(
        schema_version=1,
        proposal_id=proposal_id,
        agent_id="agent-governance",
        manifest_id="manifest-governance",
        manifest_version=1,
        previous_state_version=0,
        destination_surface="local.capability",
        update_kind="feedback_assimilation",
        source_event_window=(source_event,),
        changed_fields=("local.capability.feedback_seen",),
        proposed_values={"local.capability.feedback_seen": True},
        reversible=True,
        rollback_ref="checkpoint://governance/agent/v0",
        issuer=LocalStateUpdateIssuer.AGENT_PROPOSAL,
    )


def _base(run_id: str) -> dict[str, Any]:
    candidate = _candidate()
    return {
        "run_id": run_id,
        "task": _task(),
        "selection": _selection(candidate),
        "candidate": candidate,
        "admission_policy": _admission_policy(),
        "multi_admission_policy": _multi_policy(),
        "plan": _plan(),
        "execution": _execution(),
        "initial_local_state": _state(),
        "state_update_manifest": _manifest(run_id),
        "quarantined_state_update_proposal": _proposal(),
        "state_compiler_policy_version": "state-compiler-v1",
        "run_budget": (ResourceAmount("tokens", 100),),
        "admission_at": "2026-07-30T09:00:30+08:00",
        "action_at": "2026-07-30T09:01:10+08:00",
        "finished_at": "2026-07-30T09:01:20+08:00",
    }


def _wrapper_event(
    *,
    index: int,
    event_type: str,
    payload: Mapping[str, Any],
    previous_id: str | None,
) -> HarnessRuntimeEvent:
    event_id = f"{event_type}-{index}"
    return HarnessRuntimeEvent(
        event_id=event_id,
        event_type=event_type,
        event_schema_version=1,
        public_state_revision=index,
        causal_parent_ids=(previous_id,) if previous_id is not None else (),
        payload=payload,
        payload_sha256=_hash(payload),
    )


@dataclass(frozen=True, kw_only=True)
class GovernanceEvidence:
    events: tuple[HarnessRuntimeEvent, ...]
    organization_snapshot: OrganizationSnapshot
    ledger_totals: Mapping[str, Mapping[str, str]]
    terminal_projection_sha256: str
    artifact: Mapping[str, Any]


def run_governance_evidence(run_id: str) -> GovernanceEvidence:
    base = _base(run_id)
    rejected = run_scripted_cycle(
        **{
            key: value
            for key, value in base.items()
            if key != "quarantined_state_update_proposal"
        },
        verifier_decision=_verifier(FeedbackDisposition.REJECTED),
        state_update_proposal=_proposal(),
    )
    rejected_replay = replay_scripted_cycle(
        task=_task(),
        run_budget=(ResourceAmount("tokens", 100),),
        events=rejected.events,
    )
    if rejected_replay.terminal_projection_sha256 != (
        rejected.terminal_projection_sha256
    ):
        raise ValueError("rejected Feedback path did not replay")
    disputed = run_disputed_revalidation(
        **base,
        disputed_verifier_decision=_verifier(FeedbackDisposition.DISPUTED),
        revalidation_evidence=RevalidationEvidence(
            evidence_id="revalidation-evidence-governance",
            content=b"independent source reproduction",
            artifact_refs=("artifact://independent-source",),
            provenance_refs=("verifier://independent-v2/run-1",),
            invalidates_evidence_ids=("evidence-governance",),
            resource_cost=(ResourceAmount("tokens", 5),),
            collected_at="2026-07-30T09:02:00+08:00",
            issuer=RevalidationIssuer.INDEPENDENT_EVIDENCE_COLLECTOR,
        ),
        revalidation_decision=IndependentRevalidationDecision(
            decision_id="revalidation-decision-governance",
            evidence_id="revalidation-evidence-governance",
            disposition=FeedbackDisposition.ACCEPTED,
            confidence=0.95,
            verifier_authority="independent-verifier-v2",
            invalidates_feedback_ids=("feedback-plan-governance",),
            invalidates_evidence_ids=("evidence-governance",),
            decided_at="2026-07-30T09:02:10+08:00",
            issuer=RevalidationIssuer.INDEPENDENT_VERIFIER,
        ),
        resolution_state_update_proposal=_proposal(
            proposal_id="state-proposal-revalidation-governance",
            source_event="feedback-revalidation-decision-governance",
        ),
    )
    disputed_replay = replay_disputed_revalidation(
        **base,
        disputed_verifier_decision=_verifier(FeedbackDisposition.DISPUTED),
        resolution_state_update_proposal=_proposal(
            proposal_id="state-proposal-revalidation-governance",
            source_event="feedback-revalidation-decision-governance",
        ),
        events=disputed.events,
    )
    if disputed_replay.terminal_projection_sha256 != (
        disputed.terminal_projection_sha256
    ):
        raise ValueError("disputed revalidation path did not replay")

    resource_candidate = _candidate(bid_id="bid-resource-insufficient")
    resource_result = resolve_multi_admission(
        candidates=(resource_candidate,),
        run_budget=(ResourceAmount("tokens", 100),),
        reserved_resources=(ResourceAmount("tokens", 50),),
        existing_requirement_loads=(),
        ready_requirement_ids=("sources",),
        current_concurrency=0,
        admission_policy=_admission_policy(),
        policy=_multi_policy(),
        at="2026-07-30T09:00:30+08:00",
        run_finalized=False,
    )
    illegal_candidate = _candidate(
        action_family="forbidden_action",
        bid_id="bid-illegal-proposal",
    )
    illegal_result = resolve_multi_admission(
        candidates=(illegal_candidate,),
        run_budget=(ResourceAmount("tokens", 100),),
        reserved_resources=(),
        existing_requirement_loads=(),
        ready_requirement_ids=("sources",),
        current_concurrency=0,
        admission_policy=_admission_policy(),
        policy=_multi_policy(),
        at="2026-07-30T09:00:30+08:00",
        run_finalized=False,
    )
    rejected_contribution = sum(
        float(item.accepted_contribution)
        for item in rejected.organization_snapshot.agent_cost_contributions
    )
    rejected_no_credit = (
        rejected_contribution == 0 and rejected.lifecycle.status.value != "completed"
    )
    disputed_revalidated = (
        disputed.quarantine.evidence_status == "quarantined"
        and disputed.quarantine.feedback_status == "quarantined"
        and disputed.feedback.requirement_deltas[0].disposition
        is FeedbackDisposition.ACCEPTED
    )
    resource_decision = resource_result.decision_for(resource_candidate.bid.bid_id)
    resource_rejected = (
        resource_decision.status.value == "rejected"
        and resource_decision.reason is not None
        and resource_decision.reason.value == "budget_limit"
        and not resource_result.admitted_bid_ids
    )
    illegal_decision = illegal_result.decision_for(illegal_candidate.bid.bid_id)
    illegal_zero_side_effects = (
        illegal_decision.status.value == "rejected"
        and illegal_decision.reason is not None
        and illegal_decision.reason.value == "action_not_allowed"
        and not illegal_result.admitted_bid_ids
    )
    coverage = {
        "disputed_quarantine_revalidation": disputed_revalidated,
        "illegal_proposal_zero_side_effects": illegal_zero_side_effects,
        "rejected_feedback_no_positive_credit": rejected_no_credit,
        "resource_insufficient_rejected": resource_rejected,
    }
    if not all(coverage.values()):
        raise ValueError("governance coverage path failed its native contract")

    artifact = {
        "schema_version": 1,
        "run_id": run_id,
        "rejected_events": [event.to_dict() for event in rejected.events],
        "disputed_events": [event.to_dict() for event in disputed.events],
        "resource_insufficient_result": resource_result.to_dict(),
        "illegal_proposal_result": illegal_result.to_dict(),
    }
    payloads = (
        (
            "governance_rejected_feedback",
            {
                "accepted_contribution": rejected_contribution,
                "native_event_bundle_sha256": _hash(artifact["rejected_events"]),
            },
        ),
        (
            "governance_dispute_quarantine",
            {
                "quarantine": disputed.quarantine.to_dict(),
                "native_event_bundle_sha256": _hash(artifact["disputed_events"]),
            },
        ),
        (
            "governance_revalidation",
            {
                "disposition": disputed.feedback.requirement_deltas[
                    0
                ].disposition.value,
                "terminal_projection_sha256": (disputed.terminal_projection_sha256),
            },
        ),
        (
            "governance_resource_insufficient",
            {"result": resource_result.to_dict()},
        ),
        (
            "governance_illegal_proposal",
            {"result": illegal_result.to_dict(), "side_effect_count": 0},
        ),
    )
    events: list[HarnessRuntimeEvent] = []
    for index, (event_type, payload) in enumerate(payloads):
        events.append(
            _wrapper_event(
                index=index,
                event_type=event_type,
                payload=payload,
                previous_id=events[-1].event_id if events else None,
            )
        )
    terminal_payload = {
        "coverage": coverage,
        "artifact_sha256": _hash(artifact),
    }
    events.append(
        _wrapper_event(
            index=len(events),
            event_type="governance_terminal",
            payload=terminal_payload,
            previous_id=events[-1].event_id,
        )
    )
    terminal_hash = _hash(
        {
            "events": [event.to_dict() for event in events],
            "ledger_totals": disputed.ledger_totals,
            "organization_snapshot": disputed.organization_snapshot.to_dict(),
        }
    )
    return GovernanceEvidence(
        events=tuple(events),
        organization_snapshot=disputed.organization_snapshot,
        ledger_totals=disputed.ledger_totals,
        terminal_projection_sha256=terminal_hash,
        artifact=artifact,
    )
