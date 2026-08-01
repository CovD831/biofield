"""Exact, offline-only MEAS0 V3 confirmatory contract package.

This module deliberately seals *evidence commitments*, not scientific outcome
facts.  Existing Gold, oracle, runner-request, and retained-failure factories
are Pilot-only.  Until those typed factories gain a confirmatory schema, this
module records canonical-evaluation or retained-failure evidence without
inventing ``accepted``, ``detected``, or Judge verdicts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .meas0_budget_policy_v3 import (
    BudgetPolicyV3Error,
    expected_offline_budget_validation_hash_v3,
    FrozenMeas0BudgetPolicyV3,
    validate_frozen_meas0_budget_manifest_v3,
)
from .meas0_formal_metrics import FormalCaseIdentity, formal_attack_manifest
from .meas0_formal_runner import BackendMode, FailureCode, FormalBackendDescriptor
from .meas0_input_manifest import (
    FailurePolicyContract,
    InputManifestEntry,
    ProtectedInputCorpus,
)
from .meas0_phase_readiness import (
    PhaseCompletionDisposition,
    PhaseReadinessReceipt,
    PhaseReadinessStage,
    SimulatedPhaseCompletion,
    validate_phase_readiness_chain,
)
from .meas0_readiness import PriceManifest, arm_order_manifest
from .meas0_retained_failure_v3 import UNREPRESENTABLE_FAILURE_EVIDENCE_GAPS
from .meas0_stage_cost import StageBudgetManifest, StageCostLedger
from .meas0_trust import AuthorizationCheckpoint


CONFIRMATORY_MANIFEST_SCHEMA = "meas0.confirmatory-input-manifest.v3"
CONFIRMATORY_PLAN_SCHEMA = "meas0.confirmatory-plan.v3"
CONFIRMATORY_AUTHORIZATION_SCHEMA = "meas0.confirmatory-authorization.v3"
CONFIRMATORY_EVIDENCE_SCHEMA = "meas0.simulated-confirmatory-evidence-commitment.v3"
CONFIRMATORY_COMMITMENT_SCHEMA = "meas0.simulated-confirmatory-arm-case-commitment.v3"
CONFIRMATORY_COMMITMENT_RUN_SCHEMA = "meas0.simulated-confirmatory-commitment-run.v3"
CONFIRMATORY_COMMITMENT_PACKAGE_SCHEMA = (
    "meas0.simulated-confirmatory-commitment-package.v3"
)
CONFIRMATORY_PACKAGE_GOLD_ORACLE_GAP = (
    "GoldOutcomeFacts, detection oracle adapters, FormalArmRequest, and "
    "RetainedFailureOutcome remain Pilot-only; this B5 slice therefore seals "
    "non-claim evidence commitments and cannot emit scientific outcome facts."
)
_CLAIM_SCOPE = "simulated_nonclaim"
_ARMS = arm_order_manifest().resolved_arm_order


class ConfirmatoryContractError(ValueError):
    """The confirmatory package is incomplete, mixed, or not factory-derived."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as error:
        raise ConfirmatoryContractError(
            "confirmatory value is not canonical JSON"
        ) from error


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _bytes_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict_canonical_evidence_bytes(value: object) -> bytes:
    if type(value) is not bytes:
        raise ConfirmatoryContractError(
            "confirmatory raw commitment must be exact canonical JSON bytes"
        )

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ConfirmatoryContractError(
                    "confirmatory raw commitment contains duplicate fields"
                )
            result[key] = item
        return result

    try:
        decoded = json.loads(
            value.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ConfirmatoryContractError(
                    f"confirmatory raw commitment is non-finite: {token}"
                )
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ConfirmatoryContractError(
            "confirmatory raw commitment is not strict JSON"
        ) from error
    if not isinstance(decoded, Mapping) or value != _canonical_bytes(decoded):
        raise ConfirmatoryContractError(
            "confirmatory raw commitment bytes are not canonical"
        )
    return value


def _decode_canonical_package_bytes(value: object) -> Mapping[str, Any]:
    """Decode one exact package JSON payload without trusting persisted facts."""

    if type(value) is not bytes:
        raise ConfirmatoryContractError(
            "confirmatory package archive must be exact bytes"
        )

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ConfirmatoryContractError(
                    "confirmatory package archive contains duplicate fields"
                )
            result[key] = item
        return result

    try:
        decoded = json.loads(
            value.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ConfirmatoryContractError(
                    f"confirmatory package archive is non-finite: {token}"
                )
            ),
        )
    except ConfirmatoryContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise ConfirmatoryContractError(
            "confirmatory package archive is not strict JSON"
        ) from error
    if not isinstance(decoded, Mapping) or value != _canonical_bytes(decoded):
        raise ConfirmatoryContractError(
            "confirmatory package archive bytes are not canonical"
        )
    return decoded


