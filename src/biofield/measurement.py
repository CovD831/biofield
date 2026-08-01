from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .contracts import JsonContract, JsonScalar


class MeasurementContractError(ValueError):
    """Raised when a formal MEAS0 measurement contract is invalid."""


class EvaluationStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    DISPUTED = "disputed"
    INVALID = "invalid"


class MeasurementDimension(str, Enum):
    OUTCOME = "outcome"
    PROCESS = "process"
    SAFETY = "safety"
    EFFICIENCY = "efficiency"
    SEMANTIC = "semantic"


class MeasurementKind(str, Enum):
    DETERMINISTIC = "deterministic"
    JUDGE = "judge"
    HUMAN = "human"


class MeasurementRole(str, Enum):
    DECISIVE = "decisive"
    ADVISORY = "advisory"


class EvaluatorAuthority(str, Enum):
    HARNESS = "harness"
    EVALUATION_PLANE = "evaluation_plane"
    INDEPENDENT_JUDGE = "independent_judge"
    HUMAN = "human"
    SUBJECT_AGENT = "subject_agent"


class EvidenceKind(str, Enum):
    INPUT = "input"
    ACTION = "action"
    TOOL_RESULT = "tool_result"
    ENVIRONMENT_STATE = "environment_state"
    TRAJECTORY = "trajectory"
    ARTIFACT = "artifact"
    RESPONSE = "response"


def _text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise MeasurementContractError(f"{field_name} must be a non-empty string")


def _version(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MeasurementContractError(f"{field_name} must be a positive integer")


def _number(
    value: float,
    field_name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MeasurementContractError(f"{field_name} must be a finite number")
    if not math.isfinite(value):
        raise MeasurementContractError(f"{field_name} must be a finite number")
    if minimum is not None and value < minimum:
        raise MeasurementContractError(f"{field_name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise MeasurementContractError(f"{field_name} must be at most {maximum}")


def _text_tuple(
    owner: object,
    field_name: str,
    values: tuple[str, ...],
    *,
    required: bool = False,
) -> tuple[str, ...]:
    normalized = tuple(values)
    object.__setattr__(owner, field_name, normalized)
    if required and not normalized:
        raise MeasurementContractError(f"{field_name} cannot be empty")
    for value in normalized:
        _text(value, field_name)
    if len(set(normalized)) != len(normalized):
        raise MeasurementContractError(f"duplicate {field_name} are not allowed")
    return normalized


def _provenance(owner: object, values: tuple[str, ...]) -> tuple[str, ...]:
    return _text_tuple(owner, "provenance", values, required=True)


def _unique(values: tuple[Any, ...], field_name: str) -> None:
    if len(set(values)) != len(values):
        raise MeasurementContractError(f"duplicate {field_name} are not allowed")


def _canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256(value: str, field_name: str) -> None:
    _text(value, field_name)
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise MeasurementContractError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )


def _reject_cycles(
    references_by_id: dict[str, tuple[str, ...]],
    graph_name: str,
) -> None:
    active: set[str] = set()
    complete: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in complete:
            return
        if node_id in active:
            raise MeasurementContractError(f"{graph_name} contains a cycle")
        active.add(node_id)
        for referenced_id in references_by_id[node_id]:
            visit(referenced_id)
        active.remove(node_id)
        complete.add(node_id)

    for candidate_id in references_by_id:
        visit(candidate_id)


@dataclass(frozen=True, kw_only=True)
class TaskFrame(JsonContract):
    task_id: str
    version: int
    subject_agent_id: str
    user_intent: str
    desired_state: str
    known_initial_state: str
    entities_and_scope: tuple[str, ...]
    constraints_and_permissions: tuple[str, ...]
    available_capabilities: tuple[str, ...]
    uncertainties_and_ambiguities: tuple[str, ...]
    risk_and_reversibility: tuple[str, ...]
    required_artifacts: tuple[str, ...]
    evidence_expectations: tuple[str, ...]
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.task_id, "task_id")
        _version(self.version, "TaskFrame version")
        _text(self.subject_agent_id, "subject_agent_id")
        _text(self.user_intent, "user_intent")
        _text(self.desired_state, "desired_state")
        _text(self.known_initial_state, "known_initial_state")
        for field_name in (
            "entities_and_scope",
            "constraints_and_permissions",
            "available_capabilities",
            "uncertainties_and_ambiguities",
            "risk_and_reversibility",
            "required_artifacts",
        ):
            _text_tuple(self, field_name, getattr(self, field_name))
        _text_tuple(
            self,
            "evidence_expectations",
            self.evidence_expectations,
            required=True,
        )
        _provenance(self, self.provenance)


@dataclass(frozen=True, kw_only=True)
class Goal(JsonContract):
    goal_id: str
    desired_semantics: str
    critical: bool
    provenance: tuple[str, ...]
    parent_goal_id: str | None = None
    dependency_goal_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.goal_id, "goal_id")
        _text(self.desired_semantics, "desired_semantics")
        if not isinstance(self.critical, bool):
            raise MeasurementContractError("critical must be a boolean")
        if self.parent_goal_id is not None:
            _text(self.parent_goal_id, "parent_goal_id")
            if self.parent_goal_id == self.goal_id:
                raise MeasurementContractError("a goal cannot be its own parent")
        dependencies = _text_tuple(
            self, "dependency_goal_ids", self.dependency_goal_ids
        )
        if self.goal_id in dependencies:
            raise MeasurementContractError("a goal cannot depend on itself")
        _provenance(self, self.provenance)


