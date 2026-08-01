"""Isolated formal Judge evidence primitives for MEAS0.

The module deliberately does not enter the pilot runtime.  It builds
hash-bound J-CAL/J-AUDIT invocation and response corpora, derives J-CAL
qualification statistics, and keeps deterministic fake-provider evidence
visibly test-only.

J-CAL-v1 currently contains one normal/reversed pair per item rather than
separate order, style, and exact-repeat perturbations.  Until the frozen
manifest grows those axes, the observed pair-disagreement rate is used
conservatively for all three instability fields.  No caller-supplied rate is
accepted by the derivation API.

Its inline raw-response corpus is a legacy, internal test-only artifact
format. It is not a public export format and cannot authorize production
without per-call protected artifacts and trusted transport receipts.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from .measurement import EvaluationStatus
from .meas0_readiness import (
    ContractError,
    JAuditManifest,
    JCalManifest,
    JudgeCard,
    JudgeInvocation,
    JudgeQualification,
    JudgeQuarantine,
    JudgeResponse,
    RateEstimate,
    fuse_judge_presentations,
)
from .meas0_stage_cost import (
    CategoryCallCap,
    CostCategory,
    CostOutcome,
    PHASES,
    PhaseBudget,
    StageBudgetManifest,
    StageCostEntry,
    StageCostLedger,
)


class FormalEvidenceError(ValueError):
    """Raised when formal evidence is incomplete, inconsistent, or unsafe."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FormalEvidenceError(f"{label} must be non-empty text")
    return value


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise FormalEvidenceError(f"{label} must be a non-negative integer")
    return value


def _positive_int(value: object, label: str) -> int:
    result = _non_negative_int(value, label)
    if result == 0:
        raise FormalEvidenceError(f"{label} must be positive")
    return result


def _digest(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise FormalEvidenceError(f"{label} must be lowercase SHA-256")
    return value


class _HashBound:
    def _body(self) -> dict[str, Any]:
        raise NotImplementedError

    @property
    def contract_hash(self) -> str:
        return _sha256(_canonical(self._body()))

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "contract_hash": self.contract_hash}


@dataclass(frozen=True)
class EvidenceAttestation(_HashBound):
    """Provenance label which cannot silently default to production."""

    attestation_id: str
    issuer: str
    issued_at: str
    test_only: bool

    def __post_init__(self) -> None:
        _text(self.attestation_id, "attestation_id")
        _text(self.issuer, "attestation issuer")
        _text(self.issued_at, "attestation issued_at")
        if not isinstance(self.test_only, bool):
            raise FormalEvidenceError("attestation test_only must be explicit boolean")

    def _body(self) -> dict[str, Any]:
        return {
            "attestation_id": self.attestation_id,
            "issuer": self.issuer,
            "issued_at": self.issued_at,
            "test_only": self.test_only,
        }


@dataclass(frozen=True)
class JudgeExecutionBudget(_HashBound):
    max_calls: int
    max_input_tokens: int
    max_output_tokens: int
    max_elapsed_ms: int

    def __post_init__(self) -> None:
        for field_name in (
            "max_calls",
            "max_input_tokens",
            "max_output_tokens",
            "max_elapsed_ms",
        ):
            _positive_int(getattr(self, field_name), field_name)

    def _body(self) -> dict[str, Any]:
        return {
            "max_calls": self.max_calls,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_elapsed_ms": self.max_elapsed_ms,
            "contract_scope": "stage_budget_projection_only",
            "production_ready": False,
        }

    @property
    def production_ready(self) -> bool:
        return False

    def is_stage_budget_projection(
        self,
        manifest: StageBudgetManifest,
        phase: str,
    ) -> bool:
        if not isinstance(manifest, StageBudgetManifest):
            return False
        try:
            phase_budget = manifest.for_phase(phase)
        except ValueError:
            return False
        return (
            phase_budget.max_calls == self.max_calls
            and phase_budget.category_call_cap(CostCategory.JUDGE) == self.max_calls
            and phase_budget.max_input_tokens == self.max_input_tokens
            and phase_budget.max_output_tokens == self.max_output_tokens
            and phase_budget.max_wall_time_ms == self.max_elapsed_ms
        )


def _contract_test_stage_ledger(
    budget: JudgeExecutionBudget,
    phase: str,
) -> StageCostLedger:
    """Backwards-compatible test-only projection; never formal evidence."""

    phase_budgets = tuple(
        PhaseBudget(
            phase=item_phase,
            max_calls=(budget.max_calls if item_phase == phase else 1_000_000),
            max_input_tokens=(
                budget.max_input_tokens if item_phase == phase else 1_000_000_000
            ),
            max_output_tokens=(
                budget.max_output_tokens if item_phase == phase else 1_000_000_000
            ),
            max_wall_time_ms=(
                budget.max_elapsed_ms if item_phase == phase else 1_000_000_000
            ),
            max_bytes_transferred=1_000_000_000,
            max_retries=0,
            max_monetary_microunits=0,
            counts_toward_per_arm_equality=item_phase in {"pilot", "confirmatory"},
            category_call_caps=tuple(
                CategoryCallCap(
                    category=category,
                    max_calls=(
                        budget.max_calls
                        if item_phase == phase and category is CostCategory.JUDGE
                        else 1_000_000
                    ),
                )
                for category in CostCategory
            ),
        )
        for item_phase in PHASES
    )
    return StageCostLedger(
        ledger_id="meas0.judge-stage-cost.compatibility-test.v1",
        version=1,
        price_manifest_hash=_sha256(b"contract-test-no-production-price-manifest"),
        budget_manifest=StageBudgetManifest(
            manifest_id="meas0.stage-budget.compatibility-test.v1",
            version=1,
            phase_budgets=phase_budgets,
        ),
        entries=(),
    )


@dataclass(frozen=True)
class RawJudgeResult:
    """Raw provider result; parsing and validation stay in the Evaluation Plane."""

    raw_response: bytes = field(repr=False)
    input_tokens: int
    output_tokens: int
    elapsed_ms: int

    def __post_init__(self) -> None:
        if not isinstance(self.raw_response, bytes):
            raise FormalEvidenceError("raw_response must be bytes")
        for field_name in ("input_tokens", "output_tokens", "elapsed_ms"):
            _non_negative_int(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class JudgeProviderRequest:
    invocation: JudgeInvocation
    presentation_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.invocation, JudgeInvocation):
            raise FormalEvidenceError("provider request requires JudgeInvocation")
        if (
            not isinstance(self.presentation_hash, str)
            or len(self.presentation_hash) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.presentation_hash
            )
        ):
            raise FormalEvidenceError("presentation_hash must be SHA-256")


class JudgeProvider(Protocol):
    """Minimal provider surface; concrete live adapters remain external."""

    provider_id: str
    model_id: str
    test_only: bool

    def invoke(self, request: JudgeProviderRequest) -> RawJudgeResult: ...


class JudgeCallOutcome(str, Enum):
    OK = "ok"
    SCHEMA_INVALID = "schema_invalid"
    TIMEOUT = "timeout"
    BUDGET_EXHAUSTED = "budget_exhausted"
    PROVIDER_ERROR = "provider_error"


@dataclass(frozen=True)
class JudgeCallRecord(_HashBound):
    invocation: JudgeInvocation
    presentation_hash: str
    outcome: JudgeCallOutcome
    response: JudgeResponse | None
    raw_response: bytes = field(repr=False)
    raw_response_hash: str
    input_tokens: int
    output_tokens: int
    elapsed_ms: int
    error: str | None
    attempted: bool
    stage_cost_entry_hash: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.invocation, JudgeInvocation):
            raise FormalEvidenceError("call record requires JudgeInvocation")
        JudgeProviderRequest(self.invocation, self.presentation_hash)
        if not isinstance(self.outcome, JudgeCallOutcome):
            raise FormalEvidenceError("call outcome is invalid")
        if not isinstance(self.raw_response, bytes):
            raise FormalEvidenceError("call raw_response must be bytes")
        if (
            not isinstance(self.raw_response_hash, str)
            or len(self.raw_response_hash) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.raw_response_hash
            )
        ):
            raise FormalEvidenceError("raw_response_hash must be SHA-256")
        if _sha256(self.raw_response) != self.raw_response_hash:
            raise FormalEvidenceError("raw response hash mismatch")
        for field_name in ("input_tokens", "output_tokens", "elapsed_ms"):
            _non_negative_int(getattr(self, field_name), field_name)
        if not isinstance(self.attempted, bool):
            raise FormalEvidenceError("call attempted must be boolean")
        if self.attempted:
            if (
                not isinstance(self.stage_cost_entry_hash, str)
                or len(self.stage_cost_entry_hash) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in self.stage_cost_entry_hash
                )
            ):
                raise FormalEvidenceError(
                    "attempted call requires a stage-cost entry hash"
                )
        elif (
            self.outcome is not JudgeCallOutcome.BUDGET_EXHAUSTED
            or self.stage_cost_entry_hash is not None
            or self.raw_response
            or any((self.input_tokens, self.output_tokens, self.elapsed_ms))
        ):
            raise FormalEvidenceError(
                "unattempted call must be a cost-free budget placeholder"
            )
        if self.outcome is JudgeCallOutcome.OK:
            if self.response is None or self.error is not None:
                raise FormalEvidenceError(
                    "successful call requires response and no error"
                )
            if (
                self.response.invocation_id != self.invocation.invocation_id
                or self.response.criterion_id != self.invocation.criterion_id
                or self.response.raw_response_hash != self.raw_response_hash
            ):
                raise FormalEvidenceError(
                    "call response is not bound to invocation/raw bytes"
                )
        elif self.response is not None:
            raise FormalEvidenceError("failed call cannot retain an accepted response")
        elif self.error is None:
            raise FormalEvidenceError("failed call requires a machine-readable error")

    def _body(self) -> dict[str, Any]:
        return {
            "invocation": self.invocation.to_dict(),
            "presentation_hash": self.presentation_hash,
            "outcome": self.outcome.value,
            "response": self.response.to_dict() if self.response is not None else None,
            "raw_response_base64": base64.b64encode(self.raw_response).decode("ascii"),
            "raw_response_hash": self.raw_response_hash,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
            "attempted": self.attempted,
            "stage_cost_entry_hash": self.stage_cost_entry_hash,
        }


