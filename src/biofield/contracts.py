from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, TypeAlias


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class DependencyKind(str, Enum):
    REQUIRES = "requires"
    SYNERGIZES_WITH = "synergizes_with"
    CONFLICTS_WITH = "conflicts_with"


class ActionStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    ABANDONED = "abandoned"
    CANCELLED = "cancelled"


class FeedbackDisposition(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DISPUTED = "disputed"


class FeedbackSourceKind(str, Enum):
    ENVIRONMENT = "environment"
    VERIFIER = "verifier"
    HUMAN = "human"
    SYNTHETIC = "synthetic"


class RequirementStatus(str, Enum):
    UNKNOWN = "unknown"
    UNMET = "unmet"
    SATISFIED = "satisfied"
    DISPUTED = "disputed"


class ResourceOperation(str, Enum):
    INJECT = "inject"
    RESERVE = "reserve"
    GRANT = "grant"
    SPEND = "spend"
    RETURN = "return"
    EXPIRE = "expire"


class EvidenceLevel(str, Enum):
    EXPLORATORY = "exploratory"
    CONFIRMATORY = "confirmatory"


class ExperimentDecision(str, Enum):
    SUPPORT = "support"
    REJECT = "reject"
    INCONCLUSIVE = "inconclusive"


class RunTerminalStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    MAX_CYCLES = "max_cycles"


class RefusalReason(str, Enum):
    INSUFFICIENT_CAPABILITY = "insufficient_capability"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    DEPENDENCY_UNMET = "dependency_unmet"
    BUDGET_INSUFFICIENT = "budget_insufficient"
    RISK = "risk"
    CONGESTED = "congested"


class CommitmentIssuer(str, Enum):
    HARNESS_ADMISSION = "harness_admission"
    AGENT_PROPOSAL = "agent_proposal"


class CommitmentStatus(str, Enum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    EXPIRED = "expired"


class LocalStateUpdateIssuer(str, Enum):
    HARNESS_COMPILER = "harness_compiler"
    AGENT_PROPOSAL = "agent_proposal"


class ExperienceValidationStatus(str, Enum):
    PROMOTED = "promoted"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


class GovernanceIssuer(str, Enum):
    AGENT_PROPOSAL = "agent_proposal"
    HARNESS_ADMISSION = "harness_admission"


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_text_tuple(values: tuple[str, ...], field_name: str) -> None:
    for value in values:
        _require_text(value, field_name)
    _require_unique(values, field_name)


def _require_unique(values: tuple[Any, ...], field_name: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {field_name} are not allowed")


def _require_number(
    value: float,
    field_name: str,
    *,
    positive: bool = False,
    nonnegative: bool = False,
) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite number")
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be a finite number")
    if positive and value <= 0:
        raise ValueError(f"{field_name} must be positive")
    if nonnegative and value < 0:
        raise ValueError(f"{field_name} cannot be negative")


def _require_schema_version(value: int) -> None:
    if value != 1 or isinstance(value, bool):
        raise ValueError("schema_version must be 1")


def _require_integer(
    value: int,
    field_name: str,
    *,
    positive: bool = False,
    nonnegative: bool = False,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if positive and value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    if nonnegative and value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def _parse_timestamp(value: str, field_name: str) -> datetime:
    _require_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return parsed


def _normalize_resource_amounts(
    values: tuple["ResourceAmount", ...],
    field_name: str,
    *,
    require_nonempty: bool = False,
) -> tuple["ResourceAmount", ...]:
    normalized = tuple(values)
    if require_nonempty and not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    if not all(isinstance(item, ResourceAmount) for item in normalized):
        raise ValueError(f"{field_name} must contain ResourceAmount values")
    _require_unique(
        tuple(item.resource_type for item in normalized),
        f"{field_name} resource_types",
    )
    return normalized


def _resource_map(values: tuple["ResourceAmount", ...]) -> dict[str, float]:
    return {item.resource_type: item.amount for item in values}


def _require_sha256(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _normalize_json_mapping(
    value: Mapping[str, Any],
    field_name: str,
) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    normalized = dict(value)
    if not all(isinstance(key, str) and key.strip() for key in normalized):
        raise ValueError(f"{field_name} keys must be non-empty strings")
    try:
        json.dumps(_jsonable(normalized), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be JSON serializable") from error
    return _freeze_json(normalized)


def _jsonable(value: Any) -> JsonValue:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_json(item) for item in value)
    return value


class JsonContract:
    def to_dict(self) -> dict[str, JsonValue]:
        value = _jsonable(self)
        if not isinstance(value, dict):  # pragma: no cover - subclasses are dataclasses
            raise TypeError("contract root must serialize to an object")
        return value

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )


@dataclass(frozen=True)
class RequirementSpec(JsonContract):
    requirement_id: str
    description: str
    required: bool = True

    def __post_init__(self) -> None:
        _require_text(self.requirement_id, "requirement_id")
        _require_text(self.description, "description")
        if not isinstance(self.required, bool):
            raise ValueError("required must be a boolean")


@dataclass(frozen=True)
class RequirementDependency(JsonContract):
    requirement_id: str
    depends_on_requirement_id: str
    kind: DependencyKind

    def __post_init__(self) -> None:
        _require_text(self.requirement_id, "requirement_id")
        _require_text(self.depends_on_requirement_id, "depends_on_requirement_id")
        if not isinstance(self.kind, DependencyKind):
            raise ValueError("kind must be a DependencyKind")
        if self.requirement_id == self.depends_on_requirement_id:
            raise ValueError("a requirement cannot depend on itself")


@dataclass(frozen=True)
class ResourceLimit(JsonContract):
    resource_type: str
    amount: float

    def __post_init__(self) -> None:
        _require_text(self.resource_type, "resource_type")
        _require_number(self.amount, "amount", nonnegative=True)


@dataclass(frozen=True)
class ResourceAmount(JsonContract):
    resource_type: str
    amount: float

    def __post_init__(self) -> None:
        _require_text(self.resource_type, "resource_type")
        _require_number(self.amount, "amount", nonnegative=True)


@dataclass(frozen=True, kw_only=True)
class LocalFieldObservation(JsonContract):
    schema_version: int
    observation_id: str
    agent_id: str
    task_id: str
    requirement_schema_version: int
    public_state_revision: int
    visible_requirement_signals: tuple[str, ...]
    congestion_signals: tuple[str, ...]
    resource_terms: tuple[ResourceAmount, ...]
    risk_flags: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    field_policy_version: str
    created_at: str
    expires_at: str

    def __post_init__(self) -> None:
        for field_name in (
            "visible_requirement_signals",
            "congestion_signals",
            "risk_flags",
            "source_event_ids",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        object.__setattr__(
            self,
            "resource_terms",
            _normalize_resource_amounts(self.resource_terms, "resource_terms"),
        )
        _require_schema_version(self.schema_version)
        _require_text(self.observation_id, "observation_id")
        _require_text(self.agent_id, "agent_id")
        _require_text(self.task_id, "task_id")
        _require_integer(
            self.requirement_schema_version,
            "requirement_schema_version",
            positive=True,
        )
        _require_integer(
            self.public_state_revision,
            "public_state_revision",
            nonnegative=True,
        )
        _require_text_tuple(
            self.visible_requirement_signals,
            "visible_requirement_signals",
        )
        _require_text_tuple(self.congestion_signals, "congestion_signals")
        _require_text_tuple(self.risk_flags, "risk_flags")
        _require_text_tuple(self.source_event_ids, "source_event_ids")
        if not self.source_event_ids:
            raise ValueError("source_event_ids cannot be empty")
        _require_text(self.field_policy_version, "field_policy_version")
        created_at = _parse_timestamp(self.created_at, "created_at")
        expires_at = _parse_timestamp(self.expires_at, "expires_at")
        if expires_at <= created_at:
            raise ValueError("expires_at must be after created_at")

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "LocalFieldObservation":
        payload = dict(value)
        payload["visible_requirement_signals"] = tuple(
            payload["visible_requirement_signals"]
        )
        payload["congestion_signals"] = tuple(payload["congestion_signals"])
        payload["resource_terms"] = tuple(
            ResourceAmount(**item) for item in payload["resource_terms"]
        )
        payload["risk_flags"] = tuple(payload["risk_flags"])
        payload["source_event_ids"] = tuple(payload["source_event_ids"])
        return cls(**payload)


@dataclass(frozen=True, kw_only=True)
class AgentIntent(JsonContract):
    schema_version: int
    intent_id: str
    agent_id: str
    observation_id: str
    local_state_version: int
    target_requirement_id: str
    proposed_action_family: str
    expected_evidence_type: str
    expected_marginal_progress: float
    confidence: float
    uncertainty: float
    requested_resource_bounds: tuple[ResourceAmount, ...]
    dependency_refs: tuple[str, ...]
    expires_at: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "requested_resource_bounds",
            _normalize_resource_amounts(
                self.requested_resource_bounds,
                "requested_resource_bounds",
                require_nonempty=True,
            ),
        )
        object.__setattr__(self, "dependency_refs", tuple(self.dependency_refs))
        _require_schema_version(self.schema_version)
        _require_text(self.intent_id, "intent_id")
        _require_text(self.agent_id, "agent_id")
        _require_text(self.observation_id, "observation_id")
        _require_integer(
            self.local_state_version,
            "local_state_version",
            nonnegative=True,
        )
        _require_text(self.target_requirement_id, "target_requirement_id")
        _require_text(self.proposed_action_family, "proposed_action_family")
        _require_text(self.expected_evidence_type, "expected_evidence_type")
        for field_name in (
            "expected_marginal_progress",
            "confidence",
            "uncertainty",
        ):
            value = getattr(self, field_name)
            _require_number(value, field_name)
            if not 0 <= value <= 1:
                raise ValueError(f"{field_name} must be between 0 and 1")
        _require_text_tuple(self.dependency_refs, "dependency_refs")
        _parse_timestamp(self.expires_at, "expires_at")

    def validate_against(
        self,
        observation: LocalFieldObservation,
        *,
        at: str | None = None,
    ) -> None:
        if self.observation_id != observation.observation_id:
            raise ValueError("intent observation_id does not match its parent")
        if self.agent_id != observation.agent_id:
            raise ValueError("intent agent_id does not match observation audience")
        if (
            self.target_requirement_id
            not in observation.visible_requirement_signals
        ):
            raise ValueError(
                "intent target_requirement_id is not visible in its observation"
            )
        observation_expiry = _parse_timestamp(
            observation.expires_at,
            "observation expires_at",
        )
        if _parse_timestamp(self.expires_at, "intent expires_at") > observation_expiry:
            raise ValueError("intent cannot outlive its observation")
        if at is not None:
            checked_at = _parse_timestamp(at, "at")
            if checked_at >= observation_expiry:
                raise ValueError("observation has expired")
            if checked_at >= _parse_timestamp(self.expires_at, "intent expires_at"):
                raise ValueError("intent has expired")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AgentIntent":
        payload = dict(value)
        payload["requested_resource_bounds"] = tuple(
            ResourceAmount(**item) for item in payload["requested_resource_bounds"]
        )
        payload["dependency_refs"] = tuple(payload["dependency_refs"])
        return cls(**payload)


@dataclass(frozen=True, kw_only=True)
class AgentBid(JsonContract):
    schema_version: int
    bid_id: str
    agent_id: str
    intent_id: str
    observation_id: str
    target_requirement_id: str
    capacity_commitment: float
    estimated_cost_vector: tuple[ResourceAmount, ...]
    requested_budget_vector: tuple[ResourceAmount, ...]
    expected_completion_window: tuple[str, str]
    duplication_tolerance: float
    communication_needs: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "estimated_cost_vector",
            _normalize_resource_amounts(
                self.estimated_cost_vector,
                "estimated_cost_vector",
                require_nonempty=True,
            ),
        )
        object.__setattr__(
            self,
            "requested_budget_vector",
            _normalize_resource_amounts(
                self.requested_budget_vector,
                "requested_budget_vector",
                require_nonempty=True,
            ),
        )
        object.__setattr__(
            self,
            "expected_completion_window",
            tuple(self.expected_completion_window),
        )
        object.__setattr__(
            self,
            "communication_needs",
            tuple(self.communication_needs),
        )
        _require_schema_version(self.schema_version)
        _require_text(self.bid_id, "bid_id")
        _require_text(self.agent_id, "agent_id")
        _require_text(self.intent_id, "intent_id")
        _require_text(self.observation_id, "observation_id")
        _require_text(self.target_requirement_id, "target_requirement_id")
        _require_number(
            self.capacity_commitment,
            "capacity_commitment",
            positive=True,
        )
        if self.capacity_commitment > 1:
            raise ValueError("capacity_commitment must not exceed 1")
        if len(self.expected_completion_window) != 2:
            raise ValueError("expected_completion_window must contain start and end")
        window_start = _parse_timestamp(
            self.expected_completion_window[0],
            "expected_completion_window start",
        )
        window_end = _parse_timestamp(
            self.expected_completion_window[1],
            "expected_completion_window end",
        )
        if window_end <= window_start:
            raise ValueError(
                "expected_completion_window end must be after start"
            )
        _require_number(self.duplication_tolerance, "duplication_tolerance")
        if not 0 <= self.duplication_tolerance <= 1:
            raise ValueError("duplication_tolerance must be between 0 and 1")
        _require_text_tuple(self.communication_needs, "communication_needs")

        requested = _resource_map(self.requested_budget_vector)
        for item in self.estimated_cost_vector:
            if (
                item.resource_type not in requested
                or item.amount > requested[item.resource_type]
            ):
                raise ValueError(
                    "estimated_cost_vector must fit requested_budget_vector"
                )

    def validate_against(
        self,
        intent: AgentIntent,
        observation: LocalFieldObservation,
        *,
        run_budget: tuple[ResourceAmount, ...] | None = None,
        at: str | None = None,
    ) -> None:
        intent.validate_against(observation, at=at)
        if self.intent_id != intent.intent_id:
            raise ValueError("bid intent_id does not match its parent")
        if self.observation_id != intent.observation_id:
            raise ValueError("bid observation_id does not match its parent")
        if self.agent_id != intent.agent_id:
            raise ValueError("bid agent_id does not match intent agent_id")
        if self.target_requirement_id != intent.target_requirement_id:
            raise ValueError(
                "bid target_requirement_id does not match its intent"
            )

        intent_bounds = _resource_map(intent.requested_resource_bounds)
        for item in self.requested_budget_vector:
            if (
                item.resource_type not in intent_bounds
                or item.amount > intent_bounds[item.resource_type]
            ):
                raise ValueError(
                    "requested budget exceeds intent resource bound"
                )

        if run_budget is not None:
            normalized_budget = _normalize_resource_amounts(
                run_budget,
                "run_budget",
            )
            budget_by_type = _resource_map(normalized_budget)
            for item in self.requested_budget_vector:
                if (
                    item.resource_type not in budget_by_type
                    or item.amount > budget_by_type[item.resource_type]
                ):
                    raise ValueError("requested budget exceeds run budget")

        window_start, window_end = (
            _parse_timestamp(value, "expected_completion_window")
            for value in self.expected_completion_window
        )
        if at is not None and _parse_timestamp(at, "at") >= window_end:
            raise ValueError("bid has expired")
        if window_start < _parse_timestamp(observation.created_at, "created_at"):
            raise ValueError("bid completion window predates its observation")
        if window_end > _parse_timestamp(intent.expires_at, "intent expires_at"):
            raise ValueError("bid completion window exceeds intent expiry")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AgentBid":
        payload = dict(value)
        for field_name in ("estimated_cost_vector", "requested_budget_vector"):
            payload[field_name] = tuple(
                ResourceAmount(**item) for item in payload[field_name]
            )
        payload["expected_completion_window"] = tuple(
            payload["expected_completion_window"]
        )
        payload["communication_needs"] = tuple(payload["communication_needs"])
        return cls(**payload)


@dataclass(frozen=True, kw_only=True)
class AgentCommitment(JsonContract):
    schema_version: int
    commitment_id: str
    admission_decision_id: str
    admission_policy_version: str
    issuer: CommitmentIssuer
    agent_id: str
    task_id: str
    requirement_schema_version: int
    observation_id: str
    intent_id: str
    bid_id: str
    target_requirement_id: str
    admitted_resource_grant_ids: tuple[str, ...]
    admitted_resources: tuple[ResourceAmount, ...]
    allowed_tools: tuple[str, ...]
    accepted_scope: tuple[str, ...]
    causal_parent_ids: tuple[str, ...]
    status: CommitmentStatus
    created_at: str
    deadline: str

    def __post_init__(self) -> None:
        for field_name in (
            "admitted_resource_grant_ids",
            "allowed_tools",
            "accepted_scope",
            "causal_parent_ids",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        object.__setattr__(
            self,
            "admitted_resources",
            _normalize_resource_amounts(
                self.admitted_resources,
                "admitted_resources",
                require_nonempty=True,
            ),
        )
        _require_schema_version(self.schema_version)
        for field_name in (
            "commitment_id",
            "admission_decision_id",
            "admission_policy_version",
            "agent_id",
            "task_id",
            "observation_id",
            "intent_id",
            "bid_id",
            "target_requirement_id",
        ):
            _require_text(getattr(self, field_name), field_name)
        _require_integer(
            self.requirement_schema_version,
            "requirement_schema_version",
            positive=True,
        )
        if self.issuer is not CommitmentIssuer.HARNESS_ADMISSION:
            raise ValueError("commitment issuer must be Harness Admission")
        _require_text_tuple(
            self.admitted_resource_grant_ids,
            "admitted_resource_grant_ids",
        )
        if not self.admitted_resource_grant_ids:
            raise ValueError("admitted_resource_grant_ids cannot be empty")
        _require_text_tuple(self.allowed_tools, "allowed_tools")
        _require_text_tuple(self.accepted_scope, "accepted_scope")
        if not self.accepted_scope:
            raise ValueError("accepted_scope cannot be empty")
        if self.target_requirement_id not in self.accepted_scope:
            raise ValueError(
                "accepted_scope must include target_requirement_id"
            )
        _require_text_tuple(self.causal_parent_ids, "causal_parent_ids")
        expected_parents = (
            self.observation_id,
            self.intent_id,
            self.bid_id,
            *self.admitted_resource_grant_ids,
        )
        if self.causal_parent_ids != expected_parents:
            raise ValueError(
                "causal_parent_ids must exactly encode observation/intent/bid/grants"
            )
        if self.status is not CommitmentStatus.ACTIVE:
            raise ValueError("new commitment status must be active")
        created_at = _parse_timestamp(self.created_at, "created_at")
        deadline = _parse_timestamp(self.deadline, "deadline")
        if deadline <= created_at:
            raise ValueError("deadline must be after created_at")

    def validate_against(
        self,
        bid: AgentBid,
        intent: AgentIntent,
        observation: LocalFieldObservation,
        resource_grants: tuple[ResourceEvent, ...],
    ) -> None:
        bid.validate_against(intent, observation)
        if self.bid_id != bid.bid_id:
            raise ValueError("commitment bid_id does not match its parent")
        if self.intent_id != intent.intent_id:
            raise ValueError("commitment intent_id does not match its parent")
        if self.observation_id != observation.observation_id:
            raise ValueError(
                "commitment observation_id does not match its parent"
            )
        if self.agent_id != bid.agent_id:
            raise ValueError("commitment agent_id does not match its bid")
        if self.task_id != observation.task_id:
            raise ValueError("commitment task_id does not match its observation")
        if (
            self.requirement_schema_version
            != observation.requirement_schema_version
        ):
            raise ValueError(
                "commitment requirement_schema_version does not match observation"
            )
        if self.target_requirement_id != bid.target_requirement_id:
            raise ValueError(
                "commitment target_requirement_id does not match its bid"
            )

        grants = tuple(resource_grants)
        if tuple(item.event_id for item in grants) != (
            self.admitted_resource_grant_ids
        ):
            raise ValueError(
                "commitment admitted_resource_grant_ids do not match grants"
            )
        expected_target = f"AgentEscrow[{self.agent_id}]"
        for grant in grants:
            if grant.operation is not ResourceOperation.GRANT:
                raise ValueError("commitment references a non-grant resource event")
            if grant.source_account != "SharedPool":
                raise ValueError("resource grant must originate from SharedPool")
            if grant.target_account != expected_target:
                raise ValueError(
                    "resource grant target does not match commitment agent"
                )

        granted_by_type: dict[str, float] = {}
        for grant in grants:
            if grant.resource_type in granted_by_type:
                raise ValueError(
                    "commitment resource grants must have unique resource types"
                )
            granted_by_type[grant.resource_type] = grant.amount
        if granted_by_type != _resource_map(self.admitted_resources):
            raise ValueError(
                "commitment admitted_resources do not match resource grants"
            )

        if _parse_timestamp(self.deadline, "deadline") > _parse_timestamp(
            bid.expected_completion_window[1],
            "bid expected_completion_window end",
        ):
            raise ValueError("commitment deadline exceeds bid completion window")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AgentCommitment":
        payload = dict(value)
        payload["issuer"] = CommitmentIssuer(payload["issuer"])
        payload["status"] = CommitmentStatus(payload["status"])
        for field_name in (
            "admitted_resource_grant_ids",
            "allowed_tools",
            "accepted_scope",
            "causal_parent_ids",
        ):
            payload[field_name] = tuple(payload[field_name])
        payload["admitted_resources"] = tuple(
            ResourceAmount(**item) for item in payload["admitted_resources"]
        )
        return cls(**payload)


@dataclass(frozen=True, kw_only=True)
class ActionProposal(JsonContract):
    schema_version: int
    action_proposal_id: str
    agent_id: str
    task_id: str
    requirement_schema_version: int
    commitment_id: str
    requirement_ids: tuple[str, ...]
    tool: str
    requested_resources: tuple[ResourceAmount, ...]
    input_refs: tuple[str, ...]
    causal_parent_ids: tuple[str, ...]
    created_at: str
    expires_at: str
    issuer: GovernanceIssuer

    def __post_init__(self) -> None:
        for field_name in (
            "requirement_ids",
            "input_refs",
            "causal_parent_ids",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        object.__setattr__(
            self,
            "requested_resources",
            _normalize_resource_amounts(
                self.requested_resources,
                "requested_resources",
                require_nonempty=True,
            ),
        )
        _require_schema_version(self.schema_version)
        for field_name in (
            "action_proposal_id",
            "agent_id",
            "task_id",
            "commitment_id",
            "tool",
        ):
            _require_text(getattr(self, field_name), field_name)
        _require_integer(
            self.requirement_schema_version,
            "requirement_schema_version",
            positive=True,
        )
        _require_text_tuple(self.requirement_ids, "requirement_ids")
        if not self.requirement_ids:
            raise ValueError("requirement_ids cannot be empty")
        _require_text_tuple(self.input_refs, "input_refs")
        _require_text_tuple(self.causal_parent_ids, "causal_parent_ids")
        if self.causal_parent_ids != (self.commitment_id,):
            raise ValueError(
                "action causal_parent_ids must contain only commitment_id"
            )
        if self.issuer is not GovernanceIssuer.AGENT_PROPOSAL:
            raise ValueError("action proposal issuer must be Agent proposal")
        created_at = _parse_timestamp(self.created_at, "created_at")
        expires_at = _parse_timestamp(self.expires_at, "expires_at")
        if expires_at <= created_at:
            raise ValueError("expires_at must be after created_at")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ActionProposal":
        payload = dict(value)
        for field_name in (
            "requirement_ids",
            "input_refs",
            "causal_parent_ids",
        ):
            payload[field_name] = tuple(payload[field_name])
        payload["requested_resources"] = tuple(
            ResourceAmount(**item) for item in payload["requested_resources"]
        )
        payload["issuer"] = GovernanceIssuer(payload["issuer"])
        return cls(**payload)


@dataclass(frozen=True, kw_only=True)
class ActionAuthorization(JsonContract):
    schema_version: int
    authorization_id: str
    action_proposal_id: str
    commitment_id: str
    agent_id: str
    task_id: str
    requirement_schema_version: int
    authorized_requirement_ids: tuple[str, ...]
    authorized_tool: str
    authorized_resources: tuple[ResourceAmount, ...]
    resource_grant_ids: tuple[str, ...]
    causal_parent_ids: tuple[str, ...]
    created_at: str
    expires_at: str
    issuer: GovernanceIssuer

    def __post_init__(self) -> None:
        for field_name in (
            "authorized_requirement_ids",
            "resource_grant_ids",
            "causal_parent_ids",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        object.__setattr__(
            self,
            "authorized_resources",
            _normalize_resource_amounts(
                self.authorized_resources,
                "authorized_resources",
                require_nonempty=True,
            ),
        )
        _require_schema_version(self.schema_version)
        for field_name in (
            "authorization_id",
            "action_proposal_id",
            "commitment_id",
            "agent_id",
            "task_id",
            "authorized_tool",
        ):
            _require_text(getattr(self, field_name), field_name)
        _require_integer(
            self.requirement_schema_version,
            "requirement_schema_version",
            positive=True,
        )
        _require_text_tuple(
            self.authorized_requirement_ids,
            "authorized_requirement_ids",
        )
        if not self.authorized_requirement_ids:
            raise ValueError("authorized_requirement_ids cannot be empty")
        _require_text_tuple(self.resource_grant_ids, "resource_grant_ids")
        if not self.resource_grant_ids:
            raise ValueError("resource_grant_ids cannot be empty")
        _require_text_tuple(self.causal_parent_ids, "causal_parent_ids")
        expected_parents = (
            self.commitment_id,
            self.action_proposal_id,
            *self.resource_grant_ids,
        )
        if self.causal_parent_ids != expected_parents:
            raise ValueError(
                "authorization causal_parent_ids must encode commitment/proposal/grants"
            )
        if self.issuer is not GovernanceIssuer.HARNESS_ADMISSION:
            raise ValueError("action authorization issuer must be Harness Admission")
        created_at = _parse_timestamp(self.created_at, "created_at")
        expires_at = _parse_timestamp(self.expires_at, "expires_at")
        if expires_at <= created_at:
            raise ValueError("expires_at must be after created_at")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ActionAuthorization":
        payload = dict(value)
        for field_name in (
            "authorized_requirement_ids",
            "resource_grant_ids",
            "causal_parent_ids",
        ):
            payload[field_name] = tuple(payload[field_name])
        payload["authorized_resources"] = tuple(
            ResourceAmount(**item) for item in payload["authorized_resources"]
        )
        payload["issuer"] = GovernanceIssuer(payload["issuer"])
        return cls(**payload)


@dataclass(frozen=True, kw_only=True)
class CommitmentLifecycleSnapshot(JsonContract):
    schema_version: int
    commitment_id: str
    status: CommitmentStatus
    revision: int
    transition_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "transition_ids", tuple(self.transition_ids))
        _require_schema_version(self.schema_version)
        _require_text(self.commitment_id, "commitment_id")
        if not isinstance(self.status, CommitmentStatus):
            raise ValueError("status must be a CommitmentStatus")
        _require_integer(self.revision, "revision", nonnegative=True)
        _require_text_tuple(self.transition_ids, "transition_ids")
        if self.revision != len(self.transition_ids):
            raise ValueError("revision must equal transition_ids length")

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> "CommitmentLifecycleSnapshot":
        payload = dict(value)
        payload["status"] = CommitmentStatus(payload["status"])
        payload["transition_ids"] = tuple(payload["transition_ids"])
        return cls(**payload)


@dataclass(frozen=True, kw_only=True)
class CommitmentTransition(JsonContract):
    schema_version: int
    transition_id: str
    commitment_id: str
    previous_status: CommitmentStatus
    next_status: CommitmentStatus
    previous_revision: int
    next_revision: int
    reason: str
    occurred_at: str
    causal_parent_ids: tuple[str, ...]
    issuer: GovernanceIssuer

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "causal_parent_ids",
            tuple(self.causal_parent_ids),
        )
        _require_schema_version(self.schema_version)
        _require_text(self.transition_id, "transition_id")
        _require_text(self.commitment_id, "commitment_id")
        if self.previous_status is not CommitmentStatus.ACTIVE:
            raise ValueError("previous_status must be active")
        if self.next_status not in {
            CommitmentStatus.COMPLETED,
            CommitmentStatus.CANCELLED,
            CommitmentStatus.EXPIRED,
        }:
            raise ValueError("next_status must be terminal")
        _require_integer(
            self.previous_revision,
            "previous_revision",
            nonnegative=True,
        )
        _require_integer(self.next_revision, "next_revision", positive=True)
        if self.next_revision != self.previous_revision + 1:
            raise ValueError("next_revision must equal previous_revision + 1")
        _require_text(self.reason, "reason")
        _parse_timestamp(self.occurred_at, "occurred_at")
        _require_text_tuple(self.causal_parent_ids, "causal_parent_ids")
        if self.causal_parent_ids != (self.commitment_id,):
            raise ValueError(
                "transition causal_parent_ids must contain commitment_id"
            )
        if self.issuer is not GovernanceIssuer.HARNESS_ADMISSION:
            raise ValueError("transition issuer must be Harness Admission")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CommitmentTransition":
        payload = dict(value)
        payload["previous_status"] = CommitmentStatus(
            payload["previous_status"]
        )
        payload["next_status"] = CommitmentStatus(payload["next_status"])
        payload["causal_parent_ids"] = tuple(payload["causal_parent_ids"])
        payload["issuer"] = GovernanceIssuer(payload["issuer"])
        return cls(**payload)


@dataclass(frozen=True, kw_only=True)
class CommunicationOffer(JsonContract):
    schema_version: int
    offer_id: str
    sender_agent_id: str
    observation_id: str
    commitment_id: str
    related_requirement_id: str
    intended_audience: tuple[str, ...]
    payload_schema: str
    payload_size_bytes: int
    evidence_refs: tuple[str, ...]
    byte_budget: int
    created_at: str
    expires_at: str
    causal_parent_ids: tuple[str, ...]
    issuer: GovernanceIssuer

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "intended_audience",
            tuple(sorted(self.intended_audience)),
        )
        for field_name in ("evidence_refs", "causal_parent_ids"):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        _require_schema_version(self.schema_version)
        for field_name in (
            "offer_id",
            "sender_agent_id",
            "observation_id",
            "commitment_id",
            "related_requirement_id",
            "payload_schema",
        ):
            _require_text(getattr(self, field_name), field_name)
        _require_text_tuple(self.intended_audience, "intended_audience")
        if not self.intended_audience:
            raise ValueError("intended_audience cannot be empty")
        if self.sender_agent_id in self.intended_audience:
            raise ValueError("sender cannot be in intended_audience")
        _require_integer(
            self.payload_size_bytes,
            "payload_size_bytes",
            positive=True,
        )
        _require_integer(self.byte_budget, "byte_budget", positive=True)
        if self.payload_size_bytes > self.byte_budget:
            raise ValueError("payload_size_bytes exceeds byte_budget")
        _require_text_tuple(self.evidence_refs, "evidence_refs")
        if not self.evidence_refs:
            raise ValueError("evidence_refs cannot be empty")
        created_at = _parse_timestamp(self.created_at, "created_at")
        expires_at = _parse_timestamp(self.expires_at, "expires_at")
        if expires_at <= created_at:
            raise ValueError("expires_at must be after created_at")
        _require_text_tuple(self.causal_parent_ids, "causal_parent_ids")
        expected_parents = (
            self.observation_id,
            self.commitment_id,
            *self.evidence_refs,
        )
        if self.causal_parent_ids != expected_parents:
            raise ValueError(
                "offer causal_parent_ids must encode observation/commitment/evidence"
            )
        if self.issuer is not GovernanceIssuer.AGENT_PROPOSAL:
            raise ValueError("communication offer issuer must be Agent proposal")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CommunicationOffer":
        payload = dict(value)
        for field_name in (
            "intended_audience",
            "evidence_refs",
            "causal_parent_ids",
        ):
            payload[field_name] = tuple(payload[field_name])
        payload["issuer"] = GovernanceIssuer(payload["issuer"])
        return cls(**payload)


@dataclass(frozen=True, kw_only=True)
class CommunicationRequest(JsonContract):
    schema_version: int
    request_id: str
    requester_agent_id: str
    intended_sender_agent_id: str
    observation_id: str
    commitment_id: str
    related_requirement_id: str
    requested_payload_schema: str
    max_payload_bytes: int
    evidence_refs: tuple[str, ...]
    created_at: str
    expires_at: str
    causal_parent_ids: tuple[str, ...]
    issuer: GovernanceIssuer

    def __post_init__(self) -> None:
        for field_name in ("evidence_refs", "causal_parent_ids"):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        _require_schema_version(self.schema_version)
        for field_name in (
            "request_id",
            "requester_agent_id",
            "intended_sender_agent_id",
            "observation_id",
            "commitment_id",
            "related_requirement_id",
            "requested_payload_schema",
        ):
            _require_text(getattr(self, field_name), field_name)
        if self.requester_agent_id == self.intended_sender_agent_id:
            raise ValueError("requester and intended sender must differ")
        _require_integer(
            self.max_payload_bytes,
            "max_payload_bytes",
            positive=True,
        )
        _require_text_tuple(self.evidence_refs, "evidence_refs")
        if not self.evidence_refs:
            raise ValueError("evidence_refs cannot be empty")
        created_at = _parse_timestamp(self.created_at, "created_at")
        expires_at = _parse_timestamp(self.expires_at, "expires_at")
        if expires_at <= created_at:
            raise ValueError("expires_at must be after created_at")
        _require_text_tuple(self.causal_parent_ids, "causal_parent_ids")
        expected_parents = (
            self.observation_id,
            self.commitment_id,
            *self.evidence_refs,
        )
        if self.causal_parent_ids != expected_parents:
            raise ValueError(
                "request causal_parent_ids must encode observation/commitment/evidence"
            )
        if self.issuer is not GovernanceIssuer.AGENT_PROPOSAL:
            raise ValueError("communication request issuer must be Agent proposal")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CommunicationRequest":
        payload = dict(value)
        for field_name in ("evidence_refs", "causal_parent_ids"):
            payload[field_name] = tuple(payload[field_name])
        payload["issuer"] = GovernanceIssuer(payload["issuer"])
        return cls(**payload)


@dataclass(frozen=True, kw_only=True)
class CommunicationPermit(JsonContract):
    schema_version: int
    permit_id: str
    policy_version: str
    proposal_kind: str
    related_proposal_id: str
    commitment_id: str
    related_requirement_id: str
    sender_agent_id: str
    receiver_agent_ids: tuple[str, ...]
    payload_schema: str
    max_payload_bytes: int
    message_quota: int
    created_at: str
    expires_at: str
    causal_parent_ids: tuple[str, ...]
    issuer: GovernanceIssuer

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "receiver_agent_ids",
            tuple(sorted(self.receiver_agent_ids)),
        )
        object.__setattr__(
            self,
            "causal_parent_ids",
            tuple(self.causal_parent_ids),
        )
        _require_schema_version(self.schema_version)
        for field_name in (
            "permit_id",
            "policy_version",
            "proposal_kind",
            "related_proposal_id",
            "commitment_id",
            "related_requirement_id",
            "sender_agent_id",
            "payload_schema",
        ):
            _require_text(getattr(self, field_name), field_name)
        if self.proposal_kind not in {"offer", "request"}:
            raise ValueError("proposal_kind must be offer or request")
        _require_text_tuple(self.receiver_agent_ids, "receiver_agent_ids")
        if not self.receiver_agent_ids:
            raise ValueError("receiver_agent_ids cannot be empty")
        if self.sender_agent_id in self.receiver_agent_ids:
            raise ValueError("permit sender cannot also be a receiver")
        _require_integer(
            self.max_payload_bytes,
            "max_payload_bytes",
            positive=True,
        )
        _require_integer(self.message_quota, "message_quota", positive=True)
        created_at = _parse_timestamp(self.created_at, "created_at")
        expires_at = _parse_timestamp(self.expires_at, "expires_at")
        if expires_at <= created_at:
            raise ValueError("expires_at must be after created_at")
        _require_text_tuple(self.causal_parent_ids, "causal_parent_ids")
        if self.causal_parent_ids != (
            self.commitment_id,
            self.related_proposal_id,
        ):
            raise ValueError(
                "permit causal_parent_ids must encode commitment/proposal"
            )
        if self.issuer is not GovernanceIssuer.HARNESS_ADMISSION:
            raise ValueError("communication permit issuer must be Harness Admission")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CommunicationPermit":
        payload = dict(value)
        payload["receiver_agent_ids"] = tuple(payload["receiver_agent_ids"])
        payload["causal_parent_ids"] = tuple(payload["causal_parent_ids"])
        payload["issuer"] = GovernanceIssuer(payload["issuer"])
        return cls(**payload)


@dataclass(frozen=True)
class ActiveAgentState(JsonContract):
    agent_id: str
    state_version: int
    source_event_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_event_ids",
            tuple(sorted(self.source_event_ids)),
        )
        _require_text(self.agent_id, "agent_id")
        _require_integer(
            self.state_version,
            "state_version",
            nonnegative=True,
        )
        _require_text_tuple(self.source_event_ids, "source_event_ids")
        if self.state_version > 0 and not self.source_event_ids:
            raise ValueError(
                "non-initial agent state must reference source events"
            )


@dataclass(frozen=True)
class RequirementCommitmentLink(JsonContract):
    requirement_id: str
    commitment_id: str
    agent_id: str

    def __post_init__(self) -> None:
        _require_text(self.requirement_id, "requirement_id")
        _require_text(self.commitment_id, "commitment_id")
        _require_text(self.agent_id, "agent_id")


@dataclass(frozen=True, kw_only=True)
class CommunicationEdgeRecord(JsonContract):
    edge_id: str
    permit_id: str
    sender_agent_id: str
    receiver_agent_ids: tuple[str, ...]
    related_requirement_id: str
    payload_schema: str
    message_count: int
    payload_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "receiver_agent_ids",
            tuple(sorted(self.receiver_agent_ids)),
        )
        for field_name in (
            "edge_id",
            "permit_id",
            "sender_agent_id",
            "related_requirement_id",
            "payload_schema",
        ):
            _require_text(getattr(self, field_name), field_name)
        _require_text_tuple(self.receiver_agent_ids, "receiver_agent_ids")
        if not self.receiver_agent_ids:
            raise ValueError("receiver_agent_ids cannot be empty")
        if self.sender_agent_id in self.receiver_agent_ids:
            raise ValueError("edge sender cannot be a receiver")
        _require_integer(
            self.message_count,
            "message_count",
            nonnegative=True,
        )
        _require_integer(
            self.payload_bytes,
            "payload_bytes",
            nonnegative=True,
        )


