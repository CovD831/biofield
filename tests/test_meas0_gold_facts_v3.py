from __future__ import annotations

import hashlib
import inspect
import json
from copy import deepcopy
from dataclasses import replace

import pytest

from biofield.measurement import EvaluationStatus
from biofield.meas0_formal_lifecycle import PhaseCheckpointTarget
from biofield.meas0_formal_metrics import FormalCaseIdentity, formal_attack_manifest
from biofield.meas0_gold_facts_v3 import (
    GoldFactsDerivationError,
    GoldOutcomeFacts,
    derive_gold_outcome_facts,
)
from biofield.meas0_gold_lock_v3 import create_simulated_gold_order_lock_receipt
from biofield.meas0_phase_readiness import (
    create_simulated_phase_readiness_receipt,
)
from biofield.meas0_readiness import (
    AdjudicationRecord,
    BlindReviewerRecord,
    GoldArtifactManifest,
    GoldRecord,
    GoldRunValidity,
    GoldScopeItem,
    GoldScopeManifest,
    formal_gold_binding_hash,
)
from biofield.meas0_trust import AuthorizationCheckpoint
from test_meas0_pilot_plan_v3 import (
    _authorization,
    _ledger,
    _price_manifest,
    _readiness_pair,
    _source_lock,
    _stage_budget_manifest,
)


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


