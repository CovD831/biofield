"""Offline-only MEAS0 V3 transport re-verification seam.

This module closes the deterministic, single-batch structural portion of D6.
It deliberately accepts only the deterministic test verifier and can derive
only ``simulated_nonclaim`` evidence.  It neither implements nor emulates a
production transport verifier, root, key, gateway, or formal result.

The legacy ``TransportBatchPlan`` has no previous-batch field.  Consequently
this module can prove the receipt chain *within* one batch, but it fails closed
for production use and records the cross-batch ancestry schema gap explicitly.
This is only the first-layer B9 offline slice; strict sealed-byte restore
codecs remain work for B8a/B8b.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Sequence

from .meas0_stage_cost import (
    PHASES,
    CostCategory,
    CostOutcome,
    StageCostEntry,
    StageCostLedger,
)
from .meas0_trust import (
    DeterministicTestSignatureVerifier,
    SignedTransportReceipt,
    TransportBatchPlan,
    TransportBatchVerification,
    TransportOutcome,
    TransportReceiptBatch,
    TransportTrustRootManifest,
    TrustDomain,
    TrustVerificationMode,
    VerificationPolicy,
)


LEGACY_PREVIOUS_BATCH_ANCESTRY_GAP = (
    "legacy TransportBatchPlan has no previous_batch_hash; only in-batch "
    "receipt ancestry is representable"
)
UNVERIFIED_STAGE_COST_MEASURANDS_GAP = (
    "raw provider usage, price, wall-time, token, monetary, arm, and cost-class "
    "authority are not present; StageCost is hash-linked but not fully verified"
)
PRODUCTION_TRANSPORT_SCHEMA_GAP = (
    "production transport verification is not implemented: approved external "
    "verifier authority, production roots/keys, raw gateway envelopes, and "
    "previous-batch ancestry are absent"
)

_SHA256_HEX_LENGTH = 64
_PHASE_POLICY_TOKEN = object()
_ATTEMPT_TOKEN = object()
_RESULT_TOKEN = object()


class TransportVerificationV3Error(ValueError):
    """Raised when V3 transport evidence cannot be reverified exactly."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_hash(value: Any) -> str:
    return _sha256(_canonical(value))


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TransportVerificationV3Error(f"{label} must be non-empty text")
    return value


def _digest(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_HEX_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise TransportVerificationV3Error(
            f"{label} must be a lowercase SHA-256 digest"
        )
    return value


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TransportVerificationV3Error(f"{label} must be a non-negative integer")
    return value


def _exact_serialized_equal(observed: object, expected: object) -> bool:
    if type(observed) is not type(expected):
        return False
    if isinstance(expected, Mapping):
        return set(observed) == set(expected) and all(
            _exact_serialized_equal(observed[key], expected[key]) for key in expected
        )
    if isinstance(expected, list):
        return len(observed) == len(expected) and all(
            _exact_serialized_equal(left, right)
            for left, right in zip(observed, expected, strict=True)
        )
    return observed == expected


def _decode_canonical_result_bytes(raw_bytes: bytes) -> Mapping[str, Any]:
    if type(raw_bytes) is not bytes:
        raise TransportVerificationV3Error(
            "transport reverification archive must be exact bytes"
        )

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise TransportVerificationV3Error(
                    "transport reverification archive contains duplicate fields"
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            raw_bytes.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                TransportVerificationV3Error(
                    f"transport reverification archive is non-finite: {token}"
                )
            ),
        )
    except TransportVerificationV3Error:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise TransportVerificationV3Error(
            "transport reverification archive is not strict JSON"
        ) from error
    if not isinstance(value, Mapping) or raw_bytes != _canonical(value):
        raise TransportVerificationV3Error(
            "transport reverification archive bytes are not canonical"
        )
    return value


class _HashBound:
    def _body(self) -> dict[str, Any]:
        raise NotImplementedError

    @property
    def contract_hash(self) -> str:
        return _canonical_hash(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "contract_hash": self.contract_hash}


