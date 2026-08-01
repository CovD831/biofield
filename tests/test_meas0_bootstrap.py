from __future__ import annotations

from dataclasses import replace

import pytest

from biofield.meas0_formal_metrics import (
    CONFIRMATORY_BOOTSTRAP_PROTOCOL_GAP,
    CONFIRMATORY_BOOTSTRAP_REPLICATES,
    CONFIRMATORY_BOOTSTRAP_SEED,
    CONFIRMATORY_MUTATION_SEEDS,
    FORMAL_ARMS,
    ArmCaseOutcome,
    ConfirmatoryFiveArmCorpus,
    ContractHardGateEvidence,
    FormalMetricError,
    PairedMetric,
    build_confirmatory_five_arm_corpus,
    confirmatory_cluster_bootstrap,
    evaluate_contract_hard_gate,
    evaluate_confirmatory_gate,
    evaluate_confirmatory_performance,
    evaluate_formal_oracle_bound_confirmatory_gate,
    formal_attack_manifest,
    inverse_empirical_cdf_nearest_rank,
    paired_cluster_bootstrap,
    validate_confirmatory_bootstrap_inputs,
)


def _outcomes(
    arm: str,
    *,
    positive_seed: int,
    automatic_positive: bool = False,
) -> tuple[ArmCaseOutcome, ...]:
    manifest = formal_attack_manifest("confirmatory")
    return tuple(
        ArmCaseOutcome(
            case=case,
            arm=arm,
            gold_status="fail",
            automatic_status=(
                "pass"
                if automatic_positive and case.mutation_seed == positive_seed
                else "fail"
            ),
            accept_allowed=False,
            safety_violation=False,
            detection_expected=True,
            detected=case.mutation_seed == positive_seed,
            budget_exhausted=False,
            human_escalations=0,
            deterministic_eligible_leaves=1,
            deterministic_resolved_leaves=1,
            all_formal_leaves=1,
            deterministically_resolved_all_leaves=1,
        )
        for case in manifest.cases
    )


def _passing_hard_gate():
    manifest = formal_attack_manifest("confirmatory")
    pass_ids = tuple(item.case_id for item in manifest.cases if item.fault_id == "F18")
    return evaluate_contract_hard_gate(
        manifest,
        ContractHardGateEvidence(
            pass_case_ids=pass_ids,
            traceable_pass_case_ids=pass_ids,
            blocked_or_invalid_injection_case_ids=tuple(
                item.case_id
                for item in manifest.cases
                if item.fault_id in {"F04", "F09", "F17"}
            ),
            deterministic_hard_critical_override_count=0,
            silent_unknown_disputed_pass_count=0,
            protected_hash_checks=(True,),
            replay_hash_checks=(True,),
            denominator_recorded_case_ids=tuple(
                item.case_id for item in manifest.cases
            ),
            judge_calibration_passed=True,
            judge_audit_passed=True,
        ),
    )


def test_percentiles_use_inverse_empirical_cdf_nearest_rank() -> None:
    values = tuple(float(index) for index in range(100))

    assert inverse_empirical_cdf_nearest_rank(values, 0.025) == 2.0
    assert inverse_empirical_cdf_nearest_rank(values, 0.975) == 97.0
    assert inverse_empirical_cdf_nearest_rank(values, 0.05) == 4.0
    assert inverse_empirical_cdf_nearest_rank(values, 0.95) == 94.0


def test_bootstrap_resamples_four_seed_clusters_within_each_stratum() -> None:
    manifest = formal_attack_manifest("confirmatory")
    treatment = _outcomes(
        "evaluation_plane",
        positive_seed=CONFIRMATORY_MUTATION_SEEDS[0],
    )
    baseline = tuple(
        replace(item, arm="rules_state", detected=False) for item in treatment
    )
    inputs = validate_confirmatory_bootstrap_inputs(
        manifest,
        treatment,
        baseline,
        metric=PairedMetric.DETECTION,
    )
    result = paired_cluster_bootstrap(inputs)

    assert inputs.stratum_count == 36
    assert all(len(case_ids) == 4 for _, case_ids in inputs.strata)
    assert inputs.bootstrap_seed == CONFIRMATORY_BOOTSTRAP_SEED == 9511
    assert (
        inputs.replicates
        == result.replicates
        == CONFIRMATORY_BOOTSTRAP_REPLICATES
        == 10_000
    )
    assert result.observed_difference == pytest.approx(0.25)
    assert result.interval.method == (
        "inverse_empirical_cdf_nearest_rank_no_interpolation"
    )
    assert result.interval.confidence_level == 0.95
    assert result.interval.lower == 13 / 72
    assert result.interval.upper == 23 / 72
    assert result.gate_bound.direction == "lower"
    assert result.gate_bound.value == 7 / 36
    assert result.resampling_unit == ("mutation_seed_cluster_within_task_fault")
    assert result.draw_schedule_sha256 == (
        "6af5176069bf43f2e48759c5403ee2cdba06935ed527004c15c1fc912a4f40da"
    )
    assert result.preserves_arm_pairing is True
    assert result.uses_bca is False
    assert paired_cluster_bootstrap(inputs) == result


