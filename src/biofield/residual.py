from __future__ import annotations

from biofield.contracts import (
    DependencyKind,
    FeedbackDisposition,
    FeedbackEvent,
    RequirementResidual,
    RequirementStatus,
    ResidualSnapshot,
    TaskSpec,
)


def _extend_unique(existing: list[str], new_values: tuple[str, ...]) -> None:
    known = set(existing)
    for value in new_values:
        if value not in known:
            existing.append(value)
            known.add(value)


def _completion_required_ids(task: TaskSpec) -> frozenset[str]:
    required = {
        requirement.requirement_id
        for requirement in task.requirements
        if requirement.required
    }
    requires_by_requirement: dict[str, set[str]] = {}
    for dependency in task.requirement_dependencies:
        if dependency.kind is DependencyKind.REQUIRES:
            requires_by_requirement.setdefault(dependency.requirement_id, set()).add(
                dependency.depends_on_requirement_id
            )

    frontier = list(required)
    while frontier:
        requirement_id = frontier.pop()
        for prerequisite in requires_by_requirement.get(requirement_id, set()):
            if prerequisite not in required:
                required.add(prerequisite)
                frontier.append(prerequisite)
    return frozenset(required)


class ResidualStateMachine:
    """Deterministic B0 residual projection over an append-only feedback history.

    Feedback for a not-yet-declared requirement is retained but does not change
    the current snapshot. An additive schema upgrade replays that same history,
    which gives dimension addition a small, inspectable backfill mechanism.
    """

    def __init__(self, task: TaskSpec) -> None:
        if not isinstance(task, TaskSpec):
            raise TypeError("task must be a TaskSpec")
        self._task = task
        self._feedback_history: list[FeedbackEvent] = []
        self._feedback_by_id: dict[str, FeedbackEvent] = {}
        self._initial_status_by_requirement = {
            requirement.requirement_id: RequirementStatus.UNMET
            for requirement in task.requirements
        }
        self._completion_required = _completion_required_ids(task)
        self._revision = 0

    @property
    def task(self) -> TaskSpec:
        return self._task

    def feedback_history(self) -> tuple[FeedbackEvent, ...]:
        return tuple(self._feedback_history)

    def apply_feedback(self, event: FeedbackEvent) -> ResidualSnapshot:
        if not isinstance(event, FeedbackEvent):
            raise TypeError("event must be a FeedbackEvent")
        if event.task_id != self._task.task_id:
            raise ValueError("feedback belongs to a different task")

        previous = self._feedback_by_id.get(event.feedback_id)
        if previous is not None:
            if previous != event:
                raise ValueError(
                    f"feedback_id {event.feedback_id!r} was reused with a conflicting payload"
                )
            return self.snapshot()

        self._validate_invalidations(event)
        self._feedback_history.append(event)
        self._feedback_by_id[event.feedback_id] = event
        self._revision += 1
        return self.snapshot()

    def _validate_invalidations(self, event: FeedbackEvent) -> None:
        already_invalidated = {
            (delta.requirement_id, invalidated_feedback_id)
            for previous_event in self._feedback_history
            for delta in previous_event.requirement_deltas
            for invalidated_feedback_id in delta.invalidates_feedback_ids
        }
        for delta in event.requirement_deltas:
            for invalidated_feedback_id in delta.invalidates_feedback_ids:
                previous_event = self._feedback_by_id.get(invalidated_feedback_id)
                if previous_event is None:
                    raise ValueError(
                        "invalidates_feedback_ids must reference earlier feedback; "
                        "got unknown or non-earlier "
                        f"{invalidated_feedback_id!r}"
                    )
                if not any(
                    previous_delta.requirement_id == delta.requirement_id
                    for previous_delta in previous_event.requirement_deltas
                ):
                    raise ValueError(
                        "invalidated feedback must act on the same requirement"
                    )
                invalidation_key = (
                    delta.requirement_id,
                    invalidated_feedback_id,
                )
                if invalidation_key in already_invalidated:
                    raise ValueError(
                        f"feedback {invalidated_feedback_id!r} was already invalidated "
                        f"for requirement {delta.requirement_id!r}"
                    )

    def upgrade_schema(self, new_task: TaskSpec) -> ResidualSnapshot:
        if not isinstance(new_task, TaskSpec):
            raise TypeError("new_task must be a TaskSpec")
        if new_task.task_id != self._task.task_id:
            raise ValueError("schema belongs to a different task")
        expected_version = self._task.requirement_schema_version + 1
        if new_task.requirement_schema_version != expected_version:
            raise ValueError(
                "requirement_schema_version must be the next version "
                f"({expected_version})"
            )

        old_requirements = self._task.requirements
        new_prefix = new_task.requirements[: len(old_requirements)]
        if new_prefix != old_requirements or len(new_task.requirements) <= len(
            old_requirements
        ):
            raise ValueError("this B0 migration may only add requirements")
        if (
            new_task.goal != self._task.goal
            or new_task.constraints != self._task.constraints
            or new_task.acceptance_rules != self._task.acceptance_rules
            or new_task.resource_limits != self._task.resource_limits
        ):
            raise ValueError("this B0 migration may only add requirements")
        if not set(self._task.requirement_dependencies).issubset(
            new_task.requirement_dependencies
        ):
            raise ValueError("this B0 migration cannot remove dependencies")
        old_requirement_ids = {
            requirement.requirement_id for requirement in old_requirements
        }
        old_dependencies = set(self._task.requirement_dependencies)
        added_dependencies = set(new_task.requirement_dependencies) - old_dependencies
        if any(
            dependency.requirement_id in old_requirement_ids
            and dependency.depends_on_requirement_id in old_requirement_ids
            for dependency in added_dependencies
        ):
            raise ValueError(
                "an additive migration may only add dependencies involving a new requirement"
            )

        for requirement in new_task.requirements[len(old_requirements) :]:
            self._initial_status_by_requirement[
                requirement.requirement_id
            ] = RequirementStatus.UNKNOWN
        self._task = new_task
        self._completion_required = _completion_required_ids(new_task)
        self._revision += 1
        return self.snapshot()

    def snapshot(self) -> ResidualSnapshot:
        residuals: list[RequirementResidual] = []
        for requirement in self._task.requirements:
            requirement_id = requirement.requirement_id
            status = self._initial_status_by_requirement[requirement_id]
            supporting_evidence: list[str] = []
            conflicting_evidence: list[str] = []
            feedback_ids: list[str] = []
            invalidated_feedback_ids: list[str] = []
            accepted = False
            rejected = False
            explicitly_disputed = False

            # Invalidation is monotonic: invalidating an invalidator does not
            # resurrect the older feedback. This keeps replay deterministic and
            # makes every reactivation require a new explicit feedback event.
            for event in self._feedback_history:
                for delta in event.requirement_deltas:
                    if delta.requirement_id == requirement_id:
                        _extend_unique(
                            invalidated_feedback_ids,
                            delta.invalidates_feedback_ids,
                        )
            invalidated = set(invalidated_feedback_ids)

            for event in self._feedback_history:
                if event.feedback_id in invalidated:
                    continue
                for delta in event.requirement_deltas:
                    if delta.requirement_id != requirement_id:
                        continue
                    evidence = event.evidence_refs + delta.evidence_refs
                    feedback_ids.append(event.feedback_id)
                    if delta.disposition is FeedbackDisposition.ACCEPTED:
                        accepted = True
                        _extend_unique(supporting_evidence, evidence)
                    elif delta.disposition is FeedbackDisposition.REJECTED:
                        rejected = True
                        _extend_unique(conflicting_evidence, evidence)
                    else:
                        explicitly_disputed = True
                        _extend_unique(conflicting_evidence, evidence)

            if explicitly_disputed or (accepted and rejected):
                status = RequirementStatus.DISPUTED
            elif accepted:
                status = RequirementStatus.SATISFIED
            elif rejected:
                status = RequirementStatus.UNMET

            residuals.append(
                RequirementResidual(
                    requirement_id=requirement_id,
                    required=requirement_id in self._completion_required,
                    status=status,
                    supporting_evidence_refs=tuple(supporting_evidence),
                    conflicting_evidence_refs=tuple(conflicting_evidence),
                    feedback_ids=tuple(feedback_ids),
                    invalidated_feedback_ids=tuple(invalidated_feedback_ids),
                )
            )

        complete = all(
            not item.required or item.status is RequirementStatus.SATISFIED
            for item in residuals
        )
        return ResidualSnapshot(
            task_id=self._task.task_id,
            requirement_schema_version=self._task.requirement_schema_version,
            revision=self._revision,
            requirements=tuple(residuals),
            applied_feedback_ids=tuple(
                event.feedback_id for event in self._feedback_history
            ),
            complete=complete,
        )
