from __future__ import annotations

import json

import pytest

from biofield.contracts import (
    ActionObservation,
    ActionStatus,
    ClaimAuthority,
    DependencyKind,
    EvidenceLevel,
    ExperimentDecision,
    ExperimentResult,
    FeedbackDisposition,
    FeedbackEvent,
    FeedbackSourceKind,
    MetricInterval,
    MetricSeries,
    MetricValue,
    RequirementDelta,
    RequirementDependency,
    RequirementResidual,
    RequirementSpec,
    RequirementStatus,
    ResidualSnapshot,
    ResourceAmount,
    ResourceEvent,
    ResourceLimit,
    ResourceOperation,
    TaskSpec,
)


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="task-1",
        requirement_schema_version=1,
        goal="Produce a supported answer",
        requirements=(
            RequirementSpec("sources", "Collect relevant sources"),
            RequirementSpec("answer", "Write the answer"),
        ),
        requirement_dependencies=(
            RequirementDependency(
                requirement_id="answer",
                depends_on_requirement_id="sources",
                kind=DependencyKind.REQUIRES,
            ),
        ),
        constraints=("offline fixture",),
        acceptance_rules=("all required dimensions are satisfied",),
        resource_limits=(ResourceLimit("tokens", 2_000),),
    )


def test_public_contracts_are_json_serializable() -> None:
    task = _task()
    action = ActionObservation(
        action_id="action-1",
        agent_id="agent-1",
        requirement_ids=("sources",),
        input_refs=("input-1",),
        artifact_refs=("artifact-1",),
        evidence_refs=("evidence-1",),
        resource_cost=(ResourceAmount("tokens", 120),),
        started_at="2026-07-13T09:00:00+08:00",
        finished_at="2026-07-13T09:00:01+08:00",
        status=ActionStatus.SUCCEEDED,
    )
    feedback = FeedbackEvent(
        feedback_id="feedback-1",
        task_id=task.task_id,
        action_id=action.action_id,
        requirement_deltas=(
            RequirementDelta(
                requirement_id="sources",
                disposition=FeedbackDisposition.ACCEPTED,
                evidence_refs=("evidence-1",),
                invalidates_feedback_ids=("feedback-0",),
            ),
        ),
        source_kind=FeedbackSourceKind.VERIFIER,
        source_authority_by_claim_type=(
            ClaimAuthority("source_quality", "deterministic_fixture"),
        ),
        confidence=0.95,
        evidence_refs=("verifier-run-1",),
    )
    resource = ResourceEvent(
        event_id="resource-1",
        operation=ResourceOperation.INJECT,
        resource_type="tokens",
        amount=2_000,
        source_account="external",
        target_account="SharedPool",
        idempotency_key="inject-task-1",
    )
    snapshot = ResidualSnapshot(
        task_id=task.task_id,
        requirement_schema_version=1,
        revision=1,
        requirements=(
            RequirementResidual(
                requirement_id="sources",
                required=True,
                status=RequirementStatus.SATISFIED,
                supporting_evidence_refs=("evidence-1",),
                feedback_ids=("feedback-1",),
            ),
            RequirementResidual(
                requirement_id="answer",
                required=True,
                status=RequirementStatus.UNMET,
            ),
        ),
        applied_feedback_ids=("feedback-1",),
        complete=False,
    )
    result = ExperimentResult(
        experiment_id="b0-pilot",
        hypothesis="Residual updates are deterministic and reversible",
        configuration={"cycles": 2, "strict": True},
        seeds=(7, 11),
        task_structure="deterministic residual fixture",
        raw_metrics=(MetricSeries("completion", (0.0, 1.0)),),
        effect_sizes=(MetricValue("completion_delta", 1.0),),
        intervals=(MetricInterval("completion_delta", 0.8, 1.0, 0.95),),
        failures=(),
        evidence_level=EvidenceLevel.EXPLORATORY,
        decision=ExperimentDecision.SUPPORT,
        artifacts=("events.jsonl",),
    )

    for contract in (task, action, feedback, resource, snapshot, result):
        encoded = json.dumps(contract.to_dict(), sort_keys=True)
        assert isinstance(encoded, str)

    assert json.loads(json.dumps(feedback.to_dict()))["requirement_deltas"][0][
        "disposition"
    ] == "accepted"
    assert json.loads(json.dumps(feedback.to_dict()))["requirement_deltas"][0][
        "invalidates_feedback_ids"
    ] == ["feedback-0"]


def test_task_rejects_duplicate_requirement_ids_and_invalid_versions() -> None:
    common = dict(
        task_id="task-1",
        goal="goal",
        requirements=(
            RequirementSpec("duplicate", "first"),
            RequirementSpec("duplicate", "second"),
        ),
        acceptance_rules=("all required dimensions are satisfied",),
    )

    with pytest.raises(ValueError, match="requirement_schema_version"):
        TaskSpec(requirement_schema_version=0, **common)

    with pytest.raises(ValueError, match="duplicate requirement_ids"):
        TaskSpec(requirement_schema_version=1, **common)


