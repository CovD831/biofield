from __future__ import annotations

from dataclasses import replace

import pytest

from biofield.meas0_human import (
    BlindReviewRecord,
    HumanAttestationKind,
    HumanReviewAssessment,
    HumanReviewContractError,
    HumanReviewEvidence,
    ReviewAdjudicationRecord,
    ReviewScopeItem,
    ReviewVerdict,
    validate_production_human_evidence,
)


def _scope() -> tuple[ReviewScopeItem, ...]:
    return (
        ReviewScopeItem("case-1", "requirement-a"),
        ReviewScopeItem("case-1", "requirement-b"),
        ReviewScopeItem("case-2", "requirement-a"),
        ReviewScopeItem("case-2", "requirement-b"),
        ReviewScopeItem("case-2", "requirement-c"),
    )


def _review(
    *,
    index: int,
    reviewer: str,
    scope: ReviewScopeItem,
    verdict: ReviewVerdict,
) -> BlindReviewRecord:
    return BlindReviewRecord(
        review_id=f"review-{reviewer}-{index}",
        reviewer_role_id=reviewer,
        case_id=scope.case_id,
        requirement_id=scope.requirement_id,
        verdict=verdict,
        evidence_refs=(f"evidence:{scope.key}",),
        rationale=f"{reviewer} independently reviewed {scope.key}.",
        blinded_to_arm=True,
        blinded_to_model=True,
    )


def _evidence() -> HumanReviewEvidence:
    first_labels = (
        ReviewVerdict.PASS,
        ReviewVerdict.PASS,
        ReviewVerdict.FAIL,
        ReviewVerdict.FAIL,
        ReviewVerdict.UNKNOWN,
    )
    second_labels = (
        ReviewVerdict.PASS,
        ReviewVerdict.PASS,
        ReviewVerdict.FAIL,
        ReviewVerdict.UNKNOWN,
        ReviewVerdict.UNKNOWN,
    )
    reviews: list[BlindReviewRecord] = []
    pairs: list[tuple[BlindReviewRecord, BlindReviewRecord]] = []
    for index, (scope, first, second) in enumerate(
        zip(_scope(), first_labels, second_labels, strict=True),
        start=1,
    ):
        pair = (
            _review(
                index=index,
                reviewer="reviewer-a",
                scope=scope,
                verdict=first,
            ),
            _review(
                index=index,
                reviewer="reviewer-b",
                scope=scope,
                verdict=second,
            ),
        )
        pairs.append(pair)
        reviews.extend(pair)
    disagreement = pairs[3]
    adjudication = ReviewAdjudicationRecord(
        adjudication_id="adjudication-1",
        case_id=disagreement[0].case_id,
        requirement_id=disagreement[0].requirement_id,
        first_review_hash=disagreement[0].record_hash,
        second_review_hash=disagreement[1].record_hash,
        adjudicator_role_id="adjudicator",
        final_verdict=ReviewVerdict.FAIL,
        evidence_refs=(f"evidence:{disagreement[0].key}",),
        rationale="The protected requirement makes the failure decisive.",
    )
    return HumanReviewEvidence(
        attestation_kind=HumanAttestationKind.TEST_ONLY,
        corpus_id="synthetic-human-contract-fixture-v1",
        scope=_scope(),
        blind_reviews=tuple(reviews),
        adjudications=(adjudication,),
        gold_author_role_id="gold-author",
        operational_escalator_role_id="operational-escalator",
    )


def test_gold_agreement_and_role_separation_are_derived_from_raw_records() -> None:
    evidence = _evidence()
    assessment = HumanReviewAssessment.from_evidence(evidence)

    assert assessment.agreement.item_count == 5
    assert assessment.agreement.raw_agreement == pytest.approx(0.8)
    assert assessment.agreement.cohen_kappa == pytest.approx(
        0.7058823529411765
    )
    assert assessment.checks["roles_separated"] is True
    assert assessment.requirement_gold_by_key[
        "case-2::requirement-b"
    ].verdict is ReviewVerdict.FAIL
    assert assessment.case_gold_by_id["case-1"].verdict is ReviewVerdict.PASS
    assert assessment.case_gold_by_id["case-2"].verdict is ReviewVerdict.FAIL
    assert assessment.technical_checks_passed is True
    assert assessment.production_eligible is False
    assert assessment.passed is False
    with pytest.raises(TypeError):
        HumanReviewAssessment(  # type: ignore[call-arg]
            agreement=1.0,
            passed=True,
        )
    with pytest.raises(HumanReviewContractError, match="test_only"):
        validate_production_human_evidence(evidence)


