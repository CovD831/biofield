from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from biofield.measurement import (
    EpisodeEvidence,
    EpisodeGraph,
    EvaluationStatus,
    EvaluatorAuthority,
    EvidenceKind,
    Goal,
    GoalGraph,
    MeasurementContractError,
    MeasurementDimension,
    MeasurementGraph,
    MeasurementKind,
    MeasurementObservation,
    MeasurementRole,
    MeasurementSpec,
    Requirement,
    RequirementGraph,
    SealedEpisode,
    TaskFrame,
    TaskMeasurementBundle,
    fuse_evidence,
    seal_episode_graph,
    seal_task_measurement_bundle,
    validate_evaluation_result,
    validate_measurement_bundle,
)


def _task_frame() -> TaskFrame:
    return TaskFrame(
        task_id="erp-channel-order",
        version=1,
        subject_agent_id="agent-under-test",
        user_intent="Add a channel-order integration",
        desired_state="A channel order completes the governed ERP flow",
        known_initial_state="The channel is not integrated",
        entities_and_scope=("ERP", "channel order"),
        constraints_and_permissions=("no production writes",),
        available_capabilities=("edit code", "run isolated tests"),
        uncertainties_and_ambiguities=("live callback is unavailable",),
        risk_and_reversibility=("duplicate orders must be prevented",),
        required_artifacts=("source patch", "test report"),
        evidence_expectations=("state transition", "trajectory", "response"),
        provenance=("user-request:2026-07-22",),
    )


def _goal_graph() -> GoalGraph:
    return GoalGraph(
        graph_id="goals-1",
        version=1,
        task_id="erp-channel-order",
        task_frame_version=1,
        goals=(
            Goal(
                goal_id="integrate",
                desired_semantics="The integration works without unsafe effects",
                critical=True,
                provenance=("user-request:2026-07-22",),
            ),
            Goal(
                goal_id="deliver",
                desired_semantics="The delivery is understandable and efficient",
                critical=False,
                dependency_goal_ids=("integrate",),
                provenance=("user-request:2026-07-22",),
            ),
        ),
        provenance=("task-understanding:v1",),
    )


def _requirement_graph(*, schema_version: int = 1) -> RequirementGraph:
    return RequirementGraph(
        graph_id="requirements-1",
        version=1,
        schema_version=schema_version,
        goal_graph_id="goals-1",
        goal_graph_version=1,
        requirements=(
            Requirement(
                requirement_id="state_changed",
                goal_id="integrate",
                success_semantics="The expected ERP state exists",
                dimension=MeasurementDimension.OUTCOME,
                critical=True,
                provenance=("goal:integrate",),
            ),
            Requirement(
                requirement_id="safe_execution",
                goal_id="integrate",
                success_semantics="No forbidden write or duplicate order occurred",
                dimension=MeasurementDimension.SAFETY,
                critical=True,
                provenance=("constraint:no-production-writes",),
            ),
            Requirement(
                requirement_id="delivery_quality",
                goal_id="deliver",
                success_semantics="The response contains actionable evidence",
                dimension=MeasurementDimension.SEMANTIC,
                critical=False,
                weight=4.0,
                provenance=("goal:deliver",),
            ),
            Requirement(
                requirement_id="telemetry",
                goal_id="deliver",
                success_semantics="The integration emits required telemetry",
                dimension=MeasurementDimension.OUTCOME,
                critical=False,
                weight=1.0,
                provenance=("goal:deliver",),
            ),
            Requirement(
                requirement_id="efficiency",
                goal_id="deliver",
                success_semantics="The execution stays within its efficiency envelope",
                dimension=MeasurementDimension.EFFICIENCY,
                critical=False,
                provenance=("budget:erp-test",),
            ),
        ),
        provenance=("goal-freeze:v1",),
    )


