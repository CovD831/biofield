from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Mapping

from .admission import (
    ActionToolPolicy,
    AdmissionPolicy,
    resolve_admission,
)
from .commitment import (
    authorize_action,
    initial_commitment_lifecycle,
    transition_commitment,
)
from .communication import (
    CommunicationConsumption,
    CommunicationDelivery,
    CommunicationEdgePermission,
    CommunicationGovernanceError,
    CommunicationPolicy,
    CommunicationReceipt,
    admit_communication_request,
    consume_communication,
    deliver_communication,
    record_communication_receipt,
)
from .contracts import (
    ActionObservation,
    ActionProposal,
    ActionStatus,
    ActiveAgentState,
    AgentBid,
    AgentCommitment,
    AgentCostContribution,
    AgentIntent,
    AgentRefusal,
    CentralPresetInfo,
    ClaimAuthority,
    CommitmentLifecycleSnapshot,
    CommitmentStatus,
    CommunicationEdgeRecord,
    CommunicationPermit,
    CommunicationRequest,
    DistributionCount,
    FeedbackDisposition,
    FeedbackEvent,
    FeedbackSourceKind,
    GovernanceIssuer,
    LocalFieldObservation,
    OrganizationSnapshot,
    RefusalReason,
    RequirementCommitmentLink,
    RequirementDelta,
    RequirementSpec,
    ResidualSnapshot,
    ResourceAmount,
    ResourceEvent,
    ResourceLimit,
    ResourceOperation,
    TaskSpec,
)
from .ledger import (
    SHARED_POOL,
    SPENT,
    ResourceLedger,
    agent_escrow_account,
    reserved_account,
)
from .local_runtime import (
    HarnessCycleError,
    HarnessRuntimeEvent,
    RuntimeEvidence,
    RuntimeIssuer,
    _canonical_hash,
    _ledger_totals,
)
from .multi_admission import (
    BidCandidate,
    MultiAdmissionPolicy,
    MultiAdmissionResult,
    resolve_multi_admission,
)
from .organization import build_organization_snapshot
from .residual import ResidualStateMachine

_TASK_ID = "gate-task-1"
_REQUIREMENT_ID = "sources"
_FIELD_EVENT_ID = "gate-field-v1"
_POLICY_VERSION = "private-state-policy-v1"


@dataclass(frozen=True, kw_only=True)
class PrivateAgentState:
    state_version: int
    collect_capability: float
    verify_capability: float
    caution: float
    consumed_evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "consumed_evidence_refs",
            tuple(self.consumed_evidence_refs),
        )
        if (
            isinstance(self.state_version, bool)
            or not isinstance(self.state_version, int)
            or self.state_version < 0
        ):
            raise ValueError("state_version must be non-negative")
        for field_name in (
            "collect_capability",
            "verify_capability",
            "caution",
        ):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0 <= value <= 1
            ):
                raise ValueError(f"{field_name} must be between zero and one")
        if len(set(self.consumed_evidence_refs)) != len(
            self.consumed_evidence_refs
        ):
            raise ValueError("consumed evidence references must be unique")

    def state_hash(self) -> str:
        return _canonical_hash(
            {
                "caution": self.caution,
                "collect_capability": self.collect_capability,
                "consumed_evidence_refs": self.consumed_evidence_refs,
                "state_version": self.state_version,
                "verify_capability": self.verify_capability,
            }
        )

    def consume(self, consumption_id: str) -> PrivateAgentState:
        if consumption_id in self.consumed_evidence_refs:
            raise HarnessCycleError("communication receipt was already consumed")
        return PrivateAgentState(
            state_version=self.state_version + 1,
            collect_capability=self.collect_capability,
            verify_capability=self.verify_capability,
            caution=self.caution,
            consumed_evidence_refs=(
                *self.consumed_evidence_refs,
                consumption_id,
            ),
        )


@dataclass(frozen=True, kw_only=True)
class ScriptedBehavior:
    behavior_kind: str
    intent: AgentIntent
    bid: AgentBid
    refusal: AgentRefusal | None


def shared_field_observation(agent_id: str) -> LocalFieldObservation:
    """Return an agent-addressed view of one non-prescriptive public Field."""

    return LocalFieldObservation(
        schema_version=1,
        observation_id=f"gate-observation-{agent_id}",
        agent_id=agent_id,
        task_id=_TASK_ID,
        requirement_schema_version=1,
        public_state_revision=0,
        visible_requirement_signals=(_REQUIREMENT_ID,),
        congestion_signals=("open-work",),
        resource_terms=(ResourceAmount("tokens", 100),),
        risk_flags=(),
        source_event_ids=(_FIELD_EVENT_ID,),
        field_policy_version="non-prescriptive-field-v1",
        created_at="2026-07-30T10:00:00+08:00",
        expires_at="2026-07-30T10:10:00+08:00",
    )


def _field_content(observation: LocalFieldObservation) -> dict[str, object]:
    return {
        "congestion_signals": observation.congestion_signals,
        "created_at": observation.created_at,
        "expires_at": observation.expires_at,
        "field_policy_version": observation.field_policy_version,
        "requirement_schema_version": observation.requirement_schema_version,
        "resource_terms": tuple(
            item.to_dict() for item in observation.resource_terms
        ),
        "risk_flags": observation.risk_flags,
        "task_id": observation.task_id,
        "visible_requirement_signals": (
            observation.visible_requirement_signals
        ),
    }