@dataclass(frozen=True)
class ExactInvocationEntry(_HashBound):
    """One exact cross-object invocation membership at a frozen sequence."""

    sequence_number: int
    phase: str
    probe_call_id: str
    item_id: str
    invocation_id: str
    criterion_id: str
    presentation_hash: str
    request_fingerprint: str
    call_record_hash: str
    transport_entry_hash: str
    receipt_hash: str
    stage_cost_entry_hash: str

    def __post_init__(self) -> None:
        _non_negative_int(self.sequence_number, "invocation sequence_number")
        if self.phase not in {"jcal", "jaudit"}:
            raise FormalEvidenceError("exact invocation phase is invalid")
        for field_name in (
            "probe_call_id",
            "item_id",
            "invocation_id",
            "criterion_id",
        ):
            _text(getattr(self, field_name), field_name)
        for field_name in (
            "presentation_hash",
            "request_fingerprint",
            "call_record_hash",
            "transport_entry_hash",
            "receipt_hash",
            "stage_cost_entry_hash",
        ):
            _digest(getattr(self, field_name), field_name)

    def _body(self) -> dict[str, Any]:
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, value: object) -> ExactInvocationEntry:
        raw = _object(value, "exact invocation entry")
        try:
            result = cls(
                **{
                    field_name: raw[field_name]
                    for field_name in cls.__dataclass_fields__
                }
            )
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, FormalEvidenceError):
                raise
            raise FormalEvidenceError(
                "serialized exact invocation entry is malformed"
            ) from error
        if raw.get("contract_hash") != result.contract_hash:
            raise FormalEvidenceError("exact invocation entry hash mismatch")
        return result


