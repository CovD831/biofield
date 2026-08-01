from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from .artifacts import RunArtifactSchemas, RunArtifactStore
from .contracts import (
    ActionObservation,
    ActionStatus,
    ClaimAuthority,
    DependencyKind,
    FeedbackDisposition,
    FeedbackEvent,
    FeedbackSourceKind,
    RequirementDelta,
    RequirementDependency,
    RequirementSpec,
    RequirementStatus,
    ResourceAmount,
    ResourceEvent,
    ResourceLimit,
    ResourceOperation,
    ResidualSnapshot,
    RunTerminalStatus,
    TaskSpec,
)
from .e0 import PUBLIC_EVENT_SCHEMA_VERSION, PublicEvent
from .evidence_task import (
    EvidenceTaskBundle,
    f0_requirement_disposition,
    f0_verifier_binding,
)
from .ledger import (
    SHARED_POOL,
    SPENT,
    LedgerTotals,
    ResourceLedger,
    agent_escrow_account,
    reserved_account,
)
from .residual import ResidualStateMachine


FACT_REQUIREMENT = "fact_extraction"
CONFLICT_REQUIREMENT = "contradiction_resolution"
DECISION_REQUIREMENT = "decision_synthesis"

ROLE_BY_REQUIREMENT = {
    FACT_REQUIREMENT: "agent.fact",
    CONFLICT_REQUIREMENT: "agent.conflict",
    DECISION_REQUIREMENT: "agent.decision",
}


class RunAlreadyTerminal(RuntimeError):
    """Raised when an F0 experiment is executed after it reached a terminal state."""


class _F0PublicEventWriter:
    def __init__(self, store: RunArtifactStore) -> None:
        self._store = store
        self._next_sequence = 0

    def append(
        self,
        *,
        event_id: str,
        event_type: str,
        payload: Any,
        causal_parent_ids: tuple[str, ...] = (),
    ) -> PublicEvent:
        to_dict = getattr(payload, "to_dict", None)
        value = to_dict() if callable(to_dict) else payload
        event = PublicEvent(
            schema_version=PUBLIC_EVENT_SCHEMA_VERSION,
            event_id=event_id,
            event_type=event_type,
            sequence=self._next_sequence,
            causal_parent_ids=causal_parent_ids,
            payload=value,
        )
        self._store.append_event(event)
        self._next_sequence += 1
        return event


@dataclass(frozen=True, kw_only=True)
class F0RunConfig:
    output_directory: Path
    run_id: str
    action_budget: int = 3
    token_budget: int = 0
    max_cycles: int = 5

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_directory", Path(self.output_directory))
        if not self.run_id or not self.run_id.strip():
            raise ValueError("run_id must be non-empty")
        if (
            isinstance(self.action_budget, bool)
            or not isinstance(self.action_budget, int)
            or self.action_budget < 0
        ):
            raise ValueError("action_budget must be a non-negative integer")
        if (
            isinstance(self.token_budget, bool)
            or not isinstance(self.token_budget, int)
            or self.token_budget < 0
        ):
            raise ValueError("token_budget must be a non-negative integer")
        if (
            isinstance(self.max_cycles, bool)
            or not isinstance(self.max_cycles, int)
            or self.max_cycles < 1
        ):
            raise ValueError("max_cycles must be a positive integer")


@dataclass(frozen=True)
class F0Allocation:
    allocation_id: str
    cycle: int
    agent_id: str
    requirement_id: str
    residual_revision: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "allocation_id": self.allocation_id,
            "cycle": self.cycle,
            "agent_id": self.agent_id,
            "requirement_id": self.requirement_id,
            "residual_revision": self.residual_revision,
        }


@dataclass(frozen=True)
class F0Execution:
    status: ActionStatus
    artifact: Mapping[str, Any]
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ns: int = 0
    provider_audit: Mapping[str, Any] | None = None


class F0Executor(Protocol):
    mode: str
    token_reservation: int

    def execute(
        self,
        *,
        requirement_id: str,
        action_id: str,
        cycle: int,
        prior_artifacts: Mapping[str, Mapping[str, Any]],
    ) -> F0Execution: ...


