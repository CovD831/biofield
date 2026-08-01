from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum

from .admission import AdmissionPolicy
from .contracts import (
    AgentBid,
    AgentIntent,
    JsonContract,
    LocalFieldObservation,
    ResourceAmount,
)


class MultiAdmissionStatus(str, Enum):
    ADMITTED = "admitted"
    REJECTED = "rejected"


class MultiAdmissionReason(str, Enum):
    INVALID_BID = "invalid_bid"
    ACTION_NOT_ALLOWED = "action_not_allowed"
    BUDGET_LIMIT = "budget_limit"
    CONCURRENCY_LIMIT = "concurrency_limit"
    DUPLICATE_LIMIT = "duplicate_limit"
    DEPENDENCY_NOT_READY = "dependency_not_ready"
    RISK_HARD_STOP = "risk_hard_stop"
    RUN_FINALIZED = "run_finalized"


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_nonnegative_integer(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


@dataclass(frozen=True, kw_only=True)
class BidCandidate(JsonContract):
    bid: AgentBid
    intent: AgentIntent
    observation: LocalFieldObservation
    exploration_eligible: bool

    def __post_init__(self) -> None:
        if not isinstance(self.bid, AgentBid):
            raise ValueError("bid must be an AgentBid")
        if not isinstance(self.intent, AgentIntent):
            raise ValueError("intent must be an AgentIntent")
        if not isinstance(self.observation, LocalFieldObservation):
            raise ValueError("observation must be a LocalFieldObservation")
        if not isinstance(self.exploration_eligible, bool):
            raise ValueError("exploration_eligible must be a boolean")


@dataclass(frozen=True)
class RequirementLoad(JsonContract):
    requirement_id: str
    active_commitments: int

    def __post_init__(self) -> None:
        _require_text(self.requirement_id, "requirement_id")
        _require_nonnegative_integer(
            self.active_commitments,
            "active_commitments",
        )


@dataclass(frozen=True, kw_only=True)
class MultiAdmissionPolicy(JsonContract):
    schema_version: int
    policy_version: str
    max_concurrent_commitments: int
    max_commitments_per_requirement: int
    exploration_min_slots: int
    tie_break_rule: str

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise ValueError("schema_version must be 1")
        _require_text(self.policy_version, "policy_version")
        for value, field_name in (
            (
                self.max_concurrent_commitments,
                "max_concurrent_commitments",
            ),
            (
                self.max_commitments_per_requirement,
                "max_commitments_per_requirement",
            ),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        _require_nonnegative_integer(
            self.exploration_min_slots,
            "exploration_min_slots",
        )
        if self.exploration_min_slots > self.max_concurrent_commitments:
            raise ValueError(
                "exploration_min_slots cannot exceed max concurrency"
            )
        if self.tie_break_rule != "bid_id_lexicographic":
            raise ValueError(
                "tie_break_rule must be bid_id_lexicographic"
            )


@dataclass(frozen=True)
class MultiBidDecision(JsonContract):
    bid_id: str
    status: MultiAdmissionStatus
    reason: MultiAdmissionReason | None
    exploration_eligible: bool

    def __post_init__(self) -> None:
        _require_text(self.bid_id, "bid_id")
        if not isinstance(self.status, MultiAdmissionStatus):
            raise ValueError("status must be a MultiAdmissionStatus")
        if self.status is MultiAdmissionStatus.ADMITTED:
            if self.reason is not None:
                raise ValueError("admitted bid cannot have rejection reason")
        elif not isinstance(self.reason, MultiAdmissionReason):
            raise ValueError("rejected bid requires rejection reason")
        if not isinstance(self.exploration_eligible, bool):
            raise ValueError("exploration_eligible must be a boolean")

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "MultiBidDecision":
        payload = dict(value)
        payload["status"] = MultiAdmissionStatus(payload["status"])
        if payload["reason"] is not None:
            payload["reason"] = MultiAdmissionReason(payload["reason"])
        return cls(**payload)


@dataclass(frozen=True, kw_only=True)
class MultiAdmissionResult(JsonContract):
    schema_version: int
    result_id: str
    input_sha256: str
    policy_version: str
    decisions: tuple[MultiBidDecision, ...]
    admitted_bid_ids: tuple[str, ...]
    exploration_quota_met: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "decisions",
            tuple(sorted(self.decisions, key=lambda item: item.bid_id)),
        )
        object.__setattr__(
            self,
            "admitted_bid_ids",
            tuple(sorted(self.admitted_bid_ids)),
        )
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise ValueError("schema_version must be 1")
        _require_text(self.result_id, "result_id")
        if (
            not isinstance(self.input_sha256, str)
            or len(self.input_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.input_sha256
            )
        ):
            raise ValueError("input_sha256 must be a lowercase SHA-256 digest")
        _require_text(self.policy_version, "policy_version")
        if not self.decisions:
            raise ValueError("decisions cannot be empty")
        bid_ids = tuple(item.bid_id for item in self.decisions)
        if len(bid_ids) != len(set(bid_ids)):
            raise ValueError("duplicate bid decisions are not allowed")
        expected_admitted = tuple(
            item.bid_id
            for item in self.decisions
            if item.status is MultiAdmissionStatus.ADMITTED
        )
        if self.admitted_bid_ids != expected_admitted:
            raise ValueError(
                "admitted_bid_ids must match admitted decisions"
            )
        if not isinstance(self.exploration_quota_met, bool):
            raise ValueError("exploration_quota_met must be a boolean")

    def decision_for(self, bid_id: str) -> MultiBidDecision:
        for item in self.decisions:
            if item.bid_id == bid_id:
                return item
        raise KeyError(bid_id)

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "MultiAdmissionResult":
        payload = dict(value)
        payload["decisions"] = tuple(
            MultiBidDecision.from_dict(item)
            for item in payload["decisions"]
        )
        payload["admitted_bid_ids"] = tuple(payload["admitted_bid_ids"])
        return cls(**payload)


def _resource_map(values: tuple[ResourceAmount, ...]) -> dict[str, float]:
    result: dict[str, float] = {}
    for item in values:
        if item.resource_type in result:
            raise ValueError("duplicate resource types are not allowed")
        result[item.resource_type] = item.amount
    return result


def _input_digest(
    *,
    candidates: tuple[BidCandidate, ...],
    run_budget: tuple[ResourceAmount, ...],
    reserved_resources: tuple[ResourceAmount, ...],
    existing_requirement_loads: tuple[RequirementLoad, ...],
    ready_requirement_ids: tuple[str, ...],
    current_concurrency: int,
    admission_policy: AdmissionPolicy,
    policy: MultiAdmissionPolicy,
    at: str,
    run_finalized: bool,
) -> str:
    payload = {
        "admission_policy": admission_policy.to_dict(),
        "at": at,
        "candidates": [item.to_dict() for item in candidates],
        "current_concurrency": current_concurrency,
        "existing_requirement_loads": [
            item.to_dict() for item in existing_requirement_loads
        ],
        "ready_requirement_ids": list(ready_requirement_ids),
        "policy": policy.to_dict(),
        "reserved_resources": [
            item.to_dict() for item in reserved_resources
        ],
        "run_budget": [item.to_dict() for item in run_budget],
        "run_finalized": run_finalized,
    }
    encoded = json.dumps(
        payload,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def resolve_multi_admission(
    *,
    candidates: tuple[BidCandidate, ...],
    run_budget: tuple[ResourceAmount, ...],
    reserved_resources: tuple[ResourceAmount, ...],
    existing_requirement_loads: tuple[RequirementLoad, ...],
    ready_requirement_ids: tuple[str, ...],
    current_concurrency: int,
    admission_policy: AdmissionPolicy,
    policy: MultiAdmissionPolicy,
    at: str,
    run_finalized: bool,
) -> MultiAdmissionResult:
    """Select public Bids by frozen constraints, never by hidden utility."""

    ordered = tuple(sorted(candidates, key=lambda item: item.bid.bid_id))
    if not ordered:
        raise ValueError("candidates cannot be empty")
    bid_ids = tuple(item.bid.bid_id for item in ordered)
    if len(bid_ids) != len(set(bid_ids)):
        raise ValueError("duplicate bid IDs are not allowed")
    budget = tuple(sorted(run_budget, key=lambda item: item.resource_type))
    reserved = tuple(
        sorted(reserved_resources, key=lambda item: item.resource_type)
    )
    loads = tuple(
        sorted(
            existing_requirement_loads,
            key=lambda item: item.requirement_id,
        )
    )
    load_ids = tuple(item.requirement_id for item in loads)
    if len(load_ids) != len(set(load_ids)):
        raise ValueError("duplicate requirement loads are not allowed")
    ready_requirements = tuple(sorted(ready_requirement_ids))
    if len(ready_requirements) != len(set(ready_requirements)):
        raise ValueError("duplicate ready requirement IDs are not allowed")
    for requirement_id in ready_requirements:
        _require_text(requirement_id, "ready_requirement_id")
    _require_nonnegative_integer(current_concurrency, "current_concurrency")

    digest = _input_digest(
        candidates=ordered,
        run_budget=budget,
        reserved_resources=reserved,
        existing_requirement_loads=loads,
        ready_requirement_ids=ready_requirements,
        current_concurrency=current_concurrency,
        admission_policy=admission_policy,
        policy=policy,
        at=at,
        run_finalized=run_finalized,
    )

    decisions: dict[str, MultiBidDecision] = {}

    def reject_all(reason: MultiAdmissionReason) -> MultiAdmissionResult:
        rejected = tuple(
            MultiBidDecision(
                bid_id=item.bid.bid_id,
                status=MultiAdmissionStatus.REJECTED,
                reason=reason,
                exploration_eligible=item.exploration_eligible,
            )
            for item in ordered
        )
        return MultiAdmissionResult(
            schema_version=1,
            result_id=f"multi-admission-{digest}",
            input_sha256=digest,
            policy_version=policy.policy_version,
            decisions=rejected,
            admitted_bid_ids=(),
            exploration_quota_met=policy.exploration_min_slots == 0,
        )

    if run_finalized:
        return reject_all(MultiAdmissionReason.RUN_FINALIZED)
    if any(
        set(item.observation.risk_flags)
        & set(admission_policy.blocked_risk_flags)
        for item in ordered
    ):
        return reject_all(MultiAdmissionReason.RISK_HARD_STOP)

    valid: list[BidCandidate] = []
    for candidate in ordered:
        if (
            admission_policy.allowed_tools_for(
                candidate.intent.proposed_action_family
            )
            is None
        ):
            decisions[candidate.bid.bid_id] = MultiBidDecision(
                candidate.bid.bid_id,
                MultiAdmissionStatus.REJECTED,
                MultiAdmissionReason.ACTION_NOT_ALLOWED,
                candidate.exploration_eligible,
            )
            continue
        try:
            candidate.bid.validate_against(
                candidate.intent,
                candidate.observation,
                run_budget=budget,
                at=at,
            )
        except ValueError:
            decisions[candidate.bid.bid_id] = MultiBidDecision(
                candidate.bid.bid_id,
                MultiAdmissionStatus.REJECTED,
                MultiAdmissionReason.INVALID_BID,
                candidate.exploration_eligible,
            )
            continue
        if candidate.bid.target_requirement_id not in ready_requirements:
            decisions[candidate.bid.bid_id] = MultiBidDecision(
                candidate.bid.bid_id,
                MultiAdmissionStatus.REJECTED,
                MultiAdmissionReason.DEPENDENCY_NOT_READY,
                candidate.exploration_eligible,
            )
            continue
        valid.append(candidate)

    total_budget = _resource_map(budget)
    used_budget = _resource_map(reserved)
    for resource_type, amount in used_budget.items():
        if (
            resource_type not in total_budget
            or amount > total_budget[resource_type]
        ):
            return reject_all(MultiAdmissionReason.BUDGET_LIMIT)
    requirement_counts = {
        item.requirement_id: item.active_commitments for item in loads
    }
    selected: list[BidCandidate] = []

    def try_select(candidate: BidCandidate) -> None:
        bid_id = candidate.bid.bid_id
        if bid_id in decisions:
            return
        if current_concurrency + len(selected) >= (
            policy.max_concurrent_commitments
        ):
            reason = MultiAdmissionReason.CONCURRENCY_LIMIT
        elif requirement_counts.get(candidate.bid.target_requirement_id, 0) >= (
            policy.max_commitments_per_requirement
        ):
            reason = MultiAdmissionReason.DUPLICATE_LIMIT
        else:
            requested = _resource_map(candidate.bid.requested_budget_vector)
            fits = all(
                resource_type in total_budget
                and used_budget.get(resource_type, 0) + amount
                <= total_budget[resource_type]
                for resource_type, amount in requested.items()
            )
            if not fits:
                reason = MultiAdmissionReason.BUDGET_LIMIT
            else:
                selected.append(candidate)
                for resource_type, amount in requested.items():
                    used_budget[resource_type] = (
                        used_budget.get(resource_type, 0) + amount
                    )
                requirement_counts[candidate.bid.target_requirement_id] = (
                    requirement_counts.get(
                        candidate.bid.target_requirement_id,
                        0,
                    )
                    + 1
                )
                decisions[bid_id] = MultiBidDecision(
                    bid_id,
                    MultiAdmissionStatus.ADMITTED,
                    None,
                    candidate.exploration_eligible,
                )
                return
        decisions[bid_id] = MultiBidDecision(
            bid_id,
            MultiAdmissionStatus.REJECTED,
            reason,
            candidate.exploration_eligible,
        )

    exploration_candidates = [
        item for item in valid if item.exploration_eligible
    ]
    for candidate in exploration_candidates:
        if sum(item.exploration_eligible for item in selected) >= (
            policy.exploration_min_slots
        ):
            break
        try_select(candidate)
    for candidate in valid:
        try_select(candidate)

    ordered_decisions = tuple(
        decisions[item.bid.bid_id] for item in ordered
    )
    admitted_ids = tuple(
        item.bid_id
        for item in ordered_decisions
        if item.status is MultiAdmissionStatus.ADMITTED
    )
    selected_exploration = sum(
        item.exploration_eligible for item in selected
    )
    return MultiAdmissionResult(
        schema_version=1,
        result_id=f"multi-admission-{digest}",
        input_sha256=digest,
        policy_version=policy.policy_version,
        decisions=ordered_decisions,
        admitted_bid_ids=admitted_ids,
        exploration_quota_met=(
            selected_exploration >= policy.exploration_min_slots
        ),
    )