@dataclass(frozen=True, kw_only=True)
class GoalGraph(JsonContract):
    graph_id: str
    version: int
    task_id: str
    task_frame_version: int
    goals: tuple[Goal, ...]
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "goals", tuple(self.goals))
        _text(self.graph_id, "GoalGraph graph_id")
        _version(self.version, "GoalGraph version")
        _text(self.task_id, "GoalGraph task_id")
        _version(self.task_frame_version, "task_frame_version")
        if not self.goals or not all(isinstance(item, Goal) for item in self.goals):
            raise MeasurementContractError("goals must contain Goal values")
        goal_ids = tuple(item.goal_id for item in self.goals)
        _unique(goal_ids, "goal_ids")
        known = set(goal_ids)
        for goal in self.goals:
            refs = set(goal.dependency_goal_ids)
            if goal.parent_goal_id is not None:
                refs.add(goal.parent_goal_id)
            if not refs <= known:
                raise MeasurementContractError("goal references an unknown goal")
        _reject_cycles(
            {
                goal.goal_id: (
                    *goal.dependency_goal_ids,
                    *((goal.parent_goal_id,) if goal.parent_goal_id else ()),
                )
                for goal in self.goals
            },
            "goal graph",
        )
        _provenance(self, self.provenance)


@dataclass(frozen=True, kw_only=True)
class Requirement(JsonContract):
    requirement_id: str
    goal_id: str
    success_semantics: str
    dimension: MeasurementDimension
    critical: bool
    provenance: tuple[str, ...]
    weight: float = 1.0
    dependency_requirement_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.requirement_id, "requirement_id")
        _text(self.goal_id, "goal_id")
        _text(self.success_semantics, "success_semantics")
        if not isinstance(self.dimension, MeasurementDimension):
            raise MeasurementContractError("dimension must be a MeasurementDimension")
        if not isinstance(self.critical, bool):
            raise MeasurementContractError("critical must be a boolean")
        _number(self.weight, "weight", minimum=0.0)
        dependencies = _text_tuple(
            self,
            "dependency_requirement_ids",
            self.dependency_requirement_ids,
        )
        if self.requirement_id in dependencies:
            raise MeasurementContractError("a requirement cannot depend on itself")
        _provenance(self, self.provenance)


@dataclass(frozen=True, kw_only=True)
class RequirementGraph(JsonContract):
    graph_id: str
    version: int
    schema_version: int
    goal_graph_id: str
    goal_graph_version: int
    requirements: tuple[Requirement, ...]
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "requirements", tuple(self.requirements))
        _text(self.graph_id, "RequirementGraph graph_id")
        _version(self.version, "RequirementGraph version")
        _version(self.schema_version, "requirement schema_version")
        _text(self.goal_graph_id, "goal_graph_id")
        _version(self.goal_graph_version, "goal_graph_version")
        if not self.requirements or not all(
            isinstance(item, Requirement) for item in self.requirements
        ):
            raise MeasurementContractError(
                "requirements must contain Requirement values"
            )
        requirement_ids = tuple(item.requirement_id for item in self.requirements)
        _unique(requirement_ids, "requirement_ids")
        known = set(requirement_ids)
        for requirement in self.requirements:
            if not set(requirement.dependency_requirement_ids) <= known:
                raise MeasurementContractError(
                    "requirement references an unknown requirement"
                )
        _reject_cycles(
            {
                requirement.requirement_id: requirement.dependency_requirement_ids
                for requirement in self.requirements
            },
            "requirement graph",
        )
        _provenance(self, self.provenance)


@dataclass(frozen=True, kw_only=True)
class MeasurementSpec(JsonContract):
    measurement_id: str
    version: int
    target_requirement_id: str
    requirement_schema_version: int
    dimension: MeasurementDimension
    kind: MeasurementKind
    measurand: str
    observation_source: str
    procedure: str
    unit_or_scale: str
    expected_coverage: float
    acceptance_rule: str
    uncertainty_rule: str
    calibration_ref: str
    cost_estimate: float
    evaluator_ref: str
    evaluator_version: str
    evaluator_authority: EvaluatorAuthority
    provenance: tuple[str, ...]
    role: MeasurementRole = MeasurementRole.DECISIVE

    def __post_init__(self) -> None:
        for field_name in (
            "measurement_id",
            "target_requirement_id",
            "measurand",
            "observation_source",
            "procedure",
            "unit_or_scale",
            "acceptance_rule",
            "uncertainty_rule",
            "calibration_ref",
            "evaluator_ref",
            "evaluator_version",
        ):
            _text(getattr(self, field_name), field_name)
        _version(self.version, "MeasurementSpec version")
        _version(self.requirement_schema_version, "requirement_schema_version")
        if not isinstance(self.dimension, MeasurementDimension):
            raise MeasurementContractError("dimension must be a MeasurementDimension")
        if not isinstance(self.kind, MeasurementKind):
            raise MeasurementContractError("kind must be a MeasurementKind")
        if not isinstance(self.evaluator_authority, EvaluatorAuthority):
            raise MeasurementContractError(
                "evaluator_authority must be an EvaluatorAuthority"
            )
        if not isinstance(self.role, MeasurementRole):
            raise MeasurementContractError("role must be a MeasurementRole")
        if self.evaluator_authority is EvaluatorAuthority.SUBJECT_AGENT:
            raise MeasurementContractError(
                "Agent-owned formal evaluators are not allowed"
            )
        if self.kind is MeasurementKind.JUDGE:
            if self.dimension is not MeasurementDimension.SEMANTIC:
                raise MeasurementContractError(
                    "Judge measurements are limited to the semantic dimension"
                )
            if self.evaluator_authority is not EvaluatorAuthority.INDEPENDENT_JUDGE:
                raise MeasurementContractError(
                    "Judge measurements require an independent Judge"
                )
        if (
            self.evaluator_authority is EvaluatorAuthority.INDEPENDENT_JUDGE
            and self.kind is not MeasurementKind.JUDGE
        ):
            raise MeasurementContractError(
                "independent Judge authority requires a Judge measurement"
            )
        _number(self.expected_coverage, "expected_coverage", minimum=0.0, maximum=1.0)
        _number(self.cost_estimate, "cost_estimate", minimum=0.0)
        _provenance(self, self.provenance)


