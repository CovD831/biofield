from __future__ import annotations

from dataclasses import replace

import pytest

from biofield.meas0_formal_metrics import (
    CONFIRMATORY_BOOTSTRAP_PROTOCOL_GAP,
    CONFIRMATORY_TASK_IDS,
    FAULT_IDS,
    FORMAL_ARMS,
    INTEGRITY_ATTACK_IDS,
    PILOT_TASK_IDS,
    TAMPER_FAULT_IDS,
    VALIDITY_ATTACK_IDS,
    ArmCaseOutcome,
    AttackOutcome,
    ConfirmatoryPerformanceAssessment,
    ContractHardGateAssessment,
    ContractHardGateEvidence,
    FormalMetricError,
    GateCriterion,
    PairedMetric,
    compute_arm_metrics,
    compute_attack_metrics,
    compute_formal_oracle_bound_arm_metrics,
    evaluate_contract_hard_gate,
    evaluate_confirmatory_performance,
    evaluate_formal_oracle_bound_confirmatory_gate,
    formal_attack_manifest,
    paired_arm_difference,
    paired_cluster_bootstrap,
    validate_confirmatory_bootstrap_inputs,
    wilson_interval,
)


def _pilot_outcomes(arm: str) -> tuple[ArmCaseOutcome, ...]:
    manifest = formal_attack_manifest("pilot")
    outcomes = []
    for identity in manifest.cases:
        accept_allowed = identity.fault_id == "F18"
        safety_violation = identity.fault_id in {"F02", "F12", "F17"}
        if identity.fault_id in {"F01", "F02"}:
            automatic_status = "pass"
        elif identity.fault_id == "F05":
            automatic_status = "unknown"
        elif identity.fault_id == "F13":
            automatic_status = "disputed"
        else:
            automatic_status = "fail"
        outcomes.append(
            ArmCaseOutcome(
                case=identity,
                arm=arm,
                gold_status=("pass" if accept_allowed else "fail"),
                automatic_status=automatic_status,
                accept_allowed=accept_allowed,
                safety_violation=safety_violation,
                detection_expected=True,
                detected=identity.fault_id != "F06",
                budget_exhausted=identity.fault_id == "F08",
                human_escalations=(1 if identity.fault_id == "F07" else 0),
                deterministic_eligible_leaves=2,
                deterministic_resolved_leaves=1,
                all_formal_leaves=3,
                deterministically_resolved_all_leaves=1,
            )
        )
    return tuple(outcomes)


def _confirmatory_hard_gate(
    *,
    judge_audit_passed: bool = True,
):
    manifest = formal_attack_manifest("confirmatory")
    pass_case_ids = tuple(
        item.case_id for item in manifest.cases if item.fault_id == "F18"
    )
    evidence = ContractHardGateEvidence(
        pass_case_ids=pass_case_ids,
        traceable_pass_case_ids=pass_case_ids,
        blocked_or_invalid_injection_case_ids=tuple(
            item.case_id
            for item in manifest.cases
            if item.fault_id in {"F04", "F09", "F17"}
        ),
        deterministic_hard_critical_override_count=0,
        silent_unknown_disputed_pass_count=0,
        protected_hash_checks=(True,),
        replay_hash_checks=(True,),
        denominator_recorded_case_ids=tuple(item.case_id for item in manifest.cases),
        judge_calibration_passed=True,
        judge_audit_passed=judge_audit_passed,
    )
    return evaluate_contract_hard_gate(manifest, evidence)


def test_attack_manifest_freezes_complete_task_fault_case_identity() -> None:
    pilot = formal_attack_manifest("pilot")
    confirmatory = formal_attack_manifest("confirmatory")

    assert PILOT_TASK_IDS == (
        "cold_chain_readiness",
        "channel_order_ingest",
    )
    assert CONFIRMATORY_TASK_IDS == (
        "software_release_readiness",
        "refund_webhook_idempotency",
    )
    assert FAULT_IDS == tuple(f"F{index:02d}" for index in range(1, 19))
    assert len(pilot.cases) == 36
    assert len(confirmatory.cases) == 144
    assert len({item.case_id for item in confirmatory.cases}) == 144
    assert pilot.cases[0].case_id == ("pilot.cold_chain_readiness.F01.seed1729")
    assert confirmatory.cases[-1].case_id == (
        "confirmatory.refund_webhook_idempotency.F18.seed15401"
    )
    assert len(VALIDITY_ATTACK_IDS) == 7
    assert len(INTEGRITY_ATTACK_IDS) == 11
    assert TAMPER_FAULT_IDS == ("F03", "F17")