def _digest(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ConfirmatoryContractError(f"{label} must be a lowercase SHA-256")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfirmatoryContractError(f"{label} must be non-empty text")
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


def _typed_jaudit_receipt(value: object) -> PhaseReadinessReceipt:
    if (
        not isinstance(value, PhaseReadinessReceipt)
        or value.stage is not PhaseReadinessStage.JAUDIT_READY
        or value.target.checkpoint is not AuthorizationCheckpoint.POST_PILOT_JAUDIT
        or value.claim_scope != _CLAIM_SCOPE
        or value.production_authorized
        or not value.test_only
    ):
        raise ConfirmatoryContractError(
            "confirmatory manifest requires typed simulated JAUDIT_READY ancestry"
        )
    return value


_MANIFEST_TOKEN = object()


@dataclass(frozen=True)
class ConfirmatoryInputManifest:
    schema: str
    entries: tuple[InputManifestEntry, ...]
    protected_corpus_hash: str
    jaudit_receipt_hash: str
    jaudit_target_hash: str
    lifecycle_id: str
    comparison_block_id: str
    authority_role_id: str
    design_hash: str
    source_lock_hash: str
    confirmatory_lock_hash: str
    common_ancestry_hash: str
    manifest_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(self.entries))
        expected = formal_attack_manifest("confirmatory").cases
        if (
            self._factory_token is not _MANIFEST_TOKEN
            or self.schema != CONFIRMATORY_MANIFEST_SCHEMA
            or len(self.entries) != 144
            or not all(isinstance(item, InputManifestEntry) for item in self.entries)
            or tuple(item.phase for item in self.entries) != ("confirmatory",) * 144
            or tuple(item.case_index for item in self.entries) != tuple(range(144))
            or tuple(item.case_id for item in self.entries)
            != tuple(item.case_id for item in expected)
        ):
            raise ConfirmatoryContractError(
                "confirmatory manifest must have exact 144 frozen entries"
            )
        for name in (
            "protected_corpus_hash",
            "jaudit_receipt_hash",
            "jaudit_target_hash",
            "design_hash",
            "source_lock_hash",
            "confirmatory_lock_hash",
            "common_ancestry_hash",
            "manifest_hash",
        ):
            _digest(getattr(self, name), f"confirmatory manifest {name}")
        for name in (
            "lifecycle_id",
            "comparison_block_id",
            "authority_role_id",
        ):
            _text(getattr(self, name), f"confirmatory manifest {name}")
        if self.manifest_hash != _canonical_hash(self._body()):
            raise ConfirmatoryContractError("confirmatory manifest hash mismatch")

    def _body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "phase": "confirmatory",
            "entries": [item.to_dict() for item in self.entries],
            "protected_corpus_hash": self.protected_corpus_hash,
            "jaudit_receipt_hash": self.jaudit_receipt_hash,
            "jaudit_target_hash": self.jaudit_target_hash,
            "lifecycle_id": self.lifecycle_id,
            "comparison_block_id": self.comparison_block_id,
            "authority_role_id": self.authority_role_id,
            "design_hash": self.design_hash,
            "source_lock_hash": self.source_lock_hash,
            "confirmatory_lock_hash": self.confirmatory_lock_hash,
            "common_ancestry_hash": self.common_ancestry_hash,
            "claim_scope": _CLAIM_SCOPE,
            "production_authorized": False,
            "formal_eligible": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "manifest_hash": self.manifest_hash}

    @classmethod
    def create(
        cls,
        *,
        corpus: ProtectedInputCorpus,
        jaudit_readiness: PhaseReadinessReceipt,
    ) -> ConfirmatoryInputManifest:
        if not isinstance(corpus, ProtectedInputCorpus):
            raise ConfirmatoryContractError(
                "confirmatory manifest requires typed ProtectedInputCorpus"
            )
        if corpus.phase != "confirmatory" or len(corpus.case_inputs) != 144:
            raise ConfirmatoryContractError(
                "confirmatory corpus must retain exact 144 cases"
            )
        expected = formal_attack_manifest("confirmatory").cases
        if tuple(item.case for item in corpus.case_inputs) != expected:
            raise ConfirmatoryContractError(
                "confirmatory corpus membership/order differs from frozen scope"
            )
        try:
            rederived_corpus = ProtectedInputCorpus.create(
                phase="confirmatory",
                case_inputs=corpus.case_inputs,
            )
        except ValueError as error:
            raise ConfirmatoryContractError(
                "confirmatory corpus membership/order is invalid"
            ) from error
        if rederived_corpus != corpus:
            raise ConfirmatoryContractError(
                "confirmatory corpus hash differs from typed membership"
            )
        receipt = _typed_jaudit_receipt(jaudit_readiness)
        bindings = dict(receipt.target.evidence_bindings)
        confirmatory_lock_hash = bindings.get("confirmatory_lock")
        _digest(confirmatory_lock_hash, "confirmatory lock hash")
        entries = tuple(
            InputManifestEntry.from_protected_input(
                case_index=index,
                protected_input=item,
            )
            for index, item in enumerate(corpus.case_inputs)
        )
        body = {
            "schema": CONFIRMATORY_MANIFEST_SCHEMA,
            "phase": "confirmatory",
            "entries": [item.to_dict() for item in entries],
            "protected_corpus_hash": corpus.corpus_hash,
            "jaudit_receipt_hash": receipt.receipt_hash,
            "jaudit_target_hash": receipt.target.target_hash,
            "lifecycle_id": receipt.target.lifecycle_id,
            "comparison_block_id": receipt.target.comparison_block_id,
            "authority_role_id": receipt.target.authority_role_id,
            "design_hash": receipt.target.design_hash,
            "source_lock_hash": receipt.target.source_lock_hash,
            "confirmatory_lock_hash": confirmatory_lock_hash,
            "common_ancestry_hash": receipt.common_ancestry_hash,
            "claim_scope": _CLAIM_SCOPE,
            "production_authorized": False,
            "formal_eligible": False,
        }
        return cls(
            schema=CONFIRMATORY_MANIFEST_SCHEMA,
            entries=entries,
            protected_corpus_hash=corpus.corpus_hash,
            jaudit_receipt_hash=receipt.receipt_hash,
            jaudit_target_hash=receipt.target.target_hash,
            lifecycle_id=receipt.target.lifecycle_id,
            comparison_block_id=receipt.target.comparison_block_id,
            authority_role_id=receipt.target.authority_role_id,
            design_hash=receipt.target.design_hash,
            source_lock_hash=receipt.target.source_lock_hash,
            confirmatory_lock_hash=confirmatory_lock_hash,
            common_ancestry_hash=receipt.common_ancestry_hash,
            manifest_hash=_canonical_hash(body),
            _factory_token=_MANIFEST_TOKEN,
        )


_PLAN_TOKEN = object()