def test_same_cluster_draws_preserve_pairing_across_all_five_arms() -> None:
    manifest = formal_attack_manifest("confirmatory")
    outcomes = {
        arm: _outcomes(
            arm,
            positive_seed=CONFIRMATORY_MUTATION_SEEDS[-1],
        )
        for arm in FORMAL_ARMS
    }
    draw_schedule_hashes: set[str] = set()

    for baseline_arm in FORMAL_ARMS:
        if baseline_arm == "evaluation_plane":
            continue
        result = paired_cluster_bootstrap(
            validate_confirmatory_bootstrap_inputs(
                manifest,
                outcomes["evaluation_plane"],
                outcomes[baseline_arm],
                metric=PairedMetric.DETECTION,
            )
        )
        assert result.observed_difference == 0.0
        assert result.interval.lower == 0.0
        assert result.interval.upper == 0.0
        assert result.gate_bound.value == 0.0
        draw_schedule_hashes.add(result.draw_schedule_sha256)
    assert len(draw_schedule_hashes) == 1


def test_lower_is_better_metric_uses_one_sided_upper_bound() -> None:
    manifest = formal_attack_manifest("confirmatory")
    treatment = _outcomes(
        "evaluation_plane",
        positive_seed=CONFIRMATORY_MUTATION_SEEDS[0],
        automatic_positive=True,
    )
    baseline = tuple(
        replace(
            item,
            arm="self_eval",
            automatic_status="fail",
        )
        for item in treatment
    )
    result = paired_cluster_bootstrap(
        validate_confirmatory_bootstrap_inputs(
            manifest,
            treatment,
            baseline,
            metric=PairedMetric.FALSE_ACCEPT,
        )
    )

    assert result.observed_difference == pytest.approx(0.25)
    assert result.gate_bound.direction == "upper"
    assert 0.25 < result.gate_bound.value <= result.interval.upper


def test_bootstrap_rejects_nonfrozen_seed_or_replicate_count() -> None:
    manifest = formal_attack_manifest("confirmatory")
    treatment = _outcomes(
        "evaluation_plane",
        positive_seed=CONFIRMATORY_MUTATION_SEEDS[0],
    )
    baseline = tuple(
        replace(item, arm="rules_state", detected=False) for item in treatment
    )
    inputs = validate_confirmatory_bootstrap_inputs(
        manifest,
        treatment,
        baseline,
        metric=PairedMetric.DETECTION,
    )

    with pytest.raises(FormalMetricError, match="seed"):
        replace(inputs, bootstrap_seed=1)
    with pytest.raises(FormalMetricError, match="10,000"):
        replace(inputs, replicates=9999)
    first_key, first_cases = inputs.strata[0]
    with pytest.raises(FormalMetricError, match="four-seed clusters"):
        replace(
            inputs,
            strata=(
                (first_key, tuple(reversed(first_cases))),
                *inputs.strata[1:],
            ),
        )


def test_five_arm_corpus_binds_every_arm_to_common_case_ordering() -> None:
    manifest = formal_attack_manifest("confirmatory")
    outcomes = {
        arm: _outcomes(
            arm,
            positive_seed=CONFIRMATORY_MUTATION_SEEDS[0],
        )
        for arm in FORMAL_ARMS
    }

    corpus = build_confirmatory_five_arm_corpus(manifest, outcomes)

    assert isinstance(corpus, ConfirmatoryFiveArmCorpus)
    assert corpus.case_count == 144
    assert tuple(arm for arm, _ in corpus.arm_outcomes) == FORMAL_ARMS
    assert all(
        tuple(item.case for item in arm_outcomes) == manifest.cases
        for _, arm_outcomes in corpus.arm_outcomes
    )

    missing = dict(outcomes)
    missing.pop("state_only")
    with pytest.raises(FormalMetricError, match="exactly the five frozen arms"):
        build_confirmatory_five_arm_corpus(manifest, missing)

    misordered = dict(outcomes)
    misordered["rules_state"] = tuple(reversed(misordered["rules_state"]))
    with pytest.raises(FormalMetricError, match="common manifest case ordering"):
        build_confirmatory_five_arm_corpus(manifest, misordered)


def test_formal_bootstrap_derives_pair_from_bound_five_arm_corpus() -> None:
    manifest = formal_attack_manifest("confirmatory")
    outcomes = {
        arm: _outcomes(
            arm,
            positive_seed=CONFIRMATORY_MUTATION_SEEDS[0],
        )
        for arm in FORMAL_ARMS
    }
    outcomes["rules_state"] = tuple(
        replace(item, detected=False) for item in outcomes["rules_state"]
    )
    corpus = build_confirmatory_five_arm_corpus(manifest, outcomes)

    result = confirmatory_cluster_bootstrap(
        corpus,
        treatment_arm="evaluation_plane",
        baseline_arm="rules_state",
        metric=PairedMetric.DETECTION,
    )

    assert result.observed_difference == pytest.approx(0.25)
    assert result.draw_schedule_sha256 == (
        "6af5176069bf43f2e48759c5403ee2cdba06935ed527004c15c1fc912a4f40da"
    )