@dataclass(frozen=True, kw_only=True)
class MeasurementGraph(JsonContract):
    graph_id: str
    version: int
    task_id: str
    requirement_graph_id: str
    requirement_schema_version: int
    measurement_specs: tuple[MeasurementSpec, ...]
    hard_gate_measurement_ids: tuple[str, ...]
    provenance: tuple[str, ...]
    requirement_graph_version: int = 1
    normal_coverage_threshold: float = 0.80

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "measurement_specs", tuple(self.measurement_specs)
        )
        _text(self.graph_id, "MeasurementGraph graph_id")
        _version(self.version, "MeasurementGraph version")
        _text(self.task_id, "MeasurementGraph task_id")
        _text(self.requirement_graph_id, "requirement_graph_id")
        _version(self.requirement_graph_version, "requirement_graph_version")
        _version(self.requirement_schema_version, "requirement_schema_version")
        if not self.measurement_specs or not all(
            isinstance(item, MeasurementSpec) for item in self.measurement_specs
        ):
            raise MeasurementContractError(
                "measurement_specs must contain MeasurementSpec values"
            )
        measurement_ids = tuple(
            item.measurement_id for item in self.measurement_specs
        )
        _unique(measurement_ids, "measurement_ids")
        for spec in self.measurement_specs:
            if spec.requirement_schema_version != self.requirement_schema_version:
                raise MeasurementContractError(
                    "MeasurementSpec has a stale requirement schema version"
                )
        gates = _text_tuple(
            self,
            "hard_gate_measurement_ids",
            self.hard_gate_measurement_ids,
            required=True,
        )
        if not set(gates) <= set(measurement_ids):
            raise MeasurementContractError(
                "hard gate references an unknown measurement"
            )
        specs_by_id = {
            item.measurement_id: item for item in self.measurement_specs
        }
        if any(
            specs_by_id[measurement_id].kind is MeasurementKind.JUDGE
            for measurement_id in gates
        ):
            raise MeasurementContractError("Judge measurement cannot be a hard gate")
        if any(
            specs_by_id[measurement_id].role is not MeasurementRole.DECISIVE
            for measurement_id in gates
        ):
            raise MeasurementContractError(
                "hard gate measurement must have the decisive role"
            )
        _number(
            self.normal_coverage_threshold,
            "normal_coverage_threshold",
            minimum=0.0,
            maximum=1.0,
        )
        _provenance(self, self.provenance)


_TASK_MEASUREMENT_COMPONENT_NAMES = (
    "task_frame.json",
    "goal_graph.json",
    "requirement_graph.json",
    "measurement_graph.json",
    "bundle_manifest.json",
)


def _task_measurement_component_hashes(
    *,
    task_frame: TaskFrame,
    goal_graph: GoalGraph,
    requirement_graph: RequirementGraph,
    measurement_graph: MeasurementGraph,
    bundle_id: str,
    version: int,
    acceptance_rules: tuple[str, ...],
    deterministic_check_refs: tuple[str, ...],
    judge_refs: tuple[str, ...],
    metamorphic_relations: tuple[str, ...],
    uncertainty_and_escalation_rules: tuple[str, ...],
    measurement_budget: float,
    provenance: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    contracts = (
        task_frame.to_dict(),
        goal_graph.to_dict(),
        requirement_graph.to_dict(),
        measurement_graph.to_dict(),
        {
            "bundle_id": bundle_id,
            "version": version,
            "acceptance_rules": list(acceptance_rules),
            "deterministic_check_refs": list(deterministic_check_refs),
            "judge_refs": list(judge_refs),
            "metamorphic_relations": list(metamorphic_relations),
            "uncertainty_and_escalation_rules": list(
                uncertainty_and_escalation_rules
            ),
            "measurement_budget": measurement_budget,
            "provenance": list(provenance),
        },
    )
    return tuple(
        (name, _canonical_json_sha256(contract))
        for name, contract in zip(
            _TASK_MEASUREMENT_COMPONENT_NAMES,
            contracts,
            strict=True,
        )
    )


def _task_measurement_bundle_hash(
    *,
    component_hashes: tuple[tuple[str, str], ...],
) -> str:
    manifest = b"".join(
        f"{path}\0{digest}\n".encode("utf-8")
        for path, digest in sorted(component_hashes)
    )
    return hashlib.sha256(manifest).hexdigest()


@dataclass(frozen=True, kw_only=True)
class TaskMeasurementBundle(JsonContract):
    """A content-addressed, immutable pre-execution measurement package."""

    bundle_id: str
    version: int
    task_frame: TaskFrame
    goal_graph: GoalGraph
    requirement_graph: RequirementGraph
    measurement_graph: MeasurementGraph
    acceptance_rules: tuple[str, ...]
    deterministic_check_refs: tuple[str, ...]
    judge_refs: tuple[str, ...]
    metamorphic_relations: tuple[str, ...]
    uncertainty_and_escalation_rules: tuple[str, ...]
    measurement_budget: float
    component_hashes: tuple[tuple[str, str], ...]
    bundle_hash: str
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.bundle_id, "bundle_id")
        _version(self.version, "TaskMeasurementBundle version")
        for field_name, expected_type in (
            ("task_frame", TaskFrame),
            ("goal_graph", GoalGraph),
            ("requirement_graph", RequirementGraph),
            ("measurement_graph", MeasurementGraph),
        ):
            if not isinstance(getattr(self, field_name), expected_type):
                raise MeasurementContractError(
                    f"{field_name} must be a {expected_type.__name__}"
                )
        _validate_task_measurement_contracts(
            self.task_frame,
            self.goal_graph,
            self.requirement_graph,
            self.measurement_graph,
        )
        for field_name in (
            "acceptance_rules",
            "uncertainty_and_escalation_rules",
        ):
            _text_tuple(
                self,
                field_name,
                getattr(self, field_name),
                required=True,
            )
        for field_name in (
            "deterministic_check_refs",
            "judge_refs",
            "metamorphic_relations",
        ):
            _text_tuple(self, field_name, getattr(self, field_name))
        _number(self.measurement_budget, "measurement_budget", minimum=0.0)
        _provenance(self, self.provenance)

        deterministic_refs = {
            spec.evaluator_ref
            for spec in self.measurement_graph.measurement_specs
            if spec.kind is MeasurementKind.DETERMINISTIC
        }
        if set(self.deterministic_check_refs) != deterministic_refs:
            raise MeasurementContractError(
                "deterministic_check_refs must exactly match frozen deterministic "
                "evaluators"
            )
        frozen_judge_refs = {
            spec.evaluator_ref
            for spec in self.measurement_graph.measurement_specs
            if spec.kind is MeasurementKind.JUDGE
        }
        if set(self.judge_refs) != frozen_judge_refs:
            raise MeasurementContractError(
                "judge_refs must exactly match frozen Judge evaluators"
            )

        component_hashes = tuple(
            tuple(item) for item in self.component_hashes
        )
        object.__setattr__(self, "component_hashes", component_hashes)
        if any(len(item) != 2 for item in component_hashes):
            raise MeasurementContractError(
                "component_hashes must contain path and digest pairs"
            )
        for name, digest in component_hashes:
            _text(name, "component hash path")
            _sha256(digest, "component hash")
        expected_component_hashes = _task_measurement_component_hashes(
            task_frame=self.task_frame,
            goal_graph=self.goal_graph,
            requirement_graph=self.requirement_graph,
            measurement_graph=self.measurement_graph,
            bundle_id=self.bundle_id,
            version=self.version,
            acceptance_rules=self.acceptance_rules,
            deterministic_check_refs=self.deterministic_check_refs,
            judge_refs=self.judge_refs,
            metamorphic_relations=self.metamorphic_relations,
            uncertainty_and_escalation_rules=self.uncertainty_and_escalation_rules,
            measurement_budget=self.measurement_budget,
            provenance=self.provenance,
        )
        if component_hashes != expected_component_hashes:
            raise MeasurementContractError(
                "TaskMeasurementBundle bundle seal mismatch: component hash changed"
            )

        _sha256(self.bundle_hash, "bundle_hash")
        expected_bundle_hash = _task_measurement_bundle_hash(
            component_hashes=component_hashes,
        )
        if self.bundle_hash != expected_bundle_hash:
            raise MeasurementContractError("TaskMeasurementBundle bundle seal mismatch")


