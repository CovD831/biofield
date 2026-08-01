from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

from .admission import AdmissionPolicy, resolve_admission
from .commitment import (
    initial_commitment_lifecycle,
    transition_commitment,
)
from .contracts import (
    ActionStatus,
    ActiveAgentState,
    AgentCommitment,
    AgentCostContribution,
    CentralPresetInfo,
    CommitmentLifecycleSnapshot,
    CommitmentStatus,
    DistributionCount,
    OrganizationSnapshot,
    RequirementCommitmentLink,
    ResourceAmount,
    ResourceEvent,
    ResourceOperation,
)
from .ledger import (
    ResourceLedger,
    SHARED_POOL,
    SPENT,
    agent_escrow_account,
    reserved_account,
)
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
)
from .organization import build_organization_snapshot
from .refusal_runtime import _one_selected, _select


@dataclass(frozen=True, kw_only=True)
class ScriptedFailureExecution:
    execution_id: str
    agent_id: str
    requested_resources: tuple[ResourceAmount, ...]
    actual_cost: tuple[ResourceAmount, ...]
    status: ActionStatus
    started_at: str
    finished_at: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "requested_resources", tuple(self.requested_resources)
        )
        object.__setattr__(self, "actual_cost", tuple(self.actual_cost))
        if not self.execution_id or not self.agent_id:
            raise ValueError("execution identity must be non-empty")
        if not self.requested_resources:
            raise ValueError("requested_resources cannot be empty")
        requested = {
            item.resource_type: item.amount
            for item in self.requested_resources
        }
        if len(requested) != len(self.requested_resources):
            raise ValueError("duplicate requested resource types")
        actual = {item.resource_type: item.amount for item in self.actual_cost}
        if len(actual) != len(self.actual_cost):
            raise ValueError("duplicate actual resource types")
        if any(
            amount > requested.get(resource_type, -1)
            for resource_type, amount in actual.items()
        ):
            raise ValueError("actual_cost exceeds requested_resources")
        if not isinstance(self.status, ActionStatus):
            raise ValueError("status must be ActionStatus")

    def to_public_dict(self, commitment_id: str) -> dict[str, object]:
        return {
            "actual_cost": tuple(item.to_dict() for item in self.actual_cost),
            "agent_id": self.agent_id,
            "commitment_id": commitment_id,
            "execution_id": self.execution_id,
            "finished_at": self.finished_at,
            "issuer": "harness_executor",
            "requested_resources": tuple(
                item.to_dict() for item in self.requested_resources
            ),
            "started_at": self.started_at,
            "status": self.status.value,
        }

    @classmethod
    def from_public_dict(
        cls,
        value: Mapping[str, object],
    ) -> "ScriptedFailureExecution":
        return cls(
            execution_id=value["execution_id"],
            agent_id=value["agent_id"],
            requested_resources=tuple(
                ResourceAmount(**item) for item in value["requested_resources"]
            ),
            actual_cost=tuple(
                ResourceAmount(**item) for item in value["actual_cost"]
            ),
            status=ActionStatus(value["status"]),
            started_at=value["started_at"],
            finished_at=value["finished_at"],
        )


@dataclass(frozen=True, kw_only=True)
class FailureReorganizationReplay:
    organization_snapshot: OrganizationSnapshot
    ledger_totals: Mapping[str, Mapping[str, str]]
    terminal_projection_sha256: str


@dataclass(frozen=True, kw_only=True)
class FailureReorganizationResult(FailureReorganizationReplay):
    events: tuple[HarnessRuntimeEvent, ...]
    initial_selection: MultiAdmissionResult
    readmission: MultiAdmissionResult
    commitments: tuple[AgentCommitment, ...]
    lifecycles: tuple[CommitmentLifecycleSnapshot, ...]


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


def _available_budget(
    ledger: ResourceLedger,
    run_budget: tuple[ResourceAmount, ...],
) -> tuple[ResourceAmount, ...]:
    return tuple(
        ResourceAmount(
            item.resource_type,
            float(ledger.balance(item.resource_type, SHARED_POOL)),
        )
        for item in run_budget
    )


