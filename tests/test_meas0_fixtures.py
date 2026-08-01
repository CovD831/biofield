from __future__ import annotations

import json
from dataclasses import replace

import pytest

from biofield.meas0_fixtures import (
    MEAS0_ARMS,
    MEAS0_PROTOCOL_SCENARIOS,
    Meas0FixtureError,
    load_meas0_fault_suite,
    parse_meas0_fault_suite,
)


EXPECTED_SIGNAL_KINDS = {
    "self_report",
    "evidence",
    "source",
    "trajectory",
    "state",
    "semantic",
}


def _payload() -> dict[str, object]:
    suite = load_meas0_fault_suite()
    return json.loads(suite.source_json)


def test_packaged_v1_suite_covers_protocol_faults_and_controls() -> None:
    suite = load_meas0_fault_suite()

    assert suite.schema_id == "biofield.meas0.synthetic_fault_suite"
    assert suite.schema_version == "1"
    assert suite.suite_id == "meas0.synthetic_faults"
    assert suite.suite_version == "1"
    assert suite.protocol_ref == (
        "docs/experiments/EXPERIMENT_PROTOCOL.md#4.4"
    )
    assert suite.arms == MEAS0_ARMS
    assert len(suite.scenarios) >= 16
    assert {
        scenario.protocol_scenario
        for scenario in suite.scenarios
        if scenario.protocol_scenario is not None
    } == set(MEAS0_PROTOCOL_SCENARIOS)

    successful_control = suite.scenario("meas0.control.success")
    clean_failure = suite.scenario("meas0.control.clean_failure")
    assert successful_control.expected_gold_status == "pass"
    assert successful_control.fault_category == "none"
    assert clean_failure.expected_gold_status == "fail"
    assert clean_failure.fault_category == "clean_failure"


def test_each_scenario_has_all_signals_arms_and_provenance() -> None:
    suite = load_meas0_fault_suite()

    for scenario in suite.scenarios:
        assert {signal.kind for signal in scenario.signals} == EXPECTED_SIGNAL_KINDS
        assert scenario.applicable_arms == MEAS0_ARMS
        assert isinstance(scenario.safety_violation, bool)
        for signal in scenario.signals:
            assert signal.provenance_refs
            assert all("://" in ref for ref in signal.provenance_refs)


def test_fixture_expected_statuses_and_review_escalation_are_explicit() -> None:
    suite = load_meas0_fault_suite()

    assert {scenario.expected_gold_status for scenario in suite.scenarios} >= {
        "pass",
        "fail",
        "unknown",
        "disputed",
        "invalid",
    }
    assert all(
        scenario.human_review_required
        for scenario in suite.scenarios
        if scenario.expected_gold_status in {"unknown", "disputed"}
    )
    assert all(
        scenario.critical for scenario in suite.scenarios if scenario.hard_gate
    )


def test_integrity_controls_separate_self_report_from_judge_semantics() -> None:
    suite = load_meas0_fault_suite()

    tampering = suite.scenario("meas0.control.evaluator_tampering")
    judge_override = suite.scenario(
        "meas0.control.deterministic_fail_judge_override"
    )

    assert tampering.protocol_scenario is None
    assert tampering.expected_gold_status == "invalid"
    assert tampering.hard_gate
    assert not tampering.safety_violation
    assert tampering.signal("self_report").status == "pass"
    assert tampering.signal("source").status == "invalid"

    assert judge_override.protocol_scenario is None
    assert judge_override.expected_gold_status == "fail"
    assert judge_override.hard_gate
    assert not judge_override.safety_violation
    assert judge_override.signal("self_report").status == "pass"
    assert judge_override.signal("state").status == "fail"
    assert judge_override.signal("semantic").status == "pass"


def test_suite_is_deterministic_and_scenarios_are_immutable() -> None:
    first = load_meas0_fault_suite()
    second = load_meas0_fault_suite()

    assert first == second
    with pytest.raises((AttributeError, TypeError)):
        first.scenarios[0].scenario_id = "changed"  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        replace(first.scenarios[0].signals[0], provenance_refs=[])


@pytest.mark.parametrize(
    "version",
    ["0", "2", "../r1", "../../answer_key", "/tmp/v1", "1/../1", ""],
)
def test_unknown_versions_and_path_traversal_are_rejected(version: str) -> None:
    with pytest.raises(Meas0FixtureError, match="unsupported MEAS0 fixture version"):
        load_meas0_fault_suite(version)


def test_schema_version_mismatch_is_rejected() -> None:
    payload = _payload()
    payload["schema_version"] = "2"

    with pytest.raises(Meas0FixtureError, match="unsupported schema version"):
        parse_meas0_fault_suite(payload)


def test_duplicate_scenario_ids_are_rejected() -> None:
    payload = _payload()
    scenarios = payload["scenarios"]
    assert isinstance(scenarios, list)
    duplicate = dict(scenarios[0])
    duplicate["title"] = "duplicate"
    scenarios.append(duplicate)

    with pytest.raises(Meas0FixtureError, match="duplicate scenario_id"):
        parse_meas0_fault_suite(payload)


def test_missing_protocol_scenario_is_rejected() -> None:
    payload = _payload()
    scenarios = payload["scenarios"]
    assert isinstance(scenarios, list)
    payload["scenarios"] = [
        scenario
        for scenario in scenarios
        if scenario["protocol_scenario"] != 14
    ]

    with pytest.raises(Meas0FixtureError, match="protocol scenario coverage"):
        parse_meas0_fault_suite(payload)


def test_missing_signal_and_invalid_gold_status_are_rejected() -> None:
    payload = _payload()
    scenarios = payload["scenarios"]
    assert isinstance(scenarios, list)
    scenarios[0]["signals"].pop("source")
    scenarios[1]["expected_gold_status"] = "mostly_pass"

    with pytest.raises(Meas0FixtureError, match="fixture schema validation failed"):
        parse_meas0_fault_suite(payload)


def test_unknown_arm_and_malformed_provenance_are_rejected() -> None:
    payload = _payload()
    scenarios = payload["scenarios"]
    assert isinstance(scenarios, list)
    scenarios[0]["applicable_arms"].append("oracle_magic")
    scenarios[0]["signals"]["state"]["provenance_refs"] = ["../../state"]

    with pytest.raises(Meas0FixtureError, match="fixture schema validation failed"):
        parse_meas0_fault_suite(payload)


def test_each_scenario_must_keep_the_common_five_arm_cohort() -> None:
    payload = _payload()
    scenarios = payload["scenarios"]
    assert isinstance(scenarios, list)
    scenarios[0]["applicable_arms"] = ["evaluation_plane"]

    with pytest.raises(Meas0FixtureError, match="common five-arm cohort"):
        parse_meas0_fault_suite(payload)


def test_unknown_or_disputed_without_human_review_is_rejected() -> None:
    payload = _payload()
    scenarios = payload["scenarios"]
    assert isinstance(scenarios, list)
    target = next(
        scenario
        for scenario in scenarios
        if scenario["expected_gold_status"] == "unknown"
    )
    target["human_review_required"] = False

    with pytest.raises(Meas0FixtureError, match="requires human review"):
        parse_meas0_fault_suite(payload)


def test_hard_gate_must_be_critical() -> None:
    payload = _payload()
    scenarios = payload["scenarios"]
    assert isinstance(scenarios, list)
    target = next(scenario for scenario in scenarios if scenario["hard_gate"])
    target["critical"] = False

    with pytest.raises(Meas0FixtureError, match="hard_gate must be critical"):
        parse_meas0_fault_suite(payload)
