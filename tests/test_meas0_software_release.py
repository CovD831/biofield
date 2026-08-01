from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from biofield.meas0_software_release import (
    SoftwareReleaseEvaluatorError,
    build_software_release_episode,
    load_software_release_evaluator,
    load_software_release_subject_input,
    verify_software_release_episode_artifacts,
)
from biofield.measurement import (
    EvaluationStatus,
    fuse_evidence,
    seal_episode_graph,
)


FIXTURE_ROOT = Path(__file__).parents[1] / "src" / "biofield" / "fixtures" / "r1"


def _answer_bytes(
    *,
    citations: bool = True,
    contradictions: bool = True,
    conflicting_auth_status: bool = False,
) -> bytes:
    key_facts: list[dict[str, object]] = [
        {
            "fact_id": "planned_release_date",
            "value": "2026-07-18",
            "citations": ["release_brief"] if citations else [],
        },
        {
            "fact_id": "auth_27_status",
            "value": "open",
            "citations": ["security_audit"] if citations else [],
        },
        {
            "fact_id": "refund_regression",
            "value": "failed",
            "citations": ["ci_log"] if citations else [],
        },
        {
            "fact_id": "dashboard_snapshot_date",
            "value": "2026-07-09",
            "citations": ["dashboard_export"] if citations else [],
        },
        {
            "fact_id": "readiness",
            "value": "hold",
            "citations": (
                ["security_audit", "ci_log"] if citations else []
            ),
        },
    ]
    if conflicting_auth_status:
        key_facts.append(
            {
                "fact_id": "auth_27_status",
                "value": "closed",
                "citations": ["release_brief"],
            }
        )
    conflict_items = (
        [
            {
                "contradiction_id": "security_status_conflict",
                "material_ids": ["release_brief", "security_audit"],
            },
            {
                "contradiction_id": "critical_test_status_conflict",
                "material_ids": ["dashboard_export", "ci_log"],
            },
        ]
        if contradictions
        else []
    )
    return json.dumps(
        {
            "decision": "hold",
            "key_facts": key_facts,
            "contradictions": conflict_items,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _statuses(observations: tuple[object, ...]) -> dict[str, object]:
    return {
        observation.measurement_id: observation.status  # type: ignore[attr-defined]
        for observation in observations
    }


def test_software_release_subject_loader_is_independent_of_hidden_answer_key(
    tmp_path: Path,
) -> None:
    source = FIXTURE_ROOT / "software_release_readiness" / "task.v1.json"
    task_directory = tmp_path / "software_release_readiness"
    task_directory.mkdir()
    (task_directory / "task.v1.json").write_bytes(source.read_bytes())

    subject_input = load_software_release_subject_input(fixture_root=tmp_path)
    serialized = json.dumps(
        subject_input.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
    )

    assert subject_input.task_id == "software_release_readiness"
    assert len(subject_input.task_source_sha256) == 64
    assert "accepted_values" not in serialized
    assert "supporting_material_ids" not in serialized


def test_correct_software_release_artifact_produces_costed_result() -> None:
    subject_input = load_software_release_subject_input(
        fixture_root=FIXTURE_ROOT
    )
    evaluator = load_software_release_evaluator(fixture_root=FIXTURE_ROOT)
    episode = build_software_release_episode(
        subject_input=subject_input,
        task_measurement_bundle=evaluator.measurement_bundle,
        structured_answer_bytes=_answer_bytes(),
        response_bytes="结论：阻止发布；结构化产物包含证据。".encode(),
    )

    verify_software_release_episode_artifacts(
        episode,
        task_measurement_bundle=evaluator.measurement_bundle,
    )
    observations = evaluator.evaluate(episode)
    result = fuse_evidence(
        result_id="software-release-correct",
        task_measurement_bundle=evaluator.measurement_bundle,
        sealed_episode=episode.sealed_episode,
        observations=observations,
    )

    assert all(item.status is EvaluationStatus.PASS for item in observations)
    assert all(item.cost > 0 for item in observations)
    assert sum(item.cost for item in observations) == pytest.approx(
        evaluator.measurement_bundle.measurement_budget
    )
    assert result.outcome is EvaluationStatus.PASS


def test_software_release_text_only_cannot_replace_structured_artifact() -> None:
    subject_input = load_software_release_subject_input(
        fixture_root=FIXTURE_ROOT
    )
    evaluator = load_software_release_evaluator(fixture_root=FIXTURE_ROOT)
    episode = build_software_release_episode(
        subject_input=subject_input,
        task_measurement_bundle=evaluator.measurement_bundle,
        structured_answer_bytes=None,
        response_bytes=(
            "hold：AUTH-27 仍 open，退款幂等回归失败，存在两项材料冲突。"
        ).encode(),
    )

    observations = evaluator.evaluate(episode)
    statuses = _statuses(observations)
    result = fuse_evidence(
        result_id="software-release-text-only",
        task_measurement_bundle=evaluator.measurement_bundle,
        sealed_episode=episode.sealed_episode,
        observations=observations,
    )

    assert (
        statuses["software_release.structured_answer"]
        is EvaluationStatus.FAIL
    )
    assert (
        statuses["software_release.decision_hold"]
        is EvaluationStatus.UNKNOWN
    )
    assert result.outcome is EvaluationStatus.FAIL


def test_software_release_missing_and_conflicting_evidence_are_distinct() -> None:
    subject_input = load_software_release_subject_input(
        fixture_root=FIXTURE_ROOT
    )
    evaluator = load_software_release_evaluator(fixture_root=FIXTURE_ROOT)
    missing = build_software_release_episode(
        subject_input=subject_input,
        task_measurement_bundle=evaluator.measurement_bundle,
        structured_answer_bytes=_answer_bytes(
            citations=False,
            contradictions=False,
        ),
        response_bytes=b"hold",
    )
    conflicting = build_software_release_episode(
        subject_input=subject_input,
        task_measurement_bundle=evaluator.measurement_bundle,
        structured_answer_bytes=_answer_bytes(conflicting_auth_status=True),
        response_bytes=b"hold",
    )

    missing_statuses = _statuses(evaluator.evaluate(missing))
    conflicting_statuses = _statuses(evaluator.evaluate(conflicting))

    assert (
        missing_statuses["software_release.citation_provenance"]
        is EvaluationStatus.FAIL
    )
    assert (
        missing_statuses["software_release.security_conflict"]
        is EvaluationStatus.UNKNOWN
    )
    assert (
        missing_statuses["software_release.critical_test_conflict"]
        is EvaluationStatus.UNKNOWN
    )
    assert (
        conflicting_statuses["software_release.auth_27_open"]
        is EvaluationStatus.DISPUTED
    )


def test_software_release_verifier_rejects_bytes_and_locator_tampering() -> None:
    subject_input = load_software_release_subject_input(
        fixture_root=FIXTURE_ROOT
    )
    evaluator = load_software_release_evaluator(fixture_root=FIXTURE_ROOT)
    episode = build_software_release_episode(
        subject_input=subject_input,
        task_measurement_bundle=evaluator.measurement_bundle,
        structured_answer_bytes=_answer_bytes(),
        response_bytes=b"hold",
    )
    tampered_artifacts = replace(
        episode.artifacts,
        items=tuple(
            (evidence_id, b'{"decision":"proceed"}')
            if evidence_id == "artifact:structured_answer"
            else (evidence_id, content)
            for evidence_id, content in episode.artifacts.items
        ),
    )
    with pytest.raises(SoftwareReleaseEvaluatorError, match="content_hash"):
        verify_software_release_episode_artifacts(
            replace(episode, artifacts=tampered_artifacts),
            task_measurement_bundle=evaluator.measurement_bundle,
        )

    evidence = list(episode.sealed_episode.episode_graph.evidence)
    evidence[0] = replace(
        evidence[0],
        locator="evidence-task://wrong-task/input:task",
    )
    changed_graph = replace(
        episode.sealed_episode.episode_graph,
        evidence=tuple(evidence),
    )
    resealed = seal_episode_graph(
        task_measurement_bundle=evaluator.measurement_bundle,
        episode_graph=changed_graph,
        provenance=("test-reseal:locator-tamper",),
    )
    locator_tampered = replace(episode, sealed_episode=resealed)

    with pytest.raises(SoftwareReleaseEvaluatorError, match="locator"):
        verify_software_release_episode_artifacts(
            locator_tampered,
            task_measurement_bundle=evaluator.measurement_bundle,
        )
    with pytest.raises(SoftwareReleaseEvaluatorError, match="locator"):
        evaluator.evaluate(locator_tampered)