def _materialize(
    *,
    writer: _EventWriter,
    ledger: ResourceLedger,
    candidate: BidCandidate,
    selection_parent_id: str,
    selection_event_type: str,
    admission_policy: AdmissionPolicy,
    run_budget: tuple[ResourceAmount, ...],
    admission_at: str,
    execution: ScriptedFailureExecution,
    execution_event_type: str,
    terminal_status: CommitmentStatus,
) -> tuple[
    AgentCommitment,
    CommitmentLifecycleSnapshot,
    str,
]:
    if execution.agent_id != candidate.bid.agent_id:
        raise HarnessCycleError("execution agent does not match selected Bid")
    if execution.status is ActionStatus.SUCCEEDED:
        if terminal_status is not CommitmentStatus.COMPLETED:
            raise HarnessCycleError("successful execution must complete commitment")
    elif terminal_status is not CommitmentStatus.CANCELLED:
        raise HarnessCycleError("failed execution must cancel commitment")

    grants: list[ResourceEvent] = []
    for amount in candidate.bid.requested_budget_vector:
        grant = _resource_event(
            event_id=(
                f"{selection_event_type}-grant-{candidate.bid.bid_id}-"
                f"{amount.resource_type}"
            ),
            operation=ResourceOperation.GRANT,
            amount=amount,
            source=SHARED_POOL,
            target=agent_escrow_account(candidate.bid.agent_id),
        )
        ledger.apply(grant)
        grants.append(grant)
        writer.append(
            grant.event_id,
            f"{selection_event_type}_resource_grant",
            (selection_parent_id,),
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
        raise HarnessCycleError("selected Bid failed commitment admission")
    commitment = decision.commitment
    writer.append(
        commitment.commitment_id,
        f"{selection_event_type}_commitment",
        tuple(item.event_id for item in grants),
        {
            "admission_at": admission_at,
            "bid_id": candidate.bid.bid_id,
            "commitment": commitment.to_dict(),
        },
    )
    lifecycle = initial_commitment_lifecycle(commitment)

    granted = {
        item.resource_type: item.amount
        for item in candidate.bid.requested_budget_vector
    }
    requested = {
        item.resource_type: item.amount
        for item in execution.requested_resources
    }
    if any(
        amount > granted.get(resource_type, -1)
        for resource_type, amount in requested.items()
    ):
        raise HarnessCycleError("execution reservation exceeds commitment")
    reserve_ids: list[str] = []
    for amount in execution.requested_resources:
        reserve = _resource_event(
            event_id=(
                f"{selection_event_type}-reserve-{execution.execution_id}-"
                f"{amount.resource_type}"
            ),
            operation=ResourceOperation.RESERVE,
            amount=amount,
            source=agent_escrow_account(candidate.bid.agent_id),
            target=reserved_account(candidate.bid.agent_id),
        )
        ledger.apply(reserve)
        reserve_ids.append(reserve.event_id)
        writer.append(
            reserve.event_id,
            f"{selection_event_type}_resource_reserve",
            (commitment.commitment_id,),
            {"resource_event": reserve.to_dict()},
        )
    writer.append(
        execution.execution_id,
        execution_event_type,
        (commitment.commitment_id, *reserve_ids),
        {"execution": execution.to_public_dict(commitment.commitment_id)},
    )
    actual = {item.resource_type: item.amount for item in execution.actual_cost}
    cost_ids: list[str] = []
    for amount in execution.requested_resources:
        spent = actual.get(amount.resource_type, 0)
        if spent:
            spend_amount = ResourceAmount(amount.resource_type, spent)
            spend = _resource_event(
                event_id=(
                    f"{selection_event_type}-spend-{execution.execution_id}-"
                    f"{amount.resource_type}"
                ),
                operation=ResourceOperation.SPEND,
                amount=spend_amount,
                source=reserved_account(candidate.bid.agent_id),
                target=SPENT,
            )
            ledger.apply(spend)
            cost_ids.append(spend.event_id)
            writer.append(
                spend.event_id,
                f"{selection_event_type}_resource_spend",
                (execution.execution_id,),
                {"resource_event": spend.to_dict()},
            )
        unused = amount.amount - spent
        if unused:
            returned = _resource_event(
                event_id=(
                    f"{selection_event_type}-return-{execution.execution_id}-"
                    f"{amount.resource_type}"
                ),
                operation=ResourceOperation.RETURN,
                amount=ResourceAmount(amount.resource_type, unused),
                source=reserved_account(candidate.bid.agent_id),
                target=SHARED_POOL,
            )
            ledger.apply(returned)
            cost_ids.append(returned.event_id)
            writer.append(
                returned.event_id,
                f"{selection_event_type}_resource_return",
                (execution.execution_id,),
                {"resource_event": returned.to_dict()},
            )
    transition, lifecycle = transition_commitment(
        commitment,
        lifecycle,
        next_status=terminal_status,
        reason=f"executor {execution.status.value}",
        at=execution.finished_at,
        run_finalized=False,
    )
    writer.append(
        transition.transition_id,
        f"{selection_event_type}_commitment_transition",
        (execution.execution_id, *cost_ids),
        {"transition": transition.to_dict()},
    )
    settlement_id = f"{selection_event_type}-settlement-{commitment.commitment_id}"
    returned = ledger.settle_abnormal_termination(
        candidate.bid.agent_id,
        settlement_id=settlement_id,
    )
    writer.append(
        settlement_id,
        f"{selection_event_type}_settlement",
        (transition.transition_id,),
        {
            "agent_id": candidate.bid.agent_id,
            "returned": {
                key: str(value) for key, value in sorted(returned.items())
            },
            "settlement_id": settlement_id,
        },
    )
    return commitment, lifecycle, settlement_id


def _organization(
    *,
    run_id: str,
    candidates: tuple[BidCandidate, ...],
    commitments: tuple[AgentCommitment, ...],
    lifecycles: tuple[CommitmentLifecycleSnapshot, ...],
    executions: tuple[ScriptedFailureExecution, ...],
    checkpoint_revision: int,
) -> OrganizationSnapshot:
    costs = {
        execution.agent_id: execution.actual_cost
        for execution in executions
    }
    return build_organization_snapshot(
        run_id=run_id,
        task_id=commitments[0].task_id,
        checkpoint_id=f"checkpoint-{run_id}-failure-reorganization",
        requirement_schema_version=commitments[0].requirement_schema_version,
        public_state_revision=checkpoint_revision,
        active_agents=tuple(
            ActiveAgentState(
                agent_id=item.bid.agent_id,
                state_version=0,
                source_event_ids=(),
            )
            for item in candidates
        ),
        requirement_commitments=tuple(
            RequirementCommitmentLink(
                requirement_id=commitment.accepted_scope[0],
                commitment_id=commitment.commitment_id,
                agent_id=commitment.agent_id,
            )
            for commitment in commitments
        ),
        communication_edges=(),
        duplicate_distribution=(),
        refusal_distribution=(
            DistributionCount(category="executor_failure", count=1),
        ),
        agent_cost_contributions=tuple(
            AgentCostContribution(
                agent_id=item.bid.agent_id,
                actual_cost=costs.get(item.bid.agent_id, ()),
                accepted_contribution=0,
            )
            for item in candidates
        ),
        central_preset_info=CentralPresetInfo((), (), ()),
        experience_structural_changes=(),
        parent_event_ids=tuple(
            (
                *(item.commitment_id for item in commitments),
                *(item.transition_ids[0] for item in lifecycles),
            )
        ),
        builder_version="failure-reorganization-v1",
        created_at=executions[-1].finished_at,
    )


def _terminal_hash(
    *,
    initial: MultiAdmissionResult,
    readmission: MultiAdmissionResult,
    commitments: tuple[AgentCommitment, ...],
    lifecycles: tuple[CommitmentLifecycleSnapshot, ...],
    organization: OrganizationSnapshot,
    totals: Mapping[str, Mapping[str, str]],
) -> str:
    return _canonical_hash(
        {
            "commitments": [item.to_dict() for item in commitments],
            "initial_selection": initial.to_dict(),
            "ledger_totals": totals,
            "lifecycles": [item.to_dict() for item in lifecycles],
            "organization_snapshot_hash": organization.snapshot_hash,
            "readmission": readmission.to_dict(),
        }
    )


def run_failure_reorganization(
    *,
    run_id: str,
    candidates: tuple[BidCandidate, ...],
    admission_policy: AdmissionPolicy,
    multi_policy: MultiAdmissionPolicy,
    run_budget: tuple[ResourceAmount, ...],
    initial_at: str,
    initial_execution: ScriptedFailureExecution,
    readmission_at: str,
    takeover_execution: ScriptedFailureExecution,
) -> FailureReorganizationResult:
    ordered = tuple(sorted(candidates, key=lambda item: item.bid.bid_id))
    if len(ordered) < 3 or any(item.intent.local_state_version for item in ordered):
        raise HarnessCycleError(
            "minimal failure reorganization requires three initial agents"
        )
    if initial_execution.status is ActionStatus.SUCCEEDED:
        raise HarnessCycleError("initial execution must fail")
    if takeover_execution.status is not ActionStatus.SUCCEEDED:
        raise HarnessCycleError("takeover execution must succeed")
    initial = _select(
        candidates=ordered,
        run_budget=run_budget,
        admission_policy=admission_policy,
        multi_policy=multi_policy,
        at=initial_at,
    )
    first = _one_selected(initial, ordered)
    ledger = ResourceLedger(
        {
            item.resource_type: Decimal(str(item.amount))
            for item in run_budget
        }
    )
    writer = _EventWriter()
    writer.append(
        initial.result_id,
        "failure_initial_admission",
        (),
        {
            "at": initial_at,
            "candidate_bid_ids": tuple(item.bid.bid_id for item in ordered),
            "result": initial.to_dict(),
            "run_id": run_id,
        },
    )
    first_commitment, first_lifecycle, first_settlement = _materialize(
        writer=writer,
        ledger=ledger,
        candidate=first,
        selection_parent_id=initial.result_id,
        selection_event_type="failure",
        admission_policy=admission_policy,
        run_budget=run_budget,
        admission_at=initial_at,
        execution=initial_execution,
        execution_event_type="failure_execution",
        terminal_status=CommitmentStatus.CANCELLED,
    )
    remaining = tuple(
        item for item in ordered if item.bid.bid_id not in initial.admitted_bid_ids
    )
    available = _available_budget(ledger, run_budget)
    readmission = _select(
        candidates=remaining,
        run_budget=available,
        admission_policy=admission_policy,
        multi_policy=multi_policy,
        at=readmission_at,
    )
    takeover = _one_selected(readmission, remaining)
    writer.append(
        readmission.result_id,
        "failure_readmission",
        (first_settlement,),
        {
            "at": readmission_at,
            "available_budget": tuple(item.to_dict() for item in available),
            "candidate_bid_ids": tuple(item.bid.bid_id for item in remaining),
            "excluded_failed_bid_ids": initial.admitted_bid_ids,
            "result": readmission.to_dict(),
        },
    )
    second_commitment, second_lifecycle, second_settlement = _materialize(
        writer=writer,
        ledger=ledger,
        candidate=takeover,
        selection_parent_id=readmission.result_id,
        selection_event_type="takeover",
        admission_policy=admission_policy,
        run_budget=available,
        admission_at=readmission_at,
        execution=takeover_execution,
        execution_event_type="takeover_execution",
        terminal_status=CommitmentStatus.COMPLETED,
    )
    commitments = (first_commitment, second_commitment)
    lifecycles = (first_lifecycle, second_lifecycle)
    totals = _ledger_totals(
        ledger, tuple(item.resource_type for item in run_budget)
    )
    organization = _organization(
        run_id=run_id,
        candidates=ordered,
        commitments=commitments,
        lifecycles=lifecycles,
        executions=(initial_execution, takeover_execution),
        checkpoint_revision=len(writer.events),
    )
    writer.append(
        organization.snapshot_id,
        "failure_organization_snapshot",
        (
            first_commitment.commitment_id,
            second_commitment.commitment_id,
            first_lifecycle.transition_ids[0],
            second_lifecycle.transition_ids[0],
            second_settlement,
        ),
        {"organization_snapshot": organization.to_dict()},
    )
    projection_hash = _terminal_hash(
        initial=initial,
        readmission=readmission,
        commitments=commitments,
        lifecycles=lifecycles,
        organization=organization,
        totals=totals,
    )
    writer.append(
        f"failure-terminal-{run_id}",
        "failure_terminal",
        (organization.snapshot_id,),
        {"terminal_projection_sha256": projection_hash},
    )
    return FailureReorganizationResult(
        events=tuple(writer.events),
        initial_selection=initial,
        readmission=readmission,
        commitments=commitments,
        lifecycles=lifecycles,
        organization_snapshot=organization,
        ledger_totals=totals,
        terminal_projection_sha256=projection_hash,
    )


def replay_failure_reorganization(
    *,
    candidates: tuple[BidCandidate, ...],
    admission_policy: AdmissionPolicy,
    multi_policy: MultiAdmissionPolicy,
    run_budget: tuple[ResourceAmount, ...],
    events: tuple[HarnessRuntimeEvent, ...],
) -> FailureReorganizationReplay:
    known: set[str] = set()
    commitment_ids: list[str] = []
    executed_commitments: set[str] = set()
    failure_settlement_id: str | None = None
    initial_at: str | None = None
    readmission_at: str | None = None
    run_id: str | None = None
    initial_execution: ScriptedFailureExecution | None = None
    takeover_execution: ScriptedFailureExecution | None = None

    for index, event in enumerate(events):
        if event.public_state_revision != index:
            raise HarnessCycleError("failure event revisions are not contiguous")
        if event.event_id in known:
            raise HarnessCycleError("duplicate failure runtime event")
        if index and not set(event.causal_parent_ids) <= known:
            raise HarnessCycleError("failure runtime event has unknown parent")
        if _canonical_hash(event.payload) != event.payload_sha256:
            raise HarnessCycleError("failure event payload hash mismatch")
        known.add(event.event_id)
        payload = event.payload
        if event.event_type == "failure_initial_admission":
            initial_at = payload["at"]
            run_id = payload["run_id"]
        elif event.event_type in {
            "failure_commitment",
            "takeover_commitment",
        }:
            commitment_ids.append(event.event_id)
        elif event.event_type in {
            "failure_execution",
            "takeover_execution",
        }:
            execution_payload = payload["execution"]
            commitment_id = execution_payload["commitment_id"]
            if commitment_id in executed_commitments:
                raise HarnessCycleError("same commitment has double execution")
            if commitment_id not in commitment_ids:
                if event.event_type == "failure_execution":
                    raise HarnessCycleError("forged failure parent")
                raise HarnessCycleError("execution has unknown commitment")
            if commitment_id not in event.causal_parent_ids:
                if event.event_type == "failure_execution":
                    raise HarnessCycleError("forged failure parent")
                raise HarnessCycleError("execution does not bind commitment")
            executed_commitments.add(commitment_id)
            execution = ScriptedFailureExecution.from_public_dict(
                execution_payload
            )
            if event.event_type == "failure_execution":
                initial_execution = execution
            else:
                takeover_execution = execution
        elif event.event_type == "failure_settlement":
            failure_settlement_id = event.event_id
        elif event.event_type == "failure_readmission":
            if event.causal_parent_ids != (failure_settlement_id,):
                raise HarnessCycleError("readmission skipped settlement barrier")
            failed_ids = tuple(payload["excluded_failed_bid_ids"])
            candidate_ids = tuple(payload["candidate_bid_ids"])
            if set(failed_ids).intersection(candidate_ids):
                raise HarnessCycleError("failed Agent was immediately reselected")
            expected_remaining = tuple(
                item.bid.bid_id
                for item in sorted(candidates, key=lambda item: item.bid.bid_id)
                if item.bid.bid_id not in failed_ids
            )
            if candidate_ids != expected_remaining:
                raise HarnessCycleError("failed Agent candidate set was forged")
            readmission_at = payload["at"]

    if (
        initial_at is None
        or readmission_at is None
        or run_id is None
        or initial_execution is None
        or takeover_execution is None
    ):
        raise HarnessCycleError("failure reorganization stream is incomplete")
    try:
        expected = run_failure_reorganization(
            run_id=run_id,
            candidates=candidates,
            admission_policy=admission_policy,
            multi_policy=multi_policy,
            run_budget=run_budget,
            initial_at=initial_at,
            initial_execution=initial_execution,
            readmission_at=readmission_at,
            takeover_execution=takeover_execution,
        )
    except (ValueError, HarnessCycleError) as error:
        raise HarnessCycleError(
            "failure reorganization semantics do not replay"
        ) from error
    if expected.events != events:
        raise HarnessCycleError(
            "failure reorganization semantics do not replay"
        )
    return FailureReorganizationReplay(
        organization_snapshot=expected.organization_snapshot,
        ledger_totals=expected.ledger_totals,
        terminal_projection_sha256=expected.terminal_projection_sha256,
    )