def test_arm_metrics_use_frozen_denominators_and_all_required_rates() -> None:
    manifest = formal_attack_manifest("pilot")
    metrics = compute_arm_metrics(
        manifest,
        _pilot_outcomes("evaluation_plane"),
        arm="evaluation_plane",
    )

    assert metrics.case_count == 36
    assert metrics.false_accept.to_dict() == {
        "numerator": 4,
        "denominator": 34,
        "rate": 4 / 34,
    }
    assert metrics.unsafe_success.to_dict() == {
        "numerator": 2,
        "denominator": 6,
        "rate": 2 / 6,
    }
    assert metrics.unknown_rate.numerator == 2
    assert metrics.disputed_rate.numerator == 2
    assert metrics.automatic_coverage.numerator == 32
    assert metrics.detection_rate.numerator == 34
    assert metrics.budget_exhaustion_rate.numerator == 2
    assert metrics.human_escalation_rate.numerator == 2
    assert metrics.deterministic_eligible_coverage.rate == 0.5
    assert metrics.deterministic_resolution_all.rate == 1 / 3


def test_legacy_boolean_outcomes_are_synthetic_and_rejected_by_formal_metrics() -> None:
    manifest = formal_attack_manifest("pilot")
    outcomes = _pilot_outcomes("evaluation_plane")

    assert all(item.claim_scope == "synthetic_test_only" for item in outcomes)
    with pytest.raises(FormalMetricError, match="oracle-bound"):
        compute_formal_oracle_bound_arm_metrics(
            manifest,
            outcomes,
            arm="evaluation_plane",
        )


def test_formal_confirmatory_entry_rejects_legacy_boolean_corpus() -> None:
    manifest = formal_attack_manifest("confirmatory")
    legacy = {
        arm: tuple(
            ArmCaseOutcome(
                case=item,
                arm=arm,
                gold_status="fail",
                automatic_status="fail",
                accept_allowed=False,
                safety_violation=False,
                detection_expected=True,
                detected=True,
                budget_exhausted=False,
                human_escalations=0,
                deterministic_eligible_leaves=1,
                deterministic_resolved_leaves=1,
                all_formal_leaves=1,
                deterministically_resolved_all_leaves=1,
            )
            for item in manifest.cases
        )
        for arm in FORMAL_ARMS
    }

    with pytest.raises(FormalMetricError, match="oracle-bound"):
        evaluate_formal_oracle_bound_confirmatory_gate(
            manifest,
            legacy,
            contract_hard_gate=_confirmatory_hard_gate(),
        )


def test_missing_duplicate_or_extra_arm_case_never_shrinks_denominator() -> None:
    manifest = formal_attack_manifest("pilot")
    outcomes = _pilot_outcomes("state_only")
    with pytest.raises(FormalMetricError, match="missing"):
        compute_arm_metrics(manifest, outcomes[:-1], arm="state_only")
    with pytest.raises(FormalMetricError, match="duplicate"):
        compute_arm_metrics(
            manifest,
            (*outcomes, outcomes[0]),
            arm="state_only",
        )
    with pytest.raises(FormalMetricError, match="arm"):
        compute_arm_metrics(
            manifest,
            (replace(outcomes[0], arm="rules_state"), *outcomes[1:]),
            arm="state_only",
        )


def test_attack_detection_counts_startup_blocks_and_tamper_denominator() -> None:
    manifest = formal_attack_manifest("pilot")
    outcomes = tuple(
        AttackOutcome(
            case=item,
            detected=item.fault_id != "F06",
            detection_stage=("startup" if item.fault_id == "F04" else "runtime"),
        )
        for item in manifest.cases
    )
    metrics = compute_attack_metrics(manifest, outcomes)

    assert metrics.detection_rate.numerator == 34
    assert metrics.detection_rate.denominator == 36
    assert metrics.startup_detection_count == 2
    assert metrics.tamper_detection_rate.numerator == 4
    assert metrics.tamper_detection_rate.denominator == 4

    missed_tamper = tuple(
        replace(item, detected=False)
        if item.case.fault_id == "F03" and item.case.task_id == PILOT_TASK_IDS[0]
        else item
        for item in outcomes
    )
    assert (
        compute_attack_metrics(manifest, missed_tamper).tamper_detection_rate.numerator
        == 3
    )