@dataclass(frozen=True)
class PhaseTransportPolicyV3(_HashBound):
    """Test-scoped phase policy freezing nonce, retry, root, and batch scope."""

    schema: str
    policy_id: str
    phase: str
    transport_policy: VerificationPolicy
    root_manifest_hash: str
    revocation_snapshot_hash: str
    batch_plan_hash: str
    expected_nonces: tuple[str, ...]
    retry_parent_sequences: tuple[int | None, ...]
    stage_cost_start_sequence: int
    claim_scope: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._factory_token is not _PHASE_POLICY_TOKEN
            or self.schema != "biofield.meas0.phase_transport_policy.v3"
            or self.claim_scope != "simulated_nonclaim"
        ):
            raise TransportVerificationV3Error(
                "phase transport policy must be factory-derived simulated_nonclaim"
            )
        _text(self.policy_id, "phase transport policy_id")
        if self.phase not in PHASES:
            raise TransportVerificationV3Error(
                "phase transport policy phase is invalid"
            )
        if not isinstance(self.transport_policy, VerificationPolicy):
            raise TransportVerificationV3Error(
                "phase transport policy requires typed VerificationPolicy"
            )
        _digest(self.root_manifest_hash, "phase root manifest hash")
        _digest(self.revocation_snapshot_hash, "phase revocation snapshot hash")
        _digest(self.batch_plan_hash, "phase batch plan hash")
        nonces = tuple(
            _text(item, "expected transport nonce") for item in self.expected_nonces
        )
        if not nonces or len(nonces) != len(set(nonces)):
            raise TransportVerificationV3Error(
                "expected transport nonces must be non-empty and unique"
            )
        object.__setattr__(self, "expected_nonces", nonces)
        retries = tuple(self.retry_parent_sequences)
        if len(retries) != len(nonces):
            raise TransportVerificationV3Error(
                "nonce and retry membership must be exact"
            )
        for sequence, parent in enumerate(retries):
            if parent is None:
                continue
            _non_negative_int(parent, "retry parent sequence")
            if parent >= sequence:
                raise TransportVerificationV3Error(
                    "retry parent must identify an earlier attempt"
                )
        if retries[0] is not None:
            raise TransportVerificationV3Error(
                "first transport attempt cannot be a retry"
            )
        object.__setattr__(self, "retry_parent_sequences", retries)
        _non_negative_int(
            self.stage_cost_start_sequence,
            "StageCost start sequence",
        )
        transport = self.transport_policy
        if (
            transport.mode is not TrustVerificationMode.TEST_ONLY_CONTRACT
            or transport.trust_domain is not TrustDomain.TRANSPORT
            or transport.allow_test_only is not True
            or transport.allowed_root_manifest_hashes != (self.root_manifest_hash,)
            or transport.expected_batch_manifest_hash != self.batch_plan_hash
        ):
            raise TransportVerificationV3Error(
                "phase transport policy is not an exact test-only root/batch binding"
            )

    def _body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "policy_id": self.policy_id,
            "phase": self.phase,
            "transport_policy": self.transport_policy.to_dict(),
            "root_manifest_hash": self.root_manifest_hash,
            "revocation_snapshot_hash": self.revocation_snapshot_hash,
            "batch_plan_hash": self.batch_plan_hash,
            "expected_nonces": list(self.expected_nonces),
            "retry_parent_sequences": list(self.retry_parent_sequences),
            "stage_cost_start_sequence": self.stage_cost_start_sequence,
            "claim_scope": self.claim_scope,
        }

    @classmethod
    def create_simulated(
        cls,
        *,
        policy_id: str,
        phase: str,
        transport_policy: VerificationPolicy,
        root_manifest: TransportTrustRootManifest,
        batch_plan: TransportBatchPlan,
        expected_nonces: Sequence[str],
        retry_parent_sequences: Sequence[int | None],
        stage_cost_start_sequence: int,
    ) -> PhaseTransportPolicyV3:
        """Freeze one offline phase batch without asserting production policy."""

        if not isinstance(root_manifest, TransportTrustRootManifest):
            raise TransportVerificationV3Error(
                "typed transport root manifest is required"
            )
        if not isinstance(batch_plan, TransportBatchPlan):
            raise TransportVerificationV3Error("typed transport batch plan is required")
        if phase != batch_plan.phase:
            raise TransportVerificationV3Error(
                "phase transport policy and batch plan phase disagree"
            )
        if root_manifest.test_only is not True:
            raise TransportVerificationV3Error(
                "offline phase transport policy requires a test-only root"
            )
        if (
            transport_policy.expected_batch_manifest_hash != batch_plan.contract_hash
            or transport_policy.allowed_root_manifest_hashes
            != (root_manifest.contract_hash,)
        ):
            raise TransportVerificationV3Error(
                "phase transport policy does not bind this phase batch/root"
            )
        retries = tuple(retry_parent_sequences)
        if len(retries) != len(batch_plan.entries):
            raise TransportVerificationV3Error(
                "phase retry ancestry membership is not exact"
            )
        for sequence, parent_sequence in enumerate(retries):
            if parent_sequence is None:
                continue
            if (
                isinstance(parent_sequence, bool)
                or not isinstance(parent_sequence, int)
                or parent_sequence < 0
                or parent_sequence >= sequence
            ):
                raise TransportVerificationV3Error(
                    "phase retry ancestry parent is invalid"
                )
            attempt = batch_plan.entries[sequence]
            parent = batch_plan.entries[parent_sequence]
            if (
                attempt.criterion_id,
                attempt.presentation_hash,
                attempt.data_attestation_hash,
                attempt.request_fingerprint,
                attempt.request_bytes_hash,
            ) != (
                parent.criterion_id,
                parent.presentation_hash,
                parent.data_attestation_hash,
                parent.request_fingerprint,
                parent.request_bytes_hash,
            ):
                raise TransportVerificationV3Error(
                    "phase retry ancestry changed canonical "
                    "request/presentation/criterion"
                )
        return cls(
            schema="biofield.meas0.phase_transport_policy.v3",
            policy_id=policy_id,
            phase=phase,
            transport_policy=transport_policy,
            root_manifest_hash=root_manifest.contract_hash,
            revocation_snapshot_hash=root_manifest.revocation_snapshot_hash,
            batch_plan_hash=batch_plan.contract_hash,
            expected_nonces=tuple(expected_nonces),
            retry_parent_sequences=retries,
            stage_cost_start_sequence=stage_cost_start_sequence,
            claim_scope="simulated_nonclaim",
            _factory_token=_PHASE_POLICY_TOKEN,
        )