class DeterministicF0Executor:
    mode = "deterministic"
    token_reservation = 0

    def __init__(
        self,
        bundle: EvidenceTaskBundle,
        *,
        fail_on_requirement: str | None = None,
        invalid_on_requirement: str | None = None,
    ) -> None:
        self.bundle = bundle
        self.fail_on_requirement = fail_on_requirement
        self.invalid_on_requirement = invalid_on_requirement

    def execute(
        self,
        *,
        requirement_id: str,
        action_id: str,
        cycle: int,
        prior_artifacts: Mapping[str, Mapping[str, Any]],
    ) -> F0Execution:
        del action_id, cycle, prior_artifacts
        if requirement_id == self.fail_on_requirement:
            return F0Execution(
                status=ActionStatus.FAILED,
                artifact={"requirement_id": requirement_id, "error": "injected failure"},
                error="injected failure",
            )
        if requirement_id == self.invalid_on_requirement:
            return F0Execution(
                status=ActionStatus.SUCCEEDED,
                artifact=_empty_artifact(requirement_id),
            )
        key = self.bundle.answer_key
        if requirement_id == FACT_REQUIREMENT:
            artifact: Mapping[str, Any] = {
                "key_facts": [
                    {
                        "fact_id": fact.fact_id,
                        "value": fact.accepted_values[0],
                        "citations": list(
                            fact.supporting_material_ids[: fact.minimum_citations]
                        ),
                    }
                    for fact in key.key_facts
                ]
            }
        elif requirement_id == CONFLICT_REQUIREMENT:
            artifact = {
                "contradictions": [
                    {
                        "contradiction_id": contradiction.contradiction_id,
                        "material_ids": list(contradiction.material_ids),
                    }
                    for contradiction in key.contradictions
                ]
            }
        elif requirement_id == DECISION_REQUIREMENT:
            artifact = {"decision": key.decision}
        else:  # pragma: no cover - task construction owns the closed set
            raise ValueError(f"unknown F0 requirement: {requirement_id}")
        return F0Execution(status=ActionStatus.SUCCEEDED, artifact=artifact)


@dataclass(frozen=True)
class F0RunResult:
    status: RunTerminalStatus
    reason: str
    cycles: int
    residual: ResidualSnapshot
    allocations: tuple[F0Allocation, ...]
    actions: tuple[ActionObservation, ...]
    feedback: tuple[FeedbackEvent, ...]
    ledger_totals: Mapping[str, LedgerTotals]
    final_state_sha256: str
    run_directory: Path


def build_f0_task_spec(
    bundle: EvidenceTaskBundle,
    *,
    action_budget: int,
    token_budget: int = 0,
) -> TaskSpec:
    return TaskSpec(
        task_id=f"f0.{bundle.task.task_id}.v{bundle.task.task_version}",
        requirement_schema_version=1,
        goal=bundle.task.prompt,
        requirements=(
            RequirementSpec(FACT_REQUIREMENT, "Extract verified facts with citations"),
            RequirementSpec(
                CONFLICT_REQUIREMENT,
                "Identify contradictions across source materials",
            ),
            RequirementSpec(
                DECISION_REQUIREMENT,
                "Synthesize a decision from verified facts and contradictions",
            ),
        ),
        requirement_dependencies=(
            RequirementDependency(
                requirement_id=CONFLICT_REQUIREMENT,
                depends_on_requirement_id=FACT_REQUIREMENT,
                kind=DependencyKind.REQUIRES,
            ),
            RequirementDependency(
                requirement_id=DECISION_REQUIREMENT,
                depends_on_requirement_id=FACT_REQUIREMENT,
                kind=DependencyKind.REQUIRES,
            ),
            RequirementDependency(
                requirement_id=DECISION_REQUIREMENT,
                depends_on_requirement_id=CONFLICT_REQUIREMENT,
                kind=DependencyKind.REQUIRES,
            ),
        ),
        constraints=("Only cited fixture materials may be treated as evidence",),
        acceptance_rules=("All three required dimensions are satisfied by verifier feedback",),
        resource_limits=(
            ResourceLimit("action_units", float(action_budget)),
            ResourceLimit("tokens", float(token_budget)),
        ),
    )


