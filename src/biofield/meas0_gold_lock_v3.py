"""Test-only structural order receipt for reviewed MEAS0 V3 Pilot Gold."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .meas0_phase_readiness import PhaseReadinessReceipt, PhaseReadinessStage
from .meas0_readiness import (
    AdjudicationRecord,
    BlindReviewerRecord,
    GoldArtifactManifest,
    GoldRecord,
    GoldScopeManifest,
    formal_gold_binding_hash,
)
from .meas0_trust import AuthorizationCheckpoint


class GoldOrderLockError(ValueError):
    """The simulated Gold structural order could not be derived."""


_RECEIPT_TOKEN = object()
_STRUCTURAL_ORDER = (
    "pre_jcal_readiness",
    "gold_scope",
    "gold_records",
    "blind_reviews",
    "adjudications",
    "gold_artifact",
    "pilot_target",
    "pilot_readiness",
    "gold_order_lock_receipt",
)


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
        raise GoldOrderLockError(
            "Gold order lock value is not canonical JSON"
        ) from error


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _exact_equal(observed: object, expected: object) -> bool:
    if type(observed) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(observed) == set(expected) and all(
            _exact_equal(observed[key], expected[key]) for key in expected
        )
    if isinstance(expected, list):
        return len(observed) == len(expected) and all(
            _exact_equal(left, right)
            for left, right in zip(observed, expected, strict=True)
        )
    return observed == expected


def _typed_tuple(
    values: Sequence[Any],
    expected_type: type,
    label: str,
) -> tuple[Any, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise GoldOrderLockError(f"{label} must be a typed sequence")
    result = tuple(values)
    if not all(isinstance(item, expected_type) for item in result):
        raise GoldOrderLockError(f"{label} must contain only typed records")
    return result


def _derive_body(
    *,
    pre_jcal_readiness: PhaseReadinessReceipt,
    pilot_readiness: PhaseReadinessReceipt,
    gold_scope: GoldScopeManifest,
    gold_artifact: GoldArtifactManifest,
    gold_records: Sequence[GoldRecord],
    reviewer_records: Sequence[BlindReviewerRecord],
    adjudication_records: Sequence[AdjudicationRecord],
) -> tuple[
    dict[str, Any],
    tuple[GoldRecord, ...],
    tuple[BlindReviewerRecord, ...],
    tuple[AdjudicationRecord, ...],
]:
    if (
        not isinstance(pre_jcal_readiness, PhaseReadinessReceipt)
        or pre_jcal_readiness.stage is not PhaseReadinessStage.PRE_JCAL_READY
        or pre_jcal_readiness.target.checkpoint is not AuthorizationCheckpoint.PRE_JCAL
    ):
        raise GoldOrderLockError(
            "Gold order lock requires a PRE_JCAL_READY typed receipt"
        )
    if (
        not isinstance(pilot_readiness, PhaseReadinessReceipt)
        or pilot_readiness.stage is not PhaseReadinessStage.PILOT_READY
        or pilot_readiness.target.checkpoint is not AuthorizationCheckpoint.PILOT_START
    ):
        raise GoldOrderLockError("Gold order lock requires a PILOT_READY typed receipt")
    if not isinstance(gold_scope, GoldScopeManifest):
        raise GoldOrderLockError("Gold order lock requires a typed Gold scope")
    if not isinstance(gold_artifact, GoldArtifactManifest):
        raise GoldOrderLockError("Gold order lock requires a typed Gold artifact")

    records = _typed_tuple(gold_records, GoldRecord, "Gold membership")
    reviews = _typed_tuple(
        reviewer_records,
        BlindReviewerRecord,
        "review membership",
    )
    adjudications = _typed_tuple(
        adjudication_records,
        AdjudicationRecord,
        "adjudication membership",
    )
    if not records or not reviews:
        raise GoldOrderLockError("Gold and review membership must be non-empty")
    for values, label in (
        (records, "Gold"),
        (reviews, "review"),
        (adjudications, "adjudication"),
    ):
        hashes = tuple(item.contract_hash for item in values)
        if len(set(hashes)) != len(hashes):
            raise GoldOrderLockError(f"{label} membership contains duplicates")

    gold_record_hashes = tuple(item.contract_hash for item in records)
    reviewer_record_hashes = tuple(item.contract_hash for item in reviews)
    adjudication_record_hashes = tuple(item.contract_hash for item in adjudications)
    expected_binding = formal_gold_binding_hash(gold_scope, records)
    if (
        gold_artifact.gold_scope_hash != gold_scope.contract_hash
        or gold_artifact.gold_binding_hash != expected_binding
        or gold_artifact.gold_record_hashes != gold_record_hashes
        or gold_artifact.reviewer_record_hashes != reviewer_record_hashes
        or gold_artifact.adjudication_record_hashes != adjudication_record_hashes
    ):
        raise GoldOrderLockError(
            "Gold artifact does not bind exact ordered Gold/review/adjudication "
            "membership"
        )

    pre_target = pre_jcal_readiness.target
    pilot_target = pilot_readiness.target
    ancestry = (
        pre_target.lifecycle_id,
        pre_target.comparison_block_id,
        pre_target.authority_role_id,
        pre_target.design_hash,
        pre_target.source_lock_hash,
        pre_target.common_ancestry_hash,
    )
    pilot_ancestry = (
        pilot_target.lifecycle_id,
        pilot_target.comparison_block_id,
        pilot_target.authority_role_id,
        pilot_target.design_hash,
        pilot_target.source_lock_hash,
        pilot_target.common_ancestry_hash,
    )
    if ancestry != pilot_ancestry:
        raise GoldOrderLockError(
            "Gold order lock readiness common ancestry is inconsistent"
        )
    if (
        gold_artifact.comparison_block_id != pilot_target.comparison_block_id
        or gold_artifact.comparison_block_id != pre_target.comparison_block_id
    ):
        raise GoldOrderLockError(
            "Gold artifact comparison block differs from readiness ancestry"
        )
    if (
        pre_jcal_readiness.common_ancestry_hash != pre_target.common_ancestry_hash
        or pilot_readiness.common_ancestry_hash != pilot_target.common_ancestry_hash
    ):
        raise GoldOrderLockError(
            "Gold order lock readiness common ancestry hash is invalid"
        )
    if (
        pilot_readiness.previous_receipt_hash != pre_jcal_readiness.receipt_hash
        or pilot_target.previous_target_hash != pre_target.target_hash
    ):
        raise GoldOrderLockError(
            "Gold order lock append-only previous readiness/target link is invalid"
        )
    if (
        dict(pilot_target.evidence_bindings).get("gold_binding")
        != gold_artifact.gold_binding_hash
    ):
        raise GoldOrderLockError(
            "PILOT_READY target does not bind the reviewed Gold artifact"
        )

    membership_body = {
        "gold_scope_hash": gold_scope.contract_hash,
        "gold_artifact_manifest_hash": gold_artifact.contract_hash,
        "gold_binding_hash": gold_artifact.gold_binding_hash,
        "gold_record_hashes": list(gold_record_hashes),
        "reviewer_record_hashes": list(reviewer_record_hashes),
        "adjudication_record_hashes": list(adjudication_record_hashes),
    }
    body = {
        "schema": "meas0.simulated-gold-order-lock-receipt.v3",
        "version": 1,
        "lifecycle_id": pre_target.lifecycle_id,
        "comparison_block_id": pre_target.comparison_block_id,
        "design_hash": pre_target.design_hash,
        "source_lock_hash": pre_target.source_lock_hash,
        "common_ancestry_hash": pre_target.common_ancestry_hash,
        "pre_jcal_stage": PhaseReadinessStage.PRE_JCAL_READY.value,
        "pre_jcal_target_hash": pre_target.target_hash,
        "pre_jcal_readiness_hash": pre_jcal_readiness.receipt_hash,
        "pilot_stage": PhaseReadinessStage.PILOT_READY.value,
        "pilot_target_hash": pilot_target.target_hash,
        "pilot_readiness_hash": pilot_readiness.receipt_hash,
        **membership_body,
        "ordered_membership_hash": _canonical_hash(membership_body),
        "structural_order": list(_STRUCTURAL_ORDER),
        "append_only_structural_order_only": True,
        "trusted_time_verified": False,
        "signature_verified": False,
        "claim_scope": "simulated_nonclaim",
        "production_authorized": False,
        "test_only": True,
    }
    return body, records, reviews, adjudications


@dataclass(frozen=True)
class SimulatedGoldOrderLockReceipt:
    """A typed hash-chain order commitment, never a trusted temporal proof."""

    schema: str
    version: int
    lifecycle_id: str
    comparison_block_id: str
    design_hash: str
    source_lock_hash: str
    common_ancestry_hash: str
    pre_jcal_stage: PhaseReadinessStage
    pre_jcal_target_hash: str
    pre_jcal_readiness_hash: str
    pilot_stage: PhaseReadinessStage
    pilot_target_hash: str
    pilot_readiness_hash: str
    gold_scope_hash: str
    gold_artifact_manifest_hash: str
    gold_binding_hash: str
    gold_record_hashes: tuple[str, ...]
    reviewer_record_hashes: tuple[str, ...]
    adjudication_record_hashes: tuple[str, ...]
    ordered_membership_hash: str
    structural_order: tuple[str, ...]
    append_only_structural_order_only: bool
    trusted_time_verified: bool
    signature_verified: bool
    claim_scope: str
    production_authorized: bool
    test_only: bool
    _pre_jcal_readiness: PhaseReadinessReceipt | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _pilot_readiness: PhaseReadinessReceipt | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _gold_scope: GoldScopeManifest | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _gold_artifact: GoldArtifactManifest | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _gold_records: tuple[GoldRecord, ...] = field(
        default=(),
        repr=False,
        compare=False,
    )
    _reviewer_records: tuple[BlindReviewerRecord, ...] = field(
        default=(),
        repr=False,
        compare=False,
    )
    _adjudication_records: tuple[AdjudicationRecord, ...] = field(
        default=(),
        repr=False,
        compare=False,
    )
    _derivation_token: object = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self._derivation_token is not _RECEIPT_TOKEN:
            raise GoldOrderLockError(
                "Gold order lock receipt must be created by its factory"
            )
        expected, _, _, _ = _derive_body(
            pre_jcal_readiness=self._pre_jcal_readiness,
            pilot_readiness=self._pilot_readiness,
            gold_scope=self._gold_scope,
            gold_artifact=self._gold_artifact,
            gold_records=self._gold_records,
            reviewer_records=self._reviewer_records,
            adjudication_records=self._adjudication_records,
        )
        if not _exact_equal(self._body(), expected):
            raise GoldOrderLockError(
                "Gold order lock fields are not factory-derived from typed sources"
            )

    def _body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "version": self.version,
            "lifecycle_id": self.lifecycle_id,
            "comparison_block_id": self.comparison_block_id,
            "design_hash": self.design_hash,
            "source_lock_hash": self.source_lock_hash,
            "common_ancestry_hash": self.common_ancestry_hash,
            "pre_jcal_stage": self.pre_jcal_stage.value,
            "pre_jcal_target_hash": self.pre_jcal_target_hash,
            "pre_jcal_readiness_hash": self.pre_jcal_readiness_hash,
            "pilot_stage": self.pilot_stage.value,
            "pilot_target_hash": self.pilot_target_hash,
            "pilot_readiness_hash": self.pilot_readiness_hash,
            "gold_scope_hash": self.gold_scope_hash,
            "gold_artifact_manifest_hash": self.gold_artifact_manifest_hash,
            "gold_binding_hash": self.gold_binding_hash,
            "gold_record_hashes": list(self.gold_record_hashes),
            "reviewer_record_hashes": list(self.reviewer_record_hashes),
            "adjudication_record_hashes": list(self.adjudication_record_hashes),
            "ordered_membership_hash": self.ordered_membership_hash,
            "structural_order": list(self.structural_order),
            "append_only_structural_order_only": (
                self.append_only_structural_order_only
            ),
            "trusted_time_verified": self.trusted_time_verified,
            "signature_verified": self.signature_verified,
            "claim_scope": self.claim_scope,
            "production_authorized": self.production_authorized,
            "test_only": self.test_only,
        }

    @property
    def receipt_hash(self) -> str:
        return _canonical_hash(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "receipt_hash": self.receipt_hash}

    @classmethod
    def restore_from_sources(
        cls,
        value: object,
        *,
        pre_jcal_readiness: PhaseReadinessReceipt,
        pilot_readiness: PhaseReadinessReceipt,
        gold_scope: GoldScopeManifest,
        gold_artifact: GoldArtifactManifest,
        gold_records: Sequence[GoldRecord],
        reviewer_records: Sequence[BlindReviewerRecord],
        adjudication_records: Sequence[AdjudicationRecord],
    ) -> SimulatedGoldOrderLockReceipt:
        if not isinstance(value, Mapping):
            raise GoldOrderLockError(
                "serialized Gold order lock receipt must be a mapping"
            )
        restored = create_simulated_gold_order_lock_receipt(
            pre_jcal_readiness=pre_jcal_readiness,
            pilot_readiness=pilot_readiness,
            gold_scope=gold_scope,
            gold_artifact=gold_artifact,
            gold_records=gold_records,
            reviewer_records=reviewer_records,
            adjudication_records=adjudication_records,
        )
        if not _exact_equal(dict(value), restored.to_dict()):
            raise GoldOrderLockError(
                "serialized Gold order lock receipt disagrees with typed sources"
            )
        return restored


def create_simulated_gold_order_lock_receipt(
    *,
    pre_jcal_readiness: PhaseReadinessReceipt,
    pilot_readiness: PhaseReadinessReceipt,
    gold_scope: GoldScopeManifest,
    gold_artifact: GoldArtifactManifest,
    gold_records: Sequence[GoldRecord],
    reviewer_records: Sequence[BlindReviewerRecord],
    adjudication_records: Sequence[AdjudicationRecord],
) -> SimulatedGoldOrderLockReceipt:
    """Derive a non-production structural order commitment from typed sources."""

    body, records, reviews, adjudications = _derive_body(
        pre_jcal_readiness=pre_jcal_readiness,
        pilot_readiness=pilot_readiness,
        gold_scope=gold_scope,
        gold_artifact=gold_artifact,
        gold_records=gold_records,
        reviewer_records=reviewer_records,
        adjudication_records=adjudication_records,
    )
    return SimulatedGoldOrderLockReceipt(
        schema=body["schema"],
        version=body["version"],
        lifecycle_id=body["lifecycle_id"],
        comparison_block_id=body["comparison_block_id"],
        design_hash=body["design_hash"],
        source_lock_hash=body["source_lock_hash"],
        common_ancestry_hash=body["common_ancestry_hash"],
        pre_jcal_stage=PhaseReadinessStage(body["pre_jcal_stage"]),
        pre_jcal_target_hash=body["pre_jcal_target_hash"],
        pre_jcal_readiness_hash=body["pre_jcal_readiness_hash"],
        pilot_stage=PhaseReadinessStage(body["pilot_stage"]),
        pilot_target_hash=body["pilot_target_hash"],
        pilot_readiness_hash=body["pilot_readiness_hash"],
        gold_scope_hash=body["gold_scope_hash"],
        gold_artifact_manifest_hash=body["gold_artifact_manifest_hash"],
        gold_binding_hash=body["gold_binding_hash"],
        gold_record_hashes=tuple(body["gold_record_hashes"]),
        reviewer_record_hashes=tuple(body["reviewer_record_hashes"]),
        adjudication_record_hashes=tuple(body["adjudication_record_hashes"]),
        ordered_membership_hash=body["ordered_membership_hash"],
        structural_order=tuple(body["structural_order"]),
        append_only_structural_order_only=body["append_only_structural_order_only"],
        trusted_time_verified=body["trusted_time_verified"],
        signature_verified=body["signature_verified"],
        claim_scope=body["claim_scope"],
        production_authorized=body["production_authorized"],
        test_only=body["test_only"],
        _pre_jcal_readiness=pre_jcal_readiness,
        _pilot_readiness=pilot_readiness,
        _gold_scope=gold_scope,
        _gold_artifact=gold_artifact,
        _gold_records=records,
        _reviewer_records=reviews,
        _adjudication_records=adjudications,
        _derivation_token=_RECEIPT_TOKEN,
    )
