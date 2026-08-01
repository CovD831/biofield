from __future__ import annotations

import hashlib
import inspect
from dataclasses import replace

import pytest

from biofield.meas0_detection_oracle import (
    DetectionOracleError,
    DetectionSignalProjection,
    build_test_only_candidate_oracle,
    derive_detection_signal_projection,
    derive_test_only_detection,
)
from biofield.meas0_formal_derivation import (
    OracleBoundArmCaseOutcome,
    derive_artifact_facts,
    derive_oracle_bound_arm_case_outcome,
)
from biofield.meas0_formal_metrics import (
    FormalCaseIdentity,
    FormalMetricError,
    compute_formal_oracle_bound_arm_metrics,
    formal_attack_manifest,
)
from biofield.meas0_formal_runner import (
    CLAIM_SCOPE,
    CanonicalEvaluationBinding,
    FailureCode,
    FormalArmCaseArtifact,
    FormalCostArtifact,
    FormalFailureArtifact,
    FormalRunnerError,
    RawObservationArtifact,
    RawResultArtifact,
    ResultValidity,
)
from biofield.meas0_r1 import (
    build_cold_chain_episode,
    load_cold_chain_evaluator,
    load_cold_chain_subject_input,
)
from biofield.measurement import EvaluationStatus, fuse_evidence


def _artifact() -> FormalArmCaseArtifact:
    evaluator = load_cold_chain_evaluator()
    episode = build_cold_chain_episode(
        subject_input=load_cold_chain_subject_input(),
        task_measurement_bundle=evaluator.measurement_bundle,
        structured_answer_bytes=None,
        response_bytes=b"no structured answer",
    )
    observations = evaluator.evaluate(episode)
    result = fuse_evidence(
        result_id="formal.derivation.test",
        task_measurement_bundle=evaluator.measurement_bundle,
        sealed_episode=episode.sealed_episode,
        observations=observations,
    )
    binding = CanonicalEvaluationBinding(
        task_measurement_bundle=evaluator.measurement_bundle,
        sealed_episode=episode.sealed_episode,
        observations=observations,
        evaluation_result=result,
    )
    case_id = "pilot.cold_chain_readiness.F01.seed1729"
    return FormalArmCaseArtifact(
        authorization_hash="a" * 64,
        request_hash="e" * 64,
        execution_index=0,
        case_id=case_id,
        task_id="cold_chain_readiness",
        fault_id="F01",
        arm_id="evaluation_plane",
        backend_id="pytest.production-like",
        claim_scope=CLAIM_SCOPE,
        result_validity=ResultValidity.VALID,
        automatic_status=result.outcome,
        observations=(
            RawObservationArtifact(
                observation_id="raw.formal.derivation",
                case_id=case_id,
                arm_id="evaluation_plane",
                source="pytest",
                payload_json=(
                    '{"detection_signals":{'
                    '"authoritative_state_changed":false,'
                    '"claimed_success":true'
                    '},"source":"canonical"}'
                ),
            ),
        ),
        raw_result=RawResultArtifact(
            result_id="raw.formal.derivation",
            case_id=case_id,
            arm_id="evaluation_plane",
            automatic_status=result.outcome,
            timed_out=False,
            payload_json='{"status":"fail"}',
        ),
        cost=FormalCostArtifact(human_escalations=1),
        judge_call_costs=(),
        stage_cost_entry_hashes=(),
        failure=None,
        canonical_evaluation=binding,
    )


def test_artifact_facts_are_derived_from_canonical_bundle_and_observations() -> None:
    artifact = _artifact()
    facts = derive_artifact_facts(artifact)

    graph = artifact.canonical_evaluation.task_measurement_bundle.measurement_graph
    requirements = artifact.canonical_evaluation.task_measurement_bundle.requirement_graph.requirements
    assert facts.artifact_hash == artifact.artifact_hash
    assert facts.authorization_hash == artifact.authorization_hash
    assert facts.automatic_status is EvaluationStatus.FAIL
    assert facts.human_escalations == 1
    assert facts.all_formal_leaves == len(requirements)
    assert facts.deterministic_eligible_leaves <= len(requirements)
    assert facts.deterministic_resolved_leaves <= (facts.deterministic_eligible_leaves)
    assert len(graph.measurement_specs) >= facts.deterministic_eligible_leaves
    assert facts.derivation_hash == derive_artifact_facts(artifact).derivation_hash


def test_artifact_facts_reject_failure_status_injection() -> None:
    artifact = _artifact()
    with pytest.raises(FormalRunnerError, match="failure disposition"):
        derive_artifact_facts(
            replace(
                artifact,
                failure=FormalFailureArtifact(
                    code=FailureCode.BUDGET_EXHAUSTED,
                    message="forged budget failure",
                ),
                automatic_status=EvaluationStatus.PASS,
            )
        )


