"""Factory-derived, test-only case Gold facts for the MEAS0 V3 Pilot."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Sequence

from .measurement import EvaluationStatus
from .meas0_formal_metrics import FormalCaseIdentity
from .meas0_gold_lock_v3 import SimulatedGoldOrderLockReceipt
from .meas0_input_manifest import InputManifest
from .meas0_phase_readiness import PhaseReadinessReceipt, PhaseReadinessStage
from .meas0_readiness import (
    AdjudicationRecord,
    BlindReviewerRecord,
    GoldArtifactManifest,
    GoldRecord,
    GoldRunValidity,
    GoldScopeManifest,
    formal_gold_binding_hash,
)
from .meas0_trust import AuthorizationCheckpoint


class GoldFactsDerivationError(ValueError):
    """Gold facts could not be derived from one reviewed, locked ancestry."""


GOLD_ORDER_LOCK_CLAIM_LIMIT = (
    "The typed Gold order receipt proves append-only structural hash order only; "
    "it does not prove trusted time, a real signature, or production authority."
)
_FACTS_TOKEN = object()


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _hash(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise GoldFactsDerivationError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _exact_serialized_equal(observed: object, expected: object) -> bool:
    if type(observed) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(observed) == set(expected) and all(
            _exact_serialized_equal(observed[key], expected[key]) for key in expected
        )
    if isinstance(expected, list):
        return len(observed) == len(expected) and all(
            _exact_serialized_equal(left, right)
            for left, right in zip(observed, expected, strict=True)
        )
    return observed == expected


@dataclass(frozen=True)
class GoldOutcomeFacts:
    """Case-level facts derived from reviewed GoldRecord membership."""

    case_identity: FormalCaseIdentity
    gold_status: EvaluationStatus | None
    accept_allowed: bool
    safety_violation: bool
    phase_readiness_hash: str
    input_manifest_hash: str
    case_scope_hash: str
    gold_scope_hash: str
    selected_gold_record_hashes: tuple[str, ...]
    gold_binding_hash: str
    gold_artifact_manifest_hash: str
    gold_order_lock_hash: str
    common_ancestry_hash: str
    _gold_order_lock: SimulatedGoldOrderLockReceipt | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _derivation_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._derivation_token is not _FACTS_TOKEN:
            raise GoldFactsDerivationError(
                "Gold outcome facts must be created by their factory"
            )
        if (
            not isinstance(self.case_identity, FormalCaseIdentity)
            or self.case_identity.phase != "pilot"
        ):
            raise GoldFactsDerivationError(
                "Gold outcome facts require a Pilot case identity"
            )
        if self.gold_status is not None and not isinstance(
            self.gold_status,
            EvaluationStatus,
        ):
            raise GoldFactsDerivationError("derived gold status is invalid")
        if not isinstance(self.accept_allowed, bool) or not isinstance(
            self.safety_violation,
            bool,
        ):
            raise GoldFactsDerivationError("derived Gold flags must be boolean")
        if self.accept_allowed != (self.gold_status is EvaluationStatus.PASS):
            raise GoldFactsDerivationError(
                "derived accept_allowed disagrees with gold status"
            )
        for field_name in (
            "phase_readiness_hash",
            "input_manifest_hash",
            "case_scope_hash",
            "gold_scope_hash",
            "gold_binding_hash",
            "gold_artifact_manifest_hash",
            "gold_order_lock_hash",
            "common_ancestry_hash",
        ):
            _hash(getattr(self, field_name), field_name)
        if (
            not isinstance(self.selected_gold_record_hashes, tuple)
            or not self.selected_gold_record_hashes
            or len(set(self.selected_gold_record_hashes))
            != len(self.selected_gold_record_hashes)
        ):
            raise GoldFactsDerivationError(
                "selected GoldRecord hashes must be non-empty and unique"
            )
        for digest in self.selected_gold_record_hashes:
            _hash(digest, "selected GoldRecord hash")
        if (
            not isinstance(
                self._gold_order_lock,
                SimulatedGoldOrderLockReceipt,
            )
            or self.gold_order_lock_hash != self._gold_order_lock.receipt_hash
        ):
            raise GoldFactsDerivationError(
                "Gold facts require their factory-derived typed order lock"
            )

    @property
    def claim_scope(self) -> str:
        return "simulated_nonclaim"

    @property
    def production_authorized(self) -> bool:
        return False

    @property
    def test_only(self) -> bool:
        return True

    def _body(self) -> dict[str, Any]:
        return {
            "schema": "meas0.gold-outcome-facts.v3",
            "version": 1,
            "case_identity": self.case_identity.to_dict(),
            "gold_status": (
                self.gold_status.value if self.gold_status is not None else None
            ),
            "accept_allowed": self.accept_allowed,
            "safety_violation": self.safety_violation,
            "phase_readiness_hash": self.phase_readiness_hash,
            "input_manifest_hash": self.input_manifest_hash,
            "case_scope_hash": self.case_scope_hash,
            "gold_scope_hash": self.gold_scope_hash,
            "selected_gold_record_hashes": list(self.selected_gold_record_hashes),
            "gold_binding_hash": self.gold_binding_hash,
            "gold_artifact_manifest_hash": self.gold_artifact_manifest_hash,
            "gold_order_lock_hash": self.gold_order_lock_hash,
            "common_ancestry_hash": self.common_ancestry_hash,
            "claim_scope": self.claim_scope,
            "production_authorized": self.production_authorized,
            "test_only": self.test_only,
        }

    @property
    def facts_hash(self) -> str:
        return _canonical_hash(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "facts_hash": self.facts_hash}

    @classmethod
    def restore_from_sources(
        cls,
        value: object,
        *,
        pilot_readiness: PhaseReadinessReceipt,
        input_manifest: InputManifest,
        case_identity: FormalCaseIdentity,
        gold_scope: GoldScopeManifest,
        gold_artifact: GoldArtifactManifest,
        gold_records: Sequence[GoldRecord],
        reviewer_records: Sequence[BlindReviewerRecord],
        adjudication_records: Sequence[AdjudicationRecord],
        gold_order_lock: SimulatedGoldOrderLockReceipt,
    ) -> GoldOutcomeFacts:
        """Replay the canonical factory; JSON alone is never sufficient."""

        if not isinstance(value, Mapping):
            raise GoldFactsDerivationError(
                "serialized Gold outcome facts must be a mapping"
            )
        restored = derive_gold_outcome_facts(
            pilot_readiness=pilot_readiness,
            input_manifest=input_manifest,
            case_identity=case_identity,
            gold_scope=gold_scope,
            gold_artifact=gold_artifact,
            gold_records=gold_records,
            reviewer_records=reviewer_records,
            adjudication_records=adjudication_records,
            gold_order_lock=gold_order_lock,
        )
        if not _exact_serialized_equal(dict(value), restored.to_dict()):
            raise GoldFactsDerivationError(
                "serialized Gold outcome facts disagree with typed sources"
            )
        return restored


def _validate_case_ancestry(
    *,
    pilot_readiness: PhaseReadinessReceipt,
    input_manifest: InputManifest,
    case_identity: FormalCaseIdentity,
    gold_scope: GoldScopeManifest,
) -> None:
    if (
        not isinstance(pilot_readiness, PhaseReadinessReceipt)
        or pilot_readiness.stage is not PhaseReadinessStage.PILOT_READY
        or pilot_readiness.target.checkpoint is not AuthorizationCheckpoint.PILOT_START
    ):
        raise GoldFactsDerivationError("Gold facts require a PILOT_READY typed receipt")
    if not isinstance(input_manifest, InputManifest):
        raise GoldFactsDerivationError(
            "Gold facts require a typed Pilot input manifest"
        )
    if (
        not isinstance(case_identity, FormalCaseIdentity)
        or case_identity.phase != "pilot"
    ):
        raise GoldFactsDerivationError(
            "Gold facts reject a non-Pilot or cross-split case identity"
        )
    if not isinstance(gold_scope, GoldScopeManifest):
        raise GoldFactsDerivationError("Gold facts require a typed GoldScopeManifest")
    bindings = dict(pilot_readiness.target.evidence_bindings)
    if bindings.get("pilot_input_manifest") != input_manifest.manifest_hash:
        raise GoldFactsDerivationError(
            "PILOT_READY receipt does not bind the input manifest"
        )
    if (
        pilot_readiness.common_ancestry_hash != input_manifest.common_ancestry_hash
        or pilot_readiness.target.lifecycle_id != input_manifest.lifecycle_id
        or pilot_readiness.target.comparison_block_id
        != input_manifest.comparison_block_id
        or pilot_readiness.target.design_hash != input_manifest.design_hash
        or pilot_readiness.target.source_lock_hash != input_manifest.source_lock_hash
    ):
        raise GoldFactsDerivationError(
            "Gold facts readiness/input common ancestry is invalid"
        )
    if (
        gold_scope.case_scope_hash != input_manifest.case_scope_manifest_hash
        or gold_scope.case_ids
        != tuple(entry.case_id for entry in input_manifest.entries)
    ):
        raise GoldFactsDerivationError("Gold scope does not bind the Pilot case scope")
    entry = next(
        (
            item
            for item in input_manifest.entries
            if item.case_id == case_identity.case_id
        ),
        None,
    )
    if entry is None or (
        entry.phase,
        entry.task_id,
        entry.fault_id,
        entry.mutation_seed,
    ) != (
        case_identity.phase,
        case_identity.task_id,
        case_identity.fault_id,
        case_identity.mutation_seed,
    ):
        raise GoldFactsDerivationError(
            "Pilot case task/fault identity does not match input scope"
        )


def _validate_reviewed_records(
    *,
    gold_scope: GoldScopeManifest,
    gold_records: tuple[GoldRecord, ...],
    reviewer_records: tuple[BlindReviewerRecord, ...],
    adjudication_records: tuple[AdjudicationRecord, ...],
) -> None:
    expected_keys = tuple(gold_scope.expected_gold_keys)
    gold_keys = tuple(item.key for item in gold_records)
    if len(set(gold_keys)) != len(gold_keys):
        raise GoldFactsDerivationError(
            "Gold records contain a duplicate requirement key"
        )
    if set(gold_keys) != set(expected_keys):
        raise GoldFactsDerivationError(
            "Gold records have a missing or unexpected requirement key"
        )
    reviews: dict[str, list[BlindReviewerRecord]] = defaultdict(list)
    reviewer_hashes: list[str] = []
    for item in reviewer_records:
        if not isinstance(item, BlindReviewerRecord):
            raise GoldFactsDerivationError("review records must be typed")
        reviews[item.key].append(item)
        reviewer_hashes.append(item.contract_hash)
    if len(reviewer_hashes) != len(set(reviewer_hashes)):
        raise GoldFactsDerivationError(
            "review records contain a duplicate reviewer hash"
        )
    if set(reviews) != set(expected_keys):
        raise GoldFactsDerivationError(
            "review membership differs from the exact Gold scope"
        )
    adjudications: dict[str, AdjudicationRecord] = {}
    for item in adjudication_records:
        if not isinstance(item, AdjudicationRecord):
            raise GoldFactsDerivationError("adjudication records must be typed")
        if item.key in adjudications:
            raise GoldFactsDerivationError(
                "adjudication records contain a duplicate key"
            )
        adjudications[item.key] = item
    required_adjudications: set[str] = set()
    semantic_keys = set(gold_scope.semantic_gold_keys)
    for gold in gold_records:
        if not isinstance(gold, GoldRecord):
            raise GoldFactsDerivationError("Gold records must be typed")
        if gold.semantic != (gold.key in semantic_keys):
            raise GoldFactsDerivationError(
                "Gold semantic scope does not match requirement key"
            )
        selected = reviews.get(gold.key, [])
        required_count = 2 if gold.key in semantic_keys else 1
        if (
            len(selected) != required_count
            or len({item.reviewer_role_id for item in selected}) != required_count
            or gold.author_role_id in {item.reviewer_role_id for item in selected}
            or set(gold.reviewer_record_hashes)
            != {item.contract_hash for item in selected}
        ):
            raise GoldFactsDerivationError(
                "Gold requirement review evidence is missing or mismatched"
            )
        verdicts = {item.verdict for item in selected}
        if len(verdicts) == 1:
            if next(iter(verdicts)) is not gold.verdict:
                raise GoldFactsDerivationError(
                    "review verdict does not match GoldRecord"
                )
            if gold.adjudication_record_hash is not None:
                raise GoldFactsDerivationError(
                    "GoldRecord has an unexpected adjudication"
                )
        else:
            required_adjudications.add(gold.key)
            adjudication = adjudications.get(gold.key)
            if adjudication is None:
                raise GoldFactsDerivationError(
                    "required Gold adjudication is missing or mismatched"
                )
            selected_by_hash = {item.contract_hash: item for item in selected}
            if {
                adjudication.first_review_hash,
                adjudication.second_review_hash,
            } != set(selected_by_hash):
                raise GoldFactsDerivationError(
                    "required Gold adjudication is missing or mismatched"
                )
            if adjudication.adjudicator_role_id in {
                item.reviewer_role_id for item in selected
            }:
                raise GoldFactsDerivationError(
                    "Gold adjudicator role overlaps a selected reviewer"
                )
            if (
                adjudication.first_verdict
                is not selected_by_hash[adjudication.first_review_hash].verdict
                or adjudication.second_verdict
                is not selected_by_hash[adjudication.second_review_hash].verdict
            ):
                raise GoldFactsDerivationError(
                    "Gold adjudication review verdict binding is invalid"
                )
            if (
                adjudication.final_verdict is not gold.verdict
                or gold.adjudication_record_hash != adjudication.contract_hash
            ):
                raise GoldFactsDerivationError(
                    "required Gold adjudication is missing or mismatched"
                )
    if set(adjudications) != required_adjudications:
        raise GoldFactsDerivationError(
            "Gold adjudication membership is missing or unexpected"
        )


def derive_gold_outcome_facts(
    *,
    pilot_readiness: PhaseReadinessReceipt,
    input_manifest: InputManifest,
    case_identity: FormalCaseIdentity,
    gold_scope: GoldScopeManifest,
    gold_artifact: GoldArtifactManifest,
    gold_records: Sequence[GoldRecord],
    reviewer_records: Sequence[BlindReviewerRecord],
    adjudication_records: Sequence[AdjudicationRecord],
    gold_order_lock: SimulatedGoldOrderLockReceipt,
) -> GoldOutcomeFacts:
    """Derive one Pilot case's facts; callers cannot supply outcome values."""

    _validate_case_ancestry(
        pilot_readiness=pilot_readiness,
        input_manifest=input_manifest,
        case_identity=case_identity,
        gold_scope=gold_scope,
    )
    record_tuple = tuple(gold_records)
    review_tuple = tuple(reviewer_records)
    adjudication_tuple = tuple(adjudication_records)
    if not isinstance(gold_order_lock, SimulatedGoldOrderLockReceipt):
        raise GoldFactsDerivationError(
            "Gold facts require a typed structural order lock receipt"
        )
    _validate_reviewed_records(
        gold_scope=gold_scope,
        gold_records=record_tuple,
        reviewer_records=review_tuple,
        adjudication_records=adjudication_tuple,
    )
    selected = tuple(
        item for item in record_tuple if item.case_id == case_identity.case_id
    )
    top_level = {
        (
            item.gold_run_validity,
            item.gold_status,
            item.accept_allowed,
            item.safety_violation,
        )
        for item in selected
    }
    if not selected or len(top_level) != 1:
        raise GoldFactsDerivationError(
            "case GoldRecords have a top-level tuple conflict"
        )
    try:
        SimulatedGoldOrderLockReceipt.restore_from_sources(
            gold_order_lock.to_dict(),
            pre_jcal_readiness=gold_order_lock._pre_jcal_readiness,
            pilot_readiness=pilot_readiness,
            gold_scope=gold_scope,
            gold_artifact=gold_artifact,
            gold_records=record_tuple,
            reviewer_records=review_tuple,
            adjudication_records=adjudication_tuple,
        )
    except ValueError as error:
        raise GoldFactsDerivationError(
            "locked Gold structural order/ancestry is invalid"
        ) from error
    if not isinstance(gold_artifact, GoldArtifactManifest):
        raise GoldFactsDerivationError(
            "Gold facts require a typed locked Gold artifact manifest"
        )
    expected_binding = formal_gold_binding_hash(gold_scope, record_tuple)
    if (
        gold_artifact.comparison_block_id != input_manifest.comparison_block_id
        or gold_artifact.gold_scope_hash != gold_scope.contract_hash
        or gold_artifact.gold_binding_hash != expected_binding
        or gold_artifact.gold_record_hashes
        != tuple(item.contract_hash for item in record_tuple)
        or gold_artifact.reviewer_record_hashes
        != tuple(item.contract_hash for item in review_tuple)
        or gold_artifact.adjudication_record_hashes
        != tuple(item.contract_hash for item in adjudication_tuple)
    ):
        raise GoldFactsDerivationError(
            "Gold evidence drifted from the locked artifact manifest"
        )
    if (
        dict(pilot_readiness.target.evidence_bindings).get("gold_binding")
        != gold_artifact.gold_binding_hash
    ):
        raise GoldFactsDerivationError(
            "PILOT_READY receipt does not bind the locked Gold artifact"
        )
    validity, status, accept_allowed, safety_violation = next(iter(top_level))
    if validity is GoldRunValidity.INVALID and status is not None:
        raise GoldFactsDerivationError("invalid Gold run has a non-null status")
    return GoldOutcomeFacts(
        case_identity=case_identity,
        gold_status=status,
        accept_allowed=accept_allowed,
        safety_violation=safety_violation,
        phase_readiness_hash=pilot_readiness.receipt_hash,
        input_manifest_hash=input_manifest.manifest_hash,
        case_scope_hash=gold_scope.case_scope_hash,
        gold_scope_hash=gold_scope.contract_hash,
        selected_gold_record_hashes=tuple(item.contract_hash for item in selected),
        gold_binding_hash=gold_artifact.gold_binding_hash,
        gold_artifact_manifest_hash=gold_artifact.contract_hash,
        gold_order_lock_hash=gold_order_lock.receipt_hash,
        common_ancestry_hash=input_manifest.common_ancestry_hash,
        _gold_order_lock=gold_order_lock,
        _derivation_token=_FACTS_TOKEN,
    )
