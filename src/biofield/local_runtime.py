from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any

from .admission import ActionToolPolicy, AdmissionPolicy, resolve_admission
from .commitment import (
    authorize_action,
    initial_commitment_lifecycle,
    replay_commitment_transitions,
    transition_commitment,
)
from .communication import (
    CommunicationConsumption,
    CommunicationDelivery,
    CommunicationGovernanceError,
    CommunicationPolicy,
    CommunicationReceipt,
    admit_communication_offer,
    consume_communication,
    deliver_communication,
    record_communication_receipt,
)
from .contracts import (
    ActionObservation,
    ActionProposal,
    ActionStatus,
    ActionAuthorization,
    ActiveAgentState,
    AgentBid,
    AgentCommitment,
    AgentCostContribution,
    AgentIntent,
    CentralPresetInfo,
    ClaimAuthority,
    CommitmentLifecycleSnapshot,
    CommitmentStatus,
    CommitmentTransition,
    CommunicationEdgeRecord,
    CommunicationOffer,
    CommunicationPermit,
    FeedbackDisposition,
    FeedbackEvent,
    FeedbackSourceKind,
    GovernanceIssuer,
    JsonContract,
    LocalFieldObservation,
    LocalStateSnapshot,
    LocalStateUpdate,
    LocalStateUpdateProposal,
    OrganizationSnapshot,
    DistributionCount,
    RequirementCommitmentLink,
    RequirementDelta,
    ResidualSnapshot,
    ResourceAmount,
    ResourceEvent,
    ResourceOperation,
    TaskSpec,
    UpdateSurfaceManifest,
)
from .ledger import (
    SHARED_POOL,
    SPENT,
    ResourceLedger,
    agent_escrow_account,
    reserved_account,
)
from .multi_admission import (
    BidCandidate,
    MultiAdmissionPolicy,
    MultiAdmissionResult,
    resolve_multi_admission,
)
from .local_state import (
    apply_local_state_update,
    compile_local_state_update,
)
from .organization import build_organization_snapshot
from .residual import ResidualStateMachine


class HarnessCycleError(ValueError):
    """A single-cycle Harness bridge rejected input or replay."""


class RuntimeIssuer(str, Enum):
    AGENT_PROPOSAL = "agent_proposal"
    HARNESS_EXECUTOR = "harness_executor"
    HARNESS_VERIFIER = "harness_verifier"


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw(item) for item in value]
    return value


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        _thaw(value),
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _contains_private_state_payload(value: Any) -> bool:
    forbidden_keys = {
        "changed_fields",
        "committed_values",
        "proposed_values",
        "values",
    }
    if isinstance(value, Mapping):
        if forbidden_keys.intersection(value):
            return True
        return any(
            _contains_private_state_payload(item) for item in value.values()
        )
    if isinstance(value, (tuple, list)):
        return any(_contains_private_state_payload(item) for item in value)
    return False


def _resource_map(values: tuple[ResourceAmount, ...]) -> dict[str, float]:
    result: dict[str, float] = {}
    for item in values:
        if item.resource_type in result:
            raise HarnessCycleError("duplicate resource types")
        result[item.resource_type] = item.amount
    return result


def _public_local_state(snapshot: LocalStateSnapshot) -> dict[str, Any]:
    return {
        "agent_id": snapshot.agent_id,
        "schema_version": snapshot.schema_version,
        "source_update_ids": snapshot.source_update_ids,
        "state_hash": snapshot.state_hash(),
        "state_version": snapshot.state_version,
    }


def _public_local_state_update(
    update: LocalStateUpdate,
    proposal: LocalStateUpdateProposal,
) -> dict[str, Any]:
    return {
        "after_hash": update.after_hash,
        "agent_id": update.agent_id,
        "before_hash": update.before_hash,
        "compiler_policy_version": update.compiler_policy_version,
        "destination_surface": update.destination_surface,
        "issuer": update.issuer.value,
        "manifest_id": update.manifest_id,
        "manifest_version": update.manifest_version,
        "next_state_version": update.next_state_version,
        "previous_state_version": update.previous_state_version,
        "proposal_id": update.proposal_id,
        "proposal_sha256": _canonical_hash(proposal.to_dict()),
        "source_event_window": update.source_event_window,
        "update_id": update.update_id,
        "update_kind": update.update_kind,
    }


