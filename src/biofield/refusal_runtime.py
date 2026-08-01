from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Mapping

from .admission import AdmissionPolicy, resolve_admission
from .commitment import initial_commitment_lifecycle
from .contracts import (
    ActiveAgentState,
    AgentCommitment,
    AgentCostContribution,
    AgentRefusal,
    CentralPresetInfo,
    DistributionCount,
    OrganizationSnapshot,
    RequirementCommitmentLink,
    ResourceAmount,
    ResourceEvent,
    ResourceOperation,
)
from .ledger import ResourceLedger, SHARED_POOL, agent_escrow_account
from .local_runtime import (
    HarnessCycleError,
    HarnessRuntimeEvent,
    _EventWriter,
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


@dataclass(frozen=True, kw_only=True)
class RefusalTakeoverReplay:
    organization_snapshot: OrganizationSnapshot
    ledger_totals: Mapping[str, Mapping[str, str]]
    terminal_projection_sha256: str


@dataclass(frozen=True, kw_only=True)
class RefusalTakeoverResult(RefusalTakeoverReplay):
    events: tuple[HarnessRuntimeEvent, ...]
    initial_selection: MultiAdmissionResult
    readmission: MultiAdmissionResult
    refusal: AgentRefusal
    commitment: AgentCommitment


def _parse_time(value: str, name: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise HarnessCycleError(f"{name} must be an ISO-8601 timestamp") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise HarnessCycleError(f"{name} must include a UTC offset")
    return result


def _retry_window(refusal: AgentRefusal) -> tuple[datetime, datetime]:
    values: dict[str, datetime] = {}
    for condition in refusal.retry_conditions:
        key, separator, raw_value = condition.partition("=")
        if separator and key in {"retry_not_before", "retry_expires_at"}:
            values[key] = _parse_time(raw_value, key)
    if set(values) != {"retry_not_before", "retry_expires_at"}:
        raise HarnessCycleError(
            "refusal retry conditions must define not-before and expiry"
        )
    if values["retry_expires_at"] <= values["retry_not_before"]:
        raise HarnessCycleError("refusal retry condition window is invalid")
    return values["retry_not_before"], values["retry_expires_at"]


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
        ready_requirement_ids=tuple(
            sorted({item.bid.target_requirement_id for item in candidates})
        ),
        current_concurrency=0,
        admission_policy=admission_policy,
        policy=multi_policy,
        at=at,
        run_finalized=False,
    )


def _one_selected(
    result: MultiAdmissionResult,
    candidates: tuple[BidCandidate, ...],
) -> BidCandidate:
    if len(result.admitted_bid_ids) != 1:
        raise HarnessCycleError(
            "refusal takeover requires exactly one public selection"
        )
    selected_id = result.admitted_bid_ids[0]
    return next(item for item in candidates if item.bid.bid_id == selected_id)


def _grant(
    candidate: BidCandidate,
    amount: ResourceAmount,
) -> ResourceEvent:
    return ResourceEvent(
        event_id=f"refusal-grant-{candidate.bid.bid_id}-{amount.resource_type}",
        operation=ResourceOperation.GRANT,
        resource_type=amount.resource_type,
        amount=amount.amount,
        source_account=SHARED_POOL,
        target_account=agent_escrow_account(candidate.bid.agent_id),
        idempotency_key=(
            f"refusal-grant-{candidate.bid.bid_id}-{amount.resource_type}"
        ),
    )


def _organization(
    *,
    run_id: str,
    candidates: tuple[BidCandidate, ...],
    refusal: AgentRefusal,
    commitment: AgentCommitment,
    checkpoint_revision: int,
    created_at: str,
) -> OrganizationSnapshot:
    return build_organization_snapshot(
        run_id=run_id,
        task_id=commitment.task_id,
        checkpoint_id=f"checkpoint-{run_id}-refusal-takeover",
        requirement_schema_version=commitment.requirement_schema_version,
        public_state_revision=checkpoint_revision,
        active_agents=tuple(
            ActiveAgentState(
                agent_id=item.bid.agent_id,
                state_version=item.intent.local_state_version,
                source_event_ids=(),
            )
            for item in candidates
        ),
        requirement_commitments=(
            RequirementCommitmentLink(
                requirement_id=commitment.accepted_scope[0],
                commitment_id=commitment.commitment_id,
                agent_id=commitment.agent_id,
            ),
        ),
        communication_edges=(),
        duplicate_distribution=(),
        refusal_distribution=(
            DistributionCount(
                category=refusal.reason_code.value,
                count=1,
            ),
        ),
        agent_cost_contributions=tuple(
            AgentCostContribution(
                agent_id=item.bid.agent_id,
                actual_cost=(),
                accepted_contribution=0,
            )
            for item in candidates
        ),
        central_preset_info=CentralPresetInfo((), (), ()),
        experience_structural_changes=(),
        parent_event_ids=(refusal.refusal_id, commitment.commitment_id),
        builder_version="refusal-takeover-v1",
        created_at=created_at,
    )


def _terminal_hash(
    *,
    initial_selection: MultiAdmissionResult,
    readmission: MultiAdmissionResult,
    commitment: AgentCommitment,
    organization_snapshot: OrganizationSnapshot,
    ledger_totals: Mapping[str, Mapping[str, str]],
) -> str:
    return _canonical_hash(
        {
            "commitment": commitment.to_dict(),
            "initial_selection": initial_selection.to_dict(),
            "ledger_totals": ledger_totals,
            "organization_snapshot_hash": organization_snapshot.snapshot_hash,
            "readmission": readmission.to_dict(),
        }
    )


def run_refusal_takeover(
    *,
    run_id: str,
    candidates: tuple[BidCandidate, ...],
    refusal: AgentRefusal,
    admission_policy: AdmissionPolicy,
    multi_policy: MultiAdmissionPolicy,
    run_budget: tuple[ResourceAmount, ...],
    initial_at: str,
    refused_at: str,
    readmission_at: str,
) -> RefusalTakeoverResult:
    ordered = tuple(sorted(candidates, key=lambda item: item.bid.bid_id))
    if len(ordered) < 3:
        raise HarnessCycleError("refusal takeover requires at least three agents")
    if any(item.intent.local_state_version != 0 for item in ordered):
        raise HarnessCycleError(
            "minimal refusal takeover requires initial local state versions"
        )
    initial_selection = _select(
        candidates=ordered,
        run_budget=run_budget,
        admission_policy=admission_policy,
        multi_policy=multi_policy,
        at=initial_at,
    )
    refused_candidate = _one_selected(initial_selection, ordered)
    refusal.validate_against(refused_candidate.observation)
    if (
        refusal.agent_id != refused_candidate.bid.agent_id
        or refusal.local_state_version
        != refused_candidate.intent.local_state_version
    ):
        raise HarnessCycleError("refusal does not bind selected Agent state")
    refused_time = _parse_time(refused_at, "refused_at")
    if refused_time < _parse_time(initial_at, "initial_at"):
        raise HarnessCycleError("refusal predates initial admission")
    retry_not_before, retry_expiry = _retry_window(refusal)
    readmission_time = _parse_time(readmission_at, "readmission_at")
    if readmission_time < retry_not_before:
        raise HarnessCycleError("refusal retry condition is not ready")
    if readmission_time >= retry_expiry:
        raise HarnessCycleError("refusal retry condition expired")

    remaining = tuple(
        item for item in ordered if item.bid.bid_id not in initial_selection.admitted_bid_ids
    )
    readmission = _select(
        candidates=remaining,
        run_budget=run_budget,
        admission_policy=admission_policy,
        multi_policy=multi_policy,
        at=readmission_at,
    )
    takeover = _one_selected(readmission, remaining)
    ledger = ResourceLedger(
        {
            item.resource_type: Decimal(str(item.amount))
            for item in run_budget
        }
    )
    writer = _EventWriter()
    writer.append(
        initial_selection.result_id,
        "refusal_initial_admission",
        (),
        {
            "at": initial_at,
            "candidate_bid_ids": tuple(item.bid.bid_id for item in ordered),
            "result": initial_selection.to_dict(),
            "tie_break_rule": multi_policy.tie_break_rule,
        },
    )
    selected_event_id = f"refusal-selected-{refused_candidate.bid.bid_id}"
    writer.append(
        selected_event_id,
        "refusal_selected_candidate",
        (initial_selection.result_id,),
        {"candidate": refused_candidate.to_dict()},
    )
    writer.append(
        refusal.refusal_id,
        "agent_refusal",
        (selected_event_id,),
        {"at": refused_at, "refusal": refusal.to_dict()},
    )
    writer.append(
        readmission.result_id,
        "refusal_readmission",
        (refusal.refusal_id,),
        {
            "at": readmission_at,
            "candidate_bid_ids": tuple(item.bid.bid_id for item in remaining),
            "result": readmission.to_dict(),
            "tie_break_rule": multi_policy.tie_break_rule,
        },
    )
    grants: list[ResourceEvent] = []
    for amount in takeover.bid.requested_budget_vector:
        event = _grant(takeover, amount)
        ledger.apply(event)
        grants.append(event)
        writer.append(
            event.event_id,
            "refusal_resource_grant",
            (readmission.result_id,),
            {"resource_event": event.to_dict()},
        )
    decision = resolve_admission(
        bid=takeover.bid,
        intent=takeover.intent,
        observation=takeover.observation,
        resource_grants=tuple(grants),
        run_budget=run_budget,
        policy=admission_policy,
        at=readmission_at,
        run_finalized=False,
    )
    if decision.commitment is None:
        raise HarnessCycleError("takeover Bid failed commitment admission")
    commitment = decision.commitment
    writer.append(
        commitment.commitment_id,
        "refusal_takeover_commitment",
        tuple(item.event_id for item in grants),
        {
            "admission_at": readmission_at,
            "bid_id": takeover.bid.bid_id,
            "commitment": commitment.to_dict(),
        },
    )
    totals = _ledger_totals(
        ledger,
        tuple(item.resource_type for item in run_budget),
    )
    organization = _organization(
        run_id=run_id,
        candidates=ordered,
        refusal=refusal,
        commitment=commitment,
        checkpoint_revision=len(writer.events),
        created_at=readmission_at,
    )
    writer.append(
        organization.snapshot_id,
        "refusal_organization_snapshot",
        (refusal.refusal_id, commitment.commitment_id),
        {"organization_snapshot": organization.to_dict()},
    )
    terminal_hash = _terminal_hash(
        initial_selection=initial_selection,
        readmission=readmission,
        commitment=commitment,
        organization_snapshot=organization,
        ledger_totals=totals,
    )
    writer.append(
        f"refusal-terminal-{run_id}",
        "refusal_terminal",
        (organization.snapshot_id,),
        {"terminal_projection_sha256": terminal_hash},
    )
    return RefusalTakeoverResult(
        events=tuple(writer.events),
        initial_selection=initial_selection,
        readmission=readmission,
        refusal=refusal,
        commitment=commitment,
        organization_snapshot=organization,
        ledger_totals=totals,
        terminal_projection_sha256=terminal_hash,
    )


def replay_refusal_takeover(
    *,
    candidates: tuple[BidCandidate, ...],
    admission_policy: AdmissionPolicy,
    multi_policy: MultiAdmissionPolicy,
    run_budget: tuple[ResourceAmount, ...],
    events: tuple[HarnessRuntimeEvent, ...],
) -> RefusalTakeoverReplay:
    ordered = tuple(sorted(candidates, key=lambda item: item.bid.bid_id))
    known: set[str] = set()
    ledger = ResourceLedger(
        {
            item.resource_type: Decimal(str(item.amount))
            for item in run_budget
        }
    )
    initial: MultiAdmissionResult | None = None
    readmission: MultiAdmissionResult | None = None
    refused_candidate: BidCandidate | None = None
    refusal: AgentRefusal | None = None
    takeover: BidCandidate | None = None
    grants: list[ResourceEvent] = []
    commitment: AgentCommitment | None = None
    organization: OrganizationSnapshot | None = None
    terminal_hash: str | None = None
    readmission_at: str | None = None

    for index, event in enumerate(events):
        if terminal_hash is not None:
            raise HarnessCycleError("events exist after refusal terminal")
        if event.public_state_revision != index:
            raise HarnessCycleError("refusal event revisions are not contiguous")
        if event.event_id in known:
            raise HarnessCycleError("duplicate refusal runtime event")
        if index and not set(event.causal_parent_ids) <= known:
            raise HarnessCycleError("refusal runtime event has unknown parent")
        if _canonical_hash(event.payload) != event.payload_sha256:
            raise HarnessCycleError("refusal event payload hash mismatch")
        known.add(event.event_id)
        payload = event.payload

        if event.event_type == "refusal_initial_admission":
            if index != 0 or event.causal_parent_ids:
                raise HarnessCycleError("initial admission is not root")
            initial = MultiAdmissionResult.from_dict(payload["result"])
            replayed = _select(
                candidates=ordered,
                run_budget=run_budget,
                admission_policy=admission_policy,
                multi_policy=multi_policy,
                at=payload["at"],
            )
            if (
                replayed != initial
                or event.event_id != initial.result_id
                or tuple(payload["candidate_bid_ids"])
                != tuple(item.bid.bid_id for item in ordered)
                or payload["tie_break_rule"] != multi_policy.tie_break_rule
            ):
                raise HarnessCycleError("initial admission does not replay")
            refused_candidate = _one_selected(initial, ordered)
        elif event.event_type == "refusal_selected_candidate":
            if initial is None or refused_candidate is None:
                raise HarnessCycleError("selected candidate lacks admission")
            expected_id = f"refusal-selected-{refused_candidate.bid.bid_id}"
            if (
                event.event_id != expected_id
                or event.causal_parent_ids != (initial.result_id,)
                or _canonical_hash(payload["candidate"])
                != _canonical_hash(refused_candidate.to_dict())
            ):
                raise HarnessCycleError("selected candidate does not replay")
        elif event.event_type == "agent_refusal":
            if refused_candidate is None:
                raise HarnessCycleError("refusal has no selected candidate")
            refusal = AgentRefusal.from_dict(payload["refusal"])
            refusal.validate_against(refused_candidate.observation)
            if (
                refusal.refusal_id != event.event_id
                or refusal.agent_id != refused_candidate.bid.agent_id
                or event.causal_parent_ids
                != (f"refusal-selected-{refused_candidate.bid.bid_id}",)
            ):
                raise HarnessCycleError("refusal does not replay")
        elif event.event_type == "refusal_readmission":
            if initial is None or refusal is None:
                raise HarnessCycleError("readmission has no refusal")
            if event.causal_parent_ids != (refusal.refusal_id,):
                raise HarnessCycleError("forged takeover parent")
            retry_not_before, retry_expiry = _retry_window(refusal)
            checked_at = _parse_time(payload["at"], "readmission_at")
            if checked_at < retry_not_before:
                raise HarnessCycleError("refusal retry condition is not ready")
            if checked_at >= retry_expiry:
                raise HarnessCycleError("refusal retry condition expired")
            remaining = tuple(
                item
                for item in ordered
                if item.bid.bid_id not in initial.admitted_bid_ids
            )
            readmission = MultiAdmissionResult.from_dict(payload["result"])
            replayed = _select(
                candidates=remaining,
                run_budget=run_budget,
                admission_policy=admission_policy,
                multi_policy=multi_policy,
                at=payload["at"],
            )
            if (
                replayed != readmission
                or event.event_id != readmission.result_id
                or tuple(payload["candidate_bid_ids"])
                != tuple(item.bid.bid_id for item in remaining)
            ):
                raise HarnessCycleError("readmission does not replay")
            takeover = _one_selected(readmission, remaining)
            readmission_at = payload["at"]
        elif event.event_type == "refusal_resource_grant":
            if readmission is None or takeover is None:
                raise HarnessCycleError("takeover grant has no readmission")
            resource = ResourceEvent(
                **{
                    **payload["resource_event"],
                    "operation": ResourceOperation(
                        payload["resource_event"]["operation"]
                    ),
                }
            )
            if (
                resource.event_id != event.event_id
                or event.causal_parent_ids != (readmission.result_id,)
                or resource.target_account
                != agent_escrow_account(takeover.bid.agent_id)
            ):
                raise HarnessCycleError("takeover grant does not replay")
            ledger.apply(resource)
            grants.append(resource)
        elif event.event_type == "refusal_takeover_commitment":
            if takeover is None or readmission_at is None:
                raise HarnessCycleError("takeover commitment lacks readmission")
            commitment = AgentCommitment.from_dict(payload["commitment"])
            decision = resolve_admission(
                bid=takeover.bid,
                intent=takeover.intent,
                observation=takeover.observation,
                resource_grants=tuple(grants),
                run_budget=run_budget,
                policy=admission_policy,
                at=payload["admission_at"],
                run_finalized=False,
            )
            if (
                decision.commitment != commitment
                or commitment.commitment_id != event.event_id
                or payload["bid_id"] != takeover.bid.bid_id
                or event.causal_parent_ids
                != tuple(item.event_id for item in grants)
            ):
                raise HarnessCycleError("takeover commitment does not replay")
            initial_commitment_lifecycle(commitment)
        elif event.event_type == "refusal_organization_snapshot":
            if refusal is None or commitment is None or readmission_at is None:
                raise HarnessCycleError("organization lacks takeover state")
            organization = OrganizationSnapshot.from_dict(
                payload["organization_snapshot"]
            )
            projected = _organization(
                run_id=organization.run_id,
                candidates=ordered,
                refusal=refusal,
                commitment=commitment,
                checkpoint_revision=index,
                created_at=readmission_at,
            )
            if (
                organization.snapshot_id != event.event_id
                or organization != projected
                or event.causal_parent_ids
                != (refusal.refusal_id, commitment.commitment_id)
            ):
                raise HarnessCycleError("refusal organization does not replay")
        elif event.event_type == "refusal_terminal":
            if organization is None:
                raise HarnessCycleError("refusal terminal lacks organization")
            if event.causal_parent_ids != (organization.snapshot_id,):
                raise HarnessCycleError("refusal terminal has forged parent")
            terminal_hash = payload["terminal_projection_sha256"]

    if (
        initial is None
        or readmission is None
        or refusal is None
        or commitment is None
        or organization is None
        or terminal_hash is None
    ):
        raise HarnessCycleError("refusal takeover stream is incomplete")
    ledger.assert_conserved()
    totals = _ledger_totals(
        ledger,
        tuple(item.resource_type for item in run_budget),
    )
    expected = _terminal_hash(
        initial_selection=initial,
        readmission=readmission,
        commitment=commitment,
        organization_snapshot=organization,
        ledger_totals=totals,
    )
    if expected != terminal_hash:
        raise HarnessCycleError("refusal terminal projection hash mismatch")
    return RefusalTakeoverReplay(
        organization_snapshot=organization,
        ledger_totals=totals,
        terminal_projection_sha256=terminal_hash,
    )
