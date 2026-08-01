"""Typed P0-C retained-failure evidence for deterministic V3 tests.

These objects prove only that an approved failure code has the exact typed
diagnostic evidence required by the offline retained-failure projection.  They
do not authorize production execution, create a task verdict, or turn a
terminal reason into a detection measurand.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, ClassVar

from .meas0_budget import BudgetFailureArtifact, BudgetFailureCode, BudgetScope
from .meas0_formal_runner import (
    FailureCode,
    FormalArmRequest,
    FormalFailureArtifact,
    JudgeCallCostArtifact,
)
from .meas0_stage_cost import CostOutcome, StageCostEntry, StageCostLedger
from .meas0_trust import TransportOutcome


FAILURE_EVIDENCE_SCHEMA_V3 = "meas0.retained-failure-evidence.v3"


class FailureEvidenceV3Error(ValueError):
    """Typed failure evidence is incomplete, mixed, or self-inconsistent."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise FailureEvidenceV3Error(
            "failure evidence is not canonical JSON"
        ) from error


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _bytes_hash(value: object, label: str) -> tuple[str, int]:
    if not isinstance(value, bytes) or not value:
        raise FailureEvidenceV3Error(f"{label} must be non-empty bytes")
    return hashlib.sha256(value).hexdigest(), len(value)


