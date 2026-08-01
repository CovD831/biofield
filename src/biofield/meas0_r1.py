from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .evidence_task import EvidenceAnswerKey, load_task_bundle
from .measurement import (
    EpisodeEvidence,
    EpisodeGraph,
    EvaluationStatus,
    EvaluatorAuthority,
    EvidenceKind,
    Goal,
    GoalGraph,
    MeasurementDimension,
    MeasurementGraph,
    MeasurementKind,
    MeasurementObservation,
    MeasurementSpec,
    Requirement,
    RequirementGraph,
    SealedEpisode,
    TaskFrame,
    TaskMeasurementBundle,
    seal_episode_graph,
    seal_task_measurement_bundle,
    validate_sealed_episode,
    validate_task_measurement_bundle,
)
from .resources import fixture_root as package_fixture_root


COLD_CHAIN_TASK_ID = "cold_chain_readiness"
R1_EVALUATOR_VERSION = "meas0.r1.cold-chain.deterministic.v1"


class R1EvaluatorError(ValueError):
    """Raised when an R1 deterministic evaluation boundary is invalid."""


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _evidence_hash(value: bytes) -> str:
    return f"sha256:{_sha256_bytes(value)}"


def _text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise R1EvaluatorError(f"{field_name} must be a non-empty string")
    return value


def _r1_fixture_root(fixture_root: str | Path | None) -> Path:
    return (
        Path(fixture_root)
        if fixture_root is not None
        else package_fixture_root() / "r1"
    )


@dataclass(frozen=True)
class R1SubjectMaterial:
    material_id: str
    title: str
    content_bytes: bytes

    def __post_init__(self) -> None:
        _text(self.material_id, "material_id")
        _text(self.title, "material title")
        if not isinstance(self.content_bytes, bytes) or not self.content_bytes:
            raise R1EvaluatorError("material content_bytes must be non-empty bytes")

    @property
    def content_hash(self) -> str:
        return _sha256_bytes(self.content_bytes)

    def to_dict(self) -> dict[str, str]:
        return {
            "material_id": self.material_id,
            "title": self.title,
            "text": self.content_bytes.decode("utf-8"),
            "content_sha256": self.content_hash,
        }


@dataclass(frozen=True)
class R1SubjectInput:
    task_id: str
    task_version: str
    task_source_bytes: bytes
    materials: tuple[R1SubjectMaterial, ...]

    def __post_init__(self) -> None:
        _text(self.task_id, "task_id")
        _text(self.task_version, "task_version")
        if not isinstance(self.task_source_bytes, bytes) or not self.task_source_bytes:
            raise R1EvaluatorError("task_source_bytes must be non-empty bytes")
        object.__setattr__(self, "materials", tuple(self.materials))
        if not 3 <= len(self.materials) <= 5:
            raise R1EvaluatorError("R1 subject input must contain 3 to 5 materials")
        if len({item.material_id for item in self.materials}) != len(self.materials):
            raise R1EvaluatorError("R1 subject material IDs must be unique")

    @property
    def task_source_sha256(self) -> str:
        return _sha256_bytes(self.task_source_bytes)

    def to_dict(self) -> dict[str, Any]:
        payload = json.loads(self.task_source_bytes)
        if not isinstance(payload, dict):
            raise R1EvaluatorError("task source root must be an object")
        return {
            **payload,
            "task_source_sha256": self.task_source_sha256,
            "material_content_sha256": {
                item.material_id: item.content_hash for item in self.materials
            },
        }


@dataclass(frozen=True)
class R1EpisodeArtifacts:
    items: tuple[tuple[str, bytes], ...]

    def __post_init__(self) -> None:
        normalized = tuple((item[0], item[1]) for item in self.items)
        object.__setattr__(self, "items", normalized)
        evidence_ids: list[str] = []
        for evidence_id, content in normalized:
            _text(evidence_id, "artifact evidence_id")
            if not isinstance(content, bytes):
                raise R1EvaluatorError("episode artifact content must be bytes")
            evidence_ids.append(evidence_id)
        if len(set(evidence_ids)) != len(evidence_ids):
            raise R1EvaluatorError("episode artifact evidence IDs must be unique")

    def get(self, evidence_id: str) -> bytes | None:
        return dict(self.items).get(evidence_id)