@dataclass(frozen=True)
class DistributionCount(JsonContract):
    category: str
    count: int

    def __post_init__(self) -> None:
        _require_text(self.category, "category")
        _require_integer(self.count, "count", nonnegative=True)


@dataclass(frozen=True, kw_only=True)
class AgentCostContribution(JsonContract):
    agent_id: str
    actual_cost: tuple[ResourceAmount, ...]
    accepted_contribution: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "actual_cost",
            _normalize_resource_amounts(self.actual_cost, "actual_cost"),
        )
        _require_text(self.agent_id, "agent_id")
        _require_number(
            self.accepted_contribution,
            "accepted_contribution",
            nonnegative=True,
        )


@dataclass(frozen=True)
class CentralPresetInfo(JsonContract):
    role_bindings: tuple[str, ...]
    route_refs: tuple[str, ...]
    topology_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "role_bindings",
            "route_refs",
            "topology_refs",
        ):
            object.__setattr__(
                self,
                field_name,
                tuple(sorted(getattr(self, field_name))),
            )
            _require_text_tuple(getattr(self, field_name), field_name)


@dataclass(frozen=True, kw_only=True)
class ExperienceStructuralChange(JsonContract):
    change_id: str
    experience_update_id: str
    before_structure_hash: str
    after_structure_hash: str
    affected_edge_ids: tuple[str, ...]
    source_event_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("affected_edge_ids", "source_event_ids"):
            object.__setattr__(
                self,
                field_name,
                tuple(sorted(getattr(self, field_name))),
            )
        _require_text(self.change_id, "change_id")
        _require_text(self.experience_update_id, "experience_update_id")
        _require_sha256(
            self.before_structure_hash,
            "before_structure_hash",
        )
        _require_sha256(self.after_structure_hash, "after_structure_hash")
        if self.before_structure_hash == self.after_structure_hash:
            raise ValueError("structural change hashes must differ")
        _require_text_tuple(self.affected_edge_ids, "affected_edge_ids")
        _require_text_tuple(self.source_event_ids, "source_event_ids")
        if not self.source_event_ids:
            raise ValueError("source_event_ids cannot be empty")


