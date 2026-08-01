"""Fail-closed composition of MEAS0 artifact-derived outcome ancestry.

This module does not create a production oracle or compute scientific metrics.
It binds the frozen 36-case by five-arm run denominator to the existing typed
artifact facts, signal projections, candidate detection records, and
oracle-bound outcomes.  The bundled candidate oracle is always test-only and
cannot be promoted by this composition layer.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .meas0_detection_oracle import (
    DetectionOracleManifest,
    DetectionSignalProjection,
    DerivedDetectionRecord,
    derive_detection_signal_projection,
)
from .meas0_formal_derivation import (
    ArtifactDerivedFacts,
    OracleBoundArmCaseOutcome,
    derive_artifact_facts,
)
from .meas0_formal_metrics import formal_attack_manifest
from .meas0_formal_runner import FormalContractRun
from .meas0_readiness import arm_order_manifest


FORMAL_OUTCOME_PACKAGE_SCHEMA = "meas0.formal-outcome-package.v1"
FORMAL_OUTCOME_EVIDENCE_SEAL_SCHEMA = "meas0.formal-outcome-evidence-seal.v1"
FORMAL_OUTCOME_EVIDENCE_BUNDLE_SCHEMA = "meas0.formal-outcome-evidence-bundle.v1"
_PACKAGE_FACTORY_TOKEN = object()
_EVIDENCE_SEAL_FACTORY_TOKEN = object()
_EVIDENCE_BUNDLE_FACTORY_TOKEN = object()


class FormalOutcomeCompositionError(ValueError):
    """Raised when formal outcome ancestry or denominator closure is invalid."""


class FormalOutcomeEvidenceWriteError(FormalOutcomeCompositionError):
    """Raised when post-run evidence cannot be atomically published."""


class FormalOutcomeEvidenceExistsError(
    FormalOutcomeEvidenceWriteError,
    FileExistsError,
):
    """Raised instead of overwriting a post-run evidence bundle."""


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
        raise FormalOutcomeCompositionError(
            "formal outcome package is not canonical JSON"
        ) from error
    return hashlib.sha256(payload).hexdigest()


def _hash(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise FormalOutcomeCompositionError(f"{label} must be lowercase SHA-256")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise FormalOutcomeCompositionError(f"{label} keys are invalid")


def _expected_pairs() -> tuple[tuple[str, str], ...]:
    return tuple(
        (case.case_id, arm_id)
        for case in formal_attack_manifest("pilot").cases
        for arm_id in arm_order_manifest().resolved_arm_order
    )


def _outcome_dict(outcome: OracleBoundArmCaseOutcome) -> dict[str, Any]:
    return {
        "case": outcome.case.to_dict(),
        "arm_id": outcome.arm,
        "artifact_facts_hash": outcome.artifact_facts.derivation_hash,
        "signal_projection_hash": (
            outcome.detection_record.signal_projection_record.projection_hash
        ),
        "detection_record_hash": outcome.detection_record.record_hash,
        "gold_status": outcome.gold_status,
        "accept_allowed": outcome.accept_allowed,
        "safety_violation": outcome.safety_violation,
    }


@dataclass(frozen=True)
class FormalOutcomePackage:
    """Exact, hash-bound composition of all 180 Pilot arm-case outcomes."""

    schema: str
    claim_scope: str
    test_only: bool
    formal_eligible: bool
    run_hash: str
    plan_hash: str
    authorization_hash: str
    oracle_manifest_hash: str
    adapter_source_hashes: tuple[tuple[str, str], ...]
    artifact_facts: tuple[ArtifactDerivedFacts, ...]
    signal_projections: tuple[DetectionSignalProjection, ...]
    detection_records: tuple[DerivedDetectionRecord, ...]
    outcomes: tuple[OracleBoundArmCaseOutcome, ...]
    package_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _PACKAGE_FACTORY_TOKEN:
            raise FormalOutcomeCompositionError(
                "formal outcome packages require the composition factory"
            )
        if (
            self.schema != FORMAL_OUTCOME_PACKAGE_SCHEMA
            or not isinstance(self.test_only, bool)
            or not isinstance(self.formal_eligible, bool)
            or self.test_only is self.formal_eligible
        ):
            raise FormalOutcomeCompositionError(
                "outcome package evidence class is invalid"
            )
        for value, label in (
            (self.run_hash, "run_hash"),
            (self.plan_hash, "plan_hash"),
            (self.authorization_hash, "authorization_hash"),
            (self.oracle_manifest_hash, "oracle_manifest_hash"),
            (self.package_hash, "package_hash"),
        ):
            _hash(value, label)
        object.__setattr__(
            self,
            "adapter_source_hashes",
            tuple(self.adapter_source_hashes),
        )
        object.__setattr__(self, "artifact_facts", tuple(self.artifact_facts))
        object.__setattr__(
            self,
            "signal_projections",
            tuple(self.signal_projections),
        )
        object.__setattr__(
            self,
            "detection_records",
            tuple(self.detection_records),
        )
        object.__setattr__(self, "outcomes", tuple(self.outcomes))
        if (
            len(self.artifact_facts) != 180
            or len(self.signal_projections) != 180
            or len(self.detection_records) != 180
            or len(self.outcomes) != 180
        ):
            raise FormalOutcomeCompositionError(
                "formal outcome composition requires exactly 180 entries"
            )
        if (
            not all(
                isinstance(item, ArtifactDerivedFacts) for item in self.artifact_facts
            )
            or not all(
                isinstance(item, DetectionSignalProjection)
                for item in self.signal_projections
            )
            or not all(
                isinstance(item, DerivedDetectionRecord)
                for item in self.detection_records
            )
            or not all(
                isinstance(item, OracleBoundArmCaseOutcome) for item in self.outcomes
            )
        ):
            raise FormalOutcomeCompositionError(
                "formal outcome composition contains an untyped entry"
            )
        if tuple((item.case.case_id, item.arm) for item in self.outcomes) != (
            _expected_pairs()
        ):
            raise FormalOutcomeCompositionError(
                "formal outcome coverage or order differs from frozen 36x5"
            )
        if self.package_hash != _canonical_hash(self._body()):
            raise FormalOutcomeCompositionError("formal outcome package hash mismatch")

    @property
    def case_count(self) -> int:
        return len({item.case.case_id for item in self.outcomes})

    @property
    def arm_case_count(self) -> int:
        return len(self.outcomes)

    def require_formal_eligible(self) -> tuple[OracleBoundArmCaseOutcome, ...]:
        if not self.formal_eligible:
            raise FormalOutcomeCompositionError(
                "test-only candidate outcome package is not formal eligible"
            )
        return self.outcomes

    def _body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "claim_scope": self.claim_scope,
            "test_only": self.test_only,
            "formal_eligible": self.formal_eligible,
            "run_hash": self.run_hash,
            "plan_hash": self.plan_hash,
            "authorization_hash": self.authorization_hash,
            "oracle_manifest_hash": self.oracle_manifest_hash,
            "adapter_source_hashes": {
                task_id: source_hash
                for task_id, source_hash in self.adapter_source_hashes
            },
            "case_count": self.case_count,
            "arm_case_count": self.arm_case_count,
            "artifact_facts": [item.to_dict() for item in self.artifact_facts],
            "signal_projections": [item.to_dict() for item in self.signal_projections],
            "detection_records": [item.to_dict() for item in self.detection_records],
            "outcomes": [_outcome_dict(item) for item in self.outcomes],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "package_hash": self.package_hash}

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        run: FormalContractRun,
        oracle_manifest: DetectionOracleManifest,
        outcomes: Sequence[OracleBoundArmCaseOutcome],
    ) -> FormalOutcomePackage:
        """Restore only against the original typed run, oracle, and outcomes."""

        if not isinstance(value, Mapping):
            raise FormalOutcomeCompositionError(
                "serialized formal outcome package must be an object"
            )
        _exact_keys(
            value,
            {
                "schema",
                "claim_scope",
                "test_only",
                "formal_eligible",
                "run_hash",
                "plan_hash",
                "authorization_hash",
                "oracle_manifest_hash",
                "adapter_source_hashes",
                "case_count",
                "arm_case_count",
                "artifact_facts",
                "signal_projections",
                "detection_records",
                "outcomes",
                "package_hash",
            },
            "formal outcome package",
        )
        typed_outcomes = tuple(outcomes)
        restored = compose_formal_outcome_package(
            run=run,
            oracle_manifest=oracle_manifest,
            artifact_facts=tuple(item.artifact_facts for item in typed_outcomes),
            signal_projections=tuple(
                item.detection_record.signal_projection_record
                for item in typed_outcomes
            ),
            detection_records=tuple(item.detection_record for item in typed_outcomes),
            outcomes=typed_outcomes,
        )
        if dict(value) != restored.to_dict():
            raise FormalOutcomeCompositionError(
                "serialized package disagrees with typed source ancestry"
            )
        return restored


def compose_formal_outcome_package(
    *,
    run: FormalContractRun,
    oracle_manifest: DetectionOracleManifest,
    artifact_facts: Sequence[ArtifactDerivedFacts],
    signal_projections: Sequence[DetectionSignalProjection],
    detection_records: Sequence[DerivedDetectionRecord],
    outcomes: Sequence[OracleBoundArmCaseOutcome],
) -> FormalOutcomePackage:
    """Bind a complete frozen Pilot run to existing derived outcome leaves."""

    if not isinstance(run, FormalContractRun):
        raise FormalOutcomeCompositionError(
            "formal outcome composition requires a FormalContractRun"
        )
    if not isinstance(oracle_manifest, DetectionOracleManifest):
        raise FormalOutcomeCompositionError(
            "formal outcome composition requires a typed oracle manifest"
        )
    facts_values = tuple(artifact_facts)
    projection_values = tuple(signal_projections)
    record_values = tuple(detection_records)
    outcome_values = tuple(outcomes)
    if (
        len(run.artifacts) != 180
        or len(facts_values) != 180
        or len(projection_values) != 180
        or len(record_values) != 180
        or len(outcome_values) != 180
    ):
        raise FormalOutcomeCompositionError(
            "formal outcome composition requires exactly 180 entries"
        )
    if tuple((item.case_id, item.arm_id) for item in run.artifacts) != (
        _expected_pairs()
    ):
        raise FormalOutcomeCompositionError(
            "formal run coverage or order differs from frozen 36x5"
        )
    expected_adapters = tuple(
        (item.task_id, item.source_sha256) for item in oracle_manifest.task_adapters
    )
    for index, (
        artifact,
        facts,
        projection,
        record,
        outcome,
    ) in enumerate(
        zip(
            run.artifacts,
            facts_values,
            projection_values,
            record_values,
            outcome_values,
            strict=True,
        )
    ):
        if (
            not isinstance(facts, ArtifactDerivedFacts)
            or not isinstance(projection, DetectionSignalProjection)
            or not isinstance(record, DerivedDetectionRecord)
            or not isinstance(outcome, OracleBoundArmCaseOutcome)
        ):
            raise FormalOutcomeCompositionError(
                f"formal outcome entry {index} is not fully typed"
            )
        identity = (
            artifact.case_id,
            artifact.task_id,
            artifact.fault_id,
            artifact.arm_id,
        )
        if (
            identity
            != (
                facts.case_id,
                facts.task_id,
                facts.fault_id,
                facts.arm_id,
            )
            or identity
            != (
                projection.case_id,
                projection.task_id,
                projection.fault_id,
                projection.arm_id,
            )
            or identity
            != (
                record.case_id,
                record.task_id,
                record.fault_id,
                record.arm_id,
            )
            or identity
            != (
                outcome.case.case_id,
                outcome.case.task_id,
                outcome.case.fault_id,
                outcome.arm,
            )
        ):
            raise FormalOutcomeCompositionError(
                f"formal outcome entry {index} ancestry or order is inconsistent"
            )
        if (
            artifact.authorization_hash != run.authorization.authorization_hash
            or facts.authorization_hash != run.authorization.authorization_hash
            or projection.authorization_hash != run.authorization.authorization_hash
            or artifact.artifact_hash != facts.artifact_hash
            or artifact.artifact_hash != projection.artifact_sha256
            or artifact.artifact_hash != record.artifact_sha256
            or artifact.artifact_hash != outcome.artifact_hash
        ):
            raise FormalOutcomeCompositionError(
                f"formal outcome entry {index} run artifact ancestry is inconsistent"
            )
        try:
            expected_facts = derive_artifact_facts(artifact)
            expected_projection = derive_detection_signal_projection(
                manifest=oracle_manifest,
                artifact=artifact,
                facts=expected_facts,
            )
        except ValueError as error:
            raise FormalOutcomeCompositionError(
                f"formal outcome entry {index} cannot be independently derived"
            ) from error
        if (
            facts != expected_facts
            or projection != expected_projection
            or record is not outcome.detection_record
            or facts is not outcome.artifact_facts
            or record.signal_projection_record != projection
            or record.oracle_manifest_hash != oracle_manifest.contract_hash
            or projection.oracle_manifest_hash != oracle_manifest.contract_hash
            or projection.adapter_source_sha256
            != dict(expected_adapters)[artifact.task_id]
            or record.formal_eligible is not oracle_manifest.formal_eligible
        ):
            raise FormalOutcomeCompositionError(
                f"formal outcome entry {index} oracle or adapter ancestry is inconsistent"
            )
    formal_eligible = oracle_manifest.formal_eligible
    if formal_eligible is not run.formal_result:
        raise FormalOutcomeCompositionError(
            "run and oracle production eligibility disagree"
        )
    body = {
        "schema": FORMAL_OUTCOME_PACKAGE_SCHEMA,
        "claim_scope": oracle_manifest.claim_scope,
        "test_only": not formal_eligible,
        "formal_eligible": formal_eligible,
        "run_hash": run.run_hash,
        "plan_hash": run.authorization.plan_hash,
        "authorization_hash": run.authorization.authorization_hash,
        "oracle_manifest_hash": oracle_manifest.contract_hash,
        "adapter_source_hashes": {
            task_id: source_hash for task_id, source_hash in expected_adapters
        },
        "case_count": 36,
        "arm_case_count": 180,
        "artifact_facts": [item.to_dict() for item in facts_values],
        "signal_projections": [item.to_dict() for item in projection_values],
        "detection_records": [item.to_dict() for item in record_values],
        "outcomes": [_outcome_dict(item) for item in outcome_values],
    }
    return FormalOutcomePackage(
        schema=FORMAL_OUTCOME_PACKAGE_SCHEMA,
        claim_scope=oracle_manifest.claim_scope,
        test_only=not formal_eligible,
        formal_eligible=formal_eligible,
        run_hash=run.run_hash,
        plan_hash=run.authorization.plan_hash,
        authorization_hash=run.authorization.authorization_hash,
        oracle_manifest_hash=oracle_manifest.contract_hash,
        adapter_source_hashes=expected_adapters,
        artifact_facts=facts_values,
        signal_projections=projection_values,
        detection_records=record_values,
        outcomes=outcome_values,
        package_hash=_canonical_hash(body),
        _factory_token=_PACKAGE_FACTORY_TOKEN,
    )


@dataclass(frozen=True)
class FormalOutcomeEvidenceSeal:
    """Post-run seal over the outcome package and its complete source ancestry."""

    schema: str
    claim_scope: str
    test_only: bool
    formal_eligible: bool
    run_hash: str
    package_hash: str
    oracle_manifest_hash: str
    source_lock_hash: str
    authorization_hash: str
    artifact_refs: tuple[tuple[int, str, str, str], ...]
    seal_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _EVIDENCE_SEAL_FACTORY_TOKEN:
            raise FormalOutcomeCompositionError(
                "formal outcome evidence seals require the post-run factory"
            )
        if (
            self.schema != FORMAL_OUTCOME_EVIDENCE_SEAL_SCHEMA
            or not isinstance(self.test_only, bool)
            or not isinstance(self.formal_eligible, bool)
            or self.test_only is self.formal_eligible
        ):
            raise FormalOutcomeCompositionError(
                "outcome evidence seal class is invalid"
            )
        for value, label in (
            (self.run_hash, "evidence run_hash"),
            (self.package_hash, "evidence package_hash"),
            (self.oracle_manifest_hash, "evidence oracle_manifest_hash"),
            (self.source_lock_hash, "evidence source_lock_hash"),
            (self.authorization_hash, "evidence authorization_hash"),
            (self.seal_hash, "evidence seal_hash"),
        ):
            _hash(value, label)
        refs = tuple(self.artifact_refs)
        object.__setattr__(self, "artifact_refs", refs)
        if len(refs) != 180:
            raise FormalOutcomeCompositionError(
                "formal outcome evidence requires exactly 180 artifact hashes"
            )
        expected_pairs = _expected_pairs()
        for expected_index, (reference, expected_pair) in enumerate(
            zip(refs, expected_pairs, strict=True)
        ):
            if (
                not isinstance(reference, tuple)
                or len(reference) != 4
                or type(reference[0]) is not int
                or reference[0] != expected_index
                or reference[1:3] != expected_pair
            ):
                raise FormalOutcomeCompositionError(
                    "formal outcome evidence artifact coverage or order is invalid"
                )
            _hash(reference[3], "evidence artifact hash")
        if self.seal_hash != _canonical_hash(self._body()):
            raise FormalOutcomeCompositionError(
                "formal outcome evidence seal hash mismatch"
            )

    def _body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "claim_scope": self.claim_scope,
            "test_only": self.test_only,
            "formal_eligible": self.formal_eligible,
            "run_hash": self.run_hash,
            "package_hash": self.package_hash,
            "oracle_manifest_hash": self.oracle_manifest_hash,
            "source_lock_hash": self.source_lock_hash,
            "authorization_hash": self.authorization_hash,
            "artifact_refs": [
                {
                    "execution_index": execution_index,
                    "case_id": case_id,
                    "arm_id": arm_id,
                    "artifact_hash": artifact_hash,
                }
                for execution_index, case_id, arm_id, artifact_hash in (
                    self.artifact_refs
                )
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "seal_hash": self.seal_hash}


@dataclass(frozen=True)
class FormalOutcomeEvidenceBundle:
    """Persistable post-run envelope; it is not part of ``FormalContractRun``."""

    schema: str
    package: FormalOutcomePackage
    seal: FormalOutcomeEvidenceSeal
    bundle_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _EVIDENCE_BUNDLE_FACTORY_TOKEN:
            raise FormalOutcomeCompositionError(
                "formal outcome evidence bundles require the post-run factory"
            )
        if (
            self.schema != FORMAL_OUTCOME_EVIDENCE_BUNDLE_SCHEMA
            or not isinstance(self.package, FormalOutcomePackage)
            or not isinstance(self.seal, FormalOutcomeEvidenceSeal)
            or self.seal.package_hash != self.package.package_hash
            or self.seal.run_hash != self.package.run_hash
            or self.seal.oracle_manifest_hash != self.package.oracle_manifest_hash
            or self.seal.authorization_hash != self.package.authorization_hash
            or self.seal.claim_scope != self.package.claim_scope
            or self.seal.test_only is not self.package.test_only
            or self.seal.formal_eligible is not self.package.formal_eligible
        ):
            raise FormalOutcomeCompositionError(
                "formal outcome evidence bundle ancestry is inconsistent"
            )
        _hash(self.bundle_hash, "outcome evidence bundle_hash")
        if self.bundle_hash != _canonical_hash(self._body()):
            raise FormalOutcomeCompositionError(
                "formal outcome evidence bundle hash mismatch"
            )

    def _body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "package": self.package.to_dict(),
            "seal": self.seal.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "bundle_hash": self.bundle_hash}

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        run: FormalContractRun,
        oracle_manifest: DetectionOracleManifest,
        outcomes: Sequence[OracleBoundArmCaseOutcome],
        source_lock_hash: str,
    ) -> FormalOutcomeEvidenceBundle:
        if not isinstance(value, Mapping):
            raise FormalOutcomeCompositionError(
                "serialized outcome evidence bundle must be an object"
            )
        _exact_keys(
            value,
            {"schema", "package", "seal", "bundle_hash"},
            "formal outcome evidence bundle",
        )
        package_value = value["package"]
        if not isinstance(package_value, Mapping):
            raise FormalOutcomeCompositionError(
                "serialized outcome evidence package must be an object"
            )
        package = FormalOutcomePackage.from_dict(
            package_value,
            run=run,
            oracle_manifest=oracle_manifest,
            outcomes=outcomes,
        )
        restored = seal_formal_outcome_evidence(
            run=run,
            package=package,
            oracle_manifest=oracle_manifest,
            source_lock_hash=source_lock_hash,
        )
        if dict(value) != restored.to_dict():
            raise FormalOutcomeCompositionError(
                "serialized outcome evidence disagrees with typed source ancestry"
            )
        return restored


def seal_formal_outcome_evidence(
    *,
    run: FormalContractRun,
    package: FormalOutcomePackage,
    oracle_manifest: DetectionOracleManifest,
    source_lock_hash: str,
) -> FormalOutcomeEvidenceBundle:
    """Create a non-circular post-run seal over one exact outcome package."""

    if not isinstance(run, FormalContractRun):
        raise FormalOutcomeCompositionError(
            "formal outcome evidence requires a FormalContractRun"
        )
    if not isinstance(package, FormalOutcomePackage):
        raise FormalOutcomeCompositionError(
            "formal outcome evidence requires a FormalOutcomePackage"
        )
    if not isinstance(oracle_manifest, DetectionOracleManifest):
        raise FormalOutcomeCompositionError(
            "formal outcome evidence requires a typed oracle manifest"
        )
    _hash(source_lock_hash, "evidence source_lock_hash")
    if (
        package.run_hash != run.run_hash
        or package.plan_hash != run.authorization.plan_hash
        or package.authorization_hash != run.authorization.authorization_hash
        or package.oracle_manifest_hash != oracle_manifest.contract_hash
        or package.claim_scope != oracle_manifest.claim_scope
        or package.formal_eligible is not oracle_manifest.formal_eligible
        or package.formal_eligible is not run.formal_result
        or package.test_only is package.formal_eligible
    ):
        raise FormalOutcomeCompositionError(
            "formal outcome evidence run/package/oracle ancestry is inconsistent"
        )
    artifact_refs = tuple(
        (
            artifact.execution_index,
            artifact.case_id,
            artifact.arm_id,
            artifact.artifact_hash,
        )
        for artifact in run.artifacts
    )
    seal_body = {
        "schema": FORMAL_OUTCOME_EVIDENCE_SEAL_SCHEMA,
        "claim_scope": package.claim_scope,
        "test_only": package.test_only,
        "formal_eligible": package.formal_eligible,
        "run_hash": run.run_hash,
        "package_hash": package.package_hash,
        "oracle_manifest_hash": oracle_manifest.contract_hash,
        "source_lock_hash": source_lock_hash,
        "authorization_hash": run.authorization.authorization_hash,
        "artifact_refs": [
            {
                "execution_index": execution_index,
                "case_id": case_id,
                "arm_id": arm_id,
                "artifact_hash": artifact_hash,
            }
            for execution_index, case_id, arm_id, artifact_hash in artifact_refs
        ],
    }
    seal = FormalOutcomeEvidenceSeal(
        schema=FORMAL_OUTCOME_EVIDENCE_SEAL_SCHEMA,
        claim_scope=package.claim_scope,
        test_only=package.test_only,
        formal_eligible=package.formal_eligible,
        run_hash=run.run_hash,
        package_hash=package.package_hash,
        oracle_manifest_hash=oracle_manifest.contract_hash,
        source_lock_hash=source_lock_hash,
        authorization_hash=run.authorization.authorization_hash,
        artifact_refs=artifact_refs,
        seal_hash=_canonical_hash(seal_body),
        _factory_token=_EVIDENCE_SEAL_FACTORY_TOKEN,
    )
    bundle_body = {
        "schema": FORMAL_OUTCOME_EVIDENCE_BUNDLE_SCHEMA,
        "package": package.to_dict(),
        "seal": seal.to_dict(),
    }
    return FormalOutcomeEvidenceBundle(
        schema=FORMAL_OUTCOME_EVIDENCE_BUNDLE_SCHEMA,
        package=package,
        seal=seal,
        bundle_hash=_canonical_hash(bundle_body),
        _factory_token=_EVIDENCE_BUNDLE_FACTORY_TOKEN,
    )


@dataclass(frozen=True)
class FormalOutcomeEvidencePersistenceReceipt:
    path: Path
    file_sha256: str


def _absolute_path(path: str | os.PathLike[str]) -> Path:
    return Path(path).expanduser().absolute()


def _reject_symlink_ancestry(path: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise FormalOutcomeEvidenceWriteError(
                "outcome evidence path ancestry cannot contain a symbolic link"
            )
        if current.parent == current:
            return
        current = current.parent


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(directory, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as error:
        raise FormalOutcomeEvidenceWriteError(
            "cannot fsync outcome evidence directory"
        ) from error


class FormalOutcomeEvidenceStore:
    """Atomic, write-once persistence with typed readback re-verification."""

    @classmethod
    def write(
        cls,
        path: str | os.PathLike[str],
        bundle: FormalOutcomeEvidenceBundle,
    ) -> FormalOutcomeEvidencePersistenceReceipt:
        if not isinstance(bundle, FormalOutcomeEvidenceBundle):
            raise FormalOutcomeEvidenceWriteError(
                "outcome evidence store requires a typed bundle"
            )
        destination = _absolute_path(path)
        if not destination.name or destination.name in {".", ".."}:
            raise FormalOutcomeEvidenceWriteError(
                "outcome evidence path must name a file"
            )
        _reject_symlink_ancestry(destination)
        if not destination.parent.is_dir():
            raise FormalOutcomeEvidenceWriteError(
                "outcome evidence parent directory is missing"
            )
        if destination.is_symlink():
            raise FormalOutcomeEvidenceWriteError(
                "outcome evidence target cannot be a symbolic link"
            )
        file_bytes = (
            json.dumps(
                bundle.to_dict(),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(file_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError as error:
                raise FormalOutcomeEvidenceExistsError(
                    f"outcome evidence already exists: {destination.name}"
                ) from error
            except OSError as error:
                raise FormalOutcomeEvidenceWriteError(
                    "cannot atomically publish outcome evidence"
                ) from error
            _fsync_directory(destination.parent)
        finally:
            temporary.unlink(missing_ok=True)
        return FormalOutcomeEvidencePersistenceReceipt(
            path=Path(path),
            file_sha256=hashlib.sha256(file_bytes).hexdigest(),
        )

    @classmethod
    def read(
        cls,
        path: str | os.PathLike[str],
        *,
        run: FormalContractRun,
        oracle_manifest: DetectionOracleManifest,
        outcomes: Sequence[OracleBoundArmCaseOutcome],
        source_lock_hash: str,
        expected_file_sha256: str | None = None,
    ) -> FormalOutcomeEvidenceBundle:
        source = _absolute_path(path)
        try:
            _reject_symlink_ancestry(source)
        except FormalOutcomeEvidenceWriteError as error:
            raise FormalOutcomeCompositionError(
                "outcome evidence source cannot be a symbolic link"
            ) from error
        if not source.is_file():
            raise FormalOutcomeCompositionError(
                "outcome evidence source is missing or unreadable"
            )
        try:
            file_bytes = source.read_bytes()
        except OSError as error:
            raise FormalOutcomeCompositionError(
                "cannot read outcome evidence source"
            ) from error
        actual_file_hash = hashlib.sha256(file_bytes).hexdigest()
        if expected_file_sha256 is not None:
            _hash(expected_file_sha256, "expected outcome evidence file hash")
            if actual_file_hash != expected_file_sha256:
                raise FormalOutcomeCompositionError(
                    "outcome evidence file hash mismatch"
                )
        try:
            value = json.loads(file_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FormalOutcomeCompositionError(
                "outcome evidence source is not valid JSON"
            ) from error
        if not isinstance(value, Mapping):
            raise FormalOutcomeCompositionError(
                "outcome evidence source must contain an object"
            )
        return FormalOutcomeEvidenceBundle.from_dict(
            value,
            run=run,
            oracle_manifest=oracle_manifest,
            outcomes=outcomes,
            source_lock_hash=source_lock_hash,
        )


__all__ = [
    "FORMAL_OUTCOME_EVIDENCE_BUNDLE_SCHEMA",
    "FORMAL_OUTCOME_EVIDENCE_SEAL_SCHEMA",
    "FORMAL_OUTCOME_PACKAGE_SCHEMA",
    "FormalOutcomeCompositionError",
    "FormalOutcomeEvidenceBundle",
    "FormalOutcomeEvidenceExistsError",
    "FormalOutcomeEvidencePersistenceReceipt",
    "FormalOutcomeEvidenceSeal",
    "FormalOutcomeEvidenceStore",
    "FormalOutcomeEvidenceWriteError",
    "FormalOutcomePackage",
    "compose_formal_outcome_package",
    "seal_formal_outcome_evidence",
]