@dataclass(frozen=True)
class R1SealedEpisode:
    sealed_episode: SealedEpisode
    artifacts: R1EpisodeArtifacts

    def __post_init__(self) -> None:
        if not isinstance(self.sealed_episode, SealedEpisode):
            raise R1EvaluatorError("sealed_episode must be a SealedEpisode")
        if not isinstance(self.artifacts, R1EpisodeArtifacts):
            raise R1EvaluatorError("artifacts must be R1EpisodeArtifacts")


def load_cold_chain_subject_input(
    *,
    fixture_root: str | Path | None = None,
) -> R1SubjectInput:
    """Load only subject-visible task bytes; never open the answer key."""

    root = _r1_fixture_root(fixture_root)
    task_path = root / COLD_CHAIN_TASK_ID / "task.v1.json"
    try:
        source_bytes = task_path.read_bytes()
        payload = json.loads(source_bytes)
    except FileNotFoundError as error:
        raise R1EvaluatorError("cold-chain task fixture is missing") from error
    except (OSError, json.JSONDecodeError) as error:
        raise R1EvaluatorError("cold-chain task fixture is unreadable") from error
    if not isinstance(payload, dict):
        raise R1EvaluatorError("cold-chain task fixture root must be an object")
    task_id = _text(payload.get("task_id"), "task_id")
    task_version = _text(payload.get("task_version"), "task_version")
    if task_id != COLD_CHAIN_TASK_ID or task_version != "1":
        raise R1EvaluatorError("cold-chain task fixture identity is invalid")
    materials_payload = payload.get("materials")
    if not isinstance(materials_payload, list):
        raise R1EvaluatorError("cold-chain materials must be an array")
    materials: list[R1SubjectMaterial] = []
    for item in materials_payload:
        if not isinstance(item, Mapping):
            raise R1EvaluatorError("cold-chain material must be an object")
        materials.append(
            R1SubjectMaterial(
                material_id=_text(item.get("material_id"), "material_id"),
                title=_text(item.get("title"), "material title"),
                content_bytes=_text(item.get("text"), "material text").encode(
                    "utf-8"
                ),
            )
        )
    return R1SubjectInput(
        task_id=task_id,
        task_version=task_version,
        task_source_bytes=source_bytes,
        materials=tuple(materials),
    )


_REQUIREMENT_DEFINITIONS = (
    ("r1.structured_answer", "A valid structured answer artifact exists", True),
    ("r1.decision_hold", "The launch decision is hold", True),
    ("r1.generator_failed", "The generator load test failed", True),
    ("r1.s4_expired", "The S4 certificate is expired", True),
    (
        "r1.generator_conflict",
        "The generator conflict is explicitly represented",
        True,
    ),
    (
        "r1.sensor_conflict",
        "The sensor certificate conflict is explicitly represented",
        True,
    ),
    (
        "r1.citation_provenance",
        "All submitted citations are authorized and sufficient",
        True,
    ),
    ("r1.launch_date", "The launch date is 2026-04-18", False),
    ("r1.replacement_date", "The replacement date is 2026-04-20", False),
)


def _measurement_dimension(requirement_id: str) -> MeasurementDimension:
    if requirement_id == "r1.citation_provenance":
        return MeasurementDimension.SAFETY
    return MeasurementDimension.OUTCOME