def _candidate_manifest():
    def digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    return build_test_only_candidate_oracle(
        design_sha256=digest("design"),
        fault_manifest_sha256=digest("faults"),
        case_manifest_sha256=digest("cases"),
        task_adapter_source_hashes={
            "cold_chain_readiness": digest("cold-chain-adapter"),
            "channel_order_ingest": digest("channel-order-adapter"),
        },
        source_hashes={"oracle.py": digest("oracle-source")},
    )


def _candidate_detection(
    artifact: FormalArmCaseArtifact,
    *,
    legacy_synthetic: bool = False,
):
    manifest = _candidate_manifest()
    if legacy_synthetic:
        return derive_test_only_detection(
            manifest=manifest,
            legacy_synthetic=True,
            case_id=artifact.case_id,
            task_id=artifact.task_id,
            fault_id=artifact.fault_id,
            arm_id=artifact.arm_id,
            artifact_sha256=artifact.artifact_hash,
            signals={
                "claimed_success": True,
                "authoritative_state_changed": False,
            },
        )
    facts = derive_artifact_facts(artifact)
    projection = derive_detection_signal_projection(
        manifest=manifest,
        artifact=artifact,
        facts=facts,
    )
    return derive_test_only_detection(
        manifest=manifest,
        case_id=artifact.case_id,
        task_id=artifact.task_id,
        fault_id=artifact.fault_id,
        arm_id=artifact.arm_id,
        artifact_sha256=artifact.artifact_hash,
        projection=projection,
    )


def test_oracle_bound_outcome_has_no_caller_detection_boolean_parameters() -> None:
    artifact = _artifact()
    facts = derive_artifact_facts(artifact)
    detection = _candidate_detection(artifact)
    case = FormalCaseIdentity(
        phase="pilot",
        task_id=artifact.task_id,
        fault_id=artifact.fault_id,
        mutation_seed=1729,
        case_id=artifact.case_id,
    )

    parameters = inspect.signature(derive_oracle_bound_arm_case_outcome).parameters
    assert "detected" not in parameters
    assert "detection_expected" not in parameters

    outcome = derive_oracle_bound_arm_case_outcome(
        case=case,
        facts=facts,
        detection_record=detection,
        gold_status="fail",
        accept_allowed=False,
        safety_violation=False,
    )

    assert isinstance(outcome, OracleBoundArmCaseOutcome)
    assert outcome.artifact_facts is facts
    assert outcome.detection_record is detection
    assert outcome.detected is True
    assert outcome.detection_expected is True
    assert outcome.artifact_hash == artifact.artifact_hash


def test_projection_rejects_tamper_random_artifact_hash_and_legacy_binding() -> None:
    artifact = _artifact()
    facts = derive_artifact_facts(artifact)
    detection = _candidate_detection(artifact)
    case = FormalCaseIdentity(
        phase="pilot",
        task_id=artifact.task_id,
        fault_id=artifact.fault_id,
        mutation_seed=1729,
        case_id=artifact.case_id,
    )

    projection = detection.signal_projection_record
    assert isinstance(projection, DetectionSignalProjection)
    with pytest.raises(DetectionOracleError, match="projection hash"):
        replace(
            projection,
            signal_projection=(
                ("authoritative_state_changed", "true"),
                ("claimed_success", "true"),
            ),
        )
    with pytest.raises(DetectionOracleError, match="artifact hash"):
        derive_test_only_detection(
            manifest=_candidate_manifest(),
            case_id=artifact.case_id,
            task_id=artifact.task_id,
            fault_id=artifact.fault_id,
            arm_id=artifact.arm_id,
            artifact_sha256="f" * 64,
            projection=projection,
        )

    with pytest.raises(FormalRunnerError, match="artifact-derived projection"):
        derive_oracle_bound_arm_case_outcome(
            case=case,
            facts=facts,
            detection_record=_candidate_detection(
                artifact,
                legacy_synthetic=True,
            ),
            gold_status="fail",
            accept_allowed=False,
            safety_violation=False,
        )


def test_candidate_projection_is_bound_but_remains_ineligible_for_formal_metrics() -> (
    None
):
    artifact = _artifact()
    facts = derive_artifact_facts(artifact)
    detection = _candidate_detection(artifact)
    case = FormalCaseIdentity(
        phase="pilot",
        task_id=artifact.task_id,
        fault_id=artifact.fault_id,
        mutation_seed=1729,
        case_id=artifact.case_id,
    )
    outcome = derive_oracle_bound_arm_case_outcome(
        case=case,
        facts=facts,
        detection_record=detection,
        gold_status="fail",
        accept_allowed=False,
        safety_violation=False,
    )
    with pytest.raises(FormalMetricError, match="test-only|formal eligible"):
        compute_formal_oracle_bound_arm_metrics(
            formal_attack_manifest("pilot"),
            (outcome,),
            arm="evaluation_plane",
        )