@dataclass(frozen=True, kw_only=True)
class EpisodeEvidence(JsonContract):
    evidence_id: str
    kind: EvidenceKind
    locator: str
    content_hash: str
    provenance: tuple[str, ...]
    causal_parent_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.evidence_id, "evidence_id")
        if not isinstance(self.kind, EvidenceKind):
            raise MeasurementContractError("kind must be an EvidenceKind")
        _text(self.locator, "locator")
        _text(self.content_hash, "content_hash")
        _text_tuple(self, "causal_parent_ids", self.causal_parent_ids)
        _provenance(self, self.provenance)


@dataclass(frozen=True, kw_only=True)
class EpisodeGraph(JsonContract):
    episode_id: str
    version: int
    task_id: str
    task_frame_version: int
    evidence: tuple[EpisodeEvidence, ...]
    environment_state_ref: str
    trajectory_ref: str
    response_ref: str
    provenance: tuple[str, ...]
    artifact_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", tuple(self.evidence))
        _text(self.episode_id, "episode_id")
        _version(self.version, "EpisodeGraph version")
        _text(self.task_id, "EpisodeGraph task_id")
        _version(self.task_frame_version, "task_frame_version")
        if not self.evidence or not all(
            isinstance(item, EpisodeEvidence) for item in self.evidence
        ):
            raise MeasurementContractError(
                "evidence must contain EpisodeEvidence values"
            )
        evidence_ids = tuple(item.evidence_id for item in self.evidence)
        _unique(evidence_ids, "evidence_ids")
        known = set(evidence_ids)
        seen: set[str] = set()
        for item in self.evidence:
            parents = set(item.causal_parent_ids)
            if not parents <= known:
                raise MeasurementContractError(
                    "evidence references an unknown causal parent"
                )
            if item.kind is EvidenceKind.INPUT:
                if parents:
                    raise MeasurementContractError(
                        "input evidence cannot have a causal parent"
                    )
            elif not parents:
                raise MeasurementContractError(
                    "non-input evidence requires a causal parent"
                )
            if not parents <= seen:
                raise MeasurementContractError(
                    "causal parent must precede child evidence"
                )
            seen.add(item.evidence_id)
        for field_name in (
            "environment_state_ref",
            "trajectory_ref",
            "response_ref",
        ):
            _text(getattr(self, field_name), field_name)
            if getattr(self, field_name) not in known:
                raise MeasurementContractError(
                    f"{field_name} references unknown episode evidence"
                )
        artifacts = _text_tuple(self, "artifact_refs", self.artifact_refs)
        if not set(artifacts) <= known:
            raise MeasurementContractError(
                "artifact_refs reference unknown episode evidence"
            )
        kinds_by_id = {item.evidence_id: item.kind for item in self.evidence}
        expected_kinds = (
            (self.environment_state_ref, EvidenceKind.ENVIRONMENT_STATE),
            (self.trajectory_ref, EvidenceKind.TRAJECTORY),
            (self.response_ref, EvidenceKind.RESPONSE),
        )
        if any(kinds_by_id[ref] is not kind for ref, kind in expected_kinds):
            raise MeasurementContractError(
                "EpisodeGraph canonical references have incompatible evidence kinds"
            )
        if any(kinds_by_id[ref] is not EvidenceKind.ARTIFACT for ref in artifacts):
            raise MeasurementContractError("artifact_refs must reference artifacts")
        _provenance(self, self.provenance)


def _episode_graph_hash(episode_graph: EpisodeGraph) -> str:
    return _canonical_json_sha256(episode_graph.to_dict())