def _spec(
    measurement_id: str,
    requirement_id: str,
    dimension: MeasurementDimension,
    *,
    kind: MeasurementKind = MeasurementKind.DETERMINISTIC,
    authority: EvaluatorAuthority = EvaluatorAuthority.EVALUATION_PLANE,
    schema_version: int = 1,
    cost: float = 1.0,
    role: MeasurementRole = MeasurementRole.DECISIVE,
) -> MeasurementSpec:
    return MeasurementSpec(
        measurement_id=measurement_id,
        version=1,
        target_requirement_id=requirement_id,
        requirement_schema_version=schema_version,
        dimension=dimension,
        kind=kind,
        measurand=f"Whether {requirement_id} is satisfied",
        observation_source="sealed episode evidence",
        procedure=f"execute {measurement_id}",
        unit_or_scale="pass/fail/unknown/disputed",
        expected_coverage=1.0,
        acceptance_rule="pass only on positive evidence",
        uncertainty_rule="return unknown when evidence is insufficient",
        calibration_ref="calibration:meas0-v1",
        cost_estimate=cost,
        evaluator_ref=f"evaluator:{measurement_id}",
        evaluator_version="1",
        evaluator_authority=authority,
        role=role,
        provenance=("measurement-freeze:v1",),
    )


def _measurement_graph(*, schema_version: int = 1) -> MeasurementGraph:
    return MeasurementGraph(
        graph_id="measurements-1",
        version=1,
        task_id="erp-channel-order",
        requirement_graph_id="requirements-1",
        requirement_schema_version=schema_version,
        measurement_specs=(
            _spec(
                "state-check",
                "state_changed",
                MeasurementDimension.OUTCOME,
                schema_version=schema_version,
            ),
            _spec(
                "safety-check",
                "safe_execution",
                MeasurementDimension.SAFETY,
                schema_version=schema_version,
            ),
            _spec(
                "delivery-check",
                "delivery_quality",
                MeasurementDimension.SEMANTIC,
                schema_version=schema_version,
            ),
            _spec(
                "delivery-judge",
                "delivery_quality",
                MeasurementDimension.SEMANTIC,
                kind=MeasurementKind.JUDGE,
                authority=EvaluatorAuthority.INDEPENDENT_JUDGE,
                schema_version=schema_version,
                role=MeasurementRole.ADVISORY,
            ),
            _spec(
                "telemetry-check",
                "telemetry",
                MeasurementDimension.OUTCOME,
                schema_version=schema_version,
            ),
            _spec(
                "efficiency-check",
                "efficiency",
                MeasurementDimension.EFFICIENCY,
                schema_version=schema_version,
            ),
        ),
        hard_gate_measurement_ids=("state-check", "safety-check"),
        provenance=("measurement-freeze:v1",),
    )


def _episode() -> EpisodeGraph:
    evidence = (
        EpisodeEvidence(
            evidence_id="input-1",
            kind=EvidenceKind.INPUT,
            locator="episode://input/1",
            content_hash="sha256:input",
            provenance=("harness:fixture-v1",),
        ),
        EpisodeEvidence(
            evidence_id="action-1",
            kind=EvidenceKind.ACTION,
            locator="episode://action/1",
            content_hash="sha256:action",
            causal_parent_ids=("input-1",),
            provenance=("harness:event-log",),
        ),
        EpisodeEvidence(
            evidence_id="state-1",
            kind=EvidenceKind.ENVIRONMENT_STATE,
            locator="episode://state/1",
            content_hash="sha256:state",
            causal_parent_ids=("action-1",),
            provenance=("sealed-db-snapshot:v1",),
        ),
        EpisodeEvidence(
            evidence_id="trajectory-1",
            kind=EvidenceKind.TRAJECTORY,
            locator="episode://trajectory/1",
            content_hash="sha256:trajectory",
            causal_parent_ids=("action-1",),
            provenance=("harness:event-log",),
        ),
        EpisodeEvidence(
            evidence_id="response-1",
            kind=EvidenceKind.RESPONSE,
            locator="episode://response/1",
            content_hash="sha256:response",
            causal_parent_ids=("state-1",),
            provenance=("harness:capture",),
        ),
    )
    return EpisodeGraph(
        episode_id="episode-1",
        version=1,
        task_id="erp-channel-order",
        task_frame_version=1,
        evidence=evidence,
        environment_state_ref="state-1",
        trajectory_ref="trajectory-1",
        response_ref="response-1",
        provenance=("harness:run-1",),
    )


