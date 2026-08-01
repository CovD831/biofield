"""Offline trust contracts for future MEAS0 formal evidence.

This module deliberately implements no production trust root and no network
transport.  Its deterministic signature algorithm is forgeable by design and
exists only to exercise canonical serialization, ancestry, authorization, and
fail-closed verification contracts in offline tests.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


DETERMINISTIC_TEST_ALGORITHM = "biofield.test.sha256-envelope.v1"
_SHA256_HEX_LENGTH = 64


class TrustContractError(ValueError):
    """A trust contract is malformed or internally inconsistent."""


class TrustDomain(str, Enum):
    TRANSPORT = "transport"
    HUMAN_APPROVAL = "human_approval"


class TransportClaimScope(str, Enum):
    GATEWAY_TLS_REQUEST_RESPONSE_OBSERVATION = (
        "gateway_tls_request_response_observation"
    )
    GATEWAY_TRANSPORT_ATTEMPT_OBSERVATION = "gateway_transport_attempt_observation"


class TransportOutcome(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


class TLSVerificationResult(str, Enum):
    VERIFIED = "verified"
    FAILED = "failed"
    NOT_ESTABLISHED = "not_established"


class TrustVerificationMode(str, Enum):
    TEST_ONLY_CONTRACT = "test_only_contract"
    PRODUCTION_DENY_ALL = "production_deny_all"
    PRODUCTION_EXTERNAL = "production_external"


class AuthorizationCheckpoint(str, Enum):
    PRE_JCAL = "pre_jcal"
    PILOT_START = "pilot_start"
    POST_PILOT_JAUDIT = "post_pilot_jaudit"
    CONFIRMATORY_START = "confirmatory_start"


_CHECKPOINT_BINDINGS = {
    AuthorizationCheckpoint.PRE_JCAL: ("jcal", "pre_jcal"),
    AuthorizationCheckpoint.PILOT_START: ("pilot", "pilot_start"),
    AuthorizationCheckpoint.POST_PILOT_JAUDIT: (
        "jaudit",
        "post_pilot_jaudit",
    ),
    AuthorizationCheckpoint.CONFIRMATORY_START: (
        "confirmatory",
        "confirmatory_start",
    ),
}


class VerificationBlocker(str, Enum):
    PRODUCTION_TRUST_NOT_IMPLEMENTED = "production_trust_not_implemented"
    TRUST_DOMAIN_MISMATCH = "trust_domain_mismatch"
    ROOT_NOT_ALLOWED = "root_not_allowed"
    ROOT_BINDING_INVALID = "root_binding_invalid"
    TEST_ONLY_EVIDENCE_NOT_ALLOWED = "test_only_evidence_not_allowed"
    KEY_NOT_AUTHORIZED = "key_not_authorized"
    KEY_REVOKED = "key_revoked"
    SIGNING_TIME_INVALID = "signing_time_invalid"
    SIGNATURE_INVALID = "signature_invalid"
    CLAIM_SCOPE_NOT_ALLOWED = "claim_scope_not_allowed"
    TRANSPORT_IDENTITY_INVALID = "transport_identity_invalid"
    TLS_EVIDENCE_INVALID = "tls_evidence_invalid"
    BATCH_ANCESTRY_INVALID = "batch_ancestry_invalid"
    BATCH_MEMBERSHIP_INVALID = "batch_membership_invalid"
    BATCH_ORDER_INVALID = "batch_order_invalid"
    CALL_BINDING_INVALID = "call_binding_invalid"
    CHAIN_ANCESTRY_INVALID = "chain_ancestry_invalid"
    PAYLOAD_HASH_MISMATCH = "payload_hash_mismatch"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TrustContractError(f"{label} must be non-empty text")
    return value


def _sha256_text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_HEX_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise TrustContractError(f"{label} must be lowercase SHA-256")
    return value


def _optional_sha256(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _sha256_text(value, label)


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TrustContractError(f"{label} must be a positive integer")
    return value


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TrustContractError(f"{label} must be a non-negative integer")
    return value


def _timestamp(value: object, label: str) -> str:
    text = _text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise TrustContractError(f"{label} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TrustContractError(f"{label} must include a timezone")
    return text


def _timestamp_value(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc)


def _unique_text_tuple(
    values: Sequence[object],
    label: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    normalized = tuple(_text(value, label) for value in values)
    if not allow_empty and not normalized:
        raise TrustContractError(f"{label} cannot be empty")
    if len(set(normalized)) != len(normalized):
        raise TrustContractError(f"{label} must be unique")
    return normalized


def _strict_mapping(
    value: object,
    *,
    label: str,
    fields: set[str],
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise TrustContractError(f"{label} schema is invalid")
    return value


def _verify_contract_hash(raw: Mapping[str, Any], instance: _HashBound) -> None:
    declared = _sha256_text(raw["contract_hash"], "contract_hash")
    if declared != instance.contract_hash:
        raise TrustContractError("contract hash mismatch")


class _HashBound:
    def _body(self) -> dict[str, Any]:
        raise NotImplementedError

    @property
    def contract_hash(self) -> str:
        return _sha256(_canonical(self._body()))

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "contract_hash": self.contract_hash}


@dataclass(frozen=True)
class VerificationAuthority(_HashBound):
    """Identify a verifier implementation without asserting that it exists."""

    schema_version: int
    authority_id: str
    implementation_id: str
    trust_domain: TrustDomain
    test_only: bool

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise TrustContractError(
                "verification authority schema_version must equal one"
            )
        _text(self.authority_id, "authority_id")
        _text(self.implementation_id, "implementation_id")
        if not isinstance(self.trust_domain, TrustDomain):
            object.__setattr__(self, "trust_domain", TrustDomain(self.trust_domain))
        if not isinstance(self.test_only, bool):
            raise TrustContractError("authority test_only must be explicit boolean")

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "authority_id": self.authority_id,
            "implementation_id": self.implementation_id,
            "trust_domain": self.trust_domain.value,
            "test_only": self.test_only,
        }

    @classmethod
    def from_dict(cls, value: object) -> VerificationAuthority:
        raw = _strict_mapping(
            value,
            label="verification authority",
            fields={
                "schema_version",
                "authority_id",
                "implementation_id",
                "trust_domain",
                "test_only",
                "contract_hash",
            },
        )
        result = cls(
            schema_version=raw["schema_version"],
            authority_id=raw["authority_id"],
            implementation_id=raw["implementation_id"],
            trust_domain=TrustDomain(raw["trust_domain"]),
            test_only=raw["test_only"],
        )
        _verify_contract_hash(raw, result)
        return result


_RESULT_FACTORY_TOKEN = object()


class VerificationResultFactory:
    """Sealed construction seam reserved for a concrete verifier backend."""

    def __init__(
        self,
        *,
        authority: VerificationAuthority,
        _token: object = None,
    ) -> None:
        if _token is not _RESULT_FACTORY_TOKEN:
            raise TrustContractError(
                "verification result factory requires a registered backend"
            )
        if not isinstance(authority, VerificationAuthority):
            raise TrustContractError("typed verification authority is required")
        self.authority = authority

    @classmethod
    def _for_registered_backend(
        cls,
        authority: VerificationAuthority,
    ) -> VerificationResultFactory:
        return cls(authority=authority, _token=_RESULT_FACTORY_TOKEN)

    def production_result(
        self,
        *,
        policy_hash: str,
        root_manifest_hash: str,
        payload_hash: str,
        evidence_hash: str,
    ) -> ProductionVerificationResult:
        return ProductionVerificationResult(
            schema_version=1,
            authority=self.authority,
            policy_hash=policy_hash,
            root_manifest_hash=root_manifest_hash,
            payload_hash=payload_hash,
            evidence_hash=evidence_hash,
            _derivation_token=_RESULT_FACTORY_TOKEN,
        )


@runtime_checkable
class ProductionSignatureVerifier(Protocol):
    """Plug-in seam; this repository intentionally supplies no implementation."""

    @property
    def authority(self) -> VerificationAuthority: ...

    def verify_signature_envelope(
        self,
        *,
        envelope: SignatureEnvelope,
        payload_hash: str,
        root_manifest: TrustRootManifest,
        policy: VerificationPolicy,
    ) -> VerificationResult | ProductionVerificationResult: ...

    def verify_transport_batch(
        self,
        *,
        batch: TransportReceiptBatch,
        root_manifest: TrustRootManifest,
        policy: VerificationPolicy,
    ) -> TransportBatchVerification | ProductionVerificationResult: ...


@dataclass(frozen=True)
class KeyAuthorization(_HashBound):
    """Bind one key to exactly one role and bounded purposes/phases."""

    key_fingerprint: str
    algorithm_id: str
    role_id: str
    allowed_purposes: tuple[str, ...]
    allowed_phases: tuple[str, ...]

    def __post_init__(self) -> None:
        _sha256_text(self.key_fingerprint, "key_fingerprint")
        _text(self.algorithm_id, "algorithm_id")
        _text(self.role_id, "role_id")
        object.__setattr__(
            self,
            "allowed_purposes",
            _unique_text_tuple(self.allowed_purposes, "allowed purpose"),
        )
        object.__setattr__(
            self,
            "allowed_phases",
            _unique_text_tuple(self.allowed_phases, "allowed phase"),
        )

    def authorizes(
        self,
        *,
        key_fingerprint: str,
        algorithm_id: str,
        role_id: str,
        purpose: str,
        phase: str,
    ) -> bool:
        return (
            self.key_fingerprint == key_fingerprint
            and self.algorithm_id == algorithm_id
            and self.role_id == role_id
            and purpose in self.allowed_purposes
            and phase in self.allowed_phases
        )

    def _body(self) -> dict[str, Any]:
        return {
            "key_fingerprint": self.key_fingerprint,
            "algorithm_id": self.algorithm_id,
            "role_id": self.role_id,
            "allowed_purposes": list(self.allowed_purposes),
            "allowed_phases": list(self.allowed_phases),
        }

    @classmethod
    def from_dict(cls, value: object) -> KeyAuthorization:
        fields = {
            "key_fingerprint",
            "algorithm_id",
            "role_id",
            "allowed_purposes",
            "allowed_phases",
            "contract_hash",
        }
        raw = _strict_mapping(value, label="key authorization", fields=fields)
        result = cls(
            key_fingerprint=raw["key_fingerprint"],
            algorithm_id=raw["algorithm_id"],
            role_id=raw["role_id"],
            allowed_purposes=tuple(raw["allowed_purposes"]),
            allowed_phases=tuple(raw["allowed_phases"]),
        )
        _verify_contract_hash(raw, result)
        return result


def _validate_root_common(
    *,
    schema_version: int,
    root_id: str,
    key_authorizations: Sequence[KeyAuthorization],
    valid_from: str,
    valid_until: str,
    revocation_snapshot_hash: str,
    reviewer_role_id: str,
    test_only: bool,
) -> tuple[KeyAuthorization, ...]:
    if schema_version != 1:
        raise TrustContractError("trust-root schema_version must equal one")
    _text(root_id, "root_id")
    authorizations = tuple(key_authorizations)
    if not authorizations or any(
        not isinstance(item, KeyAuthorization) for item in authorizations
    ):
        raise TrustContractError("typed key authorizations are required")
    identities = tuple(
        (
            item.key_fingerprint,
            item.role_id,
            item.allowed_purposes,
            item.allowed_phases,
        )
        for item in authorizations
    )
    if len(set(identities)) != len(identities):
        raise TrustContractError("key authorizations must be unique")
    fingerprints = tuple(item.key_fingerprint for item in authorizations)
    if len(set(fingerprints)) != len(fingerprints):
        raise TrustContractError("one key fingerprint cannot authorize multiple roles")
    _timestamp(valid_from, "valid_from")
    _timestamp(valid_until, "valid_until")
    if _timestamp_value(valid_until) <= _timestamp_value(valid_from):
        raise TrustContractError("trust-root validity interval is invalid")
    _sha256_text(revocation_snapshot_hash, "revocation_snapshot_hash")
    _text(reviewer_role_id, "reviewer_role_id")
    if not isinstance(test_only, bool):
        raise TrustContractError("test_only must be explicit boolean")
    return authorizations


def _revoked_fingerprints(
    values: Sequence[object],
) -> tuple[str, ...]:
    revoked = tuple(_sha256_text(value, "revoked key fingerprint") for value in values)
    if len(set(revoked)) != len(revoked):
        raise TrustContractError("revoked key fingerprints must be unique")
    return revoked


@dataclass(frozen=True)
class TransportTrustRootManifest(_HashBound):
    """A scoped gateway root manifest; not a production root by itself."""

    schema_version: int
    root_id: str
    operator_id: str
    harness_administrative_domain: str
    administrative_domain: str
    harness_security_boundary_id: str
    security_boundary_id: str
    workload_identity: str
    key_custodian: str
    claim_scopes: tuple[TransportClaimScope, ...]
    provider_id: str
    endpoint_origins: tuple[str, ...]
    model_ids: tuple[str, ...]
    key_authorizations: tuple[KeyAuthorization, ...]
    valid_from: str
    valid_until: str
    revocation_snapshot_hash: str
    revoked_key_fingerprints: tuple[str, ...]
    tls_verification_policy_hash: str
    reviewer_role_id: str
    test_only: bool

    @property
    def trust_domain(self) -> TrustDomain:
        return TrustDomain.TRANSPORT

    def __post_init__(self) -> None:
        _text(self.operator_id, "operator_id")
        administrative_domain = _text(
            self.administrative_domain,
            "administrative_domain",
        )
        harness_administrative_domain = _text(
            self.harness_administrative_domain,
            "harness_administrative_domain",
        )
        security_boundary = _text(
            self.security_boundary_id,
            "security_boundary_id",
        )
        harness_security_boundary = _text(
            self.harness_security_boundary_id,
            "harness_security_boundary_id",
        )
        if (
            administrative_domain == harness_administrative_domain
            or security_boundary == harness_security_boundary
        ):
            raise TrustContractError(
                "transport root requires an independent administrative/security boundary"
            )
        _text(self.workload_identity, "workload_identity")
        _text(self.key_custodian, "key_custodian")
        scopes = tuple(
            item if isinstance(item, TransportClaimScope) else TransportClaimScope(item)
            for item in self.claim_scopes
        )
        if not scopes or len(set(scopes)) != len(scopes):
            raise TrustContractError("transport claim scopes must be non-empty unique")
        object.__setattr__(self, "claim_scopes", scopes)
        _text(self.provider_id, "provider_id")
        object.__setattr__(
            self,
            "endpoint_origins",
            _unique_text_tuple(self.endpoint_origins, "endpoint origin"),
        )
        object.__setattr__(
            self,
            "model_ids",
            _unique_text_tuple(self.model_ids, "model ID"),
        )
        object.__setattr__(
            self,
            "key_authorizations",
            _validate_root_common(
                schema_version=self.schema_version,
                root_id=self.root_id,
                key_authorizations=self.key_authorizations,
                valid_from=self.valid_from,
                valid_until=self.valid_until,
                revocation_snapshot_hash=self.revocation_snapshot_hash,
                reviewer_role_id=self.reviewer_role_id,
                test_only=self.test_only,
            ),
        )
        object.__setattr__(
            self,
            "revoked_key_fingerprints",
            _revoked_fingerprints(self.revoked_key_fingerprints),
        )
        if self.reviewer_role_id in {item.role_id for item in self.key_authorizations}:
            raise TrustContractError(
                "root reviewer must be independent from signing roles"
            )
        _sha256_text(
            self.tls_verification_policy_hash,
            "tls_verification_policy_hash",
        )

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "trust_domain": self.trust_domain.value,
            "root_id": self.root_id,
            "operator_id": self.operator_id,
            "harness_administrative_domain": (self.harness_administrative_domain),
            "administrative_domain": self.administrative_domain,
            "harness_security_boundary_id": (self.harness_security_boundary_id),
            "security_boundary_id": self.security_boundary_id,
            "workload_identity": self.workload_identity,
            "key_custodian": self.key_custodian,
            "claim_scopes": [item.value for item in self.claim_scopes],
            "provider_id": self.provider_id,
            "endpoint_origins": list(self.endpoint_origins),
            "model_ids": list(self.model_ids),
            "key_authorizations": [item.to_dict() for item in self.key_authorizations],
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "revocation_snapshot_hash": self.revocation_snapshot_hash,
            "revoked_key_fingerprints": list(self.revoked_key_fingerprints),
            "tls_verification_policy_hash": self.tls_verification_policy_hash,
            "reviewer_role_id": self.reviewer_role_id,
            "test_only": self.test_only,
        }

    @classmethod
    def from_dict(cls, value: object) -> TransportTrustRootManifest:
        fields = {
            "schema_version",
            "trust_domain",
            "root_id",
            "operator_id",
            "harness_administrative_domain",
            "administrative_domain",
            "harness_security_boundary_id",
            "security_boundary_id",
            "workload_identity",
            "key_custodian",
            "claim_scopes",
            "provider_id",
            "endpoint_origins",
            "model_ids",
            "key_authorizations",
            "valid_from",
            "valid_until",
            "revocation_snapshot_hash",
            "revoked_key_fingerprints",
            "tls_verification_policy_hash",
            "reviewer_role_id",
            "test_only",
            "contract_hash",
        }
        raw = _strict_mapping(
            value,
            label="transport trust-root manifest",
            fields=fields,
        )
        if raw["trust_domain"] != TrustDomain.TRANSPORT.value:
            raise TrustContractError("transport trust-root domain is invalid")
        result = cls(
            schema_version=raw["schema_version"],
            root_id=raw["root_id"],
            operator_id=raw["operator_id"],
            harness_administrative_domain=raw["harness_administrative_domain"],
            administrative_domain=raw["administrative_domain"],
            harness_security_boundary_id=raw["harness_security_boundary_id"],
            security_boundary_id=raw["security_boundary_id"],
            workload_identity=raw["workload_identity"],
            key_custodian=raw["key_custodian"],
            claim_scopes=tuple(raw["claim_scopes"]),
            provider_id=raw["provider_id"],
            endpoint_origins=tuple(raw["endpoint_origins"]),
            model_ids=tuple(raw["model_ids"]),
            key_authorizations=tuple(
                KeyAuthorization.from_dict(item) for item in raw["key_authorizations"]
            ),
            valid_from=raw["valid_from"],
            valid_until=raw["valid_until"],
            revocation_snapshot_hash=raw["revocation_snapshot_hash"],
            revoked_key_fingerprints=tuple(raw["revoked_key_fingerprints"]),
            tls_verification_policy_hash=raw["tls_verification_policy_hash"],
            reviewer_role_id=raw["reviewer_role_id"],
            test_only=raw["test_only"],
        )
        _verify_contract_hash(raw, result)
        return result


@dataclass(frozen=True)
class HumanTrustRootManifest(_HashBound):
    """A separately scoped root for human approval/review signatures."""

    schema_version: int
    root_id: str
    custodian_id: str
    key_authorizations: tuple[KeyAuthorization, ...]
    valid_from: str
    valid_until: str
    revocation_snapshot_hash: str
    revoked_key_fingerprints: tuple[str, ...]
    reviewer_role_id: str
    test_only: bool

    @property
    def trust_domain(self) -> TrustDomain:
        return TrustDomain.HUMAN_APPROVAL

    def __post_init__(self) -> None:
        _text(self.custodian_id, "custodian_id")
        object.__setattr__(
            self,
            "key_authorizations",
            _validate_root_common(
                schema_version=self.schema_version,
                root_id=self.root_id,
                key_authorizations=self.key_authorizations,
                valid_from=self.valid_from,
                valid_until=self.valid_until,
                revocation_snapshot_hash=self.revocation_snapshot_hash,
                reviewer_role_id=self.reviewer_role_id,
                test_only=self.test_only,
            ),
        )
        object.__setattr__(
            self,
            "revoked_key_fingerprints",
            _revoked_fingerprints(self.revoked_key_fingerprints),
        )
        if self.reviewer_role_id in {item.role_id for item in self.key_authorizations}:
            raise TrustContractError(
                "root reviewer must be independent from signing roles"
            )

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "trust_domain": self.trust_domain.value,
            "root_id": self.root_id,
            "custodian_id": self.custodian_id,
            "key_authorizations": [item.to_dict() for item in self.key_authorizations],
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "revocation_snapshot_hash": self.revocation_snapshot_hash,
            "revoked_key_fingerprints": list(self.revoked_key_fingerprints),
            "reviewer_role_id": self.reviewer_role_id,
            "test_only": self.test_only,
        }

    @classmethod
    def from_dict(cls, value: object) -> HumanTrustRootManifest:
        fields = {
            "schema_version",
            "trust_domain",
            "root_id",
            "custodian_id",
            "key_authorizations",
            "valid_from",
            "valid_until",
            "revocation_snapshot_hash",
            "revoked_key_fingerprints",
            "reviewer_role_id",
            "test_only",
            "contract_hash",
        }
        raw = _strict_mapping(
            value,
            label="human trust-root manifest",
            fields=fields,
        )
        if raw["trust_domain"] != TrustDomain.HUMAN_APPROVAL.value:
            raise TrustContractError("human trust-root domain is invalid")
        result = cls(
            schema_version=raw["schema_version"],
            root_id=raw["root_id"],
            custodian_id=raw["custodian_id"],
            key_authorizations=tuple(
                KeyAuthorization.from_dict(item) for item in raw["key_authorizations"]
            ),
            valid_from=raw["valid_from"],
            valid_until=raw["valid_until"],
            revocation_snapshot_hash=raw["revocation_snapshot_hash"],
            revoked_key_fingerprints=tuple(raw["revoked_key_fingerprints"]),
            reviewer_role_id=raw["reviewer_role_id"],
            test_only=raw["test_only"],
        )
        _verify_contract_hash(raw, result)
        return result


TrustRootManifest = TransportTrustRootManifest | HumanTrustRootManifest


@dataclass(frozen=True)
class SignatureEnvelope(_HashBound):
    """Detached signature metadata; the signature never signs itself."""

    schema_version: int
    envelope_id: str
    trust_domain: TrustDomain
    root_id: str
    root_manifest_hash: str
    key_fingerprint: str
    algorithm_id: str
    role_id: str
    purpose: str
    phase: str
    payload_hash: str
    sequence_number: int
    nonce: str
    observed_signing_time: str
    test_only: bool
    signature_hex: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise TrustContractError("signature schema_version must equal one")
        if not isinstance(self.trust_domain, TrustDomain):
            try:
                object.__setattr__(
                    self,
                    "trust_domain",
                    TrustDomain(self.trust_domain),
                )
            except ValueError as error:
                raise TrustContractError("signature trust domain is invalid") from error
        _text(self.envelope_id, "envelope_id")
        _text(self.root_id, "root_id")
        _sha256_text(self.root_manifest_hash, "root_manifest_hash")
        _sha256_text(self.key_fingerprint, "key_fingerprint")
        _text(self.algorithm_id, "algorithm_id")
        _text(self.role_id, "role_id")
        _text(self.purpose, "purpose")
        _text(self.phase, "phase")
        _sha256_text(self.payload_hash, "payload_hash")
        _non_negative_int(self.sequence_number, "sequence_number")
        _text(self.nonce, "nonce")
        _timestamp(self.observed_signing_time, "observed_signing_time")
        if not isinstance(self.test_only, bool):
            raise TrustContractError("signature test_only must be explicit boolean")
        _sha256_text(self.signature_hex, "signature_hex")

    @property
    def signed_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "envelope_id": self.envelope_id,
            "trust_domain": self.trust_domain.value,
            "root_id": self.root_id,
            "root_manifest_hash": self.root_manifest_hash,
            "key_fingerprint": self.key_fingerprint,
            "algorithm_id": self.algorithm_id,
            "role_id": self.role_id,
            "purpose": self.purpose,
            "phase": self.phase,
            "payload_hash": self.payload_hash,
            "sequence_number": self.sequence_number,
            "nonce": self.nonce,
            "observed_signing_time": self.observed_signing_time,
            "test_only": self.test_only,
        }

    def _body(self) -> dict[str, Any]:
        return {**self.signed_metadata, "signature_hex": self.signature_hex}

    @classmethod
    def from_dict(cls, value: object) -> SignatureEnvelope:
        fields = {
            "schema_version",
            "envelope_id",
            "trust_domain",
            "root_id",
            "root_manifest_hash",
            "key_fingerprint",
            "algorithm_id",
            "role_id",
            "purpose",
            "phase",
            "payload_hash",
            "sequence_number",
            "nonce",
            "observed_signing_time",
            "test_only",
            "signature_hex",
            "contract_hash",
        }
        raw = _strict_mapping(value, label="signature envelope", fields=fields)
        result = cls(
            schema_version=raw["schema_version"],
            envelope_id=raw["envelope_id"],
            trust_domain=TrustDomain(raw["trust_domain"]),
            root_id=raw["root_id"],
            root_manifest_hash=raw["root_manifest_hash"],
            key_fingerprint=raw["key_fingerprint"],
            algorithm_id=raw["algorithm_id"],
            role_id=raw["role_id"],
            purpose=raw["purpose"],
            phase=raw["phase"],
            payload_hash=raw["payload_hash"],
            sequence_number=raw["sequence_number"],
            nonce=raw["nonce"],
            observed_signing_time=raw["observed_signing_time"],
            test_only=raw["test_only"],
            signature_hex=raw["signature_hex"],
        )
        _verify_contract_hash(raw, result)
        return result


@dataclass(frozen=True)
class AuthorizationCheckpointRequirement(_HashBound):
    """One exact human authorization membership frozen before execution."""

    checkpoint: AuthorizationCheckpoint
    phase: str
    purpose: str
    role_id: str
    authorization_target_hash: str
    ledger_pre_head_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.checkpoint, AuthorizationCheckpoint):
            object.__setattr__(
                self,
                "checkpoint",
                AuthorizationCheckpoint(self.checkpoint),
            )
        expected_phase, expected_purpose = _CHECKPOINT_BINDINGS[self.checkpoint]
        if (self.phase, self.purpose) != (expected_phase, expected_purpose):
            raise TrustContractError(
                "authorization checkpoint phase/purpose is not canonical"
            )
        _text(self.role_id, "authorization checkpoint role_id")
        _sha256_text(
            self.authorization_target_hash,
            "authorization checkpoint target hash",
        )
        _sha256_text(
            self.ledger_pre_head_hash,
            "authorization checkpoint ledger_pre_head_hash",
        )

    def _body(self) -> dict[str, Any]:
        return {
            "checkpoint": self.checkpoint.value,
            "phase": self.phase,
            "purpose": self.purpose,
            "role_id": self.role_id,
            "authorization_target_hash": self.authorization_target_hash,
            "ledger_pre_head_hash": self.ledger_pre_head_hash,
            "payload_hash": self.payload_hash,
        }

    @property
    def payload_hash(self) -> str:
        """Hash of the exact signed checkpoint payload, including ledger pre-head."""

        return _sha256(
            _canonical(
                {
                    "checkpoint": self.checkpoint.value,
                    "phase": self.phase,
                    "purpose": self.purpose,
                    "role_id": self.role_id,
                    "authorization_target_hash": self.authorization_target_hash,
                    "ledger_pre_head_hash": self.ledger_pre_head_hash,
                }
            )
        )

    @classmethod
    def from_dict(cls, value: object) -> AuthorizationCheckpointRequirement:
        raw = _strict_mapping(
            value,
            label="authorization checkpoint requirement",
            fields={
                "checkpoint",
                "phase",
                "purpose",
                "role_id",
                "authorization_target_hash",
                "ledger_pre_head_hash",
                "payload_hash",
                "contract_hash",
            },
        )
        result = cls(
            checkpoint=AuthorizationCheckpoint(raw["checkpoint"]),
            phase=raw["phase"],
            purpose=raw["purpose"],
            role_id=raw["role_id"],
            authorization_target_hash=raw["authorization_target_hash"],
            ledger_pre_head_hash=raw["ledger_pre_head_hash"],
        )
        if raw["payload_hash"] != result.payload_hash:
            raise TrustContractError(
                "authorization checkpoint payload hash is not derived"
            )
        _verify_contract_hash(raw, result)
        return result


@dataclass(frozen=True)
class AuthorizationCheckpointManifest(_HashBound):
    """Freeze the complete four-checkpoint signature membership."""

    schema_version: int
    manifest_id: str
    requirements: tuple[AuthorizationCheckpointRequirement, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise TrustContractError(
                "authorization checkpoint manifest schema_version must equal one"
            )
        _text(self.manifest_id, "authorization checkpoint manifest_id")
        requirements = tuple(self.requirements)
        if not all(
            isinstance(item, AuthorizationCheckpointRequirement)
            for item in requirements
        ):
            raise TrustContractError(
                "authorization checkpoint requirements must be typed"
            )
        if tuple(item.checkpoint for item in requirements) != tuple(
            AuthorizationCheckpoint
        ):
            raise TrustContractError(
                "authorization checkpoint membership must be complete and ordered"
            )
        object.__setattr__(self, "requirements", requirements)

    def matches_raw_envelopes(
        self,
        envelopes: Sequence[SignatureEnvelope],
    ) -> bool:
        """Match raw envelope metadata exactly; cryptographic verification is separate."""

        raw = tuple(envelopes)
        return (
            len(raw) == len(self.requirements)
            and all(isinstance(item, SignatureEnvelope) for item in raw)
            and all(
                envelope.trust_domain is TrustDomain.HUMAN_APPROVAL
                and (
                    envelope.phase,
                    envelope.purpose,
                    envelope.role_id,
                    envelope.payload_hash,
                )
                == (
                    requirement.phase,
                    requirement.purpose,
                    requirement.role_id,
                    requirement.payload_hash,
                )
                for envelope, requirement in zip(
                    raw,
                    self.requirements,
                    strict=True,
                )
            )
        )

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "requirements": [item.to_dict() for item in self.requirements],
        }

    @classmethod
    def from_dict(cls, value: object) -> AuthorizationCheckpointManifest:
        raw = _strict_mapping(
            value,
            label="authorization checkpoint manifest",
            fields={
                "schema_version",
                "manifest_id",
                "requirements",
                "contract_hash",
            },
        )
        result = cls(
            schema_version=raw["schema_version"],
            manifest_id=raw["manifest_id"],
            requirements=tuple(
                AuthorizationCheckpointRequirement.from_dict(item)
                for item in raw["requirements"]
            ),
        )
        _verify_contract_hash(raw, result)
        return result


@dataclass(frozen=True)
class TransportBatchEntry(_HashBound):
    """One pre-registered Judge transport call in an exact batch plan."""

    sequence_number: int
    invocation_id: str
    criterion_id: str
    presentation_hash: str
    data_attestation_hash: str
    request_fingerprint: str
    request_bytes_hash: str

    def __post_init__(self) -> None:
        _non_negative_int(self.sequence_number, "batch entry sequence_number")
        _text(self.invocation_id, "batch entry invocation_id")
        _text(self.criterion_id, "batch entry criterion_id")
        for field_name in (
            "presentation_hash",
            "data_attestation_hash",
            "request_fingerprint",
            "request_bytes_hash",
        ):
            _sha256_text(getattr(self, field_name), f"batch entry {field_name}")

    def _body(self) -> dict[str, Any]:
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, value: object) -> TransportBatchEntry:
        fields = set(cls.__dataclass_fields__) | {"contract_hash"}
        raw = _strict_mapping(value, label="transport batch entry", fields=fields)
        result = cls(
            **{field_name: raw[field_name] for field_name in cls.__dataclass_fields__}
        )
        _verify_contract_hash(raw, result)
        return result


@dataclass(frozen=True)
class TransportBatchPlan(_HashBound):
    """Pre-registered exact order and shared bindings for one receipt batch."""

    schema_version: int
    plan_id: str
    batch_id: str
    phase: str
    comparison_block_id: str
    comparison_lock_hash: str
    design_hash: str
    execution_authorization_hash: str
    provider_id: str
    endpoint_origin: str
    requested_model_id: str
    expected_observed_model_id: str
    entries: tuple[TransportBatchEntry, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise TrustContractError(
                "transport batch plan schema_version must equal one"
            )
        for field_name in (
            "plan_id",
            "batch_id",
            "phase",
            "comparison_block_id",
            "provider_id",
            "endpoint_origin",
            "requested_model_id",
            "expected_observed_model_id",
        ):
            _text(getattr(self, field_name), f"batch plan {field_name}")
        for field_name in (
            "comparison_lock_hash",
            "design_hash",
            "execution_authorization_hash",
        ):
            _sha256_text(getattr(self, field_name), f"batch plan {field_name}")
        entries = tuple(self.entries)
        if not entries or not all(
            isinstance(item, TransportBatchEntry) for item in entries
        ):
            raise TrustContractError("transport batch plan requires typed entries")
        if tuple(item.sequence_number for item in entries) != tuple(
            range(len(entries))
        ):
            raise TrustContractError(
                "transport batch plan entry sequence must be contiguous"
            )
        if len({item.invocation_id for item in entries}) != len(entries):
            raise TrustContractError(
                "transport batch plan invocation IDs must be unique"
            )
        object.__setattr__(self, "entries", entries)

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "batch_id": self.batch_id,
            "phase": self.phase,
            "comparison_block_id": self.comparison_block_id,
            "comparison_lock_hash": self.comparison_lock_hash,
            "design_hash": self.design_hash,
            "execution_authorization_hash": self.execution_authorization_hash,
            "provider_id": self.provider_id,
            "endpoint_origin": self.endpoint_origin,
            "requested_model_id": self.requested_model_id,
            "expected_observed_model_id": self.expected_observed_model_id,
            "entries": [item.to_dict() for item in self.entries],
        }

    @classmethod
    def from_dict(cls, value: object) -> TransportBatchPlan:
        fields = {
            "schema_version",
            "plan_id",
            "batch_id",
            "phase",
            "comparison_block_id",
            "comparison_lock_hash",
            "design_hash",
            "execution_authorization_hash",
            "provider_id",
            "endpoint_origin",
            "requested_model_id",
            "expected_observed_model_id",
            "entries",
            "contract_hash",
        }
        raw = _strict_mapping(value, label="transport batch plan", fields=fields)
        result = cls(
            schema_version=raw["schema_version"],
            plan_id=raw["plan_id"],
            batch_id=raw["batch_id"],
            phase=raw["phase"],
            comparison_block_id=raw["comparison_block_id"],
            comparison_lock_hash=raw["comparison_lock_hash"],
            design_hash=raw["design_hash"],
            execution_authorization_hash=raw["execution_authorization_hash"],
            provider_id=raw["provider_id"],
            endpoint_origin=raw["endpoint_origin"],
            requested_model_id=raw["requested_model_id"],
            expected_observed_model_id=raw["expected_observed_model_id"],
            entries=tuple(
                TransportBatchEntry.from_dict(item) for item in raw["entries"]
            ),
        )
        _verify_contract_hash(raw, result)
        return result


@dataclass(frozen=True)
class TransportReceiptPayload(_HashBound):
    """Canonical gateway observation, including an explicit no-response variant."""

    schema_version: int
    receipt_id: str
    claim_scope: TransportClaimScope
    provider_id: str
    endpoint_origin: str
    requested_model_id: str
    observed_model_id: str
    purpose: str
    phase: str
    comparison_block_id: str
    comparison_lock_hash: str
    design_hash: str
    execution_authorization_hash: str
    invocation_id: str
    criterion_id: str
    presentation_hash: str
    data_attestation_hash: str
    request_fingerprint: str
    request_bytes_hash: str
    outcome: TransportOutcome
    failure_code: str | None
    response_hash: str | None
    response_size: int | None
    http_status: int | None
    started_at: str
    completed_at: str
    nonce: str
    batch_id: str
    batch_manifest_hash: str
    sequence_number: int
    previous_receipt_hash: str | None
    tls_peer_hostname: str
    tls_sni: str
    tls_certificate_sha256: str | None
    tls_spki_sha256: str | None
    tls_chain_sha256: str | None
    tls_verification_result: TLSVerificationResult
    tls_trust_store_snapshot_hash: str
    tls_verification_policy_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise TrustContractError("transport receipt schema_version must equal one")
        try:
            claim_scope = (
                self.claim_scope
                if isinstance(self.claim_scope, TransportClaimScope)
                else TransportClaimScope(self.claim_scope)
            )
            outcome = (
                self.outcome
                if isinstance(self.outcome, TransportOutcome)
                else TransportOutcome(self.outcome)
            )
            tls_result = (
                self.tls_verification_result
                if isinstance(self.tls_verification_result, TLSVerificationResult)
                else TLSVerificationResult(self.tls_verification_result)
            )
        except ValueError as error:
            raise TrustContractError("transport receipt enum is invalid") from error
        object.__setattr__(self, "claim_scope", claim_scope)
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(self, "tls_verification_result", tls_result)
        for field_name in (
            "receipt_id",
            "provider_id",
            "endpoint_origin",
            "requested_model_id",
            "observed_model_id",
            "purpose",
            "phase",
            "comparison_block_id",
            "invocation_id",
            "criterion_id",
            "nonce",
            "batch_id",
            "tls_peer_hostname",
            "tls_sni",
        ):
            _text(getattr(self, field_name), field_name)
        for field_name in (
            "comparison_lock_hash",
            "design_hash",
            "execution_authorization_hash",
            "presentation_hash",
            "data_attestation_hash",
            "request_fingerprint",
            "request_bytes_hash",
            "batch_manifest_hash",
            "tls_trust_store_snapshot_hash",
            "tls_verification_policy_hash",
        ):
            _sha256_text(getattr(self, field_name), field_name)
        _timestamp(self.started_at, "started_at")
        _timestamp(self.completed_at, "completed_at")
        if _timestamp_value(self.completed_at) < _timestamp_value(self.started_at):
            raise TrustContractError("transport receipt completion predates start")
        _non_negative_int(self.sequence_number, "sequence_number")
        if self.sequence_number == 0:
            if self.previous_receipt_hash is not None:
                raise TrustContractError("first receipt cannot have previous ancestry")
        elif self.previous_receipt_hash is None:
            raise TrustContractError("non-first receipt requires previous ancestry")
        else:
            _sha256_text(self.previous_receipt_hash, "previous_receipt_hash")
        for field_name in (
            "tls_certificate_sha256",
            "tls_spki_sha256",
            "tls_chain_sha256",
        ):
            _optional_sha256(getattr(self, field_name), field_name)
        response_fields = (self.response_hash, self.response_size)
        if (response_fields[0] is None) != (response_fields[1] is None):
            raise TrustContractError("response hash and size must be present together")
        if self.response_hash is not None:
            _sha256_text(self.response_hash, "response_hash")
            _positive_int(self.response_size, "response_size")
        if self.http_status is not None and (
            isinstance(self.http_status, bool)
            or not isinstance(self.http_status, int)
            or not 100 <= self.http_status <= 599
        ):
            raise TrustContractError("http_status must be a valid HTTP status")
        if outcome is TransportOutcome.SUCCESS:
            if (
                claim_scope
                is not TransportClaimScope.GATEWAY_TLS_REQUEST_RESPONSE_OBSERVATION
                or self.failure_code is not None
                or not self.response_present
                or self.http_status is None
            ):
                raise TrustContractError(
                    "successful transport requires complete response identity"
                )
            if (
                tls_result is not TLSVerificationResult.VERIFIED
                or self.tls_certificate_sha256 is None
                or self.tls_spki_sha256 is None
                or self.tls_chain_sha256 is None
            ):
                raise TrustContractError(
                    "successful transport requires verified TLS evidence"
                )
        else:
            _text(self.failure_code, "failure_code")
            if not self.response_present:
                if (
                    claim_scope
                    is not TransportClaimScope.GATEWAY_TRANSPORT_ATTEMPT_OBSERVATION
                    or self.http_status is not None
                ):
                    raise TrustContractError(
                        "failed absent response must be an attempt observation"
                    )
                if any(
                    value is not None
                    for value in (
                        self.tls_certificate_sha256,
                        self.tls_spki_sha256,
                        self.tls_chain_sha256,
                    )
                ):
                    raise TrustContractError(
                        "failed absent response cannot claim TLS peer hashes"
                    )
            elif (
                claim_scope
                is not TransportClaimScope.GATEWAY_TLS_REQUEST_RESPONSE_OBSERVATION
            ):
                raise TrustContractError(
                    "attempt/absent response claim cannot retain response bytes"
                )
            elif (
                tls_result is not TLSVerificationResult.VERIFIED
                or self.tls_certificate_sha256 is None
                or self.tls_spki_sha256 is None
                or self.tls_chain_sha256 is None
            ):
                raise TrustContractError(
                    "failed response observation requires verified TLS evidence"
                )

    @property
    def response_present(self) -> bool:
        return self.response_hash is not None

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "claim_scope": self.claim_scope.value,
            "provider_id": self.provider_id,
            "endpoint_origin": self.endpoint_origin,
            "requested_model_id": self.requested_model_id,
            "observed_model_id": self.observed_model_id,
            "purpose": self.purpose,
            "phase": self.phase,
            "comparison_block_id": self.comparison_block_id,
            "comparison_lock_hash": self.comparison_lock_hash,
            "design_hash": self.design_hash,
            "execution_authorization_hash": self.execution_authorization_hash,
            "invocation_id": self.invocation_id,
            "criterion_id": self.criterion_id,
            "presentation_hash": self.presentation_hash,
            "data_attestation_hash": self.data_attestation_hash,
            "request_fingerprint": self.request_fingerprint,
            "request_bytes_hash": self.request_bytes_hash,
            "outcome": self.outcome.value,
            "failure_code": self.failure_code,
            "response_present": self.response_present,
            "response_hash": self.response_hash,
            "response_size": self.response_size,
            "http_status": self.http_status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "nonce": self.nonce,
            "batch_id": self.batch_id,
            "batch_manifest_hash": self.batch_manifest_hash,
            "sequence_number": self.sequence_number,
            "previous_receipt_hash": self.previous_receipt_hash,
            "tls_peer_hostname": self.tls_peer_hostname,
            "tls_sni": self.tls_sni,
            "tls_certificate_sha256": self.tls_certificate_sha256,
            "tls_spki_sha256": self.tls_spki_sha256,
            "tls_chain_sha256": self.tls_chain_sha256,
            "tls_verification_result": self.tls_verification_result.value,
            "tls_trust_store_snapshot_hash": (self.tls_trust_store_snapshot_hash),
            "tls_verification_policy_hash": (self.tls_verification_policy_hash),
        }

    @classmethod
    def from_dict(cls, value: object) -> TransportReceiptPayload:
        body_fields = {
            "schema_version",
            "receipt_id",
            "claim_scope",
            "provider_id",
            "endpoint_origin",
            "requested_model_id",
            "observed_model_id",
            "purpose",
            "phase",
            "comparison_block_id",
            "comparison_lock_hash",
            "design_hash",
            "execution_authorization_hash",
            "invocation_id",
            "criterion_id",
            "presentation_hash",
            "data_attestation_hash",
            "request_fingerprint",
            "request_bytes_hash",
            "outcome",
            "failure_code",
            "response_present",
            "response_hash",
            "response_size",
            "http_status",
            "started_at",
            "completed_at",
            "nonce",
            "batch_id",
            "batch_manifest_hash",
            "sequence_number",
            "previous_receipt_hash",
            "tls_peer_hostname",
            "tls_sni",
            "tls_certificate_sha256",
            "tls_spki_sha256",
            "tls_chain_sha256",
            "tls_verification_result",
            "tls_trust_store_snapshot_hash",
            "tls_verification_policy_hash",
        }
        raw = _strict_mapping(
            value,
            label="transport receipt payload",
            fields=body_fields | {"contract_hash"},
        )
        kwargs = {field_name: raw[field_name] for field_name in body_fields}
        declared_response_present = kwargs.pop("response_present")
        result = cls(**kwargs)
        if declared_response_present is not result.response_present:
            raise TrustContractError("response_present does not match response fields")
        _verify_contract_hash(raw, result)
        return result


@dataclass(frozen=True)
class SignedTransportReceipt(_HashBound):
    payload: TransportReceiptPayload
    envelope: SignatureEnvelope

    def __post_init__(self) -> None:
        if not isinstance(self.payload, TransportReceiptPayload):
            raise TrustContractError("typed transport payload is required")
        if not isinstance(self.envelope, SignatureEnvelope):
            raise TrustContractError("typed signature envelope is required")
        if (
            self.envelope.trust_domain is not TrustDomain.TRANSPORT
            or self.envelope.payload_hash != self.payload.contract_hash
            or self.envelope.purpose != self.payload.purpose
            or self.envelope.phase != self.payload.phase
            or self.envelope.sequence_number != self.payload.sequence_number
            or self.envelope.nonce != self.payload.nonce
        ):
            raise TrustContractError(
                "transport signature envelope does not bind its payload"
            )

    def _body(self) -> dict[str, Any]:
        return {
            "payload": self.payload.to_dict(),
            "envelope": self.envelope.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> SignedTransportReceipt:
        raw = _strict_mapping(
            value,
            label="signed transport receipt",
            fields={"payload", "envelope", "contract_hash"},
        )
        result = cls(
            payload=TransportReceiptPayload.from_dict(raw["payload"]),
            envelope=SignatureEnvelope.from_dict(raw["envelope"]),
        )
        _verify_contract_hash(raw, result)
        return result


@dataclass(frozen=True)
class TransportReceiptBatch(_HashBound):
    """Raw receipt collection; completeness is derived by a verifier."""

    schema_version: int
    plan: TransportBatchPlan
    receipts: tuple[SignedTransportReceipt, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise TrustContractError(
                "transport receipt batch schema_version must equal one"
            )
        if not isinstance(self.plan, TransportBatchPlan):
            raise TrustContractError("transport receipt batch requires a typed plan")
        receipts = tuple(self.receipts)
        if not all(isinstance(item, SignedTransportReceipt) for item in receipts):
            raise TrustContractError("transport receipt batch requires typed receipts")
        object.__setattr__(self, "receipts", receipts)

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan": self.plan.to_dict(),
            "receipts": [item.to_dict() for item in self.receipts],
        }

    @classmethod
    def from_dict(cls, value: object) -> TransportReceiptBatch:
        raw = _strict_mapping(
            value,
            label="transport receipt batch",
            fields={"schema_version", "plan", "receipts", "contract_hash"},
        )
        result = cls(
            schema_version=raw["schema_version"],
            plan=TransportBatchPlan.from_dict(raw["plan"]),
            receipts=tuple(
                SignedTransportReceipt.from_dict(item) for item in raw["receipts"]
            ),
        )
        _verify_contract_hash(raw, result)
        return result


@dataclass(frozen=True)
class VerificationPolicy(_HashBound):
    schema_version: int
    policy_id: str
    mode: TrustVerificationMode
    trust_domain: TrustDomain
    allowed_root_manifest_hashes: tuple[str, ...]
    allowed_claim_scopes: tuple[str, ...]
    expected_batch_manifest_hash: str | None
    allow_test_only: bool

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise TrustContractError(
                "verification policy schema_version must equal one"
            )
        _text(self.policy_id, "policy_id")
        if not isinstance(self.mode, TrustVerificationMode):
            object.__setattr__(
                self,
                "mode",
                TrustVerificationMode(self.mode),
            )
        if not isinstance(self.trust_domain, TrustDomain):
            object.__setattr__(
                self,
                "trust_domain",
                TrustDomain(self.trust_domain),
            )
        roots = tuple(
            _sha256_text(item, "allowed root manifest hash")
            for item in self.allowed_root_manifest_hashes
        )
        if not roots or len(set(roots)) != len(roots):
            raise TrustContractError(
                "allowed root manifest hashes must be non-empty unique"
            )
        object.__setattr__(self, "allowed_root_manifest_hashes", roots)
        object.__setattr__(
            self,
            "allowed_claim_scopes",
            _unique_text_tuple(
                self.allowed_claim_scopes,
                "allowed claim scope",
                allow_empty=self.trust_domain is TrustDomain.HUMAN_APPROVAL,
            ),
        )
        if (
            self.trust_domain is TrustDomain.HUMAN_APPROVAL
            and self.allowed_claim_scopes
        ):
            raise TrustContractError(
                "human verification policy cannot accept transport claim scopes"
            )
        _optional_sha256(
            self.expected_batch_manifest_hash,
            "expected_batch_manifest_hash",
        )
        if not isinstance(self.allow_test_only, bool):
            raise TrustContractError("allow_test_only must be explicit boolean")
        if (
            self.mode is TrustVerificationMode.PRODUCTION_DENY_ALL
            and self.allow_test_only
        ):
            raise TrustContractError(
                "production deny-all policy cannot allow test-only evidence"
            )

    @property
    def production_deny_all(self) -> bool:
        return self.mode is TrustVerificationMode.PRODUCTION_DENY_ALL

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "mode": self.mode.value,
            "trust_domain": self.trust_domain.value,
            "allowed_root_manifest_hashes": list(self.allowed_root_manifest_hashes),
            "allowed_claim_scopes": list(self.allowed_claim_scopes),
            "expected_batch_manifest_hash": self.expected_batch_manifest_hash,
            "allow_test_only": self.allow_test_only,
            "production_authorization": (
                "external_verifier_required"
                if self.mode is TrustVerificationMode.PRODUCTION_EXTERNAL
                else "deny_all_not_implemented"
            ),
        }

    @classmethod
    def from_dict(cls, value: object) -> VerificationPolicy:
        fields = {
            "schema_version",
            "policy_id",
            "mode",
            "trust_domain",
            "allowed_root_manifest_hashes",
            "allowed_claim_scopes",
            "expected_batch_manifest_hash",
            "allow_test_only",
            "production_authorization",
            "contract_hash",
        }
        raw = _strict_mapping(value, label="verification policy", fields=fields)
        mode = TrustVerificationMode(raw["mode"])
        expected_marker = (
            "external_verifier_required"
            if mode is TrustVerificationMode.PRODUCTION_EXTERNAL
            else "deny_all_not_implemented"
        )
        if raw["production_authorization"] != expected_marker:
            raise TrustContractError("production authorization marker is invalid")
        result = cls(
            schema_version=raw["schema_version"],
            policy_id=raw["policy_id"],
            mode=mode,
            trust_domain=TrustDomain(raw["trust_domain"]),
            allowed_root_manifest_hashes=tuple(raw["allowed_root_manifest_hashes"]),
            allowed_claim_scopes=tuple(raw["allowed_claim_scopes"]),
            expected_batch_manifest_hash=raw["expected_batch_manifest_hash"],
            allow_test_only=raw["allow_test_only"],
        )
        _verify_contract_hash(raw, result)
        return result


@dataclass(frozen=True)
class VerificationResult(_HashBound):
    schema_version: int
    verified: bool
    production_authorized: bool
    claim_scope: str
    mode: TrustVerificationMode
    trust_domain: TrustDomain
    policy_hash: str
    root_manifest_hash: str
    payload_hash: str
    envelope_hash: str
    blockers: tuple[VerificationBlocker, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise TrustContractError(
                "verification result schema_version must equal one"
            )
        if not isinstance(self.verified, bool):
            raise TrustContractError("verified must be boolean")
        if self.production_authorized is not False:
            raise TrustContractError(
                "production authorization is not implemented in this module"
            )
        if self.claim_scope != "contract_only":
            raise TrustContractError("verification claim scope must be contract_only")
        if not isinstance(self.mode, TrustVerificationMode):
            object.__setattr__(
                self,
                "mode",
                TrustVerificationMode(self.mode),
            )
        if not isinstance(self.trust_domain, TrustDomain):
            object.__setattr__(
                self,
                "trust_domain",
                TrustDomain(self.trust_domain),
            )
        for field_name in (
            "policy_hash",
            "root_manifest_hash",
            "payload_hash",
            "envelope_hash",
        ):
            _sha256_text(getattr(self, field_name), field_name)
        blockers = tuple(
            item if isinstance(item, VerificationBlocker) else VerificationBlocker(item)
            for item in self.blockers
        )
        canonical = tuple(item for item in VerificationBlocker if item in set(blockers))
        if blockers != canonical or len(blockers) != len(set(blockers)):
            raise TrustContractError("verification blockers are not canonical")
        if self.verified is not (not blockers):
            raise TrustContractError("verified status and blockers disagree")
        object.__setattr__(self, "blockers", blockers)

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "verified": self.verified,
            "production_authorized": self.production_authorized,
            "claim_scope": self.claim_scope,
            "mode": self.mode.value,
            "trust_domain": self.trust_domain.value,
            "policy_hash": self.policy_hash,
            "root_manifest_hash": self.root_manifest_hash,
            "payload_hash": self.payload_hash,
            "envelope_hash": self.envelope_hash,
            "blockers": [item.value for item in self.blockers],
        }

    @classmethod
    def from_dict(cls, value: object) -> VerificationResult:
        fields = {
            "schema_version",
            "verified",
            "production_authorized",
            "claim_scope",
            "mode",
            "trust_domain",
            "policy_hash",
            "root_manifest_hash",
            "payload_hash",
            "envelope_hash",
            "blockers",
            "contract_hash",
        }
        raw = _strict_mapping(value, label="verification result", fields=fields)
        result = cls(
            schema_version=raw["schema_version"],
            verified=raw["verified"],
            production_authorized=raw["production_authorized"],
            claim_scope=raw["claim_scope"],
            mode=TrustVerificationMode(raw["mode"]),
            trust_domain=TrustDomain(raw["trust_domain"]),
            policy_hash=raw["policy_hash"],
            root_manifest_hash=raw["root_manifest_hash"],
            payload_hash=raw["payload_hash"],
            envelope_hash=raw["envelope_hash"],
            blockers=tuple(VerificationBlocker(item) for item in raw["blockers"]),
        )
        _verify_contract_hash(raw, result)
        return result


@dataclass(frozen=True)
class ProductionVerificationResult(_HashBound):
    """Ephemeral evidence minted only by a registered production backend."""

    schema_version: int
    authority: VerificationAuthority
    policy_hash: str
    root_manifest_hash: str
    payload_hash: str
    evidence_hash: str
    _derivation_token: object = dataclass_field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self._derivation_token is not _RESULT_FACTORY_TOKEN:
            raise TrustContractError(
                "production verification result must come from its factory"
            )
        if self.schema_version != 1:
            raise TrustContractError(
                "production verification result schema_version must equal one"
            )
        if (
            not isinstance(self.authority, VerificationAuthority)
            or self.authority.test_only
        ):
            raise TrustContractError(
                "production verification requires a non-test authority"
            )
        for field_name in (
            "policy_hash",
            "root_manifest_hash",
            "payload_hash",
            "evidence_hash",
        ):
            _sha256_text(getattr(self, field_name), field_name)

    @property
    def production_authorized(self) -> bool:
        return True

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "authority": self.authority.to_dict(),
            "policy_hash": self.policy_hash,
            "root_manifest_hash": self.root_manifest_hash,
            "payload_hash": self.payload_hash,
            "evidence_hash": self.evidence_hash,
        }

    @classmethod
    def from_dict(cls, value: object) -> ProductionVerificationResult:
        del value
        raise TrustContractError(
            "serialized production verification results are untrusted; reverify raw evidence"
        )


_BATCH_VERIFICATION_DERIVATION_TOKEN = object()


@dataclass(frozen=True)
class TransportBatchVerification(_HashBound):
    """Derived batch result; contract validity never implies production authority."""

    schema_version: int
    contract_verified: bool
    production_authorized: bool
    claim_scope: str
    plan_hash: str
    batch_hash: str
    policy_hash: str
    root_manifest_hash: str
    receipt_verification_hashes: tuple[str, ...]
    blockers: tuple[VerificationBlocker, ...]
    _derivation_token: object = dataclass_field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self._derivation_token is not _BATCH_VERIFICATION_DERIVATION_TOKEN:
            raise TrustContractError("transport batch verification must be derived")
        if self.schema_version != 1:
            raise TrustContractError(
                "transport batch verification schema_version must equal one"
            )
        if not isinstance(self.contract_verified, bool):
            raise TrustContractError("contract_verified must be boolean")
        if self.production_authorized is not False:
            raise TrustContractError(
                "production authorization must be derived and is not implemented"
            )
        if self.claim_scope != "contract_only":
            raise TrustContractError(
                "batch verification claim scope must be contract_only"
            )
        for field_name in (
            "plan_hash",
            "batch_hash",
            "policy_hash",
            "root_manifest_hash",
        ):
            _sha256_text(getattr(self, field_name), field_name)
        hashes = tuple(
            _sha256_text(item, "receipt verification hash")
            for item in self.receipt_verification_hashes
        )
        object.__setattr__(self, "receipt_verification_hashes", hashes)
        blockers = tuple(
            item if isinstance(item, VerificationBlocker) else VerificationBlocker(item)
            for item in self.blockers
        )
        canonical = _canonical_blockers(blockers)
        if blockers != canonical or len(blockers) != len(set(blockers)):
            raise TrustContractError(
                "transport batch verification blockers are not canonical"
            )
        if self.contract_verified is not (not blockers):
            raise TrustContractError(
                "transport batch contract status and blockers disagree"
            )
        object.__setattr__(self, "blockers", blockers)

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "contract_verified": self.contract_verified,
            "production_authorized": self.production_authorized,
            "claim_scope": self.claim_scope,
            "plan_hash": self.plan_hash,
            "batch_hash": self.batch_hash,
            "policy_hash": self.policy_hash,
            "root_manifest_hash": self.root_manifest_hash,
            "receipt_verification_hashes": list(self.receipt_verification_hashes),
            "blockers": [item.value for item in self.blockers],
        }

    @classmethod
    def _create(
        cls,
        *,
        batch: TransportReceiptBatch,
        root_manifest: TrustRootManifest,
        policy: VerificationPolicy,
        receipt_results: Sequence[VerificationResult],
        blockers: Sequence[VerificationBlocker],
    ) -> TransportBatchVerification:
        canonical = _canonical_blockers(blockers)
        return cls(
            schema_version=1,
            contract_verified=not canonical,
            production_authorized=False,
            claim_scope="contract_only",
            plan_hash=batch.plan.contract_hash,
            batch_hash=batch.contract_hash,
            policy_hash=policy.contract_hash,
            root_manifest_hash=root_manifest.contract_hash,
            receipt_verification_hashes=tuple(
                item.contract_hash for item in receipt_results
            ),
            blockers=canonical,
            _derivation_token=_BATCH_VERIFICATION_DERIVATION_TOKEN,
        )

    @classmethod
    def from_dict(cls, value: object) -> TransportBatchVerification:
        fields = {
            "schema_version",
            "contract_verified",
            "production_authorized",
            "claim_scope",
            "plan_hash",
            "batch_hash",
            "policy_hash",
            "root_manifest_hash",
            "receipt_verification_hashes",
            "blockers",
            "contract_hash",
        }
        raw = _strict_mapping(
            value,
            label="transport batch verification",
            fields=fields,
        )
        result = cls(
            schema_version=raw["schema_version"],
            contract_verified=raw["contract_verified"],
            production_authorized=raw["production_authorized"],
            claim_scope=raw["claim_scope"],
            plan_hash=raw["plan_hash"],
            batch_hash=raw["batch_hash"],
            policy_hash=raw["policy_hash"],
            root_manifest_hash=raw["root_manifest_hash"],
            receipt_verification_hashes=tuple(raw["receipt_verification_hashes"]),
            blockers=tuple(VerificationBlocker(item) for item in raw["blockers"]),
            _derivation_token=_BATCH_VERIFICATION_DERIVATION_TOKEN,
        )
        _verify_contract_hash(raw, result)
        return result


def _authorization_for(
    root_manifest: TrustRootManifest,
    envelope: SignatureEnvelope,
) -> KeyAuthorization | None:
    return next(
        (
            item
            for item in root_manifest.key_authorizations
            if item.authorizes(
                key_fingerprint=envelope.key_fingerprint,
                algorithm_id=envelope.algorithm_id,
                role_id=envelope.role_id,
                purpose=envelope.purpose,
                phase=envelope.phase,
            )
        ),
        None,
    )


def _canonical_blockers(
    blockers: Sequence[VerificationBlocker],
) -> tuple[VerificationBlocker, ...]:
    observed = set(blockers)
    return tuple(item for item in VerificationBlocker if item in observed)


class DeterministicTestSignatureVerifier:
    """Forgeable offline signer/verifier; never grants production authority."""

    algorithm_id = DETERMINISTIC_TEST_ALGORITHM
    test_only = True

    @staticmethod
    def _test_signature(signed_metadata: Mapping[str, Any]) -> str:
        return _sha256(
            b"biofield-deterministic-test-signature-v1\0"
            + _canonical(dict(signed_metadata))
        )

    def sign_test_only(
        self,
        *,
        payload_hash: str,
        root_manifest: TrustRootManifest,
        key_fingerprint: str,
        role_id: str,
        purpose: str,
        phase: str,
        sequence_number: int,
        nonce: str,
        observed_signing_time: str,
    ) -> SignatureEnvelope:
        if not isinstance(
            root_manifest,
            (TransportTrustRootManifest, HumanTrustRootManifest),
        ):
            raise TrustContractError("typed test trust-root manifest is required")
        if root_manifest.test_only is not True:
            raise TrustContractError("deterministic signer requires test-only root")
        _sha256_text(payload_hash, "payload_hash")
        authorization = next(
            (
                item
                for item in root_manifest.key_authorizations
                if item.key_fingerprint == key_fingerprint
            ),
            None,
        )
        if authorization is None or authorization.algorithm_id != self.algorithm_id:
            raise TrustContractError(
                "deterministic signer key/algorithm is not in the test root"
            )
        unsigned = SignatureEnvelope(
            schema_version=1,
            envelope_id=f"{root_manifest.root_id}.{sequence_number}.{nonce}",
            trust_domain=root_manifest.trust_domain,
            root_id=root_manifest.root_id,
            root_manifest_hash=root_manifest.contract_hash,
            key_fingerprint=key_fingerprint,
            algorithm_id=self.algorithm_id,
            role_id=role_id,
            purpose=purpose,
            phase=phase,
            payload_hash=payload_hash,
            sequence_number=sequence_number,
            nonce=nonce,
            observed_signing_time=observed_signing_time,
            test_only=True,
            signature_hex="0" * 64,
        )
        return SignatureEnvelope(
            **{
                **unsigned.signed_metadata,
                "trust_domain": unsigned.trust_domain,
                "signature_hex": self._test_signature(unsigned.signed_metadata),
            }
        )

    def _verify_envelope(
        self,
        *,
        envelope: SignatureEnvelope,
        payload_hash: str,
        root_manifest: TrustRootManifest,
        policy: VerificationPolicy,
    ) -> list[VerificationBlocker]:
        blockers: list[VerificationBlocker] = []
        if policy.production_deny_all:
            blockers.append(VerificationBlocker.PRODUCTION_TRUST_NOT_IMPLEMENTED)
        if (
            policy.trust_domain is not root_manifest.trust_domain
            or envelope.trust_domain is not root_manifest.trust_domain
        ):
            blockers.append(VerificationBlocker.TRUST_DOMAIN_MISMATCH)
        if root_manifest.contract_hash not in policy.allowed_root_manifest_hashes:
            blockers.append(VerificationBlocker.ROOT_NOT_ALLOWED)
        if (
            envelope.root_id != root_manifest.root_id
            or envelope.root_manifest_hash != root_manifest.contract_hash
        ):
            blockers.append(VerificationBlocker.ROOT_BINDING_INVALID)
        if envelope.payload_hash != payload_hash:
            blockers.append(VerificationBlocker.PAYLOAD_HASH_MISMATCH)
        if (
            root_manifest.test_only
            or envelope.test_only
            or envelope.algorithm_id == DETERMINISTIC_TEST_ALGORITHM
        ) and not policy.allow_test_only:
            blockers.append(VerificationBlocker.TEST_ONLY_EVIDENCE_NOT_ALLOWED)
        if _authorization_for(root_manifest, envelope) is None:
            blockers.append(VerificationBlocker.KEY_NOT_AUTHORIZED)
        if envelope.key_fingerprint in root_manifest.revoked_key_fingerprints:
            blockers.append(VerificationBlocker.KEY_REVOKED)
        signing_time = _timestamp_value(envelope.observed_signing_time)
        if not (
            _timestamp_value(root_manifest.valid_from)
            <= signing_time
            <= _timestamp_value(root_manifest.valid_until)
        ):
            blockers.append(VerificationBlocker.SIGNING_TIME_INVALID)
        if envelope.signature_hex != self._test_signature(envelope.signed_metadata):
            blockers.append(VerificationBlocker.SIGNATURE_INVALID)
        return blockers

    @staticmethod
    def _result(
        *,
        blockers: Sequence[VerificationBlocker],
        envelope: SignatureEnvelope,
        payload_hash: str,
        root_manifest: TrustRootManifest,
        policy: VerificationPolicy,
    ) -> VerificationResult:
        canonical = _canonical_blockers(blockers)
        return VerificationResult(
            schema_version=1,
            verified=not canonical,
            production_authorized=False,
            claim_scope="contract_only",
            mode=policy.mode,
            trust_domain=policy.trust_domain,
            policy_hash=policy.contract_hash,
            root_manifest_hash=root_manifest.contract_hash,
            payload_hash=payload_hash,
            envelope_hash=envelope.contract_hash,
            blockers=canonical,
        )

    def verify_signature_envelope(
        self,
        *,
        envelope: SignatureEnvelope,
        payload_hash: str,
        root_manifest: TrustRootManifest,
        policy: VerificationPolicy,
    ) -> VerificationResult:
        if not isinstance(envelope, SignatureEnvelope):
            raise TrustContractError("typed signature envelope is required")
        if not isinstance(
            root_manifest,
            (TransportTrustRootManifest, HumanTrustRootManifest),
        ):
            raise TrustContractError("typed trust-root manifest is required")
        if not isinstance(policy, VerificationPolicy):
            raise TrustContractError("typed verification policy is required")
        _sha256_text(payload_hash, "payload_hash")
        blockers = self._verify_envelope(
            envelope=envelope,
            payload_hash=payload_hash,
            root_manifest=root_manifest,
            policy=policy,
        )
        return self._result(
            blockers=blockers,
            envelope=envelope,
            payload_hash=payload_hash,
            root_manifest=root_manifest,
            policy=policy,
        )

    def verify_transport_receipt(
        self,
        *,
        receipt: SignedTransportReceipt,
        root_manifest: TrustRootManifest,
        policy: VerificationPolicy,
        previous_receipt: SignedTransportReceipt | None = None,
    ) -> VerificationResult:
        if not isinstance(receipt, SignedTransportReceipt):
            raise TrustContractError("typed signed transport receipt is required")
        if not isinstance(
            root_manifest,
            (TransportTrustRootManifest, HumanTrustRootManifest),
        ):
            raise TrustContractError("typed trust-root manifest is required")
        if not isinstance(policy, VerificationPolicy):
            raise TrustContractError("typed verification policy is required")
        payload = receipt.payload
        blockers = self._verify_envelope(
            envelope=receipt.envelope,
            payload_hash=payload.contract_hash,
            root_manifest=root_manifest,
            policy=policy,
        )
        if not isinstance(root_manifest, TransportTrustRootManifest):
            blockers.append(VerificationBlocker.TRUST_DOMAIN_MISMATCH)
        else:
            if payload.claim_scope not in root_manifest.claim_scopes or (
                payload.claim_scope.value not in policy.allowed_claim_scopes
            ):
                blockers.append(VerificationBlocker.CLAIM_SCOPE_NOT_ALLOWED)
            if (
                payload.provider_id != root_manifest.provider_id
                or payload.endpoint_origin not in root_manifest.endpoint_origins
                or payload.requested_model_id not in root_manifest.model_ids
                or payload.observed_model_id not in root_manifest.model_ids
            ):
                blockers.append(VerificationBlocker.TRANSPORT_IDENTITY_INVALID)
            if (
                payload.tls_verification_policy_hash
                != root_manifest.tls_verification_policy_hash
            ):
                blockers.append(VerificationBlocker.TLS_EVIDENCE_INVALID)
        if (
            policy.expected_batch_manifest_hash is not None
            and payload.batch_manifest_hash != policy.expected_batch_manifest_hash
        ):
            blockers.append(VerificationBlocker.BATCH_ANCESTRY_INVALID)
        if payload.sequence_number == 0:
            if previous_receipt is not None:
                blockers.append(VerificationBlocker.CHAIN_ANCESTRY_INVALID)
        elif previous_receipt is None:
            blockers.append(VerificationBlocker.CHAIN_ANCESTRY_INVALID)
        elif (
            previous_receipt.payload.batch_id != payload.batch_id
            or previous_receipt.payload.batch_manifest_hash
            != payload.batch_manifest_hash
            or previous_receipt.payload.sequence_number + 1 != payload.sequence_number
            or payload.previous_receipt_hash != previous_receipt.contract_hash
        ):
            blockers.append(VerificationBlocker.CHAIN_ANCESTRY_INVALID)
        return self._result(
            blockers=blockers,
            envelope=receipt.envelope,
            payload_hash=payload.contract_hash,
            root_manifest=root_manifest,
            policy=policy,
        )

    def verify_transport_batch(
        self,
        *,
        batch: TransportReceiptBatch,
        root_manifest: TrustRootManifest,
        policy: VerificationPolicy,
    ) -> TransportBatchVerification:
        """Reverify every receipt and exact plan membership in one pass."""

        if not isinstance(batch, TransportReceiptBatch):
            raise TrustContractError("typed transport receipt batch is required")
        if not isinstance(
            root_manifest,
            (TransportTrustRootManifest, HumanTrustRootManifest),
        ):
            raise TrustContractError("typed trust-root manifest is required")
        if not isinstance(policy, VerificationPolicy):
            raise TrustContractError("typed verification policy is required")
        plan = batch.plan
        receipts = batch.receipts
        blockers: list[VerificationBlocker] = []
        if (
            policy.expected_batch_manifest_hash is None
            or policy.expected_batch_manifest_hash != plan.contract_hash
        ):
            blockers.append(VerificationBlocker.BATCH_ANCESTRY_INVALID)
        if not isinstance(root_manifest, TransportTrustRootManifest) or (
            plan.provider_id != root_manifest.provider_id
            or plan.endpoint_origin not in root_manifest.endpoint_origins
            or plan.requested_model_id not in root_manifest.model_ids
            or plan.expected_observed_model_id not in root_manifest.model_ids
        ):
            blockers.append(VerificationBlocker.TRANSPORT_IDENTITY_INVALID)

        if (
            len(receipts) != len(plan.entries)
            or len({item.contract_hash for item in receipts}) != len(receipts)
            or len({item.payload.invocation_id for item in receipts}) != len(receipts)
            or {item.payload.invocation_id for item in receipts}
            != {item.invocation_id for item in plan.entries}
        ):
            blockers.append(VerificationBlocker.BATCH_MEMBERSHIP_INVALID)
        if tuple(item.payload.sequence_number for item in receipts) != tuple(
            range(len(receipts))
        ) or tuple(item.payload.invocation_id for item in receipts) != tuple(
            item.invocation_id for item in plan.entries
        ):
            blockers.append(VerificationBlocker.BATCH_ORDER_INVALID)

        receipt_results: list[VerificationResult] = []
        previous: SignedTransportReceipt | None = None
        for index, receipt in enumerate(receipts):
            result = self.verify_transport_receipt(
                receipt=receipt,
                root_manifest=root_manifest,
                policy=policy,
                previous_receipt=previous,
            )
            receipt_results.append(result)
            blockers.extend(result.blockers)
            payload = receipt.payload
            if index < len(plan.entries):
                entry = plan.entries[index]
                if (
                    payload.sequence_number != entry.sequence_number
                    or payload.invocation_id != entry.invocation_id
                    or payload.criterion_id != entry.criterion_id
                    or payload.presentation_hash != entry.presentation_hash
                    or payload.data_attestation_hash != entry.data_attestation_hash
                    or payload.request_fingerprint != entry.request_fingerprint
                    or payload.request_bytes_hash != entry.request_bytes_hash
                    or payload.batch_id != plan.batch_id
                    or payload.batch_manifest_hash != plan.contract_hash
                    or payload.phase != plan.phase
                    or payload.comparison_block_id != plan.comparison_block_id
                    or payload.comparison_lock_hash != plan.comparison_lock_hash
                    or payload.design_hash != plan.design_hash
                    or payload.execution_authorization_hash
                    != plan.execution_authorization_hash
                    or payload.provider_id != plan.provider_id
                    or payload.endpoint_origin != plan.endpoint_origin
                    or payload.requested_model_id != plan.requested_model_id
                    or payload.observed_model_id != plan.expected_observed_model_id
                ):
                    blockers.append(VerificationBlocker.CALL_BINDING_INVALID)
            previous = receipt
        return TransportBatchVerification._create(
            batch=batch,
            root_manifest=root_manifest,
            policy=policy,
            receipt_results=receipt_results,
            blockers=blockers,
        )


__all__ = [
    "AuthorizationCheckpoint",
    "AuthorizationCheckpointManifest",
    "AuthorizationCheckpointRequirement",
    "DETERMINISTIC_TEST_ALGORITHM",
    "DeterministicTestSignatureVerifier",
    "HumanTrustRootManifest",
    "KeyAuthorization",
    "ProductionSignatureVerifier",
    "ProductionVerificationResult",
    "SignatureEnvelope",
    "SignedTransportReceipt",
    "TLSVerificationResult",
    "TransportBatchEntry",
    "TransportBatchPlan",
    "TransportBatchVerification",
    "TransportClaimScope",
    "TransportOutcome",
    "TransportReceiptBatch",
    "TransportReceiptPayload",
    "TransportTrustRootManifest",
    "TrustContractError",
    "TrustDomain",
    "TrustVerificationMode",
    "VerificationBlocker",
    "VerificationAuthority",
    "VerificationPolicy",
    "VerificationResult",
    "VerificationResultFactory",
]