def test_task_rejects_dependencies_that_reference_unknown_requirements() -> None:
    with pytest.raises(ValueError, match="unknown requirement"):
        TaskSpec(
            task_id="task-1",
            requirement_schema_version=1,
            goal="goal",
            requirements=(RequirementSpec("known", "known requirement"),),
            requirement_dependencies=(
                RequirementDependency(
                    requirement_id="known",
                    depends_on_requirement_id="missing",
                    kind=DependencyKind.REQUIRES,
                ),
            ),
            acceptance_rules=("known is satisfied",),
        )


def test_event_contracts_reject_duplicate_ids_and_invalid_numbers() -> None:
    with pytest.raises(ValueError, match="duplicate requirement_ids"):
        FeedbackEvent(
            feedback_id="feedback-1",
            task_id="task-1",
            action_id="action-1",
            requirement_deltas=(
                RequirementDelta("r1", FeedbackDisposition.ACCEPTED, ("e1",)),
                RequirementDelta("r1", FeedbackDisposition.REJECTED, ("e2",)),
            ),
            source_kind=FeedbackSourceKind.ENVIRONMENT,
            confidence=0.8,
        )

    with pytest.raises(ValueError, match="confidence"):
        FeedbackEvent(
            feedback_id="feedback-1",
            task_id="task-1",
            action_id="action-1",
            requirement_deltas=(
                RequirementDelta("r1", FeedbackDisposition.ACCEPTED, ("e1",)),
            ),
            source_kind=FeedbackSourceKind.ENVIRONMENT,
            confidence=1.1,
        )

    with pytest.raises(ValueError, match="duplicate evidence_refs"):
        ActionObservation(
            action_id="action-1",
            agent_id="agent-1",
            requirement_ids=("r1",),
            evidence_refs=("e1", "e1"),
            started_at="2026-07-13T09:00:00+08:00",
            finished_at="2026-07-13T09:00:01+08:00",
            status=ActionStatus.SUCCEEDED,
        )

    with pytest.raises(ValueError, match="amount must be positive"):
        ResourceEvent(
            event_id="resource-1",
            operation=ResourceOperation.SPEND,
            resource_type="tokens",
            amount=0,
            source_account="AgentEscrow[agent-1]",
            target_account="Spent",
            idempotency_key="spend-action-1",
        )


def test_feedback_requires_traceable_evidence_for_each_delta() -> None:
    with pytest.raises(ValueError, match="evidence"):
        FeedbackEvent(
            feedback_id="feedback-1",
            task_id="task-1",
            action_id="action-1",
            requirement_deltas=(
                RequirementDelta("r1", FeedbackDisposition.DISPUTED),
            ),
            source_kind=FeedbackSourceKind.HUMAN,
            confidence=0.5,
        )


def test_requirement_delta_rejects_duplicate_invalidation_references() -> None:
    with pytest.raises(ValueError, match="duplicate invalidates_feedback_ids"):
        RequirementDelta(
            requirement_id="r1",
            disposition=FeedbackDisposition.REJECTED,
            evidence_refs=("e2",),
            invalidates_feedback_ids=("f1", "f1"),
        )


def test_experiment_result_requires_metrics_configuration_and_artifacts() -> None:
    with pytest.raises(ValueError, match="configuration"):
        ExperimentResult(
            experiment_id="empty-result",
            hypothesis="A falsifiable claim",
            configuration={},
            seeds=(1,),
            task_structure="fixture",
            raw_metrics=(),
            effect_sizes=(),
            intervals=(),
            failures=(),
            evidence_level=EvidenceLevel.EXPLORATORY,
            decision=ExperimentDecision.INCONCLUSIVE,
            artifacts=(),
        )


def test_confirmatory_support_requires_effects_and_matching_intervals() -> None:
    common = dict(
        experiment_id="confirmatory-result",
        hypothesis="A falsifiable claim",
        configuration={"fixture_version": "v1"},
        seeds=(1, 2),
        task_structure="fixture",
        raw_metrics=(MetricSeries("quality", (0.4, 0.6)),),
        failures=(),
        evidence_level=EvidenceLevel.CONFIRMATORY,
        decision=ExperimentDecision.SUPPORT,
        artifacts=("metrics.json",),
    )

    with pytest.raises(ValueError, match="effect_sizes"):
        ExperimentResult(effect_sizes=(), intervals=(), **common)

    with pytest.raises(ValueError, match="matching interval"):
        ExperimentResult(
            effect_sizes=(MetricValue("quality_delta", 0.2),),
            intervals=(MetricInterval("unrelated", 0.1, 0.3, 0.95),),
            **common,
        )


def test_experiment_result_configuration_is_deeply_immutable() -> None:
    result = ExperimentResult(
        experiment_id="immutable-result",
        hypothesis="Frozen results cannot drift after validation",
        configuration={"controller": {"weights": [0.5, 1.0]}},
        seeds=(1,),
        task_structure="fixture",
        raw_metrics=(MetricSeries("quality", (0.5,)),),
        effect_sizes=(),
        intervals=(),
        failures=(),
        evidence_level=EvidenceLevel.EXPLORATORY,
        decision=ExperimentDecision.INCONCLUSIVE,
        artifacts=("metrics.json",),
    )

    with pytest.raises(TypeError):
        result.configuration["controller"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        result.configuration["controller"]["weights"] = ()  # type: ignore[index]
    assert result.to_dict()["configuration"] == {
        "controller": {"weights": [0.5, 1.0]}
    }