@dataclass(frozen=True, kw_only=True)
class OrganizationSnapshot(JsonContract):
    schema_version: int
    snapshot_id: str
    run_id: str
    task_id: str
    checkpoint_id: str
    requirement_schema_version: int
    public_state_revision: int
    active_agents: tuple[ActiveAgentState, ...]
    requirement_commitments: tuple[RequirementCommitmentLink, ...]
    communication_edges: tuple[CommunicationEdgeRecord, ...]
    duplicate_distribution: tuple[DistributionCount, ...]
    refusal_distribution: tuple[DistributionCount, ...]
    agent_cost_contributions: tuple[AgentCostContribution, ...]
    central_preset_info: CentralPresetInfo
    experience_structural_changes: tuple[ExperienceStructuralChange, ...]
    parent_event_ids: tuple[str, ...]
    builder_version: str
    created_at: str
    snapshot_hash: str

    def __post_init__(self) -> None:
        sort_keys = {
            "active_agents": lambda item: item.agent_id,
            "requirement_commitments": lambda item: (
                item.requirement_id,
                item.commitment_id,
            ),
            "communication_edges": lambda item: item.edge_id,
            "duplicate_distribution": lambda item: item.category,
            "refusal_distribution": lambda item: item.category,
            "agent_cost_contributions": lambda item: item.agent_id,
            "experience_structural_changes": lambda item: item.change_id,
        }
        for field_name, key in sort_keys.items():
            object.__setattr__(
                self,
                field_name,
                tuple(sorted(getattr(self, field_name), key=key)),
            )
        object.__setattr__(
            self,
            "parent_event_ids",
            tuple(sorted(self.parent_event_ids)),
        )
        _require_schema_version(self.schema_version)
        for field_name in (
            "snapshot_id",
            "run_id",
            "task_id",
            "checkpoint_id",
            "builder_version",
        ):
            _require_text(getattr(self, field_name), field_name)
        _require_integer(
            self.requirement_schema_version,
            "requirement_schema_version",
            positive=True,
        )
        _require_integer(
            self.public_state_revision,
            "public_state_revision",
            nonnegative=True,
        )
        if not self.active_agents:
            raise ValueError("active_agents cannot be empty")
        typed_collections = (
            ("active_agents", ActiveAgentState),
            ("requirement_commitments", RequirementCommitmentLink),
            ("communication_edges", CommunicationEdgeRecord),
            ("duplicate_distribution", DistributionCount),
            ("refusal_distribution", DistributionCount),
            ("agent_cost_contributions", AgentCostContribution),
            ("experience_structural_changes", ExperienceStructuralChange),
        )
        for field_name, expected_type in typed_collections:
            if not all(
                isinstance(item, expected_type)
                for item in getattr(self, field_name)
            ):
                raise ValueError(
                    f"{field_name} must contain {expected_type.__name__} values"
                )
        if not isinstance(self.central_preset_info, CentralPresetInfo):
            raise ValueError(
                "central_preset_info must be a CentralPresetInfo"
            )
        uniqueness = (
            (
                tuple(item.agent_id for item in self.active_agents),
                "active agent IDs",
            ),
            (
                tuple(
                    (item.requirement_id, item.commitment_id)
                    for item in self.requirement_commitments
                ),
                "requirement-commitment links",
            ),
            (
                tuple(item.edge_id for item in self.communication_edges),
                "communication edge IDs",
            ),
            (
                tuple(item.category for item in self.duplicate_distribution),
                "duplicate distribution categories",
            ),
            (
                tuple(item.category for item in self.refusal_distribution),
                "refusal distribution categories",
            ),
            (
                tuple(
                    item.agent_id for item in self.agent_cost_contributions
                ),
                "agent cost IDs",
            ),
            (
                tuple(
                    item.change_id
                    for item in self.experience_structural_changes
                ),
                "experience structural change IDs",
            ),
        )
        for values, field_name in uniqueness:
            if len(values) != len(set(values)):
                if field_name == "active agent IDs":
                    raise ValueError("duplicate active agent IDs are not allowed")
                raise ValueError(f"duplicate {field_name} are not allowed")
        active_agent_ids = {item.agent_id for item in self.active_agents}
        referenced_agents = {
            item.agent_id for item in self.requirement_commitments
        }
        referenced_agents.update(
            edge.sender_agent_id for edge in self.communication_edges
        )
        referenced_agents.update(
            receiver
            for edge in self.communication_edges
            for receiver in edge.receiver_agent_ids
        )
        inactive_agents = referenced_agents - active_agent_ids
        if inactive_agents:
            raise ValueError(
                "organization references inactive agents: "
                + ",".join(sorted(inactive_agents))
            )
        cost_agent_ids = {
            item.agent_id for item in self.agent_cost_contributions
        }
        if cost_agent_ids != active_agent_ids:
            raise ValueError(
                "agent cost contributions must cover every active agent"
            )
        _require_text_tuple(self.parent_event_ids, "parent_event_ids")
        if not self.parent_event_ids:
            raise ValueError("parent_event_ids cannot be empty")
        required_parents = {
            source
            for agent in self.active_agents
            for source in agent.source_event_ids
        }
        required_parents.update(
            item.commitment_id for item in self.requirement_commitments
        )
        required_parents.update(
            item.permit_id for item in self.communication_edges
        )
        for change in self.experience_structural_changes:
            required_parents.add(change.experience_update_id)
            required_parents.update(change.source_event_ids)
        missing_parents = required_parents - set(self.parent_event_ids)
        if missing_parents:
            raise ValueError(
                "snapshot is missing parent event IDs: "
                + ",".join(sorted(missing_parents))
            )
        _parse_timestamp(self.created_at, "created_at")
        _require_sha256(self.snapshot_hash, "snapshot_hash")
        expected_hash = self.compute_snapshot_hash()
        if self.snapshot_hash != expected_hash:
            raise ValueError("snapshot_hash does not match snapshot payload")
        if self.snapshot_id != f"organization-snapshot-{self.snapshot_hash}":
            raise ValueError("snapshot_id must be derived from snapshot_hash")

    def compute_snapshot_hash(self) -> str:
        payload = {
            field.name: _jsonable(getattr(self, field.name))
            for field in fields(self)
            if field.name not in {"snapshot_id", "snapshot_hash"}
        }
        encoded = json.dumps(
            payload,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OrganizationSnapshot":
        payload = dict(value)
        payload["active_agents"] = tuple(
            ActiveAgentState(
                agent_id=item["agent_id"],
                state_version=item["state_version"],
                source_event_ids=tuple(item["source_event_ids"]),
            )
            for item in payload["active_agents"]
        )
        payload["requirement_commitments"] = tuple(
            RequirementCommitmentLink(**item)
            for item in payload["requirement_commitments"]
        )
        payload["communication_edges"] = tuple(
            CommunicationEdgeRecord(
                **{
                    **item,
                    "receiver_agent_ids": tuple(item["receiver_agent_ids"]),
                }
            )
            for item in payload["communication_edges"]
        )
        for field_name in (
            "duplicate_distribution",
            "refusal_distribution",
        ):
            payload[field_name] = tuple(
                DistributionCount(**item) for item in payload[field_name]
            )
        payload["agent_cost_contributions"] = tuple(
            AgentCostContribution(
                agent_id=item["agent_id"],
                actual_cost=tuple(
                    ResourceAmount(**cost) for cost in item["actual_cost"]
                ),
                accepted_contribution=item["accepted_contribution"],
            )
            for item in payload["agent_cost_contributions"]
        )
        preset = payload["central_preset_info"]
        payload["central_preset_info"] = CentralPresetInfo(
            role_bindings=tuple(preset["role_bindings"]),
            route_refs=tuple(preset["route_refs"]),
            topology_refs=tuple(preset["topology_refs"]),
        )
        payload["experience_structural_changes"] = tuple(
            ExperienceStructuralChange(
                **{
                    **item,
                    "affected_edge_ids": tuple(item["affected_edge_ids"]),
                    "source_event_ids": tuple(item["source_event_ids"]),
                }
            )
            for item in payload["experience_structural_changes"]
        )
        payload["parent_event_ids"] = tuple(payload["parent_event_ids"])
        return cls(**payload)


@dataclass(frozen=True, kw_only=True)
class AgentRefusal(JsonContract):
    schema_version: int
    refusal_id: str
    agent_id: str
    observation_id: str
    local_state_version: int
    target_requirement_id: str
    reason_code: RefusalReason
    bounded_explanation: str
    retry_conditions: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "retry_conditions", tuple(self.retry_conditions))
        _require_schema_version(self.schema_version)
        _require_text(self.refusal_id, "refusal_id")
        _require_text(self.agent_id, "agent_id")
        _require_text(self.observation_id, "observation_id")
        _require_integer(
            self.local_state_version,
            "local_state_version",
            nonnegative=True,
        )
        _require_text(self.target_requirement_id, "target_requirement_id")
        if not isinstance(self.reason_code, RefusalReason):
            raise ValueError("reason_code must be a RefusalReason")
        _require_text(self.bounded_explanation, "bounded_explanation")
        if len(self.bounded_explanation) > 500:
            raise ValueError("bounded_explanation cannot exceed 500 characters")
        _require_text_tuple(self.retry_conditions, "retry_conditions")
        if not self.retry_conditions:
            raise ValueError("retry_conditions cannot be empty")

    def validate_against(self, observation: LocalFieldObservation) -> None:
        if self.observation_id != observation.observation_id:
            raise ValueError("refusal observation_id does not match its parent")
        if self.agent_id != observation.agent_id:
            raise ValueError(
                "refusal agent_id does not match observation audience"
            )
        if (
            self.target_requirement_id
            not in observation.visible_requirement_signals
        ):
            raise ValueError(
                "refusal target_requirement_id is not visible in its observation"
            )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AgentRefusal":
        payload = dict(value)
        payload["reason_code"] = RefusalReason(payload["reason_code"])
        payload["retry_conditions"] = tuple(payload["retry_conditions"])
        return cls(**payload)