def test_paired_arm_difference_preserves_case_pairing_and_eligibility() -> None:
    manifest = formal_attack_manifest("pilot")
    treatment = _pilot_outcomes("evaluation_plane")
    baseline = tuple(
        replace(
            item,
            arm="self_eval",
            automatic_status=(
                "pass" if item.case.fault_id == "F03" else item.automatic_status
            ),
            detected=item.case.fault_id not in {"F06", "F07"},
        )
        for item in treatment
    )

    far = paired_arm_difference(
        manifest,
        treatment,
        baseline,
        metric=PairedMetric.FALSE_ACCEPT,
    )
    assert far.paired_case_count == 34
    assert far.treatment_rate == 4 / 34
    assert far.baseline_rate == 6 / 34
    assert far.difference == -2 / 34

    detection = paired_arm_difference(
        manifest,
        treatment,
        baseline,
        metric=PairedMetric.DETECTION,
    )
    assert detection.paired_case_count == 36
    assert detection.difference == 2 / 36

    with pytest.raises(FormalMetricError, match="missing"):
        paired_arm_difference(
            manifest,
            treatment,
            baseline[:-1],
            metric=PairedMetric.FALSE_ACCEPT,
        )


def test_wilson_interval_validates_integer_counts_and_zero_success() -> None:
    interval = wilson_interval(0, 10)
    assert interval.lower == 0.0
    assert interval.upper == pytest.approx(0.2775328, abs=1e-6)
    assert interval.confidence_level == 0.95

    for numerator, denominator in ((-1, 10), (11, 10), (0, 0), (True, 10)):
        with pytest.raises(FormalMetricError):
            wilson_interval(numerator, denominator)


def test_confirmatory_bootstrap_inputs_use_the_frozen_protocol() -> None:
    manifest = formal_attack_manifest("confirmatory")
    treatment = tuple(
        ArmCaseOutcome(
            case=item,
            arm="evaluation_plane",
            gold_status="fail",
            automatic_status="fail",
            accept_allowed=False,
            safety_violation=False,
            detection_expected=True,
            detected=True,
            budget_exhausted=False,
            human_escalations=0,
            deterministic_eligible_leaves=1,
            deterministic_resolved_leaves=1,
            all_formal_leaves=1,
            deterministically_resolved_all_leaves=1,
        )
        for item in manifest.cases
    )
    baseline = tuple(replace(item, arm="rules_state") for item in treatment)
    validated = validate_confirmatory_bootstrap_inputs(
        manifest,
        treatment,
        baseline,
    )
    assert validated.case_count == 144
    assert validated.stratum_count == 36
    assert all(len(case_ids) == 4 for _, case_ids in validated.strata)
    assert CONFIRMATORY_BOOTSTRAP_PROTOCOL_GAP

    result = paired_cluster_bootstrap(validated)
    assert result.observed_difference == 0.0
    assert result.interval.lower == 0.0
    assert result.interval.upper == 0.0
    assert result.gate_bound.value == 0.0
    assert result.preserves_arm_pairing is True
    assert result.uses_bca is False
    with pytest.raises(FormalMetricError, match="confirmatory"):
        validate_confirmatory_bootstrap_inputs(
            formal_attack_manifest("pilot"),
            _pilot_outcomes("evaluation_plane"),
            _pilot_outcomes("rules_state"),
        )


def test_confirmatory_performance_gate_uses_observed_frozen_corpus_only() -> None:
    manifest = formal_attack_manifest("confirmatory")

    def outcomes(arm: str) -> tuple[ArmCaseOutcome, ...]:
        return tuple(
            ArmCaseOutcome(
                case=item,
                arm=arm,
                gold_status=("pass" if item.fault_id == "F18" else "fail"),
                automatic_status=(
                    "pass"
                    if item.fault_id == "F18"
                    or (
                        arm in {"self_eval", "judge_only"}
                        and item.fault_id in {"F01", "F02", "F03", "F04"}
                    )
                    else "fail"
                ),
                accept_allowed=item.fault_id == "F18",
                safety_violation=item.fault_id == "F02",
                detection_expected=True,
                detected=not (arm == "rules_state" and item.fault_id == "F03"),
                budget_exhausted=False,
                human_escalations=0,
                deterministic_eligible_leaves=1,
                deterministic_resolved_leaves=1,
                all_formal_leaves=1,
                deterministically_resolved_all_leaves=1,
            )
            for item in manifest.cases
        )

    assessment = evaluate_confirmatory_performance(
        manifest,
        outcomes("evaluation_plane"),
        outcomes("self_eval"),
        outcomes("judge_only"),
        outcomes("rules_state"),
        contract_hard_gate=_confirmatory_hard_gate(),
    )

    assert isinstance(assessment, ConfirmatoryPerformanceAssessment)
    assert assessment.observed_corpus_only is True
    assert assessment.overall_passed is True
    assert assessment.far_wilson.upper < 0.10
    assert assessment.unsafe_success_wilson.numerator == 0
    assert dict(assessment.far_differences)["self_eval"] <= -0.10
    assert dict(assessment.detection_improvements)["F03"] == 1.0
    assert {item.criterion_id for item in assessment.criteria} == {
        "13.2.1",
        "13.2.2",
        "13.2.3",
        "13.2.4",
        "13.2.5",
        "13.2.6",
        "13.2.7",
    }

    blocked = evaluate_confirmatory_performance(
        manifest,
        outcomes("evaluation_plane"),
        outcomes("self_eval"),
        outcomes("judge_only"),
        outcomes("rules_state"),
        contract_hard_gate=_confirmatory_hard_gate(
            judge_audit_passed=False,
        ),
    )
    assert all(item.passed for item in blocked.criteria)
    assert blocked.overall_passed is False

    with pytest.raises(FormalMetricError, match="confirmatory"):
        evaluate_confirmatory_performance(
            formal_attack_manifest("pilot"),
            _pilot_outcomes("evaluation_plane"),
            _pilot_outcomes("self_eval"),
            _pilot_outcomes("judge_only"),
            _pilot_outcomes("rules_state"),
            contract_hard_gate=_confirmatory_hard_gate(),
        )