def _digest(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise FailureEvidenceV3Error(f"{label} must be a lowercase SHA-256")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FailureEvidenceV3Error(f"{label} must be non-empty text")
    return value


def _require_exact(value: object, expected: dict[str, object]) -> None:
    if not isinstance(value, dict) or set(value) != set(expected) or value != expected:
        raise FailureEvidenceV3Error(
            "serialized failure evidence differs from typed-source derivation"
        )


def _identity(
    request: FormalArmRequest,
    failure: FormalFailureArtifact,
    expected_code: FailureCode,
) -> dict[str, object]:
    if not isinstance(request, FormalArmRequest):
        raise FailureEvidenceV3Error(
            "failure evidence requires one typed FormalArmRequest"
        )
    if (
        not isinstance(failure, FormalFailureArtifact)
        or failure.code is not expected_code
    ):
        raise FailureEvidenceV3Error(
            f"failure evidence requires exact {expected_code.value} artifact"
        )
    return {
        "schema": FAILURE_EVIDENCE_SCHEMA_V3,
        "tag": expected_code.value,
        "failure_code": expected_code,
        "request_hash": request.request_hash,
        "authorization_hash": request.authorization_hash,
        "case_id": request.case.case_id,
        "task_id": request.case.task_id,
        "arm_id": request.arm_id,
        "failure_artifact_hash": _canonical_hash(failure.to_dict()),
    }


def attempt_binding_hash(
    judge_attempt: JudgeCallCostArtifact,
    stage_cost_entry: StageCostEntry,
) -> str:
    """Bind one real receipt-bearing attempt to its retained StageCost entry."""

    if not isinstance(judge_attempt, JudgeCallCostArtifact):
        raise FailureEvidenceV3Error("attempt binding requires typed Judge evidence")
    if not isinstance(stage_cost_entry, StageCostEntry):
        raise FailureEvidenceV3Error("attempt binding requires typed StageCost entry")
    receipt = judge_attempt.transport_receipt
    if (
        stage_cost_entry.raw_receipt_hash != receipt.contract_hash
        or stage_cost_entry.call_hash != receipt.payload.contract_hash
        or stage_cost_entry.request_hash == ""
    ):
        raise FailureEvidenceV3Error("attempt receipt and StageCost ancestry disagree")
    return _canonical_hash(
        {
            "receipt_hash": receipt.contract_hash,
            "stage_cost_entry_hash": stage_cost_entry.contract_hash,
        }
    )


_EVIDENCE_TOKEN = object()


@dataclass(frozen=True, kw_only=True)
class _FailureEvidenceBase:
    schema: str
    tag: str
    failure_code: FailureCode
    request_hash: str
    authorization_hash: str
    case_id: str
    task_id: str
    arm_id: str
    failure_artifact_hash: str
    no_attempt: bool
    attempt_binding_hashes: tuple[str, ...]
    terminal_reason_is_detection: bool
    claim_scope: str
    production_authorized: bool
    test_only: bool
    evidence_hash: str
    _request_source: object = field(default=None, repr=False, compare=False)
    _failure_source: object = field(default=None, repr=False, compare=False)
    _factory_token: object = field(default=None, repr=False, compare=False)

    EXPECTED_CODE: ClassVar[FailureCode]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "attempt_binding_hashes", tuple(self.attempt_binding_hashes)
        )
        if (
            self._factory_token is not _EVIDENCE_TOKEN
            or self.schema != FAILURE_EVIDENCE_SCHEMA_V3
            or self.tag != self.EXPECTED_CODE.value
            or self.failure_code is not self.EXPECTED_CODE
        ):
            raise FailureEvidenceV3Error(
                "failure evidence must be factory-derived with an exact tag"
            )
        if (
            not isinstance(self._request_source, FormalArmRequest)
            or not isinstance(self._failure_source, FormalFailureArtifact)
            or _identity(
                self._request_source,
                self._failure_source,
                self.EXPECTED_CODE,
            )
            != {
                "schema": self.schema,
                "tag": self.tag,
                "failure_code": self.failure_code,
                "request_hash": self.request_hash,
                "authorization_hash": self.authorization_hash,
                "case_id": self.case_id,
                "task_id": self.task_id,
                "arm_id": self.arm_id,
                "failure_artifact_hash": self.failure_artifact_hash,
            }
        ):
            raise FailureEvidenceV3Error(
                "failure evidence typed request/failure sources changed"
            )
        for value, label in (
            (self.request_hash, "request hash"),
            (self.authorization_hash, "authorization hash"),
            (self.failure_artifact_hash, "failure artifact hash"),
            (self.evidence_hash, "failure evidence hash"),
        ):
            _digest(value, label)
        for value in self.attempt_binding_hashes:
            _digest(value, "attempt binding hash")
        for value, label in (
            (self.case_id, "case_id"),
            (self.task_id, "task_id"),
            (self.arm_id, "arm_id"),
        ):
            _text(value, label)
        if (
            not isinstance(self.no_attempt, bool)
            or self.no_attempt != (not self.attempt_binding_hashes)
            or self.terminal_reason_is_detection is not False
            or self.claim_scope != "simulated_nonclaim"
            or self.production_authorized is not False
            or self.test_only is not True
        ):
            raise FailureEvidenceV3Error(
                "failure evidence crossed its attempt, detection, or claim boundary"
            )
        if self.evidence_hash != _canonical_hash(self._body()):
            raise FailureEvidenceV3Error("failure evidence hash mismatch")

    def _source_body(self) -> dict[str, object]:
        raise NotImplementedError

    def _body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "tag": self.tag,
            "failure_code": self.failure_code.value,
            "request_hash": self.request_hash,
            "authorization_hash": self.authorization_hash,
            "case_id": self.case_id,
            "task_id": self.task_id,
            "arm_id": self.arm_id,
            "failure_artifact_hash": self.failure_artifact_hash,
            "no_attempt": self.no_attempt,
            "attempt_binding_hashes": list(self.attempt_binding_hashes),
            "source_evidence": self._source_body(),
            "terminal_reason_is_detection": self.terminal_reason_is_detection,
            "claim_scope": self.claim_scope,
            "production_authorized": self.production_authorized,
            "test_only": self.test_only,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "evidence_hash": self.evidence_hash}


def _finish_body(
    identity: dict[str, object],
    *,
    attempt_hashes: tuple[str, ...],
    source_evidence: dict[str, object],
) -> dict[str, object]:
    return {
        **{
            key: value.value if isinstance(value, FailureCode) else value
            for key, value in identity.items()
        },
        "no_attempt": not attempt_hashes,
        "attempt_binding_hashes": list(attempt_hashes),
        "source_evidence": source_evidence,
        "terminal_reason_is_detection": False,
        "claim_scope": "simulated_nonclaim",
        "production_authorized": False,
        "test_only": True,
    }