REQUIRED_FROZEN_SURFACES = frozenset(
    {
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
    }
)


@dataclass(frozen=True)
class UpdateSurfaceRule(JsonContract):
    surface: str
    surface_schema_version: int
    max_serialized_bytes: int
    max_updates_per_run: int

    def __post_init__(self) -> None:
        _require_text(self.surface, "surface")
        _require_integer(
            self.surface_schema_version,
            "surface_schema_version",
            positive=True,
        )
        _require_integer(
            self.max_serialized_bytes,
            "max_serialized_bytes",
            positive=True,
        )
        _require_integer(
            self.max_updates_per_run,
            "max_updates_per_run",
            positive=True,
        )


@dataclass(frozen=True, kw_only=True)
class UpdateSurfaceManifest(JsonContract):
    schema_version: int
    manifest_id: str
    run_id: str
    manifest_version: int
    mutable_surface_rules: tuple[UpdateSurfaceRule, ...]
    frozen_surfaces: tuple[str, ...]
    promotion_rules: tuple[str, ...]
    invalidation_rules: tuple[str, ...]
    rollback_policy: str

    def __post_init__(self) -> None:
        rules = tuple(
            sorted(self.mutable_surface_rules, key=lambda item: item.surface)
        )
        object.__setattr__(self, "mutable_surface_rules", rules)
        for field_name in (
            "frozen_surfaces",
            "promotion_rules",
            "invalidation_rules",
        ):
            object.__setattr__(
                self,
                field_name,
                tuple(sorted(getattr(self, field_name))),
            )
        _require_schema_version(self.schema_version)
        _require_text(self.manifest_id, "manifest_id")
        _require_text(self.run_id, "run_id")
        _require_integer(
            self.manifest_version,
            "manifest_version",
            positive=True,
        )
        if not rules:
            raise ValueError("mutable_surface_rules cannot be empty")
        if not all(isinstance(item, UpdateSurfaceRule) for item in rules):
            raise ValueError(
                "mutable_surface_rules must contain UpdateSurfaceRule values"
            )
        _require_unique(
            tuple(item.surface for item in rules),
            "mutable surfaces",
        )
        _require_text_tuple(self.frozen_surfaces, "frozen_surfaces")
        missing = REQUIRED_FROZEN_SURFACES - set(self.frozen_surfaces)
        if missing:
            raise ValueError(
                "manifest is missing required frozen surfaces: "
                + ",".join(sorted(missing))
            )
        overlap = {
            mutable
            for mutable in (item.surface for item in rules)
            for frozen in self.frozen_surfaces
            if (
                mutable == frozen
                or mutable.startswith(f"{frozen}.")
                or frozen.startswith(f"{mutable}.")
            )
        }
        if overlap:
            raise ValueError(
                "surface cannot be both mutable and frozen: "
                + ",".join(sorted(overlap))
            )
        _require_text_tuple(self.promotion_rules, "promotion_rules")
        if not self.promotion_rules:
            raise ValueError("promotion_rules cannot be empty")
        _require_text_tuple(self.invalidation_rules, "invalidation_rules")
        if not self.invalidation_rules:
            raise ValueError("invalidation_rules cannot be empty")
        _require_text(self.rollback_policy, "rollback_policy")

    def rule_for(self, surface: str) -> UpdateSurfaceRule | None:
        for rule in self.mutable_surface_rules:
            if rule.surface == surface:
                return rule
        return None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UpdateSurfaceManifest":
        payload = dict(value)
        payload["mutable_surface_rules"] = tuple(
            UpdateSurfaceRule(**item)
            for item in payload["mutable_surface_rules"]
        )
        for field_name in (
            "frozen_surfaces",
            "promotion_rules",
            "invalidation_rules",
        ):
            payload[field_name] = tuple(payload[field_name])
        return cls(**payload)


