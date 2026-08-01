"""Offline protected-raw byte bundle for the MEAS0 V3 nonclaim slice.

This carrier closes the exact bytes for a *test-only protected membership*.
It is intentionally separate from the public package projection: protected
object IDs and payload bytes are not suitable for public export.  The bundle
rechecks the existing typed vault manifest and references on restore, but it
does not provide source-restoration, transport, signature, or Gate authority.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .meas0_protected_vault import (
    ProtectedEvidenceReference,
    ProtectedVaultManifest,
)


class ProtectedRawBundleError(ValueError):
    """Protected raw bytes or typed membership failed closed."""


_ENTRY_TOKEN = object()
_BUNDLE_TOKEN = object()
_SCHEMA = "meas0.simulated-protected-raw-bundle.v3"
_ENTRY_SCHEMA = "meas0.simulated-protected-raw-entry.v3"
_CLAIM_SCOPE = "simulated_nonclaim"
_MISSING_AUTHORITIES = (
    "source_restoration_artifact",
    "transport_verifier",
    "human_signature_verifier",
    "authority_bound_package_seal",
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
        raise ProtectedRawBundleError(
            "protected raw value is not canonical JSON"
        ) from error


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
        raise ProtectedRawBundleError(f"{label} must be a lowercase SHA-256")
    return value


def _strict_mapping(
    value: object, *, fields: set[str], label: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ProtectedRawBundleError(f"{label} fields are invalid")
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


def _decode_base64(value: object, label: str) -> bytes:
    if not isinstance(value, str):
        raise ProtectedRawBundleError(f"{label} must be strict base64 text")
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as error:
        raise ProtectedRawBundleError(f"{label} is not strict base64") from error


def _decode_canonical_object(raw_bytes: bytes) -> Mapping[str, Any]:
    if type(raw_bytes) is not bytes:
        raise ProtectedRawBundleError("protected raw bundle must be exact bytes")
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
        raise ProtectedRawBundleError(
            "protected raw bundle is not strict canonical JSON"
        ) from error
    if duplicate or _canonical_bytes(value) != raw_bytes:
        raise ProtectedRawBundleError(
            "protected raw bundle is not canonical or contains duplicate fields"
        )
    if not isinstance(value, dict):
        raise ProtectedRawBundleError("protected raw bundle root must be an object")
    return value


def _validate_membership(
    *,
    expected_package_id: str,
    common_ancestry_hash: str,
    protected_vault_manifest: ProtectedVaultManifest,
    protected_references: Sequence[ProtectedEvidenceReference],
) -> tuple[ProtectedVaultManifest, tuple[ProtectedEvidenceReference, ...]]:
    if not isinstance(expected_package_id, str):
        raise ProtectedRawBundleError("expected package ID is required")
    _digest(common_ancestry_hash, "common ancestry hash")
    if not isinstance(protected_vault_manifest, ProtectedVaultManifest):
        raise ProtectedRawBundleError("typed protected-vault manifest is required")
    if protected_vault_manifest.package_id != expected_package_id:
        raise ProtectedRawBundleError(
            "protected-vault package differs from expected package"
        )
    if protected_vault_manifest.common_ancestry_hash != common_ancestry_hash:
        raise ProtectedRawBundleError(
            "protected-vault ancestry differs from expected ancestry"
        )
    try:
        manifest = ProtectedVaultManifest.from_dict(protected_vault_manifest.to_dict())
    except (TypeError, ValueError) as error:
        raise ProtectedRawBundleError(
            "protected-vault manifest typed codec is invalid"
        ) from error
    try:
        references = tuple(protected_references)
        restored_references = tuple(
            ProtectedEvidenceReference.from_dict(item.to_dict()) for item in references
        )
    except (AttributeError, TypeError, ValueError) as error:
        raise ProtectedRawBundleError(
            "protected references typed codec is invalid"
        ) from error
    if restored_references != references:
        raise ProtectedRawBundleError(
            "protected references differ after typed restoration"
        )
    objects = manifest.objects
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
        raise ProtectedRawBundleError(
            "protected raw payload membership does not match vault"
        )
    return manifest, references


@dataclass(frozen=True)
class SimulatedProtectedRawEntryV3:
    """One exact protected payload bound to one typed reference."""

    schema: str
    version: int
    object_id: str
    object_hash: str
    byte_count: int
    classification: str
    encryption_state: str
    reference_hash: str
    payload_bytes: bytes = field(repr=False)
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _ENTRY_TOKEN:
            raise ProtectedRawBundleError("protected raw entry requires its factory")
        if self.schema != _ENTRY_SCHEMA or self.version != 3:
            raise ProtectedRawBundleError("protected raw entry schema is invalid")
        if not isinstance(self.object_id, str) or not self.object_id:
            raise ProtectedRawBundleError("protected raw entry object ID is invalid")
        _digest(self.object_hash, "protected object hash")
        if type(self.byte_count) is not int or self.byte_count < 0:
            raise ProtectedRawBundleError("protected raw entry byte count is invalid")
        if self.classification != "test_data":
            raise ProtectedRawBundleError("protected raw entry must be test data")
        if self.encryption_state != "simulated_not_encrypted":
            raise ProtectedRawBundleError(
                "protected raw entry encryption state is invalid"
            )
        _digest(self.reference_hash, "protected reference hash")
        if type(self.payload_bytes) is not bytes:
            raise ProtectedRawBundleError("protected payload must be exact bytes")
        if len(self.payload_bytes) != self.byte_count:
            raise ProtectedRawBundleError("protected payload byte count mismatch")
        if _bytes_hash(self.payload_bytes) != self.object_hash:
            raise ProtectedRawBundleError("protected payload hash mismatch")

    @classmethod
    def create(
        cls,
        *,
        reference: ProtectedEvidenceReference,
        payload_bytes: bytes,
    ) -> SimulatedProtectedRawEntryV3:
        if not isinstance(reference, ProtectedEvidenceReference):
            raise ProtectedRawBundleError(
                "protected raw entry requires a typed reference"
            )
        if type(payload_bytes) is not bytes:
            raise ProtectedRawBundleError("protected payload must be exact bytes")
        return cls(
            schema=_ENTRY_SCHEMA,
            version=3,
            object_id=reference.object_id,
            object_hash=reference.object_hash,
            byte_count=reference.byte_count,
            classification=reference.classification,
            encryption_state=reference.encryption_state,
            reference_hash=reference.reference_hash,
            payload_bytes=payload_bytes,
            _factory_token=_ENTRY_TOKEN,
        )

    def _body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "version": self.version,
            "object_id": self.object_id,
            "object_hash": self.object_hash,
            "byte_count": self.byte_count,
            "classification": self.classification,
            "encryption_state": self.encryption_state,
            "reference_hash": self.reference_hash,
            "payload_base64": base64.b64encode(self.payload_bytes).decode("ascii"),
        }

    def to_dict(self) -> dict[str, Any]:
        return self._body()

    @classmethod
    def restore(cls, value: object) -> SimulatedProtectedRawEntryV3:
        raw = _strict_mapping(
            value,
            fields={
                "schema",
                "version",
                "object_id",
                "object_hash",
                "byte_count",
                "classification",
                "encryption_state",
                "reference_hash",
                "payload_base64",
            },
            label="protected raw entry",
        )
        try:
            result = cls(
                schema=raw["schema"],
                version=raw["version"],
                object_id=raw["object_id"],
                object_hash=raw["object_hash"],
                byte_count=raw["byte_count"],
                classification=raw["classification"],
                encryption_state=raw["encryption_state"],
                reference_hash=raw["reference_hash"],
                payload_bytes=_decode_base64(
                    raw["payload_base64"], "protected payload"
                ),
                _factory_token=_ENTRY_TOKEN,
            )
        except (TypeError, ProtectedRawBundleError) as error:
            raise ProtectedRawBundleError(
                f"protected raw entry cannot be restored: {error}"
            ) from error
        if not _exact_equal(value, result.to_dict()):
            raise ProtectedRawBundleError(
                "protected raw entry differs from source-derived bytes"
            )
        return result


@dataclass(frozen=True)
class SimulatedProtectedRawBundleV3:
    """Canonical protected raw payload bundle; never a production seal."""

    schema: str
    version: int
    package_id: str
    vault_id: str
    common_ancestry_hash: str
    vault_manifest_hash: str
    reference_index_hash: str
    entries: tuple[SimulatedProtectedRawEntryV3, ...]
    payload_membership_closed: bool
    fresh_replay_ready: bool
    missing_replay_authorities: tuple[str, ...]
    claim_scope: str
    production_authorized: bool
    test_only: bool
    bundle_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _BUNDLE_TOKEN:
            raise ProtectedRawBundleError("protected raw bundle requires its factory")
        if self.schema != _SCHEMA or self.version != 1:
            raise ProtectedRawBundleError(
                "protected raw bundle schema/version is invalid"
            )
        if not isinstance(self.package_id, str) or not self.package_id:
            raise ProtectedRawBundleError("protected raw bundle package ID is invalid")
        if not isinstance(self.vault_id, str) or not self.vault_id:
            raise ProtectedRawBundleError("protected raw bundle vault ID is invalid")
        _digest(self.common_ancestry_hash, "common ancestry hash")
        _digest(self.vault_manifest_hash, "vault manifest hash")
        _digest(self.reference_index_hash, "reference index hash")
        object.__setattr__(self, "entries", tuple(self.entries))
        object.__setattr__(
            self, "missing_replay_authorities", tuple(self.missing_replay_authorities)
        )
        if not self.entries or not all(
            isinstance(item, SimulatedProtectedRawEntryV3) for item in self.entries
        ):
            raise ProtectedRawBundleError("protected raw bundle requires typed entries")
        if (
            self.payload_membership_closed is not True
            or self.fresh_replay_ready is not False
            or self.missing_replay_authorities != _MISSING_AUTHORITIES
            or self.claim_scope != _CLAIM_SCOPE
            or self.production_authorized is not False
            or self.test_only is not True
        ):
            raise ProtectedRawBundleError(
                "protected raw bundle authority flags are invalid"
            )
        _digest(self.bundle_hash, "protected raw bundle hash")
        if self.bundle_hash != _canonical_hash(self._body()):
            raise ProtectedRawBundleError("protected raw bundle hash mismatch")

    def _body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "version": self.version,
            "package_id": self.package_id,
            "vault_id": self.vault_id,
            "common_ancestry_hash": self.common_ancestry_hash,
            "vault_manifest_hash": self.vault_manifest_hash,
            "reference_index_hash": self.reference_index_hash,
            "entries": [item.to_dict() for item in self.entries],
            "payload_membership_closed": self.payload_membership_closed,
            "fresh_replay_ready": self.fresh_replay_ready,
            "missing_replay_authorities": list(self.missing_replay_authorities),
            "claim_scope": self.claim_scope,
            "production_authorized": self.production_authorized,
            "test_only": self.test_only,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "bundle_hash": self.bundle_hash}

    def to_canonical_bytes(self) -> bytes:
        """Return protected-only bytes for offline transport tests."""

        return _canonical_bytes(self.to_dict())

    @staticmethod
    def _reference_index_hash(
        protected_references: Sequence[ProtectedEvidenceReference],
    ) -> str:
        return _canonical_hash([item.to_dict() for item in protected_references])

    @classmethod
    def create_from_typed_sources(
        cls,
        *,
        expected_package_id: str,
        common_ancestry_hash: str,
        protected_vault_manifest: ProtectedVaultManifest,
        protected_references: Sequence[ProtectedEvidenceReference],
        payloads: Mapping[str, bytes],
    ) -> SimulatedProtectedRawBundleV3:
        manifest, references = _validate_membership(
            expected_package_id=expected_package_id,
            common_ancestry_hash=common_ancestry_hash,
            protected_vault_manifest=protected_vault_manifest,
            protected_references=protected_references,
        )
        if not isinstance(payloads, Mapping):
            raise ProtectedRawBundleError(
                "protected payload membership must be a mapping"
            )
        expected_ids = tuple(item.object_id for item in references)
        if set(payloads) != set(expected_ids):
            raise ProtectedRawBundleError(
                "protected raw payload membership must exactly match typed references"
            )
        entries = tuple(
            SimulatedProtectedRawEntryV3.create(
                reference=reference,
                payload_bytes=payloads[reference.object_id],
            )
            for reference in references
        )
        body = {
            "schema": _SCHEMA,
            "version": 1,
            "package_id": manifest.package_id,
            "vault_id": manifest.vault_id,
            "common_ancestry_hash": manifest.common_ancestry_hash,
            "vault_manifest_hash": manifest.contract_hash,
            "reference_index_hash": cls._reference_index_hash(references),
            "entries": [item.to_dict() for item in entries],
            "payload_membership_closed": True,
            "fresh_replay_ready": False,
            "missing_replay_authorities": list(_MISSING_AUTHORITIES),
            "claim_scope": _CLAIM_SCOPE,
            "production_authorized": False,
            "test_only": True,
        }
        return cls(
            schema=_SCHEMA,
            version=1,
            package_id=manifest.package_id,
            vault_id=manifest.vault_id,
            common_ancestry_hash=manifest.common_ancestry_hash,
            vault_manifest_hash=manifest.contract_hash,
            reference_index_hash=cls._reference_index_hash(references),
            entries=entries,
            payload_membership_closed=True,
            fresh_replay_ready=False,
            missing_replay_authorities=_MISSING_AUTHORITIES,
            claim_scope=_CLAIM_SCOPE,
            production_authorized=False,
            test_only=True,
            bundle_hash=_canonical_hash(body),
            _factory_token=_BUNDLE_TOKEN,
        )

    @classmethod
    def restore_from_typed_sources(
        cls,
        value: object,
        *,
        expected_package_id: str,
        common_ancestry_hash: str,
        protected_vault_manifest: ProtectedVaultManifest,
        protected_references: Sequence[ProtectedEvidenceReference],
        payloads: Mapping[str, bytes],
        expected_bundle_hash: str,
    ) -> SimulatedProtectedRawBundleV3:
        """Recompute the bundle from typed protected bytes and compare an index."""

        restored = cls.create_from_typed_sources(
            expected_package_id=expected_package_id,
            common_ancestry_hash=common_ancestry_hash,
            protected_vault_manifest=protected_vault_manifest,
            protected_references=protected_references,
            payloads=payloads,
        )
        _digest(expected_bundle_hash, "authority-bound protected raw bundle hash")
        if restored.bundle_hash != expected_bundle_hash:
            raise ProtectedRawBundleError(
                "protected raw bundle differs from authority-bound bundle hash"
            )
        fields = set(restored.to_dict())
        raw = _strict_mapping(value, fields=fields, label="protected raw bundle")
        if not _exact_equal(dict(raw), restored.to_dict()):
            raise ProtectedRawBundleError(
                "protected raw bundle differs from source-derived bytes"
            )
        return restored

    @classmethod
    def restore_from_canonical_bytes(
        cls,
        raw_bytes: bytes,
        *,
        expected_package_id: str,
        common_ancestry_hash: str,
        protected_vault_manifest: ProtectedVaultManifest,
        protected_references: Sequence[ProtectedEvidenceReference],
        expected_bundle_hash: str,
    ) -> SimulatedProtectedRawBundleV3:
        value = _decode_canonical_object(raw_bytes)
        fields = {
            "schema",
            "version",
            "package_id",
            "vault_id",
            "common_ancestry_hash",
            "vault_manifest_hash",
            "reference_index_hash",
            "entries",
            "payload_membership_closed",
            "fresh_replay_ready",
            "missing_replay_authorities",
            "claim_scope",
            "production_authorized",
            "test_only",
            "bundle_hash",
        }
        raw = _strict_mapping(value, fields=fields, label="protected raw bundle")
        entries_raw = raw["entries"]
        if not isinstance(entries_raw, list):
            raise ProtectedRawBundleError("protected raw bundle entries must be a list")
        try:
            entries = tuple(
                SimulatedProtectedRawEntryV3.restore(item) for item in entries_raw
            )
        except ProtectedRawBundleError:
            raise
        except (TypeError, ValueError) as error:
            raise ProtectedRawBundleError(
                "protected raw bundle entries cannot be restored"
            ) from error
        payloads = {entry.object_id: entry.payload_bytes for entry in entries}
        if len(payloads) != len(entries):
            raise ProtectedRawBundleError(
                "protected raw bundle contains duplicate object IDs"
            )
        return cls.restore_from_typed_sources(
            value,
            expected_package_id=expected_package_id,
            common_ancestry_hash=common_ancestry_hash,
            protected_vault_manifest=protected_vault_manifest,
            protected_references=protected_references,
            payloads=payloads,
            expected_bundle_hash=expected_bundle_hash,
        )


__all__ = [
    "ProtectedRawBundleError",
    "SimulatedProtectedRawEntryV3",
    "SimulatedProtectedRawBundleV3",
]
