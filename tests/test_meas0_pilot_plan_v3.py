from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import replace

import pytest

from biofield.meas0_formal_lifecycle import (
    PhaseCheckpointTarget,
    authorize_simulated_phase_checkpoint,
)
from biofield.meas0_budget_policy_v3 import FrozenMeas0BudgetPolicyV3
from biofield.meas0_input_manifest import InputManifest
from biofield.meas0_phase_readiness import (
    PhaseCompletionDisposition,
    create_simulated_phase_readiness_receipt,
    record_simulated_phase_completion,
)
from biofield.meas0_pilot_plan_v3 import (
    PilotPlanCandidateError,
    SimulatedPilotPlanCandidate,
    create_simulated_pilot_plan_candidate,
)
from biofield.meas0_readiness import PriceManifest, ProviderPrice
from biofield.meas0_source_lock_v3 import (
    SOURCE_LOCK_V2_SOURCE_NAMES,
    SealedSourceLockBytes,
)
from biofield.meas0_stage_cost import (
    CategoryCallCap,
    CostCategory,
    PhaseBudget,
    StageBudgetManifest,
    StageCostLedger,
)
from biofield.meas0_trust import (
    AuthorizationCheckpoint,
    TrustDomain,
    TrustVerificationMode,
    VerificationResult,
)
from test_meas0_input_manifest_v3 import _case_scope, _corpus


def _hash(index: int) -> str:
    return f"{index:064x}"


