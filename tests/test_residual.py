from __future__ import annotations

import pytest

from biofield.contracts import (
    DependencyKind,
    FeedbackDisposition,
    FeedbackEvent,
    FeedbackSourceKind,
    RequirementDelta,
    RequirementDependency,
    RequirementSpec,
    RequirementStatus,
    TaskSpec,
)
from biofield.residual import ResidualStateMachine


def _task(
    *,
    version: int = 1,
    requirements: tuple[RequirementSpec, ...] | None = None,
) -> TaskSpec:
    return TaskSpec(
        task_id="task-1",
        requirement_schema_version=version,
        goal="Produce an evidence-backed answer",
        requirements=requirements
        or (
            RequirementSpec("sources", "Collect sources"),
            RequirementSpec("answer", "Write the answer"),
        ),
        constraints=("offline",),
        acceptance_rules=("all required dimensions are satisfied",),
    )


def _feedback(
    feedback_id: str,
    requirement_id: str,
    disposition: FeedbackDisposition,
    evidence_ref: str,
    *,
    invalidates_feedback_ids: tuple[str, ...] = (),
) -> FeedbackEvent:
    return FeedbackEvent(
        feedback_id=feedback_id,
        task_id="task-1",
        action_id=f"action-{feedback_id}",
        requirement_deltas=(
            RequirementDelta(
                requirement_id=requirement_id,
                disposition=disposition,
                evidence_refs=(evidence_ref,),
                invalidates_feedback_ids=invalidates_feedback_ids,
            ),
        ),
        source_kind=FeedbackSourceKind.VERIFIER,
        confidence=0.9,
    )


def test_accepted_feedback_satisfies_requirements_and_completion_is_derived() -> None:
    machine = ResidualStateMachine(_task())

    initial = machine.snapshot()
    assert initial.complete is False
    assert initial.status_by_requirement() == {
        "sources": RequirementStatus.UNMET,
        "answer": RequirementStatus.UNMET,
    }

    after_sources = machine.apply_feedback(
        _feedback("f1", "sources", FeedbackDisposition.ACCEPTED, "source-check")
    )
    assert after_sources.complete is False
    assert after_sources.requirement("sources").status is RequirementStatus.SATISFIED
    assert after_sources.requirement("sources").supporting_evidence_refs == (
        "source-check",
    )

    completed = machine.apply_feedback(
        _feedback("f2", "answer", FeedbackDisposition.ACCEPTED, "answer-check")
    )
    assert completed.complete is True


def test_conflicting_and_disputed_feedback_suspend_completion() -> None:
    machine = ResidualStateMachine(_task())
    machine.apply_feedback(
        _feedback("f1", "sources", FeedbackDisposition.ACCEPTED, "source-check")
    )
    machine.apply_feedback(
        _feedback("f2", "answer", FeedbackDisposition.ACCEPTED, "answer-check")
    )
    assert machine.snapshot().complete is True

    rejected = machine.apply_feedback(
        _feedback("f3", "answer", FeedbackDisposition.REJECTED, "failed-check")
    )
    assert rejected.complete is False
    assert rejected.requirement("answer").status is RequirementStatus.DISPUTED
    assert rejected.requirement("answer").conflicting_evidence_refs == ("failed-check",)

    disputed = machine.apply_feedback(
        _feedback("f4", "sources", FeedbackDisposition.DISPUTED, "conflict-check")
    )
    assert disputed.complete is False
    assert disputed.requirement("sources").status is RequirementStatus.DISPUTED
    assert disputed.requirement("sources").feedback_ids == ("f1", "f4")


def test_conflicting_feedback_is_order_independent_and_becomes_disputed() -> None:
    accepted = _feedback(
        "accepted", "answer", FeedbackDisposition.ACCEPTED, "accepted-evidence"
    )
    rejected = _feedback(
        "rejected", "answer", FeedbackDisposition.REJECTED, "rejected-evidence"
    )
    forward = ResidualStateMachine(_task())
    reverse = ResidualStateMachine(_task())

    forward.apply_feedback(accepted)
    forward_result = forward.apply_feedback(rejected)
    reverse.apply_feedback(rejected)
    reverse_result = reverse.apply_feedback(accepted)

    assert forward_result.requirement("answer").status is RequirementStatus.DISPUTED
    assert reverse_result.requirement("answer").status is RequirementStatus.DISPUTED
    assert forward_result.complete is False
    assert reverse_result.complete is False


