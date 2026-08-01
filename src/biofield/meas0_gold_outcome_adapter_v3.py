"""Test-only V3 adapter from typed Gold facts to oracle-bound outcome leaves."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .measurement import EvaluationStatus
from .meas0_detection_oracle import DerivedDetectionRecord
from .meas0_formal_derivation import (
    ArtifactDerivedFacts,
    derive_oracle_bound_arm_case_outcome,
)
from .meas0_formal_metrics import FormalCaseIdentity
from .meas0_formal_runner import FormalRunnerError
from .meas0_gold_facts_v3 import GoldOutcomeFacts
from .meas0_input_manifest import InputManifest
from .meas0_phase_readiness import PhaseReadinessReceipt, PhaseReadinessStage
from .meas0_readiness import GoldArtifactManifest


class V3GoldOutcomeCompositionError(ValueError):
    """V3 Gold facts do not bind one simulated arm-case outcome."""


V3_OUTCOME_PACKAGE_INTEGRATION_GAP = (
    "FormalOutcomePackage accepts only legacy OracleBoundArmCaseOutcome leaves "
    "and cannot accept the tagged V3 simulated_nonclaim outcome without "
    "conflating test-only Gold ancestry with formal eligibility."
)
_OUTCOME_TOKEN = object()


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
        raise V3GoldOutcomeCompositionError(
            f"{label} must be a lowercase SHA-256 digest"
        )
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


def _outcome_body(
    *,
    artifact_facts: ArtifactDerivedFacts,
    detection_record: DerivedDetectionRecord,
    gold_facts: GoldOutcomeFacts,
    gold_facts_hash: str,
    selected_gold_record_hashes: tuple[str, ...],
    gold_binding_hash: str,
    gold_artifact_manifest_hash: str,
    phase_readiness_hash: str,
    input_manifest_hash: str,
    common_ancestry_hash: str,
    comparison_block_id: str,
    source_lock_hash: str,
) -> dict[str, Any]:
    return {
        "schema": "meas0.simulated-gold-bound-arm-case-outcome.v3",
        "version": 1,
        "case": gold_facts.case_identity.to_dict(),
        "arm_id": artifact_facts.arm_id,
        "artifact_facts_hash": artifact_facts.derivation_hash,
        "detection_record_hash": detection_record.record_hash,
        "gold_status": (
            gold_facts.gold_status.value if gold_facts.gold_status is not None else None
        ),
        "accept_allowed": gold_facts.accept_allowed,
        "safety_violation": gold_facts.safety_violation,
        "gold_facts_hash": gold_facts_hash,
        "selected_gold_record_hashes": list(selected_gold_record_hashes),
        "gold_binding_hash": gold_binding_hash,
        "gold_artifact_manifest_hash": gold_artifact_manifest_hash,
        "phase_readiness_hash": phase_readiness_hash,
        "input_manifest_hash": input_manifest_hash,
        "common_ancestry_hash": common_ancestry_hash,
        "comparison_block_id": comparison_block_id,
        "source_lock_hash": source_lock_hash,
        "claim_scope": "simulated_nonclaim",
        "test_only": True,
        "production_authorized": False,
        "formal_eligible": False,
    }


@dataclass(frozen=True)
class SimulatedGoldBoundArmCaseOutcomeV3:
    """Tagged V3 outcome that cannot satisfy the existing formal package DTO."""

    artifact_facts: ArtifactDerivedFacts
    detection_record: DerivedDetectionRecord
    gold_facts: GoldOutcomeFacts
    gold_artifact: GoldArtifactManifest
    pilot_readiness: PhaseReadinessReceipt
    input_manifest: InputManifest
    gold_facts_hash: str
    selected_gold_record_hashes: tuple[str, ...]
    gold_binding_hash: str
    gold_artifact_manifest_hash: str
    phase_readiness_hash: str
    input_manifest_hash: str
    common_ancestry_hash: str
    comparison_block_id: str
    source_lock_hash: str
    outcome_hash: str
    _derivation_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._derivation_token is not _OUTCOME_TOKEN:
            raise V3GoldOutcomeCompositionError(
                "V3 Gold-bound outcome must be created by its factory"
            )
        if not isinstance(self.artifact_facts, ArtifactDerivedFacts) or not isinstance(
            self.detection_record,
            DerivedDetectionRecord,
        ):
            raise V3GoldOutcomeCompositionError(
                "V3 outcome requires typed artifact/oracle ancestry"
            )
        if not isinstance(self.gold_facts, GoldOutcomeFacts):
            raise V3GoldOutcomeCompositionError(
                "V3 outcome requires typed GoldOutcomeFacts"
            )
        if not isinstance(self.gold_artifact, GoldArtifactManifest):
            raise V3GoldOutcomeCompositionError(
                "V3 outcome requires a typed Gold artifact manifest"
            )
        if (
            not isinstance(self.pilot_readiness, PhaseReadinessReceipt)
            or self.pilot_readiness.stage is not PhaseReadinessStage.PILOT_READY
        ):
            raise V3GoldOutcomeCompositionError(
                "V3 outcome requires PILOT_READY readiness ancestry"
            )
        if not isinstance(self.input_manifest, InputManifest):
            raise V3GoldOutcomeCompositionError(
                "V3 outcome requires a typed Pilot input manifest"
            )
        try:
            derive_oracle_bound_arm_case_outcome(
                case=self.gold_facts.case_identity,
                facts=self.artifact_facts,
                detection_record=self.detection_record,
                gold_status=(
                    self.gold_facts.gold_status.value
                    if self.gold_facts.gold_status is not None
                    else None
                ),
                accept_allowed=self.gold_facts.accept_allowed,
                safety_violation=self.gold_facts.safety_violation,
            )
        except FormalRunnerError as error:
            raise V3GoldOutcomeCompositionError(
                f"V3 outcome case/artifact/oracle ancestry is invalid: {error}"
            ) from error
        if self.gold_facts_hash != self.gold_facts.facts_hash:
            raise V3GoldOutcomeCompositionError(
                "V3 outcome Gold facts hash is not derived"
            )
        if (
            self.selected_gold_record_hashes
            != self.gold_facts.selected_gold_record_hashes
            or not set(self.selected_gold_record_hashes)
            <= set(self.gold_artifact.gold_record_hashes)
        ):
            raise V3GoldOutcomeCompositionError(
                "V3 outcome selected Gold hashes are invalid"
            )
        if (
            self.gold_binding_hash != self.gold_facts.gold_binding_hash
            or self.gold_binding_hash != self.gold_artifact.gold_binding_hash
        ):
            raise V3GoldOutcomeCompositionError(
                "V3 outcome Gold binding hash is invalid"
            )
        if (
            self.gold_artifact_manifest_hash
            != self.gold_facts.gold_artifact_manifest_hash
            or self.gold_artifact_manifest_hash != self.gold_artifact.contract_hash
        ):
            raise V3GoldOutcomeCompositionError(
                "V3 outcome Gold artifact hash is invalid"
            )
        if (
            self.phase_readiness_hash != self.gold_facts.phase_readiness_hash
            or self.phase_readiness_hash != self.pilot_readiness.receipt_hash
        ):
            raise V3GoldOutcomeCompositionError(
                "V3 outcome phase readiness hash is invalid"
            )
        if (
            self.input_manifest_hash != self.gold_facts.input_manifest_hash
            or self.input_manifest_hash != self.input_manifest.manifest_hash
        ):
            raise V3GoldOutcomeCompositionError(
                "V3 outcome input manifest hash is invalid"
            )
        if (
            self.common_ancestry_hash != self.gold_facts.common_ancestry_hash
            or self.common_ancestry_hash != self.input_manifest.common_ancestry_hash
            or self.common_ancestry_hash != self.pilot_readiness.common_ancestry_hash
        ):
            raise V3GoldOutcomeCompositionError(
                "V3 outcome common ancestry hash is invalid"
            )
        if (
            self.comparison_block_id != self.input_manifest.comparison_block_id
            or self.comparison_block_id
            != self.pilot_readiness.target.comparison_block_id
            or self.comparison_block_id != self.gold_artifact.comparison_block_id
        ):
            raise V3GoldOutcomeCompositionError(
                "V3 outcome comparison block binding is invalid"
            )
        if (
            self.source_lock_hash != self.input_manifest.source_lock_hash
            or self.source_lock_hash != self.pilot_readiness.target.source_lock_hash
        ):
            raise V3GoldOutcomeCompositionError(
                "V3 outcome source lock binding is invalid"
            )
        if (
            dict(self.pilot_readiness.target.evidence_bindings).get("gold_binding")
            != self.gold_binding_hash
        ):
            raise V3GoldOutcomeCompositionError(
                "V3 outcome readiness does not bind Gold"
            )
        for value, label in (
            (self.gold_facts_hash, "gold_facts_hash"),
            (self.gold_binding_hash, "gold_binding_hash"),
            (self.gold_artifact_manifest_hash, "gold_artifact_manifest_hash"),
            (self.phase_readiness_hash, "phase_readiness_hash"),
            (self.input_manifest_hash, "input_manifest_hash"),
            (self.common_ancestry_hash, "common_ancestry_hash"),
            (self.source_lock_hash, "source_lock_hash"),
            (self.outcome_hash, "outcome_hash"),
        ):
            _hash(value, label)
        if self.outcome_hash != _canonical_hash(self._body()):
            raise V3GoldOutcomeCompositionError("V3 outcome hash is invalid")

    @property
    def case(self) -> FormalCaseIdentity:
        return self.gold_facts.case_identity

    @property
    def arm_id(self) -> str:
        return self.artifact_facts.arm_id

    @property
    def gold_status(self) -> EvaluationStatus | None:
        return self.gold_facts.gold_status

    @property
    def accept_allowed(self) -> bool:
        return self.gold_facts.accept_allowed

    @property
    def safety_violation(self) -> bool:
        return self.gold_facts.safety_violation

    @property
    def claim_scope(self) -> str:
        return "simulated_nonclaim"

    @property
    def test_only(self) -> bool:
        return True

    @property
    def production_authorized(self) -> bool:
        return False

    @property
    def formal_eligible(self) -> bool:
        return False

    def _body(self) -> dict[str, Any]:
        return _outcome_body(
            artifact_facts=self.artifact_facts,
            detection_record=self.detection_record,
            gold_facts=self.gold_facts,
            gold_facts_hash=self.gold_facts_hash,
            selected_gold_record_hashes=self.selected_gold_record_hashes,
            gold_binding_hash=self.gold_binding_hash,
            gold_artifact_manifest_hash=self.gold_artifact_manifest_hash,
            phase_readiness_hash=self.phase_readiness_hash,
            input_manifest_hash=self.input_manifest_hash,
            common_ancestry_hash=self.common_ancestry_hash,
            comparison_block_id=self.comparison_block_id,
            source_lock_hash=self.source_lock_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "outcome_hash": self.outcome_hash}

    @classmethod
    def restore_from_sources(
        cls,
        value: object,
        *,
        artifact_facts: ArtifactDerivedFacts,
        detection_record: DerivedDetectionRecord,
        gold_facts: GoldOutcomeFacts,
        gold_artifact: GoldArtifactManifest,
        pilot_readiness: PhaseReadinessReceipt,
        input_manifest: InputManifest,
    ) -> SimulatedGoldBoundArmCaseOutcomeV3:
        """Replay the V3 factory and compare every serialized field exactly."""

        if not isinstance(value, Mapping):
            raise V3GoldOutcomeCompositionError(
                "serialized V3 Gold-bound outcome must be a mapping"
            )
        restored = derive_v3_gold_bound_arm_case_outcome(
            artifact_facts=artifact_facts,
            detection_record=detection_record,
            gold_facts=gold_facts,
            gold_artifact=gold_artifact,
            pilot_readiness=pilot_readiness,
            input_manifest=input_manifest,
        )
        if not _exact_serialized_equal(dict(value), restored.to_dict()):
            raise V3GoldOutcomeCompositionError(
                "serialized V3 Gold-bound outcome disagrees with typed sources"
            )
        return restored


def derive_v3_gold_bound_arm_case_outcome(
    *,
    artifact_facts: ArtifactDerivedFacts,
    detection_record: DerivedDetectionRecord,
    gold_facts: GoldOutcomeFacts,
    gold_artifact: GoldArtifactManifest,
    pilot_readiness: PhaseReadinessReceipt,
    input_manifest: InputManifest,
) -> SimulatedGoldBoundArmCaseOutcomeV3:
    """Adapt typed Gold facts without accepting caller-selected Gold values."""

    if not isinstance(gold_facts, GoldOutcomeFacts):
        raise V3GoldOutcomeCompositionError(
            "V3 outcome requires typed GoldOutcomeFacts"
        )
    values = {
        "artifact_facts": artifact_facts,
        "detection_record": detection_record,
        "gold_facts": gold_facts,
        "gold_artifact": gold_artifact,
        "pilot_readiness": pilot_readiness,
        "input_manifest": input_manifest,
        "gold_facts_hash": gold_facts.facts_hash,
        "selected_gold_record_hashes": gold_facts.selected_gold_record_hashes,
        "gold_binding_hash": gold_facts.gold_binding_hash,
        "gold_artifact_manifest_hash": gold_facts.gold_artifact_manifest_hash,
        "phase_readiness_hash": gold_facts.phase_readiness_hash,
        "input_manifest_hash": gold_facts.input_manifest_hash,
        "common_ancestry_hash": gold_facts.common_ancestry_hash,
        "comparison_block_id": input_manifest.comparison_block_id,
        "source_lock_hash": input_manifest.source_lock_hash,
    }
    return SimulatedGoldBoundArmCaseOutcomeV3(
        **values,
        outcome_hash=_canonical_hash(
            _outcome_body(
                artifact_facts=artifact_facts,
                detection_record=detection_record,
                gold_facts=gold_facts,
                gold_facts_hash=gold_facts.facts_hash,
                selected_gold_record_hashes=(gold_facts.selected_gold_record_hashes),
                gold_binding_hash=gold_facts.gold_binding_hash,
                gold_artifact_manifest_hash=(gold_facts.gold_artifact_manifest_hash),
                phase_readiness_hash=gold_facts.phase_readiness_hash,
                input_manifest_hash=gold_facts.input_manifest_hash,
                common_ancestry_hash=gold_facts.common_ancestry_hash,
                comparison_block_id=input_manifest.comparison_block_id,
                source_lock_hash=input_manifest.source_lock_hash,
            )
        ),
        _derivation_token=_OUTCOME_TOKEN,
    )
