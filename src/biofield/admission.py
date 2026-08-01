from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .contracts import (
    AgentBid,
    AgentCommitment,
    AgentIntent,
    CommitmentIssuer,
    CommitmentStatus,
    JsonContract,
    LocalFieldObservation,
    ResourceAmount,
    ResourceEvent,
    ResourceOperation,
)
from .ledger import SHARED_POOL, agent_escrow_account


class AdmissionStatus(str, Enum):
    ADMITTED = "admitted"
    REJECTED = "rejected"


class AdmissionRejectionReason(str, Enum):
    INVALID_BID = "invalid_bid"
    BUDGET_EXCEEDED = "budget_exceeded"
    EXPIRED = "expired"
    INVALID_GRANT = "invalid_grant"
    RUN_FINALIZED = "run_finalized"
    RISK_HARD_STOP = "risk_hard_stop"
    ACTION_NOT_ALLOWED = "action_not_allowed"


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_text_tuple(values: tuple[str, ...], field_name: str) -> None:
    for value in values:
        _require_text(value, field_name)
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {field_name} are not allowed")


def _parse_timestamp(value: str, field_name: str) -> datetime:
    _require_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return parsed


@dataclass(frozen=True)
class ActionToolPolicy(JsonContract):
    action_family: str
    allowed_tools: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "allowed_tools",
            tuple(sorted(self.allowed_tools)),
        )
        _require_text(self.action_family, "action_family")
        _require_text_tuple(self.allowed_tools, "allowed_tools")


@dataclass(frozen=True, kw_only=True)
class AdmissionPolicy(JsonContract):
    schema_version: int
    policy_version: str
    action_tool_policies: tuple[ActionToolPolicy, ...]
    blocked_risk_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise ValueError("schema_version must be 1")
        _require_text(self.policy_version, "policy_version")
        rules = tuple(
            sorted(self.action_tool_policies, key=lambda item: item.action_family)
        )
        if not all(isinstance(item, ActionToolPolicy) for item in rules):
            raise ValueError(
                "action_tool_policies must contain ActionToolPolicy values"
            )
        if not rules:
            raise ValueError("action_tool_policies cannot be empty")
        if len(rules) != len({item.action_family for item in rules}):
            raise ValueError("duplicate action families are not allowed")
        object.__setattr__(self, "action_tool_policies", rules)
        risk_flags = tuple(sorted(self.blocked_risk_flags))
        _require_text_tuple(risk_flags, "blocked_risk_flags")
        object.__setattr__(self, "blocked_risk_flags", risk_flags)

    def allowed_tools_for(self, action_family: str) -> tuple[str, ...] | None:
        for item in self.action_tool_policies:
            if item.action_family == action_family:
                return item.allowed_tools
        return None


@dataclass(frozen=True, kw_only=True)
class AdmissionDecision(JsonContract):
    schema_version: int
    decision_id: str
    input_sha256: str
    policy_version: str
    status: AdmissionStatus
    rejection_reason: AdmissionRejectionReason | None
    detail: str
    commitment: AgentCommitment | None

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise ValueError("schema_version must be 1")
        _require_text(self.decision_id, "decision_id")
        if (
            not isinstance(self.input_sha256, str)
            or len(self.input_sha256) != 64
            or any(
                character not in "0123456789abcdef" for character in self.input_sha256
            )
        ):
            raise ValueError("input_sha256 must be a lowercase SHA-256 digest")
        _require_text(self.policy_version, "policy_version")
        if not isinstance(self.status, AdmissionStatus):
            raise ValueError("status must be an AdmissionStatus")
        _require_text(self.detail, "detail")
        if self.status is AdmissionStatus.ADMITTED:
            if self.rejection_reason is not None:
                raise ValueError("admitted decision cannot have a rejection reason")
            if not isinstance(self.commitment, AgentCommitment):
                raise ValueError("admitted decision requires a commitment")
            if self.policy_version != self.commitment.admission_policy_version:
                raise ValueError(
                    "admission decision policy version differs from commitment"
                )
            if self.decision_id != self.commitment.admission_decision_id:
                raise ValueError("admission decision ID differs from commitment")
        else:
            if not isinstance(self.rejection_reason, AdmissionRejectionReason):
                raise ValueError("rejected decision requires a rejection reason")
            if self.commitment is not None:
                raise ValueError("rejected decision cannot contain a commitment")

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> AdmissionDecision:
        payload = dict(value)
        payload["status"] = AdmissionStatus(payload["status"])
        rejection_reason = payload["rejection_reason"]
        payload["rejection_reason"] = (
            None
            if rejection_reason is None
            else AdmissionRejectionReason(rejection_reason)
        )
        commitment = payload["commitment"]
        payload["commitment"] = (
            None if commitment is None else AgentCommitment.from_dict(commitment)
        )
        return cls(**payload)