def test_explicit_invalidation_removes_old_feedback_from_state_aggregation() -> None:
    machine = ResidualStateMachine(_task())
    machine.apply_feedback(
        _feedback("f1", "sources", FeedbackDisposition.ACCEPTED, "passed-check")
    )

    snapshot = machine.apply_feedback(
        _feedback(
            "f2",
            "sources",
            FeedbackDisposition.REJECTED,
            "failed-check",
            invalidates_feedback_ids=("f1",),
        )
    )

    residual = snapshot.requirement("sources")
    assert residual.status is RequirementStatus.UNMET
    assert residual.supporting_evidence_refs == ()
    assert residual.conflicting_evidence_refs == ("failed-check",)
    assert residual.feedback_ids == ("f2",)
    assert residual.invalidated_feedback_ids == ("f1",)
    assert snapshot.applied_feedback_ids == ("f1", "f2")


def test_unknown_cross_dimension_and_repeated_invalidations_are_rejected() -> None:
    machine = ResidualStateMachine(_task())
    machine.apply_feedback(
        _feedback("f1", "sources", FeedbackDisposition.ACCEPTED, "source-check")
    )

    with pytest.raises(ValueError, match="unknown or non-earlier"):
        machine.apply_feedback(
            _feedback(
                "unknown",
                "sources",
                FeedbackDisposition.REJECTED,
                "unknown-check",
                invalidates_feedback_ids=("missing",),
            )
        )
    with pytest.raises(ValueError, match="same requirement"):
        machine.apply_feedback(
            _feedback(
                "cross",
                "answer",
                FeedbackDisposition.REJECTED,
                "answer-check",
                invalidates_feedback_ids=("f1",),
            )
        )
    assert machine.snapshot().revision == 1
    assert machine.snapshot().applied_feedback_ids == ("f1",)

    machine.apply_feedback(
        _feedback(
            "f2",
            "sources",
            FeedbackDisposition.REJECTED,
            "failed-check",
            invalidates_feedback_ids=("f1",),
        )
    )
    before_repeated_attempt = machine.snapshot()
    with pytest.raises(ValueError, match="already invalidated"):
        machine.apply_feedback(
            _feedback(
                "repeated",
                "sources",
                FeedbackDisposition.ACCEPTED,
                "retry-check",
                invalidates_feedback_ids=("f1",),
            )
        )
    assert machine.snapshot() == before_repeated_attempt


def test_feedback_cannot_invalidate_itself() -> None:
    machine = ResidualStateMachine(_task())
    with pytest.raises(ValueError, match="unknown or non-earlier"):
        machine.apply_feedback(
            _feedback(
                "self",
                "sources",
                FeedbackDisposition.REJECTED,
                "self-check",
                invalidates_feedback_ids=("self",),
            )
        )


def test_required_dependency_blocks_completion_even_when_prerequisite_is_optional() -> None:
    task = TaskSpec(
        task_id="dependent-task",
        requirement_schema_version=1,
        goal="Produce a supported answer",
        requirements=(
            RequirementSpec("sources", "Collect sources", required=False),
            RequirementSpec("answer", "Write answer", required=True),
        ),
        requirement_dependencies=(
            RequirementDependency(
                requirement_id="answer",
                depends_on_requirement_id="sources",
                kind=DependencyKind.REQUIRES,
            ),
        ),
        acceptance_rules=("answer and its prerequisites are satisfied",),
    )
    machine = ResidualStateMachine(task)

    answer_only = machine.apply_feedback(
        FeedbackEvent(
            feedback_id="answer-ok",
            task_id=task.task_id,
            action_id="answer-action",
            requirement_deltas=(
                RequirementDelta(
                    "answer", FeedbackDisposition.ACCEPTED, ("answer-evidence",)
                ),
            ),
            source_kind=FeedbackSourceKind.VERIFIER,
            confidence=1.0,
        )
    )

    assert answer_only.requirement("answer").status is RequirementStatus.SATISFIED
    assert answer_only.requirement("sources").required is True
    assert answer_only.complete is False

    complete = machine.apply_feedback(
        FeedbackEvent(
            feedback_id="sources-ok",
            task_id=task.task_id,
            action_id="sources-action",
            requirement_deltas=(
                RequirementDelta(
                    "sources", FeedbackDisposition.ACCEPTED, ("source-evidence",)
                ),
            ),
            source_kind=FeedbackSourceKind.VERIFIER,
            confidence=1.0,
        )
    )
    assert complete.complete is True