def derive_scripted_behavior(
    *,
    agent_id: str,
    observation: LocalFieldObservation,
    private_state: PrivateAgentState,
) -> ScriptedBehavior:
    if observation.agent_id != agent_id:
        raise HarnessCycleError("Field observation has wrong audience")
    if private_state.consumed_evidence_refs:
        behavior_kind = "verify_evidence"
        action_family = "evidence.verify"
        expected_type = "verified-source"
        confidence = 0.95
        uncertainty = 0.05
        progress = 0.9
        requested = 30
        bid_prefix = "30"
        communication_needs: tuple[str, ...] = ()
    elif private_state.caution >= 0.8:
        behavior_kind = "refuse"
        action_family = "risk.probe"
        expected_type = "risk-assessment"
        confidence = 0.2
        uncertainty = 0.8
        progress = 0.1
        requested = 10
        bid_prefix = "00"
        communication_needs = ()
    elif private_state.verify_capability > private_state.collect_capability:
        behavior_kind = "request_evidence"
        action_family = "evidence.request"
        expected_type = "structured-source-evidence"
        confidence = 0.6
        uncertainty = 0.4
        progress = 0.4
        requested = 20
        bid_prefix = "10"
        communication_needs = ("structured-evidence-v1",)
    else:
        behavior_kind = "collect"
        action_family = "source.collect"
        expected_type = "source-record"
        confidence = 0.7
        uncertainty = 0.3
        progress = 0.6
        requested = 25
        bid_prefix = "20"
        communication_needs = ()
    behavior_id = f"{behavior_kind}-{agent_id}-v{private_state.state_version}"
    intent = AgentIntent(
        schema_version=1,
        intent_id=f"gate-intent-{behavior_id}",
        agent_id=agent_id,
        observation_id=observation.observation_id,
        local_state_version=private_state.state_version,
        target_requirement_id=_REQUIREMENT_ID,
        proposed_action_family=action_family,
        expected_evidence_type=expected_type,
        expected_marginal_progress=progress,
        confidence=confidence,
        uncertainty=uncertainty,
        requested_resource_bounds=(
            ResourceAmount("tokens", requested),
        ),
        dependency_refs=private_state.consumed_evidence_refs,
        expires_at="2026-07-30T10:09:00+08:00",
    )
    bid = AgentBid(
        schema_version=1,
        bid_id=f"bid-{bid_prefix}-{behavior_id}",
        agent_id=agent_id,
        intent_id=intent.intent_id,
        observation_id=observation.observation_id,
        target_requirement_id=_REQUIREMENT_ID,
        capacity_commitment=1,
        estimated_cost_vector=(
            ResourceAmount("tokens", requested),
        ),
        requested_budget_vector=(
            ResourceAmount("tokens", requested),
        ),
        expected_completion_window=(
            "2026-07-30T10:01:00+08:00",
            "2026-07-30T10:08:00+08:00",
        ),
        duplication_tolerance=0,
        communication_needs=communication_needs,
    )
    refusal = None
    if behavior_kind == "refuse":
        refusal = AgentRefusal(
            schema_version=1,
            refusal_id=f"gate-refusal-{agent_id}-v{private_state.state_version}",
            agent_id=agent_id,
            observation_id=observation.observation_id,
            local_state_version=private_state.state_version,
            target_requirement_id=_REQUIREMENT_ID,
            reason_code=RefusalReason.RISK,
            bounded_explanation="local risk threshold exceeded",
            retry_conditions=(
                "retry_not_before=2026-07-30T10:01:00+08:00",
                "retry_expires_at=2026-07-30T10:09:00+08:00",
            ),
        )
    return ScriptedBehavior(
        behavior_kind=behavior_kind,
        intent=intent,
        bid=bid,
        refusal=refusal,
    )


@dataclass(frozen=True, kw_only=True)
class GateEpisodeReplay:
    residual: ResidualSnapshot
    organization_snapshot: OrganizationSnapshot
    ledger_totals: Mapping[str, Mapping[str, str]]
    terminal_projection_sha256: str


@dataclass(frozen=True, kw_only=True)
class GateEpisodeResult(GateEpisodeReplay):
    events: tuple[HarnessRuntimeEvent, ...]
    initial_behaviors: Mapping[str, str]
    refusal: AgentRefusal
    before_communication: ScriptedBehavior
    after_communication: ScriptedBehavior
    takeover_commitment: AgentCommitment
    followup_commitment: AgentCommitment
    communication_permit: CommunicationPermit
    communication_delivery: CommunicationDelivery
    communication_receipt: CommunicationReceipt
    communication_consumption: CommunicationConsumption
    action: ActionObservation
    lifecycles: tuple[CommitmentLifecycleSnapshot, ...]


class _Writer:
    def __init__(self) -> None:
        self.events: list[HarnessRuntimeEvent] = []
        self._known: set[str] = set()

    def append(
        self,
        event_id: str,
        event_type: str,
        parents: tuple[str, ...],
        payload: Mapping[str, Any],
    ) -> HarnessRuntimeEvent:
        if event_id in self._known:
            raise HarnessCycleError(f"duplicate Gate event: {event_id}")
        if self.events and not parents:
            raise HarnessCycleError("non-root Gate event requires parents")
        if not set(parents) <= self._known:
            raise HarnessCycleError("Gate event has unknown causal parent")
        event = HarnessRuntimeEvent(
            event_id=event_id,
            event_type=event_type,
            event_schema_version=1,
            public_state_revision=len(self.events),
            causal_parent_ids=parents,
            payload=payload,
            payload_sha256=_canonical_hash(payload),
        )
        self.events.append(event)
        self._known.add(event_id)
        return event


def _policies() -> tuple[AdmissionPolicy, MultiAdmissionPolicy]:
    return (
        AdmissionPolicy(
            schema_version=1,
            policy_version="gate-admission-v1",
            action_tool_policies=(
                ActionToolPolicy("risk.probe", ("risk.inspect",)),
                ActionToolPolicy(
                    "evidence.request",
                    ("communication.request",),
                ),
                ActionToolPolicy("source.collect", ("fixture.read",)),
                ActionToolPolicy("evidence.verify", ("fixture.verify",)),
            ),
        ),
        MultiAdmissionPolicy(
            schema_version=1,
            policy_version="gate-multi-v1",
            max_concurrent_commitments=1,
            max_commitments_per_requirement=1,
            exploration_min_slots=0,
            tie_break_rule="bid_id_lexicographic",
        ),
    )