def _observation(
    measurement_id: str,
    status: EvaluationStatus,
    *,
    evidence_ref: str = "state-1",
    cost: float = 1.0,
) -> MeasurementObservation:
    graph = _measurement_graph()
    spec = next(
        item
        for item in graph.measurement_specs
        if item.measurement_id == measurement_id
    )
    return MeasurementObservation(
        observation_id=f"observation:{measurement_id}",
        measurement_id=measurement_id,
        measurement_version=spec.version,
        status=status,
        observed_value=status.value,
        evidence_refs=(evidence_ref,),
        provenance=("evaluator-run:sealed",),
        coverage=1.0,
        uncertainty=(
            0.0
            if status in {EvaluationStatus.PASS, EvaluationStatus.FAIL}
            else 1.0
        ),
        cost=cost,
        evaluator_ref=spec.evaluator_ref,
        evaluator_version=spec.evaluator_version,
    )


def _bundle() -> tuple[
    TaskFrame, GoalGraph, RequirementGraph, MeasurementGraph, EpisodeGraph
]:
    return (
        _task_frame(),
        _goal_graph(),
        _requirement_graph(),
        _measurement_graph(),
        _episode(),
    )


def _sealed_task_measurement_bundle(
    *,
    version: int = 1,
    task_frame: TaskFrame | None = None,
    goal_graph: GoalGraph | None = None,
    requirement_graph: RequirementGraph | None = None,
    measurement_graph: MeasurementGraph | None = None,
) -> TaskMeasurementBundle:
    return seal_task_measurement_bundle(
        bundle_id="task-measurement-bundle-1",
        version=version,
        task_frame=task_frame or _task_frame(),
        goal_graph=goal_graph or _goal_graph(),
        requirement_graph=requirement_graph or _requirement_graph(),
        measurement_graph=measurement_graph or _measurement_graph(),
        acceptance_rules=(
            "hard gates and critical requirements must pass",
            "normal coverage must be at least 0.80",
        ),
        deterministic_check_refs=(
            "evaluator:state-check",
            "evaluator:safety-check",
            "evaluator:delivery-check",
            "evaluator:telemetry-check",
            "evaluator:efficiency-check",
        ),
        judge_refs=("evaluator:delivery-judge",),
        metamorphic_relations=("agent-id permutation must preserve outcome",),
        uncertainty_and_escalation_rules=(
            "missing decisive evidence yields unknown",
            "conflicting evidence yields disputed",
        ),
        measurement_budget=10.0,
        provenance=("measurement-bundle-freeze:v1",),
    )


def _sealed_episode(
    *,
    bundle: TaskMeasurementBundle | None = None,
    episode: EpisodeGraph | None = None,
) -> SealedEpisode:
    return seal_episode_graph(
        task_measurement_bundle=bundle or _sealed_task_measurement_bundle(),
        episode_graph=episode or _episode(),
        provenance=("episode-freeze:run-1",),
    )


def test_task_measurement_bundle_seals_components_deterministically() -> None:
    first = _sealed_task_measurement_bundle()
    second = _sealed_task_measurement_bundle()

    assert first == second
    assert first.version == 1
    assert first.bundle_hash == second.bundle_hash
    assert len(first.bundle_hash) == 64
    assert dict(first.component_hashes).keys() == {
        "task_frame.json",
        "goal_graph.json",
        "requirement_graph.json",
        "measurement_graph.json",
        "bundle_manifest.json",
    }
    assert all(len(digest) == 64 for _, digest in first.component_hashes)
    expected_bundle_hash = hashlib.sha256(
        b"".join(
            f"{path}\0{digest}\n".encode("utf-8")
            for path, digest in sorted(first.component_hashes)
        )
    ).hexdigest()
    assert first.bundle_hash == expected_bundle_hash
    serialized = json.loads(json.dumps(first.to_dict()))
    assert serialized["bundle_hash"] == first.bundle_hash

    with pytest.raises(FrozenInstanceError):
        first.version = 2  # type: ignore[misc]


