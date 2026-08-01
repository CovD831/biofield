"""V3 retained-failure projections for non-claim-bearing contract tests.

The existing runner artifact cannot represent the approved D8
``INVALID/null`` projection because its ``automatic_status`` is non-optional.
This module therefore derives an independent tagged outcome and treats any
legacy artifact status as migration/audit input, never as projection authority.

Receipt-bearing failures require a typed Judge attempt, signed transport
receipt, and StageCost entry for every retained attempt.  The five P0-C
non-transport conditions instead require their exact tagged V3 evidence.
Legitimate pre-call failures are represented as no-attempt evidence with an
unchanged StageCost ledger; they never fabricate a receipt or a zero-cost call.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .measurement import EvaluationStatus
from .meas0_failure_evidence_v3 import (
    FAILURE_EVIDENCE_TYPES_V3,
    FailureEvidenceV3,
    attempt_binding_hash,
)
from .meas0_formal_metrics import FormalCaseIdentity
from .meas0_formal_runner import (
    FailureCode,
    FormalArmRequest,
    FormalFailureArtifact,
    JudgeCallCostArtifact,
    ResultValidity,
)
from .meas0_input_manifest import FailureDisposition, FailurePolicyContract
from .meas0_stage_cost import (
    CostCategory,
    CostOutcome,
    FORMAL_ARM_IDS,
    StageCostEntry,
    StageCostLedger,
)
from .meas0_trust import TransportOutcome


RETAINED_FAILURE_SCHEMA = "meas0.retained-failure-outcome.v3"
RETAINED_FAILURE_ATTEMPT_SCHEMA = "meas0.retained-failure-attempt.v3"
LEGACY_FORMAL_ARTIFACT_INTEGRATION_GAP = (
    "FormalArmCaseArtifact automatic_status is non-optional; V3 INVALID/null "
    "must remain independently derived until runner integration."
)
NO_RECEIPT_FAILURE_INTEGRATION_GAP = (
    "A receipt-bearing retained failure requires typed Judge and StageCost "
    "attempt evidence; a no-attempt failure requires its exact tagged evidence."
)
REQUIRED_FAILURE_EVIDENCE_DESCRIPTIONS = {
    FailureCode.MALFORMED_RESPONSE: (
        "typed parser/malformed-response evidence is not carried by a failed "
        "transport attempt"
    ),
    FailureCode.BUDGET_EXHAUSTED: (
        "per-case budget exhaustion may follow successful or non-Judge work"
    ),
    FailureCode.STAGE_BUDGET_EXHAUSTED: (
        "stage budget exhaustion may stop execution before an attempt exists"
    ),
    FailureCode.BACKEND_INVALID: (
        "backend incompatibility requires typed bundle/schema/evaluator evidence"
    ),
    FailureCode.PROTOCOL_VIOLATION: (
        "protocol contamination requires typed integrity evidence"
    ),
}
# Kept for the confirmatory commitment-only layer, which does not yet carry the
# typed P0-C evidence object and must therefore continue to fail closed.
UNREPRESENTABLE_FAILURE_EVIDENCE_GAPS = REQUIRED_FAILURE_EVIDENCE_DESCRIPTIONS
_TRANSPORT_PROVABLE_CODES = frozenset({FailureCode.TIMEOUT, FailureCode.PROVIDER_ERROR})


class RetainedFailureError(ValueError):
    """Raised when retained-failure evidence is incomplete or inconsistent."""


def project_failure_disposition(
    failure_policy: FailurePolicyContract,
    failure_code: FailureCode,
) -> FailureDisposition:
    """Return the approved D8 projection without claiming evidence sufficiency."""

    if not isinstance(failure_policy, FailurePolicyContract):
        raise RetainedFailureError(
            "failure projection requires typed FailurePolicyContract"
        )
    if not isinstance(failure_code, FailureCode):
        raise RetainedFailureError("failure projection code is not approved")
    disposition = next(
        (
            item
            for item in failure_policy.dispositions
            if item.failure_code is failure_code
        ),
        None,
    )
    if disposition is None:
        raise RetainedFailureError("failure code is absent from approved policy")
    return disposition


def _canonical_hash(value: Any) -> str:
    try:
        payload = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise RetainedFailureError(
            "retained-failure value is not canonical JSON"
        ) from error
    return hashlib.sha256(payload).hexdigest()


def _digest(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RetainedFailureError(f"{label} must be a lowercase SHA-256")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RetainedFailureError(f"{label} must be a non-empty string")
    return value


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RetainedFailureError(f"{label} must be a non-negative integer")
    return value


def _require_exact_serialization(
    value: object,
    expected: dict[str, object],
    label: str,
) -> None:
    def exact(observed: object, wanted: object) -> bool:
        if type(observed) is not type(wanted):
            return False
        if isinstance(wanted, Mapping):
            return set(observed) == set(wanted) and all(
                exact(observed[key], wanted[key]) for key in wanted
            )
        if isinstance(wanted, list):
            return len(observed) == len(wanted) and all(
                exact(left, right) for left, right in zip(observed, wanted, strict=True)
            )
        return observed == wanted

    if not exact(value, expected):
        raise RetainedFailureError(
            f"{label} is not the exact serialization derived from typed sources"
        )


_ATTEMPT_TOKEN = object()


@dataclass(frozen=True)
class RetainedFailureAttempt:
    schema: str
    attempt_index: int
    judge_attempt: JudgeCallCostArtifact
    stage_cost_entry: StageCostEntry
    receipt_hash: str
    stage_cost_entry_hash: str
    retry_of_entry_hash: str | None
    attempt_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._factory_token is not _ATTEMPT_TOKEN
            or self.schema != RETAINED_FAILURE_ATTEMPT_SCHEMA
        ):
            raise RetainedFailureError(
                "retained failure attempt must be factory-derived"
            )
        _non_negative_int(self.attempt_index, "attempt index")
        if not isinstance(self.judge_attempt, JudgeCallCostArtifact):
            raise RetainedFailureError("retained failure requires typed Judge attempt")
        if not isinstance(self.stage_cost_entry, StageCostEntry):
            raise RetainedFailureError(
                "retained failure requires typed StageCost entry"
            )
        entry = self.stage_cost_entry
        receipt = self.judge_attempt.transport_receipt
        payload = receipt.payload
        expected_cost_outcome = (
            CostOutcome.SUCCEEDED
            if payload.outcome is TransportOutcome.SUCCESS
            else CostOutcome.FAILED
        )
        if (
            entry.category is not CostCategory.JUDGE
            or entry.outcome is not expected_cost_outcome
            or not entry.automatic_arm_execution
            or entry.failure_code != payload.failure_code
            or entry.call_hash != payload.contract_hash
            or entry.raw_receipt_hash != receipt.contract_hash
            or (
                entry.input_tokens,
                entry.output_tokens,
                entry.wall_time_ms,
                entry.bytes_transferred,
            )
            != (
                self.judge_attempt.input_tokens,
                self.judge_attempt.output_tokens,
                self.judge_attempt.wall_time_ms,
                payload.response_size or 0,
            )
            or entry.provider_id != payload.provider_id
            or entry.model_id != payload.observed_model_id
        ):
            raise RetainedFailureError(
                "Judge attempt, receipt, and StageCost evidence disagree"
            )
        _digest(self.receipt_hash, "attempt receipt hash")
        _digest(self.stage_cost_entry_hash, "attempt StageCost hash")
        if self.retry_of_entry_hash is not None:
            _digest(self.retry_of_entry_hash, "attempt retry parent hash")
        _digest(self.attempt_hash, "retained failure attempt hash")
        if (
            self.receipt_hash != receipt.contract_hash
            or self.stage_cost_entry_hash != entry.contract_hash
            or self.retry_of_entry_hash != entry.retry_of_entry_hash
            or self.attempt_hash != _canonical_hash(self._body())
        ):
            raise RetainedFailureError("retained failure attempt hash ancestry changed")

    def _body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "attempt_index": self.attempt_index,
            "judge_attempt": self.judge_attempt.to_dict(),
            "stage_cost_entry": self.stage_cost_entry.to_dict(),
            "receipt_hash": self.receipt_hash,
            "stage_cost_entry_hash": self.stage_cost_entry_hash,
            "retry_of_entry_hash": self.retry_of_entry_hash,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "attempt_hash": self.attempt_hash}

    @classmethod
    def create(
        cls,
        *,
        attempt_index: int,
        judge_attempt: JudgeCallCostArtifact,
        stage_cost_entry: StageCostEntry,
    ) -> RetainedFailureAttempt:
        if not isinstance(judge_attempt, JudgeCallCostArtifact):
            raise RetainedFailureError("retained failure requires typed Judge attempt")
        if not isinstance(stage_cost_entry, StageCostEntry):
            raise RetainedFailureError(
                "retained failure requires typed StageCost entry"
            )
        body = {
            "schema": RETAINED_FAILURE_ATTEMPT_SCHEMA,
            "attempt_index": attempt_index,
            "judge_attempt": judge_attempt.to_dict(),
            "stage_cost_entry": stage_cost_entry.to_dict(),
            "receipt_hash": judge_attempt.transport_receipt.contract_hash,
            "stage_cost_entry_hash": stage_cost_entry.contract_hash,
            "retry_of_entry_hash": stage_cost_entry.retry_of_entry_hash,
        }
        return cls(
            schema=RETAINED_FAILURE_ATTEMPT_SCHEMA,
            attempt_index=attempt_index,
            judge_attempt=judge_attempt,
            stage_cost_entry=stage_cost_entry,
            receipt_hash=judge_attempt.transport_receipt.contract_hash,
            stage_cost_entry_hash=stage_cost_entry.contract_hash,
            retry_of_entry_hash=stage_cost_entry.retry_of_entry_hash,
            attempt_hash=_canonical_hash(body),
            _factory_token=_ATTEMPT_TOKEN,
        )

    @classmethod
    def restore_from_typed_sources(
        cls,
        value: object,
        *,
        attempt_index: int,
        judge_attempt: JudgeCallCostArtifact,
        stage_cost_entry: StageCostEntry,
    ) -> RetainedFailureAttempt:
        """Re-derive an attempt from typed evidence and compare serialized bytes."""

        restored = cls.create(
            attempt_index=attempt_index,
            judge_attempt=judge_attempt,
            stage_cost_entry=stage_cost_entry,
        )
        _require_exact_serialization(
            value,
            restored.to_dict(),
            "retained failure attempt",
        )
        return restored


_OUTCOME_TOKEN = object()
_NOT_OBSERVED_FIELDS = ("accepted", "detected", "judge_verdict")


@dataclass(frozen=True)
class RetainedFailureOutcome:
    schema: str
    tag: str
    case: FormalCaseIdentity
    arm_id: str
    authorization_hash: str
    request_hash: str
    failure_code: FailureCode
    failure_artifact: FormalFailureArtifact
    failure_artifact_hash: str
    failure_evidence: FailureEvidenceV3 | None
    failure_evidence_hash: str | None
    failure_policy_hash: str
    result_validity: ResultValidity
    automatic_status: EvaluationStatus | None
    attempts: tuple[RetainedFailureAttempt, ...]
    receipt_hashes: tuple[str, ...]
    stage_cost_entry_hashes: tuple[str, ...]
    stage_cost_pre_ledger_hash: str
    stage_cost_ledger_hash: str
    retry_count: int
    terminal_reason: str
    terminal_reason_hash: str
    not_observed_fields: tuple[str, ...]
    accepted: None
    detected: None
    judge_verdict: None
    denominator_retained: bool
    claim_scope: str
    production_authorized: bool
    test_only: bool
    outcome_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempts", tuple(self.attempts))
        object.__setattr__(self, "receipt_hashes", tuple(self.receipt_hashes))
        object.__setattr__(
            self,
            "stage_cost_entry_hashes",
            tuple(self.stage_cost_entry_hashes),
        )
        object.__setattr__(
            self,
            "not_observed_fields",
            tuple(self.not_observed_fields),
        )
        if (
            self._factory_token is not _OUTCOME_TOKEN
            or self.schema != RETAINED_FAILURE_SCHEMA
            or self.tag != "retained_failure"
            or not isinstance(self.case, FormalCaseIdentity)
            or self.arm_id not in FORMAL_ARM_IDS
            or not isinstance(self.failure_code, FailureCode)
            or not isinstance(self.failure_artifact, FormalFailureArtifact)
            or not isinstance(self.result_validity, ResultValidity)
        ):
            raise RetainedFailureError(
                "retained failure outcome must be factory-derived and typed"
            )
        if (
            self.failure_artifact.code is not self.failure_code
            or self.failure_artifact_hash
            != _canonical_hash(self.failure_artifact.to_dict())
        ):
            raise RetainedFailureError("retained failure artifact binding changed")
        if self.failure_evidence is None:
            if (
                self.failure_evidence_hash is not None
                or self.failure_code not in _TRANSPORT_PROVABLE_CODES
            ):
                raise RetainedFailureError(
                    "failure code requires exact tagged typed evidence"
                )
        elif (
            not isinstance(self.failure_evidence, FAILURE_EVIDENCE_TYPES_V3)
            or self.failure_evidence.failure_code is not self.failure_code
            or self.failure_evidence_hash != self.failure_evidence.evidence_hash
            or self.failure_evidence.request_hash != self.request_hash
            or self.failure_evidence.authorization_hash != self.authorization_hash
            or self.failure_evidence.case_id != self.case.case_id
            or self.failure_evidence.arm_id != self.arm_id
            or self.failure_evidence.failure_artifact_hash != self.failure_artifact_hash
        ):
            raise RetainedFailureError(
                "retained failure typed evidence ancestry changed"
            )
        for value, label in (
            (self.authorization_hash, "authorization hash"),
            (self.request_hash, "request hash"),
            (self.failure_artifact_hash, "failure artifact hash"),
            (self.failure_policy_hash, "failure policy hash"),
            (self.stage_cost_pre_ledger_hash, "StageCost pre-ledger hash"),
            (self.stage_cost_ledger_hash, "StageCost ledger hash"),
            (self.terminal_reason_hash, "terminal reason hash"),
            (self.outcome_hash, "retained failure outcome hash"),
        ):
            _digest(value, label)
        if self.failure_evidence_hash is not None:
            _digest(self.failure_evidence_hash, "failure evidence hash")
        _non_negative_int(self.retry_count, "retry count")
        _text(self.terminal_reason, "terminal reason")
        if tuple(item.attempt_index for item in self.attempts) != tuple(
            range(len(self.attempts))
        ) or not all(
            isinstance(item, RetainedFailureAttempt) for item in self.attempts
        ):
            raise RetainedFailureError(
                "retained failure attempts must be complete and ordered"
            )
        if not self.attempts and (
            self.failure_evidence is None
            or not self.failure_evidence.no_attempt
            or self.stage_cost_pre_ledger_hash != self.stage_cost_ledger_hash
        ):
            raise RetainedFailureError(
                "no-attempt failure requires typed evidence and an unchanged ledger"
            )
        if self.failure_evidence is not None:
            bindings = tuple(
                attempt_binding_hash(
                    item.judge_attempt,
                    item.stage_cost_entry,
                )
                for item in self.attempts
            )
            if bindings != self.failure_evidence.attempt_binding_hashes:
                raise RetainedFailureError(
                    "failure evidence does not bind the exact retained attempts"
                )
        if (
            self.receipt_hashes != tuple(item.receipt_hash for item in self.attempts)
            or self.stage_cost_entry_hashes
            != tuple(item.stage_cost_entry_hash for item in self.attempts)
            or len(set(self.receipt_hashes)) != len(self.receipt_hashes)
            or len(set(self.stage_cost_entry_hashes))
            != len(self.stage_cost_entry_hashes)
        ):
            raise RetainedFailureError(
                "retained failure evidence contains missing or duplicate attempts"
            )
        if (
            self.not_observed_fields != _NOT_OBSERVED_FIELDS
            or self.accepted is not None
            or self.detected is not None
            or self.judge_verdict is not None
            or self.denominator_retained is not True
            or self.claim_scope != "simulated_nonclaim"
            or self.production_authorized is not False
            or self.test_only is not True
        ):
            raise RetainedFailureError(
                "retained failure cannot forge an observed verdict or production claim"
            )
        if self.terminal_reason_hash != _canonical_hash(self.terminal_reason):
            raise RetainedFailureError("terminal reason hash mismatch")
        if self.outcome_hash != _canonical_hash(self._body()):
            raise RetainedFailureError("retained failure outcome hash mismatch")

    def _body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "tag": self.tag,
            "case": self.case.to_dict(),
            "arm_id": self.arm_id,
            "authorization_hash": self.authorization_hash,
            "request_hash": self.request_hash,
            "failure_code": self.failure_code.value,
            "failure_artifact": self.failure_artifact.to_dict(),
            "failure_artifact_hash": self.failure_artifact_hash,
            "failure_evidence": (
                self.failure_evidence.to_dict()
                if self.failure_evidence is not None
                else None
            ),
            "failure_evidence_hash": self.failure_evidence_hash,
            "failure_policy_hash": self.failure_policy_hash,
            "result_validity": self.result_validity.value,
            "automatic_status": (
                self.automatic_status.value
                if self.automatic_status is not None
                else None
            ),
            "attempts": [item.to_dict() for item in self.attempts],
            "receipt_hashes": list(self.receipt_hashes),
            "stage_cost_entry_hashes": list(self.stage_cost_entry_hashes),
            "stage_cost_pre_ledger_hash": self.stage_cost_pre_ledger_hash,
            "stage_cost_ledger_hash": self.stage_cost_ledger_hash,
            "retry_count": self.retry_count,
            "terminal_reason": self.terminal_reason,
            "terminal_reason_hash": self.terminal_reason_hash,
            "not_observed_fields": list(self.not_observed_fields),
            "accepted": self.accepted,
            "detected": self.detected,
            "judge_verdict": self.judge_verdict,
            "denominator_retained": self.denominator_retained,
            "claim_scope": self.claim_scope,
            "production_authorized": self.production_authorized,
            "test_only": self.test_only,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "outcome_hash": self.outcome_hash}

    @classmethod
    def create(
        cls,
        *,
        request: FormalArmRequest,
        failure: FormalFailureArtifact,
        failure_policy: FailurePolicyContract,
        attempts: Sequence[RetainedFailureAttempt],
        stage_cost_pre_ledger: StageCostLedger,
        stage_cost_ledger: StageCostLedger,
        terminal_reason: str,
        successful_result: object | None,
        failure_evidence: FailureEvidenceV3 | None = None,
    ) -> RetainedFailureOutcome:
        if successful_result is not None:
            raise RetainedFailureError(
                "success evidence and retained failure cannot coexist"
            )
        if not isinstance(failure, FormalFailureArtifact):
            raise RetainedFailureError(
                "retained failure requires one typed failure artifact"
            )
        if not isinstance(failure_policy, FailurePolicyContract):
            raise RetainedFailureError(
                "retained failure requires typed FailurePolicyContract"
            )
        if not isinstance(stage_cost_ledger, StageCostLedger):
            raise RetainedFailureError(
                "retained failure requires typed StageCost ledger"
            )
        if not isinstance(stage_cost_pre_ledger, StageCostLedger):
            raise RetainedFailureError(
                "retained failure requires typed StageCost pre-ledger"
            )
        if not isinstance(request, FormalArmRequest):
            raise RetainedFailureError(
                "retained failure requires one typed FormalArmRequest"
            )
        case = request.case
        arm_id = request.arm_id
        authorization_hash = request.authorization_hash
        request_hash = request.request_hash
        if terminal_reason != failure.message:
            raise RetainedFailureError(
                "terminal reason must equal the typed failure reason"
            )
        attempt_values = tuple(attempts)
        if not all(isinstance(item, RetainedFailureAttempt) for item in attempt_values):
            raise RetainedFailureError(NO_RECEIPT_FAILURE_INTEGRATION_GAP)
        policy_disposition = project_failure_disposition(
            failure_policy,
            failure.code,
        )
        if failure.code in _TRANSPORT_PROVABLE_CODES:
            if failure_evidence is not None:
                raise RetainedFailureError(
                    "transport-proven failure cannot carry a second evidence variant"
                )
        elif not isinstance(failure_evidence, FAILURE_EVIDENCE_TYPES_V3):
            gap = REQUIRED_FAILURE_EVIDENCE_DESCRIPTIONS[failure.code]
            raise RetainedFailureError(
                f"current typed transport evidence cannot prove {failure.code.value}: "
                f"{gap}"
            )
        elif (
            failure_evidence.failure_code is not failure.code
            or failure_evidence.request_hash != request_hash
            or failure_evidence.authorization_hash != authorization_hash
            or failure_evidence.case_id != case.case_id
            or failure_evidence.task_id != case.task_id
            or failure_evidence.arm_id != arm_id
            or failure_evidence.failure_artifact_hash
            != _canonical_hash(failure.to_dict())
        ):
            raise RetainedFailureError(
                "typed failure evidence request/failure ancestry disagrees"
            )
        if (
            request.failure_policy_hash != failure_policy.contract_hash
            or request.price_manifest_hash != stage_cost_pre_ledger.price_manifest_hash
            or request.price_manifest_hash != stage_cost_ledger.price_manifest_hash
            or request.stage_budget_manifest_hash
            != stage_cost_pre_ledger.budget_manifest.contract_hash
            or request.stage_budget_manifest_hash
            != stage_cost_ledger.budget_manifest.contract_hash
            or request.stage_cost_pre_ledger_hash != stage_cost_pre_ledger.contract_hash
        ):
            raise RetainedFailureError(
                "request policy/price/budget/pre-ledger ancestry disagrees "
                "with retained evidence"
            )
        if (
            stage_cost_ledger.ledger_id,
            stage_cost_ledger.version,
            stage_cost_ledger.price_manifest_hash,
            stage_cost_ledger.budget_manifest,
        ) != (
            stage_cost_pre_ledger.ledger_id,
            stage_cost_pre_ledger.version,
            stage_cost_pre_ledger.price_manifest_hash,
            stage_cost_pre_ledger.budget_manifest,
        ) or stage_cost_ledger.entries[
            : len(stage_cost_pre_ledger.entries)
        ] != stage_cost_pre_ledger.entries:
            raise RetainedFailureError(
                "final StageCost ledger is not an exact extension of the pre-ledger"
            )
        phase = case.phase
        entry_values = tuple(item.stage_cost_entry for item in attempt_values)
        receipt_values = tuple(
            item.judge_attempt.transport_receipt for item in attempt_values
        )
        ledger_entries = tuple(
            item
            for item in stage_cost_ledger.entries
            if item.phase == phase
            and item.arm_id == arm_id
            and item.request_hash == request_hash
        )
        if (
            tuple(item.attempt_index for item in attempt_values)
            != tuple(range(len(attempt_values)))
            or entry_values != ledger_entries
            or any(
                entry.phase != phase
                or entry.arm_id != arm_id
                or entry.request_hash != request_hash
                or receipt.payload.phase != phase
                or receipt.payload.execution_authorization_hash != authorization_hash
                for entry, receipt in zip(
                    entry_values,
                    receipt_values,
                    strict=True,
                )
            )
        ):
            raise RetainedFailureError(
                "case, arm, authorization, receipt, and StageCost ancestry disagree"
            )
        if failure.code is FailureCode.MALFORMED_RESPONSE:
            if (
                len(attempt_values) != 1
                or receipt_values[0].payload.outcome is not TransportOutcome.SUCCESS
                or not receipt_values[0].payload.response_present
                or receipt_values[0].payload.failure_code is not None
                or entry_values[0].outcome is not CostOutcome.SUCCEEDED
                or entry_values[0].failure_code is not None
            ):
                raise RetainedFailureError(
                    "malformed response requires one response-bearing successful "
                    "transport attempt"
                )
        elif failure.code in _TRANSPORT_PROVABLE_CODES:
            if not attempt_values or any(
                receipt.payload.outcome is not TransportOutcome.FAILED
                or receipt.payload.failure_code != failure.code.value
                or entry.outcome is not CostOutcome.FAILED
                or entry.failure_code != failure.code.value
                for entry, receipt in zip(
                    entry_values,
                    receipt_values,
                    strict=True,
                )
            ):
                raise RetainedFailureError(
                    "transport failure attempts do not prove the terminal code"
                )
        elif attempt_values:
            raise RetainedFailureError(
                "this typed retained failure is a no-attempt condition"
            )
        evidence_bindings = tuple(
            attempt_binding_hash(item.judge_attempt, item.stage_cost_entry)
            for item in attempt_values
        )
        if failure_evidence is not None and (
            evidence_bindings != failure_evidence.attempt_binding_hashes
            or failure_evidence.no_attempt != (not attempt_values)
        ):
            raise RetainedFailureError(
                "typed failure evidence does not bind the exact attempt set"
            )
        if not attempt_values and stage_cost_ledger != stage_cost_pre_ledger:
            raise RetainedFailureError(
                "no-attempt failure cannot fabricate receipt or zero-cost work"
            )
        for index, (attempt, entry, receipt) in enumerate(
            zip(attempt_values, entry_values, receipt_values, strict=True)
        ):
            expected_previous_receipt = (
                receipt_values[index - 1].contract_hash if index else None
            )
            expected_retry_parent = entry_values[0].contract_hash if index else None
            if (
                receipt.payload.sequence_number != index
                or receipt.payload.previous_receipt_hash != expected_previous_receipt
                or entry.retry_count != int(index > 0)
                or entry.retry_of_entry_hash != expected_retry_parent
                or attempt.retry_of_entry_hash != expected_retry_parent
            ):
                raise RetainedFailureError(
                    "retained failure retry/receipt ancestry is invalid"
                )
        retry_count = sum(item.retry_count for item in entry_values)
        if retry_count > stage_cost_ledger.budget_manifest.for_phase(phase).max_retries:
            raise RetainedFailureError("retained failure retry cap was exceeded")
        failure_artifact_hash = _canonical_hash(failure.to_dict())
        failure_evidence_hash = (
            failure_evidence.evidence_hash if failure_evidence is not None else None
        )
        receipt_hashes = tuple(item.contract_hash for item in receipt_values)
        stage_cost_entry_hashes = tuple(item.contract_hash for item in entry_values)
        terminal_reason_hash = _canonical_hash(terminal_reason)
        body = {
            "schema": RETAINED_FAILURE_SCHEMA,
            "tag": "retained_failure",
            "case": case.to_dict(),
            "arm_id": arm_id,
            "authorization_hash": authorization_hash,
            "request_hash": request_hash,
            "failure_code": failure.code.value,
            "failure_artifact": failure.to_dict(),
            "failure_artifact_hash": failure_artifact_hash,
            "failure_evidence": (
                failure_evidence.to_dict() if failure_evidence is not None else None
            ),
            "failure_evidence_hash": failure_evidence_hash,
            "failure_policy_hash": failure_policy.contract_hash,
            "result_validity": policy_disposition.result_validity.value,
            "automatic_status": (
                policy_disposition.automatic_status.value
                if policy_disposition.automatic_status is not None
                else None
            ),
            "attempts": [item.to_dict() for item in attempt_values],
            "receipt_hashes": list(receipt_hashes),
            "stage_cost_entry_hashes": list(stage_cost_entry_hashes),
            "stage_cost_pre_ledger_hash": stage_cost_pre_ledger.contract_hash,
            "stage_cost_ledger_hash": stage_cost_ledger.contract_hash,
            "retry_count": retry_count,
            "terminal_reason": terminal_reason,
            "terminal_reason_hash": terminal_reason_hash,
            "not_observed_fields": list(_NOT_OBSERVED_FIELDS),
            "accepted": None,
            "detected": None,
            "judge_verdict": None,
            "denominator_retained": True,
            "claim_scope": "simulated_nonclaim",
            "production_authorized": False,
            "test_only": True,
        }
        return cls(
            schema=RETAINED_FAILURE_SCHEMA,
            tag="retained_failure",
            case=case,
            arm_id=arm_id,
            authorization_hash=authorization_hash,
            request_hash=request_hash,
            failure_code=failure.code,
            failure_artifact=failure,
            failure_artifact_hash=failure_artifact_hash,
            failure_evidence=failure_evidence,
            failure_evidence_hash=failure_evidence_hash,
            failure_policy_hash=failure_policy.contract_hash,
            result_validity=policy_disposition.result_validity,
            automatic_status=policy_disposition.automatic_status,
            attempts=attempt_values,
            receipt_hashes=receipt_hashes,
            stage_cost_entry_hashes=stage_cost_entry_hashes,
            stage_cost_pre_ledger_hash=stage_cost_pre_ledger.contract_hash,
            stage_cost_ledger_hash=stage_cost_ledger.contract_hash,
            retry_count=retry_count,
            terminal_reason=terminal_reason,
            terminal_reason_hash=terminal_reason_hash,
            not_observed_fields=_NOT_OBSERVED_FIELDS,
            accepted=None,
            detected=None,
            judge_verdict=None,
            denominator_retained=True,
            claim_scope="simulated_nonclaim",
            production_authorized=False,
            test_only=True,
            outcome_hash=_canonical_hash(body),
            _factory_token=_OUTCOME_TOKEN,
        )

    @classmethod
    def restore_from_typed_sources(
        cls,
        value: object,
        *,
        request: FormalArmRequest,
        failure: FormalFailureArtifact,
        failure_policy: FailurePolicyContract,
        judge_attempts: Sequence[JudgeCallCostArtifact],
        stage_cost_entries: Sequence[StageCostEntry],
        stage_cost_pre_ledger: StageCostLedger,
        stage_cost_ledger: StageCostLedger,
        failure_evidence: FailureEvidenceV3 | None = None,
    ) -> RetainedFailureOutcome:
        """Re-run the factory from typed sources and require an exact encoding."""

        if not isinstance(failure, FormalFailureArtifact):
            raise RetainedFailureError(
                "retained failure restore requires typed failure artifact"
            )
        try:
            judge_values = tuple(judge_attempts)
            entry_values = tuple(stage_cost_entries)
        except TypeError as error:
            raise RetainedFailureError(
                "retained failure restore requires typed evidence sequences"
            ) from error
        if len(judge_values) != len(entry_values):
            raise RetainedFailureError(
                "retained failure restore requires paired Judge and StageCost evidence"
            )
        attempts = tuple(
            RetainedFailureAttempt.create(
                attempt_index=index,
                judge_attempt=judge_attempt,
                stage_cost_entry=stage_cost_entry,
            )
            for index, (judge_attempt, stage_cost_entry) in enumerate(
                zip(judge_values, entry_values, strict=True)
            )
        )
        restored = cls.create(
            request=request,
            failure=failure,
            failure_policy=failure_policy,
            attempts=attempts,
            stage_cost_pre_ledger=stage_cost_pre_ledger,
            stage_cost_ledger=stage_cost_ledger,
            terminal_reason=failure.message,
            successful_result=None,
            failure_evidence=failure_evidence,
        )
        _require_exact_serialization(
            value,
            restored.to_dict(),
            "retained failure outcome",
        )
        return restored


_INDEX_TOKEN = object()


@dataclass(frozen=True)
class RetainedFailureOutcomeIndex:
    outcomes: tuple[RetainedFailureOutcome, ...]
    index_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcomes", tuple(self.outcomes))
        typed = bool(self.outcomes) and all(
            isinstance(item, RetainedFailureOutcome) for item in self.outcomes
        )
        keys = (
            tuple((item.case.case_id, item.arm_id) for item in self.outcomes)
            if typed
            else ()
        )
        if (
            self._factory_token is not _INDEX_TOKEN
            or not typed
            or len(set(keys)) != len(keys)
            or self.index_hash
            != _canonical_hash([item.outcome_hash for item in self.outcomes])
        ):
            raise RetainedFailureError(
                "retained failure outcome index contains a duplicate or invalid entry"
            )

    @classmethod
    def create(
        cls,
        outcomes: Sequence[RetainedFailureOutcome],
    ) -> RetainedFailureOutcomeIndex:
        try:
            values = tuple(outcomes)
        except TypeError as error:
            raise RetainedFailureError(
                "retained failure outcome index requires typed outcomes"
            ) from error
        if not values or not all(
            isinstance(item, RetainedFailureOutcome) for item in values
        ):
            raise RetainedFailureError(
                "retained failure outcome index requires typed outcomes"
            )
        return cls(
            outcomes=values,
            index_hash=_canonical_hash([item.outcome_hash for item in values]),
            _factory_token=_INDEX_TOKEN,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "outcomes": [item.to_dict() for item in self.outcomes],
            "index_hash": self.index_hash,
        }

    @classmethod
    def restore_from_typed_sources(
        cls,
        value: object,
        *,
        outcomes: Sequence[RetainedFailureOutcome],
    ) -> RetainedFailureOutcomeIndex:
        """Rebuild an index from typed outcomes and require exact ordering."""

        restored = cls.create(outcomes)
        _require_exact_serialization(
            value,
            restored.to_dict(),
            "retained failure outcome index",
        )
        return restored


__all__ = [
    "LEGACY_FORMAL_ARTIFACT_INTEGRATION_GAP",
    "NO_RECEIPT_FAILURE_INTEGRATION_GAP",
    "RETAINED_FAILURE_ATTEMPT_SCHEMA",
    "RETAINED_FAILURE_SCHEMA",
    "RetainedFailureAttempt",
    "RetainedFailureError",
    "RetainedFailureOutcome",
    "RetainedFailureOutcomeIndex",
    "REQUIRED_FAILURE_EVIDENCE_DESCRIPTIONS",
    "UNREPRESENTABLE_FAILURE_EVIDENCE_GAPS",
    "project_failure_disposition",
]