class F0Experiment:
    def __init__(
        self,
        *,
        bundle: EvidenceTaskBundle,
        executor: F0Executor,
        config: F0RunConfig,
    ) -> None:
        self.bundle = bundle
        self.executor = executor
        self.config = config
        self.task = build_f0_task_spec(
            bundle,
            action_budget=config.action_budget,
            token_budget=config.token_budget,
        )
        self._result: F0RunResult | None = None

    def run(self) -> F0RunResult:
        if self._result is not None:
            raise RunAlreadyTerminal("F0 experiment is already terminal")

        store = RunArtifactStore.create(
            self.config.output_directory,
            "f0-contract" if self.executor.mode == "deterministic" else "f0-model",
            self.config.run_id,
            schemas=_f0_schemas(),
        )
        store.write_config(
            {
                "experiment_id": "f0",
                "protocol_version": 1,
                "task_id": self.task.task_id,
                "task_version": self.bundle.task.task_version,
                "executor_mode": self.executor.mode,
                "action_budget": self.config.action_budget,
                "token_budget": self.config.token_budget,
                "max_cycles": self.config.max_cycles,
                "roles": dict(ROLE_BY_REQUIREMENT),
            }
        )
        event_writer = _F0PublicEventWriter(store)
        run_started_event = event_writer.append(
            event_id="run-started",
            event_type="run_started",
            payload={
                "experiment_id": "f0",
                "protocol_version": 1,
                "task_id": self.task.task_id,
                "run_id": self.config.run_id,
                "stream_kind": "f0.native.v2",
                "task_spec": self.task.to_dict(),
                "initial_resources": {
                    "action_units": self.config.action_budget,
                    "tokens": self.config.token_budget,
                },
                "max_cycles": self.config.max_cycles,
                "token_reservation": self.executor.token_reservation,
                "verifier_binding": f0_verifier_binding(self.bundle),
            },
        )
        last_state_event_id = run_started_event.event_id

        machine = ResidualStateMachine(self.task)
        ledger = ResourceLedger(
            {
                "action_units": Decimal(self.config.action_budget),
                "tokens": Decimal(self.config.token_budget),
            }
        )
        allocations: list[F0Allocation] = []
        actions: list[ActionObservation] = []
        executions: list[F0Execution] = []
        feedback_events: list[FeedbackEvent] = []
        feedback_by_requirement: dict[str, list[FeedbackEvent]] = {}
        artifacts: dict[str, Mapping[str, Any]] = {}
        artifact_refs_by_requirement: dict[str, str] = {}
        status = RunTerminalStatus.MAX_CYCLES
        reason = "maximum cycle count reached"

        for cycle in range(self.config.max_cycles):
            snapshot = machine.snapshot()
            if snapshot.complete:
                status = RunTerminalStatus.COMPLETED
                reason = "all required evidence accepted"
                break
            if ledger.balance("action_units", SHARED_POOL) < Decimal(1):
                status = RunTerminalStatus.BUDGET_EXHAUSTED
                reason = "no action budget remains"
                break
            if ledger.balance("tokens", SHARED_POOL) < Decimal(
                self.executor.token_reservation
            ):
                status = RunTerminalStatus.BUDGET_EXHAUSTED
                reason = "insufficient tokens for the next action reservation"
                break

            requirement_id = _next_ready_requirement(self.task, snapshot)
            if requirement_id is None:
                status = RunTerminalStatus.FAILED
                reason = "no dependency-ready unmet requirement"
                break
            agent_id = ROLE_BY_REQUIREMENT[requirement_id]
            allocation = F0Allocation(
                allocation_id=f"allocation-{cycle:03d}",
                cycle=cycle,
                agent_id=agent_id,
                requirement_id=requirement_id,
                residual_revision=snapshot.revision,
            )
            allocations.append(allocation)
            allocation_event = event_writer.append(
                event_id=allocation.allocation_id,
                event_type="allocation",
                payload=allocation,
                causal_parent_ids=(last_state_event_id,),
            )

            action_id = f"action-{cycle:03d}"
            action_parent_ids = [allocation_event.event_id]
            resource_parent_id = allocation_event.event_id
            for operation, source, target in (
                (
                    ResourceOperation.GRANT,
                    SHARED_POOL,
                    agent_escrow_account(agent_id),
                ),
                (
                    ResourceOperation.RESERVE,
                    agent_escrow_account(agent_id),
                    reserved_account(agent_id),
                ),
            ):
                resource_event = _resource_event(
                    action_id=action_id,
                    operation=operation,
                    source=source,
                    target=target,
                    resource_type="action_units",
                    amount=1,
                )
                ledger.apply(resource_event)
                public_resource_event = event_writer.append(
                    event_id=resource_event.event_id,
                    event_type="resource",
                    payload=resource_event,
                    causal_parent_ids=(resource_parent_id,),
                )
                resource_parent_id = public_resource_event.event_id
                action_parent_ids.append(public_resource_event.event_id)

            if self.executor.token_reservation:
                token_parent_id = allocation_event.event_id
                for operation, source, target in (
                    (
                        ResourceOperation.GRANT,
                        SHARED_POOL,
                        agent_escrow_account(agent_id),
                    ),
                    (
                        ResourceOperation.RESERVE,
                        agent_escrow_account(agent_id),
                        reserved_account(agent_id),
                    ),
                ):
                    token_event = _resource_event(
                        action_id=action_id,
                        operation=operation,
                        source=source,
                        target=target,
                        resource_type="tokens",
                        amount=self.executor.token_reservation,
                    )
                    ledger.apply(token_event)
                    public_token_event = event_writer.append(
                        event_id=token_event.event_id,
                        event_type="resource",
                        payload=token_event,
                        causal_parent_ids=(token_parent_id,),
                    )
                    token_parent_id = public_token_event.event_id
                    action_parent_ids.append(public_token_event.event_id)

            execution = self.executor.execute(
                requirement_id=requirement_id,
                action_id=action_id,
                cycle=cycle,
                prior_artifacts=artifacts,
            )
            executions.append(execution)
            if execution.provider_audit is not None:
                model_event = event_writer.append(
                    event_id=f"model-{action_id}",
                    event_type="model_invocation",
                    payload={
                        "input_tokens": execution.input_tokens,
                        "output_tokens": execution.output_tokens,
                        "latency_ns": execution.latency_ns,
                        "audit": dict(execution.provider_audit),
                    },
                    causal_parent_ids=tuple(dict.fromkeys(action_parent_ids)),
                )
                action_parent_ids.append(model_event.event_id)
            artifact_filename = f"{action_id}.json"
            artifact_path = store.write_artifact(artifact_filename, execution.artifact)
            artifact_ref = str(artifact_path.relative_to(store.run_directory))
            artifacts[requirement_id] = dict(execution.artifact)
            prior_input_refs = tuple(artifact_refs_by_requirement.values())
            artifact_refs_by_requirement[requirement_id] = artifact_ref

            spend_event = _resource_event(
                action_id=action_id,
                operation=ResourceOperation.SPEND,
                source=reserved_account(agent_id),
                target=SPENT,
                resource_type="action_units",
                amount=1,
            )
            ledger.apply(spend_event)
            public_spend_event = event_writer.append(
                event_id=spend_event.event_id,
                event_type="resource",
                payload=spend_event,
                causal_parent_ids=(
                    f"resource-{action_id}-action_units-reserve",
                ),
            )
            action_parent_ids.append(public_spend_event.event_id)

            actual_tokens = execution.input_tokens + execution.output_tokens
            token_accounting_error: str | None = None
            if actual_tokens > self.executor.token_reservation:
                token_accounting_error = (
                    "actual token use exceeded the pre-action reservation"
                )
                actual_tokens = self.executor.token_reservation
            if actual_tokens:
                token_spend = _resource_event(
                    action_id=action_id,
                    operation=ResourceOperation.SPEND,
                    source=reserved_account(agent_id),
                    target=SPENT,
                    resource_type="tokens",
                    amount=actual_tokens,
                )
                ledger.apply(token_spend)
                public_token_spend = event_writer.append(
                    event_id=token_spend.event_id,
                    event_type="resource",
                    payload=token_spend,
                    causal_parent_ids=(
                        f"resource-{action_id}-tokens-reserve",
                    ),
                )
                action_parent_ids.append(public_token_spend.event_id)
            unused_tokens = self.executor.token_reservation - actual_tokens
            if unused_tokens:
                token_return = _resource_event(
                    action_id=action_id,
                    operation=ResourceOperation.RETURN,
                    source=reserved_account(agent_id),
                    target=SHARED_POOL,
                    resource_type="tokens",
                    amount=unused_tokens,
                )
                ledger.apply(token_return)
                public_token_return = event_writer.append(
                    event_id=token_return.event_id,
                    event_type="resource",
                    payload=token_return,
                    causal_parent_ids=(
                        f"resource-{action_id}-tokens-reserve",
                    ),
                )
                action_parent_ids.append(public_token_return.event_id)

            observation = ActionObservation(
                action_id=action_id,
                agent_id=agent_id,
                requirement_ids=(requirement_id,),
                input_refs=prior_input_refs,
                artifact_refs=(artifact_ref,),
                evidence_refs=(artifact_ref,),
                resource_cost=(
                    ResourceAmount("action_units", 1),
                    ResourceAmount("tokens", actual_tokens),
                ),
                started_at=f"cycle:{cycle}:start",
                finished_at=f"cycle:{cycle}:finish",
                status=(
                    ActionStatus.FAILED
                    if token_accounting_error is not None
                    else execution.status
                ),
            )
            actions.append(observation)
            action_event = event_writer.append(
                event_id=action_id,
                event_type="action",
                payload={
                    **observation.to_dict(),
                    "allocation_id": allocation.allocation_id,
                    "failure_reason": (
                        token_accounting_error
                        or execution.error
                        or (
                            "action failed"
                            if observation.status is not ActionStatus.SUCCEEDED
                            else None
                        )
                    ),
                },
                causal_parent_ids=tuple(dict.fromkeys(action_parent_ids)),
            )
            evidence_event = event_writer.append(
                event_id=f"evidence-{action_id}",
                event_type="evidence",
                payload={
                    "action_id": action_id,
                    "requirement_id": requirement_id,
                    "artifact_ref": artifact_ref,
                    "artifact_sha256": sha256(artifact_path.read_bytes()).hexdigest(),
                    "evidence": dict(execution.artifact),
                },
                causal_parent_ids=(action_event.event_id,),
            )
            last_state_event_id = evidence_event.event_id

            if observation.status is not ActionStatus.SUCCEEDED:
                status = RunTerminalStatus.FAILED
                reason = token_accounting_error or execution.error or "action failed"
                break

            disposition = _verify_requirement(
                self.bundle,
                requirement_id=requirement_id,
                artifact=execution.artifact,
            )
            feedback = FeedbackEvent(
                feedback_id=f"feedback-{cycle:03d}",
                task_id=self.task.task_id,
                action_id=action_id,
                requirement_deltas=(
                    RequirementDelta(
                        requirement_id=requirement_id,
                        disposition=disposition,
                        evidence_refs=(artifact_ref,),
                        invalidates_feedback_ids=(
                            tuple(
                                previous.feedback_id
                                for previous in feedback_by_requirement.get(
                                    requirement_id, []
                                )
                                if any(
                                    delta.disposition
                                    is not FeedbackDisposition.ACCEPTED
                                    for delta in previous.requirement_deltas
                                    if delta.requirement_id == requirement_id
                                )
                            )
                            if disposition is FeedbackDisposition.ACCEPTED
                            else ()
                        ),
                    ),
                ),
                source_kind=FeedbackSourceKind.VERIFIER,
                source_authority_by_claim_type=(
                    ClaimAuthority("r1_fixture", "deterministic_scorer"),
                ),
                confidence=1.0,
                evidence_refs=(artifact_ref,),
            )
            machine.apply_feedback(feedback)
            feedback_events.append(feedback)
            feedback_by_requirement.setdefault(requirement_id, []).append(feedback)
            feedback_event = event_writer.append(
                event_id=feedback.feedback_id,
                event_type="feedback",
                payload=feedback,
                causal_parent_ids=(
                    action_event.event_id,
                    evidence_event.event_id,
                ),
            )
            residual_event = event_writer.append(
                event_id=f"residual-{machine.snapshot().revision:03d}",
                event_type="residual",
                payload={"snapshot": machine.snapshot().to_dict()},
                causal_parent_ids=(feedback_event.event_id,),
            )
            last_state_event_id = residual_event.event_id
        else:
            status = RunTerminalStatus.MAX_CYCLES
            reason = "maximum cycle count reached"

        final_snapshot = machine.snapshot()
        if final_snapshot.complete:
            status = RunTerminalStatus.COMPLETED
            reason = "all required evidence accepted"
        ledger.assert_conserved()
        totals = {
            "action_units": ledger.totals("action_units"),
            "tokens": ledger.totals("tokens"),
        }
        final_state = {
            "status": status.value,
            "reason": reason,
            "residual": final_snapshot.to_dict(),
            "ledger": {
                "action_units": {
                    "expected": str(totals["action_units"].expected),
                    "accounted": str(totals["action_units"].accounted),
                    "spent": str(totals["action_units"].spent),
                    "shared_pool": str(totals["action_units"].shared_pool),
                },
                "tokens": {
                    "expected": str(totals["tokens"].expected),
                    "accounted": str(totals["tokens"].accounted),
                    "spent": str(totals["tokens"].spent),
                    "shared_pool": str(totals["tokens"].shared_pool),
                },
            },
        }
        final_state_sha256 = _canonical_state_sha256(final_state)
        if not last_state_event_id.startswith("residual-"):
            final_residual_event = event_writer.append(
                event_id=f"residual-final-{final_snapshot.revision:03d}",
                event_type="residual",
                payload={"snapshot": final_snapshot.to_dict()},
                causal_parent_ids=(last_state_event_id,),
            )
            last_state_event_id = final_residual_event.event_id
        settlement_event = event_writer.append(
            event_id="run-settlement",
            event_type="run_settlement",
            payload={"ledger": final_state["ledger"]},
            causal_parent_ids=(last_state_event_id,),
        )
        event_writer.append(
            event_id="run-terminal",
            event_type="run_terminal",
            payload={
                "status": status.value,
                "reason": reason,
                "source_final_state_sha256": final_state_sha256,
                "public_terminal_projection_sha256": final_state_sha256,
            },
            causal_parent_ids=(settlement_event.event_id,),
        )
        metrics = {
            "terminal_status": status.value,
            "cycles": len(actions),
            "complete": final_snapshot.complete,
            "residual_revision": final_snapshot.revision,
            "accepted_feedback": sum(
                1
                for event in feedback_events
                for delta in event.requirement_deltas
                if delta.disposition is FeedbackDisposition.ACCEPTED
            ),
            "rejected_feedback": sum(
                1
                for event in feedback_events
                for delta in event.requirement_deltas
                if delta.disposition is FeedbackDisposition.REJECTED
            ),
            "spent_action_units": int(totals["action_units"].spent),
            "spent_tokens": int(totals["tokens"].spent),
            "model_invocations": sum(
                1 for execution in executions if execution.provider_audit is not None
            ),
            "input_tokens": sum(execution.input_tokens for execution in executions),
            "output_tokens": sum(execution.output_tokens for execution in executions),
            "model_latency_ns": sum(execution.latency_ns for execution in executions),
        }
        store.write_metrics(metrics)
        store.write_summary(
            "# F0 episode\n\n"
            f"- status: `{status.value}`\n"
            f"- reason: {reason}\n"
            f"- cycles: {len(actions)}\n"
            f"- residual revision: {final_snapshot.revision}\n"
        )
        finalization = store.finalize(
            status=status,
            reason=reason,
            final_state=final_state,
        )
        if finalization.final_state_sha256 != final_state_sha256:
            raise RuntimeError("public and sealed F0 final-state hashes diverged")
        self._result = F0RunResult(
            status=status,
            reason=reason,
            cycles=len(actions),
            residual=final_snapshot,
            allocations=tuple(allocations),
            actions=tuple(actions),
            feedback=tuple(feedback_events),
            ledger_totals=totals,
            final_state_sha256=finalization.final_state_sha256,
            run_directory=store.run_directory,
        )
        return self._result


