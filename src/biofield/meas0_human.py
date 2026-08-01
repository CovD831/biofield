"""Derived human-gold evidence contracts for formal MEAS0.

The records in this module can preserve review artifacts and exercise the
formal validation boundary offline.  They do not establish that a real human
performed a review.  Synthetic or fake-reviewer fixtures must remain
``test_only`` and cannot satisfy production validation.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Any


FROZEN_RAW_AGREEMENT_THRESHOLD = 0.80
FROZEN_COHEN_KAPPA_THRESHOLD = 0.60


class HumanReviewContractError(ValueError):
    """Human-review evidence is malformed or insufficient for production."""


class HumanAttestationKind(str, Enum):
    TEST_ONLY = "test_only"
    PRODUCTION = "production"


class ReviewVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise HumanReviewContractError(
            "human-review value is not canonical JSON"
        ) from error


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HumanReviewContractError(f"{label} must be non-empty text")
    return value


def _text_tuple(
    values: tuple[str, ...],
    label: str,
) -> tuple[str, ...]:
    normalized = tuple(_text(value, label) for value in values)
    if not normalized or len(set(normalized)) != len(normalized):
        raise HumanReviewContractError(
            f"{label} must be non-empty and unique"
        )
    return normalized


def _verdict(value: ReviewVerdict | str) -> ReviewVerdict:
    try:
        return (
            value
            if isinstance(value, ReviewVerdict)
            else ReviewVerdict(value)
        )
    except (TypeError, ValueError) as error:
        raise HumanReviewContractError("review verdict is invalid") from error


class _RawRecord:
    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError

    @property
    def record_hash(self) -> str:
        return _sha256(_canonical_json_bytes(self.to_dict()))


@dataclass(frozen=True)
class ReviewScopeItem(_RawRecord):
    case_id: str
    requirement_id: str

    def __post_init__(self) -> None:
        _text(self.case_id, "scope case_id")
        _text(self.requirement_id, "scope requirement_id")

    @property
    def key(self) -> str:
        return f"{self.case_id}::{self.requirement_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "requirement_id": self.requirement_id,
        }


@dataclass(frozen=True)
class BlindReviewRecord(_RawRecord):
    review_id: str
    reviewer_role_id: str
    case_id: str
    requirement_id: str
    verdict: ReviewVerdict
    evidence_refs: tuple[str, ...]
    rationale: str
    blinded_to_arm: bool
    blinded_to_model: bool

    def __post_init__(self) -> None:
        _text(self.review_id, "review_id")
        _text(self.reviewer_role_id, "reviewer_role_id")
        _text(self.case_id, "review case_id")
        _text(self.requirement_id, "review requirement_id")
        object.__setattr__(self, "verdict", _verdict(self.verdict))
        object.__setattr__(
            self,
            "evidence_refs",
            _text_tuple(tuple(self.evidence_refs), "review evidence refs"),
        )
        _text(self.rationale, "review rationale")
        if not isinstance(self.blinded_to_arm, bool) or not isinstance(
            self.blinded_to_model,
            bool,
        ):
            raise HumanReviewContractError(
                "review blinding flags must be boolean"
            )

    @property
    def key(self) -> str:
        return f"{self.case_id}::{self.requirement_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "reviewer_role_id": self.reviewer_role_id,
            "case_id": self.case_id,
            "requirement_id": self.requirement_id,
            "verdict": self.verdict.value,
            "evidence_refs": list(self.evidence_refs),
            "rationale": self.rationale,
            "blinded_to_arm": self.blinded_to_arm,
            "blinded_to_model": self.blinded_to_model,
        }


@dataclass(frozen=True)
class ReviewAdjudicationRecord(_RawRecord):
    adjudication_id: str
    case_id: str
    requirement_id: str
    first_review_hash: str
    second_review_hash: str
    adjudicator_role_id: str
    final_verdict: ReviewVerdict
    evidence_refs: tuple[str, ...]
    rationale: str

    def __post_init__(self) -> None:
        _text(self.adjudication_id, "adjudication_id")
        _text(self.case_id, "adjudication case_id")
        _text(self.requirement_id, "adjudication requirement_id")
        for value, label in (
            (self.first_review_hash, "first review hash"),
            (self.second_review_hash, "second review hash"),
        ):
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise HumanReviewContractError(
                    f"{label} must be a lowercase SHA-256 digest"
                )
        if self.first_review_hash == self.second_review_hash:
            raise HumanReviewContractError(
                "adjudication must reference two distinct reviews"
            )
        _text(self.adjudicator_role_id, "adjudicator_role_id")
        object.__setattr__(
            self,
            "final_verdict",
            _verdict(self.final_verdict),
        )
        object.__setattr__(
            self,
            "evidence_refs",
            _text_tuple(
                tuple(self.evidence_refs),
                "adjudication evidence refs",
            ),
        )
        _text(self.rationale, "adjudication rationale")

    @property
    def key(self) -> str:
        return f"{self.case_id}::{self.requirement_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "adjudication_id": self.adjudication_id,
            "case_id": self.case_id,
            "requirement_id": self.requirement_id,
            "first_review_hash": self.first_review_hash,
            "second_review_hash": self.second_review_hash,
            "adjudicator_role_id": self.adjudicator_role_id,
            "final_verdict": self.final_verdict.value,
            "evidence_refs": list(self.evidence_refs),
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class HumanReviewEvidence:
    attestation_kind: HumanAttestationKind
    corpus_id: str
    scope: tuple[ReviewScopeItem, ...]
    blind_reviews: tuple[BlindReviewRecord, ...]
    adjudications: tuple[ReviewAdjudicationRecord, ...]
    gold_author_role_id: str
    operational_escalator_role_id: str

    def __post_init__(self) -> None:
        try:
            kind = (
                self.attestation_kind
                if isinstance(
                    self.attestation_kind,
                    HumanAttestationKind,
                )
                else HumanAttestationKind(self.attestation_kind)
            )
        except (TypeError, ValueError) as error:
            raise HumanReviewContractError(
                "human attestation kind is invalid"
            ) from error
        object.__setattr__(self, "attestation_kind", kind)
        _text(self.corpus_id, "human review corpus_id")
        scope = tuple(self.scope)
        reviews = tuple(self.blind_reviews)
        adjudications = tuple(self.adjudications)
        if (
            not scope
            or not all(isinstance(item, ReviewScopeItem) for item in scope)
            or len({item.key for item in scope}) != len(scope)
        ):
            raise HumanReviewContractError(
                "review scope must contain unique typed items"
            )
        if not all(isinstance(item, BlindReviewRecord) for item in reviews):
            raise HumanReviewContractError(
                "blind review records must be typed raw records"
            )
        if not all(
            isinstance(item, ReviewAdjudicationRecord)
            for item in adjudications
        ):
            raise HumanReviewContractError(
                "adjudication records must be typed raw records"
            )
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "blind_reviews", reviews)
        object.__setattr__(self, "adjudications", adjudications)
        _text(self.gold_author_role_id, "gold_author_role_id")
        _text(
            self.operational_escalator_role_id,
            "operational_escalator_role_id",
        )

    @property
    def evidence_sha256(self) -> str:
        return _sha256(_canonical_json_bytes(self.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attestation_kind": self.attestation_kind.value,
            "corpus_id": self.corpus_id,
            "scope": [item.to_dict() for item in self.scope],
            "blind_reviews": [
                {
                    **item.to_dict(),
                    "record_hash": item.record_hash,
                }
                for item in self.blind_reviews
            ],
            "adjudications": [
                {
                    **item.to_dict(),
                    "record_hash": item.record_hash,
                }
                for item in self.adjudications
            ],
            "gold_author_role_id": self.gold_author_role_id,
            "operational_escalator_role_id": (
                self.operational_escalator_role_id
            ),
        }


@dataclass(frozen=True, init=False)
class AgreementMetrics:
    item_count: int
    label_counts_first: tuple[tuple[str, int], ...]
    label_counts_second: tuple[tuple[str, int], ...]
    raw_agreement: float | None
    cohen_kappa: float | None

    @classmethod
    def _from_pairs(
        cls,
        pairs: tuple[
            tuple[BlindReviewRecord, BlindReviewRecord],
            ...,
        ],
    ) -> AgreementMetrics:
        result = object.__new__(cls)
        count = len(pairs)
        first_labels = tuple(pair[0].verdict.value for pair in pairs)
        second_labels = tuple(pair[1].verdict.value for pair in pairs)
        first_counts = Counter(first_labels)
        second_counts = Counter(second_labels)
        labels = tuple(item.value for item in ReviewVerdict)
        agreement = (
            sum(
                left == right
                for left, right in zip(
                    first_labels,
                    second_labels,
                    strict=True,
                )
            )
            / count
            if count
            else None
        )
        expected = (
            sum(
                (first_counts[label] / count)
                * (second_counts[label] / count)
                for label in labels
            )
            if count
            else None
        )
        kappa = (
            None
            if agreement is None
            or expected is None
            or math.isclose(expected, 1.0)
            else (agreement - expected) / (1 - expected)
        )
        object.__setattr__(result, "item_count", count)
        object.__setattr__(
            result,
            "label_counts_first",
            tuple((label, first_counts[label]) for label in labels),
        )
        object.__setattr__(
            result,
            "label_counts_second",
            tuple((label, second_counts[label]) for label in labels),
        )
        object.__setattr__(result, "raw_agreement", agreement)
        object.__setattr__(result, "cohen_kappa", kappa)
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_count": self.item_count,
            "label_counts_first": dict(self.label_counts_first),
            "label_counts_second": dict(self.label_counts_second),
            "raw_agreement": self.raw_agreement,
            "cohen_kappa": self.cohen_kappa,
        }


@dataclass(frozen=True, init=False)
class RequirementGold:
    case_id: str
    requirement_id: str
    verdict: ReviewVerdict
    review_hashes: tuple[str, str]
    adjudication_hash: str | None
    evidence_refs: tuple[str, ...]

    @property
    def key(self) -> str:
        return f"{self.case_id}::{self.requirement_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "requirement_id": self.requirement_id,
            "verdict": self.verdict.value,
            "review_hashes": list(self.review_hashes),
            "adjudication_hash": self.adjudication_hash,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True, init=False)
class CaseGold:
    case_id: str
    verdict: ReviewVerdict
    requirement_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "verdict": self.verdict.value,
            "requirement_keys": list(self.requirement_keys),
        }


def _pairs_by_scope(
    evidence: HumanReviewEvidence,
) -> tuple[
    dict[str, tuple[BlindReviewRecord, BlindReviewRecord]],
    bool,
]:
    expected = {item.key for item in evidence.scope}
    grouped: dict[str, list[BlindReviewRecord]] = defaultdict(list)
    for record in evidence.blind_reviews:
        grouped[record.key].append(record)
    global_roles = {
        record.reviewer_role_id for record in evidence.blind_reviews
    }
    complete = (
        set(grouped) == expected
        and len(global_roles) == 2
        and all(
            len(records) == 2
            and {item.reviewer_role_id for item in records} == global_roles
            and len({item.record_hash for item in records}) == 2
            for records in grouped.values()
        )
    )
    if not complete:
        return {}, False
    pairs = {
        key: tuple(
            sorted(
                records,
                key=lambda item: item.reviewer_role_id,
            )
        )
        for key, records in grouped.items()
    }
    return {
        key: (pair[0], pair[1])
        for key, pair in pairs.items()
    }, True


def _adjudications_complete(
    evidence: HumanReviewEvidence,
    pairs: dict[
        str,
        tuple[BlindReviewRecord, BlindReviewRecord],
    ],
) -> tuple[dict[str, ReviewAdjudicationRecord], bool]:
    grouped: dict[str, list[ReviewAdjudicationRecord]] = defaultdict(list)
    for record in evidence.adjudications:
        grouped[record.key].append(record)
    required = {
        key
        for key, pair in pairs.items()
        if pair[0].verdict is not pair[1].verdict
    }
    complete = (
        set(grouped) == required
        and all(len(records) == 1 for records in grouped.values())
        and all(
            {
                records[0].first_review_hash,
                records[0].second_review_hash,
            }
            == {item.record_hash for item in pairs[key]}
            for key, records in grouped.items()
        )
    )
    return (
        {key: records[0] for key, records in grouped.items()}
        if complete
        else {},
        complete,
    )


def _roles_separated(evidence: HumanReviewEvidence) -> bool:
    categories = (
        {item.reviewer_role_id for item in evidence.blind_reviews},
        {item.adjudicator_role_id for item in evidence.adjudications},
        {evidence.gold_author_role_id},
        {evidence.operational_escalator_role_id},
    )
    return all(
        not categories[left] & categories[right]
        for left in range(len(categories))
        for right in range(left + 1, len(categories))
    )


def _requirement_gold(
    evidence: HumanReviewEvidence,
    pairs: dict[
        str,
        tuple[BlindReviewRecord, BlindReviewRecord],
    ],
    adjudications: dict[str, ReviewAdjudicationRecord],
) -> tuple[RequirementGold, ...]:
    result: list[RequirementGold] = []
    for scope in evidence.scope:
        pair = pairs.get(scope.key)
        if pair is None:
            continue
        adjudication = adjudications.get(scope.key)
        if pair[0].verdict is pair[1].verdict:
            verdict = pair[0].verdict
        elif adjudication is not None:
            verdict = adjudication.final_verdict
        else:
            continue
        item = object.__new__(RequirementGold)
        object.__setattr__(item, "case_id", scope.case_id)
        object.__setattr__(item, "requirement_id", scope.requirement_id)
        object.__setattr__(item, "verdict", verdict)
        object.__setattr__(
            item,
            "review_hashes",
            (pair[0].record_hash, pair[1].record_hash),
        )
        object.__setattr__(
            item,
            "adjudication_hash",
            adjudication.record_hash if adjudication is not None else None,
        )
        refs = (
            adjudication.evidence_refs
            if adjudication is not None
            else tuple(
                sorted(
                    set(pair[0].evidence_refs) | set(pair[1].evidence_refs)
                )
            )
        )
        object.__setattr__(item, "evidence_refs", refs)
        result.append(item)
    return tuple(result)


def _case_gold(
    requirement_gold: tuple[RequirementGold, ...],
) -> tuple[CaseGold, ...]:
    grouped: dict[str, list[RequirementGold]] = defaultdict(list)
    for item in requirement_gold:
        grouped[item.case_id].append(item)
    result: list[CaseGold] = []
    for case_id in sorted(grouped):
        items = grouped[case_id]
        verdicts = {item.verdict for item in items}
        if ReviewVerdict.FAIL in verdicts:
            verdict = ReviewVerdict.FAIL
        elif ReviewVerdict.UNKNOWN in verdicts:
            verdict = ReviewVerdict.UNKNOWN
        else:
            verdict = ReviewVerdict.PASS
        item = object.__new__(CaseGold)
        object.__setattr__(item, "case_id", case_id)
        object.__setattr__(item, "verdict", verdict)
        object.__setattr__(
            item,
            "requirement_keys",
            tuple(gold.key for gold in items),
        )
        result.append(item)
    return tuple(result)


@dataclass(frozen=True, init=False)
class HumanReviewAssessment:
    evidence_sha256: str
    attestation_kind: HumanAttestationKind
    agreement: AgreementMetrics
    requirement_gold: tuple[RequirementGold, ...]
    case_gold: tuple[CaseGold, ...]
    _checks: tuple[tuple[str, bool], ...]

    @classmethod
    def from_evidence(
        cls,
        evidence: HumanReviewEvidence,
    ) -> HumanReviewAssessment:
        if not isinstance(evidence, HumanReviewEvidence):
            raise HumanReviewContractError(
                "assessment requires typed human-review evidence"
            )
        pairs, pairs_complete = _pairs_by_scope(evidence)
        ordered_pairs = tuple(
            pairs[item.key]
            for item in evidence.scope
            if item.key in pairs
        )
        agreement = AgreementMetrics._from_pairs(ordered_pairs)
        adjudications, adjudications_complete = _adjudications_complete(
            evidence,
            pairs,
        )
        gold = _requirement_gold(evidence, pairs, adjudications)
        raw_records_unique = (
            len({item.review_id for item in evidence.blind_reviews})
            == len(evidence.blind_reviews)
            and len({item.record_hash for item in evidence.blind_reviews})
            == len(evidence.blind_reviews)
            and len(
                {item.adjudication_id for item in evidence.adjudications}
            )
            == len(evidence.adjudications)
            and len({item.record_hash for item in evidence.adjudications})
            == len(evidence.adjudications)
        )
        checks = {
            "raw_records_unique": raw_records_unique,
            "blind_review_pairs_complete": pairs_complete,
            "reviews_blinded": bool(evidence.blind_reviews)
            and all(
                item.blinded_to_arm and item.blinded_to_model
                for item in evidence.blind_reviews
            ),
            "required_adjudications_complete": (
                pairs_complete and adjudications_complete
            ),
            "roles_separated": _roles_separated(evidence),
            "requirement_gold_complete": (
                len(gold) == len(evidence.scope)
            ),
            "raw_agreement_threshold_met": (
                agreement.raw_agreement is not None
                and agreement.raw_agreement
                >= FROZEN_RAW_AGREEMENT_THRESHOLD
            ),
            "cohen_kappa_threshold_met": (
                agreement.cohen_kappa is not None
                and agreement.cohen_kappa
                >= FROZEN_COHEN_KAPPA_THRESHOLD
            ),
        }
        result = object.__new__(cls)
        object.__setattr__(
            result,
            "evidence_sha256",
            evidence.evidence_sha256,
        )
        object.__setattr__(
            result,
            "attestation_kind",
            evidence.attestation_kind,
        )
        object.__setattr__(result, "agreement", agreement)
        object.__setattr__(result, "requirement_gold", gold)
        object.__setattr__(result, "case_gold", _case_gold(gold))
        object.__setattr__(result, "_checks", tuple(sorted(checks.items())))
        return result

    @property
    def checks(self) -> dict[str, bool]:
        return dict(self._checks)

    @property
    def requirement_gold_by_key(self) -> dict[str, RequirementGold]:
        return {item.key: item for item in self.requirement_gold}

    @property
    def case_gold_by_id(self) -> dict[str, CaseGold]:
        return {item.case_id: item for item in self.case_gold}

    @property
    def requirement_gold_complete(self) -> bool:
        return self.checks["requirement_gold_complete"]

    @property
    def technical_checks_passed(self) -> bool:
        return all(value for _, value in self._checks)

    @property
    def production_eligible(self) -> bool:
        return self.attestation_kind is HumanAttestationKind.PRODUCTION

    @property
    def passed(self) -> bool:
        return self.technical_checks_passed and self.production_eligible

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_sha256": self.evidence_sha256,
            "attestation_kind": self.attestation_kind.value,
            "agreement": self.agreement.to_dict(),
            "requirement_gold": [
                item.to_dict() for item in self.requirement_gold
            ],
            "case_gold": [item.to_dict() for item in self.case_gold],
            "checks": self.checks,
            "technical_checks_passed": self.technical_checks_passed,
            "production_eligible": self.production_eligible,
            "passed": self.passed,
        }


def validate_production_human_evidence(
    evidence: HumanReviewEvidence,
) -> HumanReviewAssessment:
    if not isinstance(evidence, HumanReviewEvidence):
        raise HumanReviewContractError(
            "production validation requires typed human-review evidence"
        )
    if evidence.attestation_kind is HumanAttestationKind.TEST_ONLY:
        raise HumanReviewContractError(
            "test_only human evidence cannot satisfy production validation"
        )
    assessment = HumanReviewAssessment.from_evidence(evidence)
    checks = assessment.checks
    if not checks["blind_review_pairs_complete"]:
        raise HumanReviewContractError(
            "production validation requires complete blind review pairs"
        )
    if not checks["reviews_blinded"]:
        raise HumanReviewContractError(
            "production validation requires blinded review records"
        )
    if not checks["required_adjudications_complete"]:
        raise HumanReviewContractError(
            "production validation requires every disagreement adjudication"
        )
    if not checks["roles_separated"]:
        raise HumanReviewContractError(
            "production validation requires role separation"
        )
    if (
        not checks["raw_agreement_threshold_met"]
        or not checks["cohen_kappa_threshold_met"]
    ):
        raise HumanReviewContractError(
            "production evidence is below frozen agreement thresholds"
        )
    if not assessment.passed:
        failed = ",".join(
            name for name, passed in checks.items() if not passed
        )
        raise HumanReviewContractError(
            f"production human-review checks failed: {failed}"
        )
    return assessment


__all__ = [
    "FROZEN_COHEN_KAPPA_THRESHOLD",
    "FROZEN_RAW_AGREEMENT_THRESHOLD",
    "AgreementMetrics",
    "BlindReviewRecord",
    "CaseGold",
    "HumanAttestationKind",
    "HumanReviewAssessment",
    "HumanReviewContractError",
    "HumanReviewEvidence",
    "RequirementGold",
    "ReviewAdjudicationRecord",
    "ReviewScopeItem",
    "ReviewVerdict",
    "validate_production_human_evidence",
]