def _task(run_budget: tuple[ResourceAmount, ...]) -> TaskSpec:
    return TaskSpec(
        task_id=_TASK_ID,
        requirement_schema_version=1,
        goal="Produce one independently verified source",
        requirements=(
            RequirementSpec(_REQUIREMENT_ID, "Verify source evidence"),
        ),
        acceptance_rules=("accepted verifier Feedback is required",),
        resource_limits=tuple(
            ResourceLimit(item.resource_type, item.amount)
            for item in run_budget
        ),
    )


def _candidate(
    behavior: ScriptedBehavior,
    observation: LocalFieldObservation,
) -> BidCandidate:
    return BidCandidate(
        bid=behavior.bid,
        intent=behavior.intent,
        observation=observation,
        exploration_eligible=False,
    )


def _select(
    *,
    candidates: tuple[BidCandidate, ...],
    run_budget: tuple[ResourceAmount, ...],
    admission_policy: AdmissionPolicy,
    multi_policy: MultiAdmissionPolicy,
    at: str,
) -> MultiAdmissionResult:
    return resolve_multi_admission(
        candidates=candidates,
        run_budget=run_budget,
        reserved_resources=(),
        existing_requirement_loads=(),
        ready_requirement_ids=(_REQUIREMENT_ID,),
        current_concurrency=0,
        admission_policy=admission_policy,
        policy=multi_policy,
        at=at,
        run_finalized=False,
    )


def _selected(
    result: MultiAdmissionResult,
    candidates: tuple[BidCandidate, ...],
) -> BidCandidate:
    if len(result.admitted_bid_ids) != 1:
        raise HarnessCycleError("Gate episode requires exactly one admitted Bid")
    bid_id = result.admitted_bid_ids[0]
    return next(item for item in candidates if item.bid.bid_id == bid_id)


def _resource_event(
    *,
    event_id: str,
    operation: ResourceOperation,
    amount: ResourceAmount,
    source: str,
    target: str,
) -> ResourceEvent:
    return ResourceEvent(
        event_id=event_id,
        operation=operation,
        resource_type=amount.resource_type,
        amount=amount.amount,
        source_account=source,
        target_account=target,
        idempotency_key=event_id,
    )


def _grant_commitment(
    *,
    writer: _Writer,
    ledger: ResourceLedger,
    candidate: BidCandidate,
    parent_id: str,
    prefix: str,
    run_budget: tuple[ResourceAmount, ...],
    admission_policy: AdmissionPolicy,
    at: str,
) -> tuple[AgentCommitment, tuple[ResourceEvent, ...]]:
    grants: list[ResourceEvent] = []
    for amount in candidate.bid.requested_budget_vector:
        grant = _resource_event(
            event_id=f"{prefix}-grant-{candidate.bid.bid_id}-{amount.resource_type}",
            operation=ResourceOperation.GRANT,
            amount=amount,
            source=SHARED_POOL,
            target=agent_escrow_account(candidate.bid.agent_id),
        )
        ledger.apply(grant)
        grants.append(grant)
        writer.append(
            grant.event_id,
            f"{prefix}_resource_grant",
            (parent_id,),
            {"resource_event": grant.to_dict()},
        )
    decision = resolve_admission(
        bid=candidate.bid,
        intent=candidate.intent,
        observation=candidate.observation,
        resource_grants=tuple(grants),
        run_budget=run_budget,
        policy=admission_policy,
        at=at,
        run_finalized=False,
    )
    if decision.commitment is None:
        raise HarnessCycleError("Gate selected Bid failed commitment admission")
    commitment = decision.commitment
    writer.append(
        commitment.commitment_id,
        f"{prefix}_commitment",
        tuple(item.event_id for item in grants),
        {
            "admission_at": at,
            "commitment": commitment.to_dict(),
        },
    )
    return commitment, tuple(grants)


def _settle(
    *,
    writer: _Writer,
    ledger: ResourceLedger,
    agent_id: str,
    commitment_id: str,
    transition_id: str,
    prefix: str,
) -> str:
    settlement_id = f"{prefix}-settlement-{commitment_id}"
    returned = ledger.settle_abnormal_termination(
        agent_id,
        settlement_id=settlement_id,
    )
    writer.append(
        settlement_id,
        f"{prefix}_settlement",
        (transition_id,),
        {
            "agent_id": agent_id,
            "returned": {
                key: str(value) for key, value in sorted(returned.items())
            },
            "settlement_id": settlement_id,
        },
    )
    return settlement_id


