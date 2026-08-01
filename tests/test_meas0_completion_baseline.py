"""Passing B0 characterization for the 14 MEAS0 completion-audit gaps.

These tests freeze public contract boundaries, not implementation details.  They
are expected to be replaced or tightened by the red/green batch that closes each
gap; they must never be converted into permanent xfails.
"""

from __future__ import annotations

import inspect
from dataclasses import fields

import pytest

from biofield import meas0
from biofield import meas0_detection_oracle as detection
from biofield import meas0_formal_derivation as derivation
from biofield import meas0_formal_lifecycle as lifecycle
from biofield import meas0_formal_metrics as metrics
from biofield import meas0_formal_outcomes as outcomes
from biofield import meas0_formal_run_store as run_store
from biofield import meas0_formal_runner as runner
from biofield import meas0_gold_facts_v3 as gold_facts_v3
from biofield import meas0_gold_outcome_adapter_v3 as gold_outcome_v3
from biofield import meas0_input_manifest as input_manifest
from biofield import meas0_phase_readiness as phase_readiness
from biofield import meas0_pilot_plan_v3 as pilot_plan_v3
from biofield import meas0_protected_vault as protected_vault
from biofield import meas0_readiness as readiness
from biofield import meas0_retained_failure_v3 as retained_failure_v3
from biofield import meas0_trust as trust


def _parameter_names(callable_object: object) -> set[str]:
    return set(inspect.signature(callable_object).parameters)


def _field_names(dataclass_type: type[object]) -> set[str]:
    return {item.name for item in fields(dataclass_type)}


def test_gap_01_v3_phase_readiness_closes_the_all_at_once_gap() -> None:
    """B2 adds ordered receipts while retaining the legacy replay contract."""

    assert tuple(item.value for item in phase_readiness.PhaseReadinessStage) == (
        "pre_jcal_ready",
        "pilot_ready",
        "jaudit_ready",
        "confirmatory_ready",
    )
    receipt_fields = _field_names(phase_readiness.PhaseReadinessReceipt)
    assert {
        "target",
        "authorization",
        "stage_evidence_hashes",
        "previous_receipt_hash",
        "previous_completion_hash",
        "authorized_next_action",
    } <= receipt_fields
    assert hasattr(phase_readiness, "validate_phase_readiness_chain")
    current_fields = _field_names(readiness.FormalReadinessInputs)
    assert {
        "judge_audit_evidence",
        "judge_audit_transport_batch",
        "authorization_checkpoint_manifest",
    } <= current_fields


def test_gap_02_no_typed_sealed_confirmatory_execution_path_exists() -> None:
    """A metrics corpus is not a typed confirmatory runner/package/store."""

    assert hasattr(metrics, "ConfirmatoryFiveArmCorpus")
    for module in (runner, outcomes, run_store):
        assert not hasattr(module, "FormalConfirmatoryPlan")
        assert not hasattr(module, "FormalConfirmatoryRun")
        assert not hasattr(module, "FormalConfirmatoryPackage")


def test_gap_03_v3_gold_facts_exist_but_legacy_package_migration_is_open() -> None:
    """B3 closes nonclaim derivation while the legacy package API remains."""

    assert {
        "gold_status",
        "accept_allowed",
        "safety_violation",
    } <= _parameter_names(derivation.derive_oracle_bound_arm_case_outcome)
    assert {
        "pilot_readiness",
        "input_manifest",
        "gold_scope",
        "gold_artifact",
        "gold_records",
        "reviewer_records",
        "adjudication_records",
    } <= _parameter_names(gold_facts_v3.derive_gold_outcome_facts)
    assert {
        "gold_status",
        "accept_allowed",
        "safety_violation",
    }.isdisjoint(
        _parameter_names(gold_outcome_v3.derive_v3_gold_bound_arm_case_outcome)
    )
    assert "cannot accept" in gold_outcome_v3.V3_OUTCOME_PACKAGE_INTEGRATION_GAP


def test_gap_04_hard_gate_still_accepts_reported_ids_counts_and_booleans() -> None:
    """The current evidence DTO is not a sealed artifact-derived evidence index."""

    current_fields = _field_names(metrics.ContractHardGateEvidence)
    assert {
        "pass_case_ids",
        "deterministic_hard_critical_override_count",
        "protected_hash_checks",
        "replay_hash_checks",
        "judge_calibration_passed",
        "judge_audit_passed",
    } <= current_fields
    assert "sealed_evidence_root" not in current_fields


def test_gap_05_v3_failure_projection_exists_but_package_integration_is_open() -> None:
    """B4 derives nonclaim failures; the legacy package still requires outcomes."""

    artifact_fields = _field_names(runner.FormalArmCaseArtifact)
    assert {"failure", "canonical_evaluation", "retained_in_denominator"} <= (
        artifact_fields
    )
    retained_fields = _field_names(retained_failure_v3.RetainedFailureOutcome)
    assert {
        "failure_artifact",
        "result_validity",
        "automatic_status",
        "attempts",
        "stage_cost_pre_ledger_hash",
        "stage_cost_ledger_hash",
        "not_observed_fields",
        "denominator_retained",
    } <= retained_fields
    assert {
        "request",
        "failure",
        "failure_policy",
        "stage_cost_pre_ledger",
        "stage_cost_ledger",
    } <= _parameter_names(retained_failure_v3.RetainedFailureOutcome.create)
    assert {
        "artifact_facts",
        "signal_projections",
        "detection_records",
        "outcomes",
    } <= _parameter_names(outcomes.compose_formal_outcome_package)


