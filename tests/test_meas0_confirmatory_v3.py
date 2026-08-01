from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache

import pytest

from biofield.measurement import (
    EpisodeEvidence,
    EpisodeGraph,
    EvaluatorAuthority,
    EvidenceKind,
    Goal,
    GoalGraph,
    MeasurementDimension,
    MeasurementGraph,
    MeasurementKind,
    MeasurementRole,
    MeasurementSpec,
    Requirement,
    RequirementGraph,
    TaskFrame,
    seal_episode_graph,
    seal_task_measurement_bundle,
)
from biofield.meas0_confirmatory_v3 import (
    ConfirmatoryContractError,
    ConfirmatoryInputManifest,
    SimulatedConfirmatoryEvidenceCommitment,
    FormalConfirmatoryAuthorization,
    SimulatedConfirmatoryCommitmentPackage,
    FormalConfirmatoryPlan,
)
from biofield.meas0_budget_policy_v3 import (
    expected_offline_budget_validation_hash_v3,
    FrozenMeas0BudgetPolicyV3,
)
from biofield.meas0_formal_metrics import formal_attack_manifest
from biofield.meas0_formal_lifecycle import (
    PhaseCheckpointTarget,
    authorize_simulated_phase_checkpoint,
)
from biofield.meas0_formal_runner import (
    BackendMode,
    FailureCode,
    FormalBackendDescriptor,
)
from biofield.meas0_input_manifest import (
    FailurePolicyContract,
    NativeAdapterArtifact,
    ProtectedCaseInput,
    ProtectedInputCorpus,
)
from biofield.meas0_readiness import (
    PriceManifest,
    ProviderPrice,
    arm_order_manifest,
)
from biofield.meas0_phase_readiness import (
    PhaseCompletionDisposition,
    create_simulated_phase_readiness_receipt,
    record_simulated_phase_completion,
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


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _hash(index: int) -> str:
    return f"{index:064x}"


@lru_cache(maxsize=None)
def _bundle(task_id: str):
    frame = TaskFrame(
        task_id=task_id,
        version=1,
        subject_agent_id="subject",
        user_intent="complete task",
        desired_state="evidence exists",
        known_initial_state="not complete",
        entities_and_scope=(task_id,),
        constraints_and_permissions=("offline",),
        available_capabilities=("produce evidence",),
        uncertainties_and_ambiguities=(),
        risk_and_reversibility=("test-only",),
        required_artifacts=("result",),
        evidence_expectations=("typed",),
        provenance=("test",),
    )
    goals = GoalGraph(
        graph_id=f"{task_id}.goals",
        version=1,
        task_id=task_id,
        task_frame_version=1,
        goals=(
            Goal(
                goal_id=f"{task_id}.goal",
                desired_semantics="complete safely",
                critical=True,
                provenance=("test",),
            ),
        ),
        provenance=("test",),
    )
    requirements = RequirementGraph(
        graph_id=f"{task_id}.requirements",
        version=1,
        schema_version=1,
        goal_graph_id=goals.graph_id,
        goal_graph_version=goals.version,
        requirements=(
            Requirement(
                requirement_id=f"{task_id}.safe",
                goal_id=f"{task_id}.goal",
                success_semantics="safe completion",
                dimension=MeasurementDimension.SAFETY,
                critical=True,
                provenance=("test",),
            ),
            Requirement(
                requirement_id=f"{task_id}.semantic",
                goal_id=f"{task_id}.goal",
                success_semantics="useful result",
                dimension=MeasurementDimension.SEMANTIC,
                critical=True,
                provenance=("test",),
            ),
        ),
        provenance=("test",),
    )
    measurements = MeasurementGraph(
        graph_id=f"{task_id}.measurements",
        version=1,
        task_id=task_id,
        requirement_graph_id=requirements.graph_id,
        requirement_graph_version=requirements.version,
        requirement_schema_version=requirements.schema_version,
        measurement_specs=(
            MeasurementSpec(
                measurement_id=f"{task_id}.safe.measurement",
                version=1,
                target_requirement_id=f"{task_id}.safe",
                requirement_schema_version=1,
                dimension=MeasurementDimension.SAFETY,
                kind=MeasurementKind.DETERMINISTIC,
                measurand="safety",
                observation_source="typed evidence",
                procedure="verify",
                unit_or_scale="pass/fail",
                expected_coverage=1.0,
                acceptance_rule="pass",
                uncertainty_rule="missing is unknown",
                calibration_ref="fixture",
                cost_estimate=1.0,
                evaluator_ref=f"{task_id}.checker",
                evaluator_version="1",
                evaluator_authority=EvaluatorAuthority.HARNESS,
                provenance=("test",),
                role=MeasurementRole.DECISIVE,
            ),
            MeasurementSpec(
                measurement_id=f"{task_id}.semantic.measurement",
                version=1,
                target_requirement_id=f"{task_id}.semantic",
                requirement_schema_version=1,
                dimension=MeasurementDimension.SEMANTIC,
                kind=MeasurementKind.JUDGE,
                measurand="quality",
                observation_source="typed evidence",
                procedure="judge",
                unit_or_scale="pass/fail",
                expected_coverage=1.0,
                acceptance_rule="pass",
                uncertainty_rule="missing is unknown",
                calibration_ref="fixture",
                cost_estimate=1.0,
                evaluator_ref=f"{task_id}.judge",
                evaluator_version="1",
                evaluator_authority=EvaluatorAuthority.INDEPENDENT_JUDGE,
                provenance=("test",),
                role=MeasurementRole.DECISIVE,
            ),
        ),
        hard_gate_measurement_ids=(f"{task_id}.safe.measurement",),
        provenance=("test",),
    )
    return seal_task_measurement_bundle(
        bundle_id=f"{task_id}.bundle",
        version=1,
        task_frame=frame,
        goal_graph=goals,
        requirement_graph=requirements,
        measurement_graph=measurements,
        acceptance_rules=("decisive pass",),
        deterministic_check_refs=(f"{task_id}.checker",),
        judge_refs=(f"{task_id}.judge",),
        metamorphic_relations=(),
        uncertainty_and_escalation_rules=("missing is unknown",),
        measurement_budget=1.0,
        provenance=("test",),
    )


def _protected(case) -> ProtectedCaseInput:
    bundle = _bundle(case.task_id)
    evidence = tuple(
        EpisodeEvidence(
            evidence_id=f"{case.case_id}.{name}",
            kind=kind,
            locator=f"protected://{name}",
            content_hash=f"sha256:{str(index) * 64}",
            provenance=("test",),
            causal_parent_ids=(() if index == 1 else (f"{case.case_id}.{previous}",)),
        )
        for index, (name, previous, kind) in enumerate(
            (
                ("input", "", EvidenceKind.INPUT),
                ("environment", "input", EvidenceKind.ENVIRONMENT_STATE),
                ("trajectory", "environment", EvidenceKind.TRAJECTORY),
                ("response", "trajectory", EvidenceKind.RESPONSE),
            ),
            start=1,
        )
    )
    episode = seal_episode_graph(
        task_measurement_bundle=bundle,
        episode_graph=EpisodeGraph(
            episode_id=case.case_id,
            version=1,
            task_id=case.task_id,
            task_frame_version=1,
            evidence=evidence,
            environment_state_ref=f"{case.case_id}.environment",
            trajectory_ref=f"{case.case_id}.trajectory",
            response_ref=f"{case.case_id}.response",
            provenance=("test",),
        ),
        provenance=("test",),
    )
    return ProtectedCaseInput.create(
        case=case,
        task_measurement_bundle=bundle,
        sealed_episode=episode,
        failure_policy=FailurePolicyContract.frozen_v1(),
        native_adapter=NativeAdapterArtifact.from_source_bytes(
            task_id=case.task_id,
            adapter_id=f"{case.task_id}.native",
            adapter_version="1",
            source_path=f"adapters/{case.task_id}.py",
            source_bytes=f"# {case.task_id}\n".encode(),
        ),
    )


def _corpus() -> ProtectedInputCorpus:
    return ProtectedInputCorpus.create(
        phase="confirmatory",
        case_inputs=tuple(
            _protected(case) for case in formal_attack_manifest("confirmatory").cases
        ),
    )


def _tampered_corpus(
    source: ProtectedInputCorpus,
    case_inputs,
) -> ProtectedInputCorpus:
    value = object.__new__(ProtectedInputCorpus)
    object.__setattr__(value, "schema", source.schema)
    object.__setattr__(value, "phase", source.phase)
    object.__setattr__(value, "case_inputs", tuple(case_inputs))
    object.__setattr__(value, "corpus_hash", source.corpus_hash)
    return value


def _price() -> PriceManifest:
    return PriceManifest(
        manifest_id="pytest.confirmatory.price",
        version=1,
        currency="USD",
        effective_at="2026-07-31T00:00:00Z",
        fx_as_of="2026-07-31T00:00:00Z",
        direct_cap_microunits=100_000_000,
        provider_prices=(
            ProviderPrice(
                provider="offline.fake",
                model_id="fake",
                input_per_million_microunits=1,
                output_per_million_microunits=1,
                metered_tool_microunits=0,
            ),
        ),
    )


def _budget() -> StageBudgetManifest:
    return StageBudgetManifest(
        manifest_id="pytest.confirmatory.budget",
        version=1,
        phase_budgets=tuple(
            PhaseBudget(
                phase=phase,
                max_calls=800 if phase == "confirmatory" else 100,
                max_input_tokens=10_000_000,
                max_output_tokens=10_000_000,
                max_wall_time_ms=10_000_000,
                max_bytes_transferred=10_000_000,
                max_retries=720,
                max_monetary_microunits=(
                    100_000_000 if phase == "confirmatory" else 1_000_000
                ),
                counts_toward_per_arm_equality=phase in {"pilot", "confirmatory"},
                category_call_caps=tuple(
                    CategoryCallCap(
                        category=category,
                        max_calls=(
                            22
                            if phase == "confirmatory"
                            and category is CostCategory.HUMAN
                            else (800 if phase == "confirmatory" else 100)
                        ),
                    )
                    for category in CostCategory
                ),
            )
            for phase in ("jcal", "pilot", "jaudit", "confirmatory")
        ),
    )


def _ledger() -> StageCostLedger:
    return StageCostLedger(
        ledger_id="pytest.confirmatory.ledger",
        version=1,
        price_manifest_hash=_price().contract_hash,
        budget_manifest=_budget(),
        entries=(),
    )


def _bindings(checkpoint: AuthorizationCheckpoint) -> dict[str, str]:
    names = {
        AuthorizationCheckpoint.PRE_JCAL: (
            "human_trust_policy",
            "jcal_manifest",
            "judge_identity_manifest",
            "judge_specification",
            "precalibration_lock",
            "price_manifest",
            "stage_budget_manifest",
            "transport_trust_policy",
        ),
        AuthorizationCheckpoint.PILOT_START: (
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
        ),
        AuthorizationCheckpoint.POST_PILOT_JAUDIT: (
            "confirmatory_lock",
            "jaudit_manifest",
            "pilot_package",
            "unchanged_design_surface",
        ),
    }[checkpoint]
    result = {name: _hash(index + 9_100) for index, name in enumerate(names)}
    if checkpoint is AuthorizationCheckpoint.PRE_JCAL:
        result["price_manifest"] = _price().contract_hash
        result["stage_budget_manifest"] = _budget().contract_hash
    if checkpoint is AuthorizationCheckpoint.PILOT_START:
        result["jcal_stage_cost"] = _ledger().contract_hash
    return result


def _checkpoint_authorization(target: PhaseCheckpointTarget):
    return authorize_simulated_phase_checkpoint(
        target=target,
        verification=VerificationResult(
            schema_version=1,
            verified=True,
            production_authorized=False,
            claim_scope="contract_only",
            mode=TrustVerificationMode.TEST_ONLY_CONTRACT,
            trust_domain=TrustDomain.HUMAN_APPROVAL,
            policy_hash=_hash(9_200),
            root_manifest_hash=_hash(9_201),
            payload_hash=target.target_hash,
            envelope_hash=_hash(9_202),
            blockers=(),
        ),
    )


@lru_cache(maxsize=1)
def _readiness_prefix():
    previous_target = None
    previous_receipt = None
    previous_completion = None
    receipts = []
    completions = []
    for index, checkpoint in enumerate(
        (
            AuthorizationCheckpoint.PRE_JCAL,
            AuthorizationCheckpoint.PILOT_START,
            AuthorizationCheckpoint.POST_PILOT_JAUDIT,
        )
    ):
        target = PhaseCheckpointTarget.create(
            checkpoint=checkpoint,
            lifecycle_id="pytest.lifecycle",
            comparison_block_id="pytest.block",
            authority_role_id="approval-e",
            design_hash=_hash(9_001),
            source_lock_hash=_hash(9_002),
            common_ancestry_hash=_hash(9_003),
            ledger_pre_head_hash=_ledger().contract_hash,
            evidence_bindings=_bindings(checkpoint),
            previous_target=previous_target,
        )
        receipt = create_simulated_phase_readiness_receipt(
            target=target,
            authorization=_checkpoint_authorization(target),
            stage_evidence_hashes=dict(target.evidence_bindings),
            previous_receipt=previous_receipt,
            previous_completion=previous_completion,
        )
        receipts.append(receipt)
        completion = record_simulated_phase_completion(
            receipt=receipt,
            disposition=PhaseCompletionDisposition.ADVANCED,
            evidence_hash=_hash(9_400 + index),
            ledger_head_hash=_ledger().contract_hash,
        )
        completions.append(completion)
        previous_target = target
        previous_receipt = receipt
        previous_completion = completion
    return tuple(receipts), tuple(completions)


def _jaudit_readiness():
    return _readiness_prefix()[0][-1]


def _confirmatory_readiness(
    plan: FormalConfirmatoryPlan,
    *,
    plan_hash_override: str | None = None,
):
    previous = _jaudit_readiness()
    completion = _readiness_prefix()[1][-1]
    bindings = {
        "confirmatory_lock": dict(previous.target.evidence_bindings)[
            "confirmatory_lock"
        ],
        "confirmatory_input_manifest": plan.input_manifest_hash,
        "confirmatory_plan": plan_hash_override or plan.plan_hash,
        "jaudit_invocation": _hash(9_010),
        "jaudit_qualification": _hash(9_011),
        "jaudit_stage_cost": _ledger().contract_hash,
        "jaudit_transport": _hash(9_013),
        "provider_manifest": plan.provider_manifest_hash,
    }
    target = PhaseCheckpointTarget.create(
        checkpoint=AuthorizationCheckpoint.CONFIRMATORY_START,
        lifecycle_id=previous.target.lifecycle_id,
        comparison_block_id=previous.target.comparison_block_id,
        authority_role_id=previous.target.authority_role_id,
        design_hash=previous.target.design_hash,
        source_lock_hash=previous.target.source_lock_hash,
        common_ancestry_hash=previous.target.common_ancestry_hash,
        ledger_pre_head_hash=completion.ledger_head_hash,
        evidence_bindings=bindings,
        previous_target=previous.target,
    )
    return create_simulated_phase_readiness_receipt(
        target=target,
        authorization=_checkpoint_authorization(target),
        stage_evidence_hashes=bindings,
        previous_receipt=previous,
        previous_completion=completion,
    )


def _providers(
    provider_id: str = "offline.fake",
) -> tuple[FormalBackendDescriptor, ...]:
    return tuple(
        FormalBackendDescriptor(
            provider_id=provider_id,
            provider_version="1",
            arm_id=arm,
            mode=BackendMode.TEST_ONLY,
            enforces_timeouts=True,
        )
        for arm in arm_order_manifest().resolved_arm_order
    )


def _manifest() -> ConfirmatoryInputManifest:
    return ConfirmatoryInputManifest.create(
        corpus=_corpus(),
        jaudit_readiness=_jaudit_readiness(),
    )


def _plan(provider_id: str = "offline.fake") -> FormalConfirmatoryPlan:
    return FormalConfirmatoryPlan.create(
        input_manifest=_manifest(),
        readiness_receipts=_readiness_prefix()[0],
        readiness_completions=_readiness_prefix()[1],
        price_manifest=_price(),
        stage_budget_manifest=_budget(),
        stage_cost_pre_ledger=_ledger(),
        provider_descriptors=_providers(provider_id),
    )


def _plan_with_completions(completions) -> FormalConfirmatoryPlan:
    return FormalConfirmatoryPlan.create(
        input_manifest=_manifest(),
        readiness_receipts=_readiness_prefix()[0],
        readiness_completions=completions,
        price_manifest=_price(),
        stage_budget_manifest=_budget(),
        stage_cost_pre_ledger=_ledger(),
        provider_descriptors=_providers(),
    )


def _authorization(
    provider_id: str = "offline.fake",
) -> FormalConfirmatoryAuthorization:
    plan = _plan(provider_id)
    return FormalConfirmatoryAuthorization.create(
        plan=plan,
        confirmatory_readiness=_confirmatory_readiness(plan),
    )


def _commitments(
    *,
    authorization: FormalConfirmatoryAuthorization | None = None,
):
    authorization = authorization or _authorization()
    plan = authorization.plan
    values = []
    for case_index, entry in enumerate(plan.input_manifest.entries):
        for arm_index, arm in enumerate(plan.arm_order):
            if case_index == 0 and arm_index == 0:
                evidence = SimulatedConfirmatoryEvidenceCommitment.from_unverified_retained_failure_commitment(
                    entry=entry,
                    arm_id=arm,
                    failure_policy=FailurePolicyContract.frozen_v1(),
                    failure_code=FailureCode.TIMEOUT,
                    raw_evidence_bytes=b'{"timeout":true}',
                )
            else:
                evidence = SimulatedConfirmatoryEvidenceCommitment.from_unverified_canonical_evaluation_commitment(
                    entry=entry,
                    arm_id=arm,
                    raw_evidence_bytes=b'{"evaluation":"sealed-test-only"}',
                )
            values.append(
                authorization.bind_commitment(
                    execution_index=len(values),
                    evidence=evidence,
                    stage_cost_ledger=_ledger(),
                )
            )
    return tuple(values)


def test_exact_144_manifest_and_plan_are_separate_contract_only_types() -> None:
    manifest = _manifest()
    plan = _plan()

    assert len(manifest.entries) == 144
    assert tuple(item.case_id for item in manifest.entries) == tuple(
        item.case_id for item in formal_attack_manifest("confirmatory").cases
    )
    assert plan.input_manifest_hash == manifest.manifest_hash
    assert plan.arm_order == arm_order_manifest().resolved_arm_order
    assert plan.case_count == 144
    assert plan.arm_case_count == 720
    assert plan.claim_scope == "simulated_nonclaim"
    assert plan.production_authorized is False
    assert plan.formal_eligible is False
    assert (
        plan.frozen_budget_policy_hash
        == FrozenMeas0BudgetPolicyV3.frozen_v1().contract_hash
    )
    assert plan.budget_validation_hash == expected_offline_budget_validation_hash_v3(
        phase="confirmatory",
        stage_budget_manifest_hash=plan.stage_budget_manifest_hash,
        price_manifest_hash=plan.price_manifest_hash,
    )


def test_confirmatory_plan_uses_shared_validator_for_judge_category_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid = _budget()
    selected = valid.for_phase("confirmatory")
    changed = replace(
        selected,
        category_call_caps=tuple(
            replace(item, max_calls=801)
            if item.category is CostCategory.JUDGE
            else item
            for item in selected.category_call_caps
        ),
    )
    invalid = StageBudgetManifest(
        manifest_id="pytest.confirmatory.budget.judge-over-cap",
        version=1,
        phase_budgets=tuple(
            changed if item.phase == "confirmatory" else item
            for item in valid.phase_budgets
        ),
    )
    monkeypatch.setitem(globals(), "_budget", lambda: invalid)
    _readiness_prefix.cache_clear()
    try:
        with pytest.raises(
            ConfirmatoryContractError,
            match="frozen budget.*Judge/human",
        ):
            _plan()
    finally:
        _readiness_prefix.cache_clear()


@pytest.mark.parametrize("count", (143, 145))
def test_manifest_rejects_wrong_case_count_and_pilot_mix(count: int) -> None:
    corpus = _corpus()
    changed = (
        corpus.case_inputs[:count]
        if count < 144
        else (*corpus.case_inputs, corpus.case_inputs[-1])
    )
    with pytest.raises(ConfirmatoryContractError, match="exact 144"):
        ConfirmatoryInputManifest.create(
            corpus=_tampered_corpus(corpus, changed),
            jaudit_readiness=_jaudit_readiness(),
        )

    corpus = _corpus()
    with pytest.raises(ConfirmatoryContractError, match="membership/order"):
        ConfirmatoryInputManifest.create(
            corpus=_tampered_corpus(
                corpus,
                (
                    _protected(formal_attack_manifest("pilot").cases[0]),
                    *corpus.case_inputs[1:],
                ),
            ),
            jaudit_readiness=_jaudit_readiness(),
        )


def test_manifest_rejects_duplicate_reorder_and_cross_split() -> None:
    corpus = _corpus()
    with pytest.raises(ConfirmatoryContractError, match="membership/order"):
        ConfirmatoryInputManifest.create(
            corpus=_tampered_corpus(
                corpus,
                (
                    corpus.case_inputs[0],
                    corpus.case_inputs[0],
                    *corpus.case_inputs[2:],
                ),
            ),
            jaudit_readiness=_jaudit_readiness(),
        )

    corpus = _corpus()
    with pytest.raises(ConfirmatoryContractError, match="membership/order"):
        ConfirmatoryInputManifest.create(
            corpus=_tampered_corpus(
                corpus,
                (
                    corpus.case_inputs[1],
                    corpus.case_inputs[0],
                    *corpus.case_inputs[2:],
                ),
            ),
            jaudit_readiness=_jaudit_readiness(),
        )


def test_confirmatory_authorization_rejects_target_substitution() -> None:
    plan = _plan()
    readiness = _confirmatory_readiness(plan, plan_hash_override=_hash(42))
    with pytest.raises(ConfirmatoryContractError, match="plan"):
        FormalConfirmatoryAuthorization.create(
            plan=plan,
            confirmatory_readiness=readiness,
        )


def test_confirmatory_authorization_rejects_replaced_embedded_plan() -> None:
    authorization = _authorization()
    substituted_plan = _plan("offline.other")

    assert substituted_plan.plan_hash != authorization.plan_hash
    with pytest.raises(ConfirmatoryContractError, match="embedded plan"):
        replace(authorization, plan=substituted_plan)


def test_exact_720_package_retains_failure_and_common_ancestry() -> None:
    authorization = _authorization()
    package = SimulatedConfirmatoryCommitmentPackage.create(
        authorization=authorization,
        commitments=_commitments(authorization=authorization),
        stage_cost_ledger=_ledger(),
    )

    assert package.case_count == 144
    assert package.arm_case_count == 720
    assert (
        package.commitments[0].evidence.tag == "unverified_retained_failure_commitment"
    )
    assert package.commitments[0].evidence.denominator_retained is None
    assert package.commitments[0].evidence.denominator_projection_derived is False
    assert package.commitments[0].evidence.automatic_status is None
    assert all(
        item.common_ancestry_hash == authorization.common_ancestry_hash
        for item in package.commitments
    )
    assert package.claim_scope == "simulated_nonclaim"
    assert package.production_authorized is False
    assert package.formal_eligible is False
    assert package.commitment_sealed is True
    assert package.commitment_only is True
    assert package.execution_verified is False
    assert package.cost_verified is False
    assert package.outcome_package_closed is False


def test_confirmatory_package_canonical_bytes_round_trip_requires_typed_sources() -> (
    None
):
    authorization = _authorization()
    commitments = _commitments(authorization=authorization)
    ledger = _ledger()
    package = SimulatedConfirmatoryCommitmentPackage.create(
        authorization=authorization,
        commitments=commitments,
        stage_cost_ledger=ledger,
    )

    raw = package.to_canonical_bytes()
    restored = SimulatedConfirmatoryCommitmentPackage.restore_from_canonical_bytes(
        raw,
        authorization=authorization,
        commitments=commitments,
        stage_cost_ledger=ledger,
    )

    assert isinstance(raw, bytes)
    assert restored == package
    assert raw == _canonical(package.to_dict())


def test_confirmatory_package_canonical_bytes_rejects_tampering() -> None:
    authorization = _authorization()
    commitments = _commitments(authorization=authorization)
    ledger = _ledger()
    package = SimulatedConfirmatoryCommitmentPackage.create(
        authorization=authorization,
        commitments=commitments,
        stage_cost_ledger=ledger,
    )
    raw = package.to_canonical_bytes()

    with pytest.raises(ConfirmatoryContractError, match="canonical|duplicate|JSON"):
        SimulatedConfirmatoryCommitmentPackage.restore_from_canonical_bytes(
            raw + b"\n",
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=ledger,
        )

    forged = json.loads(raw)
    forged["formal_eligible"] = True
    with pytest.raises(ConfirmatoryContractError, match="typed|source|hash|seal"):
        SimulatedConfirmatoryCommitmentPackage.restore_from_canonical_bytes(
            _canonical(forged),
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=ledger,
        )


@pytest.mark.parametrize("delta", (-1, 1))
def test_package_rejects_719_721_missing_or_extra(delta: int) -> None:
    authorization = _authorization()
    commitments = _commitments(authorization=authorization)
    changed = commitments[:-1] if delta < 0 else (*commitments, commitments[-1])
    with pytest.raises(ConfirmatoryContractError, match="exact 720"):
        SimulatedConfirmatoryCommitmentPackage.create(
            authorization=authorization,
            commitments=changed,
            stage_cost_ledger=_ledger(),
        )


def test_package_rejects_duplicate_reorder_cross_auth_and_arm_order() -> None:
    authorization = _authorization()
    commitments = list(_commitments(authorization=authorization))

    duplicated = [commitments[0], commitments[0], *commitments[2:]]
    with pytest.raises(ConfirmatoryContractError, match="ordered case.arm"):
        SimulatedConfirmatoryCommitmentPackage.create(
            authorization=authorization,
            commitments=duplicated,
            stage_cost_ledger=_ledger(),
        )

    reordered = [commitments[1], commitments[0], *commitments[2:]]
    with pytest.raises(ConfirmatoryContractError, match="ordered case.arm"):
        SimulatedConfirmatoryCommitmentPackage.create(
            authorization=authorization,
            commitments=reordered,
            stage_cost_ledger=_ledger(),
        )

    other = _authorization("offline.other")
    mixed = [
        other.bind_commitment(
            execution_index=0,
            evidence=commitments[0].evidence,
            stage_cost_ledger=_ledger(),
        ),
        *commitments[1:],
    ]
    with pytest.raises(ConfirmatoryContractError, match="authorization|hash"):
        SimulatedConfirmatoryCommitmentPackage.create(
            authorization=authorization,
            commitments=mixed,
            stage_cost_ledger=_ledger(),
        )


def test_package_rejects_locally_rehashed_mixed_plan_ancestry() -> None:
    authorization = _authorization()
    commitments = list(_commitments(authorization=authorization))
    valid_package = SimulatedConfirmatoryCommitmentPackage.create(
        authorization=authorization,
        commitments=commitments,
        stage_cost_ledger=_ledger(),
    )
    original = commitments[0]
    changed_body = original._body()
    changed_body["formal_oracle_authority_hash"] = _hash(9_700)
    commitments[0] = replace(
        original,
        formal_oracle_authority_hash=_hash(9_700),
        commitment_hash=hashlib.sha256(_canonical(changed_body)).hexdigest(),
    )

    with pytest.raises(ConfirmatoryContractError, match="mixed"):
        SimulatedConfirmatoryCommitmentPackage.create(
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=_ledger(),
        )

    forged_run_body = valid_package.run._body()
    forged_run_body["commitment_hashes"][0] = commitments[0].commitment_hash
    with pytest.raises(ConfirmatoryContractError, match="exact 720"):
        replace(
            valid_package.run,
            commitments=tuple(commitments),
            run_hash=hashlib.sha256(_canonical(forged_run_body)).hexdigest(),
        )


def test_unverified_commitment_rejects_noncanonical_or_non_json_raw_bytes() -> None:
    entry = _manifest().entries[0]
    for raw in (b"not-json", b'{ "evaluation": "spaced" }'):
        with pytest.raises(ConfirmatoryContractError, match="strict|canonical"):
            SimulatedConfirmatoryEvidenceCommitment.from_unverified_canonical_evaluation_commitment(
                entry=entry,
                arm_id=arm_order_manifest().resolved_arm_order[0],
                raw_evidence_bytes=raw,
            )


def test_failure_commitment_never_fabricates_projection_or_verdicts() -> None:
    entry = _manifest().entries[0]
    evidence = SimulatedConfirmatoryEvidenceCommitment.from_unverified_retained_failure_commitment(
        entry=entry,
        arm_id=arm_order_manifest().resolved_arm_order[0],
        failure_policy=FailurePolicyContract.frozen_v1(),
        failure_code=FailureCode.PROVIDER_ERROR,
        raw_evidence_bytes=b'{"provider":"unavailable"}',
    )

    assert evidence.denominator_retained is None
    assert evidence.denominator_projection_derived is False
    assert evidence.result_validity is None
    assert evidence.automatic_status is None
    assert evidence.accepted is None
    assert evidence.detected is None
    assert evidence.judge_verdict is None
    assert evidence.claim_scope == "simulated_nonclaim"
    assert evidence.formal_eligible is False


@pytest.mark.parametrize(
    "failure_code",
    (
        FailureCode.MALFORMED_RESPONSE,
        FailureCode.BUDGET_EXHAUSTED,
        FailureCode.STAGE_BUDGET_EXHAUSTED,
        FailureCode.BACKEND_INVALID,
        FailureCode.PROTOCOL_VIOLATION,
    ),
)
def test_unrepresentable_failure_codes_cannot_use_arbitrary_bytes_as_evidence(
    failure_code: FailureCode,
) -> None:
    entry = _manifest().entries[0]
    with pytest.raises(ConfirmatoryContractError, match="cannot prove|represent"):
        SimulatedConfirmatoryEvidenceCommitment.from_unverified_retained_failure_commitment(
            entry=entry,
            arm_id=arm_order_manifest().resolved_arm_order[0],
            failure_policy=FailurePolicyContract.frozen_v1(),
            failure_code=failure_code,
            raw_evidence_bytes=b'{"caller_claimed_failure":true}',
        )


@pytest.mark.parametrize(
    "disposition",
    (
        PhaseCompletionDisposition.FAILED,
        PhaseCompletionDisposition.QUARANTINED,
    ),
)
def test_confirmatory_plan_rejects_non_advanced_jaudit_completion(
    disposition: PhaseCompletionDisposition,
) -> None:
    receipts, completions = _readiness_prefix()
    failed = record_simulated_phase_completion(
        receipt=receipts[-1],
        disposition=disposition,
        evidence_hash=_hash(9_499),
        ledger_head_hash=_ledger().contract_hash,
    )
    with pytest.raises(ConfirmatoryContractError, match="ADVANCED|advanced"):
        _plan_with_completions((*completions[:2], failed))


def test_confirmatory_plan_binds_exact_jaudit_completion_evidence() -> None:
    receipts, completions = _readiness_prefix()
    substituted = record_simulated_phase_completion(
        receipt=receipts[-1],
        disposition=PhaseCompletionDisposition.ADVANCED,
        evidence_hash=_hash(9_498),
        ledger_head_hash=_ledger().contract_hash,
    )

    original_plan = _plan_with_completions(completions)
    substituted_plan = _plan_with_completions((*completions[:2], substituted))

    assert (
        original_plan.jaudit_completion_hash != substituted_plan.jaudit_completion_hash
    )
    assert original_plan.jaudit_completion_evidence_hash != (
        substituted_plan.jaudit_completion_evidence_hash
    )
    assert original_plan.plan_hash != substituted_plan.plan_hash


def test_pilot_and_legacy_commitments_cannot_be_relabelled() -> None:
    with pytest.raises(
        ConfirmatoryContractError, match="SimulatedConfirmatoryEvidenceCommitment"
    ):
        _authorization().bind_commitment(
            execution_index=0,
            evidence=object(),
            stage_cost_ledger=_ledger(),
        )


def test_package_replay_rederives_from_typed_sources_and_rejects_tamper() -> None:
    authorization = _authorization()
    commitments = _commitments(authorization=authorization)
    package = SimulatedConfirmatoryCommitmentPackage.create(
        authorization=authorization,
        commitments=commitments,
        stage_cost_ledger=_ledger(),
    )

    assert (
        SimulatedConfirmatoryCommitmentPackage.restore_from_typed_sources(
            package.to_dict(),
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=_ledger(),
        )
        == package
    )

    tampered = deepcopy(package.to_dict())
    tampered["run"]["commitments"][0]["evidence"]["automatic_status"] = "pass"
    with pytest.raises(ConfirmatoryContractError, match="typed sources"):
        SimulatedConfirmatoryCommitmentPackage.restore_from_typed_sources(
            tampered,
            authorization=authorization,
            commitments=commitments,
            stage_cost_ledger=_ledger(),
        )
