from __future__ import annotations

import json
from pathlib import Path

import pytest

from biofield.evidence_task import (
    EvidenceTaskError,
    available_task_ids,
    load_task_bundle,
    score_answer,
)


FIXTURE_ROOT = Path(__file__).parents[1] / "src" / "biofield" / "fixtures" / "r1"


def _perfect_answer(bundle: object) -> dict[str, object]:
    answer_key = bundle.answer_key  # type: ignore[attr-defined]
    return {
        "decision": answer_key.decision,
        "key_facts": [
            {
                "fact_id": fact.fact_id,
                "value": fact.accepted_values[0],
                "citations": list(
                    fact.supporting_material_ids[: fact.minimum_citations]
                ),
            }
            for fact in answer_key.key_facts
        ],
        "contradictions": [
            {
                "contradiction_id": contradiction.contradiction_id,
                "material_ids": list(contradiction.material_ids),
            }
            for contradiction in answer_key.contradictions
        ],
    }


def test_r1_contains_two_versioned_json_task_bundles() -> None:
    assert available_task_ids(FIXTURE_ROOT) == (
        "cold_chain_readiness",
        "software_release_readiness",
    )

    for task_id in available_task_ids(FIXTURE_ROOT):
        task_path = FIXTURE_ROOT / task_id / "task.v1.json"
        key_path = FIXTURE_ROOT / task_id / "answer_key.v1.json"
        assert json.loads(task_path.read_text(encoding="utf-8"))["task_version"] == "1"
        assert json.loads(key_path.read_text(encoding="utf-8"))[
            "answer_key_version"
        ] == "1"

        bundle = load_task_bundle(task_id, fixture_root=FIXTURE_ROOT)
        assert bundle.task.task_version == "1"
        assert bundle.task.answer_key_version == "1"
        assert bundle.answer_key.task_version == bundle.task.task_version
        assert bundle.answer_key.answer_key_version == bundle.task.answer_key_version


def test_each_task_is_small_cross_material_and_available_to_one_agent() -> None:
    for task_id in available_task_ids(FIXTURE_ROOT):
        bundle = load_task_bundle(task_id, fixture_root=FIXTURE_ROOT)
        task = bundle.task
        material_ids = {material.material_id for material in task.materials}

        assert 3 <= len(task.materials) <= 5
        assert task.cross_material_required is True
        assert task.single_agent_has_all_materials is True
        assert task.answer_schema["type"] == "object"
        assert set(task.fact_value_contracts) == {
            fact.fact_id for fact in bundle.answer_key.key_facts
        }
        assert all(
            contract["type"] == "string"
            for contract in task.fact_value_contracts.values()
        )
        assert set(task.answer_schema["required"]) == {
            "decision",
            "key_facts",
            "contradictions",
        }
        assert bundle.answer_key.contradictions
        assert any(
            fact.minimum_citations >= 2 for fact in bundle.answer_key.key_facts
        )
        assert all(
            set(contradiction.material_ids) <= material_ids
            for contradiction in bundle.answer_key.contradictions
        )


def test_fact_value_contracts_expose_allowed_shapes_without_revealing_answers() -> None:
    bundle = load_task_bundle("cold_chain_readiness", fixture_root=FIXTURE_ROOT)
    contracts = bundle.task.fact_value_contracts

    assert contracts["generator_test"]["enum"] == ["passed", "failed", "unknown"]
    assert contracts["s4_certificate"]["enum"] == ["valid", "expired", "missing"]
    assert contracts["readiness"]["enum"] == [
        "proceed",
        "hold",
        "insufficient_evidence",
    ]
    assert contracts["planned_launch_date"]["pattern"] == r"^\d{4}-\d{2}-\d{2}$"


@pytest.mark.parametrize(
    "task_id", ["cold_chain_readiness", "software_release_readiness"]
)
def test_perfect_structured_answers_receive_full_component_scores(task_id: str) -> None:
    bundle = load_task_bundle(task_id, fixture_root=FIXTURE_ROOT)

    score = score_answer(bundle, _perfect_answer(bundle))

    assert score.critical_fact_score == 1.0
    assert score.citation_score == 1.0
    assert score.contradiction_score == 1.0
    assert score.decision_score == 1.0
    assert score.total_score == 1.0
    assert score.issues == ()
    assert json.loads(json.dumps(score.to_dict()))["total_score"] == 1.0


def test_scorer_distinguishes_facts_citations_and_contradictions() -> None:
    bundle = load_task_bundle("cold_chain_readiness", fixture_root=FIXTURE_ROOT)
    perfect = _perfect_answer(bundle)

    no_citations = {
        **perfect,
        "key_facts": [
            {**fact, "citations": []} for fact in perfect["key_facts"]  # type: ignore[union-attr]
        ],
    }
    no_contradictions = {**perfect, "contradictions": []}
    wrong_facts = {
        **perfect,
        "key_facts": [
            {**fact, "value": "wrong"} for fact in perfect["key_facts"]  # type: ignore[union-attr]
        ],
    }

    fact_only = score_answer(bundle, no_citations)
    without_conflicts = score_answer(bundle, no_contradictions)
    incorrect = score_answer(bundle, wrong_facts)

    assert fact_only.critical_fact_score == 1.0
    assert fact_only.citation_score == 0.0
    assert fact_only.contradiction_score == 1.0
    assert without_conflicts.critical_fact_score == 1.0
    assert without_conflicts.citation_score == 1.0
    assert without_conflicts.contradiction_score == 0.0
    assert incorrect.critical_fact_score == 0.0
    assert incorrect.citation_score == 0.0


def test_scorer_is_deterministic_and_handles_malformed_partial_answers() -> None:
    bundle = load_task_bundle(
        "software_release_readiness", fixture_root=FIXTURE_ROOT
    )
    partial = {
        "decision": "hold",
        "key_facts": "not-a-list",
        "contradictions": [{"material_ids": ["release_brief"]}],
    }

    first = score_answer(bundle, partial)
    second = score_answer(bundle, partial)

    assert first == second
    assert first.total_score < 0.5
    assert first.issues


def test_loader_rejects_path_traversal_and_unknown_versions() -> None:
    with pytest.raises(EvidenceTaskError, match="safe path segment"):
        load_task_bundle("../cold_chain_readiness", fixture_root=FIXTURE_ROOT)
    with pytest.raises(EvidenceTaskError, match="not found"):
        load_task_bundle(
            "cold_chain_readiness", task_version="999", fixture_root=FIXTURE_ROOT
        )