@dataclass(frozen=True)
class FormalConfirmatoryPlan:
    schema: str
    input_manifest: ConfirmatoryInputManifest
    arm_order: tuple[str, ...]
    provider_descriptors: tuple[FormalBackendDescriptor, ...]
    stage_cost_pre_ledger: StageCostLedger
    input_manifest_hash: str
    provider_manifest_hash: str
    price_manifest_hash: str
    stage_budget_manifest_hash: str
    frozen_budget_policy_hash: str
    budget_validation_hash: str
    stage_cost_pre_ledger_hash: str
    jaudit_completion_hash: str
    jaudit_completion_evidence_hash: str
    formal_oracle_authority_hash: str
    gold_binding_hash: str
    confirmatory_lock_hash: str
    source_lock_hash: str
    common_ancestry_hash: str
    comparison_block_id: str
    plan_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "arm_order", tuple(self.arm_order))
        object.__setattr__(
            self,
            "provider_descriptors",
            tuple(self.provider_descriptors),
        )
        if (
            self._factory_token is not _PLAN_TOKEN
            or self.schema != CONFIRMATORY_PLAN_SCHEMA
            or not isinstance(self.input_manifest, ConfirmatoryInputManifest)
            or not isinstance(self.stage_cost_pre_ledger, StageCostLedger)
            or self.arm_order != _ARMS
            or tuple(item.arm_id for item in self.provider_descriptors) != _ARMS
            or not all(
                isinstance(item, FormalBackendDescriptor)
                and item.mode is BackendMode.TEST_ONLY
                for item in self.provider_descriptors
            )
        ):
            raise ConfirmatoryContractError(
                "confirmatory plan must be factory-derived and test-only"
            )
        for name in (
            "input_manifest_hash",
            "provider_manifest_hash",
            "price_manifest_hash",
            "stage_budget_manifest_hash",
            "frozen_budget_policy_hash",
            "budget_validation_hash",
            "stage_cost_pre_ledger_hash",
            "jaudit_completion_hash",
            "jaudit_completion_evidence_hash",
            "formal_oracle_authority_hash",
            "gold_binding_hash",
            "confirmatory_lock_hash",
            "source_lock_hash",
            "common_ancestry_hash",
            "plan_hash",
        ):
            _digest(getattr(self, name), f"confirmatory plan {name}")
        _text(self.comparison_block_id, "confirmatory plan comparison block")
        if (
            self.input_manifest_hash != self.input_manifest.manifest_hash
            or self.frozen_budget_policy_hash
            != FrozenMeas0BudgetPolicyV3.frozen_v1().contract_hash
            or self.budget_validation_hash
            != expected_offline_budget_validation_hash_v3(
                phase="confirmatory",
                stage_budget_manifest_hash=self.stage_budget_manifest_hash,
                price_manifest_hash=self.price_manifest_hash,
            )
            or self.stage_cost_pre_ledger_hash
            != self.stage_cost_pre_ledger.contract_hash
            or self.confirmatory_lock_hash != self.input_manifest.confirmatory_lock_hash
            or self.source_lock_hash != self.input_manifest.source_lock_hash
            or self.common_ancestry_hash != self.input_manifest.common_ancestry_hash
            or self.comparison_block_id != self.input_manifest.comparison_block_id
            or self.plan_hash != _canonical_hash(self._body())
        ):
            raise ConfirmatoryContractError(
                "confirmatory plan common ancestry or hash is invalid"
            )

    @property
    def case_count(self) -> int:
        return len(self.input_manifest.entries)

    @property
    def arm_case_count(self) -> int:
        return self.case_count * len(self.arm_order)

    @property
    def claim_scope(self) -> str:
        return _CLAIM_SCOPE

    @property
    def production_authorized(self) -> bool:
        return False

    @property
    def formal_eligible(self) -> bool:
        return False

    def _body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "input_manifest_hash": self.input_manifest_hash,
            "arm_order": list(self.arm_order),
            "provider_descriptors": [
                item.to_dict() for item in self.provider_descriptors
            ],
            "provider_manifest_hash": self.provider_manifest_hash,
            "price_manifest_hash": self.price_manifest_hash,
            "stage_budget_manifest_hash": self.stage_budget_manifest_hash,
            "frozen_budget_policy_hash": self.frozen_budget_policy_hash,
            "budget_validation_hash": self.budget_validation_hash,
            "stage_cost_pre_ledger_hash": self.stage_cost_pre_ledger_hash,
            "jaudit_completion_hash": self.jaudit_completion_hash,
            "jaudit_completion_evidence_hash": (self.jaudit_completion_evidence_hash),
            "formal_oracle_authority_hash": self.formal_oracle_authority_hash,
            "gold_binding_hash": self.gold_binding_hash,
            "confirmatory_lock_hash": self.confirmatory_lock_hash,
            "source_lock_hash": self.source_lock_hash,
            "common_ancestry_hash": self.common_ancestry_hash,
            "comparison_block_id": self.comparison_block_id,
            "claim_scope": self.claim_scope,
            "production_authorized": self.production_authorized,
            "formal_eligible": self.formal_eligible,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "plan_hash": self.plan_hash}

    @classmethod
    def create(
        cls,
        *,
        input_manifest: ConfirmatoryInputManifest,
        readiness_receipts: Sequence[PhaseReadinessReceipt],
        readiness_completions: Sequence[SimulatedPhaseCompletion],
        price_manifest: PriceManifest,
        stage_budget_manifest: StageBudgetManifest,
        stage_cost_pre_ledger: StageCostLedger,
        provider_descriptors: Sequence[FormalBackendDescriptor],
    ) -> FormalConfirmatoryPlan:
        if not isinstance(input_manifest, ConfirmatoryInputManifest):
            raise ConfirmatoryContractError(
                "confirmatory plan requires its distinct typed manifest"
            )
        receipts = tuple(readiness_receipts)
        completions = tuple(readiness_completions)
        if (
            tuple(item.stage for item in receipts)
            != (
                PhaseReadinessStage.PRE_JCAL_READY,
                PhaseReadinessStage.PILOT_READY,
                PhaseReadinessStage.JAUDIT_READY,
            )
            or len(completions) != 3
        ):
            raise ConfirmatoryContractError(
                "confirmatory plan requires the exact readiness prefix"
            )
        try:
            validate_phase_readiness_chain(receipts, completions[:2])
        except ValueError as error:
            raise ConfirmatoryContractError(
                "confirmatory readiness prefix is invalid"
            ) from error
        jaudit = receipts[-1]
        jaudit_completion = completions[-1]
        try:
            restored_completion = SimulatedPhaseCompletion.from_dict(
                jaudit_completion.to_dict()
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise ConfirmatoryContractError(
                "confirmatory plan requires a codec-valid typed J-AUDIT completion"
            ) from error
        if (
            restored_completion != jaudit_completion
            or jaudit_completion.receipt_hash != jaudit.receipt_hash
            or jaudit_completion.readiness_stage is not PhaseReadinessStage.JAUDIT_READY
            or jaudit_completion.disposition is not PhaseCompletionDisposition.ADVANCED
            or jaudit_completion.claim_scope != _CLAIM_SCOPE
            or jaudit_completion.production_authorized
            or not jaudit_completion.test_only
        ):
            raise ConfirmatoryContractError(
                "confirmatory plan requires typed ADVANCED J-AUDIT completion"
            )
        if (
            jaudit.receipt_hash != input_manifest.jaudit_receipt_hash
            or jaudit.target.target_hash != input_manifest.jaudit_target_hash
        ):
            raise ConfirmatoryContractError(
                "confirmatory manifest and readiness prefix diverged"
            )
        if not isinstance(price_manifest, PriceManifest):
            raise ConfirmatoryContractError(
                "confirmatory plan requires typed PriceManifest"
            )
        if (
            price_manifest.currency != "USD"
            or price_manifest.direct_cap_microunits > 100_000_000
        ):
            raise ConfirmatoryContractError(
                "confirmatory price exceeds the frozen 100 USD cap"
            )
        if not isinstance(stage_budget_manifest, StageBudgetManifest):
            raise ConfirmatoryContractError(
                "confirmatory plan requires typed StageBudgetManifest"
            )
        try:
            budget_validation = validate_frozen_meas0_budget_manifest_v3(
                phase="confirmatory",
                stage_budget_manifest=stage_budget_manifest,
                price_manifest=price_manifest,
            )
        except BudgetPolicyV3Error as error:
            raise ConfirmatoryContractError(
                f"confirmatory frozen budget is invalid: {error}"
            ) from error
        if not isinstance(stage_cost_pre_ledger, StageCostLedger):
            raise ConfirmatoryContractError(
                "confirmatory plan requires typed StageCost pre-ledger"
            )
        if (
            stage_cost_pre_ledger.price_manifest_hash != price_manifest.contract_hash
            or stage_cost_pre_ledger.budget_manifest.contract_hash
            != stage_budget_manifest.contract_hash
            or stage_cost_pre_ledger.contract_hash != jaudit_completion.ledger_head_hash
            or any(
                item.phase == "confirmatory" for item in stage_cost_pre_ledger.entries
            )
            or stage_cost_pre_ledger.phase_decision("confirmatory").stopped
        ):
            raise ConfirmatoryContractError(
                "confirmatory StageCost pre-ledger ancestry is invalid"
            )
        pre_bindings = dict(receipts[0].target.evidence_bindings)
        pilot_bindings = dict(receipts[1].target.evidence_bindings)
        jaudit_bindings = dict(jaudit.target.evidence_bindings)
        if (
            pre_bindings.get("price_manifest") != price_manifest.contract_hash
            or pre_bindings.get("stage_budget_manifest")
            != stage_budget_manifest.contract_hash
        ):
            raise ConfirmatoryContractError(
                "confirmatory price/budget differs from readiness ancestry"
            )
        descriptors = tuple(provider_descriptors)
        if tuple(item.arm_id for item in descriptors) != _ARMS or not all(
            isinstance(item, FormalBackendDescriptor)
            and item.mode is BackendMode.TEST_ONLY
            for item in descriptors
        ):
            raise ConfirmatoryContractError(
                "confirmatory providers must be exact ordered test-only descriptors"
            )
        provider_hash = _canonical_hash([item.to_dict() for item in descriptors])
        body = {
            "schema": CONFIRMATORY_PLAN_SCHEMA,
            "input_manifest_hash": input_manifest.manifest_hash,
            "arm_order": list(_ARMS),
            "provider_descriptors": [item.to_dict() for item in descriptors],
            "provider_manifest_hash": provider_hash,
            "price_manifest_hash": price_manifest.contract_hash,
            "stage_budget_manifest_hash": stage_budget_manifest.contract_hash,
            "frozen_budget_policy_hash": budget_validation.frozen_policy_hash,
            "budget_validation_hash": budget_validation.validation_hash,
            "stage_cost_pre_ledger_hash": stage_cost_pre_ledger.contract_hash,
            "jaudit_completion_hash": jaudit_completion.completion_hash,
            "jaudit_completion_evidence_hash": jaudit_completion.evidence_hash,
            "formal_oracle_authority_hash": pilot_bindings["formal_oracle_authority"],
            "gold_binding_hash": pilot_bindings["gold_binding"],
            "confirmatory_lock_hash": jaudit_bindings["confirmatory_lock"],
            "source_lock_hash": jaudit.target.source_lock_hash,
            "common_ancestry_hash": jaudit.common_ancestry_hash,
            "comparison_block_id": jaudit.target.comparison_block_id,
            "claim_scope": _CLAIM_SCOPE,
            "production_authorized": False,
            "formal_eligible": False,
        }
        return cls(
            schema=CONFIRMATORY_PLAN_SCHEMA,
            input_manifest=input_manifest,
            arm_order=_ARMS,
            provider_descriptors=descriptors,
            stage_cost_pre_ledger=stage_cost_pre_ledger,
            input_manifest_hash=input_manifest.manifest_hash,
            provider_manifest_hash=provider_hash,
            price_manifest_hash=price_manifest.contract_hash,
            stage_budget_manifest_hash=stage_budget_manifest.contract_hash,
            frozen_budget_policy_hash=budget_validation.frozen_policy_hash,
            budget_validation_hash=budget_validation.validation_hash,
            stage_cost_pre_ledger_hash=stage_cost_pre_ledger.contract_hash,
            jaudit_completion_hash=jaudit_completion.completion_hash,
            jaudit_completion_evidence_hash=jaudit_completion.evidence_hash,
            formal_oracle_authority_hash=pilot_bindings["formal_oracle_authority"],
            gold_binding_hash=pilot_bindings["gold_binding"],
            confirmatory_lock_hash=jaudit_bindings["confirmatory_lock"],
            source_lock_hash=jaudit.target.source_lock_hash,
            common_ancestry_hash=jaudit.common_ancestry_hash,
            comparison_block_id=jaudit.target.comparison_block_id,
            plan_hash=_canonical_hash(body),
            _factory_token=_PLAN_TOKEN,
        )


_AUTH_TOKEN = object()


@dataclass(frozen=True)
class FormalConfirmatoryAuthorization:
    schema: str
    plan: FormalConfirmatoryPlan
    plan_hash: str
    readiness_receipt_hash: str
    readiness_target_hash: str
    input_manifest_hash: str
    provider_manifest_hash: str
    common_ancestry_hash: str
    comparison_block_id: str
    authorization_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._factory_token is not _AUTH_TOKEN
            or self.schema != CONFIRMATORY_AUTHORIZATION_SCHEMA
            or not isinstance(self.plan, FormalConfirmatoryPlan)
        ):
            raise ConfirmatoryContractError(
                "confirmatory authorization must be factory-derived"
            )
        for name in (
            "plan_hash",
            "readiness_receipt_hash",
            "readiness_target_hash",
            "input_manifest_hash",
            "provider_manifest_hash",
            "common_ancestry_hash",
            "authorization_hash",
        ):
            _digest(getattr(self, name), f"confirmatory authorization {name}")
        if (
            self.plan_hash != self.plan.plan_hash
            or self.input_manifest_hash != self.plan.input_manifest_hash
            or self.provider_manifest_hash != self.plan.provider_manifest_hash
            or self.common_ancestry_hash != self.plan.common_ancestry_hash
            or self.comparison_block_id != self.plan.comparison_block_id
        ):
            raise ConfirmatoryContractError(
                "confirmatory authorization embedded plan binding mismatch"
            )
        if self.authorization_hash != _canonical_hash(self._body()):
            raise ConfirmatoryContractError("confirmatory authorization hash mismatch")

    def _body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "plan_hash": self.plan_hash,
            "readiness_receipt_hash": self.readiness_receipt_hash,
            "readiness_target_hash": self.readiness_target_hash,
            "input_manifest_hash": self.input_manifest_hash,
            "provider_manifest_hash": self.provider_manifest_hash,
            "common_ancestry_hash": self.common_ancestry_hash,
            "comparison_block_id": self.comparison_block_id,
            "claim_scope": _CLAIM_SCOPE,
            "production_authorized": False,
            "formal_eligible": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "authorization_hash": self.authorization_hash}

    @classmethod
    def create(
        cls,
        *,
        plan: FormalConfirmatoryPlan,
        confirmatory_readiness: PhaseReadinessReceipt,
    ) -> FormalConfirmatoryAuthorization:
        if not isinstance(plan, FormalConfirmatoryPlan):
            raise ConfirmatoryContractError(
                "confirmatory authorization requires typed plan"
            )
        receipt = confirmatory_readiness
        if (
            not isinstance(receipt, PhaseReadinessReceipt)
            or receipt.stage is not PhaseReadinessStage.CONFIRMATORY_READY
            or receipt.target.checkpoint
            is not AuthorizationCheckpoint.CONFIRMATORY_START
            or receipt.claim_scope != _CLAIM_SCOPE
            or receipt.production_authorized
            or not receipt.test_only
        ):
            raise ConfirmatoryContractError(
                "confirmatory authorization requires simulated CONFIRMATORY_READY"
            )
        bindings = dict(receipt.target.evidence_bindings)
        expected = {
            "confirmatory_input_manifest": plan.input_manifest_hash,
            "confirmatory_plan": plan.plan_hash,
            "provider_manifest": plan.provider_manifest_hash,
            "confirmatory_lock": plan.confirmatory_lock_hash,
        }
        for name, value in expected.items():
            if bindings.get(name) != value:
                raise ConfirmatoryContractError(
                    f"confirmatory readiness {name} binding is invalid"
                )
        if (
            receipt.common_ancestry_hash != plan.common_ancestry_hash
            or receipt.target.comparison_block_id != plan.comparison_block_id
            or receipt.target.source_lock_hash != plan.source_lock_hash
        ):
            raise ConfirmatoryContractError(
                "confirmatory authorization common ancestry is invalid"
            )
        body = {
            "schema": CONFIRMATORY_AUTHORIZATION_SCHEMA,
            "plan_hash": plan.plan_hash,
            "readiness_receipt_hash": receipt.receipt_hash,
            "readiness_target_hash": receipt.target.target_hash,
            "input_manifest_hash": plan.input_manifest_hash,
            "provider_manifest_hash": plan.provider_manifest_hash,
            "common_ancestry_hash": plan.common_ancestry_hash,
            "comparison_block_id": plan.comparison_block_id,
            "claim_scope": _CLAIM_SCOPE,
            "production_authorized": False,
            "formal_eligible": False,
        }
        return cls(
            schema=CONFIRMATORY_AUTHORIZATION_SCHEMA,
            plan=plan,
            plan_hash=plan.plan_hash,
            readiness_receipt_hash=receipt.receipt_hash,
            readiness_target_hash=receipt.target.target_hash,
            input_manifest_hash=plan.input_manifest_hash,
            provider_manifest_hash=plan.provider_manifest_hash,
            common_ancestry_hash=plan.common_ancestry_hash,
            comparison_block_id=plan.comparison_block_id,
            authorization_hash=_canonical_hash(body),
            _factory_token=_AUTH_TOKEN,
        )

    def bind_commitment(
        self,
        *,
        execution_index: int,
        evidence: SimulatedConfirmatoryEvidenceCommitment,
        stage_cost_ledger: StageCostLedger,
    ) -> SimulatedConfirmatoryArmCaseCommitment:
        return SimulatedConfirmatoryArmCaseCommitment.create(
            authorization=self,
            execution_index=execution_index,
            evidence=evidence,
            stage_cost_ledger=stage_cost_ledger,
        )