@dataclass(frozen=True, kw_only=True)
class LocalStateSnapshot(JsonContract):
    schema_version: int
    agent_id: str
    state_version: int
    values: Mapping[str, JsonValue]
    source_update_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_schema_version(self.schema_version)
        _require_text(self.agent_id, "agent_id")
        _require_integer(
            self.state_version,
            "state_version",
            nonnegative=True,
        )
        object.__setattr__(
            self,
            "values",
            _normalize_json_mapping(self.values, "values"),
        )
        object.__setattr__(
            self,
            "source_update_ids",
            tuple(self.source_update_ids),
        )
        _require_text_tuple(self.source_update_ids, "source_update_ids")
        if self.state_version != len(self.source_update_ids):
            raise ValueError(
                "state_version must equal the number of source_update_ids"
            )

    def state_hash(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LocalStateSnapshot":
        payload = dict(value)
        payload["source_update_ids"] = tuple(payload["source_update_ids"])
        return cls(**payload)


@dataclass(frozen=True, kw_only=True)
class LocalStateUpdateProposal(JsonContract):
    schema_version: int
    proposal_id: str
    agent_id: str
    manifest_id: str
    manifest_version: int
    previous_state_version: int
    destination_surface: str
    update_kind: str
    source_event_window: tuple[str, ...]
    changed_fields: tuple[str, ...]
    proposed_values: Mapping[str, JsonValue]
    reversible: bool
    rollback_ref: str | None
    issuer: LocalStateUpdateIssuer = LocalStateUpdateIssuer.AGENT_PROPOSAL

    def __post_init__(self) -> None:
        for field_name in ("source_event_window", "changed_fields"):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        object.__setattr__(
            self,
            "proposed_values",
            _normalize_json_mapping(self.proposed_values, "proposed_values"),
        )
        _require_schema_version(self.schema_version)
        for field_name in (
            "proposal_id",
            "agent_id",
            "manifest_id",
            "destination_surface",
            "update_kind",
        ):
            _require_text(getattr(self, field_name), field_name)
        _require_integer(
            self.manifest_version,
            "manifest_version",
            positive=True,
        )
        _require_integer(
            self.previous_state_version,
            "previous_state_version",
            nonnegative=True,
        )
        if self.issuer is not LocalStateUpdateIssuer.AGENT_PROPOSAL:
            raise ValueError("state proposal issuer must be Agent proposal")
        _require_text_tuple(self.source_event_window, "source_event_window")
        if not self.source_event_window:
            raise ValueError("source_event_window cannot be empty")
        _require_text_tuple(self.changed_fields, "changed_fields")
        if not self.changed_fields:
            raise ValueError("changed_fields cannot be empty")
        if set(self.changed_fields) != set(self.proposed_values):
            raise ValueError(
                "changed_fields must exactly match proposed_values keys"
            )
        if not isinstance(self.reversible, bool):
            raise ValueError("reversible must be a boolean")
        if self.reversible:
            _require_text(self.rollback_ref, "rollback_ref")
        elif self.rollback_ref is not None:
            _require_text(self.rollback_ref, "rollback_ref")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LocalStateUpdateProposal":
        payload = dict(value)
        payload["source_event_window"] = tuple(payload["source_event_window"])
        payload["changed_fields"] = tuple(payload["changed_fields"])
        payload["issuer"] = LocalStateUpdateIssuer(payload["issuer"])
        return cls(**payload)


@dataclass(frozen=True, kw_only=True)
class LocalStateUpdate(JsonContract):
    schema_version: int
    update_id: str
    proposal_id: str
    agent_id: str
    manifest_id: str
    manifest_version: int
    compiler_policy_version: str
    previous_state_version: int
    next_state_version: int
    destination_surface: str
    update_kind: str
    source_event_window: tuple[str, ...]
    changed_fields: tuple[str, ...]
    committed_values: Mapping[str, JsonValue]
    before_hash: str
    after_hash: str
    reversible: bool
    rollback_ref: str | None
    issuer: LocalStateUpdateIssuer

    def __post_init__(self) -> None:
        for field_name in ("source_event_window", "changed_fields"):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        object.__setattr__(
            self,
            "committed_values",
            _normalize_json_mapping(self.committed_values, "committed_values"),
        )
        _require_schema_version(self.schema_version)
        for field_name in (
            "update_id",
            "proposal_id",
            "agent_id",
            "manifest_id",
            "compiler_policy_version",
            "destination_surface",
            "update_kind",
        ):
            _require_text(getattr(self, field_name), field_name)
        _require_integer(
            self.manifest_version,
            "manifest_version",
            positive=True,
        )
        _require_integer(
            self.previous_state_version,
            "previous_state_version",
            nonnegative=True,
        )
        _require_integer(
            self.next_state_version,
            "next_state_version",
            positive=True,
        )
        if self.next_state_version != self.previous_state_version + 1:
            raise ValueError(
                "next_state_version must equal previous_state_version + 1"
            )
        if self.issuer is not LocalStateUpdateIssuer.HARNESS_COMPILER:
            raise ValueError("state update issuer must be Harness compiler")
        _require_text_tuple(self.source_event_window, "source_event_window")
        if not self.source_event_window:
            raise ValueError("source_event_window cannot be empty")
        _require_text_tuple(self.changed_fields, "changed_fields")
        if not self.changed_fields:
            raise ValueError("changed_fields cannot be empty")
        if set(self.changed_fields) != set(self.committed_values):
            raise ValueError(
                "changed_fields must exactly match committed_values keys"
            )
        _require_sha256(self.before_hash, "before_hash")
        _require_sha256(self.after_hash, "after_hash")
        if not isinstance(self.reversible, bool):
            raise ValueError("reversible must be a boolean")
        if self.reversible:
            _require_text(self.rollback_ref, "rollback_ref")
        elif self.rollback_ref is not None:
            _require_text(self.rollback_ref, "rollback_ref")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LocalStateUpdate":
        payload = dict(value)
        payload["source_event_window"] = tuple(payload["source_event_window"])
        payload["changed_fields"] = tuple(payload["changed_fields"])
        payload["issuer"] = LocalStateUpdateIssuer(payload["issuer"])
        return cls(**payload)


@dataclass(frozen=True, kw_only=True)
class ExperienceUpdateRecord(JsonContract):
    schema_version: int
    experience_update_id: str
    agent_id: str
    manifest_id: str
    manifest_version: int
    source_event_window: tuple[str, ...]
    compiler_policy_version: str
    destination_surface: str
    previous_version: int
    candidate_hash: str
    validation_status: ExperienceValidationStatus
    promoted_version: int | None
    rejected_reason: str | None
    expires_at: str
    invalidation_conditions: tuple[str, ...]
    rollback_ref: str
    issuer: LocalStateUpdateIssuer

    def __post_init__(self) -> None:
        for field_name in ("source_event_window", "invalidation_conditions"):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        _require_schema_version(self.schema_version)
        for field_name in (
            "experience_update_id",
            "agent_id",
            "manifest_id",
            "compiler_policy_version",
            "destination_surface",
            "rollback_ref",
        ):
            _require_text(getattr(self, field_name), field_name)
        _require_integer(
            self.manifest_version,
            "manifest_version",
            positive=True,
        )
        _require_integer(
            self.previous_version,
            "previous_version",
            nonnegative=True,
        )
        _require_text_tuple(self.source_event_window, "source_event_window")
        if not self.source_event_window:
            raise ValueError("source_event_window cannot be empty")
        _require_sha256(self.candidate_hash, "candidate_hash")
        if not isinstance(self.validation_status, ExperienceValidationStatus):
            raise ValueError(
                "validation_status must be an ExperienceValidationStatus"
            )
        if self.validation_status is ExperienceValidationStatus.PROMOTED:
            if self.promoted_version != self.previous_version + 1:
                raise ValueError(
                    "promoted_version must equal previous_version + 1"
                )
            if self.rejected_reason is not None:
                raise ValueError(
                    "promoted experience cannot have rejected_reason"
                )
        else:
            if self.promoted_version is not None:
                raise ValueError(
                    "non-promoted experience cannot have promoted_version"
                )
            _require_text(self.rejected_reason, "rejected_reason")
        _parse_timestamp(self.expires_at, "expires_at")
        _require_text_tuple(
            self.invalidation_conditions,
            "invalidation_conditions",
        )
        if not self.invalidation_conditions:
            raise ValueError("invalidation_conditions cannot be empty")
        if self.issuer is not LocalStateUpdateIssuer.HARNESS_COMPILER:
            raise ValueError("experience update issuer must be Harness compiler")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExperienceUpdateRecord":
        payload = dict(value)
        payload["source_event_window"] = tuple(payload["source_event_window"])
        payload["invalidation_conditions"] = tuple(
            payload["invalidation_conditions"]
        )
        payload["validation_status"] = ExperienceValidationStatus(
            payload["validation_status"]
        )
        payload["issuer"] = LocalStateUpdateIssuer(payload["issuer"])
        return cls(**payload)


@dataclass(frozen=True)
class TaskSpec(JsonContract):
    task_id: str
    requirement_schema_version: int
    goal: str
    requirements: tuple[RequirementSpec, ...]
    requirement_dependencies: tuple[RequirementDependency, ...] = ()
    constraints: tuple[str, ...] = ()
    acceptance_rules: tuple[str, ...] = ()
    resource_limits: tuple[ResourceLimit, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "requirements", tuple(self.requirements))
        object.__setattr__(
            self, "requirement_dependencies", tuple(self.requirement_dependencies)
        )
        object.__setattr__(self, "constraints", tuple(self.constraints))
        object.__setattr__(self, "acceptance_rules", tuple(self.acceptance_rules))
        object.__setattr__(self, "resource_limits", tuple(self.resource_limits))

        _require_text(self.task_id, "task_id")
        if (
            isinstance(self.requirement_schema_version, bool)
            or not isinstance(self.requirement_schema_version, int)
            or self.requirement_schema_version < 1
        ):
            raise ValueError("requirement_schema_version must be a positive integer")
        _require_text(self.goal, "goal")
        if not self.requirements:
            raise ValueError("requirements cannot be empty")
        if not all(isinstance(item, RequirementSpec) for item in self.requirements):
            raise ValueError("requirements must contain RequirementSpec values")
        requirement_ids = tuple(item.requirement_id for item in self.requirements)
        _require_unique(requirement_ids, "requirement_ids")
        if not any(item.required for item in self.requirements):
            raise ValueError("at least one requirement must be required")

        if not all(
            isinstance(item, RequirementDependency)
            for item in self.requirement_dependencies
        ):
            raise ValueError(
                "requirement_dependencies must contain RequirementDependency values"
            )
        known = set(requirement_ids)
        for dependency in self.requirement_dependencies:
            if (
                dependency.requirement_id not in known
                or dependency.depends_on_requirement_id not in known
            ):
                raise ValueError("dependency references an unknown requirement")
        dependency_keys = tuple(
            (
                item.requirement_id,
                item.depends_on_requirement_id,
                item.kind.value,
            )
            for item in self.requirement_dependencies
        )
        _require_unique(dependency_keys, "requirement_dependencies")

        _require_text_tuple(self.constraints, "constraints")
        _require_text_tuple(self.acceptance_rules, "acceptance_rules")
        if not self.acceptance_rules:
            raise ValueError("acceptance_rules cannot be empty")
        if not all(isinstance(item, ResourceLimit) for item in self.resource_limits):
            raise ValueError("resource_limits must contain ResourceLimit values")
        _require_unique(
            tuple(item.resource_type for item in self.resource_limits),
            "resource_types",
        )


@dataclass(frozen=True, kw_only=True)
class ActionObservation(JsonContract):
    action_id: str
    agent_id: str
    requirement_ids: tuple[str, ...]
    input_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    resource_cost: tuple[ResourceAmount, ...] = ()
    started_at: str
    finished_at: str
    status: ActionStatus

    def __post_init__(self) -> None:
        for field_name in (
            "requirement_ids",
            "input_refs",
            "artifact_refs",
            "evidence_refs",
            "resource_cost",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        _require_text(self.action_id, "action_id")
        _require_text(self.agent_id, "agent_id")
        _require_text_tuple(self.requirement_ids, "requirement_ids")
        if not self.requirement_ids:
            raise ValueError("requirement_ids cannot be empty")
        _require_text_tuple(self.input_refs, "input_refs")
        _require_text_tuple(self.artifact_refs, "artifact_refs")
        _require_text_tuple(self.evidence_refs, "evidence_refs")
        if not all(isinstance(item, ResourceAmount) for item in self.resource_cost):
            raise ValueError("resource_cost must contain ResourceAmount values")
        _require_unique(
            tuple(item.resource_type for item in self.resource_cost),
            "resource_cost resource_types",
        )
        _require_text(self.started_at, "started_at")
        _require_text(self.finished_at, "finished_at")
        if not isinstance(self.status, ActionStatus):
            raise ValueError("status must be an ActionStatus")


@dataclass(frozen=True)
class RequirementDelta(JsonContract):
    requirement_id: str
    disposition: FeedbackDisposition
    evidence_refs: tuple[str, ...] = ()
    invalidates_feedback_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        object.__setattr__(
            self,
            "invalidates_feedback_ids",
            tuple(self.invalidates_feedback_ids),
        )
        _require_text(self.requirement_id, "requirement_id")
        if not isinstance(self.disposition, FeedbackDisposition):
            raise ValueError("disposition must be a FeedbackDisposition")
        _require_text_tuple(self.evidence_refs, "evidence_refs")
        _require_text_tuple(
            self.invalidates_feedback_ids, "invalidates_feedback_ids"
        )


@dataclass(frozen=True)
class ClaimAuthority(JsonContract):
    claim_type: str
    authority: str

    def __post_init__(self) -> None:
        _require_text(self.claim_type, "claim_type")
        _require_text(self.authority, "authority")


@dataclass(frozen=True, kw_only=True)
class FeedbackEvent(JsonContract):
    feedback_id: str
    task_id: str
    action_id: str
    requirement_deltas: tuple[RequirementDelta, ...]
    source_kind: FeedbackSourceKind
    source_authority_by_claim_type: tuple[ClaimAuthority, ...] = ()
    confidence: float
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "requirement_deltas", tuple(self.requirement_deltas))
        object.__setattr__(
            self,
            "source_authority_by_claim_type",
            tuple(self.source_authority_by_claim_type),
        )
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        _require_text(self.feedback_id, "feedback_id")
        _require_text(self.task_id, "task_id")
        _require_text(self.action_id, "action_id")
        if not self.requirement_deltas:
            raise ValueError("requirement_deltas cannot be empty")
        if not all(
            isinstance(item, RequirementDelta) for item in self.requirement_deltas
        ):
            raise ValueError("requirement_deltas must contain RequirementDelta values")
        _require_unique(
            tuple(item.requirement_id for item in self.requirement_deltas),
            "requirement_ids",
        )
        if not isinstance(self.source_kind, FeedbackSourceKind):
            raise ValueError("source_kind must be a FeedbackSourceKind")
        if not all(
            isinstance(item, ClaimAuthority)
            for item in self.source_authority_by_claim_type
        ):
            raise ValueError(
                "source_authority_by_claim_type must contain ClaimAuthority values"
            )
        _require_unique(
            tuple(
                item.claim_type for item in self.source_authority_by_claim_type
            ),
            "claim_types",
        )
        _require_number(self.confidence, "confidence")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        _require_text_tuple(self.evidence_refs, "evidence_refs")
        for delta in self.requirement_deltas:
            if not delta.evidence_refs and not self.evidence_refs:
                raise ValueError(
                    f"feedback for {delta.requirement_id!r} must reference evidence"
                )


@dataclass(frozen=True, kw_only=True)
class ResourceEvent(JsonContract):
    event_id: str
    operation: ResourceOperation
    resource_type: str
    amount: float
    source_account: str
    target_account: str
    idempotency_key: str

    def __post_init__(self) -> None:
        _require_text(self.event_id, "event_id")
        if not isinstance(self.operation, ResourceOperation):
            raise ValueError("operation must be a ResourceOperation")
        _require_text(self.resource_type, "resource_type")
        _require_number(self.amount, "amount", positive=True)
        _require_text(self.source_account, "source_account")
        _require_text(self.target_account, "target_account")
        if self.source_account == self.target_account:
            raise ValueError("source_account and target_account must differ")
        _require_text(self.idempotency_key, "idempotency_key")


@dataclass(frozen=True, kw_only=True)
class RequirementResidual(JsonContract):
    requirement_id: str
    required: bool = True
    status: RequirementStatus
    supporting_evidence_refs: tuple[str, ...] = ()
    conflicting_evidence_refs: tuple[str, ...] = ()
    feedback_ids: tuple[str, ...] = ()
    invalidated_feedback_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "supporting_evidence_refs",
            "conflicting_evidence_refs",
            "feedback_ids",
            "invalidated_feedback_ids",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        _require_text(self.requirement_id, "requirement_id")
        if not isinstance(self.required, bool):
            raise ValueError("required must be a boolean")
        if not isinstance(self.status, RequirementStatus):
            raise ValueError("status must be a RequirementStatus")
        _require_text_tuple(
            self.supporting_evidence_refs, "supporting_evidence_refs"
        )
        _require_text_tuple(
            self.conflicting_evidence_refs, "conflicting_evidence_refs"
        )
        _require_text_tuple(self.feedback_ids, "feedback_ids")
        _require_text_tuple(
            self.invalidated_feedback_ids, "invalidated_feedback_ids"
        )
        if set(self.feedback_ids) & set(self.invalidated_feedback_ids):
            raise ValueError(
                "active feedback_ids and invalidated_feedback_ids cannot overlap"
            )


@dataclass(frozen=True, kw_only=True)
class ResidualSnapshot(JsonContract):
    task_id: str
    requirement_schema_version: int
    revision: int
    requirements: tuple[RequirementResidual, ...]
    applied_feedback_ids: tuple[str, ...]
    complete: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "requirements", tuple(self.requirements))
        object.__setattr__(
            self, "applied_feedback_ids", tuple(self.applied_feedback_ids)
        )
        _require_text(self.task_id, "task_id")
        if (
            isinstance(self.requirement_schema_version, bool)
            or not isinstance(self.requirement_schema_version, int)
            or self.requirement_schema_version < 1
        ):
            raise ValueError("requirement_schema_version must be a positive integer")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 0
        ):
            raise ValueError("revision must be a non-negative integer")
        if not self.requirements:
            raise ValueError("requirements cannot be empty")
        if not all(isinstance(item, RequirementResidual) for item in self.requirements):
            raise ValueError("requirements must contain RequirementResidual values")
        _require_unique(
            tuple(item.requirement_id for item in self.requirements),
            "requirement_ids",
        )
        if not any(item.required for item in self.requirements):
            raise ValueError("at least one residual requirement must be required")
        _require_text_tuple(self.applied_feedback_ids, "applied_feedback_ids")
        applied = set(self.applied_feedback_ids)
        if any(
            feedback_id not in applied
            for requirement in self.requirements
            for feedback_id in (
                requirement.feedback_ids + requirement.invalidated_feedback_ids
            )
        ):
            raise ValueError(
                "requirement feedback IDs must be applied feedback IDs"
            )
        if not isinstance(self.complete, bool):
            raise ValueError("complete must be a boolean")
        expected_complete = all(
            not item.required or item.status is RequirementStatus.SATISFIED
            for item in self.requirements
        )
        if self.complete != expected_complete:
            raise ValueError("complete must be derived from required requirement states")

    def requirement(self, requirement_id: str) -> RequirementResidual:
        for item in self.requirements:
            if item.requirement_id == requirement_id:
                return item
        raise KeyError(requirement_id)

    def status_by_requirement(self) -> dict[str, RequirementStatus]:
        return {item.requirement_id: item.status for item in self.requirements}


