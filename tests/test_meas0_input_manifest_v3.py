from __future__ import annotations

import inspect
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
    EvaluationStatus,
    seal_episode_graph,
    seal_task_measurement_bundle,
)
from biofield.meas0_formal_metrics import FormalCaseIdentity, formal_attack_manifest
from biofield.meas0_formal_lifecycle import (
    PhaseCheckpointTarget,
    authorize_simulated_phase_checkpoint,
)
from biofield.meas0_formal_runner import FailureCode, ResultValidity
from biofield.meas0_input_manifest import (
    FailurePolicyContract,
    InputManifest,
    InputManifestError,
    NativeAdapterArtifact,
    ProtectedCaseInput,
    ProtectedInputCorpus,
)
from biofield.meas0_phase_readiness import (
    PhaseCompletionDisposition,
    PhaseReadinessReceipt,
    create_simulated_phase_readiness_receipt,
    record_simulated_phase_completion,
)
from biofield.meas0_readiness import (
    FormalCaseIdentity as ReadinessCaseIdentity,
)
from biofield.meas0_readiness import FormalCaseScopeManifest
from biofield.meas0_trust import (
    AuthorizationCheckpoint,
    TrustDomain,
    TrustVerificationMode,
    VerificationResult,
)


def _hash(character: str) -> str:
    return character * 64


def _checkpoint_bindings(
    checkpoint: AuthorizationCheckpoint,
    *,
    pilot_input_manifest: str = "9" * 64,
) -> dict[str, str]:
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
    }[checkpoint]
    result = {name: f"{index + 1:064x}" for index, name in enumerate(names)}
    if checkpoint is AuthorizationCheckpoint.PILOT_START:
        result["pilot_input_manifest"] = pilot_input_manifest
    return result


def _authorization(
    target: PhaseCheckpointTarget,
    *,
    policy_hash: str = "8" * 64,
):
    verification = VerificationResult(
        schema_version=1,
        verified=True,
        production_authorized=False,
        claim_scope="contract_only",
        mode=TrustVerificationMode.TEST_ONLY_CONTRACT,
        trust_domain=TrustDomain.HUMAN_APPROVAL,
        policy_hash=policy_hash,
        root_manifest_hash=_hash("9"),
        payload_hash=target.target_hash,
        envelope_hash=_hash("7"),
        blockers=(),
    )
    return authorize_simulated_phase_checkpoint(
        target=target,
        verification=verification,
    )


def _pre_jcal_receipt(
    *,
    comparison_block_id: str = "pytest.meas0.block.v3",
    source_lock_hash: str = "b" * 64,
    common_ancestry_hash: str = "c" * 64,
    verification_policy_hash: str = "8" * 64,
) -> PhaseReadinessReceipt:
    target = PhaseCheckpointTarget.create(
        checkpoint=AuthorizationCheckpoint.PRE_JCAL,
        lifecycle_id="pytest.meas0.lifecycle.v3",
        comparison_block_id=comparison_block_id,
        authority_role_id="approval-authority-e",
        design_hash=_hash("a"),
        source_lock_hash=source_lock_hash,
        common_ancestry_hash=common_ancestry_hash,
        ledger_pre_head_hash=_hash("d"),
        evidence_bindings=_checkpoint_bindings(AuthorizationCheckpoint.PRE_JCAL),
        previous_target=None,
    )
    return create_simulated_phase_readiness_receipt(
        target=target,
        authorization=_authorization(
            target,
            policy_hash=verification_policy_hash,
        ),
        stage_evidence_hashes=dict(target.evidence_bindings),
        previous_receipt=None,
        previous_completion=None,
    )


def _pilot_target(
    pre_jcal_receipt: PhaseReadinessReceipt,
    *,
    manifest_hash: str,
) -> PhaseCheckpointTarget:
    completion = record_simulated_phase_completion(
        receipt=pre_jcal_receipt,
        disposition=PhaseCompletionDisposition.ADVANCED,
        evidence_hash=_hash("4"),
        ledger_head_hash=_hash("e"),
    )
    return PhaseCheckpointTarget.create(
        checkpoint=AuthorizationCheckpoint.PILOT_START,
        lifecycle_id=pre_jcal_receipt.target.lifecycle_id,
        comparison_block_id=pre_jcal_receipt.target.comparison_block_id,
        authority_role_id=pre_jcal_receipt.target.authority_role_id,
        design_hash=pre_jcal_receipt.target.design_hash,
        source_lock_hash=pre_jcal_receipt.target.source_lock_hash,
        common_ancestry_hash=pre_jcal_receipt.target.common_ancestry_hash,
        ledger_pre_head_hash=completion.ledger_head_hash,
        evidence_bindings=_checkpoint_bindings(
            AuthorizationCheckpoint.PILOT_START,
            pilot_input_manifest=manifest_hash,
        ),
        previous_target=pre_jcal_receipt.target,
    )


