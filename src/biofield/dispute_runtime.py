from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .admission import AdmissionPolicy
from .commitment import (
    initial_commitment_lifecycle,
    transition_commitment,
)
from .contracts import (
    ActiveAgentState,
    AgentCommitment,
    AgentCostContribution,
    CentralPresetInfo,
    ClaimAuthority,
    CommitmentLifecycleSnapshot,
    CommitmentStatus,
    DistributionCount,
    FeedbackDisposition,
    FeedbackEvent,
    FeedbackSourceKind,
    LocalStateSnapshot,
    LocalStateUpdate,
    LocalStateUpdateProposal,
    OrganizationSnapshot,
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
from .local_runtime import (
    HarnessCycleError,
    HarnessRuntimeEvent,
    RuntimeEvidence,
    ScriptedActionPlan,
    ScriptedExecutionResult,
    ScriptedVerifierDecision,
    _canonical_hash,
    _ledger_totals,
    _public_local_state,
    _public_local_state_update,
    run_scripted_cycle,
)
from .local_state import (
    apply_local_state_update,
    compile_local_state_update,
)
from .multi_admission import (
    BidCandidate,
    MultiAdmissionPolicy,
    MultiAdmissionResult,
)
from .organization import build_organization_snapshot
from .residual import ResidualStateMachine


class RevalidationIssuer(str, Enum):
    INDEPENDENT_EVIDENCE_COLLECTOR = "independent_evidence_collector"
    INDEPENDENT_VERIFIER = "independent_verifier"


@dataclass(frozen=True, kw_only=True)
class RevalidationEvidence:
    evidence_id: str
    content: bytes
    artifact_refs: tuple[str, ...]
    provenance_refs: tuple[str, ...]
    invalidates_evidence_ids: tuple[str, ...]
    resource_cost: tuple[ResourceAmount, ...]
    collected_at: str
    issuer: RevalidationIssuer

    def __post_init__(self) -> None:
        for field_name in (
            "artifact_refs",
            "provenance_refs",
            "invalidates_evidence_ids",
            "resource_cost",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        if not isinstance(self.evidence_id, str) or not self.evidence_id:
            raise ValueError("evidence_id must be non-empty")
        if not isinstance(self.content, bytes) or not self.content:
            raise ValueError("content must be non-empty bytes")
        if not self.provenance_refs:
            raise ValueError("provenance_refs cannot be empty")
        if not self.invalidates_evidence_ids:
            raise ValueError("invalidates_evidence_ids cannot be empty")
        if not self.resource_cost or any(
            item.amount <= 0 for item in self.resource_cost
        ):
            raise ValueError("resource_cost must be positive")
        if len({item.resource_type for item in self.resource_cost}) != len(
            self.resource_cost
        ):
            raise ValueError("resource_cost resource types must be unique")
        if not isinstance(self.collected_at, str) or not self.collected_at:
            raise ValueError("collected_at must be non-empty")
        if self.issuer is not RevalidationIssuer.INDEPENDENT_EVIDENCE_COLLECTOR:
            raise ValueError(
                "revalidation evidence requires independent collector"
            )

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    def to_public_dict(
        self,
        *,
        action_id: str,
        requirement_id: str,
    ) -> dict[str, object]:
        return {
            "action_id": action_id,
            "artifact_refs": self.artifact_refs,
            "collected_at": self.collected_at,
            "content_sha256": self.content_sha256,
            "evidence_id": self.evidence_id,
            "invalidates_evidence_ids": self.invalidates_evidence_ids,
            "issuer": self.issuer.value,
            "provenance_refs": self.provenance_refs,
            "requirement_id": requirement_id,
            "resource_cost": tuple(
                item.to_dict() for item in self.resource_cost
            ),
        }

    @classmethod
    def from_event_payload(
        cls,
        value: Mapping[str, Any],
    ) -> RevalidationEvidence:
        evidence = value["evidence"]
        try:
            content = bytes.fromhex(value["content_hex"])
            result = cls(
                evidence_id=evidence["evidence_id"],
                content=content,
                artifact_refs=tuple(evidence["artifact_refs"]),
                provenance_refs=tuple(evidence["provenance_refs"]),
                invalidates_evidence_ids=tuple(
                    evidence["invalidates_evidence_ids"]
                ),
                resource_cost=tuple(
                    ResourceAmount(**item)
                    for item in evidence["resource_cost"]
                ),
                collected_at=evidence["collected_at"],
                issuer=RevalidationIssuer(evidence["issuer"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise HarnessCycleError(
                "revalidation Evidence payload is invalid"
            ) from error
        if result.content_sha256 != evidence["content_sha256"]:
            raise HarnessCycleError(
                "revalidation Evidence content hash mismatch"
            )
        return result


@dataclass(frozen=True, kw_only=True)
class IndependentRevalidationDecision:
    decision_id: str
    evidence_id: str
    disposition: FeedbackDisposition
    confidence: float
    verifier_authority: str
    invalidates_feedback_ids: tuple[str, ...]
    invalidates_evidence_ids: tuple[str, ...]
    decided_at: str
    issuer: RevalidationIssuer

    def __post_init__(self) -> None:
        for field_name in (
            "invalidates_feedback_ids",
            "invalidates_evidence_ids",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        for field_name in (
            "decision_id",
            "evidence_id",
            "verifier_authority",
            "decided_at",
        ):
            if not isinstance(getattr(self, field_name), str) or not getattr(
                self, field_name
            ):
                raise ValueError(f"{field_name} must be non-empty")
        if self.disposition not in {
            FeedbackDisposition.ACCEPTED,
            FeedbackDisposition.REJECTED,
        }:
            raise ValueError(
                "revalidation disposition must be accepted or rejected"
            )
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not 0 <= self.confidence <= 1
        ):
            raise ValueError("confidence must be between 0 and 1")
        if not self.invalidates_feedback_ids:
            raise ValueError("invalidates_feedback_ids cannot be empty")
        if not self.invalidates_evidence_ids:
            raise ValueError("invalidates_evidence_ids cannot be empty")
        if self.issuer is not RevalidationIssuer.INDEPENDENT_VERIFIER:
            raise ValueError("decision requires independent verifier issuer")

    def to_dict(self) -> dict[str, object]:
        return {
            "confidence": self.confidence,
            "decided_at": self.decided_at,
            "decision_id": self.decision_id,
            "disposition": self.disposition.value,
            "evidence_id": self.evidence_id,
            "invalidates_evidence_ids": self.invalidates_evidence_ids,
            "invalidates_feedback_ids": self.invalidates_feedback_ids,
            "issuer": self.issuer.value,
            "verifier_authority": self.verifier_authority,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> IndependentRevalidationDecision:
        try:
            return cls(
                decision_id=value["decision_id"],
                evidence_id=value["evidence_id"],
                disposition=FeedbackDisposition(value["disposition"]),
                confidence=value["confidence"],
                verifier_authority=value["verifier_authority"],
                invalidates_feedback_ids=tuple(
                    value["invalidates_feedback_ids"]
                ),
                invalidates_evidence_ids=tuple(
                    value["invalidates_evidence_ids"]
                ),
                decided_at=value["decided_at"],
                issuer=RevalidationIssuer(value["issuer"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise HarnessCycleError(
                f"revalidation decision payload is invalid: {error}"
            ) from error


@dataclass(frozen=True, kw_only=True)
class DisputeQuarantine:
    quarantine_id: str
    commitment_id: str
    action_id: str
    evidence_id: str
    feedback_id: str
    requirement_id: str
    original_agent_id: str
    original_verifier_authority: str
    evidence_status: str
    feedback_status: str
    commitment_status: str
    accepted_contribution: float
    experience_update_ids: tuple[str, ...]
    created_at: str
    causal_parent_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "experience_update_ids",
            tuple(self.experience_update_ids),
        )
        object.__setattr__(
            self,
            "causal_parent_ids",
            tuple(self.causal_parent_ids),
        )
        if (
            self.evidence_status,
            self.feedback_status,
            self.commitment_status,
        ) != ("quarantined", "quarantined", "quarantined"):
            raise ValueError("all dispute artifacts must be quarantined")
        if self.accepted_contribution != 0:
            raise ValueError("quarantine cannot grant accepted contribution")
        if self.experience_update_ids:
            raise ValueError("quarantine cannot contain Experience updates")

    def to_dict(self) -> dict[str, object]:
        return {
            "accepted_contribution": self.accepted_contribution,
            "action_id": self.action_id,
            "causal_parent_ids": self.causal_parent_ids,
            "commitment_id": self.commitment_id,
            "commitment_status": self.commitment_status,
            "created_at": self.created_at,
            "evidence_id": self.evidence_id,
            "evidence_status": self.evidence_status,
            "experience_update_ids": self.experience_update_ids,
            "feedback_id": self.feedback_id,
            "feedback_status": self.feedback_status,
            "original_agent_id": self.original_agent_id,
            "original_verifier_authority": (
                self.original_verifier_authority
            ),
            "quarantine_id": self.quarantine_id,
            "requirement_id": self.requirement_id,
        }


def _normalize_totals(
    value: Mapping[str, Mapping[str, str]],
) -> Mapping[str, Mapping[str, str]]:
    return MappingProxyType(
        {
            key: MappingProxyType(dict(item))
            for key, item in sorted(value.items())
        }
    )


def _checkpoint_content(
    *,
    run_id: str,
    configuration_sha256: str,
    prefix_event_ids: tuple[str, ...],
    prefix_event_fingerprints: tuple[str, ...],
    next_public_state_revision: int,
    last_event_id: str,
    commitment: AgentCommitment,
    action: Mapping[str, Any],
    evidence: RuntimeEvidence,
    disputed_feedback: FeedbackEvent,
    residual: ResidualSnapshot,
    quarantine: DisputeQuarantine,
    ledger_totals: Mapping[str, Mapping[str, str]],
    local_state_version: int,
    local_state_sha256: str,
) -> dict[str, object]:
    return {
        "authority": "harness_quarantine",
        "checkpoint_schema_version": 1,
        "commitment": commitment.to_dict(),
        "configuration_sha256": configuration_sha256,
        "disputed_action": dict(action),
        "disputed_evidence": evidence.to_dict(),
        "disputed_feedback": disputed_feedback.to_dict(),
        "event_schema_version": 1,
        "last_event_id": last_event_id,
        "ledger_totals": {
            key: dict(item) for key, item in sorted(ledger_totals.items())
        },
        "local_state_sha256": local_state_sha256,
        "local_state_version": local_state_version,
        "next_public_state_revision": next_public_state_revision,
        "prefix_event_fingerprints": prefix_event_fingerprints,
        "prefix_event_ids": prefix_event_ids,
        "prefix_sha256": _canonical_hash(
            {
                "event_fingerprints": prefix_event_fingerprints,
                "event_ids": prefix_event_ids,
            }
        ),
        "quarantine": quarantine.to_dict(),
        "residual": residual.to_dict(),
        "run_id": run_id,
        "runtime_version": "dispute-revalidation-v1",
    }


@dataclass(frozen=True, kw_only=True)
class DisputeCheckpoint:
    run_id: str
    configuration_sha256: str
    prefix_event_ids: tuple[str, ...]
    prefix_event_fingerprints: tuple[str, ...]
    next_public_state_revision: int
    last_event_id: str
    commitment: AgentCommitment
    action: Mapping[str, Any]
    evidence: RuntimeEvidence
    disputed_feedback: FeedbackEvent
    residual: ResidualSnapshot
    quarantine: DisputeQuarantine
    ledger_totals: Mapping[str, Mapping[str, str]]
    local_state_version: int
    local_state_sha256: str
    checkpoint_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "prefix_event_ids",
            tuple(self.prefix_event_ids),
        )
        object.__setattr__(
            self,
            "prefix_event_fingerprints",
            tuple(self.prefix_event_fingerprints),
        )
        object.__setattr__(self, "action", MappingProxyType(dict(self.action)))
        object.__setattr__(
            self,
            "ledger_totals",
            _normalize_totals(self.ledger_totals),
        )
        if (
            len(self.prefix_event_ids) != self.next_public_state_revision
            or len(self.prefix_event_fingerprints)
            != self.next_public_state_revision
            or len(set(self.prefix_event_ids)) != len(self.prefix_event_ids)
            or self.last_event_id != self.prefix_event_ids[-1]
        ):
            raise HarnessCycleError("dispute checkpoint prefix is incomplete")
        prefix_sha = _canonical_hash(
            {
                "event_fingerprints": self.prefix_event_fingerprints,
                "event_ids": self.prefix_event_ids,
            }
        )
        content = _checkpoint_content(
            run_id=self.run_id,
            configuration_sha256=self.configuration_sha256,
            prefix_event_ids=self.prefix_event_ids,
            prefix_event_fingerprints=self.prefix_event_fingerprints,
            next_public_state_revision=self.next_public_state_revision,
            last_event_id=self.last_event_id,
            commitment=self.commitment,
            action=self.action,
            evidence=self.evidence,
            disputed_feedback=self.disputed_feedback,
            residual=self.residual,
            quarantine=self.quarantine,
            ledger_totals=self.ledger_totals,
            local_state_version=self.local_state_version,
            local_state_sha256=self.local_state_sha256,
        )
        if content["prefix_sha256"] != prefix_sha:
            raise HarnessCycleError("dispute checkpoint prefix hash mismatch")
        if self.checkpoint_sha256 != _canonical_hash(content):
            raise HarnessCycleError("dispute checkpoint self hash mismatch")
        if (
            self.disputed_feedback.requirement_deltas[0].disposition
            is not FeedbackDisposition.DISPUTED
            or self.residual.requirement(
                self.quarantine.requirement_id
            ).status.value
            != "disputed"
            or self.residual.complete
        ):
            raise HarnessCycleError(
                "dispute checkpoint does not preserve quarantine"
            )
        if self.commitment.commitment_id != self.quarantine.commitment_id:
            raise HarnessCycleError(
                "dispute checkpoint commitment quarantine mismatch"
            )
        if len(self.local_state_sha256) != 64:
            raise HarnessCycleError(
                "dispute checkpoint local-state hash is invalid"
            )

    def to_dict(self) -> dict[str, object]:
        content = _checkpoint_content(
            run_id=self.run_id,
            configuration_sha256=self.configuration_sha256,
            prefix_event_ids=self.prefix_event_ids,
            prefix_event_fingerprints=self.prefix_event_fingerprints,
            next_public_state_revision=self.next_public_state_revision,
            last_event_id=self.last_event_id,
            commitment=self.commitment,
            action=self.action,
            evidence=self.evidence,
            disputed_feedback=self.disputed_feedback,
            residual=self.residual,
            quarantine=self.quarantine,
            ledger_totals=self.ledger_totals,
            local_state_version=self.local_state_version,
            local_state_sha256=self.local_state_sha256,
        )
        return {**content, "checkpoint_sha256": self.checkpoint_sha256}


@dataclass(frozen=True, kw_only=True)
class DisputeCheckpointResult:
    events: tuple[HarnessRuntimeEvent, ...]
    checkpoint: DisputeCheckpoint


@dataclass(frozen=True, kw_only=True)
class DisputeResolutionReplay:
    residual: ResidualSnapshot
    local_state: LocalStateSnapshot
    lifecycle: CommitmentLifecycleSnapshot
    organization_snapshot: OrganizationSnapshot
    ledger_totals: Mapping[str, Mapping[str, str]]
    terminal_projection_sha256: str


@dataclass(frozen=True, kw_only=True)
class DisputeResumeResult(DisputeResolutionReplay):
    events: tuple[HarnessRuntimeEvent, ...]
    feedback: FeedbackEvent
    local_state_update: LocalStateUpdate | None


@dataclass(frozen=True, kw_only=True)
class DisputeResolutionResult(DisputeResumeResult):
    checkpoint: DisputeCheckpoint
    quarantine: DisputeQuarantine


class _SeededWriter:
    def __init__(
        self,
        *,
        revision_offset: int = 0,
        known_ids: tuple[str, ...] = (),
    ) -> None:
        self.events: list[HarnessRuntimeEvent] = []
        self._offset = revision_offset
        self._known = set(known_ids)

    def append(
        self,
        event_id: str,
        event_type: str,
        parents: tuple[str, ...],
        payload: Mapping[str, Any],
    ) -> HarnessRuntimeEvent:
        if event_id in self._known:
            raise HarnessCycleError("duplicate dispute runtime event")
        if self._offset + len(self.events) and not parents:
            raise HarnessCycleError("dispute runtime event requires parents")
        if not set(parents) <= self._known:
            raise HarnessCycleError(
                "dispute runtime event has unknown causal parent"
            )
        event = HarnessRuntimeEvent(
            event_id=event_id,
            event_type=event_type,
            event_schema_version=1,
            public_state_revision=self._offset + len(self.events),
            causal_parent_ids=parents,
            payload=payload,
            payload_sha256=_canonical_hash(payload),
        )
        self.events.append(event)
        self._known.add(event_id)
        return event


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


def _configuration_hash(
    *,
    run_id: str,
    task: TaskSpec,
    selection: MultiAdmissionResult,
    candidate: BidCandidate,
    admission_policy: AdmissionPolicy,
    multi_admission_policy: MultiAdmissionPolicy,
    plan: ScriptedActionPlan,
    execution: ScriptedExecutionResult,
    disputed_verifier_decision: ScriptedVerifierDecision,
    initial_local_state: LocalStateSnapshot,
    state_update_manifest: UpdateSurfaceManifest,
    quarantined_state_update_proposal: LocalStateUpdateProposal,
    state_compiler_policy_version: str,
    run_budget: tuple[ResourceAmount, ...],
    admission_at: str,
    action_at: str,
    finished_at: str,
) -> str:
    return _canonical_hash(
        {
            "action_at": action_at,
            "admission_at": admission_at,
            "admission_policy": admission_policy.to_dict(),
            "candidate": candidate.to_dict(),
            "disputed_verifier_decision": {
                "confidence": disputed_verifier_decision.confidence,
                "decision_id": disputed_verifier_decision.decision_id,
                "evaluator_version": (
                    disputed_verifier_decision.evaluator_version
                ),
                "evidence_id": disputed_verifier_decision.evidence_id,
                "feedback_disposition": (
                    disputed_verifier_decision.feedback_disposition.value
                ),
                "issuer": disputed_verifier_decision.issuer.value,
            },
            "execution": {
                "action_status": execution.action_status.value,
                "actual_cost": [
                    item.to_dict() for item in execution.actual_cost
                ],
                "artifact_refs": execution.artifact_refs,
                "evidence_id": execution.evidence_id,
                "evidence_sha256": hashlib.sha256(
                    execution.evidence_bytes
                ).hexdigest(),
                "execution_id": execution.execution_id,
                "issuer": execution.issuer.value,
            },
            "finished_at": finished_at,
            "initial_local_state_sha256": initial_local_state.state_hash(),
            "manifest": state_update_manifest.to_dict(),
            "multi_admission_policy": multi_admission_policy.to_dict(),
            "plan": {
                "issuer": plan.issuer.value,
                "plan_id": plan.plan_id,
                "requested_resources": [
                    item.to_dict() for item in plan.requested_resources
                ],
                "tool": plan.tool,
            },
            "quarantined_proposal_sha256": _canonical_hash(
                quarantined_state_update_proposal.to_dict()
            ),
            "run_budget": [item.to_dict() for item in run_budget],
            "run_id": run_id,
            "selection": selection.to_dict(),
            "state_compiler_policy_version": state_compiler_policy_version,
            "task": task.to_dict(),
        }
    )


def _feedback_from_mapping(value: Mapping[str, Any]) -> FeedbackEvent:
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


def _runtime_evidence(value: Mapping[str, Any]) -> RuntimeEvidence:
    return RuntimeEvidence(
        evidence_id=value["evidence_id"],
        action_id=value["action_id"],
        requirement_id=value["requirement_id"],
        content_sha256=value["content_sha256"],
        artifact_refs=tuple(value["artifact_refs"]),
        provenance_refs=tuple(value["provenance_refs"]),
    )


def run_dispute_to_checkpoint(
    *,
    run_id: str,
    task: TaskSpec,
    selection: MultiAdmissionResult,
    candidate: BidCandidate,
    admission_policy: AdmissionPolicy,
    multi_admission_policy: MultiAdmissionPolicy,
    plan: ScriptedActionPlan,
    execution: ScriptedExecutionResult,
    disputed_verifier_decision: ScriptedVerifierDecision,
    initial_local_state: LocalStateSnapshot,
    state_update_manifest: UpdateSurfaceManifest,
    quarantined_state_update_proposal: LocalStateUpdateProposal,
    state_compiler_policy_version: str,
    run_budget: tuple[ResourceAmount, ...],
    admission_at: str,
    action_at: str,
    finished_at: str,
) -> DisputeCheckpointResult:
    if (
        disputed_verifier_decision.feedback_disposition
        is not FeedbackDisposition.DISPUTED
    ):
        raise HarnessCycleError(
            "dispute checkpoint requires DISPUTED Feedback"
        )
    base = run_scripted_cycle(
        run_id=run_id,
        task=task,
        selection=selection,
        candidate=candidate,
        admission_policy=admission_policy,
        multi_admission_policy=multi_admission_policy,
        plan=plan,
        execution=execution,
        verifier_decision=disputed_verifier_decision,
        initial_local_state=initial_local_state,
        state_update_manifest=state_update_manifest,
        state_update_proposal=quarantined_state_update_proposal,
        state_compiler_policy_version=state_compiler_policy_version,
        run_budget=run_budget,
        admission_at=admission_at,
        action_at=action_at,
        finished_at=finished_at,
    )
    writer = _SeededWriter()
    for event in base.events:
        writer.append(
            event.event_id,
            event.event_type,
            event.causal_parent_ids,
            event.payload,
        )
        if event.event_type == "residual":
            break
    cost_events = tuple(
        event
        for event in base.events
        if event.event_type in {"resource_spend", "resource_return"}
    )
    for event in cost_events:
        writer.append(
            event.event_id,
            event.event_type,
            event.causal_parent_ids,
            event.payload,
        )
    authority = base.feedback.source_authority_by_claim_type[0].authority
    quarantine = DisputeQuarantine(
        quarantine_id=f"quarantine-{base.feedback.feedback_id}",
        commitment_id=base.commitment.commitment_id,
        action_id=base.action.action_id,
        evidence_id=base.evidence.evidence_id,
        feedback_id=base.feedback.feedback_id,
        requirement_id=candidate.bid.target_requirement_id,
        original_agent_id=candidate.bid.agent_id,
        original_verifier_authority=authority,
        evidence_status="quarantined",
        feedback_status="quarantined",
        commitment_status="quarantined",
        accepted_contribution=0,
        experience_update_ids=(),
        created_at=finished_at,
        causal_parent_ids=(
            base.commitment.commitment_id,
            base.action.action_id,
            base.evidence.evidence_id,
            base.feedback.feedback_id,
            f"residual-{base.residual.revision}",
            *(event.event_id for event in cost_events),
        ),
    )
    writer.append(
        quarantine.quarantine_id,
        "dispute_quarantine",
        quarantine.causal_parent_ids,
        {"quarantine": quarantine.to_dict()},
    )
    original_settlement = next(
        event for event in base.events if event.event_type == "settlement"
    )
    writer.append(
        original_settlement.event_id,
        "quarantine_settlement",
        (quarantine.quarantine_id,),
        original_settlement.payload,
    )
    checkpoint_projection = {
        "authority": "harness_quarantine",
        "commitment_id": base.commitment.commitment_id,
        "ledger_totals": {
            key: dict(item)
            for key, item in sorted(base.ledger_totals.items())
        },
        "local_state_sha256": initial_local_state.state_hash(),
        "local_state_version": initial_local_state.state_version,
        "quarantine_id": quarantine.quarantine_id,
        "residual_sha256": _canonical_hash(base.residual.to_dict()),
    }
    checkpoint_event_id = f"dispute-checkpoint-{run_id}"
    writer.append(
        checkpoint_event_id,
        "dispute_checkpoint",
        (
            quarantine.quarantine_id,
            original_settlement.event_id,
            f"residual-{base.residual.revision}",
        ),
        {
            "checkpoint_projection": checkpoint_projection,
            "checkpoint_projection_sha256": _canonical_hash(
                checkpoint_projection
            ),
        },
    )
    events = tuple(writer.events)
    ids = tuple(event.event_id for event in events)
    fingerprints = tuple(
        _canonical_hash(event.to_dict()) for event in events
    )
    config_hash = _configuration_hash(
        run_id=run_id,
        task=task,
        selection=selection,
        candidate=candidate,
        admission_policy=admission_policy,
        multi_admission_policy=multi_admission_policy,
        plan=plan,
        execution=execution,
        disputed_verifier_decision=disputed_verifier_decision,
        initial_local_state=initial_local_state,
        state_update_manifest=state_update_manifest,
        quarantined_state_update_proposal=quarantined_state_update_proposal,
        state_compiler_policy_version=state_compiler_policy_version,
        run_budget=run_budget,
        admission_at=admission_at,
        action_at=action_at,
        finished_at=finished_at,
    )
    content = _checkpoint_content(
        run_id=run_id,
        configuration_sha256=config_hash,
        prefix_event_ids=ids,
        prefix_event_fingerprints=fingerprints,
        next_public_state_revision=len(events),
        last_event_id=checkpoint_event_id,
        commitment=base.commitment,
        action=base.action.to_dict(),
        evidence=base.evidence,
        disputed_feedback=base.feedback,
        residual=base.residual,
        quarantine=quarantine,
        ledger_totals=base.ledger_totals,
        local_state_version=initial_local_state.state_version,
        local_state_sha256=initial_local_state.state_hash(),
    )
    checkpoint = DisputeCheckpoint(
        run_id=run_id,
        configuration_sha256=config_hash,
        prefix_event_ids=ids,
        prefix_event_fingerprints=fingerprints,
        next_public_state_revision=len(events),
        last_event_id=checkpoint_event_id,
        commitment=base.commitment,
        action=base.action.to_dict(),
        evidence=base.evidence,
        disputed_feedback=base.feedback,
        residual=base.residual,
        quarantine=quarantine,
        ledger_totals=base.ledger_totals,
        local_state_version=initial_local_state.state_version,
        local_state_sha256=initial_local_state.state_hash(),
        checkpoint_sha256=_canonical_hash(content),
    )
    return DisputeCheckpointResult(events=events, checkpoint=checkpoint)


def _combined_totals(
    checkpoint: Mapping[str, Mapping[str, str]],
    suffix_ledger: ResourceLedger,
    resource_types: tuple[str, ...],
) -> Mapping[str, Mapping[str, str]]:
    suffix = _ledger_totals(suffix_ledger, resource_types)
    result: dict[str, Mapping[str, str]] = {}
    for resource_type in sorted(set(resource_types)):
        result[resource_type] = MappingProxyType(
            {
                "expected": checkpoint[resource_type]["expected"],
                "shared_pool": format(
                    Decimal(suffix[resource_type]["shared_pool"]).normalize(),
                    "f",
                ),
                "escrow": format(
                    (
                        Decimal(checkpoint[resource_type]["escrow"])
                        + Decimal(suffix[resource_type]["escrow"])
                    ).normalize(),
                    "f",
                ),
                "reserved": format(
                    (
                        Decimal(checkpoint[resource_type]["reserved"])
                        + Decimal(suffix[resource_type]["reserved"])
                    ).normalize(),
                    "f",
                ),
                "spent": format(
                    (
                        Decimal(checkpoint[resource_type]["spent"])
                        + Decimal(suffix[resource_type]["spent"])
                    ).normalize(),
                    "f",
                ),
            }
        )
    return _normalize_totals(result)


def _organization(
    *,
    checkpoint: DisputeCheckpoint,
    local_state: LocalStateSnapshot,
    local_state_update: LocalStateUpdate | None,
    decision: IndependentRevalidationDecision,
    evidence: RevalidationEvidence,
    transition_id: str,
    public_state_revision: int,
) -> OrganizationSnapshot:
    accepted = decision.disposition is FeedbackDisposition.ACCEPTED
    source_ids = (
        () if local_state_update is None else (local_state_update.update_id,)
    )
    parent_ids = [
        checkpoint.commitment.commitment_id,
        checkpoint.last_event_id,
        checkpoint.quarantine.quarantine_id,
        evidence.evidence_id,
        decision.decision_id,
        f"feedback-{decision.decision_id}",
        transition_id,
    ]
    if local_state_update is not None:
        parent_ids.append(local_state_update.update_id)
    action_cost = tuple(
        ResourceAmount(**item)
        for item in checkpoint.action["resource_cost"]
    )
    return build_organization_snapshot(
        run_id=checkpoint.run_id,
        task_id=checkpoint.commitment.task_id,
        checkpoint_id=checkpoint.last_event_id,
        requirement_schema_version=(
            checkpoint.commitment.requirement_schema_version
        ),
        public_state_revision=public_state_revision,
        active_agents=(
            ActiveAgentState(
                agent_id=checkpoint.commitment.agent_id,
                state_version=local_state.state_version,
                source_event_ids=source_ids,
            ),
            ActiveAgentState(
                agent_id=decision.verifier_authority,
                state_version=0,
                source_event_ids=(),
            ),
        ),
        requirement_commitments=(
            RequirementCommitmentLink(
                requirement_id=checkpoint.quarantine.requirement_id,
                commitment_id=checkpoint.commitment.commitment_id,
                agent_id=checkpoint.commitment.agent_id,
            ),
        ),
        communication_edges=(),
        duplicate_distribution=(),
        refusal_distribution=(
            DistributionCount(
                category=f"dispute_resolved_{decision.disposition.value}",
                count=1,
            ),
        ),
        agent_cost_contributions=(
            AgentCostContribution(
                agent_id=checkpoint.commitment.agent_id,
                actual_cost=action_cost,
                accepted_contribution=1 if accepted else 0,
            ),
            AgentCostContribution(
                agent_id=decision.verifier_authority,
                actual_cost=evidence.resource_cost,
                accepted_contribution=0,
            ),
        ),
        central_preset_info=CentralPresetInfo((), (), ()),
        experience_structural_changes=(),
        parent_event_ids=tuple(parent_ids),
        builder_version="dispute-revalidation-v1",
        created_at=decision.decided_at,
    )


def resume_disputed_revalidation(
    *,
    checkpoint: DisputeCheckpoint,
    run_id: str,
    task: TaskSpec,
    selection: MultiAdmissionResult,
    candidate: BidCandidate,
    admission_policy: AdmissionPolicy,
    multi_admission_policy: MultiAdmissionPolicy,
    plan: ScriptedActionPlan,
    execution: ScriptedExecutionResult,
    disputed_verifier_decision: ScriptedVerifierDecision,
    initial_local_state: LocalStateSnapshot,
    state_update_manifest: UpdateSurfaceManifest,
    quarantined_state_update_proposal: LocalStateUpdateProposal,
    state_compiler_policy_version: str,
    run_budget: tuple[ResourceAmount, ...],
    admission_at: str,
    action_at: str,
    finished_at: str,
    revalidation_evidence: RevalidationEvidence,
    revalidation_decision: IndependentRevalidationDecision,
    resolution_state_update_proposal: LocalStateUpdateProposal | None,
) -> DisputeResumeResult:
    config_hash = _configuration_hash(
        run_id=run_id,
        task=task,
        selection=selection,
        candidate=candidate,
        admission_policy=admission_policy,
        multi_admission_policy=multi_admission_policy,
        plan=plan,
        execution=execution,
        disputed_verifier_decision=disputed_verifier_decision,
        initial_local_state=initial_local_state,
        state_update_manifest=state_update_manifest,
        quarantined_state_update_proposal=quarantined_state_update_proposal,
        state_compiler_policy_version=state_compiler_policy_version,
        run_budget=run_budget,
        admission_at=admission_at,
        action_at=action_at,
        finished_at=finished_at,
    )
    if checkpoint.configuration_sha256 != config_hash:
        raise HarnessCycleError("dispute checkpoint configuration mismatch")
    if (
        checkpoint.local_state_version != initial_local_state.state_version
        or checkpoint.local_state_sha256 != initial_local_state.state_hash()
    ):
        raise HarnessCycleError(
            "dispute checkpoint local-state binding mismatch"
        )
    quarantine = checkpoint.quarantine
    if revalidation_decision.verifier_authority in {
        quarantine.original_agent_id,
        quarantine.original_verifier_authority,
    }:
        raise HarnessCycleError(
            "quarantine requires an independent verifier authority"
        )
    if (
        revalidation_evidence.evidence_id == quarantine.evidence_id
        or revalidation_evidence.content_sha256
        == checkpoint.evidence.content_sha256
    ):
        raise HarnessCycleError(
            "revalidation must bind genuinely new Evidence"
        )
    if revalidation_evidence.invalidates_evidence_ids != (
        quarantine.evidence_id,
    ):
        raise HarnessCycleError(
            "revalidation Evidence invalidates binding is incomplete"
        )
    if (
        revalidation_decision.evidence_id
        != revalidation_evidence.evidence_id
        or revalidation_decision.invalidates_evidence_ids
        != (quarantine.evidence_id,)
        or revalidation_decision.invalidates_feedback_ids
        != (quarantine.feedback_id,)
    ):
        raise HarnessCycleError(
            "revalidation decision invalidates bindings are incomplete"
        )
    accepted = (
        revalidation_decision.disposition is FeedbackDisposition.ACCEPTED
    )
    if accepted and resolution_state_update_proposal is None:
        raise HarnessCycleError(
            "accepted revalidation requires LocalState proposal"
        )
    if not accepted and resolution_state_update_proposal is not None:
        raise HarnessCycleError(
            "rejected revalidation cannot produce positive LocalState update"
        )

    writer = _SeededWriter(
        revision_offset=checkpoint.next_public_state_revision,
        known_ids=checkpoint.prefix_event_ids,
    )
    shared = {
        item.resource_type: Decimal(
            checkpoint.ledger_totals[item.resource_type]["shared_pool"]
        )
        for item in run_budget
    }
    ledger = ResourceLedger(shared)
    verifier_account = revalidation_decision.verifier_authority
    reserve_ids: list[str] = []
    for amount in revalidation_evidence.resource_cost:
        grant = _resource_event(
            event_id=(
                f"revalidation-grant-{revalidation_evidence.evidence_id}-"
                f"{amount.resource_type}"
            ),
            operation=ResourceOperation.GRANT,
            amount=amount,
            source=SHARED_POOL,
            target=agent_escrow_account(verifier_account),
        )
        ledger.apply(grant)
        writer.append(
            grant.event_id,
            "revalidation_resource_grant",
            (checkpoint.last_event_id,),
            {"resource_event": grant.to_dict()},
        )
        reserve = _resource_event(
            event_id=(
                f"revalidation-reserve-{revalidation_evidence.evidence_id}-"
                f"{amount.resource_type}"
            ),
            operation=ResourceOperation.RESERVE,
            amount=amount,
            source=agent_escrow_account(verifier_account),
            target=reserved_account(verifier_account),
        )
        ledger.apply(reserve)
        reserve_ids.append(reserve.event_id)
        writer.append(
            reserve.event_id,
            "revalidation_resource_reserve",
            (grant.event_id,),
            {"resource_event": reserve.to_dict()},
        )
    evidence_payload = revalidation_evidence.to_public_dict(
        action_id=quarantine.action_id,
        requirement_id=quarantine.requirement_id,
    )
    writer.append(
        revalidation_evidence.evidence_id,
        "revalidation_evidence",
        (
            checkpoint.last_event_id,
            quarantine.evidence_id,
            *reserve_ids,
        ),
        {
            "content_hex": revalidation_evidence.content.hex(),
            "evidence": evidence_payload,
        },
    )
    spend_ids: list[str] = []
    for amount in revalidation_evidence.resource_cost:
        spend = _resource_event(
            event_id=(
                f"revalidation-spend-{revalidation_evidence.evidence_id}-"
                f"{amount.resource_type}"
            ),
            operation=ResourceOperation.SPEND,
            amount=amount,
            source=reserved_account(verifier_account),
            target=SPENT,
        )
        ledger.apply(spend)
        spend_ids.append(spend.event_id)
        writer.append(
            spend.event_id,
            "revalidation_resource_spend",
            (revalidation_evidence.evidence_id,),
            {"resource_event": spend.to_dict()},
        )
    verifier_settlement_id = (
        f"revalidation-settlement-{revalidation_evidence.evidence_id}"
    )
    returned = ledger.settle_abnormal_termination(
        verifier_account,
        settlement_id=verifier_settlement_id,
    )
    writer.append(
        verifier_settlement_id,
        "revalidation_settlement",
        tuple(spend_ids),
        {
            "agent_id": verifier_account,
            "returned": {
                key: str(value) for key, value in sorted(returned.items())
            },
            "settlement_id": verifier_settlement_id,
        },
    )
    writer.append(
        revalidation_decision.decision_id,
        "revalidation_decision",
        (
            quarantine.quarantine_id,
            revalidation_evidence.evidence_id,
            verifier_settlement_id,
        ),
        {"decision": revalidation_decision.to_dict()},
    )
    feedback = FeedbackEvent(
        feedback_id=f"feedback-{revalidation_decision.decision_id}",
        task_id=task.task_id,
        action_id=quarantine.action_id,
        requirement_deltas=(
            RequirementDelta(
                requirement_id=quarantine.requirement_id,
                disposition=revalidation_decision.disposition,
                evidence_refs=(revalidation_evidence.evidence_id,),
                invalidates_feedback_ids=(quarantine.feedback_id,),
            ),
        ),
        source_kind=FeedbackSourceKind.VERIFIER,
        source_authority_by_claim_type=(
            ClaimAuthority(
                claim_type="requirement_disposition",
                authority=revalidation_decision.verifier_authority,
            ),
        ),
        confidence=revalidation_decision.confidence,
        evidence_refs=(revalidation_evidence.evidence_id,),
    )
    writer.append(
        feedback.feedback_id,
        "revalidation_feedback",
        (
            revalidation_decision.decision_id,
            revalidation_evidence.evidence_id,
        ),
        {"feedback": feedback.to_dict()},
    )
    residual_machine = ResidualStateMachine(task)
    residual_machine.apply_feedback(checkpoint.disputed_feedback)
    residual = residual_machine.apply_feedback(feedback)
    residual_event_id = f"revalidation-residual-{residual.revision}"
    writer.append(
        residual_event_id,
        "revalidation_residual",
        (feedback.feedback_id,),
        {"residual": residual.to_dict()},
    )
    local_state = initial_local_state
    local_state_update: LocalStateUpdate | None = None
    local_state_parent_ids: tuple[str, ...] = ()
    if resolution_state_update_proposal is not None:
        if resolution_state_update_proposal.source_event_window != (
            feedback.feedback_id,
        ):
            raise HarnessCycleError(
                "revalidation LocalState proposal has wrong Feedback source"
            )
        local_state_update = compile_local_state_update(
            snapshot=initial_local_state,
            proposal=resolution_state_update_proposal,
            manifest=state_update_manifest,
            authorized_event_ids=(feedback.feedback_id,),
            compiler_policy_version=state_compiler_policy_version,
            run_finalized=False,
        )
        local_state = apply_local_state_update(
            initial_local_state,
            local_state_update,
        )
        initial_state_parent = (
            f"local-state-initial-{initial_local_state.agent_id}"
            f"-v{initial_local_state.state_version}"
        )
        writer.append(
            local_state_update.update_id,
            "local_state_update",
            (feedback.feedback_id, initial_state_parent),
            {
                "audience": "public",
                "local_state_update": _public_local_state_update(
                    local_state_update,
                    resolution_state_update_proposal,
                ),
                "redaction": "private_values_omitted",
            },
        )
        snapshot_event_id = (
            f"local-state-snapshot-{local_state.agent_id}"
            f"-v{local_state.state_version}"
        )
        writer.append(
            snapshot_event_id,
            "local_state_snapshot",
            (local_state_update.update_id,),
            {
                "audience": "public",
                "local_state_snapshot": _public_local_state(local_state),
                "redaction": "private_values_omitted",
            },
        )
        local_state_parent_ids = (snapshot_event_id,)
    next_status = (
        CommitmentStatus.COMPLETED
        if accepted
        else CommitmentStatus.CANCELLED
    )
    transition, lifecycle = transition_commitment(
        checkpoint.commitment,
        initial_commitment_lifecycle(checkpoint.commitment),
        next_status=next_status,
        reason=(
            "independent revalidation "
            f"{revalidation_decision.disposition.value}"
        ),
        at=revalidation_decision.decided_at,
        run_finalized=False,
    )
    writer.append(
        transition.transition_id,
        "revalidation_commitment_transition",
        (
            residual_event_id,
            verifier_settlement_id,
            *local_state_parent_ids,
        ),
        {"transition": transition.to_dict()},
    )
    totals = _combined_totals(
        checkpoint.ledger_totals,
        ledger,
        tuple(item.resource_type for item in run_budget),
    )
    organization = _organization(
        checkpoint=checkpoint,
        local_state=local_state,
        local_state_update=local_state_update,
        decision=revalidation_decision,
        evidence=revalidation_evidence,
        transition_id=transition.transition_id,
        public_state_revision=(
            checkpoint.next_public_state_revision + len(writer.events)
        ),
    )
    writer.append(
        organization.snapshot_id,
        "dispute_organization_snapshot",
        organization.parent_event_ids,
        {"organization_snapshot": organization.to_dict()},
    )
    terminal_projection_sha256 = _canonical_hash(
        {
            "commitment_lifecycle": lifecycle.to_dict(),
            "ledger_totals": totals,
            "local_state_sha256": local_state.state_hash(),
            "organization_snapshot_sha256": organization.snapshot_hash,
            "quarantine": quarantine.to_dict(),
            "resolution_feedback": feedback.to_dict(),
            "residual": residual.to_dict(),
        }
    )
    writer.append(
        f"dispute-terminal-{run_id}",
        "dispute_terminal",
        (organization.snapshot_id, transition.transition_id),
        {
            "terminal_projection_sha256": (
                terminal_projection_sha256
            )
        },
    )
    return DisputeResumeResult(
        events=tuple(writer.events),
        feedback=feedback,
        local_state_update=local_state_update,
        residual=residual,
        local_state=local_state,
        lifecycle=lifecycle,
        organization_snapshot=organization,
        ledger_totals=totals,
        terminal_projection_sha256=terminal_projection_sha256,
    )


def run_disputed_revalidation(
    *,
    revalidation_evidence: RevalidationEvidence,
    revalidation_decision: IndependentRevalidationDecision,
    resolution_state_update_proposal: LocalStateUpdateProposal | None,
    **base: Any,
) -> DisputeResolutionResult:
    checkpointed = run_dispute_to_checkpoint(**base)
    resumed = resume_disputed_revalidation(
        checkpoint=checkpointed.checkpoint,
        **base,
        revalidation_evidence=revalidation_evidence,
        revalidation_decision=revalidation_decision,
        resolution_state_update_proposal=resolution_state_update_proposal,
    )
    return DisputeResolutionResult(
        events=(*checkpointed.events, *resumed.events),
        checkpoint=checkpointed.checkpoint,
        quarantine=checkpointed.checkpoint.quarantine,
        feedback=resumed.feedback,
        local_state_update=resumed.local_state_update,
        residual=resumed.residual,
        local_state=resumed.local_state,
        lifecycle=resumed.lifecycle,
        organization_snapshot=resumed.organization_snapshot,
        ledger_totals=resumed.ledger_totals,
        terminal_projection_sha256=resumed.terminal_projection_sha256,
    )


def _validate_stream(events: tuple[HarnessRuntimeEvent, ...]) -> None:
    known: set[str] = set()
    terminal = False
    resolution_count = 0
    for index, event in enumerate(events):
        if terminal:
            raise HarnessCycleError("events occur after dispute terminal")
        if event.public_state_revision != index:
            raise HarnessCycleError(
                "dispute runtime revision is not contiguous"
            )
        if event.event_id in known:
            raise HarnessCycleError(
                "duplicate event or double resolution in dispute stream"
            )
        if index and not set(event.causal_parent_ids) <= known:
            raise HarnessCycleError(
                "dispute runtime event has unknown parent"
            )
        if _canonical_hash(event.payload) != event.payload_sha256:
            raise HarnessCycleError(
                "dispute runtime payload hash mismatch"
            )
        known.add(event.event_id)
        if event.event_type == "revalidation_decision":
            resolution_count += 1
        terminal = event.event_type == "dispute_terminal"
    if not terminal:
        raise HarnessCycleError("dispute stream has no terminal")
    if resolution_count != 1:
        raise HarnessCycleError(
            "dispute stream has missing or double resolution"
        )


def replay_disputed_revalidation(
    *,
    events: tuple[HarnessRuntimeEvent, ...],
    resolution_state_update_proposal: LocalStateUpdateProposal | None,
    **base: Any,
) -> DisputeResolutionReplay:
    materialized = tuple(events)
    _validate_stream(materialized)
    quarantines = tuple(
        event
        for event in materialized
        if event.event_type == "dispute_quarantine"
    )
    checkpoints = tuple(
        event
        for event in materialized
        if event.event_type == "dispute_checkpoint"
    )
    evidence_events = tuple(
        event
        for event in materialized
        if event.event_type == "revalidation_evidence"
    )
    decisions = tuple(
        event
        for event in materialized
        if event.event_type == "revalidation_decision"
    )
    if len(quarantines) != 1 or len(checkpoints) != 1:
        raise HarnessCycleError(
            "revalidation cannot skip explicit quarantine checkpoint"
        )
    if len(evidence_events) != 1 or len(decisions) != 1:
        raise HarnessCycleError(
            "revalidation requires one new Evidence and one resolution"
        )
    evidence = RevalidationEvidence.from_event_payload(
        evidence_events[0].payload
    )
    decision = IndependentRevalidationDecision.from_dict(
        decisions[0].payload["decision"]
    )
    quarantine_payload = quarantines[0].payload["quarantine"]
    expected_decision_parents = (
        quarantine_payload["quarantine_id"],
        evidence.evidence_id,
        f"revalidation-settlement-{evidence.evidence_id}",
    )
    if decisions[0].causal_parent_ids != expected_decision_parents:
        raise HarnessCycleError(
            "revalidation decision parent does not bind quarantine"
        )
    if (
        evidence_events[0].causal_parent_ids[:2]
        != (
            checkpoints[0].event_id,
            quarantine_payload["evidence_id"],
        )
    ):
        raise HarnessCycleError(
            "revalidation Evidence parent does not bind checkpoint/quarantine"
        )
    if tuple(evidence.invalidates_evidence_ids) != (
        quarantine_payload["evidence_id"],
    ):
        raise HarnessCycleError(
            "revalidation Evidence invalidates binding is incomplete"
        )
    if (
        decision.invalidates_feedback_ids
        != (quarantine_payload["feedback_id"],)
        or decision.invalidates_evidence_ids
        != (quarantine_payload["evidence_id"],)
    ):
        raise HarnessCycleError(
            "revalidation decision invalidates bindings are incomplete"
        )
    expected = run_disputed_revalidation(
        **base,
        revalidation_evidence=evidence,
        revalidation_decision=decision,
        resolution_state_update_proposal=resolution_state_update_proposal,
    )
    if expected.events != materialized:
        raise HarnessCycleError(
            "disputed revalidation event semantics do not replay"
        )
    return DisputeResolutionReplay(
        residual=expected.residual,
        local_state=expected.local_state,
        lifecycle=expected.lifecycle,
        organization_snapshot=expected.organization_snapshot,
        ledger_totals=expected.ledger_totals,
        terminal_projection_sha256=expected.terminal_projection_sha256,
    )