def _build_measurement_bundle(
    subject_input: R1SubjectInput,
    *,
    answer_key_sha256: str,
) -> TaskMeasurementBundle:
    task_frame = TaskFrame(
        task_id=COLD_CHAIN_TASK_ID,
        version=1,
        subject_agent_id="subject-agent",
        user_intent="Assess cold-chain launch readiness from all supplied materials",
        desired_state="A structured, evidenced launch decision is delivered",
        known_initial_state="Launch readiness is unresolved",
        entities_and_scope=("North Port cold-chain warehouse",),
        constraints_and_permissions=("use only supplied material IDs",),
        available_capabilities=("read fixture materials", "write structured answer"),
        uncertainties_and_ambiguities=("materials contain conflicting claims",),
        risk_and_reversibility=("unsafe launch acceptance must be prevented",),
        required_artifacts=("structured_answer.json",),
        evidence_expectations=(
            "material-backed facts",
            "explicit cross-material conflicts",
        ),
        provenance=(f"task-source-sha256:{subject_input.task_source_sha256}",),
    )
    goals = GoalGraph(
        graph_id="r1.cold-chain.goals",
        version=1,
        task_id=COLD_CHAIN_TASK_ID,
        task_frame_version=1,
        goals=(
            Goal(
                goal_id="readiness",
                desired_semantics="The launch decision follows authoritative evidence",
                critical=True,
                provenance=("meas0-r1-design:v1",),
            ),
            Goal(
                goal_id="delivery",
                desired_semantics="The structured answer preserves facts and provenance",
                critical=False,
                dependency_goal_ids=("readiness",),
                provenance=("meas0-r1-design:v1",),
            ),
        ),
        provenance=("meas0-r1-goal-freeze:v1",),
    )
    requirements = RequirementGraph(
        graph_id="r1.cold-chain.requirements",
        version=1,
        schema_version=1,
        goal_graph_id=goals.graph_id,
        goal_graph_version=goals.version,
        requirements=tuple(
            Requirement(
                requirement_id=requirement_id,
                goal_id="readiness" if critical else "delivery",
                success_semantics=statement,
                dimension=_measurement_dimension(requirement_id),
                critical=critical,
                weight=1.0,
                provenance=("meas0-r1-requirement-freeze:v1",),
            )
            for requirement_id, statement, critical in _REQUIREMENT_DEFINITIONS
        ),
        provenance=("meas0-r1-requirement-freeze:v1",),
    )
    specs = tuple(
        MeasurementSpec(
            measurement_id=requirement_id,
            version=1,
            target_requirement_id=requirement_id,
            requirement_schema_version=1,
            dimension=_measurement_dimension(requirement_id),
            kind=MeasurementKind.DETERMINISTIC,
            measurand=statement,
            observation_source="sealed R1 artifact and fixture material bytes",
            procedure=f"run {requirement_id} deterministic adapter",
            unit_or_scale="pass/fail/unknown/disputed",
            expected_coverage=1.0,
            acceptance_rule="compare structured artifact with hidden answer key",
            uncertainty_rule="missing evidence is unknown; conflicting values are disputed",
            calibration_ref="meas0-r1-deterministic-contract:v1",
            cost_estimate=1.0,
            evaluator_ref=f"biofield.meas0_r1:{requirement_id}",
            evaluator_version=R1_EVALUATOR_VERSION,
            evaluator_authority=EvaluatorAuthority.EVALUATION_PLANE,
            provenance=("meas0-r1-evaluator-freeze:v1",),
        )
        for requirement_id, statement, _ in _REQUIREMENT_DEFINITIONS
    )
    measurement_graph = MeasurementGraph(
        graph_id="r1.cold-chain.measurements",
        version=1,
        task_id=COLD_CHAIN_TASK_ID,
        requirement_graph_id=requirements.graph_id,
        requirement_graph_version=requirements.version,
        requirement_schema_version=requirements.schema_version,
        measurement_specs=specs,
        hard_gate_measurement_ids=(
            "r1.structured_answer",
            "r1.citation_provenance",
        ),
        normal_coverage_threshold=0.80,
        provenance=("meas0-r1-measurement-freeze:v1",),
    )
    return seal_task_measurement_bundle(
        bundle_id="r1.cold-chain.deterministic",
        version=1,
        task_frame=task_frame,
        goal_graph=goals,
        requirement_graph=requirements,
        measurement_graph=measurement_graph,
        acceptance_rules=(
            "hard gates and critical requirements must pass",
            "normal deterministic coverage must be at least 0.80",
        ),
        deterministic_check_refs=tuple(
            spec.evaluator_ref for spec in measurement_graph.measurement_specs
        ),
        judge_refs=(),
        metamorphic_relations=("material order must not alter the verdict",),
        uncertainty_and_escalation_rules=(
            "missing submitted evidence yields unknown",
            "conflicting submitted values yield disputed",
        ),
        measurement_budget=sum(
            spec.cost_estimate for spec in measurement_graph.measurement_specs
        ),
        provenance=(
            f"task-source-sha256:{subject_input.task_source_sha256}",
            f"hidden-answer-key-sha256:{answer_key_sha256}",
        ),
    )