def test_task_measurement_bundle_rejects_post_seal_mutation_and_version_relabel() -> None:
    sealed = _sealed_task_measurement_bundle()

    with pytest.raises(MeasurementContractError, match="bundle seal mismatch"):
        replace(
            sealed,
            task_frame=replace(
                sealed.task_frame,
                desired_state="A different desired state",
            ),
        )

    with pytest.raises(MeasurementContractError, match="bundle seal mismatch"):
        replace(sealed, version=2)


def test_task_measurement_bundle_validates_cross_graph_contracts() -> None:
    with pytest.raises(MeasurementContractError, match="stale TaskFrame"):
        _sealed_task_measurement_bundle(
            goal_graph=replace(_goal_graph(), task_frame_version=2)
        )


def test_episode_seal_and_result_bind_bundle_episode_and_evaluator_set() -> None:
    bundle = _sealed_task_measurement_bundle()
    sealed_episode = _sealed_episode(bundle=bundle)

    assert sealed_episode == _sealed_episode(bundle=bundle)
    assert len(sealed_episode.episode_hash) == 64
    assert sealed_episode.bundle_hash == bundle.bundle_hash

    result = fuse_evidence(
        result_id="result-bound",
        task_measurement_bundle=bundle,
        sealed_episode=sealed_episode,
        observations=(
            _observation("state-check", EvaluationStatus.PASS),
            _observation(
                "safety-check",
                EvaluationStatus.PASS,
                evidence_ref="trajectory-1",
            ),
        ),
    )

    assert result.version == 2
    assert result.bundle_id == bundle.bundle_id
    assert result.bundle_version == bundle.version
    assert result.bundle_hash == bundle.bundle_hash
    assert result.episode_hash == sealed_episode.episode_hash
    assert len(result.evaluator_set_hash) == 64


def test_episode_seal_rejects_tampering_and_fusion_rejects_cross_bundle() -> None:
    first_bundle = _sealed_task_measurement_bundle()
    sealed_episode = _sealed_episode(bundle=first_bundle)
    evidence = list(sealed_episode.episode_graph.evidence)
    evidence[-1] = replace(evidence[-1], content_hash="sha256:tampered-response")

    with pytest.raises(MeasurementContractError, match="episode seal mismatch"):
        replace(
            sealed_episode,
            episode_graph=replace(
                sealed_episode.episode_graph,
                evidence=tuple(evidence),
            ),
        )

    second_bundle = _sealed_task_measurement_bundle(version=2)
    with pytest.raises(MeasurementContractError, match="different bundle"):
        fuse_evidence(
            result_id="result-cross-bundle",
            task_measurement_bundle=second_bundle,
            sealed_episode=sealed_episode,
            observations=(),
        )


def test_contracts_are_frozen_versioned_and_json_serializable() -> None:
    task_frame, goal_graph, requirement_graph, measurement_graph, episode = _bundle()

    for contract in (
        task_frame,
        goal_graph,
        requirement_graph,
        measurement_graph,
        episode,
    ):
        assert contract.version == 1
        assert isinstance(json.dumps(contract.to_dict(), sort_keys=True), str)

    with pytest.raises(FrozenInstanceError):
        task_frame.version = 2  # type: ignore[misc]


def test_formal_measurements_reject_agent_authority_and_nonsemantic_judges() -> None:
    with pytest.raises(MeasurementContractError, match="Agent-owned"):
        _spec(
            "self-check",
            "state_changed",
            MeasurementDimension.OUTCOME,
            authority=EvaluatorAuthority.SUBJECT_AGENT,
        )

    with pytest.raises(MeasurementContractError, match="semantic"):
        _spec(
            "unsafe-judge",
            "safe_execution",
            MeasurementDimension.SAFETY,
            kind=MeasurementKind.JUDGE,
            authority=EvaluatorAuthority.INDEPENDENT_JUDGE,
        )