def _gold_sources(*, include_gold_order_lock: bool = True):
    price = _price_manifest()
    budget = _stage_budget_manifest()
    ledger = _ledger(price, budget)
    source_lock = _source_lock()
    initial_readiness = _readiness_pair(
        price_manifest=price,
        stage_budget_manifest=budget,
        ledger=ledger,
        source_lock_hash=source_lock.source_lock_hash,
    )
    manifest = initial_readiness[0]
    cases = formal_attack_manifest("pilot").cases
    items = tuple(
        GoldScopeItem(
            case_id=case.case_id,
            requirement_ids=(("outcome", "safety") if index == 0 else ("outcome",)),
        )
        for index, case in enumerate(cases)
    )
    semantic_key = f"{cases[0].case_id}::outcome"
    scope = GoldScopeManifest(
        manifest_id="pytest.gold-scope.v3",
        version=1,
        case_scope_hash=manifest.case_scope_manifest_hash,
        items=items,
        semantic_gold_keys=(semantic_key,),
    )
    reviews: list[BlindReviewerRecord] = []
    adjudications: list[AdjudicationRecord] = []
    records: list[GoldRecord] = []
    for item in scope.items:
        for requirement_id in item.requirement_ids:
            key = f"{item.case_id}::{requirement_id}"
            first = BlindReviewerRecord(
                review_id=f"review-a::{key}",
                reviewer_role_id=f"reviewer-a::{key}",
                case_id=item.case_id,
                requirement_id=requirement_id,
                verdict=EvaluationStatus.PASS,
                evidence_refs=(f"evidence::{key}",),
                rationale="reviewed locked test Gold",
                blinded_to_arm=True,
                blinded_to_model=True,
            )
            selected = [first]
            adjudication = None
            if key == semantic_key:
                second = BlindReviewerRecord(
                    review_id=f"review-b::{key}",
                    reviewer_role_id=f"reviewer-b::{key}",
                    case_id=item.case_id,
                    requirement_id=requirement_id,
                    verdict=EvaluationStatus.FAIL,
                    evidence_refs=(f"evidence::{key}",),
                    rationale="independent disagreement",
                    blinded_to_arm=True,
                    blinded_to_model=True,
                )
                selected.append(second)
                adjudication = AdjudicationRecord(
                    adjudication_id=f"adjudication::{key}",
                    case_id=item.case_id,
                    requirement_id=requirement_id,
                    first_review_hash=first.contract_hash,
                    first_verdict=first.verdict,
                    second_review_hash=second.contract_hash,
                    second_verdict=second.verdict,
                    adjudicator_role_id=f"adjudicator::{key}",
                    final_verdict=EvaluationStatus.PASS,
                    evidence_refs=(f"evidence::{key}",),
                    rationale="resolved disagreement",
                )
                adjudications.append(adjudication)
            reviews.extend(selected)
            records.append(
                GoldRecord(
                    gold_id=f"gold::{key}",
                    case_id=item.case_id,
                    requirement_id=requirement_id,
                    verdict=EvaluationStatus.PASS,
                    evidence_refs=(f"evidence::{key}",),
                    rationale="locked case-level truth",
                    gold_source_ref=f"source::{key}",
                    author_role_id=f"gold-author::{key}",
                    semantic=key == semantic_key,
                    gold_run_validity=GoldRunValidity.VALID,
                    gold_status=EvaluationStatus.PASS,
                    accept_allowed=True,
                    safety_violation=False,
                    reviewer_record_hashes=tuple(
                        review.contract_hash for review in selected
                    ),
                    adjudication_record_hash=(
                        adjudication.contract_hash if adjudication is not None else None
                    ),
                )
            )
    record_tuple = tuple(records)
    review_tuple = tuple(reviews)
    adjudication_tuple = tuple(adjudications)
    binding_hash = formal_gold_binding_hash(scope, record_tuple)
    artifact = GoldArtifactManifest(
        manifest_id="pytest.gold-artifact.v3",
        version=1,
        comparison_block_id=manifest.comparison_block_id,
        gold_scope_hash=scope.contract_hash,
        gold_binding_hash=binding_hash,
        gold_record_hashes=tuple(item.contract_hash for item in record_tuple),
        reviewer_record_hashes=tuple(item.contract_hash for item in review_tuple),
        adjudication_record_hashes=tuple(
            item.contract_hash for item in adjudication_tuple
        ),
    )
    old_readiness = initial_readiness[3]
    bindings = dict(old_readiness.target.evidence_bindings)
    bindings["gold_binding"] = binding_hash
    pre_target = initial_readiness[1].target
    target = PhaseCheckpointTarget.create(
        checkpoint=AuthorizationCheckpoint.PILOT_START,
        lifecycle_id=pre_target.lifecycle_id,
        comparison_block_id=pre_target.comparison_block_id,
        authority_role_id=pre_target.authority_role_id,
        design_hash=pre_target.design_hash,
        source_lock_hash=pre_target.source_lock_hash,
        common_ancestry_hash=pre_target.common_ancestry_hash,
        ledger_pre_head_hash=old_readiness.ledger_head_hash,
        evidence_bindings=bindings,
        previous_target=pre_target,
    )
    readiness = create_simulated_phase_readiness_receipt(
        target=target,
        authorization=_authorization(target),
        stage_evidence_hashes=bindings,
        previous_receipt=initial_readiness[1],
        previous_completion=initial_readiness[2],
    )
    values = {
        "pilot_readiness": readiness,
        "pre_jcal_readiness": initial_readiness[1],
        "input_manifest": manifest,
        "case_identity": cases[0],
        "gold_scope": scope,
        "gold_artifact": artifact,
        "gold_records": record_tuple,
        "reviewer_records": review_tuple,
        "adjudication_records": adjudication_tuple,
    }
    if include_gold_order_lock:
        values["gold_order_lock"] = create_simulated_gold_order_lock_receipt(
            pre_jcal_readiness=values["pre_jcal_readiness"],
            pilot_readiness=values["pilot_readiness"],
            gold_scope=values["gold_scope"],
            gold_artifact=values["gold_artifact"],
            gold_records=values["gold_records"],
            reviewer_records=values["reviewer_records"],
            adjudication_records=values["adjudication_records"],
        )
    return values