@dataclass(frozen=True)
class SimulatedTransportAttemptV3(_HashBound):
    """One factory-derived attempt/plan/receipt/bytes/StageCost binding."""

    schema: str
    phase: str
    sequence_number: int
    invocation_id: str
    plan_entry_hash: str
    receipt_hash: str
    receipt_payload_hash: str
    envelope_hash: str
    stage_cost_entry_hash: str
    stage_cost_sequence: int
    request_bytes_hash: str
    response_bytes_hash: str | None
    absent_response: bool
    nonce: str
    previous_receipt_hash: str | None
    retry_parent_sequence: int | None
    retry_parent_invocation_id: str | None
    retry_parent_stage_cost_hash: str | None
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._factory_token is not _ATTEMPT_TOKEN
            or self.schema != "biofield.meas0.simulated_transport_attempt.v3"
        ):
            raise TransportVerificationV3Error(
                "simulated transport attempt must be factory-derived"
            )
        if self.phase not in PHASES:
            raise TransportVerificationV3Error(
                "simulated transport attempt phase is invalid"
            )
        _non_negative_int(self.sequence_number, "attempt sequence")
        _text(self.invocation_id, "attempt invocation_id")
        for field_name in (
            "plan_entry_hash",
            "receipt_hash",
            "receipt_payload_hash",
            "envelope_hash",
            "stage_cost_entry_hash",
            "request_bytes_hash",
        ):
            _digest(getattr(self, field_name), field_name)
        _non_negative_int(self.stage_cost_sequence, "StageCost sequence")
        if self.response_bytes_hash is not None:
            _digest(self.response_bytes_hash, "response bytes hash")
        if not isinstance(self.absent_response, bool):
            raise TransportVerificationV3Error(
                "absent_response must be explicit boolean"
            )
        if self.absent_response is not (self.response_bytes_hash is None):
            raise TransportVerificationV3Error(
                "absent-response marker and response bytes hash disagree"
            )
        _text(self.nonce, "attempt nonce")
        if self.previous_receipt_hash is not None:
            _digest(self.previous_receipt_hash, "previous receipt hash")
        if self.retry_parent_sequence is not None:
            _non_negative_int(self.retry_parent_sequence, "retry parent sequence")
            if self.retry_parent_sequence >= self.sequence_number:
                raise TransportVerificationV3Error(
                    "retry parent must precede its attempt"
                )
        if self.retry_parent_invocation_id is not None:
            _text(
                self.retry_parent_invocation_id,
                "retry parent invocation_id",
            )
        retry_values = (
            self.retry_parent_sequence,
            self.retry_parent_invocation_id,
            self.retry_parent_stage_cost_hash,
        )
        if any(item is None for item in retry_values) and not all(
            item is None for item in retry_values
        ):
            raise TransportVerificationV3Error(
                "retry parent sequence/invocation/hash must be present together"
            )
        if self.retry_parent_stage_cost_hash is not None:
            _digest(
                self.retry_parent_stage_cost_hash,
                "retry parent StageCost hash",
            )

    def _body(self) -> dict[str, Any]:
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
            if field_name != "_factory_token"
        }