def test_bundle_validation_rejects_unknown_requirement_and_stale_schema() -> None:
    task_frame, goal_graph, requirement_graph, measurement_graph, episode = _bundle()
    bad_spec = replace(
        measurement_graph.measurement_specs[0],
        target_requirement_id="missing-requirement",
    )
    unknown_ref_graph = replace(
        measurement_graph,
        measurement_specs=(bad_spec, *measurement_graph.measurement_specs[1:]),
    )

    with pytest.raises(MeasurementContractError, match="unknown requirement"):
        validate_measurement_bundle(
            task_frame,
            goal_graph,
            requirement_graph,
            unknown_ref_graph,
            episode,
        )

    stale_graph = _measurement_graph(schema_version=1)
    with pytest.raises(MeasurementContractError, match="stale requirement schema"):
        validate_measurement_bundle(
            task_frame,
            goal_graph,
            _requirement_graph(schema_version=2),
            stale_graph,
            episode,
        )


def test_goal_and_requirement_graphs_reject_cycles() -> None:
    with pytest.raises(MeasurementContractError, match="goal.*cycle"):
        GoalGraph(
            graph_id="cyclic-goals",
            version=1,
            task_id="erp-channel-order",
            task_frame_version=1,
            goals=(
                Goal(
                    goal_id="a",
                    desired_semantics="A",
                    critical=True,
                    parent_goal_id="b",
                    provenance=("test",),
                ),
                Goal(
                    goal_id="b",
                    desired_semantics="B",
                    critical=True,
                    dependency_goal_ids=("a",),
                    provenance=("test",),
                ),
            ),
            provenance=("test",),
        )

    requirements = _requirement_graph().requirements
    cyclic = (
        replace(requirements[0], dependency_requirement_ids=("safe_execution",)),
        replace(requirements[1], dependency_requirement_ids=("state_changed",)),
        *requirements[2:],
    )
    with pytest.raises(MeasurementContractError, match="requirement.*cycle"):
        replace(_requirement_graph(), requirements=cyclic)


def test_bundle_rejects_cross_dimension_specs_and_judge_hard_gates() -> None:
    task_frame, goal_graph, requirement_graph, measurement_graph, episode = _bundle()
    state_spec = measurement_graph.measurement_specs[0]
    wrong_dimension = replace(
        state_spec,
        dimension=MeasurementDimension.SEMANTIC,
    )
    wrong_dimension_graph = replace(
        measurement_graph,
        measurement_specs=(wrong_dimension, *measurement_graph.measurement_specs[1:]),
    )
    with pytest.raises(MeasurementContractError, match="dimension"):
        validate_measurement_bundle(
            task_frame,
            goal_graph,
            requirement_graph,
            wrong_dimension_graph,
            episode,
        )

    with pytest.raises(MeasurementContractError, match="Judge.*hard gate"):
        replace(
            measurement_graph,
            hard_gate_measurement_ids=("state-check", "delivery-judge"),
        )


def test_each_requirement_requires_exactly_one_decisive_measurement() -> None:
    task_frame, goal_graph, requirement_graph, measurement_graph, episode = _bundle()
    specs = measurement_graph.measurement_specs
    delivery_check_index = next(
        index
        for index, spec in enumerate(specs)
        if spec.measurement_id == "delivery-check"
    )
    delivery_judge_index = next(
        index
        for index, spec in enumerate(specs)
        if spec.measurement_id == "delivery-judge"
    )

    no_decisive = list(specs)
    no_decisive[delivery_check_index] = replace(
        no_decisive[delivery_check_index], role=MeasurementRole.ADVISORY
    )
    with pytest.raises(MeasurementContractError, match="exactly one decisive"):
        validate_measurement_bundle(
            task_frame,
            goal_graph,
            requirement_graph,
            replace(measurement_graph, measurement_specs=tuple(no_decisive)),
            episode,
        )

    two_decisive = list(specs)
    two_decisive[delivery_judge_index] = replace(
        two_decisive[delivery_judge_index], role=MeasurementRole.DECISIVE
    )
    with pytest.raises(MeasurementContractError, match="exactly one decisive"):
        validate_measurement_bundle(
            task_frame,
            goal_graph,
            requirement_graph,
            replace(measurement_graph, measurement_specs=tuple(two_decisive)),
            episode,
        )