def _source_lock(*, suffix: str = "one") -> SealedSourceLockBytes:
    value = {
        "schema_version": 2,
        "lock_id": f"pytest.source-lock.{suffix}",
        "experiment_id": "meas0",
        "phase": "pilot",
        "implementation_version": "meas0.pilot-run-shell.v11",
        "foundation_runner_version": "pytest",
        "claim_limit": "pilot_foundation_only_not_a_formal_meas0_pilot_result",
        "design_document_sha256": _hash(70),
        "design_binding": {},
        "mutation_seed": 1729,
        "mutation_manifest_sha256": _hash(71),
        "source_hashes": {
            name: hashlib.sha256(f"{suffix}:{name}".encode()).hexdigest()
            for name in SOURCE_LOCK_V2_SOURCE_NAMES
        },
        "fixture_hashes": {},
        "evaluator_hashes": {},
        "task_bundle_hashes": {},
        "arms": [],
        "arm_order_manifest": {},
        "budget_policy": {},
        "budget_policy_hash": _hash(72),
        "replay_count": 3,
        "judge_available": False,
        "human_review_available": False,
        "case_count": 36,
        "arm_case_count": 180,
        "case_manifest_hash": _hash(73),
        "case_manifest": [],
        "native_measurement_plans": {},
        "native_measurement_plan_hashes": {},
        "environment": {},
    }
    raw = (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()
    return SealedSourceLockBytes.from_canonical_bytes(
        raw,
        expected_sha256=hashlib.sha256(raw).hexdigest(),
    )


def _price_manifest(suffix: str = "one") -> PriceManifest:
    return PriceManifest(
        manifest_id=f"pytest.price.{suffix}",
        version=1,
        currency="USD",
        effective_at="2026-07-31T00:00:00Z",
        fx_as_of="2026-07-31T00:00:00Z",
        direct_cap_microunits=1_000_000,
        provider_prices=(
            ProviderPrice(
                provider="fake",
                model_id="fake-judge",
                input_per_million_microunits=1,
                output_per_million_microunits=1,
                metered_tool_microunits=0,
            ),
        ),
    )


def _stage_budget_manifest(suffix: str = "one") -> StageBudgetManifest:
    budgets = []
    for phase in ("jcal", "pilot", "jaudit", "confirmatory"):
        phase_call_cap = (
            240 if phase == "pilot" else (800 if phase == "confirmatory" else 100)
        )
        phase_human_cap = (
            8 if phase == "pilot" else (22 if phase == "confirmatory" else 10)
        )
        budgets.append(
            PhaseBudget(
                phase=phase,
                max_calls=phase_call_cap,
                max_input_tokens=10_000_000,
                max_output_tokens=10_000_000,
                max_wall_time_ms=10_000_000,
                max_bytes_transferred=10_000_000,
                max_retries=phase_call_cap,
                max_monetary_microunits=1_000_000,
                counts_toward_per_arm_equality=phase in {"pilot", "confirmatory"},
                category_call_caps=tuple(
                    CategoryCallCap(
                        category=category,
                        max_calls=(
                            phase_human_cap
                            if category is CostCategory.HUMAN
                            else phase_call_cap
                        ),
                    )
                    for category in CostCategory
                ),
            )
        )
    return StageBudgetManifest(
        manifest_id=f"pytest.stage-budget.{suffix}",
        version=1,
        phase_budgets=tuple(budgets),
    )


def _ledger(
    price_manifest: PriceManifest,
    stage_budget_manifest: StageBudgetManifest,
) -> StageCostLedger:
    return StageCostLedger(
        ledger_id="pytest.pilot-pre-ledger",
        version=1,
        price_manifest_hash=price_manifest.contract_hash,
        budget_manifest=stage_budget_manifest,
        entries=(),
    )


def _authorization(target: PhaseCheckpointTarget):
    return authorize_simulated_phase_checkpoint(
        target=target,
        verification=VerificationResult(
            schema_version=1,
            verified=True,
            production_authorized=False,
            claim_scope="contract_only",
            mode=TrustVerificationMode.TEST_ONLY_CONTRACT,
            trust_domain=TrustDomain.HUMAN_APPROVAL,
            policy_hash=_hash(10),
            root_manifest_hash=_hash(11),
            payload_hash=target.target_hash,
            envelope_hash=_hash(12),
            blockers=(),
        ),
    )


def _readiness_pair(
    *,
    price_manifest: PriceManifest,
    stage_budget_manifest: StageBudgetManifest,
    ledger: StageCostLedger,
    manifest: InputManifest | None = None,
    pilot_manifest_hash: str | None = None,
    pilot_ledger_hash: str | None = None,
    lifecycle_id: str = "pytest.v3.pilot.lifecycle",
    source_lock_hash: str | None = None,
):
    pre_bindings = {
        "human_trust_policy": _hash(20),
        "jcal_manifest": _hash(21),
        "judge_identity_manifest": _hash(22),
        "judge_specification": _hash(23),
        "precalibration_lock": _hash(24),
        "price_manifest": price_manifest.contract_hash,
        "stage_budget_manifest": stage_budget_manifest.contract_hash,
        "transport_trust_policy": _hash(25),
    }
    pre_target = PhaseCheckpointTarget.create(
        checkpoint=AuthorizationCheckpoint.PRE_JCAL,
        lifecycle_id=lifecycle_id,
        comparison_block_id="pytest.v3.pilot.block",
        authority_role_id="approval-authority-e",
        design_hash=_hash(30),
        source_lock_hash=source_lock_hash or _source_lock().source_lock_hash,
        common_ancestry_hash=_hash(32),
        ledger_pre_head_hash=_hash(33),
        evidence_bindings=pre_bindings,
        previous_target=None,
    )
    pre_receipt = create_simulated_phase_readiness_receipt(
        target=pre_target,
        authorization=_authorization(pre_target),
        stage_evidence_hashes=pre_bindings,
        previous_receipt=None,
        previous_completion=None,
    )
    if manifest is None:
        manifest = InputManifest.create(
            corpus=_corpus("pilot"),
            case_scope_manifest=_case_scope(),
            readiness_parent=pre_receipt,
        )
    completion = record_simulated_phase_completion(
        receipt=pre_receipt,
        disposition=PhaseCompletionDisposition.ADVANCED,
        evidence_hash=_hash(34),
        ledger_head_hash=ledger.contract_hash,
    )
    pilot_bindings = {
        "formal_oracle_authority": _hash(40),
        "gold_binding": _hash(41),
        "isolation_preflight": _hash(42),
        "jcal_invocation": _hash(43),
        "jcal_qualification": _hash(44),
        "jcal_stage_cost": pilot_ledger_hash or ledger.contract_hash,
        "jcal_transport": _hash(45),
        "pilot_input_manifest": pilot_manifest_hash or manifest.manifest_hash,
        "pilot_lock": _hash(46),
        "precalibration_lock": pre_bindings["precalibration_lock"],
        "provider_manifest": _hash(47),
    }
    pilot_target = PhaseCheckpointTarget.create(
        checkpoint=AuthorizationCheckpoint.PILOT_START,
        lifecycle_id=pre_target.lifecycle_id,
        comparison_block_id=pre_target.comparison_block_id,
        authority_role_id=pre_target.authority_role_id,
        design_hash=pre_target.design_hash,
        source_lock_hash=pre_target.source_lock_hash,
        common_ancestry_hash=pre_target.common_ancestry_hash,
        ledger_pre_head_hash=ledger.contract_hash,
        evidence_bindings=pilot_bindings,
        previous_target=pre_target,
    )
    pilot_receipt = create_simulated_phase_readiness_receipt(
        target=pilot_target,
        authorization=_authorization(pilot_target),
        stage_evidence_hashes=pilot_bindings,
        previous_receipt=pre_receipt,
        previous_completion=completion,
    )
    return manifest, pre_receipt, completion, pilot_receipt


def _candidate(
    *,
    manifest=None,
    price=None,
    budget=None,
    ledger=None,
    readiness=None,
    source_lock=None,
):
    price = price or _price_manifest()
    budget = budget or _stage_budget_manifest()
    ledger = ledger or _ledger(price, budget)
    source_lock = source_lock or _source_lock()
    readiness = readiness or _readiness_pair(
        price_manifest=price,
        stage_budget_manifest=budget,
        ledger=ledger,
        manifest=manifest,
        source_lock_hash=source_lock.source_lock_hash,
    )
    manifest = manifest or readiness[0]
    return create_simulated_pilot_plan_candidate(
        input_manifest=manifest,
        pre_jcal_readiness=readiness[1],
        jcal_completion=readiness[2],
        pilot_readiness=readiness[3],
        price_manifest=price,
        stage_budget_manifest=budget,
        stage_cost_pre_ledger=ledger,
        source_lock=source_lock,
    )


def test_candidate_derives_all_36_case_inputs_and_binds_readiness() -> None:
    candidate = _candidate()
    manifest = candidate.input_manifest

    assert isinstance(candidate, SimulatedPilotPlanCandidate)
    assert candidate.claim_scope == "simulated_nonclaim"
    assert candidate.production_authorized is False
    assert candidate.test_only is True
    assert len(candidate.plan.cases) == 36
    assert tuple(
        (
            item.case.case_id,
            item.task_hash,
            item.episode_hash,
            item.failure_policy_hash,
            item.semantic_leaf_count,
            item.measurement_count,
        )
        for item in candidate.plan.cases
    ) == tuple(
        (
            entry.case_id,
            entry.task_bundle_hash,
            entry.episode_hash,
            entry.failure_policy_hash,
            entry.semantic_leaf_count,
            entry.measurement_count,
        )
        for entry in manifest.entries
    )
    assert candidate.input_manifest_hash == manifest.manifest_hash
    assert candidate.protected_corpus_hash == manifest.protected_corpus_hash
    assert candidate.pilot_readiness_hash == candidate.pilot_readiness.receipt_hash
    assert (
        candidate.frozen_budget_policy_hash
        == FrozenMeas0BudgetPolicyV3.frozen_v1().contract_hash
    )
    assert len(candidate.budget_validation_hash) == 64
    assert "formal_result" not in candidate.to_dict()
    assert {
        "cases",
        "case_count",
        "input_manifest_hash",
        "protected_corpus_hash",
    }.isdisjoint(inspect.signature(create_simulated_pilot_plan_candidate).parameters)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("max_calls", 241),
        ("human_calls", 9),
        ("judge_calls", 241),
    ),
)
def test_candidate_rejects_stage_budget_above_frozen_pilot_caps(
    field: str,
    value: int,
) -> None:
    price = _price_manifest()
    valid = _stage_budget_manifest()
    pilot = valid.for_phase("pilot")
    if field == "human_calls":
        caps = tuple(
            replace(item, max_calls=value)
            if item.category is CostCategory.HUMAN
            else item
            for item in pilot.category_call_caps
        )
        changed = replace(pilot, category_call_caps=caps)
    elif field == "judge_calls":
        caps = tuple(
            replace(item, max_calls=value)
            if item.category is CostCategory.JUDGE
            else item
            for item in pilot.category_call_caps
        )
        changed = replace(pilot, category_call_caps=caps)
    else:
        changed = replace(pilot, max_calls=value)
    budget = StageBudgetManifest(
        manifest_id="pytest.stage-budget.over-cap",
        version=1,
        phase_budgets=tuple(
            changed if item.phase == "pilot" else item for item in valid.phase_budgets
        ),
    )
    ledger = _ledger(price, budget)
    readiness = _readiness_pair(
        price_manifest=price,
        stage_budget_manifest=budget,
        ledger=ledger,
    )

    with pytest.raises(PilotPlanCandidateError, match="frozen.*budget|budget.*cap"):
        _candidate(
            price=price,
            budget=budget,
            ledger=ledger,
            readiness=readiness,
        )