def _derive(sources=None):
    values = sources or _gold_sources()
    return derive_gold_outcome_facts(
        **{
            name: values[name]
            for name in (
                "pilot_readiness",
                "input_manifest",
                "case_identity",
                "gold_scope",
                "gold_artifact",
                "gold_records",
                "reviewer_records",
                "adjudication_records",
                "gold_order_lock",
            )
        }
    )


def _restore_facts(payload, sources):
    return GoldOutcomeFacts.restore_from_sources(
        payload,
        pilot_readiness=sources["pilot_readiness"],
        input_manifest=sources["input_manifest"],
        case_identity=sources["case_identity"],
        gold_scope=sources["gold_scope"],
        gold_artifact=sources["gold_artifact"],
        gold_records=sources["gold_records"],
        reviewer_records=sources["reviewer_records"],
        adjudication_records=sources["adjudication_records"],
        gold_order_lock=sources["gold_order_lock"],
    )


def test_facts_strict_codec_replays_all_typed_sources() -> None:
    sources = _gold_sources()
    facts = _derive(sources)

    restored = _restore_facts(facts.to_dict(), sources)
    assert restored == facts
    assert restored.claim_scope == "simulated_nonclaim"
    assert restored.production_authorized is False


def test_facts_codec_rejects_schema_shape_and_self_consistent_resigning() -> None:
    sources = _gold_sources()
    payload = _derive(sources).to_dict()

    unknown = {**payload, "unknown": "field"}
    with pytest.raises(GoldFactsDerivationError, match="serialized"):
        _restore_facts(unknown, sources)
    missing = dict(payload)
    missing.pop("input_manifest_hash")
    with pytest.raises(GoldFactsDerivationError, match="serialized"):
        _restore_facts(missing, sources)
    confused = {**payload, "test_only": 1}
    with pytest.raises(GoldFactsDerivationError, match="serialized"):
        _restore_facts(confused, sources)

    resigned = deepcopy(payload)
    resigned["gold_status"] = "fail"
    resigned["accept_allowed"] = False
    body = dict(resigned)
    body.pop("facts_hash")
    resigned["facts_hash"] = _canonical_hash(body)
    with pytest.raises(GoldFactsDerivationError, match="serialized"):
        _restore_facts(resigned, sources)
    resigned_safety = deepcopy(payload)
    resigned_safety["safety_violation"] = True
    body = dict(resigned_safety)
    body.pop("facts_hash")
    resigned_safety["facts_hash"] = _canonical_hash(body)
    with pytest.raises(GoldFactsDerivationError, match="serialized"):
        _restore_facts(resigned_safety, sources)

    reordered = deepcopy(payload)
    reordered["selected_gold_record_hashes"] = list(
        reversed(reordered["selected_gold_record_hashes"])
    )
    body = dict(reordered)
    body.pop("facts_hash")
    reordered["facts_hash"] = _canonical_hash(body)
    with pytest.raises(GoldFactsDerivationError, match="serialized"):
        _restore_facts(reordered, sources)
    replaced_hash = deepcopy(payload)
    replaced_hash["selected_gold_record_hashes"][0] = "f" * 64
    body = dict(replaced_hash)
    body.pop("facts_hash")
    replaced_hash["facts_hash"] = _canonical_hash(body)
    with pytest.raises(GoldFactsDerivationError, match="serialized"):
        _restore_facts(replaced_hash, sources)

    other_case = dict(sources)
    other_case["case_identity"] = formal_attack_manifest("pilot").cases[1]
    with pytest.raises(GoldFactsDerivationError, match="serialized"):
        _restore_facts(payload, other_case)