@dataclass(frozen=True)
class ColdChainDeterministicEvaluator:
    measurement_bundle: TaskMeasurementBundle
    _answer_key: EvidenceAnswerKey
    _answer_schema_bytes: bytes
    _answer_key_sha256: str
    _material_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_task_measurement_bundle(self.measurement_bundle)
        if not isinstance(self._answer_key, EvidenceAnswerKey):
            raise R1EvaluatorError("_answer_key must be an EvidenceAnswerKey")
        if (
            not isinstance(self._answer_schema_bytes, bytes)
            or not self._answer_schema_bytes
        ):
            raise R1EvaluatorError("_answer_schema_bytes must be non-empty bytes")
        _text(self._answer_key_sha256, "_answer_key_sha256")
        if len(self._answer_key_sha256) != 64 or any(
            character not in "0123456789abcdef"
            for character in self._answer_key_sha256
        ):
            raise R1EvaluatorError(
                "_answer_key_sha256 must be a lowercase SHA-256 digest"
            )
        object.__setattr__(self, "_material_ids", tuple(self._material_ids))
        if not self._material_ids or len(set(self._material_ids)) != len(
            self._material_ids
        ):
            raise R1EvaluatorError("_material_ids must be non-empty and unique")

    def evaluate(
        self,
        episode: R1SealedEpisode,
    ) -> tuple[MeasurementObservation, ...]:
        self._verify_episode(episode)
        artifact_bytes = episode.artifacts.get("artifact:structured_answer")
        answer, schema_valid = _parse_answer(
            artifact_bytes,
            self._answer_schema_bytes,
        )
        statuses = self._evaluate_statuses(
            answer=answer,
            artifact_present=artifact_bytes is not None,
            schema_valid=schema_valid,
        )
        evidence_ids = {
            item.evidence_id for item in episode.sealed_episode.episode_graph.evidence
        }
        artifact_ref = (
            ("artifact:structured_answer",)
            if "artifact:structured_answer" in evidence_ids
            else ()
        )
        observations: list[MeasurementObservation] = []
        for spec in self.measurement_bundle.measurement_graph.measurement_specs:
            status = statuses[spec.measurement_id]
            refs = _observation_evidence_refs(
                spec.measurement_id,
                artifact_ref=artifact_ref,
                evidence_ids=evidence_ids,
            )
            observations.append(
                MeasurementObservation(
                    observation_id=(
                        f"{episode.sealed_episode.episode_graph.episode_id}:"
                        f"{spec.measurement_id}"
                    ),
                    measurement_id=spec.measurement_id,
                    measurement_version=spec.version,
                    status=status,
                    observed_value=status.value,
                    evidence_refs=refs,
                    provenance=(
                        f"hidden-answer-key-sha256:{self._answer_key_sha256}",
                        self._evaluation_provenance(),
                    ),
                    coverage=0.0 if status is EvaluationStatus.UNKNOWN else 1.0,
                    uncertainty=(
                        1.0
                        if status
                        in {EvaluationStatus.UNKNOWN, EvaluationStatus.DISPUTED}
                        else 0.0
                    ),
                    cost=spec.cost_estimate,
                    evaluator_ref=spec.evaluator_ref,
                    evaluator_version=spec.evaluator_version,
                )
            )
        return tuple(observations)

    def _verify_episode(self, episode: R1SealedEpisode) -> None:
        verify_r1_episode_artifacts(
            episode,
            task_measurement_bundle=self.measurement_bundle,
        )

    def _evaluation_provenance(self) -> str:
        return "meas0-r1-deterministic-evaluation:v1"

    def _evaluate_statuses(
        self,
        *,
        answer: Mapping[str, Any] | None,
        artifact_present: bool,
        schema_valid: bool,
    ) -> dict[str, EvaluationStatus]:
        artifact_status = (
            EvaluationStatus.PASS
            if artifact_present and schema_valid
            else EvaluationStatus.FAIL
        )
        if answer is None or not schema_valid:
            return {
                requirement_id: (
                    artifact_status
                    if requirement_id == "r1.structured_answer"
                    else EvaluationStatus.UNKNOWN
                )
                for requirement_id, _, _ in _REQUIREMENT_DEFINITIONS
            }

        expected_facts = {
            item.fact_id: item for item in self._answer_key.key_facts
        }
        return {
            "r1.structured_answer": artifact_status,
            "r1.decision_hold": _scalar_status(
                answer.get("decision"),
                self._answer_key.decision,
            ),
            "r1.generator_failed": _fact_status(
                answer,
                expected_facts["generator_test"].accepted_values,
                "generator_test",
            ),
            "r1.s4_expired": _fact_status(
                answer,
                expected_facts["s4_certificate"].accepted_values,
                "s4_certificate",
            ),
            "r1.generator_conflict": _contradiction_status(
                answer,
                self._answer_key,
                "generator_test_conflict",
            ),
            "r1.sensor_conflict": _contradiction_status(
                answer,
                self._answer_key,
                "sensor_certificate_conflict",
            ),
            "r1.citation_provenance": _citation_status(
                answer,
                self._answer_key,
                set(self._material_ids),
            ),
            "r1.launch_date": _fact_status(
                answer,
                expected_facts["planned_launch_date"].accepted_values,
                "planned_launch_date",
            ),
            "r1.replacement_date": _fact_status(
                answer,
                expected_facts["replacement_arrival"].accepted_values,
                "replacement_arrival",
            ),
        }


