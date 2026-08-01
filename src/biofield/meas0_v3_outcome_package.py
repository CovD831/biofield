"""Non-claim V3 outcome closure for Gold and retained-failure leaves.

This package is deliberately separate from ``FormalOutcomePackage``.  It
preserves the D7/D8 typed leaves and their exact 36 x 5 case/arm membership,
but it cannot enter formal metrics, Gate assessment, or production evidence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeAlias

from .meas0_detection_oracle import DerivedDetectionRecord
from .meas0_formal_derivation import ArtifactDerivedFacts
from .meas0_formal_metrics import FormalCaseIdentity, formal_attack_manifest
from .meas0_gold_outcome_adapter_v3 import (
    SimulatedGoldBoundArmCaseOutcomeV3,
)
from .meas0_input_manifest import InputManifest
from .meas0_phase_readiness import PhaseReadinessReceipt, PhaseReadinessStage
from .meas0_readiness import arm_order_manifest
from .meas0_retained_failure_v3 import RetainedFailureOutcome


V3_OUTCOME_PACKAGE_SCHEMA = "meas0.simulated-v3-outcome-package.v3"
V3_OUTCOME_CLAIM_SCOPE = "simulated_nonclaim"
_LEAF_TOKEN = object()
_PACKAGE_TOKEN = object()


class V3OutcomePackageError(ValueError):
    """A V3 Gold/failure package is incomplete or inconsistent."""


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
        raise V3OutcomePackageError("V3 outcome value is not canonical JSON") from error
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    """Encode one V3 value using the package's strict JSON representation."""

    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise V3OutcomePackageError("V3 outcome value is not canonical JSON") from error


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise V3OutcomePackageError(
                "serialized V3 outcome contains duplicate fields"
            )
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise V3OutcomePackageError(
        f"serialized V3 outcome contains non-finite value: {value}"
    )


def _decode_canonical_bytes(raw_bytes: bytes) -> object:
    if type(raw_bytes) is not bytes:
        raise V3OutcomePackageError("serialized V3 outcome must be bytes")
    try:
        value = json.loads(
            raw_bytes.decode("utf-8"),
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=_reject_nonfinite,
        )
    except V3OutcomePackageError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise V3OutcomePackageError(
            "serialized V3 outcome is not strict JSON"
        ) from error
    if raw_bytes != _canonical_bytes(value):
        raise V3OutcomePackageError("serialized V3 outcome bytes are not canonical")
    return value


