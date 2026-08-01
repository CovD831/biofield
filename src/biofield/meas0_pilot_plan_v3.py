"""Offline-only V3 Pilot-plan derivation from sealed input/readiness contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .meas0_budget_policy_v3 import (
    BudgetPolicyV3Error,
    OfflineBudgetValidationV3,
    validate_frozen_meas0_budget_manifest_v3,
)
from .meas0_formal_metrics import formal_attack_manifest
from .meas0_formal_runner import (
    FormalPilotCaseInput,
    FormalPilotPlan,
    FormalRunnerError,
)
from .meas0_input_manifest import (
    InputManifest,
    InputManifestError,
    ProtectedInputCorpus,
)
from .meas0_phase_readiness import (
    PhaseReadinessError,
    PhaseReadinessReceipt,
    PhaseReadinessStage,
    SimulatedPhaseCompletion,
    validate_phase_readiness_chain,
)
from .meas0_readiness import (
    FormalCaseScopeManifest,
    PriceManifest,
    arm_order_manifest,
    pilot_budget_policy,
)
from .meas0_source_lock_v3 import SealedSourceLockBytes
from .meas0_stage_cost import StageBudgetManifest, StageCostLedger


class PilotPlanCandidateError(ValueError):
    """The V3 simulated Pilot plan does not have one sealed ancestry."""


_CANDIDATE_TOKEN = object()


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _bindings(receipt: PhaseReadinessReceipt) -> dict[str, str]:
    return dict(receipt.target.evidence_bindings)


def _require_hash_equal(
    observed: str,
    expected: str,
    label: str,
) -> None:
    if observed != expected:
        raise PilotPlanCandidateError(f"Pilot candidate {label} binding is invalid")


def _validate_candidate_sources(
    *,
    input_manifest: InputManifest,
    pre_jcal_readiness: PhaseReadinessReceipt,
    jcal_completion: SimulatedPhaseCompletion,
    pilot_readiness: PhaseReadinessReceipt,
    price_manifest: PriceManifest,
    stage_budget_manifest: StageBudgetManifest,
    stage_cost_pre_ledger: StageCostLedger,
    source_lock: SealedSourceLockBytes,
) -> OfflineBudgetValidationV3:
    if (
        not isinstance(input_manifest, InputManifest)
        or input_manifest.phase != "pilot"
        or len(input_manifest.entries) != 36
    ):
        raise PilotPlanCandidateError(
            "Pilot candidate requires a pilot InputManifest with exact 36 entries"
        )
    if (
        not isinstance(pre_jcal_readiness, PhaseReadinessReceipt)
        or pre_jcal_readiness.stage is not PhaseReadinessStage.PRE_JCAL_READY
    ):
        raise PilotPlanCandidateError(
            "Pilot candidate requires PRE_JCAL_READY ancestry"
        )
    if (
        not isinstance(pilot_readiness, PhaseReadinessReceipt)
        or pilot_readiness.stage is not PhaseReadinessStage.PILOT_READY
    ):
        raise PilotPlanCandidateError(
            "Pilot candidate requires a PILOT_READY typed receipt"
        )
    if not isinstance(jcal_completion, SimulatedPhaseCompletion):
        raise PilotPlanCandidateError(
            "Pilot candidate requires typed J-CAL completion ancestry"
        )
    if not isinstance(source_lock, SealedSourceLockBytes):
        raise PilotPlanCandidateError(
            "Pilot candidate requires typed sealed source-lock bytes"
        )
    try:
        validate_phase_readiness_chain(
            (pre_jcal_readiness, pilot_readiness),
            (jcal_completion,),
        )
    except PhaseReadinessError as error:
        raise PilotPlanCandidateError(
            f"Pilot candidate readiness ancestry is invalid: {error}"
        ) from error
    _require_hash_equal(
        input_manifest.readiness_parent_receipt_hash,
        pre_jcal_readiness.receipt_hash,
        "input manifest parent receipt",
    )
    _require_hash_equal(
        input_manifest.readiness_parent_target_hash,
        pre_jcal_readiness.target.target_hash,
        "input manifest parent target",
    )
    _require_hash_equal(
        input_manifest.source_lock_hash,
        source_lock.source_lock_hash,
        "sealed source lock",
    )
    manifest_parent_bindings = {
        "lifecycle": (
            input_manifest.lifecycle_id,
            pre_jcal_readiness.target.lifecycle_id,
        ),
        "comparison block": (
            input_manifest.comparison_block_id,
            pre_jcal_readiness.target.comparison_block_id,
        ),
        "authority role": (
            input_manifest.authority_role_id,
            pre_jcal_readiness.target.authority_role_id,
        ),
        "design": (
            input_manifest.design_hash,
            pre_jcal_readiness.target.design_hash,
        ),
        "source lock": (
            input_manifest.source_lock_hash,
            pre_jcal_readiness.target.source_lock_hash,
        ),
        "common ancestry": (
            input_manifest.common_ancestry_hash,
            pre_jcal_readiness.target.common_ancestry_hash,
        ),
    }
    for label, (observed, expected) in manifest_parent_bindings.items():
        _require_hash_equal(
            observed,
            expected,
            f"input manifest parent {label}",
        )
    try:
        input_manifest.validate_pilot_ready_target(pilot_readiness.target)
    except InputManifestError as error:
        raise PilotPlanCandidateError(
            f"Pilot candidate input manifest target binding is invalid: {error}"
        ) from error
    if not isinstance(price_manifest, PriceManifest):
        raise PilotPlanCandidateError("Pilot candidate requires a typed PriceManifest")
    if not isinstance(stage_budget_manifest, StageBudgetManifest):
        raise PilotPlanCandidateError(
            "Pilot candidate requires a typed StageBudgetManifest"
        )
    try:
        budget_validation = validate_frozen_meas0_budget_manifest_v3(
            phase="pilot",
            stage_budget_manifest=stage_budget_manifest,
            price_manifest=price_manifest,
        )
    except BudgetPolicyV3Error as error:
        raise PilotPlanCandidateError(
            f"Pilot candidate frozen budget is invalid: {error}"
        ) from error
    if not isinstance(stage_cost_pre_ledger, StageCostLedger):
        raise PilotPlanCandidateError(
            "Pilot candidate requires a typed StageCost pre-ledger"
        )
    pre_bindings = _bindings(pre_jcal_readiness)
    pilot_bindings = _bindings(pilot_readiness)
    _require_hash_equal(
        pre_bindings["price_manifest"],
        price_manifest.contract_hash,
        "PriceManifest",
    )
    _require_hash_equal(
        pre_bindings["stage_budget_manifest"],
        stage_budget_manifest.contract_hash,
        "StageBudgetManifest",
    )
    _require_hash_equal(
        pilot_bindings["pilot_input_manifest"],
        input_manifest.manifest_hash,
        "input manifest",
    )
    _require_hash_equal(
        pilot_bindings["jcal_stage_cost"],
        stage_cost_pre_ledger.contract_hash,
        "StageCost",
    )
    _require_hash_equal(
        pilot_bindings["precalibration_lock"],
        pre_bindings["precalibration_lock"],
        "precalibration lock",
    )
    _require_hash_equal(
        pilot_readiness.target.ledger_pre_head_hash,
        stage_cost_pre_ledger.contract_hash,
        "ledger head",
    )
    _require_hash_equal(
        pilot_readiness.ledger_head_hash,
        stage_cost_pre_ledger.contract_hash,
        "readiness ledger",
    )
    _require_hash_equal(
        jcal_completion.ledger_head_hash,
        stage_cost_pre_ledger.contract_hash,
        "J-CAL completion ledger",
    )
    _require_hash_equal(
        stage_cost_pre_ledger.price_manifest_hash,
        price_manifest.contract_hash,
        "StageCost PriceManifest",
    )
    _require_hash_equal(
        stage_cost_pre_ledger.budget_manifest.contract_hash,
        stage_budget_manifest.contract_hash,
        "StageCost StageBudgetManifest",
    )
    if stage_cost_pre_ledger.phase_decision("pilot").stopped or any(
        item.phase in {"pilot", "jaudit", "confirmatory"}
        for item in stage_cost_pre_ledger.entries
    ):
        raise PilotPlanCandidateError(
            "Pilot candidate StageCost pre-ledger is not a valid Pilot boundary"
        )
    return budget_validation


def _derive_cases(
    input_manifest: InputManifest,
) -> tuple[FormalPilotCaseInput, ...]:
    frozen_cases = formal_attack_manifest("pilot").cases
    if len(frozen_cases) != len(input_manifest.entries):
        raise PilotPlanCandidateError(
            "Pilot candidate manifest differs from frozen case count"
        )
    values: list[FormalPilotCaseInput] = []
    for frozen_case, entry in zip(
        frozen_cases,
        input_manifest.entries,
        strict=True,
    ):
        if (
            entry.phase,
            entry.case_id,
            entry.task_id,
            entry.fault_id,
            entry.mutation_seed,
        ) != (
            "pilot",
            frozen_case.case_id,
            frozen_case.task_id,
            frozen_case.fault_id,
            frozen_case.mutation_seed,
        ):
            raise PilotPlanCandidateError(
                "Pilot candidate manifest case ancestry is invalid"
            )
        values.append(
            FormalPilotCaseInput(
                case=frozen_case,
                task_hash=entry.task_bundle_hash,
                episode_hash=entry.episode_hash,
                failure_policy_hash=entry.failure_policy_hash,
                semantic_leaf_count=entry.semantic_leaf_count,
                measurement_count=entry.measurement_count,
            )
        )
    return tuple(values)


@dataclass(frozen=True)
class SimulatedPilotPlanCandidate:
    """Factory-derived Pilot plan wrapper that can never be formal evidence."""

    plan: FormalPilotPlan
    input_manifest: InputManifest
    pre_jcal_readiness: PhaseReadinessReceipt
    jcal_completion: SimulatedPhaseCompletion
    pilot_readiness: PhaseReadinessReceipt
    source_lock: SealedSourceLockBytes
    input_manifest_hash: str
    protected_corpus_hash: str
    common_ancestry_hash: str
    ledger_head_hash: str
    price_manifest_hash: str
    stage_budget_manifest_hash: str
    frozen_budget_policy_hash: str
    budget_validation_hash: str
    stage_cost_pre_ledger_hash: str
    source_lock_hash: str
    claim_scope: str
    production_authorized: bool
    test_only: bool
    _derivation_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._derivation_token is not _CANDIDATE_TOKEN:
            raise PilotPlanCandidateError(
                "simulated Pilot plan candidate must be created by its factory"
            )
        if not isinstance(self.plan, FormalPilotPlan):
            raise PilotPlanCandidateError(
                "simulated Pilot candidate requires FormalPilotPlan"
            )
        budget_validation = _validate_candidate_sources(
            input_manifest=self.input_manifest,
            pre_jcal_readiness=self.pre_jcal_readiness,
            jcal_completion=self.jcal_completion,
            pilot_readiness=self.pilot_readiness,
            price_manifest=self.plan.price_manifest,
            stage_budget_manifest=self.plan.stage_budget_manifest,
            stage_cost_pre_ledger=self.plan.stage_cost_pre_ledger,
            source_lock=self.source_lock,
        )
        expected_cases = _derive_cases(self.input_manifest)
        if self.plan.cases != expected_cases:
            raise PilotPlanCandidateError(
                "simulated Pilot plan cases are not manifest-derived"
            )
        expected = {
            "input_manifest_hash": self.input_manifest.manifest_hash,
            "protected_corpus_hash": self.input_manifest.protected_corpus_hash,
            "common_ancestry_hash": self.pilot_readiness.common_ancestry_hash,
            "ledger_head_hash": self.plan.stage_cost_pre_ledger.contract_hash,
            "price_manifest_hash": self.plan.price_manifest.contract_hash,
            "stage_budget_manifest_hash": (
                self.plan.stage_budget_manifest.contract_hash
            ),
            "frozen_budget_policy_hash": budget_validation.frozen_policy_hash,
            "budget_validation_hash": budget_validation.validation_hash,
            "stage_cost_pre_ledger_hash": (
                self.plan.stage_cost_pre_ledger.contract_hash
            ),
            "source_lock_hash": self.source_lock.source_lock_hash,
        }
        if any(getattr(self, name) != value for name, value in expected.items()):
            raise PilotPlanCandidateError(
                "simulated Pilot candidate derived hashes are invalid"
            )
        if (
            self.claim_scope != "simulated_nonclaim"
            or self.production_authorized is not False
            or self.test_only is not True
        ):
            raise PilotPlanCandidateError(
                "simulated Pilot candidate cannot carry production authority"
            )

    @property
    def pilot_readiness_hash(self) -> str:
        return self.pilot_readiness.receipt_hash

    def _body(self) -> dict[str, Any]:
        return {
            "schema": "meas0.simulated-pilot-plan-candidate.v3",
            "version": 1,
            "plan": self.plan.to_dict(),
            "input_manifest": self.input_manifest.to_dict(),
            "pre_jcal_readiness": self.pre_jcal_readiness.to_dict(),
            "jcal_completion": self.jcal_completion.to_dict(),
            "pilot_readiness": self.pilot_readiness.to_dict(),
            "source_lock": self.source_lock.to_dict(),
            "input_manifest_hash": self.input_manifest_hash,
            "protected_corpus_hash": self.protected_corpus_hash,
            "common_ancestry_hash": self.common_ancestry_hash,
            "ledger_head_hash": self.ledger_head_hash,
            "price_manifest_hash": self.price_manifest_hash,
            "stage_budget_manifest_hash": self.stage_budget_manifest_hash,
            "frozen_budget_policy_hash": self.frozen_budget_policy_hash,
            "budget_validation_hash": self.budget_validation_hash,
            "stage_cost_pre_ledger_hash": self.stage_cost_pre_ledger_hash,
            "source_lock_hash": self.source_lock_hash,
            "claim_scope": self.claim_scope,
            "production_authorized": self.production_authorized,
            "test_only": self.test_only,
        }

    @property
    def candidate_hash(self) -> str:
        return _canonical_hash(self._body())

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "candidate_hash": self.candidate_hash}

    @classmethod
    def restore_from_sources(
        cls,
        value: dict[str, Any],
        *,
        source_lock: SealedSourceLockBytes,
        protected_input_corpus: ProtectedInputCorpus,
        case_scope_manifest: FormalCaseScopeManifest,
        pre_jcal_readiness: PhaseReadinessReceipt,
        jcal_completion: SimulatedPhaseCompletion,
        pilot_readiness: PhaseReadinessReceipt,
        price_manifest: PriceManifest,
        stage_budget_manifest: StageBudgetManifest,
        stage_cost_pre_ledger: StageCostLedger,
    ) -> SimulatedPilotPlanCandidate:
        """Restore only by re-deriving from every typed source contract."""

        expected_fields = frozenset(
            {
                "schema",
                "version",
                "plan",
                "input_manifest",
                "pre_jcal_readiness",
                "jcal_completion",
                "pilot_readiness",
                "source_lock",
                "input_manifest_hash",
                "protected_corpus_hash",
                "common_ancestry_hash",
                "ledger_head_hash",
                "price_manifest_hash",
                "stage_budget_manifest_hash",
                "frozen_budget_policy_hash",
                "budget_validation_hash",
                "stage_cost_pre_ledger_hash",
                "source_lock_hash",
                "claim_scope",
                "production_authorized",
                "test_only",
                "candidate_hash",
            }
        )
        if type(value) is not dict or frozenset(value) != expected_fields:
            raise PilotPlanCandidateError(
                "serialized Pilot candidate fields are invalid"
            )
        try:
            manifest = InputManifest.create(
                corpus=protected_input_corpus,
                case_scope_manifest=case_scope_manifest,
                readiness_parent=pre_jcal_readiness,
            )
        except InputManifestError as error:
            raise PilotPlanCandidateError(
                f"Pilot candidate input sources are invalid: {error}"
            ) from error
        restored = create_simulated_pilot_plan_candidate(
            input_manifest=manifest,
            pre_jcal_readiness=pre_jcal_readiness,
            jcal_completion=jcal_completion,
            pilot_readiness=pilot_readiness,
            price_manifest=price_manifest,
            stage_budget_manifest=stage_budget_manifest,
            stage_cost_pre_ledger=stage_cost_pre_ledger,
            source_lock=source_lock,
        )
        if value != restored.to_dict():
            raise PilotPlanCandidateError(
                "serialized Pilot candidate differs from source-derived candidate"
            )
        return restored


def create_simulated_pilot_plan_candidate(
    *,
    input_manifest: InputManifest,
    pre_jcal_readiness: PhaseReadinessReceipt,
    jcal_completion: SimulatedPhaseCompletion,
    pilot_readiness: PhaseReadinessReceipt,
    price_manifest: PriceManifest,
    stage_budget_manifest: StageBudgetManifest,
    stage_cost_pre_ledger: StageCostLedger,
    source_lock: SealedSourceLockBytes,
) -> SimulatedPilotPlanCandidate:
    """Derive all 36 case inputs; callers cannot supply cases, counts, or hashes."""

    budget_validation = _validate_candidate_sources(
        input_manifest=input_manifest,
        pre_jcal_readiness=pre_jcal_readiness,
        jcal_completion=jcal_completion,
        pilot_readiness=pilot_readiness,
        price_manifest=price_manifest,
        stage_budget_manifest=stage_budget_manifest,
        stage_cost_pre_ledger=stage_cost_pre_ledger,
        source_lock=source_lock,
    )
    try:
        plan = FormalPilotPlan(
            cases=_derive_cases(input_manifest),
            arm_order=arm_order_manifest(),
            budget_policy=pilot_budget_policy(),
            price_manifest=price_manifest,
            stage_budget_manifest=stage_budget_manifest,
            stage_cost_pre_ledger=stage_cost_pre_ledger,
        )
    except FormalRunnerError as error:
        raise PilotPlanCandidateError(
            f"Pilot candidate plan derivation failed: {error}"
        ) from error
    return SimulatedPilotPlanCandidate(
        plan=plan,
        input_manifest=input_manifest,
        pre_jcal_readiness=pre_jcal_readiness,
        jcal_completion=jcal_completion,
        pilot_readiness=pilot_readiness,
        source_lock=source_lock,
        input_manifest_hash=input_manifest.manifest_hash,
        protected_corpus_hash=input_manifest.protected_corpus_hash,
        common_ancestry_hash=pilot_readiness.common_ancestry_hash,
        ledger_head_hash=stage_cost_pre_ledger.contract_hash,
        price_manifest_hash=price_manifest.contract_hash,
        stage_budget_manifest_hash=stage_budget_manifest.contract_hash,
        frozen_budget_policy_hash=budget_validation.frozen_policy_hash,
        budget_validation_hash=budget_validation.validation_hash,
        stage_cost_pre_ledger_hash=stage_cost_pre_ledger.contract_hash,
        source_lock_hash=source_lock.source_lock_hash,
        claim_scope="simulated_nonclaim",
        production_authorized=False,
        test_only=True,
        _derivation_token=_CANDIDATE_TOKEN,
    )


__all__ = [
    "PilotPlanCandidateError",
    "SimulatedPilotPlanCandidate",
    "create_simulated_pilot_plan_candidate",
]