def _case_scope(*, manifest_id: str = "pytest.meas0.case-scope.v1"):
    cases = tuple(
        ReadinessCaseIdentity(
            case_id=case.case_id,
            task_id=case.task_id,
            task_version=1,
            fault_id=case.fault_id,
            native_adapter=True,
            case_descriptor_hash=f"{index + 1:064x}",
        )
        for index, case in enumerate(formal_attack_manifest("pilot").cases)
    )
    return FormalCaseScopeManifest(
        manifest_id=manifest_id,
        version=1,
        mutation_seed=1729,
        cases=cases,
    )


@lru_cache(maxsize=None)
def _bundle(task_id: str):
    task_frame = TaskFrame(
        task_id=task_id,
        version=1,
        subject_agent_id="subject",
        user_intent=f"complete {task_id}",
        desired_state="typed evidence exists",
        known_initial_state="not completed",
        entities_and_scope=(task_id,),
        constraints_and_permissions=("isolated",),
        available_capabilities=("produce evidence",),
        uncertainties_and_ambiguities=(),
        risk_and_reversibility=("test only",),
        required_artifacts=("result",),
        evidence_expectations=("typed evidence",),
        provenance=("test-fixture",),
    )
    goal_graph = GoalGraph(
        graph_id=f"{task_id}.goals",
        version=1,
        task_id=task_id,
        task_frame_version=1,
        goals=(
            Goal(
                goal_id=f"{task_id}.goal",
                desired_semantics="complete safely",
                critical=True,
                provenance=("test-fixture",),
            ),
        ),
        provenance=("test-fixture",),
    )
    requirement_graph = RequirementGraph(
        graph_id=f"{task_id}.requirements",
        version=1,
        schema_version=1,
        goal_graph_id=goal_graph.graph_id,
        goal_graph_version=goal_graph.version,
        requirements=(
            Requirement(
                requirement_id=f"{task_id}.safe",
                goal_id=f"{task_id}.goal",
                success_semantics="no unsafe action",
                dimension=MeasurementDimension.SAFETY,
                critical=True,
                provenance=("test-fixture",),
            ),
            Requirement(
                requirement_id=f"{task_id}.semantic",
                goal_id=f"{task_id}.goal",
                success_semantics="answer is useful",
                dimension=MeasurementDimension.SEMANTIC,
                critical=False,
                provenance=("test-fixture",),
            ),
        ),
        provenance=("test-fixture",),
    )
    measurement_graph = MeasurementGraph(
        graph_id=f"{task_id}.measurements",
        version=1,
        task_id=task_id,
        requirement_graph_id=requirement_graph.graph_id,
        requirement_graph_version=requirement_graph.version,
        requirement_schema_version=requirement_graph.schema_version,
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
                evaluator_ref=f"{task_id}.deterministic",
                evaluator_version="1",
                evaluator_authority=EvaluatorAuthority.HARNESS,
                provenance=("test-fixture",),
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
                provenance=("test-fixture",),
                role=MeasurementRole.DECISIVE,
            ),
        ),
        hard_gate_measurement_ids=(f"{task_id}.safe.measurement",),
        provenance=("test-fixture",),
    )
    return seal_task_measurement_bundle(
        bundle_id=f"{task_id}.bundle",
        version=1,
        task_frame=task_frame,
        goal_graph=goal_graph,
        requirement_graph=requirement_graph,
        measurement_graph=measurement_graph,
        acceptance_rules=("all decisive measurements pass",),
        deterministic_check_refs=(f"{task_id}.deterministic",),
        judge_refs=(f"{task_id}.judge",),
        metamorphic_relations=(),
        uncertainty_and_escalation_rules=("missing is unknown",),
        measurement_budget=2.0,
        provenance=("test-fixture",),
    )


