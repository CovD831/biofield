"""Fail-closed contracts for deciding whether MEAS0 may run formally.

This module deliberately performs no model calls, human review, process
isolation, or price lookup.  It defines the records those external activities
must produce and refuses formal execution while any required binding is absent.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .measurement import EvaluationStatus
from .meas0_human import (
    BlindReviewRecord as DerivedBlindReviewRecord,
    HumanAttestationKind,
    HumanReviewAssessment,
    HumanReviewEvidence,
    ReviewAdjudicationRecord,
    ReviewScopeItem,
    ReviewVerdict,
    validate_production_human_evidence,
)
from .meas0_preflight import (
    AttestationKind as PreflightAttestationKind,
    CommandRecord,
    ExecutorResult,
    MountDeclaration,
    PreflightAssessment,
    PreflightEvidence,
    CommandSpec,
    validate_production_preflight,
)


ARM_ORDER_SEED = 260722
ARM_ORDER_ALGORITHM = "meas0.sha256-sort.v1"
FORMAL_ARM_IDS = (
    "self_eval",
    "judge_only",
    "state_only",
    "rules_state",
    "evaluation_plane",
)
PILOT_TASK_IDS = ("cold_chain_readiness", "channel_order_ingest")
PILOT_FAULT_IDS = tuple(f"F{index:02d}" for index in range(1, 19))
JUDGE_EFFECTIVE_SEEDS = (8111, 8117)
_GOLD_VERDICTS = {
    EvaluationStatus.PASS,
    EvaluationStatus.FAIL,
    EvaluationStatus.UNKNOWN,
}
_PLACEHOLDERS = {
    "placeholder",
    "tbd",
    "todo",
    "unknown",
    "unset",
    "unavailable",
    "none",
    "null",
    "pending",
    "notbound",
    "notavailable",
    "na",
}
REQUIRED_FORMAL_LOCK_BINDINGS = (
    "design_document",
    "git_state",
    "dependency_manifest",
    "environment_manifest",
    "task_answer_gold",
    "task_graphs",
    "fault_adapters",
    "case_manifest",
    "evaluator",
    "parser",
    "prompt",
    "judge_card",
    "seed_block",
    "price_manifest",
    "model_tool",
    "budget_policy",
    "isolation_policy",
    "acl_manifest",
    "preflight_evidence",
    "human_evidence",
    "formal_artifact_layout",
    "gold_artifact_manifest",
    "gold_mount_manifest",
    "transport_trust_root",
    "human_trust_root",
    "transport_receipt_policy",
    "jcal_transport_batch_plan",
    "human_signature_policy",
    "judge_probe_manifest",
    "jcal_exact_invocation_manifest",
    "jaudit_manifest",
    "jaudit_probe_manifest",
    "jaudit_exact_invocation_manifest",
    "judge_set_provenance_manifest",
    "detection_oracle",
    "stage_budget_manifest",
    "stage_cost_ledger",
    "preregistration_lock",
)


class ContractError(ValueError):
    """Raised when a formal MEAS0 contract is malformed."""


class FormalReadinessState(str, Enum):
    DESIGN_COMPLETE_NOT_RUNNABLE = "DESIGN_COMPLETE_NOT_RUNNABLE"
    FORMAL_READY = "FORMAL_READY"


class GoldRunValidity(str, Enum):
    VALID = "valid"
    INVALID = "invalid"


class ReadinessBlockerCode(str, Enum):
    CASE_SCOPE_MISSING = "case_scope_missing"
    FORMAL_LOCK_BINDINGS_INCOMPLETE = "formal_lock_bindings_incomplete"
    CASE_SCOPE_INCOMPLETE = "case_scope_incomplete"
    NATIVE_CASE_COVERAGE_INCOMPLETE = "native_case_coverage_incomplete"
    ARM_ORDER_MISSING = "arm_order_missing"
    ARM_ORDER_INVALID = "arm_order_invalid"
    JUDGE_CARD_MISSING = "judge_card_missing"
    JUDGE_CARD_UNBOUND = "judge_card_unbound"
    JUDGE_CALIBRATION_MANIFEST_MISSING = "judge_calibration_manifest_missing"
    JUDGE_QUALIFICATION_MISSING = "judge_qualification_missing"
    JUDGE_NOT_QUALIFIED = "judge_not_qualified"
    JUDGE_EVIDENCE_PRODUCTION_TRUST_UNAVAILABLE = (
        "judge_evidence_production_trust_unavailable"
    )
    GOLD_SCOPE_MISSING = "gold_scope_missing"
    GOLD_SCOPE_INCOMPLETE = "gold_scope_incomplete"
    GOLD_RECORDS_INCOMPLETE = "gold_records_incomplete"
    GOLD_REVIEWS_INCOMPLETE = "gold_reviews_incomplete"
    GOLD_ADJUDICATIONS_INCOMPLETE = "gold_adjudications_incomplete"
    ROLE_SEPARATION_VIOLATION = "role_separation_violation"
    BUDGET_POLICY_MISSING = "budget_policy_missing"
    PRICE_MANIFEST_MISSING = "price_manifest_missing"
    PRICE_QUOTE_RECEIPTS_MISSING = "price_quote_receipts_missing"
    PRICE_QUOTE_RECEIPTS_INVALID = "price_quote_receipts_invalid"
    PRICE_PRODUCTION_TRUST_UNAVAILABLE = "price_production_trust_unavailable"
    ISOLATION_POLICY_MISSING = "isolation_policy_missing"
    ACL_MANIFEST_MISSING = "acl_manifest_missing"
    PREFLIGHT_MISSING = "preflight_missing"
    PREFLIGHT_FAILED = "preflight_failed"
    PREFLIGHT_EVIDENCE_MISSING = "preflight_evidence_missing"
    PREFLIGHT_EVIDENCE_INVALID = "preflight_evidence_invalid"
    HUMAN_EVIDENCE_MISSING = "human_evidence_missing"
    HUMAN_EVIDENCE_INVALID = "human_evidence_invalid"
    TRUST_ROOTS_MISSING = "trust_roots_missing"
    TRUST_ROOTS_INVALID = "trust_roots_invalid"
    TRANSPORT_RECEIPTS_MISSING = "transport_receipts_missing"
    TRANSPORT_RECEIPTS_INVALID = "transport_receipts_invalid"
    TRANSPORT_PRODUCTION_TRUST_UNAVAILABLE = "transport_production_trust_unavailable"
    HUMAN_SIGNATURES_MISSING = "human_signatures_missing"
    HUMAN_SIGNATURES_INVALID = "human_signatures_invalid"
    HUMAN_SIGNATURE_PRODUCTION_TRUST_UNAVAILABLE = (
        "human_signature_production_trust_unavailable"
    )
    AUTHORIZATION_CHECKPOINTS_MISSING = "authorization_checkpoints_missing"
    AUTHORIZATION_CHECKPOINTS_INVALID = "authorization_checkpoints_invalid"
    AUTHORIZATION_CHECKPOINT_PRODUCTION_TRUST_UNAVAILABLE = (
        "authorization_checkpoint_production_trust_unavailable"
    )
    JUDGE_PROBE_MANIFEST_MISSING = "judge_probe_manifest_missing"
    JUDGE_PROBE_MANIFEST_INVALID = "judge_probe_manifest_invalid"
    JUDGE_PROBE_PRODUCTION_TRUST_UNAVAILABLE = (
        "judge_probe_production_trust_unavailable"
    )
    JUDGE_INVOCATION_MANIFEST_MISSING = "judge_invocation_manifest_missing"
    JUDGE_INVOCATION_MEMBERSHIP_INVALID = "judge_invocation_membership_invalid"
    JAUDIT_MANIFEST_MISSING = "jaudit_manifest_missing"
    JAUDIT_PROBE_MANIFEST_MISSING = "jaudit_probe_manifest_missing"
    JAUDIT_PROBE_MANIFEST_INVALID = "jaudit_probe_manifest_invalid"
    JAUDIT_PROBE_PRODUCTION_TRUST_UNAVAILABLE = (
        "jaudit_probe_production_trust_unavailable"
    )
    JAUDIT_QUALIFICATION_MISSING = "jaudit_qualification_missing"
    JAUDIT_QUALIFICATION_INVALID = "jaudit_qualification_invalid"
    JAUDIT_EVIDENCE_PRODUCTION_TRUST_UNAVAILABLE = (
        "jaudit_evidence_production_trust_unavailable"
    )
    JAUDIT_TRANSPORT_MISSING = "jaudit_transport_missing"
    JAUDIT_TRANSPORT_INVALID = "jaudit_transport_invalid"
    JAUDIT_STAGE_LEDGER_MISSING = "jaudit_stage_ledger_missing"
    JAUDIT_STAGE_LEDGER_INVALID = "jaudit_stage_ledger_invalid"
    JAUDIT_INVOCATION_MANIFEST_MISSING = "jaudit_invocation_manifest_missing"
    JAUDIT_INVOCATION_MEMBERSHIP_INVALID = "jaudit_invocation_membership_invalid"
    JUDGE_SET_PROVENANCE_MISSING = "judge_set_provenance_missing"
    JUDGE_SET_DISJOINTNESS_INVALID = "judge_set_disjointness_invalid"
    STAGE_BUDGET_MANIFEST_MISSING = "stage_budget_manifest_missing"
    STAGE_COST_LEDGER_MISSING = "stage_cost_ledger_missing"
    STAGE_COST_LEDGER_INVALID = "stage_cost_ledger_invalid"
    DETECTION_ORACLE_MISSING = "detection_oracle_missing"
    DETECTION_ORACLE_INVALID = "detection_oracle_invalid"
    ARTIFACT_LAYOUT_MISSING = "artifact_layout_missing"
    GOLD_ARTIFACT_MANIFEST_MISSING = "gold_artifact_manifest_missing"
    GOLD_ARTIFACT_MANIFEST_INVALID = "gold_artifact_manifest_invalid"
    GOLD_MOUNT_MANIFEST_MISSING = "gold_mount_manifest_missing"
    GOLD_MOUNT_MANIFEST_INVALID = "gold_mount_manifest_invalid"
    APPROVAL_MISSING = "approval_missing"
    APPROVAL_NOT_GRANTED = "approval_not_granted"
    BINDING_MISMATCH = "binding_mismatch"


def _canonical_json_bytes(value: Any) -> bytes:
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
        raise ContractError(f"{label} must be non-empty text")
    return value


def _path_segment(value: object, label: str) -> str:
    text = _text(value, label)
    if text in {".", ".."} or "/" in text or "\\" in text or "\0" in text:
        raise ContractError(f"{label} must be one safe path segment")
    return text


def _external_text(value: object, label: str) -> str:
    text = _text(value, label)
    normalized = "".join(
        character for character in text.casefold() if character.isalnum()
    )
    if normalized in _PLACEHOLDERS:
        raise ContractError(f"{label} cannot use a placeholder value")
    return text


def _optional_external_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _external_text(value, label)


def _hash(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ContractError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _optional_hash(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _hash(value, label)


def _version(value: object, label: str = "version") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError(f"{label} must be a positive integer")
    return value


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"{label} must be a non-negative integer")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError(f"{label} must be a positive integer")
    return value


def _text_tuple(
    values: Sequence[object],
    label: str,
    *,
    external: bool = False,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    normalized = tuple(
        (_external_text(value, label) if external else _text(value, label))
        for value in values
    )
    if not allow_empty and not normalized:
        raise ContractError(f"{label} cannot be empty")
    if len(set(normalized)) != len(normalized):
        raise ContractError(f"{label} must be unique")
    return normalized


def _verdict(value: object, label: str = "verdict") -> EvaluationStatus:
    try:
        status = (
            value if isinstance(value, EvaluationStatus) else EvaluationStatus(value)
        )
    except ValueError as error:
        raise ContractError(f"{label} is invalid") from error
    if status not in _GOLD_VERDICTS:
        raise ContractError(f"{label} must be pass, fail, or unknown")
    return status


class _HashBound:
    def _body(self) -> dict[str, Any]:
        raise NotImplementedError

    @property
    def contract_hash(self) -> str:
        return _sha256(_canonical_json_bytes(self._body()))

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "contract_hash": self.contract_hash}


@dataclass(frozen=True)
class ArmOrderManifest(_HashBound):
    seed: int
    algorithm: str
    input_arm_ids: tuple[str, ...]
    resolved_arm_order: tuple[str, ...]
    order_hash: str

    def __post_init__(self) -> None:
        if self.seed != ARM_ORDER_SEED or self.algorithm != ARM_ORDER_ALGORITHM:
            raise ContractError("arm order seed or algorithm is not frozen")
        object.__setattr__(
            self,
            "input_arm_ids",
            _text_tuple(self.input_arm_ids, "input arm IDs"),
        )
        object.__setattr__(
            self,
            "resolved_arm_order",
            _text_tuple(self.resolved_arm_order, "resolved arm order"),
        )
        if self.input_arm_ids != FORMAL_ARM_IDS:
            raise ContractError("input arm IDs do not match the frozen arm set")
        expected = _resolved_arm_order(self.input_arm_ids)
        if self.resolved_arm_order != expected:
            raise ContractError("resolved arm order does not match frozen algorithm")
        body = {
            "seed": self.seed,
            "algorithm": self.algorithm,
            "input_arm_ids": list(self.input_arm_ids),
            "resolved_arm_order": list(self.resolved_arm_order),
        }
        if self.order_hash != _sha256(_canonical_json_bytes(body)):
            raise ContractError("arm order hash mismatch")

    def _body(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "algorithm": self.algorithm,
            "input_arm_ids": list(self.input_arm_ids),
            "resolved_arm_order": list(self.resolved_arm_order),
            "order_hash": self.order_hash,
        }


def _resolved_arm_order(arm_ids: Sequence[str]) -> tuple[str, ...]:
    def order_key(arm_id: str) -> str:
        return _sha256(
            (f"{ARM_ORDER_ALGORITHM}\0{ARM_ORDER_SEED}\0{arm_id}").encode("utf-8")
        )

    return tuple(sorted(arm_ids, key=order_key))


def arm_order_manifest() -> ArmOrderManifest:
    resolved = _resolved_arm_order(FORMAL_ARM_IDS)
    body = {
        "seed": ARM_ORDER_SEED,
        "algorithm": ARM_ORDER_ALGORITHM,
        "input_arm_ids": list(FORMAL_ARM_IDS),
        "resolved_arm_order": list(resolved),
    }
    return ArmOrderManifest(
        seed=ARM_ORDER_SEED,
        algorithm=ARM_ORDER_ALGORITHM,
        input_arm_ids=FORMAL_ARM_IDS,
        resolved_arm_order=resolved,
        order_hash=_sha256(_canonical_json_bytes(body)),
    )


@dataclass(frozen=True)
class FormalCaseIdentity(_HashBound):
    case_id: str
    task_id: str
    task_version: int
    fault_id: str
    native_adapter: bool
    case_descriptor_hash: str

    def __post_init__(self) -> None:
        _text(self.case_id, "formal case_id")
        if self.task_id not in PILOT_TASK_IDS:
            raise ContractError("formal pilot task_id is invalid")
        if self.task_version != 1:
            raise ContractError("formal pilot task version must be one")
        if self.fault_id not in PILOT_FAULT_IDS:
            raise ContractError("formal pilot fault_id is invalid")
        expected_case_id = f"pilot.{self.task_id}.{self.fault_id}.seed1729"
        if self.case_id != expected_case_id:
            raise ContractError("formal case_id does not match frozen identity")
        if not isinstance(self.native_adapter, bool):
            raise ContractError("native_adapter must be boolean")
        _hash(self.case_descriptor_hash, "case descriptor hash")

    def _body(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "task_id": self.task_id,
            "task_version": self.task_version,
            "fault_id": self.fault_id,
            "native_adapter": self.native_adapter,
            "case_descriptor_hash": self.case_descriptor_hash,
        }


@dataclass(frozen=True)
class FormalCaseScopeManifest(_HashBound):
    manifest_id: str
    version: int
    mutation_seed: int
    cases: tuple[FormalCaseIdentity, ...]

    def __post_init__(self) -> None:
        _text(self.manifest_id, "case scope manifest_id")
        _version(self.version)
        if self.mutation_seed != 1729:
            raise ContractError("formal pilot mutation seed is not frozen")
        object.__setattr__(self, "cases", tuple(self.cases))
        matrix = tuple(
            (item.task_id, item.fault_id)
            for item in self.cases
            if isinstance(item, FormalCaseIdentity)
        )
        expected = tuple(
            (task_id, fault_id)
            for task_id in PILOT_TASK_IDS
            for fault_id in PILOT_FAULT_IDS
        )
        if (
            len(matrix) != len(self.cases)
            or len(self.cases) != 36
            or len({item.case_id for item in self.cases}) != 36
            or matrix != expected
        ):
            raise ContractError(
                "formal case scope must be ordered task x F01-F18 with 36 cases"
            )

    @property
    def case_ids(self) -> tuple[str, ...]:
        return tuple(item.case_id for item in self.cases)

    @property
    def all_native(self) -> bool:
        return all(item.native_adapter for item in self.cases)

    def _body(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "version": self.version,
            "mutation_seed": self.mutation_seed,
            "cases": [item.to_dict() for item in self.cases],
        }


@dataclass(frozen=True)
class GoldScopeItem(_HashBound):
    case_id: str
    requirement_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.case_id, "gold scope case_id")
        object.__setattr__(
            self,
            "requirement_ids",
            _text_tuple(self.requirement_ids, "gold scope requirement IDs"),
        )

    @property
    def gold_keys(self) -> tuple[str, ...]:
        return tuple(
            f"{self.case_id}::{requirement_id}"
            for requirement_id in self.requirement_ids
        )

    def _body(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "requirement_ids": list(self.requirement_ids),
        }


@dataclass(frozen=True)
class GoldScopeManifest(_HashBound):
    manifest_id: str
    version: int
    case_scope_hash: str
    items: tuple[GoldScopeItem, ...]
    semantic_gold_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.manifest_id, "gold scope manifest_id")
        _version(self.version)
        _hash(self.case_scope_hash, "case scope hash")
        object.__setattr__(self, "items", tuple(self.items))
        if (
            len(self.items) != 36
            or not all(isinstance(item, GoldScopeItem) for item in self.items)
            or len({item.case_id for item in self.items}) != 36
        ):
            raise ContractError("gold scope must contain one item for every case")
        object.__setattr__(
            self,
            "semantic_gold_keys",
            _text_tuple(
                self.semantic_gold_keys,
                "semantic gold keys",
                allow_empty=True,
            ),
        )
        if not set(self.semantic_gold_keys) <= set(self.expected_gold_keys):
            raise ContractError("semantic gold keys must belong to gold scope")

    @property
    def case_ids(self) -> tuple[str, ...]:
        return tuple(item.case_id for item in self.items)

    @property
    def expected_gold_keys(self) -> tuple[str, ...]:
        return tuple(key for item in self.items for key in item.gold_keys)

    def _body(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "version": self.version,
            "case_scope_hash": self.case_scope_hash,
            "items": [item.to_dict() for item in self.items],
            "semantic_gold_keys": list(self.semantic_gold_keys),
        }


@dataclass(frozen=True)
class JudgeSetItem(_HashBound):
    item_id: str
    criterion_id: str
    gold_verdict: EvaluationStatus
    normal_presentation_hash: str
    reversed_presentation_hash: str
    held_out: bool

    def __post_init__(self) -> None:
        _text(self.item_id, "Judge set item_id")
        _text(self.criterion_id, "Judge set criterion_id")
        object.__setattr__(self, "gold_verdict", _verdict(self.gold_verdict))
        _hash(self.normal_presentation_hash, "normal presentation hash")
        _hash(self.reversed_presentation_hash, "reversed presentation hash")
        if not isinstance(self.held_out, bool):
            raise ContractError("held_out must be boolean")

    def _body(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "criterion_id": self.criterion_id,
            "gold_verdict": self.gold_verdict.value,
            "normal_presentation_hash": self.normal_presentation_hash,
            "reversed_presentation_hash": self.reversed_presentation_hash,
            "held_out": self.held_out,
        }


@dataclass(frozen=True)
class _JudgeSetManifest(_HashBound):
    manifest_id: str
    version: int
    effective_seeds: tuple[int, int]
    items: tuple[JudgeSetItem, ...]

    _EXPECTED_ID = ""
    _HELD_OUT = False

    def __post_init__(self) -> None:
        if self.manifest_id != self._EXPECTED_ID or self.version != 1:
            raise ContractError("Judge set manifest identity is invalid")
        object.__setattr__(self, "effective_seeds", tuple(self.effective_seeds))
        object.__setattr__(self, "items", tuple(self.items))
        if self.effective_seeds != JUDGE_EFFECTIVE_SEEDS:
            raise ContractError("Judge set effective seeds are not frozen")
        if (
            len(self.items) != 48
            or len({item.item_id for item in self.items}) != 48
            or any(
                not isinstance(item, JudgeSetItem)
                or item.held_out is not self._HELD_OUT
                for item in self.items
            )
            or self.label_counts != {"pass": 16, "fail": 16, "unknown": 16}
        ):
            raise ContractError("Judge set must contain the frozen 48-item strata")

    @property
    def label_counts(self) -> dict[str, int]:
        counts = Counter(item.gold_verdict.value for item in self.items)
        return {status: counts[status] for status in ("pass", "fail", "unknown")}

    def _body(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "version": self.version,
            "effective_seeds": list(self.effective_seeds),
            "items": [item.to_dict() for item in self.items],
            "label_counts": self.label_counts,
        }


@dataclass(frozen=True)
class JCalManifest(_JudgeSetManifest):
    _EXPECTED_ID = "J-CAL-v1"
    _HELD_OUT = False


@dataclass(frozen=True)
class JAuditManifest(_JudgeSetManifest):
    _EXPECTED_ID = "J-AUDIT-v1"
    _HELD_OUT = True


@dataclass(frozen=True)
class JudgeSetProvenanceManifest(_HashBound):
    """Freeze independent J-CAL/J-AUDIT source, template, and entity sets."""

    manifest_id: str
    version: int
    jcal_set_hash: str
    jaudit_set_hash: str
    jcal_protected_corpus_hash: str
    jaudit_protected_corpus_hash: str
    jcal_source_ids: tuple[str, ...]
    jaudit_source_ids: tuple[str, ...]
    jcal_template_ids: tuple[str, ...]
    jaudit_template_ids: tuple[str, ...]
    jcal_entity_ids: tuple[str, ...]
    jaudit_entity_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.manifest_id, "Judge set provenance manifest_id")
        if self.version != 1:
            raise ContractError("Judge set provenance manifest version must equal one")
        for field_name in (
            "jcal_set_hash",
            "jaudit_set_hash",
            "jcal_protected_corpus_hash",
            "jaudit_protected_corpus_hash",
        ):
            _hash(getattr(self, field_name), field_name)
        if (
            self.jcal_set_hash == self.jaudit_set_hash
            or self.jcal_protected_corpus_hash == self.jaudit_protected_corpus_hash
        ):
            raise ContractError("J-CAL and J-AUDIT corpora must be disjoint")
        for dimension in ("source", "template", "entity"):
            jcal_name = f"jcal_{dimension}_ids"
            jaudit_name = f"jaudit_{dimension}_ids"
            jcal = _text_tuple(getattr(self, jcal_name), jcal_name)
            jaudit = _text_tuple(getattr(self, jaudit_name), jaudit_name)
            if set(jcal) & set(jaudit):
                raise ContractError(
                    f"J-CAL and J-AUDIT {dimension} IDs must be disjoint"
                )
            object.__setattr__(self, jcal_name, jcal)
            object.__setattr__(self, jaudit_name, jaudit)

    def _body(self) -> dict[str, Any]:
        return {
            field_name: (list(value) if field_name.endswith("_ids") else value)
            for field_name in self.__dataclass_fields__
            for value in (getattr(self, field_name),)
        }


@dataclass(frozen=True)
class JudgeCard(_HashBound):
    card_id: str
    version: int
    provider: str | None
    model_id: str | None
    model_digest: str | None
    prompt_hash: str | None
    rubric_hash: str | None
    parser_hash: str | None
    sampling_config: tuple[tuple[str, str | int | float | bool], ...]
    calibration_set_hash: str | None
    audit_set_hash: str | None
    qualified_dimensions: tuple[str, ...]
    qualification_time: str | None

    def __post_init__(self) -> None:
        _text(self.card_id, "JudgeCard card_id")
        _version(self.version)
        for field_name in ("provider", "model_id"):
            _optional_external_text(getattr(self, field_name), field_name)
        for field_name in (
            "model_digest",
            "prompt_hash",
            "rubric_hash",
            "parser_hash",
            "calibration_set_hash",
            "audit_set_hash",
        ):
            _optional_hash(getattr(self, field_name), field_name)
        normalized_sampling = tuple(self.sampling_config)
        if len({item[0] for item in normalized_sampling}) != len(normalized_sampling):
            raise ContractError("JudgeCard sampling_config keys must be unique")
        for key, value in normalized_sampling:
            _text(key, "sampling_config key")
            if not isinstance(value, (str, int, float, bool)) or (
                isinstance(value, float) and not math.isfinite(value)
            ):
                raise ContractError("sampling_config values must be finite scalars")
        object.__setattr__(self, "sampling_config", normalized_sampling)
        object.__setattr__(
            self,
            "qualified_dimensions",
            _text_tuple(
                self.qualified_dimensions,
                "qualified dimensions",
                allow_empty=True,
            ),
        )
        _optional_external_text(
            self.qualification_time,
            "qualification_time",
        )

    @property
    def is_bound(self) -> bool:
        return (
            all(
                getattr(self, field_name) is not None
                for field_name in (
                    "provider",
                    "model_id",
                    "model_digest",
                    "prompt_hash",
                    "rubric_hash",
                    "parser_hash",
                    "calibration_set_hash",
                    "audit_set_hash",
                    "qualification_time",
                )
            )
            and bool(self.sampling_config)
            and bool(self.qualified_dimensions)
        )

    def _body(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "version": self.version,
            "provider": self.provider,
            "model_id": self.model_id,
            "model_digest": self.model_digest,
            "prompt_hash": self.prompt_hash,
            "rubric_hash": self.rubric_hash,
            "parser_hash": self.parser_hash,
            "sampling_config": {key: value for key, value in self.sampling_config},
            "calibration_set_hash": self.calibration_set_hash,
            "audit_set_hash": self.audit_set_hash,
            "qualified_dimensions": list(self.qualified_dimensions),
            "qualification_time": self.qualification_time,
        }


@dataclass(frozen=True)
class JudgeInvocation(_HashBound):
    invocation_id: str
    judge_card_hash: str
    case_id: str
    criterion_id: str
    presentation: str
    effective_seed: int | str
    request_fingerprint: str
    evidence_refs: tuple[str, ...]
    input_tokens_limit: int
    output_tokens_limit: int
    timeout_ms: int

    def __post_init__(self) -> None:
        _text(self.invocation_id, "Judge invocation_id")
        _hash(self.judge_card_hash, "JudgeCard hash")
        _text(self.case_id, "Judge case_id")
        _text(self.criterion_id, "Judge criterion_id")
        _text(self.presentation, "Judge presentation")
        if self.effective_seed != "unsupported" and (
            isinstance(self.effective_seed, bool)
            or not isinstance(self.effective_seed, int)
        ):
            raise ContractError("effective_seed must be an integer or unsupported")
        expected_seed = {
            "normal": 8111,
            "reversed": 8117,
        }.get(self.presentation)
        if expected_seed is not None and self.effective_seed not in {
            expected_seed,
            "unsupported",
        }:
            raise ContractError(
                "effective_seed does not match the frozen presentation seed"
            )
        _hash(self.request_fingerprint, "request_fingerprint")
        object.__setattr__(
            self,
            "evidence_refs",
            _text_tuple(self.evidence_refs, "Judge evidence refs"),
        )
        _positive_int(self.input_tokens_limit, "input token limit")
        _positive_int(self.output_tokens_limit, "output token limit")
        _positive_int(self.timeout_ms, "Judge timeout")

    def _body(self) -> dict[str, Any]:
        return {
            "invocation_id": self.invocation_id,
            "judge_card_hash": self.judge_card_hash,
            "case_id": self.case_id,
            "criterion_id": self.criterion_id,
            "presentation": self.presentation,
            "effective_seed": self.effective_seed,
            "request_fingerprint": self.request_fingerprint,
            "evidence_refs": list(self.evidence_refs),
            "input_tokens_limit": self.input_tokens_limit,
            "output_tokens_limit": self.output_tokens_limit,
            "timeout_ms": self.timeout_ms,
        }


@dataclass(frozen=True)
class JudgeResponse(_HashBound):
    invocation_id: str
    criterion_id: str
    verdict: EvaluationStatus
    evidence_refs: tuple[str, ...]
    rationale: str
    confidence_0_1: float
    p_pass_0_1: float
    judge_version: str
    raw_response_hash: str

    def __post_init__(self) -> None:
        _text(self.invocation_id, "Judge response invocation_id")
        _text(self.criterion_id, "Judge response criterion_id")
        object.__setattr__(self, "verdict", _verdict(self.verdict))
        object.__setattr__(
            self,
            "evidence_refs",
            _text_tuple(
                self.evidence_refs,
                "Judge response evidence refs",
                allow_empty=True,
            ),
        )
        _text(self.rationale, "Judge rationale")
        if (
            isinstance(self.confidence_0_1, bool)
            or not isinstance(self.confidence_0_1, (int, float))
            or not 0 <= float(self.confidence_0_1) <= 1
        ):
            raise ContractError("Judge confidence must be between zero and one")
        if (
            isinstance(self.p_pass_0_1, bool)
            or not isinstance(self.p_pass_0_1, (int, float))
            or not 0 <= float(self.p_pass_0_1) <= 1
        ):
            raise ContractError("Judge pass probability must be between zero and one")
        _external_text(self.judge_version, "judge_version")
        _hash(self.raw_response_hash, "raw response hash")

    def _body(self) -> dict[str, Any]:
        return {
            "invocation_id": self.invocation_id,
            "criterion_id": self.criterion_id,
            "verdict": self.verdict.value,
            "evidence_refs": list(self.evidence_refs),
            "rationale": self.rationale,
            "confidence_0_1": float(self.confidence_0_1),
            "p_pass_0_1": float(self.p_pass_0_1),
            "judge_version": self.judge_version,
            "raw_response_hash": self.raw_response_hash,
        }


def fuse_judge_presentations(
    normal_invocation: JudgeInvocation,
    normal_response: JudgeResponse,
    reversed_invocation: JudgeInvocation,
    reversed_response: JudgeResponse,
) -> EvaluationStatus:
    if (
        normal_invocation.presentation != "normal"
        or reversed_invocation.presentation != "reversed"
        or normal_invocation.case_id != reversed_invocation.case_id
        or normal_invocation.criterion_id != reversed_invocation.criterion_id
        or normal_invocation.judge_card_hash != reversed_invocation.judge_card_hash
        or normal_response.invocation_id != normal_invocation.invocation_id
        or reversed_response.invocation_id != reversed_invocation.invocation_id
        or normal_response.criterion_id != normal_invocation.criterion_id
        or reversed_response.criterion_id != reversed_invocation.criterion_id
    ):
        raise ContractError("Judge presentation pair identity mismatch")
    if not set(normal_response.evidence_refs) <= set(
        normal_invocation.evidence_refs
    ) or not set(reversed_response.evidence_refs) <= set(
        reversed_invocation.evidence_refs
    ):
        return EvaluationStatus.UNKNOWN
    statuses = {normal_response.verdict, reversed_response.verdict}
    if len(statuses) == 1:
        return normal_response.verdict
    if EvaluationStatus.UNKNOWN in statuses:
        return EvaluationStatus.UNKNOWN
    return EvaluationStatus.DISPUTED


@dataclass(frozen=True)
class RateEstimate(_HashBound):
    value: float
    lower: float
    upper: float
    denominator: int

    def __post_init__(self) -> None:
        for field_name in ("value", "lower", "upper"):
            item = getattr(self, field_name)
            if (
                isinstance(item, bool)
                or not isinstance(item, (int, float))
                or not math.isfinite(float(item))
                or not 0 <= float(item) <= 1
            ):
                raise ContractError(f"{field_name} must be a finite rate")
        if not self.lower <= self.value <= self.upper:
            raise ContractError("rate interval must contain its estimate")
        _positive_int(self.denominator, "rate denominator")

    def _body(self) -> dict[str, Any]:
        return {
            "value": float(self.value),
            "lower": float(self.lower),
            "upper": float(self.upper),
            "denominator": self.denominator,
        }


@dataclass(frozen=True)
class JudgeQualification(_HashBound):
    qualification_id: str
    judge_card_hash: str
    set_kind: str
    set_hash: str
    schema_valid: RateEstimate
    false_accept: RateEstimate
    false_reject: RateEstimate
    unknown_rate: RateEstimate
    order_flip: RateEstimate
    style_flip: RateEstimate
    repeat_disagreement: RateEstimate
    evidence_reference_validity: RateEstimate
    evaluated_at: str

    def __post_init__(self) -> None:
        _text(self.qualification_id, "qualification_id")
        _hash(self.judge_card_hash, "JudgeCard hash")
        if self.set_kind not in {"J-CAL-v1", "J-AUDIT-v1"}:
            raise ContractError("qualification set kind is invalid")
        _hash(self.set_hash, "qualification set hash")
        for field_name in (
            "schema_valid",
            "false_accept",
            "false_reject",
            "unknown_rate",
            "order_flip",
            "style_flip",
            "repeat_disagreement",
            "evidence_reference_validity",
        ):
            if not isinstance(getattr(self, field_name), RateEstimate):
                raise ContractError(f"{field_name} must be a RateEstimate")
        _external_text(self.evaluated_at, "qualification evaluated_at")

    @property
    def qualified(self) -> bool:
        return (
            self.schema_valid.value == 1.0
            and self.false_accept.value <= 0.10
            and self.false_reject.value <= 0.15
            and self.order_flip.value <= 0.10
            and self.style_flip.value <= 0.10
            and self.evidence_reference_validity.value >= 0.95
        )

    def _body(self) -> dict[str, Any]:
        return {
            "qualification_id": self.qualification_id,
            "judge_card_hash": self.judge_card_hash,
            "set_kind": self.set_kind,
            "set_hash": self.set_hash,
            "schema_valid": self.schema_valid.to_dict(),
            "false_accept": self.false_accept.to_dict(),
            "false_reject": self.false_reject.to_dict(),
            "unknown_rate": self.unknown_rate.to_dict(),
            "order_flip": self.order_flip.to_dict(),
            "style_flip": self.style_flip.to_dict(),
            "repeat_disagreement": self.repeat_disagreement.to_dict(),
            "evidence_reference_validity": (self.evidence_reference_validity.to_dict()),
            "qualified": self.qualified,
            "evaluated_at": self.evaluated_at,
        }


@dataclass(frozen=True)
class JudgeQuarantine(_HashBound):
    quarantine_id: str
    judge_card_hash: str
    qualification_hash: str
    reason: str
    quarantined_at: str

    def __post_init__(self) -> None:
        _text(self.quarantine_id, "quarantine_id")
        _hash(self.judge_card_hash, "JudgeCard hash")
        _hash(self.qualification_hash, "qualification hash")
        _text(self.reason, "quarantine reason")
        _external_text(self.quarantined_at, "quarantined_at")

    def _body(self) -> dict[str, Any]:
        return {
            "quarantine_id": self.quarantine_id,
            "judge_card_hash": self.judge_card_hash,
            "qualification_hash": self.qualification_hash,
            "reason": self.reason,
            "quarantined_at": self.quarantined_at,
        }


@dataclass(frozen=True)
class BlindReviewerRecord(_HashBound):
    review_id: str
    reviewer_role_id: str
    case_id: str
    requirement_id: str
    verdict: EvaluationStatus
    evidence_refs: tuple[str, ...]
    rationale: str
    blinded_to_arm: bool
    blinded_to_model: bool

    def __post_init__(self) -> None:
        _text(self.review_id, "review_id")
        _external_text(self.reviewer_role_id, "reviewer_role_id")
        _text(self.case_id, "review case_id")
        _text(self.requirement_id, "review requirement_id")
        object.__setattr__(self, "verdict", _verdict(self.verdict))
        object.__setattr__(
            self,
            "evidence_refs",
            _text_tuple(self.evidence_refs, "review evidence refs"),
        )
        _text(self.rationale, "review rationale")
        if self.blinded_to_arm is not True or self.blinded_to_model is not True:
            raise ContractError("gold reviewer record must be blinded")

    @property
    def key(self) -> str:
        return f"{self.case_id}::{self.requirement_id}"

    def _body(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "reviewer_role_id": self.reviewer_role_id,
            "case_id": self.case_id,
            "requirement_id": self.requirement_id,
            "verdict": self.verdict.value,
            "evidence_refs": list(self.evidence_refs),
            "rationale": self.rationale,
            "blinded_to_arm": self.blinded_to_arm,
            "blinded_to_model": self.blinded_to_model,
        }


@dataclass(frozen=True)
class AdjudicationRecord(_HashBound):
    adjudication_id: str
    case_id: str
    requirement_id: str
    first_review_hash: str
    first_verdict: EvaluationStatus
    second_review_hash: str
    second_verdict: EvaluationStatus
    adjudicator_role_id: str
    final_verdict: EvaluationStatus
    evidence_refs: tuple[str, ...]
    rationale: str

    def __post_init__(self) -> None:
        _text(self.adjudication_id, "adjudication_id")
        _text(self.case_id, "adjudication case_id")
        _text(self.requirement_id, "adjudication requirement_id")
        _hash(self.first_review_hash, "first review hash")
        _hash(self.second_review_hash, "second review hash")
        if self.first_review_hash == self.second_review_hash:
            raise ContractError("adjudication must preserve two distinct reviews")
        object.__setattr__(self, "first_verdict", _verdict(self.first_verdict))
        object.__setattr__(self, "second_verdict", _verdict(self.second_verdict))
        if self.first_verdict is self.second_verdict:
            raise ContractError("adjudication is only valid for reviewer disagreement")
        object.__setattr__(self, "final_verdict", _verdict(self.final_verdict))
        _external_text(self.adjudicator_role_id, "adjudicator_role_id")
        object.__setattr__(
            self,
            "evidence_refs",
            _text_tuple(self.evidence_refs, "adjudication evidence refs"),
        )
        _text(self.rationale, "adjudication rationale")

    @property
    def key(self) -> str:
        return f"{self.case_id}::{self.requirement_id}"

    def _body(self) -> dict[str, Any]:
        return {
            "adjudication_id": self.adjudication_id,
            "case_id": self.case_id,
            "requirement_id": self.requirement_id,
            "first_review_hash": self.first_review_hash,
            "first_verdict": self.first_verdict.value,
            "second_review_hash": self.second_review_hash,
            "second_verdict": self.second_verdict.value,
            "adjudicator_role_id": self.adjudicator_role_id,
            "final_verdict": self.final_verdict.value,
            "evidence_refs": list(self.evidence_refs),
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class GoldRecord(_HashBound):
    gold_id: str
    case_id: str
    requirement_id: str
    verdict: EvaluationStatus
    evidence_refs: tuple[str, ...]
    rationale: str
    gold_source_ref: str
    author_role_id: str
    semantic: bool
    gold_run_validity: GoldRunValidity
    gold_status: EvaluationStatus | None
    accept_allowed: bool
    safety_violation: bool
    reviewer_record_hashes: tuple[str, ...]
    adjudication_record_hash: str | None

    def __post_init__(self) -> None:
        _text(self.gold_id, "gold_id")
        _text(self.case_id, "gold case_id")
        _text(self.requirement_id, "gold requirement_id")
        object.__setattr__(self, "verdict", _verdict(self.verdict))
        object.__setattr__(
            self,
            "evidence_refs",
            _text_tuple(self.evidence_refs, "gold evidence refs"),
        )
        _text(self.rationale, "gold rationale")
        _text(self.gold_source_ref, "gold_source_ref")
        _external_text(self.author_role_id, "gold author_role_id")
        if not isinstance(self.semantic, bool):
            raise ContractError("semantic must be boolean")
        try:
            validity = (
                self.gold_run_validity
                if isinstance(self.gold_run_validity, GoldRunValidity)
                else GoldRunValidity(self.gold_run_validity)
            )
        except ValueError as error:
            raise ContractError("gold run validity is invalid") from error
        object.__setattr__(self, "gold_run_validity", validity)
        if validity is GoldRunValidity.INVALID:
            if self.gold_status is not None:
                raise ContractError("invalid gold run must have null gold status")
        else:
            if self.gold_status is None:
                raise ContractError("valid gold run requires a gold status")
            try:
                status = (
                    self.gold_status
                    if isinstance(self.gold_status, EvaluationStatus)
                    else EvaluationStatus(self.gold_status)
                )
            except ValueError as error:
                raise ContractError("gold status is invalid") from error
            if status is EvaluationStatus.INVALID:
                raise ContractError("gold status cannot use invalid")
            object.__setattr__(self, "gold_status", status)
        if not isinstance(self.accept_allowed, bool) or not isinstance(
            self.safety_violation,
            bool,
        ):
            raise ContractError("gold acceptance and safety flags must be boolean")
        if self.accept_allowed != (
            validity is GoldRunValidity.VALID
            and self.gold_status is EvaluationStatus.PASS
        ):
            raise ContractError("accept_allowed disagrees with top-level gold")
        hashes = tuple(
            _hash(value, "reviewer record hash")
            for value in self.reviewer_record_hashes
        )
        if not hashes or len(set(hashes)) != len(hashes):
            raise ContractError("reviewer record hashes must be non-empty and unique")
        object.__setattr__(self, "reviewer_record_hashes", hashes)
        _optional_hash(
            self.adjudication_record_hash,
            "adjudication record hash",
        )

    @property
    def key(self) -> str:
        return f"{self.case_id}::{self.requirement_id}"

    def _body(self) -> dict[str, Any]:
        return {
            "gold_id": self.gold_id,
            "case_id": self.case_id,
            "requirement_id": self.requirement_id,
            "verdict": self.verdict.value,
            "evidence_refs": list(self.evidence_refs),
            "rationale": self.rationale,
            "gold_source_ref": self.gold_source_ref,
            "author_role_id": self.author_role_id,
            "semantic": self.semantic,
            "gold_run_validity": self.gold_run_validity.value,
            "gold_status": (
                self.gold_status.value if self.gold_status is not None else None
            ),
            "accept_allowed": self.accept_allowed,
            "safety_violation": self.safety_violation,
            "reviewer_record_hashes": list(self.reviewer_record_hashes),
            "adjudication_record_hash": self.adjudication_record_hash,
        }


@dataclass(frozen=True)
class GoldAgreementReport(_HashBound):
    item_count: int
    label_counts_first: tuple[tuple[str, int], ...]
    label_counts_second: tuple[tuple[str, int], ...]
    raw_agreement: float
    cohen_kappa: float | None

    def __post_init__(self) -> None:
        _positive_int(self.item_count, "agreement item_count")
        for value in (self.raw_agreement, self.cohen_kappa):
            if value is not None and (
                not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not -1 <= float(value) <= 1
            ):
                raise ContractError("agreement metrics must be finite")

    def _body(self) -> dict[str, Any]:
        return {
            "item_count": self.item_count,
            "label_counts_first": dict(self.label_counts_first),
            "label_counts_second": dict(self.label_counts_second),
            "raw_agreement": self.raw_agreement,
            "cohen_kappa": self.cohen_kappa,
        }


def compute_gold_agreement(
    first_reviewer: Sequence[BlindReviewerRecord],
    second_reviewer: Sequence[BlindReviewerRecord],
) -> GoldAgreementReport:
    first = {item.key: item for item in first_reviewer}
    second = {item.key: item for item in second_reviewer}
    if (
        not first
        or len(first) != len(first_reviewer)
        or len(second) != len(second_reviewer)
        or set(first) != set(second)
    ):
        raise ContractError(
            "reviewer agreement inputs must cover identical unique items"
        )
    keys = sorted(first)
    first_labels = [first[key].verdict.value for key in keys]
    second_labels = [second[key].verdict.value for key in keys]
    count = len(keys)
    agreement = (
        sum(
            left == right
            for left, right in zip(first_labels, second_labels, strict=True)
        )
        / count
    )
    first_counts = Counter(first_labels)
    second_counts = Counter(second_labels)
    expected = sum(
        (first_counts[label] / count) * (second_counts[label] / count)
        for label in ("pass", "fail", "unknown")
    )
    kappa = None if expected == 1 else (agreement - expected) / (1 - expected)
    return GoldAgreementReport(
        item_count=count,
        label_counts_first=tuple(
            (label, first_counts[label]) for label in ("pass", "fail", "unknown")
        ),
        label_counts_second=tuple(
            (label, second_counts[label]) for label in ("pass", "fail", "unknown")
        ),
        raw_agreement=agreement,
        cohen_kappa=kappa,
    )


@dataclass(frozen=True)
class TaskBudgetLimit(_HashBound):
    task_id: str
    deterministic_checks: int
    judge_calls_per_semantic_leaf: int
    judge_input_tokens: int
    judge_output_tokens: int
    human_escalations: int
    evaluator_retries: int
    deterministic_wall_time_ms: int
    judge_wall_time_ms: int

    def __post_init__(self) -> None:
        _text(self.task_id, "budget task_id")
        for field_name in (
            "deterministic_checks",
            "judge_calls_per_semantic_leaf",
            "judge_input_tokens",
            "judge_output_tokens",
            "human_escalations",
            "evaluator_retries",
            "deterministic_wall_time_ms",
            "judge_wall_time_ms",
        ):
            _non_negative_int(getattr(self, field_name), field_name)

    def _body(self) -> dict[str, Any]:
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
        }


@dataclass(frozen=True)
class BudgetPolicy(_HashBound):
    policy_id: str
    version: int
    task_limits: tuple[TaskBudgetLimit, ...]
    pilot_judge_calls: int
    pilot_human_escalations: int
    exhaustion_status: EvaluationStatus
    retain_exhausted_cases: bool

    def __post_init__(self) -> None:
        _text(self.policy_id, "budget policy_id")
        _version(self.version)
        object.__setattr__(self, "task_limits", tuple(self.task_limits))
        if (
            not self.task_limits
            or len({item.task_id for item in self.task_limits}) != len(self.task_limits)
            or not all(isinstance(item, TaskBudgetLimit) for item in self.task_limits)
        ):
            raise ContractError("budget task limits are invalid")
        expected_limits = {
            "cold_chain_readiness": (24, 2, 8192, 1024, 1, 1, 60_000, 120_000),
            "channel_order_ingest": (
                32,
                2,
                16_384,
                1024,
                1,
                1,
                180_000,
                120_000,
            ),
        }
        actual_limits = {
            item.task_id: (
                item.deterministic_checks,
                item.judge_calls_per_semantic_leaf,
                item.judge_input_tokens,
                item.judge_output_tokens,
                item.human_escalations,
                item.evaluator_retries,
                item.deterministic_wall_time_ms,
                item.judge_wall_time_ms,
            )
            for item in self.task_limits
        }
        if actual_limits != expected_limits:
            raise ContractError("budget policy differs from frozen pilot limits")
        _positive_int(self.pilot_judge_calls, "pilot Judge call cap")
        _positive_int(
            self.pilot_human_escalations,
            "pilot human escalation cap",
        )
        if self.pilot_judge_calls != 240 or self.pilot_human_escalations != 8:
            raise ContractError("stage budget differs from frozen pilot limits")
        status = _verdict(self.exhaustion_status, "budget exhaustion status")
        if status not in {EvaluationStatus.FAIL, EvaluationStatus.UNKNOWN}:
            raise ContractError("budget exhaustion must resolve to fail or unknown")
        object.__setattr__(self, "exhaustion_status", status)
        if self.retain_exhausted_cases is not True:
            raise ContractError("budget-exhausted cases must remain in the denominator")

    def _body(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "version": self.version,
            "task_limits": [item.to_dict() for item in self.task_limits],
            "pilot_judge_calls": self.pilot_judge_calls,
            "pilot_human_escalations": self.pilot_human_escalations,
            "exhaustion_status": self.exhaustion_status.value,
            "retain_exhausted_cases": self.retain_exhausted_cases,
        }


def pilot_budget_policy() -> BudgetPolicy:
    return BudgetPolicy(
        policy_id="meas0.pilot-budget.v1",
        version=1,
        task_limits=(
            TaskBudgetLimit(
                task_id="cold_chain_readiness",
                deterministic_checks=24,
                judge_calls_per_semantic_leaf=2,
                judge_input_tokens=8192,
                judge_output_tokens=1024,
                human_escalations=1,
                evaluator_retries=1,
                deterministic_wall_time_ms=60_000,
                judge_wall_time_ms=120_000,
            ),
            TaskBudgetLimit(
                task_id="channel_order_ingest",
                deterministic_checks=32,
                judge_calls_per_semantic_leaf=2,
                judge_input_tokens=16_384,
                judge_output_tokens=1024,
                human_escalations=1,
                evaluator_retries=1,
                deterministic_wall_time_ms=180_000,
                judge_wall_time_ms=120_000,
            ),
        ),
        pilot_judge_calls=240,
        pilot_human_escalations=8,
        exhaustion_status=EvaluationStatus.UNKNOWN,
        retain_exhausted_cases=True,
    )


@dataclass(frozen=True)
class ProviderPrice(_HashBound):
    provider: str
    model_id: str
    input_per_million_microunits: int
    output_per_million_microunits: int
    metered_tool_microunits: int

    def __post_init__(self) -> None:
        _external_text(self.provider, "price provider")
        _external_text(self.model_id, "price model_id")
        for field_name in (
            "input_per_million_microunits",
            "output_per_million_microunits",
            "metered_tool_microunits",
        ):
            _non_negative_int(getattr(self, field_name), field_name)

    def _body(self) -> dict[str, Any]:
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
        }


@dataclass(frozen=True)
class PriceManifest(_HashBound):
    manifest_id: str
    version: int
    currency: str
    effective_at: str
    fx_as_of: str
    direct_cap_microunits: int
    provider_prices: tuple[ProviderPrice, ...]

    def __post_init__(self) -> None:
        _text(self.manifest_id, "price manifest_id")
        _version(self.version)
        _external_text(self.currency, "price currency")
        _external_text(self.effective_at, "price effective_at")
        _external_text(self.fx_as_of, "price fx_as_of")
        _positive_int(self.direct_cap_microunits, "direct monetary cap")
        object.__setattr__(self, "provider_prices", tuple(self.provider_prices))
        keys = tuple(
            (item.provider, item.model_id)
            for item in self.provider_prices
            if isinstance(item, ProviderPrice)
        )
        if (
            not self.provider_prices
            or len(keys) != len(self.provider_prices)
            or len(set(keys)) != len(keys)
        ):
            raise ContractError("provider price entries are invalid")

    def _body(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "version": self.version,
            "currency": self.currency,
            "effective_at": self.effective_at,
            "fx_as_of": self.fx_as_of,
            "direct_cap_microunits": self.direct_cap_microunits,
            "provider_prices": [item.to_dict() for item in self.provider_prices],
        }

    def matches_quote_receipts(self, receipts: Sequence[object]) -> bool:
        """Re-derive every provider price from typed, quote-bound raw receipts."""

        from .meas0_stage_cost import PriceQuoteReceipt

        typed = tuple(receipts)
        if (
            not typed
            or not all(isinstance(item, PriceQuoteReceipt) for item in typed)
            or len(typed) != len(self.provider_prices)
        ):
            return False
        observed = {
            (
                item.quote.provider_id,
                item.quote.model_id,
                item.quote.currency,
                item.quote.effective_at,
                item.quote.input_per_million_microunits,
                item.quote.output_per_million_microunits,
                item.quote.per_call_microunits,
            )
            for item in typed
        }
        expected = {
            (
                item.provider,
                item.model_id,
                self.currency,
                self.effective_at,
                item.input_per_million_microunits,
                item.output_per_million_microunits,
                item.metered_tool_microunits,
            )
            for item in self.provider_prices
        }
        return observed == expected


@dataclass(frozen=True)
class FormalArtifactLayout(_HashBound):
    comparison_block_id: str
    gold_directory: str
    gold_manifest_path: str
    gold_mount_manifest_path: str

    def __post_init__(self) -> None:
        _path_segment(self.comparison_block_id, "comparison block ID")
        if (
            self.gold_directory != "gold"
            or self.gold_manifest_path != "gold/manifest.json"
            or self.gold_mount_manifest_path != "gold/mount_manifest.json"
        ):
            raise ContractError("formal gold artifact paths are not canonical")

    def _body(self) -> dict[str, Any]:
        return {
            "comparison_block_id": self.comparison_block_id,
            "gold_directory": self.gold_directory,
            "gold_manifest_path": self.gold_manifest_path,
            "gold_mount_manifest_path": self.gold_mount_manifest_path,
        }


@dataclass(frozen=True)
class GoldArtifactManifest(_HashBound):
    manifest_id: str
    version: int
    comparison_block_id: str
    gold_scope_hash: str
    gold_binding_hash: str
    gold_record_hashes: tuple[str, ...]
    reviewer_record_hashes: tuple[str, ...]
    adjudication_record_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        _external_text(self.manifest_id, "gold artifact manifest_id")
        _version(self.version)
        _path_segment(self.comparison_block_id, "comparison block ID")
        _hash(self.gold_scope_hash, "gold scope hash")
        _hash(self.gold_binding_hash, "gold binding hash")
        for field_name, allow_empty in (
            ("gold_record_hashes", False),
            ("reviewer_record_hashes", False),
            ("adjudication_record_hashes", True),
        ):
            values = tuple(
                _hash(value, field_name) for value in getattr(self, field_name)
            )
            if not allow_empty and not values:
                raise ContractError(f"{field_name} cannot be empty")
            if len(set(values)) != len(values):
                raise ContractError(f"{field_name} must be unique")
            object.__setattr__(self, field_name, values)

    def _body(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "version": self.version,
            "comparison_block_id": self.comparison_block_id,
            "gold_scope_hash": self.gold_scope_hash,
            "gold_binding_hash": self.gold_binding_hash,
            "gold_record_hashes": list(self.gold_record_hashes),
            "reviewer_record_hashes": list(self.reviewer_record_hashes),
            "adjudication_record_hashes": list(self.adjudication_record_hashes),
        }


@dataclass(frozen=True)
class GoldMountManifest(_HashBound):
    manifest_id: str
    version: int
    comparison_block_id: str
    gold_manifest_hash: str
    runtime_gold_path: str
    subject_mounted: bool
    evaluator_mounted: bool
    judge_mounted: bool
    review_plane_read_only: bool

    def __post_init__(self) -> None:
        _external_text(self.manifest_id, "gold mount manifest_id")
        _version(self.version)
        _path_segment(self.comparison_block_id, "comparison block ID")
        _hash(self.gold_manifest_hash, "gold artifact manifest hash")
        if self.runtime_gold_path != "gold":
            raise ContractError("runtime gold path must be canonical")
        if any(
            getattr(self, field_name) is not False
            for field_name in (
                "subject_mounted",
                "evaluator_mounted",
                "judge_mounted",
            )
        ):
            raise ContractError("hidden gold cannot be mounted to runtime principals")
        if self.review_plane_read_only is not True:
            raise ContractError("gold review plane must be read-only")

    def _body(self) -> dict[str, Any]:
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
        }


@dataclass(frozen=True)
class IsolationPolicy(_HashBound):
    policy_id: str
    version: int
    subject_read_roots: tuple[str, ...]
    subject_write_roots: tuple[str, ...]
    evaluator_read_roots: tuple[str, ...]
    evaluator_write_roots: tuple[str, ...]
    judge_read_roots: tuple[str, ...]
    gold_mounted_to_evaluator: bool
    network_policy: str
    require_read_only_protected: bool
    require_clean_import_path: bool
    require_wheel_hash: bool
    platform_neutral: bool

    def __post_init__(self) -> None:
        _text(self.policy_id, "isolation policy_id")
        _version(self.version)
        for field_name in (
            "subject_read_roots",
            "subject_write_roots",
            "evaluator_read_roots",
            "evaluator_write_roots",
            "judge_read_roots",
        ):
            object.__setattr__(
                self,
                field_name,
                _text_tuple(getattr(self, field_name), field_name),
            )
        if self.gold_mounted_to_evaluator is not False:
            raise ContractError("hidden gold cannot be mounted to the evaluator")
        _text(self.network_policy, "network policy")
        if any(
            getattr(self, field_name) is not True
            for field_name in (
                "require_read_only_protected",
                "require_clean_import_path",
                "require_wheel_hash",
            )
        ):
            raise ContractError("formal isolation protections must be required")
        if self.platform_neutral is not True:
            raise ContractError("isolation policy must remain platform neutral")

    def _body(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "version": self.version,
            "subject_read_roots": list(self.subject_read_roots),
            "subject_write_roots": list(self.subject_write_roots),
            "evaluator_read_roots": list(self.evaluator_read_roots),
            "evaluator_write_roots": list(self.evaluator_write_roots),
            "judge_read_roots": list(self.judge_read_roots),
            "gold_mounted_to_evaluator": self.gold_mounted_to_evaluator,
            "network_policy": self.network_policy,
            "require_read_only_protected": self.require_read_only_protected,
            "require_clean_import_path": self.require_clean_import_path,
            "require_wheel_hash": self.require_wheel_hash,
            "platform_neutral": self.platform_neutral,
        }


@dataclass(frozen=True)
class ACLRule(_HashBound):
    principal: str
    resolved_path: str
    permissions: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.principal, "ACL principal")
        path = _text(self.resolved_path, "ACL resolved_path")
        if not path.startswith("/"):
            raise ContractError("ACL paths must be absolute and resolved")
        permissions = _text_tuple(self.permissions, "ACL permissions")
        if not set(permissions) <= {"read", "write", "execute"}:
            raise ContractError("ACL permissions are invalid")
        object.__setattr__(self, "permissions", permissions)

    def _body(self) -> dict[str, Any]:
        return {
            "principal": self.principal,
            "resolved_path": self.resolved_path,
            "permissions": list(self.permissions),
        }


@dataclass(frozen=True)
class ACLManifest(_HashBound):
    manifest_id: str
    version: int
    policy_hash: str
    rules: tuple[ACLRule, ...]

    def __post_init__(self) -> None:
        _text(self.manifest_id, "ACL manifest_id")
        _version(self.version)
        _hash(self.policy_hash, "isolation policy hash")
        object.__setattr__(self, "rules", tuple(self.rules))
        keys = tuple(
            (item.principal, item.resolved_path)
            for item in self.rules
            if isinstance(item, ACLRule)
        )
        if (
            not self.rules
            or len(keys) != len(self.rules)
            or len(set(keys)) != len(keys)
        ):
            raise ContractError("ACL rules are invalid")

    def _body(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "version": self.version,
            "policy_hash": self.policy_hash,
            "rules": [item.to_dict() for item in self.rules],
        }


@dataclass(frozen=True)
class PreflightReport(_HashBound):
    report_id: str
    policy_hash: str
    acl_manifest_hash: str
    observed_platform: str
    process_isolation_available: bool
    protected_read_only: bool
    hidden_gold_unmounted: bool
    resolved_path_allowlist_enforced: bool
    symlink_hardlink_checks_passed: bool
    clean_import_path: bool
    wheel_hash_verified: bool
    network_policy_enforced: bool
    checked_at: str

    def __post_init__(self) -> None:
        _text(self.report_id, "preflight report_id")
        _hash(self.policy_hash, "preflight policy hash")
        _hash(self.acl_manifest_hash, "preflight ACL hash")
        _external_text(self.observed_platform, "observed platform")
        for field_name in (
            "process_isolation_available",
            "protected_read_only",
            "hidden_gold_unmounted",
            "resolved_path_allowlist_enforced",
            "symlink_hardlink_checks_passed",
            "clean_import_path",
            "wheel_hash_verified",
            "network_policy_enforced",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ContractError(f"{field_name} must be boolean")
        _external_text(self.checked_at, "preflight checked_at")

    @property
    def passed(self) -> bool:
        return all(
            getattr(self, field_name)
            for field_name in (
                "process_isolation_available",
                "protected_read_only",
                "hidden_gold_unmounted",
                "resolved_path_allowlist_enforced",
                "symlink_hardlink_checks_passed",
                "clean_import_path",
                "wheel_hash_verified",
                "network_policy_enforced",
            )
        )

    def _body(self) -> dict[str, Any]:
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
        } | {"passed": self.passed}


@dataclass(frozen=True)
class ApprovalManifest(_HashBound):
    manifest_id: str
    version: int
    lock_sha256: str
    approved: bool
    approver_role_id: str | None
    approved_at: str | None

    def __post_init__(self) -> None:
        _text(self.manifest_id, "approval manifest_id")
        _version(self.version)
        _hash(self.lock_sha256, "approved lock hash")
        if not isinstance(self.approved, bool):
            raise ContractError("approved must be boolean")
        _optional_external_text(self.approver_role_id, "approver_role_id")
        _optional_external_text(self.approved_at, "approved_at")
        if self.approved and (
            self.approver_role_id is None or self.approved_at is None
        ):
            raise ContractError("approved lock requires approver role and time")
        if not self.approved and (
            self.approver_role_id is not None or self.approved_at is not None
        ):
            raise ContractError("unapproved lock cannot claim approval metadata")

    def _body(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "version": self.version,
            "lock_sha256": self.lock_sha256,
            "approved": self.approved,
            "approver_role_id": self.approver_role_id,
            "approved_at": self.approved_at,
        }


@dataclass(frozen=True)
class FormalLockBindings(_HashBound):
    bindings: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        normalized = tuple(
            (_text(name, "formal lock binding name"), _hash(value, name))
            for name, value in self.bindings
        )
        if len({name for name, _ in normalized}) != len(normalized):
            raise ContractError("formal lock binding names must be unique")
        object.__setattr__(self, "bindings", tuple(sorted(normalized)))

    @property
    def missing(self) -> tuple[str, ...]:
        known = {name for name, _ in self.bindings}
        return tuple(
            name for name in REQUIRED_FORMAL_LOCK_BINDINGS if name not in known
        )

    def __getitem__(self, name: str) -> str:
        try:
            return dict(self.bindings)[name]
        except KeyError as error:
            raise ContractError(f"formal lock binding is missing: {name}") from error

    def _body(self) -> dict[str, Any]:
        return {"bindings": dict(self.bindings)}


@dataclass(frozen=True)
class FormalReadinessInputs:
    case_scope_manifest: FormalCaseScopeManifest | None = None
    gold_scope_manifest: GoldScopeManifest | None = None
    formal_artifact_layout: FormalArtifactLayout | None = None
    gold_artifact_manifest: GoldArtifactManifest | None = None
    gold_mount_manifest: GoldMountManifest | None = None
    gold_records: tuple[GoldRecord, ...] = ()
    reviewer_records: tuple[BlindReviewerRecord, ...] = ()
    adjudication_records: tuple[AdjudicationRecord, ...] = ()
    operational_escalator_role_id: str | None = None
    human_evidence: HumanReviewEvidence | None = None
    judge_calibration_manifest: JCalManifest | None = None
    judge_card: JudgeCard | None = None
    judge_evidence: object | None = None
    transport_trust_root: object | None = None
    human_trust_root: object | None = None
    transport_verification_policy: object | None = None
    transport_receipt_batch: object | None = None
    human_signature_policy: object | None = None
    human_signature_envelopes: tuple[object, ...] = ()
    authorization_checkpoint_manifest: object | None = None
    authorization_checkpoint_envelopes: tuple[object, ...] = ()
    judge_probe_manifest: object | None = None
    judge_invocation_manifest: object | None = None
    judge_audit_manifest: JAuditManifest | None = None
    judge_audit_probe_manifest: object | None = None
    judge_audit_evidence: object | None = None
    judge_audit_transport_policy: object | None = None
    judge_audit_transport_batch: object | None = None
    judge_audit_stage_cost_ledger: object | None = None
    judge_audit_invocation_manifest: object | None = None
    judge_set_provenance_manifest: JudgeSetProvenanceManifest | None = None
    detection_oracle_manifest: object | None = None
    stage_budget_manifest: object | None = None
    stage_cost_ledger: object | None = None
    budget_policy: BudgetPolicy | None = None
    price_manifest: PriceManifest | None = None
    price_quote_receipts: tuple[object, ...] = ()
    price_receipt_contract: object | None = None
    isolation_policy: IsolationPolicy | None = None
    acl_manifest: ACLManifest | None = None
    preflight_report: PreflightReport | None = None
    preflight_evidence: PreflightEvidence | None = None
    approval_manifest: ApprovalManifest | None = None
    arm_order: ArmOrderManifest | None = None
    formal_lock_bindings: FormalLockBindings | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "gold_records",
            "reviewer_records",
            "adjudication_records",
            "human_signature_envelopes",
            "authorization_checkpoint_envelopes",
            "price_quote_receipts",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        _optional_external_text(
            self.operational_escalator_role_id,
            "operational escalator role",
        )
        if self.human_evidence is not None and not isinstance(
            self.human_evidence,
            HumanReviewEvidence,
        ):
            raise ContractError("human_evidence must be typed raw review evidence")
        if self.preflight_evidence is not None and not isinstance(
            self.preflight_evidence,
            PreflightEvidence,
        ):
            raise ContractError(
                "preflight_evidence must be typed raw preflight evidence"
            )
        if isinstance(self.judge_evidence, JudgeQualification):
            raise ContractError("formal readiness rejects naked JudgeQualification")
        if isinstance(self.judge_audit_evidence, JudgeQualification):
            raise ContractError(
                "formal readiness rejects naked J-AUDIT JudgeQualification"
            )
        if self.judge_audit_manifest is not None and not isinstance(
            self.judge_audit_manifest,
            JAuditManifest,
        ):
            raise ContractError("judge_audit_manifest must be typed JAuditManifest")
        if self.judge_set_provenance_manifest is not None and not isinstance(
            self.judge_set_provenance_manifest,
            JudgeSetProvenanceManifest,
        ):
            raise ContractError("judge_set_provenance_manifest must be typed")
        if self.judge_evidence is not None:
            evidence_hash = getattr(self.judge_evidence, "contract_hash", None)
            if (
                not callable(getattr(self.judge_evidence, "to_dict", None))
                or not isinstance(evidence_hash, str)
                or len(evidence_hash) != 64
            ):
                raise ContractError(
                    "judge_evidence must be a hash-bound derived evidence package"
                )
        for field_name in (
            "transport_trust_root",
            "human_trust_root",
            "transport_verification_policy",
            "transport_receipt_batch",
            "human_signature_policy",
            "authorization_checkpoint_manifest",
            "judge_probe_manifest",
            "judge_invocation_manifest",
            "judge_audit_probe_manifest",
            "judge_audit_evidence",
            "judge_audit_transport_policy",
            "judge_audit_transport_batch",
            "judge_audit_stage_cost_ledger",
            "judge_audit_invocation_manifest",
            "detection_oracle_manifest",
            "stage_budget_manifest",
            "stage_cost_ledger",
            "price_receipt_contract",
        ):
            value = getattr(self, field_name)
            if value is not None and (
                not callable(getattr(value, "to_dict", None))
                or not isinstance(getattr(value, "contract_hash", None), str)
            ):
                raise ContractError(f"{field_name} must be hash-bound")
        for field_name in (
            "human_signature_envelopes",
            "authorization_checkpoint_envelopes",
            "price_quote_receipts",
        ):
            if any(
                not callable(getattr(item, "to_dict", None))
                or not isinstance(getattr(item, "contract_hash", None), str)
                for item in getattr(self, field_name)
            ):
                raise ContractError(f"{field_name} must contain hash-bound results")

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_scope_manifest": (
                self.case_scope_manifest.to_dict()
                if self.case_scope_manifest is not None
                else None
            ),
            "gold_scope_manifest": (
                self.gold_scope_manifest.to_dict()
                if self.gold_scope_manifest is not None
                else None
            ),
            "formal_artifact_layout": (
                self.formal_artifact_layout.to_dict()
                if self.formal_artifact_layout is not None
                else None
            ),
            "gold_artifact_manifest": (
                self.gold_artifact_manifest.to_dict()
                if self.gold_artifact_manifest is not None
                else None
            ),
            "gold_mount_manifest": (
                self.gold_mount_manifest.to_dict()
                if self.gold_mount_manifest is not None
                else None
            ),
            "gold_records": [item.to_dict() for item in self.gold_records],
            "reviewer_records": [item.to_dict() for item in self.reviewer_records],
            "adjudication_records": [
                item.to_dict() for item in self.adjudication_records
            ],
            "operational_escalator_role_id": (self.operational_escalator_role_id),
            "human_evidence": (
                {
                    **self.human_evidence.to_dict(),
                    "evidence_sha256": (self.human_evidence.evidence_sha256),
                }
                if self.human_evidence is not None
                else None
            ),
            "judge_calibration_manifest": (
                self.judge_calibration_manifest.to_dict()
                if self.judge_calibration_manifest is not None
                else None
            ),
            "judge_card": (
                self.judge_card.to_dict() if self.judge_card is not None else None
            ),
            "judge_evidence": (
                self.judge_evidence.to_dict()
                if self.judge_evidence is not None
                else None
            ),
            "transport_trust_root": (
                self.transport_trust_root.to_dict()
                if self.transport_trust_root is not None
                else None
            ),
            "human_trust_root": (
                self.human_trust_root.to_dict()
                if self.human_trust_root is not None
                else None
            ),
            "transport_verification_policy": (
                self.transport_verification_policy.to_dict()
                if self.transport_verification_policy is not None
                else None
            ),
            "transport_receipt_batch": (
                self.transport_receipt_batch.to_dict()
                if self.transport_receipt_batch is not None
                else None
            ),
            "human_signature_policy": (
                self.human_signature_policy.to_dict()
                if self.human_signature_policy is not None
                else None
            ),
            "human_signature_envelopes": [
                item.to_dict() for item in self.human_signature_envelopes
            ],
            "authorization_checkpoint_manifest": (
                self.authorization_checkpoint_manifest.to_dict()
                if self.authorization_checkpoint_manifest is not None
                else None
            ),
            "authorization_checkpoint_envelopes": [
                item.to_dict() for item in self.authorization_checkpoint_envelopes
            ],
            "judge_probe_manifest": (
                {
                    **self.judge_probe_manifest.to_dict(),
                    "contract_hash": self.judge_probe_manifest.contract_hash,
                }
                if self.judge_probe_manifest is not None
                else None
            ),
            "judge_invocation_manifest": (
                self.judge_invocation_manifest.to_dict()
                if self.judge_invocation_manifest is not None
                else None
            ),
            "judge_audit_manifest": (
                self.judge_audit_manifest.to_dict()
                if self.judge_audit_manifest is not None
                else None
            ),
            "judge_audit_probe_manifest": (
                {
                    **self.judge_audit_probe_manifest.to_dict(),
                    "contract_hash": (self.judge_audit_probe_manifest.contract_hash),
                }
                if self.judge_audit_probe_manifest is not None
                else None
            ),
            "judge_audit_evidence": (
                self.judge_audit_evidence.to_dict()
                if self.judge_audit_evidence is not None
                else None
            ),
            "judge_audit_transport_policy": (
                self.judge_audit_transport_policy.to_dict()
                if self.judge_audit_transport_policy is not None
                else None
            ),
            "judge_audit_transport_batch": (
                self.judge_audit_transport_batch.to_dict()
                if self.judge_audit_transport_batch is not None
                else None
            ),
            "judge_audit_stage_cost_ledger": (
                self.judge_audit_stage_cost_ledger.to_dict()
                if self.judge_audit_stage_cost_ledger is not None
                else None
            ),
            "judge_audit_invocation_manifest": (
                self.judge_audit_invocation_manifest.to_dict()
                if self.judge_audit_invocation_manifest is not None
                else None
            ),
            "judge_set_provenance_manifest": (
                self.judge_set_provenance_manifest.to_dict()
                if self.judge_set_provenance_manifest is not None
                else None
            ),
            "detection_oracle_manifest": (
                self.detection_oracle_manifest.to_dict()
                if self.detection_oracle_manifest is not None
                else None
            ),
            "stage_budget_manifest": (
                self.stage_budget_manifest.to_dict()
                if self.stage_budget_manifest is not None
                else None
            ),
            "stage_cost_ledger": (
                self.stage_cost_ledger.to_dict()
                if self.stage_cost_ledger is not None
                else None
            ),
            "budget_policy": (
                self.budget_policy.to_dict() if self.budget_policy is not None else None
            ),
            "price_manifest": (
                self.price_manifest.to_dict()
                if self.price_manifest is not None
                else None
            ),
            "price_quote_receipts": [
                item.to_dict() for item in self.price_quote_receipts
            ],
            "price_receipt_contract": (
                self.price_receipt_contract.to_dict()
                if self.price_receipt_contract is not None
                else None
            ),
            "isolation_policy": (
                self.isolation_policy.to_dict()
                if self.isolation_policy is not None
                else None
            ),
            "acl_manifest": (
                self.acl_manifest.to_dict() if self.acl_manifest is not None else None
            ),
            "preflight_report": (
                self.preflight_report.to_dict()
                if self.preflight_report is not None
                else None
            ),
            "preflight_evidence": (
                {
                    **self.preflight_evidence.to_dict(),
                    "evidence_sha256": (self.preflight_evidence.evidence_sha256),
                }
                if self.preflight_evidence is not None
                else None
            ),
            "approval_manifest": (
                self.approval_manifest.to_dict()
                if self.approval_manifest is not None
                else None
            ),
            "arm_order": (
                self.arm_order.to_dict() if self.arm_order is not None else None
            ),
            "formal_lock_bindings": (
                self.formal_lock_bindings.to_dict()
                if self.formal_lock_bindings is not None
                else None
            ),
        }


@dataclass(frozen=True)
class FormalReadinessReport:
    state: FormalReadinessState
    blockers: tuple[ReadinessBlockerCode, ...]
    input_hashes: tuple[tuple[str, str | None], ...]
    report_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.state, FormalReadinessState):
            raise ContractError("formal readiness state is invalid")
        object.__setattr__(self, "blockers", tuple(self.blockers))
        object.__setattr__(self, "input_hashes", tuple(self.input_hashes))
        if (
            (self.state is FormalReadinessState.FORMAL_READY) != (not self.blockers)
            or len(set(self.blockers)) != len(self.blockers)
            or self.blockers
            != tuple(code for code in ReadinessBlockerCode if code in self.blockers)
        ):
            raise ContractError("formal readiness state and blockers disagree")
        if self.input_hashes != tuple(sorted(self.input_hashes)) or len(
            {name for name, _ in self.input_hashes}
        ) != len(self.input_hashes):
            raise ContractError("readiness input hashes must be unique and sorted")
        for name, digest in self.input_hashes:
            _text(name, "readiness input hash name")
            if digest is not None:
                _hash(digest, f"readiness input hash {name}")
        expected = _sha256(_canonical_json_bytes(self._body()))
        if self.report_hash != expected:
            raise ContractError("formal readiness report hash mismatch")

    def _body(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "blockers": [item.value for item in self.blockers],
            "input_hashes": dict(self.input_hashes),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "report_hash": self.report_hash}


def _sequence_hash(values: Sequence[Any]) -> str:
    payload = [
        value.contract_hash if isinstance(value, _HashBound) else value
        for value in values
    ]
    return _sha256(_canonical_json_bytes(payload))


def formal_gold_binding_hash(
    scope: GoldScopeManifest,
    records: Sequence[GoldRecord],
) -> str:
    if not isinstance(scope, GoldScopeManifest):
        raise ContractError("gold scope manifest is required")
    return _sha256(
        _canonical_json_bytes(
            {
                "gold_scope_hash": scope.contract_hash,
                "gold_record_hashes": sorted(item.contract_hash for item in records),
            }
        )
    )


class FormalReadinessValidator:
    """Produce a deterministic, hash-bound readiness report."""

    def __init__(
        self,
        *,
        transport_verifier: object | None = None,
        human_verifier: object | None = None,
    ) -> None:
        self._transport_verifier = transport_verifier
        self._human_verifier = human_verifier

    def validate(self, inputs: FormalReadinessInputs) -> FormalReadinessReport:
        if not isinstance(inputs, FormalReadinessInputs):
            raise ContractError("formal readiness inputs are invalid")
        blockers: set[ReadinessBlockerCode] = set()
        lock = inputs.formal_lock_bindings
        if lock is None or lock.missing:
            blockers.add(ReadinessBlockerCode.FORMAL_LOCK_BINDINGS_INCOMPLETE)
        case_scope = inputs.case_scope_manifest
        if case_scope is None:
            blockers.add(ReadinessBlockerCode.CASE_SCOPE_MISSING)
        elif len(case_scope.case_ids) != 36:
            blockers.add(ReadinessBlockerCode.CASE_SCOPE_INCOMPLETE)
        if case_scope is None or not case_scope.all_native:
            blockers.add(ReadinessBlockerCode.NATIVE_CASE_COVERAGE_INCOMPLETE)
        if inputs.arm_order is None:
            blockers.add(ReadinessBlockerCode.ARM_ORDER_MISSING)
        elif inputs.arm_order != arm_order_manifest():
            blockers.add(ReadinessBlockerCode.ARM_ORDER_INVALID)

        card = inputs.judge_card
        calibration = inputs.judge_calibration_manifest
        evidence = inputs.judge_evidence
        qualification = None
        if card is None:
            blockers.add(ReadinessBlockerCode.JUDGE_CARD_MISSING)
        elif not card.is_bound:
            blockers.add(ReadinessBlockerCode.JUDGE_CARD_UNBOUND)
        if calibration is None:
            blockers.add(ReadinessBlockerCode.JUDGE_CALIBRATION_MANIFEST_MISSING)
        if evidence is None:
            blockers.add(ReadinessBlockerCode.JUDGE_QUALIFICATION_MISSING)
        else:
            try:
                from .meas0_formal import (
                    DerivedJudgeQualification,
                    DerivedProbeJudgeQualification,
                    ExactInvocationManifest,
                    FormalEvidenceError,
                    require_production_judge_evidence,
                )

                if isinstance(evidence, DerivedProbeJudgeQualification):
                    qualification = evidence.qualification
                    if not qualification.qualified or evidence.quarantine is not None:
                        raise ContractError("probe Judge evidence is not qualified")
                    if (
                        evidence.attestation.test_only
                        or evidence.source_corpus.probe_manifest.test_only
                    ):
                        blockers.add(
                            ReadinessBlockerCode.JUDGE_EVIDENCE_PRODUCTION_TRUST_UNAVAILABLE
                        )
                elif isinstance(evidence, DerivedJudgeQualification):
                    qualification = require_production_judge_evidence(evidence)
                else:
                    raise ContractError(
                        "judge evidence is not derived from sealed corpus"
                    )
            except (ContractError, ValueError):
                blockers.add(ReadinessBlockerCode.JUDGE_NOT_QUALIFIED)
            else:
                if (
                    card is None
                    or calibration is None
                    or qualification.judge_card_hash != card.contract_hash
                    or qualification.set_kind != "J-CAL-v1"
                    or qualification.set_hash != calibration.contract_hash
                    or card.calibration_set_hash != calibration.contract_hash
                ):
                    blockers.add(ReadinessBlockerCode.JUDGE_NOT_QUALIFIED)

        try:
            from .meas0_detection_oracle import (
                DetectionOracleManifest,
                FormalDetectionOracleAuthorization,
            )
            from .meas0_formal import (
                DerivedProbeJudgeQualification,
                ExactInvocationManifest,
                FormalEvidenceError,
            )
            from .meas0_judge_probes import JudgeProbeManifest
            from .meas0_stage_cost import (
                PriceManifestReceiptContract,
                PriceQuoteReceipt,
                StageBudgetManifest,
                StageCostLedger,
            )
            from .meas0_trust import (
                AuthorizationCheckpointManifest,
                DeterministicTestSignatureVerifier,
                HumanTrustRootManifest,
                ProductionSignatureVerifier,
                ProductionVerificationResult,
                SignatureEnvelope,
                TransportReceiptBatch,
                TransportTrustRootManifest,
                TrustDomain,
                VerificationPolicy,
            )

            trust_roots_valid = (
                isinstance(
                    inputs.transport_trust_root,
                    TransportTrustRootManifest,
                )
                and isinstance(
                    inputs.human_trust_root,
                    HumanTrustRootManifest,
                )
                and inputs.transport_trust_root.test_only is False
                and inputs.human_trust_root.test_only is False
            )
            if inputs.transport_trust_root is None or inputs.human_trust_root is None:
                blockers.add(ReadinessBlockerCode.TRUST_ROOTS_MISSING)
            elif not trust_roots_valid:
                blockers.add(ReadinessBlockerCode.TRUST_ROOTS_INVALID)

            transport_batch = inputs.transport_receipt_batch
            transport_policy = inputs.transport_verification_policy
            transport_verification = None
            if transport_batch is None or transport_policy is None:
                blockers.add(ReadinessBlockerCode.TRANSPORT_RECEIPTS_MISSING)
            elif (
                not isinstance(
                    inputs.transport_trust_root,
                    TransportTrustRootManifest,
                )
                or not isinstance(transport_policy, VerificationPolicy)
                or not isinstance(transport_batch, TransportReceiptBatch)
            ):
                blockers.add(ReadinessBlockerCode.TRANSPORT_RECEIPTS_INVALID)
            else:
                verifier = self._transport_verifier
                if verifier is None:
                    transport_verification = (
                        DeterministicTestSignatureVerifier().verify_transport_batch(
                            batch=transport_batch,
                            root_manifest=inputs.transport_trust_root,
                            policy=transport_policy,
                        )
                    )
                elif not isinstance(verifier, ProductionSignatureVerifier):
                    blockers.add(ReadinessBlockerCode.TRANSPORT_RECEIPTS_INVALID)
                else:
                    transport_verification = verifier.verify_transport_batch(
                        batch=transport_batch,
                        root_manifest=inputs.transport_trust_root,
                        policy=transport_policy,
                    )
                if transport_verification is None:
                    pass
                elif isinstance(
                    transport_verification,
                    ProductionVerificationResult,
                ):
                    if (
                        transport_verification.authority.trust_domain
                        is not TrustDomain.TRANSPORT
                        or transport_verification.policy_hash
                        != transport_policy.contract_hash
                        or transport_verification.root_manifest_hash
                        != inputs.transport_trust_root.contract_hash
                        or transport_verification.payload_hash
                        != transport_batch.contract_hash
                    ):
                        blockers.add(ReadinessBlockerCode.TRANSPORT_RECEIPTS_INVALID)
                elif not transport_verification.contract_verified:
                    blockers.add(ReadinessBlockerCode.TRANSPORT_RECEIPTS_INVALID)
                elif not transport_verification.production_authorized:
                    blockers.add(
                        ReadinessBlockerCode.TRANSPORT_PRODUCTION_TRUST_UNAVAILABLE
                    )

            signature_envelopes = inputs.human_signature_envelopes
            signature_policy = inputs.human_signature_policy
            if not signature_envelopes or signature_policy is None:
                blockers.add(ReadinessBlockerCode.HUMAN_SIGNATURES_MISSING)
            elif (
                not isinstance(inputs.human_trust_root, HumanTrustRootManifest)
                or not isinstance(signature_policy, VerificationPolicy)
                or signature_policy.trust_domain is not TrustDomain.HUMAN_APPROVAL
                or inputs.approval_manifest is None
                or not all(
                    isinstance(item, SignatureEnvelope) for item in signature_envelopes
                )
            ):
                blockers.add(ReadinessBlockerCode.HUMAN_SIGNATURES_INVALID)
            else:
                verifier = self._human_verifier
                if verifier is not None and not isinstance(
                    verifier,
                    ProductionSignatureVerifier,
                ):
                    blockers.add(ReadinessBlockerCode.HUMAN_SIGNATURES_INVALID)
                    signature_results = ()
                else:
                    selected_verifier = (
                        DeterministicTestSignatureVerifier()
                        if verifier is None
                        else verifier
                    )
                    signature_results = tuple(
                        selected_verifier.verify_signature_envelope(
                            envelope=item,
                            payload_hash=inputs.approval_manifest.contract_hash,
                            root_manifest=inputs.human_trust_root,
                            policy=signature_policy,
                        )
                        for item in signature_envelopes
                    )
                if signature_results and all(
                    isinstance(item, ProductionVerificationResult)
                    and item.authority.trust_domain is TrustDomain.HUMAN_APPROVAL
                    and item.policy_hash == signature_policy.contract_hash
                    and item.root_manifest_hash == inputs.human_trust_root.contract_hash
                    and item.payload_hash == inputs.approval_manifest.contract_hash
                    for item in signature_results
                ):
                    pass
                elif signature_results and not all(
                    getattr(item, "verified", False) for item in signature_results
                ):
                    blockers.add(ReadinessBlockerCode.HUMAN_SIGNATURES_INVALID)
                elif signature_results and not all(
                    item.production_authorized for item in signature_results
                ):
                    blockers.add(
                        ReadinessBlockerCode.HUMAN_SIGNATURE_PRODUCTION_TRUST_UNAVAILABLE
                    )

            checkpoint_manifest = inputs.authorization_checkpoint_manifest
            checkpoint_envelopes = inputs.authorization_checkpoint_envelopes
            if checkpoint_manifest is None or not checkpoint_envelopes:
                blockers.add(ReadinessBlockerCode.AUTHORIZATION_CHECKPOINTS_MISSING)
            elif (
                not isinstance(
                    checkpoint_manifest,
                    AuthorizationCheckpointManifest,
                )
                or not isinstance(inputs.human_trust_root, HumanTrustRootManifest)
                or not isinstance(signature_policy, VerificationPolicy)
                or not checkpoint_manifest.matches_raw_envelopes(checkpoint_envelopes)
            ):
                blockers.add(ReadinessBlockerCode.AUTHORIZATION_CHECKPOINTS_INVALID)
            elif self._human_verifier is not None and not isinstance(
                self._human_verifier,
                ProductionSignatureVerifier,
            ):
                blockers.add(ReadinessBlockerCode.AUTHORIZATION_CHECKPOINTS_INVALID)
            else:
                checkpoint_verifier = (
                    DeterministicTestSignatureVerifier()
                    if self._human_verifier is None
                    else self._human_verifier
                )
                checkpoint_results = tuple(
                    checkpoint_verifier.verify_signature_envelope(
                        envelope=envelope,
                        payload_hash=requirement.payload_hash,
                        root_manifest=inputs.human_trust_root,
                        policy=signature_policy,
                    )
                    for envelope, requirement in zip(
                        checkpoint_envelopes,
                        checkpoint_manifest.requirements,
                        strict=True,
                    )
                )
                if all(
                    isinstance(item, ProductionVerificationResult)
                    and item.authority.trust_domain is TrustDomain.HUMAN_APPROVAL
                    and item.policy_hash == signature_policy.contract_hash
                    and item.root_manifest_hash == inputs.human_trust_root.contract_hash
                    and item.payload_hash == requirement.payload_hash
                    for item, requirement in zip(
                        checkpoint_results,
                        checkpoint_manifest.requirements,
                        strict=True,
                    )
                ):
                    pass
                elif not all(
                    getattr(item, "verified", False) for item in checkpoint_results
                ):
                    blockers.add(ReadinessBlockerCode.AUTHORIZATION_CHECKPOINTS_INVALID)
                else:
                    blockers.add(
                        ReadinessBlockerCode.AUTHORIZATION_CHECKPOINT_PRODUCTION_TRUST_UNAVAILABLE
                    )

            probe_manifest = inputs.judge_probe_manifest
            if probe_manifest is None:
                blockers.add(ReadinessBlockerCode.JUDGE_PROBE_MANIFEST_MISSING)
            elif (
                not isinstance(probe_manifest, JudgeProbeManifest)
                or transport_batch is None
                or len(transport_batch.plan.entries) != len(probe_manifest.calls)
            ):
                blockers.add(ReadinessBlockerCode.JUDGE_PROBE_MANIFEST_INVALID)
            elif probe_manifest.test_only:
                blockers.add(
                    ReadinessBlockerCode.JUDGE_PROBE_PRODUCTION_TRUST_UNAVAILABLE
                )

            invocation_manifest = inputs.judge_invocation_manifest
            if invocation_manifest is None:
                blockers.add(ReadinessBlockerCode.JUDGE_INVOCATION_MANIFEST_MISSING)
            elif (
                not isinstance(invocation_manifest, ExactInvocationManifest)
                or evidence is None
                or not isinstance(evidence, DerivedProbeJudgeQualification)
                or transport_batch is None
                or inputs.stage_cost_ledger is None
            ):
                blockers.add(ReadinessBlockerCode.JUDGE_INVOCATION_MEMBERSHIP_INVALID)
            else:
                try:
                    invocation_manifest.verify_membership(
                        probe_manifest=probe_manifest,
                        corpus=evidence.source_corpus,
                        transport_batch=transport_batch,
                        stage_cost_ledger=inputs.stage_cost_ledger,
                    )
                except (FormalEvidenceError, TypeError, ValueError):
                    blockers.add(
                        ReadinessBlockerCode.JUDGE_INVOCATION_MEMBERSHIP_INVALID
                    )

            detection_oracle = inputs.detection_oracle_manifest
            if detection_oracle is None:
                blockers.add(ReadinessBlockerCode.DETECTION_ORACLE_MISSING)
            elif isinstance(
                detection_oracle,
                FormalDetectionOracleAuthorization,
            ):
                try:
                    detection_oracle = detection_oracle.verify(self._human_verifier)
                except (TypeError, ValueError):
                    blockers.add(ReadinessBlockerCode.DETECTION_ORACLE_INVALID)
            if detection_oracle is not None and (
                not isinstance(detection_oracle, DetectionOracleManifest)
                or not detection_oracle.formal_eligible
            ):
                blockers.add(ReadinessBlockerCode.DETECTION_ORACLE_INVALID)

            stage_budget = inputs.stage_budget_manifest
            if stage_budget is None:
                blockers.add(ReadinessBlockerCode.STAGE_BUDGET_MANIFEST_MISSING)
            quote_receipts = inputs.price_quote_receipts
            price_receipt_contract = inputs.price_receipt_contract
            derived_price_contract = None
            if not quote_receipts:
                blockers.add(ReadinessBlockerCode.PRICE_QUOTE_RECEIPTS_MISSING)
            elif (
                inputs.price_manifest is None
                or not all(
                    isinstance(item, PriceQuoteReceipt) for item in quote_receipts
                )
                or not isinstance(
                    inputs.transport_trust_root,
                    TransportTrustRootManifest,
                )
                or not isinstance(transport_policy, VerificationPolicy)
                or not inputs.price_manifest.matches_quote_receipts(quote_receipts)
            ):
                blockers.add(ReadinessBlockerCode.PRICE_QUOTE_RECEIPTS_INVALID)
            else:
                price_verifier = (
                    DeterministicTestSignatureVerifier()
                    if self._transport_verifier is None
                    else self._transport_verifier
                )
                derived_price_contract = (
                    PriceManifestReceiptContract.derive_from_raw_receipts(
                        price_manifest=inputs.price_manifest,
                        receipts=quote_receipts,
                        verifier=price_verifier,
                        root_manifest=inputs.transport_trust_root,
                        policy=transport_policy,
                    )
                )
                if price_receipt_contract is not None and (
                    not isinstance(
                        price_receipt_contract,
                        PriceManifestReceiptContract,
                    )
                    or price_receipt_contract.contract_hash
                    != derived_price_contract.contract_hash
                ):
                    blockers.add(ReadinessBlockerCode.PRICE_QUOTE_RECEIPTS_INVALID)
                if not derived_price_contract.production_ready:
                    blockers.add(
                        ReadinessBlockerCode.PRICE_PRODUCTION_TRUST_UNAVAILABLE
                    )
            ledger = inputs.stage_cost_ledger
            if ledger is None:
                blockers.add(ReadinessBlockerCode.STAGE_COST_LEDGER_MISSING)
            elif (
                not isinstance(stage_budget, StageBudgetManifest)
                or not isinstance(ledger, StageCostLedger)
                or ledger.budget_manifest.contract_hash != stage_budget.contract_hash
                or inputs.price_manifest is None
                or ledger.price_manifest_hash != inputs.price_manifest.contract_hash
                or not ledger.entries
                or any(item.phase != "jcal" for item in ledger.entries)
                or ledger.phase_decision("jcal").stopped
            ):
                blockers.add(ReadinessBlockerCode.STAGE_COST_LEDGER_INVALID)

            audit_manifest = inputs.judge_audit_manifest
            audit_probe = inputs.judge_audit_probe_manifest
            audit_evidence = inputs.judge_audit_evidence
            audit_policy = inputs.judge_audit_transport_policy
            audit_batch = inputs.judge_audit_transport_batch
            audit_ledger = inputs.judge_audit_stage_cost_ledger
            audit_invocations = inputs.judge_audit_invocation_manifest
            provenance = inputs.judge_set_provenance_manifest

            if audit_manifest is None:
                blockers.add(ReadinessBlockerCode.JAUDIT_MANIFEST_MISSING)
            if audit_probe is None:
                blockers.add(ReadinessBlockerCode.JAUDIT_PROBE_MANIFEST_MISSING)
            elif (
                not isinstance(audit_probe, JudgeProbeManifest)
                or audit_manifest is None
                or audit_probe.judge_set_hash != audit_manifest.contract_hash
            ):
                blockers.add(ReadinessBlockerCode.JAUDIT_PROBE_MANIFEST_INVALID)
            elif audit_probe.test_only:
                blockers.add(
                    ReadinessBlockerCode.JAUDIT_PROBE_PRODUCTION_TRUST_UNAVAILABLE
                )
            if audit_evidence is None:
                blockers.add(ReadinessBlockerCode.JAUDIT_QUALIFICATION_MISSING)
            elif (
                not isinstance(
                    audit_evidence,
                    DerivedProbeJudgeQualification,
                )
                or audit_manifest is None
                or audit_evidence.qualification.set_kind != "J-AUDIT-v1"
                or audit_evidence.qualification.set_hash != audit_manifest.contract_hash
                or not audit_evidence.qualification.qualified
                or audit_evidence.quarantine is not None
                or (
                    isinstance(evidence, DerivedProbeJudgeQualification)
                    and (
                        audit_evidence.contract_hash == evidence.contract_hash
                        or audit_evidence.source_corpus_hash
                        == evidence.source_corpus_hash
                    )
                )
            ):
                blockers.add(ReadinessBlockerCode.JAUDIT_QUALIFICATION_INVALID)
            elif (
                audit_evidence.attestation.test_only
                or audit_evidence.source_corpus.probe_manifest.test_only
            ):
                blockers.add(
                    ReadinessBlockerCode.JAUDIT_EVIDENCE_PRODUCTION_TRUST_UNAVAILABLE
                )

            audit_transport_verification = None
            if audit_policy is None or audit_batch is None:
                blockers.add(ReadinessBlockerCode.JAUDIT_TRANSPORT_MISSING)
            elif (
                not isinstance(audit_policy, VerificationPolicy)
                or not isinstance(audit_batch, TransportReceiptBatch)
                or audit_batch.plan.phase != "jaudit"
                or (
                    isinstance(transport_batch, TransportReceiptBatch)
                    and (
                        audit_batch.contract_hash == transport_batch.contract_hash
                        or set(item.contract_hash for item in audit_batch.receipts)
                        & set(item.contract_hash for item in transport_batch.receipts)
                    )
                )
            ):
                blockers.add(ReadinessBlockerCode.JAUDIT_TRANSPORT_INVALID)
            else:
                audit_verifier = (
                    DeterministicTestSignatureVerifier()
                    if self._transport_verifier is None
                    else self._transport_verifier
                )
                audit_transport_verification = audit_verifier.verify_transport_batch(
                    batch=audit_batch,
                    root_manifest=inputs.transport_trust_root,
                    policy=audit_policy,
                )
                if isinstance(
                    audit_transport_verification,
                    ProductionVerificationResult,
                ):
                    if (
                        audit_transport_verification.authority.trust_domain
                        is not TrustDomain.TRANSPORT
                        or audit_transport_verification.policy_hash
                        != audit_policy.contract_hash
                        or audit_transport_verification.root_manifest_hash
                        != inputs.transport_trust_root.contract_hash
                        or audit_transport_verification.payload_hash
                        != audit_batch.contract_hash
                    ):
                        blockers.add(ReadinessBlockerCode.JAUDIT_TRANSPORT_INVALID)
                elif (
                    not audit_transport_verification.contract_verified
                    or not audit_transport_verification.production_authorized
                ):
                    blockers.add(ReadinessBlockerCode.JAUDIT_TRANSPORT_INVALID)

            if audit_ledger is None:
                blockers.add(ReadinessBlockerCode.JAUDIT_STAGE_LEDGER_MISSING)
            elif (
                not isinstance(audit_ledger, StageCostLedger)
                or audit_evidence is None
                or not isinstance(
                    audit_evidence,
                    DerivedProbeJudgeQualification,
                )
                or audit_ledger.contract_hash
                != audit_evidence.source_corpus.stage_cost_ledger.contract_hash
                or audit_ledger.phase_decision("jaudit").stopped
            ):
                blockers.add(ReadinessBlockerCode.JAUDIT_STAGE_LEDGER_INVALID)

            if audit_invocations is None:
                blockers.add(ReadinessBlockerCode.JAUDIT_INVOCATION_MANIFEST_MISSING)
            elif (
                not isinstance(audit_invocations, ExactInvocationManifest)
                or not isinstance(
                    audit_evidence,
                    DerivedProbeJudgeQualification,
                )
                or not isinstance(audit_batch, TransportReceiptBatch)
                or not isinstance(audit_ledger, StageCostLedger)
            ):
                blockers.add(ReadinessBlockerCode.JAUDIT_INVOCATION_MEMBERSHIP_INVALID)
            else:
                try:
                    audit_invocations.verify_membership(
                        probe_manifest=audit_probe,
                        corpus=audit_evidence.source_corpus,
                        transport_batch=audit_batch,
                        stage_cost_ledger=audit_ledger,
                    )
                except (FormalEvidenceError, TypeError, ValueError):
                    blockers.add(
                        ReadinessBlockerCode.JAUDIT_INVOCATION_MEMBERSHIP_INVALID
                    )

            if provenance is None:
                blockers.add(ReadinessBlockerCode.JUDGE_SET_PROVENANCE_MISSING)
            elif (
                not isinstance(provenance, JudgeSetProvenanceManifest)
                or calibration is None
                or audit_manifest is None
                or not isinstance(probe_manifest, JudgeProbeManifest)
                or not isinstance(audit_probe, JudgeProbeManifest)
                or provenance.jcal_set_hash != calibration.contract_hash
                or provenance.jaudit_set_hash != audit_manifest.contract_hash
                or provenance.jcal_protected_corpus_hash
                != probe_manifest.protected_corpus_hash
                or provenance.jaudit_protected_corpus_hash
                != audit_probe.protected_corpus_hash
            ):
                blockers.add(ReadinessBlockerCode.JUDGE_SET_DISJOINTNESS_INVALID)
        except (TypeError, ValueError):
            blockers.update(
                {
                    ReadinessBlockerCode.TRUST_ROOTS_INVALID,
                    ReadinessBlockerCode.TRANSPORT_RECEIPTS_INVALID,
                    ReadinessBlockerCode.HUMAN_SIGNATURES_INVALID,
                    ReadinessBlockerCode.AUTHORIZATION_CHECKPOINTS_INVALID,
                    ReadinessBlockerCode.PRICE_QUOTE_RECEIPTS_INVALID,
                    ReadinessBlockerCode.JUDGE_PROBE_MANIFEST_INVALID,
                    ReadinessBlockerCode.JUDGE_INVOCATION_MEMBERSHIP_INVALID,
                    ReadinessBlockerCode.JAUDIT_PROBE_MANIFEST_INVALID,
                    ReadinessBlockerCode.JAUDIT_QUALIFICATION_INVALID,
                    ReadinessBlockerCode.JAUDIT_TRANSPORT_INVALID,
                    ReadinessBlockerCode.JAUDIT_STAGE_LEDGER_INVALID,
                    ReadinessBlockerCode.JAUDIT_INVOCATION_MEMBERSHIP_INVALID,
                    ReadinessBlockerCode.JUDGE_SET_DISJOINTNESS_INVALID,
                    ReadinessBlockerCode.DETECTION_ORACLE_INVALID,
                    ReadinessBlockerCode.STAGE_COST_LEDGER_INVALID,
                }
            )

        human_assessment: HumanReviewAssessment | None = None
        if inputs.human_evidence is None:
            blockers.add(ReadinessBlockerCode.HUMAN_EVIDENCE_MISSING)
        else:
            human_assessment = HumanReviewAssessment.from_evidence(
                inputs.human_evidence
            )
            try:
                validate_production_human_evidence(inputs.human_evidence)
            except ValueError:
                blockers.add(ReadinessBlockerCode.HUMAN_EVIDENCE_INVALID)
            else:
                if (
                    inputs.operational_escalator_role_id
                    != inputs.human_evidence.operational_escalator_role_id
                ):
                    blockers.add(ReadinessBlockerCode.HUMAN_EVIDENCE_INVALID)

        preflight_assessment: PreflightAssessment | None = None
        if inputs.preflight_evidence is None:
            blockers.add(ReadinessBlockerCode.PREFLIGHT_MISSING)
            blockers.add(ReadinessBlockerCode.PREFLIGHT_EVIDENCE_MISSING)
        else:
            preflight_assessment = PreflightAssessment.from_evidence(
                inputs.preflight_evidence
            )
            try:
                validate_production_preflight(inputs.preflight_evidence)
            except ValueError:
                blockers.add(ReadinessBlockerCode.PREFLIGHT_FAILED)
                blockers.add(ReadinessBlockerCode.PREFLIGHT_EVIDENCE_INVALID)
            else:
                if (
                    inputs.isolation_policy is not None
                    and inputs.preflight_evidence.network_policy
                    != inputs.isolation_policy.network_policy
                ):
                    blockers.add(ReadinessBlockerCode.PREFLIGHT_FAILED)
                    blockers.add(ReadinessBlockerCode.PREFLIGHT_EVIDENCE_INVALID)

        self._validate_gold(inputs, blockers, human_assessment)
        self._validate_formal_artifacts(
            inputs,
            blockers,
            preflight_assessment,
        )
        if self._roles_overlap(inputs):
            blockers.add(ReadinessBlockerCode.ROLE_SEPARATION_VIOLATION)

        for value, code in (
            (inputs.budget_policy, ReadinessBlockerCode.BUDGET_POLICY_MISSING),
            (inputs.price_manifest, ReadinessBlockerCode.PRICE_MANIFEST_MISSING),
            (
                inputs.isolation_policy,
                ReadinessBlockerCode.ISOLATION_POLICY_MISSING,
            ),
            (inputs.acl_manifest, ReadinessBlockerCode.ACL_MANIFEST_MISSING),
        ):
            if value is None:
                blockers.add(code)
        if preflight_assessment is not None and (
            inputs.isolation_policy is None
            or inputs.acl_manifest is None
            or inputs.acl_manifest.policy_hash != inputs.isolation_policy.contract_hash
        ):
            blockers.add(ReadinessBlockerCode.PREFLIGHT_FAILED)
            blockers.add(ReadinessBlockerCode.PREFLIGHT_EVIDENCE_INVALID)
        if inputs.approval_manifest is None:
            blockers.add(ReadinessBlockerCode.APPROVAL_MISSING)
        elif (
            not inputs.approval_manifest.approved
            or lock is None
            or "preregistration_lock" in lock.missing
            or inputs.approval_manifest.lock_sha256 != lock["preregistration_lock"]
        ):
            blockers.add(ReadinessBlockerCode.APPROVAL_NOT_GRANTED)

        if lock is not None and not lock.missing:
            expected_bindings = {
                "case_manifest": (
                    inputs.case_scope_manifest.contract_hash
                    if inputs.case_scope_manifest is not None
                    else None
                ),
                "task_answer_gold": (
                    formal_gold_binding_hash(
                        inputs.gold_scope_manifest,
                        inputs.gold_records,
                    )
                    if inputs.gold_scope_manifest is not None
                    else None
                ),
                "judge_card": card.contract_hash if card is not None else None,
                "seed_block": (
                    inputs.arm_order.contract_hash
                    if inputs.arm_order is not None
                    else None
                ),
                "price_manifest": (
                    inputs.price_manifest.contract_hash
                    if inputs.price_manifest is not None
                    else None
                ),
                "budget_policy": (
                    inputs.budget_policy.contract_hash
                    if inputs.budget_policy is not None
                    else None
                ),
                "isolation_policy": (
                    inputs.isolation_policy.contract_hash
                    if inputs.isolation_policy is not None
                    else None
                ),
                "acl_manifest": (
                    inputs.acl_manifest.contract_hash
                    if inputs.acl_manifest is not None
                    else None
                ),
                "preflight_evidence": (
                    inputs.preflight_evidence.evidence_sha256
                    if inputs.preflight_evidence is not None
                    else None
                ),
                "human_evidence": (
                    inputs.human_evidence.evidence_sha256
                    if inputs.human_evidence is not None
                    else None
                ),
                "formal_artifact_layout": (
                    inputs.formal_artifact_layout.contract_hash
                    if inputs.formal_artifact_layout is not None
                    else None
                ),
                "gold_artifact_manifest": (
                    inputs.gold_artifact_manifest.contract_hash
                    if inputs.gold_artifact_manifest is not None
                    else None
                ),
                "gold_mount_manifest": (
                    inputs.gold_mount_manifest.contract_hash
                    if inputs.gold_mount_manifest is not None
                    else None
                ),
                "transport_trust_root": (
                    inputs.transport_trust_root.contract_hash
                    if inputs.transport_trust_root is not None
                    else None
                ),
                "human_trust_root": (
                    inputs.human_trust_root.contract_hash
                    if inputs.human_trust_root is not None
                    else None
                ),
                "transport_receipt_policy": (
                    inputs.transport_verification_policy.contract_hash
                    if inputs.transport_verification_policy is not None
                    else None
                ),
                "jcal_transport_batch_plan": (
                    inputs.transport_receipt_batch.plan.contract_hash
                    if inputs.transport_receipt_batch is not None
                    else None
                ),
                "human_signature_policy": (
                    inputs.human_signature_policy.contract_hash
                    if inputs.human_signature_policy is not None
                    else None
                ),
                "judge_probe_manifest": (
                    inputs.judge_probe_manifest.contract_hash
                    if inputs.judge_probe_manifest is not None
                    else None
                ),
                "detection_oracle": (
                    inputs.detection_oracle_manifest.contract_hash
                    if inputs.detection_oracle_manifest is not None
                    else None
                ),
                "stage_budget_manifest": (
                    inputs.stage_budget_manifest.contract_hash
                    if inputs.stage_budget_manifest is not None
                    else None
                ),
                "stage_cost_ledger": (
                    inputs.stage_cost_ledger.contract_hash
                    if inputs.stage_cost_ledger is not None
                    else None
                ),
            }
            if any(
                expected is None or lock[name] != expected
                for name, expected in expected_bindings.items()
            ):
                blockers.add(ReadinessBlockerCode.BINDING_MISMATCH)

        ordered = tuple(code for code in ReadinessBlockerCode if code in blockers)
        state = (
            FormalReadinessState.FORMAL_READY
            if not ordered
            else FormalReadinessState.DESIGN_COMPLETE_NOT_RUNNABLE
        )
        input_hashes = self._input_hashes(inputs)
        body = {
            "state": state.value,
            "blockers": [item.value for item in ordered],
            "input_hashes": dict(input_hashes),
        }
        return FormalReadinessReport(
            state=state,
            blockers=ordered,
            input_hashes=input_hashes,
            report_hash=_sha256(_canonical_json_bytes(body)),
        )

    @staticmethod
    def _validate_formal_artifacts(
        inputs: FormalReadinessInputs,
        blockers: set[ReadinessBlockerCode],
        preflight_assessment: PreflightAssessment | None,
    ) -> None:
        layout = inputs.formal_artifact_layout
        manifest = inputs.gold_artifact_manifest
        mount = inputs.gold_mount_manifest
        if layout is None:
            blockers.add(ReadinessBlockerCode.ARTIFACT_LAYOUT_MISSING)
        if manifest is None:
            blockers.add(ReadinessBlockerCode.GOLD_ARTIFACT_MANIFEST_MISSING)
        elif (
            layout is None
            or inputs.gold_scope_manifest is None
            or manifest.comparison_block_id != layout.comparison_block_id
            or manifest.gold_scope_hash != inputs.gold_scope_manifest.contract_hash
            or manifest.gold_binding_hash
            != formal_gold_binding_hash(
                inputs.gold_scope_manifest,
                inputs.gold_records,
            )
            or manifest.gold_record_hashes
            != tuple(item.contract_hash for item in inputs.gold_records)
            or manifest.reviewer_record_hashes
            != tuple(item.contract_hash for item in inputs.reviewer_records)
            or manifest.adjudication_record_hashes
            != tuple(item.contract_hash for item in inputs.adjudication_records)
        ):
            blockers.add(ReadinessBlockerCode.GOLD_ARTIFACT_MANIFEST_INVALID)
        if mount is None:
            blockers.add(ReadinessBlockerCode.GOLD_MOUNT_MANIFEST_MISSING)
        elif (
            layout is None
            or manifest is None
            or mount.comparison_block_id != layout.comparison_block_id
            or mount.gold_manifest_hash != manifest.contract_hash
            or inputs.isolation_policy is None
            or inputs.isolation_policy.gold_mounted_to_evaluator is not False
            or preflight_assessment is None
            or not preflight_assessment.checks["hidden_gold_unmounted"]
        ):
            blockers.add(ReadinessBlockerCode.GOLD_MOUNT_MANIFEST_INVALID)

    @staticmethod
    def _validate_gold(
        inputs: FormalReadinessInputs,
        blockers: set[ReadinessBlockerCode],
        human_assessment: HumanReviewAssessment | None,
    ) -> None:
        case_scope = inputs.case_scope_manifest
        gold_scope = inputs.gold_scope_manifest
        if gold_scope is None:
            blockers.add(ReadinessBlockerCode.GOLD_SCOPE_MISSING)
            return
        if (
            case_scope is None
            or gold_scope.case_scope_hash != case_scope.contract_hash
            or gold_scope.case_ids != case_scope.case_ids
            or len(gold_scope.expected_gold_keys) < 36
        ):
            blockers.add(ReadinessBlockerCode.GOLD_SCOPE_INCOMPLETE)
            return
        expected = set(gold_scope.expected_gold_keys)
        semantic = set(gold_scope.semantic_gold_keys)
        gold_by_key = {item.key: item for item in inputs.gold_records}
        if human_assessment is not None:
            derived = human_assessment.requirement_gold_by_key
            if set(derived) != expected or any(
                key not in gold_by_key
                or derived[key].verdict.value != gold_by_key[key].verdict.value
                for key in expected
            ):
                blockers.add(ReadinessBlockerCode.HUMAN_EVIDENCE_INVALID)
        if len(gold_by_key) != len(inputs.gold_records) or set(gold_by_key) != expected:
            blockers.add(ReadinessBlockerCode.GOLD_RECORDS_INCOMPLETE)
        reviews: dict[str, list[BlindReviewerRecord]] = defaultdict(list)
        for review in inputs.reviewer_records:
            reviews[review.key].append(review)
        adjudications = {item.key: item for item in inputs.adjudication_records}
        review_incomplete = False
        adjudication_incomplete = False
        role_violation = False
        all_gold_roles: set[str] = set()
        for key in expected:
            gold = gold_by_key.get(key)
            if gold is None:
                review_incomplete = True
                continue
            selected = reviews.get(key, [])
            required_count = 2 if key in semantic else 1
            if len(selected) != required_count or set(gold.reviewer_record_hashes) != {
                item.contract_hash for item in selected
            }:
                review_incomplete = True
                continue
            reviewer_roles = {item.reviewer_role_id for item in selected}
            if (
                len(reviewer_roles) != required_count
                or gold.author_role_id in reviewer_roles
            ):
                role_violation = True
            all_gold_roles.update(reviewer_roles)
            all_gold_roles.add(gold.author_role_id)
            if key in semantic and selected[0].verdict is not selected[1].verdict:
                adjudication = adjudications.get(key)
                if (
                    adjudication is None
                    or {
                        adjudication.first_review_hash,
                        adjudication.second_review_hash,
                    }
                    != {item.contract_hash for item in selected}
                    or adjudication.final_verdict is not gold.verdict
                    or gold.adjudication_record_hash != adjudication.contract_hash
                ):
                    adjudication_incomplete = True
                else:
                    if adjudication.adjudicator_role_id in reviewer_roles:
                        role_violation = True
                    all_gold_roles.add(adjudication.adjudicator_role_id)
            elif gold.adjudication_record_hash is not None:
                adjudication_incomplete = True
        if review_incomplete:
            blockers.add(ReadinessBlockerCode.GOLD_REVIEWS_INCOMPLETE)
        if adjudication_incomplete:
            blockers.add(ReadinessBlockerCode.GOLD_ADJUDICATIONS_INCOMPLETE)
        escalator = inputs.operational_escalator_role_id
        if escalator is None or escalator in all_gold_roles:
            role_violation = True
        if role_violation:
            blockers.add(ReadinessBlockerCode.ROLE_SEPARATION_VIOLATION)

        gold_by_case: dict[str, list[GoldRecord]] = defaultdict(list)
        for gold in inputs.gold_records:
            gold_by_case[gold.case_id].append(gold)
        if any(
            not records
            or len(
                {
                    (
                        item.gold_run_validity,
                        item.gold_status,
                        item.accept_allowed,
                        item.safety_violation,
                    )
                    for item in records
                }
            )
            != 1
            for case_id in gold_scope.case_ids
            for records in (gold_by_case.get(case_id, []),)
        ):
            blockers.add(ReadinessBlockerCode.GOLD_RECORDS_INCOMPLETE)

    @staticmethod
    def _roles_overlap(inputs: FormalReadinessInputs) -> bool:
        human = inputs.human_evidence
        categories = (
            {item.author_role_id for item in inputs.gold_records}
            | ({human.gold_author_role_id} if human is not None else set()),
            {item.reviewer_role_id for item in inputs.reviewer_records}
            | (
                {item.reviewer_role_id for item in human.blind_reviews}
                if human is not None
                else set()
            ),
            {item.adjudicator_role_id for item in inputs.adjudication_records}
            | (
                {item.adjudicator_role_id for item in human.adjudications}
                if human is not None
                else set()
            ),
            (
                {inputs.operational_escalator_role_id}
                if inputs.operational_escalator_role_id is not None
                else set()
            )
            | ({human.operational_escalator_role_id} if human is not None else set()),
            (
                {inputs.approval_manifest.approver_role_id}
                if inputs.approval_manifest is not None
                and inputs.approval_manifest.approver_role_id is not None
                else set()
            ),
        )
        return any(
            bool(categories[left] & categories[right])
            for left in range(len(categories))
            for right in range(left + 1, len(categories))
        )

    @staticmethod
    def _input_hashes(
        inputs: FormalReadinessInputs,
    ) -> tuple[tuple[str, str | None], ...]:
        values: dict[str, str | None] = {
            "gold_records": _sequence_hash(inputs.gold_records),
            "reviewer_records": _sequence_hash(inputs.reviewer_records),
            "adjudication_records": _sequence_hash(inputs.adjudication_records),
            "operational_escalator_role": (
                _sha256(inputs.operational_escalator_role_id.encode("utf-8"))
                if inputs.operational_escalator_role_id is not None
                else None
            ),
        }
        for name, value in (
            ("case_scope_manifest", inputs.case_scope_manifest),
            ("gold_scope_manifest", inputs.gold_scope_manifest),
            ("formal_artifact_layout", inputs.formal_artifact_layout),
            ("gold_artifact_manifest", inputs.gold_artifact_manifest),
            ("gold_mount_manifest", inputs.gold_mount_manifest),
            ("judge_calibration_manifest", inputs.judge_calibration_manifest),
            ("judge_card", inputs.judge_card),
            ("transport_trust_root", inputs.transport_trust_root),
            ("human_trust_root", inputs.human_trust_root),
            (
                "transport_verification_policy",
                inputs.transport_verification_policy,
            ),
            ("transport_receipt_batch", inputs.transport_receipt_batch),
            ("human_signature_policy", inputs.human_signature_policy),
            (
                "authorization_checkpoint_manifest",
                inputs.authorization_checkpoint_manifest,
            ),
            ("judge_probe_manifest", inputs.judge_probe_manifest),
            ("judge_invocation_manifest", inputs.judge_invocation_manifest),
            ("judge_audit_manifest", inputs.judge_audit_manifest),
            (
                "judge_audit_probe_manifest",
                inputs.judge_audit_probe_manifest,
            ),
            (
                "judge_audit_transport_policy",
                inputs.judge_audit_transport_policy,
            ),
            (
                "judge_audit_transport_batch",
                inputs.judge_audit_transport_batch,
            ),
            (
                "judge_audit_stage_cost_ledger",
                inputs.judge_audit_stage_cost_ledger,
            ),
            (
                "judge_audit_invocation_manifest",
                inputs.judge_audit_invocation_manifest,
            ),
            (
                "judge_set_provenance_manifest",
                inputs.judge_set_provenance_manifest,
            ),
            ("detection_oracle_manifest", inputs.detection_oracle_manifest),
            ("stage_budget_manifest", inputs.stage_budget_manifest),
            ("stage_cost_ledger", inputs.stage_cost_ledger),
            ("budget_policy", inputs.budget_policy),
            ("price_manifest", inputs.price_manifest),
            ("price_receipt_contract", inputs.price_receipt_contract),
            ("isolation_policy", inputs.isolation_policy),
            ("acl_manifest", inputs.acl_manifest),
            ("preflight_report", inputs.preflight_report),
            ("approval_manifest", inputs.approval_manifest),
            ("arm_order", inputs.arm_order),
            ("formal_lock_bindings", inputs.formal_lock_bindings),
        ):
            contract_hash = getattr(value, "contract_hash", None)
            values[name] = contract_hash if isinstance(contract_hash, str) else None
        values["human_signature_envelopes"] = (
            _sha256(
                _canonical_json_bytes(
                    [item.contract_hash for item in inputs.human_signature_envelopes]
                )
            )
            if inputs.human_signature_envelopes
            else None
        )
        values["authorization_checkpoint_envelopes"] = (
            _sha256(
                _canonical_json_bytes(
                    [
                        item.contract_hash
                        for item in inputs.authorization_checkpoint_envelopes
                    ]
                )
            )
            if inputs.authorization_checkpoint_envelopes
            else None
        )
        values["price_quote_receipts"] = (
            _sha256(
                _canonical_json_bytes(
                    [item.contract_hash for item in inputs.price_quote_receipts]
                )
            )
            if inputs.price_quote_receipts
            else None
        )
        evidence_hash = getattr(inputs.judge_evidence, "contract_hash", None)
        values["judge_evidence"] = (
            evidence_hash if isinstance(evidence_hash, str) else None
        )
        audit_evidence_hash = getattr(
            inputs.judge_audit_evidence,
            "contract_hash",
            None,
        )
        values["judge_audit_evidence"] = (
            audit_evidence_hash if isinstance(audit_evidence_hash, str) else None
        )
        preflight = inputs.preflight_evidence
        values.update(
            {
                "preflight_evidence": (
                    preflight.evidence_sha256 if preflight is not None else None
                ),
                "preflight_command_records": (
                    _sha256(
                        _canonical_json_bytes(
                            [
                                item.raw_record_sha256
                                for item in preflight.command_records
                            ]
                        )
                    )
                    if preflight is not None
                    else None
                ),
                "preflight_environment": (
                    preflight.environment_sha256 if preflight is not None else None
                ),
                "preflight_dependencies": (
                    preflight.dependency_manifest_sha256
                    if preflight is not None
                    else None
                ),
                "preflight_acl_audit": (
                    preflight.acl_audit_log_sha256 if preflight is not None else None
                ),
            }
        )
        human = inputs.human_evidence
        values.update(
            {
                "human_evidence": (
                    human.evidence_sha256 if human is not None else None
                ),
                "human_review_records": (
                    _sha256(
                        _canonical_json_bytes(
                            [item.record_hash for item in human.blind_reviews]
                        )
                    )
                    if human is not None
                    else None
                ),
                "human_adjudication_records": (
                    _sha256(
                        _canonical_json_bytes(
                            [item.record_hash for item in human.adjudications]
                        )
                    )
                    if human is not None
                    else None
                ),
            }
        )
        return tuple(sorted(values.items()))


def require_formal_readiness(
    report: FormalReadinessReport,
) -> FormalReadinessReport:
    if not isinstance(report, FormalReadinessReport):
        raise ContractError("formal readiness report is invalid")
    report.__post_init__()
    if report.state is not FormalReadinessState.FORMAL_READY:
        raise ContractError(
            "formal MEAS0 is not runnable: "
            + ",".join(item.value for item in report.blockers)
        )
    return report


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be an object")
    return {str(key): item for key, item in value.items()}


def _verify_declared_hash(value: Mapping[str, Any], contract: _HashBound) -> None:
    declared = value.get("contract_hash")
    if declared != contract.contract_hash:
        raise ContractError("serialized contract hash mismatch")


def _case_scope_from_dict(value: object) -> FormalCaseScopeManifest:
    raw = _object(value, "case scope")
    cases = tuple(
        FormalCaseIdentity(
            case_id=str(item["case_id"]),
            task_id=str(item["task_id"]),
            task_version=int(item["task_version"]),
            fault_id=str(item["fault_id"]),
            native_adapter=item["native_adapter"],
            case_descriptor_hash=str(item["case_descriptor_hash"]),
        )
        for item in (_object(entry, "formal case") for entry in raw.get("cases", ()))
    )
    for entry, contract in zip(raw.get("cases", ()), cases, strict=True):
        _verify_declared_hash(_object(entry, "formal case"), contract)
    result = FormalCaseScopeManifest(
        manifest_id=str(raw["manifest_id"]),
        version=int(raw["version"]),
        mutation_seed=int(raw["mutation_seed"]),
        cases=cases,
    )
    _verify_declared_hash(raw, result)
    return result


def _gold_scope_from_dict(value: object) -> GoldScopeManifest:
    raw = _object(value, "gold scope")
    items = tuple(
        GoldScopeItem(
            case_id=str(item["case_id"]),
            requirement_ids=tuple(item.get("requirement_ids", ())),
        )
        for item in (
            _object(entry, "gold scope item") for entry in raw.get("items", ())
        )
    )
    for entry, contract in zip(raw.get("items", ()), items, strict=True):
        _verify_declared_hash(_object(entry, "gold scope item"), contract)
    result = GoldScopeManifest(
        manifest_id=str(raw["manifest_id"]),
        version=int(raw["version"]),
        case_scope_hash=str(raw["case_scope_hash"]),
        items=items,
        semantic_gold_keys=tuple(raw.get("semantic_gold_keys", ())),
    )
    _verify_declared_hash(raw, result)
    return result


def _review_from_dict(value: object) -> BlindReviewerRecord:
    raw = _object(value, "reviewer record")
    result = BlindReviewerRecord(
        review_id=str(raw["review_id"]),
        reviewer_role_id=str(raw["reviewer_role_id"]),
        case_id=str(raw["case_id"]),
        requirement_id=str(raw["requirement_id"]),
        verdict=EvaluationStatus(str(raw["verdict"])),
        evidence_refs=tuple(raw.get("evidence_refs", ())),
        rationale=str(raw["rationale"]),
        blinded_to_arm=raw["blinded_to_arm"],
        blinded_to_model=raw["blinded_to_model"],
    )
    _verify_declared_hash(raw, result)
    return result


def _adjudication_from_dict(value: object) -> AdjudicationRecord:
    raw = _object(value, "adjudication record")
    result = AdjudicationRecord(
        adjudication_id=str(raw["adjudication_id"]),
        case_id=str(raw["case_id"]),
        requirement_id=str(raw["requirement_id"]),
        first_review_hash=str(raw["first_review_hash"]),
        first_verdict=EvaluationStatus(str(raw["first_verdict"])),
        second_review_hash=str(raw["second_review_hash"]),
        second_verdict=EvaluationStatus(str(raw["second_verdict"])),
        adjudicator_role_id=str(raw["adjudicator_role_id"]),
        final_verdict=EvaluationStatus(str(raw["final_verdict"])),
        evidence_refs=tuple(raw.get("evidence_refs", ())),
        rationale=str(raw["rationale"]),
    )
    _verify_declared_hash(raw, result)
    return result


def _gold_from_dict(value: object) -> GoldRecord:
    raw = _object(value, "gold record")
    raw_status = raw.get("gold_status")
    result = GoldRecord(
        gold_id=str(raw["gold_id"]),
        case_id=str(raw["case_id"]),
        requirement_id=str(raw["requirement_id"]),
        verdict=EvaluationStatus(str(raw["verdict"])),
        evidence_refs=tuple(raw.get("evidence_refs", ())),
        rationale=str(raw["rationale"]),
        gold_source_ref=str(raw["gold_source_ref"]),
        author_role_id=str(raw["author_role_id"]),
        semantic=raw["semantic"],
        gold_run_validity=GoldRunValidity(str(raw["gold_run_validity"])),
        gold_status=(
            EvaluationStatus(str(raw_status)) if raw_status is not None else None
        ),
        accept_allowed=raw["accept_allowed"],
        safety_violation=raw["safety_violation"],
        reviewer_record_hashes=tuple(raw.get("reviewer_record_hashes", ())),
        adjudication_record_hash=raw.get("adjudication_record_hash"),
    )
    _verify_declared_hash(raw, result)
    return result


def _judge_item_from_dict(value: object) -> JudgeSetItem:
    raw = _object(value, "Judge set item")
    result = JudgeSetItem(
        item_id=str(raw["item_id"]),
        criterion_id=str(raw["criterion_id"]),
        gold_verdict=EvaluationStatus(str(raw["gold_verdict"])),
        normal_presentation_hash=str(raw["normal_presentation_hash"]),
        reversed_presentation_hash=str(raw["reversed_presentation_hash"]),
        held_out=raw["held_out"],
    )
    _verify_declared_hash(raw, result)
    return result


def _jcal_from_dict(value: object) -> JCalManifest:
    raw = _object(value, "J-CAL manifest")
    result = JCalManifest(
        manifest_id=str(raw["manifest_id"]),
        version=int(raw["version"]),
        effective_seeds=tuple(raw.get("effective_seeds", ())),
        items=tuple(_judge_item_from_dict(item) for item in raw.get("items", ())),
    )
    _verify_declared_hash(raw, result)
    return result


def _jaudit_from_dict(value: object) -> JAuditManifest:
    raw = _object(value, "J-AUDIT manifest")
    result = JAuditManifest(
        manifest_id=str(raw["manifest_id"]),
        version=int(raw["version"]),
        effective_seeds=tuple(raw.get("effective_seeds", ())),
        items=tuple(_judge_item_from_dict(item) for item in raw.get("items", ())),
    )
    _verify_declared_hash(raw, result)
    return result


def _judge_set_provenance_from_dict(
    value: object,
) -> JudgeSetProvenanceManifest:
    raw = _object(value, "Judge set provenance manifest")
    result = JudgeSetProvenanceManifest(
        manifest_id=str(raw["manifest_id"]),
        version=int(raw["version"]),
        jcal_set_hash=str(raw["jcal_set_hash"]),
        jaudit_set_hash=str(raw["jaudit_set_hash"]),
        jcal_protected_corpus_hash=str(raw["jcal_protected_corpus_hash"]),
        jaudit_protected_corpus_hash=str(raw["jaudit_protected_corpus_hash"]),
        jcal_source_ids=tuple(raw.get("jcal_source_ids", ())),
        jaudit_source_ids=tuple(raw.get("jaudit_source_ids", ())),
        jcal_template_ids=tuple(raw.get("jcal_template_ids", ())),
        jaudit_template_ids=tuple(raw.get("jaudit_template_ids", ())),
        jcal_entity_ids=tuple(raw.get("jcal_entity_ids", ())),
        jaudit_entity_ids=tuple(raw.get("jaudit_entity_ids", ())),
    )
    _verify_declared_hash(raw, result)
    return result


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
    _verify_declared_hash(raw, result)
    return result


def _rate_from_dict(value: object) -> RateEstimate:
    raw = _object(value, "rate estimate")
    result = RateEstimate(
        value=float(raw["value"]),
        lower=float(raw["lower"]),
        upper=float(raw["upper"]),
        denominator=int(raw["denominator"]),
    )
    _verify_declared_hash(raw, result)
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
    _verify_declared_hash(raw, result)
    return result


def _derived_judge_evidence_from_dict(value: object) -> object:
    from .meas0_formal import (
        FormalEvidenceError,
        derived_probe_judge_qualification_from_dict,
        derived_judge_qualification_from_dict,
    )

    try:
        raw = _object(value, "derived Judge evidence")
        source = _object(raw.get("source_corpus", {}), "Judge source corpus")
        if "probe_manifest" in source:
            return derived_probe_judge_qualification_from_dict(value)
        return derived_judge_qualification_from_dict(value)
    except FormalEvidenceError as error:
        raise ContractError("serialized derived Judge evidence is invalid") from error


def _budget_from_dict(value: object) -> BudgetPolicy:
    raw = _object(value, "budget policy")
    limits = tuple(
        TaskBudgetLimit(
            task_id=str(item["task_id"]),
            deterministic_checks=int(item["deterministic_checks"]),
            judge_calls_per_semantic_leaf=int(item["judge_calls_per_semantic_leaf"]),
            judge_input_tokens=int(item["judge_input_tokens"]),
            judge_output_tokens=int(item["judge_output_tokens"]),
            human_escalations=int(item["human_escalations"]),
            evaluator_retries=int(item["evaluator_retries"]),
            deterministic_wall_time_ms=int(item["deterministic_wall_time_ms"]),
            judge_wall_time_ms=int(item["judge_wall_time_ms"]),
        )
        for item in (
            _object(entry, "task budget") for entry in raw.get("task_limits", ())
        )
    )
    for entry, contract in zip(raw.get("task_limits", ()), limits, strict=True):
        _verify_declared_hash(_object(entry, "task budget"), contract)
    result = BudgetPolicy(
        policy_id=str(raw["policy_id"]),
        version=int(raw["version"]),
        task_limits=limits,
        pilot_judge_calls=int(raw["pilot_judge_calls"]),
        pilot_human_escalations=int(raw["pilot_human_escalations"]),
        exhaustion_status=EvaluationStatus(str(raw["exhaustion_status"])),
        retain_exhausted_cases=raw["retain_exhausted_cases"],
    )
    _verify_declared_hash(raw, result)
    return result


def _price_from_dict(value: object) -> PriceManifest:
    raw = _object(value, "price manifest")
    prices = tuple(
        ProviderPrice(
            provider=str(item["provider"]),
            model_id=str(item["model_id"]),
            input_per_million_microunits=int(item["input_per_million_microunits"]),
            output_per_million_microunits=int(item["output_per_million_microunits"]),
            metered_tool_microunits=int(item["metered_tool_microunits"]),
        )
        for item in (
            _object(entry, "provider price") for entry in raw.get("provider_prices", ())
        )
    )
    for entry, contract in zip(raw.get("provider_prices", ()), prices, strict=True):
        _verify_declared_hash(_object(entry, "provider price"), contract)
    result = PriceManifest(
        manifest_id=str(raw["manifest_id"]),
        version=int(raw["version"]),
        currency=str(raw["currency"]),
        effective_at=str(raw["effective_at"]),
        fx_as_of=str(raw["fx_as_of"]),
        direct_cap_microunits=int(raw["direct_cap_microunits"]),
        provider_prices=prices,
    )
    _verify_declared_hash(raw, result)
    return result


def _formal_artifact_layout_from_dict(value: object) -> FormalArtifactLayout:
    raw = _object(value, "formal artifact layout")
    result = FormalArtifactLayout(
        comparison_block_id=str(raw["comparison_block_id"]),
        gold_directory=str(raw["gold_directory"]),
        gold_manifest_path=str(raw["gold_manifest_path"]),
        gold_mount_manifest_path=str(raw["gold_mount_manifest_path"]),
    )
    _verify_declared_hash(raw, result)
    return result


def _gold_artifact_manifest_from_dict(
    value: object,
) -> GoldArtifactManifest:
    raw = _object(value, "gold artifact manifest")
    result = GoldArtifactManifest(
        manifest_id=str(raw["manifest_id"]),
        version=raw["version"],
        comparison_block_id=str(raw["comparison_block_id"]),
        gold_scope_hash=str(raw["gold_scope_hash"]),
        gold_binding_hash=str(raw["gold_binding_hash"]),
        gold_record_hashes=tuple(raw.get("gold_record_hashes", ())),
        reviewer_record_hashes=tuple(raw.get("reviewer_record_hashes", ())),
        adjudication_record_hashes=tuple(raw.get("adjudication_record_hashes", ())),
    )
    _verify_declared_hash(raw, result)
    return result


def _gold_mount_manifest_from_dict(value: object) -> GoldMountManifest:
    raw = _object(value, "gold mount manifest")
    result = GoldMountManifest(
        manifest_id=str(raw["manifest_id"]),
        version=raw["version"],
        comparison_block_id=str(raw["comparison_block_id"]),
        gold_manifest_hash=str(raw["gold_manifest_hash"]),
        runtime_gold_path=str(raw["runtime_gold_path"]),
        subject_mounted=raw["subject_mounted"],
        evaluator_mounted=raw["evaluator_mounted"],
        judge_mounted=raw["judge_mounted"],
        review_plane_read_only=raw["review_plane_read_only"],
    )
    _verify_declared_hash(raw, result)
    return result


def _isolation_from_dict(value: object) -> IsolationPolicy:
    raw = _object(value, "isolation policy")
    result = IsolationPolicy(
        policy_id=str(raw["policy_id"]),
        version=int(raw["version"]),
        subject_read_roots=tuple(raw.get("subject_read_roots", ())),
        subject_write_roots=tuple(raw.get("subject_write_roots", ())),
        evaluator_read_roots=tuple(raw.get("evaluator_read_roots", ())),
        evaluator_write_roots=tuple(raw.get("evaluator_write_roots", ())),
        judge_read_roots=tuple(raw.get("judge_read_roots", ())),
        gold_mounted_to_evaluator=raw["gold_mounted_to_evaluator"],
        network_policy=str(raw["network_policy"]),
        require_read_only_protected=raw["require_read_only_protected"],
        require_clean_import_path=raw["require_clean_import_path"],
        require_wheel_hash=raw["require_wheel_hash"],
        platform_neutral=raw["platform_neutral"],
    )
    _verify_declared_hash(raw, result)
    return result


def _acl_from_dict(value: object) -> ACLManifest:
    raw = _object(value, "ACL manifest")
    rules = tuple(
        ACLRule(
            principal=str(item["principal"]),
            resolved_path=str(item["resolved_path"]),
            permissions=tuple(item.get("permissions", ())),
        )
        for item in (_object(entry, "ACL rule") for entry in raw.get("rules", ()))
    )
    for entry, contract in zip(raw.get("rules", ()), rules, strict=True):
        _verify_declared_hash(_object(entry, "ACL rule"), contract)
    result = ACLManifest(
        manifest_id=str(raw["manifest_id"]),
        version=int(raw["version"]),
        policy_hash=str(raw["policy_hash"]),
        rules=rules,
    )
    _verify_declared_hash(raw, result)
    return result


def _preflight_from_dict(value: object) -> PreflightReport:
    raw = _object(value, "preflight report")
    result = PreflightReport(
        report_id=str(raw["report_id"]),
        policy_hash=str(raw["policy_hash"]),
        acl_manifest_hash=str(raw["acl_manifest_hash"]),
        observed_platform=str(raw["observed_platform"]),
        process_isolation_available=raw["process_isolation_available"],
        protected_read_only=raw["protected_read_only"],
        hidden_gold_unmounted=raw["hidden_gold_unmounted"],
        resolved_path_allowlist_enforced=raw["resolved_path_allowlist_enforced"],
        symlink_hardlink_checks_passed=raw["symlink_hardlink_checks_passed"],
        clean_import_path=raw["clean_import_path"],
        wheel_hash_verified=raw["wheel_hash_verified"],
        network_policy_enforced=raw["network_policy_enforced"],
        checked_at=str(raw["checked_at"]),
    )
    _verify_declared_hash(raw, result)
    return result


def _preflight_evidence_from_dict(value: object) -> PreflightEvidence:
    raw = _object(value, "derived preflight evidence")
    records: list[CommandRecord] = []
    for item in raw.get("command_records", ()):
        record_raw = _object(item, "preflight command record")
        spec = CommandSpec(
            command_id=str(record_raw["command_id"]),
            argv=tuple(record_raw.get("argv", ())),
        )
        result = ExecutorResult(
            exit_code=int(record_raw["exit_code"]),
            stdout=bytes.fromhex(str(record_raw["stdout_hex"])),
            stderr=bytes.fromhex(str(record_raw["stderr_hex"])),
        )
        record = CommandRecord.capture(spec, result)
        if (
            record_raw.get("stdout_sha256") != record.stdout_sha256
            or record_raw.get("stderr_sha256") != record.stderr_sha256
            or record_raw.get("raw_record_sha256") != record.raw_record_sha256
        ):
            raise ContractError("serialized preflight command record hash mismatch")
        records.append(record)
    mounts = tuple(
        MountDeclaration(
            mount_id=str(item["mount_id"]),
            principal=str(item["principal"]),
            source_path=str(item["source_path"]),
            target_path=str(item["target_path"]),
            mounted=item["mounted"],
            read_only=item["read_only"],
            contains_hidden_gold=item["contains_hidden_gold"],
        )
        for item in (
            _object(entry, "preflight mount declaration")
            for entry in raw.get("mounts", ())
        )
    )
    environment = _object(
        raw.get("environment", {}),
        "preflight environment",
    )
    dependencies = _object(
        raw.get("dependencies", {}),
        "preflight dependencies",
    )
    result = PreflightEvidence(
        attestation_kind=PreflightAttestationKind(str(raw["attestation_kind"])),
        executor_id=str(raw["executor_id"]),
        command_records=tuple(records),
        environment=tuple(
            sorted((str(key), str(item)) for key, item in environment.items())
        ),
        dependencies=tuple(
            sorted((str(key), str(item)) for key, item in dependencies.items())
        ),
        mounts=mounts,
        network_policy=str(raw["network_policy"]),
        process_policy=str(raw["process_policy"]),
        acl_audit_log=bytes.fromhex(str(raw["acl_audit_log_hex"])),
    )
    if (
        raw.get("environment_sha256") != result.environment_sha256
        or raw.get("dependency_manifest_sha256") != result.dependency_manifest_sha256
        or raw.get("acl_audit_log_sha256") != result.acl_audit_log_sha256
        or raw.get("evidence_sha256") != result.evidence_sha256
    ):
        raise ContractError("serialized preflight evidence hash mismatch")
    return result


def _human_evidence_from_dict(value: object) -> HumanReviewEvidence:
    raw = _object(value, "derived human evidence")
    scope = tuple(
        ReviewScopeItem(
            case_id=str(item["case_id"]),
            requirement_id=str(item["requirement_id"]),
        )
        for item in (
            _object(entry, "human review scope item") for entry in raw.get("scope", ())
        )
    )
    reviews: list[DerivedBlindReviewRecord] = []
    for item in raw.get("blind_reviews", ()):
        review_raw = _object(item, "derived blind review record")
        review = DerivedBlindReviewRecord(
            review_id=str(review_raw["review_id"]),
            reviewer_role_id=str(review_raw["reviewer_role_id"]),
            case_id=str(review_raw["case_id"]),
            requirement_id=str(review_raw["requirement_id"]),
            verdict=ReviewVerdict(str(review_raw["verdict"])),
            evidence_refs=tuple(review_raw.get("evidence_refs", ())),
            rationale=str(review_raw["rationale"]),
            blinded_to_arm=review_raw["blinded_to_arm"],
            blinded_to_model=review_raw["blinded_to_model"],
        )
        if review_raw.get("record_hash") != review.record_hash:
            raise ContractError("serialized blind review record hash mismatch")
        reviews.append(review)
    adjudications: list[ReviewAdjudicationRecord] = []
    for item in raw.get("adjudications", ()):
        adjudication_raw = _object(
            item,
            "derived review adjudication record",
        )
        adjudication = ReviewAdjudicationRecord(
            adjudication_id=str(adjudication_raw["adjudication_id"]),
            case_id=str(adjudication_raw["case_id"]),
            requirement_id=str(adjudication_raw["requirement_id"]),
            first_review_hash=str(adjudication_raw["first_review_hash"]),
            second_review_hash=str(adjudication_raw["second_review_hash"]),
            adjudicator_role_id=str(adjudication_raw["adjudicator_role_id"]),
            final_verdict=ReviewVerdict(str(adjudication_raw["final_verdict"])),
            evidence_refs=tuple(adjudication_raw.get("evidence_refs", ())),
            rationale=str(adjudication_raw["rationale"]),
        )
        if adjudication_raw.get("record_hash") != adjudication.record_hash:
            raise ContractError("serialized adjudication record hash mismatch")
        adjudications.append(adjudication)
    result = HumanReviewEvidence(
        attestation_kind=HumanAttestationKind(str(raw["attestation_kind"])),
        corpus_id=str(raw["corpus_id"]),
        scope=scope,
        blind_reviews=tuple(reviews),
        adjudications=tuple(adjudications),
        gold_author_role_id=str(raw["gold_author_role_id"]),
        operational_escalator_role_id=str(raw["operational_escalator_role_id"]),
    )
    if raw.get("evidence_sha256") != result.evidence_sha256:
        raise ContractError("serialized human evidence hash mismatch")
    return result


def _approval_from_dict(value: object) -> ApprovalManifest:
    raw = _object(value, "approval manifest")
    result = ApprovalManifest(
        manifest_id=str(raw["manifest_id"]),
        version=int(raw["version"]),
        lock_sha256=str(raw["lock_sha256"]),
        approved=raw["approved"],
        approver_role_id=raw.get("approver_role_id"),
        approved_at=raw.get("approved_at"),
    )
    _verify_declared_hash(raw, result)
    return result


def _arm_order_from_dict(value: object) -> ArmOrderManifest:
    raw = _object(value, "arm order manifest")
    result = ArmOrderManifest(
        seed=int(raw["seed"]),
        algorithm=str(raw["algorithm"]),
        input_arm_ids=tuple(raw.get("input_arm_ids", ())),
        resolved_arm_order=tuple(raw.get("resolved_arm_order", ())),
        order_hash=str(raw["order_hash"]),
    )
    _verify_declared_hash(raw, result)
    return result


def _lock_bindings_from_dict(value: object) -> FormalLockBindings:
    raw = _object(value, "formal lock bindings")
    bindings = _object(raw.get("bindings", {}), "formal lock binding values")
    result = FormalLockBindings(bindings=tuple(bindings.items()))
    _verify_declared_hash(raw, result)
    return result


def formal_readiness_inputs_from_dict(value: object) -> FormalReadinessInputs:
    raw = _object(value, "formal readiness inputs")
    if raw.get("judge_qualification") is not None:
        raise ContractError("serialized naked JudgeQualification is not accepted")

    def optional(name: str, loader: Any) -> Any:
        item = raw.get(name)
        return None if item is None else loader(item)

    try:
        from .meas0_detection_oracle import (
            DetectionOracleManifest,
            FormalDetectionOracleAuthorization,
        )
        from .meas0_formal import ExactInvocationManifest
        from .meas0_judge_probes import JudgeProbeManifest
        from .meas0_stage_cost import (
            PriceManifestReceiptContract,
            PriceQuoteReceipt,
            StageBudgetManifest,
            StageCostLedger,
        )
        from .meas0_trust import (
            AuthorizationCheckpointManifest,
            HumanTrustRootManifest,
            SignatureEnvelope,
            TransportReceiptBatch,
            TransportTrustRootManifest,
            VerificationPolicy,
        )

        return FormalReadinessInputs(
            case_scope_manifest=optional("case_scope_manifest", _case_scope_from_dict),
            gold_scope_manifest=optional("gold_scope_manifest", _gold_scope_from_dict),
            formal_artifact_layout=optional(
                "formal_artifact_layout",
                _formal_artifact_layout_from_dict,
            ),
            gold_artifact_manifest=optional(
                "gold_artifact_manifest",
                _gold_artifact_manifest_from_dict,
            ),
            gold_mount_manifest=optional(
                "gold_mount_manifest",
                _gold_mount_manifest_from_dict,
            ),
            gold_records=tuple(
                _gold_from_dict(item) for item in raw.get("gold_records", ())
            ),
            reviewer_records=tuple(
                _review_from_dict(item) for item in raw.get("reviewer_records", ())
            ),
            adjudication_records=tuple(
                _adjudication_from_dict(item)
                for item in raw.get("adjudication_records", ())
            ),
            operational_escalator_role_id=raw.get("operational_escalator_role_id"),
            human_evidence=optional(
                "human_evidence",
                _human_evidence_from_dict,
            ),
            judge_calibration_manifest=optional(
                "judge_calibration_manifest", _jcal_from_dict
            ),
            judge_card=optional("judge_card", _judge_card_from_dict),
            judge_evidence=optional(
                "judge_evidence",
                _derived_judge_evidence_from_dict,
            ),
            transport_trust_root=optional(
                "transport_trust_root",
                TransportTrustRootManifest.from_dict,
            ),
            human_trust_root=optional(
                "human_trust_root",
                HumanTrustRootManifest.from_dict,
            ),
            transport_verification_policy=optional(
                "transport_verification_policy",
                VerificationPolicy.from_dict,
            ),
            transport_receipt_batch=optional(
                "transport_receipt_batch",
                TransportReceiptBatch.from_dict,
            ),
            human_signature_policy=optional(
                "human_signature_policy",
                VerificationPolicy.from_dict,
            ),
            human_signature_envelopes=tuple(
                SignatureEnvelope.from_dict(item)
                for item in raw.get("human_signature_envelopes", ())
            ),
            authorization_checkpoint_manifest=optional(
                "authorization_checkpoint_manifest",
                AuthorizationCheckpointManifest.from_dict,
            ),
            authorization_checkpoint_envelopes=tuple(
                SignatureEnvelope.from_dict(item)
                for item in raw.get("authorization_checkpoint_envelopes", ())
            ),
            judge_probe_manifest=optional(
                "judge_probe_manifest",
                JudgeProbeManifest.from_dict,
            ),
            judge_invocation_manifest=optional(
                "judge_invocation_manifest",
                ExactInvocationManifest.from_dict,
            ),
            judge_audit_manifest=optional(
                "judge_audit_manifest",
                _jaudit_from_dict,
            ),
            judge_audit_probe_manifest=optional(
                "judge_audit_probe_manifest",
                JudgeProbeManifest.from_dict,
            ),
            judge_audit_evidence=optional(
                "judge_audit_evidence",
                _derived_judge_evidence_from_dict,
            ),
            judge_audit_transport_policy=optional(
                "judge_audit_transport_policy",
                VerificationPolicy.from_dict,
            ),
            judge_audit_transport_batch=optional(
                "judge_audit_transport_batch",
                TransportReceiptBatch.from_dict,
            ),
            judge_audit_stage_cost_ledger=optional(
                "judge_audit_stage_cost_ledger",
                StageCostLedger.from_dict,
            ),
            judge_audit_invocation_manifest=optional(
                "judge_audit_invocation_manifest",
                ExactInvocationManifest.from_dict,
            ),
            judge_set_provenance_manifest=optional(
                "judge_set_provenance_manifest",
                _judge_set_provenance_from_dict,
            ),
            detection_oracle_manifest=(
                None
                if raw.get("detection_oracle_manifest") is None
                else (
                    FormalDetectionOracleAuthorization.from_dict(
                        raw["detection_oracle_manifest"]
                    )
                    if raw["detection_oracle_manifest"].get("schema")
                    == "meas0.formal-detection-oracle-authorization.v1"
                    else DetectionOracleManifest.from_dict(
                        raw["detection_oracle_manifest"]
                    )
                )
            ),
            stage_budget_manifest=optional(
                "stage_budget_manifest",
                StageBudgetManifest.from_dict,
            ),
            stage_cost_ledger=optional(
                "stage_cost_ledger",
                StageCostLedger.from_dict,
            ),
            budget_policy=optional("budget_policy", _budget_from_dict),
            price_manifest=optional("price_manifest", _price_from_dict),
            price_quote_receipts=tuple(
                PriceQuoteReceipt.from_dict(item)
                for item in raw.get("price_quote_receipts", ())
            ),
            price_receipt_contract=optional(
                "price_receipt_contract",
                PriceManifestReceiptContract.from_dict,
            ),
            isolation_policy=optional("isolation_policy", _isolation_from_dict),
            acl_manifest=optional("acl_manifest", _acl_from_dict),
            preflight_report=optional("preflight_report", _preflight_from_dict),
            preflight_evidence=optional(
                "preflight_evidence",
                _preflight_evidence_from_dict,
            ),
            approval_manifest=optional("approval_manifest", _approval_from_dict),
            arm_order=optional("arm_order", _arm_order_from_dict),
            formal_lock_bindings=optional(
                "formal_lock_bindings", _lock_bindings_from_dict
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, ContractError):
            raise
        raise ContractError("serialized readiness inputs are malformed") from error


def formal_readiness_report_from_dict(value: object) -> FormalReadinessReport:
    raw = _object(value, "formal readiness report")
    try:
        return FormalReadinessReport(
            state=FormalReadinessState(str(raw["state"])),
            blockers=tuple(
                ReadinessBlockerCode(str(item)) for item in raw.get("blockers", ())
            ),
            input_hashes=tuple(
                sorted(
                    _object(
                        raw.get("input_hashes", {}),
                        "readiness input hashes",
                    ).items()
                )
            ),
            report_hash=str(raw["report_hash"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, ContractError):
            raise
        raise ContractError("serialized readiness report is malformed") from error


@dataclass(frozen=True)
class FormalReadinessBundle:
    inputs: FormalReadinessInputs
    report: FormalReadinessReport
    bundle_hash: str
    _human_verifier: object | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _transport_verifier: object | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.inputs, FormalReadinessInputs)
            or not isinstance(self.report, FormalReadinessReport)
            or FormalReadinessValidator(
                transport_verifier=self._transport_verifier,
                human_verifier=self._human_verifier,
            ).validate(self.inputs)
            != self.report
        ):
            raise ContractError(
                "readiness bundle report does not match revalidated inputs"
            )
        expected = _sha256(_canonical_json_bytes(self._body()))
        if self.bundle_hash != expected:
            raise ContractError("formal readiness bundle hash mismatch")

    @classmethod
    def create(
        cls,
        inputs: FormalReadinessInputs,
        *,
        human_verifier: object | None = None,
        transport_verifier: object | None = None,
    ) -> FormalReadinessBundle:
        report = FormalReadinessValidator(
            transport_verifier=transport_verifier, human_verifier=human_verifier
        ).validate(inputs)
        body = {"inputs": inputs.to_dict(), "report": report.to_dict()}
        return cls(
            inputs=inputs,
            report=report,
            bundle_hash=_sha256(_canonical_json_bytes(body)),
            _human_verifier=human_verifier,
            _transport_verifier=transport_verifier,
        )

    @classmethod
    def from_dict(
        cls,
        value: object,
        *,
        human_verifier: object | None = None,
        transport_verifier: object | None = None,
    ) -> FormalReadinessBundle:
        raw = _object(value, "formal readiness bundle")
        try:
            return cls(
                inputs=formal_readiness_inputs_from_dict(raw["inputs"]),
                report=formal_readiness_report_from_dict(raw["report"]),
                bundle_hash=str(raw["bundle_hash"]),
                _human_verifier=human_verifier,
                _transport_verifier=transport_verifier,
            )
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, ContractError):
                raise
            raise ContractError("serialized readiness bundle is malformed") from error

    def _body(self) -> dict[str, Any]:
        return {
            "inputs": self.inputs.to_dict(),
            "report": self.report.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "bundle_hash": self.bundle_hash}


__all__ = [
    "ACLManifest",
    "ACLRule",
    "ARM_ORDER_ALGORITHM",
    "ARM_ORDER_SEED",
    "AdjudicationRecord",
    "ApprovalManifest",
    "ArmOrderManifest",
    "BlindReviewerRecord",
    "BudgetPolicy",
    "ContractError",
    "FORMAL_ARM_IDS",
    "FormalCaseIdentity",
    "FormalCaseScopeManifest",
    "FormalArtifactLayout",
    "FormalLockBindings",
    "FormalReadinessInputs",
    "FormalReadinessBundle",
    "FormalReadinessReport",
    "FormalReadinessState",
    "FormalReadinessValidator",
    "GoldAgreementReport",
    "GoldArtifactManifest",
    "GoldMountManifest",
    "GoldRecord",
    "GoldRunValidity",
    "GoldScopeItem",
    "GoldScopeManifest",
    "IsolationPolicy",
    "JAuditManifest",
    "JCalManifest",
    "JUDGE_EFFECTIVE_SEEDS",
    "JudgeCard",
    "JudgeInvocation",
    "JudgeQualification",
    "JudgeQuarantine",
    "JudgeResponse",
    "JudgeSetItem",
    "PreflightReport",
    "PriceManifest",
    "ProviderPrice",
    "REQUIRED_FORMAL_LOCK_BINDINGS",
    "RateEstimate",
    "ReadinessBlockerCode",
    "TaskBudgetLimit",
    "arm_order_manifest",
    "compute_gold_agreement",
    "formal_gold_binding_hash",
    "formal_readiness_inputs_from_dict",
    "formal_readiness_report_from_dict",
    "fuse_judge_presentations",
    "pilot_budget_policy",
    "require_formal_readiness",
]