@dataclass(frozen=True, kw_only=True)
class MalformedResponseEvidenceV3(_FailureEvidenceBase):
    raw_response_hash: str
    raw_response_size: int
    parser_id: str
    parser_version: str
    parser_error_code: str
    transport_receipt_hash: str
    stage_cost_entry_hash: str
    _judge_attempt_source: object = field(default=None, repr=False, compare=False)
    _stage_cost_entry_source: object = field(default=None, repr=False, compare=False)
    _raw_response_source: object = field(default=None, repr=False, compare=False)

    EXPECTED_CODE: ClassVar[FailureCode] = FailureCode.MALFORMED_RESPONSE

    def __post_init__(self) -> None:
        _digest(self.raw_response_hash, "raw response hash")
        _digest(self.transport_receipt_hash, "transport receipt hash")
        _digest(self.stage_cost_entry_hash, "StageCost entry hash")
        if (
            isinstance(self.raw_response_size, bool)
            or not isinstance(self.raw_response_size, int)
            or self.raw_response_size <= 0
        ):
            raise FailureEvidenceV3Error("raw response size must be positive")
        for value, label in (
            (self.parser_id, "parser_id"),
            (self.parser_version, "parser_version"),
            (self.parser_error_code, "parser_error_code"),
        ):
            _text(value, label)
        if (
            not isinstance(self._judge_attempt_source, JudgeCallCostArtifact)
            or not isinstance(self._stage_cost_entry_source, StageCostEntry)
            or not isinstance(self._raw_response_source, bytes)
            or _bytes_hash(self._raw_response_source, "raw response")
            != (self.raw_response_hash, self.raw_response_size)
            or self.transport_receipt_hash
            != self._judge_attempt_source.transport_receipt.contract_hash
            or self.stage_cost_entry_hash != self._stage_cost_entry_source.contract_hash
            or self.attempt_binding_hashes
            != (
                attempt_binding_hash(
                    self._judge_attempt_source,
                    self._stage_cost_entry_source,
                ),
            )
            or self._judge_attempt_source.transport_receipt.payload.outcome
            is not TransportOutcome.SUCCESS
            or not self._judge_attempt_source.transport_receipt.payload.response_present
            or self._judge_attempt_source.transport_receipt.payload.response_hash
            != self.raw_response_hash
            or self._judge_attempt_source.transport_receipt.payload.response_size
            != self.raw_response_size
            or self._stage_cost_entry_source.outcome is not CostOutcome.SUCCEEDED
            or self._stage_cost_entry_source.failure_code is not None
        ):
            raise FailureEvidenceV3Error(
                "malformed-response typed source evidence changed"
            )
        super().__post_init__()

    def _source_body(self) -> dict[str, object]:
        return {
            "raw_response_hash": self.raw_response_hash,
            "raw_response_size": self.raw_response_size,
            "parser_id": self.parser_id,
            "parser_version": self.parser_version,
            "parser_error_code": self.parser_error_code,
            "transport_receipt_hash": self.transport_receipt_hash,
            "stage_cost_entry_hash": self.stage_cost_entry_hash,
        }

    @classmethod
    def create(
        cls,
        *,
        request: FormalArmRequest,
        failure: FormalFailureArtifact,
        judge_attempt: JudgeCallCostArtifact,
        stage_cost_entry: StageCostEntry,
        raw_response: bytes,
        parser_id: str,
        parser_version: str,
        parser_error_code: str,
    ) -> MalformedResponseEvidenceV3:
        identity = _identity(request, failure, cls.EXPECTED_CODE)
        if stage_cost_entry.request_hash != request.request_hash:
            raise FailureEvidenceV3Error(
                "malformed-response StageCost does not bind the request"
            )
        raw_hash, raw_size = _bytes_hash(raw_response, "raw response")
        payload = judge_attempt.transport_receipt.payload
        if (
            payload.outcome is not TransportOutcome.SUCCESS
            or not payload.response_present
            or payload.response_hash != raw_hash
            or payload.response_size != raw_size
            or stage_cost_entry.outcome is not CostOutcome.SUCCEEDED
            or stage_cost_entry.failure_code is not None
        ):
            raise FailureEvidenceV3Error(
                "malformed response requires response-bearing transport success "
                "whose signed hash/size exactly match the parser bytes"
            )
        binding = attempt_binding_hash(judge_attempt, stage_cost_entry)
        receipt_hash = judge_attempt.transport_receipt.contract_hash
        source = {
            "raw_response_hash": raw_hash,
            "raw_response_size": raw_size,
            "parser_id": _text(parser_id, "parser_id"),
            "parser_version": _text(parser_version, "parser_version"),
            "parser_error_code": _text(parser_error_code, "parser_error_code"),
            "transport_receipt_hash": receipt_hash,
            "stage_cost_entry_hash": stage_cost_entry.contract_hash,
        }
        body = _finish_body(
            identity,
            attempt_hashes=(binding,),
            source_evidence=source,
        )
        return cls(
            **identity,
            no_attempt=False,
            attempt_binding_hashes=(binding,),
            terminal_reason_is_detection=False,
            claim_scope="simulated_nonclaim",
            production_authorized=False,
            test_only=True,
            **source,
            evidence_hash=_canonical_hash(body),
            _request_source=request,
            _failure_source=failure,
            _judge_attempt_source=judge_attempt,
            _stage_cost_entry_source=stage_cost_entry,
            _raw_response_source=raw_response,
            _factory_token=_EVIDENCE_TOKEN,
        )

    @classmethod
    def restore_from_typed_sources(
        cls,
        value: object,
        **typed_sources: object,
    ) -> MalformedResponseEvidenceV3:
        restored = cls.create(**typed_sources)
        _require_exact(value, restored.to_dict())
        return restored


