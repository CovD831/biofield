from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from biofield.artifacts import ArtifactExistsError
from biofield.meas0 import (
    MEAS0_EXPERIMENT_ID,
    Meas0Arm,
    Meas0PilotConfig,
    aggregate_meas0_results,
    evaluate_meas0_scenario,
    main,
    run_meas0_pilot,
    write_meas0_run,
)
from biofield.meas0_fixtures import load_meas0_fault_suite
from biofield.measurement import EvaluationStatus


def test_each_arm_has_an_explicit_non_overlapping_signal_view() -> None:
    suite = load_meas0_fault_suite()
    scenario = suite.scenario("meas0.fault.text_claim_without_state_change")

    assert evaluate_meas0_scenario(scenario, Meas0Arm.SELF_EVAL).predicted_status is (
        EvaluationStatus.PASS
    )
    assert evaluate_meas0_scenario(scenario, Meas0Arm.JUDGE_ONLY).predicted_status is (
        EvaluationStatus.PASS
    )
    assert evaluate_meas0_scenario(scenario, Meas0Arm.STATE_ONLY).predicted_status is (
        EvaluationStatus.FAIL
    )
    assert evaluate_meas0_scenario(scenario, Meas0Arm.RULES_STATE).predicted_status is (
        EvaluationStatus.FAIL
    )
    assert evaluate_meas0_scenario(
        scenario, Meas0Arm.EVALUATION_PLANE
    ).predicted_status is EvaluationStatus.FAIL


def test_rules_state_catches_policy_but_not_provenance_and_plane_is_noncompensatory() -> None:
    suite = load_meas0_fault_suite()
    unauthorized = suite.scenario("meas0.fault.unauthorized_success")
    provenance = suite.scenario("meas0.fault.forged_or_conflicting_provenance")
    override = suite.scenario("meas0.control.deterministic_fail_judge_override")

    assert evaluate_meas0_scenario(
        unauthorized, Meas0Arm.STATE_ONLY
    ).predicted_status is EvaluationStatus.PASS
    assert evaluate_meas0_scenario(
        unauthorized, Meas0Arm.RULES_STATE
    ).predicted_status is EvaluationStatus.FAIL

    assert evaluate_meas0_scenario(
        provenance, Meas0Arm.RULES_STATE
    ).predicted_status is EvaluationStatus.PASS
    assert evaluate_meas0_scenario(
        provenance, Meas0Arm.EVALUATION_PLANE
    ).predicted_status is EvaluationStatus.DISPUTED

    plane_result = evaluate_meas0_scenario(
        override, Meas0Arm.EVALUATION_PLANE
    )
    assert plane_result.predicted_status is EvaluationStatus.FAIL
    assert plane_result.false_accept is False
    assert "deterministic" in " ".join(plane_result.diagnostics).lower()


def test_evaluator_tampering_invalidates_only_the_formal_plane() -> None:
    scenario = load_meas0_fault_suite().scenario("meas0.control.evaluator_tampering")

    result = evaluate_meas0_scenario(scenario, Meas0Arm.EVALUATION_PLANE)

    assert result.gold_status is EvaluationStatus.INVALID
    assert result.predicted_status is EvaluationStatus.INVALID
    assert result.correct
    assert result.escalated is False


def test_invalid_deterministic_evaluator_cannot_be_treated_as_pass() -> None:
    scenario = load_meas0_fault_suite().scenario("meas0.control.success")
    invalid_state = replace(
        scenario,
        signals=tuple(
            replace(signal, status="invalid") if signal.kind == "state" else signal
            for signal in scenario.signals
        ),
    )

    assert evaluate_meas0_scenario(
        invalid_state, Meas0Arm.RULES_STATE
    ).predicted_status is EvaluationStatus.INVALID
    assert evaluate_meas0_scenario(
        invalid_state, Meas0Arm.EVALUATION_PLANE
    ).predicted_status is EvaluationStatus.INVALID


def test_pilot_is_deterministic_and_reports_comparable_denominators() -> None:
    config = Meas0PilotConfig()

    first = run_meas0_pilot(config)
    second = run_meas0_pilot(config)

    assert first == second
    assert {result.arm for result in first} == set(Meas0Arm)
    assert all(result.scenario_id for result in first)
    summary = aggregate_meas0_results(first)
    assert set(summary) == {arm.value for arm in Meas0Arm}
    for metrics in summary.values():
        assert metrics["cases"] == 18
        assert 0.0 <= metrics["false_accept_rate"] <= 1.0
        assert 0.0 <= metrics["false_reject_rate"] <= 1.0
        assert 0.0 <= metrics["coverage"] <= 1.0
        assert metrics["total_cost"] >= 0.0
    assert summary["evaluation_plane"]["unsafe_successes"] == 0
    assert summary["evaluation_plane"]["false_accepts"] == 0
    assert {metrics["cases"] for metrics in summary.values()} == {18}
    assert {metrics["safety_violation_cases"] for metrics in summary.values()} == {2}


def test_metrics_use_explicit_false_accept_and_false_reject_denominators() -> None:
    results = run_meas0_pilot(Meas0PilotConfig(arms=(Meas0Arm.STATE_ONLY,)))
    metrics = aggregate_meas0_results(results)["state_only"]

    assert metrics["false_accept_rate"] == pytest.approx(
        metrics["false_accepts"] / metrics["non_pass_gold_cases"]
    )
    assert metrics["false_reject_rate"] == pytest.approx(
        metrics["false_rejects"] / metrics["pass_gold_cases"]
    )


def test_write_meas0_run_seals_reproducible_artifacts(tmp_path: Path) -> None:
    run_directory = write_meas0_run(
        output_directory=tmp_path / "runs",
        run_id="meas0-test",
        config=Meas0PilotConfig(),
    )

    assert run_directory == tmp_path / "runs" / MEAS0_EXPERIMENT_ID / "meas0-test"
    assert (run_directory / "config.json").is_file()
    assert (run_directory / "events.jsonl").is_file()
    assert (run_directory / "metrics.json").is_file()
    assert (run_directory / "summary.md").is_file()
    assert (run_directory / "finalization.json").is_file()
    config = json.loads((run_directory / "config.json").read_text(encoding="utf-8"))
    assert config["artifact_scope"] == "decision_table_conformance"
    assert config["claim_limit"] == "not_a_meas0_pilot_result"

    with pytest.raises(ArtifactExistsError):
        write_meas0_run(
            output_directory=tmp_path / "runs",
            run_id="meas0-test",
            config=Meas0PilotConfig(),
        )


def test_meas0_cli_writes_a_sealed_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output_directory = tmp_path / "cli-runs"
    monkeypatch.setattr(
        "sys.argv",
        [
            "biofield-meas0",
            "--output-directory",
            str(output_directory),
            "--run-id",
            "cli-smoke",
        ],
    )

    main()

    run_directory = output_directory / MEAS0_EXPERIMENT_ID / "cli-smoke"
    assert (run_directory / "finalization.json").is_file()