def test_gap_06_typed_checkpoint_target_now_closes_opaque_hash_gap() -> None:
    """B1 adds the V3 target while legacy opaque requirements stay non-authority."""

    checkpoint_fields = _field_names(trust.AuthorizationCheckpointRequirement)
    assert "authorization_target_hash" in checkpoint_fields
    typed_fields = _field_names(lifecycle.PhaseCheckpointTarget)
    assert {
        "checkpoint",
        "authority_role_id",
        "comparison_block_id",
        "evidence_bindings",
        "previous_target_hash",
    } <= typed_fields
    assert hasattr(lifecycle, "validate_v3_phase_checkpoint_chain")


def test_gap_07_gate_m_has_no_terminal_derivation_factory() -> None:
    """The lifecycle exposes NOT_EVALUATED but no evidence-driven PASS/FAIL API."""

    assert lifecycle.GateMClaimState.NOT_EVALUATED.value == "not_evaluated"
    assert not hasattr(lifecycle, "derive_gate_m_terminal")
    assert not hasattr(lifecycle, "GateMTerminalReceipt")


def test_gap_08_store_replay_requires_original_typed_objects() -> None:
    """The current replay API is not a sealed-bytes source-of-truth restore."""

    replay_parameters = _parameter_names(run_store.FormalRunPackageStore.replay)
    assert {
        "plan",
        "run",
        "outcome_evidence",
        "oracle_manifest",
        "outcomes",
    } <= replay_parameters
    assert not hasattr(run_store, "restore_and_replay")


def test_gap_09_cli_has_no_production_backend_or_verifier_injection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The serialized CLI surface cannot assemble a production execution."""

    with pytest.raises(SystemExit) as exit_info:
        meas0._pilot_cli(["run", "--help"])
    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "--execution-mode" in help_text
    assert "--backend" not in help_text
    assert "--transport-verifier" not in help_text
    assert "--human-verifier" not in help_text


def test_gap_10_runtime_transport_has_no_reverification_injection_point() -> None:
    """Neither execution nor replay accepts a runtime transport verifier."""

    assert "transport_verifier" not in _parameter_names(runner.run_formal_contract)
    assert "transport_verifier" not in _parameter_names(
        run_store.FormalRunPackageStore.replay
    )


def test_gap_11_v3_candidate_is_manifest_bound_but_production_migration_is_open() -> (
    None
):
    """B2a closes offline derivation; legacy production authority is untouched."""

    assert {
        "task_hash",
        "episode_hash",
        "failure_policy_hash",
        "semantic_leaf_count",
        "measurement_count",
    } <= _field_names(runner.FormalPilotCaseInput)
    manifest_fields = _field_names(input_manifest.InputManifest)
    assert {
        "protected_corpus_hash",
        "case_scope_manifest_hash",
        "readiness_parent_receipt_hash",
        "readiness_parent_target_hash",
        "comparison_block_id",
        "source_lock_hash",
        "common_ancestry_hash",
    } <= manifest_fields
    candidate_parameters = _parameter_names(
        pilot_plan_v3.create_simulated_pilot_plan_candidate
    )
    assert {"input_manifest", "pre_jcal_readiness", "pilot_readiness"} <= (
        candidate_parameters
    )
    assert {"cases", "case_count", "input_manifest_hash"}.isdisjoint(
        candidate_parameters
    )
    assert {
        "claim_scope",
        "production_authorized",
        "test_only",
    } <= _field_names(pilot_plan_v3.SimulatedPilotPlanCandidate)
    assert not hasattr(runner.FormalPilotPlan, "create_from_readiness")
    assert not hasattr(runner.FormalPilotPlan, "restore_from_sealed")


def test_gap_12_vault_contract_exists_but_store_integration_remains_open() -> None:
    """B8a has a nonclaim vault contract; package publication is still pending."""

    reference_fields = _field_names(protected_vault.ProtectedEvidenceReference)
    assert {
        "vault_id",
        "package_id",
        "common_ancestry_hash",
        "object_id",
        "object_hash",
        "byte_count",
    } <= reference_fields
    assert {"path", "uri", "payload", "raw_bytes"}.isdisjoint(reference_fields)
    assert hasattr(protected_vault, "SimulatedProtectedEvidenceVault")
    assert "protected_evidence_vault" not in _parameter_names(
        run_store.FormalRunPackageStore.publish
    )


def test_gap_13_request_response_bytes_have_no_archive_resolver() -> None:
    """Hashes/artifacts exist, but replay cannot resolve exact protected bytes."""

    artifact_fields = _field_names(runner.FormalArmCaseArtifact)
    assert "request_hash" in artifact_fields
    assert "request_bytes" not in artifact_fields
    assert "response_bytes" not in artifact_fields
    replay_parameters = _parameter_names(run_store.FormalRunPackageStore.replay)
    assert "protected_byte_resolver" not in replay_parameters
    assert "request_response_archive" not in replay_parameters


def test_gap_14_formal_detection_still_reads_backend_authored_signals() -> None:
    """The formal projection API still consumes artifact convenience signals."""

    assert {"manifest", "artifact", "facts"} == _parameter_names(
        detection.derive_detection_signal_projection
    )
    assert "authorized_signal_fields" in _field_names(detection.DetectionOracleEntry)
    assert not hasattr(detection, "AuthoritativeMeasurandProducer")


def test_existing_test_evidence_cannot_be_deserialized_as_production() -> None:
    """B0 preserves the already-valid test/production evidence-class barrier."""

    with pytest.raises(
        trust.TrustContractError,
        match="serialized production verification results are untrusted",
    ):
        trust.ProductionVerificationResult.from_dict({"production_authorized": True})