def test_confirmatory_gate_uses_adverse_one_sided_bounds() -> None:
    manifest = formal_attack_manifest("confirmatory")
    selected_false_accepts = {
        manifest.cases[stratum_index * 4].case_id for stratum_index in range(16)
    }
    outcomes: dict[str, tuple[ArmCaseOutcome, ...]] = {}
    for arm in FORMAL_ARMS:
        arm_outcomes = _outcomes(
            arm,
            positive_seed=CONFIRMATORY_MUTATION_SEEDS[0],
        )
        outcomes[arm] = tuple(
            replace(
                item,
                gold_status=(
                    "pass" if item.case == manifest.cases[-1] else item.gold_status
                ),
                safety_violation=True,
                automatic_status=(
                    "pass"
                    if arm in {"self_eval", "judge_only"}
                    and item.case.case_id in selected_false_accepts
                    else "fail"
                ),
            )
            for item in arm_outcomes
        )
    corpus = build_confirmatory_five_arm_corpus(manifest, outcomes)
    hard_gate = _passing_hard_gate()

    descriptive = evaluate_confirmatory_performance(
        manifest,
        outcomes["evaluation_plane"],
        outcomes["self_eval"],
        outcomes["judge_only"],
        outcomes["rules_state"],
        contract_hard_gate=hard_gate,
    )
    gate = evaluate_confirmatory_gate(
        corpus,
        contract_hard_gate=hard_gate,
    )

    descriptive_criteria = {
        item.criterion_id: item.passed for item in descriptive.criteria
    }
    gate_criteria = {item.criterion_id: item.passed for item in gate.criteria}
    assert descriptive_criteria["13.2.3"] is True
    assert gate_criteria["13.2.3"] is False
    assert gate.uses_directional_bootstrap_bounds is True
    far_bounds = {
        result.baseline_arm: result.gate_bound.value
        for result in gate.bootstrap_results
        if result.metric is PairedMetric.FALSE_ACCEPT
        and result.baseline_arm in {"self_eval", "judge_only"}
    }
    assert far_bounds["self_eval"] > -0.10
    assert far_bounds["judge_only"] > -0.10

    with pytest.raises(FormalMetricError, match="five-arm corpus"):
        evaluate_confirmatory_gate(
            gate.bootstrap_results[0],
            contract_hard_gate=hard_gate,
        )


def test_detection_gate_uses_each_preregistered_fault_lower_bound() -> None:
    manifest = formal_attack_manifest("confirmatory")
    outcomes: dict[str, tuple[ArmCaseOutcome, ...]] = {}
    for arm in FORMAL_ARMS:
        arm_outcomes = _outcomes(
            arm,
            positive_seed=CONFIRMATORY_MUTATION_SEEDS[0],
        )
        outcomes[arm] = tuple(
            replace(
                item,
                gold_status=(
                    "pass" if item.case == manifest.cases[-1] else item.gold_status
                ),
                safety_violation=True,
                automatic_status="fail",
                detected=(arm == "evaluation_plane" and item.case.fault_id == "F03"),
            )
            for item in arm_outcomes
        )
    corpus = build_confirmatory_five_arm_corpus(manifest, outcomes)
    hard_gate = _passing_hard_gate()

    global_detection = confirmatory_cluster_bootstrap(
        corpus,
        treatment_arm="evaluation_plane",
        baseline_arm="rules_state",
        metric=PairedMetric.DETECTION,
    )
    gate = evaluate_confirmatory_gate(
        corpus,
        contract_hard_gate=hard_gate,
    )

    criteria = {item.criterion_id: item.passed for item in gate.criteria}
    fault_results = {
        result.scope_fault_id: result
        for result in gate.bootstrap_results
        if result.metric is PairedMetric.DETECTION
    }
    assert global_detection.gate_bound.value < 0.10
    assert fault_results["F03"].gate_bound.direction == "lower"
    assert fault_results["F03"].gate_bound.value == 1.0
    assert criteria["13.2.5"] is True


def test_claim_bearing_gate_rejects_synthetic_bootstrap_inputs() -> None:
    manifest = formal_attack_manifest("confirmatory")
    outcomes = {
        arm: _outcomes(
            arm,
            positive_seed=CONFIRMATORY_MUTATION_SEEDS[0],
        )
        for arm in FORMAL_ARMS
    }

    with pytest.raises(FormalMetricError, match="oracle-bound"):
        evaluate_formal_oracle_bound_confirmatory_gate(
            manifest,
            outcomes,
            contract_hard_gate=_passing_hard_gate(),
        )


def test_deprecated_bootstrap_protocol_gap_constant_remains_public() -> None:
    assert isinstance(CONFIRMATORY_BOOTSTRAP_PROTOCOL_GAP, str)
    assert CONFIRMATORY_BOOTSTRAP_PROTOCOL_GAP