def test_facts_are_factory_derived_from_reviewed_locked_case_gold() -> None:
    sources = _gold_sources()
    facts = _derive(sources)
    selected = tuple(
        item
        for item in sources["gold_records"]
        if item.case_id == sources["case_identity"].case_id
    )

    assert isinstance(facts, GoldOutcomeFacts)
    assert facts.case_identity == sources["case_identity"]
    assert facts.gold_status is EvaluationStatus.PASS
    assert facts.accept_allowed is True
    assert facts.safety_violation is False
    assert facts.selected_gold_record_hashes == tuple(
        item.contract_hash for item in selected
    )
    assert facts.phase_readiness_hash == sources["pilot_readiness"].receipt_hash
    assert facts.input_manifest_hash == sources["input_manifest"].manifest_hash
    assert facts.case_scope_hash == sources["gold_scope"].case_scope_hash
    assert facts.gold_scope_hash == sources["gold_scope"].contract_hash
    assert facts.gold_binding_hash == sources["gold_artifact"].gold_binding_hash
    assert facts.gold_order_lock_hash == sources["gold_order_lock"].receipt_hash
    assert facts.common_ancestry_hash == sources["input_manifest"].common_ancestry_hash
    assert facts.claim_scope == "simulated_nonclaim"
    assert facts.production_authorized is False
    assert facts.test_only is True
    assert "formal_result" not in facts.to_dict()
    assert {
        "gold_status",
        "accept_allowed",
        "safety_violation",
        "selected_gold_record_hashes",
    }.isdisjoint(inspect.signature(derive_gold_outcome_facts).parameters)
    with pytest.raises(GoldFactsDerivationError, match="factory"):
        GoldOutcomeFacts(
            case_identity=facts.case_identity,
            gold_status=facts.gold_status,
            accept_allowed=facts.accept_allowed,
            safety_violation=facts.safety_violation,
            phase_readiness_hash=facts.phase_readiness_hash,
            input_manifest_hash=facts.input_manifest_hash,
            case_scope_hash=facts.case_scope_hash,
            gold_scope_hash=facts.gold_scope_hash,
            selected_gold_record_hashes=facts.selected_gold_record_hashes,
            gold_binding_hash=facts.gold_binding_hash,
            gold_artifact_manifest_hash=facts.gold_artifact_manifest_hash,
            gold_order_lock_hash=facts.gold_order_lock_hash,
            common_ancestry_hash=facts.common_ancestry_hash,
        )


def test_missing_reviewer_and_required_adjudication_fail_closed() -> None:
    sources = _gold_sources()
    missing_review = dict(sources)
    missing_review["reviewer_records"] = sources["reviewer_records"][1:]
    with pytest.raises(GoldFactsDerivationError, match="review"):
        _derive(missing_review)
    missing_adjudication = dict(sources)
    missing_adjudication["adjudication_records"] = ()
    with pytest.raises(GoldFactsDerivationError, match="adjudication"):
        _derive(missing_adjudication)


def test_extra_cross_split_duplicate_review_and_role_overlap_fail_closed() -> None:
    sources = _gold_sources()
    extra_review = BlindReviewerRecord(
        review_id="review-extra-confirmatory",
        reviewer_role_id="reviewer-extra-confirmatory",
        case_id="confirmatory.software_release_readiness.F01.seed7301",
        requirement_id="outcome",
        verdict=EvaluationStatus.PASS,
        evidence_refs=("cross-split-evidence",),
        rationale="must not enter Pilot Gold review membership",
        blinded_to_arm=True,
        blinded_to_model=True,
    )
    extra = dict(sources)
    extra["reviewer_records"] = (*sources["reviewer_records"], extra_review)
    extra["gold_artifact"] = replace(
        sources["gold_artifact"],
        reviewer_record_hashes=tuple(
            item.contract_hash for item in extra["reviewer_records"]
        ),
    )
    with pytest.raises(GoldFactsDerivationError, match="review membership"):
        _derive(extra)

    duplicate = dict(sources)
    duplicate["reviewer_records"] = (
        *sources["reviewer_records"],
        sources["reviewer_records"][-1],
    )
    with pytest.raises(GoldFactsDerivationError, match="duplicate reviewer hash"):
        _derive(duplicate)

    overlap = dict(sources)
    overlap["adjudication_records"] = (
        replace(
            sources["adjudication_records"][0],
            adjudicator_role_id=sources["reviewer_records"][0].reviewer_role_id,
        ),
    )
    with pytest.raises(GoldFactsDerivationError, match="adjudicator role"):
        _derive(overlap)

    verdict_drift = dict(sources)
    verdict_drift["adjudication_records"] = (
        replace(
            sources["adjudication_records"][0],
            first_verdict=EvaluationStatus.FAIL,
            second_verdict=EvaluationStatus.PASS,
        ),
    )
    with pytest.raises(GoldFactsDerivationError, match="review verdict binding"):
        _derive(verdict_drift)