def _episode(case: FormalCaseIdentity):
    bundle = _bundle(case.task_id)
    evidence = (
        EpisodeEvidence(
            evidence_id=f"{case.case_id}.input",
            kind=EvidenceKind.INPUT,
            locator="protected://input",
            content_hash=f"sha256:{'1' * 64}",
            provenance=("test-fixture",),
        ),
        EpisodeEvidence(
            evidence_id=f"{case.case_id}.environment",
            kind=EvidenceKind.ENVIRONMENT_STATE,
            locator="protected://environment",
            content_hash=f"sha256:{'2' * 64}",
            provenance=("test-fixture",),
            causal_parent_ids=(f"{case.case_id}.input",),
        ),
        EpisodeEvidence(
            evidence_id=f"{case.case_id}.trajectory",
            kind=EvidenceKind.TRAJECTORY,
            locator="protected://trajectory",
            content_hash=f"sha256:{'3' * 64}",
            provenance=("test-fixture",),
            causal_parent_ids=(f"{case.case_id}.environment",),
        ),
        EpisodeEvidence(
            evidence_id=f"{case.case_id}.response",
            kind=EvidenceKind.RESPONSE,
            locator="protected://response",
            content_hash=f"sha256:{'4' * 64}",
            provenance=("test-fixture",),
            causal_parent_ids=(f"{case.case_id}.trajectory",),
        ),
    )
    graph = EpisodeGraph(
        episode_id=case.case_id,
        version=1,
        task_id=case.task_id,
        task_frame_version=1,
        evidence=evidence,
        environment_state_ref=f"{case.case_id}.environment",
        trajectory_ref=f"{case.case_id}.trajectory",
        response_ref=f"{case.case_id}.response",
        provenance=("test-fixture",),
    )
    return seal_episode_graph(
        task_measurement_bundle=bundle,
        episode_graph=graph,
        provenance=("test-fixture",),
    )


@lru_cache(maxsize=None)
def _adapter(task_id: str) -> NativeAdapterArtifact:
    return NativeAdapterArtifact.from_source_bytes(
        task_id=task_id,
        adapter_id=f"{task_id}.native",
        adapter_version="1",
        source_path=f"src/adapters/{task_id}.py",
        source_bytes=f"def adapt_{task_id}(): pass\n".encode(),
    )


def _protected(case: FormalCaseIdentity) -> ProtectedCaseInput:
    return ProtectedCaseInput.create(
        case=case,
        task_measurement_bundle=_bundle(case.task_id),
        sealed_episode=_episode(case),
        failure_policy=FailurePolicyContract.frozen_v1(),
        native_adapter=_adapter(case.task_id),
    )


def _corpus(phase: str) -> ProtectedInputCorpus:
    cases = formal_attack_manifest(phase).cases
    return ProtectedInputCorpus.create(
        phase=phase,
        case_inputs=tuple(_protected(case) for case in cases),
    )


def test_failure_policy_v1_exactly_freezes_existing_dispositions() -> None:
    policy = FailurePolicyContract.frozen_v1()
    assert tuple(
        (
            item.failure_code,
            item.result_validity,
            item.automatic_status,
            item.retained_in_denominator,
        )
        for item in policy.dispositions
    ) == (
        (
            FailureCode.TIMEOUT,
            ResultValidity.VALID,
            EvaluationStatus.UNKNOWN,
            True,
        ),
        (
            FailureCode.PROVIDER_ERROR,
            ResultValidity.VALID,
            EvaluationStatus.UNKNOWN,
            True,
        ),
        (
            FailureCode.MALFORMED_RESPONSE,
            ResultValidity.VALID,
            EvaluationStatus.UNKNOWN,
            True,
        ),
        (
            FailureCode.BACKEND_INVALID,
            ResultValidity.INVALID,
            None,
            True,
        ),
        (
            FailureCode.BUDGET_EXHAUSTED,
            ResultValidity.VALID,
            EvaluationStatus.UNKNOWN,
            True,
        ),
        (
            FailureCode.STAGE_BUDGET_EXHAUSTED,
            ResultValidity.VALID,
            EvaluationStatus.UNKNOWN,
            True,
        ),
        (
            FailureCode.PROTOCOL_VIOLATION,
            ResultValidity.INVALID,
            None,
            True,
        ),
    )
    assert all(item.retained_in_denominator for item in policy.dispositions)
    assert FailurePolicyContract.from_dict(policy.to_dict()) == policy
    with pytest.raises(InputManifestError):
        replace(policy, dispositions=policy.dispositions[:-1])


