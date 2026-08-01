"""Artifact-derived MEAS0 facts and oracle-bound metric ancestry.

Artifact facts remain non-claim-bearing.  A separate factory may bind them to
gold flags and a typed detection record without accepting detection booleans.
Formal eligibility is still decided by the record and claim-bearing metric
entry points; the bundled candidate remains test-only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .meas0_detection_oracle import DerivedDetectionRecord
from .meas0_formal_metrics import FormalCaseIdentity
from .meas0_formal_runner import (
    FailureCode,
    FormalArmCaseArtifact,
    FormalRunnerError,
)
from .measurement import (
    EvaluationStatus,
    MeasurementKind,
    MeasurementRole,
)


FORMAL_DERIVATION_VERSION = "meas0.formal-artifact-facts.v2"
_DERIVATION_TOKEN = object()
_ORACLE_BOUND_OUTCOME_TOKEN = object()


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


@dataclass(frozen=True)
class ArtifactDerivedFacts:
    """Fields that can be projected without gold or a detection oracle."""

    derivation_version: str
    case_id: str
    task_id: str
    fault_id: str
    arm_id: str
    authorization_hash: str
    artifact_hash: str
    canonical_bundle_hash: str
    canonical_episode_hash: str
    automatic_status: EvaluationStatus
    budget_exhausted: bool
    human_escalations: int
    deterministic_eligible_leaves: int
    deterministic_resolved_leaves: int
    all_formal_leaves: int
    deterministically_resolved_all_leaves: int
    derivation_hash: str
    _derivation_token: object = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self.derivation_version != FORMAL_DERIVATION_VERSION:
            raise FormalRunnerError("formal artifact derivation version is invalid")
        if self._derivation_token is not _DERIVATION_TOKEN:
            raise FormalRunnerError(
                "formal artifact facts must be derived from a canonical artifact"
            )
        expected = _canonical_hash(self._body())
        if self.derivation_hash != expected:
            raise FormalRunnerError("formal artifact derivation hash mismatch")

    def _body(self) -> dict[str, Any]:
        return {
            "derivation_version": self.derivation_version,
            "case_id": self.case_id,
            "task_id": self.task_id,
            "fault_id": self.fault_id,
            "arm_id": self.arm_id,
            "authorization_hash": self.authorization_hash,
            "artifact_hash": self.artifact_hash,
            "canonical_bundle_hash": self.canonical_bundle_hash,
            "canonical_episode_hash": self.canonical_episode_hash,
            "automatic_status": self.automatic_status.value,
            "budget_exhausted": self.budget_exhausted,
            "human_escalations": self.human_escalations,
            "deterministic_eligible_leaves": (self.deterministic_eligible_leaves),
            "deterministic_resolved_leaves": (self.deterministic_resolved_leaves),
            "all_formal_leaves": self.all_formal_leaves,
            "deterministically_resolved_all_leaves": (
                self.deterministically_resolved_all_leaves
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "derivation_hash": self.derivation_hash}


@dataclass(frozen=True)
class OracleBoundArmCaseOutcome:
    """Metric leaves whose detection values come only from an oracle record.

    This type does not itself make the bundled test-only candidate formally
    eligible.  Claim-bearing metric entry points additionally require a
    production-eligible record.
    """

    case: FormalCaseIdentity
    artifact_facts: ArtifactDerivedFacts
    detection_record: DerivedDetectionRecord
    gold_status: str | None
    accept_allowed: bool
    safety_violation: bool
    _derivation_token: object = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self._derivation_token is not _ORACLE_BOUND_OUTCOME_TOKEN:
            raise FormalRunnerError(
                "oracle-bound outcomes must be created by the derivation factory"
            )
        if (
            not isinstance(self.case, FormalCaseIdentity)
            or not isinstance(self.artifact_facts, ArtifactDerivedFacts)
            or not isinstance(self.detection_record, DerivedDetectionRecord)
        ):
            raise FormalRunnerError("oracle-bound outcome ancestry is malformed")
        facts = self.artifact_facts
        record = self.detection_record
        projection = record.signal_projection_record
        if (
            record.legacy_synthetic
            or projection is None
            or projection.artifact_facts_hash != facts.derivation_hash
            or projection.authorization_hash != facts.authorization_hash
        ):
            raise FormalRunnerError(
                "oracle-bound outcome requires an artifact-derived projection"
            )
        identity = (
            self.case.case_id,
            self.case.task_id,
            self.case.fault_id,
        )
        if (
            identity != (facts.case_id, facts.task_id, facts.fault_id)
            or identity != (record.case_id, record.task_id, record.fault_id)
            or facts.arm_id != record.arm_id
            or facts.artifact_hash != record.artifact_sha256
        ):
            raise FormalRunnerError(
                "oracle-bound outcome artifact ancestry is inconsistent"
            )
        if self.gold_status is not None and self.gold_status not in {
            "pass",
            "fail",
            "unknown",
            "disputed",
            "invalid",
        }:
            raise FormalRunnerError("oracle-bound gold status is invalid")
        if not isinstance(self.accept_allowed, bool) or not isinstance(
            self.safety_violation,
            bool,
        ):
            raise FormalRunnerError("oracle-bound gold flags must be boolean")

    @property
    def arm(self) -> str:
        return self.artifact_facts.arm_id

    @property
    def artifact_hash(self) -> str:
        return self.artifact_facts.artifact_hash

    @property
    def automatic_status(self) -> str:
        return self.artifact_facts.automatic_status.value

    @property
    def detection_expected(self) -> bool:
        return self.detection_record.detection_expected

    @property
    def detected(self) -> bool:
        return self.detection_record.detected

    @property
    def budget_exhausted(self) -> bool:
        return self.artifact_facts.budget_exhausted

    @property
    def human_escalations(self) -> int:
        return self.artifact_facts.human_escalations

    @property
    def deterministic_eligible_leaves(self) -> int:
        return self.artifact_facts.deterministic_eligible_leaves

    @property
    def deterministic_resolved_leaves(self) -> int:
        return self.artifact_facts.deterministic_resolved_leaves

    @property
    def all_formal_leaves(self) -> int:
        return self.artifact_facts.all_formal_leaves

    @property
    def deterministically_resolved_all_leaves(self) -> int:
        return self.artifact_facts.deterministically_resolved_all_leaves


def derive_oracle_bound_arm_case_outcome(
    *,
    case: FormalCaseIdentity,
    facts: ArtifactDerivedFacts,
    detection_record: DerivedDetectionRecord,
    gold_status: str | None,
    accept_allowed: bool,
    safety_violation: bool,
) -> OracleBoundArmCaseOutcome:
    """Bind artifact facts and oracle evidence without accepting detection flags."""

    return OracleBoundArmCaseOutcome(
        case=case,
        artifact_facts=facts,
        detection_record=detection_record,
        gold_status=gold_status,
        accept_allowed=accept_allowed,
        safety_violation=safety_violation,
        _derivation_token=_ORACLE_BOUND_OUTCOME_TOKEN,
    )


def derive_artifact_facts(
    artifact: FormalArmCaseArtifact,
) -> ArtifactDerivedFacts:
    """Recompute the metric leaves available from one canonical artifact."""

    if not isinstance(artifact, FormalArmCaseArtifact):
        raise FormalRunnerError("formal artifact facts require a FormalArmCaseArtifact")
    canonical = artifact.canonical_evaluation
    if canonical is None:
        raise FormalRunnerError(
            "formal artifact facts require canonical evaluation evidence"
        )
    bundle = canonical.task_measurement_bundle
    graph = bundle.measurement_graph
    requirements = bundle.requirement_graph.requirements
    observations = {item.measurement_id: item for item in canonical.observations}

    decisive_specs = {}
    for requirement in requirements:
        matching = tuple(
            item
            for item in graph.measurement_specs
            if item.target_requirement_id == requirement.requirement_id
            and item.role is MeasurementRole.DECISIVE
        )
        if len(matching) != 1:
            raise FormalRunnerError(
                "formal artifact requirement lacks one decisive measurement"
            )
        decisive_specs[requirement.requirement_id] = matching[0]

    deterministic_specs = tuple(
        spec
        for spec in decisive_specs.values()
        if spec.kind is MeasurementKind.DETERMINISTIC
    )
    resolved = sum(
        spec.measurement_id in observations
        and observations[spec.measurement_id].status
        in {EvaluationStatus.PASS, EvaluationStatus.FAIL}
        for spec in deterministic_specs
    )
    budget_exhausted = artifact.failure is not None and artifact.failure.code in {
        FailureCode.BUDGET_EXHAUSTED,
        FailureCode.STAGE_BUDGET_EXHAUSTED,
    }
    body = {
        "derivation_version": FORMAL_DERIVATION_VERSION,
        "case_id": artifact.case_id,
        "task_id": artifact.task_id,
        "fault_id": artifact.fault_id,
        "arm_id": artifact.arm_id,
        "authorization_hash": artifact.authorization_hash,
        "artifact_hash": artifact.artifact_hash,
        "canonical_bundle_hash": bundle.bundle_hash,
        "canonical_episode_hash": canonical.sealed_episode.episode_hash,
        "automatic_status": artifact.automatic_status.value,
        "budget_exhausted": budget_exhausted,
        "human_escalations": artifact.cost.human_escalations,
        "deterministic_eligible_leaves": len(deterministic_specs),
        "deterministic_resolved_leaves": resolved,
        "all_formal_leaves": len(requirements),
        "deterministically_resolved_all_leaves": resolved,
    }
    return ArtifactDerivedFacts(
        derivation_version=FORMAL_DERIVATION_VERSION,
        case_id=artifact.case_id,
        task_id=artifact.task_id,
        fault_id=artifact.fault_id,
        arm_id=artifact.arm_id,
        authorization_hash=artifact.authorization_hash,
        artifact_hash=artifact.artifact_hash,
        canonical_bundle_hash=bundle.bundle_hash,
        canonical_episode_hash=canonical.sealed_episode.episode_hash,
        automatic_status=artifact.automatic_status,
        budget_exhausted=budget_exhausted,
        human_escalations=artifact.cost.human_escalations,
        deterministic_eligible_leaves=len(deterministic_specs),
        deterministic_resolved_leaves=resolved,
        all_formal_leaves=len(requirements),
        deterministically_resolved_all_leaves=resolved,
        derivation_hash=_canonical_hash(body),
        _derivation_token=_DERIVATION_TOKEN,
    )


__all__ = [
    "FORMAL_DERIVATION_VERSION",
    "ArtifactDerivedFacts",
    "OracleBoundArmCaseOutcome",
    "derive_artifact_facts",
    "derive_oracle_bound_arm_case_outcome",
]
