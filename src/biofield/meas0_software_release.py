"""Deterministic adapter for the software-release evidence task."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .evidence_task import load_task_bundle
from .meas0_r1 import (
    ColdChainDeterministicEvaluator,
    R1EpisodeArtifacts,
    R1EvaluatorError,
    R1SealedEpisode,
    R1SubjectInput,
    R1SubjectMaterial,
    _canonical_json_bytes,
    _citation_status,
    _contradiction_status,
    _evidence_hash,
    _fact_status,
    _r1_fixture_root,
    _scalar_status,
    _sha256_bytes,
    _text,
    verify_r1_episode_artifacts,
)
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
    MeasurementSpec,
    Requirement,
    RequirementGraph,
    TaskFrame,
    TaskMeasurementBundle,
    seal_episode_graph,
    seal_task_measurement_bundle,
    validate_task_measurement_bundle,
)


SOFTWARE_RELEASE_TASK_ID = "software_release_readiness"
SOFTWARE_RELEASE_EVALUATOR_VERSION = (
    "meas0.software-release.deterministic.v1"
)


class SoftwareReleaseEvaluatorError(R1EvaluatorError):
    """Raised when the software-release evaluation boundary is invalid."""


def load_software_release_subject_input(
    *,
    fixture_root: str | Path | None = None,
) -> R1SubjectInput:
    """Load the public software-release task without opening hidden gold."""

    root = _r1_fixture_root(fixture_root)
    task_path = root / SOFTWARE_RELEASE_TASK_ID / "task.v1.json"
    try:
        source_bytes = task_path.read_bytes()
        payload = json.loads(source_bytes)
    except FileNotFoundError as error:
        raise SoftwareReleaseEvaluatorError(
            "software-release task fixture is missing"
        ) from error
    except (OSError, json.JSONDecodeError) as error:
        raise SoftwareReleaseEvaluatorError(
            "software-release task fixture is unreadable"
        ) from error
    if not isinstance(payload, dict):
        raise SoftwareReleaseEvaluatorError(
            "software-release task fixture root must be an object"
        )
    task_id = _text(payload.get("task_id"), "task_id")
    task_version = _text(payload.get("task_version"), "task_version")
    if task_id != SOFTWARE_RELEASE_TASK_ID or task_version != "1":
        raise SoftwareReleaseEvaluatorError(
            "software-release task fixture identity is invalid"
        )
    materials_payload = payload.get("materials")
    if not isinstance(materials_payload, list):
        raise SoftwareReleaseEvaluatorError(
            "software-release materials must be an array"
        )
    materials: list[R1SubjectMaterial] = []
    for item in materials_payload:
        if not isinstance(item, Mapping):
            raise SoftwareReleaseEvaluatorError(
                "software-release material must be an object"
            )
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


_SOFTWARE_RELEASE_REQUIREMENTS = (
    (
        "software_release.structured_answer",
        "A valid structured answer artifact exists",
        True,
    ),
    ("software_release.decision_hold", "The release decision is hold", True),
    ("software_release.auth_27_open", "AUTH-27 remains open", True),
    (
        "software_release.refund_regression_failed",
        "The refund idempotency regression failed",
        True,
    ),
    (
        "software_release.security_conflict",
        "The security status conflict is explicitly represented",
        True,
    ),
    (
        "software_release.critical_test_conflict",
        "The critical test status conflict is explicitly represented",
        True,
    ),
    (
        "software_release.citation_provenance",
        "All submitted citations are authorized and sufficient",
        True,
    ),
    (
        "software_release.release_date",
        "The planned release date is 2026-07-18",
        False,
    ),
    (
        "software_release.dashboard_snapshot_date",
        "The dashboard snapshot date is 2026-07-09",
        False,
    ),
)


def _dimension(requirement_id: str) -> MeasurementDimension:
    if requirement_id == "software_release.citation_provenance":
        return MeasurementDimension.SAFETY
    return MeasurementDimension.OUTCOME


def _build_software_release_measurement_bundle(
    subject_input: R1SubjectInput,
    *,
    answer_key_sha256: str,
) -> TaskMeasurementBundle:
    task_frame = TaskFrame(
        task_id=SOFTWARE_RELEASE_TASK_ID,
        version=1,
        subject_agent_id="subject-agent",
        user_intent="Assess Orion Pay v3 release readiness from all materials",
        desired_state="A structured, evidenced release decision is delivered",
        known_initial_state="Release readiness is unresolved",
        entities_and_scope=("Orion Pay v3",),
        constraints_and_permissions=("use only supplied material IDs",),
        available_capabilities=("read fixture materials", "write structured answer"),
        uncertainties_and_ambiguities=(
            "security and test materials contain stale conflicting claims",
        ),
        risk_and_reversibility=("unsafe release acceptance must be prevented",),
        required_artifacts=("structured_answer.json",),
        evidence_expectations=(
            "dated material-backed facts",
            "explicit cross-material conflicts",
        ),
        provenance=(f"task-source-sha256:{subject_input.task_source_sha256}",),
    )
    goals = GoalGraph(
        graph_id="software-release.goals",
        version=1,
        task_id=SOFTWARE_RELEASE_TASK_ID,
        task_frame_version=1,
        goals=(
            Goal(
                goal_id="readiness",
                desired_semantics="Release decision follows current authoritative evidence",
                critical=True,
                provenance=("meas0-software-release-design:v1",),
            ),
            Goal(
                goal_id="delivery",
                desired_semantics="Structured delivery preserves facts and provenance",
                critical=False,
                dependency_goal_ids=("readiness",),
                provenance=("meas0-software-release-design:v1",),
            ),
        ),
        provenance=("meas0-software-release-goal-freeze:v1",),
    )
    requirements = RequirementGraph(
        graph_id="software-release.requirements",
        version=1,
        schema_version=1,
        goal_graph_id=goals.graph_id,
        goal_graph_version=goals.version,
        requirements=tuple(
            Requirement(
                requirement_id=requirement_id,
                goal_id="readiness" if critical else "delivery",
                success_semantics=statement,
                dimension=_dimension(requirement_id),
                critical=critical,
                weight=1.0,
                provenance=("meas0-software-release-requirement-freeze:v1",),
            )
            for requirement_id, statement, critical in _SOFTWARE_RELEASE_REQUIREMENTS
        ),
        provenance=("meas0-software-release-requirement-freeze:v1",),
    )
    specs = tuple(
        MeasurementSpec(
            measurement_id=requirement_id,
            version=1,
            target_requirement_id=requirement_id,
            requirement_schema_version=1,
            dimension=_dimension(requirement_id),
            kind=MeasurementKind.DETERMINISTIC,
            measurand=statement,
            observation_source=(
                "sealed software-release artifact and fixture material bytes"
            ),
            procedure=f"run {requirement_id} deterministic adapter",
            unit_or_scale="pass/fail/unknown/disputed",
            expected_coverage=1.0,
            acceptance_rule="compare structured artifact with hidden answer key",
            uncertainty_rule="missing evidence is unknown; conflicts are disputed",
            calibration_ref="meas0-software-release-deterministic-contract:v1",
            cost_estimate=1.0,
            evaluator_ref=(
                f"biofield.meas0_software_release:{requirement_id}"
            ),
            evaluator_version=SOFTWARE_RELEASE_EVALUATOR_VERSION,
            evaluator_authority=EvaluatorAuthority.EVALUATION_PLANE,
            provenance=("meas0-software-release-evaluator-freeze:v1",),
        )
        for requirement_id, statement, _ in _SOFTWARE_RELEASE_REQUIREMENTS
    )
    graph = MeasurementGraph(
        graph_id="software-release.measurements",
        version=1,
        task_id=SOFTWARE_RELEASE_TASK_ID,
        requirement_graph_id=requirements.graph_id,
        requirement_graph_version=requirements.version,
        requirement_schema_version=requirements.schema_version,
        measurement_specs=specs,
        hard_gate_measurement_ids=(
            "software_release.structured_answer",
            "software_release.citation_provenance",
        ),
        normal_coverage_threshold=0.80,
        provenance=("meas0-software-release-measurement-freeze:v1",),
    )
    return seal_task_measurement_bundle(
        bundle_id="software-release.deterministic",
        version=1,
        task_frame=task_frame,
        goal_graph=goals,
        requirement_graph=requirements,
        measurement_graph=graph,
        acceptance_rules=(
            "hard gates and critical requirements must pass",
            "normal deterministic coverage must be at least 0.80",
        ),
        deterministic_check_refs=tuple(spec.evaluator_ref for spec in specs),
        judge_refs=(),
        metamorphic_relations=("material order must not alter the verdict",),
        uncertainty_and_escalation_rules=(
            "missing submitted evidence yields unknown",
            "conflicting submitted values yield disputed",
        ),
        measurement_budget=sum(spec.cost_estimate for spec in specs),
        provenance=(
            f"task-source-sha256:{subject_input.task_source_sha256}",
            f"hidden-answer-key-sha256:{answer_key_sha256}",
        ),
    )


@dataclass(frozen=True)
class SoftwareReleaseDeterministicEvaluator(ColdChainDeterministicEvaluator):
    def _verify_episode(self, episode: R1SealedEpisode) -> None:
        verify_software_release_episode_artifacts(
            episode,
            task_measurement_bundle=self.measurement_bundle,
        )

    def _evaluation_provenance(self) -> str:
        return "meas0-software-release-deterministic-evaluation:v1"

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
                    if requirement_id == "software_release.structured_answer"
                    else EvaluationStatus.UNKNOWN
                )
                for requirement_id, _, _ in _SOFTWARE_RELEASE_REQUIREMENTS
            }
        expected_facts = {
            item.fact_id: item for item in self._answer_key.key_facts
        }
        return {
            "software_release.structured_answer": artifact_status,
            "software_release.decision_hold": _scalar_status(
                answer.get("decision"),
                self._answer_key.decision,
            ),
            "software_release.auth_27_open": _fact_status(
                answer,
                expected_facts["auth_27_status"].accepted_values,
                "auth_27_status",
            ),
            "software_release.refund_regression_failed": _fact_status(
                answer,
                expected_facts["refund_regression"].accepted_values,
                "refund_regression",
            ),
            "software_release.security_conflict": _contradiction_status(
                answer,
                self._answer_key,
                "security_status_conflict",
            ),
            "software_release.critical_test_conflict": _contradiction_status(
                answer,
                self._answer_key,
                "critical_test_status_conflict",
            ),
            "software_release.citation_provenance": _citation_status(
                answer,
                self._answer_key,
                set(self._material_ids),
            ),
            "software_release.release_date": _fact_status(
                answer,
                expected_facts["planned_release_date"].accepted_values,
                "planned_release_date",
            ),
            "software_release.dashboard_snapshot_date": _fact_status(
                answer,
                expected_facts["dashboard_snapshot_date"].accepted_values,
                "dashboard_snapshot_date",
            ),
        }


def load_software_release_evaluator(
    *,
    fixture_root: str | Path | None = None,
) -> SoftwareReleaseDeterministicEvaluator:
    root = _r1_fixture_root(fixture_root)
    subject_input = load_software_release_subject_input(fixture_root=root)
    answer_key_path = root / SOFTWARE_RELEASE_TASK_ID / "answer_key.v1.json"
    try:
        answer_key_bytes = answer_key_path.read_bytes()
    except (OSError, FileNotFoundError) as error:
        raise SoftwareReleaseEvaluatorError(
            "software-release hidden answer key is unavailable"
        ) from error
    bundle = load_task_bundle(SOFTWARE_RELEASE_TASK_ID, fixture_root=root)
    return SoftwareReleaseDeterministicEvaluator(
        measurement_bundle=_build_software_release_measurement_bundle(
            subject_input,
            answer_key_sha256=_sha256_bytes(answer_key_bytes),
        ),
        _answer_key=bundle.answer_key,
        _answer_schema_bytes=_canonical_json_bytes(dict(bundle.task.answer_schema)),
        _answer_key_sha256=_sha256_bytes(answer_key_bytes),
        _material_ids=tuple(item.material_id for item in subject_input.materials),
    )


def build_software_release_episode(
    *,
    subject_input: R1SubjectInput,
    task_measurement_bundle: TaskMeasurementBundle,
    structured_answer_bytes: bytes | None,
    response_bytes: bytes,
) -> R1SealedEpisode:
    validate_task_measurement_bundle(task_measurement_bundle)
    if subject_input.task_id != SOFTWARE_RELEASE_TASK_ID:
        raise SoftwareReleaseEvaluatorError(
            "subject input is not software_release_readiness"
        )
    if task_measurement_bundle.task_frame.task_id != subject_input.task_id:
        raise SoftwareReleaseEvaluatorError(
            "measurement bundle targets a different task"
        )
    if structured_answer_bytes is not None and not isinstance(
        structured_answer_bytes, bytes
    ):
        raise SoftwareReleaseEvaluatorError(
            "structured_answer_bytes must be bytes or None"
        )
    if not isinstance(response_bytes, bytes):
        raise SoftwareReleaseEvaluatorError("response_bytes must be bytes")

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
            "action": "submit_software_release_readiness_assessment",
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
    lookup = dict(content_by_id)
    evidence: list[EpisodeEvidence] = [
        EpisodeEvidence(
            evidence_id=evidence_id,
            kind=EvidenceKind.INPUT,
            locator=f"evidence-task://{subject_input.task_id}/{evidence_id}",
            content_hash=_evidence_hash(content),
            provenance=("subject-visible-software-release-fixture:v1",),
        )
        for evidence_id, content in content_by_id
        if evidence_id.startswith("input:")
    ]
    evidence.append(
        EpisodeEvidence(
            evidence_id="action:submit",
            kind=EvidenceKind.ACTION,
            locator=f"evidence-task://{subject_input.task_id}/action/submit",
            content_hash=_evidence_hash(lookup["action:submit"]),
            causal_parent_ids=input_ids,
            provenance=("software-release-harness-action:v1",),
        )
    )
    if structured_answer_bytes is not None:
        evidence.append(
            EpisodeEvidence(
                evidence_id="artifact:structured_answer",
                kind=EvidenceKind.ARTIFACT,
                locator=(
                    "evidence-task://"
                    f"{subject_input.task_id}/artifact/structured-answer"
                ),
                content_hash=_evidence_hash(structured_answer_bytes),
                causal_parent_ids=("action:submit",),
                provenance=("software-release-harness-capture:v1",),
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
                locator=(
                    f"evidence-task://{subject_input.task_id}/state/submission"
                ),
                content_hash=_evidence_hash(state_bytes),
                causal_parent_ids=(state_parent,),
                provenance=("software-release-protected-state:v1",),
            ),
            EpisodeEvidence(
                evidence_id="trajectory:submission",
                kind=EvidenceKind.TRAJECTORY,
                locator=(
                    "evidence-task://"
                    f"{subject_input.task_id}/trajectory/submission"
                ),
                content_hash=_evidence_hash(trajectory_bytes),
                causal_parent_ids=("action:submit",),
                provenance=("software-release-harness-trajectory:v1",),
            ),
            EpisodeEvidence(
                evidence_id="response:final",
                kind=EvidenceKind.RESPONSE,
                locator=(
                    f"evidence-task://{subject_input.task_id}/response/final"
                ),
                content_hash=_evidence_hash(response_bytes),
                causal_parent_ids=("state:submission",),
                provenance=("software-release-harness-capture:v1",),
            ),
        )
    )
    graph = EpisodeGraph(
        episode_id="software-release.episode",
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
        provenance=("meas0-software-release-episode:v1",),
    )
    return R1SealedEpisode(
        sealed_episode=seal_episode_graph(
            task_measurement_bundle=task_measurement_bundle,
            episode_graph=graph,
            provenance=("meas0-software-release-episode-seal:v1",),
        ),
        artifacts=R1EpisodeArtifacts(items=tuple(content_by_id)),
    )


def _expected_locator(task_id: str, evidence_id: str) -> str:
    suffixes = {
        "action:submit": "action/submit",
        "artifact:structured_answer": "artifact/structured-answer",
        "state:submission": "state/submission",
        "trajectory:submission": "trajectory/submission",
        "response:final": "response/final",
    }
    suffix = suffixes.get(evidence_id, evidence_id)
    return f"evidence-task://{task_id}/{suffix}"


def verify_software_release_episode_artifacts(
    episode: R1SealedEpisode,
    *,
    task_measurement_bundle: TaskMeasurementBundle,
) -> None:
    try:
        verify_r1_episode_artifacts(
            episode,
            task_measurement_bundle=task_measurement_bundle,
        )
    except R1EvaluatorError as error:
        raise SoftwareReleaseEvaluatorError(str(error)) from error
    graph = episode.sealed_episode.episode_graph
    if graph.task_id != SOFTWARE_RELEASE_TASK_ID:
        raise SoftwareReleaseEvaluatorError(
            "software-release episode targets the wrong task"
        )
    for evidence in graph.evidence:
        expected = _expected_locator(graph.task_id, evidence.evidence_id)
        if evidence.locator != expected:
            raise SoftwareReleaseEvaluatorError(
                f"evidence locator mismatch: {evidence.evidence_id}"
            )


__all__ = [
    "SoftwareReleaseEvaluatorError",
    "SOFTWARE_RELEASE_TASK_ID",
    "SoftwareReleaseDeterministicEvaluator",
    "build_software_release_episode",
    "load_software_release_evaluator",
    "load_software_release_subject_input",
    "verify_software_release_episode_artifacts",
]