def test_candidate_rejects_nonpilot_manifest_and_wrong_readiness_stage() -> None:
    price = _price_manifest()
    budget = _stage_budget_manifest()
    ledger = _ledger(price, budget)
    readiness = _readiness_pair(
        price_manifest=price,
        stage_budget_manifest=budget,
        ledger=ledger,
    )
    manifest = readiness[0]
    with pytest.raises(PilotPlanCandidateError, match="PILOT_READY"):
        create_simulated_pilot_plan_candidate(
            input_manifest=manifest,
            pre_jcal_readiness=readiness[1],
            jcal_completion=readiness[2],
            pilot_readiness=readiness[1],
            price_manifest=price,
            stage_budget_manifest=budget,
            stage_cost_pre_ledger=ledger,
            source_lock=_source_lock(),
        )


def test_candidate_rejects_manifest_and_ledger_binding_substitution() -> None:
    price = _price_manifest()
    budget = _stage_budget_manifest()
    ledger = _ledger(price, budget)
    valid = _readiness_pair(
        price_manifest=price,
        stage_budget_manifest=budget,
        ledger=ledger,
    )
    manifest = valid[0]

    wrong_manifest_readiness = _readiness_pair(
        manifest=manifest,
        price_manifest=price,
        stage_budget_manifest=budget,
        ledger=ledger,
        pilot_manifest_hash=_hash(50),
    )
    with pytest.raises(PilotPlanCandidateError, match="input manifest"):
        _candidate(
            manifest=manifest,
            price=price,
            budget=budget,
            ledger=ledger,
            readiness=wrong_manifest_readiness,
        )

    wrong_ledger_readiness = _readiness_pair(
        manifest=manifest,
        price_manifest=price,
        stage_budget_manifest=budget,
        ledger=ledger,
        pilot_ledger_hash=_hash(51),
    )
    with pytest.raises(PilotPlanCandidateError, match="StageCost"):
        _candidate(
            manifest=manifest,
            price=price,
            budget=budget,
            ledger=ledger,
            readiness=wrong_ledger_readiness,
        )


