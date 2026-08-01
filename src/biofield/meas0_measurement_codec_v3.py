"""Strict offline restoration for the frozen Measurement Plane contracts."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from .measurement import (
    EpisodeEvidence,
    EpisodeGraph,
    EvaluationResult,
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
)
from .meas0_formal_runner import CanonicalEvaluationBinding, FormalRunnerError


class MeasurementCodecError(ValueError):
    """Serialized Measurement Plane evidence is not canonical or rederivable."""


@dataclass(frozen=True)
class SimulatedMeasurementCodecBoundary:
    """This codec restores structure; it grants no claim or execution authority."""

    claim_scope: str = field(default="simulated_nonclaim", init=False)
    production_authorized: bool = field(default=False, init=False)
    test_only: bool = field(default=True, init=False)


MEASUREMENT_CODEC_BOUNDARY = SimulatedMeasurementCodecBoundary()


T = TypeVar("T")


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MeasurementCodecError("sealed JSON contains duplicate fields")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise MeasurementCodecError(f"sealed JSON contains non-finite value: {value}")


def _decode_canonical_bytes(raw_bytes: bytes) -> object:
    try:
        value = json.loads(
            raw_bytes.decode("utf-8"),
            object_pairs_hook=_pairs_without_duplicates,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise MeasurementCodecError(
            "sealed measurement payload is not strict JSON"
        ) from error
    canonical = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if raw_bytes != canonical:
        raise MeasurementCodecError("sealed measurement bytes are not canonical")
    return value


def _strict_object(value: object, fields: set[str], label: str) -> dict[str, Any]:
    if type(value) is bytes:
        value = _decode_canonical_bytes(value)
    if type(value) is not dict or set(value) != fields:
        raise MeasurementCodecError(f"{label} fields are invalid")
    _strict_json_tree(value, label)
    return value


def _strict_json_tree(value: object, label: str) -> None:
    if value is None or type(value) in {str, int, bool}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise MeasurementCodecError(f"{label} contains a non-finite number")
        return
    if type(value) is list:
        for item in value:
            _strict_json_tree(item, label)
        return
    if type(value) is dict:
        if not all(type(key) is str for key in value):
            raise MeasurementCodecError(f"{label} contains a non-string key")
        for item in value.values():
            _strict_json_tree(item, label)
        return
    raise MeasurementCodecError(f"{label} contains a non-JSON value")


def _list(value: object, label: str) -> list[Any]:
    if type(value) is not list:
        raise MeasurementCodecError(f"{label} must be a list")
    return value


def _strings(value: object, label: str) -> tuple[str, ...]:
    values = _list(value, label)
    if not all(type(item) is str for item in values):
        raise MeasurementCodecError(f"{label} must contain strings")
    return tuple(values)


def _int(value: object, label: str) -> int:
    if type(value) is not int:
        raise MeasurementCodecError(f"{label} must be an integer")
    return value


def _float(value: object, label: str) -> int | float:
    if type(value) not in {int, float} or not math.isfinite(value):
        raise MeasurementCodecError(f"{label} must be a finite number")
    return value


def _enum(enum_type: type[T], value: object, label: str) -> T:
    if type(value) is not str:
        raise MeasurementCodecError(f"{label} must be an enum string")
    try:
        return enum_type(value)  # type: ignore[call-arg]
    except ValueError as error:
        raise MeasurementCodecError(f"{label} enum is invalid") from error


def _restore(
    factory: Callable[[], T],
    *,
    label: str,
) -> T:
    try:
        return factory()
    except (MeasurementContractError, FormalRunnerError) as error:
        raise MeasurementCodecError(f"{label} contract is invalid: {error}") from error


def restore_task_frame(value: object) -> TaskFrame:
    raw = _strict_object(
        value,
        {
            "task_id",
            "version",
            "subject_agent_id",
            "user_intent",
            "desired_state",
            "known_initial_state",
            "entities_and_scope",
            "constraints_and_permissions",
            "available_capabilities",
            "uncertainties_and_ambiguities",
            "risk_and_reversibility",
            "required_artifacts",
            "evidence_expectations",
            "provenance",
        },
        "TaskFrame",
    )
    return _restore(
        lambda: TaskFrame(
            task_id=raw["task_id"],
            version=_int(raw["version"], "TaskFrame version"),
            subject_agent_id=raw["subject_agent_id"],
            user_intent=raw["user_intent"],
            desired_state=raw["desired_state"],
            known_initial_state=raw["known_initial_state"],
            entities_and_scope=_strings(raw["entities_and_scope"], "entities"),
            constraints_and_permissions=_strings(
                raw["constraints_and_permissions"], "constraints"
            ),
            available_capabilities=_strings(
                raw["available_capabilities"], "capabilities"
            ),
            uncertainties_and_ambiguities=_strings(
                raw["uncertainties_and_ambiguities"], "uncertainties"
            ),
            risk_and_reversibility=_strings(raw["risk_and_reversibility"], "risk"),
            required_artifacts=_strings(raw["required_artifacts"], "artifacts"),
            evidence_expectations=_strings(
                raw["evidence_expectations"], "evidence expectations"
            ),
            provenance=_strings(raw["provenance"], "provenance"),
        ),
        label="TaskFrame",
    )


def _restore_goal(value: object) -> Goal:
    raw = _strict_object(
        value,
        {
            "goal_id",
            "desired_semantics",
            "critical",
            "provenance",
            "parent_goal_id",
            "dependency_goal_ids",
        },
        "Goal",
    )
    if type(raw["critical"]) is not bool:
        raise MeasurementCodecError("Goal critical must be boolean")
    if raw["parent_goal_id"] is not None and type(raw["parent_goal_id"]) is not str:
        raise MeasurementCodecError("Goal parent_goal_id is invalid")
    return _restore(
        lambda: Goal(
            goal_id=raw["goal_id"],
            desired_semantics=raw["desired_semantics"],
            critical=raw["critical"],
            provenance=_strings(raw["provenance"], "Goal provenance"),
            parent_goal_id=raw["parent_goal_id"],
            dependency_goal_ids=_strings(
                raw["dependency_goal_ids"], "Goal dependencies"
            ),
        ),
        label="Goal",
    )


def restore_goal_graph(value: object) -> GoalGraph:
    raw = _strict_object(
        value,
        {"graph_id", "version", "task_id", "task_frame_version", "goals", "provenance"},
        "GoalGraph",
    )
    goals = tuple(_restore_goal(item) for item in _list(raw["goals"], "goals"))
    return _restore(
        lambda: GoalGraph(
            graph_id=raw["graph_id"],
            version=_int(raw["version"], "GoalGraph version"),
            task_id=raw["task_id"],
            task_frame_version=_int(raw["task_frame_version"], "task_frame_version"),
            goals=goals,
            provenance=_strings(raw["provenance"], "GoalGraph provenance"),
        ),
        label="GoalGraph",
    )


def _restore_requirement(value: object) -> Requirement:
    raw = _strict_object(
        value,
        {
            "requirement_id",
            "goal_id",
            "success_semantics",
            "dimension",
            "critical",
            "provenance",
            "weight",
            "dependency_requirement_ids",
        },
        "Requirement",
    )
    if type(raw["critical"]) is not bool:
        raise MeasurementCodecError("Requirement critical must be boolean")
    return _restore(
        lambda: Requirement(
            requirement_id=raw["requirement_id"],
            goal_id=raw["goal_id"],
            success_semantics=raw["success_semantics"],
            dimension=_enum(
                MeasurementDimension, raw["dimension"], "Requirement dimension"
            ),
            critical=raw["critical"],
            provenance=_strings(raw["provenance"], "Requirement provenance"),
            weight=_float(raw["weight"], "Requirement weight"),
            dependency_requirement_ids=_strings(
                raw["dependency_requirement_ids"], "Requirement dependencies"
            ),
        ),
        label="Requirement",
    )


def restore_requirement_graph(value: object) -> RequirementGraph:
    raw = _strict_object(
        value,
        {
            "graph_id",
            "version",
            "schema_version",
            "goal_graph_id",
            "goal_graph_version",
            "requirements",
            "provenance",
        },
        "RequirementGraph",
    )
    requirements = tuple(
        _restore_requirement(item)
        for item in _list(raw["requirements"], "requirements")
    )
    return _restore(
        lambda: RequirementGraph(
            graph_id=raw["graph_id"],
            version=_int(raw["version"], "RequirementGraph version"),
            schema_version=_int(raw["schema_version"], "requirement schema"),
            goal_graph_id=raw["goal_graph_id"],
            goal_graph_version=_int(raw["goal_graph_version"], "goal graph version"),
            requirements=requirements,
            provenance=_strings(raw["provenance"], "RequirementGraph provenance"),
        ),
        label="RequirementGraph",
    )


def _restore_measurement_spec(value: object) -> MeasurementSpec:
    fields = {
        "measurement_id",
        "version",
        "target_requirement_id",
        "requirement_schema_version",
        "dimension",
        "kind",
        "measurand",
        "observation_source",
        "procedure",
        "unit_or_scale",
        "expected_coverage",
        "acceptance_rule",
        "uncertainty_rule",
        "calibration_ref",
        "cost_estimate",
        "evaluator_ref",
        "evaluator_version",
        "evaluator_authority",
        "provenance",
        "role",
    }
    raw = _strict_object(value, fields, "MeasurementSpec")
    return _restore(
        lambda: MeasurementSpec(
            measurement_id=raw["measurement_id"],
            version=_int(raw["version"], "MeasurementSpec version"),
            target_requirement_id=raw["target_requirement_id"],
            requirement_schema_version=_int(
                raw["requirement_schema_version"], "requirement schema"
            ),
            dimension=_enum(
                MeasurementDimension, raw["dimension"], "measurement dimension"
            ),
            kind=_enum(MeasurementKind, raw["kind"], "measurement kind"),
            measurand=raw["measurand"],
            observation_source=raw["observation_source"],
            procedure=raw["procedure"],
            unit_or_scale=raw["unit_or_scale"],
            expected_coverage=_float(raw["expected_coverage"], "expected coverage"),
            acceptance_rule=raw["acceptance_rule"],
            uncertainty_rule=raw["uncertainty_rule"],
            calibration_ref=raw["calibration_ref"],
            cost_estimate=_float(raw["cost_estimate"], "cost estimate"),
            evaluator_ref=raw["evaluator_ref"],
            evaluator_version=raw["evaluator_version"],
            evaluator_authority=_enum(
                EvaluatorAuthority, raw["evaluator_authority"], "evaluator authority"
            ),
            provenance=_strings(raw["provenance"], "MeasurementSpec provenance"),
            role=_enum(MeasurementRole, raw["role"], "measurement role"),
        ),
        label="MeasurementSpec",
    )


def restore_measurement_graph(value: object) -> MeasurementGraph:
    raw = _strict_object(
        value,
        {
            "graph_id",
            "version",
            "task_id",
            "requirement_graph_id",
            "requirement_schema_version",
            "measurement_specs",
            "hard_gate_measurement_ids",
            "provenance",
            "requirement_graph_version",
            "normal_coverage_threshold",
        },
        "MeasurementGraph",
    )
    specs = tuple(
        _restore_measurement_spec(item)
        for item in _list(raw["measurement_specs"], "measurement specs")
    )
    return _restore(
        lambda: MeasurementGraph(
            graph_id=raw["graph_id"],
            version=_int(raw["version"], "MeasurementGraph version"),
            task_id=raw["task_id"],
            requirement_graph_id=raw["requirement_graph_id"],
            requirement_schema_version=_int(
                raw["requirement_schema_version"], "requirement schema"
            ),
            measurement_specs=specs,
            hard_gate_measurement_ids=_strings(
                raw["hard_gate_measurement_ids"], "hard gates"
            ),
            provenance=_strings(raw["provenance"], "MeasurementGraph provenance"),
            requirement_graph_version=_int(
                raw["requirement_graph_version"], "requirement graph version"
            ),
            normal_coverage_threshold=_float(
                raw["normal_coverage_threshold"], "coverage threshold"
            ),
        ),
        label="MeasurementGraph",
    )


def restore_task_measurement_bundle(value: object) -> TaskMeasurementBundle:
    raw = _strict_object(
        value,
        {
            "bundle_id",
            "version",
            "task_frame",
            "goal_graph",
            "requirement_graph",
            "measurement_graph",
            "acceptance_rules",
            "deterministic_check_refs",
            "judge_refs",
            "metamorphic_relations",
            "uncertainty_and_escalation_rules",
            "measurement_budget",
            "component_hashes",
            "bundle_hash",
            "provenance",
        },
        "TaskMeasurementBundle",
    )
    bundle = _restore(
        lambda: seal_task_measurement_bundle(
            bundle_id=raw["bundle_id"],
            version=_int(raw["version"], "bundle version"),
            task_frame=restore_task_frame(raw["task_frame"]),
            goal_graph=restore_goal_graph(raw["goal_graph"]),
            requirement_graph=restore_requirement_graph(raw["requirement_graph"]),
            measurement_graph=restore_measurement_graph(raw["measurement_graph"]),
            acceptance_rules=_strings(raw["acceptance_rules"], "acceptance rules"),
            deterministic_check_refs=_strings(
                raw["deterministic_check_refs"], "deterministic refs"
            ),
            judge_refs=_strings(raw["judge_refs"], "judge refs"),
            metamorphic_relations=_strings(
                raw["metamorphic_relations"], "metamorphic relations"
            ),
            uncertainty_and_escalation_rules=_strings(
                raw["uncertainty_and_escalation_rules"], "uncertainty rules"
            ),
            measurement_budget=_float(raw["measurement_budget"], "measurement budget"),
            provenance=_strings(raw["provenance"], "bundle provenance"),
        ),
        label="TaskMeasurementBundle",
    )
    if bundle.to_dict() != raw:
        raise MeasurementCodecError(
            "TaskMeasurementBundle differs from source-derived bundle"
        )
    return bundle


def _restore_episode_evidence(value: object) -> EpisodeEvidence:
    raw = _strict_object(
        value,
        {
            "evidence_id",
            "kind",
            "locator",
            "content_hash",
            "provenance",
            "causal_parent_ids",
        },
        "EpisodeEvidence",
    )
    return _restore(
        lambda: EpisodeEvidence(
            evidence_id=raw["evidence_id"],
            kind=_enum(EvidenceKind, raw["kind"], "evidence kind"),
            locator=raw["locator"],
            content_hash=raw["content_hash"],
            provenance=_strings(raw["provenance"], "evidence provenance"),
            causal_parent_ids=_strings(raw["causal_parent_ids"], "causal parents"),
        ),
        label="EpisodeEvidence",
    )


def restore_episode_graph(value: object) -> EpisodeGraph:
    raw = _strict_object(
        value,
        {
            "episode_id",
            "version",
            "task_id",
            "task_frame_version",
            "evidence",
            "environment_state_ref",
            "trajectory_ref",
            "response_ref",
            "provenance",
            "artifact_refs",
        },
        "EpisodeGraph",
    )
    evidence = tuple(
        _restore_episode_evidence(item)
        for item in _list(raw["evidence"], "episode evidence")
    )
    return _restore(
        lambda: EpisodeGraph(
            episode_id=raw["episode_id"],
            version=_int(raw["version"], "episode version"),
            task_id=raw["task_id"],
            task_frame_version=_int(raw["task_frame_version"], "task frame version"),
            evidence=evidence,
            environment_state_ref=raw["environment_state_ref"],
            trajectory_ref=raw["trajectory_ref"],
            response_ref=raw["response_ref"],
            provenance=_strings(raw["provenance"], "episode provenance"),
            artifact_refs=_strings(raw["artifact_refs"], "artifact refs"),
        ),
        label="EpisodeGraph",
    )


def restore_sealed_episode(
    value: object,
    *,
    bundle: TaskMeasurementBundle,
) -> SealedEpisode:
    raw = _strict_object(
        value,
        {
            "bundle_id",
            "bundle_version",
            "bundle_hash",
            "episode_graph",
            "episode_hash",
            "provenance",
        },
        "SealedEpisode",
    )
    sealed = _restore(
        lambda: seal_episode_graph(
            task_measurement_bundle=bundle,
            episode_graph=restore_episode_graph(raw["episode_graph"]),
            provenance=_strings(raw["provenance"], "sealed episode provenance"),
        ),
        label="SealedEpisode",
    )
    if sealed.to_dict() != raw:
        raise MeasurementCodecError("SealedEpisode differs from source-derived episode")
    return sealed


def restore_measurement_observation(value: object) -> MeasurementObservation:
    raw = _strict_object(
        value,
        {
            "observation_id",
            "measurement_id",
            "measurement_version",
            "status",
            "observed_value",
            "evidence_refs",
            "provenance",
            "coverage",
            "uncertainty",
            "cost",
            "evaluator_ref",
            "evaluator_version",
        },
        "MeasurementObservation",
    )
    return _restore(
        lambda: MeasurementObservation(
            observation_id=raw["observation_id"],
            measurement_id=raw["measurement_id"],
            measurement_version=_int(raw["measurement_version"], "measurement version"),
            status=_enum(EvaluationStatus, raw["status"], "observation status"),
            observed_value=raw["observed_value"],
            evidence_refs=_strings(raw["evidence_refs"], "evidence refs"),
            provenance=_strings(raw["provenance"], "observation provenance"),
            coverage=_float(raw["coverage"], "observation coverage"),
            uncertainty=_float(raw["uncertainty"], "observation uncertainty"),
            cost=_float(raw["cost"], "observation cost"),
            evaluator_ref=raw["evaluator_ref"],
            evaluator_version=raw["evaluator_version"],
        ),
        label="MeasurementObservation",
    )


_EVALUATION_FIELDS = {
    "result_id",
    "version",
    "task_id",
    "bundle_id",
    "bundle_version",
    "bundle_hash",
    "measurement_graph_id",
    "measurement_graph_version",
    "episode_id",
    "episode_version",
    "episode_hash",
    "evaluator_set_hash",
    "requirement_statuses",
    "outcome",
    "noncritical_coverage",
    "safety_status",
    "efficiency_status",
    "semantic_status",
    "total_measurement_cost",
    "evidence_trace",
    "diagnostics",
    "provenance",
}


def restore_evaluation_result(
    value: object,
    *,
    bundle: TaskMeasurementBundle,
    sealed_episode: SealedEpisode,
    observations: tuple[MeasurementObservation, ...],
) -> EvaluationResult:
    raw = _strict_object(value, _EVALUATION_FIELDS, "EvaluationResult")
    if type(raw["result_id"]) is not str:
        raise MeasurementCodecError("EvaluationResult result_id must be a string")
    derived = _restore(
        lambda: fuse_evidence(
            result_id=raw["result_id"],
            task_measurement_bundle=bundle,
            sealed_episode=sealed_episode,
            observations=observations,
        ),
        label="canonical fusion",
    )
    if derived.to_dict() != raw:
        raise MeasurementCodecError(
            "EvaluationResult differs from source-derived canonical fusion"
        )
    return derived


def restore_canonical_evaluation_binding(
    value: object,
) -> CanonicalEvaluationBinding:
    raw = _strict_object(
        value,
        {
            "task_measurement_bundle",
            "sealed_episode",
            "observations",
            "evaluation_result",
        },
        "CanonicalEvaluationBinding",
    )
    bundle = restore_task_measurement_bundle(raw["task_measurement_bundle"])
    episode = restore_sealed_episode(raw["sealed_episode"], bundle=bundle)
    observations = tuple(
        restore_measurement_observation(item)
        for item in _list(raw["observations"], "observations")
    )
    result = restore_evaluation_result(
        raw["evaluation_result"],
        bundle=bundle,
        sealed_episode=episode,
        observations=observations,
    )
    return _restore(
        lambda: CanonicalEvaluationBinding(
            task_measurement_bundle=bundle,
            sealed_episode=episode,
            observations=observations,
            evaluation_result=result,
        ),
        label="CanonicalEvaluationBinding",
    )


def restore_canonical_evaluation_binding_bytes(
    raw_bytes: bytes,
) -> CanonicalEvaluationBinding:
    if type(raw_bytes) is not bytes:
        raise MeasurementCodecError("sealed measurement payload must be exact bytes")
    return restore_canonical_evaluation_binding(_decode_canonical_bytes(raw_bytes))


__all__ = [
    "MEASUREMENT_CODEC_BOUNDARY",
    "MeasurementCodecError",
    "SimulatedMeasurementCodecBoundary",
    "restore_canonical_evaluation_binding",
    "restore_canonical_evaluation_binding_bytes",
    "restore_episode_graph",
    "restore_evaluation_result",
    "restore_goal_graph",
    "restore_measurement_graph",
    "restore_measurement_observation",
    "restore_requirement_graph",
    "restore_sealed_episode",
    "restore_task_frame",
    "restore_task_measurement_bundle",
]