@dataclass(frozen=True)
class ExactInvocationManifest(_HashBound):
    """Exact ordered bijection across probes, calls, transport, and cost."""

    schema_version: int
    manifest_id: str
    phase: str
    probe_manifest_hash: str
    corpus_hash: str
    transport_batch_hash: str
    stage_cost_ledger_hash: str
    entries: tuple[ExactInvocationEntry, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise FormalEvidenceError(
                "exact invocation manifest schema_version must equal one"
            )
        _text(self.manifest_id, "exact invocation manifest_id")
        if self.phase not in {"jcal", "jaudit"}:
            raise FormalEvidenceError("exact invocation manifest phase is invalid")
        for field_name in (
            "probe_manifest_hash",
            "corpus_hash",
            "transport_batch_hash",
            "stage_cost_ledger_hash",
        ):
            _digest(getattr(self, field_name), field_name)
        entries = tuple(self.entries)
        if (
            not entries
            or not all(isinstance(item, ExactInvocationEntry) for item in entries)
            or tuple(item.sequence_number for item in entries)
            != tuple(range(len(entries)))
            or any(item.phase != self.phase for item in entries)
        ):
            raise FormalEvidenceError(
                "exact invocation membership must be typed, contiguous, and ordered"
            )
        for field_name in (
            "probe_call_id",
            "invocation_id",
            "call_record_hash",
            "transport_entry_hash",
            "receipt_hash",
            "stage_cost_entry_hash",
        ):
            values = tuple(getattr(item, field_name) for item in entries)
            if len(set(values)) != len(values):
                raise FormalEvidenceError(
                    f"exact invocation {field_name} membership must be unique"
                )
        object.__setattr__(self, "entries", entries)

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "phase": self.phase,
            "probe_manifest_hash": self.probe_manifest_hash,
            "corpus_hash": self.corpus_hash,
            "transport_batch_hash": self.transport_batch_hash,
            "stage_cost_ledger_hash": self.stage_cost_ledger_hash,
            "entries": [item.to_dict() for item in self.entries],
        }

    @classmethod
    def from_dict(cls, value: object) -> ExactInvocationManifest:
        raw = _object(value, "exact invocation manifest")
        try:
            result = cls(
                schema_version=raw["schema_version"],
                manifest_id=raw["manifest_id"],
                phase=raw["phase"],
                probe_manifest_hash=raw["probe_manifest_hash"],
                corpus_hash=raw["corpus_hash"],
                transport_batch_hash=raw["transport_batch_hash"],
                stage_cost_ledger_hash=raw["stage_cost_ledger_hash"],
                entries=tuple(
                    ExactInvocationEntry.from_dict(item) for item in raw["entries"]
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, FormalEvidenceError):
                raise
            raise FormalEvidenceError(
                "serialized exact invocation manifest is malformed"
            ) from error
        if raw.get("contract_hash") != result.contract_hash:
            raise FormalEvidenceError("exact invocation manifest hash mismatch")
        return result

    @classmethod
    def derive(
        cls,
        *,
        manifest_id: str,
        probe_manifest: object,
        corpus: ProbeJudgeCorpus,
        transport_batch: object,
        stage_cost_ledger: StageCostLedger,
    ) -> ExactInvocationManifest:
        """Derive and immediately reverify the ordered cross-object bijection."""

        from .meas0_judge_probes import JudgeProbeManifest
        from .meas0_trust import TransportReceiptBatch

        if (
            not isinstance(probe_manifest, JudgeProbeManifest)
            or not isinstance(corpus, ProbeJudgeCorpus)
            or not isinstance(transport_batch, TransportReceiptBatch)
            or not isinstance(stage_cost_ledger, StageCostLedger)
        ):
            raise FormalEvidenceError(
                "exact invocation derivation requires typed 288-call evidence"
            )
        stage_entries = stage_cost_ledger.entries[
            len(corpus.stage_cost_pre_ledger.entries) :
        ]
        collections = (
            probe_manifest.calls,
            corpus.records,
            transport_batch.plan.entries,
            transport_batch.receipts,
            stage_entries,
        )
        if len({len(items) for items in collections}) != 1:
            raise FormalEvidenceError(
                "exact invocation derivation membership is incomplete"
            )
        result = cls(
            schema_version=1,
            manifest_id=manifest_id,
            phase=corpus.phase,
            probe_manifest_hash=probe_manifest.contract_hash,
            corpus_hash=corpus.contract_hash,
            transport_batch_hash=transport_batch.contract_hash,
            stage_cost_ledger_hash=stage_cost_ledger.contract_hash,
            entries=tuple(
                ExactInvocationEntry(
                    sequence_number=sequence,
                    phase=corpus.phase,
                    probe_call_id=probe.call_id,
                    item_id=probe.item_id,
                    invocation_id=record.invocation.invocation_id,
                    criterion_id=record.invocation.criterion_id,
                    presentation_hash=record.presentation_hash,
                    request_fingerprint=record.invocation.request_fingerprint,
                    call_record_hash=record.contract_hash,
                    transport_entry_hash=transport.contract_hash,
                    receipt_hash=receipt.contract_hash,
                    stage_cost_entry_hash=stage.contract_hash,
                )
                for sequence, (
                    probe,
                    record,
                    transport,
                    receipt,
                    stage,
                ) in enumerate(zip(*collections, strict=True))
            ),
        )
        result.verify_membership(
            probe_manifest=probe_manifest,
            corpus=corpus,
            transport_batch=transport_batch,
            stage_cost_ledger=stage_cost_ledger,
        )
        return result

    def verify_membership(
        self,
        *,
        probe_manifest: object,
        corpus: JudgeCorpus | ProbeJudgeCorpus,
        transport_batch: object,
        stage_cost_ledger: StageCostLedger,
    ) -> None:
        """Fail closed unless every raw collection is the same ordered set."""

        from .meas0_judge_probes import JudgeProbeManifest
        from .meas0_trust import TransportReceiptBatch

        if (
            not isinstance(probe_manifest, JudgeProbeManifest)
            or not isinstance(corpus, (JudgeCorpus, ProbeJudgeCorpus))
            or not isinstance(transport_batch, TransportReceiptBatch)
            or not isinstance(stage_cost_ledger, StageCostLedger)
            or self.phase != corpus.phase
            or transport_batch.plan.phase != self.phase
            or self.probe_manifest_hash != probe_manifest.contract_hash
            or self.corpus_hash != corpus.contract_hash
            or self.transport_batch_hash != transport_batch.contract_hash
            or self.stage_cost_ledger_hash != stage_cost_ledger.contract_hash
        ):
            raise FormalEvidenceError("exact invocation ancestry is misbound")
        stage_entries = stage_cost_ledger.entries[
            len(corpus.stage_cost_pre_ledger.entries) :
        ]
        collections = (
            probe_manifest.calls,
            corpus.records,
            transport_batch.plan.entries,
            transport_batch.receipts,
            stage_entries,
            self.entries,
        )
        if len({len(items) for items in collections}) != 1 or not all(
            record.attempted for record in corpus.records
        ):
            raise FormalEvidenceError(
                "exact invocation membership has missing or extra entries"
            )
        for sequence, (
            probe,
            record,
            transport,
            receipt,
            stage,
            frozen,
        ) in enumerate(zip(*collections, strict=True)):
            expected = ExactInvocationEntry(
                sequence_number=sequence,
                phase=self.phase,
                probe_call_id=probe.call_id,
                item_id=probe.item_id,
                invocation_id=record.invocation.invocation_id,
                criterion_id=record.invocation.criterion_id,
                presentation_hash=record.presentation_hash,
                request_fingerprint=record.invocation.request_fingerprint,
                call_record_hash=record.contract_hash,
                transport_entry_hash=transport.contract_hash,
                receipt_hash=receipt.contract_hash,
                stage_cost_entry_hash=stage.contract_hash,
            )
            payload = receipt.payload
            if (
                frozen != expected
                or probe.item_id != record.invocation.case_id
                or probe.presentation_hash != record.presentation_hash
                or transport.sequence_number != sequence
                or transport.invocation_id != record.invocation.invocation_id
                or transport.criterion_id != record.invocation.criterion_id
                or transport.presentation_hash != record.presentation_hash
                or transport.request_fingerprint
                != record.invocation.request_fingerprint
                or payload.invocation_id != transport.invocation_id
                or payload.criterion_id != transport.criterion_id
                or payload.presentation_hash != transport.presentation_hash
                or payload.request_fingerprint != transport.request_fingerprint
                or record.stage_cost_entry_hash != stage.contract_hash
                or stage.phase != self.phase
                or stage.request_hash != record.invocation.request_fingerprint
                or stage.raw_receipt_hash != receipt.contract_hash
            ):
                raise FormalEvidenceError(
                    "exact invocation membership is reordered or misbound"
                )


@dataclass(frozen=True)
class JudgeCorpus(_HashBound):
    """Legacy 96-call normal/reversed corpus; never production-capable."""

    judge_card: JudgeCard
    calibration_manifest: JCalManifest | JAuditManifest
    attestation: EvidenceAttestation
    budget: JudgeExecutionBudget
    records: tuple[JudgeCallRecord, ...]
    stage_cost_pre_ledger: StageCostLedger
    stage_cost_ledger: StageCostLedger

    def __post_init__(self) -> None:
        if not isinstance(self.judge_card, JudgeCard) or not self.judge_card.is_bound:
            raise FormalEvidenceError("corpus requires a bound JudgeCard")
        if not isinstance(
            self.calibration_manifest,
            (JCalManifest, JAuditManifest),
        ):
            raise FormalEvidenceError("corpus requires a typed Judge set manifest")
        expected_set_hash = (
            self.judge_card.calibration_set_hash
            if isinstance(self.calibration_manifest, JCalManifest)
            else self.judge_card.audit_set_hash
        )
        if expected_set_hash != self.calibration_manifest.contract_hash:
            raise FormalEvidenceError(
                "JudgeCard is not bound to the Judge set manifest"
            )
        if not isinstance(self.attestation, EvidenceAttestation):
            raise FormalEvidenceError("corpus requires evidence attestation")
        if not isinstance(self.budget, JudgeExecutionBudget):
            raise FormalEvidenceError("corpus requires execution budget")
        if not isinstance(
            self.stage_cost_pre_ledger,
            StageCostLedger,
        ) or not isinstance(self.stage_cost_ledger, StageCostLedger):
            raise FormalEvidenceError("corpus requires typed stage-cost ledgers")
        if (
            self.stage_cost_pre_ledger.ledger_id != self.stage_cost_ledger.ledger_id
            or self.stage_cost_pre_ledger.version != self.stage_cost_ledger.version
            or self.stage_cost_pre_ledger.price_manifest_hash
            != self.stage_cost_ledger.price_manifest_hash
            or self.stage_cost_pre_ledger.budget_manifest
            != self.stage_cost_ledger.budget_manifest
            or self.stage_cost_ledger.entries[: len(self.stage_cost_pre_ledger.entries)]
            != self.stage_cost_pre_ledger.entries
        ):
            raise FormalEvidenceError("corpus stage-cost ledger ancestry is invalid")
        if not self.budget.is_stage_budget_projection(
            self.stage_cost_ledger.budget_manifest,
            self.phase,
        ):
            raise FormalEvidenceError(
                "legacy execution budget is not a StageBudget projection"
            )
        object.__setattr__(self, "records", tuple(self.records))
        expected = tuple(
            (item.item_id, item.criterion_id, presentation)
            for item in self.calibration_manifest.items
            for presentation in ("normal", "reversed")
        )
        observed = tuple(
            (
                record.invocation.case_id,
                record.invocation.criterion_id,
                record.invocation.presentation,
            )
            for record in self.records
            if isinstance(record, JudgeCallRecord)
        )
        if observed != expected or len(self.records) != 96:
            raise FormalEvidenceError(
                "J-CAL corpus must contain ordered normal/reversed records for 48 items"
            )
        if any(
            record.invocation.judge_card_hash != self.judge_card.contract_hash
            for record in self.records
        ):
            raise FormalEvidenceError("corpus invocation JudgeCard binding mismatch")
        if len({record.invocation.invocation_id for record in self.records}) != 96:
            raise FormalEvidenceError("corpus invocation IDs must be unique")
        appended_entries = self.stage_cost_ledger.entries[
            len(self.stage_cost_pre_ledger.entries) :
        ]
        attempted_records = tuple(record for record in self.records if record.attempted)
        if tuple(record.stage_cost_entry_hash for record in attempted_records) != tuple(
            entry.contract_hash for entry in appended_entries
        ):
            raise FormalEvidenceError(
                "Judge attempts and stage-cost entries are not one-to-one"
            )
        if any(
            entry.phase != self.phase
            or entry.category is not CostCategory.JUDGE
            or entry.provider_id != self.judge_card.provider
            or entry.model_id != self.judge_card.model_id
            or entry.request_hash != record.invocation.request_fingerprint
            for record, entry in zip(
                attempted_records,
                appended_entries,
                strict=True,
            )
        ):
            raise FormalEvidenceError(
                "Judge attempt stage-cost ancestry is inconsistent"
            )
        for record in self.records:
            if record.outcome is JudgeCallOutcome.OK:
                reparsed = _parse_response(
                    record.raw_response,
                    invocation=record.invocation,
                    judge_card=self.judge_card,
                )
                if reparsed != record.response:
                    raise FormalEvidenceError(
                        "accepted response does not match sealed raw corpus"
                    )
            elif record.outcome is JudgeCallOutcome.SCHEMA_INVALID:
                try:
                    _parse_response(
                        record.raw_response,
                        invocation=record.invocation,
                        judge_card=self.judge_card,
                    )
                except FormalEvidenceError:
                    pass
                else:
                    raise FormalEvidenceError(
                        "schema-invalid outcome contradicts sealed raw corpus"
                    )

    @property
    def calibration_manifest_hash(self) -> str:
        return self.calibration_manifest.contract_hash

    @property
    def phase(self) -> str:
        return (
            "jcal" if isinstance(self.calibration_manifest, JCalManifest) else "jaudit"
        )

    @property
    def ledger_pre_head_hash(self) -> str:
        return self.stage_cost_pre_ledger.contract_hash

    @property
    def final_ledger_hash(self) -> str:
        return self.stage_cost_ledger.contract_hash

    @property
    def production_ready(self) -> bool:
        return False

    @property
    def corpus_kind(self) -> str:
        return "legacy_96_test_contract"

    def _body(self) -> dict[str, Any]:
        return {
            "judge_card": self.judge_card.to_dict(),
            "calibration_manifest": self.calibration_manifest.to_dict(),
            "attestation": self.attestation.to_dict(),
            "budget": self.budget.to_dict(),
            "records": [record.to_dict() for record in self.records],
            "stage_cost_pre_ledger": self.stage_cost_pre_ledger.to_dict(),
            "stage_cost_ledger": self.stage_cost_ledger.to_dict(),
            "ledger_pre_head_hash": self.ledger_pre_head_hash,
            "final_ledger_hash": self.final_ledger_hash,
            "production_ready": self.production_ready,
            "corpus_kind": self.corpus_kind,
        }


@dataclass(frozen=True)
class ProbeJudgeCorpus(_HashBound):
    """Probe-aware 288-call corpus for formal J-CAL/J-AUDIT evidence."""

    judge_card: JudgeCard
    calibration_manifest: JCalManifest | JAuditManifest
    probe_manifest: object
    attestation: EvidenceAttestation
    records: tuple[JudgeCallRecord, ...]
    stage_cost_pre_ledger: StageCostLedger
    stage_cost_ledger: StageCostLedger

    def __post_init__(self) -> None:
        from .meas0_judge_probes import JudgeProbeManifest

        if not isinstance(self.judge_card, JudgeCard) or not self.judge_card.is_bound:
            raise FormalEvidenceError("probe corpus requires a bound JudgeCard")
        if not isinstance(
            self.calibration_manifest,
            (JCalManifest, JAuditManifest),
        ):
            raise FormalEvidenceError("probe corpus requires a typed Judge set")
        expected_set_hash = (
            self.judge_card.calibration_set_hash
            if isinstance(self.calibration_manifest, JCalManifest)
            else self.judge_card.audit_set_hash
        )
        if (
            expected_set_hash != self.calibration_manifest.contract_hash
            or not isinstance(self.probe_manifest, JudgeProbeManifest)
            or self.probe_manifest.judge_set_hash
            != self.calibration_manifest.contract_hash
        ):
            raise FormalEvidenceError("probe corpus Judge set ancestry is invalid")
        if not isinstance(self.attestation, EvidenceAttestation):
            raise FormalEvidenceError("probe corpus requires typed attestation")
        records = tuple(self.records)
        calls = self.probe_manifest.calls
        if (
            len(records) != 288
            or len(calls) != 288
            or not all(isinstance(item, JudgeCallRecord) for item in records)
            or not all(item.attempted for item in records)
        ):
            raise FormalEvidenceError(
                "probe corpus requires 288 attempted typed call records"
            )
        criterion_by_item = {
            item.item_id: item.criterion_id for item in self.calibration_manifest.items
        }
        for call, record in zip(calls, records, strict=True):
            invocation = record.invocation
            if (
                invocation.invocation_id != call.call_id
                or invocation.case_id != call.item_id
                or invocation.criterion_id != criterion_by_item.get(call.item_id)
                or invocation.presentation != call.presentation
                or record.presentation_hash != call.presentation_hash
                or invocation.judge_card_hash != self.judge_card.contract_hash
            ):
                raise FormalEvidenceError(
                    "probe call record order or invocation binding is invalid"
                )
            if record.outcome is JudgeCallOutcome.OK and (
                record.response is None
                or _parse_response(
                    record.raw_response,
                    invocation=invocation,
                    judge_card=self.judge_card,
                )
                != record.response
            ):
                raise FormalEvidenceError(
                    "probe response is not derived from sealed raw bytes"
                )
        if len({item.invocation.invocation_id for item in records}) != 288:
            raise FormalEvidenceError("probe invocation IDs must be unique")
        if not isinstance(
            self.stage_cost_pre_ledger,
            StageCostLedger,
        ) or not isinstance(self.stage_cost_ledger, StageCostLedger):
            raise FormalEvidenceError("probe corpus requires typed stage ledgers")
        if (
            self.stage_cost_pre_ledger.ledger_id != self.stage_cost_ledger.ledger_id
            or self.stage_cost_ledger.entries[: len(self.stage_cost_pre_ledger.entries)]
            != self.stage_cost_pre_ledger.entries
        ):
            raise FormalEvidenceError("probe corpus stage-cost ancestry is invalid")
        appended = self.stage_cost_ledger.entries[
            len(self.stage_cost_pre_ledger.entries) :
        ]
        if len(appended) != 288 or tuple(
            item.stage_cost_entry_hash for item in records
        ) != tuple(item.contract_hash for item in appended):
            raise FormalEvidenceError(
                "probe records and stage-cost entries are not a bijection"
            )
        if any(
            entry.phase != self.phase
            or entry.category is not CostCategory.JUDGE
            or entry.request_hash != record.invocation.request_fingerprint
            or entry.provider_id != self.judge_card.provider
            or entry.model_id != self.judge_card.model_id
            for record, entry in zip(records, appended, strict=True)
        ):
            raise FormalEvidenceError("probe stage-cost membership is misbound")
        object.__setattr__(self, "records", records)

    @property
    def phase(self) -> str:
        return (
            "jcal" if isinstance(self.calibration_manifest, JCalManifest) else "jaudit"
        )

    @property
    def ledger_pre_head_hash(self) -> str:
        return self.stage_cost_pre_ledger.contract_hash

    def _body(self) -> dict[str, Any]:
        return {
            "judge_card": self.judge_card.to_dict(),
            "calibration_manifest": self.calibration_manifest.to_dict(),
            "probe_manifest": self.probe_manifest.to_dict(),
            "attestation": self.attestation.to_dict(),
            "records": [item.to_dict() for item in self.records],
            "stage_cost_pre_ledger": self.stage_cost_pre_ledger.to_dict(),
            "stage_cost_ledger": self.stage_cost_ledger.to_dict(),
            "phase": self.phase,
            "ledger_pre_head_hash": self.ledger_pre_head_hash,
        }


@dataclass(frozen=True)
class DerivedProbeJudgeQualification(_HashBound):
    source_corpus: ProbeJudgeCorpus
    qualification: JudgeQualification
    quarantine: JudgeQuarantine | None

    def __post_init__(self) -> None:
        if not isinstance(self.source_corpus, ProbeJudgeCorpus):
            raise FormalEvidenceError("probe qualification requires ProbeJudgeCorpus")
        expected = _probe_qualification_for(
            self.source_corpus,
            qualification_id=self.qualification.qualification_id,
            evaluated_at=self.qualification.evaluated_at,
        )
        if expected.contract_hash != self.qualification.contract_hash:
            raise FormalEvidenceError(
                "probe qualification statistics must be re-derived"
            )
        if self.qualification.qualified:
            if self.quarantine is not None:
                raise FormalEvidenceError("qualified probe Judge cannot be quarantined")
        elif (
            not isinstance(self.quarantine, JudgeQuarantine)
            or self.quarantine.qualification_hash != self.qualification.contract_hash
        ):
            raise FormalEvidenceError(
                "unqualified probe Judge requires bound quarantine"
            )

    @property
    def source_corpus_hash(self) -> str:
        return self.source_corpus.contract_hash

    @property
    def attestation(self) -> EvidenceAttestation:
        return self.source_corpus.attestation

    def _body(self) -> dict[str, Any]:
        return {
            "source_corpus": self.source_corpus.to_dict(),
            "qualification": self.qualification.to_dict(),
            "quarantine": (
                self.quarantine.to_dict() if self.quarantine is not None else None
            ),
        }


@dataclass(frozen=True)
class FusedJudgeItem(_HashBound):
    item_id: str
    criterion_id: str
    status: EvaluationStatus
    normal_record_hash: str
    reversed_record_hash: str

    def __post_init__(self) -> None:
        _text(self.item_id, "fused item_id")
        _text(self.criterion_id, "fused criterion_id")
        if self.status not in {
            EvaluationStatus.PASS,
            EvaluationStatus.FAIL,
            EvaluationStatus.UNKNOWN,
            EvaluationStatus.DISPUTED,
        }:
            raise FormalEvidenceError("fused Judge status is invalid")

    def _body(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "criterion_id": self.criterion_id,
            "status": self.status.value,
            "normal_record_hash": self.normal_record_hash,
            "reversed_record_hash": self.reversed_record_hash,
        }


def _json_object(raw: bytes) -> dict[str, Any]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise FormalEvidenceError("raw Judge response has duplicate keys")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FormalEvidenceError(
            "raw Judge response is not valid UTF-8 JSON"
        ) from error
    if not isinstance(value, dict):
        raise FormalEvidenceError("raw Judge response must be a JSON object")
    return value


_RESPONSE_FIELDS = {
    "criterion_id",
    "verdict",
    "evidence_refs",
    "rationale",
    "confidence_0_1",
    "p_pass_0_1",
    "judge_version",
}


def _parse_response(
    raw: bytes,
    *,
    invocation: JudgeInvocation,
    judge_card: JudgeCard,
) -> JudgeResponse:
    payload = _json_object(raw)
    if set(payload) != _RESPONSE_FIELDS:
        raise FormalEvidenceError("raw Judge response does not match frozen schema")
    if payload["criterion_id"] != invocation.criterion_id:
        raise FormalEvidenceError("Judge criterion_id does not match invocation")
    if payload["judge_version"] != judge_card.card_id:
        raise FormalEvidenceError("Judge version does not match frozen JudgeCard")
    evidence_refs = payload["evidence_refs"]
    if not isinstance(evidence_refs, list) or any(
        not isinstance(item, str) for item in evidence_refs
    ):
        raise FormalEvidenceError("Judge evidence_refs must be a string array")
    try:
        return JudgeResponse(
            invocation_id=invocation.invocation_id,
            criterion_id=payload["criterion_id"],
            verdict=payload["verdict"],
            evidence_refs=tuple(evidence_refs),
            rationale=payload["rationale"],
            confidence_0_1=payload["confidence_0_1"],
            p_pass_0_1=payload["p_pass_0_1"],
            judge_version=payload["judge_version"],
            raw_response_hash=_sha256(raw),
        )
    except (ContractError, TypeError) as error:
        raise FormalEvidenceError(
            "raw Judge response does not match frozen schema"
        ) from error


class JudgeCorpusRunner:
    """Single-use deterministic, test-only J-CAL/J-AUDIT corpus builder."""

    def __init__(
        self,
        *,
        judge_card: JudgeCard,
        calibration_manifest: JCalManifest | JAuditManifest,
        provider: JudgeProvider,
        attestation: EvidenceAttestation,
        budget: JudgeExecutionBudget,
        stage_cost_ledger: StageCostLedger | None = None,
        input_tokens_limit: int,
        output_tokens_limit: int,
        timeout_ms: int,
    ) -> None:
        if not isinstance(judge_card, JudgeCard) or not judge_card.is_bound:
            raise FormalEvidenceError("formal Judge runner requires bound JudgeCard")
        if not isinstance(
            calibration_manifest,
            (JCalManifest, JAuditManifest),
        ):
            raise FormalEvidenceError("formal Judge runner requires a typed Judge set")
        phase = "jcal" if isinstance(calibration_manifest, JCalManifest) else "jaudit"
        expected_set_hash = (
            judge_card.calibration_set_hash
            if phase == "jcal"
            else judge_card.audit_set_hash
        )
        if expected_set_hash != calibration_manifest.contract_hash:
            raise FormalEvidenceError("JudgeCard Judge-set binding mismatch")
        if (
            getattr(provider, "provider_id", None) != judge_card.provider
            or getattr(provider, "model_id", None) != judge_card.model_id
        ):
            raise FormalEvidenceError("provider identity does not match JudgeCard")
        provider_test_only = getattr(provider, "test_only", None)
        if not isinstance(provider_test_only, bool):
            raise FormalEvidenceError("provider must explicitly declare test_only")
        if (
            not isinstance(attestation, EvidenceAttestation)
            or attestation.test_only is not provider_test_only
        ):
            raise FormalEvidenceError(
                "provider and evidence attestation test-only status mismatch"
            )
        if not isinstance(budget, JudgeExecutionBudget):
            raise FormalEvidenceError("formal Judge runner requires execution budget")
        if stage_cost_ledger is None and provider_test_only:
            stage_cost_ledger = _contract_test_stage_ledger(
                budget,
                phase,
            )
        if not isinstance(stage_cost_ledger, StageCostLedger):
            raise FormalEvidenceError("formal Judge runner requires a StageCost ledger")
        if stage_cost_ledger.production_ready:
            raise FormalEvidenceError(
                "test-only Judge runner cannot accept production-ready cost"
            )
        if not budget.is_stage_budget_projection(
            stage_cost_ledger.budget_manifest,
            phase,
        ):
            raise FormalEvidenceError(
                "legacy Judge budget must be an exact StageBudget projection"
            )
        if stage_cost_ledger.phase_decision(phase).stopped:
            raise FormalEvidenceError(
                "Judge phase cannot start from a stopped StageCost ledger"
            )
        self.judge_card = judge_card
        self.calibration_manifest = calibration_manifest
        self.provider = provider
        self.attestation = attestation
        self.budget = budget
        self.stage_cost_pre_ledger = stage_cost_ledger
        self.phase = phase
        self.input_tokens_limit = _positive_int(
            input_tokens_limit, "input_tokens_limit"
        )
        self.output_tokens_limit = _positive_int(
            output_tokens_limit, "output_tokens_limit"
        )
        self.timeout_ms = _positive_int(timeout_ms, "timeout_ms")
        self._used = False

    def run(self) -> JudgeCorpus:
        if self._used:
            raise FormalEvidenceError("JudgeCorpusRunner is single-use")
        self._used = True
        records: list[JudgeCallRecord] = []
        calls = input_tokens = output_tokens = elapsed_ms = 0
        stage_cost_ledger = self.stage_cost_pre_ledger
        for item in self.calibration_manifest.items:
            for presentation, effective_seed, presentation_hash in (
                ("normal", 8111, item.normal_presentation_hash),
                ("reversed", 8117, item.reversed_presentation_hash),
            ):
                invocation = self._invocation(
                    item_id=item.item_id,
                    criterion_id=item.criterion_id,
                    presentation=presentation,
                    effective_seed=effective_seed,
                    presentation_hash=presentation_hash,
                )
                if (
                    calls >= self.budget.max_calls
                    or stage_cost_ledger.phase_decision(self.phase).stopped
                ):
                    records.append(
                        self._unattempted_record(
                            invocation,
                            presentation_hash,
                            "max_calls",
                        )
                    )
                    continue
                calls += 1
                try:
                    raw = self.provider.invoke(
                        JudgeProviderRequest(invocation, presentation_hash)
                    )
                    if not isinstance(raw, RawJudgeResult):
                        raise FormalEvidenceError(
                            "provider did not return RawJudgeResult"
                        )
                except TimeoutError:
                    record, stage_cost_ledger = self._attempt_record(
                        invocation=invocation,
                        presentation_hash=presentation_hash,
                        outcome=JudgeCallOutcome.TIMEOUT,
                        response=None,
                        raw=None,
                        error="provider_timeout",
                        ledger=stage_cost_ledger,
                    )
                    records.append(record)
                    continue
                except Exception as error:  # provider boundary is fail-closed
                    record, stage_cost_ledger = self._attempt_record(
                        invocation=invocation,
                        presentation_hash=presentation_hash,
                        outcome=JudgeCallOutcome.PROVIDER_ERROR,
                        response=None,
                        raw=None,
                        error=f"provider_error:{type(error).__name__}",
                        ledger=stage_cost_ledger,
                    )
                    records.append(record)
                    continue
                input_tokens += raw.input_tokens
                output_tokens += raw.output_tokens
                elapsed_ms += raw.elapsed_ms
                if raw.elapsed_ms > invocation.timeout_ms:
                    record, stage_cost_ledger = self._attempt_record(
                        invocation=invocation,
                        presentation_hash=presentation_hash,
                        outcome=JudgeCallOutcome.TIMEOUT,
                        response=None,
                        raw=raw,
                        error="elapsed_ms",
                        ledger=stage_cost_ledger,
                    )
                    records.append(record)
                    continue
                budget_error = self._budget_error(
                    raw=raw,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    elapsed_ms=elapsed_ms,
                )
                if budget_error is not None:
                    record, stage_cost_ledger = self._attempt_record(
                        invocation=invocation,
                        presentation_hash=presentation_hash,
                        outcome=JudgeCallOutcome.BUDGET_EXHAUSTED,
                        response=None,
                        raw=raw,
                        error=budget_error,
                        ledger=stage_cost_ledger,
                    )
                    records.append(record)
                    continue
                try:
                    response = _parse_response(
                        raw.raw_response,
                        invocation=invocation,
                        judge_card=self.judge_card,
                    )
                except FormalEvidenceError as error:
                    record, stage_cost_ledger = self._attempt_record(
                        invocation=invocation,
                        presentation_hash=presentation_hash,
                        outcome=JudgeCallOutcome.SCHEMA_INVALID,
                        response=None,
                        raw=raw,
                        error=str(error),
                        ledger=stage_cost_ledger,
                    )
                    records.append(record)
                    continue
                record, stage_cost_ledger = self._attempt_record(
                    invocation=invocation,
                    presentation_hash=presentation_hash,
                    outcome=JudgeCallOutcome.OK,
                    response=response,
                    raw=raw,
                    error=None,
                    ledger=stage_cost_ledger,
                )
                records.append(record)
        return JudgeCorpus(
            judge_card=self.judge_card,
            calibration_manifest=self.calibration_manifest,
            attestation=self.attestation,
            budget=self.budget,
            records=tuple(records),
            stage_cost_pre_ledger=self.stage_cost_pre_ledger,
            stage_cost_ledger=stage_cost_ledger,
        )

    def _invocation(
        self,
        *,
        item_id: str,
        criterion_id: str,
        presentation: str,
        effective_seed: int,
        presentation_hash: str,
    ) -> JudgeInvocation:
        evidence_refs = (f"{self.phase}:{item_id}:evidence",)
        request_body = {
            "judge_card_hash": self.judge_card.contract_hash,
            "calibration_manifest_hash": self.calibration_manifest.contract_hash,
            "item_id": item_id,
            "criterion_id": criterion_id,
            "presentation": presentation,
            "presentation_hash": presentation_hash,
            "effective_seed": effective_seed,
            "evidence_refs": list(evidence_refs),
            "input_tokens_limit": self.input_tokens_limit,
            "output_tokens_limit": self.output_tokens_limit,
            "timeout_ms": self.timeout_ms,
        }
        return JudgeInvocation(
            invocation_id=(
                f"{self.calibration_manifest.manifest_id}.{item_id}.{presentation}"
            ),
            judge_card_hash=self.judge_card.contract_hash,
            case_id=item_id,
            criterion_id=criterion_id,
            presentation=presentation,
            effective_seed=effective_seed,
            request_fingerprint=_sha256(_canonical(request_body)),
            evidence_refs=evidence_refs,
            input_tokens_limit=self.input_tokens_limit,
            output_tokens_limit=self.output_tokens_limit,
            timeout_ms=self.timeout_ms,
        )

    def _budget_error(
        self,
        *,
        raw: RawJudgeResult,
        input_tokens: int,
        output_tokens: int,
        elapsed_ms: int,
    ) -> str | None:
        if raw.input_tokens > self.input_tokens_limit:
            return "call_input_tokens"
        if raw.output_tokens > self.output_tokens_limit:
            return "call_output_tokens"
        if input_tokens > self.budget.max_input_tokens:
            return "max_input_tokens"
        if output_tokens > self.budget.max_output_tokens:
            return "max_output_tokens"
        if elapsed_ms > self.budget.max_elapsed_ms:
            return "max_elapsed_ms"
        return None

    @staticmethod
    def _unattempted_record(
        invocation: JudgeInvocation,
        presentation_hash: str,
        error: str,
    ) -> JudgeCallRecord:
        return JudgeCallRecord(
            invocation=invocation,
            presentation_hash=presentation_hash,
            outcome=JudgeCallOutcome.BUDGET_EXHAUSTED,
            response=None,
            raw_response=b"",
            raw_response_hash=_sha256(b""),
            input_tokens=0,
            output_tokens=0,
            elapsed_ms=0,
            error=error,
            attempted=False,
            stage_cost_entry_hash=None,
        )

    def _attempt_record(
        self,
        *,
        invocation: JudgeInvocation,
        presentation_hash: str,
        outcome: JudgeCallOutcome,
        response: JudgeResponse | None,
        raw: RawJudgeResult | None,
        error: str | None,
        ledger: StageCostLedger,
    ) -> tuple[JudgeCallRecord, StageCostLedger]:
        raw_bytes = raw.raw_response if raw is not None else b""
        raw_hash = _sha256(raw_bytes)
        input_tokens = raw.input_tokens if raw is not None else 0
        output_tokens = raw.output_tokens if raw is not None else 0
        elapsed_ms = raw.elapsed_ms if raw is not None else 0
        receipt_projection = {
            "scope": "contract_test_untrusted_receipt_projection",
            "phase": self.phase,
            "provider_id": self.provider.provider_id,
            "model_id": self.provider.model_id,
            "invocation_id": invocation.invocation_id,
            "request_hash": invocation.request_fingerprint,
            "raw_response_hash": raw_hash,
            "outcome": outcome.value,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "elapsed_ms": elapsed_ms,
            "error": error,
        }
        raw_receipt_hash = _sha256(_canonical(receipt_projection))
        call_hash = _sha256(
            _canonical(
                {
                    "request_hash": invocation.request_fingerprint,
                    "raw_receipt_hash": raw_receipt_hash,
                }
            )
        )
        previous_entry_hash = (
            ledger.entries[-1].contract_hash if ledger.entries else None
        )
        entry = StageCostEntry(
            entry_id=f"{self.phase}.{len(ledger.entries):06d}",
            sequence=len(ledger.entries),
            phase=self.phase,
            category=CostCategory.JUDGE,
            outcome=(
                CostOutcome.SUCCEEDED
                if outcome is JudgeCallOutcome.OK
                else CostOutcome.FAILED
            ),
            failure_code=(None if outcome is JudgeCallOutcome.OK else outcome.value),
            request_hash=invocation.request_fingerprint,
            call_hash=call_hash,
            raw_receipt_hash=raw_receipt_hash,
            calls=1,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            wall_time_ms=elapsed_ms,
            bytes_transferred=len(raw_bytes),
            retry_count=0,
            monetary_microunits=0,
            monetary_fact=None,
            automatic_arm_execution=False,
            arm_id=None,
            provider_id=self.provider.provider_id,
            model_id=self.provider.model_id,
            cost_class="judge_provider_call.contract_test",
            retry_of_entry_hash=None,
            previous_entry_hash=previous_entry_hash,
        )
        updated = ledger.append(entry)
        return (
            JudgeCallRecord(
                invocation=invocation,
                presentation_hash=presentation_hash,
                outcome=outcome,
                response=response,
                raw_response=raw_bytes,
                raw_response_hash=raw_hash,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                elapsed_ms=elapsed_ms,
                error=error,
                attempted=True,
                stage_cost_entry_hash=entry.contract_hash,
            ),
            updated,
        )


def fuse_corpus_presentations(
    corpus: JudgeCorpus,
) -> tuple[FusedJudgeItem, ...]:
    if not isinstance(corpus, JudgeCorpus):
        raise FormalEvidenceError("fusion requires JudgeCorpus")
    fused: list[FusedJudgeItem] = []
    for index, item in enumerate(corpus.calibration_manifest.items):
        normal = corpus.records[index * 2]
        reversed_record = corpus.records[index * 2 + 1]
        if (
            normal.outcome is not JudgeCallOutcome.OK
            or reversed_record.outcome is not JudgeCallOutcome.OK
            or normal.response is None
            or reversed_record.response is None
        ):
            status = EvaluationStatus.UNKNOWN
        else:
            try:
                status = fuse_judge_presentations(
                    normal.invocation,
                    normal.response,
                    reversed_record.invocation,
                    reversed_record.response,
                )
            except ContractError as error:
                raise FormalEvidenceError(
                    "corpus presentation binding failed"
                ) from error
        fused.append(
            FusedJudgeItem(
                item_id=item.item_id,
                criterion_id=item.criterion_id,
                status=status,
                normal_record_hash=normal.contract_hash,
                reversed_record_hash=reversed_record.contract_hash,
            )
        )
    return tuple(fused)


def _wilson(successes: int, denominator: int) -> RateEstimate:
    if not 0 <= successes <= denominator or denominator <= 0:
        raise FormalEvidenceError("Wilson inputs are invalid")
    z = 1.959963984540054
    proportion = successes / denominator
    adjustment = z * z / denominator
    center = (proportion + adjustment / 2) / (1 + adjustment)
    spread = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / denominator
            + z * z / (4 * denominator * denominator)
        )
        / (1 + adjustment)
    )
    return RateEstimate(
        value=proportion,
        lower=min(proportion, max(0.0, center - spread)),
        upper=max(proportion, min(1.0, center + spread)),
        denominator=denominator,
    )