def test_missing_review_or_required_adjudication_fails_closed() -> None:
    missing_review = replace(
        _evidence(),
        blind_reviews=_evidence().blind_reviews[:-1],
    )
    review_assessment = HumanReviewAssessment.from_evidence(missing_review)
    assert review_assessment.checks["blind_review_pairs_complete"] is False
    assert review_assessment.requirement_gold_complete is False

    missing_adjudication = replace(_evidence(), adjudications=())
    adjudication_assessment = HumanReviewAssessment.from_evidence(
        missing_adjudication
    )
    assert (
        adjudication_assessment.checks["required_adjudications_complete"]
        is False
    )
    production = replace(
        missing_adjudication,
        attestation_kind=HumanAttestationKind.PRODUCTION,
    )
    with pytest.raises(HumanReviewContractError, match="adjudication"):
        validate_production_human_evidence(production)


def test_production_rejects_role_overlap_and_unblinded_review() -> None:
    overlap = replace(
        _evidence(),
        attestation_kind=HumanAttestationKind.PRODUCTION,
        operational_escalator_role_id="reviewer-a",
    )
    overlap_assessment = HumanReviewAssessment.from_evidence(overlap)
    assert overlap_assessment.checks["roles_separated"] is False
    with pytest.raises(HumanReviewContractError, match="role separation"):
        validate_production_human_evidence(overlap)

    first = _evidence().blind_reviews[0]
    unblinded = replace(
        _evidence(),
        attestation_kind=HumanAttestationKind.PRODUCTION,
        blind_reviews=(
            replace(first, blinded_to_model=False),
            *_evidence().blind_reviews[1:],
        ),
    )
    with pytest.raises(HumanReviewContractError, match="blinded"):
        validate_production_human_evidence(unblinded)


def test_production_rejects_metrics_below_frozen_thresholds() -> None:
    original = _evidence()
    replacements = (
        ReviewVerdict.FAIL,
        ReviewVerdict.FAIL,
        ReviewVerdict.UNKNOWN,
        ReviewVerdict.UNKNOWN,
        ReviewVerdict.PASS,
    )
    second_reviews = original.blind_reviews[1::2]
    changed_second = tuple(
        replace(review, verdict=verdict)
        for review, verdict in zip(
            second_reviews,
            replacements,
            strict=True,
        )
    )
    changed_reviews = tuple(
        item
        for pair in zip(
            original.blind_reviews[::2],
            changed_second,
            strict=True,
        )
        for item in pair
    )
    adjudications = tuple(
        ReviewAdjudicationRecord(
            adjudication_id=f"low-agreement-adjudication-{index}",
            case_id=first.case_id,
            requirement_id=first.requirement_id,
            first_review_hash=first.record_hash,
            second_review_hash=second.record_hash,
            adjudicator_role_id="adjudicator",
            final_verdict=ReviewVerdict.UNKNOWN,
            evidence_refs=(f"evidence:{first.key}",),
            rationale="Synthetic contract fixture resolves disagreement.",
        )
        for index, (first, second) in enumerate(
            zip(
                changed_reviews[::2],
                changed_reviews[1::2],
                strict=True,
            ),
            start=1,
        )
    )
    low_agreement = replace(
        original,
        attestation_kind=HumanAttestationKind.PRODUCTION,
        blind_reviews=changed_reviews,
        adjudications=adjudications,
    )
    assessment = HumanReviewAssessment.from_evidence(low_agreement)

    assert assessment.agreement.raw_agreement == 0.0
    assert assessment.checks["raw_agreement_threshold_met"] is False
    assert assessment.checks["cohen_kappa_threshold_met"] is False
    with pytest.raises(HumanReviewContractError, match="frozen agreement"):
        validate_production_human_evidence(low_agreement)