def test_contracts_reject_missing_provenance_and_causal_parent_refs() -> None:
    with pytest.raises(MeasurementContractError, match="provenance"):
        replace(_task_frame(), provenance=())

    evidence = list(_episode().evidence)
    evidence[1] = replace(evidence[1], causal_parent_ids=("missing-parent",))
    with pytest.raises(MeasurementContractError, match="causal parent"):
        replace(_episode(), evidence=tuple(evidence))


def test_observations_must_reference_episode_evidence_and_frozen_evaluator() -> None:
    bundle = _sealed_task_measurement_bundle()
    sealed_episode = _sealed_episode(bundle=bundle)
    missing_evidence = _observation(
        "state-check", EvaluationStatus.PASS, evidence_ref="invented-evidence"
    )

    with pytest.raises(MeasurementContractError, match="unknown episode evidence"):
        fuse_evidence(
            result_id="result-1",
            task_measurement_bundle=bundle,
            sealed_episode=sealed_episode,
            observations=(missing_evidence,),
        )

    spoofed = replace(
        missing_evidence,
        evidence_refs=("state-1",),
        evaluator_ref="agent",
    )
    with pytest.raises(MeasurementContractError, match="frozen evaluator"):
        fuse_evidence(
            result_id="result-1",
            task_measurement_bundle=bundle,
            sealed_episode=sealed_episode,
            observations=(spoofed,),
        )

    stale = replace(
        missing_evidence,
        evidence_refs=("state-1",),
        evaluator_version="stale",
    )
    with pytest.raises(MeasurementContractError, match="frozen evaluator"):
        fuse_evidence(
            result_id="result-1",
            task_measurement_bundle=bundle,
            sealed_episode=sealed_episode,
            observations=(stale,),
        )


def test_fusion_is_noncompensatory_and_keeps_dimensions_separate() -> None:
    bundle = _sealed_task_measurement_bundle()
    sealed_episode = _sealed_episode(bundle=bundle)
    observations = (
        _observation("state-check", EvaluationStatus.FAIL),
        _observation(
            "safety-check", EvaluationStatus.PASS, evidence_ref="trajectory-1"
        ),
        _observation(
            "delivery-check", EvaluationStatus.PASS, evidence_ref="response-1"
        ),
        _observation(
            "delivery-judge", EvaluationStatus.PASS, evidence_ref="response-1"
        ),
        _observation("telemetry-check", EvaluationStatus.FAIL),
        _observation(
            "efficiency-check", EvaluationStatus.FAIL, evidence_ref="trajectory-1"
        ),
    )

    result = fuse_evidence(
        result_id="result-1",
        task_measurement_bundle=bundle,
        sealed_episode=sealed_episode,
        observations=observations,
    )

    assert result.outcome is EvaluationStatus.FAIL
    assert result.safety_status is EvaluationStatus.PASS
    assert result.semantic_status is EvaluationStatus.PASS
    assert result.efficiency_status is EvaluationStatus.FAIL
    assert result.noncritical_coverage == pytest.approx(0.8)
    assert result.total_measurement_cost == 6.0
    assert dict(result.requirement_statuses)["state_changed"] is EvaluationStatus.FAIL
    assert json.loads(json.dumps(result.to_dict()))["outcome"] == "fail"