def test_duplicate_missing_key_and_case_tuple_conflict_fail_closed() -> None:
    sources = _gold_sources()
    duplicate = dict(sources)
    duplicate["gold_records"] = (
        *sources["gold_records"],
        sources["gold_records"][0],
    )
    with pytest.raises(GoldFactsDerivationError, match="duplicate"):
        _derive(duplicate)
    missing = dict(sources)
    missing["gold_records"] = sources["gold_records"][1:]
    with pytest.raises(GoldFactsDerivationError, match="missing"):
        _derive(missing)
    conflict = dict(sources)
    conflict_records = list(sources["gold_records"])
    conflict_records[1] = replace(conflict_records[1], safety_violation=True)
    conflict["gold_records"] = tuple(conflict_records)
    conflict["gold_artifact"] = replace(
        sources["gold_artifact"],
        gold_binding_hash=formal_gold_binding_hash(
            sources["gold_scope"],
            conflict["gold_records"],
        ),
        gold_record_hashes=tuple(
            item.contract_hash for item in conflict["gold_records"]
        ),
    )
    with pytest.raises(GoldFactsDerivationError, match="top-level"):
        _derive(conflict)


def test_scope_split_readiness_and_locked_artifact_drift_fail_closed() -> None:
    sources = _gold_sources()
    wrong_scope = dict(sources)
    wrong_scope["gold_scope"] = replace(
        sources["gold_scope"],
        case_scope_hash="f" * 64,
    )
    with pytest.raises(GoldFactsDerivationError, match="case scope"):
        _derive(wrong_scope)
    wrong_stage = dict(sources)
    wrong_stage["pilot_readiness"] = sources["pre_jcal_readiness"]
    with pytest.raises(GoldFactsDerivationError, match="PILOT_READY"):
        _derive(wrong_stage)
    cross_split = dict(sources)
    cross_split["case_identity"] = FormalCaseIdentity(
        phase="confirmatory",
        task_id="software_release_readiness",
        fault_id="F01",
        mutation_seed=7301,
        case_id="confirmatory.software_release_readiness.F01.seed7301",
    )
    with pytest.raises(GoldFactsDerivationError, match="Pilot|split"):
        _derive(cross_split)
    drifted = dict(sources)
    drifted_records = list(sources["gold_records"])
    drifted_records[0] = replace(
        drifted_records[0],
        rationale="post-lock drift",
    )
    drifted["gold_records"] = tuple(drifted_records)
    with pytest.raises(GoldFactsDerivationError, match="locked"):
        _derive(drifted)


def test_gold_facts_require_typed_structural_order_lock() -> None:
    sources = _gold_sources()
    missing = dict(sources)
    missing.pop("gold_order_lock")
    with pytest.raises(TypeError, match="gold_order_lock"):
        derive_gold_outcome_facts(
            **{
                name: missing[name]
                for name in (
                    "pilot_readiness",
                    "input_manifest",
                    "case_identity",
                    "gold_scope",
                    "gold_artifact",
                    "gold_records",
                    "reviewer_records",
                    "adjudication_records",
                )
            }
        )
    assert sources["gold_order_lock"].trusted_time_verified is False
    assert sources["gold_order_lock"].signature_verified is False
