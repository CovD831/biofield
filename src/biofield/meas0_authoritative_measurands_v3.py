"""Offline D11 authority inventory for independently derived MEAS0 facts.

This module deliberately does not create a detection record.  It separates:

* a simulated, non-claim-bearing projection reconstructed only from typed
  request/artifact/measurement/failure sources; and
* a backend ``detection_signals`` audit record that is permanently ineligible
  as authority or detection input.

The first slice derives only facts that the existing schemas can independently
close.  Every other oracle signal is represented explicitly as unavailable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .meas0_detection_oracle import DetectionOracleManifest
from .meas0_failure_evidence_v3 import (
    FAILURE_EVIDENCE_TYPES_V3,
    FailureEvidenceV3,
)
from .meas0_formal_runner import (
    FailureCode,
    FormalArmCaseArtifact,
    FormalArmRequest,
)
from .measurement import MeasurementDimension


AUTHORITY_PROJECTION_SCHEMA_V3 = "meas0.simulated-authoritative-measurand-projection.v3"
RAW_DETECTION_AUDIT_SCHEMA_V3 = "meas0.raw-detection-signals-audit.v3"
ORACLE_BINDING_SCHEMA_V3 = "meas0.simulated-frozen-oracle-binding.v3"
CLAIM_SCOPE_V3 = "simulated_nonclaim"


class AuthoritativeMeasurandV3Error(ValueError):
    """Typed D11 authority evidence is incomplete, mixed, or inconsistent."""


class MeasurandAvailabilityV3(str, Enum):
    DERIVED = "derived"
    UNAVAILABLE = "unavailable"


_PROJECTION_TOKEN = object()
_FACT_TOKEN = object()
_AUDIT_TOKEN = object()
_ORACLE_BINDING_TOKEN = object()
_STRUCTURE_FACT_NAMES = (
    "request_artifact_ancestry_valid",
    "judge_transport_membership_authority_valid",
    "legacy_formal_detection_authority_valid",
    "artifact_denominator_retained",
    "canonical_measurement_binding_valid",
    "internal_measurement_contract_consistent",
    "sealed_episode_parent_structure_valid",
    "failure_evidence_integrity_valid",
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
        raise AuthoritativeMeasurandV3Error(
            "D11 evidence is not canonical JSON"
        ) from error


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _duplicate_rejecting_object(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AuthoritativeMeasurandV3Error(
                "serialized D11 evidence contains duplicate fields"
            )
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise AuthoritativeMeasurandV3Error(
        f"serialized D11 evidence contains non-finite value: {value}"
    )


def _decode_canonical_bytes(raw_bytes: bytes) -> object:
    if type(raw_bytes) is not bytes:
        raise AuthoritativeMeasurandV3Error("serialized D11 evidence must be bytes")
    try:
        value = json.loads(
            raw_bytes.decode("utf-8"),
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=_reject_nonfinite,
        )
    except AuthoritativeMeasurandV3Error:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise AuthoritativeMeasurandV3Error(
            "serialized D11 evidence is not strict JSON"
        ) from error
    if raw_bytes != _canonical_bytes(value):
        raise AuthoritativeMeasurandV3Error(
            "serialized D11 evidence bytes are not canonical"
        )
    return value


def _digest(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise AuthoritativeMeasurandV3Error(f"{label} must be a lowercase SHA-256")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthoritativeMeasurandV3Error(f"{label} must be non-empty text")
    return value


def _exact_type_equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, Mapping):
        assert isinstance(right, Mapping)
        return set(left) == set(right) and all(
            _exact_type_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, (list, tuple)):
        assert isinstance(right, (list, tuple))
        return len(left) == len(right) and all(
            _exact_type_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return left == right


def _strict_equal(value: object, expected: Mapping[str, object]) -> None:
    if not _exact_type_equal(value, expected):
        raise AuthoritativeMeasurandV3Error(
            "serialized projection differs from typed-source derivation"
        )


def _json_value(value: object, label: str) -> object:
    _canonical_bytes(value)
    if isinstance(value, (dict, list)):
        raise AuthoritativeMeasurandV3Error(
            f"{label} must be a scalar in this D11 slice"
        )
    return value


@dataclass(frozen=True)
class SimulatedFrozenOracleBindingV3:
    """Explicit offline binding of one typed request to one frozen oracle."""

    schema: str
    version: int
    claim_scope: str
    test_only: bool
    production_authorized: bool
    request_hash: str
    authorization_hash: str
    oracle_manifest_hash: str
    oracle_entry_hashes: tuple[str, ...]
    binding_hash: str
    _request_source: object = field(default=None, repr=False, compare=False)
    _oracle_source: object = field(default=None, repr=False, compare=False)
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._factory_token is not _ORACLE_BINDING_TOKEN
            or self.schema != ORACLE_BINDING_SCHEMA_V3
            or self.version != 3
            or self.claim_scope != CLAIM_SCOPE_V3
            or self.test_only is not True
            or self.production_authorized is not False
            or not isinstance(self._request_source, FormalArmRequest)
            or not isinstance(self._oracle_source, DetectionOracleManifest)
        ):
            raise AuthoritativeMeasurandV3Error(
                "simulated frozen oracle binding is invalid"
            )
        object.__setattr__(
            self,
            "oracle_entry_hashes",
            tuple(self.oracle_entry_hashes),
        )
        if (
            self.request_hash != self._request_source.request_hash
            or self.authorization_hash != self._request_source.authorization_hash
            or self.oracle_manifest_hash != self._oracle_source.contract_hash
            or self.oracle_entry_hashes
            != tuple(entry.contract_hash for entry in self._oracle_source.entries)
        ):
            raise AuthoritativeMeasurandV3Error(
                "oracle binding differs from its typed sources"
            )
        for value, label in (
            (self.request_hash, "oracle binding request hash"),
            (self.authorization_hash, "oracle binding authorization hash"),
            (self.oracle_manifest_hash, "oracle binding manifest hash"),
            (self.binding_hash, "oracle binding hash"),
        ):
            _digest(value, label)
        for value in self.oracle_entry_hashes:
            _digest(value, "oracle binding entry hash")
        if self.binding_hash != _canonical_hash(self._body()):
            raise AuthoritativeMeasurandV3Error("oracle binding hash mismatch")

    @classmethod
    def create(
        cls,
        *,
        request: FormalArmRequest,
        oracle: DetectionOracleManifest,
    ) -> SimulatedFrozenOracleBindingV3:
        if not isinstance(request, FormalArmRequest) or not isinstance(
            oracle,
            DetectionOracleManifest,
        ):
            raise AuthoritativeMeasurandV3Error(
                "oracle binding requires typed request and oracle sources"
            )
        body = {
            "schema": ORACLE_BINDING_SCHEMA_V3,
            "version": 3,
            "claim_scope": CLAIM_SCOPE_V3,
            "test_only": True,
            "production_authorized": False,
            "request_hash": request.request_hash,
            "authorization_hash": request.authorization_hash,
            "oracle_manifest_hash": oracle.contract_hash,
            "oracle_entry_hashes": [entry.contract_hash for entry in oracle.entries],
        }
        return cls(
            schema=ORACLE_BINDING_SCHEMA_V3,
            version=3,
            claim_scope=CLAIM_SCOPE_V3,
            test_only=True,
            production_authorized=False,
            request_hash=request.request_hash,
            authorization_hash=request.authorization_hash,
            oracle_manifest_hash=oracle.contract_hash,
            oracle_entry_hashes=tuple(body["oracle_entry_hashes"]),
            binding_hash=_canonical_hash(body),
            _request_source=request,
            _oracle_source=oracle,
            _factory_token=_ORACLE_BINDING_TOKEN,
        )

    @property
    def oracle(self) -> DetectionOracleManifest:
        assert isinstance(self._oracle_source, DetectionOracleManifest)
        return self._oracle_source

    def _body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "claim_scope": self.claim_scope,
            "test_only": self.test_only,
            "production_authorized": self.production_authorized,
            "request_hash": self.request_hash,
            "authorization_hash": self.authorization_hash,
            "oracle_manifest_hash": self.oracle_manifest_hash,
            "oracle_entry_hashes": list(self.oracle_entry_hashes),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "binding_hash": self.binding_hash}


@dataclass(frozen=True)
class AuthoritativeFactV3:
    """One typed-source fact or an explicit unavailable oracle measurand."""

    name: str
    availability: MeasurandAvailabilityV3
    value: object | None
    source_kind: str | None
    source_hashes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _FACT_TOKEN:
            raise AuthoritativeMeasurandV3Error(
                "authoritative facts require typed derivation"
            )
        _text(self.name, "fact name")
        if not isinstance(self.availability, MeasurandAvailabilityV3):
            raise AuthoritativeMeasurandV3Error("fact availability is invalid")
        object.__setattr__(self, "source_hashes", tuple(self.source_hashes))
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        for value in self.source_hashes:
            _digest(value, "fact source hash")
        for value in self.evidence_refs:
            _text(value, "fact evidence ref")
        if self.availability is MeasurandAvailabilityV3.DERIVED:
            if self.value is None or self.source_kind is None:
                raise AuthoritativeMeasurandV3Error(
                    "derived fact requires a value and typed source"
                )
            _json_value(self.value, "derived fact value")
            _text(self.source_kind, "fact source kind")
            if not self.source_hashes or not self.evidence_refs:
                raise AuthoritativeMeasurandV3Error(
                    "derived fact requires source hashes and evidence refs"
                )
        elif (
            self.value is not None
            or self.source_kind is not None
            or self.source_hashes
            or self.evidence_refs
        ):
            raise AuthoritativeMeasurandV3Error(
                "unavailable fact cannot carry a value or source authority"
            )

    @classmethod
    def derived(
        cls,
        *,
        name: str,
        value: object,
        source_kind: str,
        source_hashes: tuple[str, ...],
        evidence_refs: tuple[str, ...],
    ) -> AuthoritativeFactV3:
        return cls(
            name=name,
            availability=MeasurandAvailabilityV3.DERIVED,
            value=value,
            source_kind=source_kind,
            source_hashes=source_hashes,
            evidence_refs=evidence_refs,
            _factory_token=_FACT_TOKEN,
        )

    @classmethod
    def unavailable(cls, name: str) -> AuthoritativeFactV3:
        return cls(
            name=name,
            availability=MeasurandAvailabilityV3.UNAVAILABLE,
            value=None,
            source_kind=None,
            source_hashes=(),
            evidence_refs=(),
            _factory_token=_FACT_TOKEN,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "availability": self.availability.value,
            "value": self.value,
            "source_kind": self.source_kind,
            "source_hashes": list(self.source_hashes),
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class SimulatedAuthoritativeMeasurandProjectionV3:
    """Non-claim D11 inventory reconstructed from typed authority only."""

    schema: str
    version: int
    claim_scope: str
    test_only: bool
    production_authorized: bool
    formal_eligible: bool
    detection_eligible: bool
    authority_binding_hash: str
    request_hash: str
    artifact_hash: str
    oracle_manifest_hash: str
    oracle_entry_hash: str
    case_id: str
    task_id: str
    fault_id: str
    arm_id: str
    structure_facts: tuple[AuthoritativeFactV3, ...]
    measurands: tuple[AuthoritativeFactV3, ...]
    projection_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _PROJECTION_TOKEN:
            raise AuthoritativeMeasurandV3Error(
                "authoritative projection requires typed-source derivation"
            )
        if (
            self.schema != AUTHORITY_PROJECTION_SCHEMA_V3
            or self.version != 3
            or self.claim_scope != CLAIM_SCOPE_V3
            or self.test_only is not True
            or self.production_authorized is not False
            or self.formal_eligible is not False
            or self.detection_eligible is not False
        ):
            raise AuthoritativeMeasurandV3Error(
                "authoritative projection crossed its offline nonclaim boundary"
            )
        for value, label in (
            (self.authority_binding_hash, "authority binding hash"),
            (self.request_hash, "request hash"),
            (self.artifact_hash, "artifact hash"),
            (self.oracle_manifest_hash, "oracle manifest hash"),
            (self.oracle_entry_hash, "oracle entry hash"),
            (self.projection_hash, "projection hash"),
        ):
            _digest(value, label)
        for value, label in (
            (self.case_id, "case_id"),
            (self.task_id, "task_id"),
            (self.fault_id, "fault_id"),
            (self.arm_id, "arm_id"),
        ):
            _text(value, label)
        object.__setattr__(self, "structure_facts", tuple(self.structure_facts))
        object.__setattr__(self, "measurands", tuple(self.measurands))
        if (
            not all(
                isinstance(item, AuthoritativeFactV3)
                for item in (*self.structure_facts, *self.measurands)
            )
            or tuple(item.name for item in self.structure_facts)
            != _STRUCTURE_FACT_NAMES
            or not self.measurands
            or len({item.name for item in self.measurands}) != len(self.measurands)
        ):
            raise AuthoritativeMeasurandV3Error(
                "authoritative projection fact membership is invalid"
            )
        if self.projection_hash != _canonical_hash(self._body()):
            raise AuthoritativeMeasurandV3Error(
                "authoritative projection hash mismatch"
            )

    def _body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "claim_scope": self.claim_scope,
            "test_only": self.test_only,
            "production_authorized": self.production_authorized,
            "formal_eligible": self.formal_eligible,
            "detection_eligible": self.detection_eligible,
            "authority_binding_hash": self.authority_binding_hash,
            "request_hash": self.request_hash,
            "artifact_hash": self.artifact_hash,
            "oracle_manifest_hash": self.oracle_manifest_hash,
            "oracle_entry_hash": self.oracle_entry_hash,
            "case_id": self.case_id,
            "task_id": self.task_id,
            "fault_id": self.fault_id,
            "arm_id": self.arm_id,
            "structure_facts": [item.to_dict() for item in self.structure_facts],
            "measurands": [item.to_dict() for item in self.measurands],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "projection_hash": self.projection_hash}

    def to_canonical_bytes(self) -> bytes:
        """Serialize the nonclaim projection using strict canonical JSON."""

        return _canonical_bytes(self.to_dict())

    @classmethod
    def restore_from_typed_sources(
        cls,
        value: object,
        *,
        request: FormalArmRequest,
        artifact: FormalArmCaseArtifact,
        oracle_binding: SimulatedFrozenOracleBindingV3,
        failure_evidence: FailureEvidenceV3 | None = None,
    ) -> SimulatedAuthoritativeMeasurandProjectionV3:
        restored = derive_simulated_authoritative_measurands(
            request=request,
            artifact=artifact,
            oracle_binding=oracle_binding,
            failure_evidence=failure_evidence,
        )
        _strict_equal(value, restored.to_dict())
        return restored

    @classmethod
    def restore_from_canonical_bytes(
        cls,
        raw_bytes: bytes,
        *,
        request: FormalArmRequest,
        artifact: FormalArmCaseArtifact,
        oracle_binding: SimulatedFrozenOracleBindingV3,
        failure_evidence: FailureEvidenceV3 | None = None,
    ) -> SimulatedAuthoritativeMeasurandProjectionV3:
        """Restore only when canonical bytes match typed D11 sources."""

        value = _decode_canonical_bytes(raw_bytes)
        if type(value) is not dict:
            raise AuthoritativeMeasurandV3Error(
                "serialized D11 projection must be an object"
            )
        return cls.restore_from_typed_sources(
            value,
            request=request,
            artifact=artifact,
            oracle_binding=oracle_binding,
            failure_evidence=failure_evidence,
        )


def _validate_typed_ancestry(
    *,
    request: FormalArmRequest,
    artifact: FormalArmCaseArtifact,
    oracle_binding: SimulatedFrozenOracleBindingV3,
    failure_evidence: FailureEvidenceV3 | None,
) -> DetectionOracleManifest:
    if not isinstance(request, FormalArmRequest):
        raise AuthoritativeMeasurandV3Error(
            "projection requires a typed FormalArmRequest"
        )
    if not isinstance(artifact, FormalArmCaseArtifact):
        raise AuthoritativeMeasurandV3Error(
            "projection requires a typed FormalArmCaseArtifact"
        )
    if not isinstance(oracle_binding, SimulatedFrozenOracleBindingV3):
        raise AuthoritativeMeasurandV3Error(
            "projection requires a typed frozen oracle binding"
        )
    oracle_binding.__post_init__()
    oracle = oracle_binding.oracle
    identity = (
        request.case.case_id,
        request.case.task_id,
        request.case.fault_id,
        request.arm_id,
    )
    if identity != (
        artifact.case_id,
        artifact.task_id,
        artifact.fault_id,
        artifact.arm_id,
    ):
        raise AuthoritativeMeasurandV3Error("request/artifact identity is inconsistent")
    if (
        request.authorization_hash != artifact.authorization_hash
        or request.request_hash != artifact.request_hash
        or request.execution_index != artifact.execution_index
    ):
        raise AuthoritativeMeasurandV3Error(
            "request/artifact common ancestry is inconsistent"
        )
    if (
        oracle_binding.request_hash != request.request_hash
        or oracle_binding.authorization_hash != request.authorization_hash
    ):
        raise AuthoritativeMeasurandV3Error("oracle binding is not request-bound")
    try:
        oracle.entry(artifact.fault_id)
    except (KeyError, ValueError) as error:
        raise AuthoritativeMeasurandV3Error(
            "oracle does not cover the typed artifact identity"
        ) from error
    canonical = artifact.canonical_evaluation
    if canonical is not None:
        bundle = canonical.task_measurement_bundle
        semantic_count = sum(
            requirement.dimension is MeasurementDimension.SEMANTIC
            for requirement in bundle.requirement_graph.requirements
        )
        if (
            bundle.task_frame.task_id != request.case.task_id
            or bundle.bundle_hash != request.task_hash
            or canonical.sealed_episode.episode_hash != request.episode_hash
            or len(bundle.measurement_graph.measurement_specs)
            != request.measurement_count
            or semantic_count != request.semantic_leaf_count
        ):
            raise AuthoritativeMeasurandV3Error(
                "canonical measurement evidence is not request-bound"
            )
    if failure_evidence is not None and not isinstance(
        failure_evidence,
        FAILURE_EVIDENCE_TYPES_V3,
    ):
        raise AuthoritativeMeasurandV3Error(
            "failure_evidence must be typed failure evidence"
        )
    if artifact.failure is None:
        if failure_evidence is not None:
            raise AuthoritativeMeasurandV3Error(
                "successful artifact cannot carry failure evidence"
            )
    elif failure_evidence is not None:
        if (
            failure_evidence.request_hash != request.request_hash
            or failure_evidence.authorization_hash != request.authorization_hash
            or (
                failure_evidence.case_id,
                failure_evidence.task_id,
                failure_evidence.arm_id,
            )
            != (
                request.case.case_id,
                request.case.task_id,
                request.arm_id,
            )
            or failure_evidence.failure_code is not artifact.failure.code
            or failure_evidence.failure_artifact_hash
            != _canonical_hash(artifact.failure.to_dict())
            or failure_evidence.terminal_reason_is_detection is not False
        ):
            raise AuthoritativeMeasurandV3Error(
                "failure evidence common ancestry is inconsistent"
            )
    return oracle


def _structure_facts(
    *,
    request: FormalArmRequest,
    artifact: FormalArmCaseArtifact,
    failure_evidence: FailureEvidenceV3 | None,
) -> tuple[AuthoritativeFactV3, ...]:
    canonical = artifact.canonical_evaluation
    facts = [
        AuthoritativeFactV3.derived(
            name="request_artifact_ancestry_valid",
            value=True,
            source_kind="typed_request_and_artifact",
            source_hashes=(request.request_hash, artifact.artifact_hash),
            evidence_refs=("formal_arm_request", "formal_arm_case_artifact"),
        ),
        # JudgeCallCostArtifact currently carries only test-only transport
        # membership.  There is no independently injected production
        # transport verifier or trust root in this offline slice, so this
        # authority fact must remain explicitly unavailable even when typed
        # Judge receipts are present on the artifact.
        AuthoritativeFactV3.unavailable("judge_transport_membership_authority_valid"),
        # The legacy formal detector still consumes backend ``detection_signals``;
        # no typed-source replacement has been integrated into that path.  Keep
        # this boundary explicit rather than treating the candidate projection
        # as authority for the legacy claim-bearing API.
        AuthoritativeFactV3.unavailable("legacy_formal_detection_authority_valid"),
        AuthoritativeFactV3.derived(
            name="artifact_denominator_retained",
            value=True,
            source_kind="typed_formal_artifact_denominator",
            source_hashes=(artifact.artifact_hash,),
            evidence_refs=("formal_arm_case_artifact.retained_in_denominator",),
        ),
    ]
    if canonical is None:
        facts.extend(
            (
                AuthoritativeFactV3.unavailable("canonical_measurement_binding_valid"),
                AuthoritativeFactV3.unavailable(
                    "internal_measurement_contract_consistent"
                ),
                AuthoritativeFactV3.unavailable(
                    "sealed_episode_parent_structure_valid"
                ),
            )
        )
    else:
        canonical_hash = _canonical_hash(canonical.to_dict())
        facts.extend(
            (
                AuthoritativeFactV3.derived(
                    name="canonical_measurement_binding_valid",
                    value=True,
                    source_kind="canonical_measurement_binding",
                    source_hashes=(
                        canonical.task_measurement_bundle.bundle_hash,
                        canonical_hash,
                    ),
                    evidence_refs=(
                        "task_measurement_bundle",
                        "canonical_evaluation_binding",
                    ),
                ),
                AuthoritativeFactV3.derived(
                    name="internal_measurement_contract_consistent",
                    value=True,
                    source_kind="canonical_measurement_contract",
                    source_hashes=(
                        _canonical_hash(
                            canonical.task_measurement_bundle.measurement_graph.to_dict()
                        ),
                    ),
                    evidence_refs=(
                        "requirement_graph.schema_version",
                        "measurement_graph.requirement_schema_version",
                    ),
                ),
                AuthoritativeFactV3.derived(
                    name="sealed_episode_parent_structure_valid",
                    value=True,
                    source_kind="sealed_episode_graph",
                    source_hashes=(canonical.sealed_episode.episode_hash,),
                    evidence_refs=(
                        "sealed_episode",
                        "episode_graph.causal_parent_ids",
                    ),
                ),
            )
        )
    facts.append(
        AuthoritativeFactV3.unavailable("failure_evidence_integrity_valid")
        if failure_evidence is None
        else AuthoritativeFactV3.derived(
            name="failure_evidence_integrity_valid",
            value=True,
            source_kind="typed_retained_failure_evidence",
            source_hashes=(failure_evidence.evidence_hash,),
            evidence_refs=(f"failure_evidence:{failure_evidence.failure_code.value}",),
        )
    )
    return tuple(facts)


def _derived_or_unavailable_measurand(
    *,
    name: str,
    artifact: FormalArmCaseArtifact,
    failure_evidence: FailureEvidenceV3 | None,
) -> AuthoritativeFactV3:
    if name == "budget_exhausted":
        if artifact.failure is None:
            return AuthoritativeFactV3.derived(
                name=name,
                value=False,
                source_kind="typed_formal_artifact_disposition",
                source_hashes=(artifact.artifact_hash,),
                evidence_refs=("formal_arm_case_artifact.failure",),
            )
        if failure_evidence is not None:
            return AuthoritativeFactV3.derived(
                name=name,
                value=artifact.failure.code
                in {
                    FailureCode.BUDGET_EXHAUSTED,
                    FailureCode.STAGE_BUDGET_EXHAUSTED,
                },
                source_kind="typed_retained_failure_evidence",
                source_hashes=(failure_evidence.evidence_hash,),
                evidence_refs=(
                    f"failure_evidence:{failure_evidence.failure_code.value}",
                ),
            )
    return AuthoritativeFactV3.unavailable(name)


def derive_simulated_authoritative_measurands(
    *,
    request: FormalArmRequest,
    artifact: FormalArmCaseArtifact,
    oracle_binding: SimulatedFrozenOracleBindingV3,
    failure_evidence: FailureEvidenceV3 | None = None,
) -> SimulatedAuthoritativeMeasurandProjectionV3:
    """Derive only presently closed typed facts; never consume backend signals."""

    oracle = _validate_typed_ancestry(
        request=request,
        artifact=artifact,
        oracle_binding=oracle_binding,
        failure_evidence=failure_evidence,
    )
    entry = oracle.entry(artifact.fault_id)
    structure_facts = _structure_facts(
        request=request,
        artifact=artifact,
        failure_evidence=failure_evidence,
    )
    measurands = tuple(
        _derived_or_unavailable_measurand(
            name=name,
            artifact=artifact,
            failure_evidence=failure_evidence,
        )
        for name in entry.authorized_signal_fields
    )
    body = {
        "schema": AUTHORITY_PROJECTION_SCHEMA_V3,
        "version": 3,
        "claim_scope": CLAIM_SCOPE_V3,
        "test_only": True,
        "production_authorized": False,
        "formal_eligible": False,
        "detection_eligible": False,
        "authority_binding_hash": oracle_binding.binding_hash,
        "request_hash": request.request_hash,
        "artifact_hash": artifact.artifact_hash,
        "oracle_manifest_hash": oracle.contract_hash,
        "oracle_entry_hash": entry.contract_hash,
        "case_id": artifact.case_id,
        "task_id": artifact.task_id,
        "fault_id": artifact.fault_id,
        "arm_id": artifact.arm_id,
        "structure_facts": [item.to_dict() for item in structure_facts],
        "measurands": [item.to_dict() for item in measurands],
    }
    return SimulatedAuthoritativeMeasurandProjectionV3(
        schema=AUTHORITY_PROJECTION_SCHEMA_V3,
        version=3,
        claim_scope=CLAIM_SCOPE_V3,
        test_only=True,
        production_authorized=False,
        formal_eligible=False,
        detection_eligible=False,
        authority_binding_hash=oracle_binding.binding_hash,
        request_hash=request.request_hash,
        artifact_hash=artifact.artifact_hash,
        oracle_manifest_hash=oracle.contract_hash,
        oracle_entry_hash=entry.contract_hash,
        case_id=artifact.case_id,
        task_id=artifact.task_id,
        fault_id=artifact.fault_id,
        arm_id=artifact.arm_id,
        structure_facts=structure_facts,
        measurands=measurands,
        projection_hash=_canonical_hash(body),
        _factory_token=_PROJECTION_TOKEN,
    )


@dataclass(frozen=True)
class RawDetectionSignalsAuditV3:
    """Hash-bound backend self-report that can never act as D11 authority."""

    schema: str
    version: int
    claim_scope: str
    test_only: bool
    production_authorized: bool
    audit_only: bool
    authoritative: bool
    detection_eligible: bool
    formal_eligible: bool
    authority_binding_hash: str
    artifact_hash: str
    oracle_manifest_hash: str
    oracle_entry_hash: str
    case_id: str
    task_id: str
    fault_id: str
    arm_id: str
    candidate_count: int
    raw_projection: tuple[tuple[str, str], ...]
    raw_observation_hashes: tuple[str, ...]
    audit_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _AUDIT_TOKEN:
            raise AuthoritativeMeasurandV3Error(
                "raw detection audit requires artifact capture"
            )
        if (
            self.schema != RAW_DETECTION_AUDIT_SCHEMA_V3
            or self.version != 3
            or self.claim_scope != CLAIM_SCOPE_V3
            or self.test_only is not True
            or self.production_authorized is not False
            or self.audit_only is not True
            or self.authoritative is not False
            or self.detection_eligible is not False
            or self.formal_eligible is not False
        ):
            raise AuthoritativeMeasurandV3Error(
                "raw detection audit crossed its audit-only boundary"
            )
        for value, label in (
            (self.authority_binding_hash, "raw audit authority binding hash"),
            (self.artifact_hash, "raw audit artifact hash"),
            (self.oracle_manifest_hash, "raw audit oracle hash"),
            (self.oracle_entry_hash, "raw audit oracle entry hash"),
            (self.audit_hash, "raw audit hash"),
        ):
            _digest(value, label)
        if (
            isinstance(self.candidate_count, bool)
            or not isinstance(self.candidate_count, int)
            or self.candidate_count < 0
        ):
            raise AuthoritativeMeasurandV3Error("raw audit candidate count is invalid")
        object.__setattr__(self, "raw_projection", tuple(self.raw_projection))
        object.__setattr__(
            self,
            "raw_observation_hashes",
            tuple(self.raw_observation_hashes),
        )
        if (
            self.raw_projection != tuple(sorted(self.raw_projection))
            or len({name for name, _ in self.raw_projection})
            != len(self.raw_projection)
            or len(self.raw_observation_hashes) != self.candidate_count
        ):
            raise AuthoritativeMeasurandV3Error(
                "raw detection audit membership is invalid"
            )
        for name, value_json in self.raw_projection:
            _text(name, "raw signal name")
            try:
                json.loads(value_json)
            except (TypeError, json.JSONDecodeError) as error:
                raise AuthoritativeMeasurandV3Error(
                    "raw signal value is invalid JSON"
                ) from error
        for value in self.raw_observation_hashes:
            _digest(value, "raw observation hash")
        if self.audit_hash != _canonical_hash(self._body()):
            raise AuthoritativeMeasurandV3Error("raw detection audit hash mismatch")

    def _body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "claim_scope": self.claim_scope,
            "test_only": self.test_only,
            "production_authorized": self.production_authorized,
            "audit_only": self.audit_only,
            "authoritative": self.authoritative,
            "detection_eligible": self.detection_eligible,
            "formal_eligible": self.formal_eligible,
            "authority_binding_hash": self.authority_binding_hash,
            "artifact_hash": self.artifact_hash,
            "oracle_manifest_hash": self.oracle_manifest_hash,
            "oracle_entry_hash": self.oracle_entry_hash,
            "case_id": self.case_id,
            "task_id": self.task_id,
            "fault_id": self.fault_id,
            "arm_id": self.arm_id,
            "candidate_count": self.candidate_count,
            "raw_projection": [
                {"name": name, "value_json": value}
                for name, value in self.raw_projection
            ],
            "raw_observation_hashes": list(self.raw_observation_hashes),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "audit_hash": self.audit_hash}

    def to_canonical_bytes(self) -> bytes:
        """Serialize the audit-only projection using strict canonical JSON."""

        return _canonical_bytes(self.to_dict())

    @classmethod
    def restore_from_typed_sources(
        cls,
        value: object,
        *,
        artifact: FormalArmCaseArtifact,
        oracle_binding: SimulatedFrozenOracleBindingV3,
    ) -> RawDetectionSignalsAuditV3:
        restored = capture_raw_detection_signals_audit(
            artifact=artifact,
            oracle_binding=oracle_binding,
        )
        _strict_equal(value, restored.to_dict())
        return restored

    @classmethod
    def restore_from_canonical_bytes(
        cls,
        raw_bytes: bytes,
        *,
        artifact: FormalArmCaseArtifact,
        oracle_binding: SimulatedFrozenOracleBindingV3,
    ) -> RawDetectionSignalsAuditV3:
        """Restore audit bytes only against the original typed artifact."""

        value = _decode_canonical_bytes(raw_bytes)
        if type(value) is not dict:
            raise AuthoritativeMeasurandV3Error(
                "serialized D11 raw audit must be an object"
            )
        return cls.restore_from_typed_sources(
            value,
            artifact=artifact,
            oracle_binding=oracle_binding,
        )


def capture_raw_detection_signals_audit(
    *,
    artifact: FormalArmCaseArtifact,
    oracle_binding: SimulatedFrozenOracleBindingV3,
) -> RawDetectionSignalsAuditV3:
    """Capture backend self-reports without validating or authorizing them."""

    if not isinstance(artifact, FormalArmCaseArtifact):
        raise AuthoritativeMeasurandV3Error(
            "raw audit requires a typed FormalArmCaseArtifact"
        )
    if not isinstance(oracle_binding, SimulatedFrozenOracleBindingV3):
        raise AuthoritativeMeasurandV3Error(
            "raw audit requires a typed frozen oracle binding"
        )
    oracle_binding.__post_init__()
    if (
        oracle_binding.request_hash != artifact.request_hash
        or oracle_binding.authorization_hash != artifact.authorization_hash
    ):
        raise AuthoritativeMeasurandV3Error(
            "raw audit oracle binding is not artifact-bound"
        )
    oracle = oracle_binding.oracle
    entry = oracle.entry(artifact.fault_id)
    candidates: list[Mapping[str, Any]] = []
    observation_hashes: list[str] = []
    for observation in artifact.observations:
        try:
            payload = json.loads(observation.payload_json)
        except (TypeError, json.JSONDecodeError) as error:
            raise AuthoritativeMeasurandV3Error(
                "raw observation payload is malformed"
            ) from error
        if not isinstance(payload, Mapping):
            raise AuthoritativeMeasurandV3Error(
                "raw observation payload must be an object"
            )
        if "detection_signals" not in payload:
            continue
        raw = payload["detection_signals"]
        if not isinstance(raw, Mapping):
            raise AuthoritativeMeasurandV3Error(
                "raw detection_signals must be an object"
            )
        candidates.append(raw)
        observation_hashes.append(_canonical_hash(observation.to_dict()))
    raw_projection: tuple[tuple[str, str], ...] = ()
    if len(candidates) == 1:
        raw_projection = tuple(
            (
                _text(name, "raw signal name"),
                _canonical_bytes(value).decode("utf-8"),
            )
            for name, value in sorted(candidates[0].items())
        )
    body = {
        "schema": RAW_DETECTION_AUDIT_SCHEMA_V3,
        "version": 3,
        "claim_scope": CLAIM_SCOPE_V3,
        "test_only": True,
        "production_authorized": False,
        "audit_only": True,
        "authoritative": False,
        "detection_eligible": False,
        "formal_eligible": False,
        "authority_binding_hash": oracle_binding.binding_hash,
        "artifact_hash": artifact.artifact_hash,
        "oracle_manifest_hash": oracle.contract_hash,
        "oracle_entry_hash": entry.contract_hash,
        "case_id": artifact.case_id,
        "task_id": artifact.task_id,
        "fault_id": artifact.fault_id,
        "arm_id": artifact.arm_id,
        "candidate_count": len(candidates),
        "raw_projection": [
            {"name": name, "value_json": value} for name, value in raw_projection
        ],
        "raw_observation_hashes": observation_hashes,
    }
    return RawDetectionSignalsAuditV3(
        schema=RAW_DETECTION_AUDIT_SCHEMA_V3,
        version=3,
        claim_scope=CLAIM_SCOPE_V3,
        test_only=True,
        production_authorized=False,
        audit_only=True,
        authoritative=False,
        detection_eligible=False,
        formal_eligible=False,
        authority_binding_hash=oracle_binding.binding_hash,
        artifact_hash=artifact.artifact_hash,
        oracle_manifest_hash=oracle.contract_hash,
        oracle_entry_hash=entry.contract_hash,
        case_id=artifact.case_id,
        task_id=artifact.task_id,
        fault_id=artifact.fault_id,
        arm_id=artifact.arm_id,
        candidate_count=len(candidates),
        raw_projection=raw_projection,
        raw_observation_hashes=tuple(observation_hashes),
        audit_hash=_canonical_hash(body),
        _factory_token=_AUDIT_TOKEN,
    )


__all__ = [
    "AUTHORITY_PROJECTION_SCHEMA_V3",
    "CLAIM_SCOPE_V3",
    "ORACLE_BINDING_SCHEMA_V3",
    "RAW_DETECTION_AUDIT_SCHEMA_V3",
    "AuthoritativeFactV3",
    "AuthoritativeMeasurandV3Error",
    "MeasurandAvailabilityV3",
    "RawDetectionSignalsAuditV3",
    "SimulatedAuthoritativeMeasurandProjectionV3",
    "SimulatedFrozenOracleBindingV3",
    "capture_raw_detection_signals_audit",
    "derive_simulated_authoritative_measurands",
]