def test_candidate_rejects_price_budget_and_common_ancestry_substitution() -> None:
    price = _price_manifest()
    budget = _stage_budget_manifest()
    ledger = _ledger(price, budget)
    readiness = _readiness_pair(
        price_manifest=price,
        stage_budget_manifest=budget,
        ledger=ledger,
    )
    manifest = readiness[0]

    with pytest.raises(PilotPlanCandidateError, match="PriceManifest"):
        _candidate(
            manifest=manifest,
            price=_price_manifest("other"),
            budget=budget,
            ledger=ledger,
            readiness=readiness,
        )
    with pytest.raises(PilotPlanCandidateError, match="StageBudget"):
        _candidate(
            manifest=manifest,
            price=price,
            budget=_stage_budget_manifest("other"),
            ledger=ledger,
            readiness=readiness,
        )

    substituted_completion = record_simulated_phase_completion(
        receipt=readiness[1],
        disposition=PhaseCompletionDisposition.ADVANCED,
        evidence_hash=_hash(52),
        ledger_head_hash=ledger.contract_hash,
    )
    with pytest.raises(PilotPlanCandidateError, match="completion|ancestry"):
        create_simulated_pilot_plan_candidate(
            input_manifest=manifest,
            pre_jcal_readiness=readiness[1],
            jcal_completion=substituted_completion,
            pilot_readiness=readiness[3],
            price_manifest=price,
            stage_budget_manifest=budget,
            stage_cost_pre_ledger=ledger,
            source_lock=_source_lock(),
        )


def test_candidate_rejects_manifest_parent_substitution_even_with_valid_chain() -> None:
    price = _price_manifest()
    budget = _stage_budget_manifest()
    ledger = _ledger(price, budget)
    first = _readiness_pair(
        price_manifest=price,
        stage_budget_manifest=budget,
        ledger=ledger,
    )
    second = _readiness_pair(
        price_manifest=price,
        stage_budget_manifest=budget,
        ledger=ledger,
        manifest=first[0],
        lifecycle_id="pytest.v3.pilot.foreign-lifecycle",
    )

    with pytest.raises(PilotPlanCandidateError, match="parent receipt"):
        _candidate(
            manifest=first[0],
            price=price,
            budget=budget,
            ledger=ledger,
            readiness=second,
        )


