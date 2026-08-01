from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import replace

import pytest

from biofield.meas0 import Meas0Arm
from biofield.meas0_authoritative_measurands_v3 import (
    AuthoritativeMeasurandV3Error,
    MeasurandAvailabilityV3,
    RawDetectionSignalsAuditV3,
    SimulatedAuthoritativeMeasurandProjectionV3,
    SimulatedFrozenOracleBindingV3,
    capture_raw_detection_signals_audit,
    derive_simulated_authoritative_measurands,
)
from biofield.meas0_budget import (
    BudgetFailureArtifact,
    BudgetFailureCode,
    BudgetScope,
)
from biofield.meas0_detection_oracle import build_test_only_candidate_oracle
from biofield.meas0_failure_evidence_v3 import BudgetExhaustedEvidenceV3
from biofield.meas0_formal_metrics import formal_attack_manifest
from biofield.meas0_formal_runner import (
    CLAIM_SCOPE,
    CanonicalEvaluationBinding,
    FailureCode,
    FormalArmCaseArtifact,
    FormalArmRequest,
    FormalCostArtifact,
    FormalFailureArtifact,
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


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _oracle():
    return build_test_only_candidate_oracle(
        design_sha256=_hash("design"),
        fault_manifest_sha256=_hash("faults"),
        case_manifest_sha256=_hash("cases"),
        task_adapter_source_hashes={
            "cold_chain_readiness": _hash("cold-chain-adapter"),
            "channel_order_ingest": _hash("channel-order-adapter"),
        },
        source_hashes={"oracle.py": _hash("oracle-source")},
    )


def _binding() -> CanonicalEvaluationBinding:
    evaluator = load_cold_chain_evaluator()
    episode = build_cold_chain_episode(
        subject_input=load_cold_chain_subject_input(),
        task_measurement_bundle=evaluator.measurement_bundle,
        structured_answer_bytes=None,
        response_bytes=b"no structured answer",
    )
    observations = evaluator.evaluate(episode)
    result = fuse_evidence(
        result_id="d11.authority.test",
        task_measurement_bundle=evaluator.measurement_bundle,
        sealed_episode=episode.sealed_episode,
        observations=observations,
    )
    return CanonicalEvaluationBinding(
        task_measurement_bundle=evaluator.measurement_bundle,
        sealed_episode=episode.sealed_episode,
        observations=observations,
        evaluation_result=result,
    )


def _raw_signals(fault_id: str, value: bool = True) -> dict[str, object]:
    fields = _oracle().entry(fault_id).authorized_signal_fields
    return {field: value for field in fields}


def _sources(
    fault_id: str,
    *,
    raw_signals: dict[str, object] | None = None,
    terminal_reason: str | None = None,
    include_canonical: bool = True,
):
    binding = _binding()
    case = next(
        item
        for item in formal_attack_manifest("pilot").cases
        if item.task_id == "cold_chain_readiness" and item.fault_id == fault_id
    )
    request = FormalArmRequest(
        authorization_hash=_hash("d11-authorization"),
        execution_index=0,
        case=case,
        arm_id="evaluation_plane",
        task_hash=binding.task_measurement_bundle.bundle_hash,
        episode_hash=binding.sealed_episode.episode_hash,
        failure_policy_hash=_hash("failure-policy"),
        semantic_leaf_count=0,
        measurement_count=len(
            binding.task_measurement_bundle.measurement_graph.measurement_specs
        ),
        budget_policy_hash=_hash("budget-policy"),
        price_manifest_hash=_hash("price-manifest"),
        stage_budget_manifest_hash=_hash("stage-budget"),
        stage_cost_pre_ledger_hash=_hash("stage-ledger"),
    )
    payload = json.dumps(
        {"detection_signals": raw_signals or _raw_signals(fault_id)},
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    failure = None
    failure_evidence = None
    validity = ResultValidity.VALID
    automatic_status = binding.evaluation_result.outcome
    if terminal_reason is not None:
        failure = FormalFailureArtifact(
            code=FailureCode.BUDGET_EXHAUSTED,
            message=terminal_reason,
        )
        automatic_status = EvaluationStatus.UNKNOWN
        budget_failure = BudgetFailureArtifact(
            case_id=case.case_id,
            task_id=case.task_id,
            arm=Meas0Arm(request.arm_id),
            code=BudgetFailureCode.BUDGET_EXHAUSTED,
            scope=BudgetScope.ARM_CASE,
            metric="judge_calls",
            limit=2,
            observed=3,
        )
        failure_evidence = BudgetExhaustedEvidenceV3.create(
            request=request,
            failure=failure,
            budget_failure=budget_failure,
        )
    raw_result = RawResultArtifact(
        result_id=f"d11.{fault_id}",
        case_id=case.case_id,
        arm_id=request.arm_id,
        automatic_status=binding.evaluation_result.outcome,
        timed_out=False,
        payload_json='{"backend":"test-only"}',
    )
    observation = RawObservationArtifact(
        observation_id=f"d11.{fault_id}",
        case_id=case.case_id,
        arm_id=request.arm_id,
        source="pytest-backend",
        payload_json=payload,
    )
    artifact = FormalArmCaseArtifact(
        authorization_hash=request.authorization_hash,
        request_hash=request.request_hash,
        execution_index=request.execution_index,
        case_id=case.case_id,
        task_id=case.task_id,
        fault_id=case.fault_id,
        arm_id=request.arm_id,
        backend_id="pytest-backend",
        claim_scope=CLAIM_SCOPE,
        result_validity=validity,
        automatic_status=automatic_status,
        observations=(observation,),
        raw_result=raw_result if include_canonical or failure is None else None,
        cost=FormalCostArtifact(),
        judge_call_costs=(),
        stage_cost_entry_hashes=(),
        failure=failure,
        canonical_evaluation=binding if include_canonical else None,
    )
    oracle_binding = SimulatedFrozenOracleBindingV3.create(
        request=request,
        oracle=_oracle(),
    )
    return request, artifact, oracle_binding, failure_evidence


def _measurands(
    projection: SimulatedAuthoritativeMeasurandProjectionV3,
) -> dict[str, object]:
    return {item.name: item for item in projection.measurands}


def test_authoritative_factory_excludes_raw_and_terminal_inputs() -> None:
    parameters = inspect.signature(derive_simulated_authoritative_measurands).parameters
    assert tuple(parameters) == (
        "request",
        "artifact",
        "oracle_binding",
        "failure_evidence",
    )
    assert {
        "signals",
        "detection_signals",
        "detected",
        "terminal_reason",
    }.isdisjoint(parameters)


def test_structure_projection_derives_only_independently_closed_measurands() -> None:
    request, artifact, oracle, failure_evidence = _sources("F03")
    projection = derive_simulated_authoritative_measurands(
        request=request,
        artifact=artifact,
        oracle_binding=oracle,
        failure_evidence=failure_evidence,
    )

    facts = {item.name: item for item in projection.structure_facts}
    assert facts["request_artifact_ancestry_valid"].value is True
    assert facts["canonical_measurement_binding_valid"].value is True
    assert facts["sealed_episode_parent_structure_valid"].value is True
    assert facts["failure_evidence_integrity_valid"].availability is (
        MeasurandAvailabilityV3.UNAVAILABLE
    )

    measurands = _measurands(projection)
    assert measurands["parent_chain_valid"].availability is (
        MeasurandAvailabilityV3.UNAVAILABLE
    )
    assert measurands["parent_chain_valid"].value is None
    assert measurands["evidence_hash_valid"].availability is (
        MeasurandAvailabilityV3.UNAVAILABLE
    )
    assert measurands["evidence_hash_valid"].value is None
    assert tuple(measurands) == oracle.oracle.entry("F03").authorized_signal_fields
    assert projection.claim_scope == "simulated_nonclaim"
    assert projection.test_only is True
    assert projection.production_authorized is False
    assert projection.formal_eligible is False
    assert projection.detection_eligible is False


def test_judge_transport_membership_authority_is_explicitly_unavailable() -> None:
    request, artifact, oracle, failure_evidence = _sources("F03")
    projection = derive_simulated_authoritative_measurands(
        request=request,
        artifact=artifact,
        oracle_binding=oracle,
        failure_evidence=failure_evidence,
    )

    facts = {item.name: item for item in projection.structure_facts}
    fact = facts["judge_transport_membership_authority_valid"]
    assert fact.availability is MeasurandAvailabilityV3.UNAVAILABLE
    assert fact.value is None
    assert fact.source_kind is None
    assert fact.source_hashes == ()
    assert fact.evidence_refs == ()


def test_legacy_formal_detection_authority_is_explicitly_unavailable() -> None:
    request, artifact, oracle, failure_evidence = _sources("F03")
    projection = derive_simulated_authoritative_measurands(
        request=request,
        artifact=artifact,
        oracle_binding=oracle,
        failure_evidence=failure_evidence,
    )

    facts = {item.name: item for item in projection.structure_facts}
    fact = facts["legacy_formal_detection_authority_valid"]
    assert fact.availability is MeasurandAvailabilityV3.UNAVAILABLE
    assert fact.value is None
    assert fact.source_kind is None
    assert fact.source_hashes == ()
    assert fact.evidence_refs == ()
    # The D11 package carries no legacy signal projection or detection record.
    assert "signal_projection" not in projection.to_dict()
    assert "detection_record" not in projection.to_dict()


def test_artifact_denominator_retention_is_explicitly_typed() -> None:
    request, artifact, oracle, failure_evidence = _sources("F03")
    projection = derive_simulated_authoritative_measurands(
        request=request,
        artifact=artifact,
        oracle_binding=oracle,
        failure_evidence=failure_evidence,
    )

    facts = {item.name: item for item in projection.structure_facts}
    fact = facts["artifact_denominator_retained"]
    assert fact.availability is MeasurandAvailabilityV3.DERIVED
    assert fact.value is True
    assert fact.source_kind == "typed_formal_artifact_denominator"
    assert fact.source_hashes == (artifact.artifact_hash,)
    assert fact.evidence_refs == ("formal_arm_case_artifact.retained_in_denominator",)


def test_internal_schema_consistency_does_not_claim_oracle_compatibility() -> None:
    request, artifact, oracle, failure_evidence = _sources("F09")
    projection = derive_simulated_authoritative_measurands(
        request=request,
        artifact=artifact,
        oracle_binding=oracle,
        failure_evidence=failure_evidence,
    )
    fact = _measurands(projection)["schema_compatible"]
    assert fact.availability is MeasurandAvailabilityV3.UNAVAILABLE
    assert fact.value is None
    structure = {item.name: item for item in projection.structure_facts}
    assert structure["internal_measurement_contract_consistent"].value is True

    request, artifact, oracle, failure_evidence = _sources("F01")
    unavailable = derive_simulated_authoritative_measurands(
        request=request,
        artifact=artifact,
        oracle_binding=oracle,
        failure_evidence=failure_evidence,
    )
    assert all(
        item.availability is MeasurandAvailabilityV3.UNAVAILABLE and item.value is None
        for item in unavailable.measurands
    )


def test_raw_all_true_or_false_changes_only_audit_not_authoritative_values() -> None:
    sources_true = _sources("F01", raw_signals=_raw_signals("F01", True))
    sources_false = _sources("F01", raw_signals=_raw_signals("F01", False))
    true_projection = derive_simulated_authoritative_measurands(
        request=sources_true[0],
        artifact=sources_true[1],
        oracle_binding=sources_true[2],
    )
    false_projection = derive_simulated_authoritative_measurands(
        request=sources_false[0],
        artifact=sources_false[1],
        oracle_binding=sources_false[2],
    )
    assert true_projection.measurands == false_projection.measurands
    assert tuple(
        (item.name, item.availability, item.value)
        for item in true_projection.structure_facts
    ) == tuple(
        (item.name, item.availability, item.value)
        for item in false_projection.structure_facts
    )

    true_audit = capture_raw_detection_signals_audit(
        artifact=sources_true[1],
        oracle_binding=sources_true[2],
    )
    false_audit = capture_raw_detection_signals_audit(
        artifact=sources_false[1],
        oracle_binding=sources_false[2],
    )
    assert true_audit.raw_projection != false_audit.raw_projection
    for audit in (true_audit, false_audit):
        assert audit.audit_only is True
        assert audit.authoritative is False
        assert audit.detection_eligible is False
        assert audit.formal_eligible is False
        assert audit.claim_scope == "simulated_nonclaim"


def test_raw_audit_type_cannot_enter_authoritative_projection() -> None:
    request, artifact, oracle, _ = _sources("F03")
    audit = capture_raw_detection_signals_audit(
        artifact=artifact,
        oracle_binding=oracle,
    )
    assert isinstance(audit, RawDetectionSignalsAuditV3)
    restored = RawDetectionSignalsAuditV3.restore_from_typed_sources(
        audit.to_dict(),
        artifact=artifact,
        oracle_binding=oracle,
    )
    assert restored == audit
    with pytest.raises(
        AuthoritativeMeasurandV3Error,
        match="audit-only boundary",
    ):
        replace(audit, authoritative=True)
    with pytest.raises(
        AuthoritativeMeasurandV3Error,
        match="typed failure evidence",
    ):
        derive_simulated_authoritative_measurands(
            request=request,
            artifact=artifact,
            oracle_binding=oracle,
            failure_evidence=audit,  # type: ignore[arg-type]
        )


def test_projection_canonical_bytes_round_trip_requires_typed_sources() -> None:
    request, artifact, oracle, failure_evidence = _sources("F09")
    projection = derive_simulated_authoritative_measurands(
        request=request,
        artifact=artifact,
        oracle_binding=oracle,
        failure_evidence=failure_evidence,
    )
    raw = projection.to_canonical_bytes()
    assert raw == json.dumps(
        projection.to_dict(),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    restored = SimulatedAuthoritativeMeasurandProjectionV3.restore_from_canonical_bytes(
        raw,
        request=request,
        artifact=artifact,
        oracle_binding=oracle,
        failure_evidence=failure_evidence,
    )
    assert restored == projection

    with pytest.raises(AuthoritativeMeasurandV3Error, match="canonical"):
        SimulatedAuthoritativeMeasurandProjectionV3.restore_from_canonical_bytes(
            raw + b"\n",
            request=request,
            artifact=artifact,
            oracle_binding=oracle,
            failure_evidence=failure_evidence,
        )

    duplicate = b'{"schema":"x","schema":"y"}'
    with pytest.raises(AuthoritativeMeasurandV3Error, match="duplicate"):
        SimulatedAuthoritativeMeasurandProjectionV3.restore_from_canonical_bytes(
            duplicate,
            request=request,
            artifact=artifact,
            oracle_binding=oracle,
            failure_evidence=failure_evidence,
        )

    with pytest.raises(AuthoritativeMeasurandV3Error, match="typed-source"):
        other_oracle = build_test_only_candidate_oracle(
            design_sha256=_hash("other-design"),
            fault_manifest_sha256=_hash("faults"),
            case_manifest_sha256=_hash("cases"),
            task_adapter_source_hashes={
                "cold_chain_readiness": _hash("cold-chain-adapter"),
                "channel_order_ingest": _hash("channel-order-adapter"),
            },
            source_hashes={"oracle.py": _hash("oracle-source")},
        )
        other = SimulatedFrozenOracleBindingV3.create(
            request=request,
            oracle=other_oracle,
        )
        SimulatedAuthoritativeMeasurandProjectionV3.restore_from_canonical_bytes(
            raw,
            request=request,
            artifact=artifact,
            oracle_binding=other,
            failure_evidence=failure_evidence,
        )


def test_raw_detection_audit_canonical_bytes_round_trip_is_audit_only() -> None:
    _, artifact, oracle, _ = _sources("F03")
    audit = capture_raw_detection_signals_audit(
        artifact=artifact,
        oracle_binding=oracle,
    )
    raw = audit.to_canonical_bytes()
    restored = RawDetectionSignalsAuditV3.restore_from_canonical_bytes(
        raw,
        artifact=artifact,
        oracle_binding=oracle,
    )
    assert restored == audit
    assert restored.audit_only is True
    assert restored.authoritative is False
    with pytest.raises(AuthoritativeMeasurandV3Error, match="canonical"):
        RawDetectionSignalsAuditV3.restore_from_canonical_bytes(
            b" " + raw,
            artifact=artifact,
            oracle_binding=oracle,
        )


def test_terminal_reason_never_becomes_detection_or_a_measurand() -> None:
    first = _sources(
        "F18",
        terminal_reason="F18 detected: retry loop exhausted",
    )
    second = _sources(
        "F18",
        terminal_reason="hidden gold accessed and schema invalid",
    )
    projections = [
        derive_simulated_authoritative_measurands(
            request=request,
            artifact=artifact,
            oracle_binding=oracle,
            failure_evidence=failure_evidence,
        )
        for request, artifact, oracle, failure_evidence in (first, second)
    ]
    for projection in projections:
        measurands = _measurands(projection)
        assert measurands["budget_exhausted"].value is True
        assert measurands["budget_exhausted"].availability is (
            MeasurandAvailabilityV3.DERIVED
        )
        assert all("terminal" not in item.name for item in projection.measurands)
        assert "detected" not in projection.to_dict()
    assert tuple(
        (item.name, item.availability, item.value) for item in projections[0].measurands
    ) == tuple(
        (item.name, item.availability, item.value) for item in projections[1].measurands
    )


def test_cross_request_task_case_and_oracle_substitution_fail_closed() -> None:
    request, artifact, oracle, failure_evidence = _sources("F09")
    with pytest.raises(AuthoritativeMeasurandV3Error, match="ancestry"):
        derive_simulated_authoritative_measurands(
            request=replace(request, authorization_hash=_hash("other-auth")),
            artifact=artifact,
            oracle_binding=oracle,
            failure_evidence=failure_evidence,
        )
    with pytest.raises(
        AuthoritativeMeasurandV3Error,
        match="binding|canonical",
    ):
        derive_simulated_authoritative_measurands(
            request=replace(request, task_hash=_hash("other-task")),
            artifact=replace(
                artifact,
                request_hash=replace(
                    request,
                    task_hash=_hash("other-task"),
                ).request_hash,
            ),
            oracle_binding=oracle,
            failure_evidence=failure_evidence,
        )
    with pytest.raises(AuthoritativeMeasurandV3Error, match="identity"):
        other_case = next(
            item
            for item in formal_attack_manifest("pilot").cases
            if item.task_id == request.case.task_id and item.fault_id == "F08"
        )
        derive_simulated_authoritative_measurands(
            request=replace(request, case=other_case),
            artifact=artifact,
            oracle_binding=oracle,
            failure_evidence=failure_evidence,
        )

    projection = derive_simulated_authoritative_measurands(
        request=request,
        artifact=artifact,
        oracle_binding=oracle,
        failure_evidence=failure_evidence,
    )
    other_oracle = build_test_only_candidate_oracle(
        design_sha256=_hash("other-design"),
        fault_manifest_sha256=_hash("faults"),
        case_manifest_sha256=_hash("cases"),
        task_adapter_source_hashes={
            "cold_chain_readiness": _hash("cold-chain-adapter"),
            "channel_order_ingest": _hash("channel-order-adapter"),
        },
        source_hashes={"oracle.py": _hash("oracle-source")},
    )
    other_binding = SimulatedFrozenOracleBindingV3.create(
        request=request,
        oracle=other_oracle,
    )
    with pytest.raises(AuthoritativeMeasurandV3Error, match="typed-source"):
        SimulatedAuthoritativeMeasurandProjectionV3.restore_from_typed_sources(
            projection.to_dict(),
            request=request,
            artifact=artifact,
            oracle_binding=other_binding,
            failure_evidence=failure_evidence,
        )
    with pytest.raises(AuthoritativeMeasurandV3Error, match="oracle binding"):
        replace(
            oracle,
            oracle_manifest_hash=other_oracle.contract_hash,
        )


def test_strict_restore_rejects_replace_and_rehash() -> None:
    request, artifact, oracle, failure_evidence = _sources("F09")
    projection = derive_simulated_authoritative_measurands(
        request=request,
        artifact=artifact,
        oracle_binding=oracle,
        failure_evidence=failure_evidence,
    )
    restored = SimulatedAuthoritativeMeasurandProjectionV3.restore_from_typed_sources(
        projection.to_dict(),
        request=request,
        artifact=artifact,
        oracle_binding=oracle,
        failure_evidence=failure_evidence,
    )
    assert restored == projection

    forged = projection.to_dict()
    forged["measurands"][0]["value"] = False
    body = {key: value for key, value in forged.items() if key != "projection_hash"}
    forged["projection_hash"] = hashlib.sha256(
        json.dumps(
            body,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    with pytest.raises(AuthoritativeMeasurandV3Error, match="typed-source"):
        SimulatedAuthoritativeMeasurandProjectionV3.restore_from_typed_sources(
            forged,
            request=request,
            artifact=artifact,
            oracle_binding=oracle,
            failure_evidence=failure_evidence,
        )

    type_forged = projection.to_dict()
    type_forged["version"] = True
    type_body = {
        key: value for key, value in type_forged.items() if key != "projection_hash"
    }
    type_forged["projection_hash"] = hashlib.sha256(
        json.dumps(
            type_body,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    with pytest.raises(AuthoritativeMeasurandV3Error, match="typed-source"):
        SimulatedAuthoritativeMeasurandProjectionV3.restore_from_typed_sources(
            type_forged,
            request=request,
            artifact=artifact,
            oracle_binding=oracle,
            failure_evidence=failure_evidence,
        )


def test_failure_integrity_does_not_require_canonical_measurement_binding() -> None:
    request, artifact, oracle, failure_evidence = _sources(
        "F18",
        terminal_reason="budget evidence only; not detection",
        include_canonical=False,
    )
    projection = derive_simulated_authoritative_measurands(
        request=request,
        artifact=artifact,
        oracle_binding=oracle,
        failure_evidence=failure_evidence,
    )
    structure = {item.name: item for item in projection.structure_facts}
    assert structure["canonical_measurement_binding_valid"].availability is (
        MeasurandAvailabilityV3.UNAVAILABLE
    )
    assert structure["internal_measurement_contract_consistent"].availability is (
        MeasurandAvailabilityV3.UNAVAILABLE
    )
    assert structure["sealed_episode_parent_structure_valid"].availability is (
        MeasurandAvailabilityV3.UNAVAILABLE
    )
    assert structure["failure_evidence_integrity_valid"].value is True
    budget = _measurands(projection)["budget_exhausted"]
    assert budget.availability is MeasurandAvailabilityV3.DERIVED
    assert budget.value is True