@dataclass(frozen=True, kw_only=True)
class BudgetExhaustedEvidenceV3(_FailureEvidenceBase):
    budget_failure: BudgetFailureArtifact
    budget_failure_hash: str

    EXPECTED_CODE: ClassVar[FailureCode] = FailureCode.BUDGET_EXHAUSTED

    def __post_init__(self) -> None:
        if not isinstance(self.budget_failure, BudgetFailureArtifact):
            raise FailureEvidenceV3Error(
                "budget exhaustion requires typed BudgetFailureArtifact"
            )
        _digest(self.budget_failure_hash, "budget failure hash")
        if (
            self.budget_failure.code is not BudgetFailureCode.BUDGET_EXHAUSTED
            or self.budget_failure.scope is not BudgetScope.ARM_CASE
            or self.budget_failure.observed <= self.budget_failure.limit
            or self.budget_failure_hash
            != _canonical_hash(self.budget_failure.to_dict())
        ):
            raise FailureEvidenceV3Error(
                "budget failure does not prove arm-case exhaustion"
            )
        super().__post_init__()

    def _source_body(self) -> dict[str, object]:
        return {
            "budget_failure": self.budget_failure.to_dict(),
            "budget_failure_hash": self.budget_failure_hash,
        }

    @classmethod
    def create(
        cls,
        *,
        request: FormalArmRequest,
        failure: FormalFailureArtifact,
        budget_failure: BudgetFailureArtifact,
    ) -> BudgetExhaustedEvidenceV3:
        identity = _identity(request, failure, cls.EXPECTED_CODE)
        if not isinstance(budget_failure, BudgetFailureArtifact) or (
            budget_failure.case_id,
            budget_failure.task_id,
            budget_failure.arm.value,
        ) != (request.case.case_id, request.case.task_id, request.arm_id):
            raise FailureEvidenceV3Error(
                "budget failure case/task/arm ancestry changed"
            )
        budget_hash = _canonical_hash(budget_failure.to_dict())
        source = {
            "budget_failure": budget_failure.to_dict(),
            "budget_failure_hash": budget_hash,
        }
        body = _finish_body(identity, attempt_hashes=(), source_evidence=source)
        return cls(
            **identity,
            no_attempt=True,
            attempt_binding_hashes=(),
            terminal_reason_is_detection=False,
            claim_scope="simulated_nonclaim",
            production_authorized=False,
            test_only=True,
            budget_failure=budget_failure,
            budget_failure_hash=budget_hash,
            evidence_hash=_canonical_hash(body),
            _request_source=request,
            _failure_source=failure,
            _factory_token=_EVIDENCE_TOKEN,
        )

    @classmethod
    def restore_from_typed_sources(
        cls,
        value: object,
        **typed_sources: object,
    ) -> BudgetExhaustedEvidenceV3:
        restored = cls.create(**typed_sources)
        _require_exact(value, restored.to_dict())
        return restored


