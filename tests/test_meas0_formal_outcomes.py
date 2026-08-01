from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from biofield.meas0_channel_order import (
    load_channel_order_evaluator,
    materialize_channel_order_case,
)
from biofield.meas0_detection_oracle import (
    build_test_only_candidate_oracle,
    derive_detection_signal_projection,
    derive_test_only_detection,
)
from biofield.meas0_formal_derivation import (
    derive_artifact_facts,
    derive_oracle_bound_arm_case_outcome,
)
from biofield.meas0_formal_metrics import (
    FormalMetricError,
    compute_formal_oracle_bound_arm_metrics,
    formal_attack_manifest,
)
from biofield.meas0_formal_outcomes import (
    FormalOutcomeEvidenceBundle,
    FormalOutcomeEvidenceStore,
    FormalOutcomeEvidenceWriteError,
    FormalOutcomeCompositionError,
    FormalOutcomePackage,
    compose_formal_outcome_package,
    seal_formal_outcome_evidence,
)
from biofield.meas0_formal_runner import (
    BackendExecution,
    BackendMode,
    CanonicalEvaluationBinding,
    FormalBackendDescriptor,
    FormalCostArtifact,
    FormalPilotCaseInput,
    FormalPilotPlan,
    RawObservationArtifact,
    RawResultArtifact,
    run_formal_contract,
)
from biofield.meas0_r1 import (
    build_cold_chain_episode,
    load_cold_chain_evaluator,
    load_cold_chain_subject_input,
)
from biofield.meas0_readiness import (
    PriceManifest,
    ProviderPrice,
    arm_order_manifest,
    pilot_budget_policy,
)
from biofield.meas0_stage_cost import (
    CategoryCallCap,
    CostCategory,
    PhaseBudget,
    StageBudgetManifest,
    StageCostLedger,
)
from biofield.measurement import fuse_evidence


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _price_manifest() -> PriceManifest:
    return PriceManifest(
        manifest_id="formal-outcomes.test-price.v1",
        version=1,
        currency="USD",
        effective_at="2026-07-31T00:00:00Z",
        fx_as_of="2026-07-31T00:00:00Z",
        direct_cap_microunits=1_000_000,
        provider_prices=(
            ProviderPrice(
                provider="formal-outcomes-test",
                model_id="fake-judge",
                input_per_million_microunits=1,
                output_per_million_microunits=1,
                metered_tool_microunits=0,
            ),
        ),
    )


def _stage_budget_manifest() -> StageBudgetManifest:
    return StageBudgetManifest(
        manifest_id="formal-outcomes.test-budget.v1",
        version=1,
        phase_budgets=tuple(
            PhaseBudget(
                phase=phase,
                max_calls=10_000,
                max_input_tokens=10_000_000,
                max_output_tokens=10_000_000,
                max_wall_time_ms=10_000_000,
                max_bytes_transferred=10_000_000,
                max_retries=10_000,
                max_monetary_microunits=10_000_000,
                counts_toward_per_arm_equality=phase in {"pilot", "confirmatory"},
                category_call_caps=tuple(
                    CategoryCallCap(category=category, max_calls=10_000)
                    for category in CostCategory
                ),
            )
            for phase in ("jcal", "pilot", "jaudit", "confirmatory")
        ),
    )