def _organization(
    *,
    run_id: str,
    agents: tuple[str, ...],
    receiver_state_version: int,
    state_transition_id: str,
    commitments: tuple[AgentCommitment, ...],
    lifecycles: tuple[CommitmentLifecycleSnapshot, ...],
    permit: CommunicationPermit,
    delivery: CommunicationDelivery,
    consumption: CommunicationConsumption,
    public_state_revision: int,
    finished_at: str,
) -> OrganizationSnapshot:
    receiver = commitments[0].agent_id
    return build_organization_snapshot(
        run_id=run_id,
        task_id=_TASK_ID,
        checkpoint_id=f"checkpoint-{run_id}-gate",
        requirement_schema_version=1,
        public_state_revision=public_state_revision,
        active_agents=tuple(
            ActiveAgentState(
                agent_id=agent,
                state_version=(
                    receiver_state_version if agent == receiver else 0
                ),
                source_event_ids=(
                    (state_transition_id,) if agent == receiver else ()
                ),
            )
            for agent in agents
        ),
        requirement_commitments=tuple(
            RequirementCommitmentLink(
                requirement_id=_REQUIREMENT_ID,
                commitment_id=item.commitment_id,
                agent_id=item.agent_id,
            )
            for item in commitments
        ),
        communication_edges=(
            CommunicationEdgeRecord(
                edge_id=consumption.consumption_id,
                permit_id=permit.permit_id,
                sender_agent_id=delivery.sender_agent_id,
                receiver_agent_ids=(delivery.receiver_agent_id,),
                related_requirement_id=_REQUIREMENT_ID,
                payload_schema=delivery.payload_schema,
                message_count=delivery.message_count,
                payload_bytes=delivery.payload_size_bytes,
            ),
        ),
        duplicate_distribution=(),
        refusal_distribution=(
            DistributionCount(category="private_state_refusal", count=1),
        ),
        agent_cost_contributions=tuple(
            AgentCostContribution(
                agent_id=agent,
                actual_cost=(
                    (ResourceAmount("tokens", 23),)
                    if agent == receiver
                    else ()
                ),
                accepted_contribution=1 if agent == receiver else 0,
            )
            for agent in agents
        ),
        central_preset_info=CentralPresetInfo((), (), ()),
        experience_structural_changes=(),
        parent_event_ids=(
            *(item.commitment_id for item in commitments),
            *(item.transition_ids[0] for item in lifecycles),
            permit.permit_id,
            consumption.consumption_id,
            state_transition_id,
        ),
        builder_version="gate-episode-v1",
        created_at=finished_at,
    )