def _input_digest(
    *,
    bid: AgentBid,
    intent: AgentIntent,
    observation: LocalFieldObservation,
    resource_grants: tuple[ResourceEvent, ...],
    run_budget: tuple[ResourceAmount, ...],
    policy: AdmissionPolicy,
    at: str,
    run_finalized: bool,
) -> str:
    payload = {
        "at": at,
        "bid": bid.to_dict(),
        "intent": intent.to_dict(),
        "observation": observation.to_dict(),
        "policy": policy.to_dict(),
        "resource_grants": [item.to_dict() for item in resource_grants],
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


def _validate_grants(
    bid: AgentBid,
    resource_grants: tuple[ResourceEvent, ...],
) -> tuple[ResourceAmount, ...]:
    if not resource_grants:
        raise ValueError("resource_grants cannot be empty")
    event_ids = tuple(item.event_id for item in resource_grants)
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("duplicate resource grant event IDs are not allowed")
    resource_types = tuple(item.resource_type for item in resource_grants)
    if len(resource_types) != len(set(resource_types)):
        raise ValueError("resource grants must have unique resource types")

    expected_target = agent_escrow_account(bid.agent_id)
    for grant in resource_grants:
        if grant.operation is not ResourceOperation.GRANT:
            raise ValueError("resource event is not a grant")
        if grant.source_account != SHARED_POOL:
            raise ValueError("grant must originate from SharedPool")
        if grant.target_account != expected_target:
            raise ValueError("grant target does not match bid agent")

    granted = {item.resource_type: item.amount for item in resource_grants}
    requested = {
        item.resource_type: item.amount for item in bid.requested_budget_vector
    }
    if granted != requested:
        raise ValueError("resource grants must exactly match requested budget")
    return tuple(
        ResourceAmount(item.resource_type, granted[item.resource_type])
        for item in bid.requested_budget_vector
    )


def resolve_admission(
    *,
    bid: AgentBid,
    intent: AgentIntent,
    observation: LocalFieldObservation,
    resource_grants: tuple[ResourceEvent, ...],
    run_budget: tuple[ResourceAmount, ...],
    policy: AdmissionPolicy,
    at: str,
    run_finalized: bool,
) -> AdmissionDecision:
    """Resolve one public Bid without hidden optimization or mutable state."""

    grants = tuple(sorted(resource_grants, key=lambda item: item.event_id))
    budget = tuple(sorted(run_budget, key=lambda item: item.resource_type))
    digest = _input_digest(
        bid=bid,
        intent=intent,
        observation=observation,
        resource_grants=grants,
        run_budget=budget,
        policy=policy,
        at=at,
        run_finalized=run_finalized,
    )
    decision_id = f"admission-{digest}"

    def reject(
        reason: AdmissionRejectionReason,
        detail: str,
    ) -> AdmissionDecision:
        return AdmissionDecision(
            schema_version=1,
            decision_id=decision_id,
            input_sha256=digest,
            policy_version=policy.policy_version,
            status=AdmissionStatus.REJECTED,
            rejection_reason=reason,
            detail=detail,
            commitment=None,
        )

    try:
        checked_at = _parse_timestamp(at, "at")
    except ValueError as error:
        return reject(AdmissionRejectionReason.INVALID_BID, str(error))

    if run_finalized:
        return reject(
            AdmissionRejectionReason.RUN_FINALIZED,
            "run is already finalized",
        )

    blocked_risks = sorted(set(observation.risk_flags) & set(policy.blocked_risk_flags))
    if blocked_risks:
        return reject(
            AdmissionRejectionReason.RISK_HARD_STOP,
            f"blocked risk flags: {','.join(blocked_risks)}",
        )

    allowed_tools = policy.allowed_tools_for(intent.proposed_action_family)
    if allowed_tools is None:
        return reject(
            AdmissionRejectionReason.ACTION_NOT_ALLOWED,
            "action family has no admission policy",
        )

    try:
        bid.validate_against(
            intent,
            observation,
            run_budget=budget,
            at=at,
        )
    except ValueError as error:
        detail = str(error)
        if "run budget" in detail:
            reason = AdmissionRejectionReason.BUDGET_EXCEEDED
        elif "expired" in detail:
            reason = AdmissionRejectionReason.EXPIRED
        else:
            reason = AdmissionRejectionReason.INVALID_BID
        return reject(reason, detail)

    _window_start = _parse_timestamp(
        bid.expected_completion_window[0],
        "expected_completion_window start",
    )
    window_end = _parse_timestamp(
        bid.expected_completion_window[1],
        "expected_completion_window end",
    )
    if checked_at >= window_end:
        return reject(AdmissionRejectionReason.EXPIRED, "bid has expired")

    try:
        admitted_resources = _validate_grants(bid, grants)
    except ValueError as error:
        return reject(AdmissionRejectionReason.INVALID_GRANT, str(error))

    grant_ids = tuple(item.event_id for item in grants)
    commitment = AgentCommitment(
        schema_version=1,
        commitment_id=f"commitment-{digest}",
        admission_decision_id=decision_id,
        admission_policy_version=policy.policy_version,
        issuer=CommitmentIssuer.HARNESS_ADMISSION,
        agent_id=bid.agent_id,
        task_id=observation.task_id,
        requirement_schema_version=observation.requirement_schema_version,
        observation_id=observation.observation_id,
        intent_id=intent.intent_id,
        bid_id=bid.bid_id,
        target_requirement_id=bid.target_requirement_id,
        admitted_resource_grant_ids=grant_ids,
        admitted_resources=admitted_resources,
        allowed_tools=allowed_tools,
        accepted_scope=(bid.target_requirement_id,),
        causal_parent_ids=(
            observation.observation_id,
            intent.intent_id,
            bid.bid_id,
            *grant_ids,
        ),
        status=CommitmentStatus.ACTIVE,
        created_at=at,
        deadline=bid.expected_completion_window[1],
    )
    commitment.validate_against(bid, intent, observation, grants)
    return AdmissionDecision(
        schema_version=1,
        decision_id=decision_id,
        input_sha256=digest,
        policy_version=policy.policy_version,
        status=AdmissionStatus.ADMITTED,
        rejection_reason=None,
        detail="bid admitted under deterministic public policy",
        commitment=commitment,
    )