_EVIDENCE_TOKEN = object()


@dataclass(frozen=True)
class SimulatedConfirmatoryEvidenceCommitment:
    schema: str
    tag: str
    case: FormalCaseIdentity
    arm_id: str
    input_entry_hash: str
    raw_evidence_sha256: str
    failure_policy_hash: str
    failure_code: str | None
    result_validity: None
    automatic_status: None
    denominator_retained: None
    denominator_projection_derived: bool
    accepted: None
    detected: None
    judge_verdict: None
    execution_verified: bool
    cost_verified: bool
    evidence_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._factory_token is not _EVIDENCE_TOKEN
            or self.schema != CONFIRMATORY_EVIDENCE_SCHEMA
            or not isinstance(self.case, FormalCaseIdentity)
            or self.case.phase != "confirmatory"
            or self.arm_id not in _ARMS
            or self.tag
            not in {
                "unverified_canonical_evaluation_commitment",
                "unverified_retained_failure_commitment",
            }
            or self.result_validity is not None
            or self.automatic_status is not None
            or self.denominator_retained is not None
            or self.denominator_projection_derived is not False
            or self.accepted is not None
            or self.detected is not None
            or self.judge_verdict is not None
            or self.execution_verified is not False
            or self.cost_verified is not False
        ):
            raise ConfirmatoryContractError(
                "confirmatory outcome evidence must be factory-derived"
            )
        _digest(self.input_entry_hash, "confirmatory input entry hash")
        _digest(self.raw_evidence_sha256, "confirmatory raw evidence hash")
        _digest(self.failure_policy_hash, "confirmatory failure policy hash")
        _digest(self.evidence_hash, "confirmatory evidence hash")
        if self.tag == "unverified_canonical_evaluation_commitment":
            if self.failure_code is not None:
                raise ConfirmatoryContractError(
                    "unfused canonical evidence cannot report outcome facts"
                )
        elif self.failure_code is None:
            raise ConfirmatoryContractError(
                "failure commitment requires a committed failure code"
            )
        if self.evidence_hash != _canonical_hash(self._body()):
            raise ConfirmatoryContractError("confirmatory evidence hash mismatch")

    @property
    def claim_scope(self) -> str:
        return _CLAIM_SCOPE

    @property
    def formal_eligible(self) -> bool:
        return False

    def _body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "tag": self.tag,
            "case": self.case.to_dict(),
            "arm_id": self.arm_id,
            "input_entry_hash": self.input_entry_hash,
            "raw_evidence_sha256": self.raw_evidence_sha256,
            "failure_policy_hash": self.failure_policy_hash,
            "failure_code": self.failure_code,
            "result_validity": self.result_validity,
            "automatic_status": self.automatic_status,
            "denominator_retained": self.denominator_retained,
            "denominator_projection_derived": (self.denominator_projection_derived),
            "accepted": self.accepted,
            "detected": self.detected,
            "judge_verdict": self.judge_verdict,
            "execution_verified": self.execution_verified,
            "cost_verified": self.cost_verified,
            "claim_scope": self.claim_scope,
            "production_authorized": False,
            "formal_eligible": self.formal_eligible,
            "commitment_only": True,
            "outcome_facts_derived": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "evidence_hash": self.evidence_hash}

    @classmethod
    def _create(
        cls,
        *,
        entry: InputManifestEntry,
        arm_id: str,
        raw_evidence_bytes: bytes,
        tag: str,
        failure_code: str | None,
    ) -> SimulatedConfirmatoryEvidenceCommitment:
        if (
            not isinstance(entry, InputManifestEntry)
            or entry.phase != "confirmatory"
            or arm_id not in _ARMS
        ):
            raise ConfirmatoryContractError(
                "confirmatory evidence requires a frozen manifest entry and arm"
            )
        raw_evidence_bytes = _strict_canonical_evidence_bytes(raw_evidence_bytes)
        body = {
            "schema": CONFIRMATORY_EVIDENCE_SCHEMA,
            "tag": tag,
            "case": formal_attack_manifest("confirmatory")
            .cases[entry.case_index]
            .to_dict(),
            "arm_id": arm_id,
            "input_entry_hash": entry.entry_hash,
            "raw_evidence_sha256": _bytes_hash(raw_evidence_bytes),
            "failure_policy_hash": entry.failure_policy_hash,
            "failure_code": failure_code,
            "result_validity": None,
            "automatic_status": None,
            "denominator_retained": None,
            "denominator_projection_derived": False,
            "accepted": None,
            "detected": None,
            "judge_verdict": None,
            "execution_verified": False,
            "cost_verified": False,
            "claim_scope": _CLAIM_SCOPE,
            "production_authorized": False,
            "formal_eligible": False,
            "commitment_only": True,
            "outcome_facts_derived": False,
        }
        return cls(
            schema=CONFIRMATORY_EVIDENCE_SCHEMA,
            tag=tag,
            case=formal_attack_manifest("confirmatory").cases[entry.case_index],
            arm_id=arm_id,
            input_entry_hash=entry.entry_hash,
            raw_evidence_sha256=_bytes_hash(raw_evidence_bytes),
            failure_policy_hash=entry.failure_policy_hash,
            failure_code=failure_code,
            result_validity=None,
            automatic_status=None,
            denominator_retained=None,
            denominator_projection_derived=False,
            accepted=None,
            detected=None,
            judge_verdict=None,
            execution_verified=False,
            cost_verified=False,
            evidence_hash=_canonical_hash(body),
            _factory_token=_EVIDENCE_TOKEN,
        )

    @classmethod
    def from_unverified_canonical_evaluation_commitment(
        cls,
        *,
        entry: InputManifestEntry,
        arm_id: str,
        raw_evidence_bytes: bytes,
    ) -> SimulatedConfirmatoryEvidenceCommitment:
        return cls._create(
            entry=entry,
            arm_id=arm_id,
            raw_evidence_bytes=raw_evidence_bytes,
            tag="unverified_canonical_evaluation_commitment",
            failure_code=None,
        )

    @classmethod
    def from_unverified_retained_failure_commitment(
        cls,
        *,
        entry: InputManifestEntry,
        arm_id: str,
        failure_policy: FailurePolicyContract,
        failure_code: FailureCode,
        raw_evidence_bytes: bytes,
    ) -> SimulatedConfirmatoryEvidenceCommitment:
        if (
            not isinstance(failure_policy, FailurePolicyContract)
            or entry.failure_policy_hash != failure_policy.contract_hash
            or not isinstance(failure_code, FailureCode)
        ):
            raise ConfirmatoryContractError(
                "retained failure requires the typed frozen failure policy"
            )
        if failure_code in UNREPRESENTABLE_FAILURE_EVIDENCE_GAPS:
            raise ConfirmatoryContractError(
                "current typed evidence cannot prove or represent "
                f"{failure_code.value}: "
                f"{UNREPRESENTABLE_FAILURE_EVIDENCE_GAPS[failure_code]}"
            )
        if not any(
            item.failure_code is failure_code for item in failure_policy.dispositions
        ):
            raise ConfirmatoryContractError(
                "failure code is absent from the frozen policy"
            )
        return cls._create(
            entry=entry,
            arm_id=arm_id,
            raw_evidence_bytes=raw_evidence_bytes,
            tag="unverified_retained_failure_commitment",
            failure_code=failure_code.value,
        )