def load_cold_chain_evaluator(
    *,
    fixture_root: str | Path | None = None,
) -> ColdChainDeterministicEvaluator:
    root = _r1_fixture_root(fixture_root)
    subject_input = load_cold_chain_subject_input(fixture_root=root)
    answer_key_path = root / COLD_CHAIN_TASK_ID / "answer_key.v1.json"
    try:
        answer_key_bytes = answer_key_path.read_bytes()
    except (OSError, FileNotFoundError) as error:
        raise R1EvaluatorError("cold-chain hidden answer key is unavailable") from error
    bundle = load_task_bundle(COLD_CHAIN_TASK_ID, fixture_root=root)
    answer_schema = bundle.task.answer_schema
    return ColdChainDeterministicEvaluator(
        measurement_bundle=_build_measurement_bundle(
            subject_input,
            answer_key_sha256=_sha256_bytes(answer_key_bytes),
        ),
        _answer_key=bundle.answer_key,
        _answer_schema_bytes=_canonical_json_bytes(dict(answer_schema)),
        _answer_key_sha256=_sha256_bytes(answer_key_bytes),
        _material_ids=tuple(item.material_id for item in subject_input.materials),
    )


def build_cold_chain_episode(
    *,
    subject_input: R1SubjectInput,
    task_measurement_bundle: TaskMeasurementBundle,
    structured_answer_bytes: bytes | None,
    response_bytes: bytes,
) -> R1SealedEpisode:
    validate_task_measurement_bundle(task_measurement_bundle)
    if subject_input.task_id != COLD_CHAIN_TASK_ID:
        raise R1EvaluatorError("subject input is not cold_chain_readiness")
    if task_measurement_bundle.task_frame.task_id != subject_input.task_id:
        raise R1EvaluatorError("measurement bundle targets a different task")
    if structured_answer_bytes is not None and not isinstance(
        structured_answer_bytes, bytes
    ):
        raise R1EvaluatorError("structured_answer_bytes must be bytes or None")
    if not isinstance(response_bytes, bytes):
        raise R1EvaluatorError("response_bytes must be bytes")

    content_by_id: list[tuple[str, bytes]] = [
        ("input:task", subject_input.task_source_bytes),
        *(
            (f"input:material:{item.material_id}", item.content_bytes)
            for item in subject_input.materials
        ),
    ]
    input_ids = tuple(evidence_id for evidence_id, _ in content_by_id)
    action_bytes = _canonical_json_bytes(
        {
            "action": "submit_cold_chain_readiness_assessment",
            "task_id": subject_input.task_id,
            "task_version": subject_input.task_version,
        }
    )
    content_by_id.append(("action:submit", action_bytes))
    if structured_answer_bytes is not None:
        content_by_id.append(
            ("artifact:structured_answer", structured_answer_bytes)
        )
    state_bytes = _canonical_json_bytes(
        {
            "structured_answer_present": structured_answer_bytes is not None,
            "task_id": subject_input.task_id,
        }
    )
    trajectory_bytes = _canonical_json_bytes(
        {
            "events": [
                *input_ids,
                "action:submit",
                *(
                    ("artifact:structured_answer",)
                    if structured_answer_bytes is not None
                    else ()
                ),
            ]
        }
    )
    content_by_id.extend(
        (
            ("state:submission", state_bytes),
            ("trajectory:submission", trajectory_bytes),
            ("response:final", response_bytes),
        )
    )
    content_lookup = dict(content_by_id)
    evidence: list[EpisodeEvidence] = [
        EpisodeEvidence(
            evidence_id=evidence_id,
            kind=EvidenceKind.INPUT,
            locator=f"r1://{subject_input.task_id}/{evidence_id}",
            content_hash=_evidence_hash(content),
            provenance=("subject-visible-r1-fixture:v1",),
        )
        for evidence_id, content in content_by_id
        if evidence_id.startswith("input:")
    ]
    evidence.append(
        EpisodeEvidence(
            evidence_id="action:submit",
            kind=EvidenceKind.ACTION,
            locator=f"r1://{subject_input.task_id}/action/submit",
            content_hash=_evidence_hash(content_lookup["action:submit"]),
            causal_parent_ids=input_ids,
            provenance=("r1-harness-action:v1",),
        )
    )
    if structured_answer_bytes is not None:
        evidence.append(
            EpisodeEvidence(
                evidence_id="artifact:structured_answer",
                kind=EvidenceKind.ARTIFACT,
                locator=f"r1://{subject_input.task_id}/artifact/structured-answer",
                content_hash=_evidence_hash(structured_answer_bytes),
                causal_parent_ids=("action:submit",),
                provenance=("r1-harness-capture:v1",),
            )
        )
    state_parent = (
        "artifact:structured_answer"
        if structured_answer_bytes is not None
        else "action:submit"
    )
    evidence.extend(
        (
            EpisodeEvidence(
                evidence_id="state:submission",
                kind=EvidenceKind.ENVIRONMENT_STATE,
                locator=f"r1://{subject_input.task_id}/state/submission",
                content_hash=_evidence_hash(state_bytes),
                causal_parent_ids=(state_parent,),
                provenance=("r1-protected-state:v1",),
            ),
            EpisodeEvidence(
                evidence_id="trajectory:submission",
                kind=EvidenceKind.TRAJECTORY,
                locator=f"r1://{subject_input.task_id}/trajectory/submission",
                content_hash=_evidence_hash(trajectory_bytes),
                causal_parent_ids=("action:submit",),
                provenance=("r1-harness-trajectory:v1",),
            ),
            EpisodeEvidence(
                evidence_id="response:final",
                kind=EvidenceKind.RESPONSE,
                locator=f"r1://{subject_input.task_id}/response/final",
                content_hash=_evidence_hash(response_bytes),
                causal_parent_ids=("state:submission",),
                provenance=("r1-harness-capture:v1",),
            ),
        )
    )
    episode_graph = EpisodeGraph(
        episode_id="r1.cold-chain.episode",
        version=1,
        task_id=subject_input.task_id,
        task_frame_version=task_measurement_bundle.task_frame.version,
        evidence=tuple(evidence),
        environment_state_ref="state:submission",
        trajectory_ref="trajectory:submission",
        response_ref="response:final",
        artifact_refs=(
            ("artifact:structured_answer",)
            if structured_answer_bytes is not None
            else ()
        ),
        provenance=("meas0-r1-episode:v1",),
    )
    sealed_episode = seal_episode_graph(
        task_measurement_bundle=task_measurement_bundle,
        episode_graph=episode_graph,
        provenance=("meas0-r1-episode-seal:v1",),
    )
    return R1SealedEpisode(
        sealed_episode=sealed_episode,
        artifacts=R1EpisodeArtifacts(items=tuple(content_by_id)),
    )