@dataclass(frozen=True, kw_only=True)
class SealedEpisode(JsonContract):
    """An immutable EpisodeGraph content hash bound to one measurement bundle."""

    bundle_id: str
    bundle_version: int
    bundle_hash: str
    episode_graph: EpisodeGraph
    episode_hash: str
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.bundle_id, "bundle_id")
        _version(self.bundle_version, "bundle_version")
        _sha256(self.bundle_hash, "bundle_hash")
        if not isinstance(self.episode_graph, EpisodeGraph):
            raise MeasurementContractError(
                "episode_graph must be an EpisodeGraph"
            )
        _sha256(self.episode_hash, "episode_hash")
        _provenance(self, self.provenance)
        if self.episode_hash != _episode_graph_hash(self.episode_graph):
            raise MeasurementContractError("SealedEpisode episode seal mismatch")


@dataclass(frozen=True, kw_only=True)
class MeasurementObservation(JsonContract):
    observation_id: str
    measurement_id: str
    measurement_version: int
    status: EvaluationStatus
    observed_value: JsonScalar
    evidence_refs: tuple[str, ...]
    provenance: tuple[str, ...]
    coverage: float
    uncertainty: float
    cost: float
    evaluator_ref: str
    evaluator_version: str

    def __post_init__(self) -> None:
        _text(self.observation_id, "observation_id")
        _text(self.measurement_id, "measurement_id")
        _version(self.measurement_version, "measurement_version")
        if not isinstance(self.status, EvaluationStatus):
            raise MeasurementContractError("status must be an EvaluationStatus")
        if not (
            self.observed_value is None
            or isinstance(self.observed_value, (str, int, float, bool))
        ):
            raise MeasurementContractError("observed_value must be a JSON scalar")
        _text_tuple(self, "evidence_refs", self.evidence_refs, required=True)
        _provenance(self, self.provenance)
        _number(self.coverage, "coverage", minimum=0.0, maximum=1.0)
        _number(self.uncertainty, "uncertainty", minimum=0.0, maximum=1.0)
        _number(self.cost, "cost", minimum=0.0)
        _text(self.evaluator_ref, "evaluator_ref")
        _text(self.evaluator_version, "evaluator_version")


@dataclass(frozen=True, kw_only=True)
class EvaluationResult(JsonContract):
    result_id: str
    version: int
    task_id: str
    bundle_id: str
    bundle_version: int
    bundle_hash: str
    measurement_graph_id: str
    measurement_graph_version: int
    episode_id: str
    episode_version: int
    episode_hash: str
    evaluator_set_hash: str
    requirement_statuses: tuple[tuple[str, EvaluationStatus], ...]
    outcome: EvaluationStatus
    noncritical_coverage: float
    safety_status: EvaluationStatus
    efficiency_status: EvaluationStatus
    semantic_status: EvaluationStatus
    total_measurement_cost: float
    evidence_trace: tuple[str, ...]
    diagnostics: tuple[str, ...]
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "requirement_statuses", tuple(self.requirement_statuses)
        )
        _text(self.result_id, "result_id")
        _version(self.version, "EvaluationResult version")
        _text(self.task_id, "task_id")
        _text(self.bundle_id, "bundle_id")
        _version(self.bundle_version, "bundle_version")
        _sha256(self.bundle_hash, "bundle_hash")
        _text(self.measurement_graph_id, "measurement_graph_id")
        _version(self.measurement_graph_version, "measurement_graph_version")
        _text(self.episode_id, "episode_id")
        _version(self.episode_version, "episode_version")
        _sha256(self.episode_hash, "episode_hash")
        _sha256(self.evaluator_set_hash, "evaluator_set_hash")
        requirement_ids: list[str] = []
        for requirement_id, status in self.requirement_statuses:
            _text(requirement_id, "requirement_id")
            if not isinstance(status, EvaluationStatus):
                raise MeasurementContractError(
                    "requirement status must be an EvaluationStatus"
                )
            requirement_ids.append(requirement_id)
        _unique(tuple(requirement_ids), "requirement result IDs")
        for field_name in (
            "outcome",
            "safety_status",
            "efficiency_status",
            "semantic_status",
        ):
            if not isinstance(getattr(self, field_name), EvaluationStatus):
                raise MeasurementContractError(
                    f"{field_name} must be an EvaluationStatus"
                )
        _number(
            self.noncritical_coverage,
            "noncritical_coverage",
            minimum=0.0,
            maximum=1.0,
        )
        _number(
            self.total_measurement_cost,
            "total_measurement_cost",
            minimum=0.0,
        )
        _text_tuple(self, "evidence_trace", self.evidence_trace, required=True)
        _text_tuple(self, "diagnostics", self.diagnostics)
        _provenance(self, self.provenance)


def _validate_task_measurement_contracts(
    task_frame: TaskFrame,
    goal_graph: GoalGraph,
    requirement_graph: RequirementGraph,
    measurement_graph: MeasurementGraph,
) -> None:
    if goal_graph.task_id != task_frame.task_id:
        raise MeasurementContractError("GoalGraph references the wrong task")
    if goal_graph.task_frame_version != task_frame.version:
        raise MeasurementContractError("GoalGraph has a stale TaskFrame version")
    if requirement_graph.goal_graph_id != goal_graph.graph_id:
        raise MeasurementContractError(
            "RequirementGraph references the wrong GoalGraph"
        )
    if requirement_graph.goal_graph_version != goal_graph.version:
        raise MeasurementContractError("RequirementGraph has a stale GoalGraph version")
    goal_ids = {item.goal_id for item in goal_graph.goals}
    if any(item.goal_id not in goal_ids for item in requirement_graph.requirements):
        raise MeasurementContractError("requirement references an unknown goal")
    if measurement_graph.task_id != task_frame.task_id:
        raise MeasurementContractError("MeasurementGraph references the wrong task")
    if measurement_graph.requirement_graph_id != requirement_graph.graph_id:
        raise MeasurementContractError(
            "MeasurementGraph references the wrong RequirementGraph"
        )
    if measurement_graph.requirement_graph_version != requirement_graph.version:
        raise MeasurementContractError(
            "MeasurementGraph has a stale RequirementGraph version"
        )
    if (
        measurement_graph.requirement_schema_version
        != requirement_graph.schema_version
    ):
        raise MeasurementContractError(
            "MeasurementGraph has a stale requirement schema version"
        )
    requirement_ids = {
        item.requirement_id for item in requirement_graph.requirements
    }
    measured_ids = {
        item.target_requirement_id for item in measurement_graph.measurement_specs
    }
    unknown = measured_ids - requirement_ids
    if unknown:
        raise MeasurementContractError(
            f"MeasurementSpec references an unknown requirement: {sorted(unknown)!r}"
        )
    missing = requirement_ids - measured_ids
    if missing:
        raise MeasurementContractError(
            f"requirements have no measurement: {sorted(missing)!r}"
        )
    requirements_by_id = {
        item.requirement_id: item for item in requirement_graph.requirements
    }
    for spec in measurement_graph.measurement_specs:
        requirement = requirements_by_id[spec.target_requirement_id]
        if spec.dimension is not requirement.dimension:
            raise MeasurementContractError(
                "MeasurementSpec dimension must match its target Requirement dimension"
            )
        if (
            spec.kind is MeasurementKind.JUDGE
            and requirement.dimension is not MeasurementDimension.SEMANTIC
        ):
            raise MeasurementContractError(
                "Judge can only target a semantic requirement"
            )
    for requirement_id in requirement_ids:
        decisive_count = sum(
            spec.target_requirement_id == requirement_id
            and spec.role is MeasurementRole.DECISIVE
            for spec in measurement_graph.measurement_specs
        )
        if decisive_count != 1:
            raise MeasurementContractError(
                "each requirement must have exactly one decisive measurement"
            )