_COMMITMENT_TOKEN = object()


@dataclass(frozen=True)
class SimulatedConfirmatoryArmCaseCommitment:
    schema: str
    execution_index: int
    evidence: SimulatedConfirmatoryEvidenceCommitment
    case_id: str
    arm_id: str
    input_entry_hash: str
    authorization_hash: str
    plan_hash: str
    input_manifest_hash: str
    provider_manifest_hash: str
    price_manifest_hash: str
    stage_budget_manifest_hash: str
    stage_cost_pre_ledger_hash: str
    stage_cost_ledger_hash: str
    formal_oracle_authority_hash: str
    gold_binding_hash: str
    confirmatory_lock_hash: str
    source_lock_hash: str
    common_ancestry_hash: str
    comparison_block_id: str
    commitment_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._factory_token is not _COMMITMENT_TOKEN
            or self.schema != CONFIRMATORY_COMMITMENT_SCHEMA
            or isinstance(self.execution_index, bool)
            or not isinstance(self.execution_index, int)
            or self.execution_index < 0
            or not isinstance(self.evidence, SimulatedConfirmatoryEvidenceCommitment)
            or self.case_id != self.evidence.case.case_id
            or self.arm_id != self.evidence.arm_id
            or self.input_entry_hash != self.evidence.input_entry_hash
            or self.evidence.execution_verified is not False
            or self.evidence.cost_verified is not False
        ):
            raise ConfirmatoryContractError(
                "confirmatory outcome must be factory-derived"
            )
        for name in (
            "input_entry_hash",
            "authorization_hash",
            "plan_hash",
            "input_manifest_hash",
            "provider_manifest_hash",
            "price_manifest_hash",
            "stage_budget_manifest_hash",
            "stage_cost_pre_ledger_hash",
            "stage_cost_ledger_hash",
            "formal_oracle_authority_hash",
            "gold_binding_hash",
            "confirmatory_lock_hash",
            "source_lock_hash",
            "common_ancestry_hash",
            "commitment_hash",
        ):
            _digest(getattr(self, name), f"confirmatory outcome {name}")
        if self.commitment_hash != _canonical_hash(self._body()):
            raise ConfirmatoryContractError("confirmatory outcome hash mismatch")

    def _body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "execution_index": self.execution_index,
            "evidence_hash": self.evidence.evidence_hash,
            "case_id": self.case_id,
            "arm_id": self.arm_id,
            "input_entry_hash": self.input_entry_hash,
            "authorization_hash": self.authorization_hash,
            "plan_hash": self.plan_hash,
            "input_manifest_hash": self.input_manifest_hash,
            "provider_manifest_hash": self.provider_manifest_hash,
            "price_manifest_hash": self.price_manifest_hash,
            "stage_budget_manifest_hash": self.stage_budget_manifest_hash,
            "stage_cost_pre_ledger_hash": self.stage_cost_pre_ledger_hash,
            "stage_cost_ledger_hash": self.stage_cost_ledger_hash,
            "formal_oracle_authority_hash": self.formal_oracle_authority_hash,
            "gold_binding_hash": self.gold_binding_hash,
            "confirmatory_lock_hash": self.confirmatory_lock_hash,
            "source_lock_hash": self.source_lock_hash,
            "common_ancestry_hash": self.common_ancestry_hash,
            "comparison_block_id": self.comparison_block_id,
            "claim_scope": _CLAIM_SCOPE,
            "production_authorized": False,
            "formal_eligible": False,
            "commitment_only": True,
            "execution_verified": False,
            "cost_verified": False,
            "outcome_facts_derived": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._body(),
            "evidence": self.evidence.to_dict(),
            "commitment_hash": self.commitment_hash,
        }

    @classmethod
    def create(
        cls,
        *,
        authorization: FormalConfirmatoryAuthorization,
        execution_index: int,
        evidence: SimulatedConfirmatoryEvidenceCommitment,
        stage_cost_ledger: StageCostLedger,
    ) -> SimulatedConfirmatoryArmCaseCommitment:
        if not isinstance(authorization, FormalConfirmatoryAuthorization):
            raise ConfirmatoryContractError(
                "confirmatory outcome requires typed authorization"
            )
        if not isinstance(evidence, SimulatedConfirmatoryEvidenceCommitment):
            raise ConfirmatoryContractError(
                "confirmatory outcome requires SimulatedConfirmatoryEvidenceCommitment"
            )
        plan = authorization.plan
        if not isinstance(stage_cost_ledger, StageCostLedger):
            raise ConfirmatoryContractError(
                "confirmatory outcome requires typed StageCost ledger"
            )
        pre_ledger = plan.stage_cost_pre_ledger
        if (
            stage_cost_ledger.ledger_id != pre_ledger.ledger_id
            or stage_cost_ledger.version != pre_ledger.version
            or stage_cost_ledger.price_manifest_hash != pre_ledger.price_manifest_hash
            or stage_cost_ledger.budget_manifest != pre_ledger.budget_manifest
            or stage_cost_ledger.entries[: len(pre_ledger.entries)]
            != pre_ledger.entries
            or stage_cost_ledger.phase_decision("confirmatory").stopped
        ):
            raise ConfirmatoryContractError(
                "confirmatory outcome StageCost ledger is not an allowed extension"
            )
        expected_index = evidence.case and next(
            index
            for index, entry in enumerate(plan.input_manifest.entries)
            if entry.case_id == evidence.case.case_id
        ) * len(_ARMS) + _ARMS.index(evidence.arm_id)
        if execution_index != expected_index:
            raise ConfirmatoryContractError(
                "confirmatory execution index differs from frozen case.arm order"
            )
        entry = plan.input_manifest.entries[execution_index // len(_ARMS)]
        if evidence.input_entry_hash != entry.entry_hash:
            raise ConfirmatoryContractError(
                "confirmatory outcome evidence belongs to another case"
            )
        values = {
            "schema": CONFIRMATORY_COMMITMENT_SCHEMA,
            "execution_index": execution_index,
            "evidence_hash": evidence.evidence_hash,
            "case_id": evidence.case.case_id,
            "arm_id": evidence.arm_id,
            "input_entry_hash": evidence.input_entry_hash,
            "authorization_hash": authorization.authorization_hash,
            "plan_hash": plan.plan_hash,
            "input_manifest_hash": plan.input_manifest_hash,
            "provider_manifest_hash": plan.provider_manifest_hash,
            "price_manifest_hash": plan.price_manifest_hash,
            "stage_budget_manifest_hash": plan.stage_budget_manifest_hash,
            "stage_cost_pre_ledger_hash": plan.stage_cost_pre_ledger_hash,
            "stage_cost_ledger_hash": stage_cost_ledger.contract_hash,
            "formal_oracle_authority_hash": plan.formal_oracle_authority_hash,
            "gold_binding_hash": plan.gold_binding_hash,
            "confirmatory_lock_hash": plan.confirmatory_lock_hash,
            "source_lock_hash": plan.source_lock_hash,
            "common_ancestry_hash": plan.common_ancestry_hash,
            "comparison_block_id": plan.comparison_block_id,
            "claim_scope": _CLAIM_SCOPE,
            "production_authorized": False,
            "formal_eligible": False,
            "commitment_only": True,
            "execution_verified": False,
            "cost_verified": False,
            "outcome_facts_derived": False,
        }
        return cls(
            schema=CONFIRMATORY_COMMITMENT_SCHEMA,
            execution_index=execution_index,
            evidence=evidence,
            case_id=evidence.case.case_id,
            arm_id=evidence.arm_id,
            input_entry_hash=evidence.input_entry_hash,
            authorization_hash=authorization.authorization_hash,
            plan_hash=plan.plan_hash,
            input_manifest_hash=plan.input_manifest_hash,
            provider_manifest_hash=plan.provider_manifest_hash,
            price_manifest_hash=plan.price_manifest_hash,
            stage_budget_manifest_hash=plan.stage_budget_manifest_hash,
            stage_cost_pre_ledger_hash=plan.stage_cost_pre_ledger_hash,
            stage_cost_ledger_hash=stage_cost_ledger.contract_hash,
            formal_oracle_authority_hash=plan.formal_oracle_authority_hash,
            gold_binding_hash=plan.gold_binding_hash,
            confirmatory_lock_hash=plan.confirmatory_lock_hash,
            source_lock_hash=plan.source_lock_hash,
            common_ancestry_hash=plan.common_ancestry_hash,
            comparison_block_id=plan.comparison_block_id,
            commitment_hash=_canonical_hash(values),
            _factory_token=_COMMITMENT_TOKEN,
        )


def _commitment_matches_authorization(
    item: SimulatedConfirmatoryArmCaseCommitment,
    authorization: FormalConfirmatoryAuthorization,
    stage_cost_ledger_hash: str,
) -> bool:
    plan = authorization.plan
    return (
        item.authorization_hash == authorization.authorization_hash
        and item.plan_hash == authorization.plan_hash
        and item.input_manifest_hash == authorization.input_manifest_hash
        and item.provider_manifest_hash == authorization.provider_manifest_hash
        and item.price_manifest_hash == plan.price_manifest_hash
        and item.stage_budget_manifest_hash == plan.stage_budget_manifest_hash
        and item.stage_cost_pre_ledger_hash == plan.stage_cost_pre_ledger_hash
        and item.stage_cost_ledger_hash == stage_cost_ledger_hash
        and item.formal_oracle_authority_hash == plan.formal_oracle_authority_hash
        and item.gold_binding_hash == plan.gold_binding_hash
        and item.confirmatory_lock_hash == plan.confirmatory_lock_hash
        and item.source_lock_hash == plan.source_lock_hash
        and item.common_ancestry_hash == authorization.common_ancestry_hash
        and item.comparison_block_id == authorization.comparison_block_id
    )


_RUN_TOKEN = object()


@dataclass(frozen=True)
class SimulatedConfirmatoryCommitmentRun:
    schema: str
    authorization: FormalConfirmatoryAuthorization
    authorization_hash: str
    stage_cost_ledger_hash: str
    commitments: tuple[SimulatedConfirmatoryArmCaseCommitment, ...]
    run_hash: str
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "commitments", tuple(self.commitments))
        if (
            self._factory_token is not _RUN_TOKEN
            or self.schema != CONFIRMATORY_COMMITMENT_RUN_SCHEMA
            or not isinstance(
                self.authorization,
                FormalConfirmatoryAuthorization,
            )
            or self.authorization_hash != self.authorization.authorization_hash
            or len(self.commitments) != 720
            or tuple(item.execution_index for item in self.commitments)
            != tuple(range(720))
            or any(
                not isinstance(item, SimulatedConfirmatoryArmCaseCommitment)
                or not _commitment_matches_authorization(
                    item,
                    self.authorization,
                    self.stage_cost_ledger_hash,
                )
                or item.stage_cost_ledger_hash != self.stage_cost_ledger_hash
                for item in self.commitments
            )
        ):
            raise ConfirmatoryContractError(
                "confirmatory run requires exact 720 ordered commitments"
            )
        if self.run_hash != _canonical_hash(self._body()):
            raise ConfirmatoryContractError("confirmatory run hash mismatch")

    def _body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "authorization_hash": self.authorization_hash,
            "stage_cost_ledger_hash": self.stage_cost_ledger_hash,
            "commitment_hashes": [item.commitment_hash for item in self.commitments],
            "claim_scope": _CLAIM_SCOPE,
            "production_authorized": False,
            "formal_eligible": False,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._body(),
            "commitments": [item.to_dict() for item in self.commitments],
            "run_hash": self.run_hash,
        }

    @classmethod
    def create(
        cls,
        *,
        authorization: FormalConfirmatoryAuthorization,
        commitments: Sequence[SimulatedConfirmatoryArmCaseCommitment],
        stage_cost_ledger: StageCostLedger,
    ) -> SimulatedConfirmatoryCommitmentRun:
        if not isinstance(authorization, FormalConfirmatoryAuthorization):
            raise ConfirmatoryContractError(
                "confirmatory run requires typed authorization"
            )
        values = tuple(commitments)
        if not isinstance(stage_cost_ledger, StageCostLedger):
            raise ConfirmatoryContractError(
                "confirmatory run requires typed StageCost ledger"
            )
        if len(values) != 720:
            raise ConfirmatoryContractError(
                "confirmatory run requires exact 720 commitments"
            )
        expected_keys = tuple(
            (entry.case_id, arm)
            for entry in authorization.plan.input_manifest.entries
            for arm in authorization.plan.arm_order
        )
        observed_keys = tuple(
            (item.case_id, item.arm_id)
            for item in values
            if isinstance(item, SimulatedConfirmatoryArmCaseCommitment)
        )
        if observed_keys != expected_keys:
            raise ConfirmatoryContractError(
                "confirmatory run differs from ordered case.arm membership"
            )
        if any(
            not _commitment_matches_authorization(
                item,
                authorization,
                stage_cost_ledger.contract_hash,
            )
            for item in values
        ):
            raise ConfirmatoryContractError(
                "confirmatory run has mixed authorization or common ancestry"
            )
        body = {
            "schema": CONFIRMATORY_COMMITMENT_RUN_SCHEMA,
            "authorization_hash": authorization.authorization_hash,
            "stage_cost_ledger_hash": stage_cost_ledger.contract_hash,
            "commitment_hashes": [item.commitment_hash for item in values],
            "claim_scope": _CLAIM_SCOPE,
            "production_authorized": False,
            "formal_eligible": False,
        }
        return cls(
            schema=CONFIRMATORY_COMMITMENT_RUN_SCHEMA,
            authorization=authorization,
            authorization_hash=authorization.authorization_hash,
            stage_cost_ledger_hash=stage_cost_ledger.contract_hash,
            commitments=values,
            run_hash=_canonical_hash(body),
            _factory_token=_RUN_TOKEN,
        )