def run_gate_episode(
    *,
    run_id: str,
    private_states: Mapping[str, PrivateAgentState],
    run_budget: tuple[ResourceAmount, ...],
    initial_at: str,
    refused_at: str,
    takeover_at: str,
    requested_at: str,
    delivered_at: str,
    received_at: str,
    consumed_at: str,
    followup_at: str,
    finished_at: str,
) -> GateEpisodeResult:
    agents = tuple(sorted(private_states))
    if agents != ("agent-a", "agent-b", "agent-c"):
        raise HarnessCycleError(
            "Gate episode requires three opaque scripted Agent identities"
        )
    if set(item.resource_type for item in run_budget) != {"tokens"}:
        raise HarnessCycleError("Gate episode requires a tokens budget")
    task = _task(run_budget)
    admission_policy, multi_policy = _policies()
    observations = {
        agent: shared_field_observation(agent) for agent in agents
    }
    field_hashes = {
        _canonical_hash(_field_content(item))
        for item in observations.values()
    }
    if len(field_hashes) != 1:
        raise HarnessCycleError("Agents did not receive the same public Field")
    initial = {
        agent: derive_scripted_behavior(
            agent_id=agent,
            observation=observations[agent],
            private_state=private_states[agent],
        )
        for agent in agents
    }
    candidates = tuple(
        _candidate(initial[agent], observations[agent]) for agent in agents
    )
    initial_selection = _select(
        candidates=candidates,
        run_budget=run_budget,
        admission_policy=admission_policy,
        multi_policy=multi_policy,
        at=initial_at,
    )
    refused_candidate = _selected(initial_selection, candidates)
    refusal = initial[refused_candidate.bid.agent_id].refusal
    if refusal is None:
        raise HarnessCycleError(
            "public admission did not select the state-derived Refusal"
        )
    refusal.validate_against(refused_candidate.observation)
    remaining = tuple(
        item
        for item in candidates
        if item.bid.bid_id not in initial_selection.admitted_bid_ids
    )
    takeover_selection = _select(
        candidates=remaining,
        run_budget=run_budget,
        admission_policy=admission_policy,
        multi_policy=multi_policy,
        at=takeover_at,
    )
    takeover_candidate = _selected(takeover_selection, remaining)
    before = initial[takeover_candidate.bid.agent_id]
    if before.behavior_kind != "request_evidence":
        raise HarnessCycleError(
            "takeover behavior must request structured Evidence"
        )
    writer = _Writer()
    field_content = _field_content(observations[agents[0]])
    writer.append(
        _FIELD_EVENT_ID,
        "gate_field",
        (),
        {
            "field_content": field_content,
            "field_content_sha256": next(iter(field_hashes)),
            "non_prescriptive": True,
            "policy_version": _POLICY_VERSION,
        },
    )
    for agent in agents:
        state = private_states[agent]
        writer.append(
            f"local-state-projection-{agent}-v{state.state_version}",
            "local_state_projection",
            (_FIELD_EVENT_ID,),
            {
                "audience": "public",
                "local_state": {
                    "agent_id": agent,
                    "state_sha256": state.state_hash(),
                    "state_version": state.state_version,
                },
                "redaction": "private_values_omitted",
            },
        )
        writer.append(
            observations[agent].observation_id,
            "gate_field_observation",
            (_FIELD_EVENT_ID,),
            {
                "field_content_sha256": next(iter(field_hashes)),
                "observation": observations[agent].to_dict(),
            },
        )
        writer.append(
            initial[agent].intent.intent_id,
            "gate_initial_intent",
            (
                observations[agent].observation_id,
                f"local-state-projection-{agent}-v{state.state_version}",
            ),
            {
                "intent": initial[agent].intent.to_dict(),
                "policy_version": _POLICY_VERSION,
            },
        )
        writer.append(
            initial[agent].bid.bid_id,
            "gate_initial_bid",
            (initial[agent].intent.intent_id,),
            {"bid": initial[agent].bid.to_dict()},
        )
    writer.append(
        initial_selection.result_id,
        "gate_initial_admission",
        tuple(item.bid.bid_id for item in candidates),
        {
            "candidate_bid_ids": tuple(item.bid.bid_id for item in candidates),
            "result": initial_selection.to_dict(),
            "tie_break_rule": multi_policy.tie_break_rule,
        },
    )
    writer.append(
        refusal.refusal_id,
        "gate_agent_refusal",
        (initial_selection.result_id, refused_candidate.bid.bid_id),
        {
            "at": refused_at,
            "refusal": refusal.to_dict(),
        },
    )
    writer.append(
        takeover_selection.result_id,
        "gate_takeover_admission",
        (
            refusal.refusal_id,
            *(item.bid.bid_id for item in remaining),
        ),
        {
            "candidate_bid_ids": tuple(
                item.bid.bid_id for item in remaining
            ),
            "result": takeover_selection.to_dict(),
            "tie_break_rule": multi_policy.tie_break_rule,
        },
    )
    ledger = ResourceLedger(
        {
            item.resource_type: Decimal(str(item.amount))
            for item in run_budget
        }
    )
    takeover_commitment, _ = _grant_commitment(
        writer=writer,
        ledger=ledger,
        candidate=takeover_candidate,
        parent_id=takeover_selection.result_id,
        prefix="gate_takeover",
        run_budget=run_budget,
        admission_policy=admission_policy,
        at=takeover_at,
    )
    takeover_lifecycle = initial_commitment_lifecycle(
        takeover_commitment
    )
    collector_agent = next(
        agent
        for agent, behavior in initial.items()
        if behavior.behavior_kind == "collect"
    )
    gap_event_id = (
        f"evidence-gap-{takeover_candidate.bid.agent_id}-sources"
    )
    writer.append(
        gap_event_id,
        "gate_evidence_gap",
        (takeover_commitment.commitment_id,),
        {
            "evidence_status": "missing",
            "requirement_id": _REQUIREMENT_ID,
        },
    )
    request = CommunicationRequest(
        schema_version=1,
        request_id=f"gate-communication-request-{takeover_candidate.bid.agent_id}",
        requester_agent_id=takeover_candidate.bid.agent_id,
        intended_sender_agent_id=collector_agent,
        observation_id=takeover_candidate.observation.observation_id,
        commitment_id=takeover_commitment.commitment_id,
        related_requirement_id=_REQUIREMENT_ID,
        requested_payload_schema="structured-evidence-v1",
        max_payload_bytes=256,
        evidence_refs=(gap_event_id,),
        created_at=requested_at,
        expires_at="2026-07-30T10:05:00+08:00",
        causal_parent_ids=(
            takeover_candidate.observation.observation_id,
            takeover_commitment.commitment_id,
            gap_event_id,
        ),
        issuer=GovernanceIssuer.AGENT_PROPOSAL,
    )
    writer.append(
        request.request_id,
        "gate_communication_request",
        request.causal_parent_ids,
        {"request": request.to_dict()},
    )
    communication_policy = CommunicationPolicy(
        schema_version=1,
        policy_version="gate-communication-v1",
        edge_permissions=(
            CommunicationEdgePermission(
                sender_agent_id=collector_agent,
                receiver_agent_id=takeover_candidate.bid.agent_id,
                allowed_payload_schemas=("structured-evidence-v1",),
                max_payload_bytes=256,
                max_messages=1,
            ),
        ),
    )
    permit = admit_communication_request(
        request=request,
        observation=takeover_candidate.observation,
        commitment=takeover_commitment,
        lifecycle=takeover_lifecycle,
        policy=communication_policy,
        edge_usage=(),
        at=requested_at,
        run_finalized=False,
    )
    writer.append(
        permit.permit_id,
        "gate_communication_permit",
        (takeover_commitment.commitment_id, request.request_id),
        {
            "permit": permit.to_dict(),
            "policy": communication_policy.to_dict(),
        },
    )
    structured_payload = (
        b'{"claim":"source_verified","evidence_id":"structured-evidence-a",'
        b'"source_ref":"fixture://gate/source-1"}'
    )
    delivery = deliver_communication(
        permit=permit,
        sender_agent_id=collector_agent,
        receiver_agent_id=takeover_candidate.bid.agent_id,
        payload_schema="structured-evidence-v1",
        payload=structured_payload,
        message_count=1,
        resource_cost=(ResourceAmount("tokens", 3),),
        at=delivered_at,
    )
    writer.append(
        delivery.delivery_id,
        "gate_communication_delivery",
        (permit.permit_id,),
        {
            "content_hex": structured_payload.hex(),
            "delivery": delivery.to_dict(),
            "structured_evidence_id": "structured-evidence-a",
        },
    )
    receipt = record_communication_receipt(
        permit=permit,
        delivery=delivery,
        receiver_agent_id=takeover_candidate.bid.agent_id,
        at=received_at,
    )
    writer.append(
        receipt.receipt_id,
        "gate_communication_receipt",
        (delivery.delivery_id,),
        {"receipt": receipt.to_dict()},
    )
    consumption = consume_communication(
        permit=permit,
        delivery=delivery,
        receipt=receipt,
        consumer_agent_id=takeover_candidate.bid.agent_id,
        consumed_receipt_ids=(),
        at=consumed_at,
    )
    writer.append(
        consumption.consumption_id,
        "gate_communication_consumption",
        (receipt.receipt_id,),
        {"consumption": consumption.to_dict()},
    )
    communication_cost = delivery.resource_cost[0]
    communication_spend = _resource_event(
        event_id=f"gate-communication-spend-{delivery.delivery_id}-tokens",
        operation=ResourceOperation.SPEND,
        amount=communication_cost,
        source=agent_escrow_account(takeover_candidate.bid.agent_id),
        target=SPENT,
    )
    ledger.apply(communication_spend)
    writer.append(
        communication_spend.event_id,
        "gate_communication_resource_spend",
        (consumption.consumption_id,),
        {
            "delivery_id": delivery.delivery_id,
            "resource_event": communication_spend.to_dict(),
        },
    )
    before_private = private_states[takeover_candidate.bid.agent_id]
    after_private = before_private.consume(consumption.consumption_id)
    state_transition_id = (
        f"local-state-communication-{takeover_candidate.bid.agent_id}"
        f"-v{after_private.state_version}"
    )
    writer.append(
        state_transition_id,
        "local_state_communication_transition",
        (consumption.consumption_id,),
        {
            "audience": "public",
            "local_state_transition": {
                "after_sha256": after_private.state_hash(),
                "agent_id": takeover_candidate.bid.agent_id,
                "before_sha256": before_private.state_hash(),
                "next_state_version": after_private.state_version,
                "previous_state_version": before_private.state_version,
                "source_consumption_id": consumption.consumption_id,
            },
            "redaction": "private_values_omitted",
        },
    )
    takeover_transition, takeover_lifecycle = transition_commitment(
        takeover_commitment,
        takeover_lifecycle,
        next_status=CommitmentStatus.CANCELLED,
        reason="communication preparation completed; follow-up bid required",
        at=consumed_at,
        run_finalized=False,
    )
    writer.append(
        takeover_transition.transition_id,
        "gate_takeover_commitment_transition",
        (
            communication_spend.event_id,
            state_transition_id,
            consumption.consumption_id,
        ),
        {"transition": takeover_transition.to_dict()},
    )
    remaining_escrow = ledger.balance(
        "tokens",
        agent_escrow_account(takeover_candidate.bid.agent_id),
    )
    takeover_release = _resource_event(
        event_id=(
            f"gate-takeover-release-"
            f"{takeover_commitment.commitment_id}-tokens"
        ),
        operation=ResourceOperation.RETURN,
        amount=ResourceAmount(
            "tokens",
            (
                int(remaining_escrow)
                if remaining_escrow == remaining_escrow.to_integral()
                else float(remaining_escrow)
            ),
        ),
        source=agent_escrow_account(takeover_candidate.bid.agent_id),
        target=SHARED_POOL,
    )
    ledger.apply(takeover_release)
    writer.append(
        takeover_release.event_id,
        "gate_takeover_resource_release",
        (takeover_transition.transition_id,),
        {
            "commitment_id": takeover_commitment.commitment_id,
            "resource_event": takeover_release.to_dict(),
        },
    )
    after = derive_scripted_behavior(
        agent_id=takeover_candidate.bid.agent_id,
        observation=takeover_candidate.observation,
        private_state=after_private,
    )
    if (
        after.behavior_kind != "verify_evidence"
        or after.intent.dependency_refs != (consumption.consumption_id,)
    ):
        raise HarnessCycleError(
            "communication consumption did not change scripted behavior"
        )
    writer.append(
        after.intent.intent_id,
        "gate_post_communication_intent",
        (state_transition_id, consumption.consumption_id),
        {
            "intent": after.intent.to_dict(),
            "policy_version": _POLICY_VERSION,
        },
    )
    writer.append(
        after.bid.bid_id,
        "gate_post_communication_bid",
        (after.intent.intent_id,),
        {"bid": after.bid.to_dict()},
    )
    available = tuple(
        ResourceAmount(
            item.resource_type,
            float(ledger.balance(item.resource_type, SHARED_POOL)),
        )
        for item in run_budget
    )
    followup_candidate = _candidate(
        after,
        takeover_candidate.observation,
    )
    followup_selection = _select(
        candidates=(followup_candidate,),
        run_budget=available,
        admission_policy=admission_policy,
        multi_policy=multi_policy,
        at=followup_at,
    )
    writer.append(
        followup_selection.result_id,
        "gate_followup_admission",
        (takeover_release.event_id, after.bid.bid_id),
        {
            "available_budget": tuple(
                item.to_dict() for item in available
            ),
            "candidate_bid_ids": (after.bid.bid_id,),
            "result": followup_selection.to_dict(),
        },
    )
    followup_commitment, followup_grants = _grant_commitment(
        writer=writer,
        ledger=ledger,
        candidate=followup_candidate,
        parent_id=followup_selection.result_id,
        prefix="gate_followup",
        run_budget=available,
        admission_policy=admission_policy,
        at=followup_at,
    )
    followup_lifecycle = initial_commitment_lifecycle(
        followup_commitment
    )
    proposal = ActionProposal(
        schema_version=1,
        action_proposal_id=f"gate-action-proposal-{after.intent.intent_id}",
        agent_id=followup_commitment.agent_id,
        task_id=_TASK_ID,
        requirement_schema_version=1,
        commitment_id=followup_commitment.commitment_id,
        requirement_ids=(_REQUIREMENT_ID,),
        tool="fixture.verify",
        requested_resources=(ResourceAmount("tokens", 20),),
        input_refs=(consumption.consumption_id,),
        causal_parent_ids=(followup_commitment.commitment_id,),
        created_at=followup_at,
        expires_at=followup_commitment.deadline,
        issuer=GovernanceIssuer.AGENT_PROPOSAL,
    )
    authorization = authorize_action(
        proposal=proposal,
        commitment=followup_commitment,
        lifecycle=followup_lifecycle,
        resource_grants=followup_grants,
        at=followup_at,
        run_finalized=False,
    )
    writer.append(
        authorization.authorization_id,
        "gate_action_authorization",
        (followup_commitment.commitment_id,),
        {
            "action_proposal": proposal.to_dict(),
            "authorization": authorization.to_dict(),
        },
    )
    reserve = _resource_event(
        event_id="gate-followup-reserve-verify-tokens",
        operation=ResourceOperation.RESERVE,
        amount=ResourceAmount("tokens", 20),
        source=agent_escrow_account(followup_commitment.agent_id),
        target=reserved_account(followup_commitment.agent_id),
    )
    ledger.apply(reserve)
    writer.append(
        reserve.event_id,
        "gate_followup_resource_reserve",
        (authorization.authorization_id,),
        {"resource_event": reserve.to_dict()},
    )
    execution_id = "gate-execution-verify"
    evidence_id = "gate-evidence-verified"
    evidence_bytes = b"independently verified structured source"
    writer.append(
        execution_id,
        "gate_execution_result",
        (authorization.authorization_id, reserve.event_id),
        {
            "execution_result": {
                "action_status": ActionStatus.SUCCEEDED.value,
                "actual_cost": (
                    ResourceAmount("tokens", 20).to_dict(),
                ),
                "artifact_refs": ("artifact://gate/verified-source",),
                "evidence_id": evidence_id,
                "evidence_sha256": hashlib.sha256(
                    evidence_bytes
                ).hexdigest(),
                "execution_id": execution_id,
                "issuer": RuntimeIssuer.HARNESS_EXECUTOR.value,
            }
        },
    )
    action = ActionObservation(
        action_id="gate-action-verify",
        agent_id=followup_commitment.agent_id,
        requirement_ids=(_REQUIREMENT_ID,),
        input_refs=(
            followup_commitment.commitment_id,
            authorization.authorization_id,
            consumption.consumption_id,
        ),
        artifact_refs=("artifact://gate/verified-source",),
        evidence_refs=(evidence_id,),
        resource_cost=(ResourceAmount("tokens", 20),),
        started_at=followup_at,
        finished_at=finished_at,
        status=ActionStatus.SUCCEEDED,
    )
    writer.append(
        action.action_id,
        "gate_action",
        (execution_id,),
        {"action": action.to_dict()},
    )
    evidence = RuntimeEvidence(
        evidence_id=evidence_id,
        action_id=action.action_id,
        requirement_id=_REQUIREMENT_ID,
        content_sha256=hashlib.sha256(evidence_bytes).hexdigest(),
        artifact_refs=action.artifact_refs,
        provenance_refs=(
            action.action_id,
            authorization.authorization_id,
            consumption.consumption_id,
        ),
    )
    writer.append(
        evidence.evidence_id,
        "gate_evidence",
        (action.action_id,),
        {
            "content_hex": evidence_bytes.hex(),
            "evidence": evidence.to_dict(),
        },
    )
    verifier_id = "gate-verifier-decision"
    writer.append(
        verifier_id,
        "gate_verifier_decision",
        (evidence.evidence_id,),
        {
            "decision": {
                "confidence": 1.0,
                "decision_id": verifier_id,
                "disposition": FeedbackDisposition.ACCEPTED.value,
                "evidence_id": evidence.evidence_id,
                "issuer": RuntimeIssuer.HARNESS_VERIFIER.value,
                "verifier_authority": "episode-verifier-v1",
            }
        },
    )
    feedback = FeedbackEvent(
        feedback_id="gate-feedback-accepted",
        task_id=_TASK_ID,
        action_id=action.action_id,
        requirement_deltas=(
            RequirementDelta(
                requirement_id=_REQUIREMENT_ID,
                disposition=FeedbackDisposition.ACCEPTED,
                evidence_refs=(evidence.evidence_id,),
            ),
        ),
        source_kind=FeedbackSourceKind.VERIFIER,
        source_authority_by_claim_type=(
            ClaimAuthority(
                claim_type="requirement_disposition",
                authority="episode-verifier-v1",
            ),
        ),
        confidence=1.0,
        evidence_refs=(evidence.evidence_id,),
    )
    writer.append(
        feedback.feedback_id,
        "gate_feedback",
        (verifier_id,),
        {"feedback": feedback.to_dict()},
    )
    residual = ResidualStateMachine(task).apply_feedback(feedback)
    residual_event_id = f"gate-residual-{residual.revision}"
    writer.append(
        residual_event_id,
        "gate_residual",
        (feedback.feedback_id,),
        {"residual": residual.to_dict()},
    )
    action_spend = _resource_event(
        event_id="gate-followup-spend-verify-tokens",
        operation=ResourceOperation.SPEND,
        amount=ResourceAmount("tokens", 20),
        source=reserved_account(followup_commitment.agent_id),
        target=SPENT,
    )
    ledger.apply(action_spend)
    writer.append(
        action_spend.event_id,
        "gate_followup_resource_spend",
        (action.action_id,),
        {"resource_event": action_spend.to_dict()},
    )
    followup_transition, followup_lifecycle = transition_commitment(
        followup_commitment,
        followup_lifecycle,
        next_status=CommitmentStatus.COMPLETED,
        reason="communication-enabled verification accepted",
        at=finished_at,
        run_finalized=False,
    )
    writer.append(
        followup_transition.transition_id,
        "gate_followup_commitment_transition",
        (
            residual_event_id,
            action_spend.event_id,
            state_transition_id,
        ),
        {"transition": followup_transition.to_dict()},
    )
    followup_settlement = _settle(
        writer=writer,
        ledger=ledger,
        agent_id=followup_commitment.agent_id,
        commitment_id=followup_commitment.commitment_id,
        transition_id=followup_transition.transition_id,
        prefix="gate_followup",
    )
    totals = _ledger_totals(
        ledger,
        tuple(item.resource_type for item in run_budget),
    )
    lifecycles = (takeover_lifecycle, followup_lifecycle)
    organization = _organization(
        run_id=run_id,
        agents=agents,
        receiver_state_version=after_private.state_version,
        state_transition_id=state_transition_id,
        commitments=(takeover_commitment, followup_commitment),
        lifecycles=lifecycles,
        permit=permit,
        delivery=delivery,
        consumption=consumption,
        public_state_revision=len(writer.events),
        finished_at=finished_at,
    )
    writer.append(
        organization.snapshot_id,
        "gate_organization_snapshot",
        (
            *organization.parent_event_ids,
            followup_settlement,
        ),
        {"organization_snapshot": organization.to_dict()},
    )
    terminal_projection_sha256 = _canonical_hash(
        {
            "communication_consumption_id": consumption.consumption_id,
            "followup_behavior": after.behavior_kind,
            "ledger_totals": totals,
            "lifecycles": [item.to_dict() for item in lifecycles],
            "organization_snapshot_sha256": organization.snapshot_hash,
            "residual": residual.to_dict(),
            "state_sha256": after_private.state_hash(),
        }
    )
    writer.append(
        f"gate-terminal-{run_id}",
        "gate_terminal",
        (organization.snapshot_id, followup_settlement),
        {
            "terminal_projection_sha256": (
                terminal_projection_sha256
            )
        },
    )
    return GateEpisodeResult(
        events=tuple(writer.events),
        initial_behaviors=MappingProxyType(
            {
                agent: initial[agent].behavior_kind
                for agent in agents
            }
        ),
        refusal=refusal,
        before_communication=before,
        after_communication=after,
        takeover_commitment=takeover_commitment,
        followup_commitment=followup_commitment,
        communication_permit=permit,
        communication_delivery=delivery,
        communication_receipt=receipt,
        communication_consumption=consumption,
        action=action,
        lifecycles=lifecycles,
        residual=residual,
        organization_snapshot=organization,
        ledger_totals=totals,
        terminal_projection_sha256=terminal_projection_sha256,
    )


