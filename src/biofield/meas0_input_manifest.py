"""Typed, content-addressed MEAS0 protected input manifests.

This module binds Pilot and confirmatory case identities to the measurement,
episode, failure-policy, and native-adapter inputs from which runner values must
later be derived.  It deliberately does not authorize execution or construct a
``FormalPilotPlan``.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from .measurement import (
    EvaluationStatus,
    MeasurementDimension,
    SealedEpisode,
    TaskMeasurementBundle,
    validate_sealed_episode,
    validate_task_measurement_bundle,
)
from .meas0_formal_lifecycle import PhaseCheckpointTarget
from .meas0_formal_metrics import FormalCaseIdentity, formal_attack_manifest
from .meas0_formal_runner import FailureCode, ResultValidity
from .meas0_phase_readiness import PhaseReadinessReceipt, PhaseReadinessStage
from .meas0_readiness import FormalCaseScopeManifest
from .meas0_trust import AuthorizationCheckpoint


FAILURE_POLICY_SCHEMA = "meas0.failure-policy.v1"
NATIVE_ADAPTER_ARTIFACT_SCHEMA = "meas0.native-adapter-artifact.v1"
PROTECTED_INPUT_CORPUS_SCHEMA = "meas0.protected-input-corpus.v1"
INPUT_MANIFEST_SCHEMA = "meas0.input-manifest.v1"


class InputManifestError(ValueError):
    """Raised when protected input ancestry is incomplete or inconsistent."""


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise InputManifestError(
            "input manifest value is not canonical JSON"
        ) from error


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _bytes_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputManifestError(f"{label} must be a non-empty string")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InputManifestError(f"{label} must be a positive integer")
    return value


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InputManifestError(f"{label} must be a non-negative integer")
    return value


def _digest(value: object, label: str) -> str:
    text = _text(value, label)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise InputManifestError(f"{label} must be a lowercase SHA-256 digest")
    return text


def _strict_mapping(
    value: object,
    *,
    fields: set[str],
    label: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise InputManifestError(f"{label} must contain the exact schema fields")
    return value


@dataclass(frozen=True)
class FailureDisposition:
    failure_code: FailureCode
    result_validity: ResultValidity
    automatic_status: EvaluationStatus | None
    retained_in_denominator: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.failure_code, FailureCode)
            or not isinstance(self.result_validity, ResultValidity)
            or self.retained_in_denominator is not True
        ):
            raise InputManifestError("failure disposition is invalid")
        if self.result_validity is ResultValidity.VALID:
            if self.automatic_status is not EvaluationStatus.UNKNOWN:
                raise InputManifestError(
                    "unavailable failure disposition must project to UNKNOWN"
                )
        elif self.automatic_status is not None:
            raise InputManifestError(
                "integrity failure disposition must have null automatic status"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "failure_code": self.failure_code.value,
            "result_validity": self.result_validity.value,
            "automatic_status": (
                self.automatic_status.value
                if self.automatic_status is not None
                else None
            ),
            "retained_in_denominator": self.retained_in_denominator,
        }


_FROZEN_FAILURE_DISPOSITIONS = (
    FailureDisposition(
        FailureCode.TIMEOUT,
        ResultValidity.VALID,
        EvaluationStatus.UNKNOWN,
        True,
    ),
    FailureDisposition(
        FailureCode.PROVIDER_ERROR,
        ResultValidity.VALID,
        EvaluationStatus.UNKNOWN,
        True,
    ),
    FailureDisposition(
        FailureCode.MALFORMED_RESPONSE,
        ResultValidity.VALID,
        EvaluationStatus.UNKNOWN,
        True,
    ),
    FailureDisposition(
        FailureCode.BACKEND_INVALID,
        ResultValidity.INVALID,
        None,
        True,
    ),
    FailureDisposition(
        FailureCode.BUDGET_EXHAUSTED,
        ResultValidity.VALID,
        EvaluationStatus.UNKNOWN,
        True,
    ),
    FailureDisposition(
        FailureCode.STAGE_BUDGET_EXHAUSTED,
        ResultValidity.VALID,
        EvaluationStatus.UNKNOWN,
        True,
    ),
    FailureDisposition(
        FailureCode.PROTOCOL_VIOLATION,
        ResultValidity.INVALID,
        None,
        True,
    ),
)
_FAILURE_POLICY_TOKEN = object()


@dataclass(frozen=True)
class FailurePolicyContract:
    schema: str
    dispositions: tuple[FailureDisposition, ...]
    contract_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "dispositions", tuple(self.dispositions))
        if (
            self._factory_token is not _FAILURE_POLICY_TOKEN
            or self.schema != FAILURE_POLICY_SCHEMA
            or self.dispositions != _FROZEN_FAILURE_DISPOSITIONS
        ):
            raise InputManifestError("failure policy must be the frozen V1 mapping")
        _digest(self.contract_hash, "failure policy hash")
        if self.contract_hash != _canonical_hash(self._body()):
            raise InputManifestError("failure policy hash mismatch")

    def _body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "dispositions": [item.to_dict() for item in self.dispositions],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "contract_hash": self.contract_hash}

    @classmethod
    def frozen_v1(cls) -> FailurePolicyContract:
        body = {
            "schema": FAILURE_POLICY_SCHEMA,
            "dispositions": [item.to_dict() for item in _FROZEN_FAILURE_DISPOSITIONS],
        }
        return cls(
            schema=FAILURE_POLICY_SCHEMA,
            dispositions=_FROZEN_FAILURE_DISPOSITIONS,
            contract_hash=_canonical_hash(body),
            _factory_token=_FAILURE_POLICY_TOKEN,
        )

    @classmethod
    def from_dict(cls, value: object) -> FailurePolicyContract:
        raw = _strict_mapping(
            value,
            fields={"schema", "dispositions", "contract_hash"},
            label="failure policy",
        )
        expected = cls.frozen_v1()
        if dict(raw) != expected.to_dict():
            raise InputManifestError("serialized failure policy is not frozen V1")
        return expected


_NATIVE_ADAPTER_TOKEN = object()


@dataclass(frozen=True)
class NativeAdapterArtifact:
    schema: str
    task_id: str
    adapter_id: str
    adapter_version: str
    source_path: str
    source_bytes: bytes
    source_sha256: str
    artifact_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _NATIVE_ADAPTER_TOKEN:
            raise InputManifestError("native adapter must come from exact source bytes")
        if self.schema != NATIVE_ADAPTER_ARTIFACT_SCHEMA:
            raise InputManifestError("native adapter schema is invalid")
        for name in ("task_id", "adapter_id", "adapter_version", "source_path"):
            _text(getattr(self, name), f"native adapter {name}")
        path = PurePosixPath(self.source_path)
        if path.is_absolute() or ".." in path.parts or str(path) != self.source_path:
            raise InputManifestError("native adapter source_path must be normalized")
        if not isinstance(self.source_bytes, bytes) or not self.source_bytes:
            raise InputManifestError(
                "native adapter source_bytes must be non-empty bytes"
            )
        _digest(self.source_sha256, "native adapter source hash")
        _digest(self.artifact_hash, "native adapter artifact hash")
        if self.source_sha256 != _bytes_hash(self.source_bytes):
            raise InputManifestError("native adapter source bytes changed")
        if self.artifact_hash != _canonical_hash(self._body()):
            raise InputManifestError("native adapter artifact hash mismatch")

    def _body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "source_path": self.source_path,
            "source_base64": base64.b64encode(self.source_bytes).decode("ascii"),
            "source_sha256": self.source_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "artifact_hash": self.artifact_hash}

    @classmethod
    def from_source_bytes(
        cls,
        *,
        task_id: str,
        adapter_id: str,
        adapter_version: str,
        source_path: str,
        source_bytes: bytes,
    ) -> NativeAdapterArtifact:
        source_hash = (
            _bytes_hash(source_bytes) if isinstance(source_bytes, bytes) else ""
        )
        body = {
            "schema": NATIVE_ADAPTER_ARTIFACT_SCHEMA,
            "task_id": task_id,
            "adapter_id": adapter_id,
            "adapter_version": adapter_version,
            "source_path": source_path,
            "source_base64": (
                base64.b64encode(source_bytes).decode("ascii")
                if isinstance(source_bytes, bytes)
                else ""
            ),
            "source_sha256": source_hash,
        }
        return cls(
            schema=NATIVE_ADAPTER_ARTIFACT_SCHEMA,
            task_id=task_id,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            source_path=source_path,
            source_bytes=source_bytes,
            source_sha256=source_hash,
            artifact_hash=_canonical_hash(body),
            _factory_token=_NATIVE_ADAPTER_TOKEN,
        )

    @classmethod
    def from_dict(cls, value: object) -> NativeAdapterArtifact:
        raw = _strict_mapping(
            value,
            fields={
                "schema",
                "task_id",
                "adapter_id",
                "adapter_version",
                "source_path",
                "source_base64",
                "source_sha256",
                "artifact_hash",
            },
            label="native adapter artifact",
        )
        try:
            source_bytes = base64.b64decode(raw["source_base64"], validate=True)
        except (TypeError, ValueError) as error:
            raise InputManifestError(
                "native adapter source_base64 is invalid"
            ) from error
        restored = cls.from_source_bytes(
            task_id=raw["task_id"],
            adapter_id=raw["adapter_id"],
            adapter_version=raw["adapter_version"],
            source_path=raw["source_path"],
            source_bytes=source_bytes,
        )
        if dict(raw) != restored.to_dict():
            raise InputManifestError("serialized native adapter disagrees with bytes")
        return restored


_PROTECTED_INPUT_TOKEN = object()


@dataclass(frozen=True)
class ProtectedCaseInput:
    case: FormalCaseIdentity
    task_measurement_bundle: TaskMeasurementBundle
    sealed_episode: SealedEpisode
    failure_policy: FailurePolicyContract
    native_adapter: NativeAdapterArtifact
    protected_input_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _PROTECTED_INPUT_TOKEN:
            raise InputManifestError("protected case input must be factory-derived")
        if not isinstance(self.case, FormalCaseIdentity):
            raise InputManifestError("protected input case identity is invalid")
        if not isinstance(self.task_measurement_bundle, TaskMeasurementBundle):
            raise InputManifestError("protected input requires TaskMeasurementBundle")
        if not isinstance(self.sealed_episode, SealedEpisode):
            raise InputManifestError("protected input requires SealedEpisode")
        if not isinstance(self.failure_policy, FailurePolicyContract):
            raise InputManifestError("protected input requires FailurePolicyContract")
        if not isinstance(self.native_adapter, NativeAdapterArtifact):
            raise InputManifestError("protected input requires NativeAdapterArtifact")
        validate_task_measurement_bundle(self.task_measurement_bundle)
        validate_sealed_episode(
            self.sealed_episode,
            task_measurement_bundle=self.task_measurement_bundle,
        )
        if (
            self.task_measurement_bundle.task_frame.task_id != self.case.task_id
            or self.sealed_episode.episode_graph.task_id != self.case.task_id
            or self.sealed_episode.episode_graph.episode_id != self.case.case_id
            or self.native_adapter.task_id != self.case.task_id
        ):
            raise InputManifestError("protected input case ancestry is inconsistent")
        _digest(self.protected_input_hash, "protected input hash")
        if self.protected_input_hash != _canonical_hash(self._body()):
            raise InputManifestError("protected input hash mismatch")

    @property
    def task_bundle_hash(self) -> str:
        return self.task_measurement_bundle.bundle_hash

    @property
    def episode_hash(self) -> str:
        return self.sealed_episode.episode_hash

    @property
    def failure_policy_hash(self) -> str:
        return self.failure_policy.contract_hash

    @property
    def semantic_leaf_count(self) -> int:
        return sum(
            requirement.dimension is MeasurementDimension.SEMANTIC
            for requirement in self.task_measurement_bundle.requirement_graph.requirements
        )

    @property
    def measurement_count(self) -> int:
        return len(self.task_measurement_bundle.measurement_graph.measurement_specs)

    def _body(self) -> dict[str, object]:
        return {
            "case": self.case.to_dict(),
            "task_bundle_hash": self.task_bundle_hash,
            "episode_hash": self.episode_hash,
            "failure_policy_hash": self.failure_policy_hash,
            "semantic_leaf_count": self.semantic_leaf_count,
            "measurement_count": self.measurement_count,
            "native_adapter_artifact_hash": self.native_adapter.artifact_hash,
        }

    @classmethod
    def create(
        cls,
        *,
        case: FormalCaseIdentity,
        task_measurement_bundle: TaskMeasurementBundle,
        sealed_episode: SealedEpisode,
        failure_policy: FailurePolicyContract,
        native_adapter: NativeAdapterArtifact,
    ) -> ProtectedCaseInput:
        if not isinstance(task_measurement_bundle, TaskMeasurementBundle):
            raise InputManifestError("protected input requires TaskMeasurementBundle")
        body = {
            "case": case.to_dict() if isinstance(case, FormalCaseIdentity) else None,
            "task_bundle_hash": task_measurement_bundle.bundle_hash,
            "episode_hash": (
                sealed_episode.episode_hash
                if isinstance(sealed_episode, SealedEpisode)
                else None
            ),
            "failure_policy_hash": (
                failure_policy.contract_hash
                if isinstance(failure_policy, FailurePolicyContract)
                else None
            ),
            "semantic_leaf_count": sum(
                requirement.dimension is MeasurementDimension.SEMANTIC
                for requirement in task_measurement_bundle.requirement_graph.requirements
            ),
            "measurement_count": len(
                task_measurement_bundle.measurement_graph.measurement_specs
            ),
            "native_adapter_artifact_hash": (
                native_adapter.artifact_hash
                if isinstance(native_adapter, NativeAdapterArtifact)
                else None
            ),
        }
        return cls(
            case=case,
            task_measurement_bundle=task_measurement_bundle,
            sealed_episode=sealed_episode,
            failure_policy=failure_policy,
            native_adapter=native_adapter,
            protected_input_hash=_canonical_hash(body),
            _factory_token=_PROTECTED_INPUT_TOKEN,
        )


def _corpus_hash(
    phase: str,
    protected_input_hashes: Sequence[str],
) -> str:
    return _canonical_hash(
        {
            "schema": PROTECTED_INPUT_CORPUS_SCHEMA,
            "phase": phase,
            "protected_input_hashes": list(protected_input_hashes),
        }
    )


_CORPUS_TOKEN = object()


@dataclass(frozen=True)
class ProtectedInputCorpus:
    schema: str
    phase: str
    case_inputs: tuple[ProtectedCaseInput, ...]
    corpus_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_inputs", tuple(self.case_inputs))
        if (
            self._factory_token is not _CORPUS_TOKEN
            or self.schema != PROTECTED_INPUT_CORPUS_SCHEMA
        ):
            raise InputManifestError("protected corpus must be factory-derived")
        try:
            expected_cases = formal_attack_manifest(self.phase).cases
        except ValueError as error:
            raise InputManifestError("protected corpus phase is invalid") from error
        if (
            not all(isinstance(item, ProtectedCaseInput) for item in self.case_inputs)
            or tuple(item.case for item in self.case_inputs) != expected_cases
        ):
            raise InputManifestError(
                "protected corpus membership/order differs from frozen manifest"
            )
        _digest(self.corpus_hash, "protected corpus hash")
        expected_hash = _corpus_hash(
            self.phase,
            tuple(item.protected_input_hash for item in self.case_inputs),
        )
        if self.corpus_hash != expected_hash:
            raise InputManifestError("protected corpus hash mismatch")

    @classmethod
    def create(
        cls,
        *,
        phase: str,
        case_inputs: Sequence[ProtectedCaseInput],
    ) -> ProtectedInputCorpus:
        values = tuple(case_inputs)
        if not all(isinstance(item, ProtectedCaseInput) for item in values):
            raise InputManifestError(
                "protected corpus requires ProtectedCaseInput values"
            )
        return cls(
            schema=PROTECTED_INPUT_CORPUS_SCHEMA,
            phase=phase,
            case_inputs=values,
            corpus_hash=_corpus_hash(
                phase,
                tuple(item.protected_input_hash for item in values),
            ),
            _factory_token=_CORPUS_TOKEN,
        )


_ENTRY_TOKEN = object()


@dataclass(frozen=True)
class InputManifestEntry:
    phase: str
    case_index: int
    case_id: str
    task_id: str
    fault_id: str
    mutation_seed: int
    task_bundle_id: str
    task_bundle_version: int
    task_bundle_hash: str
    episode_id: str
    episode_version: int
    episode_hash: str
    failure_policy_hash: str
    semantic_leaf_count: int
    measurement_count: int
    adapter_id: str
    adapter_version: str
    adapter_source_sha256: str
    adapter_artifact_hash: str
    protected_input_hash: str
    entry_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _ENTRY_TOKEN:
            raise InputManifestError("input manifest entry must be factory-derived")
        expected_cases = formal_attack_manifest(self.phase).cases
        _non_negative_int(self.case_index, "case index")
        if self.case_index >= len(expected_cases):
            raise InputManifestError("case index is outside frozen manifest")
        expected = expected_cases[self.case_index]
        if (
            self.case_id,
            self.task_id,
            self.fault_id,
            self.mutation_seed,
        ) != (
            expected.case_id,
            expected.task_id,
            expected.fault_id,
            expected.mutation_seed,
        ):
            raise InputManifestError("manifest entry case identity is inconsistent")
        for name in (
            "task_bundle_id",
            "adapter_id",
            "adapter_version",
            "episode_id",
        ):
            _text(getattr(self, name), f"manifest entry {name}")
        for name in (
            "task_bundle_hash",
            "episode_hash",
            "failure_policy_hash",
            "adapter_source_sha256",
            "adapter_artifact_hash",
            "protected_input_hash",
            "entry_hash",
        ):
            _digest(getattr(self, name), f"manifest entry {name}")
        _positive_int(self.task_bundle_version, "task bundle version")
        _positive_int(self.episode_version, "episode version")
        _non_negative_int(self.semantic_leaf_count, "semantic leaf count")
        _positive_int(self.measurement_count, "measurement count")
        if self.episode_id != self.case_id:
            raise InputManifestError("manifest episode is not case-bound")
        if self.entry_hash != _canonical_hash(self._body()):
            raise InputManifestError("manifest entry hash mismatch")

    def _body(self) -> dict[str, object]:
        return {
            name: getattr(self, name)
            for name in (
                "phase",
                "case_index",
                "case_id",
                "task_id",
                "fault_id",
                "mutation_seed",
                "task_bundle_id",
                "task_bundle_version",
                "task_bundle_hash",
                "episode_id",
                "episode_version",
                "episode_hash",
                "failure_policy_hash",
                "semantic_leaf_count",
                "measurement_count",
                "adapter_id",
                "adapter_version",
                "adapter_source_sha256",
                "adapter_artifact_hash",
                "protected_input_hash",
            )
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "entry_hash": self.entry_hash}

    @classmethod
    def from_protected_input(
        cls,
        *,
        case_index: int,
        protected_input: ProtectedCaseInput,
    ) -> InputManifestEntry:
        if not isinstance(protected_input, ProtectedCaseInput):
            raise InputManifestError("manifest entry requires ProtectedCaseInput")
        case = protected_input.case
        bundle = protected_input.task_measurement_bundle
        episode = protected_input.sealed_episode.episode_graph
        adapter = protected_input.native_adapter
        body = {
            "phase": case.phase,
            "case_index": case_index,
            "case_id": case.case_id,
            "task_id": case.task_id,
            "fault_id": case.fault_id,
            "mutation_seed": case.mutation_seed,
            "task_bundle_id": bundle.bundle_id,
            "task_bundle_version": bundle.version,
            "task_bundle_hash": protected_input.task_bundle_hash,
            "episode_id": episode.episode_id,
            "episode_version": episode.version,
            "episode_hash": protected_input.episode_hash,
            "failure_policy_hash": protected_input.failure_policy_hash,
            "semantic_leaf_count": protected_input.semantic_leaf_count,
            "measurement_count": protected_input.measurement_count,
            "adapter_id": adapter.adapter_id,
            "adapter_version": adapter.adapter_version,
            "adapter_source_sha256": adapter.source_sha256,
            "adapter_artifact_hash": adapter.artifact_hash,
            "protected_input_hash": protected_input.protected_input_hash,
        }
        return cls(
            **body,
            entry_hash=_canonical_hash(body),
            _factory_token=_ENTRY_TOKEN,
        )

    @classmethod
    def from_dict(cls, value: object) -> InputManifestEntry:
        body_fields = {
            "phase",
            "case_index",
            "case_id",
            "task_id",
            "fault_id",
            "mutation_seed",
            "task_bundle_id",
            "task_bundle_version",
            "task_bundle_hash",
            "episode_id",
            "episode_version",
            "episode_hash",
            "failure_policy_hash",
            "semantic_leaf_count",
            "measurement_count",
            "adapter_id",
            "adapter_version",
            "adapter_source_sha256",
            "adapter_artifact_hash",
            "protected_input_hash",
        }
        raw = _strict_mapping(
            value,
            fields={*body_fields, "entry_hash"},
            label="input manifest entry",
        )
        return cls(
            **{name: raw[name] for name in body_fields},
            entry_hash=raw["entry_hash"],
            _factory_token=_ENTRY_TOKEN,
        )


_MANIFEST_TOKEN = object()


@dataclass(frozen=True)
class InputManifest:
    schema: str
    phase: str
    entries: tuple[InputManifestEntry, ...]
    protected_corpus_hash: str
    case_scope_manifest_hash: str
    readiness_parent_receipt_hash: str
    readiness_parent_target_hash: str
    lifecycle_id: str
    comparison_block_id: str
    authority_role_id: str
    design_hash: str
    source_lock_hash: str
    common_ancestry_hash: str
    manifest_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(self.entries))
        if (
            self._factory_token is not _MANIFEST_TOKEN
            or self.schema != INPUT_MANIFEST_SCHEMA
            or self.phase != "pilot"
        ):
            raise InputManifestError("input manifest must be factory-derived")
        expected_cases = formal_attack_manifest(self.phase).cases
        if (
            not all(isinstance(item, InputManifestEntry) for item in self.entries)
            or tuple(item.phase for item in self.entries)
            != (self.phase,) * len(expected_cases)
            or tuple(item.case_index for item in self.entries)
            != tuple(range(len(expected_cases)))
            or tuple(item.case_id for item in self.entries)
            != tuple(item.case_id for item in expected_cases)
        ):
            raise InputManifestError(
                "input manifest membership/order differs from frozen manifest"
            )
        _digest(self.protected_corpus_hash, "protected corpus hash")
        for name in (
            "case_scope_manifest_hash",
            "readiness_parent_receipt_hash",
            "readiness_parent_target_hash",
            "design_hash",
            "source_lock_hash",
            "common_ancestry_hash",
        ):
            _digest(getattr(self, name), f"input manifest {name}")
        for name in (
            "lifecycle_id",
            "comparison_block_id",
            "authority_role_id",
        ):
            _text(getattr(self, name), f"input manifest {name}")
        _digest(self.manifest_hash, "input manifest hash")
        if self.protected_corpus_hash != _corpus_hash(
            self.phase,
            tuple(item.protected_input_hash for item in self.entries),
        ):
            raise InputManifestError("manifest protected corpus hash mismatch")
        if self.manifest_hash != _canonical_hash(self._body()):
            raise InputManifestError("input manifest hash mismatch")

    def _body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "phase": self.phase,
            "entries": [item.to_dict() for item in self.entries],
            "protected_corpus_hash": self.protected_corpus_hash,
            "case_scope_manifest_hash": self.case_scope_manifest_hash,
            "readiness_parent_receipt_hash": self.readiness_parent_receipt_hash,
            "readiness_parent_target_hash": self.readiness_parent_target_hash,
            "lifecycle_id": self.lifecycle_id,
            "comparison_block_id": self.comparison_block_id,
            "authority_role_id": self.authority_role_id,
            "design_hash": self.design_hash,
            "source_lock_hash": self.source_lock_hash,
            "common_ancestry_hash": self.common_ancestry_hash,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "manifest_hash": self.manifest_hash}

    @staticmethod
    def entry_from_protected_input(
        *,
        case_index: int,
        protected_input: ProtectedCaseInput,
    ) -> InputManifestEntry:
        return InputManifestEntry.from_protected_input(
            case_index=case_index,
            protected_input=protected_input,
        )

    @classmethod
    def create(
        cls,
        *,
        corpus: ProtectedInputCorpus,
        case_scope_manifest: FormalCaseScopeManifest,
        readiness_parent: PhaseReadinessReceipt,
    ) -> InputManifest:
        if not isinstance(corpus, ProtectedInputCorpus):
            raise InputManifestError("input manifest requires ProtectedInputCorpus")
        if corpus.phase != "pilot":
            raise InputManifestError(
                "PRE_JCAL ancestry can only derive a Pilot input manifest"
            )
        if not isinstance(case_scope_manifest, FormalCaseScopeManifest):
            raise InputManifestError(
                "input manifest requires typed FormalCaseScopeManifest"
            )
        if not case_scope_manifest.all_native or case_scope_manifest.case_ids != tuple(
            item.case.case_id for item in corpus.case_inputs
        ):
            raise InputManifestError(
                "input manifest case scope does not match protected corpus"
            )
        if (
            not isinstance(readiness_parent, PhaseReadinessReceipt)
            or readiness_parent.stage is not PhaseReadinessStage.PRE_JCAL_READY
            or readiness_parent.target.checkpoint
            is not AuthorizationCheckpoint.PRE_JCAL
        ):
            raise InputManifestError(
                "input manifest requires a PRE_JCAL_READY typed parent"
            )
        target = readiness_parent.target
        entries = tuple(
            cls.entry_from_protected_input(
                case_index=index,
                protected_input=item,
            )
            for index, item in enumerate(corpus.case_inputs)
        )
        body = {
            "schema": INPUT_MANIFEST_SCHEMA,
            "phase": corpus.phase,
            "entries": [item.to_dict() for item in entries],
            "protected_corpus_hash": corpus.corpus_hash,
            "case_scope_manifest_hash": case_scope_manifest.contract_hash,
            "readiness_parent_receipt_hash": readiness_parent.receipt_hash,
            "readiness_parent_target_hash": target.target_hash,
            "lifecycle_id": target.lifecycle_id,
            "comparison_block_id": target.comparison_block_id,
            "authority_role_id": target.authority_role_id,
            "design_hash": target.design_hash,
            "source_lock_hash": target.source_lock_hash,
            "common_ancestry_hash": target.common_ancestry_hash,
        }
        return cls(
            schema=INPUT_MANIFEST_SCHEMA,
            phase=corpus.phase,
            entries=entries,
            protected_corpus_hash=corpus.corpus_hash,
            case_scope_manifest_hash=case_scope_manifest.contract_hash,
            readiness_parent_receipt_hash=readiness_parent.receipt_hash,
            readiness_parent_target_hash=target.target_hash,
            lifecycle_id=target.lifecycle_id,
            comparison_block_id=target.comparison_block_id,
            authority_role_id=target.authority_role_id,
            design_hash=target.design_hash,
            source_lock_hash=target.source_lock_hash,
            common_ancestry_hash=target.common_ancestry_hash,
            manifest_hash=_canonical_hash(body),
            _factory_token=_MANIFEST_TOKEN,
        )

    @classmethod
    def from_dict(
        cls,
        value: object,
        *,
        corpus: ProtectedInputCorpus,
        case_scope_manifest: FormalCaseScopeManifest,
        readiness_parent: PhaseReadinessReceipt,
    ) -> InputManifest:
        raw = _strict_mapping(
            value,
            fields={
                "schema",
                "phase",
                "entries",
                "protected_corpus_hash",
                "case_scope_manifest_hash",
                "readiness_parent_receipt_hash",
                "readiness_parent_target_hash",
                "lifecycle_id",
                "comparison_block_id",
                "authority_role_id",
                "design_hash",
                "source_lock_hash",
                "common_ancestry_hash",
                "manifest_hash",
            },
            label="input manifest",
        )
        try:
            entries = tuple(
                InputManifestEntry.from_dict(item) for item in raw["entries"]
            )
        except TypeError as error:
            raise InputManifestError(
                "input manifest entries must be a sequence"
            ) from error
        restored = cls.create(
            corpus=corpus,
            case_scope_manifest=case_scope_manifest,
            readiness_parent=readiness_parent,
        )
        if entries != restored.entries or dict(raw) != restored.to_dict():
            raise InputManifestError(
                "serialized input manifest disagrees with typed ancestry"
            )
        return restored

    def validate_pilot_ready_target(
        self,
        target: PhaseCheckpointTarget,
    ) -> bool:
        if (
            not isinstance(target, PhaseCheckpointTarget)
            or target.checkpoint is not AuthorizationCheckpoint.PILOT_START
            or target.previous_target_hash != self.readiness_parent_target_hash
            or (
                target.lifecycle_id,
                target.comparison_block_id,
                target.authority_role_id,
                target.design_hash,
                target.source_lock_hash,
                target.common_ancestry_hash,
            )
            != (
                self.lifecycle_id,
                self.comparison_block_id,
                self.authority_role_id,
                self.design_hash,
                self.source_lock_hash,
                self.common_ancestry_hash,
            )
            or dict(target.evidence_bindings).get("pilot_input_manifest")
            != self.manifest_hash
        ):
            raise InputManifestError(
                "PILOT_READY target does not bind this input manifest ancestry"
            )
        return True


__all__ = [
    "FAILURE_POLICY_SCHEMA",
    "INPUT_MANIFEST_SCHEMA",
    "NATIVE_ADAPTER_ARTIFACT_SCHEMA",
    "PROTECTED_INPUT_CORPUS_SCHEMA",
    "FailureDisposition",
    "FailurePolicyContract",
    "InputManifest",
    "InputManifestEntry",
    "InputManifestError",
    "NativeAdapterArtifact",
    "ProtectedCaseInput",
    "ProtectedInputCorpus",
]