def _qualification_for(
    corpus: JudgeCorpus,
    *,
    qualification_id: str,
    evaluated_at: str,
) -> JudgeQualification:
    _text(qualification_id, "qualification_id")
    _text(evaluated_at, "evaluated_at")
    records_by_item = {
        item.item_id: corpus.records[index * 2 : index * 2 + 2]
        for index, item in enumerate(corpus.calibration_manifest.items)
    }
    ok_records = tuple(
        record
        for record in corpus.records
        if record.outcome is JudgeCallOutcome.OK and record.response is not None
    )
    false_accepts = sum(
        record.response is not None and record.response.verdict is EvaluationStatus.PASS
        for item in corpus.calibration_manifest.items
        if item.gold_verdict is EvaluationStatus.FAIL
        for record in records_by_item[item.item_id]
    )
    false_rejects = sum(
        record.response is not None and record.response.verdict is EvaluationStatus.FAIL
        for item in corpus.calibration_manifest.items
        if item.gold_verdict is EvaluationStatus.PASS
        for record in records_by_item[item.item_id]
    )
    unknowns = sum(
        record.response is None or record.response.verdict is EvaluationStatus.UNKNOWN
        for record in corpus.records
    )
    pair_disagreements = 0
    for item in corpus.calibration_manifest.items:
        responses = tuple(
            record.response
            for record in records_by_item[item.item_id]
            if record.response is not None
        )
        if len(responses) == 2 and responses[0].verdict is not responses[1].verdict:
            pair_disagreements += 1
    valid_evidence_refs = sum(
        record.response is not None
        and set(record.response.evidence_refs) <= set(record.invocation.evidence_refs)
        for record in corpus.records
    )
    order_instability = _wilson(pair_disagreements, 48)
    missing_independent_probe = RateEstimate(
        value=1.0,
        lower=1.0,
        upper=1.0,
        denominator=48,
    )
    return JudgeQualification(
        qualification_id=qualification_id,
        judge_card_hash=corpus.judge_card.contract_hash,
        set_kind=(
            "J-CAL-v1"
            if isinstance(corpus.calibration_manifest, JCalManifest)
            else "J-AUDIT-v1"
        ),
        set_hash=corpus.calibration_manifest.contract_hash,
        schema_valid=_wilson(len(ok_records), 96),
        false_accept=_wilson(false_accepts, 32),
        false_reject=_wilson(false_rejects, 32),
        unknown_rate=_wilson(unknowns, 96),
        order_flip=order_instability,
        # This legacy corpus has only normal/order-reversed calls.  Reusing
        # that pair for style and repeat would manufacture evidence, so those
        # independently registered relations remain unavailable/fail-closed.
        style_flip=missing_independent_probe,
        repeat_disagreement=missing_independent_probe,
        evidence_reference_validity=_wilson(valid_evidence_refs, 96),
        evaluated_at=evaluated_at,
    )


