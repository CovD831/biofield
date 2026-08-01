"""Offline-only V3 Gate assessment preview contracts.

This module deliberately does not implement a claim-bearing Gate M terminal.
It reports coverage diagnostics from membership in a strict, sealed,
test-verifier index.  Because that index is created from caller-provided
simulated membership rather than a B8b verified snapshot, every §13.1 fact
remains ``UNKNOWN`` and Gate M remains ``NOT_EVALUATED``.

The production terminal remains a fail-closed integration seam until B8b can
provide a fresh-replayed production snapshot and frozen §13.2 inputs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, NoReturn, Sequence


HARD_GATE_CRITERION_IDS = tuple(f"13.1.{index}" for index in range(1, 9))
REQUIRED_GATE_CLOSURE_ROLES = (
    "confirmatory_run",
    "write_once_store",
    "fresh_replay_receipt",
    "production_trust_qualification",
    "lifecycle",
    "transport_receipts",
    "stage_cost",
    "detection_oracle",
    "gold",
    "protected_vault",
)
B8B_PRODUCTION_SNAPSHOT_GAP = (
    "B8b fresh-replayed production verified snapshot and frozen §13.2 "
    "performance inputs are unavailable; no formal Gate M terminal can be "
    "derived."
)

_SLICE_SCHEMA = "meas0.gate-evidence-slice.v3"
_INDEX_SCHEMA = "meas0.simulated-sealed-gate-evidence-index.v3"
_FACT_SCHEMA = "meas0.gate-criterion-fact.v3"
_ASSESSMENT_SCHEMA = "meas0.gate-assessment-preview.v3"
_SLICE_TOKEN = object()
_INDEX_TOKEN = object()
_FACT_TOKEN = object()
_ASSESSMENT_TOKEN = object()


class GateAssessmentV3Error(ValueError):
    """Gate preview input is malformed or attempts to cross a claim boundary."""


class CriterionFactStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class GateMPreviewState(str, Enum):
    NOT_EVALUATED = "not_evaluated"


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
        raise GateAssessmentV3Error(
            "Gate assessment value is not canonical JSON"
        ) from error


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise GateAssessmentV3Error(f"{label} must be a lowercase SHA-256")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GateAssessmentV3Error(f"{label} must be non-empty text")
    return value


def _canonical_ids(values: Sequence[str], label: str) -> tuple[str, ...]:
    result = tuple(values)
    if (
        any(not isinstance(item, str) or not item.strip() for item in result)
        or len(set(result)) != len(result)
        or result != tuple(sorted(result))
    ):
        raise GateAssessmentV3Error(
            f"{label} must be unique, non-empty, and canonically ordered"
        )
    return result


def _strict_json(raw: bytes) -> object:
    if not isinstance(raw, bytes):
        raise GateAssessmentV3Error("sealed Gate index must be bytes")

    def reject_duplicate(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise GateAssessmentV3Error(
                    "sealed Gate index contains duplicate JSON keys"
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate,
            parse_constant=lambda token: (_ for _ in ()).throw(
                GateAssessmentV3Error(
                    f"sealed Gate index contains non-finite number: {token}"
                )
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GateAssessmentV3Error("sealed Gate index is not strict JSON") from error
    if raw != _canonical_bytes(value):
        raise GateAssessmentV3Error("sealed Gate index bytes are not canonical")
    return value


def _exact_mapping(
    value: object,
    expected_fields: set[str],
    label: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        raise GateAssessmentV3Error(f"{label} has an invalid serialized shape")
    return value


def _exact_serialized_equal(observed: object, expected: object) -> bool:
    if type(observed) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(observed) == set(expected) and all(
            _exact_serialized_equal(observed[key], expected[key]) for key in expected
        )
    if isinstance(expected, list):
        return len(observed) == len(expected) and all(
            _exact_serialized_equal(left, right)
            for left, right in zip(observed, expected, strict=True)
        )
    return observed == expected


@dataclass(frozen=True)
class GateEvidenceSliceV3:
    """One sealed simulated membership-coverage diagnostic.

    Member coverage and caller-flagged members remain useful for attacking the
    future B8b adapter, but cannot determine a Gate fact.  No
    pass/count/coverage Boolean is accepted or stored.
    """

    schema: str
    version: int
    criterion_id: str
    comparison_block_id: str
    common_ancestry_hash: str
    required_member_ids: tuple[str, ...]
    observed_member_ids: tuple[str, ...]
    violation_member_ids: tuple[str, ...]
    member_evidence_refs: tuple[tuple[str, str], ...]
    slice_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _SLICE_TOKEN:
            raise GateAssessmentV3Error("Gate evidence slice must be factory-derived")
        if (
            self.schema != _SLICE_SCHEMA
            or self.version != 3
            or self.criterion_id not in HARD_GATE_CRITERION_IDS
        ):
            raise GateAssessmentV3Error("Gate evidence slice schema is invalid")
        _text(self.comparison_block_id, "comparison_block_id")
        _digest(self.common_ancestry_hash, "common_ancestry_hash")
        required = _canonical_ids(self.required_member_ids, "required members")
        observed = _canonical_ids(self.observed_member_ids, "observed members")
        violations = _canonical_ids(self.violation_member_ids, "violation members")
        if not required:
            raise GateAssessmentV3Error(
                "Gate evidence slice requires a non-empty frozen population"
            )
        if not set(observed) <= set(required):
            raise GateAssessmentV3Error(
                "observed Gate members are outside the frozen population"
            )
        if not set(violations) <= set(observed):
            raise GateAssessmentV3Error("violation members must have observed evidence")
        refs = tuple(self.member_evidence_refs)
        if tuple(member_id for member_id, _ in refs) != observed or len(refs) != len(
            observed
        ):
            raise GateAssessmentV3Error(
                "observed Gate members require exact evidence refs"
            )
        for member_id, digest in refs:
            _text(member_id, "evidence member identity")
            _digest(digest, f"evidence ref for {member_id}")
        _digest(self.slice_hash, "Gate evidence slice hash")
        if self.slice_hash != _canonical_hash(self._body()):
            raise GateAssessmentV3Error("Gate evidence slice hash changed")

    def _body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "criterion_id": self.criterion_id,
            "comparison_block_id": self.comparison_block_id,
            "common_ancestry_hash": self.common_ancestry_hash,
            "required_member_ids": list(self.required_member_ids),
            "observed_member_ids": list(self.observed_member_ids),
            "violation_member_ids": list(self.violation_member_ids),
            "member_evidence_refs": [
                {"member_id": member_id, "evidence_ref": evidence_ref}
                for member_id, evidence_ref in self.member_evidence_refs
            ],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "slice_hash": self.slice_hash}

    @classmethod
    def create(
        cls,
        *,
        criterion_id: str,
        comparison_block_id: str,
        common_ancestry_hash: str,
        required_member_ids: Sequence[str],
        observed_member_ids: Sequence[str],
        violation_member_ids: Sequence[str],
        member_evidence_refs: Sequence[tuple[str, str]],
    ) -> GateEvidenceSliceV3:
        body = {
            "schema": _SLICE_SCHEMA,
            "version": 3,
            "criterion_id": criterion_id,
            "comparison_block_id": comparison_block_id,
            "common_ancestry_hash": common_ancestry_hash,
            "required_member_ids": list(required_member_ids),
            "observed_member_ids": list(observed_member_ids),
            "violation_member_ids": list(violation_member_ids),
            "member_evidence_refs": [
                {"member_id": member_id, "evidence_ref": evidence_ref}
                for member_id, evidence_ref in member_evidence_refs
            ],
        }
        return cls(
            schema=_SLICE_SCHEMA,
            version=3,
            criterion_id=criterion_id,
            comparison_block_id=comparison_block_id,
            common_ancestry_hash=common_ancestry_hash,
            required_member_ids=tuple(required_member_ids),
            observed_member_ids=tuple(observed_member_ids),
            violation_member_ids=tuple(violation_member_ids),
            member_evidence_refs=tuple(member_evidence_refs),
            slice_hash=_canonical_hash(body),
            _factory_token=_SLICE_TOKEN,
        )

    @classmethod
    def restore_from_dict(cls, value: object) -> GateEvidenceSliceV3:
        fields = {
            "schema",
            "version",
            "criterion_id",
            "comparison_block_id",
            "common_ancestry_hash",
            "required_member_ids",
            "observed_member_ids",
            "violation_member_ids",
            "member_evidence_refs",
            "slice_hash",
        }
        source = _exact_mapping(value, fields, "Gate evidence slice")
        for name in (
            "required_member_ids",
            "observed_member_ids",
            "violation_member_ids",
            "member_evidence_refs",
        ):
            if not isinstance(source[name], list):
                raise GateAssessmentV3Error(
                    "Gate evidence slice has an invalid serialized shape"
                )
        refs: list[tuple[str, str]] = []
        for item in source["member_evidence_refs"]:
            entry = _exact_mapping(
                item,
                {"member_id", "evidence_ref"},
                "Gate member evidence ref",
            )
            refs.append((entry["member_id"], entry["evidence_ref"]))
        restored = cls.create(
            criterion_id=source["criterion_id"],
            comparison_block_id=source["comparison_block_id"],
            common_ancestry_hash=source["common_ancestry_hash"],
            required_member_ids=source["required_member_ids"],
            observed_member_ids=source["observed_member_ids"],
            violation_member_ids=source["violation_member_ids"],
            member_evidence_refs=refs,
        )
        if not _exact_serialized_equal(dict(source), restored.to_dict()):
            raise GateAssessmentV3Error(
                "Gate evidence slice is not its exact derived serialization"
            )
        return restored


@dataclass(frozen=True)
class SimulatedSealedGateEvidenceIndexV3:
    """Strict test-verifier index; never production Gate authority."""

    schema: str
    version: int
    phase: str
    comparison_block_id: str
    common_ancestry_hash: str
    source_lock_hash: str
    sealed_package_hash: str
    closure_evidence_refs: tuple[tuple[str, str], ...]
    criterion_slices: tuple[GateEvidenceSliceV3, ...]
    index_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._factory_token is not _INDEX_TOKEN:
            raise GateAssessmentV3Error(
                "sealed Gate evidence index must be factory-derived"
            )
        if (
            self.schema != _INDEX_SCHEMA
            or self.version != 3
            or self.phase != "confirmatory"
        ):
            raise GateAssessmentV3Error("sealed Gate evidence index schema is invalid")
        _text(self.comparison_block_id, "comparison_block_id")
        for name in (
            "common_ancestry_hash",
            "source_lock_hash",
            "sealed_package_hash",
        ):
            _digest(getattr(self, name), name)
        closure = tuple(self.closure_evidence_refs)
        roles = tuple(role for role, _ in closure)
        expected_subsequence = tuple(
            role for role in REQUIRED_GATE_CLOSURE_ROLES if role in set(roles)
        )
        if roles != expected_subsequence or len(set(roles)) != len(roles):
            raise GateAssessmentV3Error(
                "Gate closure evidence roles are not canonically ordered"
            )
        for role, digest in closure:
            _text(role, "Gate closure role")
            _digest(digest, f"Gate closure evidence ref for {role}")
        slices = tuple(self.criterion_slices)
        if not all(isinstance(item, GateEvidenceSliceV3) for item in slices):
            raise GateAssessmentV3Error("Gate criteria require typed evidence slices")
        criterion_ids = tuple(item.criterion_id for item in slices)
        expected_ids = tuple(
            criterion_id
            for criterion_id in HARD_GATE_CRITERION_IDS
            if criterion_id in set(criterion_ids)
        )
        if criterion_ids != expected_ids or len(set(criterion_ids)) != len(
            criterion_ids
        ):
            raise GateAssessmentV3Error(
                "Gate evidence slices must be unique and ordered"
            )
        if any(
            item.comparison_block_id != self.comparison_block_id
            or item.common_ancestry_hash != self.common_ancestry_hash
            for item in slices
        ):
            raise GateAssessmentV3Error(
                "Gate evidence slices do not share common ancestry"
            )
        _digest(self.index_hash, "Gate evidence index hash")
        if self.index_hash != _canonical_hash(self._body()):
            raise GateAssessmentV3Error("sealed Gate evidence index hash changed")

    @property
    def claim_scope(self) -> str:
        return "simulated_nonclaim"

    @property
    def verification_scope(self) -> str:
        return "test_verifier"

    @property
    def test_only(self) -> bool:
        return True

    @property
    def production_authorized(self) -> bool:
        return False

    @property
    def formal_eligible(self) -> bool:
        return False

    def _body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "version": self.version,
            "phase": self.phase,
            "comparison_block_id": self.comparison_block_id,
            "common_ancestry_hash": self.common_ancestry_hash,
            "source_lock_hash": self.source_lock_hash,
            "sealed_package_hash": self.sealed_package_hash,
            "closure_evidence_refs": [
                {"role": role, "evidence_ref": evidence_ref}
                for role, evidence_ref in self.closure_evidence_refs
            ],
            "criterion_slices": [item.to_dict() for item in self.criterion_slices],
            "verification_scope": self.verification_scope,
            "claim_scope": self.claim_scope,
            "test_only": self.test_only,
            "production_authorized": self.production_authorized,
            "formal_eligible": self.formal_eligible,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "index_hash": self.index_hash}

    def to_canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @classmethod
    def create(
        cls,
        *,
        comparison_block_id: str,
        common_ancestry_hash: str,
        source_lock_hash: str,
        sealed_package_hash: str,
        closure_evidence_refs: Sequence[tuple[str, str]],
        criterion_slices: Sequence[GateEvidenceSliceV3],
    ) -> SimulatedSealedGateEvidenceIndexV3:
        body = {
            "schema": _INDEX_SCHEMA,
            "version": 3,
            "phase": "confirmatory",
            "comparison_block_id": comparison_block_id,
            "common_ancestry_hash": common_ancestry_hash,
            "source_lock_hash": source_lock_hash,
            "sealed_package_hash": sealed_package_hash,
            "closure_evidence_refs": [
                {"role": role, "evidence_ref": evidence_ref}
                for role, evidence_ref in closure_evidence_refs
            ],
            "criterion_slices": [item.to_dict() for item in criterion_slices],
            "verification_scope": "test_verifier",
            "claim_scope": "simulated_nonclaim",
            "test_only": True,
            "production_authorized": False,
            "formal_eligible": False,
        }
        return cls(
            schema=_INDEX_SCHEMA,
            version=3,
            phase="confirmatory",
            comparison_block_id=comparison_block_id,
            common_ancestry_hash=common_ancestry_hash,
            source_lock_hash=source_lock_hash,
            sealed_package_hash=sealed_package_hash,
            closure_evidence_refs=tuple(closure_evidence_refs),
            criterion_slices=tuple(criterion_slices),
            index_hash=_canonical_hash(body),
            _factory_token=_INDEX_TOKEN,
        )

    @classmethod
    def restore_from_sealed_bytes(
        cls,
        sealed_bytes: bytes,
        *,
        expected_sha256: str,
    ) -> SimulatedSealedGateEvidenceIndexV3:
        expected = _digest(expected_sha256, "expected sealed bytes hash")
        if hashlib.sha256(sealed_bytes).hexdigest() != expected:
            raise GateAssessmentV3Error("sealed bytes hash does not match authority")
        source = _exact_mapping(
            _strict_json(sealed_bytes),
            {
                "schema",
                "version",
                "phase",
                "comparison_block_id",
                "common_ancestry_hash",
                "source_lock_hash",
                "sealed_package_hash",
                "closure_evidence_refs",
                "criterion_slices",
                "verification_scope",
                "claim_scope",
                "test_only",
                "production_authorized",
                "formal_eligible",
                "index_hash",
            },
            "sealed Gate evidence index",
        )
        if (
            source["verification_scope"] != "test_verifier"
            or source["claim_scope"] != "simulated_nonclaim"
            or source["test_only"] is not True
            or source["production_authorized"] is not False
            or source["formal_eligible"] is not False
        ):
            raise GateAssessmentV3Error(
                "sealed Gate evidence index violates its nonclaim boundary"
            )
        if not isinstance(source["closure_evidence_refs"], list) or not isinstance(
            source["criterion_slices"],
            list,
        ):
            raise GateAssessmentV3Error(
                "sealed Gate evidence index has an invalid serialized shape"
            )
        closure_refs: list[tuple[str, str]] = []
        for item in source["closure_evidence_refs"]:
            entry = _exact_mapping(
                item,
                {"role", "evidence_ref"},
                "Gate closure evidence ref",
            )
            closure_refs.append((entry["role"], entry["evidence_ref"]))
        slices = tuple(
            GateEvidenceSliceV3.restore_from_dict(item)
            for item in source["criterion_slices"]
        )
        restored = cls.create(
            comparison_block_id=source["comparison_block_id"],
            common_ancestry_hash=source["common_ancestry_hash"],
            source_lock_hash=source["source_lock_hash"],
            sealed_package_hash=source["sealed_package_hash"],
            closure_evidence_refs=closure_refs,
            criterion_slices=slices,
        )
        if not _exact_serialized_equal(dict(source), restored.to_dict()):
            raise GateAssessmentV3Error(
                "sealed Gate evidence index is not its exact derived serialization"
            )
        return restored


@dataclass(frozen=True)
class GateCriterionFactV3:
    schema: str
    criterion_id: str
    status: CriterionFactStatus
    required_member_ids: tuple[str, ...]
    observed_member_ids: tuple[str, ...]
    missing_member_ids: tuple[str, ...]
    violation_member_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    source_slice_hash: str | None
    reason_code: str
    fact_hash: str
    _derivation_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._derivation_token is not _FACT_TOKEN:
            raise GateAssessmentV3Error("Gate criterion fact must be derived")
        if (
            self.schema != _FACT_SCHEMA
            or self.criterion_id not in HARD_GATE_CRITERION_IDS
            or not isinstance(self.status, CriterionFactStatus)
            or self.status is not CriterionFactStatus.UNKNOWN
        ):
            raise GateAssessmentV3Error(
                "simulated Gate criterion facts must remain UNKNOWN"
            )
        for name in (
            "required_member_ids",
            "observed_member_ids",
            "missing_member_ids",
            "violation_member_ids",
            "evidence_refs",
        ):
            _canonical_ids(getattr(self, name), name)
        if self.source_slice_hash is not None:
            _digest(self.source_slice_hash, "source Gate evidence slice hash")
        _text(self.reason_code, "Gate criterion reason code")
        _digest(self.fact_hash, "Gate criterion fact hash")
        if self.fact_hash != _canonical_hash(self._body()):
            raise GateAssessmentV3Error("Gate criterion fact hash changed")

    def _body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "criterion_id": self.criterion_id,
            "status": self.status.value,
            "required_member_ids": list(self.required_member_ids),
            "observed_member_ids": list(self.observed_member_ids),
            "missing_member_ids": list(self.missing_member_ids),
            "violation_member_ids": list(self.violation_member_ids),
            "evidence_refs": list(self.evidence_refs),
            "source_slice_hash": self.source_slice_hash,
            "reason_code": self.reason_code,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "fact_hash": self.fact_hash}


def _criterion_fact(
    criterion_id: str,
    evidence_slice: GateEvidenceSliceV3 | None,
) -> GateCriterionFactV3:
    if evidence_slice is None:
        values: dict[str, object] = {
            "schema": _FACT_SCHEMA,
            "criterion_id": criterion_id,
            "status": CriterionFactStatus.UNKNOWN.value,
            "required_member_ids": [],
            "observed_member_ids": [],
            "missing_member_ids": [],
            "violation_member_ids": [],
            "evidence_refs": [],
            "source_slice_hash": None,
            "reason_code": "CRITERION_EVIDENCE_ABSENT",
        }
    else:
        missing = tuple(
            member_id
            for member_id in evidence_slice.required_member_ids
            if member_id not in set(evidence_slice.observed_member_ids)
        )
        values = {
            "schema": _FACT_SCHEMA,
            "criterion_id": criterion_id,
            "status": CriterionFactStatus.UNKNOWN.value,
            "required_member_ids": list(evidence_slice.required_member_ids),
            "observed_member_ids": list(evidence_slice.observed_member_ids),
            "missing_member_ids": list(missing),
            "violation_member_ids": list(evidence_slice.violation_member_ids),
            "evidence_refs": sorted(
                {
                    evidence_ref
                    for _, evidence_ref in evidence_slice.member_evidence_refs
                }
            ),
            "source_slice_hash": evidence_slice.slice_hash,
            "reason_code": "SIMULATED_MEMBERSHIP_DIAGNOSTIC_ONLY",
        }
    return GateCriterionFactV3(
        schema=_FACT_SCHEMA,
        criterion_id=criterion_id,
        status=CriterionFactStatus(values["status"]),
        required_member_ids=tuple(values["required_member_ids"]),
        observed_member_ids=tuple(values["observed_member_ids"]),
        missing_member_ids=tuple(values["missing_member_ids"]),
        violation_member_ids=tuple(values["violation_member_ids"]),
        evidence_refs=tuple(values["evidence_refs"]),
        source_slice_hash=values["source_slice_hash"],
        reason_code=values["reason_code"],
        fact_hash=_canonical_hash(values),
        _derivation_token=_FACT_TOKEN,
    )


@dataclass(frozen=True)
class GateMAssessmentPreviewV3:
    """A deterministic non-evidentiary preview, never a Gate terminal."""

    schema: str
    evidence_index_hash: str
    comparison_block_id: str
    common_ancestry_hash: str
    criteria: tuple[GateCriterionFactV3, ...]
    missing_criterion_ids: tuple[str, ...]
    missing_closure_roles: tuple[str, ...]
    assessment_complete: bool
    hard_gate_status: CriterionFactStatus
    gate_m_state: GateMPreviewState
    reason_codes: tuple[str, ...]
    assessment_hash: str
    _derivation_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._derivation_token is not _ASSESSMENT_TOKEN:
            raise GateAssessmentV3Error("Gate assessment preview must be derived")
        if self.schema != _ASSESSMENT_SCHEMA:
            raise GateAssessmentV3Error("Gate assessment preview schema is invalid")
        _digest(self.evidence_index_hash, "Gate evidence index hash")
        _text(self.comparison_block_id, "comparison_block_id")
        _digest(self.common_ancestry_hash, "common_ancestry_hash")
        if tuple(
            item.criterion_id for item in self.criteria
        ) != HARD_GATE_CRITERION_IDS or not all(
            isinstance(item, GateCriterionFactV3) for item in self.criteria
        ):
            raise GateAssessmentV3Error(
                "Gate assessment requires eight ordered derived facts"
            )
        _canonical_ids(self.missing_criterion_ids, "missing criterion ids")
        if self.missing_closure_roles != tuple(
            role
            for role in REQUIRED_GATE_CLOSURE_ROLES
            if role in set(self.missing_closure_roles)
        ):
            raise GateAssessmentV3Error(
                "missing Gate closure roles are not canonically ordered"
            )
        if not isinstance(self.assessment_complete, bool):
            raise GateAssessmentV3Error("assessment completeness must be derived")
        if (
            not isinstance(self.hard_gate_status, CriterionFactStatus)
            or self.gate_m_state is not GateMPreviewState.NOT_EVALUATED
            or self.assessment_complete is not False
            or self.hard_gate_status is not CriterionFactStatus.UNKNOWN
        ):
            raise GateAssessmentV3Error(
                "simulated Gate preview must remain incomplete and UNKNOWN"
            )
        if self.assessment_complete != (
            not self.missing_criterion_ids
            and not self.missing_closure_roles
            and all(
                item.status is not CriterionFactStatus.UNKNOWN for item in self.criteria
            )
        ) or (
            not self.assessment_complete
            and self.hard_gate_status is not CriterionFactStatus.UNKNOWN
        ):
            raise GateAssessmentV3Error(
                "Gate assessment completeness/status disagrees with evidence"
            )
        _canonical_ids(self.reason_codes, "Gate preview reason codes")
        _digest(self.assessment_hash, "Gate assessment preview hash")
        if self.assessment_hash != _canonical_hash(self._body()):
            raise GateAssessmentV3Error("Gate assessment preview hash changed")

    @property
    def terminal(self) -> bool:
        return False

    @property
    def terminal_receipt_hash(self) -> None:
        return None

    @property
    def claim_scope(self) -> str:
        return "simulated_nonclaim"

    @property
    def formal_eligible(self) -> bool:
        return False

    @property
    def prohibited_claim_scopes(self) -> tuple[str, ...]:
        return (
            "formal_gate_m_terminal",
            "pilot_evidence",
            "confirmatory_evidence",
            "scientific_evidence",
        )

    def _body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "evidence_index_hash": self.evidence_index_hash,
            "comparison_block_id": self.comparison_block_id,
            "common_ancestry_hash": self.common_ancestry_hash,
            "criteria": [item.to_dict() for item in self.criteria],
            "missing_criterion_ids": list(self.missing_criterion_ids),
            "missing_closure_roles": list(self.missing_closure_roles),
            "assessment_complete": self.assessment_complete,
            "hard_gate_status": self.hard_gate_status.value,
            "gate_m_state": self.gate_m_state.value,
            "reason_codes": list(self.reason_codes),
            "terminal": self.terminal,
            "terminal_receipt_hash": self.terminal_receipt_hash,
            "claim_scope": self.claim_scope,
            "formal_eligible": self.formal_eligible,
            "prohibited_claim_scopes": list(self.prohibited_claim_scopes),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "assessment_hash": self.assessment_hash}

    @classmethod
    def restore_from_index(
        cls,
        value: object,
        *,
        evidence_index: SimulatedSealedGateEvidenceIndexV3,
    ) -> GateMAssessmentPreviewV3:
        """Re-derive rather than trust any persisted preview field."""

        expected = derive_gate_m_assessment_preview(evidence_index)
        if not _exact_serialized_equal(value, expected.to_dict()):
            raise GateAssessmentV3Error(
                "Gate assessment preview is not its exact derived serialization"
            )
        return expected


def derive_gate_m_assessment_preview(
    evidence_index: SimulatedSealedGateEvidenceIndexV3,
) -> GateMAssessmentPreviewV3:
    """Derive non-authoritative §13.1 coverage diagnostics."""

    if not isinstance(evidence_index, SimulatedSealedGateEvidenceIndexV3):
        raise GateAssessmentV3Error(
            "Gate assessment requires a typed sealed evidence index"
        )
    evidence_index.__post_init__()
    by_criterion = {item.criterion_id: item for item in evidence_index.criterion_slices}
    criteria = tuple(
        _criterion_fact(criterion_id, by_criterion.get(criterion_id))
        for criterion_id in HARD_GATE_CRITERION_IDS
    )
    missing_criterion_ids = tuple(
        criterion_id
        for criterion_id in HARD_GATE_CRITERION_IDS
        if criterion_id not in by_criterion
    )
    closure_roles = {role for role, _ in evidence_index.closure_evidence_refs}
    missing_closure_roles = tuple(
        role for role in REQUIRED_GATE_CLOSURE_ROLES if role not in closure_roles
    )
    # The public simulated index is caller-created diagnostic material.  Its
    # apparent membership coverage must never become Gate evidence.
    complete = False
    hard_gate_status = CriterionFactStatus.UNKNOWN
    reasons = {
        "ASSESSMENT_EVIDENCE_INCOMPLETE",
        "B8B_VERIFIED_SNAPSHOT_UNAVAILABLE",
        "PERFORMANCE_INPUTS_UNAVAILABLE",
        "SIMULATED_SNAPSHOT_NOT_GATE_AUTHORITY",
    }
    if (
        missing_criterion_ids
        or missing_closure_roles
        or any(item.missing_member_ids for item in criteria)
    ):
        reasons.add("SIMULATED_DIAGNOSTIC_MEMBERSHIP_INCOMPLETE")
    values: dict[str, object] = {
        "schema": _ASSESSMENT_SCHEMA,
        "evidence_index_hash": evidence_index.index_hash,
        "comparison_block_id": evidence_index.comparison_block_id,
        "common_ancestry_hash": evidence_index.common_ancestry_hash,
        "criteria": [item.to_dict() for item in criteria],
        "missing_criterion_ids": list(missing_criterion_ids),
        "missing_closure_roles": list(missing_closure_roles),
        "assessment_complete": complete,
        "hard_gate_status": hard_gate_status.value,
        "gate_m_state": GateMPreviewState.NOT_EVALUATED.value,
        "reason_codes": sorted(reasons),
        "terminal": False,
        "terminal_receipt_hash": None,
        "claim_scope": "simulated_nonclaim",
        "formal_eligible": False,
        "prohibited_claim_scopes": [
            "formal_gate_m_terminal",
            "pilot_evidence",
            "confirmatory_evidence",
            "scientific_evidence",
        ],
    }
    return GateMAssessmentPreviewV3(
        schema=_ASSESSMENT_SCHEMA,
        evidence_index_hash=evidence_index.index_hash,
        comparison_block_id=evidence_index.comparison_block_id,
        common_ancestry_hash=evidence_index.common_ancestry_hash,
        criteria=criteria,
        missing_criterion_ids=missing_criterion_ids,
        missing_closure_roles=missing_closure_roles,
        assessment_complete=complete,
        hard_gate_status=hard_gate_status,
        gate_m_state=GateMPreviewState.NOT_EVALUATED,
        reason_codes=tuple(sorted(reasons)),
        assessment_hash=_canonical_hash(values),
        _derivation_token=_ASSESSMENT_TOKEN,
    )


def derive_gate_m_terminal(verified_snapshot: object) -> NoReturn:
    """Fail closed until a production B8b snapshot and §13.2 closure exist."""

    if isinstance(verified_snapshot, SimulatedSealedGateEvidenceIndexV3):
        raise GateAssessmentV3Error(
            "simulated_nonclaim/test-verifier snapshots can never create a "
            "formal Gate M terminal"
        )
    raise GateAssessmentV3Error(B8B_PRODUCTION_SNAPSHOT_GAP)


def derive_verified_hard_gate_assessment(verified_snapshot: object) -> NoReturn:
    """Fail closed until B8b supplies the typed production snapshot input."""

    if isinstance(verified_snapshot, SimulatedSealedGateEvidenceIndexV3):
        raise GateAssessmentV3Error(
            "simulated_nonclaim/test-verifier membership diagnostics cannot "
            "determine a formal §13.1 hard-Gate fact"
        )
    raise GateAssessmentV3Error(B8B_PRODUCTION_SNAPSHOT_GAP)


__all__ = [
    "B8B_PRODUCTION_SNAPSHOT_GAP",
    "HARD_GATE_CRITERION_IDS",
    "REQUIRED_GATE_CLOSURE_ROLES",
    "CriterionFactStatus",
    "GateAssessmentV3Error",
    "GateCriterionFactV3",
    "GateEvidenceSliceV3",
    "GateMAssessmentPreviewV3",
    "GateMPreviewState",
    "SimulatedSealedGateEvidenceIndexV3",
    "derive_gate_m_assessment_preview",
    "derive_gate_m_terminal",
    "derive_verified_hard_gate_assessment",
]
