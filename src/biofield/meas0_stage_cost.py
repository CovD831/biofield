"""Offline, non-claim-bearing MEAS0 stage-cost contracts.

This module records caller-supplied cost facts and their ancestry.  It does not
select a production budget or price, execute a provider, approve formal
readiness, or change an experimental Gate.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping


PHASES = ("jcal", "pilot", "jaudit", "confirmatory")
_PHASE_INDEX = {phase: index for index, phase in enumerate(PHASES)}
FORMAL_ARM_IDS = (
    "self_eval",
    "judge_only",
    "state_only",
    "rules_state",
    "evaluation_plane",
)
_BUDGET_DIMENSIONS = (
    "calls",
    "input_tokens",
    "output_tokens",
    "wall_time_ms",
    "bytes_transferred",
    "retry_count",
    "monetary_microunits",
)


class StageCostError(ValueError):
    """Raised when a stage-cost artifact violates its frozen local contract."""


class CostCategory(str, Enum):
    SUBJECT = "subject"
    JUDGE = "judge"
    GATEWAY = "gateway"
    INFRA = "infra"
    HUMAN = "human"


class CostOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


_CATEGORY_INDEX = {category: index for index, category in enumerate(CostCategory)}


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
        raise StageCostError(f"{label} must be non-empty text")
    return value


def _hash(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise StageCostError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _optional_hash(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _hash(value, label)


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StageCostError(f"{label} must be a non-negative integer")
    return value


def _version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise StageCostError("version must be a positive integer")
    return value


def _timestamp(value: object, label: str) -> str:
    text = _text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise StageCostError(f"{label} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StageCostError(f"{label} must include a timezone")
    return text


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise StageCostError(f"{label} must be an object")
    return {str(key): item for key, item in value.items()}


class _HashBound:
    def _body(self) -> dict[str, Any]:
        raise NotImplementedError

    @property
    def contract_hash(self) -> str:
        return _sha256(_canonical(self._body()))

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "contract_hash": self.contract_hash}


def _verify_hash(raw: Mapping[str, Any], value: _HashBound) -> None:
    if raw.get("contract_hash") != value.contract_hash:
        raise StageCostError("serialized stage-cost contract hash mismatch")


@dataclass(frozen=True)
class PriceQuote(_HashBound):
    """One provider/model price quote; values are supplied, never invented."""

    schema_version: int
    quote_id: str
    provider_id: str
    model_id: str
    currency: str
    effective_at: str
    expires_at: str
    input_per_million_microunits: int
    output_per_million_microunits: int
    per_call_microunits: int

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise StageCostError("price quote schema_version must equal one")
        for field_name in (
            "quote_id",
            "provider_id",
            "model_id",
            "currency",
        ):
            _text(getattr(self, field_name), field_name)
        effective = _timestamp(self.effective_at, "effective_at")
        expires = _timestamp(self.expires_at, "expires_at")
        if datetime.fromisoformat(effective.replace("Z", "+00:00")) >= (
            datetime.fromisoformat(expires.replace("Z", "+00:00"))
        ):
            raise StageCostError("price quote validity interval is empty")
        for field_name in (
            "input_per_million_microunits",
            "output_per_million_microunits",
            "per_call_microunits",
        ):
            _non_negative_int(getattr(self, field_name), field_name)

    def _body(self) -> dict[str, Any]:
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, value: object) -> PriceQuote:
        raw = _object(value, "price quote")
        try:
            result = cls(
                **{
                    field_name: raw[field_name]
                    for field_name in cls.__dataclass_fields__
                }
            )
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, StageCostError):
                raise
            raise StageCostError("serialized price quote is invalid") from error
        _verify_hash(raw, result)
        return result


@dataclass(frozen=True)
class PriceQuoteReceipt(_HashBound):
    """Raw detached-signature receipt whose payload is exactly one quote."""

    schema_version: int
    quote: PriceQuote
    envelope: object

    def __post_init__(self) -> None:
        from .meas0_trust import SignatureEnvelope, TrustDomain

        if self.schema_version != 1:
            raise StageCostError("price quote receipt schema_version must equal one")
        if not isinstance(self.quote, PriceQuote):
            raise StageCostError("price quote receipt requires a typed quote")
        if (
            not isinstance(self.envelope, SignatureEnvelope)
            or self.envelope.trust_domain is not TrustDomain.TRANSPORT
            or self.envelope.payload_hash != self.quote.contract_hash
        ):
            raise StageCostError(
                "price quote receipt signature does not bind the typed quote"
            )

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "quote": self.quote.to_dict(),
            "envelope": self.envelope.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> PriceQuoteReceipt:
        from .meas0_trust import SignatureEnvelope

        raw = _object(value, "price quote receipt")
        try:
            result = cls(
                schema_version=raw["schema_version"],
                quote=PriceQuote.from_dict(raw["quote"]),
                envelope=SignatureEnvelope.from_dict(raw["envelope"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, StageCostError):
                raise
            raise StageCostError("serialized price quote receipt is invalid") from error
        _verify_hash(raw, result)
        return result


_PRICE_RECEIPT_CONTRACT_TOKEN = object()


@dataclass(frozen=True)
class PriceManifestReceiptContract(_HashBound):
    """Derived quote-receipt ancestry; never trusts a serialized readiness flag."""

    schema_version: int
    price_manifest_hash: str
    quote_receipt_hashes: tuple[str, ...]
    verification_result_hashes: tuple[str, ...]
    production_ready: bool
    _derivation_token: object = dataclass_field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self._derivation_token is not _PRICE_RECEIPT_CONTRACT_TOKEN:
            raise StageCostError(
                "price manifest receipt contract must be derived from raw receipts"
            )
        if self.schema_version != 1:
            raise StageCostError(
                "price manifest receipt contract schema_version must equal one"
            )
        _hash(self.price_manifest_hash, "price manifest hash")
        receipts = tuple(
            _hash(item, "quote receipt hash") for item in self.quote_receipt_hashes
        )
        results = tuple(
            _hash(item, "verification result hash")
            for item in self.verification_result_hashes
        )
        if not receipts or len(receipts) != len(results):
            raise StageCostError(
                "price receipt and verification membership must be non-empty and exact"
            )
        if len(set(receipts)) != len(receipts):
            raise StageCostError("price quote receipt membership must be unique")
        if not isinstance(self.production_ready, bool):
            raise StageCostError("production_ready must be derived boolean")
        object.__setattr__(self, "quote_receipt_hashes", receipts)
        object.__setattr__(self, "verification_result_hashes", results)

    @classmethod
    def derive_candidate(
        cls,
        *,
        price_manifest_hash: str,
        quote_receipt_hashes: tuple[str, ...],
        verification_result_hashes: tuple[str, ...],
    ) -> PriceManifestReceiptContract:
        """Bind candidate receipts while explicitly retaining fail-closed status."""

        return cls(
            schema_version=1,
            price_manifest_hash=price_manifest_hash,
            quote_receipt_hashes=quote_receipt_hashes,
            verification_result_hashes=verification_result_hashes,
            production_ready=False,
            _derivation_token=_PRICE_RECEIPT_CONTRACT_TOKEN,
        )

    @classmethod
    def derive_from_raw_receipts(
        cls,
        *,
        price_manifest: object,
        receipts: tuple[PriceQuoteReceipt, ...],
        verifier: object,
        root_manifest: object,
        policy: object,
    ) -> PriceManifestReceiptContract:
        """Reverify every raw quote envelope and re-derive manifest membership."""

        from .meas0_trust import (
            ProductionSignatureVerifier,
            ProductionVerificationResult,
            TrustDomain,
        )

        matcher = getattr(price_manifest, "matches_quote_receipts", None)
        manifest_hash = getattr(price_manifest, "contract_hash", None)
        if (
            not callable(matcher)
            or not matcher(receipts)
            or not isinstance(manifest_hash, str)
            or not receipts
        ):
            raise StageCostError(
                "price manifest cannot be re-derived from quote receipts"
            )
        results = tuple(
            verifier.verify_signature_envelope(
                envelope=receipt.envelope,
                payload_hash=receipt.quote.contract_hash,
                root_manifest=root_manifest,
                policy=policy,
            )
            for receipt in receipts
        )
        production_ready = isinstance(verifier, ProductionSignatureVerifier) and all(
            isinstance(result, ProductionVerificationResult)
            and result.authority.trust_domain is TrustDomain.TRANSPORT
            and result.payload_hash == receipt.quote.contract_hash
            and result.policy_hash == getattr(policy, "contract_hash", None)
            and result.root_manifest_hash
            == getattr(root_manifest, "contract_hash", None)
            for receipt, result in zip(receipts, results, strict=True)
        )
        return cls(
            schema_version=1,
            price_manifest_hash=manifest_hash,
            quote_receipt_hashes=tuple(item.contract_hash for item in receipts),
            verification_result_hashes=tuple(item.contract_hash for item in results),
            production_ready=production_ready,
            _derivation_token=_PRICE_RECEIPT_CONTRACT_TOKEN,
        )

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "price_manifest_hash": self.price_manifest_hash,
            "quote_receipt_hashes": list(self.quote_receipt_hashes),
            "verification_result_hashes": list(self.verification_result_hashes),
            "production_ready": self.production_ready,
        }

    @classmethod
    def from_dict(cls, value: object) -> PriceManifestReceiptContract:
        raw = _object(value, "price manifest receipt contract")
        if raw.get("production_ready") is not False:
            raise StageCostError(
                "serialized price receipt production_ready is not derivable"
            )
        result = cls.derive_candidate(
            price_manifest_hash=raw.get("price_manifest_hash"),
            quote_receipt_hashes=tuple(raw.get("quote_receipt_hashes", ())),
            verification_result_hashes=tuple(raw.get("verification_result_hashes", ())),
        )
        _verify_hash(raw, result)
        return result


@dataclass(frozen=True)
class MonetaryCostFact(_HashBound):
    """Caller-supplied monetary fact bound to a frozen PriceManifest ancestry."""

    price_manifest_hash: str
    derivation_basis_hash: str
    monetary_microunits: int

    def __post_init__(self) -> None:
        _hash(self.price_manifest_hash, "PriceManifest hash")
        _hash(self.derivation_basis_hash, "monetary derivation basis hash")
        if (
            _non_negative_int(
                self.monetary_microunits,
                "monetary microunits",
            )
            == 0
        ):
            raise StageCostError("zero monetary cost must not carry a monetary fact")

    def _body(self) -> dict[str, Any]:
        return {
            "price_manifest_hash": self.price_manifest_hash,
            "derivation_basis_hash": self.derivation_basis_hash,
            "monetary_microunits": self.monetary_microunits,
        }

    @classmethod
    def from_dict(cls, value: object) -> MonetaryCostFact:
        raw = _object(value, "monetary cost fact")
        try:
            result = cls(
                price_manifest_hash=raw["price_manifest_hash"],
                derivation_basis_hash=raw["derivation_basis_hash"],
                monetary_microunits=raw["monetary_microunits"],
            )
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, StageCostError):
                raise
            raise StageCostError("serialized monetary cost fact is invalid") from error
        _verify_hash(raw, result)
        return result


@dataclass(frozen=True)
class CategoryCallCap(_HashBound):
    """A phase-local call cap for exactly one cost category."""

    category: CostCategory
    max_calls: int

    def __post_init__(self) -> None:
        if not isinstance(self.category, CostCategory):
            raise StageCostError("category call cap category is invalid")
        _non_negative_int(self.max_calls, "category max_calls")

    def _body(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "max_calls": self.max_calls,
        }

    @classmethod
    def from_dict(cls, value: object) -> CategoryCallCap:
        raw = _object(value, "category call cap")
        try:
            result = cls(
                category=CostCategory(raw["category"]),
                max_calls=raw["max_calls"],
            )
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, StageCostError):
                raise
            raise StageCostError("serialized category call cap is invalid") from error
        _verify_hash(raw, result)
        return result


@dataclass(frozen=True)
class PhaseBudget(_HashBound):
    """A caller-approved phase budget; this module supplies no default values."""

    phase: str
    max_calls: int
    max_input_tokens: int
    max_output_tokens: int
    max_wall_time_ms: int
    max_bytes_transferred: int
    max_retries: int
    max_monetary_microunits: int
    counts_toward_per_arm_equality: bool
    category_call_caps: tuple[CategoryCallCap, ...]

    def __post_init__(self) -> None:
        if self.phase not in PHASES:
            raise StageCostError("phase budget has an invalid phase")
        for field_name in (
            "max_calls",
            "max_input_tokens",
            "max_output_tokens",
            "max_wall_time_ms",
            "max_bytes_transferred",
            "max_retries",
            "max_monetary_microunits",
        ):
            _non_negative_int(getattr(self, field_name), field_name)
        if not isinstance(self.counts_toward_per_arm_equality, bool):
            raise StageCostError("counts_toward_per_arm_equality must be boolean")
        expected = self.phase in {"pilot", "confirmatory"}
        if self.counts_toward_per_arm_equality is not expected:
            if self.phase in {"jcal", "jaudit"}:
                raise StageCostError(
                    "qualification phase budget cannot enter per-arm equality"
                )
            raise StageCostError(
                "automatic experiment phase budget must support per-arm equality"
            )
        caps = tuple(self.category_call_caps)
        if (
            len(caps) != len(CostCategory)
            or not all(isinstance(item, CategoryCallCap) for item in caps)
            or {item.category for item in caps} != set(CostCategory)
        ):
            raise StageCostError(
                "phase budget requires exactly one cap for every cost category"
            )
        object.__setattr__(
            self,
            "category_call_caps",
            tuple(sorted(caps, key=lambda item: _CATEGORY_INDEX[item.category])),
        )

    def category_call_cap(self, category: CostCategory) -> int:
        if not isinstance(category, CostCategory):
            raise StageCostError("cost category is invalid")
        return next(
            item.max_calls
            for item in self.category_call_caps
            if item.category is category
        )

    def _body(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "max_calls": self.max_calls,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_wall_time_ms": self.max_wall_time_ms,
            "max_bytes_transferred": self.max_bytes_transferred,
            "max_retries": self.max_retries,
            "max_monetary_microunits": self.max_monetary_microunits,
            "counts_toward_per_arm_equality": (self.counts_toward_per_arm_equality),
            "category_call_caps": [item.to_dict() for item in self.category_call_caps],
        }

    @classmethod
    def from_dict(cls, value: object) -> PhaseBudget:
        raw = _object(value, "phase budget")
        try:
            result = cls(
                phase=raw["phase"],
                max_calls=raw["max_calls"],
                max_input_tokens=raw["max_input_tokens"],
                max_output_tokens=raw["max_output_tokens"],
                max_wall_time_ms=raw["max_wall_time_ms"],
                max_bytes_transferred=raw["max_bytes_transferred"],
                max_retries=raw["max_retries"],
                max_monetary_microunits=raw["max_monetary_microunits"],
                counts_toward_per_arm_equality=raw["counts_toward_per_arm_equality"],
                category_call_caps=tuple(
                    CategoryCallCap.from_dict(item)
                    for item in raw["category_call_caps"]
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, StageCostError):
                raise
            raise StageCostError("serialized phase budget is invalid") from error
        _verify_hash(raw, result)
        return result


@dataclass(frozen=True)
class StageBudgetManifest(_HashBound):
    manifest_id: str
    version: int
    phase_budgets: tuple[PhaseBudget, ...]

    def __post_init__(self) -> None:
        _text(self.manifest_id, "budget manifest_id")
        _version(self.version)
        supplied = tuple(self.phase_budgets)
        if (
            len(supplied) != len(PHASES)
            or not all(isinstance(item, PhaseBudget) for item in supplied)
            or {item.phase for item in supplied} != set(PHASES)
        ):
            raise StageCostError(
                "budget manifest requires exactly one budget for every phase"
            )
        object.__setattr__(
            self,
            "phase_budgets",
            tuple(sorted(supplied, key=lambda item: _PHASE_INDEX[item.phase])),
        )

    def for_phase(self, phase: str) -> PhaseBudget:
        if phase not in PHASES:
            raise StageCostError("stage-cost phase is invalid")
        return next(item for item in self.phase_budgets if item.phase == phase)

    def _body(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "version": self.version,
            "phase_budgets": [item.to_dict() for item in self.phase_budgets],
        }

    @classmethod
    def from_dict(cls, value: object) -> StageBudgetManifest:
        raw = _object(value, "stage budget manifest")
        try:
            result = cls(
                manifest_id=raw["manifest_id"],
                version=raw["version"],
                phase_budgets=tuple(
                    PhaseBudget.from_dict(item) for item in raw["phase_budgets"]
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, StageCostError):
                raise
            raise StageCostError(
                "serialized stage budget manifest is invalid"
            ) from error
        _verify_hash(raw, result)
        return result


@dataclass(frozen=True)
class StageCostEntry(_HashBound):
    entry_id: str
    sequence: int
    phase: str
    category: CostCategory
    outcome: CostOutcome
    failure_code: str | None
    request_hash: str
    call_hash: str
    raw_receipt_hash: str
    calls: int
    input_tokens: int
    output_tokens: int
    wall_time_ms: int
    bytes_transferred: int
    retry_count: int
    monetary_microunits: int
    monetary_fact: MonetaryCostFact | None
    automatic_arm_execution: bool
    arm_id: str | None
    provider_id: str
    model_id: str
    cost_class: str
    retry_of_entry_hash: str | None
    previous_entry_hash: str | None

    def __post_init__(self) -> None:
        _text(self.entry_id, "stage-cost entry_id")
        _non_negative_int(self.sequence, "stage-cost sequence")
        if self.phase not in PHASES:
            raise StageCostError("stage-cost entry phase is invalid")
        if not isinstance(self.category, CostCategory):
            raise StageCostError("stage-cost category is invalid")
        if not isinstance(self.outcome, CostOutcome):
            raise StageCostError("stage-cost outcome is invalid")
        if self.outcome is CostOutcome.SUCCEEDED:
            if self.failure_code is not None:
                raise StageCostError("successful entry must not carry failure_code")
        elif self.failure_code is None:
            raise StageCostError("failed entry requires failure_code")
        else:
            _text(self.failure_code, "failure_code")
        for field_name in ("request_hash", "call_hash", "raw_receipt_hash"):
            _hash(getattr(self, field_name), field_name)
        for field_name in (
            "calls",
            "input_tokens",
            "output_tokens",
            "wall_time_ms",
            "bytes_transferred",
            "retry_count",
            "monetary_microunits",
        ):
            _non_negative_int(getattr(self, field_name), field_name)
        if self.calls != 1:
            raise StageCostError(
                "each stage-cost entry must represent exactly one attempt"
            )
        if self.retry_count not in {0, 1}:
            raise StageCostError("a retry must be represented by one separate entry")
        _optional_hash(self.retry_of_entry_hash, "retry entry hash")
        if (self.retry_count == 1) != (self.retry_of_entry_hash is not None):
            raise StageCostError(
                "retry_count and retry ancestry must identify one separate retry"
            )
        if self.monetary_microunits:
            if (
                not isinstance(self.monetary_fact, MonetaryCostFact)
                or self.monetary_fact.monetary_microunits != self.monetary_microunits
            ):
                raise StageCostError(
                    "non-zero monetary cost requires a matching monetary fact"
                )
        elif self.monetary_fact is not None:
            raise StageCostError("zero monetary cost cannot carry a monetary fact")
        if not isinstance(self.automatic_arm_execution, bool):
            raise StageCostError("automatic_arm_execution must be boolean")
        if self.automatic_arm_execution and self.phase not in {
            "pilot",
            "confirmatory",
        }:
            raise StageCostError(
                "qualification phase cannot contain an automatic arm entry"
            )
        if self.automatic_arm_execution:
            if self.arm_id not in FORMAL_ARM_IDS:
                raise StageCostError("automatic entry requires a frozen arm_id")
        elif self.arm_id is not None:
            raise StageCostError("non-automatic entry cannot carry arm_id")
        _text(self.provider_id, "provider_id")
        _text(self.model_id, "model_id")
        _text(self.cost_class, "cost_class")
        _optional_hash(self.previous_entry_hash, "previous entry hash")

    def _body(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "sequence": self.sequence,
            "phase": self.phase,
            "category": self.category.value,
            "outcome": self.outcome.value,
            "failure_code": self.failure_code,
            "request_hash": self.request_hash,
            "call_hash": self.call_hash,
            "raw_receipt_hash": self.raw_receipt_hash,
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "wall_time_ms": self.wall_time_ms,
            "bytes_transferred": self.bytes_transferred,
            "retry_count": self.retry_count,
            "monetary_microunits": self.monetary_microunits,
            "monetary_fact": (
                self.monetary_fact.to_dict() if self.monetary_fact is not None else None
            ),
            "automatic_arm_execution": self.automatic_arm_execution,
            "arm_id": self.arm_id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "cost_class": self.cost_class,
            "retry_of_entry_hash": self.retry_of_entry_hash,
            "previous_entry_hash": self.previous_entry_hash,
        }

    @classmethod
    def from_dict(cls, value: object) -> StageCostEntry:
        raw = _object(value, "stage-cost entry")
        try:
            monetary_raw = raw["monetary_fact"]
            result = cls(
                entry_id=raw["entry_id"],
                sequence=raw["sequence"],
                phase=raw["phase"],
                category=CostCategory(raw["category"]),
                outcome=CostOutcome(raw["outcome"]),
                failure_code=raw["failure_code"],
                request_hash=raw["request_hash"],
                call_hash=raw["call_hash"],
                raw_receipt_hash=raw["raw_receipt_hash"],
                calls=raw["calls"],
                input_tokens=raw["input_tokens"],
                output_tokens=raw["output_tokens"],
                wall_time_ms=raw["wall_time_ms"],
                bytes_transferred=raw["bytes_transferred"],
                retry_count=raw["retry_count"],
                monetary_microunits=raw["monetary_microunits"],
                monetary_fact=(
                    MonetaryCostFact.from_dict(monetary_raw)
                    if monetary_raw is not None
                    else None
                ),
                automatic_arm_execution=raw["automatic_arm_execution"],
                arm_id=raw["arm_id"],
                provider_id=raw["provider_id"],
                model_id=raw["model_id"],
                cost_class=raw["cost_class"],
                retry_of_entry_hash=raw["retry_of_entry_hash"],
                previous_entry_hash=raw["previous_entry_hash"],
            )
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, StageCostError):
                raise
            raise StageCostError("serialized stage-cost entry is invalid") from error
        _verify_hash(raw, result)
        return result


@dataclass(frozen=True)
class StageTotals:
    retained_entry_count: int = 0
    failed_entry_count: int = 0
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    wall_time_ms: int = 0
    bytes_transferred: int = 0
    retry_count: int = 0
    monetary_microunits: int = 0

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            _non_negative_int(getattr(self, field_name), field_name)

    def __add__(self, other: StageTotals) -> StageTotals:
        if not isinstance(other, StageTotals):
            return NotImplemented
        return StageTotals(
            **{
                field_name: getattr(self, field_name) + getattr(other, field_name)
                for field_name in self.__dataclass_fields__
            }
        )

    def to_dict(self) -> dict[str, int]:
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
        }

    @classmethod
    def from_entry(cls, entry: StageCostEntry) -> StageTotals:
        return cls(
            retained_entry_count=1,
            failed_entry_count=int(entry.outcome is CostOutcome.FAILED),
            calls=entry.calls,
            input_tokens=entry.input_tokens,
            output_tokens=entry.output_tokens,
            wall_time_ms=entry.wall_time_ms,
            bytes_transferred=entry.bytes_transferred,
            retry_count=entry.retry_count,
            monetary_microunits=entry.monetary_microunits,
        )


@dataclass(frozen=True)
class PhaseBudgetDecision:
    phase: str
    totals: StageTotals
    stopped: bool
    trigger_entry_hash: str | None
    exceeded_dimensions: tuple[str, ...]

    @property
    def retained_entry_count(self) -> int:
        return self.totals.retained_entry_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "totals": self.totals.to_dict(),
            "stopped": self.stopped,
            "trigger_entry_hash": self.trigger_entry_hash,
            "exceeded_dimensions": list(self.exceeded_dimensions),
        }


def _exceeded(
    totals: StageTotals,
    budget: PhaseBudget,
    category_totals: Mapping[CostCategory, StageTotals],
) -> tuple[str, ...]:
    caps = {
        "calls": budget.max_calls,
        "input_tokens": budget.max_input_tokens,
        "output_tokens": budget.max_output_tokens,
        "wall_time_ms": budget.max_wall_time_ms,
        "bytes_transferred": budget.max_bytes_transferred,
        "retry_count": budget.max_retries,
        "monetary_microunits": budget.max_monetary_microunits,
    }
    dimensions = tuple(
        dimension
        for dimension in _BUDGET_DIMENSIONS
        if getattr(totals, dimension) > caps[dimension]
    )
    category_dimensions = tuple(
        f"category_calls:{category.value}"
        for category in CostCategory
        if category_totals[category].calls > budget.category_call_cap(category)
    )
    return (*dimensions, *category_dimensions)


@dataclass(frozen=True)
class StageCostLedger(_HashBound):
    ledger_id: str
    version: int
    price_manifest_hash: str
    budget_manifest: StageBudgetManifest
    entries: tuple[StageCostEntry, ...]

    def __post_init__(self) -> None:
        _text(self.ledger_id, "stage-cost ledger_id")
        _version(self.version)
        _hash(self.price_manifest_hash, "ledger PriceManifest hash")
        if not isinstance(self.budget_manifest, StageBudgetManifest):
            raise StageCostError("stage-cost ledger requires a budget manifest")
        entries = tuple(self.entries)
        if not all(isinstance(item, StageCostEntry) for item in entries):
            raise StageCostError("stage-cost ledger entries are invalid")
        object.__setattr__(self, "entries", entries)
        if len({item.entry_id for item in entries}) != len(entries):
            raise StageCostError("stage-cost entry IDs contain a duplicate")
        decisions: dict[str, PhaseBudgetDecision] = {}
        previous: StageCostEntry | None = None
        previous_phase_index = -1
        phase_totals = {phase: StageTotals() for phase in PHASES}
        phase_category_totals = {
            phase: {category: StageTotals() for category in CostCategory}
            for phase in PHASES
        }
        stopped = {phase: False for phase in PHASES}
        stop_trigger: dict[str, StageCostEntry] = {}
        entries_by_hash: dict[str, StageCostEntry] = {}
        for expected_sequence, entry in enumerate(entries):
            if entry.sequence != expected_sequence:
                raise StageCostError("stage-cost entry sequence is not contiguous")
            expected_previous = previous.contract_hash if previous is not None else None
            if entry.previous_entry_hash != expected_previous:
                raise StageCostError("stage-cost hash chain is broken")
            if entry.retry_of_entry_hash is not None:
                retry_target = entries_by_hash.get(entry.retry_of_entry_hash)
                if retry_target is None or (
                    entry.phase,
                    entry.category,
                    entry.arm_id,
                    entry.provider_id,
                    entry.model_id,
                    entry.cost_class,
                    entry.request_hash,
                ) != (
                    retry_target.phase,
                    retry_target.category,
                    retry_target.arm_id,
                    retry_target.provider_id,
                    retry_target.model_id,
                    retry_target.cost_class,
                    retry_target.request_hash,
                ):
                    raise StageCostError("stage-cost retry ancestry is invalid")
            phase_index = _PHASE_INDEX[entry.phase]
            if phase_index < previous_phase_index:
                raise StageCostError("stage-cost phase order regressed")
            if stopped[entry.phase]:
                trigger = stop_trigger[entry.phase]
                if (
                    entry.request_hash != trigger.request_hash
                    or entry.retry_count
                    or (
                        entry.phase,
                        entry.category,
                        entry.automatic_arm_execution,
                        entry.arm_id,
                        entry.provider_id,
                        entry.model_id,
                        entry.cost_class,
                    )
                    != (
                        trigger.phase,
                        trigger.category,
                        trigger.automatic_arm_execution,
                        trigger.arm_id,
                        trigger.provider_id,
                        trigger.model_id,
                        trigger.cost_class,
                    )
                ):
                    raise StageCostError(
                        "stage-cost entry appears after phase budget stop"
                    )
            if (
                entry.monetary_fact is not None
                and entry.monetary_fact.price_manifest_hash != self.price_manifest_hash
            ):
                raise StageCostError(
                    "monetary fact PriceManifest ancestry does not match ledger"
                )
            phase_totals[entry.phase] = phase_totals[
                entry.phase
            ] + StageTotals.from_entry(entry)
            phase_category_totals[entry.phase][entry.category] = phase_category_totals[
                entry.phase
            ][entry.category] + StageTotals.from_entry(entry)
            exceeded = _exceeded(
                phase_totals[entry.phase],
                self.budget_manifest.for_phase(entry.phase),
                phase_category_totals[entry.phase],
            )
            if exceeded and not stopped[entry.phase]:
                stopped[entry.phase] = True
                stop_trigger[entry.phase] = entry
                decisions[entry.phase] = PhaseBudgetDecision(
                    phase=entry.phase,
                    totals=phase_totals[entry.phase],
                    stopped=True,
                    trigger_entry_hash=entry.contract_hash,
                    exceeded_dimensions=exceeded,
                )
            previous = entry
            previous_phase_index = phase_index
            entries_by_hash[entry.contract_hash] = entry
        for phase in PHASES:
            if phase not in decisions:
                decisions[phase] = PhaseBudgetDecision(
                    phase=phase,
                    totals=phase_totals[phase],
                    stopped=False,
                    trigger_entry_hash=None,
                    exceeded_dimensions=(),
                )

    @property
    def all_in_totals(self) -> StageTotals:
        result = StageTotals()
        for entry in self.entries:
            result += StageTotals.from_entry(entry)
        return result

    @property
    def per_arm_equality_totals(self) -> StageTotals:
        result = StageTotals()
        for entry in self.entries:
            if entry.automatic_arm_execution:
                result += StageTotals.from_entry(entry)
        return result

    @property
    def category_totals(self) -> dict[CostCategory, StageTotals]:
        totals = {category: StageTotals() for category in CostCategory}
        for entry in self.entries:
            totals[entry.category] = totals[entry.category] + StageTotals.from_entry(
                entry
            )
        return totals

    @property
    def phase_arm_category_totals(
        self,
    ) -> dict[str, dict[str, dict[str, StageTotals]]]:
        """Derived automatic-execution totals for each phase, arm, and category."""

        totals = {
            phase: {
                arm_id: {category.value: StageTotals() for category in CostCategory}
                for arm_id in FORMAL_ARM_IDS
            }
            for phase in PHASES
        }
        for entry in self.entries:
            if not entry.automatic_arm_execution:
                continue
            assert entry.arm_id is not None
            current = totals[entry.phase][entry.arm_id][entry.category.value]
            totals[entry.phase][entry.arm_id][entry.category.value] = (
                current + StageTotals.from_entry(entry)
            )
        return totals

    @property
    def production_ready(self) -> bool:
        """Current ledger lacks typed receipt and price rederivation evidence."""

        return False

    def production_ready_from_price_receipts(
        self,
        *,
        price_manifest: object,
        quote_receipts: tuple[PriceQuoteReceipt, ...],
        receipt_contract: PriceManifestReceiptContract,
    ) -> bool:
        """Re-derive PriceManifest ancestry instead of trusting a ledger flag."""

        if (
            not isinstance(receipt_contract, PriceManifestReceiptContract)
            or not receipt_contract.production_ready
            or getattr(price_manifest, "contract_hash", None)
            != self.price_manifest_hash
            or receipt_contract.price_manifest_hash != self.price_manifest_hash
            or receipt_contract.quote_receipt_hashes
            != tuple(item.contract_hash for item in quote_receipts)
        ):
            return False
        matcher = getattr(price_manifest, "matches_quote_receipts", None)
        return callable(matcher) and bool(matcher(quote_receipts))

    def phase_decision(self, phase: str) -> PhaseBudgetDecision:
        budget = self.budget_manifest.for_phase(phase)
        totals = StageTotals()
        category_totals = {category: StageTotals() for category in CostCategory}
        trigger_entry_hash: str | None = None
        exceeded_dimensions: tuple[str, ...] = ()
        trigger_request_hash: str | None = None
        for entry in self.entries:
            if entry.phase != phase:
                continue
            if (
                trigger_request_hash is not None
                and entry.request_hash != trigger_request_hash
            ):
                break
            totals += StageTotals.from_entry(entry)
            category_totals[entry.category] = category_totals[
                entry.category
            ] + StageTotals.from_entry(entry)
            exceeded = _exceeded(totals, budget, category_totals)
            if exceeded and trigger_entry_hash is None:
                trigger_entry_hash = entry.contract_hash
                exceeded_dimensions = exceeded
                trigger_request_hash = entry.request_hash
        if trigger_entry_hash is not None:
            return PhaseBudgetDecision(
                phase=phase,
                totals=totals,
                stopped=True,
                trigger_entry_hash=trigger_entry_hash,
                exceeded_dimensions=exceeded_dimensions,
            )
        return PhaseBudgetDecision(
            phase=phase,
            totals=totals,
            stopped=False,
            trigger_entry_hash=None,
            exceeded_dimensions=(),
        )

    def append(self, entry: StageCostEntry) -> StageCostLedger:
        """Return a new validated ledger whose only change is one tail entry."""

        if not isinstance(entry, StageCostEntry):
            raise StageCostError("append requires a typed stage-cost entry")
        expected_sequence = len(self.entries)
        expected_previous = self.entries[-1].contract_hash if self.entries else None
        if (
            entry.sequence != expected_sequence
            or entry.previous_entry_hash != expected_previous
        ):
            raise StageCostError("appended entry does not match the chain tail")
        return StageCostLedger(
            ledger_id=self.ledger_id,
            version=self.version,
            price_manifest_hash=self.price_manifest_hash,
            budget_manifest=self.budget_manifest,
            entries=(*self.entries, entry),
        )

    def _body(self) -> dict[str, Any]:
        return {
            "ledger_id": self.ledger_id,
            "version": self.version,
            "price_manifest_hash": self.price_manifest_hash,
            "budget_manifest": self.budget_manifest.to_dict(),
            "entries": [item.to_dict() for item in self.entries],
            "phase_decisions": {
                phase: self.phase_decision(phase).to_dict() for phase in PHASES
            },
            "all_in_totals": self.all_in_totals.to_dict(),
            "per_arm_equality_totals": (self.per_arm_equality_totals.to_dict()),
            "category_totals": {
                category.value: self.category_totals[category].to_dict()
                for category in CostCategory
            },
            "phase_arm_category_totals": {
                phase: {
                    arm_id: {
                        category: total.to_dict()
                        for category, total in categories.items()
                    }
                    for arm_id, categories in arms.items()
                }
                for phase, arms in self.phase_arm_category_totals.items()
            },
            "production_ready": self.production_ready,
        }

    @classmethod
    def from_dict(cls, value: object) -> StageCostLedger:
        raw = _object(value, "stage-cost ledger")
        try:
            result = cls(
                ledger_id=raw["ledger_id"],
                version=raw["version"],
                price_manifest_hash=raw["price_manifest_hash"],
                budget_manifest=StageBudgetManifest.from_dict(raw["budget_manifest"]),
                entries=tuple(
                    StageCostEntry.from_dict(item) for item in raw["entries"]
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, StageCostError):
                raise
            raise StageCostError("serialized stage-cost ledger is invalid") from error
        expected = result.to_dict()
        if raw.get("production_ready") is not False:
            raise StageCostError(
                "serialized stage-cost production_ready is not derived"
            )
        for field_name in (
            "phase_decisions",
            "all_in_totals",
            "per_arm_equality_totals",
            "category_totals",
            "phase_arm_category_totals",
        ):
            if raw.get(field_name) != expected[field_name]:
                raise StageCostError(
                    f"serialized stage-cost {field_name} is not derived"
                )
        _verify_hash(raw, result)
        return result


__all__ = [
    "CategoryCallCap",
    "CostCategory",
    "CostOutcome",
    "FORMAL_ARM_IDS",
    "MonetaryCostFact",
    "PHASES",
    "PhaseBudget",
    "PhaseBudgetDecision",
    "PriceManifestReceiptContract",
    "PriceQuote",
    "PriceQuoteReceipt",
    "StageBudgetManifest",
    "StageCostEntry",
    "StageCostError",
    "StageCostLedger",
    "StageTotals",
]