def _probe_qualification_for(
    corpus: ProbeJudgeCorpus,
    *,
    qualification_id: str,
    evaluated_at: str,
) -> JudgeQualification:
    from .meas0_judge_probes import derive_probe_rates

    _text(qualification_id, "qualification_id")
    _text(evaluated_at, "evaluated_at")
    verdicts = {
        record.invocation.invocation_id: (
            record.response.verdict
            if record.outcome is JudgeCallOutcome.OK and record.response is not None
            else EvaluationStatus.UNKNOWN
        )
        for record in corpus.records
    }
    probe_rates = derive_probe_rates(corpus.probe_manifest, verdicts)
    gold_by_item = {
        item.item_id: item.gold_verdict for item in corpus.calibration_manifest.items
    }
    false_accepts = sum(
        verdicts[record.invocation.invocation_id] is EvaluationStatus.PASS
        and gold_by_item[record.invocation.case_id] is EvaluationStatus.FAIL
        for record in corpus.records
    )
    false_rejects = sum(
        verdicts[record.invocation.invocation_id] is EvaluationStatus.FAIL
        and gold_by_item[record.invocation.case_id] is EvaluationStatus.PASS
        for record in corpus.records
    )
    unknowns = sum(verdict is EvaluationStatus.UNKNOWN for verdict in verdicts.values())
    schema_valid = sum(
        record.outcome is JudgeCallOutcome.OK and record.response is not None
        for record in corpus.records
    )
    evidence_valid = sum(
        record.response is not None
        and set(record.response.evidence_refs) <= set(record.invocation.evidence_refs)
        for record in corpus.records
    )
    return JudgeQualification(
        qualification_id=qualification_id,
        judge_card_hash=corpus.judge_card.contract_hash,
        set_kind=(
            "J-CAL-v1"
            if isinstance(corpus.calibration_manifest, JCalManifest)
            else "J-AUDIT-v1"
        ),
        set_hash=corpus.calibration_manifest.contract_hash,
        schema_valid=_wilson(schema_valid, 288),
        false_accept=_wilson(false_accepts, 96),
        false_reject=_wilson(false_rejects, 96),
        unknown_rate=_wilson(unknowns, 288),
        order_flip=probe_rates.order_flip,
        style_flip=probe_rates.style_flip,
        repeat_disagreement=probe_rates.repeat_disagreement,
        evidence_reference_validity=_wilson(evidence_valid, 288),
        evaluated_at=evaluated_at,
    )