def test_native_adapter_binds_exact_source_bytes_and_identity() -> None:
    adapter = _adapter("cold_chain_readiness")
    assert len(adapter.source_sha256) == 64
    assert NativeAdapterArtifact.from_dict(adapter.to_dict()) == adapter
    with pytest.raises(InputManifestError):
        replace(adapter, source_bytes=adapter.source_bytes + b"# drift\n")


def test_protected_case_input_derives_all_manifest_values() -> None:
    item = _protected(formal_attack_manifest("pilot").cases[0])
    assert item.task_bundle_hash == item.task_measurement_bundle.bundle_hash
    assert item.episode_hash == item.sealed_episode.episode_hash
    assert item.failure_policy_hash == item.failure_policy.contract_hash
    assert item.semantic_leaf_count == 1
    assert item.measurement_count == 2
    assert {
        "task_hash",
        "episode_hash",
        "failure_policy_hash",
        "semantic_leaf_count",
        "measurement_count",
    }.isdisjoint(inspect.signature(ProtectedCaseInput.create).parameters)


@pytest.mark.parametrize(
    ("phase", "expected_count"), (("pilot", 36), ("confirmatory", 144))
)
def test_corpus_has_exact_frozen_membership(
    phase: str,
    expected_count: int,
) -> None:
    corpus = _corpus(phase)
    expected_ids = tuple(case.case_id for case in formal_attack_manifest(phase).cases)
    assert len(corpus.case_inputs) == expected_count
    assert tuple(item.case.case_id for item in corpus.case_inputs) == expected_ids


def test_pilot_manifest_derives_scope_and_pre_jcal_ancestry() -> None:
    corpus = _corpus("pilot")
    case_scope = _case_scope()
    parent = _pre_jcal_receipt()
    manifest = InputManifest.create(
        corpus=corpus,
        case_scope_manifest=case_scope,
        readiness_parent=parent,
    )
    expected_ids = tuple(case.case_id for case in formal_attack_manifest("pilot").cases)
    assert tuple(item.case_id for item in manifest.entries) == expected_ids
    assert tuple(item.case_index for item in manifest.entries) == tuple(range(36))
    assert manifest.protected_corpus_hash == corpus.corpus_hash
    assert manifest.case_scope_manifest_hash == case_scope.contract_hash
    assert manifest.readiness_parent_receipt_hash == parent.receipt_hash
    assert manifest.readiness_parent_target_hash == parent.target.target_hash
    assert manifest.comparison_block_id == parent.target.comparison_block_id
    assert manifest.source_lock_hash == parent.target.source_lock_hash
    assert manifest.common_ancestry_hash == parent.target.common_ancestry_hash
    assert all(
        "source_path" not in entry.to_dict() and "source_bytes" not in entry.to_dict()
        for entry in manifest.entries
    )
    assert (
        InputManifest.from_dict(
            manifest.to_dict(),
            corpus=corpus,
            case_scope_manifest=case_scope,
            readiness_parent=parent,
        )
        == manifest
    )
    assert manifest.validate_pilot_ready_target(
        _pilot_target(parent, manifest_hash=manifest.manifest_hash)
    )


def test_corpus_rejects_duplicate_reorder_and_cross_case_swap() -> None:
    corpus = _corpus("pilot")
    values = corpus.case_inputs
    with pytest.raises(InputManifestError):
        ProtectedInputCorpus.create(
            phase="pilot",
            case_inputs=(values[0], values[0], *values[2:]),
        )
    with pytest.raises(InputManifestError):
        ProtectedInputCorpus.create(
            phase="pilot",
            case_inputs=(values[1], values[0], *values[2:]),
        )
    with pytest.raises(InputManifestError):
        replace(values[1], sealed_episode=values[0].sealed_episode)


def test_manifest_codec_rejects_unknown_missing_and_drifted_fields() -> None:
    corpus = _corpus("pilot")
    case_scope = _case_scope()
    parent = _pre_jcal_receipt()
    raw = InputManifest.create(
        corpus=corpus,
        case_scope_manifest=case_scope,
        readiness_parent=parent,
    ).to_dict()
    with pytest.raises(InputManifestError):
        InputManifest.from_dict(
            {**raw, "caller_count": 36},
            corpus=corpus,
            case_scope_manifest=case_scope,
            readiness_parent=parent,
        )
    missing = dict(raw)
    missing.pop("manifest_hash")
    with pytest.raises(InputManifestError):
        InputManifest.from_dict(
            missing,
            corpus=corpus,
            case_scope_manifest=case_scope,
            readiness_parent=parent,
        )
    drifted = dict(raw)
    drifted["entries"] = [*raw["entries"]]
    drifted["entries"][0] = {
        **drifted["entries"][0],
        "measurement_count": 999,
    }
    with pytest.raises(InputManifestError):
        InputManifest.from_dict(
            drifted,
            corpus=corpus,
            case_scope_manifest=case_scope,
            readiness_parent=parent,
        )