def verify_r1_episode_artifacts(
    episode: R1SealedEpisode,
    *,
    task_measurement_bundle: TaskMeasurementBundle,
) -> None:
    if not isinstance(episode, R1SealedEpisode):
        raise R1EvaluatorError("episode must be an R1SealedEpisode")
    validate_sealed_episode(
        episode.sealed_episode,
        task_measurement_bundle=task_measurement_bundle,
    )
    evidence_by_id = {
        item.evidence_id: item
        for item in episode.sealed_episode.episode_graph.evidence
    }
    artifact_ids = {evidence_id for evidence_id, _ in episode.artifacts.items}
    if artifact_ids != set(evidence_by_id):
        raise R1EvaluatorError(
            "artifact bytes do not exactly cover sealed evidence"
        )
    for evidence_id, content in episode.artifacts.items:
        if _evidence_hash(content) != evidence_by_id[evidence_id].content_hash:
            raise R1EvaluatorError(
                "artifact bytes do not match sealed evidence content_hash"
            )


def _parse_answer(
    artifact_bytes: bytes | None,
    answer_schema_bytes: bytes,
) -> tuple[Mapping[str, Any] | None, bool]:
    if artifact_bytes is None:
        return None, False
    try:
        value = json.loads(artifact_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, False
    if not isinstance(value, Mapping):
        return None, False
    answer_schema = json.loads(answer_schema_bytes)
    if not isinstance(answer_schema, dict):
        raise R1EvaluatorError("frozen answer schema root must be an object")
    errors = tuple(Draft202012Validator(answer_schema).iter_errors(value))
    return value, not errors


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _scalar_status(value: Any, expected: str) -> EvaluationStatus:
    if value is None:
        return EvaluationStatus.UNKNOWN
    if not isinstance(value, str):
        return EvaluationStatus.FAIL
    return (
        EvaluationStatus.PASS
        if _normalize(value) == _normalize(expected)
        else EvaluationStatus.FAIL
    )


def _fact_candidates(
    answer: Mapping[str, Any],
    fact_id: str,
) -> tuple[Mapping[str, Any], ...]:
    value = answer.get("key_facts")
    if not isinstance(value, list):
        return ()
    return tuple(
        item
        for item in value
        if isinstance(item, Mapping) and item.get("fact_id") == fact_id
    )


def _fact_status(
    answer: Mapping[str, Any],
    accepted_values: tuple[str, ...],
    fact_id: str,
) -> EvaluationStatus:
    candidates = _fact_candidates(answer, fact_id)
    if not candidates:
        return EvaluationStatus.UNKNOWN
    values = {
        _normalize(item["value"])
        for item in candidates
        if isinstance(item.get("value"), str)
    }
    if len(values) > 1:
        return EvaluationStatus.DISPUTED
    if not values:
        return EvaluationStatus.FAIL
    accepted = {_normalize(item) for item in accepted_values}
    return (
        EvaluationStatus.PASS
        if next(iter(values)) in accepted
        else EvaluationStatus.FAIL
    )


def _contradiction_status(
    answer: Mapping[str, Any],
    answer_key: EvidenceAnswerKey,
    contradiction_id: str,
) -> EvaluationStatus:
    contradictions = answer.get("contradictions")
    if not isinstance(contradictions, list):
        return EvaluationStatus.UNKNOWN
    candidates = tuple(
        item
        for item in contradictions
        if isinstance(item, Mapping)
        and item.get("contradiction_id") == contradiction_id
    )
    if not candidates:
        return EvaluationStatus.UNKNOWN
    pairs = {
        frozenset(item["material_ids"])
        for item in candidates
        if isinstance(item.get("material_ids"), list)
        and all(isinstance(value, str) for value in item["material_ids"])
    }
    if len(pairs) > 1:
        return EvaluationStatus.DISPUTED
    if not pairs:
        return EvaluationStatus.FAIL
    expected = next(
        item for item in answer_key.contradictions if item.contradiction_id == contradiction_id
    )
    return (
        EvaluationStatus.PASS
        if next(iter(pairs)) == frozenset(expected.material_ids)
        else EvaluationStatus.FAIL
    )


def _citation_status(
    answer: Mapping[str, Any],
    answer_key: EvidenceAnswerKey,
    material_ids: set[str],
) -> EvaluationStatus:
    unresolved = False
    for expected in answer_key.key_facts:
        candidates = _fact_candidates(answer, expected.fact_id)
        if not candidates:
            unresolved = True
            continue
        for candidate in candidates:
            citations = candidate.get("citations")
            if not isinstance(citations, list) or not all(
                isinstance(item, str) for item in citations
            ):
                return EvaluationStatus.FAIL
            unique = set(citations)
            if not unique <= material_ids:
                return EvaluationStatus.FAIL
            if (
                len(unique & set(expected.supporting_material_ids))
                < expected.minimum_citations
            ):
                return EvaluationStatus.FAIL
    return EvaluationStatus.UNKNOWN if unresolved else EvaluationStatus.PASS


def _observation_evidence_refs(
    measurement_id: str,
    *,
    artifact_ref: tuple[str, ...],
    evidence_ids: set[str],
) -> tuple[str, ...]:
    refs: list[str] = [*artifact_ref]
    if measurement_id.endswith(".structured_answer"):
        refs.append("state:submission")
    else:
        refs.extend(
            sorted(
                evidence_id
                for evidence_id in evidence_ids
                if evidence_id.startswith("input:material:")
            )
        )
    return tuple(dict.fromkeys(refs or ["state:submission"]))


__all__ = [
    "COLD_CHAIN_TASK_ID",
    "ColdChainDeterministicEvaluator",
    "R1EpisodeArtifacts",
    "R1EvaluatorError",
    "R1SealedEpisode",
    "R1SubjectInput",
    "R1SubjectMaterial",
    "build_cold_chain_episode",
    "load_cold_chain_evaluator",
    "load_cold_chain_subject_input",
    "verify_r1_episode_artifacts",
]