def _validate_stream(events: tuple[HarnessRuntimeEvent, ...]) -> None:
    consumptions = tuple(
        event
        for event in events
        if event.event_type == "gate_communication_consumption"
    )
    if len(consumptions) != 1:
        raise HarnessCycleError(
            "Gate episode requires exactly one communication consumption"
        )
    known: set[str] = set()
    terminal = False
    for index, event in enumerate(events):
        if terminal:
            raise HarnessCycleError("Gate event occurs after terminal")
        if event.public_state_revision != index:
            raise HarnessCycleError("Gate event revision is not contiguous")
        if event.event_id in known:
            raise HarnessCycleError("duplicate Gate event")
        if index and not set(event.causal_parent_ids) <= known:
            if event.public_state_revision >= consumptions[0].public_state_revision:
                raise HarnessCycleError(
                    "communication consumption is missing from behavior chain"
                )
            raise HarnessCycleError("Gate event has unknown parent")
        if _canonical_hash(event.payload) != event.payload_sha256:
            raise HarnessCycleError("Gate event payload hash mismatch")
        known.add(event.event_id)
        terminal = event.event_type == "gate_terminal"
    if not terminal:
        raise HarnessCycleError("Gate episode has no terminal event")


def replay_gate_episode(
    *,
    events: tuple[HarnessRuntimeEvent, ...],
    **inputs: Any,
) -> GateEpisodeReplay:
    materialized = tuple(events)
    _validate_stream(materialized)
    try:
        permit_event = next(
            event
            for event in materialized
            if event.event_type == "gate_communication_permit"
        )
        delivery_event = next(
            event
            for event in materialized
            if event.event_type == "gate_communication_delivery"
        )
        receipt_event = next(
            event
            for event in materialized
            if event.event_type == "gate_communication_receipt"
        )
        consumption_event = next(
            event
            for event in materialized
            if event.event_type == "gate_communication_consumption"
        )
        permit = CommunicationPermit.from_dict(
            permit_event.payload["permit"]
        )
        delivery = CommunicationDelivery.from_dict(
            delivery_event.payload["delivery"]
        )
        receipt = CommunicationReceipt.from_dict(
            receipt_event.payload["receipt"]
        )
        consumption = CommunicationConsumption.from_dict(
            consumption_event.payload["consumption"]
        )
        content = bytes.fromhex(delivery_event.payload["content_hex"])
        replayed_delivery = deliver_communication(
            permit=permit,
            sender_agent_id=delivery.sender_agent_id,
            receiver_agent_id=delivery.receiver_agent_id,
            payload_schema=delivery.payload_schema,
            payload=content,
            message_count=delivery.message_count,
            resource_cost=delivery.resource_cost,
            at=delivery.delivered_at,
        )
        replayed_receipt = record_communication_receipt(
            permit=permit,
            delivery=delivery,
            receiver_agent_id=receipt.receiver_agent_id,
            at=receipt.received_at,
        )
        replayed_consumption = consume_communication(
            permit=permit,
            delivery=delivery,
            receipt=receipt,
            consumer_agent_id=consumption.consumer_agent_id,
            consumed_receipt_ids=(),
            at=consumption.consumed_at,
        )
    except (
        KeyError,
        StopIteration,
        TypeError,
        ValueError,
        CommunicationGovernanceError,
    ) as error:
        raise HarnessCycleError(
            "communication consumption does not replay"
        ) from error
    if (
        replayed_delivery != delivery
        or replayed_receipt != receipt
        or replayed_consumption != consumption
        or consumption_event.causal_parent_ids != (receipt.receipt_id,)
    ):
        raise HarnessCycleError(
            "communication consumption does not replay"
        )
    expected = run_gate_episode(**inputs)
    if expected.events != materialized:
        raise HarnessCycleError(
            "Gate episode semantics do not fully replay"
        )
    return GateEpisodeReplay(
        residual=expected.residual,
        organization_snapshot=expected.organization_snapshot,
        ledger_totals=expected.ledger_totals,
        terminal_projection_sha256=expected.terminal_projection_sha256,
    )