def _empty_artifact(requirement_id: str) -> Mapping[str, Any]:
    if requirement_id == FACT_REQUIREMENT:
        return {"key_facts": []}
    if requirement_id == CONFLICT_REQUIREMENT:
        return {"contradictions": []}
    return {"decision": "unsupported"}


def _verify_requirement(
    bundle: EvidenceTaskBundle,
    *,
    requirement_id: str,
    artifact: Mapping[str, Any],
) -> FeedbackDisposition:
    return f0_requirement_disposition(
        bundle,
        requirement_id=requirement_id,
        artifact=artifact,
    )


def _next_ready_requirement(
    task: TaskSpec,
    snapshot: ResidualSnapshot,
) -> str | None:
    status = snapshot.status_by_requirement()
    prerequisites: dict[str, set[str]] = {}
    for dependency in task.requirement_dependencies:
        if dependency.kind is DependencyKind.REQUIRES:
            prerequisites.setdefault(dependency.requirement_id, set()).add(
                dependency.depends_on_requirement_id
            )
    for requirement in task.requirements:
        requirement_id = requirement.requirement_id
        if status[requirement_id] is RequirementStatus.SATISFIED:
            continue
        if all(
            status[prerequisite] is RequirementStatus.SATISFIED
            for prerequisite in prerequisites.get(requirement_id, set())
        ):
            return requirement_id
    return None


