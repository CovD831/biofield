from __future__ import annotations

import hashlib
import inspect
import json
from copy import deepcopy
from dataclasses import replace

import pytest

from biofield.meas0_formal_metrics import formal_attack_manifest
from biofield.meas0_gold_outcome_adapter_v3 import (
    V3_OUTCOME_PACKAGE_INTEGRATION_GAP,
    SimulatedGoldBoundArmCaseOutcomeV3,
    V3GoldOutcomeCompositionError,
    derive_v3_gold_bound_arm_case_outcome,
)
from test_meas0_formal_outcomes import _build_formal_fixture
from test_meas0_gold_facts_v3 import _derive, _gold_sources


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


@pytest.fixture(scope="module")
def v3_sources(tmp_path_factory: pytest.TempPathFactory):
    _, _, _, legacy_package = _build_formal_fixture(tmp_path_factory)
    gold_sources = _gold_sources()
    return {
        **gold_sources,
        "gold_facts": _derive(gold_sources),
        "artifact_facts": legacy_package.artifact_facts[0],
        "detection_record": legacy_package.detection_records[0],
        "legacy_outcome": legacy_package.outcomes[0],
    }


def _derive_outcome(values):
    return derive_v3_gold_bound_arm_case_outcome(
        artifact_facts=values["artifact_facts"],
        detection_record=values["detection_record"],
        gold_facts=values["gold_facts"],
        gold_artifact=values["gold_artifact"],
        pilot_readiness=values["pilot_readiness"],
        input_manifest=values["input_manifest"],
    )


def _restore_outcome(payload, values):
    return SimulatedGoldBoundArmCaseOutcomeV3.restore_from_sources(
        payload,
        artifact_facts=values["artifact_facts"],
        detection_record=values["detection_record"],
        gold_facts=values["gold_facts"],
        gold_artifact=values["gold_artifact"],
        pilot_readiness=values["pilot_readiness"],
        input_manifest=values["input_manifest"],
    )


def test_v3_outcome_strict_codec_replays_typed_sources(v3_sources) -> None:
    outcome = _derive_outcome(v3_sources)
    restored = _restore_outcome(outcome.to_dict(), v3_sources)

    assert restored == outcome
    assert restored.claim_scope == "simulated_nonclaim"
    assert restored.formal_eligible is False


def test_v3_outcome_codec_rejects_shape_resigning_and_persisted_gold_tamper(
    v3_sources,
) -> None:
    payload = _derive_outcome(v3_sources).to_dict()

    with pytest.raises(V3GoldOutcomeCompositionError, match="serialized"):
        _restore_outcome({**payload, "unknown": None}, v3_sources)
    missing = dict(payload)
    missing.pop("gold_facts_hash")
    with pytest.raises(V3GoldOutcomeCompositionError, match="serialized"):
        _restore_outcome(missing, v3_sources)
    confused = {**payload, "test_only": 1}
    with pytest.raises(V3GoldOutcomeCompositionError, match="serialized"):
        _restore_outcome(confused, v3_sources)
    with pytest.raises(V3GoldOutcomeCompositionError, match="serialized"):
        _restore_outcome(["not", "a", "mapping"], v3_sources)

    for name, value in (
        ("gold_status", "fail"),
        ("accept_allowed", False),
        ("safety_violation", True),
        ("comparison_block_id", "resigned.block"),
        ("source_lock_hash", "f" * 64),
    ):
        resigned = deepcopy(payload)
        resigned[name] = value
        body = dict(resigned)
        body.pop("outcome_hash")
        resigned["outcome_hash"] = _canonical_hash(body)
        with pytest.raises(V3GoldOutcomeCompositionError, match="serialized"):
            _restore_outcome(resigned, v3_sources)

    reordered = deepcopy(payload)
    reordered["selected_gold_record_hashes"] = list(
        reversed(reordered["selected_gold_record_hashes"])
    )
    body = dict(reordered)
    body.pop("outcome_hash")
    reordered["outcome_hash"] = _canonical_hash(body)
    with pytest.raises(V3GoldOutcomeCompositionError, match="serialized"):
        _restore_outcome(reordered, v3_sources)
    replaced_hash = deepcopy(payload)
    replaced_hash["selected_gold_record_hashes"][0] = "f" * 64
    body = dict(replaced_hash)
    body.pop("outcome_hash")
    replaced_hash["outcome_hash"] = _canonical_hash(body)
    with pytest.raises(V3GoldOutcomeCompositionError, match="serialized"):
        _restore_outcome(replaced_hash, v3_sources)

    wrong_readiness = dict(v3_sources)
    wrong_readiness["pilot_readiness"] = v3_sources["pre_jcal_readiness"]
    with pytest.raises(V3GoldOutcomeCompositionError, match="readiness"):
        _restore_outcome(payload, wrong_readiness)


