"""V3 phase-specific readiness receipts for offline contract testing.

This module deliberately produces only ``simulated_nonclaim`` evidence.  It
does not mint production verification, formal eligibility, or a Gate result.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .meas0_formal_lifecycle import (
    PhaseCheckpointTarget,
    SimulatedPhaseCheckpointAuthorization,
    authorize_simulated_phase_checkpoint,
)
from .meas0_trust import AuthorizationCheckpoint, VerificationResult


class PhaseReadinessError(ValueError):
    """A V3 readiness receipt is malformed or violates phase ancestry."""


class PhaseReadinessStage(str, Enum):
    PRE_JCAL_READY = "pre_jcal_ready"
    PILOT_READY = "pilot_ready"
    JAUDIT_READY = "jaudit_ready"
    CONFIRMATORY_READY = "confirmatory_ready"


class PhaseCompletionDisposition(str, Enum):
    ADVANCED = "advanced"
    FAILED = "failed"
    QUARANTINED = "quarantined"


_CHECKPOINT_STAGE = {
    AuthorizationCheckpoint.PRE_JCAL: PhaseReadinessStage.PRE_JCAL_READY,
    AuthorizationCheckpoint.PILOT_START: PhaseReadinessStage.PILOT_READY,
    AuthorizationCheckpoint.POST_PILOT_JAUDIT: PhaseReadinessStage.JAUDIT_READY,
    AuthorizationCheckpoint.CONFIRMATORY_START: (
        PhaseReadinessStage.CONFIRMATORY_READY
    ),
}
_AUTHORIZED_NEXT_ACTION = {
    PhaseReadinessStage.PRE_JCAL_READY: "run_jcal",
    PhaseReadinessStage.PILOT_READY: "run_pilot",
    PhaseReadinessStage.JAUDIT_READY: "run_jaudit",
    PhaseReadinessStage.CONFIRMATORY_READY: "run_confirmatory",
}
_RECEIPT_TOKEN = object()
_COMPLETION_TOKEN = object()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _content_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _hash(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise PhaseReadinessError(f"{label} must be a lowercase SHA-256")
    return value


def _strict_mapping(
    value: object,
    *,
    label: str,
    fields: set[str],
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PhaseReadinessError(f"{label} fields are invalid")
    return value


def _authorization_dict(
    authorization: SimulatedPhaseCheckpointAuthorization,
) -> dict[str, Any]:
    return {
        **authorization.to_dict(),
        "verification": authorization.verification.to_dict(),
    }


def _authorization_from_dict(
    value: object,
    *,
    target: PhaseCheckpointTarget,
) -> SimulatedPhaseCheckpointAuthorization:
    fields = {
        "schema",
        "version",
        "target_hash",
        "verification_hash",
        "claim_scope",
        "production_authorized",
        "test_only",
        "authorization_hash",
        "verification",
    }
    raw = _strict_mapping(
        value,
        label="simulated phase authorization",
        fields=fields,
    )
    verification = VerificationResult.from_dict(raw["verification"])
    result = authorize_simulated_phase_checkpoint(
        target=target,
        verification=verification,
    )
    if dict(raw) != _authorization_dict(result):
        raise PhaseReadinessError(
            "simulated phase authorization content or hash is invalid"
        )
    return result


@dataclass(frozen=True)
class SimulatedPhaseCompletion:
    """Test-only result of the action authorized by one readiness receipt."""

    schema: str
    version: int
    receipt_hash: str
    readiness_stage: PhaseReadinessStage
    disposition: PhaseCompletionDisposition
    evidence_hash: str
    ledger_head_hash: str
    claim_scope: str
    production_authorized: bool
    test_only: bool
    _derivation_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._derivation_token is not _COMPLETION_TOKEN:
            raise PhaseReadinessError(
                "simulated phase completion must be created by its factory"
            )
        if self.schema != "meas0.simulated-phase-completion" or self.version != 1:
            raise PhaseReadinessError(
                "simulated phase completion schema/version is invalid"
            )
        if not isinstance(self.readiness_stage, PhaseReadinessStage):
            object.__setattr__(
                self,
                "readiness_stage",
                PhaseReadinessStage(self.readiness_stage),
            )
        if not isinstance(self.disposition, PhaseCompletionDisposition):
            object.__setattr__(
                self,
                "disposition",
                PhaseCompletionDisposition(self.disposition),
            )
        _hash(self.receipt_hash, "receipt_hash")
        _hash(self.evidence_hash, "evidence_hash")
        _hash(self.ledger_head_hash, "ledger_head_hash")
        if (
            self.claim_scope != "simulated_nonclaim"
            or self.production_authorized is not False
            or self.test_only is not True
        ):
            raise PhaseReadinessError(
                "simulated phase completion cannot carry production authority"
            )

    def _body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "version": self.version,
            "receipt_hash": self.receipt_hash,
            "readiness_stage": self.readiness_stage.value,
            "disposition": self.disposition.value,
            "evidence_hash": self.evidence_hash,
            "ledger_head_hash": self.ledger_head_hash,
            "claim_scope": self.claim_scope,
            "production_authorized": self.production_authorized,
            "test_only": self.test_only,
        }

    @property
    def completion_hash(self) -> str:
        return _content_hash(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "completion_hash": self.completion_hash}

    @classmethod
    def from_dict(cls, value: object) -> SimulatedPhaseCompletion:
        fields = {
            "schema",
            "version",
            "receipt_hash",
            "readiness_stage",
            "disposition",
            "evidence_hash",
            "ledger_head_hash",
            "claim_scope",
            "production_authorized",
            "test_only",
            "completion_hash",
        }
        raw = _strict_mapping(
            value,
            label="simulated phase completion",
            fields=fields,
        )
        result = cls(
            schema=raw["schema"],
            version=raw["version"],
            receipt_hash=raw["receipt_hash"],
            readiness_stage=PhaseReadinessStage(raw["readiness_stage"]),
            disposition=PhaseCompletionDisposition(raw["disposition"]),
            evidence_hash=raw["evidence_hash"],
            ledger_head_hash=raw["ledger_head_hash"],
            claim_scope=raw["claim_scope"],
            production_authorized=raw["production_authorized"],
            test_only=raw["test_only"],
            _derivation_token=_COMPLETION_TOKEN,
        )
        if raw["completion_hash"] != result.completion_hash:
            raise PhaseReadinessError("simulated phase completion hash is invalid")
        return result


@dataclass(frozen=True)
class PhaseReadinessReceipt:
    """Append-only V3 readiness receipt with no production claim authority."""

    schema: str
    version: int
    stage: PhaseReadinessStage
    target: PhaseCheckpointTarget
    authorization: SimulatedPhaseCheckpointAuthorization
    stage_evidence_hashes: tuple[tuple[str, str], ...]
    previous_receipt_hash: str | None
    previous_completion_hash: str | None
    ledger_head_hash: str
    common_ancestry_hash: str
    authorized_next_action: str
    claim_scope: str
    production_authorized: bool
    test_only: bool
    _derivation_token: object = field(default=None, repr=False, compare=False)
    _expected_previous_receipt_hash: str | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _expected_previous_completion_hash: str | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self._derivation_token is not _RECEIPT_TOKEN:
            raise PhaseReadinessError(
                "phase readiness receipt must be created by its factory"
            )
        if self.schema != "meas0.phase-readiness-receipt" or self.version != 3:
            raise PhaseReadinessError("phase readiness schema/version is invalid")
        if not isinstance(self.stage, PhaseReadinessStage):
            object.__setattr__(self, "stage", PhaseReadinessStage(self.stage))
        if not isinstance(self.target, PhaseCheckpointTarget):
            raise PhaseReadinessError(
                "phase readiness requires a typed checkpoint target"
            )
        if not isinstance(
            self.authorization,
            SimulatedPhaseCheckpointAuthorization,
        ):
            raise PhaseReadinessError(
                "phase readiness requires a simulated checkpoint authorization"
            )
        if self.authorization.target != self.target:
            raise PhaseReadinessError(
                "phase readiness authorization target does not match"
            )
        if _CHECKPOINT_STAGE[self.target.checkpoint] is not self.stage:
            raise PhaseReadinessError(
                "phase readiness stage does not match checkpoint target"
            )
        if not isinstance(
            self.stage_evidence_hashes, tuple
        ) or self.stage_evidence_hashes != tuple(self.target.evidence_bindings):
            raise PhaseReadinessError(
                "phase readiness stage-available evidence does not match target"
            )
        if self.previous_receipt_hash is not None:
            _hash(self.previous_receipt_hash, "previous_receipt_hash")
        if self.previous_completion_hash is not None:
            _hash(self.previous_completion_hash, "previous_completion_hash")
        if self.previous_receipt_hash != self._expected_previous_receipt_hash:
            raise PhaseReadinessError(
                "phase readiness previous receipt hash is not factory-derived"
            )
        if self.previous_completion_hash != self._expected_previous_completion_hash:
            raise PhaseReadinessError(
                "phase readiness previous completion hash is not factory-derived"
            )
        is_first = self.stage is PhaseReadinessStage.PRE_JCAL_READY
        if is_first and (
            self.previous_receipt_hash is not None
            or self.previous_completion_hash is not None
        ):
            raise PhaseReadinessError(
                "first phase readiness receipt cannot have a parent"
            )
        if not is_first and (
            self.previous_receipt_hash is None or self.previous_completion_hash is None
        ):
            raise PhaseReadinessError(
                "later phase readiness requires previous receipt and completion"
            )
        if self.ledger_head_hash != self.target.ledger_pre_head_hash:
            raise PhaseReadinessError(
                "phase readiness ledger head does not match checkpoint target"
            )
        if self.common_ancestry_hash != self.target.common_ancestry_hash:
            raise PhaseReadinessError(
                "phase readiness common ancestry does not match checkpoint target"
            )
        if self.authorized_next_action != _AUTHORIZED_NEXT_ACTION[self.stage]:
            raise PhaseReadinessError(
                "phase readiness authorized next action is invalid"
            )
        if (
            self.claim_scope != "simulated_nonclaim"
            or self.production_authorized is not False
            or self.test_only is not True
        ):
            raise PhaseReadinessError(
                "phase readiness receipt cannot carry production authority"
            )

    def _body(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "version": self.version,
            "stage": self.stage.value,
            "target": self.target.to_dict(),
            "authorization": _authorization_dict(self.authorization),
            "stage_evidence_hashes": dict(self.stage_evidence_hashes),
            "previous_receipt_hash": self.previous_receipt_hash,
            "previous_completion_hash": self.previous_completion_hash,
            "ledger_head_hash": self.ledger_head_hash,
            "common_ancestry_hash": self.common_ancestry_hash,
            "authorized_next_action": self.authorized_next_action,
            "claim_scope": self.claim_scope,
            "production_authorized": self.production_authorized,
            "test_only": self.test_only,
        }

    @property
    def receipt_hash(self) -> str:
        return _content_hash(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "receipt_hash": self.receipt_hash}

    @classmethod
    def from_dict(cls, value: object) -> PhaseReadinessReceipt:
        fields = {
            "schema",
            "version",
            "stage",
            "target",
            "authorization",
            "stage_evidence_hashes",
            "previous_receipt_hash",
            "previous_completion_hash",
            "ledger_head_hash",
            "common_ancestry_hash",
            "authorized_next_action",
            "claim_scope",
            "production_authorized",
            "test_only",
            "receipt_hash",
        }
        raw = _strict_mapping(
            value,
            label="phase readiness receipt",
            fields=fields,
        )
        target = PhaseCheckpointTarget.from_dict(raw["target"])
        authorization = _authorization_from_dict(
            raw["authorization"],
            target=target,
        )
        evidence = raw["stage_evidence_hashes"]
        if not isinstance(evidence, Mapping):
            raise PhaseReadinessError(
                "phase readiness stage-available evidence must be a mapping"
            )
        previous_receipt_hash = raw["previous_receipt_hash"]
        previous_completion_hash = raw["previous_completion_hash"]
        result = cls(
            schema=raw["schema"],
            version=raw["version"],
            stage=PhaseReadinessStage(raw["stage"]),
            target=target,
            authorization=authorization,
            stage_evidence_hashes=tuple(sorted(evidence.items())),
            previous_receipt_hash=previous_receipt_hash,
            previous_completion_hash=previous_completion_hash,
            ledger_head_hash=raw["ledger_head_hash"],
            common_ancestry_hash=raw["common_ancestry_hash"],
            authorized_next_action=raw["authorized_next_action"],
            claim_scope=raw["claim_scope"],
            production_authorized=raw["production_authorized"],
            test_only=raw["test_only"],
            _derivation_token=_RECEIPT_TOKEN,
            _expected_previous_receipt_hash=previous_receipt_hash,
            _expected_previous_completion_hash=previous_completion_hash,
        )
        if raw["receipt_hash"] != result.receipt_hash:
            raise PhaseReadinessError("phase readiness receipt hash is invalid")
        return result


def create_simulated_phase_readiness_receipt(
    *,
    target: PhaseCheckpointTarget,
    authorization: SimulatedPhaseCheckpointAuthorization,
    stage_evidence_hashes: Mapping[str, str],
    previous_receipt: PhaseReadinessReceipt | None,
    previous_completion: SimulatedPhaseCompletion | None,
) -> PhaseReadinessReceipt:
    if not isinstance(target, PhaseCheckpointTarget):
        raise PhaseReadinessError("phase readiness requires a typed checkpoint target")
    if not isinstance(
        authorization,
        SimulatedPhaseCheckpointAuthorization,
    ):
        raise PhaseReadinessError(
            "phase readiness requires a simulated checkpoint authorization"
        )
    if authorization.target != target:
        raise PhaseReadinessError("phase readiness authorization target does not match")
    if not isinstance(stage_evidence_hashes, Mapping):
        raise PhaseReadinessError(
            "phase readiness stage-available evidence must be a mapping"
        )
    evidence_tuple = tuple(sorted(stage_evidence_hashes.items()))
    if evidence_tuple != tuple(target.evidence_bindings):
        raise PhaseReadinessError(
            "phase readiness stage-available evidence does not match target"
        )
    stage = _CHECKPOINT_STAGE[target.checkpoint]
    stages = tuple(PhaseReadinessStage)
    stage_index = stages.index(stage)
    if stage_index == 0:
        if previous_receipt is not None or previous_completion is not None:
            raise PhaseReadinessError(
                "first phase readiness receipt cannot have a parent"
            )
        previous_receipt_hash = None
        previous_completion_hash = None
    else:
        if not isinstance(previous_receipt, PhaseReadinessReceipt):
            raise PhaseReadinessError("later phase readiness requires previous receipt")
        if previous_receipt.stage is not stages[stage_index - 1]:
            raise PhaseReadinessError(
                "phase readiness previous receipt is missing or out of order"
            )
        if not isinstance(previous_completion, SimulatedPhaseCompletion):
            raise PhaseReadinessError(
                "later phase readiness requires previous completion"
            )
        if previous_completion.receipt_hash != previous_receipt.receipt_hash:
            raise PhaseReadinessError(
                "phase readiness completion does not bind previous receipt"
            )
        if previous_completion.readiness_stage is not previous_receipt.stage:
            raise PhaseReadinessError(
                "phase readiness completion stage does not match previous receipt"
            )
        if previous_completion.disposition is not PhaseCompletionDisposition.ADVANCED:
            raise PhaseReadinessError("phase readiness parent must have advanced")
        ancestry = (
            target.lifecycle_id,
            target.comparison_block_id,
            target.authority_role_id,
            target.design_hash,
            target.source_lock_hash,
            target.common_ancestry_hash,
        )
        previous_ancestry = (
            previous_receipt.target.lifecycle_id,
            previous_receipt.target.comparison_block_id,
            previous_receipt.target.authority_role_id,
            previous_receipt.target.design_hash,
            previous_receipt.target.source_lock_hash,
            previous_receipt.target.common_ancestry_hash,
        )
        if ancestry != previous_ancestry:
            raise PhaseReadinessError(
                "phase readiness common ancestry does not match previous receipt"
            )
        if target.previous_target_hash != previous_receipt.target.target_hash:
            raise PhaseReadinessError(
                "phase readiness previous target does not match previous receipt"
            )
        if target.ledger_pre_head_hash != previous_completion.ledger_head_hash:
            raise PhaseReadinessError(
                "phase readiness ledger head does not match parent completion"
            )
        previous_receipt_hash = previous_receipt.receipt_hash
        previous_completion_hash = previous_completion.completion_hash
    return PhaseReadinessReceipt(
        schema="meas0.phase-readiness-receipt",
        version=3,
        stage=stage,
        target=target,
        authorization=authorization,
        stage_evidence_hashes=evidence_tuple,
        previous_receipt_hash=previous_receipt_hash,
        previous_completion_hash=previous_completion_hash,
        ledger_head_hash=target.ledger_pre_head_hash,
        common_ancestry_hash=target.common_ancestry_hash,
        authorized_next_action=_AUTHORIZED_NEXT_ACTION[stage],
        claim_scope="simulated_nonclaim",
        production_authorized=False,
        test_only=True,
        _derivation_token=_RECEIPT_TOKEN,
        _expected_previous_receipt_hash=previous_receipt_hash,
        _expected_previous_completion_hash=previous_completion_hash,
    )


def record_simulated_phase_completion(
    *,
    receipt: PhaseReadinessReceipt,
    disposition: PhaseCompletionDisposition,
    evidence_hash: str,
    ledger_head_hash: str,
) -> SimulatedPhaseCompletion:
    if not isinstance(receipt, PhaseReadinessReceipt):
        raise PhaseReadinessError(
            "simulated phase completion requires a readiness receipt"
        )
    return SimulatedPhaseCompletion(
        schema="meas0.simulated-phase-completion",
        version=1,
        receipt_hash=receipt.receipt_hash,
        readiness_stage=receipt.stage,
        disposition=(
            disposition
            if isinstance(disposition, PhaseCompletionDisposition)
            else PhaseCompletionDisposition(disposition)
        ),
        evidence_hash=evidence_hash,
        ledger_head_hash=ledger_head_hash,
        claim_scope="simulated_nonclaim",
        production_authorized=False,
        test_only=True,
        _derivation_token=_COMPLETION_TOKEN,
    )


def validate_phase_readiness_chain(
    receipts: Sequence[PhaseReadinessReceipt],
    completions: Sequence[SimulatedPhaseCompletion],
) -> tuple[PhaseReadinessReceipt, ...]:
    receipt_tuple = tuple(receipts)
    completion_tuple = tuple(completions)
    if not receipt_tuple or len(receipt_tuple) > len(PhaseReadinessStage):
        raise PhaseReadinessError("phase readiness chain length is invalid")
    if not all(isinstance(item, PhaseReadinessReceipt) for item in receipt_tuple):
        raise PhaseReadinessError("phase readiness chain requires typed receipts")
    expected_stages = tuple(PhaseReadinessStage)[: len(receipt_tuple)]
    if tuple(item.stage for item in receipt_tuple) != expected_stages:
        raise PhaseReadinessError(
            "phase readiness receipts are not append-only and ordered"
        )
    if len(completion_tuple) != len(receipt_tuple) - 1 or not all(
        isinstance(item, SimulatedPhaseCompletion) for item in completion_tuple
    ):
        raise PhaseReadinessError(
            "phase readiness chain completion membership is invalid"
        )
    for index, receipt in enumerate(receipt_tuple):
        if index == 0:
            if (
                receipt.previous_receipt_hash is not None
                or receipt.previous_completion_hash is not None
            ):
                raise PhaseReadinessError(
                    "first phase readiness receipt has unexpected ancestry"
                )
            continue
        previous = receipt_tuple[index - 1]
        completion = completion_tuple[index - 1]
        if completion.disposition is not PhaseCompletionDisposition.ADVANCED:
            raise PhaseReadinessError("phase readiness parent must have advanced")
        if (
            receipt.previous_receipt_hash != previous.receipt_hash
            or receipt.previous_completion_hash != completion.completion_hash
            or completion.receipt_hash != previous.receipt_hash
            or completion.readiness_stage is not previous.stage
            or receipt.target.previous_target_hash != previous.target.target_hash
        ):
            raise PhaseReadinessError("phase readiness append-only ancestry is invalid")
        ancestry = (
            receipt.target.lifecycle_id,
            receipt.target.comparison_block_id,
            receipt.target.authority_role_id,
            receipt.target.design_hash,
            receipt.target.source_lock_hash,
            receipt.target.common_ancestry_hash,
        )
        previous_ancestry = (
            previous.target.lifecycle_id,
            previous.target.comparison_block_id,
            previous.target.authority_role_id,
            previous.target.design_hash,
            previous.target.source_lock_hash,
            previous.target.common_ancestry_hash,
        )
        if ancestry != previous_ancestry:
            raise PhaseReadinessError("phase readiness common ancestry is invalid")
        if receipt.ledger_head_hash != completion.ledger_head_hash:
            raise PhaseReadinessError("phase readiness ledger ancestry is invalid")
    return receipt_tuple


__all__ = [
    "PhaseCompletionDisposition",
    "PhaseReadinessError",
    "PhaseReadinessReceipt",
    "PhaseReadinessStage",
    "SimulatedPhaseCompletion",
    "create_simulated_phase_readiness_receipt",
    "record_simulated_phase_completion",
    "validate_phase_readiness_chain",
]