@dataclass(frozen=True)
class SimulatedTransportReverificationV3(_HashBound):
    """Successful offline verification result with no formal claim authority."""

    schema: str
    phase: str
    phase_policy_hash: str
    batch_hash: str
    batch_verification_hash: str
    root_manifest_hash: str
    revocation_snapshot_hash: str
    stage_cost_ledger_hash: str
    stage_cost_start_sequence: int
    attempts: tuple[SimulatedTransportAttemptV3, ...]
    transport_membership_verified: bool
    cost_verified: bool
    claim_scope: str
    evidence_class: str
    production_authorized: bool
    formal_result: bool
    formal_eligible: bool
    schema_gaps: tuple[str, ...]
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._factory_token is not _RESULT_TOKEN
            or self.schema != "biofield.meas0.transport_reverification.v3"
            or self.transport_membership_verified is not True
            or self.cost_verified is not False
            or self.claim_scope != "simulated_nonclaim"
            or self.evidence_class != "test_only"
            or self.production_authorized is not False
            or self.formal_result is not False
            or self.formal_eligible is not False
        ):
            raise TransportVerificationV3Error(
                "transport reverification result must be factory-derived "
                "simulated_nonclaim"
            )
        if self.phase not in PHASES:
            raise TransportVerificationV3Error(
                "transport reverification phase is invalid"
            )
        for field_name in (
            "phase_policy_hash",
            "batch_hash",
            "batch_verification_hash",
            "root_manifest_hash",
            "revocation_snapshot_hash",
            "stage_cost_ledger_hash",
        ):
            _digest(getattr(self, field_name), field_name)
        _non_negative_int(
            self.stage_cost_start_sequence,
            "StageCost start sequence",
        )
        attempts = tuple(self.attempts)
        if (
            not attempts
            or not all(
                isinstance(item, SimulatedTransportAttemptV3) for item in attempts
            )
            or tuple(item.sequence_number for item in attempts)
            != tuple(range(len(attempts)))
            or any(item.phase != self.phase for item in attempts)
        ):
            raise TransportVerificationV3Error(
                "transport attempt membership must be exact and ordered"
            )
        if tuple(item.stage_cost_sequence for item in attempts) != tuple(
            range(
                self.stage_cost_start_sequence,
                self.stage_cost_start_sequence + len(attempts),
            )
        ):
            raise TransportVerificationV3Error(
                "StageCost global sequence does not match the frozen batch slice"
            )
        for sequence, attempt in enumerate(attempts):
            parent_sequence = attempt.retry_parent_sequence
            if parent_sequence is None:
                continue
            parent = attempts[parent_sequence]
            if (
                parent_sequence >= sequence
                or attempt.retry_parent_invocation_id != parent.invocation_id
                or attempt.retry_parent_stage_cost_hash != parent.stage_cost_entry_hash
            ):
                raise TransportVerificationV3Error(
                    "retry parent invocation/StageCost ancestry changed"
                )
        object.__setattr__(self, "attempts", attempts)
        if self.schema_gaps != (
            LEGACY_PREVIOUS_BATCH_ANCESTRY_GAP,
            UNVERIFIED_STAGE_COST_MEASURANDS_GAP,
        ):
            raise TransportVerificationV3Error(
                "transport and StageCost schema gaps must remain explicit"
            )

    def _body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "phase": self.phase,
            "phase_policy_hash": self.phase_policy_hash,
            "batch_hash": self.batch_hash,
            "batch_verification_hash": self.batch_verification_hash,
            "root_manifest_hash": self.root_manifest_hash,
            "revocation_snapshot_hash": self.revocation_snapshot_hash,
            "stage_cost_ledger_hash": self.stage_cost_ledger_hash,
            "stage_cost_start_sequence": self.stage_cost_start_sequence,
            "attempts": [item.to_dict() for item in self.attempts],
            "transport_membership_verified": self.transport_membership_verified,
            "cost_verified": self.cost_verified,
            "claim_scope": self.claim_scope,
            "evidence_class": self.evidence_class,
            "production_authorized": self.production_authorized,
            "formal_result": self.formal_result,
            "formal_eligible": self.formal_eligible,
            "schema_gaps": list(self.schema_gaps),
        }

    def to_canonical_bytes(self) -> bytes:
        """Serialize test-only transport evidence for typed fresh-process replay."""

        return _canonical(self.to_dict())

    @classmethod
    def restore_from_canonical_bytes(
        cls,
        raw_bytes: bytes,
        *,
        phase_policy: PhaseTransportPolicyV3,
        batch: TransportReceiptBatch,
        root_manifest: TransportTrustRootManifest,
        stage_cost_ledger: StageCostLedger,
        request_bytes: Sequence[bytes],
        response_bytes: Sequence[bytes | None],
        verifier: DeterministicTestSignatureVerifier,
    ) -> SimulatedTransportReverificationV3:
        """Restore only after re-running the typed transport derivation."""

        value = _decode_canonical_result_bytes(raw_bytes)
        restored = reverify_simulated_transport_phase_v3(
            phase_policy=phase_policy,
            batch=batch,
            root_manifest=root_manifest,
            stage_cost_ledger=stage_cost_ledger,
            request_bytes=request_bytes,
            response_bytes=response_bytes,
            verifier=verifier,
        )
        if not _exact_serialized_equal(value, restored.to_dict()):
            raise TransportVerificationV3Error(
                "serialized transport reverification disagrees with typed sources"
            )
        return restored