def _resource_event(
    *,
    action_id: str,
    operation: ResourceOperation,
    source: str,
    target: str,
    resource_type: str,
    amount: int,
) -> ResourceEvent:
    return ResourceEvent(
        event_id=f"resource-{action_id}-{resource_type}-{operation.value}",
        operation=operation,
        resource_type=resource_type,
        amount=amount,
        source_account=source,
        target_account=target,
        idempotency_key=f"{action_id}:{operation.value}:{resource_type}",
    )


def _canonical_state_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _f0_schemas() -> RunArtifactSchemas:
    return RunArtifactSchemas(
        config={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "experiment_id",
                "protocol_version",
                "task_id",
                "task_version",
                "executor_mode",
                "action_budget",
                "token_budget",
                "max_cycles",
                "roles",
            ],
            "properties": {
                "experiment_id": {"const": "f0"},
                "protocol_version": {"const": 1},
                "task_id": {"type": "string", "minLength": 1},
                "task_version": {"type": "string", "minLength": 1},
                "executor_mode": {"type": "string", "minLength": 1},
                "action_budget": {"type": "integer", "minimum": 0},
                "token_budget": {"type": "integer", "minimum": 0},
                "max_cycles": {"type": "integer", "minimum": 1},
                "roles": {"type": "object", "minProperties": 3},
            },
        },
        event={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version",
                "event_id",
                "event_type",
                "sequence",
                "causal_parent_ids",
                "payload",
            ],
            "properties": {
                "schema_version": {"const": PUBLIC_EVENT_SCHEMA_VERSION},
                "event_id": {"type": "string", "minLength": 1},
                "event_type": {
                    "type": "string",
                    "enum": [
                        "run_started",
                        "allocation",
                        "resource",
                        "action",
                        "evidence",
                        "feedback",
                        "residual",
                        "model_invocation",
                        "run_settlement",
                        "run_terminal",
                    ],
                },
                "sequence": {"type": "integer", "minimum": 0},
                "causal_parent_ids": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "uniqueItems": True,
                },
                "payload": {"type": "object"},
            },
        },
        metrics={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "terminal_status",
                "cycles",
                "complete",
                "residual_revision",
                "accepted_feedback",
                "rejected_feedback",
                "spent_action_units",
                "spent_tokens",
                "model_invocations",
                "input_tokens",
                "output_tokens",
                "model_latency_ns",
            ],
            "properties": {
                "terminal_status": {
                    "type": "string",
                    "enum": [item.value for item in RunTerminalStatus],
                },
                "cycles": {"type": "integer", "minimum": 0},
                "complete": {"type": "boolean"},
                "residual_revision": {"type": "integer", "minimum": 0},
                "accepted_feedback": {"type": "integer", "minimum": 0},
                "rejected_feedback": {"type": "integer", "minimum": 0},
                "spent_action_units": {"type": "integer", "minimum": 0},
                "spent_tokens": {"type": "integer", "minimum": 0},
                "model_invocations": {"type": "integer", "minimum": 0},
                "input_tokens": {"type": "integer", "minimum": 0},
                "output_tokens": {"type": "integer", "minimum": 0},
                "model_latency_ns": {"type": "integer", "minimum": 0},
            },
        },
    )
