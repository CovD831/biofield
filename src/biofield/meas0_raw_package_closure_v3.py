"""Typed, non-authoritative public-file slice for MEAS0 V3.

The slice is built only from existing strict typed objects.  It is not the
complete B8a raw closure, has no source-restoration or verifier authority, and
cannot be used as a fresh-replay or formal-evidence seal.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .meas0_input_manifest import InputManifest
from .meas0_phase_readiness import PhaseReadinessReceipt, PhaseReadinessStage
from .meas0_pilot_plan_v3 import SimulatedPilotPlanCandidate
from .meas0_protected_vault import (
    ProtectedEvidenceReference,
    ProtectedVaultManifest,
)
from .meas0_source_lock_v3 import SealedSourceLockBytes


class RawPackageClosureError(ValueError):
    """Typed public-slice bytes or ancestry failed closed."""


PUBLIC_PILOT_SLICE_FILES = (
    "phase/pre_jcal_readiness.json",
    "phase/pilot_readiness.json",
    "source/source_lock.json",
    "input/pilot_manifest.json",
    "plan/pilot_candidate.json",
    "protected/vault_manifest.json",
    "protected/vault_refs.json",
)
_ARTIFACT_TOKEN = object()
_CLOSURE_TOKEN = object()
_MISSING_AUTHORITIES = (
    "complete_public_and_protected_raw_closure",
    "source_restoration_artifact",
    "transport_verifier",
    "human_signature_verifier",
    "authority_bound_package_seal",
)


def _canonical_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise RawPackageClosureError(
            "public slice value is not canonical JSON"
        ) from error


def _decode_canonical_bytes(raw_bytes: bytes) -> Mapping[str, Any]:
    """Decode one strict canonical JSON object without accepting aliases."""

    if type(raw_bytes) is not bytes:
        raise RawPackageClosureError(
            "serialized public slice must be supplied as exact bytes"
        )
    duplicate = False

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        nonlocal duplicate
        result: dict[str, Any] = {}
        for key, item in items:
            if key in result:
                duplicate = True
            result[key] = item
        return result

    try:
        value = json.loads(
            raw_bytes.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON token {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise RawPackageClosureError(
            "serialized public slice is not strict canonical JSON"
        ) from error
    if duplicate or _canonical_bytes(value) != raw_bytes:
        raise RawPackageClosureError(
            "serialized public slice is not canonical or contains duplicate fields"
        )
    if not isinstance(value, dict):
        raise RawPackageClosureError("serialized public slice must be an object")
    return value


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _bytes_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RawPackageClosureError(f"{label} must be a lowercase SHA-256")
    return value


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


def _strict_mapping(
    value: object,
    *,
    fields: set[str],
    label: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise RawPackageClosureError(f"{label} fields are invalid")
    return value


@dataclass(frozen=True)
class SimulatedPublicArtifact:
    """One canonical public file derived internally from a typed source."""

    relative_path: str
    raw_bytes: bytes = field(repr=False)
    content_sha256: str
    byte_count: int
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._factory_token is not _ARTIFACT_TOKEN
            or self.relative_path not in PUBLIC_PILOT_SLICE_FILES
            or type(self.raw_bytes) is not bytes
            or self.content_sha256 != _bytes_hash(self.raw_bytes)
            or type(self.byte_count) is not int
            or isinstance(self.byte_count, bool)
            or self.byte_count != len(self.raw_bytes)
        ):
            raise RawPackageClosureError(
                "public artifact must be derived from one exact typed source"
            )

    @classmethod
    def _from_typed_bytes(
        cls,
        *,
        relative_path: str,
        raw_bytes: bytes,
    ) -> SimulatedPublicArtifact:
        return cls(
            relative_path=relative_path,
            raw_bytes=raw_bytes,
            content_sha256=_bytes_hash(raw_bytes),
            byte_count=len(raw_bytes),
            _factory_token=_ARTIFACT_TOKEN,
        )

    def to_index_entry(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "content_sha256": self.content_sha256,
            "byte_count": self.byte_count,
        }


def _validate_typed_sources(
    *,
    pilot_candidate: SimulatedPilotPlanCandidate,
    protected_vault_manifest: ProtectedVaultManifest,
    protected_references: Sequence[ProtectedEvidenceReference],
) -> tuple[
    SimulatedPilotPlanCandidate,
    ProtectedVaultManifest,
    tuple[ProtectedEvidenceReference, ...],
]:
    if not isinstance(pilot_candidate, SimulatedPilotPlanCandidate):
        raise RawPackageClosureError("typed simulated Pilot candidate is required")
    try:
        pilot_candidate.__post_init__()
    except ValueError as error:
        raise RawPackageClosureError(
            "Pilot candidate typed ancestry is invalid"
        ) from error
    if (
        pilot_candidate.claim_scope != "simulated_nonclaim"
        or pilot_candidate.production_authorized is not False
        or pilot_candidate.test_only is not True
    ):
        raise RawPackageClosureError("Pilot candidate claim boundary is invalid")
    pre = pilot_candidate.pre_jcal_readiness
    pilot = pilot_candidate.pilot_readiness
    if (
        PhaseReadinessReceipt.from_dict(pre.to_dict()) != pre
        or PhaseReadinessReceipt.from_dict(pilot.to_dict()) != pilot
        or pre.stage is not PhaseReadinessStage.PRE_JCAL_READY
        or pilot.stage is not PhaseReadinessStage.PILOT_READY
    ):
        raise RawPackageClosureError("Pilot readiness typed codec is invalid")
    source_lock = pilot_candidate.source_lock
    if not isinstance(source_lock, SealedSourceLockBytes):
        raise RawPackageClosureError("typed source-lock bytes are required")
    if not isinstance(pilot_candidate.input_manifest, InputManifest):
        raise RawPackageClosureError("typed Pilot input manifest is required")
    try:
        pilot_candidate.input_manifest.__post_init__()
    except ValueError as error:
        raise RawPackageClosureError(
            "Pilot input manifest typed ancestry is invalid"
        ) from error
    if not isinstance(protected_vault_manifest, ProtectedVaultManifest):
        raise RawPackageClosureError("typed protected-vault manifest is required")
    try:
        restored_manifest = ProtectedVaultManifest.from_dict(
            protected_vault_manifest.to_dict()
        )
    except ValueError as error:
        raise RawPackageClosureError(
            "protected-vault manifest typed codec is invalid"
        ) from error
    if restored_manifest != protected_vault_manifest:
        raise RawPackageClosureError(
            "protected-vault manifest differs after typed restoration"
        )
    references = tuple(protected_references)
    try:
        restored_references = tuple(
            ProtectedEvidenceReference.from_dict(item.to_dict()) for item in references
        )
    except (AttributeError, ValueError) as error:
        raise RawPackageClosureError(
            "protected reference typed codec is invalid"
        ) from error
    if restored_references != references:
        raise RawPackageClosureError(
            "protected references differ after typed restoration"
        )
    objects = protected_vault_manifest.objects
    if (
        len(references) != len(objects)
        or tuple(item.object_id for item in references)
        != tuple(item.object_id for item in objects)
        or tuple(item.object_hash for item in references)
        != tuple(item.object_hash for item in objects)
        or tuple(item.byte_count for item in references)
        != tuple(item.byte_count for item in objects)
        or tuple(item.reference_hash for item in references)
        != tuple(item.reference_hash for item in objects)
    ):
        raise RawPackageClosureError(
            "protected reference membership does not exactly match vault objects"
        )
    ancestry = pilot_candidate.common_ancestry_hash
    if (
        protected_vault_manifest.common_ancestry_hash != ancestry
        or any(item.common_ancestry_hash != ancestry for item in references)
        or any(
            item.package_id != protected_vault_manifest.package_id
            or item.vault_id != protected_vault_manifest.vault_id
            for item in references
        )
    ):
        raise RawPackageClosureError(
            "public Pilot slice and protected membership have mixed ancestry"
        )
    return pilot_candidate, protected_vault_manifest, references


def _typed_artifacts(
    *,
    pilot_candidate: SimulatedPilotPlanCandidate,
    protected_vault_manifest: ProtectedVaultManifest,
    protected_references: tuple[ProtectedEvidenceReference, ...],
) -> tuple[SimulatedPublicArtifact, ...]:
    public_objects = [
        {
            "membership_index": index,
            "object_hash": item.object_hash,
            "byte_count": item.byte_count,
            "classification": item.classification,
            "encryption_state": item.encryption_state,
            "reference_hash": item.reference_hash,
            "object_contract_hash": item.contract_hash,
        }
        for index, item in enumerate(protected_vault_manifest.objects)
    ]
    public_manifest = {
        "schema": "meas0.protected-vault-public-manifest.v3",
        "version": 1,
        "vault_id": protected_vault_manifest.vault_id,
        "package_id": protected_vault_manifest.package_id,
        "common_ancestry_hash": protected_vault_manifest.common_ancestry_hash,
        "acl_policy_hash": protected_vault_manifest.acl_policy_hash,
        "encryption_policy_hash": protected_vault_manifest.encryption_policy_hash,
        "retention_policy_ref": protected_vault_manifest.retention_policy_ref,
        "legal_hold_ref": protected_vault_manifest.legal_hold_ref,
        "protected_manifest_commitment_hash": protected_vault_manifest.contract_hash,
        "objects": public_objects,
        "object_ids_serialized": False,
        "object_id_hiding_verified": False,
        "object_id_hiding_gap": (
            "deterministic_commitments_allow_low_entropy_dictionary_confirmation"
        ),
        "claim_scope": "simulated_nonclaim",
        "production_authorized": False,
        "test_only": True,
    }
    refs_index = {
        "schema": "meas0.protected-vault-reference-index.v3",
        "version": 1,
        "package_id": protected_vault_manifest.package_id,
        "vault_id": protected_vault_manifest.vault_id,
        "common_ancestry_hash": protected_vault_manifest.common_ancestry_hash,
        "vault_manifest_hash": protected_vault_manifest.contract_hash,
        "references": [
            {
                "membership_index": index,
                "object_hash": item.object_hash,
                "byte_count": item.byte_count,
                "classification": item.classification,
                "encryption_state": item.encryption_state,
                "reference_hash": item.reference_hash,
            }
            for index, item in enumerate(protected_references)
        ],
        "object_ids_serialized": False,
        "object_id_hiding_verified": False,
        "object_id_hiding_gap": (
            "deterministic_commitments_allow_low_entropy_dictionary_confirmation"
        ),
        "claim_scope": "simulated_nonclaim",
        "production_authorized": False,
        "test_only": True,
    }
    values = (
        (
            "phase/pre_jcal_readiness.json",
            _canonical_bytes(pilot_candidate.pre_jcal_readiness.to_dict()),
        ),
        (
            "phase/pilot_readiness.json",
            _canonical_bytes(pilot_candidate.pilot_readiness.to_dict()),
        ),
        ("source/source_lock.json", pilot_candidate.source_lock.raw_bytes),
        (
            "input/pilot_manifest.json",
            _canonical_bytes(pilot_candidate.input_manifest.to_dict()),
        ),
        (
            "plan/pilot_candidate.json",
            _canonical_bytes(pilot_candidate.to_dict()),
        ),
        (
            "protected/vault_manifest.json",
            _canonical_bytes(public_manifest),
        ),
        ("protected/vault_refs.json", _canonical_bytes(refs_index)),
    )
    return tuple(
        SimulatedPublicArtifact._from_typed_bytes(
            relative_path=relative_path,
            raw_bytes=raw_bytes,
        )
        for relative_path, raw_bytes in values
    )


@dataclass(frozen=True)
class SimulatedPublicPackageClosure:
    """Typed seven-file index; explicitly not the complete raw package."""

    schema: str
    version: int
    package_id: str
    artifacts: tuple[SimulatedPublicArtifact, ...]
    common_ancestry_hash: str
    source_lock_hash: str
    input_manifest_hash: str
    vault_manifest_hash: str
    artifact_index_hash: str
    slice_membership_closed: bool
    raw_package_closed: bool
    source_restoration_authorized: bool
    fresh_replay_ready: bool
    missing_replay_authorities: tuple[str, ...]
    claim_scope: str
    production_authorized: bool
    test_only: bool
    closure_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
        object.__setattr__(
            self,
            "missing_replay_authorities",
            tuple(self.missing_replay_authorities),
        )
        if (
            self._factory_token is not _CLOSURE_TOKEN
            or self.schema != "meas0.simulated-public-package-closure.v3"
            or type(self.version) is not int
            or self.version != 1
            or tuple(item.relative_path for item in self.artifacts)
            != PUBLIC_PILOT_SLICE_FILES
            or not all(
                isinstance(item, SimulatedPublicArtifact) for item in self.artifacts
            )
        ):
            raise RawPackageClosureError(
                "public package lacks its exact typed Pilot slice"
            )
        for value, label in (
            (self.common_ancestry_hash, "common ancestry"),
            (self.source_lock_hash, "source lock"),
            (self.input_manifest_hash, "input manifest"),
            (self.vault_manifest_hash, "vault manifest"),
            (self.artifact_index_hash, "artifact index"),
            (self.closure_hash, "closure"),
        ):
            _digest(value, label)
        if (
            self.slice_membership_closed is not True
            or self.raw_package_closed is not False
            or self.source_restoration_authorized is not False
            or self.fresh_replay_ready is not False
            or self.missing_replay_authorities != _MISSING_AUTHORITIES
            or self.claim_scope != "simulated_nonclaim"
            or self.production_authorized is not False
            or self.test_only is not True
        ):
            raise RawPackageClosureError(
                "partial public slice cannot carry replay or production authority"
            )
        if self.artifact_index_hash != _canonical_hash(self._artifact_index()):
            raise RawPackageClosureError("public artifact index hash mismatch")
        if self.closure_hash != _canonical_hash(self._body()):
            raise RawPackageClosureError("public slice closure hash mismatch")

    def _artifact_index(self) -> list[dict[str, object]]:
        return [item.to_index_entry() for item in self.artifacts]

    def _body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "version": self.version,
            "package_id": self.package_id,
            "artifacts": self._artifact_index(),
            "common_ancestry_hash": self.common_ancestry_hash,
            "source_lock_hash": self.source_lock_hash,
            "input_manifest_hash": self.input_manifest_hash,
            "vault_manifest_hash": self.vault_manifest_hash,
            "artifact_index_hash": self.artifact_index_hash,
            "slice_membership_closed": self.slice_membership_closed,
            "raw_package_closed": self.raw_package_closed,
            "source_restoration_authorized": self.source_restoration_authorized,
            "fresh_replay_ready": self.fresh_replay_ready,
            "missing_replay_authorities": list(self.missing_replay_authorities),
            "claim_scope": self.claim_scope,
            "production_authorized": self.production_authorized,
            "test_only": self.test_only,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "closure_hash": self.closure_hash}

    def to_canonical_bytes(self) -> bytes:
        """Return strict bytes for offline transport and replay tests only."""

        return _canonical_bytes(self.to_dict())

    @classmethod
    def create_from_typed_sources(
        cls,
        *,
        expected_package_id: str,
        pilot_candidate: SimulatedPilotPlanCandidate,
        protected_vault_manifest: ProtectedVaultManifest,
        protected_references: Sequence[ProtectedEvidenceReference],
    ) -> SimulatedPublicPackageClosure:
        candidate, vault_manifest, references = _validate_typed_sources(
            pilot_candidate=pilot_candidate,
            protected_vault_manifest=protected_vault_manifest,
            protected_references=protected_references,
        )
        if (
            not isinstance(expected_package_id, str)
            or vault_manifest.package_id != expected_package_id
        ):
            raise RawPackageClosureError(
                "protected vault package differs from expected package binding"
            )
        artifacts = _typed_artifacts(
            pilot_candidate=candidate,
            protected_vault_manifest=vault_manifest,
            protected_references=references,
        )
        artifact_index_hash = _canonical_hash(
            [item.to_index_entry() for item in artifacts]
        )
        body = {
            "schema": "meas0.simulated-public-package-closure.v3",
            "version": 1,
            "package_id": vault_manifest.package_id,
            "artifacts": [item.to_index_entry() for item in artifacts],
            "common_ancestry_hash": candidate.common_ancestry_hash,
            "source_lock_hash": candidate.source_lock_hash,
            "input_manifest_hash": candidate.input_manifest_hash,
            "vault_manifest_hash": vault_manifest.contract_hash,
            "artifact_index_hash": artifact_index_hash,
            "slice_membership_closed": True,
            "raw_package_closed": False,
            "source_restoration_authorized": False,
            "fresh_replay_ready": False,
            "missing_replay_authorities": list(_MISSING_AUTHORITIES),
            "claim_scope": "simulated_nonclaim",
            "production_authorized": False,
            "test_only": True,
        }
        return cls(
            schema=body["schema"],
            version=body["version"],
            package_id=body["package_id"],
            artifacts=artifacts,
            common_ancestry_hash=body["common_ancestry_hash"],
            source_lock_hash=body["source_lock_hash"],
            input_manifest_hash=body["input_manifest_hash"],
            vault_manifest_hash=body["vault_manifest_hash"],
            artifact_index_hash=body["artifact_index_hash"],
            slice_membership_closed=True,
            raw_package_closed=False,
            source_restoration_authorized=False,
            fresh_replay_ready=False,
            missing_replay_authorities=_MISSING_AUTHORITIES,
            claim_scope="simulated_nonclaim",
            production_authorized=False,
            test_only=True,
            closure_hash=_canonical_hash(body),
            _factory_token=_CLOSURE_TOKEN,
        )

    @classmethod
    def restore_from_typed_sources(
        cls,
        value: object,
        *,
        expected_package_id: str,
        pilot_candidate: SimulatedPilotPlanCandidate,
        protected_vault_manifest: ProtectedVaultManifest,
        protected_references: Sequence[ProtectedEvidenceReference],
        expected_closure_hash: str,
    ) -> SimulatedPublicPackageClosure:
        expected_hash = _digest(
            expected_closure_hash,
            "authority-bound closure hash",
        )
        restored = cls.create_from_typed_sources(
            expected_package_id=expected_package_id,
            pilot_candidate=pilot_candidate,
            protected_vault_manifest=protected_vault_manifest,
            protected_references=protected_references,
        )
        if restored.closure_hash != expected_hash:
            raise RawPackageClosureError(
                "typed public slice differs from authority-bound closure hash"
            )
        source = _strict_mapping(
            value,
            fields=set(restored.to_dict()),
            label="serialized public slice closure",
        )
        if not _exact_equal(dict(source), restored.to_dict()):
            raise RawPackageClosureError(
                "serialized public slice differs from source-derived closure"
            )
        return restored

    @classmethod
    def restore_from_canonical_bytes(
        cls,
        raw_bytes: bytes,
        *,
        expected_package_id: str,
        pilot_candidate: SimulatedPilotPlanCandidate,
        protected_vault_manifest: ProtectedVaultManifest,
        protected_references: Sequence[ProtectedEvidenceReference],
        expected_closure_hash: str,
    ) -> SimulatedPublicPackageClosure:
        """Restore canonical bytes only against typed sources and a bound hash."""

        value = _decode_canonical_bytes(raw_bytes)
        return cls.restore_from_typed_sources(
            value,
            expected_package_id=expected_package_id,
            pilot_candidate=pilot_candidate,
            protected_vault_manifest=protected_vault_manifest,
            protected_references=protected_references,
            expected_closure_hash=expected_closure_hash,
        )


__all__ = [
    "PUBLIC_PILOT_SLICE_FILES",
    "RawPackageClosureError",
    "SimulatedPublicArtifact",
    "SimulatedPublicPackageClosure",
]