def _used_key_authorization(
    *,
    receipt: SignedTransportReceipt,
    root_manifest: TransportTrustRootManifest,
) -> object:
    envelope = receipt.envelope
    matches = tuple(
        item
        for item in root_manifest.key_authorizations
        if item.key_fingerprint == envelope.key_fingerprint
        and item.algorithm_id == envelope.algorithm_id
        and item.role_id == envelope.role_id
    )
    if len(matches) != 1:
        raise TransportVerificationV3Error(
            "transport root does not contain one exact signing authorization"
        )
    authorization = matches[0]
    if (
        authorization.allowed_phases != (receipt.payload.phase,)
        or receipt.payload.purpose not in authorization.allowed_purposes
    ):
        raise TransportVerificationV3Error(
            "transport root key scope is not phase-specific"
        )
    return authorization


def _validate_raw_bytes(
    *,
    request: object,
    response: object,
    receipt: SignedTransportReceipt,
) -> tuple[str, str | None]:
    if not isinstance(request, bytes):
        raise TransportVerificationV3Error(
            "canonical request bytes must be typed bytes"
        )
    request_hash = _sha256(request)
    payload = receipt.payload
    if request_hash != payload.request_bytes_hash:
        raise TransportVerificationV3Error(
            "canonical request bytes do not match the receipt/plan"
        )
    if response is None:
        if payload.response_present:
            raise TransportVerificationV3Error(
                "response bytes are missing for a response-bearing receipt"
            )
        return request_hash, None
    if not isinstance(response, bytes):
        raise TransportVerificationV3Error(
            "canonical response bytes must be bytes or explicit absence"
        )
    response_hash = _sha256(response)
    if (
        not payload.response_present
        or payload.response_hash != response_hash
        or payload.response_size != len(response)
    ):
        raise TransportVerificationV3Error(
            "canonical response bytes do not match the receipt"
        )
    return request_hash, response_hash


def _validate_stage_cost(
    *,
    entry: StageCostEntry,
    receipt: SignedTransportReceipt,
    phase: str,
    response: bytes | None,
) -> None:
    payload = receipt.payload
    expected_outcome = (
        CostOutcome.SUCCEEDED
        if payload.outcome is TransportOutcome.SUCCESS
        else CostOutcome.FAILED
    )
    if (
        entry.phase != phase
        or entry.category is not CostCategory.JUDGE
        or entry.outcome is not expected_outcome
        or entry.failure_code != payload.failure_code
        or entry.request_hash != payload.request_fingerprint
        or entry.call_hash != payload.contract_hash
        or entry.raw_receipt_hash != receipt.contract_hash
        or entry.provider_id != payload.provider_id
        or entry.model_id != payload.observed_model_id
        or entry.bytes_transferred != (len(response) if response is not None else 0)
    ):
        raise TransportVerificationV3Error(
            "Judge attempt, receipt, and StageCost entry disagree"
        )


