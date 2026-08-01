"""Contract-only orchestration primitives for a future formal MEAS0 Pilot.

This module deliberately does not reuse the offline foundation runner and
does not claim that a formal Pilot has run.  Test-only providers can exercise
the frozen 36-case by five-arm denominator.  Production providers additionally
require independently validated readiness evidence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from .measurement import (
    EvaluationResult,
    EvaluationStatus,
    MeasurementContractError,
    MeasurementDimension,
    MeasurementObservation,
    SealedEpisode,
    TaskMeasurementBundle,
    fuse_evidence,
)
from .meas0_formal_metrics import (
    FORMAL_ARMS,
    FormalCaseIdentity,
    formal_attack_manifest,
)
from .meas0_readiness import (
    ArmOrderManifest,
    BudgetPolicy,
    FormalReadinessBundle,
    FormalReadinessState,
    PriceManifest,
    arm_order_manifest,
    pilot_budget_policy,
)
from .meas0_stage_cost import (
    CostCategory,
    CostOutcome,
    StageBudgetManifest,
    StageCostEntry,
    StageCostLedger,
)
from .meas0_trust import (
    SignedTransportReceipt,
    TransportBatchEntry,
    TransportOutcome,
)


FORMAL_RUNNER_VERSION = "meas0.formal-runner-contract.v6"
CLAIM_SCOPE = "contract_only"
_FORMAL_AUTHORIZATION_DERIVATION_TOKEN = object()


class FormalRunnerError(ValueError):
    """Raised when formal runner inputs violate the frozen contract."""


class FormalRunnerProtocolGap(FormalRunnerError):
    """Raised when the design does not freeze enough execution semantics."""


class BackendMode(str, Enum):
    TEST_ONLY = "test_only"
    PRODUCTION = "production"


class ResultValidity(str, Enum):
    VALID = "valid"
    INVALID = "invalid"


class FailureCode(str, Enum):
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    MALFORMED_RESPONSE = "malformed_response"
    BACKEND_INVALID = "backend_invalid"
    BUDGET_EXHAUSTED = "budget_exhausted"
    STAGE_BUDGET_EXHAUSTED = "stage_budget_exhausted"
    PROTOCOL_VIOLATION = "protocol_violation"


_FAILURE_DISPOSITIONS = {
    FailureCode.TIMEOUT: (ResultValidity.VALID, EvaluationStatus.UNKNOWN),
    FailureCode.PROVIDER_ERROR: (
        ResultValidity.INVALID,
        EvaluationStatus.INVALID,
    ),
    FailureCode.MALFORMED_RESPONSE: (
        ResultValidity.INVALID,
        EvaluationStatus.INVALID,
    ),
    FailureCode.BACKEND_INVALID: (
        ResultValidity.INVALID,
        EvaluationStatus.INVALID,
    ),
    FailureCode.BUDGET_EXHAUSTED: (
        ResultValidity.VALID,
        EvaluationStatus.UNKNOWN,
    ),
    FailureCode.STAGE_BUDGET_EXHAUSTED: (
        ResultValidity.VALID,
        EvaluationStatus.UNKNOWN,
    ),
    FailureCode.PROTOCOL_VIOLATION: (
        ResultValidity.INVALID,
        EvaluationStatus.INVALID,
    ),
}
_FORMAL_RUN_DERIVATION_TOKEN = object()


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FormalRunnerError(f"{label} must be non-empty text")
    return value


def _sha256_text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise FormalRunnerError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise FormalRunnerError(f"{label} must be a non-negative integer")
    return value


def _positive_int(value: object, label: str) -> int:
    result = _non_negative_int(value, label)
    if result == 0:
        raise FormalRunnerError(f"{label} must be a positive integer")
    return result


def _json_text(value: object, label: str) -> str:
    text = _text(value, label)
    try:
        json.loads(
            text,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError(f"invalid constant: {item}")
            ),
        )
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise FormalRunnerError(f"{label} must contain valid JSON") from error
    return text


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _content_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


@dataclass(frozen=True)
class FormalBackendDescriptor:
    provider_id: str
    provider_version: str
    arm_id: str
    mode: BackendMode
    enforces_timeouts: bool

    def __post_init__(self) -> None:
        _text(self.provider_id, "provider_id")
        _text(self.provider_version, "provider_version")
        if self.arm_id not in FORMAL_ARMS:
            raise FormalRunnerError("backend arm_id is outside the frozen set")
        if not isinstance(self.mode, BackendMode):
            raise FormalRunnerError("backend mode is invalid")
        if not isinstance(self.enforces_timeouts, bool):
            raise FormalRunnerError("enforces_timeouts must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "arm_id": self.arm_id,
            "mode": self.mode.value,
            "enforces_timeouts": self.enforces_timeouts,
        }


@dataclass(frozen=True)
class FormalCostArtifact:
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
    wall_time_ms: int = 0
    cpu_time_ms: int = 0
    bytes_transferred: int = 0
    communication_messages: int = 0
    communication_tokens: int = 0
    state_update_calls: int = 0
    verifier_calls: int = 0
    deterministic_check_calls: int = 0
    deterministic_wall_time_ms: int = 0
    judge_calls: int = 0
    human_escalations: int = 0
    retry_count: int = 0
    accounting_complete: bool = True

    def __post_init__(self) -> None:
        for field_name, value in self.to_dict().items():
            if field_name == "accounting_complete":
                if not isinstance(value, bool):
                    raise FormalRunnerError("cost accounting_complete must be boolean")
                continue
            _non_negative_int(value, f"cost {field_name}")

    def to_dict(self) -> dict[str, int | bool]:
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
        }


@dataclass(frozen=True)
class JudgeCallCostArtifact:
    input_tokens: int
    output_tokens: int
    wall_time_ms: int
    transport_batch_entry: TransportBatchEntry | None = None
    transport_receipt: SignedTransportReceipt | None = None

    def __post_init__(self) -> None:
        for field_name in ("input_tokens", "output_tokens", "wall_time_ms"):
            _non_negative_int(
                getattr(self, field_name),
                f"Judge call {field_name}",
            )
        if not isinstance(
            self.transport_batch_entry, TransportBatchEntry
        ) or not isinstance(
            self.transport_receipt,
            SignedTransportReceipt,
        ):
            raise FormalRunnerError(
                "Judge call requires typed transport batch entry and receipt"
            )
        entry = self.transport_batch_entry
        payload = self.transport_receipt.payload
        if (
            payload.phase != "pilot"
            or payload.batch_manifest_hash != entry.contract_hash
            or payload.sequence_number != entry.sequence_number
            or payload.invocation_id != entry.invocation_id
            or payload.criterion_id != entry.criterion_id
            or payload.presentation_hash != entry.presentation_hash
            or payload.data_attestation_hash != entry.data_attestation_hash
            or payload.request_fingerprint != entry.request_fingerprint
            or payload.request_bytes_hash != entry.request_bytes_hash
        ):
            raise FormalRunnerError(
                "Judge transport receipt/batch-entry binding is invalid"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "wall_time_ms": self.wall_time_ms,
            "transport_batch_entry": self.transport_batch_entry.to_dict(),
            "transport_receipt": self.transport_receipt.to_dict(),
        }


@dataclass(frozen=True)
class RawObservationArtifact:
    observation_id: str
    case_id: str
    arm_id: str
    source: str
    payload_json: str

    def __post_init__(self) -> None:
        _text(self.observation_id, "observation_id")
        _text(self.case_id, "observation case_id")
        if self.arm_id not in FORMAL_ARMS:
            raise FormalRunnerError("observation arm_id is invalid")
        _text(self.source, "observation source")
        _json_text(self.payload_json, "observation payload")

    def to_dict(self) -> dict[str, str]:
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
        }


@dataclass(frozen=True)
class RawResultArtifact:
    result_id: str
    case_id: str
    arm_id: str
    automatic_status: EvaluationStatus
    timed_out: bool
    payload_json: str

    def __post_init__(self) -> None:
        _text(self.result_id, "raw result_id")
        _text(self.case_id, "raw result case_id")
        if self.arm_id not in FORMAL_ARMS:
            raise FormalRunnerError("raw result arm_id is invalid")
        if not isinstance(self.automatic_status, EvaluationStatus):
            raise FormalRunnerError("raw result status is invalid")
        if not isinstance(self.timed_out, bool):
            raise FormalRunnerError("raw result timed_out must be boolean")
        _json_text(self.payload_json, "raw result payload")

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "case_id": self.case_id,
            "arm_id": self.arm_id,
            "automatic_status": self.automatic_status.value,
            "timed_out": self.timed_out,
            "payload_json": self.payload_json,
        }


@dataclass(frozen=True)
class CanonicalEvaluationBinding:
    """Typed leaves and result rederived by the frozen Measurement Plane."""

    task_measurement_bundle: TaskMeasurementBundle
    sealed_episode: SealedEpisode
    observations: tuple[MeasurementObservation, ...]
    evaluation_result: EvaluationResult

    def __post_init__(self) -> None:
        if not isinstance(self.task_measurement_bundle, TaskMeasurementBundle):
            raise FormalRunnerError(
                "canonical evaluation requires a TaskMeasurementBundle"
            )
        if not isinstance(self.sealed_episode, SealedEpisode):
            raise FormalRunnerError("canonical evaluation requires a SealedEpisode")
        object.__setattr__(self, "observations", tuple(self.observations))
        if not self.observations or not all(
            isinstance(item, MeasurementObservation) for item in self.observations
        ):
            raise FormalRunnerError(
                "canonical evaluation requires typed measurement observations"
            )
        if not isinstance(self.evaluation_result, EvaluationResult):
            raise FormalRunnerError("canonical evaluation requires an EvaluationResult")
        try:
            derived = fuse_evidence(
                result_id=self.evaluation_result.result_id,
                task_measurement_bundle=self.task_measurement_bundle,
                sealed_episode=self.sealed_episode,
                observations=self.observations,
            )
        except MeasurementContractError as error:
            raise FormalRunnerError(
                "canonical evaluation inputs violate the frozen measurement contract"
            ) from error
        if derived != self.evaluation_result:
            raise FormalRunnerError(
                "canonical fusion does not reproduce the supplied evaluation result"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_measurement_bundle": self.task_measurement_bundle.to_dict(),
            "sealed_episode": self.sealed_episode.to_dict(),
            "observations": [item.to_dict() for item in self.observations],
            "evaluation_result": self.evaluation_result.to_dict(),
        }


@dataclass(frozen=True)
class BackendExecution:
    authorization_hash: str
    case_id: str
    arm_id: str
    observations: tuple[RawObservationArtifact, ...]
    raw_result: RawResultArtifact
    cost: FormalCostArtifact
    judge_call_costs: tuple[JudgeCallCostArtifact, ...] = ()
    canonical_evaluation: CanonicalEvaluationBinding | None = None

    def __post_init__(self) -> None:
        _sha256_text(self.authorization_hash, "backend authorization_hash")
        _text(self.case_id, "backend execution case_id")
        if self.arm_id not in FORMAL_ARMS:
            raise FormalRunnerError("backend execution arm_id is invalid")
        object.__setattr__(self, "observations", tuple(self.observations))
        object.__setattr__(
            self,
            "judge_call_costs",
            tuple(self.judge_call_costs),
        )
        if not all(
            isinstance(item, RawObservationArtifact) for item in self.observations
        ):
            raise FormalRunnerError("backend observations are malformed")
        if not isinstance(self.raw_result, RawResultArtifact):
            raise FormalRunnerError("backend raw result is malformed")
        if not isinstance(self.cost, FormalCostArtifact):
            raise FormalRunnerError("backend cost is malformed")
        if not all(
            isinstance(item, JudgeCallCostArtifact) for item in self.judge_call_costs
        ):
            raise FormalRunnerError("Judge call costs are malformed")
        if self.canonical_evaluation is not None and not isinstance(
            self.canonical_evaluation,
            CanonicalEvaluationBinding,
        ):
            raise FormalRunnerError("canonical evaluation binding is malformed")
        if (
            self.canonical_evaluation is not None
            and self.raw_result.automatic_status
            is not self.canonical_evaluation.evaluation_result.outcome
        ):
            raise FormalRunnerError(
                "backend-reported status differs from canonical evaluation"
            )


@dataclass(frozen=True)
class BackendFailureEvidence:
    """Typed accounting returned when a provider call fails after Judge attempts."""

    authorization_hash: str
    case_id: str
    arm_id: str
    cost: FormalCostArtifact
    judge_call_costs: tuple[JudgeCallCostArtifact, ...]

    def __post_init__(self) -> None:
        _sha256_text(self.authorization_hash, "backend failure authorization_hash")
        _text(self.case_id, "backend failure case_id")
        if self.arm_id not in FORMAL_ARMS:
            raise FormalRunnerError("backend failure arm_id is invalid")
        if not isinstance(self.cost, FormalCostArtifact):
            raise FormalRunnerError("backend failure cost is malformed")
        object.__setattr__(self, "judge_call_costs", tuple(self.judge_call_costs))
        if (
            not self.cost.accounting_complete
            or self.cost.judge_calls != len(self.judge_call_costs)
            or not self.judge_call_costs
            or not all(
                isinstance(item, JudgeCallCostArtifact)
                for item in self.judge_call_costs
            )
            or any(
                item.transport_receipt.payload.outcome is not TransportOutcome.FAILED
                for item in self.judge_call_costs
            )
        ):
            raise FormalRunnerError(
                "backend failure requires complete typed failed Judge attempts"
            )


class FormalBackendExecutionError(Exception):
    """Provider failure carrying complete evidence for already-made Judge calls."""

    def __init__(
        self,
        *,
        code: FailureCode,
        message: str,
        evidence: BackendFailureEvidence,
    ) -> None:
        if code not in {FailureCode.TIMEOUT, FailureCode.PROVIDER_ERROR}:
            raise FormalRunnerError("backend execution error code is invalid")
        _text(message, "backend execution error message")
        if not isinstance(evidence, BackendFailureEvidence):
            raise FormalRunnerError("backend execution error evidence is malformed")
        self.code = code
        self.evidence = evidence
        super().__init__(message)


@dataclass(frozen=True)
class FormalPilotCaseInput:
    case: FormalCaseIdentity
    task_hash: str
    episode_hash: str
    failure_policy_hash: str
    semantic_leaf_count: int
    measurement_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.case, FormalCaseIdentity) or self.case.phase != "pilot":
            raise FormalRunnerError("formal runner case must be a pilot case")
        _sha256_text(self.task_hash, "task_hash")
        _sha256_text(self.episode_hash, "episode_hash")
        _sha256_text(self.failure_policy_hash, "failure_policy_hash")
        _non_negative_int(self.semantic_leaf_count, "semantic_leaf_count")
        _positive_int(self.measurement_count, "measurement_count")

    def to_dict(self) -> dict[str, Any]:
        return {
            "case": self.case.to_dict(),
            "task_hash": self.task_hash,
            "episode_hash": self.episode_hash,
            "failure_policy_hash": self.failure_policy_hash,
            "semantic_leaf_count": self.semantic_leaf_count,
            "measurement_count": self.measurement_count,
        }


@dataclass(frozen=True)
class FormalPilotPlan:
    cases: tuple[FormalPilotCaseInput, ...]
    arm_order: ArmOrderManifest
    budget_policy: BudgetPolicy
    price_manifest: PriceManifest
    stage_budget_manifest: StageBudgetManifest
    stage_cost_pre_ledger: StageCostLedger

    def __post_init__(self) -> None:
        object.__setattr__(self, "cases", tuple(self.cases))
        if len(self.cases) != 36:
            raise FormalRunnerError("formal Pilot plan must retain exactly 36 cases")
        if not all(isinstance(item, FormalPilotCaseInput) for item in self.cases):
            raise FormalRunnerError("formal Pilot case inputs are malformed")
        case_ids = tuple(item.case.case_id for item in self.cases)
        if len(set(case_ids)) != len(case_ids):
            raise FormalRunnerError("formal Pilot cases contain a duplicate")
        expected = tuple(item.case_id for item in formal_attack_manifest("pilot").cases)
        if case_ids != expected:
            raise FormalRunnerError(
                "formal Pilot case order differs from the frozen manifest"
            )
        if self.arm_order != arm_order_manifest():
            raise FormalRunnerError("formal Pilot arm order is not frozen")
        if self.budget_policy != pilot_budget_policy():
            raise FormalRunnerError("formal Pilot budget policy is not frozen")
        if not isinstance(self.price_manifest, PriceManifest):
            raise FormalRunnerError("formal Pilot requires a typed PriceManifest")
        if not isinstance(self.stage_budget_manifest, StageBudgetManifest):
            raise FormalRunnerError("formal Pilot requires a typed StageBudgetManifest")
        if not isinstance(self.stage_cost_pre_ledger, StageCostLedger):
            raise FormalRunnerError(
                "formal Pilot requires a typed StageCost pre-ledger"
            )
        if (
            self.stage_cost_pre_ledger.price_manifest_hash
            != self.price_manifest.contract_hash
            or self.stage_cost_pre_ledger.budget_manifest.contract_hash
            != self.stage_budget_manifest.contract_hash
            or any(
                item.phase in {"pilot", "jaudit", "confirmatory"}
                for item in self.stage_cost_pre_ledger.entries
            )
            or self.stage_cost_pre_ledger.phase_decision("pilot").stopped
        ):
            raise FormalRunnerError(
                "formal Pilot StageCost pre-ledger ancestry is invalid"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cases": [item.to_dict() for item in self.cases],
            "arm_order": self.arm_order.to_dict(),
            "budget_policy": self.budget_policy.to_dict(),
            "price_manifest": self.price_manifest.to_dict(),
            "stage_budget_manifest": self.stage_budget_manifest.to_dict(),
            "stage_cost_pre_ledger": self.stage_cost_pre_ledger.to_dict(),
        }

    @property
    def plan_hash(self) -> str:
        return _content_hash(self.to_dict())


@dataclass(frozen=True)
class FormalExecutionAuthorization:
    """Hash-bound pre-execution authority for one formal contract run."""

    execution_id: str
    mode: BackendMode
    plan_hash: str
    readiness_bundle_hash: str | None
    price_manifest_hash: str
    stage_budget_manifest_hash: str
    stage_cost_pre_ledger_hash: str
    provider_descriptors: tuple[FormalBackendDescriptor, ...]
    provider_manifest_hash: str
    authorization_hash: str
    _derivation_token: object = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self._derivation_token is not _FORMAL_AUTHORIZATION_DERIVATION_TOKEN:
            raise FormalRunnerError(
                "formal execution authorization must be derived by create()"
            )
        _text(self.execution_id, "formal execution_id")
        if not isinstance(self.mode, BackendMode):
            raise FormalRunnerError("formal authorization mode is invalid")
        _sha256_text(self.plan_hash, "formal authorization plan_hash")
        if self.readiness_bundle_hash is not None:
            _sha256_text(
                self.readiness_bundle_hash,
                "formal authorization readiness_bundle_hash",
            )
        _sha256_text(
            self.price_manifest_hash,
            "formal authorization price_manifest_hash",
        )
        _sha256_text(
            self.stage_budget_manifest_hash,
            "formal authorization stage_budget_manifest_hash",
        )
        _sha256_text(
            self.stage_cost_pre_ledger_hash,
            "formal authorization stage_cost_pre_ledger_hash",
        )
        if self.mode is BackendMode.PRODUCTION and self.readiness_bundle_hash is None:
            raise FormalRunnerError(
                "production authorization requires a readiness bundle hash"
            )
        if (
            self.mode is BackendMode.TEST_ONLY
            and self.readiness_bundle_hash is not None
        ):
            raise FormalRunnerError(
                "test-only authorization cannot claim production readiness"
            )
        object.__setattr__(
            self,
            "provider_descriptors",
            tuple(self.provider_descriptors),
        )
        if tuple(
            item.arm_id for item in self.provider_descriptors
        ) != arm_order_manifest().resolved_arm_order or not all(
            isinstance(item, FormalBackendDescriptor) and item.mode is self.mode
            for item in self.provider_descriptors
        ):
            raise FormalRunnerError(
                "formal authorization provider manifest is malformed"
            )
        if self.mode is BackendMode.PRODUCTION and any(
            not item.enforces_timeouts for item in self.provider_descriptors
        ):
            raise FormalRunnerError(
                "production authorization requires backend timeout enforcement"
            )
        expected_provider_hash = _content_hash(
            [item.to_dict() for item in self.provider_descriptors]
        )
        if self.provider_manifest_hash != expected_provider_hash:
            raise FormalRunnerError(
                "formal authorization provider manifest hash mismatch"
            )
        expected_authorization_hash = _content_hash(self._body())
        if self.authorization_hash != expected_authorization_hash:
            raise FormalRunnerError("formal authorization hash mismatch")

    @classmethod
    def create(
        cls,
        *,
        execution_id: str,
        mode: BackendMode,
        plan: FormalPilotPlan,
        readiness_bundle: FormalReadinessBundle | None,
        provider_descriptors: Sequence[FormalBackendDescriptor],
    ) -> FormalExecutionAuthorization:
        if not isinstance(plan, FormalPilotPlan):
            raise FormalRunnerError("formal authorization requires a Pilot plan")
        if mode is BackendMode.PRODUCTION:
            if (
                not isinstance(readiness_bundle, FormalReadinessBundle)
                or readiness_bundle.report.state
                is not FormalReadinessState.FORMAL_READY
            ):
                raise FormalRunnerError(
                    "production authorization requires a typed FORMAL_READY bundle"
                )
            inputs = readiness_bundle.inputs
            if (
                inputs.price_manifest != plan.price_manifest
                or inputs.stage_budget_manifest != plan.stage_budget_manifest
                or inputs.stage_cost_ledger != plan.stage_cost_pre_ledger
            ):
                raise FormalRunnerError(
                    "production plan StageCost inputs differ from readiness"
                )
            readiness_bundle_hash = readiness_bundle.bundle_hash
        elif mode is BackendMode.TEST_ONLY:
            if readiness_bundle is not None:
                raise FormalRunnerError(
                    "test-only authorization cannot accept production readiness"
                )
            readiness_bundle_hash = None
        else:
            raise FormalRunnerError("formal authorization mode is invalid")
        descriptors = tuple(provider_descriptors)
        provider_hash = _content_hash([item.to_dict() for item in descriptors])
        body = {
            "execution_id": execution_id,
            "mode": mode.value,
            "plan_hash": plan.plan_hash,
            "readiness_bundle_hash": readiness_bundle_hash,
            "price_manifest_hash": plan.price_manifest.contract_hash,
            "stage_budget_manifest_hash": plan.stage_budget_manifest.contract_hash,
            "stage_cost_pre_ledger_hash": (plan.stage_cost_pre_ledger.contract_hash),
            "provider_manifest_hash": provider_hash,
        }
        return cls(
            execution_id=execution_id,
            mode=mode,
            plan_hash=plan.plan_hash,
            readiness_bundle_hash=readiness_bundle_hash,
            price_manifest_hash=plan.price_manifest.contract_hash,
            stage_budget_manifest_hash=plan.stage_budget_manifest.contract_hash,
            stage_cost_pre_ledger_hash=plan.stage_cost_pre_ledger.contract_hash,
            provider_descriptors=descriptors,
            provider_manifest_hash=provider_hash,
            authorization_hash=_content_hash(body),
            _derivation_token=_FORMAL_AUTHORIZATION_DERIVATION_TOKEN,
        )

    def _body(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "mode": self.mode.value,
            "plan_hash": self.plan_hash,
            "readiness_bundle_hash": self.readiness_bundle_hash,
            "price_manifest_hash": self.price_manifest_hash,
            "stage_budget_manifest_hash": self.stage_budget_manifest_hash,
            "stage_cost_pre_ledger_hash": self.stage_cost_pre_ledger_hash,
            "provider_manifest_hash": self.provider_manifest_hash,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._body(),
            "provider_descriptors": [
                item.to_dict() for item in self.provider_descriptors
            ],
            "authorization_hash": self.authorization_hash,
        }


@dataclass(frozen=True)
class FormalArmRequest:
    authorization_hash: str
    execution_index: int
    case: FormalCaseIdentity
    arm_id: str
    task_hash: str
    episode_hash: str
    failure_policy_hash: str
    semantic_leaf_count: int
    measurement_count: int
    budget_policy_hash: str
    price_manifest_hash: str
    stage_budget_manifest_hash: str
    stage_cost_pre_ledger_hash: str

    def __post_init__(self) -> None:
        _sha256_text(self.authorization_hash, "request authorization_hash")
        _non_negative_int(self.execution_index, "request execution_index")
        if not isinstance(self.case, FormalCaseIdentity) or self.case.phase != "pilot":
            raise FormalRunnerError("request case must be a Pilot FormalCaseIdentity")
        if self.arm_id not in FORMAL_ARMS:
            raise FormalRunnerError("request arm_id is outside the frozen set")
        _sha256_text(self.task_hash, "request task_hash")
        _sha256_text(self.episode_hash, "request episode_hash")
        _sha256_text(
            self.failure_policy_hash,
            "request failure_policy_hash",
        )
        _non_negative_int(
            self.semantic_leaf_count,
            "request semantic_leaf_count",
        )
        _positive_int(self.measurement_count, "request measurement_count")
        _sha256_text(
            self.budget_policy_hash,
            "request budget_policy_hash",
        )
        for field_name in (
            "price_manifest_hash",
            "stage_budget_manifest_hash",
            "stage_cost_pre_ledger_hash",
        ):
            _sha256_text(getattr(self, field_name), f"request {field_name}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorization_hash": self.authorization_hash,
            "execution_index": self.execution_index,
            "case": self.case.to_dict(),
            "arm_id": self.arm_id,
            "task_hash": self.task_hash,
            "episode_hash": self.episode_hash,
            "failure_policy_hash": self.failure_policy_hash,
            "semantic_leaf_count": self.semantic_leaf_count,
            "measurement_count": self.measurement_count,
            "budget_policy_hash": self.budget_policy_hash,
            "price_manifest_hash": self.price_manifest_hash,
            "stage_budget_manifest_hash": self.stage_budget_manifest_hash,
            "stage_cost_pre_ledger_hash": self.stage_cost_pre_ledger_hash,
        }

    @property
    def request_hash(self) -> str:
        return _content_hash(self.to_dict())


@runtime_checkable
class FormalArmProvider(Protocol):
    descriptor: FormalBackendDescriptor

    def execute(self, request: FormalArmRequest) -> BackendExecution:
        """Execute exactly one arm-case and return raw bound artifacts."""


@dataclass(frozen=True)
class FormalFailureArtifact:
    code: FailureCode
    message: str
    retained_in_denominator: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.code, FailureCode):
            raise FormalRunnerError("failure code is invalid")
        _text(self.message, "failure message")
        if self.retained_in_denominator is not True:
            raise FormalRunnerError("formal failure cannot drop a denominator")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "retained_in_denominator": self.retained_in_denominator,
        }


@dataclass(frozen=True)
class FormalArmCaseArtifact:
    authorization_hash: str
    request_hash: str
    execution_index: int
    case_id: str
    task_id: str
    fault_id: str
    arm_id: str
    backend_id: str
    claim_scope: str
    result_validity: ResultValidity
    automatic_status: EvaluationStatus
    observations: tuple[RawObservationArtifact, ...]
    raw_result: RawResultArtifact | None
    cost: FormalCostArtifact
    judge_call_costs: tuple[JudgeCallCostArtifact, ...]
    stage_cost_entry_hashes: tuple[str, ...]
    failure: FormalFailureArtifact | None
    canonical_evaluation: CanonicalEvaluationBinding | None = None
    retained_in_denominator: bool = True

    def __post_init__(self) -> None:
        _sha256_text(self.authorization_hash, "artifact authorization_hash")
        _sha256_text(self.request_hash, "artifact request_hash")
        _non_negative_int(self.execution_index, "execution_index")
        if (
            self.arm_id not in FORMAL_ARMS
            or self.claim_scope != CLAIM_SCOPE
            or not isinstance(self.result_validity, ResultValidity)
            or not isinstance(self.automatic_status, EvaluationStatus)
            or not isinstance(self.cost, FormalCostArtifact)
            or self.retained_in_denominator is not True
        ):
            raise FormalRunnerError("formal arm-case artifact is invalid")
        object.__setattr__(self, "observations", tuple(self.observations))
        object.__setattr__(
            self,
            "judge_call_costs",
            tuple(self.judge_call_costs),
        )
        object.__setattr__(
            self,
            "stage_cost_entry_hashes",
            tuple(
                _sha256_text(item, "artifact StageCost entry hash")
                for item in self.stage_cost_entry_hashes
            ),
        )
        expected_case = next(
            (
                item
                for item in formal_attack_manifest("pilot").cases
                if item.case_id == self.case_id
            ),
            None,
        )
        if (
            expected_case is None
            or self.task_id != expected_case.task_id
            or self.fault_id != expected_case.fault_id
        ):
            raise FormalRunnerError(
                "formal artifact case/task/fault identity is inconsistent"
            )
        _text(self.backend_id, "artifact backend_id")
        if not all(
            isinstance(item, RawObservationArtifact) for item in self.observations
        ):
            raise FormalRunnerError("formal artifact observations are malformed")
        if self.raw_result is not None and not isinstance(
            self.raw_result,
            RawResultArtifact,
        ):
            raise FormalRunnerError("formal artifact raw result is malformed")
        if self.failure is not None and not isinstance(
            self.failure,
            FormalFailureArtifact,
        ):
            raise FormalRunnerError("formal artifact failure is malformed")
        if not all(
            isinstance(item, JudgeCallCostArtifact) for item in self.judge_call_costs
        ):
            raise FormalRunnerError("formal artifact Judge costs are malformed")
        if len(self.stage_cost_entry_hashes) != len(self.judge_call_costs) and not (
            self.failure is not None
            and self.failure.code is FailureCode.MALFORMED_RESPONSE
            and not self.stage_cost_entry_hashes
        ):
            raise FormalRunnerError(
                "formal artifact Judge/StageCost ancestry is inconsistent"
            )
        receipts = tuple(
            item.transport_receipt.contract_hash for item in self.judge_call_costs
        )
        invocations = tuple(
            item.transport_receipt.payload.invocation_id
            for item in self.judge_call_costs
        )
        if len(set(receipts)) != len(receipts) or len(set(invocations)) != len(
            invocations
        ):
            raise FormalRunnerError(
                "formal artifact has duplicate Judge transport evidence"
            )
        if self.result_validity is ResultValidity.INVALID and (
            self.automatic_status is not EvaluationStatus.INVALID
        ):
            raise FormalRunnerError("invalid result must have invalid status")
        if self.failure is None and (
            self.result_validity is ResultValidity.INVALID
            or self.automatic_status is EvaluationStatus.INVALID
        ):
            raise FormalRunnerError("invalid result requires a failure artifact")
        if self.failure is None and (
            self.raw_result is None
            or not self.observations
            or self.raw_result.case_id != self.case_id
            or self.raw_result.arm_id != self.arm_id
            or any(
                item.case_id != self.case_id or item.arm_id != self.arm_id
                for item in self.observations
            )
        ):
            raise FormalRunnerError(
                "successful formal artifact identity is inconsistent"
            )
        if self.failure is not None:
            expected_validity, expected_status = _FAILURE_DISPOSITIONS[
                self.failure.code
            ]
            if (
                self.result_validity is not expected_validity
                or self.automatic_status is not expected_status
            ):
                raise FormalRunnerError(
                    "formal artifact failure disposition is inconsistent"
                )
        elif not self.cost.accounting_complete:
            raise FormalRunnerError(
                "successful formal artifact requires complete cost accounting"
            )
        elif self.raw_result.timed_out:
            raise FormalRunnerError(
                "successful formal artifact raw result cannot be timed out"
            )
        elif self.cost.judge_calls != len(self.judge_call_costs):
            raise FormalRunnerError(
                "successful formal artifact Judge accounting is inconsistent"
            )
        if self.canonical_evaluation is not None and not isinstance(
            self.canonical_evaluation,
            CanonicalEvaluationBinding,
        ):
            raise FormalRunnerError("formal artifact canonical evaluation is malformed")
        if self.canonical_evaluation is not None and (
            self.canonical_evaluation.task_measurement_bundle.task_frame.task_id
            != self.task_id
        ):
            raise FormalRunnerError(
                "formal artifact canonical task identity is inconsistent"
            )
        if self.failure is None:
            derived_status = (
                self.canonical_evaluation.evaluation_result.outcome
                if self.canonical_evaluation is not None
                else self.raw_result.automatic_status
            )
            if self.automatic_status is not derived_status:
                raise FormalRunnerError(
                    "formal artifact status differs from its authoritative result"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorization_hash": self.authorization_hash,
            "request_hash": self.request_hash,
            "execution_index": self.execution_index,
            "case_id": self.case_id,
            "task_id": self.task_id,
            "fault_id": self.fault_id,
            "arm_id": self.arm_id,
            "backend_id": self.backend_id,
            "claim_scope": self.claim_scope,
            "result_validity": self.result_validity.value,
            "automatic_status": self.automatic_status.value,
            "observations": [item.to_dict() for item in self.observations],
            "raw_result": (
                self.raw_result.to_dict() if self.raw_result is not None else None
            ),
            "cost": self.cost.to_dict(),
            "judge_call_costs": [item.to_dict() for item in self.judge_call_costs],
            "stage_cost_entry_hashes": list(self.stage_cost_entry_hashes),
            "failure": (self.failure.to_dict() if self.failure is not None else None),
            "canonical_evaluation": (
                self.canonical_evaluation.to_dict()
                if self.canonical_evaluation is not None
                else None
            ),
            "retained_in_denominator": self.retained_in_denominator,
        }

    @property
    def artifact_hash(self) -> str:
        return _content_hash(self.to_dict())


@dataclass(frozen=True)
class FormalContractRun:
    runner_version: str
    claim_scope: str
    formal_result: bool
    authorization: FormalExecutionAuthorization
    provider_descriptors: tuple[FormalBackendDescriptor, ...]
    artifacts: tuple[FormalArmCaseArtifact, ...]
    stage_cost_pre_ledger: StageCostLedger
    stage_cost_final_ledger: StageCostLedger
    stage_stopped: bool
    _derivation_token: object = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
        object.__setattr__(
            self,
            "provider_descriptors",
            tuple(self.provider_descriptors),
        )
        if (
            self.runner_version != FORMAL_RUNNER_VERSION
            or self.claim_scope != CLAIM_SCOPE
            or not isinstance(self.formal_result, bool)
            or not isinstance(
                self.authorization,
                FormalExecutionAuthorization,
            )
            or len(self.artifacts) != 180
            or not isinstance(self.stage_cost_pre_ledger, StageCostLedger)
            or not isinstance(self.stage_cost_final_ledger, StageCostLedger)
            or not isinstance(self.stage_stopped, bool)
        ):
            raise FormalRunnerError("formal contract run is malformed")
        if self.provider_descriptors != self.authorization.provider_descriptors or any(
            item.authorization_hash != self.authorization.authorization_hash
            for item in self.artifacts
        ):
            raise FormalRunnerError(
                "formal contract run authorization ancestry is inconsistent"
            )
        descriptors_by_arm = {item.arm_id: item for item in self.provider_descriptors}
        if any(
            item.backend_id != descriptors_by_arm[item.arm_id].provider_id
            for item in self.artifacts
        ):
            raise FormalRunnerError(
                "formal contract run backend identity is inconsistent"
            )
        if (
            self.authorization.price_manifest_hash
            != self.stage_cost_pre_ledger.price_manifest_hash
            or self.authorization.price_manifest_hash
            != self.stage_cost_final_ledger.price_manifest_hash
            or self.authorization.stage_budget_manifest_hash
            != self.stage_cost_pre_ledger.budget_manifest.contract_hash
            or self.authorization.stage_budget_manifest_hash
            != self.stage_cost_final_ledger.budget_manifest.contract_hash
            or self.authorization.stage_cost_pre_ledger_hash
            != self.stage_cost_pre_ledger.contract_hash
            or self.stage_cost_final_ledger.entries[
                : len(self.stage_cost_pre_ledger.entries)
            ]
            != self.stage_cost_pre_ledger.entries
        ):
            raise FormalRunnerError(
                "formal contract run StageCost ancestry is inconsistent"
            )
        artifact_entry_hashes = tuple(
            entry_hash
            for artifact in self.artifacts
            for entry_hash in artifact.stage_cost_entry_hashes
        )
        appended_entry_hashes = tuple(
            item.contract_hash
            for item in self.stage_cost_final_ledger.entries[
                len(self.stage_cost_pre_ledger.entries) :
            ]
        )
        if artifact_entry_hashes != appended_entry_hashes or len(
            set(artifact_entry_hashes)
        ) != len(artifact_entry_hashes):
            raise FormalRunnerError(
                "formal contract run Judge/StageCost membership is inconsistent"
            )
        appended_by_hash = {
            item.contract_hash: item
            for item in self.stage_cost_final_ledger.entries[
                len(self.stage_cost_pre_ledger.entries) :
            ]
        }
        for artifact in self.artifacts:
            if not artifact.stage_cost_entry_hashes:
                continue
            for call, entry_hash in zip(
                artifact.judge_call_costs,
                artifact.stage_cost_entry_hashes,
                strict=True,
            ):
                entry = appended_by_hash[entry_hash]
                receipt = call.transport_receipt
                if (
                    entry.request_hash != artifact.request_hash
                    or entry.raw_receipt_hash != receipt.contract_hash
                    or entry.call_hash != receipt.payload.contract_hash
                    or entry.arm_id != artifact.arm_id
                    or entry.provider_id != artifact.backend_id
                    or entry.model_id != receipt.payload.observed_model_id
                ):
                    raise FormalRunnerError(
                        "formal contract run receipt/StageCost cross-binding is inconsistent"
                    )
        receipt_hashes = tuple(
            call.transport_receipt.contract_hash
            for artifact in self.artifacts
            if artifact.stage_cost_entry_hashes
            for call in artifact.judge_call_costs
        )
        invocation_ids = tuple(
            call.transport_receipt.payload.invocation_id
            for artifact in self.artifacts
            if artifact.stage_cost_entry_hashes
            for call in artifact.judge_call_costs
        )
        if len(set(receipt_hashes)) != len(receipt_hashes) or len(
            set(invocation_ids)
        ) != len(invocation_ids):
            raise FormalRunnerError(
                "formal contract run has duplicate Judge transport evidence"
            )
        if self.authorization.mode is BackendMode.PRODUCTION and any(
            item.failure is None and item.canonical_evaluation is None
            for item in self.artifacts
        ):
            raise FormalRunnerError(
                "production formal run has a successful artifact without canonical evidence"
            )
        expected_stage_stopped = self.stage_cost_final_ledger.phase_decision(
            "pilot"
        ).stopped
        if self.stage_stopped is not expected_stage_stopped:
            raise FormalRunnerError(
                "formal contract run stage_stopped is not derived from artifacts"
            )
        expected_indices = tuple(range(180))
        if tuple(item.execution_index for item in self.artifacts) != (expected_indices):
            raise FormalRunnerError("formal contract run order is incomplete")
        expected_pairs = tuple(
            (case.case_id, arm_id)
            for case in formal_attack_manifest("pilot").cases
            for arm_id in arm_order_manifest().resolved_arm_order
        )
        if (
            tuple((item.case_id, item.arm_id) for item in self.artifacts)
            != expected_pairs
        ):
            raise FormalRunnerError(
                "formal contract run denominator or arm order drifted"
            )
        if self._derivation_token is not _FORMAL_RUN_DERIVATION_TOKEN:
            raise FormalRunnerError(
                "formal contract run must be derived by the contract runner"
            )
        expected_formal_result = (
            self.authorization.mode is BackendMode.PRODUCTION
            and self.authorization.readiness_bundle_hash is not None
        )
        if self.formal_result is not expected_formal_result:
            raise FormalRunnerError(
                "formal_result is not derived from the readiness-bound "
                "production authorization and validated run evidence"
            )

    @property
    def case_count(self) -> int:
        return len({item.case_id for item in self.artifacts})

    @property
    def arm_case_count(self) -> int:
        return len(self.artifacts)

    @property
    def run_hash(self) -> str:
        return _content_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "runner_version": self.runner_version,
            "claim_scope": self.claim_scope,
            "formal_result": self.formal_result,
            "authorization": self.authorization.to_dict(),
            "provider_descriptors": [
                item.to_dict() for item in self.provider_descriptors
            ],
            "artifacts": [item.to_dict() for item in self.artifacts],
            "stage_cost_pre_ledger": self.stage_cost_pre_ledger.to_dict(),
            "stage_cost_final_ledger": self.stage_cost_final_ledger.to_dict(),
            "stage_cost_pre_ledger_hash": self.stage_cost_pre_ledger_hash,
            "stage_cost_final_ledger_hash": self.stage_cost_final_ledger_hash,
            "stage_stopped": self.stage_stopped,
        }

    @property
    def stage_cost_pre_ledger_hash(self) -> str:
        return self.stage_cost_pre_ledger.contract_hash

    @property
    def stage_cost_final_ledger_hash(self) -> str:
        return self.stage_cost_final_ledger.contract_hash


def _providers_by_arm(
    providers: Mapping[str, FormalArmProvider],
) -> dict[str, FormalArmProvider]:
    if not isinstance(providers, Mapping):
        raise FormalRunnerError("formal providers must be a mapping")
    if set(providers) != set(FORMAL_ARMS):
        raise FormalRunnerError("formal providers must cover five frozen arms")
    selected = dict(providers)
    for arm_id, provider in selected.items():
        descriptor = getattr(provider, "descriptor", None)
        if (
            not isinstance(descriptor, FormalBackendDescriptor)
            or descriptor.arm_id != arm_id
            or not callable(getattr(provider, "execute", None))
        ):
            raise FormalRunnerError(f"formal provider contract is invalid for {arm_id}")
    return selected


def validate_production_backends(
    providers: Mapping[str, FormalArmProvider],
    *,
    readiness_bundle: FormalReadinessBundle | None,
) -> None:
    selected = _providers_by_arm(providers)
    test_only = tuple(
        arm_id
        for arm_id, provider in selected.items()
        if provider.descriptor.mode is BackendMode.TEST_ONLY
    )
    if test_only:
        raise FormalRunnerError(
            "production validation rejects test_only backends: "
            + ",".join(sorted(test_only))
        )
    without_timeout = tuple(
        arm_id
        for arm_id, provider in selected.items()
        if not provider.descriptor.enforces_timeouts
    )
    if without_timeout:
        raise FormalRunnerError(
            "production backends lack runtime timeout enforcement: "
            + ",".join(sorted(without_timeout))
        )
    if readiness_bundle is None:
        raise FormalRunnerError(
            "production readiness is missing Judge, human, and preflight evidence"
        )
    if not isinstance(readiness_bundle, FormalReadinessBundle):
        raise FormalRunnerError("production readiness bundle is malformed")
    inputs = readiness_bundle.inputs
    missing = []
    if inputs.judge_evidence is None:
        missing.append("Judge")
    if inputs.human_evidence is None:
        missing.append("human")
    if inputs.preflight_evidence is None:
        missing.append("preflight")
    if missing:
        raise FormalRunnerError(
            "production readiness is missing " + ", ".join(missing) + " evidence"
        )
    if readiness_bundle.report.state is not FormalReadinessState.FORMAL_READY:
        raise FormalRunnerError("production readiness is not FORMAL_READY")


def _empty_cost(*, accounting_complete: bool = True) -> FormalCostArtifact:
    return FormalCostArtifact(accounting_complete=accounting_complete)


def _failure_artifact(
    *,
    request: FormalArmRequest,
    backend_id: str,
    code: FailureCode,
    message: str,
    validity: ResultValidity,
    automatic_status: EvaluationStatus,
    observations: Sequence[RawObservationArtifact] = (),
    raw_result: RawResultArtifact | None = None,
    cost: FormalCostArtifact | None = None,
    judge_call_costs: Sequence[JudgeCallCostArtifact] = (),
    stage_cost_entry_hashes: Sequence[str] = (),
    canonical_evaluation: CanonicalEvaluationBinding | None = None,
) -> FormalArmCaseArtifact:
    return FormalArmCaseArtifact(
        authorization_hash=request.authorization_hash,
        request_hash=request.request_hash,
        execution_index=request.execution_index,
        case_id=request.case.case_id,
        task_id=request.case.task_id,
        fault_id=request.case.fault_id,
        arm_id=request.arm_id,
        backend_id=backend_id,
        claim_scope=CLAIM_SCOPE,
        result_validity=validity,
        automatic_status=automatic_status,
        observations=tuple(observations),
        raw_result=raw_result,
        cost=cost or _empty_cost(),
        judge_call_costs=tuple(judge_call_costs),
        stage_cost_entry_hashes=tuple(stage_cost_entry_hashes),
        failure=FormalFailureArtifact(code=code, message=message),
        canonical_evaluation=canonical_evaluation,
    )


def _binding_error(
    request: FormalArmRequest,
    execution: BackendExecution,
    *,
    require_canonical: bool,
    expected_provider_id: str | None = None,
) -> str | None:
    if execution.authorization_hash != request.authorization_hash:
        return "backend result authorization does not match the request"
    if (
        execution.case_id != request.case.case_id
        or execution.arm_id != request.arm_id
        or execution.raw_result.case_id != request.case.case_id
        or execution.raw_result.arm_id != request.arm_id
    ):
        return "backend result identity does not match the request"
    if not execution.observations:
        return "backend result has no raw observations"
    if any(
        item.case_id != request.case.case_id or item.arm_id != request.arm_id
        for item in execution.observations
    ):
        return "raw observation identity does not match the request"
    if not execution.cost.accounting_complete:
        return "backend result has incomplete cost accounting"
    if execution.cost.judge_calls != len(execution.judge_call_costs):
        return "Judge call count does not match raw call costs"
    transport_error = _judge_transport_binding_error(
        request,
        execution,
        expected_provider_id=expected_provider_id,
    )
    if transport_error is not None:
        return transport_error
    if execution.cost.input_tokens < sum(
        item.input_tokens for item in execution.judge_call_costs
    ) or execution.cost.output_tokens < sum(
        item.output_tokens for item in execution.judge_call_costs
    ):
        return "aggregate Judge token accounting is lower than raw call costs"
    canonical = execution.canonical_evaluation
    if require_canonical and canonical is None:
        return "production backend result has no canonical evaluation derivation"
    if (
        canonical is None
        and request.arm_id == "evaluation_plane"
        and execution.cost.judge_calls
    ):
        return "evaluation-plane Judge use has no canonical semantic leaf count"
    if canonical is not None:
        bundle = canonical.task_measurement_bundle
        if (
            bundle.task_frame.task_id != request.case.task_id
            or bundle.bundle_hash != request.task_hash
            or canonical.sealed_episode.episode_hash != request.episode_hash
            or len(bundle.measurement_graph.measurement_specs)
            != request.measurement_count
        ):
            return (
                "canonical evaluation bundle hash or other binding "
                "does not match the request"
            )
        semantic_leaf_count = sum(
            requirement.dimension is MeasurementDimension.SEMANTIC
            for requirement in bundle.requirement_graph.requirements
        )
        if semantic_leaf_count != request.semantic_leaf_count:
            return "canonical semantic leaf count does not match the request"
    return None


def _judge_transport_binding_error(
    request: FormalArmRequest,
    execution: BackendExecution | BackendFailureEvidence,
    *,
    expected_provider_id: str | None = None,
) -> str | None:
    for call in execution.judge_call_costs:
        entry = call.transport_batch_entry
        payload = call.transport_receipt.payload
        if (
            entry.request_bytes_hash != request.request_hash
            or entry.request_fingerprint != request.request_hash
            or payload.execution_authorization_hash != request.authorization_hash
            or payload.request_bytes_hash != request.request_hash
            or payload.request_fingerprint != request.request_hash
            or payload.criterion_id != request.case.fault_id
            or (
                expected_provider_id is not None
                and payload.provider_id != expected_provider_id
            )
        ):
            return "Judge transport binding does not match the formal request"
    receipt_hashes = tuple(
        item.transport_receipt.contract_hash for item in execution.judge_call_costs
    )
    invocation_ids = tuple(
        item.transport_receipt.payload.invocation_id
        for item in execution.judge_call_costs
    )
    if len(set(receipt_hashes)) != len(receipt_hashes) or len(
        set(invocation_ids)
    ) != len(invocation_ids):
        return "Judge transport evidence contains a duplicate"
    return None


def _append_judge_attempts(
    *,
    ledger: StageCostLedger,
    request: FormalArmRequest,
    execution: BackendExecution | BackendFailureEvidence,
    provider_id: str,
) -> tuple[StageCostLedger, tuple[str, ...]]:
    entries = list(ledger.entries)
    appended_hashes: list[str] = []
    for attempt_index, attempt in enumerate(execution.judge_call_costs):
        receipt = attempt.transport_receipt
        payload = receipt.payload
        outcome = (
            CostOutcome.SUCCEEDED
            if payload.outcome is TransportOutcome.SUCCESS
            else CostOutcome.FAILED
        )
        entry = StageCostEntry(
            entry_id=(
                f"{request.authorization_hash[:12]}.pilot."
                f"{request.execution_index}.{attempt_index}"
            ),
            sequence=len(entries),
            phase="pilot",
            category=CostCategory.JUDGE,
            outcome=outcome,
            failure_code=payload.failure_code,
            request_hash=request.request_hash,
            call_hash=payload.contract_hash,
            raw_receipt_hash=receipt.contract_hash,
            calls=1,
            input_tokens=attempt.input_tokens,
            output_tokens=attempt.output_tokens,
            wall_time_ms=attempt.wall_time_ms,
            bytes_transferred=payload.response_size or 0,
            retry_count=0,
            monetary_microunits=0,
            monetary_fact=None,
            automatic_arm_execution=True,
            arm_id=request.arm_id,
            provider_id=provider_id,
            model_id=payload.observed_model_id,
            cost_class="judge",
            retry_of_entry_hash=None,
            previous_entry_hash=(entries[-1].contract_hash if entries else None),
        )
        entries.append(entry)
        appended_hashes.append(entry.contract_hash)
    final = StageCostLedger(
        ledger_id=ledger.ledger_id,
        version=ledger.version,
        price_manifest_hash=ledger.price_manifest_hash,
        budget_manifest=ledger.budget_manifest,
        entries=tuple(entries),
    )
    return final, tuple(appended_hashes)


def _per_case_budget_violation(
    request: FormalArmRequest,
    execution: BackendExecution,
    policy: BudgetPolicy,
) -> tuple[FailureCode, str] | None:
    limit = next(
        item for item in policy.task_limits if item.task_id == request.case.task_id
    )
    cost = execution.cost
    deterministic_arms = {
        "state_only",
        "rules_state",
        "evaluation_plane",
    }
    if request.arm_id not in deterministic_arms and (
        cost.deterministic_check_calls or cost.deterministic_wall_time_ms
    ):
        return (
            FailureCode.PROTOCOL_VIOLATION,
            "arm is forbidden from borrowing deterministic checks",
        )
    if cost.deterministic_check_calls > limit.deterministic_checks:
        return (
            FailureCode.BUDGET_EXHAUSTED,
            "deterministic check cap exceeded",
        )
    if cost.deterministic_wall_time_ms > limit.deterministic_wall_time_ms:
        return (
            FailureCode.BUDGET_EXHAUSTED,
            "deterministic wall-time cap exceeded",
        )
    if request.arm_id == "judge_only":
        judge_cap = 2
    elif request.arm_id == "evaluation_plane":
        judge_cap = 2 * request.semantic_leaf_count
    else:
        judge_cap = 0
    if judge_cap == 0 and cost.judge_calls:
        return (
            FailureCode.PROTOCOL_VIOLATION,
            "arm is forbidden from invoking the independent Judge",
        )
    if cost.judge_calls > judge_cap:
        return (FailureCode.BUDGET_EXHAUSTED, "Judge call cap exceeded")
    if any(
        item.input_tokens > limit.judge_input_tokens
        or item.output_tokens > limit.judge_output_tokens
        or item.wall_time_ms > limit.judge_wall_time_ms
        for item in execution.judge_call_costs
    ):
        return (
            FailureCode.BUDGET_EXHAUSTED,
            "per-call Judge token or timeout cap exceeded",
        )
    if cost.human_escalations > limit.human_escalations:
        return (
            FailureCode.BUDGET_EXHAUSTED,
            "human escalation cap exceeded",
        )
    if cost.retry_count > request.measurement_count * limit.evaluator_retries:
        return (
            FailureCode.BUDGET_EXHAUSTED,
            "evaluator retry cap exceeded",
        )
    return None


def _success_artifact(
    request: FormalArmRequest,
    backend_id: str,
    execution: BackendExecution,
    stage_cost_entry_hashes: Sequence[str],
) -> FormalArmCaseArtifact:
    raw_status = (
        execution.canonical_evaluation.evaluation_result.outcome
        if execution.canonical_evaluation is not None
        else execution.raw_result.automatic_status
    )
    if execution.raw_result.timed_out:
        return _failure_artifact(
            request=request,
            backend_id=backend_id,
            code=FailureCode.TIMEOUT,
            message="backend reported a timeout",
            validity=ResultValidity.VALID,
            automatic_status=EvaluationStatus.UNKNOWN,
            observations=execution.observations,
            raw_result=execution.raw_result,
            cost=execution.cost,
            judge_call_costs=execution.judge_call_costs,
            stage_cost_entry_hashes=stage_cost_entry_hashes,
            canonical_evaluation=execution.canonical_evaluation,
        )
    if raw_status is EvaluationStatus.INVALID:
        return _failure_artifact(
            request=request,
            backend_id=backend_id,
            code=FailureCode.BACKEND_INVALID,
            message="backend explicitly returned invalid",
            validity=ResultValidity.INVALID,
            automatic_status=EvaluationStatus.INVALID,
            observations=execution.observations,
            raw_result=execution.raw_result,
            cost=execution.cost,
            judge_call_costs=execution.judge_call_costs,
            stage_cost_entry_hashes=stage_cost_entry_hashes,
            canonical_evaluation=execution.canonical_evaluation,
        )
    return FormalArmCaseArtifact(
        authorization_hash=request.authorization_hash,
        request_hash=request.request_hash,
        execution_index=request.execution_index,
        case_id=request.case.case_id,
        task_id=request.case.task_id,
        fault_id=request.case.fault_id,
        arm_id=request.arm_id,
        backend_id=backend_id,
        claim_scope=CLAIM_SCOPE,
        result_validity=ResultValidity.VALID,
        automatic_status=raw_status,
        observations=execution.observations,
        raw_result=execution.raw_result,
        cost=execution.cost,
        judge_call_costs=execution.judge_call_costs,
        stage_cost_entry_hashes=tuple(stage_cost_entry_hashes),
        failure=None,
        canonical_evaluation=execution.canonical_evaluation,
    )


def run_formal_contract(
    plan: FormalPilotPlan,
    providers: Mapping[str, FormalArmProvider],
    *,
    production_readiness: FormalReadinessBundle | None = None,
    execution_id: str = "contract-test-only.default",
) -> FormalContractRun:
    """Exercise the frozen Pilot denominator without making a Pilot claim."""

    if not isinstance(plan, FormalPilotPlan):
        raise FormalRunnerError("formal runner requires a FormalPilotPlan")
    selected = _providers_by_arm(providers)
    modes = {provider.descriptor.mode for provider in selected.values()}
    if len(modes) != 1:
        raise FormalRunnerError("formal backend modes cannot be mixed")
    if modes == {BackendMode.PRODUCTION}:
        validate_production_backends(
            selected,
            readiness_bundle=production_readiness,
        )
    mode = next(iter(modes))
    descriptors = tuple(
        selected[arm_id].descriptor for arm_id in plan.arm_order.resolved_arm_order
    )
    authorization = FormalExecutionAuthorization.create(
        execution_id=execution_id,
        mode=mode,
        plan=plan,
        readiness_bundle=production_readiness,
        provider_descriptors=descriptors,
    )

    artifacts: list[FormalArmCaseArtifact] = []
    stage_cost_ledger = plan.stage_cost_pre_ledger
    stage_stopped = stage_cost_ledger.phase_decision("pilot").stopped
    retained_receipt_hashes: set[str] = set()
    retained_invocation_ids: set[str] = set()
    execution_index = 0
    budget_hash = plan.budget_policy.contract_hash
    for case_input in plan.cases:
        for arm_id in plan.arm_order.resolved_arm_order:
            provider = selected[arm_id]
            request = FormalArmRequest(
                authorization_hash=authorization.authorization_hash,
                execution_index=execution_index,
                case=case_input.case,
                arm_id=arm_id,
                task_hash=case_input.task_hash,
                episode_hash=case_input.episode_hash,
                failure_policy_hash=case_input.failure_policy_hash,
                semantic_leaf_count=case_input.semantic_leaf_count,
                measurement_count=case_input.measurement_count,
                budget_policy_hash=budget_hash,
                price_manifest_hash=plan.price_manifest.contract_hash,
                stage_budget_manifest_hash=(plan.stage_budget_manifest.contract_hash),
                stage_cost_pre_ledger_hash=(plan.stage_cost_pre_ledger.contract_hash),
            )
            execution_index += 1
            if stage_stopped:
                artifacts.append(
                    _failure_artifact(
                        request=request,
                        backend_id=provider.descriptor.provider_id,
                        code=FailureCode.STAGE_BUDGET_EXHAUSTED,
                        message=(
                            "provider was not called after the frozen stage "
                            "budget stopped execution"
                        ),
                        validity=ResultValidity.VALID,
                        automatic_status=EvaluationStatus.UNKNOWN,
                    )
                )
                continue
            try:
                execution = provider.execute(request)
            except FormalBackendExecutionError as error:
                evidence = error.evidence
                transport_error = _judge_transport_binding_error(
                    request,
                    evidence,
                    expected_provider_id=provider.descriptor.provider_id,
                )
                if (
                    evidence.authorization_hash != request.authorization_hash
                    or evidence.case_id != request.case.case_id
                    or evidence.arm_id != request.arm_id
                ):
                    transport_error = (
                        "failed backend evidence identity does not match request"
                    )
                candidate_receipt_hashes = {
                    item.transport_receipt.contract_hash
                    for item in evidence.judge_call_costs
                }
                candidate_invocation_ids = {
                    item.transport_receipt.payload.invocation_id
                    for item in evidence.judge_call_costs
                }
                if transport_error is None and (
                    retained_receipt_hashes & candidate_receipt_hashes
                    or retained_invocation_ids & candidate_invocation_ids
                ):
                    transport_error = "Judge transport evidence contains a duplicate"
                stage_cost_entry_hashes: tuple[str, ...] = ()
                if transport_error is None:
                    stage_cost_ledger, stage_cost_entry_hashes = _append_judge_attempts(
                        ledger=stage_cost_ledger,
                        request=request,
                        execution=evidence,
                        provider_id=provider.descriptor.provider_id,
                    )
                    retained_receipt_hashes.update(candidate_receipt_hashes)
                    retained_invocation_ids.update(candidate_invocation_ids)
                    stage_stopped = stage_cost_ledger.phase_decision("pilot").stopped
                failure_code = (
                    error.code
                    if transport_error is None
                    else FailureCode.MALFORMED_RESPONSE
                )
                validity, automatic_status = _FAILURE_DISPOSITIONS[failure_code]
                artifacts.append(
                    _failure_artifact(
                        request=request,
                        backend_id=provider.descriptor.provider_id,
                        code=failure_code,
                        message=transport_error or str(error),
                        validity=validity,
                        automatic_status=automatic_status,
                        cost=evidence.cost,
                        judge_call_costs=evidence.judge_call_costs,
                        stage_cost_entry_hashes=stage_cost_entry_hashes,
                    )
                )
                continue
            except TimeoutError as error:
                artifacts.append(
                    _failure_artifact(
                        request=request,
                        backend_id=provider.descriptor.provider_id,
                        code=FailureCode.TIMEOUT,
                        message=str(error) or "backend timeout",
                        validity=ResultValidity.VALID,
                        automatic_status=EvaluationStatus.UNKNOWN,
                        cost=_empty_cost(accounting_complete=False),
                    )
                )
                continue
            except Exception as error:
                artifacts.append(
                    _failure_artifact(
                        request=request,
                        backend_id=provider.descriptor.provider_id,
                        code=FailureCode.PROVIDER_ERROR,
                        message=(
                            f"{type(error).__name__}: {error}"
                            if str(error)
                            else type(error).__name__
                        ),
                        validity=ResultValidity.INVALID,
                        automatic_status=EvaluationStatus.INVALID,
                        cost=_empty_cost(accounting_complete=False),
                    )
                )
                continue
            if not isinstance(execution, BackendExecution):
                artifacts.append(
                    _failure_artifact(
                        request=request,
                        backend_id=provider.descriptor.provider_id,
                        code=FailureCode.MALFORMED_RESPONSE,
                        message="backend did not return BackendExecution",
                        validity=ResultValidity.INVALID,
                        automatic_status=EvaluationStatus.INVALID,
                        cost=_empty_cost(accounting_complete=False),
                    )
                )
                continue
            transport_error = _judge_transport_binding_error(
                request,
                execution,
                expected_provider_id=provider.descriptor.provider_id,
            )
            candidate_receipt_hashes = {
                item.transport_receipt.contract_hash
                for item in execution.judge_call_costs
            }
            candidate_invocation_ids = {
                item.transport_receipt.payload.invocation_id
                for item in execution.judge_call_costs
            }
            if transport_error is None and (
                retained_receipt_hashes & candidate_receipt_hashes
                or retained_invocation_ids & candidate_invocation_ids
            ):
                transport_error = "Judge transport evidence contains a duplicate"
            stage_cost_entry_hashes: tuple[str, ...] = ()
            if transport_error is None:
                stage_cost_ledger, stage_cost_entry_hashes = _append_judge_attempts(
                    ledger=stage_cost_ledger,
                    request=request,
                    execution=execution,
                    provider_id=provider.descriptor.provider_id,
                )
                retained_receipt_hashes.update(candidate_receipt_hashes)
                retained_invocation_ids.update(candidate_invocation_ids)
                stage_stopped = stage_cost_ledger.phase_decision("pilot").stopped
            binding_error = _binding_error(
                request,
                execution,
                require_canonical=(provider.descriptor.mode is BackendMode.PRODUCTION),
                expected_provider_id=provider.descriptor.provider_id,
            )
            if binding_error is not None:
                artifacts.append(
                    _failure_artifact(
                        request=request,
                        backend_id=provider.descriptor.provider_id,
                        code=FailureCode.MALFORMED_RESPONSE,
                        message=binding_error,
                        validity=ResultValidity.INVALID,
                        automatic_status=EvaluationStatus.INVALID,
                        observations=execution.observations,
                        raw_result=execution.raw_result,
                        cost=execution.cost,
                        judge_call_costs=execution.judge_call_costs,
                        stage_cost_entry_hashes=stage_cost_entry_hashes,
                        canonical_evaluation=execution.canonical_evaluation,
                    )
                )
                continue
            budget_error = _per_case_budget_violation(
                request,
                execution,
                plan.budget_policy,
            )
            if budget_error is not None:
                failure_code, failure_message = budget_error
                validity = (
                    ResultValidity.INVALID
                    if failure_code is FailureCode.PROTOCOL_VIOLATION
                    else ResultValidity.VALID
                )
                automatic_status = (
                    EvaluationStatus.INVALID
                    if validity is ResultValidity.INVALID
                    else plan.budget_policy.exhaustion_status
                )
                artifacts.append(
                    _failure_artifact(
                        request=request,
                        backend_id=provider.descriptor.provider_id,
                        code=failure_code,
                        message=failure_message,
                        validity=validity,
                        automatic_status=automatic_status,
                        observations=execution.observations,
                        raw_result=execution.raw_result,
                        cost=execution.cost,
                        judge_call_costs=execution.judge_call_costs,
                        stage_cost_entry_hashes=stage_cost_entry_hashes,
                        canonical_evaluation=execution.canonical_evaluation,
                    )
                )
                continue
            if stage_stopped:
                artifacts.append(
                    _failure_artifact(
                        request=request,
                        backend_id=provider.descriptor.provider_id,
                        code=FailureCode.STAGE_BUDGET_EXHAUSTED,
                        message="frozen Pilot stage budget exceeded",
                        validity=ResultValidity.VALID,
                        automatic_status=plan.budget_policy.exhaustion_status,
                        observations=execution.observations,
                        raw_result=execution.raw_result,
                        cost=execution.cost,
                        judge_call_costs=execution.judge_call_costs,
                        stage_cost_entry_hashes=stage_cost_entry_hashes,
                        canonical_evaluation=execution.canonical_evaluation,
                    )
                )
                continue
            artifacts.append(
                _success_artifact(
                    request,
                    provider.descriptor.provider_id,
                    execution,
                    stage_cost_entry_hashes,
                )
            )

    return FormalContractRun(
        runner_version=FORMAL_RUNNER_VERSION,
        claim_scope=CLAIM_SCOPE,
        formal_result=(authorization.mode is BackendMode.PRODUCTION),
        authorization=authorization,
        provider_descriptors=descriptors,
        artifacts=tuple(artifacts),
        stage_cost_pre_ledger=plan.stage_cost_pre_ledger,
        stage_cost_final_ledger=stage_cost_ledger,
        stage_stopped=stage_stopped,
        _derivation_token=_FORMAL_RUN_DERIVATION_TOKEN,
    )


__all__ = [
    "CLAIM_SCOPE",
    "FORMAL_RUNNER_VERSION",
    "BackendExecution",
    "BackendFailureEvidence",
    "BackendMode",
    "CanonicalEvaluationBinding",
    "FailureCode",
    "FormalArmCaseArtifact",
    "FormalArmProvider",
    "FormalArmRequest",
    "FormalBackendDescriptor",
    "FormalBackendExecutionError",
    "FormalContractRun",
    "FormalCostArtifact",
    "FormalExecutionAuthorization",
    "FormalFailureArtifact",
    "FormalPilotCaseInput",
    "FormalPilotPlan",
    "FormalRunnerError",
    "FormalRunnerProtocolGap",
    "JudgeCallCostArtifact",
    "RawObservationArtifact",
    "RawResultArtifact",
    "ResultValidity",
    "run_formal_contract",
    "validate_production_backends",
]