def _digest(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise V3OutcomePackageError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _exact_equal(observed: object, expected: object) -> bool:
    if type(observed) is not type(expected):
        return False
    if isinstance(expected, Mapping):
        return set(observed) == set(expected) and all(
            _exact_equal(observed[key], expected[key]) for key in expected
        )
    if isinstance(expected, list):
        return len(observed) == len(expected) and all(
            _exact_equal(left, right)
            for left, right in zip(observed, expected, strict=True)
        )
    return observed == expected


def _expected_pairs() -> tuple[tuple[str, str], ...]:
    return tuple(
        (case.case_id, arm_id)
        for case in formal_attack_manifest("pilot").cases
        for arm_id in arm_order_manifest().resolved_arm_order
    )


def _identity_from_case(case: FormalCaseIdentity) -> tuple[str, str, str]:
    return case.case_id, case.task_id, case.fault_id


@dataclass(frozen=True)
class SimulatedRetainedFailureBoundOutcomeV3:
    """Bind one retained failure to the same Pilot ancestry as Gold leaves."""

    artifact_facts: ArtifactDerivedFacts
    detection_record: DerivedDetectionRecord | None
    retained_failure: RetainedFailureOutcome
    pilot_readiness: PhaseReadinessReceipt
    input_manifest: InputManifest
    common_ancestry_hash: str
    comparison_block_id: str
    source_lock_hash: str
    phase_readiness_hash: str
    input_manifest_hash: str
    outcome_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _LEAF_TOKEN:
            raise V3OutcomePackageError("retained failure leaf requires its factory")
        if not isinstance(self.artifact_facts, ArtifactDerivedFacts):
            raise V3OutcomePackageError("retained failure leaf requires artifact facts")
        if not isinstance(self.retained_failure, RetainedFailureOutcome):
            raise V3OutcomePackageError("retained failure leaf requires typed failure")
        if not isinstance(self.pilot_readiness, PhaseReadinessReceipt) or (
            self.pilot_readiness.stage is not PhaseReadinessStage.PILOT_READY
        ):
            raise V3OutcomePackageError("retained failure leaf requires PILOT_READY")
        if not isinstance(self.input_manifest, InputManifest):
            raise V3OutcomePackageError("retained failure leaf requires input manifest")
        failure = self.retained_failure
        if (
            _identity_from_case(failure.case)
            != (
                self.artifact_facts.case_id,
                self.artifact_facts.task_id,
                self.artifact_facts.fault_id,
            )
            or failure.arm_id != self.artifact_facts.arm_id
            or failure.authorization_hash != self.artifact_facts.authorization_hash
            or failure.denominator_retained is not True
            or failure.accepted is not None
            or failure.detected is not None
            or failure.judge_verdict is not None
            or failure.claim_scope != V3_OUTCOME_CLAIM_SCOPE
            or failure.production_authorized is not False
            or failure.test_only is not True
        ):
            raise V3OutcomePackageError(
                "retained failure leaf ancestry or claim boundary is invalid"
            )
        if self.detection_record is not None:
            if (
                not isinstance(self.detection_record, DerivedDetectionRecord)
                or self.detection_record.case_id != failure.case.case_id
                or self.detection_record.task_id != failure.case.task_id
                or self.detection_record.fault_id != failure.case.fault_id
                or self.detection_record.arm_id != failure.arm_id
                or self.detection_record.artifact_sha256
                != self.artifact_facts.artifact_hash
            ):
                raise V3OutcomePackageError(
                    "retained failure detection context is inconsistent"
                )
        expected_case_ids = {item.case_id for item in self.input_manifest.entries}
        if failure.case.case_id not in expected_case_ids:
            raise V3OutcomePackageError(
                "retained failure case is absent from input manifest"
            )
        if (
            self.common_ancestry_hash != self.input_manifest.common_ancestry_hash
            or self.common_ancestry_hash != self.pilot_readiness.common_ancestry_hash
            or self.comparison_block_id != self.input_manifest.comparison_block_id
            or self.comparison_block_id
            != self.pilot_readiness.target.comparison_block_id
            or self.source_lock_hash != self.input_manifest.source_lock_hash
            or self.source_lock_hash != self.pilot_readiness.target.source_lock_hash
            or self.phase_readiness_hash != self.pilot_readiness.receipt_hash
            or self.input_manifest_hash != self.input_manifest.manifest_hash
        ):
            raise V3OutcomePackageError(
                "retained failure package ancestry is inconsistent"
            )
        for value, label in (
            (self.common_ancestry_hash, "common ancestry hash"),
            (self.source_lock_hash, "source lock hash"),
            (self.phase_readiness_hash, "phase readiness hash"),
            (self.input_manifest_hash, "input manifest hash"),
            (self.outcome_hash, "retained failure outcome hash"),
        ):
            _digest(value, label)
        if self.outcome_hash != _canonical_hash(self._body()):
            raise V3OutcomePackageError("retained failure leaf hash mismatch")

    @property
    def case(self) -> FormalCaseIdentity:
        return self.retained_failure.case

    @property
    def arm_id(self) -> str:
        return self.retained_failure.arm_id

    @property
    def variant(self) -> str:
        return "retained_failure"

    @property
    def claim_scope(self) -> str:
        return V3_OUTCOME_CLAIM_SCOPE

    @property
    def test_only(self) -> bool:
        return True

    @property
    def production_authorized(self) -> bool:
        return False

    @property
    def formal_eligible(self) -> bool:
        return False

    @property
    def result_validity(self) -> str:
        return self.retained_failure.result_validity.value

    @property
    def automatic_status(self) -> str | None:
        return (
            self.retained_failure.automatic_status.value
            if self.retained_failure.automatic_status is not None
            else None
        )

    def _body(self) -> dict[str, Any]:
        return {
            "schema": "meas0.simulated-retained-failure-bound-outcome.v3",
            "version": 1,
            "variant": self.variant,
            "case": self.case.to_dict(),
            "arm_id": self.arm_id,
            "artifact_facts_hash": self.artifact_facts.derivation_hash,
            "detection_record_hash": (
                self.detection_record.record_hash if self.detection_record else None
            ),
            "retained_failure_hash": self.retained_failure.outcome_hash,
            "result_validity": self.result_validity,
            "automatic_status": self.automatic_status,
            "denominator_retained": True,
            "common_ancestry_hash": self.common_ancestry_hash,
            "comparison_block_id": self.comparison_block_id,
            "source_lock_hash": self.source_lock_hash,
            "phase_readiness_hash": self.phase_readiness_hash,
            "input_manifest_hash": self.input_manifest_hash,
            "claim_scope": V3_OUTCOME_CLAIM_SCOPE,
            "test_only": True,
            "production_authorized": False,
            "formal_eligible": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "outcome_hash": self.outcome_hash}


def derive_simulated_retained_failure_bound_outcome(
    *,
    artifact_facts: ArtifactDerivedFacts,
    detection_record: DerivedDetectionRecord | None,
    retained_failure: RetainedFailureOutcome,
    pilot_readiness: PhaseReadinessReceipt,
    input_manifest: InputManifest,
) -> SimulatedRetainedFailureBoundOutcomeV3:
    values = {
        "artifact_facts": artifact_facts,
        "detection_record": detection_record,
        "retained_failure": retained_failure,
        "pilot_readiness": pilot_readiness,
        "input_manifest": input_manifest,
        "common_ancestry_hash": input_manifest.common_ancestry_hash,
        "comparison_block_id": input_manifest.comparison_block_id,
        "source_lock_hash": input_manifest.source_lock_hash,
        "phase_readiness_hash": pilot_readiness.receipt_hash,
        "input_manifest_hash": input_manifest.manifest_hash,
    }
    body = {
        "schema": "meas0.simulated-retained-failure-bound-outcome.v3",
        "version": 1,
        "variant": "retained_failure",
        "case": retained_failure.case.to_dict(),
        "arm_id": retained_failure.arm_id,
        "artifact_facts_hash": artifact_facts.derivation_hash,
        "detection_record_hash": (
            detection_record.record_hash if detection_record else None
        ),
        "retained_failure_hash": retained_failure.outcome_hash,
        "result_validity": retained_failure.result_validity.value,
        "automatic_status": (
            retained_failure.automatic_status.value
            if retained_failure.automatic_status is not None
            else None
        ),
        "denominator_retained": True,
        "common_ancestry_hash": input_manifest.common_ancestry_hash,
        "comparison_block_id": input_manifest.comparison_block_id,
        "source_lock_hash": input_manifest.source_lock_hash,
        "phase_readiness_hash": pilot_readiness.receipt_hash,
        "input_manifest_hash": input_manifest.manifest_hash,
        "claim_scope": V3_OUTCOME_CLAIM_SCOPE,
        "test_only": True,
        "production_authorized": False,
        "formal_eligible": False,
    }
    return SimulatedRetainedFailureBoundOutcomeV3(
        **values,
        outcome_hash=_canonical_hash(body),
        _factory_token=_LEAF_TOKEN,
    )


V3OutcomeLeaf: TypeAlias = (
    SimulatedGoldBoundArmCaseOutcomeV3 | SimulatedRetainedFailureBoundOutcomeV3
)


@dataclass(frozen=True)
class SimulatedV3OutcomePackage:
    """Exact non-claim closure of one Pilot case-by-arm outcome set."""

    schema: str
    claim_scope: str
    test_only: bool
    production_authorized: bool
    formal_eligible: bool
    common_ancestry_hash: str
    comparison_block_id: str
    source_lock_hash: str
    phase_readiness_hash: str
    input_manifest_hash: str
    leaves: tuple[V3OutcomeLeaf, ...]
    package_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _PACKAGE_TOKEN:
            raise V3OutcomePackageError("V3 outcome package requires its factory")
        object.__setattr__(self, "leaves", tuple(self.leaves))
        if (
            self.schema != V3_OUTCOME_PACKAGE_SCHEMA
            or self.claim_scope != V3_OUTCOME_CLAIM_SCOPE
            or self.test_only is not True
            or self.production_authorized is not False
            or self.formal_eligible is not False
            or len(self.leaves) != 180
            or not all(
                isinstance(
                    item,
                    (
                        SimulatedGoldBoundArmCaseOutcomeV3,
                        SimulatedRetainedFailureBoundOutcomeV3,
                    ),
                )
                for item in self.leaves
            )
        ):
            raise V3OutcomePackageError("V3 outcome package class or size is invalid")
        if (
            tuple((item.case.case_id, item.arm_id) for item in self.leaves)
            != _expected_pairs()
        ):
            raise V3OutcomePackageError(
                "V3 outcome package coverage or order is invalid"
            )
        for leaf in self.leaves:
            if (
                leaf.claim_scope != V3_OUTCOME_CLAIM_SCOPE
                or leaf.test_only is not True
                or leaf.production_authorized is not False
                or leaf.formal_eligible is not False
                or leaf.common_ancestry_hash != self.common_ancestry_hash
                or leaf.comparison_block_id != self.comparison_block_id
                or leaf.source_lock_hash != self.source_lock_hash
                or leaf.phase_readiness_hash != self.phase_readiness_hash
                or leaf.input_manifest_hash != self.input_manifest_hash
            ):
                raise V3OutcomePackageError(
                    "V3 outcome leaf ancestry or claim boundary differs"
                )
        for value, label in (
            (self.common_ancestry_hash, "common ancestry hash"),
            (self.source_lock_hash, "source lock hash"),
            (self.phase_readiness_hash, "phase readiness hash"),
            (self.input_manifest_hash, "input manifest hash"),
            (self.package_hash, "package hash"),
        ):
            _digest(value, label)
        if self.package_hash != _canonical_hash(self._body()):
            raise V3OutcomePackageError("V3 outcome package hash mismatch")

    @property
    def case_count(self) -> int:
        return len({item.case.case_id for item in self.leaves})

    @property
    def arm_case_count(self) -> int:
        return len(self.leaves)

    def _body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "claim_scope": self.claim_scope,
            "test_only": self.test_only,
            "production_authorized": self.production_authorized,
            "formal_eligible": self.formal_eligible,
            "common_ancestry_hash": self.common_ancestry_hash,
            "comparison_block_id": self.comparison_block_id,
            "source_lock_hash": self.source_lock_hash,
            "phase_readiness_hash": self.phase_readiness_hash,
            "input_manifest_hash": self.input_manifest_hash,
            "case_count": self.case_count,
            "arm_case_count": self.arm_case_count,
            "leaves": [item.to_dict() for item in self.leaves],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "package_hash": self.package_hash}

    def to_canonical_bytes(self) -> bytes:
        """Return the strict, deterministic serialized package projection.

        The bytes carry no additional authority.  Restoration still requires
        the independently reconstructed typed leaves, so a byte payload alone
        cannot create or upgrade an outcome package.
        """

        return _canonical_bytes(self.to_dict())

    @classmethod
    def restore_from_typed_sources(
        cls,
        value: object,
        *,
        leaves: Sequence[V3OutcomeLeaf],
    ) -> SimulatedV3OutcomePackage:
        restored = compose_simulated_v3_outcome_package(leaves)
        if not _exact_equal(value, restored.to_dict()):
            raise V3OutcomePackageError(
                "serialized V3 package differs from typed leaves"
            )
        return restored

    @classmethod
    def restore_from_canonical_bytes(
        cls,
        raw_bytes: bytes,
        *,
        leaves: Sequence[V3OutcomeLeaf],
    ) -> SimulatedV3OutcomePackage:
        """Restore only when canonical bytes agree with typed leaf sources."""

        value = _decode_canonical_bytes(raw_bytes)
        if type(value) is not dict:
            raise V3OutcomePackageError(
                "serialized V3 outcome package must be an object"
            )
        return cls.restore_from_typed_sources(value, leaves=leaves)