def derive_probe_qualification(
    corpus: ProbeJudgeCorpus,
    *,
    qualification_id: str,
    evaluated_at: str,
) -> DerivedProbeJudgeQualification:
    """Derive all rates from the 288 calls and 144 independent relations."""

    if not isinstance(corpus, ProbeJudgeCorpus):
        raise FormalEvidenceError("probe qualification requires ProbeJudgeCorpus")
    qualification = _probe_qualification_for(
        corpus,
        qualification_id=qualification_id,
        evaluated_at=evaluated_at,
    )
    quarantine = None
    if not qualification.qualified:
        quarantine = JudgeQuarantine(
            quarantine_id=f"quarantine-{qualification_id}",
            judge_card_hash=qualification.judge_card_hash,
            qualification_hash=qualification.contract_hash,
            reason="probe qualification failed",
            quarantined_at=evaluated_at,
        )
    return DerivedProbeJudgeQualification(
        source_corpus=corpus,
        qualification=qualification,
        quarantine=quarantine,
    )


@dataclass(frozen=True)
class DerivedJudgeQualification(_HashBound):
    """Qualification whose statistics are recomputed from its source corpus."""

    source_corpus: JudgeCorpus
    qualification: JudgeQualification
    quarantine: JudgeQuarantine | None

    def __post_init__(self) -> None:
        if not isinstance(self.source_corpus, JudgeCorpus):
            raise FormalEvidenceError("derived qualification requires source corpus")
        if not isinstance(self.qualification, JudgeQualification):
            raise FormalEvidenceError("derived qualification contract is invalid")
        expected = _qualification_for(
            self.source_corpus,
            qualification_id=self.qualification.qualification_id,
            evaluated_at=self.qualification.evaluated_at,
        )
        if expected.contract_hash != self.qualification.contract_hash:
            raise FormalEvidenceError(
                "qualification statistics must be derived from source corpus"
            )
        if self.qualification.qualified:
            if self.quarantine is not None:
                raise FormalEvidenceError("qualified Judge cannot be quarantined")
        else:
            if (
                not isinstance(self.quarantine, JudgeQuarantine)
                or self.quarantine.judge_card_hash != self.qualification.judge_card_hash
                or self.quarantine.qualification_hash
                != self.qualification.contract_hash
            ):
                raise FormalEvidenceError("unqualified Judge requires bound quarantine")

    @property
    def source_corpus_hash(self) -> str:
        return self.source_corpus.contract_hash

    @property
    def attestation(self) -> EvidenceAttestation:
        return self.source_corpus.attestation

    def _body(self) -> dict[str, Any]:
        return {
            "source_corpus": self.source_corpus.to_dict(),
            "qualification": self.qualification.to_dict(),
            "quarantine": (
                self.quarantine.to_dict() if self.quarantine is not None else None
            ),
        }