@dataclass(frozen=True, kw_only=True)
class StageBudgetExhaustedEvidenceV3(_FailureEvidenceBase):
    stage_cost_ledger_hash: str
    phase: str
    trigger_entry_hash: str
    exceeded_dimensions: tuple[str, ...]
    _stage_cost_ledger_source: object = field(default=None, repr=False, compare=False)

    EXPECTED_CODE: ClassVar[FailureCode] = FailureCode.STAGE_BUDGET_EXHAUSTED

    def __post_init__(self) -> None:
        object.__setattr__(self, "exceeded_dimensions", tuple(self.exceeded_dimensions))
        _digest(self.stage_cost_ledger_hash, "StageCost ledger hash")
        _digest(self.trigger_entry_hash, "stage budget trigger hash")
        _text(self.phase, "phase")
        if not self.exceeded_dimensions:
            raise FailureEvidenceV3Error(
                "stage exhaustion requires exceeded dimensions"
            )
        for value in self.exceeded_dimensions:
            _text(value, "exceeded dimension")
        if not isinstance(self._stage_cost_ledger_source, StageCostLedger):
            raise FailureEvidenceV3Error("stage exhaustion typed ledger source changed")
        decision = self._stage_cost_ledger_source.phase_decision(self.phase)
        if (
            self.stage_cost_ledger_hash != self._stage_cost_ledger_source.contract_hash
            or not decision.stopped
            or decision.trigger_entry_hash != self.trigger_entry_hash
            or decision.exceeded_dimensions != self.exceeded_dimensions
        ):
            raise FailureEvidenceV3Error(
                "stage exhaustion typed ledger derivation changed"
            )
        super().__post_init__()

    def _source_body(self) -> dict[str, object]:
        return {
            "stage_cost_ledger_hash": self.stage_cost_ledger_hash,
            "phase": self.phase,
            "trigger_entry_hash": self.trigger_entry_hash,
            "exceeded_dimensions": list(self.exceeded_dimensions),
        }

    @classmethod
    def create(
        cls,
        *,
        request: FormalArmRequest,
        failure: FormalFailureArtifact,
        stage_cost_ledger: StageCostLedger,
    ) -> StageBudgetExhaustedEvidenceV3:
        identity = _identity(request, failure, cls.EXPECTED_CODE)
        if not isinstance(stage_cost_ledger, StageCostLedger):
            raise FailureEvidenceV3Error(
                "stage exhaustion requires typed StageCost ledger"
            )
        if request.stage_cost_pre_ledger_hash != stage_cost_ledger.contract_hash:
            raise FailureEvidenceV3Error(
                "stage exhaustion ledger is not the request pre-ledger"
            )
        decision = stage_cost_ledger.phase_decision(request.case.phase)
        if (
            not decision.stopped
            or decision.trigger_entry_hash is None
            or not decision.exceeded_dimensions
        ):
            raise FailureEvidenceV3Error(
                "StageCost ledger does not prove a stopped stage"
            )
        source = {
            "stage_cost_ledger_hash": stage_cost_ledger.contract_hash,
            "phase": decision.phase,
            "trigger_entry_hash": decision.trigger_entry_hash,
            "exceeded_dimensions": list(decision.exceeded_dimensions),
        }
        body = _finish_body(identity, attempt_hashes=(), source_evidence=source)
        return cls(
            **identity,
            no_attempt=True,
            attempt_binding_hashes=(),
            terminal_reason_is_detection=False,
            claim_scope="simulated_nonclaim",
            production_authorized=False,
            test_only=True,
            stage_cost_ledger_hash=stage_cost_ledger.contract_hash,
            phase=decision.phase,
            trigger_entry_hash=decision.trigger_entry_hash,
            exceeded_dimensions=decision.exceeded_dimensions,
            evidence_hash=_canonical_hash(body),
            _request_source=request,
            _failure_source=failure,
            _stage_cost_ledger_source=stage_cost_ledger,
            _factory_token=_EVIDENCE_TOKEN,
        )

    @classmethod
    def restore_from_typed_sources(
        cls,
        value: object,
        **typed_sources: object,
    ) -> StageBudgetExhaustedEvidenceV3:
        restored = cls.create(**typed_sources)
        _require_exact(value, restored.to_dict())
        return restored