def test_v3_outcome_only_accepts_typed_gold_facts_and_is_nonclaim(
    v3_sources,
) -> None:
    outcome = _derive_outcome(v3_sources)
    facts = v3_sources["gold_facts"]

    assert isinstance(outcome, SimulatedGoldBoundArmCaseOutcomeV3)
    assert outcome.case == facts.case_identity
    assert outcome.arm_id == v3_sources["artifact_facts"].arm_id
    assert outcome.gold_status == facts.gold_status
    assert outcome.accept_allowed is facts.accept_allowed
    assert outcome.safety_violation is facts.safety_violation
    assert outcome.gold_facts_hash == facts.facts_hash
    assert outcome.selected_gold_record_hashes == facts.selected_gold_record_hashes
    assert outcome.gold_binding_hash == facts.gold_binding_hash
    assert outcome.gold_artifact_manifest_hash == facts.gold_artifact_manifest_hash
    assert outcome.phase_readiness_hash == facts.phase_readiness_hash
    assert outcome.input_manifest_hash == facts.input_manifest_hash
    assert outcome.common_ancestry_hash == facts.common_ancestry_hash
    assert outcome.claim_scope == "simulated_nonclaim"
    assert outcome.test_only is True
    assert outcome.production_authorized is False
    assert outcome.formal_eligible is False
    assert "formal_result" not in outcome.to_dict()
    assert {
        "gold_status",
        "accept_allowed",
        "safety_violation",
        "selected_gold_record_hashes",
    }.isdisjoint(inspect.signature(derive_v3_gold_bound_arm_case_outcome).parameters)


def test_v3_rejects_facts_substitution_cross_case_and_legacy_masquerade(
    v3_sources,
) -> None:
    with pytest.raises(V3GoldOutcomeCompositionError, match="GoldOutcomeFacts"):
        derive_v3_gold_bound_arm_case_outcome(
            artifact_facts=v3_sources["artifact_facts"],
            detection_record=v3_sources["detection_record"],
            gold_facts=v3_sources["legacy_outcome"],
            gold_artifact=v3_sources["gold_artifact"],
            pilot_readiness=v3_sources["pilot_readiness"],
            input_manifest=v3_sources["input_manifest"],
        )

    other_sources = _gold_sources()
    other_sources["case_identity"] = next(
        case
        for case in formal_attack_manifest("pilot").cases
        if case.case_id != v3_sources["gold_facts"].case_identity.case_id
    )
    other_facts = _derive(other_sources)
    cross_case = dict(v3_sources)
    cross_case["gold_facts"] = other_facts
    with pytest.raises(V3GoldOutcomeCompositionError, match="case"):
        _derive_outcome(cross_case)


def test_v3_rejects_block_source_binding_and_hash_resigning(v3_sources) -> None:
    outcome = _derive_outcome(v3_sources)

    with pytest.raises(V3GoldOutcomeCompositionError, match="comparison block"):
        replace(outcome, comparison_block_id="substituted.block")
    with pytest.raises(V3GoldOutcomeCompositionError, match="source lock"):
        replace(outcome, source_lock_hash="f" * 64)
    with pytest.raises(V3GoldOutcomeCompositionError, match="selected Gold"):
        replace(outcome, selected_gold_record_hashes=("f" * 64,))
    with pytest.raises(V3GoldOutcomeCompositionError, match="facts hash"):
        replace(outcome, gold_facts_hash="f" * 64)
    with pytest.raises(V3GoldOutcomeCompositionError, match="outcome hash"):
        replace(outcome, outcome_hash="f" * 64)
    with pytest.raises(V3GoldOutcomeCompositionError, match="factory"):
        replace(outcome, _derivation_token=None)


def test_v3_rejects_gold_artifact_and_readiness_substitution(v3_sources) -> None:
    wrong_artifact = dict(v3_sources)
    wrong_artifact["gold_artifact"] = replace(
        v3_sources["gold_artifact"],
        comparison_block_id="other-block",
    )
    with pytest.raises(V3GoldOutcomeCompositionError, match="Gold artifact"):
        _derive_outcome(wrong_artifact)

    wrong_readiness = dict(v3_sources)
    wrong_readiness["pilot_readiness"] = v3_sources["pre_jcal_readiness"]
    with pytest.raises(V3GoldOutcomeCompositionError, match="readiness"):
        _derive_outcome(wrong_readiness)


def test_current_formal_package_has_no_safe_v3_nonclaim_slot() -> None:
    assert "cannot accept" in V3_OUTCOME_PACKAGE_INTEGRATION_GAP