def test_manifest_factories_accept_no_caller_hashes_or_counts() -> None:
    entry_parameters = inspect.signature(
        InputManifest.entry_from_protected_input
    ).parameters
    manifest_parameters = inspect.signature(InputManifest.create).parameters
    forbidden = {
        "task_bundle_hash",
        "episode_hash",
        "failure_policy_hash",
        "semantic_leaf_count",
        "measurement_count",
        "adapter_source_sha256",
        "case_scope_manifest_hash",
        "readiness_parent_receipt_hash",
        "readiness_parent_target_hash",
        "comparison_block_id",
        "source_lock_hash",
        "common_ancestry_hash",
    }
    assert forbidden.isdisjoint(entry_parameters)
    assert forbidden.isdisjoint(manifest_parameters)


def test_manifest_rejects_scope_block_source_and_parent_substitution() -> None:
    corpus = _corpus("pilot")
    case_scope = _case_scope()
    parent = _pre_jcal_receipt()
    manifest = InputManifest.create(
        corpus=corpus,
        case_scope_manifest=case_scope,
        readiness_parent=parent,
    )
    raw = manifest.to_dict()
    substitutions = (
        {
            "case_scope_manifest": _case_scope(
                manifest_id="pytest.other.case-scope.v1"
            ),
            "readiness_parent": parent,
        },
        {
            "case_scope_manifest": case_scope,
            "readiness_parent": _pre_jcal_receipt(
                comparison_block_id="pytest.other.block.v3"
            ),
        },
        {
            "case_scope_manifest": case_scope,
            "readiness_parent": _pre_jcal_receipt(source_lock_hash=_hash("f")),
        },
        {
            "case_scope_manifest": case_scope,
            "readiness_parent": _pre_jcal_receipt(common_ancestry_hash=_hash("e")),
        },
        {
            "case_scope_manifest": case_scope,
            "readiness_parent": _pre_jcal_receipt(verification_policy_hash=_hash("6")),
        },
    )
    for parents in substitutions:
        with pytest.raises(InputManifestError):
            InputManifest.from_dict(raw, corpus=corpus, **parents)


def test_manifest_rejects_non_pre_jcal_parent_and_fake_ancestry_hash() -> None:
    corpus = _corpus("pilot")
    case_scope = _case_scope()
    parent = _pre_jcal_receipt()
    manifest = InputManifest.create(
        corpus=corpus,
        case_scope_manifest=case_scope,
        readiness_parent=parent,
    )
    pilot_target = _pilot_target(parent, manifest_hash=manifest.manifest_hash)
    completion = record_simulated_phase_completion(
        receipt=parent,
        disposition=PhaseCompletionDisposition.ADVANCED,
        evidence_hash=_hash("4"),
        ledger_head_hash=_hash("e"),
    )
    pilot_receipt = create_simulated_phase_readiness_receipt(
        target=pilot_target,
        authorization=_authorization(pilot_target),
        stage_evidence_hashes=dict(pilot_target.evidence_bindings),
        previous_receipt=parent,
        previous_completion=completion,
    )
    with pytest.raises(InputManifestError):
        InputManifest.create(
            corpus=corpus,
            case_scope_manifest=case_scope,
            readiness_parent=pilot_receipt,
        )

    drifted = manifest.to_dict()
    drifted["source_lock_hash"] = _hash("f")
    with pytest.raises(InputManifestError):
        InputManifest.from_dict(
            drifted,
            corpus=corpus,
            case_scope_manifest=case_scope,
            readiness_parent=parent,
        )


def test_pilot_ready_target_must_reverse_bind_the_manifest_hash() -> None:
    corpus = _corpus("pilot")
    case_scope = _case_scope()
    parent = _pre_jcal_receipt()
    manifest = InputManifest.create(
        corpus=corpus,
        case_scope_manifest=case_scope,
        readiness_parent=parent,
    )
    with pytest.raises(InputManifestError):
        manifest.validate_pilot_ready_target(
            _pilot_target(parent, manifest_hash=_hash("f"))
        )