_BACKEND_SURFACES = frozenset(
    {"backend_descriptor", "bundle_schema", "evaluator_schema"}
)
_PROTOCOL_INVARIANTS = frozenset({"request_ancestry", "bundle_hash"})


@dataclass(frozen=True, kw_only=True)
class BackendInvalidEvidenceV3(_FailureEvidenceBase):
    invalid_surface: str
    expected_contract_hash: str
    observed_artifact_hash: str
    observed_artifact_size: int
    _observed_artifact_source: object = field(default=None, repr=False, compare=False)

    EXPECTED_CODE: ClassVar[FailureCode] = FailureCode.BACKEND_INVALID

    def __post_init__(self) -> None:
        if self.invalid_surface not in _BACKEND_SURFACES:
            raise FailureEvidenceV3Error("backend invalid surface is not approved")
        _digest(self.expected_contract_hash, "expected backend contract hash")
        _digest(self.observed_artifact_hash, "observed backend artifact hash")
        if (
            self.expected_contract_hash == self.observed_artifact_hash
            or isinstance(self.observed_artifact_size, bool)
            or not isinstance(self.observed_artifact_size, int)
            or self.observed_artifact_size <= 0
        ):
            raise FailureEvidenceV3Error(
                "backend evidence does not prove incompatibility"
            )
        if not isinstance(self._observed_artifact_source, bytes) or _bytes_hash(
            self._observed_artifact_source,
            "observed backend artifact",
        ) != (self.observed_artifact_hash, self.observed_artifact_size):
            raise FailureEvidenceV3Error("backend typed artifact source changed")
        super().__post_init__()

    def _source_body(self) -> dict[str, object]:
        return {
            "invalid_surface": self.invalid_surface,
            "expected_contract_hash": self.expected_contract_hash,
            "observed_artifact_hash": self.observed_artifact_hash,
            "observed_artifact_size": self.observed_artifact_size,
        }

    @classmethod
    def create(
        cls,
        *,
        request: FormalArmRequest,
        failure: FormalFailureArtifact,
        invalid_surface: str,
        expected_contract_hash: str,
        observed_artifact: bytes,
    ) -> BackendInvalidEvidenceV3:
        _identity(request, failure, cls.EXPECTED_CODE)
        raise FailureEvidenceV3Error(
            "backend invalid evidence schema gap: FormalArmRequest carries no "
            "request/plan-bound authoritative backend descriptor hash"
        )

    @classmethod
    def restore_from_typed_sources(
        cls,
        value: object,
        **typed_sources: object,
    ) -> BackendInvalidEvidenceV3:
        restored = cls.create(**typed_sources)
        _require_exact(value, restored.to_dict())
        return restored


