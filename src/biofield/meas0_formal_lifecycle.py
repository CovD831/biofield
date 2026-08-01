"""Derived, hash-bound lifecycle for the four-stage MEAS0 experiment.

The lifecycle is deliberately an evidence reducer, not an orchestration API.
Callers supply typed ledgers and receipts; they cannot supply a stage outcome,
claim state, or terminal status.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from .meas0_formal import (
    DerivedJudgeQualification,
    DerivedProbeJudgeQualification,
)
from .meas0_readiness import JudgeQualification
from .meas0_stage_cost import CostOutcome, PHASES, StageCostLedger
from .meas0_trust import (
    AuthorizationCheckpoint,
    AuthorizationCheckpointManifest,
    AuthorizationCheckpointRequirement,
    ProductionVerificationResult,
    TrustDomain,
    TrustVerificationMode,
    VerificationResult,
)


class FormalLifecycleError(ValueError):
    """A lifecycle transition or serialized replay is not evidence-derived."""


class LifecycleStage(str, Enum):
    PRE_JCAL = "pre_jcal"
    JCAL = "jcal"
    PILOT = "pilot"
    JAUDIT = "jaudit"
    CONFIRMATORY = "confirmatory"
    CLOSED = "closed"


class LifecycleTerminalStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"
    FAILED = "failed"
    STOPPED = "stopped"
    QUARANTINED = "quarantined"


class LifecycleDisposition(str, Enum):
    ADVANCED = "advanced"
    CLOSED = "closed"
    FAILED = "failed"
    STOPPED = "stopped"
    QUARANTINED = "quarantined"


class LifecycleEvidenceClass(str, Enum):
    TEST_ONLY = "test_only"
    PRODUCTION = "production"


class GateMClaimState(str, Enum):
    NOT_EVALUATED = "not_evaluated"


class ExperimentClaimState(str, Enum):
    NOT_REACHED = "not_reached"
    CONTRACT_ONLY = "contract_only"
    FORMAL_EVIDENCE = "formal_evidence"


_AUTHORIZATION_TOKEN = object()
_PHASE_TARGET_TOKEN = object()
_SIMULATED_PHASE_AUTHORIZATION_TOKEN = object()
_QUALIFICATION_TOKEN = object()
_RECORD_TOKEN = object()
_LIFECYCLE_TOKEN = object()
_STAGE_INDEX = {
    LifecycleStage.JCAL: 0,
    LifecycleStage.PILOT: 1,
    LifecycleStage.JAUDIT: 2,
    LifecycleStage.CONFIRMATORY: 3,
}
_STAGE_PHASE = {
    LifecycleStage.PRE_JCAL: "jcal",
    LifecycleStage.JCAL: "jcal",
    LifecycleStage.PILOT: "pilot",
    LifecycleStage.JAUDIT: "jaudit",
    LifecycleStage.CONFIRMATORY: "confirmatory",
}
_NEXT_STAGE = {
    LifecycleStage.PRE_JCAL: LifecycleStage.JCAL,
    LifecycleStage.JCAL: LifecycleStage.PILOT,
    LifecycleStage.PILOT: LifecycleStage.JAUDIT,
    LifecycleStage.JAUDIT: LifecycleStage.CONFIRMATORY,
    LifecycleStage.CONFIRMATORY: LifecycleStage.CLOSED,
}
_CHECKPOINT = {
    LifecycleStage.PRE_JCAL: AuthorizationCheckpoint.PRE_JCAL,
    LifecycleStage.JCAL: AuthorizationCheckpoint.PILOT_START,
    LifecycleStage.PILOT: AuthorizationCheckpoint.POST_PILOT_JAUDIT,
    LifecycleStage.JAUDIT: AuthorizationCheckpoint.CONFIRMATORY_START,
}
_QUALIFICATION_KIND = {
    LifecycleStage.JCAL: "J-CAL-v1",
    LifecycleStage.JAUDIT: "J-AUDIT-v1",
}


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise FormalLifecycleError("lifecycle value is not canonical JSON") from error


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FormalLifecycleError("serialized lifecycle contains duplicate fields")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise FormalLifecycleError(
        f"serialized lifecycle contains non-finite value: {value}"
    )


def _decode_canonical_bytes(raw_bytes: bytes) -> object:
    if type(raw_bytes) is not bytes:
        raise FormalLifecycleError("serialized lifecycle must be bytes")
    try:
        value = json.loads(
            raw_bytes.decode("utf-8"),
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=_reject_nonfinite,
        )
    except FormalLifecycleError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise FormalLifecycleError("serialized lifecycle is not strict JSON") from error
    if raw_bytes != _canonical(value):
        raise FormalLifecycleError("serialized lifecycle bytes are not canonical")
    return value


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _hash(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise FormalLifecycleError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FormalLifecycleError(f"{label} must be non-empty text")
    return value


_V3_CHECKPOINT_BINDINGS = {
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
_V3_REQUIRED_EVIDENCE_BINDINGS = {
    AuthorizationCheckpoint.PRE_JCAL: frozenset(
        {
            "human_trust_policy",
            "jcal_manifest",
            "judge_identity_manifest",
            "judge_specification",
            "precalibration_lock",
            "price_manifest",
            "stage_budget_manifest",
            "transport_trust_policy",
        }
    ),
    AuthorizationCheckpoint.PILOT_START: frozenset(
        {
            "formal_oracle_authority",
            "gold_binding",
            "isolation_preflight",
            "jcal_invocation",
            "jcal_qualification",
            "jcal_stage_cost",
            "jcal_transport",
            "pilot_input_manifest",
            "pilot_lock",
            "precalibration_lock",
            "provider_manifest",
        }
    ),
    AuthorizationCheckpoint.POST_PILOT_JAUDIT: frozenset(
        {
            "confirmatory_lock",
            "jaudit_manifest",
            "pilot_package",
            "unchanged_design_surface",
        }
    ),
    AuthorizationCheckpoint.CONFIRMATORY_START: frozenset(
        {
            "confirmatory_lock",
            "confirmatory_input_manifest",
            "confirmatory_plan",
            "jaudit_invocation",
            "jaudit_qualification",
            "jaudit_stage_cost",
            "jaudit_transport",
            "provider_manifest",
        }
    ),
}


@dataclass(frozen=True)
class PhaseCheckpointTarget:
    """Versioned, canonical target for one V3 lifecycle checkpoint."""

    schema: str
    version: int
    checkpoint: AuthorizationCheckpoint
    phase: str
    purpose: str
    lifecycle_id: str
    comparison_block_id: str
    authority_role_id: str
    design_hash: str
    source_lock_hash: str
    common_ancestry_hash: str
    ledger_pre_head_hash: str
    evidence_bindings: tuple[tuple[str, str], ...]
    previous_target_hash: str | None
    _derivation_token: object = field(default=None, repr=False, compare=False)
    _expected_previous_target_hash: str | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self._derivation_token is not _PHASE_TARGET_TOKEN:
            raise FormalLifecycleError(
                "typed V3 checkpoint target must be created by its factory"
            )
        if self.schema != "meas0.phase-checkpoint-target" or self.version != 3:
            raise FormalLifecycleError(
                "typed V3 checkpoint target schema/version is invalid"
            )
        if not isinstance(self.checkpoint, AuthorizationCheckpoint):
            object.__setattr__(
                self,
                "checkpoint",
                AuthorizationCheckpoint(self.checkpoint),
            )
        expected_phase, expected_purpose = _V3_CHECKPOINT_BINDINGS[self.checkpoint]
        if (self.phase, self.purpose) != (expected_phase, expected_purpose):
            raise FormalLifecycleError(
                "checkpoint phase/purpose does not match its typed V3 checkpoint"
            )
        _text(self.lifecycle_id, "lifecycle_id")
        _text(self.comparison_block_id, "comparison_block_id")
        _text(self.authority_role_id, "authority_role_id")
        for field_name in (
            "design_hash",
            "source_lock_hash",
            "common_ancestry_hash",
            "ledger_pre_head_hash",
        ):
            _hash(getattr(self, field_name), field_name)
        if not isinstance(self.evidence_bindings, tuple):
            raise FormalLifecycleError(
                "checkpoint evidence bindings must be a canonical tuple"
            )
        names: list[str] = []
        normalized: list[tuple[str, str]] = []
        for item in self.evidence_bindings:
            if (
                not isinstance(item, tuple)
                or len(item) != 2
                or not isinstance(item[0], str)
            ):
                raise FormalLifecycleError("checkpoint evidence bindings are invalid")
            name, digest = item
            names.append(name)
            normalized.append((name, _hash(digest, f"evidence binding {name}")))
        if (
            tuple(normalized) != tuple(sorted(normalized))
            or len(names) != len(set(names))
            or frozenset(names) != _V3_REQUIRED_EVIDENCE_BINDINGS[self.checkpoint]
        ):
            raise FormalLifecycleError(
                "checkpoint evidence bindings do not match the required contract"
            )
        if self.previous_target_hash is not None:
            _hash(self.previous_target_hash, "previous_target_hash")
        if self.previous_target_hash != self._expected_previous_target_hash:
            raise FormalLifecycleError(
                "checkpoint previous target hash is not factory-derived"
            )
        if (
            self.checkpoint is AuthorizationCheckpoint.PRE_JCAL
            and self.previous_target_hash is not None
        ):
            raise FormalLifecycleError(
                "first checkpoint previous target hash must be absent"
            )
        if (
            self.checkpoint is not AuthorizationCheckpoint.PRE_JCAL
            and self.previous_target_hash is None
        ):
            raise FormalLifecycleError(
                "non-first checkpoint previous target hash is required"
            )

    @classmethod
    def create(
        cls,
        *,
        checkpoint: AuthorizationCheckpoint,
        lifecycle_id: str,
        comparison_block_id: str,
        authority_role_id: str,
        design_hash: str,
        source_lock_hash: str,
        common_ancestry_hash: str,
        ledger_pre_head_hash: str,
        evidence_bindings: Mapping[str, str],
        previous_target: PhaseCheckpointTarget | None,
    ) -> PhaseCheckpointTarget:
        if not isinstance(checkpoint, AuthorizationCheckpoint):
            checkpoint = AuthorizationCheckpoint(checkpoint)
        order = tuple(AuthorizationCheckpoint)
        index = order.index(checkpoint)
        if index == 0:
            if previous_target is not None:
                raise FormalLifecycleError(
                    "first checkpoint previous target must be absent"
                )
        elif (
            not isinstance(previous_target, PhaseCheckpointTarget)
            or previous_target.checkpoint is not order[index - 1]
        ):
            raise FormalLifecycleError(
                "checkpoint previous target is missing or out of order"
            )
        if previous_target is not None:
            if authority_role_id != previous_target.authority_role_id:
                raise FormalLifecycleError(
                    "checkpoint authority role does not match previous target"
                )
            ancestry = (
                lifecycle_id,
                comparison_block_id,
                design_hash,
                source_lock_hash,
                common_ancestry_hash,
            )
            previous_ancestry = (
                previous_target.lifecycle_id,
                previous_target.comparison_block_id,
                previous_target.design_hash,
                previous_target.source_lock_hash,
                previous_target.common_ancestry_hash,
            )
            if ancestry != previous_ancestry:
                raise FormalLifecycleError(
                    "checkpoint common ancestry does not match previous target"
                )
        if not isinstance(evidence_bindings, Mapping):
            raise FormalLifecycleError("checkpoint evidence bindings must be a mapping")
        previous_hash = (
            previous_target.target_hash if previous_target is not None else None
        )
        phase, purpose = _V3_CHECKPOINT_BINDINGS[checkpoint]
        return cls(
            schema="meas0.phase-checkpoint-target",
            version=3,
            checkpoint=checkpoint,
            phase=phase,
            purpose=purpose,
            lifecycle_id=lifecycle_id,
            comparison_block_id=comparison_block_id,
            authority_role_id=authority_role_id,
            design_hash=design_hash,
            source_lock_hash=source_lock_hash,
            common_ancestry_hash=common_ancestry_hash,
            ledger_pre_head_hash=ledger_pre_head_hash,
            evidence_bindings=tuple(sorted(evidence_bindings.items())),
            previous_target_hash=previous_hash,
            _derivation_token=_PHASE_TARGET_TOKEN,
            _expected_previous_target_hash=previous_hash,
        )

    def _body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "version": self.version,
            "checkpoint": self.checkpoint.value,
            "phase": self.phase,
            "purpose": self.purpose,
            "lifecycle_id": self.lifecycle_id,
            "comparison_block_id": self.comparison_block_id,
            "authority_role_id": self.authority_role_id,
            "design_hash": self.design_hash,
            "source_lock_hash": self.source_lock_hash,
            "common_ancestry_hash": self.common_ancestry_hash,
            "ledger_pre_head_hash": self.ledger_pre_head_hash,
            "evidence_bindings": dict(self.evidence_bindings),
            "previous_target_hash": self.previous_target_hash,
        }

    @property
    def target_hash(self) -> str:
        return _sha256(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "target_hash": self.target_hash}

    @classmethod
    def from_dict(cls, value: object) -> PhaseCheckpointTarget:
        if not isinstance(value, Mapping):
            raise FormalLifecycleError("typed V3 checkpoint target must be a mapping")
        fields = {
            "schema",
            "version",
            "checkpoint",
            "phase",
            "purpose",
            "lifecycle_id",
            "comparison_block_id",
            "authority_role_id",
            "design_hash",
            "source_lock_hash",
            "common_ancestry_hash",
            "ledger_pre_head_hash",
            "evidence_bindings",
            "previous_target_hash",
            "target_hash",
        }
        if set(value) != fields:
            raise FormalLifecycleError("typed V3 checkpoint target fields are invalid")
        bindings = value["evidence_bindings"]
        if not isinstance(bindings, Mapping):
            raise FormalLifecycleError("checkpoint evidence bindings must be a mapping")
        previous_hash = value["previous_target_hash"]
        result = cls(
            schema=value["schema"],
            version=value["version"],
            checkpoint=AuthorizationCheckpoint(value["checkpoint"]),
            phase=value["phase"],
            purpose=value["purpose"],
            lifecycle_id=value["lifecycle_id"],
            comparison_block_id=value["comparison_block_id"],
            authority_role_id=value["authority_role_id"],
            design_hash=value["design_hash"],
            source_lock_hash=value["source_lock_hash"],
            common_ancestry_hash=value["common_ancestry_hash"],
            ledger_pre_head_hash=value["ledger_pre_head_hash"],
            evidence_bindings=tuple(sorted(bindings.items())),
            previous_target_hash=previous_hash,
            _derivation_token=_PHASE_TARGET_TOKEN,
            _expected_previous_target_hash=previous_hash,
        )
        if value["target_hash"] != result.target_hash:
            raise FormalLifecycleError("typed V3 checkpoint target hash is invalid")
        return result


@dataclass(frozen=True)
class SimulatedPhaseCheckpointAuthorization:
    """Test-only checkpoint authorization; it is never production evidence."""

    target: PhaseCheckpointTarget
    verification: VerificationResult
    _derivation_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._derivation_token is not _SIMULATED_PHASE_AUTHORIZATION_TOKEN:
            raise FormalLifecycleError(
                "simulated checkpoint authorization must be created by its factory"
            )
        if not isinstance(self.target, PhaseCheckpointTarget):
            raise FormalLifecycleError(
                "simulated checkpoint authorization requires a typed V3 target"
            )
        if type(self.verification) is not VerificationResult:
            raise FormalLifecycleError(
                "simulated checkpoint authorization requires test-only verification"
            )
        if self.verification.payload_hash != self.target.target_hash:
            raise FormalLifecycleError(
                "simulated authorization verification payload does not bind target"
            )
        if (
            not self.verification.verified
            or self.verification.production_authorized
            or self.verification.claim_scope != "contract_only"
            or self.verification.mode is not TrustVerificationMode.TEST_ONLY_CONTRACT
            or self.verification.trust_domain is not TrustDomain.HUMAN_APPROVAL
        ):
            raise FormalLifecycleError(
                "simulated checkpoint authorization requires verified "
                "test-only human approval"
            )

    @property
    def claim_scope(self) -> str:
        return "simulated_nonclaim"

    @property
    def production_authorized(self) -> bool:
        return False

    @property
    def test_only(self) -> bool:
        return True

    @property
    def authorization_hash(self) -> str:
        return _sha256(self._body())

    def _body(self) -> dict[str, Any]:
        return {
            "schema": "meas0.simulated-phase-checkpoint-authorization",
            "version": 1,
            "target_hash": self.target.target_hash,
            "verification_hash": self.verification.contract_hash,
            "claim_scope": self.claim_scope,
            "production_authorized": self.production_authorized,
            "test_only": self.test_only,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "authorization_hash": self.authorization_hash}


def authorize_simulated_phase_checkpoint(
    *,
    target: PhaseCheckpointTarget,
    verification: VerificationResult,
) -> SimulatedPhaseCheckpointAuthorization:
    return SimulatedPhaseCheckpointAuthorization(
        target=target,
        verification=verification,
        _derivation_token=_SIMULATED_PHASE_AUTHORIZATION_TOKEN,
    )


def validate_v3_phase_checkpoint_chain(
    targets: Sequence[PhaseCheckpointTarget],
    authorizations: Sequence[SimulatedPhaseCheckpointAuthorization],
) -> tuple[SimulatedPhaseCheckpointAuthorization, ...]:
    target_tuple = tuple(targets)
    authorization_tuple = tuple(authorizations)
    expected_order = tuple(AuthorizationCheckpoint)
    if len(target_tuple) != len(expected_order) or not all(
        isinstance(item, PhaseCheckpointTarget) for item in target_tuple
    ):
        raise FormalLifecycleError(
            "all production checkpoint inputs must be typed V3 targets"
        )
    if tuple(item.checkpoint for item in target_tuple) != expected_order:
        raise FormalLifecycleError(
            "typed V3 checkpoint targets must be ordered by lifecycle phase"
        )
    authority_role_id = target_tuple[0].authority_role_id
    if any(item.authority_role_id != authority_role_id for item in target_tuple[1:]):
        raise FormalLifecycleError("typed V3 checkpoint targets changed authority role")
    ancestry = (
        target_tuple[0].lifecycle_id,
        target_tuple[0].comparison_block_id,
        target_tuple[0].design_hash,
        target_tuple[0].source_lock_hash,
        target_tuple[0].common_ancestry_hash,
    )
    if any(
        (
            item.lifecycle_id,
            item.comparison_block_id,
            item.design_hash,
            item.source_lock_hash,
            item.common_ancestry_hash,
        )
        != ancestry
        for item in target_tuple[1:]
    ):
        raise FormalLifecycleError(
            "typed V3 checkpoint targets do not share common ancestry"
        )
    if target_tuple[0].previous_target_hash is not None or any(
        current.previous_target_hash != previous.target_hash
        for previous, current in zip(
            target_tuple[:-1],
            target_tuple[1:],
            strict=True,
        )
    ):
        raise FormalLifecycleError(
            "typed V3 checkpoint previous target chain is invalid"
        )
    if len(authorization_tuple) != len(target_tuple) or not all(
        isinstance(item, SimulatedPhaseCheckpointAuthorization)
        for item in authorization_tuple
    ):
        raise FormalLifecycleError(
            "typed V3 checkpoint chain requires simulated authorizations"
        )
    if any(
        authorization.target != target
        for target, authorization in zip(
            target_tuple,
            authorization_tuple,
            strict=True,
        )
    ):
        raise FormalLifecycleError(
            "authorization target does not match typed V3 checkpoint target"
        )
    return authorization_tuple


@dataclass(frozen=True)
class StageAuthorizationReceipt:
    """A verified checkpoint requirement, preserving its evidence class."""

    requirement: AuthorizationCheckpointRequirement
    verification: VerificationResult | ProductionVerificationResult
    _derivation_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._derivation_token is not _AUTHORIZATION_TOKEN:
            raise FormalLifecycleError(
                "authorization receipt must be created by its factory"
            )
        if not isinstance(self.requirement, AuthorizationCheckpointRequirement):
            raise FormalLifecycleError(
                "authorization receipt requires a typed checkpoint"
            )
        if not isinstance(
            self.verification,
            (VerificationResult, ProductionVerificationResult),
        ):
            raise FormalLifecycleError(
                "authorization receipt requires a typed verification"
            )
        if self.verification.payload_hash != self.requirement.payload_hash:
            raise FormalLifecycleError(
                "authorization verification does not bind checkpoint payload"
            )
        if isinstance(self.verification, VerificationResult):
            if (
                not self.verification.verified
                or self.verification.trust_domain is not TrustDomain.HUMAN_APPROVAL
            ):
                raise FormalLifecycleError(
                    "authorization verification is not a verified human approval"
                )
        elif self.verification.authority.trust_domain is not TrustDomain.HUMAN_APPROVAL:
            raise FormalLifecycleError(
                "production authorization authority has the wrong trust domain"
            )

    @classmethod
    def from_verification(
        cls,
        *,
        requirement: AuthorizationCheckpointRequirement,
        verification: VerificationResult | ProductionVerificationResult,
    ) -> StageAuthorizationReceipt:
        return cls(
            requirement=requirement,
            verification=verification,
            _derivation_token=_AUTHORIZATION_TOKEN,
        )

    @property
    def production_authorized(self) -> bool:
        return isinstance(self.verification, ProductionVerificationResult)

    @property
    def test_only(self) -> bool:
        return not self.production_authorized

    def _body(self) -> dict[str, Any]:
        return {
            "requirement": self.requirement.to_dict(),
            "verification": self.verification.to_dict(),
            "production_authorized": self.production_authorized,
            "test_only": self.test_only,
        }

    @property
    def contract_hash(self) -> str:
        return _sha256(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "contract_hash": self.contract_hash}


@dataclass(frozen=True)
class StageQualificationReceipt:
    """A qualification result with an explicit, non-upgradable evidence class."""

    qualification: JudgeQualification
    source_evidence_hash: str
    test_only: bool
    derived_evidence: (
        DerivedJudgeQualification | DerivedProbeJudgeQualification | None
    ) = None
    production_attestation: ProductionVerificationResult | None = None
    _derivation_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._derivation_token is not _QUALIFICATION_TOKEN:
            raise FormalLifecycleError(
                "qualification receipt must be created by its factory"
            )
        if not isinstance(self.qualification, JudgeQualification):
            raise FormalLifecycleError(
                "qualification receipt requires a typed qualification"
            )
        _hash(self.source_evidence_hash, "qualification source evidence hash")
        if not isinstance(self.test_only, bool):
            raise FormalLifecycleError(
                "qualification evidence class must be derived boolean"
            )
        if self.test_only:
            if (
                self.derived_evidence is not None
                or self.production_attestation is not None
            ):
                raise FormalLifecycleError(
                    "test-only qualification cannot carry production evidence"
                )
        else:
            if not isinstance(
                self.derived_evidence,
                (DerivedJudgeQualification, DerivedProbeJudgeQualification),
            ) or not isinstance(
                self.production_attestation,
                ProductionVerificationResult,
            ):
                raise FormalLifecycleError(
                    "production qualification requires derived evidence and "
                    "a production attestation"
                )
            evidence = self.derived_evidence
            attestation = self.production_attestation
            if (
                evidence.qualification != self.qualification
                or evidence.contract_hash != self.source_evidence_hash
                or evidence.attestation.test_only
                or (
                    isinstance(evidence, DerivedProbeJudgeQualification)
                    and evidence.source_corpus.probe_manifest.test_only
                )
                or attestation.payload_hash != evidence.contract_hash
                or attestation.authority.trust_domain is not TrustDomain.TRANSPORT
            ):
                raise FormalLifecycleError(
                    "production qualification evidence ancestry is invalid"
                )

    @classmethod
    def from_test_qualification(
        cls,
        *,
        qualification: JudgeQualification,
        source_evidence_hash: str,
    ) -> StageQualificationReceipt:
        return cls(
            qualification=qualification,
            source_evidence_hash=source_evidence_hash,
            test_only=True,
            _derivation_token=_QUALIFICATION_TOKEN,
        )

    @classmethod
    def from_derived_qualification(
        cls,
        *,
        evidence: DerivedJudgeQualification | DerivedProbeJudgeQualification,
        production_attestation: ProductionVerificationResult,
    ) -> StageQualificationReceipt:
        """Bind corpus-derived statistics to a production transport attestation."""

        if not isinstance(
            evidence,
            (DerivedJudgeQualification, DerivedProbeJudgeQualification),
        ):
            raise FormalLifecycleError(
                "production qualification requires typed derived Judge evidence"
            )
        if not isinstance(production_attestation, ProductionVerificationResult):
            raise FormalLifecycleError(
                "production qualification requires a production attestation"
            )
        return cls(
            qualification=evidence.qualification,
            source_evidence_hash=evidence.contract_hash,
            test_only=False,
            derived_evidence=evidence,
            production_attestation=production_attestation,
            _derivation_token=_QUALIFICATION_TOKEN,
        )

    @property
    def qualified(self) -> bool:
        return self.qualification.qualified

    @property
    def set_kind(self) -> str:
        return self.qualification.set_kind

    def _body(self) -> dict[str, Any]:
        return {
            "qualification": self.qualification.to_dict(),
            "source_evidence_hash": self.source_evidence_hash,
            "test_only": self.test_only,
            "qualified": self.qualified,
            "derived_evidence": (
                self.derived_evidence.to_dict()
                if self.derived_evidence is not None
                else None
            ),
            "production_attestation": (
                self.production_attestation.to_dict()
                if self.production_attestation is not None
                else None
            ),
        }

    @property
    def contract_hash(self) -> str:
        return _sha256(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "contract_hash": self.contract_hash}


@dataclass(frozen=True)
class LifecycleRecord:
    sequence: int
    from_stage: LifecycleStage
    to_stage: LifecycleStage
    disposition: LifecycleDisposition
    ledger_hash: str
    ledger_phase: str
    budget_trigger_entry_hash: str | None
    authorization_receipt_hash: str | None
    authorization_evidence_class: LifecycleEvidenceClass | None
    qualification_receipt_hash: str | None
    qualification_evidence_class: LifecycleEvidenceClass | None
    failure_entry_hash: str | None
    previous_record_hash: str | None
    _derivation_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._derivation_token is not _RECORD_TOKEN:
            raise FormalLifecycleError("lifecycle record must be evidence-derived")
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
        ):
            raise FormalLifecycleError("record sequence must be non-negative")
        for name in (
            "ledger_hash",
            "budget_trigger_entry_hash",
            "authorization_receipt_hash",
            "qualification_receipt_hash",
            "failure_entry_hash",
            "previous_record_hash",
        ):
            value = getattr(self, name)
            if value is not None:
                _hash(value, name)
        if self.ledger_phase not in PHASES:
            raise FormalLifecycleError("record ledger phase is invalid")
        for name in (
            "authorization_evidence_class",
            "qualification_evidence_class",
        ):
            value = getattr(self, name)
            if value is not None and not isinstance(value, LifecycleEvidenceClass):
                try:
                    object.__setattr__(
                        self,
                        name,
                        LifecycleEvidenceClass(value),
                    )
                except ValueError as error:
                    raise FormalLifecycleError(f"record {name} is invalid") from error
        if (self.authorization_receipt_hash is None) is not (
            self.authorization_evidence_class is None
        ):
            raise FormalLifecycleError(
                "authorization receipt hash and evidence class must be paired"
            )
        if (self.qualification_receipt_hash is None) is not (
            self.qualification_evidence_class is None
        ):
            raise FormalLifecycleError(
                "qualification receipt hash and evidence class must be paired"
            )

    def _body(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "from_stage": self.from_stage.value,
            "to_stage": self.to_stage.value,
            "disposition": self.disposition.value,
            "ledger_hash": self.ledger_hash,
            "ledger_phase": self.ledger_phase,
            "budget_trigger_entry_hash": self.budget_trigger_entry_hash,
            "authorization_receipt_hash": self.authorization_receipt_hash,
            "authorization_evidence_class": (
                self.authorization_evidence_class.value
                if self.authorization_evidence_class is not None
                else None
            ),
            "qualification_receipt_hash": self.qualification_receipt_hash,
            "qualification_evidence_class": (
                self.qualification_evidence_class.value
                if self.qualification_evidence_class is not None
                else None
            ),
            "failure_entry_hash": self.failure_entry_hash,
            "previous_record_hash": self.previous_record_hash,
        }

    @property
    def contract_hash(self) -> str:
        return _sha256(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "contract_hash": self.contract_hash}


@dataclass(frozen=True)
class FormalLifecycle:
    lifecycle_id: str
    checkpoint_manifest: AuthorizationCheckpointManifest
    records: tuple[LifecycleRecord, ...]
    stage: LifecycleStage
    terminal_status: LifecycleTerminalStatus
    _last_ledger: StageCostLedger | None = field(default=None, repr=False)
    _derivation_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._derivation_token is not _LIFECYCLE_TOKEN:
            raise FormalLifecycleError("lifecycle must be evidence-derived")
        _text(self.lifecycle_id, "lifecycle_id")
        if not isinstance(
            self.checkpoint_manifest,
            AuthorizationCheckpointManifest,
        ):
            raise FormalLifecycleError("lifecycle requires a typed checkpoint manifest")
        records = tuple(self.records)
        if not all(isinstance(item, LifecycleRecord) for item in records):
            raise FormalLifecycleError("lifecycle records must be typed")
        for index, record in enumerate(records):
            expected_previous = records[index - 1].contract_hash if index else None
            if (
                record.sequence != index
                or record.previous_record_hash != expected_previous
            ):
                raise FormalLifecycleError("lifecycle record hash ancestry is broken")
        object.__setattr__(self, "records", records)

    @property
    def gate_m_claim(self) -> GateMClaimState:
        return GateMClaimState.NOT_EVALUATED

    @property
    def pilot_claim(self) -> ExperimentClaimState:
        reached = any(
            record.from_stage is LifecycleStage.PILOT
            and record.to_stage is LifecycleStage.JAUDIT
            for record in self.records
        )
        if not reached:
            return ExperimentClaimState.NOT_REACHED
        if self.formal_evidence:
            return ExperimentClaimState.FORMAL_EVIDENCE
        return ExperimentClaimState.CONTRACT_ONLY

    @property
    def confirmatory_claim(self) -> ExperimentClaimState:
        if self.stage is not LifecycleStage.CLOSED:
            return ExperimentClaimState.NOT_REACHED
        if self.formal_evidence:
            return ExperimentClaimState.FORMAL_EVIDENCE
        return ExperimentClaimState.CONTRACT_ONLY

    @property
    def formal_evidence(self) -> bool:
        if (
            self.stage is not LifecycleStage.CLOSED
            or self.terminal_status is not LifecycleTerminalStatus.CLOSED
        ):
            return False
        authorization_classes = tuple(
            record.authorization_evidence_class
            for record in self.records
            if record.authorization_evidence_class is not None
        )
        qualification_classes = tuple(
            record.qualification_evidence_class
            for record in self.records
            if record.qualification_evidence_class is not None
        )
        return (
            len(authorization_classes) == len(AuthorizationCheckpoint)
            and all(
                item is LifecycleEvidenceClass.PRODUCTION
                for item in authorization_classes
            )
            and len(qualification_classes) == len(_QUALIFICATION_KIND)
            and all(
                item is LifecycleEvidenceClass.PRODUCTION
                for item in qualification_classes
            )
        )

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "lifecycle_id": self.lifecycle_id,
            "checkpoint_manifest_hash": self.checkpoint_manifest.contract_hash,
            "records": [record.to_dict() for record in self.records],
            "stage": self.stage.value,
            "terminal_status": self.terminal_status.value,
            "last_ledger_hash": (
                self._last_ledger.contract_hash
                if self._last_ledger is not None
                else None
            ),
            "gate_m_claim": self.gate_m_claim.value,
            "pilot_claim": self.pilot_claim.value,
            "confirmatory_claim": self.confirmatory_claim.value,
            "formal_evidence": self.formal_evidence,
        }

    @property
    def lifecycle_hash(self) -> str:
        return _sha256(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "lifecycle_hash": self.lifecycle_hash}

    def to_canonical_bytes(self) -> bytes:
        """Return the strict serialized lifecycle projection.

        The bytes are only a replay carrier.  Restoration still requires the
        independently reconstructed checkpoint manifest, ledgers, and typed
        receipts, so bytes alone cannot create lifecycle evidence.
        """

        return _canonical(self.to_dict())


def start_lifecycle(
    *,
    lifecycle_id: str,
    checkpoint_manifest: AuthorizationCheckpointManifest,
) -> FormalLifecycle:
    return FormalLifecycle(
        lifecycle_id=lifecycle_id,
        checkpoint_manifest=checkpoint_manifest,
        records=(),
        stage=LifecycleStage.PRE_JCAL,
        terminal_status=LifecycleTerminalStatus.ACTIVE,
        _derivation_token=_LIFECYCLE_TOKEN,
    )


def _ensure_active(lifecycle: FormalLifecycle) -> None:
    if not isinstance(lifecycle, FormalLifecycle):
        raise FormalLifecycleError("a typed lifecycle is required")
    if lifecycle.terminal_status is not LifecycleTerminalStatus.ACTIVE:
        raise FormalLifecycleError("terminal lifecycle cannot be reopened")


def _validate_ledger_ancestry(
    lifecycle: FormalLifecycle,
    ledger: StageCostLedger,
) -> None:
    if not isinstance(ledger, StageCostLedger):
        raise FormalLifecycleError("a typed StageCost ledger is required")
    previous = lifecycle._last_ledger
    if previous is None:
        return
    if (
        ledger.ledger_id != previous.ledger_id
        or ledger.version != previous.version
        or ledger.price_manifest_hash != previous.price_manifest_hash
        or ledger.budget_manifest != previous.budget_manifest
        or len(ledger.entries) < len(previous.entries)
        or ledger.entries[: len(previous.entries)] != previous.entries
    ):
        raise FormalLifecycleError("StageCost ledger ancestry is invalid")


def _validate_phase_order(
    stage: LifecycleStage,
    ledger: StageCostLedger,
) -> None:
    allowed_phase = _STAGE_PHASE[stage]
    allowed_index = PHASES.index(allowed_phase)
    if stage is LifecycleStage.PRE_JCAL:
        invalid = bool(ledger.entries)
    else:
        invalid = any(
            PHASES.index(entry.phase) > allowed_index for entry in ledger.entries
        )
    if invalid:
        raise FormalLifecycleError(
            "StageCost ledger contains entries after the current stage"
        )


def _require_checkpoint(
    lifecycle: FormalLifecycle,
    ledger: StageCostLedger,
    receipt: StageAuthorizationReceipt | None,
) -> None:
    expected_checkpoint = _CHECKPOINT[lifecycle.stage]
    expected = lifecycle.checkpoint_manifest.requirements[
        tuple(AuthorizationCheckpoint).index(expected_checkpoint)
    ]
    if (
        not isinstance(receipt, StageAuthorizationReceipt)
        or receipt.requirement != expected
    ):
        raise FormalLifecycleError(
            f"authorization checkpoint {expected_checkpoint.value} is required"
        )
    if receipt.requirement.ledger_pre_head_hash != ledger.contract_hash:
        raise FormalLifecycleError(
            "authorization checkpoint ledger pre-head does not match StageCost ledger"
        )


def _require_qualification(
    stage: LifecycleStage,
    receipt: StageQualificationReceipt | None,
) -> StageQualificationReceipt:
    expected_kind = _QUALIFICATION_KIND[stage]
    if (
        not isinstance(receipt, StageQualificationReceipt)
        or receipt.set_kind != expected_kind
    ):
        raise FormalLifecycleError(f"{expected_kind} qualification receipt is required")
    return receipt


def _append(
    lifecycle: FormalLifecycle,
    *,
    ledger: StageCostLedger,
    to_stage: LifecycleStage,
    disposition: LifecycleDisposition,
    budget_trigger_entry_hash: str | None = None,
    authorization_receipt: StageAuthorizationReceipt | None = None,
    qualification_receipt: StageQualificationReceipt | None = None,
    failure_entry_hash: str | None = None,
) -> FormalLifecycle:
    previous_hash = lifecycle.records[-1].contract_hash if lifecycle.records else None
    record = LifecycleRecord(
        sequence=len(lifecycle.records),
        from_stage=lifecycle.stage,
        to_stage=to_stage,
        disposition=disposition,
        ledger_hash=ledger.contract_hash,
        ledger_phase=_STAGE_PHASE[lifecycle.stage],
        budget_trigger_entry_hash=budget_trigger_entry_hash,
        authorization_receipt_hash=(
            authorization_receipt.contract_hash
            if authorization_receipt is not None
            else None
        ),
        authorization_evidence_class=(
            LifecycleEvidenceClass.PRODUCTION
            if authorization_receipt is not None
            and authorization_receipt.production_authorized
            else LifecycleEvidenceClass.TEST_ONLY
            if authorization_receipt is not None
            else None
        ),
        qualification_receipt_hash=(
            qualification_receipt.contract_hash
            if qualification_receipt is not None
            else None
        ),
        qualification_evidence_class=(
            LifecycleEvidenceClass.TEST_ONLY
            if qualification_receipt is not None and qualification_receipt.test_only
            else LifecycleEvidenceClass.PRODUCTION
            if qualification_receipt is not None
            else None
        ),
        failure_entry_hash=failure_entry_hash,
        previous_record_hash=previous_hash,
        _derivation_token=_RECORD_TOKEN,
    )
    terminal_status = {
        LifecycleDisposition.ADVANCED: LifecycleTerminalStatus.ACTIVE,
        LifecycleDisposition.CLOSED: LifecycleTerminalStatus.CLOSED,
        LifecycleDisposition.FAILED: LifecycleTerminalStatus.FAILED,
        LifecycleDisposition.STOPPED: LifecycleTerminalStatus.STOPPED,
        LifecycleDisposition.QUARANTINED: LifecycleTerminalStatus.QUARANTINED,
    }[disposition]
    return FormalLifecycle(
        lifecycle_id=lifecycle.lifecycle_id,
        checkpoint_manifest=lifecycle.checkpoint_manifest,
        records=(*lifecycle.records, record),
        stage=to_stage,
        terminal_status=terminal_status,
        _last_ledger=ledger,
        _derivation_token=_LIFECYCLE_TOKEN,
    )


def advance_lifecycle(
    lifecycle: FormalLifecycle,
    *,
    ledger: StageCostLedger,
    authorization_receipt: StageAuthorizationReceipt | None = None,
    qualification_receipt: StageQualificationReceipt | None = None,
) -> FormalLifecycle:
    """Derive exactly one transition from typed budget and receipt evidence."""

    _ensure_active(lifecycle)
    _validate_ledger_ancestry(lifecycle, ledger)
    if lifecycle.stage is LifecycleStage.CLOSED:
        raise FormalLifecycleError("closed lifecycle is terminal")

    stage = lifecycle.stage
    phase = _STAGE_PHASE[stage]
    decision = ledger.phase_decision(phase)
    if decision.stopped:
        return _append(
            lifecycle,
            ledger=ledger,
            to_stage=stage,
            disposition=LifecycleDisposition.STOPPED,
            budget_trigger_entry_hash=decision.trigger_entry_hash,
        )

    if stage in _CHECKPOINT:
        _require_checkpoint(lifecycle, ledger, authorization_receipt)
    elif authorization_receipt is not None:
        raise FormalLifecycleError(
            "authorization checkpoint receipt is extraneous at this stage"
        )
    _validate_phase_order(stage, ledger)

    qualification: StageQualificationReceipt | None = None
    if stage in _QUALIFICATION_KIND:
        qualification = _require_qualification(stage, qualification_receipt)
        if not qualification.qualified:
            return _append(
                lifecycle,
                ledger=ledger,
                to_stage=stage,
                disposition=LifecycleDisposition.QUARANTINED,
                authorization_receipt=authorization_receipt,
                qualification_receipt=qualification,
            )
    elif qualification_receipt is not None:
        raise FormalLifecycleError("qualification receipt is extraneous at this stage")

    to_stage = _NEXT_STAGE[stage]
    disposition = (
        LifecycleDisposition.CLOSED
        if to_stage is LifecycleStage.CLOSED
        else LifecycleDisposition.ADVANCED
    )
    return _append(
        lifecycle,
        ledger=ledger,
        to_stage=to_stage,
        disposition=disposition,
        authorization_receipt=authorization_receipt,
        qualification_receipt=qualification,
    )


def fail_lifecycle(
    lifecycle: FormalLifecycle,
    *,
    ledger: StageCostLedger,
    failure_entry_hash: str,
) -> FormalLifecycle:
    """Derive terminal failure from one failed StageCost entry."""

    _ensure_active(lifecycle)
    _validate_ledger_ancestry(lifecycle, ledger)
    _validate_phase_order(lifecycle.stage, ledger)
    target = _hash(failure_entry_hash, "failure entry hash")
    matching = [entry for entry in ledger.entries if entry.contract_hash == target]
    if (
        len(matching) != 1
        or matching[0].outcome is not CostOutcome.FAILED
        or matching[0].phase != _STAGE_PHASE[lifecycle.stage]
    ):
        raise FormalLifecycleError(
            "failure must bind exactly one failed StageCost entry in the current phase"
        )
    return _append(
        lifecycle,
        ledger=ledger,
        to_stage=lifecycle.stage,
        disposition=LifecycleDisposition.FAILED,
        failure_entry_hash=target,
    )


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FormalLifecycleError(f"{label} must be an object")
    return value


def _unique_by_hash(
    values: Sequence[object],
    *,
    kind: type,
    label: str,
) -> dict[str, Any]:
    if not all(isinstance(value, kind) for value in values):
        raise FormalLifecycleError(f"{label} must contain typed evidence")
    result = {value.contract_hash: value for value in values}
    if len(result) != len(values):
        raise FormalLifecycleError(f"{label} contains duplicate evidence hashes")
    return result


def replay_lifecycle(
    value: object,
    *,
    checkpoint_manifest: AuthorizationCheckpointManifest,
    ledgers: Sequence[StageCostLedger],
    authorization_receipts: Sequence[StageAuthorizationReceipt],
    qualification_receipts: Sequence[StageQualificationReceipt],
) -> FormalLifecycle:
    """Recompute every transition and compare it with the serialized hash chain."""

    raw = _mapping(value, "serialized lifecycle")
    if raw.get("schema_version") != 1:
        raise FormalLifecycleError("serialized lifecycle schema version is invalid")
    if (
        not isinstance(checkpoint_manifest, AuthorizationCheckpointManifest)
        or raw.get("checkpoint_manifest_hash") != checkpoint_manifest.contract_hash
    ):
        raise FormalLifecycleError(
            "serialized lifecycle checkpoint ancestry is invalid"
        )
    raw_records = raw.get("records")
    if not isinstance(raw_records, list):
        raise FormalLifecycleError("serialized lifecycle records are invalid")
    ledger_map = _unique_by_hash(
        ledgers,
        kind=StageCostLedger,
        label="ledger replay ancestry",
    )
    authorization_map = _unique_by_hash(
        authorization_receipts,
        kind=StageAuthorizationReceipt,
        label="authorization replay ancestry",
    )
    qualification_map = _unique_by_hash(
        qualification_receipts,
        kind=StageQualificationReceipt,
        label="qualification replay ancestry",
    )
    lifecycle = start_lifecycle(
        lifecycle_id=raw.get("lifecycle_id"),
        checkpoint_manifest=checkpoint_manifest,
    )
    for index, raw_record_value in enumerate(raw_records):
        raw_record = _mapping(raw_record_value, "serialized lifecycle record")
        if raw_record.get("sequence") != index:
            raise FormalLifecycleError("serialized lifecycle record order is invalid")
        try:
            ledger = ledger_map[raw_record.get("ledger_hash")]
        except KeyError as error:
            raise FormalLifecycleError(
                "serialized lifecycle ledger ancestry is missing"
            ) from error
        authorization_hash = raw_record.get("authorization_receipt_hash")
        qualification_hash = raw_record.get("qualification_receipt_hash")
        try:
            authorization = (
                authorization_map[authorization_hash]
                if authorization_hash is not None
                else None
            )
            qualification = (
                qualification_map[qualification_hash]
                if qualification_hash is not None
                else None
            )
        except KeyError as error:
            raise FormalLifecycleError(
                "serialized lifecycle receipt ancestry is missing"
            ) from error
        if raw_record.get("disposition") == LifecycleDisposition.FAILED.value:
            lifecycle = fail_lifecycle(
                lifecycle,
                ledger=ledger,
                failure_entry_hash=raw_record.get("failure_entry_hash"),
            )
        else:
            lifecycle = advance_lifecycle(
                lifecycle,
                ledger=ledger,
                authorization_receipt=authorization,
                qualification_receipt=qualification,
            )
        if lifecycle.records[-1].to_dict() != dict(raw_record):
            raise FormalLifecycleError(
                "serialized lifecycle record hash or derived state mismatch"
            )
    if lifecycle.to_dict() != dict(raw):
        raise FormalLifecycleError(
            "serialized lifecycle hash or derived claim state mismatch"
        )
    return lifecycle


def replay_lifecycle_from_canonical_bytes(
    raw_bytes: bytes,
    *,
    checkpoint_manifest: AuthorizationCheckpointManifest,
    ledgers: Sequence[StageCostLedger],
    authorization_receipts: Sequence[StageAuthorizationReceipt],
    qualification_receipts: Sequence[StageQualificationReceipt],
) -> FormalLifecycle:
    """Replay a canonical lifecycle payload against independent typed sources."""

    value = _decode_canonical_bytes(raw_bytes)
    if not isinstance(value, dict):
        raise FormalLifecycleError("serialized lifecycle must be an object")
    return replay_lifecycle(
        value,
        checkpoint_manifest=checkpoint_manifest,
        ledgers=ledgers,
        authorization_receipts=authorization_receipts,
        qualification_receipts=qualification_receipts,
    )