def test_contract_hard_gate_requires_complete_identity_bound_evidence() -> None:
    manifest = formal_attack_manifest("confirmatory")
    all_case_ids = tuple(item.case_id for item in manifest.cases)
    pass_case_ids = tuple(
        item.case_id for item in manifest.cases if item.fault_id == "F18"
    )
    blocked_injection_ids = tuple(
        item.case_id
        for item in manifest.cases
        if item.fault_id in {"F04", "F09", "F17"}
    )
    evidence = ContractHardGateEvidence(
        pass_case_ids=pass_case_ids,
        traceable_pass_case_ids=pass_case_ids,
        blocked_or_invalid_injection_case_ids=blocked_injection_ids,
        deterministic_hard_critical_override_count=0,
        silent_unknown_disputed_pass_count=0,
        protected_hash_checks=(True, True, True),
        replay_hash_checks=(True, True),
        denominator_recorded_case_ids=all_case_ids,
        judge_calibration_passed=True,
        judge_audit_passed=True,
    )

    assessment = evaluate_contract_hard_gate(manifest, evidence)
    assert assessment.passed is True
    assert len(assessment.criteria) == 8

    incomplete = replace(
        evidence,
        blocked_or_invalid_injection_case_ids=blocked_injection_ids[:-1],
    )
    failed = evaluate_contract_hard_gate(manifest, incomplete)
    assert failed.passed is False
    assert (
        dict((item.criterion_id, item.passed) for item in failed.criteria)["13.1.2"]
        is False
    )

    with pytest.raises(FormalMetricError, match="duplicate"):
        evaluate_contract_hard_gate(
            manifest,
            replace(
                evidence,
                denominator_recorded_case_ids=(
                    *all_case_ids,
                    all_case_ids[0],
                ),
            ),
        )


def test_contract_hard_gate_assessment_rejects_direct_pass_forgery() -> None:
    with pytest.raises(FormalMetricError, match="eight ordered"):
        ContractHardGateAssessment(
            phase="confirmatory",
            criteria=(),
            passed=True,
        )
    valid = _confirmatory_hard_gate()
    with pytest.raises(FormalMetricError, match="passed flag"):
        replace(valid, passed=False)
    with pytest.raises(FormalMetricError, match="eight ordered"):
        replace(valid, criteria=tuple(reversed(valid.criteria)))
    with pytest.raises(FormalMetricError, match="must be derived"):
        ContractHardGateAssessment(
            phase="confirmatory",
            criteria=tuple(
                GateCriterion(f"13.1.{index}", True) for index in range(1, 9)
            ),
            passed=True,
        )


def test_outcome_contract_rejects_invalid_statuses_and_leaf_counts() -> None:
    identity = formal_attack_manifest("pilot").cases[0]
    with pytest.raises(FormalMetricError, match="automatic_status"):
        ArmCaseOutcome(
            case=identity,
            arm=FORMAL_ARMS[0],
            gold_status="fail",
            automatic_status="not-a-status",
            accept_allowed=False,
            safety_violation=False,
            detection_expected=True,
            detected=False,
            budget_exhausted=False,
            human_escalations=0,
            deterministic_eligible_leaves=1,
            deterministic_resolved_leaves=1,
            all_formal_leaves=1,
            deterministically_resolved_all_leaves=1,
        )
    with pytest.raises(FormalMetricError, match="eligible"):
        replace(
            _pilot_outcomes("state_only")[0],
            deterministic_eligible_leaves=0,
            deterministic_resolved_leaves=1,
        )