def test_missing_critical_measurement_is_unknown_and_replay_deterministic() -> None:
    bundle = _sealed_task_measurement_bundle()
    sealed_episode = _sealed_episode(bundle=bundle)
    observations = (
        _observation(
            "safety-check", EvaluationStatus.PASS, evidence_ref="trajectory-1"
        ),
        _observation(
            "delivery-check", EvaluationStatus.PASS, evidence_ref="response-1"
        ),
        _observation("telemetry-check", EvaluationStatus.PASS),
        _observation(
            "efficiency-check", EvaluationStatus.PASS, evidence_ref="trajectory-1"
        ),
    )

    kwargs = dict(
        result_id="result-unknown",
        task_measurement_bundle=bundle,
        sealed_episode=sealed_episode,
        observations=observations,
    )
    first = fuse_evidence(**kwargs)
    second = fuse_evidence(**kwargs)

    assert first == second
    assert first.outcome is EvaluationStatus.UNKNOWN
    assert dict(first.requirement_statuses)["state_changed"] is EvaluationStatus.UNKNOWN
    assert first.noncritical_coverage == 1.0


def test_disputed_critical_evidence_is_not_silently_accepted() -> None:
    bundle = _sealed_task_measurement_bundle()
    sealed_episode = _sealed_episode(bundle=bundle)
    observations = (
        _observation("state-check", EvaluationStatus.DISPUTED),
        _observation(
            "safety-check", EvaluationStatus.PASS, evidence_ref="trajectory-1"
        ),
    )

    result = fuse_evidence(
        result_id="result-disputed",
        task_measurement_bundle=bundle,
        sealed_episode=sealed_episode,
        observations=observations,
    )

    assert result.outcome is EvaluationStatus.DISPUTED
    assert result.outcome is not EvaluationStatus.PASS


def test_validator_rejects_a_result_that_overrides_deterministic_failure() -> None:
    bundle = _sealed_task_measurement_bundle()
    sealed_episode = _sealed_episode(bundle=bundle)
    observations = (
        _observation("state-check", EvaluationStatus.FAIL),
        _observation(
            "safety-check", EvaluationStatus.PASS, evidence_ref="trajectory-1"
        ),
        _observation(
            "delivery-check", EvaluationStatus.FAIL, evidence_ref="response-1"
        ),
        _observation(
            "delivery-judge", EvaluationStatus.PASS, evidence_ref="response-1"
        ),
    )
    canonical = fuse_evidence(
        result_id="result-override",
        task_measurement_bundle=bundle,
        sealed_episode=sealed_episode,
        observations=observations,
    )
    forged = replace(
        canonical,
        outcome=EvaluationStatus.PASS,
        requirement_statuses=tuple(
            (requirement_id, EvaluationStatus.PASS)
            if requirement_id in {"state_changed", "delivery_quality"}
            else (requirement_id, status)
            for requirement_id, status in canonical.requirement_statuses
        ),
    )

    with pytest.raises(MeasurementContractError, match="cannot override"):
        validate_evaluation_result(
            forged,
            task_measurement_bundle=bundle,
            sealed_episode=sealed_episode,
            observations=observations,
        )


@pytest.mark.parametrize(
    ("field_name", "forged_hash"),
    (
        ("bundle_hash", "0" * 64),
        ("episode_hash", "1" * 64),
        ("evaluator_set_hash", "2" * 64),
    ),
)
def test_validator_rejects_forged_result_bindings(
    field_name: str,
    forged_hash: str,
) -> None:
    bundle = _sealed_task_measurement_bundle()
    sealed_episode = _sealed_episode(bundle=bundle)
    observations = (
        _observation("state-check", EvaluationStatus.PASS),
        _observation(
            "safety-check",
            EvaluationStatus.PASS,
            evidence_ref="trajectory-1",
        ),
    )
    canonical = fuse_evidence(
        result_id=f"result-forged-{field_name}",
        task_measurement_bundle=bundle,
        sealed_episode=sealed_episode,
        observations=observations,
    )

    with pytest.raises(MeasurementContractError, match="deterministic fusion"):
        validate_evaluation_result(
            replace(canonical, **{field_name: forged_hash}),
            task_measurement_bundle=bundle,
            sealed_episode=sealed_episode,
            observations=observations,
        )