def derive_jcal_qualification(
    corpus: JudgeCorpus,
    *,
    qualification_id: str,
    evaluated_at: str,
) -> DerivedJudgeQualification:
    """Derive every frozen qualification rate; accepts no statistic inputs."""

    if not isinstance(corpus, JudgeCorpus):
        raise FormalEvidenceError("qualification derivation requires JudgeCorpus")
    if not isinstance(corpus.calibration_manifest, JCalManifest):
        raise FormalEvidenceError("J-CAL qualification cannot be derived from J-AUDIT")
    qualification = _qualification_for(
        corpus,
        qualification_id=qualification_id,
        evaluated_at=evaluated_at,
    )
    quarantine = None
    if not qualification.qualified:
        failed = []
        if qualification.schema_valid.value != 1.0:
            failed.append("schema_valid")
        if qualification.false_accept.value > 0.10:
            failed.append("false_accept")
        if qualification.false_reject.value > 0.15:
            failed.append("false_reject")
        if qualification.order_flip.value > 0.10:
            failed.append("order_flip")
        if qualification.style_flip.value > 0.10:
            failed.append("style_flip")
        if qualification.evidence_reference_validity.value < 0.95:
            failed.append("evidence_reference_validity")
        quarantine = JudgeQuarantine(
            quarantine_id=f"quarantine-{qualification_id}",
            judge_card_hash=qualification.judge_card_hash,
            qualification_hash=qualification.contract_hash,
            reason="qualification failed: " + ",".join(failed),
            quarantined_at=evaluated_at,
        )
    return DerivedJudgeQualification(
        source_corpus=corpus,
        qualification=qualification,
        quarantine=quarantine,
    )


def derive_jaudit_qualification(
    corpus: JudgeCorpus,
    *,
    qualification_id: str,
    evaluated_at: str,
) -> DerivedJudgeQualification:
    """Derive an audit qualification only from an independent J-AUDIT corpus."""

    if not isinstance(corpus, JudgeCorpus):
        raise FormalEvidenceError("J-AUDIT derivation requires JudgeCorpus")
    if not isinstance(corpus.calibration_manifest, JAuditManifest):
        raise FormalEvidenceError("J-AUDIT qualification cannot reuse a J-CAL corpus")
    qualification = _qualification_for(
        corpus,
        qualification_id=qualification_id,
        evaluated_at=evaluated_at,
    )
    quarantine = None
    if not qualification.qualified:
        failed = tuple(
            name
            for name, passed in (
                ("schema_valid", qualification.schema_valid.value == 1.0),
                ("false_accept", qualification.false_accept.value <= 0.10),
                ("false_reject", qualification.false_reject.value <= 0.15),
                ("order_flip", qualification.order_flip.value <= 0.10),
                ("style_flip", qualification.style_flip.value <= 0.10),
                (
                    "evidence_reference_validity",
                    qualification.evidence_reference_validity.value >= 0.95,
                ),
            )
            if not passed
        )
        quarantine = JudgeQuarantine(
            quarantine_id=f"quarantine-{qualification_id}",
            judge_card_hash=qualification.judge_card_hash,
            qualification_hash=qualification.contract_hash,
            reason="qualification failed: " + ",".join(failed),
            quarantined_at=evaluated_at,
        )
    return DerivedJudgeQualification(
        source_corpus=corpus,
        qualification=qualification,
        quarantine=quarantine,
    )


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FormalEvidenceError(f"{label} must be an object")
    return {str(key): item for key, item in value.items()}


def _verify_declared_hash(value: Mapping[str, Any], contract: _HashBound) -> None:
    if value.get("contract_hash") != contract.contract_hash:
        raise FormalEvidenceError("serialized formal evidence hash mismatch")


def _judge_card_from_dict(value: object) -> JudgeCard:
    raw = _object(value, "JudgeCard")
    sampling = _object(raw.get("sampling_config", {}), "sampling_config")
    result = JudgeCard(
        card_id=str(raw["card_id"]),
        version=int(raw["version"]),
        provider=raw.get("provider"),
        model_id=raw.get("model_id"),
        model_digest=raw.get("model_digest"),
        prompt_hash=raw.get("prompt_hash"),
        rubric_hash=raw.get("rubric_hash"),
        parser_hash=raw.get("parser_hash"),
        sampling_config=tuple(sorted(sampling.items())),
        calibration_set_hash=raw.get("calibration_set_hash"),
        audit_set_hash=raw.get("audit_set_hash"),
        qualified_dimensions=tuple(raw.get("qualified_dimensions", ())),
        qualification_time=raw.get("qualification_time"),
    )
    if raw.get("contract_hash") != result.contract_hash:
        raise FormalEvidenceError("serialized JudgeCard hash mismatch")
    return result


def _judge_set_from_dict(
    value: object,
) -> JCalManifest | JAuditManifest:
    from .meas0_readiness import JudgeSetItem

    raw = _object(value, "J-CAL manifest")
    items = []
    for value_item in raw.get("items", ()):
        item_raw = _object(value_item, "Judge set item")
        item = JudgeSetItem(
            item_id=str(item_raw["item_id"]),
            criterion_id=str(item_raw["criterion_id"]),
            gold_verdict=EvaluationStatus(str(item_raw["gold_verdict"])),
            normal_presentation_hash=str(item_raw["normal_presentation_hash"]),
            reversed_presentation_hash=str(item_raw["reversed_presentation_hash"]),
            held_out=item_raw["held_out"],
        )
        if item_raw.get("contract_hash") != item.contract_hash:
            raise FormalEvidenceError("serialized Judge item hash mismatch")
        items.append(item)
    manifest_type = (
        JCalManifest
        if raw.get("manifest_id") == "J-CAL-v1"
        else JAuditManifest
        if raw.get("manifest_id") == "J-AUDIT-v1"
        else None
    )
    if manifest_type is None:
        raise FormalEvidenceError("serialized Judge set identity is invalid")
    result = manifest_type(
        manifest_id=str(raw["manifest_id"]),
        version=int(raw["version"]),
        effective_seeds=tuple(raw.get("effective_seeds", ())),
        items=tuple(items),
    )
    if raw.get("contract_hash") != result.contract_hash:
        raise FormalEvidenceError("serialized Judge set hash mismatch")
    return result


def _invocation_from_dict(value: object) -> JudgeInvocation:
    raw = _object(value, "Judge invocation")
    result = JudgeInvocation(
        invocation_id=str(raw["invocation_id"]),
        judge_card_hash=str(raw["judge_card_hash"]),
        case_id=str(raw["case_id"]),
        criterion_id=str(raw["criterion_id"]),
        presentation=str(raw["presentation"]),
        effective_seed=raw["effective_seed"],
        request_fingerprint=str(raw["request_fingerprint"]),
        evidence_refs=tuple(raw.get("evidence_refs", ())),
        input_tokens_limit=int(raw["input_tokens_limit"]),
        output_tokens_limit=int(raw["output_tokens_limit"]),
        timeout_ms=int(raw["timeout_ms"]),
    )
    if raw.get("contract_hash") != result.contract_hash:
        raise FormalEvidenceError("serialized invocation hash mismatch")
    return result


def _response_from_dict(value: object) -> JudgeResponse:
    raw = _object(value, "Judge response")
    result = JudgeResponse(
        invocation_id=str(raw["invocation_id"]),
        criterion_id=str(raw["criterion_id"]),
        verdict=EvaluationStatus(str(raw["verdict"])),
        evidence_refs=tuple(raw.get("evidence_refs", ())),
        rationale=str(raw["rationale"]),
        confidence_0_1=float(raw["confidence_0_1"]),
        p_pass_0_1=float(raw["p_pass_0_1"]),
        judge_version=str(raw["judge_version"]),
        raw_response_hash=str(raw["raw_response_hash"]),
    )
    if raw.get("contract_hash") != result.contract_hash:
        raise FormalEvidenceError("serialized response hash mismatch")
    return result


def _rate_from_dict(value: object) -> RateEstimate:
    raw = _object(value, "rate estimate")
    result = RateEstimate(
        value=float(raw["value"]),
        lower=float(raw["lower"]),
        upper=float(raw["upper"]),
        denominator=int(raw["denominator"]),
    )
    if raw.get("contract_hash") != result.contract_hash:
        raise FormalEvidenceError("serialized rate hash mismatch")
    return result