_PACKAGE_TOKEN = object()


@dataclass(frozen=True)
class SimulatedConfirmatoryCommitmentPackage:
    schema: str
    run: SimulatedConfirmatoryCommitmentRun
    package_hash: str
    seal_hash: str
    commitment_sealed: bool
    _factory_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._factory_token is not _PACKAGE_TOKEN
            or self.schema != CONFIRMATORY_COMMITMENT_PACKAGE_SCHEMA
            or not isinstance(self.run, SimulatedConfirmatoryCommitmentRun)
            or self.commitment_sealed is not True
            or self.package_hash != _canonical_hash(self._body())
            or self.seal_hash
            != _canonical_hash(
                {
                    "schema": "meas0.simulated-confirmatory-commitment-seal.v3",
                    "package_hash": self.package_hash,
                    "run_hash": self.run.run_hash,
                    "claim_scope": _CLAIM_SCOPE,
                }
            )
        ):
            raise ConfirmatoryContractError("confirmatory package seal is invalid")

    @property
    def commitments(self) -> tuple[SimulatedConfirmatoryArmCaseCommitment, ...]:
        return self.run.commitments

    @property
    def case_count(self) -> int:
        return 144

    @property
    def arm_case_count(self) -> int:
        return len(self.run.commitments)

    @property
    def claim_scope(self) -> str:
        return _CLAIM_SCOPE

    @property
    def production_authorized(self) -> bool:
        return False

    @property
    def formal_eligible(self) -> bool:
        return False

    @property
    def commitment_only(self) -> bool:
        return True

    @property
    def execution_verified(self) -> bool:
        return False

    @property
    def cost_verified(self) -> bool:
        return False

    @property
    def outcome_package_closed(self) -> bool:
        return False

    def _body(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "run_hash": self.run.run_hash,
            "case_count": self.case_count,
            "arm_case_count": self.arm_case_count,
            "claim_scope": self.claim_scope,
            "production_authorized": self.production_authorized,
            "formal_eligible": self.formal_eligible,
            "commitment_only": self.commitment_only,
            "execution_verified": self.execution_verified,
            "cost_verified": self.cost_verified,
            "outcome_package_closed": self.outcome_package_closed,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._body(),
            "run": self.run.to_dict(),
            "package_hash": self.package_hash,
            "seal_hash": self.seal_hash,
            "commitment_sealed": self.commitment_sealed,
        }

    def to_canonical_bytes(self) -> bytes:
        """Serialize the nonclaim commitment package for byte-level replay."""

        return _canonical_bytes(self.to_dict())

    @classmethod
    def create(
        cls,
        *,
        authorization: FormalConfirmatoryAuthorization,
        commitments: Sequence[SimulatedConfirmatoryArmCaseCommitment],
        stage_cost_ledger: StageCostLedger,
    ) -> SimulatedConfirmatoryCommitmentPackage:
        run = SimulatedConfirmatoryCommitmentRun.create(
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=stage_cost_ledger,
        )
        body = {
            "schema": CONFIRMATORY_COMMITMENT_PACKAGE_SCHEMA,
            "run_hash": run.run_hash,
            "case_count": 144,
            "arm_case_count": 720,
            "claim_scope": _CLAIM_SCOPE,
            "production_authorized": False,
            "formal_eligible": False,
            "commitment_only": True,
            "execution_verified": False,
            "cost_verified": False,
            "outcome_package_closed": False,
        }
        package_hash = _canonical_hash(body)
        return cls(
            schema=CONFIRMATORY_COMMITMENT_PACKAGE_SCHEMA,
            run=run,
            package_hash=package_hash,
            seal_hash=_canonical_hash(
                {
                    "schema": "meas0.simulated-confirmatory-commitment-seal.v3",
                    "package_hash": package_hash,
                    "run_hash": run.run_hash,
                    "claim_scope": _CLAIM_SCOPE,
                }
            ),
            commitment_sealed=True,
            _factory_token=_PACKAGE_TOKEN,
        )

    @classmethod
    def restore_from_typed_sources(
        cls,
        value: object,
        *,
        authorization: FormalConfirmatoryAuthorization,
        commitments: Sequence[SimulatedConfirmatoryArmCaseCommitment],
        stage_cost_ledger: StageCostLedger,
    ) -> SimulatedConfirmatoryCommitmentPackage:
        if not isinstance(value, Mapping):
            raise ConfirmatoryContractError(
                "serialized confirmatory package must be a mapping"
            )
        restored = cls.create(
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=stage_cost_ledger,
        )
        if not _exact_serialized_equal(dict(value), restored.to_dict()):
            raise ConfirmatoryContractError(
                "serialized confirmatory package disagrees with typed sources"
            )
        return restored

    @classmethod
    def restore_from_canonical_bytes(
        cls,
        value: bytes,
        *,
        authorization: FormalConfirmatoryAuthorization,
        commitments: Sequence[SimulatedConfirmatoryArmCaseCommitment],
        stage_cost_ledger: StageCostLedger,
    ) -> SimulatedConfirmatoryCommitmentPackage:
        """Restore canonical bytes only after typed ancestry is re-derived."""

        return cls.restore_from_typed_sources(
            _decode_canonical_package_bytes(value),
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=stage_cost_ledger,
        )


__all__ = [
    "CONFIRMATORY_PACKAGE_GOLD_ORACLE_GAP",
    "ConfirmatoryContractError",
    "ConfirmatoryInputManifest",
    "SimulatedConfirmatoryEvidenceCommitment",
    "FormalConfirmatoryAuthorization",
    "SimulatedConfirmatoryArmCaseCommitment",
    "SimulatedConfirmatoryCommitmentPackage",
    "FormalConfirmatoryPlan",
    "SimulatedConfirmatoryCommitmentRun",
]