def compose_simulated_v3_outcome_package(
    leaves: Sequence[V3OutcomeLeaf],
) -> SimulatedV3OutcomePackage:
    try:
        values = tuple(leaves)
    except TypeError as error:
        raise V3OutcomePackageError(
            "V3 package leaves must be a typed sequence"
        ) from error
    if len(values) != 180:
        raise V3OutcomePackageError("V3 outcome package requires exactly 180 leaves")
    first = values[0]
    if not isinstance(
        first,
        (SimulatedGoldBoundArmCaseOutcomeV3, SimulatedRetainedFailureBoundOutcomeV3),
    ):
        raise V3OutcomePackageError("V3 package leaf type is invalid")
    body = {
        "schema": V3_OUTCOME_PACKAGE_SCHEMA,
        "claim_scope": V3_OUTCOME_CLAIM_SCOPE,
        "test_only": True,
        "production_authorized": False,
        "formal_eligible": False,
        "common_ancestry_hash": first.common_ancestry_hash,
        "comparison_block_id": first.comparison_block_id,
        "source_lock_hash": first.source_lock_hash,
        "phase_readiness_hash": first.phase_readiness_hash,
        "input_manifest_hash": first.input_manifest_hash,
        "case_count": 36,
        "arm_case_count": 180,
        "leaves": [item.to_dict() for item in values],
    }
    return SimulatedV3OutcomePackage(
        schema=V3_OUTCOME_PACKAGE_SCHEMA,
        claim_scope=V3_OUTCOME_CLAIM_SCOPE,
        test_only=True,
        production_authorized=False,
        formal_eligible=False,
        common_ancestry_hash=first.common_ancestry_hash,
        comparison_block_id=first.comparison_block_id,
        source_lock_hash=first.source_lock_hash,
        phase_readiness_hash=first.phase_readiness_hash,
        input_manifest_hash=first.input_manifest_hash,
        leaves=values,
        package_hash=_canonical_hash(body),
        _factory_token=_PACKAGE_TOKEN,
    )


__all__ = [
    "SimulatedRetainedFailureBoundOutcomeV3",
    "SimulatedV3OutcomePackage",
    "V3_OUTCOME_PACKAGE_SCHEMA",
    "V3OutcomeLeaf",
    "V3OutcomePackageError",
    "compose_simulated_v3_outcome_package",
    "derive_simulated_retained_failure_bound_outcome",
]