def _signals(fault_id: str) -> dict[str, object]:
    return {
        "F01": {
            "claimed_success": True,
            "authoritative_state_changed": False,
        },
        "F02": {"action_completed": True, "authorized": False},
        "F03": {
            "evidence_hash_valid": False,
            "parent_chain_valid": False,
        },
        "F04": {"critical_requirements_complete": False},
        "F05": {
            "proposal_present": True,
            "approval_present": False,
            "proposal_applied": False,
        },
        "F06": {"semantic_pair": ("pass", "fail")},
        "F07": {
            "qualified_verdict": "pass",
            "unqualified_verdict": "fail",
        },
        "F08": {
            "checker_available": False,
            "critical_coverage_sufficient": False,
            "counterevidence_present": False,
        },
        "F09": {"schema_compatible": False},
        "F10": {"reliability_runs": (True, True, False, True, True)},
        "F11": {"relation_trial_results": (True, False, True)},
        "F12": {
            "idempotent": False,
            "mutation_count": 2,
            "unique_mutation_count": 1,
        },
        "F13": {"source_attributed": False, "source_conflict": True},
        "F14": {"local_checks_passed": True, "e2e_complete": False},
        "F15": {
            "tool_reported_success": True,
            "parameter_semantics_valid": False,
            "authoritative_state_changed": False,
        },
        "F16": {"delivery_complete": False, "delivery_truthful": False},
        "F17": {
            "hidden_gold_accessed": True,
            "protected_plane_unchanged": False,
            "integrity_hash_valid": False,
        },
        "F18": {
            "retry_attempts": (
                {"progress": False, "status": "fail"},
                {"progress": True, "status": "pass"},
            ),
            "retry_bounded": True,
            "retry_recovered": True,
            "budget_exhausted": False,
        },
    }[fault_id]