def test_identical_feedback_is_idempotent_but_conflicting_id_reuse_is_rejected() -> None:
    machine = ResidualStateMachine(_task())
    event = _feedback("f1", "sources", FeedbackDisposition.ACCEPTED, "source-check")

    first = machine.apply_feedback(event)
    duplicate = machine.apply_feedback(event)

    assert duplicate == first
    assert duplicate.revision == 1
    assert duplicate.applied_feedback_ids == ("f1",)

    reused_id = _feedback(
        "f1", "sources", FeedbackDisposition.REJECTED, "different-check"
    )
    with pytest.raises(ValueError, match="conflicting payload"):
        machine.apply_feedback(reused_id)


def test_schema_addition_replays_historical_feedback_for_the_new_dimension() -> None:
    task_v1 = _task()
    machine = ResidualStateMachine(task_v1)

    # A signal can be retained before schema review formally adds its dimension.
    machine.apply_feedback(
        _feedback("f-risk", "risk", FeedbackDisposition.ACCEPTED, "risk-check")
    )
    before_upgrade = machine.snapshot()
    assert "risk" not in before_upgrade.status_by_requirement()

    task_v2 = _task(
        version=2,
        requirements=task_v1.requirements
        + (RequirementSpec("risk", "Resolve material risks"),),
    )
    upgraded = machine.upgrade_schema(task_v2)

    assert upgraded.requirement_schema_version == 2
    assert upgraded.requirement("risk").status is RequirementStatus.SATISFIED
    assert upgraded.requirement("risk").supporting_evidence_refs == ("risk-check",)
    assert upgraded.requirement("risk").feedback_ids == ("f-risk",)


def test_new_dimension_without_historical_evidence_starts_unknown() -> None:
    task_v1 = _task()
    machine = ResidualStateMachine(task_v1)
    task_v2 = _task(
        version=2,
        requirements=task_v1.requirements
        + (RequirementSpec("risk", "Resolve material risks"),),
    )

    upgraded = machine.upgrade_schema(task_v2)

    assert upgraded.requirement("risk").status is RequirementStatus.UNKNOWN
    assert upgraded.complete is False


def test_schema_upgrade_only_allows_one_versioned_additive_change() -> None:
    task_v1 = _task()
    machine = ResidualStateMachine(task_v1)

    with pytest.raises(ValueError, match="next version"):
        machine.upgrade_schema(_task(version=3))

    changed_existing = _task(
        version=2,
        requirements=(
            RequirementSpec("sources", "Changed meaning"),
            RequirementSpec("answer", "Write the answer"),
        ),
    )
    with pytest.raises(ValueError, match="only add requirements"):
        machine.upgrade_schema(changed_existing)


def test_schema_upgrade_cannot_add_a_dependency_only_between_old_requirements() -> None:
    task_v1 = _task()
    machine = ResidualStateMachine(task_v1)
    task_v2 = TaskSpec(
        task_id=task_v1.task_id,
        requirement_schema_version=2,
        goal=task_v1.goal,
        requirements=task_v1.requirements
        + (RequirementSpec("risk", "Resolve material risks"),),
        requirement_dependencies=(
            RequirementDependency(
                requirement_id="answer",
                depends_on_requirement_id="sources",
                kind=DependencyKind.REQUIRES,
            ),
        ),
        constraints=task_v1.constraints,
        acceptance_rules=task_v1.acceptance_rules,
        resource_limits=task_v1.resource_limits,
    )

    with pytest.raises(ValueError, match="new requirement"):
        machine.upgrade_schema(task_v2)


def test_feedback_for_a_different_task_is_rejected() -> None:
    machine = ResidualStateMachine(_task())
    event = FeedbackEvent(
        feedback_id="f-other",
        task_id="other-task",
        action_id="a-other",
        requirement_deltas=(
            RequirementDelta(
                "sources", FeedbackDisposition.ACCEPTED, ("source-check",)
            ),
        ),
        source_kind=FeedbackSourceKind.VERIFIER,
        confidence=1.0,
    )

    with pytest.raises(ValueError, match="different task"):
        machine.apply_feedback(event)