def seal_task_measurement_bundle(
    *,
    bundle_id: str,
    version: int,
    task_frame: TaskFrame,
    goal_graph: GoalGraph,
    requirement_graph: RequirementGraph,
    measurement_graph: MeasurementGraph,
    acceptance_rules: tuple[str, ...],
    deterministic_check_refs: tuple[str, ...],
    judge_refs: tuple[str, ...],
    metamorphic_relations: tuple[str, ...],
    uncertainty_and_escalation_rules: tuple[str, ...],
    measurement_budget: float,
    provenance: tuple[str, ...],
) -> TaskMeasurementBundle:
    """Validate and content-address a pre-execution TaskMeasurementBundle."""

    component_hashes = _task_measurement_component_hashes(
        task_frame=task_frame,
        goal_graph=goal_graph,
        requirement_graph=requirement_graph,
        measurement_graph=measurement_graph,
        bundle_id=bundle_id,
        version=version,
        acceptance_rules=tuple(acceptance_rules),
        deterministic_check_refs=tuple(deterministic_check_refs),
        judge_refs=tuple(judge_refs),
        metamorphic_relations=tuple(metamorphic_relations),
        uncertainty_and_escalation_rules=tuple(
            uncertainty_and_escalation_rules
        ),
        measurement_budget=measurement_budget,
        provenance=tuple(provenance),
    )
    bundle_hash = _task_measurement_bundle_hash(
        component_hashes=component_hashes,
    )
    return TaskMeasurementBundle(
        bundle_id=bundle_id,
        version=version,
        task_frame=task_frame,
        goal_graph=goal_graph,
        requirement_graph=requirement_graph,
        measurement_graph=measurement_graph,
        acceptance_rules=tuple(acceptance_rules),
        deterministic_check_refs=tuple(deterministic_check_refs),
        judge_refs=tuple(judge_refs),
        metamorphic_relations=tuple(metamorphic_relations),
        uncertainty_and_escalation_rules=tuple(
            uncertainty_and_escalation_rules
        ),
        measurement_budget=measurement_budget,
        component_hashes=component_hashes,
        bundle_hash=bundle_hash,
        provenance=tuple(provenance),
    )


def validate_task_measurement_bundle(bundle: TaskMeasurementBundle) -> None:
    """Revalidate a sealed bundle at a trust boundary."""

    if not isinstance(bundle, TaskMeasurementBundle):
        raise MeasurementContractError(
            "bundle must be a TaskMeasurementBundle"
        )
    bundle.__post_init__()


def validate_measurement_bundle(
    task_frame: TaskFrame,
    goal_graph: GoalGraph,
    requirement_graph: RequirementGraph,
    measurement_graph: MeasurementGraph,
    episode_graph: EpisodeGraph,
) -> None:
    """Validate task measurement contracts plus an executed EpisodeGraph."""

    _validate_task_measurement_contracts(
        task_frame,
        goal_graph,
        requirement_graph,
        measurement_graph,
    )
    if episode_graph.task_id != task_frame.task_id:
        raise MeasurementContractError("EpisodeGraph references the wrong task")
    if episode_graph.task_frame_version != task_frame.version:
        raise MeasurementContractError("EpisodeGraph has a stale TaskFrame version")


def seal_episode_graph(
    *,
    task_measurement_bundle: TaskMeasurementBundle,
    episode_graph: EpisodeGraph,
    provenance: tuple[str, ...],
) -> SealedEpisode:
    """Validate and seal an EpisodeGraph against one frozen measurement bundle."""

    validate_task_measurement_bundle(task_measurement_bundle)
    validate_measurement_bundle(
        task_measurement_bundle.task_frame,
        task_measurement_bundle.goal_graph,
        task_measurement_bundle.requirement_graph,
        task_measurement_bundle.measurement_graph,
        episode_graph,
    )
    return SealedEpisode(
        bundle_id=task_measurement_bundle.bundle_id,
        bundle_version=task_measurement_bundle.version,
        bundle_hash=task_measurement_bundle.bundle_hash,
        episode_graph=episode_graph,
        episode_hash=_episode_graph_hash(episode_graph),
        provenance=tuple(provenance),
    )