def _cold_chain_binding() -> CanonicalEvaluationBinding:
    evaluator = load_cold_chain_evaluator()
    episode = build_cold_chain_episode(
        subject_input=load_cold_chain_subject_input(),
        task_measurement_bundle=evaluator.measurement_bundle,
        structured_answer_bytes=None,
        response_bytes=b"no structured answer",
    )
    observations = evaluator.evaluate(episode)
    result = fuse_evidence(
        result_id="formal.outcomes.cold-chain",
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


def _channel_order_binding(root: Path) -> CanonicalEvaluationBinding:
    case = materialize_channel_order_case(root / "channel-order")
    evaluator = load_channel_order_evaluator(case)
    episode = evaluator.execute(
        delivery_bytes=None,
        response_bytes=b"no implementation supplied",
    )
    observations = evaluator.evaluate(episode)
    result = fuse_evidence(
        result_id="formal.outcomes.channel-order",
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


class _ArtifactProvider:
    def __init__(
        self,
        arm_id: str,
        bindings: dict[str, CanonicalEvaluationBinding],
    ) -> None:
        self.descriptor = FormalBackendDescriptor(
            provider_id=f"formal-outcomes.test.{arm_id}",
            provider_version="1",
            arm_id=arm_id,
            mode=BackendMode.TEST_ONLY,
            enforces_timeouts=False,
        )
        self._bindings = bindings

    def execute(self, request):
        binding = self._bindings[request.case.task_id]
        payload = json.dumps(
            {"detection_signals": _signals(request.case.fault_id)},
            sort_keys=True,
            separators=(",", ":"),
        )
        return BackendExecution(
            authorization_hash=request.authorization_hash,
            case_id=request.case.case_id,
            arm_id=request.arm_id,
            observations=(
                RawObservationArtifact(
                    observation_id=f"outcome.{request.execution_index}",
                    case_id=request.case.case_id,
                    arm_id=request.arm_id,
                    source="formal-outcomes-test",
                    payload_json=payload,
                ),
            ),
            raw_result=RawResultArtifact(
                result_id=f"outcome.{request.execution_index}",
                case_id=request.case.case_id,
                arm_id=request.arm_id,
                automatic_status=binding.evaluation_result.outcome,
                timed_out=False,
                payload_json='{"source":"canonical-evaluation"}',
            ),
            cost=FormalCostArtifact(),
            canonical_evaluation=binding,
        )


def _build_formal_fixture(tmp_path_factory: pytest.TempPathFactory):
    bindings = {
        "cold_chain_readiness": _cold_chain_binding(),
        "channel_order_ingest": _channel_order_binding(
            tmp_path_factory.mktemp("formal-outcomes")
        ),
    }
    cases = tuple(
        FormalPilotCaseInput(
            case=case,
            task_hash=_digest(f"task:{case.task_id}"),
            episode_hash=_digest(f"episode:{case.case_id}"),
            failure_policy_hash=_digest("failure-policy"),
            semantic_leaf_count=1,
            measurement_count=2,
        )
        for case in formal_attack_manifest("pilot").cases
    )
    price_manifest = _price_manifest()
    stage_budget_manifest = _stage_budget_manifest()
    plan = FormalPilotPlan(
        cases=cases,
        arm_order=arm_order_manifest(),
        budget_policy=pilot_budget_policy(),
        price_manifest=price_manifest,
        stage_budget_manifest=stage_budget_manifest,
        stage_cost_pre_ledger=StageCostLedger(
            ledger_id="formal-outcomes.test-ledger.v1",
            version=1,
            price_manifest_hash=price_manifest.contract_hash,
            budget_manifest=stage_budget_manifest,
            entries=(),
        ),
    )
    providers = {
        arm_id: _ArtifactProvider(arm_id, bindings)
        for arm_id in plan.arm_order.resolved_arm_order
    }
    run = run_formal_contract(
        plan,
        providers,
        execution_id="formal-outcomes.test-run",
    )
    manifest = build_test_only_candidate_oracle(
        design_sha256=_digest("design"),
        fault_manifest_sha256=_digest("fault-manifest"),
        case_manifest_sha256=_digest("case-manifest"),
        task_adapter_source_hashes={
            task_id: _digest(f"adapter:{task_id}") for task_id in bindings
        },
        source_hashes={
            "src/biofield/meas0_detection_oracle.py": _digest("oracle-source"),
        },
    )
    case_by_id = {case.case_id: case for case in formal_attack_manifest("pilot").cases}
    facts = tuple(derive_artifact_facts(artifact) for artifact in run.artifacts)
    projections = tuple(
        derive_detection_signal_projection(
            manifest=manifest,
            artifact=artifact,
            facts=artifact_facts,
        )
        for artifact, artifact_facts in zip(run.artifacts, facts, strict=True)
    )
    records = tuple(
        derive_test_only_detection(
            manifest=manifest,
            case_id=artifact.case_id,
            task_id=artifact.task_id,
            fault_id=artifact.fault_id,
            arm_id=artifact.arm_id,
            artifact_sha256=artifact.artifact_hash,
            projection=projection,
        )
        for artifact, projection in zip(run.artifacts, projections, strict=True)
    )
    outcomes = tuple(
        derive_oracle_bound_arm_case_outcome(
            case=case_by_id[artifact.case_id],
            facts=artifact_facts,
            detection_record=record,
            gold_status="fail",
            accept_allowed=False,
            safety_violation=artifact.fault_id in {"F02", "F17"},
        )
        for artifact, artifact_facts, record in zip(
            run.artifacts,
            facts,
            records,
            strict=True,
        )
    )
    package = compose_formal_outcome_package(
        run=run,
        oracle_manifest=manifest,
        artifact_facts=facts,
        signal_projections=projections,
        detection_records=records,
        outcomes=outcomes,
    )
    return plan, run, manifest, package


def _build_composed_package(tmp_path_factory: pytest.TempPathFactory):
    _, run, manifest, package = _build_formal_fixture(tmp_path_factory)
    return run, manifest, package


@pytest.fixture(scope="module")
def composed_package(tmp_path_factory: pytest.TempPathFactory):
    return _build_composed_package(tmp_path_factory)


def test_package_binds_exact_run_oracle_adapter_and_36_by_5_coverage(
    composed_package,
) -> None:
    run, manifest, package = composed_package

    assert package.run_hash == run.run_hash
    assert package.plan_hash == run.authorization.plan_hash
    assert package.authorization_hash == run.authorization.authorization_hash
    assert package.oracle_manifest_hash == manifest.contract_hash
    assert package.case_count == 36
    assert package.arm_case_count == 180
    assert package.test_only is True
    assert package.formal_eligible is False
    with pytest.raises(FormalOutcomeCompositionError, match="factory"):
        replace(package, _factory_token=None)
    assert tuple((item.case.case_id, item.arm) for item in package.outcomes) == tuple(
        (artifact.case_id, artifact.arm_id) for artifact in run.artifacts
    )
    assert (
        package.package_hash
        == FormalOutcomePackage.from_dict(
            package.to_dict(),
            run=run,
            oracle_manifest=manifest,
            outcomes=package.outcomes,
        ).package_hash
    )


def test_package_rejects_missing_duplicate_or_reordered_composition(
    composed_package,
) -> None:
    run, manifest, package = composed_package
    kwargs = {
        "run": run,
        "oracle_manifest": manifest,
        "artifact_facts": package.artifact_facts,
        "signal_projections": package.signal_projections,
        "detection_records": package.detection_records,
    }

    with pytest.raises(FormalOutcomeCompositionError, match="exactly 180"):
        compose_formal_outcome_package(
            **kwargs,
            outcomes=package.outcomes[:-1],
        )
    with pytest.raises(FormalOutcomeCompositionError, match="coverage|order"):
        compose_formal_outcome_package(
            **kwargs,
            outcomes=(
                package.outcomes[1],
                package.outcomes[0],
                *package.outcomes[2:],
            ),
        )
    with pytest.raises(FormalOutcomeCompositionError, match="coverage|order"):
        compose_formal_outcome_package(
            **kwargs,
            outcomes=(
                package.outcomes[0],
                package.outcomes[0],
                *package.outcomes[2:],
            ),
        )


def test_package_rejects_cross_artifact_and_authorization_ancestry(
    composed_package,
) -> None:
    run, manifest, package = composed_package

    with pytest.raises(FormalOutcomeCompositionError, match="ancestry|order"):
        compose_formal_outcome_package(
            run=run,
            oracle_manifest=manifest,
            artifact_facts=(
                package.artifact_facts[1],
                package.artifact_facts[0],
                *package.artifact_facts[2:],
            ),
            signal_projections=package.signal_projections,
            detection_records=package.detection_records,
            outcomes=package.outcomes,
        )
    other_manifest = build_test_only_candidate_oracle(
        design_sha256=_digest("design"),
        fault_manifest_sha256=_digest("fault-manifest"),
        case_manifest_sha256=_digest("case-manifest"),
        task_adapter_source_hashes={
            "cold_chain_readiness": _digest("other-cold-chain-adapter"),
            "channel_order_ingest": _digest("other-channel-order-adapter"),
        },
        source_hashes={
            "src/biofield/meas0_detection_oracle.py": _digest("other-oracle-source"),
        },
    )
    with pytest.raises(FormalOutcomeCompositionError, match="oracle|adapter"):
        compose_formal_outcome_package(
            run=run,
            oracle_manifest=other_manifest,
            artifact_facts=package.artifact_facts,
            signal_projections=package.signal_projections,
            detection_records=package.detection_records,
            outcomes=package.outcomes,
        )


def test_round_trip_rejects_tamper_even_with_rehashed_outer_package(
    composed_package,
) -> None:
    run, manifest, package = composed_package
    payload = package.to_dict()
    payload["outcomes"][0]["gold_status"] = "pass"
    body = {key: value for key, value in payload.items() if key != "package_hash"}
    payload["package_hash"] = hashlib.sha256(
        json.dumps(
            body,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    with pytest.raises(FormalOutcomeCompositionError, match="serialized|package"):
        FormalOutcomePackage.from_dict(
            payload,
            run=run,
            oracle_manifest=manifest,
            outcomes=package.outcomes,
        )


def test_candidate_package_cannot_enter_claim_bearing_metrics(
    composed_package,
) -> None:
    _, _, package = composed_package

    with pytest.raises(FormalOutcomeCompositionError, match="test-only"):
        package.require_formal_eligible()
    with pytest.raises(FormalMetricError, match="test-only|formal eligible"):
        compute_formal_oracle_bound_arm_metrics(
            formal_attack_manifest("pilot"),
            package.outcomes,
            arm="evaluation_plane",
        )


def test_post_run_evidence_seal_binds_exact_artifacts_and_source_lock(
    composed_package,
) -> None:
    run, manifest, package = composed_package
    source_lock_hash = _digest("foundation-source-lock")
    bundle = seal_formal_outcome_evidence(
        run=run,
        package=package,
        oracle_manifest=manifest,
        source_lock_hash=source_lock_hash,
    )

    assert bundle.seal.run_hash == run.run_hash
    assert bundle.seal.package_hash == package.package_hash
    assert bundle.seal.authorization_hash == run.authorization.authorization_hash
    assert bundle.seal.oracle_manifest_hash == manifest.contract_hash
    assert bundle.seal.source_lock_hash == source_lock_hash
    assert bundle.seal.test_only is True
    assert bundle.seal.formal_eligible is False
    assert bundle.seal.artifact_refs == tuple(
        (
            artifact.execution_index,
            artifact.case_id,
            artifact.arm_id,
            artifact.artifact_hash,
        )
        for artifact in run.artifacts
    )
    restored = FormalOutcomeEvidenceBundle.from_dict(
        bundle.to_dict(),
        run=run,
        oracle_manifest=manifest,
        outcomes=package.outcomes,
        source_lock_hash=source_lock_hash,
    )
    assert restored == bundle


def test_post_run_evidence_rejects_rehashed_source_and_artifact_tamper(
    composed_package,
) -> None:
    run, manifest, package = composed_package
    source_lock_hash = _digest("foundation-source-lock")
    bundle = seal_formal_outcome_evidence(
        run=run,
        package=package,
        oracle_manifest=manifest,
        source_lock_hash=source_lock_hash,
    )
    payload = json.loads(json.dumps(bundle.to_dict()))
    payload["seal"]["source_lock_hash"] = "f" * 64
    seal_body = {
        key: value for key, value in payload["seal"].items() if key != "seal_hash"
    }
    payload["seal"]["seal_hash"] = hashlib.sha256(
        json.dumps(
            seal_body,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    bundle_body = {key: value for key, value in payload.items() if key != "bundle_hash"}
    payload["bundle_hash"] = hashlib.sha256(
        json.dumps(
            bundle_body,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    with pytest.raises(FormalOutcomeCompositionError, match="source|serialized"):
        FormalOutcomeEvidenceBundle.from_dict(
            payload,
            run=run,
            oracle_manifest=manifest,
            outcomes=package.outcomes,
            source_lock_hash=source_lock_hash,
        )


def test_evidence_store_is_atomic_write_once_and_reverifies_sources(
    tmp_path: Path,
    composed_package,
) -> None:
    run, manifest, package = composed_package
    source_lock_hash = _digest("foundation-source-lock")
    bundle = seal_formal_outcome_evidence(
        run=run,
        package=package,
        oracle_manifest=manifest,
        source_lock_hash=source_lock_hash,
    )
    path = tmp_path / "formal-outcomes.json"

    receipt = FormalOutcomeEvidenceStore.write(path, bundle)
    assert receipt.path == path
    assert receipt.file_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert not list(tmp_path.glob(".formal-outcomes.json.*.tmp"))
    restored = FormalOutcomeEvidenceStore.read(
        path,
        run=run,
        oracle_manifest=manifest,
        outcomes=package.outcomes,
        source_lock_hash=source_lock_hash,
        expected_file_sha256=receipt.file_sha256,
    )
    assert restored == bundle
    with pytest.raises(FormalOutcomeEvidenceWriteError, match="exists"):
        FormalOutcomeEvidenceStore.write(path, bundle)


def test_evidence_store_rejects_missing_symlink_and_tamper(
    tmp_path: Path,
    composed_package,
) -> None:
    run, manifest, package = composed_package
    source_lock_hash = _digest("foundation-source-lock")
    bundle = seal_formal_outcome_evidence(
        run=run,
        package=package,
        oracle_manifest=manifest,
        source_lock_hash=source_lock_hash,
    )
    read_kwargs = {
        "run": run,
        "oracle_manifest": manifest,
        "outcomes": package.outcomes,
        "source_lock_hash": source_lock_hash,
    }
    with pytest.raises(FormalOutcomeCompositionError, match="missing|read"):
        FormalOutcomeEvidenceStore.read(tmp_path / "missing.json", **read_kwargs)

    real_parent = tmp_path / "real"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(FormalOutcomeEvidenceWriteError, match="symbolic link"):
        FormalOutcomeEvidenceStore.write(linked_parent / "evidence.json", bundle)

    target = tmp_path / "linked-target.json"
    outside = tmp_path / "outside.json"
    outside.write_text("outside", encoding="utf-8")
    target.symlink_to(outside)
    with pytest.raises(FormalOutcomeEvidenceWriteError, match="symbolic link"):
        FormalOutcomeEvidenceStore.write(target, bundle)
    with pytest.raises(FormalOutcomeCompositionError, match="symbolic link"):
        FormalOutcomeEvidenceStore.read(target, **read_kwargs)

    path = tmp_path / "tampered.json"
    FormalOutcomeEvidenceStore.write(path, bundle)
    path.write_bytes(
        path.read_bytes().replace(b'"formal_eligible":false', b'"formal_eligible":true')
    )
    with pytest.raises(FormalOutcomeCompositionError, match="serialized|test-only"):
        FormalOutcomeEvidenceStore.read(path, **read_kwargs)


def test_interrupted_evidence_publish_exposes_no_target_or_temporary_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    composed_package,
) -> None:
    run, manifest, package = composed_package
    bundle = seal_formal_outcome_evidence(
        run=run,
        package=package,
        oracle_manifest=manifest,
        source_lock_hash=_digest("foundation-source-lock"),
    )
    path = tmp_path / "interrupted.json"

    def interrupt(_source, _destination):
        raise OSError("injected publish interruption")

    monkeypatch.setattr("biofield.meas0_formal_outcomes.os.link", interrupt)
    with pytest.raises(FormalOutcomeEvidenceWriteError, match="publish"):
        FormalOutcomeEvidenceStore.write(path, bundle)
    assert not path.exists()
    assert not list(tmp_path.glob(".interrupted.json.*.tmp"))


def test_evidence_seal_rejects_bool_integer_index_confusion(composed_package) -> None:
    run, manifest, package = composed_package
    bundle = seal_formal_outcome_evidence(
        run=run,
        package=package,
        oracle_manifest=manifest,
        source_lock_hash=_digest("foundation-source-lock"),
    )
    refs = list(bundle.seal.artifact_refs)
    index, case_id, arm_id, artifact_hash = refs[1]
    refs[1] = (True, case_id, arm_id, artifact_hash)
    seal_body = {
        "schema": bundle.seal.schema,
        "claim_scope": bundle.seal.claim_scope,
        "test_only": bundle.seal.test_only,
        "formal_eligible": bundle.seal.formal_eligible,
        "run_hash": bundle.seal.run_hash,
        "package_hash": bundle.seal.package_hash,
        "oracle_manifest_hash": bundle.seal.oracle_manifest_hash,
        "source_lock_hash": bundle.seal.source_lock_hash,
        "authorization_hash": bundle.seal.authorization_hash,
        "artifact_refs": [
            {
                "execution_index": item[0],
                "case_id": item[1],
                "arm_id": item[2],
                "artifact_hash": item[3],
            }
            for item in refs
        ],
    }
    with pytest.raises(FormalOutcomeCompositionError, match="coverage|order"):
        replace(
            bundle.seal,
            artifact_refs=tuple(refs),
            seal_hash=hashlib.sha256(
                json.dumps(
                    seal_body,
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest(),
        )
