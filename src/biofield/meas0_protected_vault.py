"""Typed contracts for a simulated, in-memory MEAS0 protected evidence vault.

This module models commitments and readback verification only. It does not
implement encryption, access control, filesystem storage, or production trust.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping


class ProtectedVaultError(ValueError):
    """Protected-vault input or evidence failed closed."""


_ARTIFACT_TOKEN = object()
_VAULT_TOKEN = object()
_OPAQUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_OPAQUE_PACKAGE_ID = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9_-]{0,62}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9_-]{0,62}[A-Za-z0-9])?)*\Z"
)
_REFERENCE_SCHEMA = "meas0.protected-evidence-reference"
_OBJECT_SCHEMA = "meas0.protected-vault-object"
_MANIFEST_SCHEMA = "meas0.protected-vault-manifest"
_READBACK_SCHEMA = "meas0.protected-evidence-readback"
_CLAIM_SCOPE = "simulated_nonclaim"
_CLASSIFICATION = "test_data"
_ENCRYPTION_STATE = "simulated_not_encrypted"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _contract_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _bytes_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ProtectedVaultError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _opaque_id(value: object, label: str) -> str:
    if not isinstance(value, str) or _OPAQUE_ID.fullmatch(value) is None:
        raise ProtectedVaultError(
            f"{label} must be an opaque object ID without path or link syntax"
        )
    return value


def _opaque_package_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 256
        or _OPAQUE_PACKAGE_ID.fullmatch(value) is None
    ):
        raise ProtectedVaultError(
            "package_id must be an opaque package ID without path or URI syntax"
        )
    return value


def _strict_mapping(
    value: object,
    *,
    label: str,
    fields: set[str],
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ProtectedVaultError(f"{label} fields are invalid")
    return value


@dataclass(frozen=True)
class ProtectedEvidenceReference:
    """Location-free public reference to one protected test-data object."""

    schema: str
    version: int
    vault_id: str
    package_id: str
    common_ancestry_hash: str
    object_id: str
    object_hash: str
    byte_count: int
    classification: str
    encryption_state: str
    _derivation_token: object = field(default=None, repr=False, compare=False)
    _expected_object_hash: str | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self._derivation_token is not _ARTIFACT_TOKEN:
            raise ProtectedVaultError(
                "protected evidence reference must be created by its factory"
            )
        if self.schema != _REFERENCE_SCHEMA or self.version != 3:
            raise ProtectedVaultError("protected evidence reference schema is invalid")
        _opaque_id(self.vault_id, "vault_id")
        _opaque_package_id(self.package_id)
        _hash(self.common_ancestry_hash, "common_ancestry_hash")
        _opaque_id(self.object_id, "object_id")
        _hash(self.object_hash, "object_hash")
        if self.object_hash != self._expected_object_hash:
            raise ProtectedVaultError(
                "protected evidence reference object hash is not factory-derived"
            )
        if type(self.byte_count) is not int or self.byte_count < 0:
            raise ProtectedVaultError("byte count must be a non-negative integer")
        if self.classification != _CLASSIFICATION:
            raise ProtectedVaultError(
                "protected evidence reference must describe test data"
            )
        if self.encryption_state != _ENCRYPTION_STATE:
            raise ProtectedVaultError(
                "simulated vault encryption state must be non-production"
            )

    @property
    def claim_scope(self) -> str:
        return _CLAIM_SCOPE

    @property
    def test_only(self) -> bool:
        return True

    @property
    def production_authorized(self) -> bool:
        return False

    def _body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "version": self.version,
            "vault_id": self.vault_id,
            "package_id": self.package_id,
            "common_ancestry_hash": self.common_ancestry_hash,
            "object_id": self.object_id,
            "object_hash": self.object_hash,
            "byte_count": self.byte_count,
            "classification": self.classification,
            "encryption_state": self.encryption_state,
            "claim_scope": self.claim_scope,
            "test_only": self.test_only,
            "production_authorized": self.production_authorized,
        }

    @property
    def reference_hash(self) -> str:
        return _contract_hash(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "reference_hash": self.reference_hash}

    @classmethod
    def from_dict(cls, value: object) -> ProtectedEvidenceReference:
        fields = {
            "schema",
            "version",
            "vault_id",
            "package_id",
            "common_ancestry_hash",
            "object_id",
            "object_hash",
            "byte_count",
            "classification",
            "encryption_state",
            "claim_scope",
            "test_only",
            "production_authorized",
            "reference_hash",
        }
        raw = _strict_mapping(
            value,
            label="protected evidence reference",
            fields=fields,
        )
        if (
            raw["claim_scope"] != _CLAIM_SCOPE
            or raw["test_only"] is not True
            or raw["production_authorized"] is not False
        ):
            raise ProtectedVaultError(
                "protected evidence reference claim markers are invalid"
            )
        result = cls(
            schema=raw["schema"],
            version=raw["version"],
            vault_id=raw["vault_id"],
            package_id=raw["package_id"],
            common_ancestry_hash=raw["common_ancestry_hash"],
            object_id=raw["object_id"],
            object_hash=raw["object_hash"],
            byte_count=raw["byte_count"],
            classification=raw["classification"],
            encryption_state=raw["encryption_state"],
            _derivation_token=_ARTIFACT_TOKEN,
            _expected_object_hash=raw["object_hash"],
        )
        if raw["reference_hash"] != result.reference_hash:
            raise ProtectedVaultError(
                "protected evidence reference contract hash is invalid"
            )
        return result


@dataclass(frozen=True)
class ProtectedVaultObject:
    """Exact-byte metadata for one ordered vault-manifest member."""

    schema: str
    version: int
    object_id: str
    object_hash: str
    byte_count: int
    classification: str
    encryption_state: str
    reference_hash: str
    _derivation_token: object = field(default=None, repr=False, compare=False)
    _expected_object_hash: str | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self._derivation_token is not _ARTIFACT_TOKEN:
            raise ProtectedVaultError(
                "protected vault object must be created by its factory"
            )
        if self.schema != _OBJECT_SCHEMA or self.version != 3:
            raise ProtectedVaultError("protected vault object schema is invalid")
        _opaque_id(self.object_id, "object_id")
        _hash(self.object_hash, "object_hash")
        if self.object_hash != self._expected_object_hash:
            raise ProtectedVaultError(
                "protected vault object hash is not factory-derived"
            )
        if type(self.byte_count) is not int or self.byte_count < 0:
            raise ProtectedVaultError("byte count must be a non-negative integer")
        if self.classification != _CLASSIFICATION:
            raise ProtectedVaultError("protected vault object must be test data")
        if self.encryption_state != _ENCRYPTION_STATE:
            raise ProtectedVaultError(
                "simulated vault encryption state must be non-production"
            )
        _hash(self.reference_hash, "reference_hash")

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
        }

    @property
    def contract_hash(self) -> str:
        return _contract_hash(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "contract_hash": self.contract_hash}

    @classmethod
    def from_dict(cls, value: object) -> ProtectedVaultObject:
        fields = {
            "schema",
            "version",
            "object_id",
            "object_hash",
            "byte_count",
            "classification",
            "encryption_state",
            "reference_hash",
            "contract_hash",
        }
        raw = _strict_mapping(value, label="protected vault object", fields=fields)
        result = cls(
            schema=raw["schema"],
            version=raw["version"],
            object_id=raw["object_id"],
            object_hash=raw["object_hash"],
            byte_count=raw["byte_count"],
            classification=raw["classification"],
            encryption_state=raw["encryption_state"],
            reference_hash=raw["reference_hash"],
            _derivation_token=_ARTIFACT_TOKEN,
            _expected_object_hash=raw["object_hash"],
        )
        if raw["contract_hash"] != result.contract_hash:
            raise ProtectedVaultError("protected vault object contract hash is invalid")
        return result


@dataclass(frozen=True)
class ProtectedVaultManifest:
    """Hash-bound ordered membership and policy commitments for one vault."""

    schema: str
    version: int
    vault_id: str
    package_id: str
    common_ancestry_hash: str
    acl_policy_hash: str
    encryption_policy_hash: str
    retention_policy_ref: str
    legal_hold_ref: str
    objects: tuple[ProtectedVaultObject, ...]
    _derivation_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._derivation_token is not _ARTIFACT_TOKEN:
            raise ProtectedVaultError(
                "protected vault manifest must be created by its factory"
            )
        if self.schema != _MANIFEST_SCHEMA or self.version != 3:
            raise ProtectedVaultError("protected vault manifest schema is invalid")
        _opaque_id(self.vault_id, "vault_id")
        _opaque_package_id(self.package_id)
        for field_name in (
            "common_ancestry_hash",
            "acl_policy_hash",
            "encryption_policy_hash",
            "retention_policy_ref",
            "legal_hold_ref",
        ):
            _hash(getattr(self, field_name), field_name)
        if not isinstance(self.objects, tuple) or not all(
            isinstance(item, ProtectedVaultObject) for item in self.objects
        ):
            raise ProtectedVaultError(
                "protected vault manifest requires typed ordered membership"
            )
        object_ids = tuple(item.object_id for item in self.objects)
        if len(object_ids) != len(set(object_ids)):
            raise ProtectedVaultError(
                "protected vault manifest contains duplicate object IDs"
            )

    @property
    def claim_scope(self) -> str:
        return _CLAIM_SCOPE

    @property
    def test_only(self) -> bool:
        return True

    @property
    def production_authorized(self) -> bool:
        return False

    def _body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "version": self.version,
            "vault_id": self.vault_id,
            "package_id": self.package_id,
            "common_ancestry_hash": self.common_ancestry_hash,
            "acl_policy_hash": self.acl_policy_hash,
            "encryption_policy_hash": self.encryption_policy_hash,
            "retention_policy_ref": self.retention_policy_ref,
            "legal_hold_ref": self.legal_hold_ref,
            "objects": [item.to_dict() for item in self.objects],
            "claim_scope": self.claim_scope,
            "test_only": self.test_only,
            "production_authorized": self.production_authorized,
        }

    @property
    def contract_hash(self) -> str:
        return _contract_hash(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "contract_hash": self.contract_hash}

    @classmethod
    def from_dict(cls, value: object) -> ProtectedVaultManifest:
        fields = {
            "schema",
            "version",
            "vault_id",
            "package_id",
            "common_ancestry_hash",
            "acl_policy_hash",
            "encryption_policy_hash",
            "retention_policy_ref",
            "legal_hold_ref",
            "objects",
            "claim_scope",
            "test_only",
            "production_authorized",
            "contract_hash",
        }
        raw = _strict_mapping(
            value,
            label="protected vault manifest",
            fields=fields,
        )
        if (
            raw["claim_scope"] != _CLAIM_SCOPE
            or raw["test_only"] is not True
            or raw["production_authorized"] is not False
        ):
            raise ProtectedVaultError(
                "protected vault manifest claim markers are invalid"
            )
        objects = raw["objects"]
        if not isinstance(objects, list):
            raise ProtectedVaultError(
                "protected vault manifest objects must be an ordered list"
            )
        result = cls(
            schema=raw["schema"],
            version=raw["version"],
            vault_id=raw["vault_id"],
            package_id=raw["package_id"],
            common_ancestry_hash=raw["common_ancestry_hash"],
            acl_policy_hash=raw["acl_policy_hash"],
            encryption_policy_hash=raw["encryption_policy_hash"],
            retention_policy_ref=raw["retention_policy_ref"],
            legal_hold_ref=raw["legal_hold_ref"],
            objects=tuple(ProtectedVaultObject.from_dict(item) for item in objects),
            _derivation_token=_ARTIFACT_TOKEN,
        )
        if raw["contract_hash"] != result.contract_hash:
            raise ProtectedVaultError(
                "protected vault manifest contract hash is invalid"
            )
        return result


@dataclass(frozen=True)
class ProtectedEvidenceReadbackReceipt:
    """Hash-only receipt proving exact in-memory test-byte readback."""

    schema: str
    version: int
    reference_hash: str
    observed_object_hash: str
    observed_byte_count: int
    exact_match: bool
    _derivation_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._derivation_token is not _ARTIFACT_TOKEN:
            raise ProtectedVaultError(
                "protected evidence readback receipt must be created by its factory"
            )
        if self.schema != _READBACK_SCHEMA or self.version != 3:
            raise ProtectedVaultError("protected readback receipt schema is invalid")
        _hash(self.reference_hash, "reference_hash")
        _hash(self.observed_object_hash, "observed_object_hash")
        if type(self.observed_byte_count) is not int or self.observed_byte_count < 0:
            raise ProtectedVaultError(
                "observed byte count must be a non-negative integer"
            )
        if self.exact_match is not True:
            raise ProtectedVaultError("protected readback must be an exact match")

    @property
    def claim_scope(self) -> str:
        return _CLAIM_SCOPE

    @property
    def test_only(self) -> bool:
        return True

    @property
    def production_authorized(self) -> bool:
        return False

    def _body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "version": self.version,
            "reference_hash": self.reference_hash,
            "observed_object_hash": self.observed_object_hash,
            "observed_byte_count": self.observed_byte_count,
            "exact_match": self.exact_match,
            "claim_scope": self.claim_scope,
            "test_only": self.test_only,
            "production_authorized": self.production_authorized,
        }

    @property
    def receipt_hash(self) -> str:
        return _contract_hash(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "receipt_hash": self.receipt_hash}

    @classmethod
    def from_dict(cls, value: object) -> ProtectedEvidenceReadbackReceipt:
        fields = {
            "schema",
            "version",
            "reference_hash",
            "observed_object_hash",
            "observed_byte_count",
            "exact_match",
            "claim_scope",
            "test_only",
            "production_authorized",
            "receipt_hash",
        }
        raw = _strict_mapping(
            value,
            label="protected evidence readback receipt",
            fields=fields,
        )
        if (
            raw["claim_scope"] != _CLAIM_SCOPE
            or raw["test_only"] is not True
            or raw["production_authorized"] is not False
        ):
            raise ProtectedVaultError(
                "protected evidence readback claim markers are invalid"
            )
        result = cls(
            schema=raw["schema"],
            version=raw["version"],
            reference_hash=raw["reference_hash"],
            observed_object_hash=raw["observed_object_hash"],
            observed_byte_count=raw["observed_byte_count"],
            exact_match=raw["exact_match"],
            _derivation_token=_ARTIFACT_TOKEN,
        )
        if raw["receipt_hash"] != result.receipt_hash:
            raise ProtectedVaultError(
                "protected evidence readback receipt hash is invalid"
            )
        return result


class SimulatedProtectedEvidenceVault:
    """Write-once in-memory test vault with no real security enforcement."""

    __slots__ = (
        "_acl_policy_hash",
        "_common_ancestry_hash",
        "_encryption_policy_hash",
        "_legal_hold_ref",
        "_objects",
        "_package_id",
        "_payloads",
        "_retention_policy_ref",
        "_sealed",
        "_vault_id",
    )

    def __init__(
        self,
        *,
        vault_id: str,
        package_id: str,
        common_ancestry_hash: str,
        acl_policy_hash: str,
        encryption_policy_hash: str,
        retention_policy_ref: str,
        legal_hold_ref: str,
        _derivation_token: object = None,
    ) -> None:
        if _derivation_token is not _VAULT_TOKEN:
            raise ProtectedVaultError(
                "simulated protected evidence vault must be created by its factory"
            )
        self._vault_id = _opaque_id(vault_id, "vault_id")
        self._package_id = _opaque_package_id(package_id)
        self._common_ancestry_hash = _hash(
            common_ancestry_hash,
            "common_ancestry_hash",
        )
        self._acl_policy_hash = _hash(acl_policy_hash, "acl_policy_hash")
        self._encryption_policy_hash = _hash(
            encryption_policy_hash,
            "encryption_policy_hash",
        )
        self._retention_policy_ref = _hash(
            retention_policy_ref,
            "retention_policy_ref",
        )
        self._legal_hold_ref = _hash(legal_hold_ref, "legal_hold_ref")
        self._payloads: dict[str, bytes] = {}
        self._objects: list[ProtectedVaultObject] = []
        self._sealed = False

    @classmethod
    def create(
        cls,
        *,
        vault_id: str,
        package_id: str,
        common_ancestry_hash: str,
        acl_policy_hash: str,
        encryption_policy_hash: str,
        retention_policy_ref: str,
        legal_hold_ref: str,
    ) -> SimulatedProtectedEvidenceVault:
        return cls(
            vault_id=vault_id,
            package_id=package_id,
            common_ancestry_hash=common_ancestry_hash,
            acl_policy_hash=acl_policy_hash,
            encryption_policy_hash=encryption_policy_hash,
            retention_policy_ref=retention_policy_ref,
            legal_hold_ref=legal_hold_ref,
            _derivation_token=_VAULT_TOKEN,
        )

    @property
    def claim_scope(self) -> str:
        return _CLAIM_SCOPE

    @property
    def test_only(self) -> bool:
        return True

    @property
    def production_authorized(self) -> bool:
        return False

    def write_once(
        self,
        *,
        object_id: str,
        payload: bytes,
        classification: str,
    ) -> ProtectedEvidenceReference:
        if self._sealed:
            raise ProtectedVaultError("sealed protected vault cannot accept writes")
        normalized_id = _opaque_id(object_id, "object_id")
        if normalized_id in self._payloads:
            raise ProtectedVaultError("protected vault object IDs are write-once")
        if type(payload) is not bytes:
            raise ProtectedVaultError("protected vault payload must be exact bytes")
        if classification != _CLASSIFICATION:
            raise ProtectedVaultError(
                "simulated protected vault accepts test data only"
            )
        object_hash = _bytes_hash(payload)
        reference = ProtectedEvidenceReference(
            schema=_REFERENCE_SCHEMA,
            version=3,
            vault_id=self._vault_id,
            package_id=self._package_id,
            common_ancestry_hash=self._common_ancestry_hash,
            object_id=normalized_id,
            object_hash=object_hash,
            byte_count=len(payload),
            classification=classification,
            encryption_state=_ENCRYPTION_STATE,
            _derivation_token=_ARTIFACT_TOKEN,
            _expected_object_hash=object_hash,
        )
        item = ProtectedVaultObject(
            schema=_OBJECT_SCHEMA,
            version=3,
            object_id=normalized_id,
            object_hash=object_hash,
            byte_count=len(payload),
            classification=classification,
            encryption_state=_ENCRYPTION_STATE,
            reference_hash=reference.reference_hash,
            _derivation_token=_ARTIFACT_TOKEN,
            _expected_object_hash=object_hash,
        )
        self._payloads[normalized_id] = payload
        self._objects.append(item)
        return reference

    def seal(self) -> ProtectedVaultManifest:
        self._sealed = True
        return ProtectedVaultManifest(
            schema=_MANIFEST_SCHEMA,
            version=3,
            vault_id=self._vault_id,
            package_id=self._package_id,
            common_ancestry_hash=self._common_ancestry_hash,
            acl_policy_hash=self._acl_policy_hash,
            encryption_policy_hash=self._encryption_policy_hash,
            retention_policy_ref=self._retention_policy_ref,
            legal_hold_ref=self._legal_hold_ref,
            objects=tuple(self._objects),
            _derivation_token=_ARTIFACT_TOKEN,
        )

    def readback(
        self,
        reference: ProtectedEvidenceReference,
    ) -> ProtectedEvidenceReadbackReceipt:
        if not isinstance(reference, ProtectedEvidenceReference):
            raise ProtectedVaultError(
                "readback requires a typed protected evidence reference"
            )
        if (
            reference.vault_id != self._vault_id
            or reference.package_id != self._package_id
            or reference.common_ancestry_hash != self._common_ancestry_hash
        ):
            raise ProtectedVaultError(
                "protected evidence reference has the wrong vault binding"
            )
        payload = self._payloads.get(reference.object_id)
        if payload is None:
            raise ProtectedVaultError("protected evidence reference object is missing")
        item = next(
            candidate
            for candidate in self._objects
            if candidate.object_id == reference.object_id
        )
        if (
            reference.object_hash != item.object_hash
            or reference.byte_count != item.byte_count
            or reference.classification != item.classification
            or reference.encryption_state != item.encryption_state
            or reference.reference_hash != item.reference_hash
        ):
            raise ProtectedVaultError(
                "protected evidence reference does not match vault membership"
            )
        observed_hash = _bytes_hash(payload)
        observed_count = len(payload)
        if (
            observed_hash != reference.object_hash
            or observed_count != reference.byte_count
        ):
            raise ProtectedVaultError("protected evidence exact-byte readback failed")
        return ProtectedEvidenceReadbackReceipt(
            schema=_READBACK_SCHEMA,
            version=3,
            reference_hash=reference.reference_hash,
            observed_object_hash=observed_hash,
            observed_byte_count=observed_count,
            exact_match=True,
            _derivation_token=_ARTIFACT_TOKEN,
        )