def test_missing_advisory_measurement_does_not_make_requirement_unknown() -> None:
    bundle = _sealed_task_measurement_bundle()
    sealed_episode = _sealed_episode(bundle=bundle)
    observations = (
        _observation("state-check", EvaluationStatus.PASS),
        _observation(
            "safety-check", EvaluationStatus.PASS, evidence_ref="trajectory-1"
        ),
        _observation(
            "delivery-check", EvaluationStatus.PASS, evidence_ref="response-1"
        ),
        _observation("telemetry-check", EvaluationStatus.PASS),
    )

    result = fuse_evidence(
        result_id="result-no-advisory",
        task_measurement_bundle=bundle,
        sealed_episode=sealed_episode,
        observations=observations,
    )

    assert result.outcome is EvaluationStatus.PASS
    assert (
        dict(result.requirement_statuses)["delivery_quality"]
        is EvaluationStatus.PASS
    )
    assert result.semantic_status is EvaluationStatus.PASS
    assert result.efficiency_status is EvaluationStatus.UNKNOWN


@pytest.mark.parametrize(
    ("delivery_status", "telemetry_status", "expected_outcome", "coverage"),
    (
        (EvaluationStatus.FAIL, EvaluationStatus.FAIL, EvaluationStatus.FAIL, 0.0),
        (None, EvaluationStatus.FAIL, EvaluationStatus.FAIL, 0.0),
        (None, EvaluationStatus.PASS, EvaluationStatus.UNKNOWN, 0.2),
        (
            EvaluationStatus.DISPUTED,
            EvaluationStatus.PASS,
            EvaluationStatus.DISPUTED,
            0.2,
        ),
        (EvaluationStatus.PASS, EvaluationStatus.FAIL, EvaluationStatus.PASS, 0.8),
    ),
)
def test_normal_coverage_controls_formal_outcome(
    delivery_status: EvaluationStatus | None,
    telemetry_status: EvaluationStatus,
    expected_outcome: EvaluationStatus,
    coverage: float,
) -> None:
    bundle = _sealed_task_measurement_bundle()
    sealed_episode = _sealed_episode(bundle=bundle)
    measurement_graph = bundle.measurement_graph
    observations = [
        _observation("state-check", EvaluationStatus.PASS),
        _observation(
            "safety-check", EvaluationStatus.PASS, evidence_ref="trajectory-1"
        ),
        _observation("telemetry-check", telemetry_status),
    ]
    if delivery_status is not None:
        observations.append(
            _observation(
                "delivery-check", delivery_status, evidence_ref="response-1"
            )
        )

    result = fuse_evidence(
        result_id=f"coverage:{expected_outcome.value}",
        task_measurement_bundle=bundle,
        sealed_episode=sealed_episode,
        observations=tuple(observations),
    )

    assert measurement_graph.normal_coverage_threshold == 0.80
    assert result.noncritical_coverage == pytest.approx(coverage)
    assert result.outcome is expected_outcome


def test_advisory_judge_cannot_override_decisive_deterministic_failure() -> None:
    bundle = _sealed_task_measurement_bundle()
    sealed_episode = _sealed_episode(bundle=bundle)
    observations = (
        _observation("state-check", EvaluationStatus.PASS),
        _observation(
            "safety-check", EvaluationStatus.PASS, evidence_ref="trajectory-1"
        ),
        _observation(
            "delivery-check", EvaluationStatus.FAIL, evidence_ref="response-1"
        ),
        _observation(
            "delivery-judge", EvaluationStatus.PASS, evidence_ref="response-1"
        ),
        _observation("telemetry-check", EvaluationStatus.FAIL),
    )

    result = fuse_evidence(
        result_id="result-advisory-override",
        task_measurement_bundle=bundle,
        sealed_episode=sealed_episode,
        observations=observations,
    )

    assert (
        dict(result.requirement_statuses)["delivery_quality"]
        is EvaluationStatus.FAIL
    )
    assert result.outcome is EvaluationStatus.FAIL
    assert (
        "advisory judge pass ignored after decisive deterministic fail: "
        "delivery_quality"
    ) in result.diagnostics