def _qualification_from_dict(value: object) -> JudgeQualification:
    raw = _object(value, "Judge qualification")
    result = JudgeQualification(
        qualification_id=str(raw["qualification_id"]),
        judge_card_hash=str(raw["judge_card_hash"]),
        set_kind=str(raw["set_kind"]),
        set_hash=str(raw["set_hash"]),
        schema_valid=_rate_from_dict(raw["schema_valid"]),
        false_accept=_rate_from_dict(raw["false_accept"]),
        false_reject=_rate_from_dict(raw["false_reject"]),
        unknown_rate=_rate_from_dict(raw["unknown_rate"]),
        order_flip=_rate_from_dict(raw["order_flip"]),
        style_flip=_rate_from_dict(raw["style_flip"]),
        repeat_disagreement=_rate_from_dict(raw["repeat_disagreement"]),
        evidence_reference_validity=_rate_from_dict(raw["evidence_reference_validity"]),
        evaluated_at=str(raw["evaluated_at"]),
    )
    if raw.get("contract_hash") != result.contract_hash:
        raise FormalEvidenceError("serialized qualification hash mismatch")
    return result


def _quarantine_from_dict(value: object) -> JudgeQuarantine:
    raw = _object(value, "Judge quarantine")
    result = JudgeQuarantine(
        quarantine_id=str(raw["quarantine_id"]),
        judge_card_hash=str(raw["judge_card_hash"]),
        qualification_hash=str(raw["qualification_hash"]),
        reason=str(raw["reason"]),
        quarantined_at=str(raw["quarantined_at"]),
    )
    if raw.get("contract_hash") != result.contract_hash:
        raise FormalEvidenceError("serialized quarantine hash mismatch")
    return result


def _corpus_from_dict(value: object) -> JudgeCorpus:
    raw = _object(value, "Judge corpus")
    attestation_raw = _object(raw["attestation"], "evidence attestation")
    attestation = EvidenceAttestation(
        attestation_id=str(attestation_raw["attestation_id"]),
        issuer=str(attestation_raw["issuer"]),
        issued_at=str(attestation_raw["issued_at"]),
        test_only=attestation_raw["test_only"],
    )
    _verify_declared_hash(attestation_raw, attestation)
    budget_raw = _object(raw["budget"], "Judge execution budget")
    budget = JudgeExecutionBudget(
        max_calls=int(budget_raw["max_calls"]),
        max_input_tokens=int(budget_raw["max_input_tokens"]),
        max_output_tokens=int(budget_raw["max_output_tokens"]),
        max_elapsed_ms=int(budget_raw["max_elapsed_ms"]),
    )
    _verify_declared_hash(budget_raw, budget)
    records = []
    for value_record in raw.get("records", ()):
        record_raw = _object(value_record, "Judge call record")
        encoded = record_raw.get("raw_response_base64")
        if not isinstance(encoded, str):
            raise FormalEvidenceError("sealed raw response is missing")
        try:
            raw_response = base64.b64decode(encoded, validate=True)
        except ValueError as error:
            raise FormalEvidenceError("sealed raw response is not base64") from error
        response_value = record_raw.get("response")
        record = JudgeCallRecord(
            invocation=_invocation_from_dict(record_raw["invocation"]),
            presentation_hash=str(record_raw["presentation_hash"]),
            outcome=JudgeCallOutcome(str(record_raw["outcome"])),
            response=(
                _response_from_dict(response_value)
                if response_value is not None
                else None
            ),
            raw_response=raw_response,
            raw_response_hash=str(record_raw["raw_response_hash"]),
            input_tokens=int(record_raw["input_tokens"]),
            output_tokens=int(record_raw["output_tokens"]),
            elapsed_ms=int(record_raw["elapsed_ms"]),
            error=record_raw.get("error"),
            attempted=record_raw["attempted"],
            stage_cost_entry_hash=record_raw.get("stage_cost_entry_hash"),
        )
        _verify_declared_hash(record_raw, record)
        records.append(record)
    result = JudgeCorpus(
        judge_card=_judge_card_from_dict(raw["judge_card"]),
        calibration_manifest=_judge_set_from_dict(raw["calibration_manifest"]),
        attestation=attestation,
        budget=budget,
        records=tuple(records),
        stage_cost_pre_ledger=StageCostLedger.from_dict(raw["stage_cost_pre_ledger"]),
        stage_cost_ledger=StageCostLedger.from_dict(raw["stage_cost_ledger"]),
    )
    _verify_declared_hash(raw, result)
    return result


def derived_judge_qualification_from_dict(
    value: object,
) -> DerivedJudgeQualification:
    """Restore evidence and rederive qualification from sealed raw corpus."""

    raw = _object(value, "derived Judge qualification")
    try:
        quarantine_value = raw.get("quarantine")
        result = DerivedJudgeQualification(
            source_corpus=_corpus_from_dict(raw["source_corpus"]),
            qualification=_qualification_from_dict(raw["qualification"]),
            quarantine=(
                _quarantine_from_dict(quarantine_value)
                if quarantine_value is not None
                else None
            ),
        )
        _verify_declared_hash(raw, result)
        return result
    except (KeyError, TypeError, ValueError, ContractError) as error:
        if isinstance(error, FormalEvidenceError):
            raise
        raise FormalEvidenceError(
            "serialized derived Judge evidence is malformed"
        ) from error


def derived_probe_judge_qualification_from_dict(
    value: object,
) -> DerivedProbeJudgeQualification:
    """Restore and fully rederive a sealed 288-call probe qualification."""

    from .meas0_judge_probes import JudgeProbeManifest

    raw = _object(value, "derived probe Judge qualification")
    corpus_raw = _object(raw["source_corpus"], "probe Judge corpus")
    attestation_raw = _object(
        corpus_raw["attestation"],
        "probe evidence attestation",
    )
    attestation = EvidenceAttestation(
        attestation_id=str(attestation_raw["attestation_id"]),
        issuer=str(attestation_raw["issuer"]),
        issued_at=str(attestation_raw["issued_at"]),
        test_only=attestation_raw["test_only"],
    )
    _verify_declared_hash(attestation_raw, attestation)
    records: list[JudgeCallRecord] = []
    for value_record in corpus_raw.get("records", ()):
        record_raw = _object(value_record, "probe Judge call record")
        encoded = record_raw.get("raw_response_base64")
        if not isinstance(encoded, str):
            raise FormalEvidenceError("sealed probe response is missing")
        try:
            raw_response = base64.b64decode(encoded, validate=True)
        except ValueError as error:
            raise FormalEvidenceError("sealed probe response is not base64") from error
        response_value = record_raw.get("response")
        record = JudgeCallRecord(
            invocation=_invocation_from_dict(record_raw["invocation"]),
            presentation_hash=str(record_raw["presentation_hash"]),
            outcome=JudgeCallOutcome(str(record_raw["outcome"])),
            response=(
                _response_from_dict(response_value)
                if response_value is not None
                else None
            ),
            raw_response=raw_response,
            raw_response_hash=str(record_raw["raw_response_hash"]),
            input_tokens=int(record_raw["input_tokens"]),
            output_tokens=int(record_raw["output_tokens"]),
            elapsed_ms=int(record_raw["elapsed_ms"]),
            error=record_raw.get("error"),
            attempted=record_raw["attempted"],
            stage_cost_entry_hash=record_raw.get("stage_cost_entry_hash"),
        )
        _verify_declared_hash(record_raw, record)
        records.append(record)
    probe_raw = _object(corpus_raw["probe_manifest"], "probe manifest")
    if "contract_hash" not in probe_raw:
        probe_raw["contract_hash"] = _sha256(_canonical(probe_raw))
    corpus = ProbeJudgeCorpus(
        judge_card=_judge_card_from_dict(corpus_raw["judge_card"]),
        calibration_manifest=_judge_set_from_dict(corpus_raw["calibration_manifest"]),
        probe_manifest=JudgeProbeManifest.from_dict(probe_raw),
        attestation=attestation,
        records=tuple(records),
        stage_cost_pre_ledger=StageCostLedger.from_dict(
            corpus_raw["stage_cost_pre_ledger"]
        ),
        stage_cost_ledger=StageCostLedger.from_dict(corpus_raw["stage_cost_ledger"]),
    )
    _verify_declared_hash(corpus_raw, corpus)
    quarantine_value = raw.get("quarantine")
    result = DerivedProbeJudgeQualification(
        source_corpus=corpus,
        qualification=_qualification_from_dict(raw["qualification"]),
        quarantine=(
            _quarantine_from_dict(quarantine_value)
            if quarantine_value is not None
            else None
        ),
    )
    _verify_declared_hash(raw, result)
    return result


def require_production_judge_evidence(
    evidence: DerivedJudgeQualification,
) -> JudgeQualification:
    """Reject fake/test attestations and unqualified evidence for formal use."""

    if not isinstance(evidence, DerivedJudgeQualification):
        raise FormalEvidenceError("production requires derived Judge evidence")
    if evidence.attestation.test_only:
        raise FormalEvidenceError(
            "test-only Judge evidence cannot authorize production formal execution"
        )
    if not evidence.qualification.qualified or evidence.quarantine is not None:
        raise FormalEvidenceError("Judge evidence is quarantined or unqualified")
    raise FormalEvidenceError(
        "production Judge evidence requires per-call protected trusted "
        "transport receipts; no production trust root is implemented"
    )


def require_production_probe_judge_evidence(
    evidence: DerivedProbeJudgeQualification,
) -> JudgeQualification:
    """Validate the non-transport portion of a 288-call production corpus."""

    if not isinstance(evidence, DerivedProbeJudgeQualification):
        raise FormalEvidenceError(
            "production probe evidence requires derived 288-call evidence"
        )
    if (
        evidence.attestation.test_only
        or evidence.source_corpus.probe_manifest.test_only
    ):
        raise FormalEvidenceError(
            "test-only probe evidence cannot authorize production"
        )
    if not evidence.qualification.qualified or evidence.quarantine is not None:
        raise FormalEvidenceError("probe Judge evidence is quarantined or unqualified")
    return evidence.qualification