@dataclass(frozen=True, kw_only=True)
class ScriptedActionPlan:
    plan_id: str
    tool: str
    requested_resources: tuple[ResourceAmount, ...]
    issuer: RuntimeIssuer

    def __post_init__(self) -> None:
        for field_name in ("plan_id", "tool"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
        object.__setattr__(
            self,
            "requested_resources",
            tuple(self.requested_resources),
        )
        if not _resource_map(self.requested_resources):
            raise ValueError("requested_resources cannot be empty")
        if self.issuer is not RuntimeIssuer.AGENT_PROPOSAL:
            raise ValueError("action plan issuer must be Agent proposal")


@dataclass(frozen=True, kw_only=True)
class ScriptedExecutionResult:
    execution_id: str
    actual_cost: tuple[ResourceAmount, ...]
    artifact_refs: tuple[str, ...]
    evidence_id: str
    evidence_bytes: bytes
    action_status: ActionStatus
    issuer: RuntimeIssuer

    def __post_init__(self) -> None:
        for field_name in ("execution_id", "evidence_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
        for field_name in (
            "actual_cost",
            "artifact_refs",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        _resource_map(self.actual_cost)
        if not self.evidence_bytes:
            raise ValueError("evidence_bytes cannot be empty")
        if not isinstance(self.action_status, ActionStatus):
            raise ValueError("action_status must be an ActionStatus")
        if self.issuer is not RuntimeIssuer.HARNESS_EXECUTOR:
            raise ValueError("execution result issuer must be Harness executor")


@dataclass(frozen=True, kw_only=True)
class ScriptedVerifierDecision:
    decision_id: str
    evidence_id: str
    feedback_disposition: FeedbackDisposition
    confidence: float
    evaluator_version: str
    issuer: RuntimeIssuer

    def __post_init__(self) -> None:
        for field_name in ("decision_id", "evidence_id", "evaluator_version"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
        if not isinstance(self.feedback_disposition, FeedbackDisposition):
            raise ValueError(
                "feedback_disposition must be a FeedbackDisposition"
            )
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not 0 <= self.confidence <= 1
        ):
            raise ValueError("confidence must be between 0 and 1")
        if self.issuer is not RuntimeIssuer.HARNESS_VERIFIER:
            raise ValueError("verifier decision issuer must be Harness verifier")


@dataclass(frozen=True, kw_only=True)
class ScriptedCommunicationPlan:
    sender_agent_id: str
    receiver_agent_id: str
    payload_schema: str
    payload: bytes
    message_count: int
    resource_cost: tuple[ResourceAmount, ...]
    admitted_at: str
    delivered_at: str
    received_at: str
    consumed_at: str
    issuer: RuntimeIssuer

    def __post_init__(self) -> None:
        for field_name in (
            "sender_agent_id",
            "receiver_agent_id",
            "payload_schema",
            "admitted_at",
            "delivered_at",
            "received_at",
            "consumed_at",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
        if self.sender_agent_id == self.receiver_agent_id:
            raise ValueError("communication endpoints must differ")
        if not isinstance(self.payload, bytes) or not self.payload:
            raise ValueError("payload must be non-empty bytes")
        if (
            isinstance(self.message_count, bool)
            or not isinstance(self.message_count, int)
            or self.message_count <= 0
        ):
            raise ValueError("message_count must be a positive integer")
        object.__setattr__(self, "resource_cost", tuple(self.resource_cost))
        if not _resource_map(self.resource_cost):
            raise ValueError("resource_cost cannot be empty")
        if self.issuer is not RuntimeIssuer.AGENT_PROPOSAL:
            raise ValueError("communication plan issuer must be Agent proposal")


@dataclass(frozen=True, kw_only=True)
class RuntimeEvidence(JsonContract):
    evidence_id: str
    action_id: str
    requirement_id: str
    content_sha256: str
    artifact_refs: tuple[str, ...]
    provenance_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("artifact_refs", "provenance_refs"):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        for field_name in ("evidence_id", "action_id", "requirement_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
        if (
            len(self.content_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.content_sha256
            )
        ):
            raise ValueError("content_sha256 must be a SHA-256 digest")
        if not self.provenance_refs:
            raise ValueError("provenance_refs cannot be empty")


@dataclass(frozen=True, kw_only=True)
class HarnessRuntimeEvent(JsonContract):
    event_id: str
    event_type: str
    event_schema_version: int
    public_state_revision: int
    causal_parent_ids: tuple[str, ...]
    payload: Mapping[str, Any]
    payload_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "causal_parent_ids",
            tuple(self.causal_parent_ids),
        )
        object.__setattr__(self, "payload", _freeze(self.payload))
        for field_name in ("event_id", "event_type"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
        if self.event_schema_version != 1:
            raise ValueError("event_schema_version must be 1")
        if (
            isinstance(self.public_state_revision, bool)
            or not isinstance(self.public_state_revision, int)
            or self.public_state_revision < 0
        ):
            raise ValueError(
                "public_state_revision must be a non-negative integer"
            )
        if (
            len(self.payload_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.payload_sha256
            )
        ):
            raise ValueError("payload_sha256 must be a SHA-256 digest")
        if self.event_type.startswith("local_state_"):
            if (
                self.payload.get("audience") != "public"
                or self.payload.get("redaction")
                != "private_values_omitted"
                or _contains_private_state_payload(self.payload)
            ):
                raise ValueError(
                    "public local-state event must omit private values"
                )


@dataclass(frozen=True, kw_only=True)
class PublicLocalStateProjection:
    agent_id: str
    state_version: int
    source_update_ids: tuple[str, ...]
    state_hash: str


@dataclass(frozen=True, kw_only=True)
class HarnessReplayProjection:
    residual: ResidualSnapshot
    local_state: PublicLocalStateProjection
    ledger_totals: Mapping[str, Mapping[str, str]]
    terminal_projection_sha256: str


@dataclass(frozen=True, kw_only=True)
class HarnessCycleResult:
    events: tuple[HarnessRuntimeEvent, ...]
    commitment: AgentCommitment
    authorization: ActionAuthorization
    action: ActionObservation
    evidence: RuntimeEvidence
    feedback: FeedbackEvent
    residual: ResidualSnapshot
    local_state_update: LocalStateUpdate
    local_state: LocalStateSnapshot
    communication_permit: CommunicationPermit | None
    communication_delivery: CommunicationDelivery | None
    communication_receipt: CommunicationReceipt | None
    communication_consumption: CommunicationConsumption | None
    lifecycle: CommitmentLifecycleSnapshot
    organization_snapshot: OrganizationSnapshot
    ledger_totals: Mapping[str, Mapping[str, str]]
    terminal_projection_sha256: str


class _EventWriter:
    def __init__(self) -> None:
        self.events: list[HarnessRuntimeEvent] = []
        self._ids: set[str] = set()

    def append(
        self,
        event_id: str,
        event_type: str,
        parents: tuple[str, ...],
        payload: Mapping[str, Any],
    ) -> HarnessRuntimeEvent:
        if event_id in self._ids:
            raise HarnessCycleError(f"duplicate runtime event ID: {event_id}")
        if self.events and not parents:
            raise HarnessCycleError("non-initial runtime event requires parents")
        missing = set(parents) - self._ids
        if missing:
            raise HarnessCycleError(
                "runtime event references missing parents: "
                + ",".join(sorted(missing))
            )
        frozen_payload = _freeze(payload)
        event = HarnessRuntimeEvent(
            event_id=event_id,
            event_type=event_type,
            event_schema_version=1,
            public_state_revision=len(self.events),
            causal_parent_ids=parents,
            payload=frozen_payload,
            payload_sha256=_canonical_hash(frozen_payload),
        )
        self.events.append(event)
        self._ids.add(event_id)
        return event


def _resource_event(
    *,
    event_id: str,
    operation: ResourceOperation,
    resource_type: str,
    amount: float,
    source: str,
    target: str,
) -> ResourceEvent:
    return ResourceEvent(
        event_id=event_id,
        operation=operation,
        resource_type=resource_type,
        amount=amount,
        source_account=source,
        target_account=target,
        idempotency_key=event_id,
    )


def _ledger_totals(
    ledger: ResourceLedger,
    resource_types: tuple[str, ...],
) -> Mapping[str, Mapping[str, str]]:
    result: dict[str, Mapping[str, str]] = {}
    for resource_type in sorted(set(resource_types)):
        totals = ledger.totals(resource_type)
        result[resource_type] = MappingProxyType(
            {
                "expected": str(totals.expected),
                "shared_pool": str(totals.shared_pool),
                "escrow": str(totals.escrow),
                "reserved": str(totals.reserved),
                "spent": str(totals.spent),
            }
        )
    return MappingProxyType(result)


def _terminal_hash(
    residual: ResidualSnapshot,
    local_state_hash: str,
    ledger_totals: Mapping[str, Mapping[str, str]],
    settlement: Mapping[str, str],
    lifecycle: CommitmentLifecycleSnapshot,
    organization_snapshot_hash: str,
) -> str:
    return _canonical_hash(
        {
            "commitment_lifecycle": lifecycle.to_dict(),
            "ledger_totals": ledger_totals,
            "local_state_hash": local_state_hash,
            "organization_snapshot_hash": organization_snapshot_hash,
            "residual": residual.to_dict(),
            "settlement": settlement,
        }
    )


def _preflight(
    *,
    run_id: str,
    task: TaskSpec,
    selection: MultiAdmissionResult,
    candidate: BidCandidate,
    admission_policy: AdmissionPolicy,
    multi_admission_policy: MultiAdmissionPolicy,
    admission_at: str,
    plan: ScriptedActionPlan,
    execution: ScriptedExecutionResult,
    verifier_decision: ScriptedVerifierDecision,
    initial_local_state: LocalStateSnapshot,
    state_update_manifest: UpdateSurfaceManifest,
    state_update_proposal: LocalStateUpdateProposal,
    communication_offer: CommunicationOffer | None,
    communication_policy: CommunicationPolicy | None,
    communication_plan: ScriptedCommunicationPlan | None,
    run_budget: tuple[ResourceAmount, ...],
) -> None:
    if candidate.bid.bid_id not in selection.admitted_bid_ids:
        raise HarnessCycleError("candidate Bid was not selected")
    replayed_selection = resolve_multi_admission(
        candidates=(candidate,),
        run_budget=run_budget,
        reserved_resources=(),
        existing_requirement_loads=(),
        ready_requirement_ids=(candidate.bid.target_requirement_id,),
        current_concurrency=0,
        admission_policy=admission_policy,
        policy=multi_admission_policy,
        at=admission_at,
        run_finalized=False,
    )
    if replayed_selection != selection:
        raise HarnessCycleError(
            "multi-admission selection does not replay from public rules"
        )
    if candidate.observation.task_id != task.task_id:
        raise HarnessCycleError("candidate belongs to a different task")
    if (
        candidate.observation.requirement_schema_version
        != task.requirement_schema_version
    ):
        raise HarnessCycleError("candidate requirement schema version mismatch")
    if candidate.bid.target_requirement_id not in {
        item.requirement_id for item in task.requirements
    }:
        raise HarnessCycleError("candidate targets an unknown requirement")
    task_budget = {item.resource_type: item.amount for item in task.resource_limits}
    supplied_budget = _resource_map(run_budget)
    if supplied_budget != task_budget:
        raise HarnessCycleError("run_budget does not match TaskSpec")
    requested = _resource_map(plan.requested_resources)
    bid_budget = _resource_map(candidate.bid.requested_budget_vector)
    for resource_type, amount in requested.items():
        if resource_type not in bid_budget or amount > bid_budget[resource_type]:
            raise HarnessCycleError(
                "plan requested_resources exceed selected Bid"
            )
    actual = _resource_map(execution.actual_cost)
    for resource_type, amount in actual.items():
        if amount > requested.get(resource_type, -1):
            raise HarnessCycleError("execution actual_cost exceeds authorization")
    communication_inputs = (
        communication_offer,
        communication_policy,
        communication_plan,
    )
    if any(item is not None for item in communication_inputs) and not all(
        item is not None for item in communication_inputs
    ):
        raise HarnessCycleError(
            "communication offer, policy, and plan must be supplied together"
        )
    if communication_plan is not None:
        assert communication_offer is not None
        communication_cost = _resource_map(communication_plan.resource_cost)
        for resource_type in set(actual) | set(communication_cost):
            if (
                actual.get(resource_type, 0)
                + communication_cost.get(resource_type, 0)
                > requested.get(resource_type, -1)
            ):
                raise HarnessCycleError(
                    "communication resource cost exceeds authorization"
                )
        if (
            communication_offer.sender_agent_id
            != communication_plan.sender_agent_id
            or communication_plan.receiver_agent_id
            not in communication_offer.intended_audience
            or communication_offer.payload_schema
            != communication_plan.payload_schema
        ):
            raise HarnessCycleError(
                "communication plan exceeds Agent offer"
            )
        if communication_offer.payload_size_bytes != len(
            communication_plan.payload
        ):
            raise HarnessCycleError(
                "communication payload bytes do not match Agent offer"
            )
        if communication_offer.evidence_refs != (execution.evidence_id,):
            raise HarnessCycleError(
                "communication offer must reference execution evidence"
            )
    if verifier_decision.evidence_id != execution.evidence_id:
        raise HarnessCycleError(
            "verifier decision does not reference execution evidence"
        )
    if (
        verifier_decision.feedback_disposition is FeedbackDisposition.ACCEPTED
        and execution.action_status is not ActionStatus.SUCCEEDED
    ):
        raise HarnessCycleError(
            "verifier cannot accept evidence from an unsuccessful action"
        )
    if initial_local_state.agent_id != candidate.bid.agent_id:
        raise HarnessCycleError("initial local state belongs to another agent")
    if initial_local_state.state_version != candidate.intent.local_state_version:
        raise HarnessCycleError(
            "initial local state version does not match Agent intent"
        )
    if state_update_manifest.run_id != run_id:
        raise HarnessCycleError("state update manifest belongs to another run")
    if state_update_proposal.agent_id != candidate.bid.agent_id:
        raise HarnessCycleError("state update proposal belongs to another agent")
    if (
        state_update_proposal.previous_state_version
        != initial_local_state.state_version
    ):
        raise HarnessCycleError(
            "state update proposal version is not the current local state"
        )
    expected_feedback_id = f"feedback-{plan.plan_id}"
    if state_update_proposal.source_event_window != (expected_feedback_id,):
        raise HarnessCycleError(
            "state update proposal must consume this cycle's Feedback event"
        )


def project_organization_snapshot_from_events(
    *,
    events: tuple[HarnessRuntimeEvent, ...],
    run_id: str,
    checkpoint_id: str,
    builder_version: str = "runtime-projection-v1",
) -> OrganizationSnapshot:
    """Project observable organization solely from committed runtime events."""

    checkpoint_revision = len(events)
    for event in events:
        if event.event_type == "organization_snapshot":
            checkpoint_revision = event.public_state_revision
            break
    source_events = events[:checkpoint_revision]

    def exactly_one(event_type: str) -> HarnessRuntimeEvent:
        matches = tuple(
            event for event in source_events if event.event_type == event_type
        )
        if len(matches) != 1:
            raise HarnessCycleError(
                f"organization projection requires one {event_type} event"
            )
        return matches[0]

    def optional_one(event_type: str) -> HarnessRuntimeEvent | None:
        matches = tuple(
            event for event in source_events if event.event_type == event_type
        )
        if len(matches) > 1:
            raise HarnessCycleError(
                f"organization projection allows at most one {event_type} event"
            )
        return matches[0] if matches else None

    intent_event = exactly_one("agent_intent")
    commitment_event = exactly_one("commitment")
    action_event = exactly_one("action")
    feedback_event = exactly_one("feedback")
    bid_event = exactly_one("agent_bid")
    state_update_event = exactly_one("local_state_update")
    state_snapshot_event = exactly_one("local_state_snapshot")
    intent = intent_event.payload["intent"]
    commitment = commitment_event.payload["commitment"]
    action = action_event.payload["action"]
    feedback = feedback_event.payload["feedback"]
    bid = bid_event.payload["bid"]
    state_update = state_update_event.payload["local_state_update"]
    state_snapshot = state_snapshot_event.payload["local_state_snapshot"]
    if state_snapshot["source_update_ids"][-1] != state_update["update_id"]:
        raise HarnessCycleError(
            "organization projection local state does not reference update"
        )
    accepted = any(
        delta["disposition"] == FeedbackDisposition.ACCEPTED.value
        for delta in feedback["requirement_deltas"]
    )
    duplicate_count = 0
    multi_event = exactly_one("multi_admission")
    for decision in multi_event.payload["result"]["decisions"]:
        if decision["reason"] == "duplicate_limit":
            duplicate_count += 1
    cost_by_type = {
        item["resource_type"]: item["amount"]
        for item in action["resource_cost"]
    }
    communication_event_types = (
        "communication_permit",
        "communication_delivery",
        "communication_receipt",
        "communication_consumption",
    )
    communication_events = tuple(
        optional_one(event_type) for event_type in communication_event_types
    )
    communication_edges: tuple[CommunicationEdgeRecord, ...] = ()
    communication_parent_ids: tuple[str, ...] = ()
    communication_active_agents: tuple[ActiveAgentState, ...] = ()
    communication_cost_contributions: tuple[AgentCostContribution, ...] = ()
    if any(event is not None for event in communication_events):
        if not all(event is not None for event in communication_events):
            raise HarnessCycleError(
                "organization projection requires complete communication chain"
            )
        permit_runtime_event = communication_events[0]
        delivery_runtime_event = communication_events[1]
        receipt_runtime_event = communication_events[2]
        consumption_runtime_event = communication_events[3]
        assert permit_runtime_event is not None
        assert delivery_runtime_event is not None
        assert receipt_runtime_event is not None
        assert consumption_runtime_event is not None
        permit = permit_runtime_event.payload["permit"]
        delivery = delivery_runtime_event.payload["delivery"]
        receipt = receipt_runtime_event.payload["receipt"]
        consumption = consumption_runtime_event.payload["consumption"]
        if (
            delivery["permit_id"] != permit["permit_id"]
            or receipt["delivery_id"] != delivery["delivery_id"]
            or consumption["receipt_id"] != receipt["receipt_id"]
        ):
            raise HarnessCycleError(
                "organization projection communication chain is inconsistent"
            )
        for item in delivery["resource_cost"]:
            resource_type = item["resource_type"]
            cost_by_type[resource_type] = (
                cost_by_type.get(resource_type, 0) + item["amount"]
            )
        communication_edges = (
            CommunicationEdgeRecord(
                edge_id=consumption_runtime_event.event_id,
                permit_id=permit["permit_id"],
                sender_agent_id=delivery["sender_agent_id"],
                receiver_agent_ids=(delivery["receiver_agent_id"],),
                related_requirement_id=permit["related_requirement_id"],
                payload_schema=delivery["payload_schema"],
                message_count=delivery["message_count"],
                payload_bytes=delivery["payload_size_bytes"],
            ),
        )
        communication_parent_ids = (
            permit_runtime_event.event_id,
            consumption_runtime_event.event_id,
        )
        communication_active_agents = (
            ActiveAgentState(
                agent_id=delivery["receiver_agent_id"],
                state_version=0,
                source_event_ids=(),
            ),
        )
        communication_cost_contributions = (
            AgentCostContribution(
                agent_id=delivery["receiver_agent_id"],
                actual_cost=(),
                accepted_contribution=0.0,
            ),
        )
    actual_cost = tuple(
        ResourceAmount(resource_type=resource_type, amount=amount)
        for resource_type, amount in sorted(cost_by_type.items())
    )
    return build_organization_snapshot(
        run_id=run_id,
        task_id=commitment["task_id"],
        checkpoint_id=checkpoint_id,
        requirement_schema_version=commitment[
            "requirement_schema_version"
        ],
        public_state_revision=checkpoint_revision,
        active_agents=(
            ActiveAgentState(
                agent_id=intent["agent_id"],
                state_version=state_snapshot["state_version"],
                source_event_ids=(state_update_event.event_id,),
            ),
            *communication_active_agents,
        ),
        requirement_commitments=(
            RequirementCommitmentLink(
                requirement_id=bid["target_requirement_id"],
                commitment_id=commitment_event.event_id,
                agent_id=commitment["agent_id"],
            ),
        ),
        communication_edges=communication_edges,
        duplicate_distribution=(
            DistributionCount(
                category=bid["target_requirement_id"],
                count=duplicate_count,
            ),
        ),
        refusal_distribution=(),
        agent_cost_contributions=(
            AgentCostContribution(
                agent_id=commitment["agent_id"],
                actual_cost=actual_cost,
                accepted_contribution=1.0 if accepted else 0.0,
            ),
            *communication_cost_contributions,
        ),
        central_preset_info=CentralPresetInfo((), (), ()),
        experience_structural_changes=(),
        parent_event_ids=(
            state_update_event.event_id,
            commitment_event.event_id,
            *communication_parent_ids,
        ),
        builder_version=builder_version,
        created_at=(
            consumption["consumed_at"]
            if communication_edges
            else action["finished_at"]
        ),
    )


def run_scripted_cycle(
    *,
    run_id: str,
    task: TaskSpec,
    selection: MultiAdmissionResult,
    candidate: BidCandidate,
    admission_policy: AdmissionPolicy,
    multi_admission_policy: MultiAdmissionPolicy,
    plan: ScriptedActionPlan,
    execution: ScriptedExecutionResult,
    verifier_decision: ScriptedVerifierDecision,
    initial_local_state: LocalStateSnapshot,
    state_update_manifest: UpdateSurfaceManifest,
    state_update_proposal: LocalStateUpdateProposal,
    state_compiler_policy_version: str,
    run_budget: tuple[ResourceAmount, ...],
    admission_at: str,
    action_at: str,
    finished_at: str,
    communication_offer: CommunicationOffer | None = None,
    communication_policy: CommunicationPolicy | None = None,
    communication_plan: ScriptedCommunicationPlan | None = None,
) -> HarnessCycleResult:
    """Run one selected local-agency action with no externally visible mutation."""

    _preflight(
        run_id=run_id,
        task=task,
        selection=selection,
        candidate=candidate,
        admission_policy=admission_policy,
        multi_admission_policy=multi_admission_policy,
        admission_at=admission_at,
        plan=plan,
        execution=execution,
        verifier_decision=verifier_decision,
        initial_local_state=initial_local_state,
        state_update_manifest=state_update_manifest,
        state_update_proposal=state_update_proposal,
        communication_offer=communication_offer,
        communication_policy=communication_policy,
        communication_plan=communication_plan,
        run_budget=run_budget,
    )
    writer = _EventWriter()
    writer.append(
        selection.result_id,
        "multi_admission",
        (),
        {
            "context": {
                "admission_at": admission_at,
                "admission_policy": admission_policy.to_dict(),
                "candidate": candidate.to_dict(),
                "current_concurrency": 0,
                "existing_requirement_loads": (),
                "multi_admission_policy": multi_admission_policy.to_dict(),
                "ready_requirement_ids": (
                    candidate.bid.target_requirement_id,
                ),
                "reserved_resources": (),
                "run_budget": tuple(
                    item.to_dict() for item in run_budget
                ),
                "run_finalized": False,
            },
            "result": selection.to_dict(),
        },
    )
    writer.append(
        candidate.observation.observation_id,
        "field_observation",
        (selection.result_id,),
        {"observation": candidate.observation.to_dict()},
    )
    writer.append(
        candidate.intent.intent_id,
        "agent_intent",
        (candidate.observation.observation_id,),
        {"intent": candidate.intent.to_dict()},
    )
    writer.append(
        candidate.bid.bid_id,
        "agent_bid",
        (candidate.intent.intent_id,),
        {"bid": candidate.bid.to_dict()},
    )
    initial_state_event_id = (
        f"local-state-initial-{initial_local_state.agent_id}"
        f"-v{initial_local_state.state_version}"
    )
    writer.append(
        initial_state_event_id,
        "local_state_initial",
        (candidate.intent.intent_id,),
        {
            "audience": "public",
            "local_state": _public_local_state(initial_local_state),
            "redaction": "private_values_omitted",
            "update_surface_manifest": state_update_manifest.to_dict(),
        },
    )

    ledger = ResourceLedger(
        {
            item.resource_type: Decimal(str(item.amount))
            for item in run_budget
        }
    )
    grants: list[ResourceEvent] = []
    for amount in candidate.bid.requested_budget_vector:
        grant = _resource_event(
            event_id=f"grant-{candidate.bid.bid_id}-{amount.resource_type}",
            operation=ResourceOperation.GRANT,
            resource_type=amount.resource_type,
            amount=amount.amount,
            source=SHARED_POOL,
            target=agent_escrow_account(candidate.bid.agent_id),
        )
        ledger.apply(grant)
        grants.append(grant)
        writer.append(
            grant.event_id,
            "resource_grant",
            (candidate.bid.bid_id,),
            {"resource_event": grant.to_dict()},
        )

    decision = resolve_admission(
        bid=candidate.bid,
        intent=candidate.intent,
        observation=candidate.observation,
        resource_grants=tuple(grants),
        run_budget=run_budget,
        policy=admission_policy,
        at=admission_at,
        run_finalized=False,
    )
    if decision.commitment is None:
        raise HarnessCycleError(
            f"selected Bid failed single admission: {decision.detail}"
        )
    commitment = decision.commitment
    writer.append(
        commitment.commitment_id,
        "commitment",
        tuple(item.event_id for item in grants),
        {
            "admission_at": admission_at,
            "commitment": commitment.to_dict(),
        },
    )
    lifecycle = initial_commitment_lifecycle(commitment)
    proposal = ActionProposal(
        schema_version=1,
        action_proposal_id=f"action-proposal-{plan.plan_id}",
        agent_id=candidate.bid.agent_id,
        task_id=task.task_id,
        requirement_schema_version=task.requirement_schema_version,
        commitment_id=commitment.commitment_id,
        requirement_ids=(candidate.bid.target_requirement_id,),
        tool=plan.tool,
        requested_resources=plan.requested_resources,
        input_refs=candidate.intent.dependency_refs,
        causal_parent_ids=(commitment.commitment_id,),
        created_at=action_at,
        expires_at=commitment.deadline,
        issuer=GovernanceIssuer.AGENT_PROPOSAL,
    )
    authorization = authorize_action(
        proposal=proposal,
        commitment=commitment,
        lifecycle=lifecycle,
        resource_grants=tuple(grants),
        at=action_at,
        run_finalized=False,
    )
    writer.append(
        authorization.authorization_id,
        "action_authorization",
        (commitment.commitment_id,),
        {
            "action_proposal": proposal.to_dict(),
            "authorization": authorization.to_dict(),
        },
    )

    reserve_events: list[ResourceEvent] = []
    for amount in plan.requested_resources:
        reserve = _resource_event(
            event_id=f"reserve-{plan.plan_id}-{amount.resource_type}",
            operation=ResourceOperation.RESERVE,
            resource_type=amount.resource_type,
            amount=amount.amount,
            source=agent_escrow_account(candidate.bid.agent_id),
            target=reserved_account(candidate.bid.agent_id),
        )
        ledger.apply(reserve)
        reserve_events.append(reserve)
        writer.append(
            reserve.event_id,
            "resource_reserve",
            (authorization.authorization_id,),
            {"resource_event": reserve.to_dict()},
        )

    writer.append(
        execution.execution_id,
        "execution_result",
        (
            authorization.authorization_id,
            *tuple(item.event_id for item in reserve_events),
        ),
        {
            "execution_result": {
                "execution_id": execution.execution_id,
                "actual_cost": tuple(
                    item.to_dict() for item in execution.actual_cost
                ),
                "artifact_refs": execution.artifact_refs,
                "evidence_id": execution.evidence_id,
                "evidence_sha256": hashlib.sha256(
                    execution.evidence_bytes
                ).hexdigest(),
                "action_status": execution.action_status.value,
                "issuer": execution.issuer.value,
            }
        },
    )
    action_id = f"action-{plan.plan_id}"
    action = ActionObservation(
        action_id=action_id,
        agent_id=candidate.bid.agent_id,
        requirement_ids=(candidate.bid.target_requirement_id,),
        input_refs=(
            commitment.commitment_id,
            authorization.authorization_id,
            *candidate.intent.dependency_refs,
        ),
        artifact_refs=execution.artifact_refs,
        evidence_refs=(execution.evidence_id,),
        resource_cost=execution.actual_cost,
        started_at=action_at,
        finished_at=finished_at,
        status=execution.action_status,
    )
    writer.append(
        action.action_id,
        "action",
        (
            execution.execution_id,
        ),
        {"action": action.to_dict()},
    )
    evidence = RuntimeEvidence(
        evidence_id=execution.evidence_id,
        action_id=action.action_id,
        requirement_id=candidate.bid.target_requirement_id,
        content_sha256=hashlib.sha256(execution.evidence_bytes).hexdigest(),
        artifact_refs=execution.artifact_refs,
        provenance_refs=(action.action_id, authorization.authorization_id),
    )
    writer.append(
        evidence.evidence_id,
        "evidence",
        (action.action_id,),
        {
            "content_hex": execution.evidence_bytes.hex(),
            "evidence": evidence.to_dict(),
        },
    )
    communication_permit: CommunicationPermit | None = None
    communication_delivery: CommunicationDelivery | None = None
    communication_receipt: CommunicationReceipt | None = None
    communication_consumption: CommunicationConsumption | None = None
    communication_cost_event_ids: list[str] = []
    communication_by_type: dict[str, float] = {}
    if (
        communication_offer is not None
        and communication_policy is not None
        and communication_plan is not None
    ):
        communication_permit = admit_communication_offer(
            offer=communication_offer,
            observation=candidate.observation,
            commitment=commitment,
            lifecycle=lifecycle,
            policy=communication_policy,
            edge_usage=(),
            at=communication_plan.admitted_at,
            run_finalized=False,
        )
        writer.append(
            communication_offer.offer_id,
            "communication_offer",
            communication_offer.causal_parent_ids,
            {"offer": communication_offer.to_dict()},
        )
        writer.append(
            communication_permit.permit_id,
            "communication_permit",
            (
                commitment.commitment_id,
                communication_offer.offer_id,
            ),
            {
                "permit": communication_permit.to_dict(),
                "policy": communication_policy.to_dict(),
            },
        )
        communication_delivery = deliver_communication(
            permit=communication_permit,
            sender_agent_id=communication_plan.sender_agent_id,
            receiver_agent_id=communication_plan.receiver_agent_id,
            payload_schema=communication_plan.payload_schema,
            payload=communication_plan.payload,
            message_count=communication_plan.message_count,
            resource_cost=communication_plan.resource_cost,
            at=communication_plan.delivered_at,
        )
        writer.append(
            communication_delivery.delivery_id,
            "communication_delivery",
            (communication_permit.permit_id,),
            {
                "content_hex": communication_plan.payload.hex(),
                "delivery": communication_delivery.to_dict(),
            },
        )
        communication_receipt = record_communication_receipt(
            permit=communication_permit,
            delivery=communication_delivery,
            receiver_agent_id=communication_plan.receiver_agent_id,
            at=communication_plan.received_at,
        )
        writer.append(
            communication_receipt.receipt_id,
            "communication_receipt",
            (communication_delivery.delivery_id,),
            {"receipt": communication_receipt.to_dict()},
        )
        communication_consumption = consume_communication(
            permit=communication_permit,
            delivery=communication_delivery,
            receipt=communication_receipt,
            consumer_agent_id=communication_plan.receiver_agent_id,
            consumed_receipt_ids=(),
            at=communication_plan.consumed_at,
        )
        writer.append(
            communication_consumption.consumption_id,
            "communication_consumption",
            (communication_receipt.receipt_id,),
            {"consumption": communication_consumption.to_dict()},
        )
        communication_by_type = _resource_map(
            communication_delivery.resource_cost
        )
        for amount in communication_delivery.resource_cost:
            spend = _resource_event(
                event_id=(
                    f"communication-spend-"
                    f"{communication_delivery.delivery_id}-"
                    f"{amount.resource_type}"
                ),
                operation=ResourceOperation.SPEND,
                resource_type=amount.resource_type,
                amount=amount.amount,
                source=reserved_account(candidate.bid.agent_id),
                target=SPENT,
            )
            ledger.apply(spend)
            communication_cost_event_ids.append(spend.event_id)
            writer.append(
                spend.event_id,
                "communication_resource_spend",
                (communication_consumption.consumption_id,),
                {
                    "delivery_id": communication_delivery.delivery_id,
                    "resource_event": spend.to_dict(),
                },
            )
    writer.append(
        verifier_decision.decision_id,
        "verifier_decision",
        (evidence.evidence_id,),
        {
            "decision": {
                "decision_id": verifier_decision.decision_id,
                "evidence_id": verifier_decision.evidence_id,
                "feedback_disposition": (
                    verifier_decision.feedback_disposition.value
                ),
                "confidence": verifier_decision.confidence,
                "evaluator_version": verifier_decision.evaluator_version,
                "issuer": verifier_decision.issuer.value,
            }
        },
    )
    feedback = FeedbackEvent(
        feedback_id=f"feedback-{plan.plan_id}",
        task_id=task.task_id,
        action_id=action.action_id,
        requirement_deltas=(
            RequirementDelta(
                requirement_id=candidate.bid.target_requirement_id,
                disposition=verifier_decision.feedback_disposition,
                evidence_refs=(evidence.evidence_id,),
            ),
        ),
        source_kind=FeedbackSourceKind.VERIFIER,
        source_authority_by_claim_type=(
            ClaimAuthority(
                "requirement_disposition",
                verifier_decision.evaluator_version,
            ),
        ),
        confidence=verifier_decision.confidence,
        evidence_refs=(evidence.evidence_id,),
    )
    writer.append(
        feedback.feedback_id,
        "feedback",
        (verifier_decision.decision_id,),
        {"feedback": feedback.to_dict()},
    )
    residual_machine = ResidualStateMachine(task)
    residual = residual_machine.apply_feedback(feedback)
    residual_event_id = f"residual-{residual.revision}"
    writer.append(
        residual_event_id,
        "residual",
        (feedback.feedback_id,),
        {"residual": residual.to_dict()},
    )
    local_state_update = compile_local_state_update(
        snapshot=initial_local_state,
        proposal=state_update_proposal,
        manifest=state_update_manifest,
        authorized_event_ids=(feedback.feedback_id,),
        compiler_policy_version=state_compiler_policy_version,
        run_finalized=False,
    )
    local_state = apply_local_state_update(
        initial_local_state,
        local_state_update,
    )
    writer.append(
        local_state_update.update_id,
        "local_state_update",
        (feedback.feedback_id, initial_state_event_id),
        {
            "audience": "public",
            "local_state_update": _public_local_state_update(
                local_state_update,
                state_update_proposal,
            ),
            "redaction": "private_values_omitted",
        },
    )
    local_state_snapshot_event_id = (
        f"local-state-snapshot-{local_state.agent_id}"
        f"-v{local_state.state_version}"
    )
    writer.append(
        local_state_snapshot_event_id,
        "local_state_snapshot",
        (local_state_update.update_id,),
        {
            "audience": "public",
            "local_state_snapshot": _public_local_state(local_state),
            "redaction": "private_values_omitted",
        },
    )

    actual_by_type = _resource_map(execution.actual_cost)
    cost_event_ids: list[str] = list(communication_cost_event_ids)
    for requested in plan.requested_resources:
        actual_amount = actual_by_type.get(requested.resource_type, 0)
        if actual_amount:
            spend = _resource_event(
                event_id=f"spend-{plan.plan_id}-{requested.resource_type}",
                operation=ResourceOperation.SPEND,
                resource_type=requested.resource_type,
                amount=actual_amount,
                source=reserved_account(candidate.bid.agent_id),
                target=SPENT,
            )
            ledger.apply(spend)
            cost_event_ids.append(spend.event_id)
            writer.append(
                spend.event_id,
                "resource_spend",
                (action.action_id,),
                {"resource_event": spend.to_dict()},
            )
        unused = (
            requested.amount
            - actual_amount
            - communication_by_type.get(requested.resource_type, 0)
        )
        if unused:
            returned = _resource_event(
                event_id=f"return-{plan.plan_id}-{requested.resource_type}",
                operation=ResourceOperation.RETURN,
                resource_type=requested.resource_type,
                amount=unused,
                source=reserved_account(candidate.bid.agent_id),
                target=SHARED_POOL,
            )
            ledger.apply(returned)
            cost_event_ids.append(returned.event_id)
            writer.append(
                returned.event_id,
                "resource_return",
                (action.action_id,),
                {"resource_event": returned.to_dict()},
            )

    terminal_status = (
        CommitmentStatus.COMPLETED
        if (
            execution.action_status is ActionStatus.SUCCEEDED
            and verifier_decision.feedback_disposition
            is FeedbackDisposition.ACCEPTED
        )
        else CommitmentStatus.CANCELLED
    )
    terminal_at = (
        communication_plan.consumed_at
        if communication_plan is not None
        else finished_at
    )
    transition, lifecycle = transition_commitment(
        commitment,
        lifecycle,
        next_status=terminal_status,
        reason=(
            f"scripted action {execution.action_status.value}; "
            f"feedback {verifier_decision.feedback_disposition.value}"
        ),
        at=terminal_at,
        run_finalized=False,
    )
    writer.append(
        transition.transition_id,
        "commitment_transition",
        (
            residual_event_id,
            local_state_snapshot_event_id,
            *tuple(cost_event_ids),
        ),
        {"transition": transition.to_dict()},
    )
    settlement_id = f"settlement-{commitment.commitment_id}"
    settlement_decimal = ledger.settle_abnormal_termination(
        candidate.bid.agent_id,
        settlement_id=settlement_id,
    )
    settlement = {
        key: str(value) for key, value in sorted(settlement_decimal.items())
    }
    writer.append(
        settlement_id,
        "settlement",
        (transition.transition_id,),
        {
            "agent_id": candidate.bid.agent_id,
            "returned": settlement,
            "settlement_id": settlement_id,
        },
    )
    ledger.assert_conserved()
    resource_types = tuple(item.resource_type for item in run_budget)
    totals = _ledger_totals(ledger, resource_types)

    organization_snapshot = project_organization_snapshot_from_events(
        events=tuple(writer.events),
        run_id=run_id,
        checkpoint_id=f"checkpoint-{run_id}-1",
    )
    writer.append(
        organization_snapshot.snapshot_id,
        "organization_snapshot",
        (
            commitment.commitment_id,
            local_state_update.update_id,
            settlement_id,
        ),
        {"organization_snapshot": organization_snapshot.to_dict()},
    )
    projection_hash = _terminal_hash(
        residual,
        local_state.state_hash(),
        totals,
        settlement,
        lifecycle,
        organization_snapshot.snapshot_hash,
    )
    writer.append(
        f"terminal-{run_id}",
        "terminal",
        (organization_snapshot.snapshot_id, settlement_id),
        {"terminal_projection_sha256": projection_hash},
    )
    return HarnessCycleResult(
        events=tuple(writer.events),
        commitment=commitment,
        authorization=authorization,
        action=action,
        evidence=evidence,
        feedback=feedback,
        residual=residual,
        local_state_update=local_state_update,
        local_state=local_state,
        communication_permit=communication_permit,
        communication_delivery=communication_delivery,
        communication_receipt=communication_receipt,
        communication_consumption=communication_consumption,
        lifecycle=lifecycle,
        organization_snapshot=organization_snapshot,
        ledger_totals=totals,
        terminal_projection_sha256=projection_hash,
    )


def _feedback_from_payload(value: Mapping[str, Any]) -> FeedbackEvent:
    return FeedbackEvent(
        feedback_id=value["feedback_id"],
        task_id=value["task_id"],
        action_id=value["action_id"],
        requirement_deltas=tuple(
            RequirementDelta(
                requirement_id=item["requirement_id"],
                disposition=FeedbackDisposition(item["disposition"]),
                evidence_refs=tuple(item["evidence_refs"]),
                invalidates_feedback_ids=tuple(
                    item["invalidates_feedback_ids"]
                ),
            )
            for item in value["requirement_deltas"]
        ),
        source_kind=FeedbackSourceKind(value["source_kind"]),
        source_authority_by_claim_type=tuple(
            ClaimAuthority(**item)
            for item in value["source_authority_by_claim_type"]
        ),
        confidence=value["confidence"],
        evidence_refs=tuple(value["evidence_refs"]),
    )


def _resource_from_payload(value: Mapping[str, Any]) -> ResourceEvent:
    return ResourceEvent(
        event_id=value["event_id"],
        operation=ResourceOperation(value["operation"]),
        resource_type=value["resource_type"],
        amount=value["amount"],
        source_account=value["source_account"],
        target_account=value["target_account"],
        idempotency_key=value["idempotency_key"],
    )


def _admission_policy_from_payload(
    value: Mapping[str, Any],
) -> AdmissionPolicy:
    return AdmissionPolicy(
        schema_version=value["schema_version"],
        policy_version=value["policy_version"],
        action_tool_policies=tuple(
            ActionToolPolicy(
                action_family=item["action_family"],
                allowed_tools=tuple(item["allowed_tools"]),
            )
            for item in value["action_tool_policies"]
        ),
        blocked_risk_flags=tuple(value["blocked_risk_flags"]),
    )


def _candidate_from_payload(value: Mapping[str, Any]) -> BidCandidate:
    return BidCandidate(
        bid=AgentBid.from_dict(value["bid"]),
        intent=AgentIntent.from_dict(value["intent"]),
        observation=LocalFieldObservation.from_dict(value["observation"]),
        exploration_eligible=value["exploration_eligible"],
    )


def _public_state_from_payload(
    value: Mapping[str, Any],
) -> PublicLocalStateProjection:
    state_hash = value["state_hash"]
    if (
        not isinstance(state_hash, str)
        or len(state_hash) != 64
        or any(character not in "0123456789abcdef" for character in state_hash)
    ):
        raise HarnessCycleError("public local state hash is invalid")
    source_update_ids = tuple(value["source_update_ids"])
    state_version = value["state_version"]
    if (
        isinstance(state_version, bool)
        or not isinstance(state_version, int)
        or state_version < 0
        or state_version != len(source_update_ids)
    ):
        raise HarnessCycleError("public local state version is invalid")
    return PublicLocalStateProjection(
        agent_id=value["agent_id"],
        state_version=state_version,
        source_update_ids=source_update_ids,
        state_hash=state_hash,
    )


def replay_scripted_cycle(
    *,
    task: TaskSpec,
    run_budget: tuple[ResourceAmount, ...],
    events: tuple[HarnessRuntimeEvent, ...],
) -> HarnessReplayProjection:
    ledger = ResourceLedger(
        {
            item.resource_type: Decimal(str(item.amount))
            for item in run_budget
        }
    )
    residual_machine = ResidualStateMachine(task)
    residual = residual_machine.snapshot()
    known: set[str] = set()
    settlement: dict[str, str] = {}
    terminal_hash: str | None = None
    commitment: AgentCommitment | None = None
    lifecycle: CommitmentLifecycleSnapshot | None = None
    organization_snapshot: OrganizationSnapshot | None = None
    observation: LocalFieldObservation | None = None
    local_state: PublicLocalStateProjection | None = None
    selection: MultiAdmissionResult | None = None
    selected_candidate: BidCandidate | None = None
    replay_admission_policy: AdmissionPolicy | None = None
    intent: AgentIntent | None = None
    bid: AgentBid | None = None
    grants: list[ResourceEvent] = []
    authorization: ActionAuthorization | None = None
    action_event_id: str | None = None
    execution_result: Mapping[str, Any] | None = None
    verifier_decision: Mapping[str, Any] | None = None
    verified_feedback: FeedbackEvent | None = None
    communication_offer: CommunicationOffer | None = None
    communication_permit: CommunicationPermit | None = None
    communication_delivery: CommunicationDelivery | None = None
    communication_receipt: CommunicationReceipt | None = None
    communication_consumption: CommunicationConsumption | None = None
    consumed_receipt_ids: set[str] = set()
    communication_spent: dict[str, float] = {}
    resource_event_types = {
        "resource_grant",
        "resource_reserve",
        "resource_spend",
        "resource_return",
        "communication_resource_spend",
    }
    for index, event in enumerate(events):
        if terminal_hash is not None:
            raise HarnessCycleError("runtime stream contains events after terminal")
        if event.public_state_revision != index:
            raise HarnessCycleError("runtime event revision is not contiguous")
        if event.event_id in known:
            raise HarnessCycleError("duplicate runtime event ID")
        if index > 0 and not event.causal_parent_ids:
            raise HarnessCycleError("runtime event is missing causal parents")
        if not set(event.causal_parent_ids) <= known:
            raise HarnessCycleError("runtime event has unknown causal parent")
        if _canonical_hash(event.payload) != event.payload_sha256:
            raise HarnessCycleError("runtime event payload_sha256 mismatch")
        known.add(event.event_id)
        payload = event.payload
        if event.event_type == "multi_admission":
            if index != 0 or event.causal_parent_ids:
                raise HarnessCycleError(
                    "multi-admission must be the root runtime event"
                )
            context = payload["context"]
            selected_candidate = _candidate_from_payload(
                context["candidate"]
            )
            replay_admission_policy = _admission_policy_from_payload(
                context["admission_policy"]
            )
            multi_policy = MultiAdmissionPolicy(
                **context["multi_admission_policy"]
            )
            context_budget = tuple(
                ResourceAmount(**item) for item in context["run_budget"]
            )
            if (
                context_budget != run_budget
                or tuple(context["reserved_resources"]) != ()
                or tuple(context["existing_requirement_loads"]) != ()
                or context["current_concurrency"] != 0
                or context["run_finalized"] is not False
            ):
                raise HarnessCycleError(
                    "multi-admission context is outside single-cycle contract"
                )
            selection = MultiAdmissionResult.from_dict(payload["result"])
            replayed_selection = resolve_multi_admission(
                candidates=(selected_candidate,),
                run_budget=context_budget,
                reserved_resources=(),
                existing_requirement_loads=(),
                ready_requirement_ids=tuple(
                    context["ready_requirement_ids"]
                ),
                current_concurrency=0,
                admission_policy=replay_admission_policy,
                policy=multi_policy,
                at=context["admission_at"],
                run_finalized=False,
            )
            if (
                selection.result_id != event.event_id
                or replayed_selection != selection
                or selected_candidate.bid.bid_id
                not in selection.admitted_bid_ids
            ):
                raise HarnessCycleError(
                    "multi-admission result does not replay"
                )
        elif event.event_type in resource_event_types:
            resource_event = _resource_from_payload(payload["resource_event"])
            if resource_event.event_id != event.event_id:
                raise HarnessCycleError(
                    "resource event_id does not match runtime event"
                )
            ledger.apply(resource_event)
            if event.event_type == "resource_grant":
                if (
                    bid is None
                    or event.causal_parent_ids != (bid.bid_id,)
                    or resource_event.target_account
                    != agent_escrow_account(bid.agent_id)
                ):
                    raise HarnessCycleError(
                        "resource grant does not bind selected Bid"
                    )
                grants.append(resource_event)
            elif event.event_type == "resource_reserve":
                if (
                    authorization is None
                    or event.causal_parent_ids
                    != (authorization.authorization_id,)
                ):
                    raise HarnessCycleError(
                        "resource reservation does not bind authorization"
                    )
            elif event.event_type in {"resource_spend", "resource_return"}:
                if (
                    action_event_id is None
                    or event.causal_parent_ids != (action_event_id,)
                ):
                    raise HarnessCycleError(
                        "action resource event does not bind action"
                    )
            if event.event_type == "communication_resource_spend":
                if (
                    communication_delivery is None
                    or payload["delivery_id"]
                    != communication_delivery.delivery_id
                ):
                    raise HarnessCycleError(
                        "communication spend does not reference delivery"
                    )
                if resource_event.operation is not ResourceOperation.SPEND:
                    raise HarnessCycleError(
                        "communication resource event must spend"
                    )
                if resource_event.resource_type in communication_spent:
                    raise HarnessCycleError(
                        "duplicate communication resource spend"
                    )
                communication_spent[resource_event.resource_type] = (
                    resource_event.amount
                )
        elif event.event_type == "field_observation":
            observation = LocalFieldObservation.from_dict(
                payload["observation"]
            )
            if (
                selection is None
                or selected_candidate is None
                or observation != selected_candidate.observation
                or observation.observation_id != event.event_id
                or event.causal_parent_ids != (selection.result_id,)
            ):
                raise HarnessCycleError(
                    "field observation does not match selected candidate"
                )
        elif event.event_type == "agent_intent":
            intent = AgentIntent.from_dict(payload["intent"])
            if (
                observation is None
                or selected_candidate is None
                or intent != selected_candidate.intent
                or intent.intent_id != event.event_id
                or event.causal_parent_ids != (observation.observation_id,)
            ):
                raise HarnessCycleError(
                    "Agent intent does not match selected candidate"
                )
        elif event.event_type == "agent_bid":
            bid = AgentBid.from_dict(payload["bid"])
            if (
                intent is None
                or selected_candidate is None
                or bid != selected_candidate.bid
                or bid.bid_id != event.event_id
                or event.causal_parent_ids != (intent.intent_id,)
            ):
                raise HarnessCycleError(
                    "Agent Bid does not match selected candidate"
                )
        elif event.event_type == "commitment":
            commitment = AgentCommitment.from_dict(payload["commitment"])
            if (
                bid is None
                or intent is None
                or observation is None
                or replay_admission_policy is None
            ):
                raise HarnessCycleError(
                    "commitment has incomplete admission context"
                )
            try:
                replayed_admission = resolve_admission(
                    bid=bid,
                    intent=intent,
                    observation=observation,
                    resource_grants=tuple(grants),
                    run_budget=run_budget,
                    policy=replay_admission_policy,
                    at=payload["admission_at"],
                    run_finalized=False,
                )
            except ValueError as error:
                raise HarnessCycleError(
                    "commitment does not replay from admission"
                ) from error
            if (
                commitment.commitment_id != event.event_id
                or replayed_admission.commitment != commitment
                or event.causal_parent_ids
                != tuple(item.event_id for item in grants)
            ):
                raise HarnessCycleError(
                    "commitment does not replay from admission"
                )
            lifecycle = initial_commitment_lifecycle(commitment)
        elif event.event_type == "local_state_initial":
            if local_state is not None:
                raise HarnessCycleError(
                    "runtime stream has multiple initial local states"
                )
            if (
                payload.get("audience") != "public"
                or payload.get("redaction") != "private_values_omitted"
                or "values" in payload["local_state"]
            ):
                raise HarnessCycleError(
                    "public local state event is not redacted"
                )
            local_state = _public_state_from_payload(payload["local_state"])
            if (
                intent is None
                or local_state.agent_id != intent.agent_id
                or local_state.state_version != intent.local_state_version
                or event.causal_parent_ids != (intent.intent_id,)
            ):
                raise HarnessCycleError(
                    "public initial local state does not match Agent intent"
                )
            UpdateSurfaceManifest.from_dict(
                payload["update_surface_manifest"]
            )
        elif event.event_type == "action_authorization":
            if commitment is None or lifecycle is None:
                raise HarnessCycleError(
                    "action authorization has no active commitment"
                )
            try:
                proposal = ActionProposal.from_dict(
                    payload["action_proposal"]
                )
                parsed_authorization = ActionAuthorization.from_dict(
                    payload["authorization"]
                )
                replayed_authorization = authorize_action(
                    proposal=proposal,
                    commitment=commitment,
                    lifecycle=lifecycle,
                    resource_grants=tuple(grants),
                    at=parsed_authorization.created_at,
                    run_finalized=False,
                )
            except ValueError as error:
                raise HarnessCycleError(
                    "action authorization does not replay"
                ) from error
            if (
                parsed_authorization.authorization_id != event.event_id
                or replayed_authorization != parsed_authorization
                or event.causal_parent_ids != (commitment.commitment_id,)
            ):
                raise HarnessCycleError(
                    "action authorization does not replay"
                )
            authorization = parsed_authorization
        elif event.event_type == "execution_result":
            if execution_result is not None:
                raise HarnessCycleError(
                    "runtime stream has multiple execution results"
                )
            execution_result = payload["execution_result"]
            if (
                authorization is None
                or execution_result["execution_id"] != event.event_id
                or authorization.authorization_id
                not in event.causal_parent_ids
            ):
                raise HarnessCycleError(
                    "execution event_id does not match execution result"
                )
            if execution_result["issuer"] != RuntimeIssuer.HARNESS_EXECUTOR.value:
                raise HarnessCycleError(
                    "execution result was not issued by Harness executor"
                )
        elif event.event_type == "action":
            if payload["action"]["action_id"] != event.event_id:
                raise HarnessCycleError(
                    "action event_id does not match action contract"
                )
            if execution_result is None:
                raise HarnessCycleError("action has no Harness execution result")
            action_payload = payload["action"]
            if (
                commitment is None
                or authorization is None
                or event.causal_parent_ids
                != (execution_result["execution_id"],)
                or action_payload["agent_id"] != commitment.agent_id
                or action_payload["requirement_ids"]
                != authorization.authorized_requirement_ids
                or action_payload["input_refs"][:2]
                != (
                    commitment.commitment_id,
                    authorization.authorization_id,
                )
                or
                action_payload["artifact_refs"]
                != execution_result["artifact_refs"]
                or action_payload["evidence_refs"]
                != (execution_result["evidence_id"],)
                or action_payload["resource_cost"]
                != execution_result["actual_cost"]
                or action_payload["status"]
                != execution_result["action_status"]
            ):
                raise HarnessCycleError(
                    "action does not match Harness execution result"
                )
            action_event_id = event.event_id
        elif event.event_type == "evidence":
            evidence = payload["evidence"]
            if evidence["evidence_id"] != event.event_id:
                raise HarnessCycleError(
                    "evidence event_id does not match evidence contract"
                )
            try:
                content = bytes.fromhex(payload["content_hex"])
            except (TypeError, ValueError) as error:
                raise HarnessCycleError(
                    "evidence content_hex is invalid"
                ) from error
            if hashlib.sha256(content).hexdigest() != evidence["content_sha256"]:
                raise HarnessCycleError(
                    "evidence content hash does not replay"
                )
            if execution_result is None or (
                evidence["evidence_id"] != execution_result["evidence_id"]
                or evidence["content_sha256"]
                != execution_result["evidence_sha256"]
            ):
                raise HarnessCycleError(
                    "evidence does not match Harness execution result"
                )
        elif event.event_type == "communication_offer":
            if communication_offer is not None:
                raise HarnessCycleError(
                    "runtime stream has multiple communication offers"
                )
            communication_offer = CommunicationOffer.from_dict(
                payload["offer"]
            )
            if communication_offer.offer_id != event.event_id:
                raise HarnessCycleError(
                    "communication offer_id does not match runtime event"
                )
        elif event.event_type == "communication_permit":
            if (
                communication_offer is None
                or observation is None
                or commitment is None
                or lifecycle is None
            ):
                raise HarnessCycleError(
                    "communication permit has incomplete governance context"
                )
            if communication_permit is not None:
                raise HarnessCycleError(
                    "runtime stream has multiple communication permits"
                )
            communication_permit = CommunicationPermit.from_dict(
                payload["permit"]
            )
            policy = CommunicationPolicy.from_dict(payload["policy"])
            try:
                replayed_permit = admit_communication_offer(
                    offer=communication_offer,
                    observation=observation,
                    commitment=commitment,
                    lifecycle=lifecycle,
                    policy=policy,
                    edge_usage=(),
                    at=communication_permit.created_at,
                    run_finalized=False,
                )
            except CommunicationGovernanceError as error:
                raise HarnessCycleError(
                    "communication permit does not replay"
                ) from error
            if (
                communication_permit.permit_id != event.event_id
                or replayed_permit != communication_permit
            ):
                raise HarnessCycleError(
                    "communication permit does not replay"
                )
        elif event.event_type == "communication_delivery":
            if communication_permit is None:
                raise HarnessCycleError(
                    "communication delivery has no permit"
                )
            if communication_delivery is not None:
                raise HarnessCycleError(
                    "runtime stream has multiple communication deliveries"
                )
            communication_delivery = CommunicationDelivery.from_dict(
                payload["delivery"]
            )
            try:
                content = bytes.fromhex(payload["content_hex"])
            except (TypeError, ValueError) as error:
                raise HarnessCycleError(
                    "communication content_hex is invalid"
                ) from error
            try:
                replayed_delivery = deliver_communication(
                    permit=communication_permit,
                    sender_agent_id=communication_delivery.sender_agent_id,
                    receiver_agent_id=communication_delivery.receiver_agent_id,
                    payload_schema=communication_delivery.payload_schema,
                    payload=content,
                    message_count=communication_delivery.message_count,
                    resource_cost=communication_delivery.resource_cost,
                    at=communication_delivery.delivered_at,
                )
            except CommunicationGovernanceError as error:
                raise HarnessCycleError(
                    "communication delivery does not replay"
                ) from error
            if (
                communication_delivery.delivery_id != event.event_id
                or replayed_delivery != communication_delivery
            ):
                raise HarnessCycleError(
                    "communication delivery does not replay"
                )
        elif event.event_type == "communication_receipt":
            if communication_permit is None or communication_delivery is None:
                raise HarnessCycleError(
                    "communication receipt has no delivery"
                )
            if communication_receipt is not None:
                raise HarnessCycleError(
                    "runtime stream has multiple communication receipts"
                )
            communication_receipt = CommunicationReceipt.from_dict(
                payload["receipt"]
            )
            try:
                replayed_receipt = record_communication_receipt(
                    permit=communication_permit,
                    delivery=communication_delivery,
                    receiver_agent_id=(
                        communication_receipt.receiver_agent_id
                    ),
                    at=communication_receipt.received_at,
                )
            except CommunicationGovernanceError as error:
                raise HarnessCycleError(
                    "communication receipt does not replay"
                ) from error
            if (
                communication_receipt.receipt_id != event.event_id
                or replayed_receipt != communication_receipt
            ):
                raise HarnessCycleError(
                    "communication receipt does not replay"
                )
        elif event.event_type == "communication_consumption":
            if (
                communication_permit is None
                or communication_delivery is None
                or communication_receipt is None
            ):
                raise HarnessCycleError(
                    "communication consumption has no receipt"
                )
            communication_consumption = CommunicationConsumption.from_dict(
                payload["consumption"]
            )
            try:
                replayed_consumption = consume_communication(
                    permit=communication_permit,
                    delivery=communication_delivery,
                    receipt=communication_receipt,
                    consumer_agent_id=(
                        communication_consumption.consumer_agent_id
                    ),
                    consumed_receipt_ids=tuple(consumed_receipt_ids),
                    at=communication_consumption.consumed_at,
                )
            except CommunicationGovernanceError as error:
                raise HarnessCycleError(
                    "communication consumption does not replay"
                ) from error
            if (
                communication_consumption.consumption_id != event.event_id
                or replayed_consumption != communication_consumption
            ):
                raise HarnessCycleError(
                    "communication consumption does not replay"
                )
            consumed_receipt_ids.add(communication_receipt.receipt_id)
        elif event.event_type == "verifier_decision":
            if verifier_decision is not None:
                raise HarnessCycleError(
                    "runtime stream has multiple verifier decisions"
                )
            verifier_decision = payload["decision"]
            if verifier_decision["decision_id"] != event.event_id:
                raise HarnessCycleError(
                    "verifier event_id does not match verifier decision"
                )
            if (
                verifier_decision["issuer"]
                != RuntimeIssuer.HARNESS_VERIFIER.value
            ):
                raise HarnessCycleError(
                    "verifier decision was not issued by Harness verifier"
                )
            if execution_result is None or (
                verifier_decision["evidence_id"]
                != execution_result["evidence_id"]
            ):
                raise HarnessCycleError(
                    "verifier decision does not reference execution evidence"
                )
            if (
                verifier_decision["feedback_disposition"]
                == FeedbackDisposition.ACCEPTED.value
                and execution_result["action_status"]
                != ActionStatus.SUCCEEDED.value
            ):
                raise HarnessCycleError(
                    "verifier accepted an unsuccessful execution"
                )
        elif event.event_type == "feedback":
            feedback = _feedback_from_payload(payload["feedback"])
            if feedback.feedback_id != event.event_id:
                raise HarnessCycleError(
                    "feedback event_id does not match feedback contract"
                )
            if verifier_decision is None:
                raise HarnessCycleError(
                    "feedback has no Harness verifier decision"
                )
            authority = feedback.source_authority_by_claim_type
            if (
                len(feedback.requirement_deltas) != 1
                or feedback.source_kind is not FeedbackSourceKind.VERIFIER
                or feedback.requirement_deltas[0].disposition.value
                != verifier_decision["feedback_disposition"]
                or feedback.confidence != verifier_decision["confidence"]
                or feedback.evidence_refs
                != (verifier_decision["evidence_id"],)
                or len(authority) != 1
                or authority[0].claim_type != "requirement_disposition"
                or authority[0].authority
                != verifier_decision["evaluator_version"]
            ):
                raise HarnessCycleError(
                    "feedback does not match Harness verifier decision"
                )
            residual = residual_machine.apply_feedback(feedback)
            verified_feedback = feedback
        elif event.event_type == "residual":
            if payload["residual"] != _freeze(residual.to_dict()):
                raise HarnessCycleError("committed residual does not replay")
        elif event.event_type == "local_state_update":
            if local_state is None:
                raise HarnessCycleError(
                    "local state update has no initial snapshot"
                )
            if (
                payload.get("audience") != "public"
                or payload.get("redaction") != "private_values_omitted"
            ):
                raise HarnessCycleError(
                    "public local state update is not redacted"
                )
            update = payload["local_state_update"]
            forbidden = {
                "changed_fields",
                "committed_values",
                "proposed_values",
                "values",
            }
            if forbidden.intersection(update):
                raise HarnessCycleError(
                    "public local state update exposes private values"
                )
            if (
                update["update_id"] != event.event_id
                or update["issuer"] != "harness_compiler"
                or update["agent_id"] != local_state.agent_id
                or update["previous_state_version"]
                != local_state.state_version
                or update["next_state_version"]
                != local_state.state_version + 1
                or update["before_hash"] != local_state.state_hash
            ):
                raise HarnessCycleError(
                    "public local state update does not replay"
                )
            if verified_feedback is None:
                raise HarnessCycleError(
                    "local state update has no verified Feedback event"
                )
            if (
                tuple(update["source_event_window"])
                != (verified_feedback.feedback_id,)
                or event.causal_parent_ids
                != (
                    verified_feedback.feedback_id,
                    (
                        f"local-state-initial-{local_state.agent_id}"
                        f"-v{local_state.state_version}"
                    ),
                )
            ):
                raise HarnessCycleError(
                    "public local state update has invalid sources"
                )
            for hash_field in ("after_hash", "proposal_sha256"):
                digest = update[hash_field]
                if (
                    not isinstance(digest, str)
                    or len(digest) != 64
                    or any(
                        character not in "0123456789abcdef"
                        for character in digest
                    )
                ):
                    raise HarnessCycleError(
                        "public local state update hash is invalid"
                    )
            local_state = PublicLocalStateProjection(
                agent_id=local_state.agent_id,
                state_version=update["next_state_version"],
                source_update_ids=(
                    *local_state.source_update_ids,
                    update["update_id"],
                ),
                state_hash=update["after_hash"],
            )
        elif event.event_type == "local_state_snapshot":
            if local_state is None:
                raise HarnessCycleError(
                    "local state snapshot has no replayed state"
                )
            if (
                payload.get("audience") != "public"
                or payload.get("redaction") != "private_values_omitted"
                or "values" in payload["local_state_snapshot"]
            ):
                raise HarnessCycleError(
                    "public local state snapshot is not redacted"
                )
            committed_state = _public_state_from_payload(
                payload["local_state_snapshot"]
            )
            if (
                committed_state != local_state
                or event.causal_parent_ids
                != (local_state.source_update_ids[-1],)
            ):
                raise HarnessCycleError(
                    "committed local state does not replay"
                )
        elif event.event_type == "settlement":
            if payload["settlement_id"] != event.event_id:
                raise HarnessCycleError(
                    "settlement event_id does not match settlement contract"
                )
            returned = ledger.settle_abnormal_termination(
                payload["agent_id"],
                settlement_id=payload["settlement_id"],
            )
            settlement = {
                key: str(value) for key, value in sorted(returned.items())
            }
            if settlement != _thaw(payload["returned"]):
                raise HarnessCycleError("committed settlement does not replay")
        elif event.event_type == "commitment_transition":
            if commitment is None or lifecycle is None:
                raise HarnessCycleError(
                    "commitment transition has no active commitment"
                )
            transition = CommitmentTransition.from_dict(payload["transition"])
            if transition.transition_id != event.event_id:
                raise HarnessCycleError(
                    "transition event_id does not match transition contract"
                )
            lifecycle = replay_commitment_transitions(
                commitment,
                (transition,),
            )
        elif event.event_type == "organization_snapshot":
            organization_snapshot = OrganizationSnapshot.from_dict(
                payload["organization_snapshot"]
            )
            if organization_snapshot.snapshot_id != event.event_id:
                raise HarnessCycleError(
                    "organization event_id does not match snapshot contract"
                )
            projected = project_organization_snapshot_from_events(
                events=events,
                run_id=organization_snapshot.run_id,
                checkpoint_id=organization_snapshot.checkpoint_id,
                builder_version=organization_snapshot.builder_version,
            )
            if projected != organization_snapshot:
                raise HarnessCycleError(
                    "organization snapshot does not match event projection"
                )
        elif event.event_type == "terminal":
            terminal_hash = payload["terminal_projection_sha256"]

    if terminal_hash is None:
        raise HarnessCycleError("runtime stream has no terminal event")
    if lifecycle is None or lifecycle.status is CommitmentStatus.ACTIVE:
        raise HarnessCycleError("runtime stream has no terminal commitment")
    if organization_snapshot is None:
        raise HarnessCycleError("runtime stream has no organization snapshot")
    if local_state is None or local_state.state_version == 0:
        raise HarnessCycleError("runtime stream has no committed local state update")
    communication_chain = (
        communication_offer,
        communication_permit,
        communication_delivery,
        communication_receipt,
        communication_consumption,
    )
    if any(item is not None for item in communication_chain):
        if not all(item is not None for item in communication_chain):
            raise HarnessCycleError(
                "runtime stream has incomplete communication chain"
            )
        assert communication_delivery is not None
        expected_communication_spent = _resource_map(
            communication_delivery.resource_cost
        )
        if communication_spent != expected_communication_spent:
            raise HarnessCycleError(
                "communication resource cost does not match Ledger events"
            )
    elif communication_spent:
        raise HarnessCycleError(
            "communication spend exists without communication chain"
        )
    resource_types = tuple(item.resource_type for item in run_budget)
    totals = _ledger_totals(ledger, resource_types)
    expected = _terminal_hash(
        residual,
        local_state.state_hash,
        totals,
        settlement,
        lifecycle,
        organization_snapshot.snapshot_hash,
    )
    if terminal_hash != expected:
        raise HarnessCycleError("terminal projection hash mismatch")
    ledger.assert_conserved()
    return HarnessReplayProjection(
        residual=residual,
        local_state=local_state,
        ledger_totals=totals,
        terminal_projection_sha256=terminal_hash,
    )