def validate_sealed_episode(
    sealed_episode: SealedEpisode,
    *,
    task_measurement_bundle: TaskMeasurementBundle,
) -> None:
    """Reject a stale, tampered, or cross-bundle sealed episode."""

    if not isinstance(sealed_episode, SealedEpisode):
        raise MeasurementContractError(
            "sealed_episode must be a SealedEpisode"
        )
    validate_task_measurement_bundle(task_measurement_bundle)
    sealed_episode.__post_init__()
    if (
        sealed_episode.bundle_id != task_measurement_bundle.bundle_id
        or sealed_episode.bundle_version != task_measurement_bundle.version
        or sealed_episode.bundle_hash != task_measurement_bundle.bundle_hash
    ):
        raise MeasurementContractError(
            "SealedEpisode belongs to a different bundle"
        )
    validate_measurement_bundle(
        task_measurement_bundle.task_frame,
        task_measurement_bundle.goal_graph,
        task_measurement_bundle.requirement_graph,
        task_measurement_bundle.measurement_graph,
        sealed_episode.episode_graph,
    )


def _evaluator_set_hash(measurement_graph: MeasurementGraph) -> str:
    identities = tuple(
        {
            "measurement_id": spec.measurement_id,
            "measurement_version": spec.version,
            "kind": spec.kind.value,
            "evaluator_ref": spec.evaluator_ref,
            "evaluator_version": spec.evaluator_version,
            "evaluator_authority": spec.evaluator_authority.value,
        }
        for spec in measurement_graph.measurement_specs
    )
    return _canonical_json_sha256(identities)


def _aggregate_status(statuses: tuple[EvaluationStatus, ...]) -> EvaluationStatus:
    if not statuses:
        return EvaluationStatus.UNKNOWN
    for status in (
        EvaluationStatus.INVALID,
        EvaluationStatus.FAIL,
        EvaluationStatus.DISPUTED,
        EvaluationStatus.UNKNOWN,
    ):
        if status in statuses:
            return status
    return EvaluationStatus.PASS