@dataclass(frozen=True, kw_only=True)
class ProtocolViolationEvidenceV3(_FailureEvidenceBase):
    violated_invariant: str
    expected_contract_hash: str
    offending_artifact_hash: str
    offending_artifact_size: int
    _offending_artifact_source: object = field(default=None, repr=False, compare=False)

    EXPECTED_CODE: ClassVar[FailureCode] = FailureCode.PROTOCOL_VIOLATION

    def __post_init__(self) -> None:
        if self.violated_invariant not in _PROTOCOL_INVARIANTS:
            raise FailureEvidenceV3Error("protocol invariant is not approved")
        if not isinstance(self._request_source, FormalArmRequest):
            raise FailureEvidenceV3Error(
                "protocol expected authority requires typed request source"
            )
        derived_expected = {
            "request_ancestry": self._request_source.request_hash,
            "bundle_hash": self._request_source.task_hash,
        }[self.violated_invariant]
        _digest(self.expected_contract_hash, "expected protocol contract hash")
        _digest(self.offending_artifact_hash, "offending artifact hash")
        if (
            self.expected_contract_hash != derived_expected
            or self.expected_contract_hash == self.offending_artifact_hash
            or isinstance(self.offending_artifact_size, bool)
            or not isinstance(self.offending_artifact_size, int)
            or self.offending_artifact_size <= 0
        ):
            raise FailureEvidenceV3Error(
                "protocol evidence does not prove an invariant mismatch"
            )
        if not isinstance(self._offending_artifact_source, FormalArmRequest):
            raise FailureEvidenceV3Error("protocol typed request source changed")
        observed_value = {
            "request_ancestry": self._offending_artifact_source.request_hash,
            "bundle_hash": self._offending_artifact_source.task_hash,
        }[self.violated_invariant]
        serialized = _canonical_bytes(self._offending_artifact_source.to_dict())
        if (
            self.offending_artifact_hash != observed_value
            or self.offending_artifact_size != len(serialized)
        ):
            raise FailureEvidenceV3Error("protocol typed request derivation changed")
        super().__post_init__()

    def _source_body(self) -> dict[str, object]:
        return {
            "violated_invariant": self.violated_invariant,
            "expected_contract_hash": self.expected_contract_hash,
            "offending_artifact_hash": self.offending_artifact_hash,
            "offending_artifact_size": self.offending_artifact_size,
        }

    @classmethod
    def create(
        cls,
        *,
        request: FormalArmRequest,
        failure: FormalFailureArtifact,
        violated_invariant: str,
        observed_request: FormalArmRequest,
    ) -> ProtocolViolationEvidenceV3:
        identity = _identity(request, failure, cls.EXPECTED_CODE)
        if violated_invariant not in _PROTOCOL_INVARIANTS:
            raise FailureEvidenceV3Error(
                "protocol invariant has no request-bound typed expected authority"
            )
        expected = {
            "request_ancestry": request.request_hash,
            "bundle_hash": request.task_hash,
        }[violated_invariant]
        if not isinstance(observed_request, FormalArmRequest):
            raise FailureEvidenceV3Error(
                "protocol violation requires typed observed request"
            )
        observed_hash = {
            "request_ancestry": observed_request.request_hash,
            "bundle_hash": observed_request.task_hash,
        }[violated_invariant]
        observed_size = len(_canonical_bytes(observed_request.to_dict()))
        source = {
            "violated_invariant": violated_invariant,
            "expected_contract_hash": expected,
            "offending_artifact_hash": observed_hash,
            "offending_artifact_size": observed_size,
        }
        body = _finish_body(identity, attempt_hashes=(), source_evidence=source)
        return cls(
            **identity,
            no_attempt=True,
            attempt_binding_hashes=(),
            terminal_reason_is_detection=False,
            claim_scope="simulated_nonclaim",
            production_authorized=False,
            test_only=True,
            **source,
            evidence_hash=_canonical_hash(body),
            _request_source=request,
            _failure_source=failure,
            _offending_artifact_source=observed_request,
            _factory_token=_EVIDENCE_TOKEN,
        )

    @classmethod
    def restore_from_typed_sources(
        cls,
        value: object,
        **typed_sources: object,
    ) -> ProtocolViolationEvidenceV3:
        restored = cls.create(**typed_sources)
        _require_exact(value, restored.to_dict())
        return restored


FailureEvidenceV3 = (
    MalformedResponseEvidenceV3
    | BudgetExhaustedEvidenceV3
    | StageBudgetExhaustedEvidenceV3
    | BackendInvalidEvidenceV3
    | ProtocolViolationEvidenceV3
)

FAILURE_EVIDENCE_TYPES_V3 = (
    MalformedResponseEvidenceV3,
    BudgetExhaustedEvidenceV3,
    StageBudgetExhaustedEvidenceV3,
    BackendInvalidEvidenceV3,
    ProtocolViolationEvidenceV3,
)


__all__ = [
    "BackendInvalidEvidenceV3",
    "BudgetExhaustedEvidenceV3",
    "FAILURE_EVIDENCE_SCHEMA_V3",
    "FAILURE_EVIDENCE_TYPES_V3",
    "FailureEvidenceV3",
    "FailureEvidenceV3Error",
    "MalformedResponseEvidenceV3",
    "ProtocolViolationEvidenceV3",
    "StageBudgetExhaustedEvidenceV3",
    "attempt_binding_hash",
]