@dataclass(frozen=True, kw_only=True)
class RunFinalization(JsonContract):
    schema_version: int
    experiment_id: str
    run_id: str
    status: RunTerminalStatus
    reason: str
    event_count: int
    file_sha256: Mapping[str, str]
    final_state_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("schema_version must be 1")
        _require_text(self.experiment_id, "experiment_id")
        _require_text(self.run_id, "run_id")
        if not isinstance(self.status, RunTerminalStatus):
            raise ValueError("status must be a RunTerminalStatus")
        _require_text(self.reason, "reason")
        if (
            isinstance(self.event_count, bool)
            or not isinstance(self.event_count, int)
            or self.event_count < 0
        ):
            raise ValueError("event_count must be a non-negative integer")
        if not isinstance(self.file_sha256, Mapping) or not self.file_sha256:
            raise ValueError("file_sha256 must be a non-empty mapping")
        normalized_hashes = dict(self.file_sha256)
        for filename, digest in normalized_hashes.items():
            _require_text(filename, "file_sha256 filename")
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ValueError("file_sha256 values must be lowercase SHA-256 digests")
        object.__setattr__(self, "file_sha256", MappingProxyType(normalized_hashes))
        if (
            not isinstance(self.final_state_sha256, str)
            or len(self.final_state_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.final_state_sha256
            )
        ):
            raise ValueError("final_state_sha256 must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class MetricSeries(JsonContract):
    name: str
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", tuple(self.values))
        _require_text(self.name, "name")
        if not self.values:
            raise ValueError("metric values cannot be empty")
        for value in self.values:
            _require_number(value, "metric value")


@dataclass(frozen=True)
class MetricValue(JsonContract):
    name: str
    value: float

    def __post_init__(self) -> None:
        _require_text(self.name, "name")
        _require_number(self.value, "metric value")


@dataclass(frozen=True)
class MetricInterval(JsonContract):
    name: str
    lower: float
    upper: float
    confidence_level: float

    def __post_init__(self) -> None:
        _require_text(self.name, "name")
        _require_number(self.lower, "lower")
        _require_number(self.upper, "upper")
        if self.lower > self.upper:
            raise ValueError("interval lower cannot exceed upper")
        _require_number(self.confidence_level, "confidence_level")
        if not 0 < self.confidence_level < 1:
            raise ValueError("confidence_level must be between 0 and 1")


@dataclass(frozen=True, kw_only=True)
class ExperimentResult(JsonContract):
    experiment_id: str
    hypothesis: str
    configuration: Mapping[str, JsonValue]
    seeds: tuple[int, ...]
    task_structure: str
    raw_metrics: tuple[MetricSeries, ...]
    effect_sizes: tuple[MetricValue, ...]
    intervals: tuple[MetricInterval, ...]
    failures: tuple[str, ...]
    evidence_level: EvidenceLevel
    decision: ExperimentDecision
    artifacts: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "configuration", dict(self.configuration))
        for field_name in (
            "seeds",
            "raw_metrics",
            "effect_sizes",
            "intervals",
            "failures",
            "artifacts",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        _require_text(self.experiment_id, "experiment_id")
        _require_text(self.hypothesis, "hypothesis")
        if not isinstance(self.configuration, Mapping):
            raise ValueError("configuration must be a mapping")
        if not self.configuration:
            raise ValueError("configuration cannot be empty")
        if not all(isinstance(key, str) and key for key in self.configuration):
            raise ValueError("configuration keys must be non-empty strings")
        try:
            json.dumps(_jsonable(self.configuration), allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError("configuration must be JSON serializable") from error
        object.__setattr__(self, "configuration", _freeze_json(self.configuration))
        if not self.seeds:
            raise ValueError("seeds cannot be empty")
        if any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
            for seed in self.seeds
        ):
            raise ValueError("seeds must be non-negative integers")
        _require_unique(self.seeds, "seeds")
        _require_text(self.task_structure, "task_structure")
        if not all(isinstance(item, MetricSeries) for item in self.raw_metrics):
            raise ValueError("raw_metrics must contain MetricSeries values")
        if not self.raw_metrics:
            raise ValueError("raw_metrics cannot be empty")
        if not all(isinstance(item, MetricValue) for item in self.effect_sizes):
            raise ValueError("effect_sizes must contain MetricValue values")
        if not all(isinstance(item, MetricInterval) for item in self.intervals):
            raise ValueError("intervals must contain MetricInterval values")
        _require_unique(tuple(item.name for item in self.raw_metrics), "raw metric names")
        _require_unique(
            tuple(item.name for item in self.effect_sizes), "effect size names"
        )
        _require_unique(tuple(item.name for item in self.intervals), "interval names")
        _require_text_tuple(self.failures, "failures")
        if not isinstance(self.evidence_level, EvidenceLevel):
            raise ValueError("evidence_level must be an EvidenceLevel")
        if not isinstance(self.decision, ExperimentDecision):
            raise ValueError("decision must be an ExperimentDecision")
        _require_text_tuple(self.artifacts, "artifacts")
        if not self.artifacts:
            raise ValueError("artifacts cannot be empty")
        if self.decision in {
            ExperimentDecision.SUPPORT,
            ExperimentDecision.REJECT,
        } and not self.effect_sizes:
            raise ValueError("support/reject decisions require effect_sizes")
        if self.evidence_level is EvidenceLevel.CONFIRMATORY:
            if not self.intervals:
                raise ValueError("confirmatory results require intervals")
            interval_names = {item.name for item in self.intervals}
            missing = [
                item.name for item in self.effect_sizes if item.name not in interval_names
            ]
            if missing:
                raise ValueError(
                    "every confirmatory effect size requires a matching interval"
                )