def _ordered_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def fuse_evidence(
    *,
    result_id: str,
    task_measurement_bundle: TaskMeasurementBundle,
    sealed_episode: SealedEpisode,
    observations: tuple[MeasurementObservation, ...],
) -> EvaluationResult:
    """Fuse a frozen MEAS0 run without scalar compensation or Judge authority."""

    _text(result_id, "result_id")
    validate_sealed_episode(
        sealed_episode,
        task_measurement_bundle=task_measurement_bundle,
    )
    task_frame = task_measurement_bundle.task_frame
    requirement_graph = task_measurement_bundle.requirement_graph
    measurement_graph = task_measurement_bundle.measurement_graph
    episode_graph = sealed_episode.episode_graph
    observations = tuple(observations)
    if not all(isinstance(item, MeasurementObservation) for item in observations):
        raise MeasurementContractError(
            "observations must contain MeasurementObservation values"
        )
    _unique(tuple(item.observation_id for item in observations), "observation_ids")
    _unique(
        tuple(item.measurement_id for item in observations),
        "observed measurement_ids",
    )

    specs = {
        item.measurement_id: item for item in measurement_graph.measurement_specs
    }
    evidence_ids = {item.evidence_id for item in episode_graph.evidence}
    observations_by_measurement: dict[str, MeasurementObservation] = {}
    for observation in observations:
        spec = specs.get(observation.measurement_id)
        if spec is None:
            raise MeasurementContractError(
                "observation references an unknown measurement"
            )
        if observation.measurement_version != spec.version:
            raise MeasurementContractError(
                "observation references a stale MeasurementSpec version"
            )
        if (
            observation.evaluator_ref != spec.evaluator_ref
            or observation.evaluator_version != spec.evaluator_version
        ):
            raise MeasurementContractError(
                "observation does not come from the frozen evaluator"
            )
        if not set(observation.evidence_refs) <= evidence_ids:
            raise MeasurementContractError(
                "observation references unknown episode evidence"
            )
        observations_by_measurement[observation.measurement_id] = observation

    requirements = {
        item.requirement_id: item for item in requirement_graph.requirements
    }
    statuses_by_requirement: dict[str, EvaluationStatus] = {}
    diagnostics: list[str] = []
    for requirement_id in requirements:
        requirement_specs = tuple(
            item
            for item in measurement_graph.measurement_specs
            if item.target_requirement_id == requirement_id
        )
        decisive_spec = next(
            item
            for item in requirement_specs
            if item.role is MeasurementRole.DECISIVE
        )
        decisive_observation = observations_by_measurement.get(
            decisive_spec.measurement_id
        )
        decisive_status = (
            decisive_observation.status
            if decisive_observation is not None
            else EvaluationStatus.UNKNOWN
        )
        statuses_by_requirement[requirement_id] = decisive_status
        advisory_judge_passed = any(
            item.role is MeasurementRole.ADVISORY
            and item.kind is MeasurementKind.JUDGE
            and observations_by_measurement.get(item.measurement_id) is not None
            and observations_by_measurement[item.measurement_id].status
            is EvaluationStatus.PASS
            for item in requirement_specs
        )
        if (
            decisive_spec.kind is MeasurementKind.DETERMINISTIC
            and decisive_status is EvaluationStatus.FAIL
            and advisory_judge_passed
        ):
            diagnostics.append(
                "advisory judge pass ignored after decisive deterministic fail: "
                f"{requirement_id}"
            )

    def dimension_status(dimension: MeasurementDimension) -> EvaluationStatus:
        dimension_statuses = tuple(
            observations_by_measurement[item.measurement_id].status
            if item.measurement_id in observations_by_measurement
            else EvaluationStatus.UNKNOWN
            for item in measurement_graph.measurement_specs
            if item.dimension is dimension
            and item.role is MeasurementRole.DECISIVE
        )
        return _aggregate_status(dimension_statuses)

    hard_gate_status = _aggregate_status(
        tuple(
            observations_by_measurement[measurement_id].status
            if measurement_id in observations_by_measurement
            else EvaluationStatus.UNKNOWN
            for measurement_id in measurement_graph.hard_gate_measurement_ids
        )
    )
    safety_status = dimension_status(MeasurementDimension.SAFETY)
    efficiency_status = dimension_status(MeasurementDimension.EFFICIENCY)
    semantic_status = dimension_status(MeasurementDimension.SEMANTIC)
    critical_status = _aggregate_status(
        tuple(
            statuses_by_requirement[item.requirement_id]
            for item in requirement_graph.requirements
            if item.critical
        )
    )

    completion_requirements = tuple(
        item
        for item in requirement_graph.requirements
        if not item.critical
        and item.dimension
        not in {MeasurementDimension.SAFETY, MeasurementDimension.EFFICIENCY}
    )
    denominator = sum(item.weight for item in completion_requirements)
    if denominator == 0:
        noncritical_coverage = 1.0
        normal_status = EvaluationStatus.PASS
    else:
        passed_weight = sum(
            item.weight
            for item in completion_requirements
            if statuses_by_requirement[item.requirement_id]
            is EvaluationStatus.PASS
        )
        unresolved_weight = sum(
            item.weight
            for item in completion_requirements
            if statuses_by_requirement[item.requirement_id]
            in {EvaluationStatus.UNKNOWN, EvaluationStatus.DISPUTED}
        )
        noncritical_coverage = passed_weight / denominator
        possible_coverage = (passed_weight + unresolved_weight) / denominator
        disputed_weight = sum(
            item.weight
            for item in completion_requirements
            if statuses_by_requirement[item.requirement_id]
            is EvaluationStatus.DISPUTED
        )
        normal_statuses = tuple(
            statuses_by_requirement[item.requirement_id]
            for item in completion_requirements
        )
        threshold = measurement_graph.normal_coverage_threshold
        if EvaluationStatus.INVALID in normal_statuses:
            normal_status = EvaluationStatus.INVALID
        elif noncritical_coverage >= threshold:
            normal_status = EvaluationStatus.PASS
        elif EvaluationStatus.FAIL in normal_statuses:
            normal_status = EvaluationStatus.FAIL
        elif possible_coverage < threshold:
            normal_status = EvaluationStatus.FAIL
        elif (
            EvaluationStatus.DISPUTED in normal_statuses
            and (passed_weight + disputed_weight) / denominator >= threshold
        ):
            normal_status = EvaluationStatus.DISPUTED
        elif EvaluationStatus.UNKNOWN in normal_statuses:
            normal_status = EvaluationStatus.UNKNOWN
        else:
            normal_status = EvaluationStatus.FAIL

    decisive_statuses = tuple(statuses_by_requirement.values())
    if EvaluationStatus.INVALID in decisive_statuses:
        outcome = EvaluationStatus.INVALID
    else:
        mandatory_status = _aggregate_status(
            (hard_gate_status, safety_status, critical_status)
        )
        outcome = (
            mandatory_status
            if mandatory_status is not EvaluationStatus.PASS
            else normal_status
        )

    evidence_trace = _ordered_unique(
        tuple(
            evidence_ref
            for observation in observations
            for evidence_ref in observation.evidence_refs
        )
    )
    if not evidence_trace:
        # A fully missing run still points at the sealed episode rather than
        # fabricating positive evidence for any measurement.
        evidence_trace = (episode_graph.trajectory_ref,)

    return EvaluationResult(
        result_id=result_id,
        version=2,
        task_id=task_frame.task_id,
        bundle_id=task_measurement_bundle.bundle_id,
        bundle_version=task_measurement_bundle.version,
        bundle_hash=task_measurement_bundle.bundle_hash,
        measurement_graph_id=measurement_graph.graph_id,
        measurement_graph_version=measurement_graph.version,
        episode_id=episode_graph.episode_id,
        episode_version=episode_graph.version,
        episode_hash=sealed_episode.episode_hash,
        evaluator_set_hash=_evaluator_set_hash(measurement_graph),
        requirement_statuses=tuple(statuses_by_requirement.items()),
        outcome=outcome,
        noncritical_coverage=noncritical_coverage,
        safety_status=safety_status,
        efficiency_status=efficiency_status,
        semantic_status=semantic_status,
        total_measurement_cost=sum(item.cost for item in observations),
        evidence_trace=evidence_trace,
        diagnostics=tuple(diagnostics),
        provenance=(
            "measurement-bundle:"
            f"{task_measurement_bundle.bundle_id}:"
            f"v{task_measurement_bundle.version}:"
            f"{task_measurement_bundle.bundle_hash}",
            "measurement-graph:"
            f"{measurement_graph.graph_id}:v{measurement_graph.version}",
            "episode:"
            f"{episode_graph.episode_id}:"
            f"v{episode_graph.version}:"
            f"{sealed_episode.episode_hash}",
        ),
    )


def validate_evaluation_result(
    result: EvaluationResult,
    *,
    task_measurement_bundle: TaskMeasurementBundle,
    sealed_episode: SealedEpisode,
    observations: tuple[MeasurementObservation, ...],
) -> None:
    """Reject a result that differs from deterministic fusion of frozen inputs."""

    expected = fuse_evidence(
        result_id=result.result_id,
        task_measurement_bundle=task_measurement_bundle,
        sealed_episode=sealed_episode,
        observations=observations,
    )
    if result != expected:
        raise MeasurementContractError(
            "EvaluationResult violates deterministic fusion; a Judge cannot override "
            "a deterministic failure"
        )


__all__ = [
    "EpisodeEvidence",
    "EpisodeGraph",
    "EvaluationResult",
    "EvaluationStatus",
    "EvaluatorAuthority",
    "EvidenceKind",
    "Goal",
    "GoalGraph",
    "MeasurementContractError",
    "MeasurementDimension",
    "MeasurementGraph",
    "MeasurementKind",
    "MeasurementObservation",
    "MeasurementRole",
    "MeasurementSpec",
    "Requirement",
    "RequirementGraph",
    "SealedEpisode",
    "TaskFrame",
    "TaskMeasurementBundle",
    "fuse_evidence",
    "seal_episode_graph",
    "seal_task_measurement_bundle",
    "validate_evaluation_result",
    "validate_measurement_bundle",
    "validate_sealed_episode",
    "validate_task_measurement_bundle",
]
