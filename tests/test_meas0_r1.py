from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from biofield.meas0_r1 import (
    R1EvaluatorError,
    build_cold_chain_episode,
    load_cold_chain_evaluator,
    load_cold_chain_subject_input,
    verify_r1_episode_artifacts,
)
from biofield.measurement import EvaluationStatus, fuse_evidence


FIXTURE_ROOT = Path(__file__).parents[1] / "src" / "biofield" / "fixtures" / "r1"


def _answer_bytes(
    *,
    citations: bool = True,
    contradictions: bool = True,
    conflicting_generator: bool = False,
) -> bytes:
    key_facts: list[dict[str, object]] = [
        {
            "fact_id": "planned_launch_date",
            "value": "2026-04-18",
            "citations": ["operations_brief"] if citations else [],
        },
        {
            "fact_id": "generator_test",
            "value": "failed",
            "citations": ["maintenance_log"] if citations else [],
        },
        {
            "fact_id": "replacement_arrival",
            "value": "2026-04-20",
            "citations": ["maintenance_log"] if citations else [],
        },
        {
            "fact_id": "s4_certificate",
            "value": "expired",
            "citations": ["inspection_report"] if citations else [],
        },
        {
            "fact_id": "readiness",
            "value": "hold",
            "citations": (
                ["maintenance_log", "inspection_report"] if citations else []
            ),
        },
    ]
    if conflicting_generator:
        key_facts.append(
            {
                "fact_id": "generator_test",
                "value": "passed",
                "citations": ["operations_brief"],
            }
        )
    conflict_items = (
        [
            {
                "contradiction_id": "generator_test_conflict",
                "material_ids": ["operations_brief", "maintenance_log"],
            },
            {
                "contradiction_id": "sensor_certificate_conflict",
                "material_ids": ["vendor_letter", "inspection_report"],
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


def _status_by_measurement(observations: tuple[object, ...]) -> dict[str, object]:
    return {
        observation.measurement_id: observation.status  # type: ignore[attr-defined]
        for observation in observations
    }


def test_subject_loader_does_not_read_or_expose_hidden_answer_key(
    tmp_path: Path,
) -> None:
    source = FIXTURE_ROOT / "cold_chain_readiness" / "task.v1.json"
    task_directory = tmp_path / "cold_chain_readiness"
    task_directory.mkdir()
    (task_directory / "task.v1.json").write_bytes(source.read_bytes())

    subject_input = load_cold_chain_subject_input(fixture_root=tmp_path)
    payload = subject_input.to_dict()
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert subject_input.task_id == "cold_chain_readiness"
    assert len(subject_input.task_source_sha256) == 64
    assert "answer_key" not in payload
    assert "accepted_values" not in serialized
    assert "supporting_material_ids" not in serialized


def test_correct_r1_artifact_produces_sealed_deterministic_observations() -> None:
    subject_input = load_cold_chain_subject_input(fixture_root=FIXTURE_ROOT)
    evaluator = load_cold_chain_evaluator(fixture_root=FIXTURE_ROOT)
    episode = build_cold_chain_episode(
        subject_input=subject_input,
        task_measurement_bundle=evaluator.measurement_bundle,
        structured_answer_bytes=_answer_bytes(),
        response_bytes="结论：应暂停上线；结构化产物包含依据。".encode(),
    )

    verify_r1_episode_artifacts(
        episode,
        task_measurement_bundle=evaluator.measurement_bundle,
    )
    observations = evaluator.evaluate(episode)
    result = fuse_evidence(
        result_id="r1-correct",
        task_measurement_bundle=evaluator.measurement_bundle,
        sealed_episode=episode.sealed_episode,
        observations=observations,
    )

    expected_ids = {
        spec.measurement_id
        for spec in evaluator.measurement_bundle.measurement_graph.measurement_specs
    }
    assert {item.measurement_id for item in observations} == expected_ids
    assert all(item.status is EvaluationStatus.PASS for item in observations)
    assert all(item.cost > 0 for item in observations)
    assert sum(item.cost for item in observations) == pytest.approx(
        sum(
            spec.cost_estimate
            for spec in evaluator.measurement_bundle.measurement_graph.measurement_specs
        )
    )
    assert result.outcome is EvaluationStatus.PASS


def test_text_claim_without_structured_artifact_cannot_pass() -> None:
    subject_input = load_cold_chain_subject_input(fixture_root=FIXTURE_ROOT)
    evaluator = load_cold_chain_evaluator(fixture_root=FIXTURE_ROOT)
    episode = build_cold_chain_episode(
        subject_input=subject_input,
        task_measurement_bundle=evaluator.measurement_bundle,
        structured_answer_bytes=None,
        response_bytes=(
            "决定 hold。发电机测试失败，S4 已过期，材料冲突均已核对。"
        ).encode(),
    )

    observations = evaluator.evaluate(episode)
    statuses = _status_by_measurement(observations)
    result = fuse_evidence(
        result_id="r1-text-only",
        task_measurement_bundle=evaluator.measurement_bundle,
        sealed_episode=episode.sealed_episode,
        observations=observations,
    )

    assert statuses["r1.structured_answer"] is EvaluationStatus.FAIL
    assert statuses["r1.decision_hold"] is EvaluationStatus.UNKNOWN
    assert result.outcome is EvaluationStatus.FAIL


def test_missing_and_conflicting_evidence_remain_distinct() -> None:
    subject_input = load_cold_chain_subject_input(fixture_root=FIXTURE_ROOT)
    evaluator = load_cold_chain_evaluator(fixture_root=FIXTURE_ROOT)

    missing = build_cold_chain_episode(
        subject_input=subject_input,
        task_measurement_bundle=evaluator.measurement_bundle,
        structured_answer_bytes=_answer_bytes(
            citations=False,
            contradictions=False,
        ),
        response_bytes=b"hold",
    )
    missing_statuses = _status_by_measurement(evaluator.evaluate(missing))

    conflicting = build_cold_chain_episode(
        subject_input=subject_input,
        task_measurement_bundle=evaluator.measurement_bundle,
        structured_answer_bytes=_answer_bytes(conflicting_generator=True),
        response_bytes=b"hold",
    )
    conflicting_statuses = _status_by_measurement(evaluator.evaluate(conflicting))

    assert missing_statuses["r1.citation_provenance"] is EvaluationStatus.FAIL
    assert (
        missing_statuses["r1.generator_conflict"]
        is EvaluationStatus.UNKNOWN
    )
    assert missing_statuses["r1.sensor_conflict"] is EvaluationStatus.UNKNOWN
    assert (
        conflicting_statuses["r1.generator_failed"]
        is EvaluationStatus.DISPUTED
    )


def test_evaluator_rejects_artifact_bytes_changed_after_episode_seal() -> None:
    subject_input = load_cold_chain_subject_input(fixture_root=FIXTURE_ROOT)
    evaluator = load_cold_chain_evaluator(fixture_root=FIXTURE_ROOT)
    episode = build_cold_chain_episode(
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
    tampered_episode = replace(episode, artifacts=tampered_artifacts)

    with pytest.raises(R1EvaluatorError, match="artifact bytes.*sealed evidence"):
        verify_r1_episode_artifacts(
            tampered_episode,
            task_measurement_bundle=evaluator.measurement_bundle,
        )
    with pytest.raises(R1EvaluatorError, match="artifact bytes.*sealed evidence"):
        evaluator.evaluate(tampered_episode)