def test_candidate_is_factory_only_and_legacy_plan_stays_unqualified() -> None:
    candidate = _candidate()

    with pytest.raises(PilotPlanCandidateError, match="derived hashes"):
        replace(candidate, frozen_budget_policy_hash=_hash(9_901))
    with pytest.raises(PilotPlanCandidateError, match="derived hashes"):
        replace(candidate, budget_validation_hash=_hash(9_902))
    with pytest.raises(PilotPlanCandidateError, match="factory"):
        SimulatedPilotPlanCandidate(
            plan=candidate.plan,
            input_manifest=candidate.input_manifest,
            pre_jcal_readiness=candidate.pre_jcal_readiness,
            jcal_completion=candidate.jcal_completion,
            pilot_readiness=candidate.pilot_readiness,
            input_manifest_hash=candidate.input_manifest_hash,
            protected_corpus_hash=candidate.protected_corpus_hash,
            common_ancestry_hash=candidate.common_ancestry_hash,
            ledger_head_hash=candidate.ledger_head_hash,
            price_manifest_hash=candidate.price_manifest_hash,
            stage_budget_manifest_hash=candidate.stage_budget_manifest_hash,
            frozen_budget_policy_hash=candidate.frozen_budget_policy_hash,
            budget_validation_hash=candidate.budget_validation_hash,
            stage_cost_pre_ledger_hash=candidate.stage_cost_pre_ledger_hash,
            source_lock=candidate.source_lock,
            source_lock_hash=candidate.source_lock_hash,
            claim_scope=candidate.claim_scope,
            production_authorized=candidate.production_authorized,
            test_only=candidate.test_only,
        )
    assert not hasattr(candidate.plan, "production_authorized")
    assert not hasattr(candidate.plan, "formal_result")


def test_candidate_strict_restore_rederives_from_all_typed_sources() -> None:
    candidate = _candidate()

    restored = SimulatedPilotPlanCandidate.restore_from_sources(
        candidate.to_dict(),
        source_lock=candidate.source_lock,
        protected_input_corpus=_corpus("pilot"),
        case_scope_manifest=_case_scope(),
        pre_jcal_readiness=candidate.pre_jcal_readiness,
        jcal_completion=candidate.jcal_completion,
        pilot_readiness=candidate.pilot_readiness,
        price_manifest=candidate.plan.price_manifest,
        stage_budget_manifest=candidate.plan.stage_budget_manifest,
        stage_cost_pre_ledger=candidate.plan.stage_cost_pre_ledger,
    )

    assert restored == candidate
    assert not hasattr(SimulatedPilotPlanCandidate, "from_dict")
    assert (
        "input_manifest"
        not in inspect.signature(
            SimulatedPilotPlanCandidate.restore_from_sources
        ).parameters
    )


def test_candidate_restore_rejects_unknown_missing_and_self_rehashed_drift() -> None:
    candidate = _candidate()
    sources = {
        "source_lock": candidate.source_lock,
        "protected_input_corpus": _corpus("pilot"),
        "case_scope_manifest": _case_scope(),
        "pre_jcal_readiness": candidate.pre_jcal_readiness,
        "jcal_completion": candidate.jcal_completion,
        "pilot_readiness": candidate.pilot_readiness,
        "price_manifest": candidate.plan.price_manifest,
        "stage_budget_manifest": candidate.plan.stage_budget_manifest,
        "stage_cost_pre_ledger": candidate.plan.stage_cost_pre_ledger,
    }
    unknown = {**candidate.to_dict(), "forged_authority": True}
    with pytest.raises(PilotPlanCandidateError, match="fields"):
        SimulatedPilotPlanCandidate.restore_from_sources(unknown, **sources)

    missing = candidate.to_dict()
    missing.pop("candidate_hash")
    with pytest.raises(PilotPlanCandidateError, match="fields"):
        SimulatedPilotPlanCandidate.restore_from_sources(missing, **sources)

    drifted = candidate.to_dict()
    drifted["claim_scope"] = "formal"
    drifted["candidate_hash"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in drifted.items() if key != "candidate_hash"},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()
    with pytest.raises(PilotPlanCandidateError, match="differs"):
        SimulatedPilotPlanCandidate.restore_from_sources(drifted, **sources)

    substituted_sources = {**sources, "source_lock": _source_lock(suffix="other")}
    with pytest.raises(PilotPlanCandidateError, match="source lock"):
        SimulatedPilotPlanCandidate.restore_from_sources(
            candidate.to_dict(),
            **substituted_sources,
        )