def reverify_simulated_transport_phase_v3(
    *,
    phase_policy: PhaseTransportPolicyV3,
    batch: TransportReceiptBatch,
    root_manifest: TransportTrustRootManifest,
    stage_cost_ledger: StageCostLedger,
    request_bytes: Sequence[bytes],
    response_bytes: Sequence[bytes | None],
    verifier: DeterministicTestSignatureVerifier,
) -> SimulatedTransportReverificationV3:
    """Reverify one exact test batch and derive only simulated evidence."""

    if not isinstance(phase_policy, PhaseTransportPolicyV3):
        raise TransportVerificationV3Error("typed phase transport policy is required")
    if not isinstance(batch, TransportReceiptBatch):
        raise TransportVerificationV3Error("typed transport receipt batch is required")
    if not isinstance(root_manifest, TransportTrustRootManifest):
        raise TransportVerificationV3Error("typed transport root manifest is required")
    if not isinstance(stage_cost_ledger, StageCostLedger):
        raise TransportVerificationV3Error("typed StageCost ledger is required")
    if type(verifier) is not DeterministicTestSignatureVerifier:
        raise TransportVerificationV3Error(
            "offline transport seam accepts only the deterministic test verifier"
        )
    plan = batch.plan
    if (
        plan.phase != phase_policy.phase
        or phase_policy.batch_plan_hash != plan.contract_hash
    ):
        raise TransportVerificationV3Error(
            "phase-specific transport policy/batch ancestry changed"
        )
    if (
        root_manifest.test_only is not True
        or phase_policy.root_manifest_hash != root_manifest.contract_hash
        or phase_policy.revocation_snapshot_hash
        != root_manifest.revocation_snapshot_hash
    ):
        raise TransportVerificationV3Error(
            "phase-specific transport root/revocation binding changed"
        )
    collections = (
        tuple(plan.entries),
        tuple(batch.receipts),
        tuple(request_bytes),
        tuple(response_bytes),
        phase_policy.expected_nonces,
        phase_policy.retry_parent_sequences,
    )
    if len({len(items) for items in collections}) != 1 or not plan.entries:
        raise TransportVerificationV3Error(
            "transport batch attempt membership is missing or extra"
        )
    start = phase_policy.stage_cost_start_sequence
    end = start + len(plan.entries)
    stage_entries = stage_cost_ledger.entries[start:end]
    if len(stage_entries) != len(plan.entries):
        raise TransportVerificationV3Error(
            "StageCost batch membership is missing or extra"
        )
    receipt_hashes = {item.contract_hash for item in batch.receipts}
    all_matching_stage_entries = tuple(
        item
        for item in stage_cost_ledger.entries
        if item.raw_receipt_hash in receipt_hashes
    )
    if all_matching_stage_entries != stage_entries:
        raise TransportVerificationV3Error(
            "StageCost receipt membership/order is not exact"
        )
    for receipt in batch.receipts:
        _used_key_authorization(
            receipt=receipt,
            root_manifest=root_manifest,
        )
    try:
        batch_verification = verifier.verify_transport_batch(
            batch=batch,
            root_manifest=root_manifest,
            policy=phase_policy.transport_policy,
        )
    except Exception as error:
        raise TransportVerificationV3Error(
            "test transport verifier failed closed"
        ) from error
    if (
        type(batch_verification) is not TransportBatchVerification
        or not batch_verification.contract_verified
        or batch_verification.production_authorized
        or batch_verification.claim_scope != "contract_only"
    ):
        raise TransportVerificationV3Error("transport batch verification failed closed")

    attempts: list[SimulatedTransportAttemptV3] = []
    for sequence, (
        plan_entry,
        receipt,
        request,
        response,
        expected_nonce,
        retry_parent_sequence,
        stage_entry,
    ) in enumerate(
        zip(*collections, stage_entries, strict=True),
    ):
        payload = receipt.payload
        if (
            plan_entry.sequence_number != sequence
            or payload.sequence_number != sequence
            or payload.nonce != expected_nonce
            or receipt.envelope.nonce != expected_nonce
            or receipt.envelope.sequence_number != sequence
        ):
            raise TransportVerificationV3Error(
                "transport nonce/sequence binding changed"
            )
        expected_previous = (
            batch.receipts[sequence - 1].contract_hash if sequence else None
        )
        if payload.previous_receipt_hash != expected_previous:
            raise TransportVerificationV3Error(
                "transport previous receipt ancestry changed"
            )
        request_hash, response_hash = _validate_raw_bytes(
            request=request,
            response=response,
            receipt=receipt,
        )
        if request_hash != plan_entry.request_bytes_hash:
            raise TransportVerificationV3Error(
                "canonical request bytes do not match the phase plan"
            )
        _validate_stage_cost(
            entry=stage_entry,
            receipt=receipt,
            phase=phase_policy.phase,
            response=response,
        )
        expected_retry_hash = (
            stage_entries[retry_parent_sequence].contract_hash
            if retry_parent_sequence is not None
            else None
        )
        if (
            stage_entry.sequence != start + sequence
            or stage_entry.retry_count != int(retry_parent_sequence is not None)
            or stage_entry.retry_of_entry_hash != expected_retry_hash
        ):
            raise TransportVerificationV3Error(
                "transport retry ancestry disagrees with StageCost"
            )
        attempts.append(
            SimulatedTransportAttemptV3(
                schema="biofield.meas0.simulated_transport_attempt.v3",
                phase=phase_policy.phase,
                sequence_number=sequence,
                invocation_id=payload.invocation_id,
                plan_entry_hash=plan_entry.contract_hash,
                receipt_hash=receipt.contract_hash,
                receipt_payload_hash=payload.contract_hash,
                envelope_hash=receipt.envelope.contract_hash,
                stage_cost_entry_hash=stage_entry.contract_hash,
                stage_cost_sequence=stage_entry.sequence,
                request_bytes_hash=request_hash,
                response_bytes_hash=response_hash,
                absent_response=response is None,
                nonce=payload.nonce,
                previous_receipt_hash=payload.previous_receipt_hash,
                retry_parent_sequence=retry_parent_sequence,
                retry_parent_invocation_id=(
                    plan.entries[retry_parent_sequence].invocation_id
                    if retry_parent_sequence is not None
                    else None
                ),
                retry_parent_stage_cost_hash=expected_retry_hash,
                _factory_token=_ATTEMPT_TOKEN,
            )
        )

    return SimulatedTransportReverificationV3(
        schema="biofield.meas0.transport_reverification.v3",
        phase=phase_policy.phase,
        phase_policy_hash=phase_policy.contract_hash,
        batch_hash=batch.contract_hash,
        batch_verification_hash=batch_verification.contract_hash,
        root_manifest_hash=root_manifest.contract_hash,
        revocation_snapshot_hash=root_manifest.revocation_snapshot_hash,
        stage_cost_ledger_hash=stage_cost_ledger.contract_hash,
        stage_cost_start_sequence=start,
        attempts=tuple(attempts),
        transport_membership_verified=True,
        cost_verified=False,
        claim_scope="simulated_nonclaim",
        evidence_class="test_only",
        production_authorized=False,
        formal_result=False,
        formal_eligible=False,
        schema_gaps=(
            LEGACY_PREVIOUS_BATCH_ANCESTRY_GAP,
            UNVERIFIED_STAGE_COST_MEASURANDS_GAP,
        ),
        _factory_token=_RESULT_TOKEN,
    )


def require_production_transport_verification_v3(*, verifier: object) -> None:
    """Fail closed until real external authority and missing schemas exist."""

    del verifier
    raise TransportVerificationV3Error(PRODUCTION_TRANSPORT_SCHEMA_GAP)


__all__ = [
    "LEGACY_PREVIOUS_BATCH_ANCESTRY_GAP",
    "PRODUCTION_TRANSPORT_SCHEMA_GAP",
    "UNVERIFIED_STAGE_COST_MEASURANDS_GAP",
    "PhaseTransportPolicyV3",
    "SimulatedTransportAttemptV3",
    "SimulatedTransportReverificationV3",
    "TransportVerificationV3Error",
    "require_production_transport_verification_v3",
    "reverify_simulated_transport_phase_v3",
]
